"""Session state — lets a conversation persist across separate runs.
This is the mechanism behind the earlier finding: when a query is
ambiguous, the agent stops completely (run.complete) and the user's
reply starts a BRAND NEW run. Session is what connects the two.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import uuid


@dataclass
class Session:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    messages: list[dict] = field(default_factory=list)      # full history, every turn
    pending_domain: str | None = None                        # e.g. "mandate" - set when we're mid-task
    pending_context: dict = field(default_factory=dict)      # e.g. {"candidates": [...]} while waiting on user

    def add_user_message(self, content: str):
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str):
        self.messages.append({"role": "assistant", "content": content})

    def set_pending(self, domain: str, context: dict):
        """Called when a run stops mid-task waiting for the user (e.g. ambiguous match)."""
        self.pending_domain = domain
        self.pending_context = context

    def clear_pending(self):
        """Called once the pending task is resolved (or abandoned)."""
        self.pending_domain = None
        self.pending_context = {}

    def has_pending_task(self) -> bool:
        return self.pending_domain is not None


# In-memory store, keyed by session_id. In the real framework this would be
# saved to disk (--resume flag). For our mini version, a dict is enough.
_SESSIONS: dict[str, Session] = {}


def get_or_create_session(session_id: str | None) -> Session:
    if session_id and session_id in _SESSIONS:
        return _SESSIONS[session_id]
    s = Session(session_id=session_id or str(uuid.uuid4())[:8])
    _SESSIONS[s.session_id] = s
    return s