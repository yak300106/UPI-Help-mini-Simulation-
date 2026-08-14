"""Real LLM adapter — talks to a real model (here, local Ollama) using the
same .decide(messages, tools) -> dict interface as ScriptedMockLLM, so
NOTHING else in core/loop.py needs to change to use this instead of the mock.
"""
from __future__ import annotations
import json
from openai import OpenAI


class RealLLM:
    def __init__(self, model: str = "llama3.2", base_url: str = "http://localhost:11434/v1"):
        # Ollama doesn't need a real API key, but the client requires SOMETHING non-empty
        self.client = OpenAI(base_url=base_url, api_key="ollama")
        self.model = model

    def decide(self, messages: list[dict], tools) -> dict:
        """tools is our ToolRegistry — convert it to OpenAI's schema format,
        call the model, and translate its response back into the same shape
        ScriptedMockLLM uses: {"tool_call": {...}} or {"final": "..."}.
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools.openai_schemas(),
        )
        msg = response.choices[0].message

        if msg.tool_calls:
            call = msg.tool_calls[0]   # only handle the first tool call per step, same as our loop expects
            try:
                arguments = json.loads(call.function.arguments)
            except json.JSONDecodeError:
                arguments = {}
            return {"tool_call": {"name": call.function.name, "arguments": arguments}}

        return {"final": msg.content or ""}