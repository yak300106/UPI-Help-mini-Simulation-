"""The Router — decides which domain a query belongs to, and whether it's
simple enough to skip straight to a tool (fast lane) or needs full agent
reasoning (slow lane).

NOTE: domain classification here is simple keyword matching, not a real LLM
call. This proves the MECHANISM. Swap in a real model later (see llm/) —
nothing else in the router needs to change when you do.
"""
from __future__ import annotations
from dataclasses import dataclass
from tools.registry import ToolRegistry
from core.session import Session
from domains.mandate_tools import build_mandate_tools
from domains.payment_tools import build_payment_tools
from domains.faq_tools import build_faq_tools
from domains.dispute_tools import build_dispute_tools

# Keyword hints per domain — crude, but enough to prove domain routing works
_DOMAIN_KEYWORDS = {
    "mandate": ["mandate", "autopay", "auto-pay", "subscription", "pause", "revoke",
                "cancel", "unpause", "resume", "recurring"],
    "payment": ["transaction", "payment", "txn", "failed", "pending", "refund", "money"],
    "dispute": ["dispute", "complaint", "complain", "file a complaint", "raise a dispute"],
    "faq": ["what is", "how to", "how do i", "register", "limit", "explain", "upi lite"],
}


@dataclass
class RouteDecision:
    domain: str
    registry: ToolRegistry
    fast_lane_eligible: bool
    fast_lane_tool: str | None
    reason: str


def build_full_registry() -> ToolRegistry:
    """All tools from all domains, combined — this is the 'full toolkit' the
    Router filters DOWN from, matching how one AgentLoop gets reconfigured
    per turn instead of needing separate agents.
    """
    registry = ToolRegistry()
    for tool in build_mandate_tools() + build_payment_tools() + build_faq_tools():
        registry.register(tool)
    return registry

def build_full_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool in build_mandate_tools() + build_payment_tools() + build_faq_tools() + build_dispute_tools():
        registry.register(tool)
    return registry

def classify_domain(query: str, session: Session) -> tuple[str, str]:
    """Returns (domain, reason). Checks session first — if there's a pending
    task (e.g. ambiguous mandate match awaiting clarification), skip
    classification entirely and stay in that domain.
    """
    if session.has_pending_task():
        return session.pending_domain, "resumed from pending session state"

    query_lower = query.lower()
    scores = {}
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        scores[domain] = sum(1 for kw in keywords if kw in query_lower)

    best_domain = max(scores, key=scores.get)
    if scores[best_domain] == 0:
        return "faq", "no keyword match, defaulting to FAQ"
    return best_domain, f"matched keywords for '{best_domain}'"


# Per-tool keyword hints — crude, matches your domain-level approach.
# Maps: tool_name -> keywords that suggest THIS tool specifically applies.
_FAST_LANE_TOOL_HINTS = {
    "get_answer_from_query": ["what is", "how", "explain", "limit", "define"],
    "get_upi_mapper": ["my upi", "my vpa", "my linked", "my app"],
    "get_transaction_details": ["txn", "transaction id"],
    "search_transactions": [],  # needs merchant/status context, keep in slow lane
    "mandate_summary": ["list", "show", "my mandates"],
    "calculator": ["total", "sum", "add up"],
}


def decide_fast_lane(query: str, registry: ToolRegistry) -> tuple[bool, str, str | None]:
    """Fast lane = query clearly, unambiguously matches exactly ONE safe tool's
    keyword hints. If zero or 2+ tools match, fall back to the slow lane.
    Deliberately conservative: when in doubt, slow lane.
    """
    safe_tools = [t for t in registry.all() if t.risk == "safe" and not t.terminal]
    if not safe_tools:
        return False, "no safe tools available in this domain", None

    query_lower = query.lower()
    matched = []
    for tool in safe_tools:
        hints = _FAST_LANE_TOOL_HINTS.get(tool.name, [])
        if any(h in query_lower for h in hints):
            matched.append(tool)

    word_count = len(query.split())
    if word_count <= 6 and len(matched) == 1:
        tool = matched[0]
        return True, f"short query, clearly matches safe tool '{tool.name}'", tool.name

    if len(matched) == 0:
        return False, "no safe tool clearly matched", None
    return False, f"ambiguous — {len(matched)} safe tools could match", None


def route(query: str, session: Session) -> RouteDecision:
    """The single entry point run_demo.py will call."""
    full_registry = build_full_registry()
    domain, reason = classify_domain(query, session)
    domain_registry = full_registry.filter_by_domain(domain)
    fast_eligible, fast_reason, fast_tool = decide_fast_lane(query, domain_registry)
    return RouteDecision(
        domain=domain,
        registry=domain_registry,
        fast_lane_eligible=fast_eligible,
        fast_lane_tool=fast_tool,
        reason=f"{reason}; fast_lane={fast_eligible} ({fast_reason})",
    )