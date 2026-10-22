"""Settings, read from environment variables (see .env.example)."""

import os
from pathlib import Path

# Any Claude model id the Anthropic API accepts. Haiku is the cheapest that handles this agent well.
MODEL = os.environ.get("SUPPORT_AGENT_MODEL", "claude-haiku-5-5")

DATA_DIR = Path(os.environ.get("SUPPORT_AGENT_DATA", ".data"))
SHOP_DB = DATA_DIR / "shop.db"

# The two A2A services run as separate processes, as they would in production.
HOST = "127.0.0.1"
JUDGE_PORT = int(os.environ.get("JUDGE_PORT", "8101"))
MASKER_PORT = int(os.environ.get("MASKER_PORT", "8102"))

MAX_INPUT_CHARS = 500


def mock_mode() -> bool:
    """Without an API key (or with SUPPORT_AGENT_MOCK=1) every model call is answered by a small local script."""
    return os.environ.get("SUPPORT_AGENT_MOCK") == "1" or not os.environ.get("ANTHROPIC_API_KEY")
