"""Dream Engine V1 — persona-scoped memory maintenance.

Dream snapshots the persona's learned vaults, removes safe working-memory repetition,
keeps durable vaults intact apart from exact duplicate cleanup/cap enforcement, clears
obsolete legacy embedding traces, and returns an auditable report. Semantic duplicate
judgement and guidance protection use Dunoon's configured primary GGUF only; Dream never
semantically rewrites factual or deep memory.
"""
from __future__ import annotations

import json
import os
import random
import re
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Dict, Iterable, List, Tuple

from config import SESSIONS_DIR, get_session_vault_paths, WORKING_MAX_ENTRIES, DEEP_MAX_ENTRIES
from memory_semantics import semantic_similarity, semantic_dedupe, semantics_available, count_relevant
from memory_transactions import memory_transaction, load_json, atomic_save_json

INTENT_MAX = 400
TASK_MAX = 400
FACTUAL_MAX = 1000
CONTINUATION_MAX = 600
RESET_MAX = 200
PRUNE_TELEMETRY_MAX = 1000

DREAM_COOLDOWN_HOURS = 6
DREAM_WORKING_TRIGGER = 64
DREAM_DUPLICATE_TRIGGER = 8
DREAM_DUPLICATE_RATIO_TRIGGER = 0.15
DREAM_ORPHAN_EMBEDDING_TRIGGER = 50
DREAM_NEAR_DUPLICATE_THRESHOLD = 0.84

# Dream maintenance never infers semantic identity from vocabulary.


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _atomic_save(path: str, data):
    return atomic_save_json(path, data)


def _load(path: str, default):
    return load_json(path, default)

def _as_text(item) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        return str(item.get("text") or item.get("summary") or "").strip()
    return ""


def _clean_strings(items: Iterable) -> List[str]:
    result = []
    seen = set()
    for item in items or []:
        text = _as_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _semantic_similarity(a: str, b: str) -> float:
    return semantic_similarity(a, b)

def _protected(text: str, guidance: str) -> bool:
    if not str(guidance or "").strip():
        return False
    return _semantic_similarity(text, guidance) >= 0.62

def _similar(a: str, b: str) -> bool:
    return _semantic_similarity(a, b) >= DREAM_NEAR_DUPLICATE_THRESHOLD

def _dedupe_working(items: List[str], guidance: str = "") -> Tuple[List[str], int, int]:
    """Keep newest semantic variant using only the configured primary model."""
    cleaned, exact_removed, near_removed = semantic_dedupe(
        [_as_text(x) for x in items if _as_text(x)], guidance=str(guidance or ''),
        threshold=DREAM_NEAR_DUPLICATE_THRESHOLD,
    )
    return cleaned[-WORKING_MAX_ENTRIES:], exact_removed, near_removed

def _all_live_texts(paths: Dict[str, str]) -> List[str]:
    valid: List[str] = []
    for key in ("working_memory", "deep_memory", "intent_memory", "task_memory", "factual_memory", "continuation_memory", "reset_memory"):
        valid.extend(_clean_strings(_load(paths[key], [])))
    for item in _load(paths["journal_memory"], []):
        text = _as_text(item)
        if text:
            valid.append(text)
    return list(dict.fromkeys(valid))


def _embedding_count(paths: Dict[str, str]) -> int:
    data = _load(paths["embeddings"], {})
    return len(data) if isinstance(data, dict) else 0


def _working_duplicate_pressure(items: List[str]) -> Tuple[int, float]:
    """Cheap Home-screen pressure estimate. Semantic dedupe itself runs only inside Dream."""
    raw = [_as_text(x) for x in (items or []) if _as_text(x)][-300:]
    if len(raw) < 2:
        return 0, 0.0
    seen = set()
    duplicates = 0
    for text in raw:
        if text in seen:
            duplicates += 1
        else:
            seen.add(text)
    return duplicates, duplicates / max(1, len(raw))

