"""Mandate domain — now backed by a real SQLite database instead of a dict.
Two-step action flow: an action tool (revoke/pause/unpause) creates a
PENDING intent (matches how UPI really works — the link isn't the completed
transaction). A separate confirm step, simulating the user tapping the
link, actually applies the change to the mandate's real stored status.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from core.types import ToolDefinition
from db.schema import get_connection

# Tracks the last mandate_fetch result per mandate_id, so the safety hook can check it.
# Still needed in-memory because it's about "what happened THIS conversation",
# not stored data — separate concern from the database itself.
LAST_FETCHED: dict[str, dict] = {}


def _row_to_dict(row) -> dict:
    return {k: row[k] for k in row.keys()}


def mandate_summary(filter: str = "") -> dict:
    """List mandates, optionally filtered by merchant name. Reads real DB rows now."""
    conn = get_connection()
    if filter:
        rows = conn.execute(
            "SELECT * FROM mandates WHERE merchant LIKE ? AND status != 'REVOKED'",
            (f"%{filter}%",),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM mandates WHERE status != 'REVOKED'").fetchall()
    conn.close()

    matches = [
        {"mandate_id": r["mandate_id"], "merchant": r["merchant"], "amount": r["amount"],
         "status": r["status"], "frequency": r["frequency"]}
        for r in rows
    ]
    return {"matches": matches}


def mandate_fetch(mandate_id: str) -> dict:
    """Get one mandate's current details. UMN is never exposed in the returned dict."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM mandates WHERE mandate_id = ?", (mandate_id,)).fetchone()
    conn.close()
    if row is None:
        return {"error": "not found"}

    full = _row_to_dict(row)
    LAST_FETCHED[mandate_id] = full  # hook checks this, including the real is_revoke/is_pause flags
    safe = {k: v for k, v in full.items() if k != "umn"}
    return safe


