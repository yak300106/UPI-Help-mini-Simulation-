"""OCR-based evidence extraction from uploaded screenshots.
Same regex philosophy as gather_evidence_from_session — just reading OCR
text instead of stored conversation messages.
"""
from __future__ import annotations
import re
import pytesseract
from PIL import Image
import shutil
_tess_path = shutil.which("tesseract") or "/usr/local/bin/tesseract"
pytesseract.pytesseract.tesseract_cmd = _tess_path
from pathlib import Path


def extract_evidence_from_image(image_path: Path) -> dict:
    """Run OCR on an uploaded screenshot and pull out transaction-shaped fields."""
    img = Image.open(image_path)
    img.thumbnail((900, 900))
    raw_text = pytesseract.image_to_string(img)
    evidence = {}

    txn_match = re.search(r'\bTXN\d{3,}\b', raw_text, re.IGNORECASE)
    if txn_match:
        evidence["txn_id"] = txn_match.group(0).upper()

    amount_match = re.search(r'[₹Rs.]\s?([\d,]+(?:\.\d{1,2})?)', raw_text)
    if amount_match:
        evidence["amount"] = amount_match.group(1).replace(",", "")

    date_match = re.search(r'\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b', raw_text)
    if date_match:
        evidence["date"] = date_match.group(1)

    status_match = re.search(r'\b(FAILED|SUCCESS|PENDING)\b', raw_text, re.IGNORECASE)
    if status_match:
        evidence["txn_status"] = status_match.group(1).upper()

    # Merchant is the hardest to extract reliably via regex alone — check
    # against your known merchant list from the DB, same as _guess_merchant()
    from db.schema import get_connection
    conn = get_connection()
    merchants = [r["merchant"] for r in conn.execute("SELECT DISTINCT merchant FROM mandates").fetchall()]
    conn.close()
    for m in merchants:
        if m.lower() in raw_text.lower():
            evidence["merchant"] = m
            break

    evidence["_raw_ocr_text"] = raw_text.strip()  # keep for debugging/audit
    return evidence