"""
Append-only audit trail.

Every question answered, refund proposed, human decision, and execution
result gets written here as one JSON line — never mutated, never deleted.
Hand this file to someone and they can reconstruct exactly what the agent
told a customer, what it proposed doing with their money, who approved or
denied it, and when.
"""

from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUDIT_LOG_PATH = Path(__file__).parent / "audit_log.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(entry: dict[str, Any]) -> None:
    entry["timestamp"] = _now()
    with AUDIT_LOG_PATH.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def log_faq_answer(run_id: str, question: str, sources: list[str], answer: str) -> None:
    _write({
        "event": "faq_answered",
        "run_id": run_id,
        "question": question,
        "policy_sources": sources,
        "answer": answer,
    })


def log_refund_proposal(run_id: str, order_id: str, args: dict, eligible: bool, justification: str) -> None:
    _write({
        "event": "refund_proposed",
        "run_id": run_id,
        "order_id": order_id,
        "args": args,
        "policy_eligible": eligible,
        "justification": justification,
    })


def log_decision(run_id: str, decision: str, approver: str, note: str = "") -> None:
    _write({
        "event": "decision",
        "run_id": run_id,
        "decision": decision,  # "approved" | "denied"
        "approver": approver,
        "note": note,
    })


def log_execution(run_id: str, result: dict) -> None:
    _write({
        "event": "executed",
        "run_id": run_id,
        "result": result,
    })


def log_error(run_id: str, error: str) -> None:
    _write({"event": "error", "run_id": run_id, "error": error})


def read_trail(run_id: str | None = None) -> list[dict]:
    if not AUDIT_LOG_PATH.exists():
        return []
    entries = [json.loads(line) for line in AUDIT_LOG_PATH.read_text().splitlines() if line.strip()]
    if run_id:
        entries = [e for e in entries if e.get("run_id") == run_id]
    return entries
