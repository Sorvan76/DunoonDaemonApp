# memory_deep.py — Session-Scoped Deep Memory & Primacy Engine
import json
import os
import threading
from config import get_session_vault_paths, BASE_DIR, ensure_dirs
from memory_semantics import semantic_rank
from memory_transactions import memory_transaction, load_json, atomic_save_json
from journal_vault import add_journal_entry
from journal_entry import JournalEntry, make_journal_id, now_iso
from significance import score_significance

ensure_dirs()
DEEP_MAX_ENTRIES = 1000

_deep_lock = threading.RLock()

def _get_path(session_id: str = None) -> str:
    if session_id:
        return get_session_vault_paths(session_id)["deep_memory"]
    fallback_dir = os.path.join(BASE_DIR, "data", "sessions", "default_session", "vaults")
    os.makedirs(fallback_dir, exist_ok=True)
    return os.path.join(fallback_dir, "deep_memory.json")

def _load_file(path: str) -> list:
    data = load_json(path, [])
    return data if isinstance(data, list) else []

def _save_file(path: str, items: list):
    return atomic_save_json(path, items)

def save_deep_memory_raw(text: str, session_id: str = None):
    """Saves a string entry into session-scoped deep memory with thread lock and primary-model semantic judgement."""
    if not text or not str(text).strip():
        return

    clean_text = str(text).strip()
    path = _get_path(session_id)

    with memory_transaction(session_id), _deep_lock:
        memories = _load_file(path)

        existing_strings = [
            m.get("text", "") if isinstance(m, dict) else str(m)
            for m in memories
        ]

        if clean_text not in existing_strings:
            memories.append(clean_text)
            memories = memories[-DEEP_MAX_ENTRIES:]
            _save_file(path, memories)


def save_deep_memory_journal(text: str, session_id: str = None, primacy_count: int = 0, primacy_enabled: bool = True):
    """Score and commit journal + deep memory as one persona-scoped transaction."""
    if not text or not str(text).strip():
        return

    clean_text = str(text).strip()
    with memory_transaction(session_id):
        significance = score_significance(clean_text, session_id=session_id)
        if primacy_enabled and primacy_count > 100 and significance < 0.6:
            return

        entry = JournalEntry(
            id=make_journal_id(clean_text),
            text=clean_text,
            summary=clean_text,
            timestamp=now_iso(),
            tags=["deep"],
            significance=significance,
        )

        try:
            add_journal_entry(entry, session=session_id)
        except Exception as e:
            print(f"[Journal Vault Warning]: {e}")
        save_deep_memory_raw(clean_text, session_id=session_id)

def load_deep_memory(session_id: str = None, limit: int = 50) -> list:
    """Thread-safe disk read of the active session's deep memories."""
    path = _get_path(session_id)
    with memory_transaction(session_id), _deep_lock:
        memories = _load_file(path)
        return memories[-limit:]

def retrieve_relevant_deep_memories(query: str, session_id: str = None, top_k: int = 5) -> list:
    """Reads directly from session disk to run semantic similarity scoring."""
    path = _get_path(session_id)
    with memory_transaction(session_id), _deep_lock:
        memories = _load_file(path)

    clean_memories = [
        m.get("text", "") if isinstance(m, dict) else str(m)
        for m in memories
        if m
    ]

    if not clean_memories:
        return []

    return semantic_rank(query, clean_memories, top_k=top_k)