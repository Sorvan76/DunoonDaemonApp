# memory_router.py — Lean Session-Scoped Memory Admission Router
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from config import (
    WORKING_MEMORY_FILE, DEEP_MEMORY_FILE, INTENT_MEMORY_FILE,
    TASK_MEMORY_FILE, FACTUAL_MEMORY_FILE, CONTINUATION_MEMORY_FILE, RESET_MEMORY_FILE,
    get_session_vault_paths,
)
from significance import score_significance
from memory_semantics import assess_memory, score_candidates, superseded_texts
from memory_transactions import memory_transaction, load_json, atomic_save_json, bump_memory_generation
from memory_validation import validate_memory
from memory_lifecycle import is_runtime_artifact

try:
    from memory_diagnostics import log_admission as _log_memory_admission
except Exception:
    _log_memory_admission = None


VAULT_PATHS = {
    "intent": INTENT_MEMORY_FILE,
    "task": TASK_MEMORY_FILE,
    "factual": FACTUAL_MEMORY_FILE,
    "continuation": CONTINUATION_MEMORY_FILE,
    "reset": RESET_MEMORY_FILE,
    "working": WORKING_MEMORY_FILE,
    "deep": DEEP_MEMORY_FILE,
}


def _load_list(path):
    if not path:
        return []
    data = load_json(path, [])
    return data if isinstance(data, list) else []


def _save_list(path, data):
    if not path:
        return False
    return atomic_save_json(path, list(data or []))


def detect_vault(text):
    assessment = assess_memory(text)
    return assessment.get("vault"), float(assessment.get("confidence", 0.0) or 0.0)


def analyse_semantic_relations(text, vault_path, session_id=None):
    memories = []
    for item in _load_list(vault_path):
        if isinstance(item, dict):
            value = str(item.get("text") or item.get("summary") or "").strip()
        else:
            value = str(item or "").strip()
        if value:
            memories.append(value)
    if not memories:
        return 1.0, 0.0, 0.0
    rows = score_candidates(text, memories)
    if not rows:
        return 1.0, 0.0, 0.0
    best = max((score for _, score in rows), default=0.0)
    novelty = max(0.0, min(1.0, 1.0 - best))
    reinforcement = best if best >= 0.75 else 0.0
    # Contradiction is not the inverse of similarity. Factual replacement is handled by
    # a dedicated primary-model supersession judgement below.
    return novelty, reinforcement, 0.0


def _path_for(vault: str, session_id=None):
    if session_id:
        paths = get_session_vault_paths(str(session_id))
        key = f"{vault}_memory"
        return paths.get(key, paths.get(vault, VAULT_PATHS.get(vault)))
    return VAULT_PATHS.get(vault, WORKING_MEMORY_FILE)


def save_to_vault(vault, text, session_id=None):
    path = _path_for(vault, session_id=session_id)
    with memory_transaction(session_id):
        data = _load_list(path)
        if text not in data:
            data.append(text)
            return _save_list(path, data)
    return True


