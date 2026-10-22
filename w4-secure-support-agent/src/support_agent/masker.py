"""The data masker: an A2A agent with no model in it, just patterns that redact personal data from replies.

Not every agent needs an LLM. This one is a plain ADK agent, so it can be served over A2A like the others.
"""

import re
from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

PII_PATTERNS: dict[str, str] = {
    "EMAIL": r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
    "CARD": r"\b\d(?:[ -]?\d){12,15}\b",
    "PHONE": r"\+?\d{1,3}[ .-]?\(?\d{3}\)?[ .-]?\d{4}\b|\b\d{3}[ .-]\d{4}\b",
    "ADDRESS": r"\b\d{1,5}\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Way|Court|Ct)\b(?:,\s*[A-Z][a-z]+)?",
}
_COMPILED = [(label, re.compile(p)) for label, p in PII_PATTERNS.items()]


def mask(text: str) -> tuple[str, list[str]]:
    """The text with personal data replaced by [EMAIL], [PHONE], ..., and the labels it replaced."""
    found = []
    for label, pattern in _COMPILED:
        text, n = pattern.subn(f"[{label}]", text)
        if n:
            found.append(label)
    return text, found


class DataMasker(BaseAgent):
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        incoming = "".join(p.text or "" for p in (ctx.user_content.parts if ctx.user_content else []))
        masked, _ = mask(incoming)
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            content=types.Content(role="model", parts=[types.Part(text=masked)]),
        )


def data_masker_agent() -> DataMasker:
    return DataMasker(name="data_masker", description="Redacts emails, phone numbers, card numbers and street addresses.")
