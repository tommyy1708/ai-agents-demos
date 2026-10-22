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
from livekit.agents import AgentServer, AgentSession, ChatMessage, ConversationItemAddedEvent, JobContext, JobProcess, cli, inference
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
    """After each reply, logs how long the caller waited and where the time went: the budget from slide 19,
    measured. LiveKit attaches these timings to each message in the conversation."""

    def __init__(self) -> None:
        self.end_of_turn = 0.0

    def __call__(self, ev: ConversationItemAddedEvent) -> None:
        item = ev.item
        if not isinstance(item, ChatMessage):
            return
        m = item.metrics or {}
        if item.role == "user":
            self.end_of_turn = m.get("end_of_turn_delay", 0.0)
            return
        if item.role != "assistant" or "e2e_latency" not in m:
            return
        parts = {
            "end of turn": self.end_of_turn,
            "Claude first token": m.get("llm_node_ttft", 0.0),
            "first audio": m.get("tts_node_ttfb", 0.0),
        }
        # Whatever is left: tool calls, and a first model call that only asked for a tool.
        parts["tools and other steps"] = max(m["e2e_latency"] - sum(parts.values()), 0.0)
        detail = ", ".join(f"{k} {v * 1000:.0f}" for k, v in parts.items() if v)
        log.info("caller waited %.0f ms (%s)", m["e2e_latency"] * 1000, detail)


@server.rtc_session()
async def entrypoint(ctx: JobContext) -> None:
    session = AgentSession(
        stt=inference.STT(STT_MODEL, language="en"),
        llm=build_llm(),
        tts=inference.TTS(TTS_MODEL),
        vad=ctx.proc.userdata["vad"],
        # End of turn is decided by a small model that reads the transcript, not by silence alone (slides 17-18).
        turn_handling={"turn_detection": MultilingualModel()},
    )
    session.on("conversation_item_added", LatencyLog())
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
