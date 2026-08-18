# prune.py — Session Vault Capacity Engine & Dynamic Memory Consolidation
import json
import os
import re
from config import WORKING_MAX_ENTRIES, DEEP_MAX_ENTRIES, get_session_vault_paths

INTENT_MAX = 400
TASK_MAX = 400
FACTUAL_MAX = 1000
CONTINUATION_MAX = 600
RESET_MAX = 200
PRUNE_TELEMETRY_MAX = 1000

def _load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []

def _save(path, items):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except Exception: pass

def _clean_list(items):
    cleaned = []
    seen = set()
    for m in items:
        if not isinstance(m, str):
            continue
        m = m.strip()
        if not m or m in seen:
            continue
        seen.add(m)
        cleaned.append(m)
    return cleaned

def prune_session_vaults(session_id: str):
    if not session_id:
        return

    paths = get_session_vault_paths(session_id)

    working      = _clean_list(_load(paths["working_memory"]))[-WORKING_MAX_ENTRIES:]
    deep         = _clean_list(_load(paths["deep_memory"]))[-DEEP_MAX_ENTRIES:]
    intent       = _clean_list(_load(paths["intent_memory"]))[-INTENT_MAX:]
    task         = _clean_list(_load(paths["task_memory"]))[-TASK_MAX:]
    factual      = _clean_list(_load(paths["factual_memory"]))[-FACTUAL_MAX:]
    continuation = _clean_list(_load(paths["continuation_memory"]))[-CONTINUATION_MAX:]
    reset        = _clean_list(_load(paths["reset_memory"]))[-RESET_MAX:]
    telemetry    = _clean_list(_load(paths["prune_telemetry"]))[-PRUNE_TELEMETRY_MAX:]

    _save(paths["working_memory"], working)
    _save(paths["deep_memory"], deep)
    _save(paths["intent_memory"], intent)
    _save(paths["task_memory"], task)
    _save(paths["factual_memory"], factual)
    _save(paths["continuation_memory"], continuation)
    _save(paths["reset_memory"], reset)
    _save(paths["prune_telemetry"], telemetry)

def prune_vaults(session_id: str = None):
    if session_id:
        prune_session_vaults(session_id)

def parse_model_b_parameter(model_identifier: str = "") -> int:
    if not model_identifier:
        return 31
        
    match = re.search(r'(\d+)\s*b', model_identifier.lower())
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
            
    return 31

def get_dynamic_working_threshold(session) -> int:
    model_name = getattr(session, "model_name", "") or getattr(session, "active_model", "")
    b_val = parse_model_b_parameter(model_name)
    return max(16, min(150, b_val * 2))

def run_session_sleep_cycle(session, threshold: int = None):
    session_id = getattr(session, "id", None) or getattr(session, "session_id", None)
    if not session_id:
        return

    if threshold is None:
        threshold = get_dynamic_working_threshold(session)

    paths = get_session_vault_paths(session_id)
    working_items = _load(paths["working_memory"])

    if len(working_items) < threshold:
        return

    slice_to_summarize = working_items[:-10]
    raw_text_block = "\n".join(slice_to_summarize)

    prompt = (
        "Summarize the following conversation logs into 2-3 concise, high-value episodic journal notes. "
        "Focus ONLY on key personal facts, decisions, emotional shifts, or character developments. "
        "Omit pleasantries and routine chit-chat.\n\n"
        f"LOGS:\n{raw_text_block}"
    )

    try:
        from overmind import neutral_summarize
        from memory_deep import save_deep_memory_journal

        model_handler = getattr(getattr(session, "brain", None), "model_handler", None)
        summary = neutral_summarize(prompt, model_handler=model_handler)

        if summary and not summary.startswith("("):
            save_deep_memory_journal(
                f"[Consolidated Memory]: {summary.strip()}",
                session_id=session_id
            )

            recent_turns = working_items[-10:]
            _save(paths["working_memory"], recent_turns)
            print(f"[Sleep Cycle] Consolidated {len(slice_to_summarize)} entries for session '{session_id}' (Dynamic Threshold: {threshold}).")

    except Exception as e:
        print(f"[Sleep Cycle Error] Failed consolidation for '{session_id}': {e}")