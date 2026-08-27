from __future__ import annotations

"""Lean, relevance-first memory context for Dunoon 2.0.

Learned memories are historical evidence, not present-world authority. This module gathers
session-scoped memory candidates, removes duplicates/runtime artefacts/recent transcript echoes,
and returns only the memories that are actually relevant to the current turn.
"""

import json
import os
import re
from typing import Iterable

from config import get_session_vault_paths
from journal_vault import get_all_journal_entries
from memory_semantics import semantic_rank, requests_superseded_history
from memory_lifecycle import is_runtime_artifact
from memory_transactions import memory_transaction, load_json

try:
    from memory_diagnostics import log_retrieval as _log_memory_retrieval
except Exception:
    _log_memory_retrieval = None


_VAULT_SPECS = (
    ("factual_memory", "fact"),
    ("intent_memory", "intent"),
    ("task_memory", "task"),
    ("deep_memory", "durable"),
    ("working_memory", "recent"),
)


def _load_list(path: str) -> list:
    if not path:
        return []
    data = load_json(path, [])
    return data if isinstance(data, list) else []


def semantic_search(query, candidates, top_k=5, session_id=None):
    """Compatibility name; semantics are supplied by the configured primary model."""
    return semantic_rank(query, candidates, top_k=top_k)


def _text(value) -> str:
    if isinstance(value, dict):
        value = value.get("text") or value.get("summary") or value.get("content") or ""
    return str(value or "").strip()


def _key(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip()).casefold()


def _recent_transcript_keys(session, limit: int = 16) -> set[str]:
    if not session:
        return set()
    try:
        history = session.get_history(limit=limit)
    except Exception:
        history = getattr(session, "messages", [])[-limit:]
    out = set()
    for item in history or []:
        if isinstance(item, dict):
            t = _text(item.get("content") or item.get("text"))
        else:
            t = _text(item)
        if t:
            out.add(_key(t))
    return out


def _candidate_rows(session) -> list[tuple[str, str]]:
    sid = (
        getattr(session, "memory_session_id", None)
        or getattr(session, "id", None)
        or getattr(session, "session_id", None)
    )
    if not sid:
        return []
    paths = get_session_vault_paths(str(sid))
    rows: list[tuple[str, str]] = []
    with memory_transaction(str(sid)):
        for path_key, label in _VAULT_SPECS:
            for item in _load_list(paths.get(path_key, "")):
                text = _text(item)
                if text:
                    rows.append((label, text))
        try:
            for entry in get_all_journal_entries(str(sid)):
                text = _text(getattr(entry, "text", ""))
                if text:
                    rows.append(("journal", text))
        except Exception:
            pass
    return rows




def _immediate_superseded_rows(session, current_facts: list[str]) -> list[tuple[str, str]]:
    if not session or not current_facts:
        return []
    sid = (
        getattr(session, "memory_session_id", None)
        or getattr(session, "id", None)
        or getattr(session, "session_id", None)
    )
    if not sid:
        return []
    paths = get_session_vault_paths(str(sid))
    with memory_transaction(str(sid)):
        history = _load_list(paths.get("superseded_memory", ""))
    rows = []
    for current in current_facts:
        for item in reversed(history):
            if not isinstance(item, dict):
                continue
            old_text = _text(item)
            successor = str(item.get("superseded_by") or "").strip()
            if old_text and successor == current:
                rows.append(("superseded", old_text))
                break
    return rows