def _empty(reason: str):
    return {
        "vault": None,
        "reason": reason,
        "significance": 0.0,
        "novelty": 0.0,
        "reinforcement": 0.0,
        "contradiction": 0.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _choose_user_vault(detected: str | None, confidence: float, significance: float, *, text: str = "") -> str:
    """Choose from primary-model semantics + significance only; no wording templates."""
    if detected in {"factual", "intent", "task", "reset"} and confidence >= 0.56 and significance >= 0.34:
        return detected
    if detected == "continuation" and confidence >= 0.62 and significance >= 0.38:
        return "continuation"
    if significance >= 0.66:
        return "deep"
    return "working"


def _choose_actor_vault(significance: float) -> str:
    """A persona's own prose is autobiographical context, not automatically a fact/task/goal."""
    return "deep" if significance >= 0.72 else "working"


def _item_text(item) -> str:
    if isinstance(item, dict):
        return str(item.get("text") or item.get("summary") or item.get("content") or "").strip()
    return str(item or "").strip()


def _remove_superseded_facts(new_fact: str, factual_path: str, session_id=None) -> list[str]:
    """Remove older values for the same factual slot and return the removed text.

    Returning the exact displaced facts lets the caller preserve a small explicit history while
    keeping the live factual vault authoritative.
    """
    current = _load_list(factual_path)
    strings = [_item_text(item) for item in current]
    targets = set(superseded_texts(new_fact, [x for x in strings if x and x != new_fact]))
    if not targets:
        return []
    removed = [text for text in strings if text in targets]
    filtered = [item for item, text in zip(current, strings) if text not in targets]
    if len(filtered) == len(current):
        return []
    if not _save_list(factual_path, filtered):
        return []
    return list(dict.fromkeys(removed))


def _archive_superseded_facts(paths: dict, removed: list[str], new_fact: str) -> bool:
    if not removed:
        return True
    path = paths.get("superseded_memory")
    if not path:
        return True
    history = _load_list(path)
    stamp = datetime.now(timezone.utc).isoformat()
    for old in removed:
        row = {"text": old, "superseded_by": new_fact, "timestamp": stamp}
        if row not in history:
            history.append(row)
    # History is for immediate-prior reconstruction, not an unbounded shadow vault.
    return _save_list(path, history[-500:])


def _quarantine_superseded_echoes(new_fact: str, paths: dict) -> int:
    """Remove stale same-slot echoes from ordinary retrievable autobiographical vaults.

    Actor acknowledgements and sleep summaries can paraphrase an older factual value into
    working/deep memory.  Once the primary model has confirmed a real factual supersession,
    those paraphrases must not remain eligible to compete with the new current fact.
    """
    removed_count = 0
    for key in ("working_memory", "deep_memory"):
        path = paths.get(key)
        if not path:
            continue
        current = _load_list(path)
        texts = [_item_text(item) for item in current]
        candidates = [text for text in texts if text]
        if not candidates:
            continue
        targets = set(superseded_texts(new_fact, candidates))
        if not targets:
            continue
        filtered = [item for item, text in zip(current, texts) if text not in targets]
        if len(filtered) != len(current) and _save_list(path, filtered):
            removed_count += len(current) - len(filtered)
    return removed_count


def route_memory(text, session=None, is_user=True):
    session_id = (
        getattr(session, "memory_session_id", None)
        or getattr(session, "session_id", None)
        or getattr(session, "id", None)
    ) if session else None

    def _reject(reason):
        result = _empty(reason)
        if callable(_log_memory_admission):
            try:
                _log_memory_admission(
                    session_id=session_id or "", is_user=is_user, reason=reason,
                    wrote=False, text=str(text or "")
                )
            except Exception:
                pass
        return result

    if session is not None and not bool(getattr(session, "memory_write_enabled", True)):
        return _reject("memory_write_disabled_for_chat_mode")
    clean = str(text or "").strip()
    if is_runtime_artifact(clean):
        return _reject("runtime_artifact")
    if not validate_memory(clean):
        return _reject("validation_failed")

    # score_significance() and detect_vault() share the same cached primary-model assessment.
    significance = score_significance(clean, session_id=session_id)
    detected, confidence = detect_vault(clean)
    vault = _choose_user_vault(detected, confidence, significance, text=clean) if is_user else _choose_actor_vault(significance)

    if vault == "working":
        if is_user and significance < 0.30:
            return _reject("user_working_low_significance")
        if not is_user and significance < 0.48:
            return _reject("actor_working_low_significance")

    target_path = _path_for(vault, session_id=session_id)
    superseded = False
    superseded_echoes = 0

    # One persona-scoped transaction owns read -> semantic relation check -> mutation.
    # This prevents Dream/sleep/purge/router writers from replacing each other's updates.
    with memory_transaction(session_id):
        novelty, reinforcement, contradiction = analyse_semantic_relations(clean, target_path, session_id=session_id)
        if not is_user and vault == "working" and novelty < 0.20:
            return _reject("actor_working_repetitive")

        before = _load_list(target_path)
        already_present = clean in before
        # Durability invariant: establish the new current value first.  If this write fails, an
        # older fact is never deleted merely because a correction was attempted.
        persisted = bool(save_to_vault(vault, clean, session_id=session_id))
        wrote = (not already_present) and persisted

        if is_user and vault == "factual" and persisted:
            paths = get_session_vault_paths(str(session_id)) if session_id else {}
            removed_facts = _remove_superseded_facts(clean, target_path, session_id=session_id)
            superseded = bool(removed_facts)
            if superseded:
                _archive_superseded_facts(paths, removed_facts, clean)
                superseded_echoes = _quarantine_superseded_echoes(clean, paths)
                # Any in-flight sleep/consolidation snapshot was taken against the old factual
                # world and may otherwise reintroduce a stale value after this correction.
                bump_memory_generation(session_id)

    detected_note = detected or "none"
    if callable(_log_memory_admission):
        try:
            _log_memory_admission(
                session_id=session_id or "", is_user=is_user, semantic=detected_note,
                confidence=confidence, significance=significance, vault=vault,
                novelty=novelty, reinforcement=reinforcement, contradiction=contradiction,
                wrote=wrote, reason=f"admission:{vault}" + ("; superseded_prior_fact" if superseded else "") + (f"; quarantined_echoes={superseded_echoes}" if superseded_echoes else ""), text=clean,
            )
        except Exception:
            pass
    return {
        "vault": vault,
        "reason": f"admission:{vault}; semantic={detected_note}:{confidence:.2f}; significance={significance:.2f}" + ("; superseded_prior_fact" if superseded else "") + (f"; quarantined_echoes={superseded_echoes}" if superseded_echoes else ""),
        "significance": significance,
        "novelty": novelty,
        "reinforcement": reinforcement,
        "contradiction": contradiction,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
