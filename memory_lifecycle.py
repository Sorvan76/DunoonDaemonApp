from __future__ import annotations

"""Persona-scoped memory inspection and destructive purge helpers."""

import json
import os
from typing import Dict

from config import get_session_vault_paths
from memory_transactions import memory_transaction, load_json, atomic_save_json, bump_memory_generation


_LIST_VAULT_KEYS = (
    "working_memory", "deep_memory", "journal_memory", "intent_memory", "task_memory",
    "factual_memory", "superseded_memory", "continuation_memory", "reset_memory", "prune_telemetry",
)


def _read_count(path: str) -> int:
    data = load_json(path, [])
    return len(data) if isinstance(data, (list, dict)) else 0


def persona_memory_counts(session_id: str) -> Dict[str, int]:
    paths = get_session_vault_paths(str(session_id))
    result = {key: _read_count(paths[key]) for key in _LIST_VAULT_KEYS}
    result["embeddings"] = _read_count(paths["embeddings"])
    return result


def _atomic_json(path: str, value) -> None:
    if not atomic_save_json(path, value):
        raise OSError(f"Failed to save memory vault: {path}")


def purge_persona_memories(session_id: str) -> Dict[str, int]:
    """Clear learned memory vaults for exactly one persona/session id.

    Persona definition, OCEAN profile and conversation transcript are intentionally untouched.
    """
    sid = str(session_id)
    with memory_transaction(sid):
        bump_memory_generation(sid)
        before = persona_memory_counts(sid)
        paths = get_session_vault_paths(sid)
        for key in _LIST_VAULT_KEYS:
            _atomic_json(paths[key], [])
        _atomic_json(paths["embeddings"], {})
        return before


def is_runtime_artifact(text: str) -> bool:
    """Software/runtime notices are not experiences the persona should learn as memories."""
    value = str(text or "").strip().casefold()
    if not value:
        return True
    prefixes = (
        "(native model backend unavailable:",
        "(native model backend failed",
        "(error talking to ",
        "(model backend unavailable",
    )
    fragments = (
        "returned no usable response",
        "completed turn, but returned an empty response",
        "press ⏩ continue to retry",
        "press continue to retry",
    )
    return value.startswith(prefixes) or any(frag in value for frag in fragments)
