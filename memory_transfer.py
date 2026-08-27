# memory_transfer.py — Cross-Persona Semantic Distillation Bridge
from __future__ import annotations

import json
import os

from config import get_session_vault_paths
from memory_semantics import semantic_rank
from memory_transactions import memory_transaction, load_json


def retrieve_cross_persona_insights(query: str, current_session, sm, top_k: int = 2) -> list:
    """Scan opted-in foreign vaults and return primary-model semantic matches with provenance."""
    if not sm or not str(query or '').strip():
        return []

    all_foreign_memories = []
    provenance = {}
    current_id = str(getattr(current_session, "id", None) or "")

    for sess_id, sess in getattr(sm, "sessions", {}).items():
        sess_id = str(sess_id)
        if sess_id == current_id:
            continue
        if not bool(getattr(sess, "share_insights", False)):
            continue

        paths = get_session_vault_paths(sess_id)
        with memory_transaction(sess_id):
            # Shared durable facts were previously omitted here, which meant an opted-in
            # persona could share autobiographical chatter while its actual factual canary was
            # literally absent from the candidate bank.  Factual memory is the first source so
            # current learned facts participate in the same semantic ranking as deep/working.
            for vault in ("factual_memory", "deep_memory", "working_memory"):
                data = load_json(paths.get(vault, ""), [])
                if not isinstance(data, list):
                    continue
                for entry in data:
                    if isinstance(entry, dict):
                        text_val = str(entry.get("text") or entry.get("summary") or "").strip()
                    else:
                        text_val = str(entry or "").strip()
                    if not text_val:
                        continue
                    if text_val not in provenance:
                        all_foreign_memories.append(text_val)
                        provenance[text_val] = set()
                    provenance[text_val].add(str(getattr(sess, "agent_name", sess_id) or sess_id))

    if not all_foreign_memories:
        return []

    matches = semantic_rank(str(query), all_foreign_memories, top_k=max(1, int(top_k)))
    formatted = []
    for memory in matches:
        sources = sorted(provenance.get(memory, {"Unknown persona"}))
        formatted.append(
            f"[Cross-Persona Insight — source: {', '.join(sources)}; second-hand]: {memory}"
        )
    return formatted
