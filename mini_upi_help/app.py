"""Flask backend for the mini UPI Help frontend.
Wires the existing AgentLoop/Router/Session code straight into a web API.
"""
from __future__ import annotations
from flask import Flask, request, jsonify, send_from_directory, send_file

from core.events import EventBus
from core.hooks import ToolHookBus
from core.session import get_or_create_session
from core.loop import AgentLoop
from router.router import route
from domains.mandate_tools import mandate_eligibility_hook, try_deterministic_mandate_action
from domains.dispute_tools import (
    dispute_evidence_hook, gather_evidence_from_session, raise_dispute_with_evidence,
    find_last_dispute_id_in_session, check_dispute_status, RECEIPTS_DIR,
)
from llm.real_llm import RealLLM
from prompts.base_prompt import BASE_PROMPT
from prompts.mandate_prompt import MANDATE_PROMPT
from prompts.payment_prompt import PAYMENT_PROMPT
from prompts.faq_prompt import FAQ_PROMPT
from prompts.dispute_prompt import DISPUTE_PROMPT


app = Flask(__name__, static_folder="static", static_url_path="")
import os
from pathlib import Path
from werkzeug.utils import secure_filename

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

_DOMAIN_PROMPTS = {"mandate": MANDATE_PROMPT, "payment": PAYMENT_PROMPT, "faq": FAQ_PROMPT, "dispute": DISPUTE_PROMPT}

_DISPUTE_KEYWORDS = ["file a complaint", "raise a dispute", "file a dispute", "complain about", "dispute this"]
_STATUS_CHECK_KEYWORDS = ["check my dispute", "dispute status", "status of my complaint", "check my complaint"]

def build_prompt(domain: str) -> str:
    return BASE_PROMPT + "\n\n" + _DOMAIN_PROMPTS[domain]


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True)
    query = data.get("message", "").strip()
    session_id = data.get("session_id", "default-session")

    if not query:
        return jsonify({"error": "empty message"}), 400

    session = get_or_create_session(session_id)

    # ---- Case A: mid-clarification, user is answering "which one did you mean?" ----
    if session.has_pending_task():
        from router.router import build_full_registry
        pending_domain = session.pending_domain
        pending_context = session.pending_context
        full_registry = build_full_registry()
        domain_registry = full_registry.filter_by_domain(pending_domain)

        bus = EventBus()
        hooks = ToolHookBus(bus)
        if pending_domain == "mandate":
            hooks.register(mandate_eligibility_hook)
        if pending_domain == "dispute":
            hooks.register(dispute_evidence_hook)

        loop = AgentLoop(llm=None, tools=domain_registry, system_prompt="", bus=bus,
                          hooks=hooks, session=session, domain_name=pending_domain)
        result = loop.resolve_pending(query, pending_context)

        candidates = pending_context.get("candidates") if result.reason == "ambiguous_pause" else None
        return jsonify({
            "answer": result.answer, "reason": result.reason, "domain": pending_domain,
            "fast_lane": False, "router_reason": "resolved from pending clarification",
            "candidates": candidates, "trace": bus.trace(),
            "pending_intent_id": result.pending_intent_id,
        })

    # ---- Case B: fresh query — route it, and set up bus/hooks BEFORE anything uses them ----
    decision = route(query, session)

    bus = EventBus()
    hooks = ToolHookBus(bus)
    if decision.domain == "mandate":
        hooks.register(mandate_eligibility_hook)
    if decision.domain == "dispute":
        hooks.register(dispute_evidence_hook)

    # ---- Case B1: deterministic shortcut for mandate actions ----
    if decision.domain == "mandate":
        shortcut = try_deterministic_mandate_action(query, hooks)
        if shortcut is not None:
            if shortcut["status"] == "ambiguous":
                session.set_pending(domain="mandate", context={
                    "candidates": shortcut["candidates"], "original_query": query
                })
                candidate_desc = ", ".join(f"{c['merchant']} (₹{c['amount']})" for c in shortcut["candidates"])
                return jsonify({
                    "answer": f"I found more than one match: {candidate_desc}. Which one did you mean?",
                    "reason": "ambiguous_pause", "domain": "mandate", "fast_lane": False,
                    "router_reason": "deterministic shortcut", "candidates": shortcut["candidates"],
                    "trace": bus.trace(), "pending_intent_id": None,
                })
            if shortcut["status"] == "blocked":
                return jsonify({
                    "answer": "I want to make sure I have the right details before doing that — "
                              "could you tell me again which mandate you mean?",
                    "reason": "hook_blocked", "domain": "mandate", "fast_lane": False,
                    "router_reason": "deterministic shortcut", "candidates": None,
                    "trace": bus.trace(), "pending_intent_id": None,
                })
            if shortcut["status"] == "resolved":
                intent = shortcut["result"]
                answer = (f"Your {shortcut['merchant']} mandate is ready to be {shortcut['action_word']}d — "
                          f"tap here to confirm: {intent.get('intent_link', '')}")
                return jsonify({
                    "answer": answer, "reason": "resolved_from_pending", "domain": "mandate",
                    "fast_lane": False, "router_reason": "deterministic shortcut", "candidates": None,
                    "trace": bus.trace(), "pending_intent_id": intent.get("intent_id"),
                })

    # ---- Case B1b: deterministic shortcut for dispute filing — pulls evidence
    # straight from this session's own history instead of relying on the model. ----
    if decision.domain == "dispute" and any(k in query.lower() for k in _DISPUTE_KEYWORDS):
        evidence = gather_evidence_from_session(session)

        if not evidence.get("txn_id") and not evidence.get("mandate_id"):
            return jsonify({
                "answer": "I don't have a transaction or mandate on hand yet for this complaint — "
                          "could you tell me which one it's about, or ask about it first?",
                "reason": "no_evidence", "domain": "dispute", "fast_lane": False,
                "router_reason": "deterministic shortcut", "candidates": None,
                "trace": bus.trace(), "pending_intent_id": None,
            })

        result = raise_dispute_with_evidence(reason=query, **evidence)
        answer = (f"I've filed your dispute — reference {result['dispute_id']}. "
                  f"You can download a receipt below.")
        session.messages.append({"role": "assistant", "content": answer})
        return jsonify({
            "answer": answer, "reason": "dispute_filed", "domain": "dispute", "fast_lane": False,
            "router_reason": "deterministic shortcut", "candidates": None,
            "trace": bus.trace(), "pending_intent_id": None,
            "receipt_url": result["receipt_url"],
        })
    # ---- Case B1c: deterministic shortcut for checking dispute status ----
    if decision.domain == "dispute" and any(k in query.lower() for k in _STATUS_CHECK_KEYWORDS):
        dispute_id = find_last_dispute_id_in_session(session)

        if dispute_id is None:
            return jsonify({
                "answer": "I don't have a dispute reference for this session yet — "
                          "file a complaint first, or tell me the dispute ID directly.",
                "reason": "no_dispute_found", "domain": "dispute", "fast_lane": False,
                "router_reason": "deterministic shortcut", "candidates": None,
                "trace": bus.trace(), "pending_intent_id": None,
            })

        result = check_dispute_status(dispute_id)
        if "error" in result:
            answer = f"Couldn't find a dispute with reference {dispute_id}."
        else:
            answer = f"Your dispute {result['dispute_id']} is currently {result['status']}. Filed on {result['created_at']}."

        return jsonify({
            "answer": answer, "reason": "dispute_status_checked", "domain": "dispute", "fast_lane": False,
            "router_reason": "deterministic shortcut", "candidates": None,
            "trace": bus.trace(), "pending_intent_id": None,
            "receipt_url": result.get("receipt_url"),
        })
    # ---- Case B2: normal flow — fast lane or full reasoning loop ----
    if decision.fast_lane_eligible:
        loop = AgentLoop(llm=None, tools=decision.registry, system_prompt="", bus=bus,
                          hooks=hooks, session=session, domain_name=decision.domain)
        result = loop.run_fast_lane(query, decision.fast_lane_tool)
    else:
        llm = RealLLM()
        prompt = build_prompt(decision.domain)
        loop = AgentLoop(llm=llm, tools=decision.registry, system_prompt=prompt,
                          bus=bus, hooks=hooks, session=session, domain_name=decision.domain)
        result = loop.run(query)

    candidates = None
    if session.has_pending_task():
        candidates = session.pending_context.get("candidates")

    return jsonify({
        "answer": result.answer, "reason": result.reason, "domain": decision.domain,
        "fast_lane": decision.fast_lane_eligible, "router_reason": decision.reason,
        "candidates": candidates, "trace": bus.trace(),
        "pending_intent_id": result.pending_intent_id,
    })


