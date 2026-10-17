"""
Customer Support Agent — Policy RAG + Human-Gated Refunds
============================================================

One agent, two behaviors, split by what's actually at stake:

  - General questions (shipping, returns process, policy) are answered
    directly from a small knowledge base via retrieval. No approval
    needed — this is the "operate autonomously within its lane" half.

  - Refund requests are different: the agent looks up the real order,
    checks it against policy, drafts the specific action with its own
    justification — then always stops and asks a human before anything
    executes. Money never moves without a person saying yes.

Every question answered and every refund proposed/decided/executed is
logged to audit_log.jsonl with a shared run_id.

Usage:
    export GEMINI_API_KEY=your_key_here      # optional — omit for dry-run demo
    python agent.py "what's your return window?"
    python agent.py "order A-1029 arrived broken, I want a refund"
    python agent.py --show-trail
"""

from __future__ import annotations
import json
import os
import re
import sys
import uuid

from pydantic import ValidationError

import audit
import retriever
from tools import RefundRequestArgs, OrderNotFound, load_order, assess_eligibility, execute_refund


class NeedsApprovalException(Exception):
    def __init__(self, order, eligible, justification):
        self.order = order
        self.eligible = eligible
        self.justification = justification

# Added for web integration
_customer_handler = print
_internal_handler = print

def set_output_handlers(customer_handler, internal_handler):
    global _customer_handler, _internal_handler
    _customer_handler = customer_handler
    _internal_handler = internal_handler

def emit_customer(msg):
    _customer_handler(msg)

def emit_internal_log(msg):
    _internal_handler(msg)


# ---------------------------------------------------------------------------
# Intent routing
# ---------------------------------------------------------------------------

GEMINI_TOOL_DECLARATIONS = [
    {
        "name": "answer_general_question",
        "description": "Answer a general question about shipping, returns, or policy that is not tied to a specific order refund.",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
    {
        "name": "request_refund",
        "description": "Handle a request to refund a specific order.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The order ID mentioned by the customer"},
                "reason": {"type": "string", "description": "Why the customer wants a refund, in their words"},
            },
            "required": ["order_id", "reason"],
        },
    },
]

REFUND_HINTS = re.compile(r"\brefund|money back|charge ?back|reimburse\b", re.IGNORECASE)
ORDER_ID_PATTERN = re.compile(r"\b([A-Za-z]-?\d{2,})\b")


def classify_via_gemini(message: str) -> tuple[str, dict]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    tool = types.Tool(function_declarations=GEMINI_TOOL_DECLARATIONS)
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=message,
        config=types.GenerateContentConfig(
            tools=[tool],
            system_instruction=(
                "You are a customer support intent router. If the customer is asking "
                "a general question, call answer_general_question. If they are asking "
                "for a refund tied to a specific order, call request_refund with the "
                "order id and their stated reason. Always pick exactly one."
            ),
        ),
    )
    call = response.candidates[0].content.parts[0].function_call
    if call is None:
        return "answer_general_question", {"question": message}
    return call.name, dict(call.args)


def classify_rule_based(message: str) -> tuple[str, dict]:
    if REFUND_HINTS.search(message):
        order_match = ORDER_ID_PATTERN.search(message)
        return "request_refund", {
            "order_id": order_match.group(1) if order_match else "",
            "reason": message,
        }
    return "answer_general_question", {"question": message}


def classify(message: str) -> tuple[str, dict]:
    if os.environ.get("GEMINI_API_KEY"):
        return classify_via_gemini(message)
    emit_internal_log("[dry-run mode: no GEMINI_API_KEY set — using rule-based router]\n")
    return classify_rule_based(message)


# ---------------------------------------------------------------------------
# FAQ path — retrieval, no side effects, no approval
# ---------------------------------------------------------------------------

