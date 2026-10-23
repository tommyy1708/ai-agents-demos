from voice_bench import report


def rec(system, **kw):
    base = {"system": system, "case": "q01", "repeat": 1, "error": None, "tool_calls": [], "leaks": [], "personal_data": [],
            "forbidden_calls": [], "tool_precision": 1.0, "tool_recall": 1.0, "first_audio_ms": 1000, "reply_end_ms": 3000,
            "wer": 0.0, "cost_usd": 0.001, "accuracy": 1.0, "completeness": 1.0}
    return base | kw


def test_overlapping_intervals_are_no_winner():
    assert report.verdict((0.90, 0.05), (0.85, 0.05), True, ("a", "b")) == "overlap: no clear winner"
    assert report.verdict((0.95, 0.01), (0.80, 0.02), True, ("a", "b")) == "a"
    assert report.verdict((900, 50), (500, 50), False, ("a", "b")) == "b"


def test_table_and_failures():
    records = [rec("cascaded", first_audio_ms=1400 + i) for i in range(3)] + [
        rec("s2s", first_audio_ms=600 + i) for i in range(2)
    ] + [rec("s2s", personal_data=["address"], tool_recall=0.0, tool_calls=[{"name": "log_action"}])]
    out = report.table(records)
    assert "Time to first audio (ms)" in out and "s2s" in out.splitlines()[0]
    assert "1 of 3" in out  # personal data spoken by s2s
    assert "spoke address" in report.failures(records)
    assert "tools: log_action" in report.failures(records)


def test_failed_runs_are_left_out_of_the_means():
    records = [rec("cascaded", first_audio_ms=1000), rec("cascaded", first_audio_ms=None, error="timeout")]
    assert "1000 ± 0" in report.table(records)
