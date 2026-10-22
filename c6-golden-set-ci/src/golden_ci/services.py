"""Runs the Week 4 A2A services in this process, on free ports, so their model calls land in the same trace."""

import socket
import threading
import time
from contextlib import contextmanager

import uvicorn
from support_agent import config, services


def _free_port() -> int:
    with socket.socket() as s:
        s.bind((config.HOST, 0))
        return s.getsockname()[1]


@contextmanager
def a2a_services():
    """Yields (judge_port, masker_port) while both services run."""
    judge_port, masker_port = _free_port(), _free_port()
    servers = [
        uvicorn.Server(uvicorn.Config(app, host=config.HOST, port=port, log_level="warning"))
        for port, app in services.apps(judge_port, masker_port).items()
    ]
    for server in servers:
        threading.Thread(target=server.run, daemon=True).start()
    deadline = time.time() + 30
    while not all(s.started for s in servers):
        if time.time() > deadline:
            raise RuntimeError("The A2A services didn't start")
        time.sleep(0.05)
    try:
        yield judge_port, masker_port
    finally:
        for server in servers:
            server.should_exit = True
