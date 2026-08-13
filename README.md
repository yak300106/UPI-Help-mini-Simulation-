# Mini UPI Help — Agentic Framework

A working, hands-on rebuild of NPCI's UPI Help chatbot on top of the new single-agent framework architecture, built to test ideas from architecture research against a real local LLM, a real database, and a real chat UI.

![Architecture Diagram](architecture_diagram.png)

---

## What this is

Every design decision here traces back to something confirmed by reading the real UPI Help codebase and the real target framework's source code:

- **One shared `AgentLoop`**, not four separate agents — matches the real framework's own stated identity ("a transparent, single-agent, self-hosted runtime").
- **Domains are tool groupings + prompt blocks**, not separate reasoning systems.
- **Deterministic safety hooks** replace prose-based rules the model can't be trusted to always follow.
- **Post-generation output validation** catches hallucinated tool-call syntax and fabricated data.
- **A real SQLite database**, real two-step confirmation flows (generate intent → confirm intent), matching how UPI actually works.
- **Evidence-aware dispute filing (UDIR)** — pulls transaction/mandate details already surfaced in the conversation instead of asking the user to re-supply them, with a downloadable PDF receipt.

## Tech stack

| Layer | Choice |
|---|---|
| Model | Ollama, `llama3.2` (local, OpenAI-compatible API) |
| Backend | Python, Flask |
| Frontend | Single-page HTML/CSS/JS, no framework |
| Database | SQLite |
| Receipts | `reportlab` (PDF generation) |

## Project structure
```
mini_upi_help/
├── core/
│   ├── types.py          # ToolDefinition, RunResult
│   ├── events.py          # EventBus — structured logging
│   ├── hooks.py            # ToolHookBus — pre-execution safety checks
│   ├── output_hooks.py     # post-generation hallucination/fabrication check
│   ├── session.py          # message history + pending-clarification state
│   └── loop.py              # AgentLoop — the ONE shared reasoning loop
├── tools/
│   └── registry.py          # name -> ToolDefinition, domain filtering
├── domains/
│   ├── mandate_tools.py     # summary/fetch/pause/revoke/unpause/confirm_intent
│   ├── payment_tools.py     # transaction lookup, dispute (legacy)
│   ├── faq_tools.py         # retrieval-based Q&A
│   └── dispute_tools.py     # UDIR evidence-based filing + receipts
├── prompts/
│   ├── base_prompt.py       # shared, cross-domain rules (bucket 3)
│   ├── mandate_prompt.py    # domain-specific judgment calls only (bucket 1)
│   ├── payment_prompt.py
│   ├── faq_prompt.py
│   └── dispute_prompt.py
├── router/
│   └── router.py             # domain classification + fast-lane check
├── llm/
│   ├── mock_llm.py           # scripted LLM for isolated testing
│   └── real_llm.py           # Ollama adapter
├── db/
│   ├── schema.py             # SQLite schema + seed data
│   └── reset.py               # wipe + reseed
├── static/
│   └── index.html             # chat frontend
├── receipts/                   # generated PDF receipts
├── app.py                       # Flask API
└── run_demo.py                   # scripted end-to-end scenario runner
```
## The 3-bucket prompt method

Every rule in a domain's prompt is sorted into one of three categories, instead of writing the same rule three times (instruction + example + checklist) the way the real production prompts do:

| Bucket | Example | Where it lives |
|---|---|---|
| 1. Genuine judgment | "Ask which mandate if the match is ambiguous" | Stays in the domain's prompt, kept short |
| 2. Deterministic rule | "Check the eligibility flag before revoking" | Moved to a hook (`core/hooks.py`) — enforced in code, not prose |
| 3. Cross-domain rule | "Answer in the user's language" | Moved to `prompts/base_prompt.py`, written once |

Result: dramatically shorter, non-duplicated prompts, with safety guarantees that don't depend on the model remembering anything.

## Key mechanisms

### Pre-execution hooks (`core/hooks.py`)
Run right before a tool executes. Can block or modify a call. Proven live: the local model repeatedly tried to skip `mandate_fetch` before `mandate_revoke` — the hook caught it every time, regardless of prompt wording.

### Post-generation validation (`core/output_hooks.py`)
Runs after the model produces a final answer. Catches hallucinated tool-call-looking text and fabricated data (numbers/dates not backed by any real tool result this turn).

### Two-step intent confirmation
Mandate actions don't complete in one step. `mandate_revoke`/`pause`/`unpause` create a **pending intent** and return a link — nothing changes in the database yet. A separate `confirm_intent()` call (simulating the user tapping the link) is the only place the database actually updates. Mirrors how real UPI works.

### Deterministic shortcuts
Given the local model's unreliability at initiating multi-step flows correctly, several flows bypass the LLM entirely for well-defined patterns:
- **Mandate actions** ("cancel my Spotify mandate") — matches the user's own wording against real merchant names in the database, resolves ambiguity via real mandate cards, and completes the whole flow without a model call.
- **Dispute filing** ("file a complaint about this") — pulls evidence straight from the session's own message history.
- **Dispute status check** ("check my dispute status") — finds the most recently mentioned dispute ID in the session automatically.

Hooks and validation still apply on every deterministic path — the shortcut only skips reasoning, never safety.

### Session-based evidence gathering
`Session.messages` stores the full conversation, including every tool result. `gather_evidence_from_session()` scans this history to auto-attach transaction/mandate details to a new dispute, so the user never has to re-supply information the system already has.

## Running it

```bash
# 1. Start Ollama (separate terminal, or via the app)
ollama serve

# 2. Set up the database (first time only)
python3 -m db.schema

# 3. Run the Flask app
python3 app.py

# 4. Open the browser
http://localhost:5050
```

Reset the database at any time via the **Reset database** button in the UI, or:
```bash
python3 -m db.reset
```

## Known limitations

- The local 3B model (`llama3.2`) is unreliable at multi-step tool-calling — this is *why* deterministic shortcuts and hooks exist, not a bug to be fixed here.
- Tool selection/routing uses simple keyword matching, not the real framework's hybrid BM25 + embeddings + RRF system — a known, deliberate simplification for this scale of demo.
- The deterministic-matching pattern is only generalized for the Mandate and Dispute domains, not yet Payment or FAQ.

## What this demonstrates

A complete, working proof that the architectural ideas explored in research — single shared loop, domain-based tool/prompt filtering, hooks over prose, evidence-aware automation — hold up when actually built and tested against a real (imperfect) model, not just diagrammed.
