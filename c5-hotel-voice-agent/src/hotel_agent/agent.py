"""The hotel agent: its instructions and tools. The same agent runs in every step from 02 on; only what's around
it changes (text in a terminal, voice on your laptop, a room, a phone line).
"""

import logging
import os
from datetime import date, timedelta

from livekit.agents import Agent, RunContext, ToolError, function_tool
from livekit.agents.beta.tools import EndCallTool
from livekit.agents.utils import is_given
from livekit.plugins import anthropic

from hotel_agent import knowledge
from hotel_agent.hotel import ROOM_TYPES, BookingError, Hotel

log = logging.getLogger("hotel_agent")

# Any Claude model id. Haiku is the fastest Claude model, and on a call every 100 ms counts.
MODEL = os.environ.get("HOTEL_AGENT_MODEL", "claude-haiku-5-5")
# Thinking before each reply costs the caller time: in our measurements it took Claude Haiku 5.5's first token from
# about 0.9 s to 1.5 s. A booking agent with clear tools doesn't need it. Set HOTEL_AGENT_THINKING=on to compare.
THINKING = os.environ.get("HOTEL_AGENT_THINKING", "off") == "on"

INSTRUCTIONS = """You are the voice reservation agent of the Clarium Bay Hotel. Callers talk to you on the phone.
Today is {today}. The next two weeks, so you never have to work out a date:
{calendar}

What you do: check room availability, make reservations, and answer questions about the hotel's policies.
For anything else (changing or cancelling a booking, group bookings, complaints, special requests), offer to
transfer the caller to the front desk.

How you speak: this is a phone call, so keep every reply to one or two short sentences. No lists, no markdown, no
emojis. Say prices and dates the way people say them out loud ("a hundred and forty-nine dollars a night",
"Friday the twelfth").

Rules:
- Never say your reasoning out loud. Call the tool, then give the caller the answer.
- Answer policy questions only from lookup_policy. If it has no answer, say so and offer the front desk.
- Before you book, read back the room, dates, number of guests, name and phone number, and get a clear yes.
- After booking, read the confirmation code one character at a time.
- Hotel reservations only. If the caller asks about something else, say politely that you can only help with
  reservations at the Clarium Bay Hotel, and steer back."""


def _calendar(today: date, days: int = 14) -> str:
    return "\n".join(f"- {(today + timedelta(d)).strftime('%A %B %d')}: {(today + timedelta(d)).isoformat()}" for d in range(1, days + 1))


def _date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ToolError(f"{name} must be a date like 2026-11-12") from None


class HotelAgent(Agent):
    def __init__(self, hotel: Hotel | None = None) -> None:
        self.hotel = hotel or Hotel()
        self.policies = knowledge.load()
        super().__init__(
            instructions=INSTRUCTIONS.format(today=self.hotel.today.strftime("%A, %B %d, %Y"), calendar=_calendar(self.hotel.today)),
            tools=[EndCallTool(extra_description="Use it after the caller says goodbye.")],
        )

    @function_tool()
    async def check_availability(self, context: RunContext, check_in: str, check_out: str, guests: int) -> dict:
        """Find the room types free for a stay, cheapest first, with the price.

        Args:
            check_in: arrival date, YYYY-MM-DD
            check_out: departure date, YYYY-MM-DD
            guests: number of people staying in the room
        """
        try:
            options = self.hotel.availability(_date(check_in, "check_in"), _date(check_out, "check_out"), guests)
        except BookingError as e:
            raise ToolError(str(e)) from None
        return {"available": options} if options else {"available": [], "note": "Nothing free for those dates."}

    @function_tool()
    async def make_reservation(
        self, context: RunContext, guest_name: str, phone: str, room_type: str, check_in: str, check_out: str, guests: int
    ) -> dict:
        """Book a room once the caller has confirmed every detail.

        Args:
            guest_name: full name for the reservation
            phone: the caller's phone number
            room_type: one of standard_queen, deluxe_king, family_suite
            check_in: arrival date, YYYY-MM-DD
            check_out: departure date, YYYY-MM-DD
            guests: number of people staying in the room
        """
        try:
            r = self.hotel.reserve(guest_name, phone, room_type, _date(check_in, "check_in"), _date(check_out, "check_out"), guests)
        except BookingError as e:
            raise ToolError(str(e)) from None
        log.info("reservation %s: %s, %s to %s", r.code, r.room_type, r.check_in, r.check_out)
        return {
            "confirmation_code": r.code,
            "room": ROOM_TYPES[r.room_type].name,
            "check_in": r.check_in.isoformat(),
            "check_out": r.check_out.isoformat(),
            "nights": r.nights,
            "total": r.total,
        }

    @function_tool()
    async def lookup_policy(self, context: RunContext, question: str) -> dict:
        """Look up the hotel's policies: check-in and check-out, cancellation, payment, breakfast, children,
        pets, Wi-Fi and smoking.

        Args:
            question: the caller's question, in a few words
        """
        found = knowledge.search(question, self.policies)
        if not found:
            return {"found": False, "note": "The policy file doesn't cover this."}
        return {"found": True, "sections": [{"title": s.title, "text": s.text} for s in found]}

    @function_tool()
    async def transfer_to_front_desk(self, context: RunContext, reason: str) -> str:
        """Hand the call to a person at the front desk, for anything you can't do yourself.

        Args:
            reason: one short sentence the front desk will see
        """
        # On a phone line this would move the call with a SIP transfer (see sip/README.md). Here we only log it.
        log.info("transfer to front desk: %s", reason)
        return "Transfer requested. Tell the caller you're connecting them to the front desk now."


class VoiceClaude(anthropic.LLM):
    """Claude for a phone call: with thinking turned off unless HOTEL_AGENT_THINKING=on."""

    def chat(self, *, extra_kwargs=None, **kwargs):
        extra = dict(extra_kwargs) if extra_kwargs is not None and is_given(extra_kwargs) else {}
        if not THINKING:
            extra.setdefault("thinking", {"type": "disabled"})
        return super().chat(extra_kwargs=extra, **kwargs)


def build_llm() -> anthropic.LLM:
    return VoiceClaude(model=MODEL)
