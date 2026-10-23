"""The benchmark's commands.

    bench cases                     the scripted calls and what each one expects
    bench audio                     turn the questions into audio files (needs LiveKit)
    bench run                       play every question into both systems, score, and print the table
    bench report                    print the table for the last run again
"""

import argparse
import asyncio
import json
import os
import sys
import tomllib
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
CASES_FILE = ROOT / "cases.toml"
DATA = ROOT / ".data"
AUDIO = DATA / "audio"
RESULTS = DATA / "results"

CALLER_VOICES = os.environ.get("BENCH_CALLER_VOICES", "athena,apollo,theia,odysseus").split(",")
CALLER_TTS = os.environ.get("BENCH_CALLER_TTS", "deepgram/aura-2")

NEEDS = {
    "audio": ["LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"],
    "cascaded": ["LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "ANTHROPIC_API_KEY"],
    "s2s": ["GOOGLE_API_KEY"],
    "judge": ["ANTHROPIC_API_KEY"],
}


def load_cases(only: str | None = None) -> list[dict]:
    cases = tomllib.loads(CASES_FILE.read_text())["case"]
    if only:
        wanted = set(only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    return cases


def require(*parts: str) -> None:
    missing = sorted({k for p in parts for k in NEEDS[p] if not os.environ.get(k)})
    if missing:
        sys.exit(f"Missing {', '.join(missing)}. Copy .env.example to .env and fill it in (see README, Setup).")


def cmd_cases(args) -> None:
    for c in load_cases(args.cases):
        tools = " → ".join(c["expected_tools"]) or "no tools"
        extra = f"   never: {', '.join(c['forbidden_tools'])}" if c.get("forbidden_tools") else ""
        print(f"{c['id']}  {c['category']:<26} {c['question']}\n     expects: {tools}{extra}")


async def make_audio(cases: list[dict], force: bool) -> None:
    from voice_bench.audio import synthesize_questions

    print(f"Questions to audio with {CALLER_TTS}, voices {', '.join(CALLER_VOICES)}:")
    await synthesize_questions(cases, AUDIO, CALLER_VOICES, CALLER_TTS, force=force)


def cmd_audio(args) -> None:
    require("audio")
    asyncio.run(make_audio(load_cases(args.cases), args.force))


async def run_all(cases: list[dict], systems: list[str], repeat: int, judge_on: bool) -> list[dict]:
    from livekit.plugins import silero

    from voice_bench import scoring
    from voice_bench.runner import run_once

    missing_audio = [c for c in cases if not (AUDIO / f"{c['id']}.wav").exists()]
    if missing_audio:
        require("audio")
        await make_audio(missing_audio, force=False)

    client = None
    if judge_on:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic()
    vad = silero.VAD.load() if "cascaded" in systems else None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = RESULTS / stamp
    records = []
    for n in range(1, repeat + 1):
        for case in cases:
            # Alternate which system goes first, so neither always gets the warmer connection.
            order = systems if (n + cases.index(case)) % 2 else list(reversed(systems))
            for system in order:
                record = await run_once(
                    system, case, AUDIO / f"{case['id']}.wav", vad=vad, save_audio=out_dir / f"{case['id']}-{system}-{n}.wav"
                )
                record["repeat"] = n
                record.update(scoring.score(record, case))
                if client is not None and not record["error"]:
                    try:
                        verdict = await scoring.judge(client, record, case)
                        record.update(accuracy=verdict["accuracy"], completeness=verdict["completeness"], judge_reason=verdict.get("reason", ""))
                    except Exception as e:  # noqa: BLE001
                        record.update(accuracy=None, completeness=None, judge_reason=f"judge failed: {e}")
                records.append(record)
                first = f"{record['first_audio_ms']} ms" if record["first_audio_ms"] is not None else "no audio"
                print(f"  {case['id']} {system:<9} #{n}  first audio {first:>9}  heard: {record['heard'][:60]!r}")
                print(f"  {'':<3} {'':<9}     said: {record['spoken'][:110]!r}")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    return records


def print_report(records: list[dict], where: Path | None = None) -> None:
    from voice_bench.report import failures, table

    print()
    print(table(records))
    print("\nRuns to look at:")
    print(failures(records))
    if where:
        print(f"\nRecords and the agent's audio for every run: {where}")


def cmd_run(args) -> None:
    systems = args.systems.split(",")
    for s in systems:
        if s not in ("cascaded", "s2s"):
            sys.exit(f"Unknown system {s!r}: use cascaded, s2s or both (cascaded,s2s)")
    require(*systems, *(["judge"] if not args.no_judge else []))
    cases = load_cases(args.cases)
    records = asyncio.run(run_all(cases, systems, args.repeat, not args.no_judge))
    print_report(records, sorted(RESULTS.iterdir())[-1])


def cmd_report(args) -> None:
    runs = sorted(RESULTS.iterdir()) if RESULTS.exists() else []
    if not runs:
        sys.exit("No results yet. Run `uv run bench run` first.")
    path = Path(args.path) if args.path else runs[-1]
    records = [json.loads(line) for line in (path / "results.jsonl").read_text().splitlines()]
    print_report(records, path)


def main() -> None:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(prog="bench", description="Cascaded vs speech-to-speech, head to head.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("cases", help="list the scripted calls")
    p.add_argument("--cases", help="only these case ids, comma-separated")
    p.set_defaults(func=cmd_cases)

    p = sub.add_parser("audio", help="turn the questions into audio files")
    p.add_argument("--cases", help="only these case ids, comma-separated")
    p.add_argument("--force", action="store_true", help="remake files that already exist")
    p.set_defaults(func=cmd_audio)

    p = sub.add_parser("run", help="run the benchmark")
    p.add_argument("--systems", default="cascaded,s2s", help="cascaded, s2s, or cascaded,s2s (default)")
    p.add_argument("--cases", help="only these case ids, comma-separated, e.g. q01,q12")
    p.add_argument("--repeat", type=int, default=3, help="runs per case per system (default 3)")
    p.add_argument("--no-judge", action="store_true", help="skip the LLM judge")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("report", help="print the table for the last run again")
    p.add_argument("path", nargs="?", help="a results folder under .data/results (default: the latest)")
    p.set_defaults(func=cmd_report)

    args = parser.parse_args()
    args.func(args)
