# vault_auto_repair.py — Automated Multi-Tier & Session Vault Healer
import os
import json
from config import (
    WORKING_MEMORY_FILE,
    DEEP_MEMORY_FILE,
    INTENT_MEMORY_FILE,
    TASK_MEMORY_FILE,
    FACTUAL_MEMORY_FILE,
    CONTINUATION_MEMORY_FILE,
    RESET_MEMORY_FILE,
    PRUNE_TELEMETRY_FILE,
    SESSIONS_DIR,
    get_session_vault_paths,
    ensure_dirs
)

def _repair_file_list(path: str):
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f)
    else:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, list):
                    raise ValueError("Invalid format")
        except Exception:
            with open(path, "w", encoding="utf-8") as f:
                json.dump([], f)

def _repair_file_dict(path: str):
    """Repair JSON stores that are expected to be dictionaries (e.g. embeddings)."""
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({}, f)
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Invalid dictionary format")
    except Exception:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({}, f)

def repair_vaults(session_id: str = None):
    ensure_dirs()
    
    if session_id:
        v_paths = get_session_vault_paths(session_id)
        for key, p in v_paths.items():
            if isinstance(p, str) and p.endswith(".json"):
                if key == "embeddings":
                    _repair_file_dict(p)
                else:
                    _repair_file_list(p)
        return

    # 1. Repair Global Vault Fallbacks
    global_paths = [
        WORKING_MEMORY_FILE,
        DEEP_MEMORY_FILE,
        INTENT_MEMORY_FILE,
        TASK_MEMORY_FILE,
        FACTUAL_MEMORY_FILE,
        CONTINUATION_MEMORY_FILE,
        RESET_MEMORY_FILE,
        PRUNE_TELEMETRY_FILE,
    ]
    for path in global_paths:
        _repair_file_list(path)

    # 2. Repair All Active Session Sub-Vaults
    if os.path.exists(SESSIONS_DIR):
        for item in os.listdir(SESSIONS_DIR):
            sess_dir = os.path.join(SESSIONS_DIR, item)
            if os.path.isdir(sess_dir):
                s_paths = get_session_vault_paths(item)
                for key, p in s_paths.items():
                    if isinstance(p, str) and p.endswith(".json"):
                        if key == "embeddings":
                            _repair_file_dict(p)
                        else:
                            _repair_file_list(p)

if __name__ == "__main__":
    repair_vaults()
    print("[VaultAutoRepair] All session and global memory vaults verified and healed.")