@app.route("/api/confirm_intent", methods=["POST"])
def confirm_intent_endpoint():
    from domains.mandate_tools import confirm_intent
    data = request.get_json(force=True)
    intent_id = data.get("intent_id", "")

    if not intent_id:
        return jsonify({"error": "missing intent_id"}), 400

    result = confirm_intent(intent_id)
    return jsonify(result)


@app.route("/api/receipt/<dispute_id>")
def download_receipt(dispute_id):
    path = RECEIPTS_DIR / f"{dispute_id}.pdf"
    if not path.is_file():
        return jsonify({"error": "receipt not found"}), 404
    return send_file(path, as_attachment=True, download_name=f"{dispute_id}_receipt.pdf")


@app.route("/api/reset", methods=["POST"])
def reset_endpoint():
    from db.reset import reset_database
    result = reset_database()
    return jsonify(result)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

@app.route("/api/upload_screenshot", methods=["POST"])
def upload_screenshot():
    from domains.ocr_evidence import extract_evidence_from_image
    from domains.dispute_tools import raise_dispute_with_evidence

    if "file" not in request.files:
        return jsonify({"error": "no file uploaded"}), 400

    file = request.files["file"]
    filename = secure_filename(file.filename)
    save_path = UPLOAD_DIR / filename
    file.save(save_path)

    evidence = extract_evidence_from_image(save_path)
    clean_evidence = {k: v for k, v in evidence.items() if k != "_raw_ocr_text" and v}

    if not clean_evidence.get("txn_id") and not clean_evidence.get("mandate_id"):
        return jsonify({"error": "I couldn't read clear transaction details from that image — try a clearer screenshot."})

    result = raise_dispute_with_evidence(reason="Filed from uploaded screenshot", **clean_evidence)

    return jsonify({
        "dispute_id": result["dispute_id"],
        "receipt_url": result["receipt_url"],
        "merchant": clean_evidence.get("merchant", ""),
        "amount": clean_evidence.get("amount", ""),
        "txn_status": clean_evidence.get("txn_status", ""),
        "date": clean_evidence.get("date", ""),
    })



if __name__ == "__main__":
    app.run(debug=True, port=5050)