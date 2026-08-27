from __future__ import annotations

"""Primary-model semantic bridge for Dunoon memory.

No auxiliary embedding model is loaded. Semantic admission, ranking, similarity and Dream
maintenance are delegated to the same configured GGUF used by the rest of Dunoon. If that
model is unavailable or returns unusable structured output, callers fail conservatively.
"""

import json
import re
import threading
import weakref
from collections import OrderedDict
from typing import Iterable

_HANDLER_REF = None
_HANDLER_LOCK = threading.RLock()
_CACHE_LOCK = threading.RLock()
_ASSESS_CACHE: "OrderedDict[str, dict]" = OrderedDict()
_SIM_CACHE: "OrderedDict[tuple[str, str], float]" = OrderedDict()
_HISTORY_INTENT_CACHE: "OrderedDict[str, bool]" = OrderedDict()
_CACHE_MAX = 512


def _clear_semantic_caches() -> None:
    # Cached semantic decisions belong to the model/runtime that produced them. A model
    # swap must never inherit those judgements.
    with _CACHE_LOCK:
        _ASSESS_CACHE.clear()
        _SIM_CACHE.clear()
        _HISTORY_INTENT_CACHE.clear()


def set_primary_model_handler(handler) -> None:
    global _HANDLER_REF
    with _HANDLER_LOCK:
        current = _HANDLER_REF() if _HANDLER_REF else None
        if current is handler:
            return
        _HANDLER_REF = weakref.ref(handler) if handler is not None else None
    _clear_semantic_caches()


def clear_primary_model_handler(handler=None) -> None:
    global _HANDLER_REF
    cleared = False
    with _HANDLER_LOCK:
        current = _HANDLER_REF() if _HANDLER_REF else None
        if handler is None or current is handler:
            _HANDLER_REF = None
            cleared = True
    if cleared:
        _clear_semantic_caches()


def get_primary_model_handler():
    with _HANDLER_LOCK:
        handler = _HANDLER_REF() if _HANDLER_REF else None
    if handler is None:
        return None
    try:
        return handler if handler.is_active() else None
    except Exception:
        return None


def semantics_available() -> bool:
    return get_primary_model_handler() is not None


