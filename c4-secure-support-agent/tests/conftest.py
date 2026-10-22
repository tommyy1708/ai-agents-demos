"""Tests run in mock mode against a throwaway database, with the A2A services on free ports."""

import os
import socket
import tempfile
import threading
import time

os.environ["SUPPORT_AGENT_MOCK"] = "1"
os.environ["SUPPORT_AGENT_DATA"] = tempfile.mkdtemp(prefix="support-agent-test-")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


os.environ["JUDGE_PORT"] = str(_free_port())
os.environ["MASKER_PORT"] = str(_free_port())

import pytest  # noqa: E402
import uvicorn  # noqa: E402

from support_agent import config, services  # noqa: E402


@pytest.fixture(scope="session")
def a2a_services():
    servers = []
    for port, app in services.apps().items():
        server = uvicorn.Server(uvicorn.Config(app, host=config.HOST, port=port, log_level="warning"))
        threading.Thread(target=server.run, daemon=True).start()
        servers.append(server)
    while not all(s.started for s in servers):
        time.sleep(0.05)
    yield
    for s in servers:
        s.should_exit = True


@pytest.fixture
def fresh_shop():
    config.SHOP_DB.unlink(missing_ok=True)
    yield
