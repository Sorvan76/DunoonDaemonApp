from __future__ import annotations

"""Per-window chat context modes for Dunoon Daemon.

Persona identity is always the same persistent character. The two user-facing axes are:
- remember the prior conversation/session or start a fresh local transcript;
- bring the persona's learned memory vaults into the prompt or keep them out.

Memory *writing* is intentionally separate from memory *reading*. Sandbox is a read-only
character testbox: it receives learned memories but never writes new ones. Bubble is fully
disposable; Canvas can form new memories even though old memories are not injected into that chat.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from copy import deepcopy
import uuid


@dataclass(frozen=True)
class ChatModeSpec:
    key: str
    label: str
    remember_session: bool
    bring_memories: bool
    write_memories: bool
    tagline: str
    description: str


CHAT_MODES = {
    "continuation": ChatModeSpec(
        key="continuation",
        label="Continuation",
        remember_session=True,
        bring_memories=True,
        write_memories=True,
        tagline="Same conversation · Same memories",
        description="Resume the ongoing relationship and conversation. The persona sees the existing session and can draw on learned memories.",
    ),
    "sandbox": ChatModeSpec(
        key="sandbox",
        label="Sandbox",
        remember_session=False,
        bring_memories=True,
        write_memories=False,
        tagline="Fresh testbox · Memories read-only",
        description="Test the fully developed character in a fresh scenario. Learned memories come in, but the transcript is disposable and nothing that happens here is written back to long-term memory.",
    ),
    "canvas": ChatModeSpec(
        key="canvas",
        label="Canvas",
        remember_session=True,
        bring_memories=False,
        write_memories=True,
        tagline="Same conversation · Memories withheld",
        description="Continue the existing conversation without retrieving the long-term memory vaults. New experiences may still become future memories.",
    ),
    "bubble": ChatModeSpec(
        key="bubble",
        label="Bubble",
        remember_session=False,
        bring_memories=False,
        write_memories=False,
        tagline="Fresh conversation · No memory",
        description="A sealed disposable chat. The persona and OCEAN profile remain intact, but prior transcript and learned memories stay out and nothing from this chat is added to long-term memory.",
    ),
}


def get_chat_mode(key: str | None) -> ChatModeSpec:
    return CHAT_MODES.get(str(key or "continuation").strip().lower(), CHAT_MODES["continuation"])


class ChatSessionView:
    """A per-window view of one persistent persona/session.

    The view always owns a local transcript so even Sandbox/Bubble remain coherent while the
    window is open. When the selected mode remembers the session, accepted local messages are
    mirrored into the canonical Session and persisted by SessionManager.
    """

    _LOCAL_FIELDS = {
        "_base_session", "_session_manager", "chat_mode", "chat_mode_key", "messages",
        "history_read_enabled", "history_write_enabled", "memory_read_enabled",
        "memory_write_enabled", "memory_session_id", "scene_state_id", "session_manager",
        "window", "fresh_scene", "_narrative_freedom_override", "_transient_location", "_transient_threat", "_transient_opportunity",
        "_transient_is_deceased",
    }

    _PERSISTENT_PERSONA_FIELDS = {
        "name", "private", "system_prompt", "agent_name", "ocean_profile", "primacy_count",
        "primacy_enabled", "backend", "model_path", "psychology_mode", "share_insights",
        "blind_to_others", "backstory", "eto_enabled", "mortality_enabled", "physiology",
        "powers", "narrative_freedom", "last_mood_update", "avatar_path", "showcase_quote", "pinned_quotes", "voice_mode",
    }

    _TRANSIENT_SCENE_FIELDS = {"location", "threat", "opportunity", "is_deceased"}

    def __init__(self, base_session, session_manager, mode: ChatModeSpec | str = "continuation"):
        spec = get_chat_mode(mode if isinstance(mode, str) else mode.key)
        object.__setattr__(self, "_base_session", base_session)
        object.__setattr__(self, "_session_manager", session_manager)
        object.__setattr__(self, "chat_mode", spec)
        object.__setattr__(self, "chat_mode_key", spec.key)
        object.__setattr__(self, "history_read_enabled", spec.remember_session)
        object.__setattr__(self, "history_write_enabled", spec.remember_session)
        object.__setattr__(self, "memory_read_enabled", spec.bring_memories)
        object.__setattr__(self, "memory_write_enabled", spec.write_memories)
        object.__setattr__(self, "memory_session_id", str(getattr(base_session, "id", None) or getattr(base_session, "session_id", "")))
        object.__setattr__(self, "session_manager", session_manager)
        object.__setattr__(self, "window", None)
        object.__setattr__(self, "fresh_scene", not spec.remember_session)
        object.__setattr__(self, "_narrative_freedom_override", None)

        if spec.remember_session:
            initial_messages = deepcopy(getattr(base_session, "messages", []) or [])
            scene_id = f"persona:{self.memory_session_id}:continuation"
        else:
            initial_messages = []
            scene_id = f"persona:{self.memory_session_id}:{spec.key}:{uuid.uuid4().hex}"
        object.__setattr__(self, "messages", initial_messages)
        object.__setattr__(self, "scene_state_id", scene_id)
        object.__setattr__(self, "_transient_location", getattr(base_session, "location", "") if spec.remember_session else "")
        object.__setattr__(self, "_transient_threat", getattr(base_session, "threat", "") if spec.remember_session else "")
        object.__setattr__(self, "_transient_opportunity", getattr(base_session, "opportunity", "") if spec.remember_session else "")
        object.__setattr__(self, "_transient_is_deceased", bool(getattr(base_session, "is_deceased", False)) if spec.remember_session else False)

    @property
    def id(self):
        # Backward compatibility: memory/vault code historically keys on session.id.
        return self.memory_session_id

    @property
    def session_id(self):
        return self.memory_session_id

    @property
    def base_session(self):
        return self._base_session

    def __getattr__(self, name):
        if name == "narrative_freedom":
            override = object.__getattribute__(self, "_narrative_freedom_override")
            if override is not None:
                return bool(override)
            return bool(getattr(self._base_session, "narrative_freedom", False))
        if name == "location":
            return self._transient_location
        if name == "threat":
            return self._transient_threat
        if name == "opportunity":
            return self._transient_opportunity
        if name == "is_deceased":
            return self._transient_is_deceased
        return getattr(self._base_session, name)

    def __setattr__(self, name, value):
        if name in self._LOCAL_FIELDS or name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        if name in self._PERSISTENT_PERSONA_FIELDS:
            setattr(self._base_session, name, value)
            if self._session_manager and hasattr(self._session_manager, "_save"):
                self._session_manager._save()
            return
        if name in self._TRANSIENT_SCENE_FIELDS:
            object.__setattr__(self, f"_transient_{name}", value)
            if self.history_write_enabled:
                setattr(self._base_session, name, value)
                if self._session_manager and hasattr(self._session_manager, "_save"):
                    self._session_manager._save()
            return
        object.__setattr__(self, name, value)

    def _append_local(self, role: str, text: str):
        self.messages.append({
            "role": role,
            "text": str(text),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def _append(self, role: str, text: str):
        self._append_local(role, text)
        if self.history_write_enabled:
            if role == "user":
                self._base_session.append_user(text)
            elif role == "assistant":
                self._base_session.append_roxie(text)
            else:
                self._base_session.append_system(text)

    def append_user(self, text):
        self._append("user", text)

    def append_roxie(self, text):
        self._append("assistant", text)

    def append_system(self, text):
        self._append("system", text)

    def get_history(self, limit=12):
        history = []
        for m in self.messages[-limit:]:
            if not isinstance(m, dict):
                continue
            role = str(m.get("role", "user") or "user").lower()
            if role in ("roxie", "kylo", "agent", "assistant", str(getattr(self, "agent_name", "")).lower()):
                role = "assistant"
            elif role != "system":
                role = "user"
            text = m.get("text") or m.get("content") or ""
            if str(text).strip():
                history.append({"role": role, "content": str(text).strip()})
        return history

    def set_narrative_freedom_override(self, value):
        """Override Narrative Freedom for this chat only; None inherits the persona default."""
        object.__setattr__(self, "_narrative_freedom_override", None if value is None else bool(value))

    def narrative_freedom_source(self) -> str:
        return "persona" if self._narrative_freedom_override is None else "chat override"

    def describe_mode(self) -> str:
        return self.chat_mode.tagline