def _bounded_float(value, default=0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return float(default)


def _extract_json(raw: str):
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0:
        return None
    # Try progressively shorter suffixes ending at the last JSON delimiter.
    for end_char in ("}", "]"):
        end = text.rfind(end_char)
        if end >= start:
            try:
                return json.loads(text[start:end + 1])
            except Exception:
                continue
    return None


def _call_json(system: str, user: str, *, max_tokens: int = 384):
    handler = get_primary_model_handler()
    if handler is None:
        return None
    packet = {
        "system": system,
        "history": [],
        "user": user,
        "temperature": 0.0,
        "repeat_penalty": 1.0,
        "presence_penalty": 0.0,
        "max_tokens": int(max_tokens),
        "disable_reasoning": True,
        "response_format": {"type": "json_object"},
    }
    try:
        return _extract_json(handler.send(packet))
    except Exception as exc:
        print(f"[Memory Semantics Warning] Primary-model semantic call failed: {exc}")
        return None


def _cache_put(cache: OrderedDict, key, value):
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > _CACHE_MAX:
        cache.popitem(last=False)


def assess_memory(text: str) -> dict:
    clean = str(text or "").strip()
    if not clean:
        return {"significance": 0.0, "vault": None, "confidence": 0.0}
    with _CACHE_LOCK:
        if clean in _ASSESS_CACHE:
            value = dict(_ASSESS_CACHE[clean])
            _ASSESS_CACHE.move_to_end(clean)
            return value

    system = (
        "You are Dunoon Daemon's semantic memory assessor. Judge meaning, not wording. "
        "Return JSON only with keys significance, vault, confidence. significance is 0..1 and means how useful this exact statement would be to remember in a later conversation. "
        "Routine greetings, one-off formatting requests, immediate questions and disposable chatter should score low. Durable facts, preferences, identity/history, meaningful relationship developments, consequential decisions, commitments, goals, constraints, major emotional developments and material project/story changes score higher. "
        "vault must be one of factual, intent, task, continuation, reset, none. factual is a stable reusable fact/preference/history/relationship/world/project fact. intent is a durable desired outcome or plan. task is a concrete unfinished obligation/next action. continuation is an explicit durable request to resume an established thread later. reset is an explicit intention to abandon/replace an active context. Use none when no durable semantic vault fits. confidence is 0..1 for the vault classification. "
        "Do not infer hidden facts beyond the supplied statement."
    )
    data = _call_json(system, clean, max_tokens=160)
    if not isinstance(data, dict):
        result = {"significance": 0.0, "vault": None, "confidence": 0.0}
    else:
        vault = str(data.get("vault") or "none").strip().lower()
        if vault not in {"factual", "intent", "task", "continuation", "reset"}:
            vault = None
        result = {
            "significance": _bounded_float(data.get("significance"), 0.0),
            "vault": vault,
            "confidence": _bounded_float(data.get("confidence"), 0.0),
        }
    with _CACHE_LOCK:
        _cache_put(_ASSESS_CACHE, clean, dict(result))
    return result


def requests_superseded_history(query: str) -> bool:
    """Return True only when the primary model judges that the user explicitly wants prior state.

    This is semantic intent, so Python does not infer it from vocabulary.  If the configured
    primary model is unavailable or the structured judgement is unusable, fail conservatively
    and keep superseded values out of the prompt.
    """
    clean = str(query or "").strip()
    if not clean:
        return False
    with _CACHE_LOCK:
        if clean in _HISTORY_INTENT_CACHE:
            value = bool(_HISTORY_INTENT_CACHE[clean])
            _HISTORY_INTENT_CACHE.move_to_end(clean)
            return value

    system = (
        "You are Dunoon Daemon's memory-history intent judge. Judge meaning, not vocabulary. "
        "Return JSON only as {\"requests_superseded_history\": true|false}. "
        "True means the user is explicitly asking for an earlier, previous, replaced, or superseded value/state as historical information, including a comparison between prior and current state. "
        "False means the user only wants the current state, ordinary recall, or something unrelated. "
        "Do not infer a request for history merely because the wording happens to contain a word that can sometimes refer to age or sequence."
    )
    data = _call_json(system, clean[:1600], max_tokens=80)
    value = bool(isinstance(data, dict) and data.get("requests_superseded_history") is True)
    with _CACHE_LOCK:
        _cache_put(_HISTORY_INTENT_CACHE, clean, value)
    return value


def score_candidates(query: str, candidates: Iterable[str], *, batch_chars: int = 11000, purpose: str = "general") -> list[tuple[str, float]]:
    query = str(query or "").strip()
    texts = [str(x or "").strip() for x in candidates if str(x or "").strip()]
    if not query or not texts or not semantics_available():
        return []

    # Preserve duplicates by index internally; callers normally dedupe before this point.
    scored: list[tuple[int, str, float]] = []
    start = 0
    while start < len(texts):
        batch = []
        chars = 0
        i = start
        while i < len(texts) and len(batch) < 56:
            clipped = texts[i][:600]
            cost = len(clipped) + 24
            if batch and chars + cost > batch_chars:
                break
            batch.append((i, clipped))
            chars += cost
            i += 1
        if not batch:
            batch = [(start, texts[start][:600])]
            i = start + 1

        numbered = "\n".join(f"{idx}: {txt}" for idx, txt in batch)
        system = (
            "You are Dunoon Daemon's semantic retrieval judge. Compare the query with every numbered memory by meaning, including paraphrases and indirect but genuinely useful relevance. "
            "Return JSON only as {\"scores\":[{\"i\":number,\"score\":0..1}, ...]}. Include every supplied index exactly once. "
            "A score near 1 means directly useful to answer or understand the query; near 0 means unrelated. Do not reward mere shared words when the meanings differ."
        )
        if str(purpose or '').strip().lower() == 'arena':
            system += (
                " ARENA STRICTNESS: this retrieval feeds a fresh autonomous Arena scene. Score historical memory highly only when it is directly needed for the current named participant, an explicitly established current relationship, or a concrete fact in the current scene. "
                "A prior fight, room, prop, injury, joke, opponent or absent person is NOT relevant merely because the present scene is also a fight or has a similar mood. Memories whose main subject is an absent earlier participant should score near zero unless the current query explicitly asks about that person/history. Prevent cross-scene callbacks and physical-scene bleed."
            )
        data = _call_json(system, f"QUERY:\n{query[:1200]}\n\nMEMORIES:\n{numbered}", max_tokens=max(220, len(batch) * 16))
        by_index = {}
        if isinstance(data, dict) and isinstance(data.get("scores"), list):
            for row in data["scores"]:
                if not isinstance(row, dict):
                    continue
                try:
                    idx = int(row.get("i"))
                except Exception:
                    continue
                by_index[idx] = _bounded_float(row.get("score"), 0.0)
        for idx, _ in batch:
            scored.append((idx, texts[idx], by_index.get(idx, 0.0)))
        start = i

    scored.sort(key=lambda row: (-row[2], row[0]))
    return [(text, score) for _, text, score in scored]


def semantic_rank(query: str, candidates: Iterable[str], top_k: int = 5, *, min_score: float = 0.12, purpose: str = "general") -> list[str]:
    ranked = score_candidates(query, candidates, purpose=purpose)
    out = []
    for text, score in ranked:
        if score < min_score:
            continue
        out.append(text)
        if len(out) >= max(1, int(top_k)):
            break
    return out


def semantic_similarity(a: str, b: str) -> float:
    a = str(a or "").strip()
    b = str(b or "").strip()
    if not a or not b:
        return -1.0
    if a.casefold() == b.casefold():
        return 1.0
    key = tuple(sorted((a, b)))
    with _CACHE_LOCK:
        if key in _SIM_CACHE:
            value = _SIM_CACHE[key]
            _SIM_CACHE.move_to_end(key)
            return value
    rows = score_candidates(a, [b])
    score = rows[0][1] if rows else -1.0
    with _CACHE_LOCK:
        _cache_put(_SIM_CACHE, key, score)
    return score


def count_relevant(query: str, candidates: Iterable[str], *, threshold: float = 0.62) -> int:
    return sum(1 for _, score in score_candidates(query, candidates) if score >= threshold)


def semantic_dedupe(items: list[str], guidance: str = "", *, threshold: float = 0.84) -> tuple[list[str], int, int]:
    """Primary-model near-duplicate maintenance for Dream.

    Exact duplicates are removed deterministically first. Semantic duplicate decisions are
    batched so Dream does not make one model call per memory. Newest variants win.
    """
    exact = []
    seen = set()
    exact_removed = 0
    for raw in items or []:
        text = str(raw or "").strip()
        if not text:
            continue
        if text in seen:
            exact_removed += 1
            continue
        seen.add(text)
        exact.append(text)
    if len(exact) < 2 or not semantics_available():
        return exact, exact_removed, 0

    protected_indices = set()
    guidance = str(guidance or "").strip()
    if guidance:
        score_map = {text: score for text, score in score_candidates(guidance, exact)}
        protected_indices = {i for i, text in enumerate(exact) if score_map.get(text, 0.0) >= 0.62}

    removed_indices = set()
    kept_newer_indices: list[int] = []
    end = len(exact)
    while end > 0:
        start = max(0, end - 48)
        candidate_indices = list(range(start, end))
        # A small bank of already-kept newer memories catches duplicates across batch boundaries.
        ref_indices = kept_newer_indices[:24]
        candidate_block = "\n".join(f"{i}: {exact[i][:600]}" for i in candidate_indices)
        ref_block = "\n".join(f"R{i}: {exact[i][:600]}" for i in ref_indices) or "(none)"
        protected_block = ", ".join(str(i) for i in sorted(protected_indices.intersection(candidate_indices))) or "none"
        system = (
            "You are Dunoon Daemon's Dream duplicate judge. Compare each numbered CANDIDATE by meaning with NEWER REFERENCES and with candidates that have a higher numeric index. "
            "Mark a candidate only when it is essentially the same remembered fact/event/decision/meaning and the newer wording can safely stand in for it. Related-but-distinct memories must coexist. "
            "Never mark a protected candidate. Return JSON only as {\"duplicates\":[{\"i\":number,\"score\":0..1}, ...]}. score is confidence that removal is safe."
        )
        data = _call_json(
            system,
            f"PROTECTED CANDIDATE INDICES: {protected_block}\n\nNEWER REFERENCES:\n{ref_block}\n\nCANDIDATES:\n{candidate_block}",
            max_tokens=max(180, len(candidate_indices) * 10),
        )
        rows = data.get("duplicates", []) if isinstance(data, dict) else []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            try:
                idx = int(row.get("i"))
            except Exception:
                continue
            score = _bounded_float(row.get("score"), 0.0)
            if idx in candidate_indices and idx not in protected_indices and score >= threshold:
                removed_indices.add(idx)

        # Newest-first representative bank for the next, older batch.
        for idx in reversed(candidate_indices):
            if idx not in removed_indices:
                kept_newer_indices.append(idx)
        end = start

    kept = [text for i, text in enumerate(exact) if i not in removed_indices]
    return kept, exact_removed, len(removed_indices)


def superseded_texts(new_fact: str, existing_facts: Iterable[str]) -> list[str]:
    """Return older factual memories that the new fact clearly replaces or contradicts.

    The primary model decides semantic fact identity. Ambiguous related facts coexist.
    """
    new_fact = str(new_fact or "").strip()
    existing = [str(x or "").strip() for x in existing_facts if str(x or "").strip()]
    if not new_fact or not existing or not semantics_available():
        return []
    removed = []
    start = 0
    while start < len(existing):
        batch = existing[start:start + 48]
        numbered = "\n".join(f"{start+i}: {text[:650]}" for i, text in enumerate(batch))
        system = (
            "You are Dunoon Daemon's factual supersession judge. A new factual memory may replace an older fact only when both refer to the same underlying fact slot and the new statement clearly corrects, changes, negates, or updates the older value. "
            "Related facts that can both be true must coexist. Be conservative. Return JSON only as {\"supersede\":[indices]}."
        )
        data = _call_json(system, f"NEW FACT:\n{new_fact[:1200]}\n\nOLDER FACTS:\n{numbered}", max_tokens=180)
        indices = data.get("supersede", []) if isinstance(data, dict) else []
        for raw in indices if isinstance(indices, list) else []:
            try:
                idx = int(raw)
            except Exception:
                continue
            if start <= idx < start + len(batch):
                removed.append(existing[idx])
        start += len(batch)
    return list(dict.fromkeys(removed))
