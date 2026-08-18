# journal_vault.py — Thread-Safe, Session-Scoped Journal Storage
import os
import json
import threading
from typing import List
from journal_entry import JournalEntry
from config import get_session_vault_dir, BASE_DIR, ensure_dirs

ensure_dirs()
MAX_JOURNAL_ENTRIES = 1000

_journal_lock = threading.Lock()

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
    os.makedirs(os.path.dirname(target_file), exist_ok=True)
    tmp_path = f"{target_file}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, target_file)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

def _load_journal(session=None) -> List[dict]:
    target_file = _resolve_journal_path(session)
    if not os.path.exists(target_file):
        return []
    try:
        with open(target_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []

def add_journal_entry(entry: JournalEntry, session=None):
    with _journal_lock:
        entries = _load_journal(session)
        entries = [e for e in entries if isinstance(e, dict) and e.get("id") != getattr(entry, "id", None)]
        entry_data = entry.to_dict() if hasattr(entry, "to_dict") else dict(entry)
        entries.append(entry_data)
        _save_journal(entries, session)

def get_all_journal_entries(session=None) -> List[JournalEntry]:
    with _journal_lock:
        entries = _load_journal(session)
        results = []
        for e in entries:
            if isinstance(e, dict):
                try:
                    results.append(JournalEntry(**e))
                except Exception:
                    pass
        return results