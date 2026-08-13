"""A fake 'model' so you can test the LOOP MECHANICS (hooks blocking,
terminal tools, event logging) without needing any API key yet.

IMPORTANT: this does NOT read the system prompt to reason — it just plays
back a fixed script. It proves the plumbing works. To test whether a REAL
model, given only your prompt, makes the right calls on its own, you need
a real model (we'll add that as a separate file later).
"""
from __future__ import annotations


class ScriptedMockLLM:
    """Plays back one decision per .decide() call, in order."""
    def __init__(self, script: list[dict]):
        self._script = list(script)
        self._i = 0

    def decide(self, messages, tools) -> dict:
        if self._i >= len(self._script):
            return {"final": "(script exhausted — add more steps if needed)"}
        step = self._script[self._i]
        self._i += 1
        return step


# ---------------------------------------------------------------------------
# Pre-built scripts for your test scenarios.
# Each one matches something you already reasoned through by hand earlier.
# ---------------------------------------------------------------------------

def mandate_happy_path_script(mandate_id="M001") -> list[dict]:
    """Cancel Spotify (M001) — fully eligible, should succeed end to end."""
    return [
        {"tool_call": {"name": "mandate_summary", "arguments": {"filter": "Spotify"}}},
        {"tool_call": {"name": "mandate_fetch", "arguments": {"mandate_id": mandate_id}}},
        {"tool_call": {"name": "mandate_revoke", "arguments": {"mandate_id": mandate_id}}},
        {"tool_call": {"name": "output", "arguments": {
            "message": f"Your Spotify mandate cancellation is ready — tap here to confirm: "
                       f"[Intent_Link:true]upi://confirm/revoke/{mandate_id}"}}},
    ]


def mandate_skip_fetch_script(mandate_id="M002") -> list[dict]:
    """Model 'forgets' to fetch before acting — should be blocked by the hook."""
    return [
        {"tool_call": {"name": "mandate_revoke", "arguments": {"mandate_id": mandate_id}}},
    ]


def mandate_ineligible_script(mandate_id="M002") -> list[dict]:
    """M002 (Netflix) has is_revoke=False — should be blocked after a proper fetch."""
    return [
        {"tool_call": {"name": "mandate_fetch", "arguments": {"mandate_id": mandate_id}}},
        {"tool_call": {"name": "mandate_revoke", "arguments": {"mandate_id": mandate_id}}},
    ]


def payment_status_check_script(txn_id="TXN002") -> list[dict]:
    """Simple payment status lookup — no hooks involved, should just work."""
    return [
        {"tool_call": {"name": "get_transaction_details", "arguments": {"txn_id": txn_id}}},
        {"tool_call": {"name": "output", "arguments": {
            "message": "Your Swiggy transaction of ₹1200 failed on 12-07-2026."}}},
    ]


def faq_query_script() -> list[dict]:
    """A basic FAQ lookup, using the keyword-overlap retrieval tool."""
    return [
        {"tool_call": {"name": "get_answer_from_query", "arguments": {"query": "what is the UPI transaction limit"}}},
        {"tool_call": {"name": "output", "arguments": {
            "message": "The default UPI transaction limit is ₹1 lakh per transaction for most banks."}}},
    ]