"""One benchmark run: one recorded question, played into one system, start to finish.

Each run gets a fresh session and a fresh database, so runs can't affect each other.
"""

import asyncio
import time
from pathlib import Path

import aiohttp
from livekit.agents import AgentSession, inference

from voice_bench import support
from voice_bench.audio import CaptureOutput, WavInput, read_wav, write_wav

SYSTEMS = ("cascaded", "s2s")

# The call is over when the agent has been quiet this long after speaking, or this long after the question ended.
QUIET_S = 2.5
TIMEOUT_S = 60.0


def _session(system: str, http: aiohttp.ClientSession, vad, call: support.Call) -> tuple[AgentSession, object]:
    # The caller is a recording that goes quiet after the question, so it never talks over the agent. The cascade
    # turns interruptions off so a noise can't cut a reply short; Gemini Live decides turns on its own servers, and
    # LiveKit only allows that with interruptions on.
    if system == "cascaded":
        session = AgentSession(
            stt=inference.STT(support.STT_MODEL, language="en", http_session=http),
            llm=support.build_cascade_llm(),
            tts=inference.TTS(support.TTS_MODEL, http_session=http),
            vad=vad,
            userdata=call,
            turn_handling={"turn_detection": "vad", "interruption": {"enabled": False, "resume_false_interruption": False}},
        )
        return session, support.CascadedAgent()
    session = AgentSession(userdata=call, turn_handling={"interruption": {"resume_false_interruption": False}})
    return session, support.S2SAgent()


def _texts(session: AgentSession, role: str) -> str:
    return " ".join((item.text_content or "").strip() for item in session.history.items if getattr(item, "role", None) == role).strip()


async def run_once(system: str, case: dict, wav: Path, *, vad=None, save_audio: Path | None = None) -> dict:
    call = support.Call()
    async with aiohttp.ClientSession() as http:
        session, agent = _session(system, http, vad, call)
        mic = WavInput(read_wav(wav))
        speaker = CaptureOutput()
        session.input.audio = mic
        session.output.audio = speaker
        # Text output would print each reply; the benchmark keeps it in the history instead.
        session.output.transcription = None
        error = None
        # What the speech recognizer heard, before the input check gets a chance to rewrite it.
        heard_parts: list[str] = []
        errors: list[str] = []
        session.on("user_input_transcribed", lambda ev: heard_parts.append(ev.transcript) if ev.is_final else None)
        # Errors a model recovers from (a retry that worked) are part of the run; only the ones that end it count.
        session.on("error", lambda ev: None if getattr(ev.error, "recoverable", False) else errors.append(str(ev.error)))
        try:
            await session.start(agent, record=False)
            quiet_since = None
            while True:
                await asyncio.sleep(0.1)
                now = time.monotonic()
                if mic.speech_end is None or now < mic.speech_end:
                    continue
                busy = session.agent_state in ("thinking", "speaking") or (speaker.last_audio_end or 0) > now
                if busy or speaker.first_audio is None:
                    quiet_since = None
                elif quiet_since is None:
                    quiet_since = now
                if quiet_since is not None and now - quiet_since >= QUIET_S:
                    break
                if errors and session.agent_state not in ("thinking", "speaking"):
                    break
                if now - mic.speech_end > TIMEOUT_S:
                    error = f"timeout: no complete reply within {TIMEOUT_S:.0f} s"
                    break
        except Exception as e:  # noqa: BLE001 - a failed run is a result, not a crash
            error = f"{type(e).__name__}: {e}"
        finally:
            mic.close()
            heard = " ".join(p.strip() for p in heard_parts if p.strip()) or _texts(session, "user")
            spoken = _texts(session, "assistant")
            error = error or (errors[0] if errors else None)
            usage = [u.model_dump() for u in session.usage.model_usage]
            await session.aclose()

    if save_audio is not None and speaker.frames:
        write_wav(save_audio, speaker.pcm())

    def ms(t: float | None) -> int | None:
        return round((t - mic.speech_end) * 1000) if t is not None and mic.speech_end is not None else None

    # "One moment, let me check" is first audio, but not the answer. The answer is the first speech after the last
    # tool returned; with no tools, it's the first audio.
    last_tool = max((t["at"] for t in call.tool_calls), default=None)
    answer = speaker.first_audio if last_tool is None else next((t for t in speaker.segment_starts if t > last_tool), None)

    return {
        "system": system,
        "case": case["id"],
        "category": case["category"],
        "heard": heard,
        "spoken": spoken,
        "tool_calls": call.tool_calls,
        "blocked_by_input_check": getattr(agent, "blocked", None) is not None,
        # From the end of the caller's speech: to the agent's first audio, to the answer, and to the end of the reply.
        "first_audio_ms": ms(speaker.first_audio),
        "answer_audio_ms": ms(answer),
        "reply_end_ms": ms(speaker.last_audio_end),
        "usage": usage,
        "error": error,
    }
