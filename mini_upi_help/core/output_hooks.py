"""Output validation — runs AFTER the model produces a final answer, checking
it against what tools actually returned this turn. This is a DIFFERENT layer
from ToolHookBus (which runs BEFORE a tool executes) — this one catches
problems in the model's own generated TEXT, not in a tool call it's making.

Two real failure modes we saw in actual model output, both caught here:
1. The model wrote fake tool-call-looking syntax into its final text
   (e.g. "[called getTransactionStatus with {...}]") — it never really
   called that tool, it just hallucinated the syntax.
2. The model stated a specific date/number that doesn't match anything
   any real tool actually returned this turn (a fabricated detail).
"""
from __future__ import annotations
import re


_FAKE_TOOL_CALL_PATTERN = re.compile(r"\[called\s+\w+.*?\]", re.IGNORECASE)
_DATE_PATTERN = re.compile(r"\b\d{1,2}[-/ ](?:\d{1,2}|[A-Za-z]+)[-/ ]\d{4}\b")


def validate_output(final_answer: str, tool_results_this_run: list[dict]) -> tuple[str, list[str]]:
    """Returns (possibly_cleaned_answer, list_of_issues_found).
    Does NOT block the run — this is a lighter-weight check than ToolHookBus,
    since we're validating text, not stopping a risky action. It flags and
    strips, rather than refusing outright.
    """
    issues: list[str] = []
    cleaned = final_answer

    # Check 1: strip any hallucinated tool-call-looking syntax
    fake_calls = _FAKE_TOOL_CALL_PATTERN.findall(cleaned)
    if fake_calls:
        issues.append(f"Model wrote fake tool-call syntax into its answer: {fake_calls}")
        cleaned = _FAKE_TOOL_CALL_PATTERN.sub("", cleaned).strip()

    # Check 2: any date mentioned must appear in an actual tool result this turn
    all_tool_result_text = " ".join(str(r) for r in tool_results_this_run)
    dates_in_answer = _DATE_PATTERN.findall(cleaned)
    for date_str in dates_in_answer:
        if date_str not in all_tool_result_text:
            issues.append(f"Date '{date_str}' in the answer does not match any tool result this turn — possibly fabricated.")

    return cleaned, issues