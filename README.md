# UPI Help — Mini Simulation

**A synthetic multi-agent clone of NPCI's UPI Help query resolution platform, built to prototype and stress-test an agentic architecture independently of the real production system.**

Repo: `github.com/yak300106/UPI-Help-mini-Simulation-`

---

## 1. What this project is

UPI Help Mini Simulation is a self-contained Flask + vanilla-JS application that reproduces the core mechanics of a real conversational fintech support system — the kind that handles UPI AutoPay mandates, transaction/payment status, general FAQs, and dispute filing — using synthetic data instead of production banking data.

The point of building it wasn't to ship a product. It was to have a safe, fully inspectable sandbox to work out hard agentic-systems questions (routing, safety gating, ambiguity handling, multi-turn state, tool-calling discipline, output validation) before those decisions get made against a real system with real money and real users on the other end. Every mechanism in here — the router, the safety hooks, the fast lane, the output validator — mirrors a real problem encountered while working on the actual UPI Help platform, reduced to its essential shape and made runnable end-to-end on a laptop.

---

## 2. Core design philosophy

A few decisions run through the entire codebase and are worth calling out up front, because they explain *why* the code is organized the way it is:

- **One loop, not many agents.** There is exactly one `AgentLoop` class. "Mandate agent", "Payment agent", "FAQ agent", "Dispute agent" are not separate classes or separate processes — they're the *same* loop, reconfigured per turn with a different tool registry and a different prompt block. This was a deliberate correction against an earlier design that spun up genuinely separate agents per domain, which turned out to be unnecessary complexity — domain-switching is a data problem (which tools, which prompt), not an architecture problem.

- **Three buckets of "why the model behaves correctly", and each rule lives in exactly one bucket:**
  1. **Judgment calls** — things that genuinely need language understanding (e.g. "which mandate did the user mean", "did they give a pause date"). These live in the domain prompt files (`prompts/*.py`), and only these live there.
  2. **Deterministic rules** — things that should *never* depend on the model remembering to check them (e.g. "don't revoke a mandate that isn't eligible", "don't file a dispute with zero evidence"). These live in **hooks** (`core/hooks.py` + the domain-specific hook functions), which run in code before a tool executes, and can't be talked around by a cleverly-worded prompt injection or a model having a bad turn.
  3. **Cross-domain rules** — apply no matter which domain got picked (e.g. "never fabricate an ID a tool didn't actually return", "always end the turn by calling a tool"). These live once in `prompts/base_prompt.py` instead of being copy-pasted into every domain prompt.

  This split is the single biggest structural idea in the codebase: it keeps prompts short (each domain prompt is 3–6 lines) and keeps safety-critical behavior out of the parts of the system that are probabilistic.

- **Fast lane vs. slow lane.** Not every query needs a full LLM reasoning loop. If the Router can tell, deterministically, that a short query clearly and unambiguously matches exactly one *safe* tool, it skips the model entirely and calls that tool directly (`run_fast_lane`). This is a real latency/cost optimization pattern, reproduced here so its trade-offs (when is "obviously safe" actually safe?) could be examined directly.

- **Deterministic shortcuts before the LLM, not instead of it.** Several high-frequency intents (cancel/pause/unpause a mandate, file a dispute, check dispute status) are handled by pure Python pattern-matching in `app.py`/`domains/*.py` *before* the query is ever handed to the model loop at all. This isn't the fast lane (which still involves the tool registry/hooks machinery) — it's a step earlier, for cases common enough and structured enough that they don't need the model to interpret them at all. The LLM loop is the fallback for everything that doesn't match a deterministic shortcut.

- **Session-scoped memory of what already happened.** Instead of forcing the user to repeat a transaction ID or mandate ID they already gave earlier in the conversation, several tools scan the session's own message history (`gather_evidence_from_session`, `find_last_dispute_id_in_session`) and reuse whatever was already surfaced. This trades a bit of regex fragility for a noticeably less annoying user experience.

- **Two-step "intent, then confirm" for anything irreversible.** Mandate actions (revoke/pause/unpause) never apply immediately. Calling `mandate_revoke` etc. only creates a `pending_intents` row and returns an intent link — nothing in the database actually changes until a separate `confirm_intent` call happens, simulating the user tapping the UPI deep link. This mirrors how UPI mandate actions actually work in production (the intent and the confirmation are genuinely two different events), and it means an LLM mis-calling an action tool doesn't, by itself, cause an irreversible change.

