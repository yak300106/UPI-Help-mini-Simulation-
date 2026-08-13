"""Dispute domain — UDIR-style complaint filing with automatic evidence
bundling from the current conversation, plus a downloadable receipt.

Key idea: instead of asking the user to re-supply a transaction reference
number, gather_evidence_from_session() scans the SESSION's own message
history (which already stores every tool result from earlier in this
conversation) and pulls out whatever transaction/mandate details are
already there.
"""
from __future__ import annotations
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from core.types import ToolDefinition
from db.schema import get_connection

RECEIPTS_DIR = Path(__file__).parent.parent / "receipts"
RECEIPTS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Evidence gathering — the new mechanism
# ---------------------------------------------------------------------------

def gather_evidence_from_session(session) -> dict:
    """Scan the session's message history for the most recent transaction or
    mandate details already surfaced in this conversation. Returns whatever
    it finds — may be empty if nothing relevant has come up yet.
    """
    evidence = {}
    if session is None:
        return evidence

    for msg in reversed(session.messages):
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        if "txn_id" in content and "txn_id" not in evidence:
            txn_match = re.search(r"'txn_id':\s*'([^']+)'", content)
            merchant_match = re.search(r"'merchant':\s*'([^']+)'", content)
            amount_match = re.search(r"'amount':\s*(\d+)", content)
            status_match = re.search(r"'status':\s*'([^']+)'", content)
            date_match = re.search(r"'date':\s*'([^']+)'", content)
            if txn_match:
                evidence["txn_id"] = txn_match.group(1)
                evidence["merchant"] = merchant_match.group(1) if merchant_match else ""
                evidence["amount"] = amount_match.group(1) if amount_match else ""
                evidence["txn_status"] = status_match.group(1) if status_match else ""
                evidence["date"] = date_match.group(1) if date_match else ""
        if "mandate_id" in content and "mandate_id" not in evidence:
            mandate_match = re.search(r"'mandate_id':\s*'([^']+)'", content)
            if mandate_match:
                evidence["mandate_id"] = mandate_match.group(1)
        if evidence:
            break

    return evidence

def find_last_dispute_id_in_session(session) -> str | None:
    """Scan session history for the most recent dispute ID mentioned —
    so the user doesn't have to remember/retype it after just filing one.
    """
    if session is None:
        return None
    for msg in reversed(session.messages):
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        match = re.search(r"DSP-[A-F0-9]{8}", content)
        if match:
            return match.group(0)
    return None

# ---------------------------------------------------------------------------
# Receipt generation
# ---------------------------------------------------------------------------

def generate_receipt_pdf(dispute_id: str, reason: str, status: str, evidence: dict, created_at: str) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    path = RECEIPTS_DIR / f"{dispute_id}.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    y = height - 60

    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, "UPI DISPUTE RECEIPT")
    y -= 30

    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"Dispute ID: {dispute_id}")
    y -= 16
    c.drawString(50, y, f"Filed: {created_at}")
    y -= 30

    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Transaction / Mandate Details")
    y -= 20
    c.setFont("Helvetica", 10)
    for label, key in [("Reference", "txn_id"), ("Mandate ID", "mandate_id"),
                        ("Merchant", "merchant"), ("Amount", "amount"),
                        ("Status", "txn_status"), ("Date", "date")]:
        if evidence.get(key):
            value = evidence[key]
            if key == "amount":
                value = f"Rs. {value}"
            c.drawString(60, y, f"{label}: {value}")
            y -= 16

    y -= 14
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Dispute")
    y -= 20
    c.setFont("Helvetica", 10)
    c.drawString(60, y, f"Status: {status}")
    y -= 16
    c.drawString(60, y, f"Reason: {reason}")
    y -= 30

    c.setFont("Helvetica-Oblique", 9)
    c.drawString(50, y, "Keep this reference for tracking your complaint.")

    c.save()
    return path


# ---------------------------------------------------------------------------
# Core tools
# ---------------------------------------------------------------------------

def raise_dispute_with_evidence(reason: str, txn_id: str = "", mandate_id: str = "",
                                  merchant: str = "", amount: str = "",
                                  txn_status: str = "", date: str = "") -> dict:
    """File a dispute. Evidence fields are optional individually, but the
    hook (dispute_evidence_hook) requires at least ONE of txn_id/mandate_id
    to be present before this ever runs.
    """
    dispute_id = f"DSP-{uuid.uuid4().hex[:8].upper()}"
    created_at = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    evidence = {"txn_id": txn_id, "mandate_id": mandate_id, "merchant": merchant,
                "amount": amount, "txn_status": txn_status, "date": date}
    evidence = {k: v for k, v in evidence.items() if v}

    conn = get_connection()
    conn.execute(
        "INSERT INTO disputes (dispute_id, txn_id, mandate_id, reason, status, evidence, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (dispute_id, txn_id or None, mandate_id or None, reason, "OPEN",
         json.dumps(evidence), created_at),
    )
    conn.commit()
    conn.close()

    receipt_path = generate_receipt_pdf(dispute_id, reason, "OPEN", evidence, created_at)

    return {
        "dispute_id": dispute_id, "status": "OPEN", "reason": reason,
        "evidence": evidence, "created_at": created_at,
        "receipt_url": f"/api/receipt/{dispute_id}",
    }


def check_dispute_status(dispute_id: str) -> dict:
    conn = get_connection()
    row = conn.execute("SELECT * FROM disputes WHERE dispute_id = ?", (dispute_id,)).fetchone()
    conn.close()
    if row is None:
        return {"error": "dispute not found"}
    return {
        "dispute_id": row["dispute_id"], "status": row["status"], "reason": row["reason"],
        "created_at": row["created_at"], "receipt_url": f"/api/receipt/{row['dispute_id']}",
    }


def dispute_output(message: str) -> dict:
    return {"message": message}


def build_dispute_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="raise_dispute_with_evidence", domain="dispute", risk="action",
            description="File a UPI dispute, automatically attaching transaction/mandate evidence already known from this conversation.",
            parameters={
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                    "txn_id": {"type": "string"}, "mandate_id": {"type": "string"},
                    "merchant": {"type": "string"}, "amount": {"type": "string"},
                    "txn_status": {"type": "string"}, "date": {"type": "string"},
                },
                "required": ["reason"],
            },
            handler=raise_dispute_with_evidence,
        ),
        ToolDefinition(
            name="check_dispute_status", domain="dispute", risk="safe",
            description="Look up the status of a previously filed dispute by its dispute_id.",
            parameters={"type": "object", "properties": {"dispute_id": {"type": "string"}}, "required": ["dispute_id"]},
            handler=check_dispute_status,
        ),
        ToolDefinition(
            name="dispute_output", domain="dispute", risk="safe", terminal=True,
            description="Send the final response to the user. Ends the conversation turn.",
            parameters={"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]},
            handler=dispute_output,
        ),
    ]


# ---------------------------------------------------------------------------
# Hook — bucket 2, deterministic: never file a dispute with zero evidence
# ---------------------------------------------------------------------------

def dispute_evidence_hook(tool_name: str, arguments: dict) -> tuple[bool, dict, str | None]:
    if tool_name != "raise_dispute_with_evidence":
        return True, arguments, None
    if not arguments.get("txn_id") and not arguments.get("mandate_id"):
        return False, arguments, "A dispute needs at least a transaction or mandate reference attached before it can be filed."
    return True, arguments, None