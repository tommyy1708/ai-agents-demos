"""Steps 03 and 04: the hotel agent with a voice.

    uv run hotel-voice download-files   # once: the VAD and turn-detection models
    uv run hotel-voice console          # step 03: your laptop's microphone and speaker
    uv run hotel-voice dev              # step 04: join a room on LiveKit Cloud, talk from the browser

Speech-to-text and text-to-speech run on LiveKit Cloud (LiveKit Inference); the reasoning is Claude.
Voice activity detection and end-of-turn detection run on your laptop.
"""

import logging
import os
import sys

from dotenv import load_dotenv
from livekit.agents import AgentServer, AgentSession, JobContext, JobProcess, MetricsCollectedEvent, cli, inference, metrics
from livekit.plugins import silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from hotel_agent.agent import HotelAgent, build_llm

load_dotenv()
log = logging.getLogger("hotel_agent.latency")

STT_MODEL = "deepgram/nova-3"
TTS_MODEL = "cartesia/sonic-3"


def prewarm(proc: JobProcess) -> None:
    # Load the VAD once per process, not once per call.
    proc.userdata["vad"] = silero.VAD.load()


server = AgentServer(setup_fnc=prewarm)


class LatencyLog:
    """Prints how long each step of a turn took: the voice-to-voice budget from the slides, measured."""

    def __init__(self) -> None:
        self.turns: dict[str, dict[str, float]] = {}

    def __call__(self, ev: MetricsCollectedEvent) -> None:
        m = ev.metrics
        speech = getattr(m, "speech_id", None)
        if speech is None:
            return
        t = self.turns.setdefault(speech, {})
        if isinstance(m, metrics.EOUMetrics):
            t["end of turn"] = m.end_of_utterance_delay
        elif isinstance(m, metrics.LLMMetrics):
            t["Claude first token"] = m.ttft
        elif isinstance(m, metrics.TTSMetrics):
            t["first audio"] = m.ttfb
            parts = " + ".join(f"{k} {v * 1000:.0f} ms" for k, v in t.items())
            log.info("turn latency: %s = %.0f ms", parts, sum(t.values()) * 1000)
            self.turns.pop(speech, None)


@server.rtc_session()
async def entrypoint(ctx: JobContext) -> None:
    session = AgentSession(
        stt=inference.STT(STT_MODEL, language="en"),
        llm=build_llm(),
        tts=inference.TTS(TTS_MODEL),
        vad=ctx.proc.userdata["vad"],
        turn_detection=MultilingualModel(),
    )
    session.on("metrics_collected", LatencyLog())
    await session.start(agent=HotelAgent(), room=ctx.room)
    await session.generate_reply(instructions="Greet the caller as the Clarium Bay Hotel and ask how you can help.")


def main() -> None:
    needs = ["ANTHROPIC_API_KEY", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"]
    if len(sys.argv) > 1 and sys.argv[1] in ("dev", "start", "connect"):
        needs.append("LIVEKIT_URL")
    missing = [k for k in needs if not os.environ.get(k)] if sys.argv[1:2] != ["download-files"] else []
    if missing:
        sys.exit(f"Missing {', '.join(missing)}. Copy .env.example to .env and fill it in (see the README).")
    logging.getLogger("hotel_agent").setLevel(logging.INFO)
    cli.run_app(server)


if __name__ == "__main__":
    main()
