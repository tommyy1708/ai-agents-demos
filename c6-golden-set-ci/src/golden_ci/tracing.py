"""Traces: every step one request took, with its time and, for model calls, its tokens and cost.

The Week 4 pipeline already creates spans for its layers, and ADK creates spans for agents, model calls and tool
calls. This module collects them. Set OTEL_EXPORTER_OTLP_ENDPOINT (for example http://localhost:6006/v1/traces for
a local Arize Phoenix) to also send them to a tracing tool.
"""

import os
from dataclasses import dataclass, field

from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# USD per million tokens. Claude Haiku 5.5 on the Anthropic API, Oct 2026.
PRICES = {
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125},
    "mock": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0},
}

# Plumbing spans that make a trace harder to read without telling you anything about the agent.
HIDDEN = ("MCP send", "a2a.", "generate_content", "anthropic.messages", "invocation")

_exporter: InMemorySpanExporter | None = None


def setup() -> InMemorySpanExporter:
    """Installs the tracer provider once per process."""
    global _exporter
    if _exporter is None:
        _exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(_exporter))
        if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
    return _exporter


@dataclass
class Span:
    name: str
    ms: float
    attrs: dict
    children: list["Span"] = field(default_factory=list)

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass
class Trace:
    root: Span

    @property
    def ms(self) -> float:
        return self.root.ms

    def spans(self, prefix: str) -> list[Span]:
        return [s for s in self.root.walk() if s.name.startswith(prefix)]

    @property
    def tools(self) -> list[str]:
        return [s.attrs.get("gen_ai.tool.name", s.name.removeprefix("execute_tool ")) for s in self.spans("execute_tool")]

    @property
    def tokens(self) -> dict[str, int]:
        total = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        for s in self.spans("call_llm"):
            total["input"] += s.attrs.get("gen_ai.usage.input_tokens", 0)
            total["output"] += s.attrs.get("gen_ai.usage.output_tokens", 0)
            total["cache_read"] += s.attrs.get("gen_ai.usage.cache_read.input_tokens", 0)
            total["cache_write"] += s.attrs.get("gen_ai.usage.cache_creation.input_tokens", 0)
        return total

    @property
    def cost(self) -> float | None:
        """Estimated USD for every model call in the request, or None if a model has no price here."""
        usd = 0.0
        for s in self.spans("call_llm"):
            model = str(s.attrs.get("gen_ai.request.model", "")).split("anthropic.")[-1]
            price = PRICES.get(model)
            if price is None:
                return None
            usd += (
                s.attrs.get("gen_ai.usage.input_tokens", 0) * price["input"]
                + s.attrs.get("gen_ai.usage.output_tokens", 0) * price["output"]
                + s.attrs.get("gen_ai.usage.cache_read.input_tokens", 0) * price["cache_read"]
                + s.attrs.get("gen_ai.usage.cache_creation.input_tokens", 0) * price["cache_write"]
            ) / 1_000_000
        return usd


def collect(spans: list[ReadableSpan]) -> Trace:
    """Builds the tree under the newest agent.turn span. Spans from the A2A services, which run in this process
    but arrive without a parent, are attached to the turn by time."""
    turn = max((s for s in spans if s.name == "agent.turn"), key=lambda s: s.start_time)
    inside = [s for s in spans if s.start_time >= turn.start_time and s.end_time <= turn.end_time]
    nodes = {s.context.span_id: Span(s.name, (s.end_time - s.start_time) / 1e6, dict(s.attributes or {})) for s in inside}
    root = nodes[turn.context.span_id]
    by_start = sorted(inside, key=lambda s: s.start_time)
    for s in by_start:
        if s is turn:
            continue
        parent = nodes.get(s.parent.span_id) if s.parent else None
        if parent is None:
            # No parent here: hang it on the deepest layer span that was open when it started.
            layers = [l for l in by_start if l.name.startswith(("security.", "guardrail.")) and l.start_time <= s.start_time <= l.end_time]
            parent = nodes[layers[-1].context.span_id] if layers else root
        parent.children.append(nodes[s.context.span_id])
    return Trace(root)


def visible(span: Span) -> list[Span]:
    """A span's children as the rendered trace shows them: plumbing spans are skipped, their children kept."""
    out = []
    for child in span.children:
        out.extend(visible(child) if child.name.startswith(HIDDEN) else [child])
    return out


def render(t: Trace, *, all_spans: bool = False) -> str:
    lines = []

    def visit(span: Span, depth: int) -> None:
        visible = all_spans or not span.name.startswith(HIDDEN)
        if visible:
            label = "  " * depth + ("└ " if depth else "") + span.name
            detail = f"{span.ms:7.0f} ms"
            if span.name == "call_llm":
                detail += f"   {span.attrs.get('gen_ai.usage.input_tokens', 0)} in / {span.attrs.get('gen_ai.usage.output_tokens', 0)} out tokens"
            if span.attrs.get("passed") is False:
                detail += f"   BLOCKED: {span.attrs.get('reason', '')}"
            lines.append(f"{label:<44}{detail}")
        for child in span.children:
            visit(child, depth + 1 if visible else depth)

    visit(t.root, 0)
    cost = "unknown (no price for this model)" if t.cost is None else f"${t.cost:.5f}"
    tokens = t.tokens
    lines.append(f"\nTotal: {t.ms / 1000:.1f} s, {tokens['input']} input + {tokens['output']} output tokens, cost {cost}")
    return "\n".join(lines)
