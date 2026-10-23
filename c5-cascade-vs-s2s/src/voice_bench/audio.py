"""Audio in and out for the benchmark, without a room or a microphone.

    WavInput       plays a recorded question into the agent in real time, then silence, like a caller who stops talking
    CaptureOutput  stands in for the speaker: records when the agent's first audio arrives and keeps the audio

Both run at real speed. Feeding audio faster than real time would make the latency numbers meaningless.
"""

import asyncio
import time
import wave
from pathlib import Path

from livekit import rtc
from livekit.agents.voice import io

# One format for every question, so both systems hear exactly the same thing (slide 69: standardize).
SAMPLE_RATE = 16000
FRAME_MS = 20
LEAD_SILENCE_S = 0.5


def read_wav(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, SAMPLE_RATE):
            raise ValueError(f"{path} must be 16 kHz mono 16-bit; run `bench audio --force` to remake it")
        return w.readframes(w.getnframes())


def write_wav(path: Path, pcm: bytes, sample_rate: int = SAMPLE_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)


def to_standard(frames: list[rtc.AudioFrame]) -> bytes:
    """Mono 16 kHz PCM from frames at whatever rate a TTS produced them."""
    if not frames:
        return b""
    resampler = rtc.AudioResampler(input_rate=frames[0].sample_rate, output_rate=SAMPLE_RATE, num_channels=1)
    out = []
    for f in frames:
        out.extend(resampler.push(f))
    out.extend(resampler.flush())
    return b"".join(bytes(f.data) for f in out)


class WavInput(io.AudioInput):
    """Half a second of silence, the question, then silence until closed."""

    def __init__(self, pcm: bytes) -> None:
        super().__init__(label="benchmark caller")
        samples = SAMPLE_RATE * FRAME_MS // 1000
        self._chunk = samples * 2
        self._silence = bytes(self._chunk)
        lead = int(LEAD_SILENCE_S * 1000 / FRAME_MS)
        self._frames = [self._silence] * lead + [pcm[i : i + self._chunk].ljust(self._chunk, b"\0") for i in range(0, len(pcm), self._chunk)]
        self._samples = samples
        self._sent = 0
        self._started: float | None = None
        self._closed = False
        self.speech_end: float | None = None  # time.monotonic() when the last frame of the question was played

    @property
    def speech_seconds(self) -> float:
        return len(self._frames) * FRAME_MS / 1000 - LEAD_SILENCE_S

    async def __anext__(self) -> rtc.AudioFrame:
        if self._closed:
            raise StopAsyncIteration
        if self._started is None:
            self._started = time.monotonic()
        # Hold each frame back until its moment comes, so 20 ms of audio takes 20 ms to arrive.
        due = self._started + self._sent * FRAME_MS / 1000
        delay = due - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        data = self._frames[self._sent] if self._sent < len(self._frames) else self._silence
        self._sent += 1
        if self._sent == len(self._frames):
            self.speech_end = self._started + self._sent * FRAME_MS / 1000
        return rtc.AudioFrame(data=data, sample_rate=SAMPLE_RATE, num_channels=1, samples_per_channel=self._samples)

    def close(self) -> None:
        self._closed = True


class CaptureOutput(io.AudioOutput):
    """A pretend speaker that plays at real speed, so the session sees playback start and finish as it would."""

    def __init__(self) -> None:
        super().__init__(label="benchmark capture", capabilities=io.AudioOutputCapabilities(pause=False))
        self.frames: list[rtc.AudioFrame] = []
        self.first_audio: float | None = None  # time.monotonic() of the agent's first audio frame
        self.segment_starts: list[float] = []  # when each stretch of speech began
        self.last_audio_end: float | None = None
        self._segment_start: float | None = None
        self._segment_seconds = 0.0
        self._playout: asyncio.Task | None = None

    async def capture_frame(self, frame: rtc.AudioFrame) -> None:
        await super().capture_frame(frame)
        now = time.monotonic()
        if self.first_audio is None:
            self.first_audio = now
        if self._segment_start is None:
            self._segment_start = now
            self._segment_seconds = 0.0
            self.segment_starts.append(now)
            self.on_playback_started(created_at=time.time())
        self._segment_seconds += frame.duration
        self.frames.append(frame)

    def flush(self) -> None:
        super().flush()
        if self._segment_start is None:
            return
        end = self._segment_start + self._segment_seconds
        played = self._segment_seconds
        self._segment_start = None
        self.last_audio_end = max(self.last_audio_end or 0.0, end)
        self._playout = asyncio.create_task(self._finish_at(end, played))

    async def _finish_at(self, end: float, played: float) -> None:
        await asyncio.sleep(max(0.0, end - time.monotonic()))
        self.on_playback_finished(playback_position=played, interrupted=False)

    def clear_buffer(self) -> None:
        if self._playout and not self._playout.done():
            self._playout.cancel()
        if self._segment_start is not None:
            played = time.monotonic() - self._segment_start
            self._segment_start = None
            self.on_playback_finished(playback_position=played, interrupted=True)

    def pcm(self) -> bytes:
        return to_standard(self.frames)


async def synthesize_questions(cases: list[dict], out_dir: Path, voices: list[str], model: str, force: bool = False) -> list[Path]:
    """Turn each question into a WAV file with a TTS service, rotating voices to reduce speaker bias (slide 69).

    The caller's voices come from a different TTS vendor than the cascaded agent's own voice, so the agent's STT
    isn't hearing its own vendor's audio.
    """
    import aiohttp

    from livekit.agents import inference

    paths = []
    async with aiohttp.ClientSession() as http:
        for i, case in enumerate(cases):
            voice = voices[i % len(voices)]
            path = out_dir / f"{case['id']}.wav"
            paths.append(path)
            if path.exists() and not force:
                continue
            tts = inference.TTS(model, voice=voice, language="en", http_session=http)
            frames = [ev.frame async for ev in tts.synthesize(case["question"])]
            await tts.aclose()
            write_wav(path, to_standard(frames))
            print(f"  {case['id']}  {voice:<10} {case['question']}")
    return paths
