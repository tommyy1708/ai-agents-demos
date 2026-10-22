"""Steps 01 and 02 of the workshop: `hotel smoke` (tools only) and `hotel text` (the agent, in text)."""

import argparse
import asyncio
import json
from datetime import timedelta

from dotenv import load_dotenv

from hotel_agent import knowledge
from hotel_agent.hotel import BookingError, Hotel

load_dotenv()


def _next(hotel: Hotel, weekday: int):
    days = (weekday - hotel.today.weekday()) % 7 or 7
    return hotel.today + timedelta(days=days)


def smoke() -> None:
    """Step 01: every tool, called directly. No model, no audio, no network."""
    hotel = Hotel()
    tuesday, friday = _next(hotel, 1), _next(hotel, 4)

    def show(label: str, fn) -> None:
        try:
            result = fn()
        except BookingError as e:
            result = f"BookingError: {e}"
        print(f"{label}\n  {json.dumps(result, default=str) if not isinstance(result, str) else result}\n")

    show(f"Availability, two guests, Tuesday {tuesday} for two nights", lambda: hotel.availability(tuesday, tuesday + timedelta(2), 2))
    show(f"Availability, four guests, Friday {friday} for two nights (suites are taken on weekends)", lambda: hotel.availability(friday, friday + timedelta(2), 4))
    r = hotel.reserve("Ana Lima", "+1 555 0100", "deluxe_king", tuesday, tuesday + timedelta(2), 2)
    show("Reservation", lambda: {"code": r.code, "room": r.room_type, "nights": r.nights, "total": r.total})
    show("Check-out before check-in", lambda: hotel.availability(tuesday, tuesday, 2))
    show("Five guests in a deluxe king", lambda: hotel.reserve("Ana Lima", "+1 555 0100", "deluxe_king", tuesday, tuesday + timedelta(1), 5))
    sections = knowledge.load()
    for q in ["What time is check-out?", "Can I cancel for free?", "Do you have parking?"]:
        found = knowledge.search(q, sections, k=1)
        print(f"Policy lookup: {q}\n  {found[0].title + ': ' + found[0].text[:90] + '...' if found else 'nothing in the knowledge file'}\n")


async def text_chat() -> None:
    """Step 02: the agent with Claude, in text. Same instructions and tools the voice agent uses."""
    from livekit.agents import AgentSession

    from hotel_agent.agent import MODEL, HotelAgent, build_llm

    print(f"Clarium Bay Hotel, text mode, model {MODEL}. Type a message, or 'quit'.\n")
    async with build_llm() as llm, AgentSession(llm=llm) as session:
        await session.start(HotelAgent())
        while True:
            try:
                message = await asyncio.to_thread(input, "you> ")
            except (EOFError, KeyboardInterrupt):
                break
            if message.strip().lower() in {"quit", "exit"}:
                break
            result = await session.run(user_input=message)
            for ev in result.events:
                if ev.type == "function_call":
                    print(f"      tool {ev.item.name}({ev.item.arguments})")
                elif ev.type == "function_call_output":
                    print(f"        -> {ev.item.output[:160]}")
                elif ev.type == "message" and ev.item.role == "assistant":
                    print(f"agent> {ev.item.text_content}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="hotel", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("smoke", help="step 01: call every tool directly")
    sub.add_parser("text", help="step 02: talk to the agent in text (needs ANTHROPIC_API_KEY)")
    args = parser.parse_args()
    if args.command == "smoke":
        smoke()
    else:
        asyncio.run(text_chat())
