"""Stand-in for live traffic: customers' messages through the agent, each logged with its trace summary.

In production this log comes from the running service. Here `golden simulate` writes it, and `--drift` adds
requests of a kind the agent was never built for, which is what drift usually is: the world changed, the code
didn't.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from support_agent import config
from support_agent.pipeline import Pipeline

from golden_ci import tracing

LOG = config.DATA_DIR / "traffic.jsonl"

EVERYDAY = [
    ("maya.chen@example.com", "Has order 2 shipped yet?"),
    ("maya.chen@example.com", "What did I order in order 10?"),
    ("leo.garcia@example.com", "Where is my order number 5?"),
    ("leo.garcia@example.com", "Which orders have I placed?"),
    ("ines.novak@example.com", "Can you tell me the status of order 6?"),
    ("ines.novak@example.com", "I'd like to return order 7, the bookshelf. Yes, I confirm."),
    ("sam.okafor@example.com", "What is the status of order 8?"),
    ("sam.okafor@example.com", "Hello! Which orders have I placed?"),
]

# New kinds of requests: the shop started selling gift cards and a loyalty scheme, and nobody told the agent.
DRIFT = [
    ("maya.chen@example.com", "How much is left on my gift card?"),
    ("leo.garcia@example.com", "How many loyalty points do I have?"),
    ("ines.novak@example.com", "Can I pay for my next purchase with my gift card?"),
    ("sam.okafor@example.com", "Do my loyalty points expire?"),
    ("maya.chen@example.com", "Can I buy a gift card for a friend?"),
    ("leo.garcia@example.com", "Can I use loyalty points on order 5?"),
]


async def simulate(ports: tuple[int, int], *, drift: bool) -> int:
    exporter = tracing.setup()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    messages = EVERYDAY + (DRIFT if drift else [])
    with LOG.open("a") as log:
        for customer, says in messages:
            exporter.clear()
            pipeline = Pipeline(customer, judge_port=ports[0], masker_port=ports[1])
            try:
                turn = await pipeline.handle(says)
            finally:
                await pipeline.close()
            t = tracing.collect(exporter.get_finished_spans())
            entry = {
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "customer": customer,
                "says": says,
                "reply": turn.reply,
                "blocked_by": next((c.name for c in turn.checks if not c.passed), ""),
                "tools": t.tools,
                "ms": round(t.ms),
                "cost": t.cost,
            }
            log.write(json.dumps(entry) + "\n")
            print(f"  {customer:<24} {says[:60]}", flush=True)
    return len(messages)


def read(path: Path = LOG) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
