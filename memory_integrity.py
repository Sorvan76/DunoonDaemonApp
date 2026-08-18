# memory_integrity.py — Session-Aware Vault Integrity Sanitizer
import json
import os
from config import (
    WORKING_MEMORY_FILE,
    DEEP_MEMORY_FILE,
    INTENT_MEMORY_FILE,
    TASK_MEMORY_FILE,
    FACTUAL_MEMORY_FILE,
    CONTINUATION_MEMORY_FILE,
    RESET_MEMORY_FILE,
    PRUNE_TELEMETRY_FILE,
    get_session_vault_paths,
    ensure_dirs
)

ensure_dirs()

def _load_safe(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []

def _save_safe(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(f"{path}.tmp"):
            try: os.remove(f"{path}.tmp")
            except Exception: pass

def _clean_memory_list(mem_list):
    """Sanitize memories without silently deleting supported structured entries."""
    cleaned = []
    seen = set()
    for m in mem_list:
        if isinstance(m, str):
            text = m.strip()
            if not text or len(text) > 1000 or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        elif isinstance(m, dict):
            text = str(m.get("text", "")).strip()
            if not text or len(text) > 1000 or text in seen:
                continue
            seen.add(text)
            clean_entry = dict(m)
            clean_entry["text"] = text
            cleaned.append(clean_entry)
    return cleaned

def check_memory_integrity(session_id: str = None):
    """Run integrity checks on all vaults for a specific session or global fallback."""
    if session_id:
        v_paths = get_session_vault_paths(session_id)
        vault_paths = {
            "working": v_paths["working_memory"],
            "deep": v_paths["deep_memory"],
            "intent": v_paths["intent_memory"],
            "task": v_paths["task_memory"],
            "factual": v_paths["factual_memory"],
            "continuation": v_paths["continuation_memory"],
            "reset": v_paths["reset_memory"],
            "prune_telemetry": v_paths["prune_telemetry"],
        }
    else:
        vault_paths = {
            "working": WORKING_MEMORY_FILE,
            "deep": DEEP_MEMORY_FILE,
            "intent": INTENT_MEMORY_FILE,
            "task": TASK_MEMORY_FILE,
            "factual": FACTUAL_MEMORY_FILE,
            "continuation": CONTINUATION_MEMORY_FILE,
            "reset": RESET_MEMORY_FILE,
            "prune_telemetry": PRUNE_TELEMETRY_FILE,
        }

    report = {}
    for name, path in vault_paths.items():
        before = _load_safe(path)
        after = _clean_memory_list(before)
        _save_safe(path, after)
        report[name] = {
            "before": len(before),
            "after": len(after),
        }
    return report