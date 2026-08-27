# memory_working.py — Thread-Safe, Session-Scoped Working Memory Store
import json
import os
import threading
from config import get_session_vault_paths, BASE_DIR, ensure_dirs
from memory_semantics import semantic_rank
from memory_transactions import memory_transaction, load_json, atomic_save_json

ensure_dirs()
WORKING_MAX_ENTRIES = 800

_working_lock = threading.RLock()

def _get_path(session_id: str = None) -> str:
    if session_id:
        return get_session_vault_paths(session_id)["working_memory"]
    fallback_dir = os.path.join(BASE_DIR, "data", "sessions", "default_session", "vaults")
    os.makedirs(fallback_dir, exist_ok=True)
    return os.path.join(fallback_dir, "working_memory.json")

def _load_file(path: str) -> list:
    data = load_json(path, [])
    return data if isinstance(data, list) else []

def _save_file(path: str, items: list):
    return atomic_save_json(path, items)

def save_working_memory_raw(text: str, session_id: str = None):
    """Saves a string memory entry with thread locking, atomic writes, and primary-model semantic retrieval."""
    if not text or not str(text).strip():
        return

    clean_text = str(text).strip()
    path = _get_path(session_id)

    with memory_transaction(session_id), _working_lock:
        memories = _load_file(path)

        # Normalize existing entries to string format for uniform deduplication
        existing_strings = [
            m.get("text", "") if isinstance(m, dict) else str(m)
            for m in memories
        ]

        if clean_text not in existing_strings:
            memories.append(clean_text)
            memories = memories[-WORKING_MAX_ENTRIES:]
            _save_file(path, memories)


def save_working_memory(text: str, session_id: str = None):
    """Primary alias for save_working_memory_raw."""
    save_working_memory_raw(text, session_id=session_id)

def load_working_memory(session_id: str = None, limit: int = 50) -> list:
    """Thread-safe disk read of the active session's working memories."""
    path = _get_path(session_id)
    with memory_transaction(session_id), _working_lock:
        memories = _load_file(path)
        return memories[-limit:]

def retrieve_relevant_working_memories(query: str, session_id: str = None, top_k: int = 5) -> list:
    """Reads directly from disk to prevent stale caching and runs semantic similarity scoring."""
    path = _get_path(session_id)
    with memory_transaction(session_id), _working_lock:
        memories = _load_file(path)

    clean_memories = [
        m.get("text", "") if isinstance(m, dict) else str(m)
        for m in memories
        if m
    ]

    if not clean_memories:
        return []

    return semantic_rank(query, clean_memories, top_k=top_k)