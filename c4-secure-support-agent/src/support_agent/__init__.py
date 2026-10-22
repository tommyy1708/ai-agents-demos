"""Week 4 demo: a secure customer-support agent with ADK, MCP and A2A."""

import warnings

# ADK marks its A2A integration as experimental and warns on every call; the README says so once instead.
warnings.filterwarnings("ignore", message=r"\[EXPERIMENTAL\]", category=UserWarning)
