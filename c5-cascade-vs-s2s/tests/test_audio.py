import asyncio
import time

from livekit import rtc

from voice_bench.audio import FRAME_MS, LEAD_SILENCE_S, SAMPLE_RATE, CaptureOutput, WavInput


async def test_wav_input_plays_in_real_time_and_marks_the_end_of_speech():
    speech = bytes(SAMPLE_RATE * 2 // 2)  # half a second
    mic = WavInput(speech)
    start = time.monotonic()
    frames = 0
    while mic.speech_end is None:
        await mic.__anext__()
        frames += 1
    elapsed = time.monotonic() - start
    assert frames == int((LEAD_SILENCE_S + 0.5) * 1000 / FRAME_MS)
    assert 0.9 < elapsed + FRAME_MS / 1000 < 1.2
    # After the question, silence keeps coming until the run closes the input.
    assert (await mic.__anext__()).data.tobytes() == bytes(SAMPLE_RATE * FRAME_MS // 1000 * 2)
    mic.close()


async def test_capture_output_times_first_audio_and_finishes_playback_at_real_speed():
    out = CaptureOutput()
    finished = []
    out.on("playback_finished", lambda ev: finished.append(ev))
    frame = rtc.AudioFrame(data=bytes(2400 * 2), sample_rate=24000, num_channels=1, samples_per_channel=2400)  # 100 ms
    before = time.monotonic()
    for _ in range(3):
        await out.capture_frame(frame)
    out.flush()
    assert out.first_audio is not None and out.first_audio >= before
    assert finished == []
    ev = await asyncio.wait_for(out.wait_for_playout(), 1)
    assert not ev.interrupted and abs(ev.playback_position - 0.3) < 1e-6
    assert time.monotonic() - before >= 0.29
    assert len(out.pcm()) == 3 * 1600 * 2  # resampled to 16 kHz


async def test_capture_output_keeps_the_start_of_each_stretch_of_speech():
    out = CaptureOutput()
    frame = rtc.AudioFrame(data=bytes(480 * 2), sample_rate=24000, num_channels=1, samples_per_channel=480)  # 20 ms
    await out.capture_frame(frame)
    out.flush()
    await out.wait_for_playout()
    await asyncio.sleep(0.05)
    await out.capture_frame(frame)
    out.flush()
    assert len(out.segment_starts) == 2 and out.segment_starts[1] - out.segment_starts[0] >= 0.05
    assert out.first_audio == out.segment_starts[0]
