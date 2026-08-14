"""The AgentLoop — the single reasoning loop used by EVERY domain.
This is the concrete proof of the big correction from earlier: there is
only ONE loop in the whole system. "Domain" just changes which tools and
which prompt block get loaded into it for a given turn.
"""
from __future__ import annotations
import re
from tools.registry import ToolRegistry
from core.hooks import ToolHookBus
from core.types import RunResult


def _friendly_blocked_message(internal_reason: str) -> str:
    """Never show the raw hook reason to the user — it's internal/debug detail.
    The real reason still gets logged in the event trace for debugging.
    """
    return ("I want to make sure I have the right details before doing that — "
            "could you tell me again which mandate you mean?")


def _narrow_matches_by_query(matches: list[dict], user_message: str) -> list[dict]:
    """If the model called mandate_summary without a filter (or a bad one) and
    got back multiple matches, check whether the user's ORIGINAL message already
    named a specific merchant. If exactly one match's merchant appears in the
    user's own words, that's not really ambiguous — the user already told us.
    Only fall back to asking 'which one?' if this narrowing still leaves 2+.
    """
    query_lower = user_message.lower()
    narrowed = [m for m in matches if m.get("merchant", "").lower() in query_lower]
    if len(narrowed) == 1:
        return narrowed
    return matches  # still genuinely ambiguous (or nothing matched) — leave as-is


