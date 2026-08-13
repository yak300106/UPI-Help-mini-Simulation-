"""Tool registry — name -> ToolDefinition, with domain-based filtering.
This file is 100% generic. It has no idea what a "mandate" or "FAQ" is —
the real tools get registered into it from domains/*.py, next.
"""
from __future__ import annotations
from core.types import ToolDefinition


class ToolRegistry:
    def __init__(self, tools: list[ToolDefinition] | None = None):
        self._tools: dict[str, ToolDefinition] = {}
        for t in (tools or []):
            self.register(t)

    def register(self, tool: ToolDefinition):
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def all(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def filter_by_domain(self, domain: str) -> "ToolRegistry":
        """This is literally what 'the Router picks a domain' means mechanically:
        return a smaller registry containing only that domain's tools.
        """
        return ToolRegistry([t for t in self._tools.values() if t.domain == domain])

    def openai_schemas(self) -> list[dict]:
        """Convert our ToolDefinitions into the JSON schema format an LLM API expects."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]