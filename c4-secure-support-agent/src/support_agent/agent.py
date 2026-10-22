"""The core customer-support agent: Claude (or the mock script) plus the shop's MCP tools.

Safe mode applies the fix from the slides: don't load the write tool, and check every tool call in code before it
runs. `--unsafe` turns both off, so you can watch the prompt alone fail to protect the shop.
"""

import re
import sys
from contextlib import closing
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models.llm_request import LlmRequest
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from google.adk.tools.tool_context import ToolContext
from google.genai import types
from mcp import StdioServerParameters

from support_agent import config, shop
from support_agent.models import call, last_tool_result, last_user_text, model_for, text, tool_names, tool_payload

SAFE_TOOLS = ["get-order-status", "find-customer-orders", "action-log"]

INSTRUCTION = """You are the customer-support agent of an online shop. You help the signed-in customer with their
orders: status, items, deliveries, returns and cancellations.

Signed-in customer: {name} <{email}>
What you remember about them from earlier conversations:
{memory}

Rules:
- Never change an order yourself; log a request for a person instead, with action-log.
- Only discuss this customer's own orders.
- Ask the customer to confirm before you log a cancellation, return or change.
- Be brief, friendly and plain. Never show raw JSON or database errors."""


def instruction(ctx: ReadonlyContext) -> str:
    s = ctx.state
    return INSTRUCTION.format(name=s["customer_name"], email=s["customer_email"], memory=s.get("memory") or "(nothing yet)")


def check_tool_call(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext) -> dict | None:
    """Runs before every tool call. Returning a dict skips the tool and hands the dict to the model as its result."""
    email = tool_context.state["customer_email"]
    if tool.name == "update-order-status":
        return {"error": "Order changes need a person. Log a request with action-log instead."}
    if "email" in args and str(args["email"]).lower() != email:
        return {"error": "You can only act for the signed-in customer."}
    if args.get("order_id") is not None:
        with closing(shop.connect(config.SHOP_DB)) as conn:
            owner = shop.owner_of(conn, int(args["order_id"]))
        if owner != email:
            # Same answer as a missing order, so nobody can probe which order numbers exist.
            return {"error": f"Order {args['order_id']} not found"}
    return None


def shop_tools(unsafe: bool) -> McpToolset:
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=sys.executable,
                args=["-m", "support_agent.mcp_server"],
                env={"SHOP_DB": str(config.SHOP_DB.resolve())},
            ),
            timeout=15,
        ),
        tool_filter=None if unsafe else SAFE_TOOLS,
    )


def support_agent(unsafe: bool = False) -> LlmAgent:
    return LlmAgent(
        name="support_agent",
        description="Answers an online shop's customers about their orders.",
        model=model_for(_script),
        instruction=instruction,
        tools=[shop_tools(unsafe)],
        before_tool_callback=None if unsafe else check_tool_call,
    )


# ---------- mock mode: keyword rules standing in for the model ----------

_NUMBERS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten".split())}


def _order_number(message: str) -> int | None:
    m = re.search(r"\border\s*(?:number|no\.?|#)?\s*(\d+|" + "|".join(_NUMBERS) + r")\b", message, re.IGNORECASE)
    if not m:
        return None
    n = m.group(1).lower()
    return int(n) if n.isdigit() else _NUMBERS[n]


def _signed_in_email(req: LlmRequest) -> str:
    m = re.search(r"Signed-in customer: .*<([^>]+)>", str(req.config.system_instruction))
    return m.group(1) if m else ""


def _describe(result: dict) -> str:
    if "error" in result:
        return f"Sorry, I couldn't do that: {result['error']}."
    if "ticket" in result:
        return f"Done: I've logged that for our support team (ticket {result['ticket']}). They'll be in touch."
    if "orders" in result:
        lines = [f"- Order {o['order_id']}: {o['status']}, ${o['total']:.2f}" for o in result["orders"]]
        return "Here are your orders:\n" + "\n".join(lines) if lines else "I can't find any orders for you."
    if "previous_status" in result:
        return f"Order {result['order_id']} is now {result['status']} (it was {result['previous_status']})."
    items = ", ".join(f"{i['quantity']} x {i['product']}" for i in result["items"])
    return (
        f"Order {result['order_id']} is {result['status']}: {items}, ${result['total']:.2f}. "
        f"It ships to {result['shipping_address']}, and updates go to {result['customer_email']}."
    )


def _script(req: LlmRequest) -> types.Part:
    result = last_tool_result(req)
    if result is not None:
        return text(_describe(tool_payload(result.response)))

    message = last_user_text(req)
    order_id = _order_number(message)
    wants_change = re.search(r"\b(cancel|return|exchange|refund|change|move|mark|set)\b", message, re.IGNORECASE)
    if wants_change and order_id is not None:
        if "update-order-status" in tool_names(req) and re.search(r"\b(mark|set|change)\b", message, re.IGNORECASE):
            status = next((s for s in ("cancelled", "delivered", "returned", "shipped") if s[:5] in message.lower()), "cancelled")
            return call("update-order-status", order_id=order_id, status=status)
        action = next((a for a in ("cancel", "return", "exchange", "refund") if a in message.lower()), "change")
        return call("action-log", email=_signed_in_email(req), action=action, note=message, order_id=order_id)
    if order_id is not None:
        return call("get-order-status", order_id=order_id)
    if re.search(r"\b(my orders|orders (have|did) i|list)\b", message, re.IGNORECASE):
        return call("find-customer-orders", email=_signed_in_email(req))
    return text("I can help with your orders, deliveries, returns and cancellations. What do you need?")
