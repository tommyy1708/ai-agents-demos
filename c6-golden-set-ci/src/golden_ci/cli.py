"""Command line for the Week 6 demo: trace a request, run the golden set as a release gate, simulate live traffic,
and run the nightly judge."""

import argparse
import asyncio
import shutil
import sys

from support_agent import config
from support_agent.pipeline import Pipeline

from golden_ci import golden, nightly, traffic, tracing
from golden_ci.services import a2a_services


def _banner() -> None:
    mode = "mock mode (no ANTHROPIC_API_KEY): scripted replies" if config.mock_mode() else f"model {config.MODEL}"
    print(f"Running with {mode}.\n")


async def _trace(message: str, email: str, unsafe: bool, all_spans: bool, ports) -> None:
    exporter = tracing.setup()
    pipeline = Pipeline(email, unsafe=unsafe, judge_port=ports[0], masker_port=ports[1])
    try:
        turn = await pipeline.handle(message)
    finally:
        await pipeline.close()
    print(f"> {message}\n")
    print(tracing.render(tracing.collect(exporter.get_finished_spans()), all_spans=all_spans))
    print(f"\nREPLY: {turn.reply}")


async def _run(unsafe: bool, runs: int, only: str | None, ports) -> bool:
    cases = [c for c in golden.load() if not only or c.id == only]
    if not cases:
        raise SystemExit(f"No case with the id {only!r}")
    label = f"pass^{runs}: every one of {runs} runs must pass" if runs > 1 else "one run per case"
    print(f"Golden set: {len(cases)} cases, {label}{', UNSAFE mode' if unsafe else ''}\n")
    results = []
    for case in cases:
        result = await golden.run_case(case, unsafe=unsafe, ports=ports, runs=runs)
        results.append(result)
        mark = "PASS" if result.passed else "FAIL"
        tally = f"{runs - len(result.failures)}/{runs}" if runs > 1 else ""
        print(f"  {mark} {tally:>5}  {case.kind:<6}  {case.id:<22} {case.says[:52]}", flush=True)
        for problems in result.failures[:1]:
            for p in problems:
                print(f"{'':>22}- {p}")
    failed = [r for r in results if not r.passed]
    print(f"\n{len(results) - len(failed)}/{len(results)} cases pass.", end=" ")
    print("Gate: OPEN, ship it." if not failed else "Gate: CLOSED, fix the failing cases before you ship.")
    return not failed


async def _simulate(drift: bool, ports) -> None:
    print(f"Sending {'everyday and new kinds of' if drift else 'everyday'} requests through the agent:")
    n = await traffic.simulate(ports, drift=drift)
    print(f"\nLogged {n} conversations to {traffic.LOG}. Next: golden nightly")


async def _nightly(sample: int, sla: float, seed: int | None) -> None:
    last = (nightly.history() or [{}])[-1].get("at", "")
    entries = [e for e in traffic.read() if e["at"] > last] if last else traffic.read()
    if not entries:
        raise SystemExit("No new traffic since the last nightly run. Run `golden simulate` first.")
    print(f"Judging {min(sample, len(entries))} of {len(entries)} new conversations against the rubric (3 = production ready):\n")
    results = await nightly.score(entries, sample, seed)
    for r in results:
        print(f"  {r['score']}  {r['says'][:56]:<56} {r['reason'][:60]}")
    s = nightly.summarize(results, sla)
    print(f"\nProduction ready: {s['share_ready']:.0%} (SLA {sla:.0%}), mean score {s['mean_score']}")
    print("ALERT: below the SLA. Read the low scores, add them to the golden set, fix, and ship through the gate."
          if s["alert"] else "Within the SLA.")
    runs = nightly.history()
    if len(runs) > 1:
        print("\nNight by night:")
        for h in runs[-7:]:
            bar = "█" * round(h["share_ready"] * 20)
            print(f"  {h['at'][:16]}  {bar:<20} {h['share_ready']:.0%}{'  ALERT' if h['alert'] else ''}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="golden", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("trace", help="send one message and show its trace: every step, its time and cost")
    t.add_argument("message")
    t.add_argument("--as", dest="email", default="maya.chen@example.com", help="customer email")
    t.add_argument("--unsafe", action="store_true", help="the Week 4 agent without its checks in code")
    t.add_argument("--all", action="store_true", help="show plumbing spans too (MCP, A2A transport, raw model calls)")
    r = sub.add_parser("run", help="run the golden set; exits with an error if any case fails (the release gate)")
    r.add_argument("--unsafe", action="store_true", help="run it against the agent without its checks in code")
    r.add_argument("--runs", type=int, default=1, help="runs per case; a case passes only if all pass (pass^k)")
    r.add_argument("--case", help="run only the case with this id")
    s = sub.add_parser("simulate", help="send a day of customer messages through the agent and log them")
    s.add_argument("--drift", action="store_true", help="add new kinds of requests the agent wasn't built for")
    n = sub.add_parser("nightly", help="judge a sample of the logged conversations and compare with the SLA")
    n.add_argument("--sample", type=int, default=10, help="conversations to judge (default 10)")
    n.add_argument("--sla", type=float, default=0.9, help="share that must score 3 (default 0.9)")
    n.add_argument("--seed", type=int, help="fix the random sample")
    sub.add_parser("reset", help="delete the shop data, traffic log and nightly history")
    args = parser.parse_args()

    if args.command == "reset":
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)
        print(f"Deleted {config.DATA_DIR}/.")
        return
    _banner()
    if args.command == "nightly":
        asyncio.run(_nightly(args.sample, args.sla, args.seed))
        return
    with a2a_services() as ports:
        if args.command == "trace":
            asyncio.run(_trace(args.message, args.email, args.unsafe, args.all, ports))
        elif args.command == "run":
            ok = asyncio.run(_run(args.unsafe, args.runs, args.case, ports))
            sys.exit(0 if ok else 1)
        elif args.command == "simulate":
            asyncio.run(_simulate(args.drift, ports))
