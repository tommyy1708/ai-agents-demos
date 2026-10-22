"""One customer message through every layer, in order, with a record of what each layer decided.

The order is fixed in code, not left to a model: a message that fails a check never reaches the next layer.
"""

from contextlib import closing
from dataclasses import dataclass, field

from google.adk.a2a.agent import RemoteA2aAgent
from google.adk.agents import BaseAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from support_agent import config, shop
from support_agent.agent import support_agent
from support_agent.checks import Check, guardrail_agent, guardrail_check, judge_check, sanitize
from support_agent.models import tool_payload
from support_agent.services import card_url

APP = "secure-support-agent"


@dataclass
class ToolCall:
    name: str
    args: dict
    result: dict | None = None


@dataclass
class Turn:
    message: str
    checks: list[Check] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    reply: str = ""

    @property
    def blocked(self) -> bool:
        return any(not c.passed for c in self.checks)


class _Agent:
    """An agent with its own runner and session, so each layer keeps its own conversation."""

    def __init__(self, agent: BaseAgent, user_id: str, state: dict | None = None):
        self.sessions = InMemorySessionService()
        self.runner = Runner(agent=agent, app_name=APP, session_service=self.sessions)
        self.user_id = user_id
        self.state = state
        self.session_id: str | None = None

    async def ask(self, message: str, *, keep_history: bool = False, on_event=None) -> str:
        if self.session_id is None or not keep_history:
            session = await self.sessions.create_session(app_name=APP, user_id=self.user_id, state=self.state)
            self.session_id = session.id
        reply = ""
        content = types.Content(role="user", parts=[types.Part(text=message)])
        async for event in self.runner.run_async(user_id=self.user_id, session_id=self.session_id, new_message=content):
            if on_event:
                on_event(event)
            if event.is_final_response() and event.content and event.content.parts:
                reply = "".join(p.text or "" for p in event.content.parts) or reply
        return reply

    async def close(self) -> None:
        await self.runner.close()


class Pipeline:
    def __init__(self, customer_email: str, *, unsafe: bool = False, judge_port: int = config.JUDGE_PORT, masker_port: int = config.MASKER_PORT):
        with closing(shop.connect(config.SHOP_DB)) as conn:
            customer = shop.customer(conn, customer_email)
            if not customer:
                raise ValueError(f"No customer with the email {customer_email}")
            memory = shop.recall(conn, customer["email"])
        self.email = customer["email"]
        self.judge = _Agent(RemoteA2aAgent(name="security_judge", agent_card=card_url(judge_port)), self.email)
        self.guardrail = _Agent(guardrail_agent(), self.email)
        self.agent = _Agent(
            support_agent(unsafe),
            self.email,
            state={"customer_email": self.email, "customer_name": customer["name"], "memory": "\n".join(f"- {m}" for m in memory)},
        )
        self.masker = _Agent(RemoteA2aAgent(name="data_masker", agent_card=card_url(masker_port)), self.email)

    async def handle(self, message: str) -> Turn:
        turn = Turn(message)

        def stop(check: Check) -> bool:
            turn.checks.append(check)
            if not check.passed:
                turn.reply = "Sorry, I can't help with that. I can help with your orders, deliveries and returns."
            return not check.passed

        if stop(sanitize(message)):
            return turn
        if stop(judge_check(await self.judge.ask(message))):
            return turn
        if stop(guardrail_check(await self.guardrail.ask(message))):
            return turn

        def record(event) -> None:
            for call in event.get_function_calls():
                turn.tool_calls.append(ToolCall(call.name, dict(call.args or {})))
            for response in event.get_function_responses():
                for call in turn.tool_calls:
                    if call.name == response.name and call.result is None:
                        call.result = tool_payload(response.response)
                        break

        try:
            answer = await self.agent.ask(message, keep_history=True, on_event=record)
            turn.reply = await self.masker.ask(answer) if answer else answer
        except Exception as e:  # a model or service failure must not crash the conversation
            turn.checks.append(Check("support agent", False, f"failed: {e}"[:200]))
            turn.reply = "Sorry, something went wrong on our side. Please try again in a moment."
            return turn
        redacted = sorted({tag for tag in ("EMAIL", "PHONE", "CARD", "ADDRESS") if f"[{tag}]" in turn.reply and f"[{tag}]" not in answer})
        turn.checks.append(Check("data masker", True, f"redacted {', '.join(redacted)}" if redacted else ""))

        with closing(shop.connect(config.SHOP_DB)) as conn:
            shop.remember(conn, self.email, f"Asked: {message[:120]} | Answered: {turn.reply[:160]}")
        return turn

    async def close(self) -> None:
        for layer in (self.judge, self.guardrail, self.agent, self.masker):
            await layer.close()
