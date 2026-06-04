"""In-memory conversation history scoped by session_id."""
from collections import defaultdict
from typing import TypedDict


class Message(TypedDict):
    role: str      # "user" | "assistant"
    content: str


_store: dict[str, list[Message]] = defaultdict(list)
_MAX_HISTORY = 10  # keep last 10 messages (5 turns) to bound context size


def get(session_id: str) -> list[Message]:
    return list(_store[session_id][-_MAX_HISTORY:])


def append(session_id: str, role: str, content: str) -> None:
    _store[session_id].append({"role": role, "content": content})


def clear(session_id: str) -> None:
    _store.pop(session_id, None)
