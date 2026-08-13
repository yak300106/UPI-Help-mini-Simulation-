"""Payment domain — transaction status + dispute filing.
Notice: everything here is 'risk=safe' except raising a dispute, which
creates a real record (a mild action, but not irreversible like a mandate
revoke). Good contrast case against the Mandate domain later.
"""
from __future__ import annotations
import uuid
from core.types import ToolDefinition

# ---------------------------------------------------------------------------
# SYNTHETIC DATA
# ---------------------------------------------------------------------------
_TRANSACTIONS = {
    "TXN001": {"txn_id": "TXN001", "amount": 500, "merchant": "Amazon", "status": "SUCCESS", "date": "10-07-2026"},
    "TXN002": {"txn_id": "TXN002", "amount": 1200, "merchant": "Swiggy", "status": "FAILED", "date": "12-07-2026"},
    "TXN003": {"txn_id": "TXN003", "amount": 75, "merchant": "BluSmart", "status": "PENDING", "date": "14-07-2026"},
}

_DISPUTES: dict[str, dict] = {}


def get_transaction_details(txn_id: str) -> dict:
    """Look up one transaction by ID."""
    txn = _TRANSACTIONS.get(txn_id)
    if not txn:
        return {"error": "not found"}
    return txn


def search_transactions(merchant: str = "", status: str = "") -> dict:
    """Find transactions by merchant name and/or status, for when the user doesn't have a txn_id."""
    results = list(_TRANSACTIONS.values())
    if merchant:
        results = [t for t in results if merchant.lower() in t["merchant"].lower()]
    if status:
        results = [t for t in results if t["status"].upper() == status.upper()]
    return {"matches": results}


def raise_dispute(txn_id: str, reason: str) -> dict:
    """File a dispute for a transaction. Creates a real record, so this is 'risk=action',
    even though it's not irreversible the way a mandate revoke is.
    """
    if txn_id not in _TRANSACTIONS:
        return {"error": "cannot dispute unknown transaction"}
    crn = f"CRN-{uuid.uuid4().hex[:8].upper()}"
    _DISPUTES[crn] = {"crn": crn, "txn_id": txn_id, "reason": reason, "status": "OPEN"}
    return {"crn": crn, "status": "OPEN"}


def output(message: str) -> dict:
    return {"message": message}


def build_payment_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="get_transaction_details", domain="payment", risk="safe",
            description="Get the status and details of one transaction by its ID.",
            parameters={"type": "object", "properties": {"txn_id": {"type": "string"}}, "required": ["txn_id"]},
            handler=get_transaction_details,
        ),
        ToolDefinition(
            name="search_transactions", domain="payment", risk="safe",
            description="Search transactions by merchant name and/or status, when the user doesn't have a transaction ID.",
            parameters={"type": "object", "properties": {
                "merchant": {"type": "string"}, "status": {"type": "string"}}, "required": []},
            handler=search_transactions,
        ),
        ToolDefinition(
            name="raise_dispute", domain="payment", risk="action",
            description="File a dispute for a failed or incorrect transaction.",
            parameters={"type": "object", "properties": {
                "txn_id": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["txn_id", "reason"]},
            handler=raise_dispute,
        ),
        ToolDefinition(
            name="payment_output", domain="payment", risk="safe", terminal=True,
            description="Send the final response to the user. Ends the conversation turn.",
            parameters={"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]},
            handler=output,
        ),
    ]