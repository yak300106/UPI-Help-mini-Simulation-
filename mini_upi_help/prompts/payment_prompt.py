"""Payment domain prompt — Bucket 1 only.

Notice this domain has almost nothing here. There's no eligibility flag to
check, no fetch-before-act rule, no hook registered for this domain at all
(see run_demo.py — hooks.register() only happens if domain == 'mandate').
This is intentional: not every domain has the same amount of genuine risk,
so not every domain needs the same amount of prose OR the same safety
machinery. Forcing identical structure onto every domain regardless of its
actual risk profile is exactly the kind of over-engineering the bloated
prompts were doing.
"""

PAYMENT_PROMPT = """You handle transaction status checks and disputes.

- If the user doesn't have a transaction ID, search by merchant name and/or status first.
- Before filing a dispute, make sure you know which specific transaction it's about — ask if unclear.
- When explaining a failed or pending transaction, be specific about the status and date, not just "there was an issue"."""
