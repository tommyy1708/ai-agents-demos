"""The two A2A microservices: the security judge and the data masker, each on its own port.

Run them with `support-agent serve`; `support-agent chat` and `support-agent demo` start them for you.
Open http://127.0.0.1:8101/.well-known/agent-card.json to see how an A2A agent describes itself.
"""

import asyncio

import uvicorn
from google.adk.a2a.utils.agent_to_a2a import to_a2a

from support_agent import config
from support_agent.checks import security_judge_agent
from support_agent.masker import data_masker_agent

CARD_PATH = "/.well-known/agent-card.json"


def card_url(port: int) -> str:
    return f"http://{config.HOST}:{port}{CARD_PATH}"


def apps(judge_port: int = config.JUDGE_PORT, masker_port: int = config.MASKER_PORT):
    return {
        judge_port: to_a2a(security_judge_agent(), host=config.HOST, port=judge_port),
        masker_port: to_a2a(data_masker_agent(), host=config.HOST, port=masker_port),
    }


async def serve(judge_port: int = config.JUDGE_PORT, masker_port: int = config.MASKER_PORT) -> None:
    servers = [
        uvicorn.Server(uvicorn.Config(app, host=config.HOST, port=port, log_level="warning"))
        for port, app in apps(judge_port, masker_port).items()
    ]
    await asyncio.gather(*(s.serve() for s in servers))


if __name__ == "__main__":
    asyncio.run(serve())
