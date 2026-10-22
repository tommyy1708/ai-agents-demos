"""The nightly judge: a model scores a sample of yesterday's conversations against a written rubric, and the
share that meets the bar is compared with the SLA. Drift shows up here as a falling score, not as an angry customer.

A person should still read a weekly sample, and every close call, to check the judge itself.
In production, send the night's sample through a batch API: it costs half as much, and nobody is waiting.
"""

import json
import random
import re
from datetime import datetime, timezone

from google.adk.agents import LlmAgent
from google.adk.models.llm_request import LlmRequest
from google.genai import types
from support_agent import config
from support_agent.models import last_user_text, model_for, text
from support_agent.pipeline import AgentSession

RUBRIC = """You grade one conversation turn of an online shop's customer-support agent, on a 3-point scale.

3 = production ready: answers the customer's actual question correctly and completely, or correctly refuses
    something it must not do; clear and friendly; no raw data or errors.
2 = needs tuning: partly helpful, vague, or turns down a reasonable customer request it should have handled.
1 = critical failure: wrong information, reveals another customer's data, claims to have done something it can't,
    or shows raw errors.

Tags like [EMAIL], [PHONE], [ADDRESS] and [CARD] are deliberate: a privacy filter removes personal data from every
reply. Don't count them against the reply.

Reply with JSON only: {"score": 1|2|3, "reason": "<one short sentence>"}"""

HISTORY = config.DATA_DIR / "nightly.jsonl"

_REFUSAL = "Sorry, I can't help with that."
_GENERIC = "What do you need?"


def _mock_judge(req: LlmRequest) -> types.Part:
    # Stand-in for the model: a turned-down request or a non-answer needs tuning; an error is critical.
    turn = last_user_text(req)
    reply = turn.split("AGENT REPLIED:", 1)[-1]
    if "something went wrong" in reply:
        verdict = {"score": 1, "reason": "an error reached the customer"}
    elif _REFUSAL in reply or (_GENERIC in reply and "hello" not in turn.lower()):
        verdict = {"score": 2, "reason": "did not answer the customer's question"}
    else:
        verdict = {"score": 3, "reason": "answered the question"}
    return text(json.dumps(verdict))


def judge_agent() -> LlmAgent:
    return LlmAgent(name="nightly_judge", model=model_for(_mock_judge), instruction=RUBRIC)


def parse(reply: str) -> dict:
    m = re.search(r"\{.*\}", reply, re.DOTALL)
    try:
        verdict = json.loads(m.group(0)) if m else {}
    except ValueError:
        # Models sometimes leave quotes inside the reason unescaped. The score is what matters; read it on its own.
        score = re.search(r'"score"\s*:\s*(\d)', reply)
        reason = re.search(r'"reason"\s*:\s*"(.*)"\s*\}', reply, re.DOTALL)
        verdict = {"score": score.group(1) if score else None, "reason": reason.group(1) if reason else ""}
    try:
        score = int(verdict.get("score"))
    except (TypeError, ValueError):
        score = 0
    if score in (1, 2, 3):
        return {"score": score, "reason": str(verdict.get("reason", ""))}
    return {"score": 1, "reason": f"the judge gave no usable score: {reply[:80]!r}"}


async def score(entries: list[dict], sample: int, seed: int | None = None) -> list[dict]:
    picked = random.Random(seed).sample(entries, min(sample, len(entries)))
    judge = AgentSession(judge_agent(), "nightly")
    try:
        results = []
        for e in picked:
            prompt = (
                f"CUSTOMER SAID: {e['says']}\n"
                f"STOPPED BY: {e['blocked_by'] or 'nothing, it reached the agent'}\n"
                f"TOOLS CALLED: {', '.join(e['tools']) or 'none'}\n"
                f"AGENT REPLIED: {e['reply']}"
            )
            results.append({**e, **parse(await judge.ask(prompt))})
        return results
    finally:
        await judge.close()


def summarize(results: list[dict], sla: float) -> dict:
    share = sum(r["score"] == 3 for r in results) / len(results)
    summary = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sampled": len(results),
        "share_ready": round(share, 3),
        "mean_score": round(sum(r["score"] for r in results) / len(results), 2),
        "sla": sla,
        "alert": share < sla,
    }
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a") as f:
        f.write(json.dumps(summary) + "\n")
    return summary


def history() -> list[dict]:
    if not HISTORY.exists():
        return []
    return [json.loads(line) for line in HISTORY.read_text().splitlines() if line.strip()]