---

## 3. High-level architecture

```
                         ┌─────────────────────────┐
                         │   static/index.html      │  ← single-page chat UI
                         │   (vanilla JS, no build)  │
                         └────────────┬─────────────┘
                                      │ fetch()
                         ┌────────────▼─────────────┐
                         │        app.py (Flask)     │  ← HTTP layer / wiring
                         └────────────┬─────────────┘
                                      │
              ┌───────────────────────┼────────────────────────┐
              │                       │                        │
     ┌────────▼────────┐   ┌──────────▼─────────┐   ┌──────────▼─────────┐
     │  router/router.py │   │   core/session.py   │   │  core/events.py    │
     │  domain + lane     │   │   per-conversation   │   │  structured trace  │
     │  classification     │   │   pending-state       │   │  of every decision │
     └────────┬────────┘   └──────────┬─────────┘   └──────────┬─────────┘
              │                       │                        │
              └───────────┬───────────┴────────────┬───────────┘
                           │                        │
                 ┌─────────▼─────────┐    ┌─────────▼─────────┐
                 │   core/loop.py     │    │  core/hooks.py     │
                 │   AgentLoop         │◄──►│  Safety Gateway     │
                 │   (the ONE loop)    │    │  (pre-tool checks)  │
                 └─────────┬─────────┘    └────────────────────┘
                           │
              ┌────────────┼────────────────────────────┐
              │            │                             │
     ┌────────▼───┐ ┌──────▼──────┐ ┌────────▼──────┐ ┌──▼───────────┐
     │  mandate_   │ │ payment_    │ │  faq_tools.py  │ │ dispute_     │
     │  tools.py    │ │ tools.py     │ │                 │ │ tools.py      │
     └────────┬───┘ └─────────────┘ └────────────────┘ └──┬───────────┘
              │                                             │
     ┌────────▼─────────────────────────────────────────────▼───────┐
     │                    db/schema.py — SQLite (upi_help.db)         │
     │        mandates · transactions · pending_intents · disputes    │
     └──────────────────────────────────────────────────────────────┘

     Separate side-channel:
     domains/ocr_evidence.py  →  pytesseract  →  screenshot → evidence dict
                                                         │
                                                         ▼
                                          feeds into raise_dispute_with_evidence()
```

---

## 4. Request lifecycle — what actually happens on one chat message

1. **Frontend** (`static/index.html`) POSTs `{ message, session_id }` to `/api/chat`.
2. **`app.py`** loads (or creates) the `Session` for that `session_id`.
3. **If the session has a pending clarification** (e.g. it just asked "which mandate did you mean?"), the new message is routed straight to `AgentLoop.resolve_pending()` — domain classification is skipped entirely, because the domain is already known.
4. **Otherwise**, `router.route()` runs:
   - `classify_domain()` — crude but effective keyword scoring across `mandate` / `payment` / `dispute` / `faq`, defaulting to `faq` if nothing scores.
   - `decide_fast_lane()` — checks whether the query is short (≤6 words) and unambiguously matches exactly one *safe*, non-terminal tool's keyword hints. If yes → fast lane. If zero or 2+ tools match → slow lane (deliberately conservative).
