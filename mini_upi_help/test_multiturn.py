"""Direct test of the ambiguous-match -> session-pause -> resume mechanism.
Uses a SCRIPTED mock LLM (not the flaky real model) to force the exact
sequence needed, so we can prove OUR code works correctly, independent of
whether the real model reliably calls mandate_summary first.
"""
from core.events import EventBus
from core.hooks import ToolHookBus
from core.session import get_or_create_session
from core.loop import AgentLoop
from tools.registry import ToolRegistry
from domains.mandate_tools import build_mandate_tools, mandate_eligibility_hook, LAST_FETCHED
from llm.mock_llm import ScriptedMockLLM
from prompts.base_prompt import BASE_PROMPT
from prompts.mandate_prompt import MANDATE_PROMPT
from router.router import classify_domain

LAST_FETCHED.clear()
session = get_or_create_session("multiturn-direct-test")

registry = ToolRegistry(build_mandate_tools())
bus = EventBus()
hooks = ToolHookBus(bus)
hooks.register(mandate_eligibility_hook)

# Force the model to call mandate_summary("Netflix") first, no matter what
# the real model would have done. This proves OUR ambiguity-check code.
script = [
    {"tool_call": {"name": "mandate_summary", "arguments": {"filter": "Netflix"}}},
]
llm = ScriptedMockLLM(script)

print("=== TURN 1: 'cancel my Netflix mandate' ===\n")
loop1 = AgentLoop(llm=llm, tools=registry, system_prompt=BASE_PROMPT + "\n\n" + MANDATE_PROMPT,
                  bus=bus, hooks=hooks, session=session, domain_name="mandate")
result1 = loop1.run("cancel my Netflix mandate")

print(f"\nRESULT: reason='{result1.reason}'")
print(f"ANSWER: {result1.answer}\n")

print("--- Checking session state after turn 1 ---")
print(f"session.has_pending_task() = {session.has_pending_task()}")
print(f"session.pending_domain     = {session.pending_domain}")
print(f"session.pending_context    = {session.pending_context}")

print("\n=== TURN 2: 'the one for 199 rupees' (SAME session) ===\n")
domain, reason = classify_domain("the one for 199 rupees", session)
print(f"classify_domain() -> domain='{domain}', reason='{reason}'")