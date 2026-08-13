"""FAQ domain — real tool names from the actual FAQ Agent code you found earlier.
Retrieval here is simple keyword overlap, not real embeddings — good enough
to prove the RAG-as-a-tool PATTERN works; swap in a real vector store later
if you want to test retrieval quality itself.
"""
from __future__ import annotations
from core.types import ToolDefinition

# ---------------------------------------------------------------------------
# SYNTHETIC KNOWLEDGE BASE — tiny, on purpose. Each doc is a short FAQ chunk.
# ---------------------------------------------------------------------------
_DOCS = [
    {"id": "doc1", "text": "UPI (Unified Payments Interface) is an instant payment system by NPCI enabling real-time transfers between bank accounts, available 24/7."},
    {"id": "doc2", "text": "The default UPI transaction limit is ₹1 lakh per transaction for most banks, though some banks allow higher limits for verified merchants."},
    {"id": "doc3", "text": "To register for UPI, you need a bank account, a registered mobile number, and a UPI-enabled app. Registration takes about 5 minutes."},
    {"id": "doc4", "text": "UPI AutoPay lets you set up recurring mandates for subscriptions, EMIs, and bills, which can be paused, resumed, or cancelled anytime."},
    {"id": "doc5", "text": "To file a UPI complaint, use the UDIR (UPI Dispute Resolution) system through your bank's app, providing the transaction reference number."},
    {"id": "doc6", "text": "UPI Lite is designed for small transactions under ₹1,000 using an on-device wallet, bypassing the need for a UPI PIN for faster payments."},
]

# ---------------------------------------------------------------------------
# SYNTHETIC UPI MAPPER DATA — for get_upi_mapper, keyed by fake mobile hash
# ---------------------------------------------------------------------------
_UPI_MAPPER = {
    "user_hash_123": {"app": "Google Pay", "vpa": "ananya@okhdfcbank", "bank": "HDFC Bank"},
}


def get_answer_from_query(query: str) -> dict:
    """Simple keyword-overlap retrieval — stand-in for real vector search.
    Returns the top matching chunk(s) so the model can synthesize an answer.
    """
    query_words = set(query.lower().split())
    scored = []
    for doc in _DOCS:
        doc_words = set(doc["text"].lower().split())
        overlap = len(query_words & doc_words)
        if overlap > 0:
            scored.append((overlap, doc))
    scored.sort(key=lambda x: x[0], reverse=True)
    top_chunks = [d["text"] for _, d in scored[:2]]
    if not top_chunks:
        return {"chunks": [], "found": False}
    return {"chunks": top_chunks, "found": True}


def get_upi_mapper(user_hash: str = "user_hash_123") -> dict:
    """Fetch the user's linked UPI app/VPA/bank. Defaults to one fake user for testing."""
    mapping = _UPI_MAPPER.get(user_hash)
    if not mapping:
        return {"found": False}
    return {"found": True, **mapping}


def output(message: str) -> dict:
    return {"message": message}


def build_faq_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="get_answer_from_query", domain="faq", risk="safe",
            description="Retrieve information to answer a general UPI/fintech question from the knowledge base.",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            handler=get_answer_from_query,
        ),
        ToolDefinition(
            name="get_upi_mapper", domain="faq", risk="safe",
            description="Get the user's own linked UPI app, VPA, and bank details.",
            parameters={"type": "object", "properties": {"user_hash": {"type": "string"}}, "required": []},
            handler=get_upi_mapper,
        ),
        ToolDefinition(
            name="faq_output", domain="faq", risk="safe", terminal=True,
            description="Send the final response to the user. Ends the conversation turn.",
            parameters={"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]},
            handler=output,
        ),
    ]