def answer_faq(run_id: str, question: str) -> None:
    chunks = retriever.retrieve(question, top_k=3)

    if not chunks:
        answer = "I don't have policy information covering that — let me get a human to help."
        audit.log_faq_answer(run_id, question, [], answer)
        emit_customer(answer)
        return

    sources = [c.source for c in chunks]

    if os.environ.get("GEMINI_API_KEY"):
        answer = _synthesize_answer_via_gemini(question, chunks)
    else:
        answer = "\n\n".join(f"{c.text}" for c in chunks)

    audit.log_faq_answer(run_id, question, sources, answer)
    emit_customer(answer)


def _synthesize_answer_via_gemini(question: str, chunks: list) -> str:
    from google import genai

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    context = "\n\n".join(f"[{c.source}]\n{c.text}" for c in chunks)
    prompt = (
        f"Using ONLY the policy context below, answer the customer's question in "
        f"2-3 sentences. If the context doesn't fully answer it, say what's missing.\n\n"
        f"Context:\n{context}\n\nQuestion: {question}"
    )
    response = client.models.generate_content(model="gemini-3.6-flash", contents=prompt)
    return response.text.strip()


# ---------------------------------------------------------------------------
# Refund path — order lookup, policy eligibility check, human gate, execute
# ---------------------------------------------------------------------------

def request_human_approval(order: dict, eligible: bool, justification: str) -> tuple[bool, str]:
    emit_internal_log("=" * 60)
    emit_internal_log("REFUND APPROVAL REQUIRED")
    emit_internal_log("=" * 60)
    emit_internal_log(f"Order:          {order['order_id']} ({order['item']})")
    emit_internal_log(f"Customer:       {order['customer_email']}")
    emit_internal_log(f"Amount:         ${order['amount_usd']:.2f}")
    emit_internal_log(f"Order date:     {order['order_date']}")
    emit_internal_log(f"Policy check:   {'ELIGIBLE' if eligible else 'NOT CLEARLY ELIGIBLE'}")
    emit_internal_log(f"Justification:  {justification}")
    emit_internal_log("-" * 60)
    raise NeedsApprovalException(order, eligible, justification)


def handle_refund_request(run_id: str, raw_args: dict) -> None:
    try:
        validated = RefundRequestArgs(**raw_args)
    except ValidationError as e:
        msg = f"Couldn't understand the refund request: {e}"
        emit_internal_log(msg)
        audit.log_error(run_id, msg)
        return

    try:
        order = load_order(validated.order_id)
    except OrderNotFound as e:
        emit_internal_log(str(e))
        audit.log_error(run_id, str(e))
        return

    eligible, justification = assess_eligibility(order, validated.reason)
    audit.log_refund_proposal(
        run_id, order["order_id"],
        {"order_id": order["order_id"], "reason": validated.reason, "amount_usd": order["amount_usd"]},
        eligible, justification,
    )

    # Refunds always require a human — this is the whole point of the demo.
    request_human_approval(order, eligible, justification)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(message: str) -> None:
    run_id = str(uuid.uuid4())[:8]
    emit_internal_log(f"\nRun ID: {run_id}")
    emit_internal_log(f"Message: {message}\n")

    intent, args = classify(message)

    if intent == "request_refund":
        if not args.get("order_id"):
            emit_customer("This sounds like a refund request, but I couldn't find an order ID — "
                  "could you share the order number?")
            emit_internal_log("Refund intent detected but no order_id extracted.")
            return
        handle_refund_request(run_id, args)
    else:
        answer_faq(run_id, args.get("question", message))


def show_trail() -> None:
    entries = audit.read_trail()
    if not entries:
        emit_internal_log("No audit entries yet. Run a message through the agent first.")
        return
    for e in entries:
        emit_internal_log(json.dumps(e, indent=2))
        emit_internal_log("-" * 40)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        emit_internal_log(__doc__)
        sys.exit(1)

    if sys.argv[1] == "--show-trail":
        show_trail()
    else:
        run(" ".join(sys.argv[1:]))
