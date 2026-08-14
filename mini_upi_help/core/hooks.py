"""Pre-tool hooks — the Safety Gateway.
A hook runs BEFORE a tool executes and can block it.
This is where DETERMINISTIC rules live, instead of hoping the prompt
reminds the model to check them every time.
"""
from __future__ import annotations
from typing import Callable


# A hook is a function: (tool_name, arguments) -> (allowed, possibly_modified_args, reason_if_blocked)
HookFn = Callable[[str, dict], tuple[bool, dict, str | None]]


class ToolHookBus:
    def __init__(self, bus):
        self.bus = bus
        self._hooks: list[HookFn] = []

    def register(self, hook: HookFn):
        self._hooks.append(hook)

    def run(self, tool_name: str, arguments: dict) -> tuple[bool, dict, str | None]:
        """Run every registered hook in order. First one to block wins."""
        args = arguments
        for hook in self._hooks:
            allowed, args, reason = hook(tool_name, args)
            if not allowed:
                self.bus.emit("tool.hook.blocked", tool=tool_name, reason=reason)
                return False, args, reason
            if args != arguments:
                self.bus.emit("tool.hook.modified", tool=tool_name, args=args)
        return True, args, None