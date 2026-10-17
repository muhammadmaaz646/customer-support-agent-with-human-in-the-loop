"""
Everything to do with the one gated action this agent can take: refunds.

FAQ answers never touch this file — they're pure retrieval + generation,
no side effects, no approval needed. The moment money is involved, it
routes through here, and everything here ends at a human, not an executor
running unattended.
"""

from __future__ import annotations
import json
from datetime import date, datetime
from pathlib import Path
from pydantic import BaseModel, Field

ORDERS_PATH = Path(__file__).parent / "orders.json"
RETURN_WINDOW_DAYS = 30


class RefundRequestArgs(BaseModel):
    order_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=500)


class OrderNotFound(Exception):
    pass


def load_order(order_id: str) -> dict:
    orders = json.loads(ORDERS_PATH.read_text())
    order = orders.get(order_id.upper())
    if order is None:
        raise OrderNotFound(f"No order found with id '{order_id}'.")
    return {**order, "order_id": order_id.upper()}


def _days_since(order_date_str: str) -> int:
    order_dt = datetime.strptime(order_date_str, "%Y-%m-%d").date()
    return (date.today() - order_dt).days


def assess_eligibility(order: dict, reason: str) -> tuple[bool, str]:
    """
    Mirrors refund_policy.md / return_policy.md in code, so the agent's
    decision and the policy doc it cites always agree. This is the part
    a real system would keep in sync with the KB (or derive from it) —
    here it's explicit so the logic is easy to audit and change.
    """
    reason_lower = reason.lower()
    is_damage_or_error = any(w in reason_lower for w in
                              ["damaged", "defective", "broken", "wrong item", "arrived incorrect"])

    if is_damage_or_error:
        return True, (
            "Item reported as damaged/defective/wrong item — eligible for a full "
            "refund regardless of the return window, per refund policy."
        )

    days_old = _days_since(order["order_date"])
    if days_old <= RETURN_WINDOW_DAYS:
        return True, (
            f"Order is {days_old} days old, within the {RETURN_WINDOW_DAYS}-day "
            f"return window — eligible per return policy."
        )

    return False, (
        f"Order is {days_old} days old, outside the {RETURN_WINDOW_DAYS}-day "
        f"return window, and reason given doesn't indicate damage/defect/our error. "
        f"Not covered by policy — requires manager discretion."
    )


def execute_refund(order: dict) -> dict:
    """Simulated executor. Swap for a real payment-processor call."""
    return {
        "status": "refunded",
        "order_id": order["order_id"],
        "amount_usd": order["amount_usd"],
        "transaction_id": f"sim-{abs(hash(order['order_id'])) % 10**8}",
    }
