# memory_api.py — Session Ingestion & Retrieval Gateway
from memory_validation import validate_memory
from memory_working import (
    save_working_memory_raw,
    load_working_memory as _load_working_mem,
    retrieve_relevant_working_memories,
)
from memory_deep import (
    save_deep_memory_raw,
    save_deep_memory_journal,
    load_deep_memory as _load_deep_mem,
    retrieve_relevant_deep_memories,
)
from prune import prune_vaults
from config import ensure_dirs

ensure_dirs()


def save_working_memory(text: str, session_id: str = None):
    """Validates, persists to session working memory, and triggers prune telemetry."""
    if validate_memory(text):
        save_working_memory_raw(text, session_id=session_id)
        try:
            prune_vaults(session_id=session_id)
        except Exception as e:
            print(f"[Memory API Warning] Pruning error on working save: {e}")


def save_deep_memory(text: str, session_id: str = None, as_journal: bool = False):
    """Validates, persists to session deep memory/journal, and triggers prune telemetry."""
    if validate_memory(text):
        if as_journal:
            save_deep_memory_journal(text, session_id=session_id)
        else:
            save_deep_memory_raw(text, session_id=session_id)
        try:
            prune_vaults(session_id=session_id)
        except Exception as e:
            print(f"[Memory API Warning] Pruning error on deep save: {e}")


def load_working_memory(session_id: str = None, limit: int = 20) -> list:
    """Thread-safe delegated read directly from the session vault."""
    try:
        return _load_working_mem(session_id=session_id, limit=limit)
    except Exception as e:
        print(f"[Memory API Warning] Could not load working memory: {e}")
        return []


def load_deep_memory(session_id: str = None, limit: int = 50) -> list:
    """Thread-safe delegated read from deep memory."""
    try:
        return _load_deep_mem(session_id=session_id, limit=limit)
    except Exception as e:
        print(f"[Memory API Warning] Could not load deep memory: {e}")
        return []


def fetch_working_memories(session_id: str = None, limit: int = 20) -> list:
    """Alias for load_working_memory."""
    return load_working_memory(session_id=session_id, limit=limit)


def search_working_memories(query: str, session_id: str = None, top_k: int = 5) -> list:
    """Delegated vector semantic search on session working memory."""
    return retrieve_relevant_working_memories(query, session_id=session_id, top_k=top_k)


def search_deep_memories(query: str, session_id: str = None, top_k: int = 5) -> list:
    """Delegated vector semantic search on session deep memory."""
    return retrieve_relevant_deep_memories(query, session_id=session_id, top_k=top_k)