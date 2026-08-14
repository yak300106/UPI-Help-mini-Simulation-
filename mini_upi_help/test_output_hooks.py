"""Direct test of validate_output — doesn't depend on the model reproducing
the same hallucination twice. Uses the EXACT bad output captured from a real
run earlier, so we can prove the hook logic works regardless of whether the
live model happens to misbehave on any given run.
"""
from core.output_hooks import validate_output

# The exact hallucinated answer captured from your first real-model run
BAD_ANSWER = (
    "The transaction with TXN002 on Swiggy failed due to the status 'FAILED' and date "
    "'12-07-2026'. The exact reason for this failure may not be available, but please "
    "contact Swiggy's payment support team for assistance regarding this specific issue. \n\n"
    "[called getTransactionStatus with {'txn_id': 'TXN002', 'status': ''}]"
)

# What the tool ACTUALLY returned that turn (correct date: 12-07-2026)
REAL_TOOL_RESULTS = [
    {"matches": [{"txn_id": "TXN002", "amount": 1200, "merchant": "Swiggy",
                   "status": "FAILED", "date": "12-07-2026"}]}
]

cleaned, issues = validate_output(BAD_ANSWER, REAL_TOOL_RESULTS)

print("ISSUES FOUND:")
for i in issues:
    print(" -", i)

print("\nCLEANED ANSWER:")
print(cleaned)

# Now test the OTHER hallucination we saw: a wrong, fabricated date
BAD_DATE_ANSWER = "Your transaction failed on Date: 07 December 2022."
cleaned2, issues2 = validate_output(BAD_DATE_ANSWER, REAL_TOOL_RESULTS)
print("\n--- Second test: fabricated date ---")
print("ISSUES FOUND:")
for i in issues2:
    print(" -", i)