5. **Deterministic shortcuts are checked before the model ever runs**, in this order:
   - Mandate action keywords ("cancel", "pause", "revoke", "resume", "unpause") → `try_deterministic_mandate_action()` resolves the merchant against the real DB, fetches it (populating the safety hook's state), and either resolves it directly, asks for clarification (2+ matches), or reports it as blocked (ineligible) — all without an LLM call.
   - Dispute-filing keywords → evidence is pulled from the session's own history and a dispute is filed directly.
   - Dispute-status keywords → the most recent dispute ID mentioned in the session is looked up directly.
6. **If nothing deterministic matched**, either:
   - **Fast lane**: `AgentLoop.run_fast_lane()` calls the one identified tool directly (still passing through the hook layer), and formats the raw result into a sentence via `core/formatting.py` (there's no LLM call in this path, so nothing else can phrase the answer).
   - **Slow lane**: a real `AgentLoop.run()` reasoning loop starts, backed by `RealLLM` (see §7), with the domain's tool registry and `BASE_PROMPT + domain prompt` as the system prompt. It loops (max 6 steps) between "model requests a tool call" → hook check → tool execution → feed result back → repeat, until the model calls a terminal `*_output` tool or returns a plain final answer.
7. Every step — router decision, tool request, hook block/modify, tool result, ambiguity detection, final answer — is emitted onto an `EventBus` and returned to the frontend as `trace`, which renders as a collapsible "show trace" panel in the chat bubble. This was built specifically so agent behavior could be watched decision-by-decision rather than only seeing the final text.
8. The response also carries `pending_intent_id` (if an action created an unconfirmed intent) and `candidates` (if the loop paused on ambiguity) — the frontend uses these to render either a "✓ Confirm this action" button or clickable mandate-candidate cards.

---

## 5. The four domains

| Domain | Purpose | Risk profile | Hook registered? |
|---|---|---|---|
| **Mandate** | View / pause / unpause / revoke UPI AutoPay mandates | Highest — irreversible actions (revoke) | ✅ `mandate_eligibility_hook` |
| **Payment** | Look up / search transaction status | Low — read-only in practice | ❌ none |
| **FAQ** | Answer general UPI questions via retrieval; look up the user's own linked UPI/VPA details | Lowest | ❌ none |
| **Dispute** | File a UPI complaint (UDIR-style) with evidence, check dispute status | Medium — creates a real record, but not destructive | ✅ `dispute_evidence_hook` |

This table itself reflects a deliberate idea in the codebase: **not every domain gets identical scaffolding.** The Payment and FAQ prompt files even say so explicitly in their own docstrings — forcing the same amount of hook machinery and prompt prose onto a read-only FAQ lookup as onto an irreversible mandate cancellation would be over-engineering. Risk-appropriate safety, not uniform safety.

### 5.1 Mandate domain (`domains/mandate_tools.py`)
- Backed by a real SQLite table (`mandates`), not an in-memory dict — six seeded mandates (Spotify ×3, Netflix ×2, a HomeLoan EMI) each with independent `is_pause` / `is_revoke` / `is_unpause` eligibility flags, so different scenarios (eligible vs. blocked) are testable against real rows.
- **`mandate_eligibility_hook`** enforces two rules in code, not prompt text: (1) you must have fetched the mandate this conversation before acting on it (`LAST_FETCHED`, an in-memory per-run cache — deliberately *not* persisted, since it's about "what happened this conversation" rather than stored state), and (2) the mandate's own eligibility flag for that specific action must be true.
- Actions never touch the DB directly — `mandate_revoke` / `mandate_pause` / `mandate_unpause` all funnel through `_create_pending_intent()`, which just inserts a row into `pending_intents` and returns a fake `upi://confirm/...` deep link. The actual `UPDATE mandates SET status = ...` only happens in `confirm_intent()`, simulating the "tap the intent link" step.
- Also holds `calculator` (safe arithmetic via an AST whitelist — no `eval()`) for "what's my total monthly spend across mandates" type questions.
- `try_deterministic_mandate_action()` is the non-LLM shortcut described in §4 — handles the large majority of real mandate requests without ever calling the model.

### 5.2 Payment domain (`domains/payment_tools.py`)
- **Note:** this module is largely superseded by `dispute_tools.py` for anything dispute-related — it has its own separate in-memory `_TRANSACTIONS` / `_DISPUTES` dicts and its own `raise_dispute` tool, but `app.py` never imports `raise_dispute` from here; the live dispute-filing path is entirely `dispute_tools.raise_dispute_with_evidence`. `get_transaction_details` / `search_transactions` are the parts of this module actually in active use, for read-only status lookups.
- Exists as the intentional "low ceremony" contrast case against Mandate: read-only lookups need no hook at all.

### 5.3 FAQ domain (`domains/faq_tools.py`)
- `get_answer_from_query`: a tiny synthetic knowledge base (6 short UPI FAQ chunks) retrieved by plain keyword overlap — explicitly a stand-in to prove the "retrieval as a tool call" *pattern* works, not a real embeddings/vector-search implementation. Swapping in a real vector store wouldn't require changing anything else in the architecture.
- `get_upi_mapper`: returns a fake user's linked UPI app / VPA / bank, for "what's my UPI ID linked to" style questions.

### 5.4 Dispute domain (`domains/dispute_tools.py`)
The most fleshed-out domain, and the one the OCR feature plugs into.

- **`gather_evidence_from_session(session)`** — instead of asking the user to retype a transaction reference, this regex-scans the session's own message history (which already stores every tool result from earlier this conversation, as raw stringified dicts) for the most recent `txn_id` or `mandate_id` mentioned, plus merchant/amount/status/date around it.
- **`dispute_evidence_hook`** — the deterministic safety rule for this domain: a dispute can never be filed with zero evidence attached (no `txn_id` and no `mandate_id`). This is what actually produces the "I couldn't read clear transaction details" type message when evidence extraction comes up empty.
- **`raise_dispute_with_evidence()`** — writes a row to the `disputes` table (evidence stored as a JSON blob) and calls `generate_receipt_pdf()` to produce a real downloadable PDF receipt via ReportLab, served back through `/api/receipt/<dispute_id>`.
- **`check_dispute_status()`** / **`find_last_dispute_id_in_session()`** — lets the user check on a dispute later without re-supplying the dispute ID, by scanning session history for the last `DSP-XXXXXXXX` reference mentioned.

### 5.5 OCR evidence extraction (`domains/ocr_evidence.py`)
A second, independent way to file a dispute: instead of describing the transaction in the chat, the user uploads a screenshot of a failed/successful payment card, and the system extracts the same evidence fields via OCR instead of conversation.

- Uses **pytesseract** (Tesseract OCR) + **Pillow**. The image is thumbnailed to a max 900×900 box, then run through `image_to_string()`.
- Each field is extracted independently by its own regex, best-effort — a miss on one field doesn't block the others:
  - `txn_id` — pattern `TXN[\dOo]{3,}`, normalizing any `O`↔`0` OCR misreads (see §8, this was a real bug found and fixed during this project).
  - `amount` — matches a ₹/Rs.-prefixed number, strips commas.
  - `date` — `DD-MM-YYYY`(ish) pattern, `-` or `/` separator.
  - `txn_status` — looks for `FAILED` / `SUCCESS` / `PENDING`.
  - `merchant` — *not* regexed freeform; instead cross-checked against real merchant names already in the `mandates` table, so it only ever returns a merchant the system actually knows about.
- The endpoint hard-requires at least a `txn_id` or `mandate_id` before proceeding — mirroring `dispute_evidence_hook`'s rule, just enforced at the OCR entry point instead.
- The raw OCR text is kept internally (`_raw_ocr_text`) for debugging/audit but stripped before anything downstream sees it.

---

## 6. Core framework layer (`core/`)

| File | Responsibility |
|---|---|
| `core/types.py` | Shared dataclasses: `ToolDefinition` (name, description, JSON-schema parameters, handler, domain, risk level, whether it's terminal) and `RunResult` (answer, reason code, step count, pending intent info). |
| `core/loop.py` | `AgentLoop` — the single reasoning loop, described in §4. Also owns `resolve_pending()` (deterministic multi-turn clarification resolution) and `run_fast_lane()`. |
| `core/hooks.py` | `ToolHookBus` — the Safety Gateway. Hooks are plain functions `(tool_name, args) -> (allowed, possibly_modified_args, reason_if_blocked)`, run in registration order before a tool executes; the first hook to block wins. |
| `core/output_hooks.py` | `validate_output()` — a *different* layer from `ToolHookBus`: this runs *after* the model produces its final text, catching problems in generated language rather than in a tool call. Specifically catches (1) the model writing fake `[called toolX with {...}]`-looking syntax into its own answer without actually having called that tool, and (2) the model stating a specific date that doesn't appear in any real tool result from that turn — i.e. a fabricated detail. Flags and strips rather than blocking the run outright. |
| `core/events.py` | `EventBus` / `Event` — structured, timestamped logging of every meaningful decision in a run (`run.start`, `tool.request`, `tool.hook.blocked`, `ambiguity.auto_resolved`, `run.complete`, etc.), printed live to console and returned as a JSON-able `trace()` for the frontend's debug panel. |
| `core/session.py` | `Session` dataclass — per-conversation state: full message history, and `pending_domain` / `pending_context` for when a run pauses mid-task (e.g. asking "which mandate?"). Backed by an in-memory dict keyed by `session_id` (`_SESSIONS`) — a real deployment would swap this for persistent storage, but the interface wouldn't need to change. |
| `core/formatting.py` | Converts raw tool-result dicts into readable sentences for the fast lane, which has no LLM to phrase the answer since it skips the model entirely. |

---

## 7. LLM layer (`llm/`)

Both implementations share one interface — `.decide(messages, tools) -> dict`, returning either `{"tool_call": {...}}` or `{"final": "..."}` — so nothing in `core/loop.py` needs to know or care which one is plugged in.

- **`llm/mock_llm.py` — `ScriptedMockLLM`.** Plays back a fixed, hand-written sequence of decisions. Used to test the *loop mechanics themselves* (does a hook actually block correctly? does a terminal tool actually end the run? does ambiguity actually pause the session?) independent of whether a real model happens to behave correctly on a given run. Ships several pre-built scripts covering the mandate happy path, a model that "forgets" to fetch before acting (should be hook-blocked), an ineligible action (should be blocked after a proper fetch), a payment status check, and an FAQ lookup.
- **`llm/real_llm.py` — `RealLLM`.** Talks to a real model through the OpenAI-compatible chat-completions API, pointed at a **local Ollama instance** (`http://localhost:11434/v1`, model `llama3.2` by default) rather than a hosted API — meaning this simulation runs entirely offline against a local model. Converts the tool registry to OpenAI-style function-calling schema via `ToolRegistry.openai_schemas()`, and translates the response back into the same `{"tool_call"}` / `{"final"}` shape the mock uses.

---

## 8. Data layer (`db/`)

Single SQLite database, `db/upi_help.db`, four tables:

- **`mandates`** — `mandate_id`, `merchant`, `amount`, `frequency`, `status` (ACTIVE/PAUSED/REVOKED), independent `is_pause`/`is_revoke`/`is_unpause` eligibility flags, `umn` (never exposed to callers — stripped in `mandate_fetch`), `upi_app`, `paused_until`. Seeded with 6 rows.
- **`transactions`** — `txn_id`, `amount`, `merchant`, `status`, `date`. Seeded with 3 rows (including `TXN002` / Swiggy / ₹1200 / FAILED — the transaction referenced throughout the OCR testing).
- **`pending_intents`** — the "intent created but not yet confirmed" table backing the two-step mandate action flow: `intent_id`, `mandate_id`, `action`, `till_date`, `created_at`, `confirmed` flag.
- **`disputes`** — `dispute_id`, `txn_id`, `mandate_id`, `reason`, `status`, `evidence` (JSON blob), `created_at`.

`db/schema.py` handles both creation and reset (`init_db(reset=True)` drops and reseeds everything); `db/reset.py` exposes this as a callable used by the `/api/reset` endpoint and the frontend's "reset" button, so the whole demo can be returned to a known state at any time.

---

## 9. Web layer (`app.py` + `static/index.html`)

### Backend — Flask, single file (`app.py`)

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Serves the single-page frontend. |
| `/api/chat` | POST | Main conversational entry point — full routing/loop logic from §4. |
| `/api/confirm_intent` | POST | Confirms a pending mandate action (revoke/pause/unpause), applying the real DB change. |
| `/api/receipt/<dispute_id>` | GET | Downloads the generated PDF receipt for a dispute. |
| `/api/reset` | POST | Wipes and reseeds the database back to demo state. |
| `/api/upload_screenshot` | POST | Screenshot upload → OCR evidence extraction → dispute filing (see §5.5; this is the endpoint most recently reworked, see §10). |

### Frontend — `static/index.html` (single file, no build step)
A self-contained chat UI (~380 lines: inline CSS + vanilla JS, no frameworks) styled as a mobile-width app window. Notable pieces:
- Chat bubbles carry a **domain badge** and a **fast lane / full reasoning badge**, plus a **"show trace ▾"** panel that renders the full `EventBus` trace for that turn — this was built specifically to make agent decisions visible, not just outcomes.
- **Mandate ambiguity** renders as clickable candidate cards (merchant, amount, status) instead of forcing the user to type a disambiguating reply.
- **Pending mandate actions** render a **"✓ Confirm this action"** button wired to `/api/confirm_intent`.
- **Dispute filing via screenshot** has its own upload control, wired to `/api/upload_screenshot`.
- A **reset** button in the header wipes the DB back to seed state via `/api/reset`.

---

## 10. Feature timeline / what's been actively worked on

- **Core agentic framework** — single `AgentLoop`, three-bucket prompt discipline, router with domain classification + fast/slow lane split, pre-tool `ToolHookBus` safety gateway, post-answer `output_hooks` validation, full `EventBus` tracing.
- **Mandate domain** — migrated from a hardcoded dict to a real SQLite-backed implementation with genuine eligibility flags per mandate; two-step intent/confirm flow matching how real UPI mandate actions work.
- **Multi-turn session state** — ambiguous mandate matches pause the run and resume from the user's next message without re-classifying the domain, tested directly in `test_multiturn.py` using the scripted mock LLM (so the test is independent of whether the live model behaves correctly on any given run).
- **Dispute domain** — session-aware evidence gathering (no need to repeat a txn/mandate reference already mentioned), real PDF receipt generation via ReportLab, dispute-status lookup.
- **OCR-based dispute filing** — screenshot upload → Tesseract OCR → regex field extraction → dispute filing, as an alternative to describing the transaction in chat.
- **Two known issues found and fixed on this exact OCR path during development:**
  1. **OCR digit/letter confusion.** Tesseract was consistently misreading the `0` in `TXN002` as the letter `O` on the transaction-card font used in test screenshots — confirmed by running OCR directly against both a freshly uploaded screenshot and the bundled demo image (`uploads/Test_SS.png`), both of which produced literal `TXNO02`. Since the original regex (`\bTXN\d{3,}\b`) only matches digits, extraction silently failed every time. Fixed by widening the match to `\bTXN[\dOo]{3,}\b` and normalizing `O`→`0` after the match.
  2. **Immediate auto-filing instead of a confirm step.** The original `/api/upload_screenshot` handler extracted evidence and called `raise_dispute_with_evidence()` in the same request — meaning a dispute was filed automatically the instant OCR succeeded, with no user confirmation. This was reworked into a two-step flow mirroring the existing mandate-confirm pattern: the upload endpoint now only extracts evidence and stashes it (keyed by a generated `evidence_id`) via new `store_pending_evidence()` / `pop_pending_evidence()` functions; a new `/api/confirm_dispute` endpoint actually files the dispute once the user explicitly taps "File complaint" in the UI.
- **Output validation hardening** — `output_hooks.py`'s two checks (fake tool-call syntax leaking into final text; fabricated dates not backed by any real tool result) were both written in direct response to real hallucinations observed from the live local model during testing, captured verbatim as regression fixtures in `test_output_hooks.py`.

---

## 11. Tech stack

| Layer | Technology |
|---|---|
| Backend framework | Flask (Python) |
| Database | SQLite (via Python's built-in `sqlite3`, `sqlite3.Row` row factory) |
| LLM inference | Ollama, local, OpenAI-compatible chat-completions API (`llama3.2` default) via the `openai` Python client |
| OCR | Tesseract (`pytesseract` binding) + Pillow for image preprocessing |
| PDF generation | ReportLab (`reportlab.pdfgen.canvas`) |
| Frontend | Vanilla HTML/CSS/JS, single file, no build tooling, no framework |
| Testing | Plain Python scripts (`test_multiturn.py`, `test_output_hooks.py`) using the scripted mock LLM to make loop-mechanics tests deterministic and independent of live-model behavior |

No external package manager manifest (`requirements.txt`/`pyproject.toml`) is currently checked into the repo — dependencies (`flask`, `pytesseract`, `pillow`, `openai`, `reportlab`, `werkzeug`) are installed ad hoc.

---

## 12. Repository structure

```
UPI-Help-mini-Simulation-/
└── mini_upi_help/
    ├── app.py                      # Flask app, all HTTP routes
    ├── run_demo.py                 # CLI script running scripted end-to-end scenarios
    ├── test_multiturn.py           # Direct test of ambiguous-match/pause/resume
    ├── test_output_hooks.py        # Direct test of output validation against real captured hallucinations
    ├── core/
    │   ├── types.py                 # ToolDefinition, RunResult
    │   ├── loop.py                  # AgentLoop — the one reasoning loop
    │   ├── hooks.py                 # ToolHookBus — pre-tool Safety Gateway
    │   ├── output_hooks.py          # Post-answer output validation
    │   ├── events.py                # EventBus / structured tracing
    │   ├── session.py               # Session state, in-memory store
    │   └── formatting.py            # Fast-lane result → sentence formatting
    ├── router/
    │   └── router.py                # Domain classification + fast/slow lane decision
    ├── tools/
    │   └── registry.py              # ToolRegistry (generic, domain-agnostic)
    ├── domains/
    │   ├── mandate_tools.py         # Mandate domain: tools + eligibility hook + deterministic shortcut
    │   ├── payment_tools.py         # Payment domain (partially superseded, see §5.2)
    │   ├── faq_tools.py             # FAQ domain: keyword-overlap retrieval + UPI mapper
    │   ├── dispute_tools.py         # Dispute domain: evidence gathering, PDF receipts, filing/status
    │   └── ocr_evidence.py          # Screenshot OCR → evidence extraction
    ├── prompts/
    │   ├── base_prompt.py           # Bucket 3 — cross-domain rules
    │   ├── mandate_prompt.py        # Bucket 1 — mandate-specific judgment calls
    │   ├── payment_prompt.py        # Bucket 1 — payment-specific judgment calls
    │   ├── faq_prompt.py            # Bucket 1 — FAQ-specific judgment calls
    │   └── dispute_prompt.py        # Bucket 1 — dispute-specific judgment calls
    ├── llm/
    │   ├── mock_llm.py              # ScriptedMockLLM + pre-built test scripts
    │   └── real_llm.py              # RealLLM — Ollama-backed, OpenAI-compatible interface
    ├── db/
    │   ├── schema.py                # Table definitions, seed data, init_db()
    │   ├── reset.py                 # reset_database() callable
    │   └── upi_help.db              # SQLite database file
    ├── static/
    │   └── index.html               # Entire frontend — chat UI, single file
    ├── uploads/                     # Uploaded screenshots land here
    └── receipts/                    # Generated dispute PDF receipts land here
```

---

## 13. How to run it

```bash
cd mini_upi_help
python db/schema.py              # initialize/seed the database (first run only)
python app.py                    # starts Flask on http://localhost:5050
```

Requires a local Tesseract install (for OCR) and a running Ollama instance serving `llama3.2` (or another model — change `RealLLM(model=..., base_url=...)` in `app.py` to point elsewhere) for the slow-lane reasoning loop. The fast lane and all deterministic shortcuts work without any model running at all.

To run the scripted, model-independent test scenarios instead:

```bash
python run_demo.py               # 8 end-to-end scenarios, including the multi-turn ambiguity flow
python test_multiturn.py         # isolated pause/resume test
python test_output_hooks.py      # isolated output-validation test against real captured hallucinations
```

---

## 14. Known limitations / things flagged during development

- `domains/payment_tools.py` still defines its own `_TRANSACTIONS` / `_DISPUTES` dicts and a `raise_dispute` tool that's no longer wired into `app.py` — the live path for disputes is entirely through `dispute_tools.py`. Worth removing or clearly deprecating to avoid confusion later.
- Session state (`core/session.py`) and per-run "already fetched" state (`mandate_tools.LAST_FETCHED`) are both plain in-memory dicts — fine for a single-process demo, but would need to move to persistent/shared storage (Redis, DB-backed) for anything multi-worker or restart-safe.
- OCR field extraction is regex-based against a specific card layout; it's tolerant of the one font-rendering issue found and fixed (`0`/`O` confusion) but hasn't been stress-tested against materially different screenshot layouts (different banks/apps, different languages, lower resolution).
- No `requirements.txt`/`pyproject.toml` checked in yet.
- `README.md` at the repo root is currently empty — this document is intended to fill that gap.
