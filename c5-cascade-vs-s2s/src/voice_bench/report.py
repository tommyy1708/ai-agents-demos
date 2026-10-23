"""The results table: each metric's mean with a 95% confidence interval, per system.

Slide 73's takeaway is the point of the table: compare the intervals, not just the averages. When two systems'
intervals overlap, this run hasn't shown a winner; run more repeats or call it a tie.
"""

import math
import statistics


def interval(values: list[float]) -> tuple[float, float] | None:
    """Mean and the half-width of a 95% confidence interval (normal approximation)."""
    values = [v for v in values if v is not None]
    if not values:
        return None
    mean = statistics.fmean(values)
    half = 1.96 * statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else 0.0
    return mean, half


# (label, record key, format, higher is better)
METRICS = [
    ("Time to first audio (ms)", "first_audio_ms", "{:.0f}", False),
    ("Time to the answer (ms)", "answer_audio_ms", "{:.0f}", False),
    ("Reply finished (ms)", "reply_end_ms", "{:.0f}", False),
    ("Tool precision", "tool_precision", "{:.2f}", True),
    ("Tool recall", "tool_recall", "{:.2f}", True),
    ("Response accuracy", "accuracy", "{:.2f}", True),
    ("Response completeness", "completeness", "{:.2f}", True),
    ("Word error rate", "wer", "{:.2f}", False),
    ("Cost per turn (USD)", "cost_usd", "{:.4f}", False),
]

COUNTS = [
    ("Leaks (another customer's data)", lambda r: bool(r["leaks"])),
    ("Personal data spoken", lambda r: bool(r["personal_data"])),
    ("Restricted tool called", lambda r: bool(r["forbidden_calls"])),
    ("Failed runs", lambda r: bool(r["error"])),
]


def _cell(iv: tuple[float, float] | None, fmt: str) -> str:
    if iv is None:
        return "n/a"
    mean, half = iv
    return f"{fmt.format(mean)} ± {fmt.format(half)}"


def verdict(a: tuple[float, float] | None, b: tuple[float, float] | None, higher_better: bool, names: tuple[str, str]) -> str:
    if a is None or b is None:
        return ""
    (ma, ha), (mb, hb) = a, b
    if abs(ma - mb) <= ha + hb:
        return "overlap: no clear winner"
    a_wins = ma > mb if higher_better else ma < mb
    return names[0] if a_wins else names[1]


def table(records: list[dict]) -> str:
    systems = sorted({r["system"] for r in records})
    by_system = {s: [r for r in records if r["system"] == s] for s in systems}
    header = ["Metric", *systems] + (["Better"] if len(systems) == 2 else [])
    rows = []
    for label, key, fmt, higher in METRICS:
        ivs = [interval([r.get(key) for r in by_system[s] if not r["error"]]) for s in systems]
        row = [label, *(_cell(iv, fmt) for iv in ivs)]
        if len(systems) == 2:
            row.append(verdict(ivs[0], ivs[1], higher, (systems[0], systems[1])))
        rows.append(row)
    for label, hit in COUNTS:
        row = [label, *(f"{sum(hit(r) for r in by_system[s])} of {len(by_system[s])}" for s in systems)]
        if len(systems) == 2:
            row.append("must be zero" if label.startswith("Leaks") else "")
        rows.append(row)
    widths = [max(len(str(x)) for x in col) for col in zip(header, *rows)]
    line = lambda cells: "  ".join(str(c).ljust(w) for c, w in zip(cells, widths)).rstrip()  # noqa: E731
    return "\n".join([line(header), line(["-" * w for w in widths]), *map(line, rows)])


def failures(records: list[dict]) -> str:
    """The runs worth listening to: anything wrong, one line each."""
    lines = []
    for r in records:
        problems = []
        if r["error"]:
            problems.append(r["error"])
        if r["tool_recall"] < 1 or r["tool_precision"] < 1:
            problems.append("tools: " + (", ".join(t["name"] for t in r["tool_calls"]) or "none"))
        if r["forbidden_calls"]:
            problems.append("restricted tool")
        if r["leaks"]:
            problems.append("leaked " + ", ".join(r["leaks"]))
        if r["personal_data"]:
            problems.append("spoke " + ", ".join(r["personal_data"]))
        if r.get("accuracy") is not None and min(r["accuracy"], r["completeness"]) < 0.7:
            problems.append(f"judge {r['accuracy']:.1f}/{r['completeness']:.1f}: {r.get('judge_reason', '')}")
        if problems:
            lines.append(f"  {r['case']} {r['system']:<9} #{r['repeat']}  " + "; ".join(problems))
    return "\n".join(lines) or "  none"
