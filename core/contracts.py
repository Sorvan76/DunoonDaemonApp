from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class SourceKind(str, Enum):
    """Where a turn originated. Authority is decided by the TurnEngine/Scene layer, not UI text."""

    USER = "user"
    ARENA_PEER = "arena_peer"
    LIVE_EVENT = "live_event"
    SYSTEM_EVENT = "system_event"
    INTERNAL_CONTROL = "internal_control"
    RELATIONSHIP_SUMMARY = "relationship_summary"

    @classmethod
    def coerce(cls, value: str | "SourceKind" | None) -> "SourceKind":
        if isinstance(value, cls):
            return value
        raw = str(value or cls.USER.value).strip().lower()
        try:
            return cls(raw)
        except ValueError:
            return cls.USER


@dataclass(slots=True)
class TurnRequest:
    text: str
    session: Any
    source: SourceKind = SourceKind.USER
    commit_lifecycle: bool = True


@dataclass(slots=True)
class TurnResult:
    text: str
    raw_text: str
    source: SourceKind
    finish_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_error(self) -> bool:
        return self.text.startswith("(Native model backend") or self.text.startswith("(Model backend")
