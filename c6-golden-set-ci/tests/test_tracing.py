from support_agent.pipeline import Pipeline

from golden_ci import tracing


async def test_a_trace_has_a_span_for_every_layer(ports):
    exporter = tracing.setup()
    exporter.clear()
    pipeline = Pipeline("maya.chen@example.com", judge_port=ports[0], masker_port=ports[1])
    try:
        await pipeline.handle("What is the status of order 2?")
    finally:
        await pipeline.close()
    t = tracing.collect(exporter.get_finished_spans())

    assert t.root.name == "agent.turn"
    assert [s.name for s in tracing.visible(t.root)] == [
        "security.sanitize",
        "security.a2a_judge",
        "guardrail.check",
        "memory.recall",
        "invoke_agent support_agent",
        "security.a2a_mask",
        "memory.save",
    ]
    assert t.tools == ["get-order-status"]
    assert t.cost == 0  # mock mode
    assert "execute_tool get-order-status" in tracing.render(t)


async def test_a_blocked_request_stops_at_its_layer(ports):
    exporter = tracing.setup()
    exporter.clear()
    pipeline = Pipeline("maya.chen@example.com", judge_port=ports[0], masker_port=ports[1])
    try:
        await pipeline.handle("order 5; DELETE FROM orders")
    finally:
        await pipeline.close()
    t = tracing.collect(exporter.get_finished_spans())
    assert [s.name for s in tracing.visible(t.root)] == ["security.sanitize", "security.a2a_judge"]
    assert tracing.visible(t.root)[-1].attrs["passed"] is False
    assert t.tools == []
