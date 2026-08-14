"""Structured event bus — every loop/tool/hook decision gets logged here.
This is what lets us SEE the architecture working, step by step.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid


@dataclass
class Event:
    type: str
    data: dict
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EventBus:
    def __init__(self):
        self.run_id: str = str(uuid.uuid4())[:8]   # short id to identify this run in logs
        self.events: list[Event] = []

    def emit(self, type_: str, **data: Any):
        """Record an event and print it live so you can watch the run happen."""
        e = Event(type=type_, data=data)
        self.events.append(e)
        print(f"[{self.run_id}] {e.type:<22} {e.data}")

    def trace(self) -> list[dict]:
        """Return the full run as a replayable list of dicts — like a .jsonl trace file."""
        return [{"type": e.type, "data": e.data, "ts": e.ts} for e in self.events]