def relevant_memory_items(query: str, session, *, arena: bool = False, max_items: int | None = None) -> list[tuple[str, str]]:
    """Return a small, de-duplicated, relevance-ranked memory set.

    The current input and recent transcript are deliberately excluded so the model never sees
    the same statement as both live conversation and remembered history.
    """
    if not session or not bool(getattr(session, "memory_read_enabled", True)):
        return []

    query_text = _text(query)
    if not query_text:
        return []

    limit = int(max_items or (2 if arena else 8))
    limit = max(1, min(12, limit))
    blocked = _recent_transcript_keys(session)
    blocked.add(_key(query_text))

    # First occurrence wins. The source order intentionally favours explicit factual/intent/task
    # memories over duplicate journal/deep copies of the same prose.
    source_by_key: dict[str, str] = {}
    text_by_key: dict[str, str] = {}
    ordered_keys: list[str] = []
    fresh_scene = bool(getattr(session, "fresh_scene", False))
    for label, text in _candidate_rows(session):
        if fresh_scene and label == "recent":
            continue
        k = _key(text)
        if not k or k in blocked or k in text_by_key:
            continue
        if is_runtime_artifact(text):
            continue
        source_by_key[k] = label
        text_by_key[k] = text
        ordered_keys.append(k)

    if not ordered_keys:
        return []

    sid = (
        getattr(session, "memory_session_id", None)
        or getattr(session, "id", None)
        or getattr(session, "session_id", None)
    )
    candidates = [text_by_key[k] for k in ordered_keys]
    try:
        if arena:
            # Arena is a fresh physical scene. Use a deliberately strict primary-model relevance
            # gate so generic similarity to earlier fights cannot drag absent opponents/props in.
            ranked = semantic_rank(
                query_text, candidates, top_k=min(len(candidates), max(2, limit)),
                min_score=0.62, purpose='arena'
            )
        else:
            # score_candidates already evaluates the whole candidate bank; asking semantic_rank
            # to return every relevant row costs no extra model pass.  We can therefore reserve
            # relevant factual-vault rows ahead of autobiographical echoes instead of allowing
            # dozens of semantically similar old working/deep memories to crowd current truth out.
            ranked = semantic_search(query_text, candidates, top_k=len(candidates), session_id=str(sid) if sid else None)
    except Exception:
        ranked = []

    # Current factual-vault entries are the authoritative learned value for their fact slot.
    # Preserve semantic relevance, but move at most two already-ranked facts ahead of lower-tier
    # working/deep echoes.  This is ordering, not keyword-based fact detection.
    forced_facts: list[str] = []
    if not arena:
        for text in ranked:
            k = _key(text)
            if k in source_by_key and source_by_key[k] == "fact" and text not in forced_facts:
                forced_facts.append(text)
                if len(forced_facts) >= min(2, limit):
                    break
    ordered_ranked = forced_facts + [text for text in ranked if text not in forced_facts]

    # If primary-model semantic relevance is unavailable, inject nothing; the live transcript is
    # safer than stuffing unrelated autobiographical material into the character's next turn.
    out: list[tuple[str, str]] = []
    seen = set()
    for text in ordered_ranked:
        k = _key(text)
        if not k or k in seen or k not in text_by_key:
            continue
        seen.add(k)
        out.append((source_by_key[k], text_by_key[k]))
        if len(out) >= limit:
            break

    # Superseded values live outside ordinary retrieval and are exposed only when the user
    # explicitly asks about the prior state.  Linkage by exact successor preserves the immediate
    # predecessor rather than asking semantic ranking to choose among a long history of old values.
    if (not arena) and forced_facts:
        history_rows = _immediate_superseded_rows(session, forced_facts)
        if history_rows and requests_superseded_history(query_text):
            rebuilt: list[tuple[str, str]] = []
            injected_history = False
            for row in out:
                rebuilt.append(row)
                if not injected_history and row[0] == "fact" and row[1] in forced_facts:
                    for hrow in history_rows:
                        if hrow not in rebuilt:
                            rebuilt.append(hrow)
                    injected_history = True
            out = rebuilt[:limit]
    if callable(_log_memory_retrieval):
        try:
            _log_memory_retrieval(
                session_id=str(sid) if sid else "", query=query_text, arena=arena,
                fresh_scene=fresh_scene, selected=out,
                candidate_count=len(candidates), blocked_count=len(blocked),
            )
        except Exception:
            pass
    if out:
        callback = getattr(session, "memory_activity_callback", None)
        if callable(callback):
            try:
                callback()
            except Exception:
                pass
    return out


def format_memory_context(query: str, session, *, arena: bool = False, max_items: int | None = None) -> str:
    items = relevant_memory_items(query, session, arena=arena, max_items=max_items)
    if not items:
        return ""
    lines = [
        "[RELEVANT MEMORY]",
        "These are historical recollections and learned context, not current-world authority. Use them only when relevant. "
        "The human's current message and any CURRENT REALITY block outrank stale, uncertain or conflicting memory. "
        "A supported remembered fact does not prove adjacent details that are absent from memory; knowing an object exists does not establish where it was placed. "
        "If a specific remembered detail is not supported, admit uncertainty instead of inventing a plausible value and calling it memory. "
        "Do not mention the memory system unless the human explicitly asks about it.",
        "A (fact) entry is the current learned factual value. A (superseded) entry, when present, is explicitly historical and must never be presented as current.",
    ]
    if bool(getattr(session, "fresh_scene", False)):
        lines.append(
            "FRESH SCENE BOUNDARY: every memory below happened previously. Do not assume old locations, people, objects, injuries, positions, unfinished actions, or activities are physically present now. "
            "The new immediate scene begins unestablished until the human establishes it. You may recognise directly relevant history and relationships, but do not resume an old scene automatically or mention unrelated absent prior participants merely because a previous event had a similar mood or conflict."
        )
    lines.extend(f"- ({label}) {text}" for label, text in items)
    return "\n".join(lines)
