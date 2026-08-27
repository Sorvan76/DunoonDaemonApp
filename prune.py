# prune.py — Session Vault Capacity Engine & Dynamic Memory Consolidation
from __future__ import annotations

import os
import threading
from collections import Counter

from config import WORKING_MAX_ENTRIES, DEEP_MAX_ENTRIES, get_session_vault_paths
from memory_transactions import memory_transaction, load_json, atomic_save_json, get_memory_generation

INTENT_MAX = 400
TASK_MAX = 400
FACTUAL_MAX = 1000
CONTINUATION_MAX = 600
RESET_MAX = 200
PRUNE_TELEMETRY_MAX = 1000

_SLEEP_GUARD = threading.Lock()
_SLEEP_INFLIGHT: set[str] = set()


def _load(path):
    data = load_json(path, [])
    return data if isinstance(data, list) else []


def _save(path, items):
    return atomic_save_json(path, items)


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
    with memory_transaction(session_id):
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


def get_dynamic_working_threshold(session) -> int:
    """Choose memory-consolidation cadence from actual GGUF size when available."""
    path = str(getattr(session, "model_path", "") or "")
    try:
        if path and os.path.exists(path):
            gb = os.path.getsize(path) / (1024 ** 3)
            return max(24, min(120, int(24 + gb * 4)))
    except Exception:
        pass
    return 48


def _enter_sleep(session_id: str) -> bool:
    with _SLEEP_GUARD:
        if session_id in _SLEEP_INFLIGHT:
            return False
        _SLEEP_INFLIGHT.add(session_id)
        return True


def _leave_sleep(session_id: str) -> None:
    with _SLEEP_GUARD:
        _SLEEP_INFLIGHT.discard(session_id)


def _remove_snapshot_entries(current: list, consumed: list) -> list:
    """Remove only entries actually consolidated from the old snapshot.

    Any memories appended while the model was summarising remain untouched. Counter semantics
    also preserve extra duplicate occurrences if a future store ever permits them.
    """
    remaining_to_remove = Counter(str(x) for x in consumed)
    out = []
    for item in current:
        key = str(item)
        if remaining_to_remove.get(key, 0) > 0:
            remaining_to_remove[key] -= 1
            continue
        out.append(item)
    return out


def run_session_sleep_cycle(session, threshold: int = None, model_handler=None):
    session_id = str(getattr(session, "id", None) or getattr(session, "session_id", None) or "")
    if not session_id or not _enter_sleep(session_id):
        return

    try:
        if threshold is None:
            threshold = get_dynamic_working_threshold(session)

        paths = get_session_vault_paths(session_id)
        # Snapshot quickly, then release the memory lock during expensive primary-model work.
        with memory_transaction(session_id):
            snapshot_generation = get_memory_generation(session_id)
            working_items = list(_load(paths["working_memory"]))
            if len(working_items) < threshold:
                return
            slice_to_summarize = list(working_items[:-10])

        raw_text_block = "\n".join(str(x) for x in slice_to_summarize)
        prompt = (
            "Summarize the following conversation logs into 2-3 concise, high-value episodic journal notes. "
            "Focus ONLY on key personal facts, decisions, emotional shifts, or character developments. "
            "Omit pleasantries and routine chit-chat.\n\n"
            f"LOGS:\n{raw_text_block}"
        )

        from overmind import neutral_summarize
        from memory_deep import save_deep_memory_journal

        summary = neutral_summarize(prompt, model_handler=model_handler)
        if not summary or summary.startswith("("):
            return

        with memory_transaction(session_id):
            if get_memory_generation(session_id) != snapshot_generation:
                print(f"[Sleep Cycle] Aborted stale consolidation for '{session_id}' after memory reset/purge.")
                return
            save_deep_memory_journal(
                f"[Consolidated Memory]: {summary.strip()}",
                session_id=session_id,
            )

            # Optimistic merge: consume only the entries from the captured snapshot. Anything
            # appended while summarisation was running survives this commit.
            current = list(_load(paths["working_memory"]))
            merged = _remove_snapshot_entries(current, slice_to_summarize)
            _save(paths["working_memory"], merged[-WORKING_MAX_ENTRIES:])

        print(
            f"[Sleep Cycle] Consolidated {len(slice_to_summarize)} entries for session "
            f"'{session_id}' (Dynamic Threshold: {threshold})."
        )
    except Exception as e:
        print(f"[Sleep Cycle Error] Failed consolidation for '{session_id}': {e}")
    finally:
        _leave_sleep(session_id)
