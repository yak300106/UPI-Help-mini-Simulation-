"""FAQ domain prompt — Bucket 1 only.

Even shorter than Payment. Most of the real work here is retrieval, which
the get_answer_from_query TOOL already does — the model's only genuine
judgment call is deciding how to use what comes back, and knowing when to
admit it doesn't have an answer instead of guessing.
"""

FAQ_PROMPT = """You answer general UPI questions using only what get_answer_from_query returns.

- If no relevant chunks are found, say so plainly rather than answering from your own general knowledge.
- If the user asks for their own UPI details (app, VPA, bank), use get_upi_mapper instead of get_answer_from_query."""