def _create_pending_intent(mandate_id: str, action: str, till_date: str | None = None) -> dict:
    intent_id = f"INTENT-{uuid.uuid4().hex[:10].upper()}"
    conn = get_connection()
    conn.execute(
        "INSERT INTO pending_intents (intent_id, mandate_id, action, till_date, created_at, confirmed) "
        "VALUES (?,?,?,?,?,0)",
        (intent_id, mandate_id, action, till_date, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    return {"mandate_id": mandate_id, "intent_id": intent_id,
            "intent_link": f"upi://confirm/{action}/{intent_id}"}


def mandate_revoke(mandate_id: str) -> dict:
    return _create_pending_intent(mandate_id, "revoke")


def mandate_pause(mandate_id: str, till_date: str) -> dict:
    return _create_pending_intent(mandate_id, "pause", till_date=till_date)


def mandate_unpause(mandate_id: str) -> dict:
    return _create_pending_intent(mandate_id, "unpause")


def confirm_intent(intent_id: str) -> dict:
    """Simulates the user tapping the UPI intent link. THIS is where the
    database actually changes — everything before this point was just
    preparation. Mirrors the real system: the intent link is not the
    completed transaction, tapping it is.
    """
    conn = get_connection()
    intent = conn.execute(
        "SELECT * FROM pending_intents WHERE intent_id = ?", (intent_id,)
    ).fetchone()
    if intent is None:
        conn.close()
        return {"error": "intent not found or already used"}
    if intent["confirmed"]:
        conn.close()
        return {"error": "this intent was already confirmed"}

    action = intent["action"]
    mandate_id = intent["mandate_id"]

    if action == "revoke":
        conn.execute("UPDATE mandates SET status = 'REVOKED' WHERE mandate_id = ?", (mandate_id,))
    elif action == "pause":
        conn.execute(
            "UPDATE mandates SET status = 'PAUSED', paused_until = ? WHERE mandate_id = ?",
            (intent["till_date"], mandate_id),
        )
    elif action == "unpause":
        conn.execute("UPDATE mandates SET status = 'ACTIVE', paused_until = NULL WHERE mandate_id = ?", (mandate_id,))

    conn.execute("UPDATE pending_intents SET confirmed = 1 WHERE intent_id = ?", (intent_id,))
    conn.commit()

    updated = conn.execute("SELECT * FROM mandates WHERE mandate_id = ?", (mandate_id,)).fetchone()
    conn.close()

    return {"confirmed": True, "action": action, "mandate": _row_to_dict(updated)}


def calculator(expression: str) -> dict:
    import ast, operator
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
    def _eval(node):
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](_eval(node.left), _eval(node.right))
        raise ValueError("unsupported expression")
    tree = ast.parse(expression, mode="eval")
    return {"expression": expression, "result": _eval(tree.body)}


def output(message: str) -> dict:
    return {"message": message}


def build_mandate_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="mandate_summary", domain="mandate", risk="safe",
            description="List mandates, optionally filtered by merchant name.",
            parameters={"type": "object", "properties": {"filter": {"type": "string"}}, "required": []},
            handler=mandate_summary,
        ),
        ToolDefinition(
            name="mandate_fetch", domain="mandate", risk="safe",
            description="Get one mandate's current details by mandate_id. Required before any action.",
            parameters={"type": "object", "properties": {"mandate_id": {"type": "string"}}, "required": ["mandate_id"]},
            handler=mandate_fetch,
        ),
        ToolDefinition(
            name="mandate_revoke", domain="mandate", risk="action",
            description="Cancel a mandate permanently. Requires mandate_fetch first. Returns an intent link, not a completed action.",
            parameters={"type": "object", "properties": {"mandate_id": {"type": "string"}}, "required": ["mandate_id"]},
            handler=mandate_revoke,
        ),
        ToolDefinition(
            name="mandate_pause", domain="mandate", risk="action",
            description="Pause a mandate until a given date (DD-MM-YYYY). Requires mandate_fetch first.",
            parameters={"type": "object", "properties": {
                "mandate_id": {"type": "string"}, "till_date": {"type": "string"}},
                "required": ["mandate_id", "till_date"]},
            handler=mandate_pause,
        ),
        ToolDefinition(
            name="mandate_unpause", domain="mandate", risk="action",
            description="Resume a paused mandate. Requires mandate_fetch first.",
            parameters={"type": "object", "properties": {"mandate_id": {"type": "string"}}, "required": ["mandate_id"]},
            handler=mandate_unpause,
        ),
        ToolDefinition(
            name="confirm_intent", domain="mandate", risk="action",
            description="Confirm a pending mandate action by intent_id, simulating the user tapping the UPI link. This is what actually applies the change.",
            parameters={"type": "object", "properties": {"intent_id": {"type": "string"}}, "required": ["intent_id"]},
            handler=confirm_intent,
        ),
        ToolDefinition(
            name="calculator", domain="mandate", risk="safe",
            description="Evaluate a math expression, e.g. total amount across mandates.",
            parameters={"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]},
            handler=calculator,
        ),
        ToolDefinition(
            name="mandate_output", domain="mandate", risk="safe", terminal=True,
            description="Send the final response to the user. Ends the conversation turn.",
            parameters={"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]},
            handler=output,
        ),
    ]


def mandate_eligibility_hook(tool_name: str, arguments: dict) -> tuple[bool, dict, str | None]:
    """Same as before: check the eligibility flag AND that fetch happened first —
    now checking the REAL flags read from the database, not a hardcoded dict.
    """
    action_tools = {"mandate_pause": "is_pause", "mandate_revoke": "is_revoke", "mandate_unpause": "is_unpause"}
    if tool_name not in action_tools:
        return True, arguments, None

    mandate_id = arguments.get("mandate_id")
    mandate = LAST_FETCHED.get(mandate_id)
    if mandate is None:
        return False, arguments, "You need to fetch this mandate's details before acting on it."

    flag_name = action_tools[tool_name]
    if not mandate.get(flag_name, False):
        action_word = tool_name.split("_")[1]
        return False, arguments, f"This mandate cannot be {action_word}d right now."
    return True, arguments, None

_ACTION_KEYWORDS = {
    "cancel": "mandate_revoke", "revoke": "mandate_revoke",
    "pause": "mandate_pause", "stop": "mandate_pause",
    "unpause": "mandate_unpause", "resume": "mandate_unpause",
}


def _detect_action_tool(user_message: str) -> str | None:
    msg = user_message.lower()
    for keyword, tool_name in _ACTION_KEYWORDS.items():
        if keyword in msg:
            return tool_name
    return None


def _guess_merchant(user_message: str) -> str:
    """Check the user's own words against real merchant names in the DB —
    deterministic, doesn't rely on the model extracting this correctly.
    """
    conn = get_connection()
    merchants = [r["merchant"] for r in conn.execute("SELECT DISTINCT merchant FROM mandates").fetchall()]
    conn.close()
    msg_lower = user_message.lower()
    for m in merchants:
        if m.lower() in msg_lower:
            return m
    return ""


def try_deterministic_mandate_action(user_message: str, hooks) -> dict | None:
    """Handles 'cancel/pause/unpause my X mandate' WITHOUT the LLM at all.
    Returns None if this doesn't look like an action request (falls back to
    normal reasoning). Otherwise returns a dict describing exactly what
    happened: resolved (single match, action done), ambiguous (needs cards),
    or blocked (hook stopped it).
    """
    action_tool_name = _detect_action_tool(user_message)
    if action_tool_name is None:
        return None

    merchant_guess = _guess_merchant(user_message)
    summary = mandate_summary(filter=merchant_guess)
    matches = summary.get("matches", [])

    if len(matches) == 0:
        return None  # nothing matched — let normal reasoning try instead

    if len(matches) > 1:
        return {"status": "ambiguous", "candidates": matches, "action_tool": action_tool_name}

    mandate_id = matches[0]["mandate_id"]
    mandate_fetch(mandate_id)  # populates LAST_FETCHED for the hook to check

    action_args = {"mandate_id": mandate_id}
    if action_tool_name == "mandate_pause":
        action_args["till_date"] = "31-12-2026"

    allowed, action_args, block_reason = hooks.run(action_tool_name, action_args)
    if not allowed:
        return {"status": "blocked", "reason": block_reason}

    action_fn = {"mandate_revoke": mandate_revoke,
                 "mandate_pause": mandate_pause,
                 "mandate_unpause": mandate_unpause}[action_tool_name]
    result = action_fn(**action_args)
    return {"status": "resolved", "result": result, "merchant": matches[0]["merchant"],
            "action_word": action_tool_name.split("_")[1]}