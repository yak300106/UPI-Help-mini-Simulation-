"""Core shared types used across the whole framework."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Any


@dataclass
class ToolDefinition:
    """One callable tool the loop can invoke.

    name/description/parameters are what the MODEL sees (so it can decide
    when and how to call this tool). handler is the REAL Python function
    that actually runs when the tool gets called.
    """
    name: str
    description: str
    parameters: dict           # JSON schema, e.g. {"type": "object", "properties": {...}}
    handler: Callable[..., Any]
    domain: str = "general"    # which domain this belongs to: "mandate" / "payment" / "faq"
    risk: str = "safe"         # "safe" = fast-lane eligible | "action" = must go through full reasoning
    terminal: bool = False     # if True, calling this tool ENDS the run (e.g. an "output" tool)


@dataclass
class RunResult:
    """What a completed run returns."""
    answer: str
    reason: str                # "no_tool_calls" | "terminal_tool" | "max_steps" | "hook_blocked" | ...
    steps: int
    pending_intent_id: str | None = None   # set when an action (revoke/pause/unpause) created an
                                             # unconfirmed intent — frontend uses this to show a
                                             # "confirm" button, which calls /api/confirm_intent
    pending_action: str | None = None       # e.g. "revoke", "pause", "unpause" — for display purposes
    pending_merchant: str | None = None     # e.g. "Netflix" — for display purposes