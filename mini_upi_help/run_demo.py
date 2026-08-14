"""Wires everything together and runs test scenarios end to end.

Run with:  python run_demo.py
"""
from llm.real_llm import RealLLM
from core.events import EventBus
from core.hooks import ToolHookBus
from core.session import get_or_create_session
from core.loop import AgentLoop

from router.router import route

from domains.mandate_tools import mandate_eligibility_hook, LAST_FETCHED

from llm.mock_llm import (
    ScriptedMockLLM,
    mandate_happy_path_script,
    mandate_skip_fetch_script,
    mandate_ineligible_script,
    payment_status_check_script,
    faq_query_script,
)

from prompts.base_prompt import BASE_PROMPT
from prompts.mandate_prompt import MANDATE_PROMPT
from prompts.payment_prompt import PAYMENT_PROMPT
from prompts.faq_prompt import FAQ_PROMPT

# Real bucket-based prompts: shared base (bucket 3) + domain block (bucket 1).
# Bucket 2 (deterministic rules) lives in core/hooks.py + the domain tool
# handlers themselves — never in these prompt strings at all.
_DOMAIN_PROMPTS = {
    "mandate": MANDATE_PROMPT,
    "payment": PAYMENT_PROMPT,
    "faq": FAQ_PROMPT,
}


def build_prompt(domain: str) -> str:
    return BASE_PROMPT + "\n\n" + _DOMAIN_PROMPTS[domain]


def run_scenario(name: str, query: str, script: list[dict], session_id: str = None):
    print(f"\n{'=' * 70}")
    print(f"SCENARIO: {name}")
    print(f"QUERY: \"{query}\"")
    print('=' * 70)

    LAST_FETCHED.clear()  # reset synthetic "already fetched" state between scenarios
    session = get_or_create_session(session_id)

    decision = route(query, session)
    print(f"\n[ROUTER] domain='{decision.domain}' | {decision.reason}\n")

    bus = EventBus()
    hooks = ToolHookBus(bus)
    if decision.domain == "mandate":
        hooks.register(mandate_eligibility_hook)

    if decision.fast_lane_eligible:
        loop = AgentLoop(llm=None, tools=decision.registry, system_prompt="", bus=bus, hooks=hooks,
                          session=session, domain_name=decision.domain)
        result = loop.run_fast_lane(query, decision.fast_lane_tool)
    else:
        llm = RealLLM()
        prompt = build_prompt(decision.domain)
        loop = AgentLoop(llm=llm, tools=decision.registry, system_prompt=prompt,
                          bus=bus, hooks=hooks, session=session, domain_name=decision.domain)
        result = loop.run(query)

    print(f"\nRESULT: reason='{result.reason}' | steps={result.steps}")
    print(f"ANSWER: {result.answer}\n")
    return result


if __name__ == "__main__":
    run_scenario(
        "Mandate — happy path (cancel Spotify)",
        "I want to cancel my Spotify mandate",
        mandate_happy_path_script(),
    )

    run_scenario(
        "Mandate — model skips fetch (should be blocked)",
        "cancel my Netflix mandate",
        mandate_skip_fetch_script(),
    )

    run_scenario(
        "Mandate — ineligible action (should be blocked after fetch)",
        "cancel my Netflix mandate",
        mandate_ineligible_script(),
    )

    run_scenario(
        "Payment — status check",
        "why did my Swiggy payment fail",
        payment_status_check_script(),
    )

    run_scenario(
        "FAQ — general question",
        "what is the UPI transaction limit",
        faq_query_script(),
    )

    run_scenario(
        "FAQ — fast lane candidate (short query)",
        "UPI limit",
        None,  # script unused now, real model / fast lane handles it
    )

    print(f"\n{'=' * 70}")
    print("MULTI-TURN TEST: ambiguous mandate match, then clarification")
    print('=' * 70)

    run_scenario(
        "Mandate — ambiguous match (turn 1)",
        "cancel my Netflix mandate",
        None,
        session_id="multi-turn-test-1",
    )

    run_scenario(
        "Mandate — clarification (turn 2, SAME session)",
        "the one for 199 rupees",
        None,
        session_id="multi-turn-test-1",
    )

    print(f"\n{'=' * 70}")
    print("All scenarios complete. Notice: ONE AgentLoop class ran all scenarios,")
    print("just reconfigured each time with a different domain's tools + prompt.")
    print('=' * 70)