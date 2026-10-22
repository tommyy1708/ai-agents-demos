"""The release gate: the golden set passes on the Week 4 agent, and fails on it without its checks in code."""

from golden_ci import golden

CASES = golden.load()


async def run_all(ports, unsafe: bool) -> dict[str, golden.Result]:
    return {c.id: await golden.run_case(c, unsafe=unsafe, ports=ports) for c in CASES}


async def test_the_golden_set_passes_on_the_agent(ports):
    failed = {id: r.failures for id, r in (await run_all(ports, unsafe=False)).items() if not r.passed}
    assert failed == {}


async def test_the_gate_closes_without_the_checks_in_code(ports):
    results = await run_all(ports, unsafe=True)
    failed = sorted(id for id, r in results.items() if not r.passed)
    assert failed == ["claims-to-own-it", "direct-status-change", "someone-elses-order"]


def test_every_case_has_an_id_and_a_reason():
    assert len({c.id for c in CASES}) == len(CASES)
    assert all(c.why and c.kind in {"normal", "attack"} for c in CASES)