def dream_need(session) -> dict:
    """Return a cheap, deterministic explanation of whether this persona needs a Dream."""
    sid = str(getattr(session, "id", None) or getattr(session, "session_id", ""))
    if not sid:
        return {"needed": False, "cooldown": False, "reasons": [], "score": 0.0}
    paths = get_session_vault_paths(sid)
    raw_working = _load(paths["working_memory"], [])
    working = _clean_strings(raw_working)
    duplicate_count, duplicate_ratio = _working_duplicate_pressure(raw_working if isinstance(raw_working, list) else [])
    live_text_count = len(_all_live_texts(paths))
    embeddings = _embedding_count(paths)
    orphan_estimate = max(0, embeddings - live_text_count)

    last = _parse_iso(getattr(session, "last_dream_at", ""))
    now = datetime.now(timezone.utc)
    cooldown = bool(last and now - last < timedelta(hours=DREAM_COOLDOWN_HOURS))
    cooldown_remaining = 0.0
    if cooldown:
        cooldown_remaining = max(0.0, DREAM_COOLDOWN_HOURS - (now - last).total_seconds() / 3600.0)

    reasons = []
    if len(working) >= DREAM_WORKING_TRIGGER:
        reasons.append(f"working memory has {len(working)} entries")
    if duplicate_count >= DREAM_DUPLICATE_TRIGGER or (len(working) >= 24 and duplicate_ratio >= DREAM_DUPLICATE_RATIO_TRIGGER):
        reasons.append(f"working memory contains about {duplicate_count} repetitive entries")
    if orphan_estimate >= DREAM_ORPHAN_EMBEDDING_TRIGGER:
        reasons.append(f"embedding index has about {orphan_estimate} stale entries")

    score = min(1.0, max(
        len(working) / max(1, DREAM_WORKING_TRIGGER),
        duplicate_count / max(1, DREAM_DUPLICATE_TRIGGER),
        orphan_estimate / max(1, DREAM_ORPHAN_EMBEDDING_TRIGGER),
    ))
    return {
        "needed": bool(reasons) and not cooldown,
        "maintenance_due": bool(reasons),
        "cooldown": cooldown,
        "cooldown_remaining_hours": round(cooldown_remaining, 2),
        "reasons": reasons,
        "score": round(score, 3),
        "working": len(working),
        "duplicate_count": duplicate_count,
        "duplicate_ratio": round(duplicate_ratio, 3),
        "embeddings": embeddings,
        "orphan_embedding_estimate": orphan_estimate,
    }


def _snapshot(session, paths: Dict[str, str], need: dict) -> Tuple[str, dict]:
    sid = str(getattr(session, "id", None) or getattr(session, "session_id", ""))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dream_dir = os.path.join(SESSIONS_DIR, sid, "dreams")
    os.makedirs(dream_dir, exist_ok=True)
    snapshot_path = os.path.join(dream_dir, f"dream_{stamp}_before.json")
    snapshot = {
        "schema": 1,
        "created_utc": _now_iso(),
        "persona": getattr(session, "agent_name", "Persona"),
        "session_id": sid,
        "dream_guidance": getattr(session, "dream_guidance", ""),
        "need": need,
        "vaults": {key: _load(path, []) for key, path in paths.items() if key not in ("vault_dir", "embeddings")},
        # Embeddings are a regenerable index, not canonical memory evidence. Keep keys/count
        # for audit without copying megabytes of vectors into every Dream snapshot.
        "embedding_index": {
            "count": _embedding_count(paths),
            "keys": list((_load(paths["embeddings"], {}) or {}).keys()) if isinstance(_load(paths["embeddings"], {}), dict) else [],
        },
    }
    _atomic_save(snapshot_path, snapshot)
    return snapshot_path, snapshot


def _ocean_score(session, trait: str, default: float = 50.0) -> float:
    profile = getattr(session, "ocean_profile", {}) or {}
    traits = profile.get("traits", profile) if isinstance(profile, dict) else {}
    data = traits.get(trait, {}) if isinstance(traits, dict) else {}
    try:
        return float(data.get("base_score", data.get("score", default))) if isinstance(data, dict) else float(data)
    except Exception:
        return default