class AgentLoop:
    def __init__(self, llm, tools: ToolRegistry, system_prompt: str, bus,
                 hooks: ToolHookBus, session=None, max_steps: int = 6, domain_name: str = "general"):
        self.llm = llm
        self.tools = tools
        self.system_prompt = system_prompt
        self.bus = bus
        self.hooks = hooks
        self.session = session
        self.max_steps = max_steps
        self.domain_name = domain_name

    def run_fast_lane(self, user_message: str, tool_name: str) -> RunResult:
        """Skip reasoning entirely — call one known-safe tool directly.
        Still goes through hooks (safety applies regardless of lane) and
        still emits full trace events, so this is visible in logs exactly
        like a normal run, just with zero LLM calls.
        """
        self.bus.emit("run.start", input=user_message, mode="fast_lane", tools=[tool_name])

        tool = self.tools.get(tool_name)
        if tool is None:
            self.bus.emit("run.complete", reason="fast_lane_error", answer=f"unknown tool '{tool_name}'")
            return RunResult(answer=f"unknown tool '{tool_name}'", reason="fast_lane_error", steps=0)

        args = {}
        required = tool.parameters.get("required", [])
        if required:
            first_param = required[0]
            args = {first_param: user_message}

        self.bus.emit("tool.request", step=0, name=tool_name, arguments=args, mode="fast_lane")
        allowed, args, block_reason = self.hooks.run(tool_name, args)
        if not allowed:
            self.bus.emit("run.complete", reason="hook_blocked", answer=block_reason)
            return RunResult(answer=_friendly_blocked_message(block_reason), reason="hook_blocked", steps=1)

        result = tool.handler(**args)
        self.bus.emit("tool.call", step=0, name=tool_name, args=args, result=result, mode="fast_lane")

        from core.formatting import format_result_for_user
        answer = format_result_for_user(tool_name, result)
        self.bus.emit("run.complete", reason="fast_lane_terminal", answer=answer)

        pending_intent_id = result.get("intent_id") if isinstance(result, dict) else None
        return RunResult(answer=answer, reason="fast_lane_terminal", steps=1,
                          pending_intent_id=pending_intent_id)

    def resolve_pending(self, user_message: str, pending_context: dict) -> RunResult:
        """Called when the user is answering a 'which one did you mean?' clarification.
        Matches their reply to a specific candidate, figures out what action was
        originally requested, and completes fetch + action deterministically —
        no LLM call needed, since the ambiguity is already resolved by this point.
        """
        candidates = pending_context.get("candidates", [])
        original_query = pending_context.get("original_query", "").lower()

        numbers = re.findall(r"\d+", user_message)
        matched = None
        for c in candidates:
            if str(c.get("amount")) in numbers:
                matched = c
                break
        if matched is None:
            for c in candidates:
                merchant = c.get("merchant", "").lower()
                if merchant and merchant in user_message.lower():
                    matched = c
                    break

        if matched is None:
            desc = ", ".join(f"{c.get('merchant','?')} (₹{c.get('amount','?')})" for c in candidates)
            answer = f"Sorry, I couldn't tell which one you meant. Options: {desc}."
            self.bus.emit("run.complete", reason="ambiguous_pause", answer=answer)
            return RunResult(answer=answer, reason="ambiguous_pause", steps=1)

        mandate_id = matched.get("mandate_id")

        if "pause" in original_query:
            action_tool_name = "mandate_pause"
        elif "unpause" in original_query or "resume" in original_query:
            action_tool_name = "mandate_unpause"
        else:
            action_tool_name = "mandate_revoke"

        fetch_tool = self.tools.get("mandate_fetch")
        fetch_result = fetch_tool.handler(mandate_id=mandate_id)
        self.bus.emit("tool.call", step=0, name="mandate_fetch", args={"mandate_id": mandate_id}, result=fetch_result)

        action_args = {"mandate_id": mandate_id}
        if action_tool_name == "mandate_pause":
            action_args["till_date"] = "31-12-2026"  # placeholder; a real flow would ask for this

        allowed, action_args, block_reason = self.hooks.run(action_tool_name, action_args)
        if self.session is not None:
            self.session.clear_pending()
        if not allowed:
            self.bus.emit("run.complete", reason="hook_blocked", answer=block_reason)
            return RunResult(answer=_friendly_blocked_message(block_reason), reason="hook_blocked", steps=1)

        action_tool = self.tools.get(action_tool_name)
        action_result = action_tool.handler(**action_args)
        self.bus.emit("tool.call", step=0, name=action_tool_name, args=action_args, result=action_result)

        action_word = action_tool_name.split("_")[1]
        intent_id = action_result.get("intent_id", "")
        intent_link = action_result.get("intent_link", "")
        answer = (f"Your {matched.get('merchant')} mandate is ready to be {action_word}d — "
                  f"tap here to confirm: {intent_link}")
        self.bus.emit("run.complete", reason="resolved_from_pending", answer=answer)
        return RunResult(answer=answer, reason="resolved_from_pending", steps=1,
                          pending_intent_id=intent_id, pending_action=action_word,
                          pending_merchant=matched.get('merchant'))

    def run(self, user_message: str) -> RunResult:
        self.bus.emit("run.start", input=user_message, tools=self.tools.names())
        if self.session is not None:
            self.session.messages.append({"role": "user", "content": user_message})
            
        self.bus.emit("run.start", input=user_message, tools=self.tools.names())

        messages = [{"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_message}]
        tool_results_this_run: list[dict] = []

        for step in range(self.max_steps):
            self.bus.emit("step.start", step=step)

            decision = self.llm.decide(messages, self.tools)
            self.bus.emit("llm.reasoning", step=step, decision=decision)

            # --- Case 1: model is done, gives a plain final answer ---
            if "final" in decision:
                from core.output_hooks import validate_output
                cleaned_answer, issues = validate_output(decision["final"], tool_results_this_run)
                if issues:
                    self.bus.emit("output.validation.flagged", issues=issues)
                self.bus.emit("run.complete", reason="no_tool_calls", answer=cleaned_answer)
                return RunResult(answer=cleaned_answer, reason="no_tool_calls", steps=step + 1)

            # --- Case 2: model wants to call a tool ---
            call = decision["tool_call"]
            name, args = call["name"], call.get("arguments", {})
            self.bus.emit("tool.request", step=step, name=name, arguments=args)

            # Hooks run BEFORE the tool executes — this is the Safety Gateway
            allowed, args, block_reason = self.hooks.run(name, args)
            if not allowed:
                self.bus.emit("run.complete", reason="hook_blocked", answer=block_reason)
                return RunResult(answer=_friendly_blocked_message(block_reason), reason="hook_blocked", steps=step + 1)

            tool = self.tools.get(name)
            if tool is None:
                result = {"error": f"unknown tool '{name}'"}
            else:
                try:
                    result = tool.handler(**args)
                except TypeError:
                    result = {"error": "WrongArguments",
                               "message": f"'{name}' was called with incorrect arguments: {args}"}
            self.bus.emit("tool.call", step=step, name=name, args=args, result=result)
            tool_results_this_run.append(result)

            # --- Ambiguity check: if a search/summary tool returned 2+ matches,
            # first try to auto-narrow using the user's ORIGINAL wording (e.g.
            # they already said "Spotify" — the model just forgot to filter by
            # it). Only pause and ask if genuine ambiguity remains after that. ---
            if isinstance(result, dict) and "matches" in result and len(result.get("matches", [])) > 1:
                narrowed_matches = _narrow_matches_by_query(result["matches"], user_message)

                if len(narrowed_matches) == 1:
                    # Not actually ambiguous — the user already told us which one.
                    # Rewrite the tool result the model sees so it proceeds correctly,
                    # and continue the loop normally instead of pausing.
                    result["matches"] = narrowed_matches
                    self.bus.emit("ambiguity.auto_resolved", narrowed_to=narrowed_matches[0])
                else:
                    if self.session is not None:
                        self.session.set_pending(domain=self.domain_name,
                                                  context={"candidates": narrowed_matches, "original_query": user_message})
                    candidate_desc = ", ".join(
                        f"{m.get('merchant', m.get('mandate_id', '?'))} (₹{m.get('amount', '?')})"
                        for m in narrowed_matches
                    )
                    answer = f"I found more than one match: {candidate_desc}. Which one did you mean?"
                    self.bus.emit("run.complete", reason="ambiguous_pause", answer=answer)
                    return RunResult(answer=answer, reason="ambiguous_pause", steps=step + 1)

            messages.append({"role": "assistant", "content": f"[called {name} with {args}]"})
            messages.append({"role": "tool", "content": str(result)})
            if self.session is not None:
                self.session.messages.append({"role": "tool", "content": str(result)})

            # --- Case 3: that tool was TERMINAL -> ends the run declaratively ---
            if tool is not None and tool.terminal:
                from core.output_hooks import validate_output
                answer = result.get("message", str(result))
                cleaned_answer, issues = validate_output(answer, tool_results_this_run)
                if issues:
                    self.bus.emit("output.validation.flagged", issues=issues)

                pending_intent_id = None
                for r in tool_results_this_run:
                    if isinstance(r, dict) and "intent_id" in r:
                        pending_intent_id = r["intent_id"]

                self.bus.emit("run.complete", reason="terminal_tool", answer=cleaned_answer)
                return RunResult(answer=cleaned_answer, reason="terminal_tool", steps=step + 1,
                                  pending_intent_id=pending_intent_id)

        # --- Case 4: ran out of steps without a final answer or terminal tool ---
        self.bus.emit("run.complete", reason="max_steps", answer=None)
        return RunResult(answer="(max steps reached without a final answer)", reason="max_steps", steps=self.max_steps)