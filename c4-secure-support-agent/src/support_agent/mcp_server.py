"""The shop's MCP server: the four order tools the support agent can load.

Run on its own with `python -m support_agent.mcp_server` (stdio). The agent starts it for you.
The tools trust their arguments, like many real internal APIs do; deciding who may call what is the agent's job.
"""

import os
from contextlib import contextmanager
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from support_agent import shop

DB_PATH = Path(os.environ.get("SHOP_DB", ".data/shop.db"))

server = MCPServer("shop", instructions="Order tools for the online shop's customer support.")


@contextmanager
def db():
    conn = shop.connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


@server.tool(name="get-order-status")
def get_order_status(order_id: int) -> dict:
    """Get one order's status, items, total, date and shipping details."""
    with db() as conn:
        return shop.order(conn, order_id) or {"error": f"Order {order_id} not found"}


@server.tool(name="find-customer-orders")
def find_customer_orders(email: str) -> dict:
    """List every order placed by the customer with this email address."""
    with db() as conn:
        return {"email": email, "orders": shop.customer_orders(conn, email)}


@server.tool(name="action-log")
def action_log(email: str, action: str, note: str, order_id: int | None = None) -> dict:
    """Log a request (cancel, return, address change, ...) for a person on the support team to handle."""
    with db() as conn:
        ticket = shop.log_action(conn, email, action, note, order_id)
    return {"ticket": ticket, "status": "logged for the support team"}


@server.tool(name="update-order-status")
def update_order_status(order_id: int, status: str) -> dict:
    """Change an order's status directly (processing, shipped, delivered, cancelled, returned)."""
    with db() as conn:
        return shop.update_status(conn, order_id, status)


if __name__ == "__main__":
    server.run("stdio")