def _story(session, result: dict) -> str:
    """CPU-only procedural veneer. It cannot invent maintenance events."""
    seed_src = f"{result['dream_id']}|{getattr(session, 'id', '')}|{result['before']['working']}|{result['after']['working']}"
    seed = int(hashlib.sha256(seed_src.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    openness = _ocean_score(session, "Openness")
    conscientious = _ocean_score(session, "Conscientiousness")
    neurotic = _ocean_score(session, "Neuroticism")

    if conscientious >= 65:
        openings = ["I put the archive in order.", "I sorted through what had accumulated.", "I went carefully through the shelves of memory."]
    elif openness >= 65:
        openings = ["The old fragments drifted past in strange little constellations.", "Memory moved like scraps of paper in a night wind.", "I wandered through the echoes for a while."]
    elif neurotic >= 65:
        openings = ["There was more noise in there than I liked.", "A few memories kept circling back on themselves.", "The archive felt crowded, so I checked it carefully."]
    else:
        openings = ["I dreamed for a while.", "I spent some quiet time with what I remembered.", "I went through the recent memories."]

    removed = result["changes"]["working_removed"]
    orphans = result["changes"]["embeddings_removed"]
    exact = result["changes"]["exact_duplicates_removed"]
    near = result["changes"]["near_duplicates_removed"]
    details = []
    if removed:
        details.append(rng.choice([
            f"{removed} repeated fragments were allowed to fall away.",
            f"I found {removed} pieces that were saying the same things and kept the cleaner versions.",
            f"{removed} echoes no longer needed separate places, so I let them go.",
        ]))
    else:
        details.append(rng.choice([
            "Nothing important needed to be discarded.",
            "The memories themselves were already surprisingly tidy.",
            "I found no repeated memories worth removing.",
        ]))
    if orphans:
        details.append(rng.choice([
            f"I also cleared {orphans} old index traces that no longer pointed to a living memory.",
            f"{orphans} stale routes through the archive were closed.",
            f"The index had {orphans} dead ends; they are gone now.",
        ]))
    if result["guidance_hits"]:
        details.append(rng.choice([
            f"I kept {result['guidance_hits']} memories close because they matched the guidance you gave me.",
            f"Your guidance marked {result['guidance_hits']} memories as things I should take particular care with.",
        ]))
    closings = [
        "What remains is a little quieter.",
        "The important shape of things is still there.",
        "I remember less noise, not less truth.",
    ]
    return " ".join([rng.choice(openings)] + details + [rng.choice(closings)])


def run_dream(session, *, force: bool = False) -> dict:
    """Run one persona-scoped maintenance transaction and return a complete audit result."""
    sid = str(getattr(session, "id", None) or getattr(session, "session_id", ""))
    if not sid:
        return {"status": "error", "message": "Persona has no session id."}

    need = dream_need(session)
    name = getattr(session, "agent_name", "Persona")
    if need.get("cooldown") and not force:
        return {
            "status": "cooldown",
            "message": f"{name} has already dreamed recently. Try again later.",
            "need": need,
        }
    if not need.get("maintenance_due") and not force:
        return {"status": "not_needed", "message": f"{name} does not need to dream yet.", "need": need}

    paths = get_session_vault_paths(sid)
    with memory_transaction(sid):
        snapshot_path, snapshot = _snapshot(session, paths, need)
        # Preserve duplicate occurrences for truthful before/after accounting. _clean_strings()
        # is intentionally not used until after Dream has had a chance to count removals.
        before_working = [
            _as_text(item) for item in snapshot["vaults"].get("working_memory", [])
            if _as_text(item)
        ]
        before_embeddings = int(snapshot.get("embedding_index", {}).get("count", 0))
        guidance = str(getattr(session, "dream_guidance", "") or "")

        cleaned_working, exact_removed, near_removed = _dedupe_working(before_working, guidance=guidance)
        guidance_candidates = list(dict.fromkeys(before_working))
        guidance_hits = count_relevant(guidance, guidance_candidates, threshold=0.62) if guidance and semantics_available() else 0
        _atomic_save(paths["working_memory"], cleaned_working)

        caps = {
            "deep_memory": DEEP_MAX_ENTRIES,
            "intent_memory": INTENT_MAX,
            "task_memory": TASK_MAX,
            "factual_memory": FACTUAL_MAX,
            "continuation_memory": CONTINUATION_MAX,
            "reset_memory": RESET_MAX,
            "prune_telemetry": PRUNE_TELEMETRY_MAX,
        }
        durable_exact_removed = 0
        for key, cap in caps.items():
            raw = _load(paths[key], [])
            cleaned = _clean_strings(raw)
            durable_exact_removed += max(0, len(raw) - len(cleaned))
            _atomic_save(paths[key], cleaned[-cap:])

        # 🐉 Silver Wyrm: removed the auxiliary embedding brain. Any surviving vector file is legacy
        # cache only, so Dream may safely clear it instead of pretending it remains live state.
        _atomic_save(paths["embeddings"], {})
        after_embeddings = 0
        after_working = _clean_strings(_load(paths["working_memory"], []))

    dream_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    result = {
        "status": "complete",
        "dream_id": dream_id,
        "persona": name,
        "session_id": sid,
        "snapshot": snapshot_path,
        "created_utc": _now_iso(),
        "before": {"working": len(before_working), "embeddings": before_embeddings},
        "after": {"working": len(after_working), "embeddings": after_embeddings},
        "changes": {
            "exact_duplicates_removed": exact_removed + durable_exact_removed,
            "near_duplicates_removed": near_removed,
            "working_removed": max(0, len(before_working) - len(after_working)),
            "embeddings_removed": max(0, before_embeddings - after_embeddings),
        },
        "guidance_hits": guidance_hits,
        "guidance": guidance,
        "need_before": need,
        "safety": {
            "factual_semantic_rewrite": False,
            "deep_semantic_rewrite": False,
            "primary_model_semantic_judgement": bool(semantics_available()),
            "snapshot_before_mutation": True,
        },
    }
    result["story"] = _story(session, result)

    report_dir = os.path.join(SESSIONS_DIR, sid, "dreams")
    report_path = os.path.join(report_dir, f"dream_{dream_id.replace(':','').replace('.','_')}_report.json")
    result["report_path"] = report_path
    _atomic_save(report_path, result)

    session.last_dream_at = result["created_utc"]
    session.last_dream_report = {
        "dream_id": dream_id,
        "created_utc": result["created_utc"],
        "story": result["story"],
        "changes": result["changes"],
    }
    manager = getattr(session, "session_manager", None)
    if manager is not None:
        try:
            manager.save()
        except Exception:
            pass
    return result
