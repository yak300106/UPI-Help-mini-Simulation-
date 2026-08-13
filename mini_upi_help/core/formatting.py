"""Turns raw tool results into readable sentences for the fast lane,
which skips the LLM entirely and therefore has no one to phrase the
answer in natural language. This does that job with plain string templates.
"""
from __future__ import annotations


def format_result_for_user(tool_name: str, result: dict) -> str:
    if tool_name == "get_answer_from_query":
        chunks = result.get("chunks", [])
        if not chunks:
            return "I don't have information on that topic."
        return " ".join(chunks[:2])

    if tool_name == "get_upi_mapper":
        if not result.get("found"):
            return "I couldn't find your linked UPI details."
        return (f"Your UPI ID is linked to {result.get('app')} "
                f"({result.get('vpa')}) with {result.get('bank')}.")

    if tool_name == "mandate_summary":
        matches = result.get("matches", [])
        if not matches:
            return "No mandates found matching that."
        lines = [f"{m['merchant']} — ₹{m['amount']}" for m in matches]
        return "Here are your matching mandates: " + "; ".join(lines)

    if tool_name in ("get_transaction_details", "search_transactions"):
        matches = result.get("matches", [result] if "txn_id" in result else [])
        if not matches:
            return "No matching transaction found."
        lines = [f"{m['merchant']} (₹{m['amount']}) — {m['status']} on {m['date']}" for m in matches]
        return "Here's what I found: " + "; ".join(lines)

    return str(result)