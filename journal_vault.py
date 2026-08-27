# journal_vault.py — Thread-Safe, Session-Scoped Journal Storage
import os
import json
import threading
from typing import List
from journal_entry import JournalEntry
from config import get_session_vault_dir, BASE_DIR, ensure_dirs
from memory_transactions import memory_transaction, load_json, atomic_save_json

ensure_dirs()
MAX_JOURNAL_ENTRIES = 1000

_journal_lock = threading.RLock()

def _resolve_journal_path(session=None) -> str:
    """Resolves the journal path for active session UUID or fallback."""
    if isinstance(session, str):
        session_id = session.strip()
    else:
        session_id = getattr(session, "session_id", None) or getattr(session, "id", None)
        
    if session_id:
        v_dir = get_session_vault_dir(str(session_id))
        return os.path.join(v_dir, "journal_vault.json")
        
    fallback_dir = os.path.join(BASE_DIR, "data", "sessions", "default_session", "vaults")
    os.makedirs(fallback_dir, exist_ok=True)
    return os.path.join(fallback_dir, "journal_vault.json")

def _save_journal(entries: List[dict], session=None):
    if len(entries) > MAX_JOURNAL_ENTRIES:
        entries = entries[-MAX_JOURNAL_ENTRIES:]
    target_file = _resolve_journal_path(session)
    return atomic_save_json(target_file, entries)

def _load_journal(session=None) -> List[dict]:
    target_file = _resolve_journal_path(session)
    data = load_json(target_file, [])
    return data if isinstance(data, list) else []

def add_journal_entry(entry: JournalEntry, session=None):
    sid = session if isinstance(session, str) else (getattr(session, "session_id", None) or getattr(session, "id", None))
    with memory_transaction(sid), _journal_lock:
        entries = _load_journal(session)
        entries = [e for e in entries if isinstance(e, dict) and e.get("id") != getattr(entry, "id", None)]
        entry_data = entry.to_dict() if hasattr(entry, "to_dict") else dict(entry)
        entries.append(entry_data)
        _save_journal(entries, session)

def get_all_journal_entries(session=None) -> List[JournalEntry]:
    sid = session if isinstance(session, str) else (getattr(session, "session_id", None) or getattr(session, "id", None))
    with memory_transaction(sid), _journal_lock:
        entries = _load_journal(session)
        results = []
        for e in entries:
            if isinstance(e, dict):
                try:
                    results.append(JournalEntry(**e))
                except Exception:
                    pass
        return results