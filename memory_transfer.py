# memory_transfer.py — Cross-Persona Semantic Distillation Bridge
import os
import json
from config import get_session_vault_paths
from memory_embeddings import semantic_search

def retrieve_cross_persona_insights(query: str, current_session, sm, top_k: int = 2) -> list:
    """Scans all permitted foreign vaults and extracts highly relevant semantic matches."""
    if not sm or not query:
        return []
        
    all_foreign_memories = []
    provenance = {}
    current_id = getattr(current_session, "id", None)
    
    # 1. Iterate over all existing sessions in the registry
    for sess_id, sess in getattr(sm, "sessions", {}).items():
        if sess_id == current_id:
            continue
            
        # 2. Skip if the persona has NOT explicitly opted-in to share insights
        if not getattr(sess, "share_insights", False):
            continue
            
        # 3. Pull from their Deep and Working memory vaults
        paths = get_session_vault_paths(sess_id)
        for vault in ["deep_memory", "working_memory"]:
            path = paths.get(vault)
            if path and os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            for entry in data:
                                if isinstance(entry, dict):
                                    text_val = entry.get("text", "")
                                    if text_val:
                                        text_val = text_val.strip()
                                        all_foreign_memories.append(text_val)
                                        provenance.setdefault(text_val, set()).add(getattr(sess, "agent_name", sess_id))
                                elif isinstance(entry, str) and entry.strip():
                                    text_val = entry.strip()
                                    all_foreign_memories.append(text_val)
                                    provenance.setdefault(text_val, set()).add(getattr(sess, "agent_name", sess_id))
                except Exception:
                    pass
                    
    if not all_foreign_memories:
        return []
        
    # 4. Deduplicate and execute SentenceTransformer semantic sweep
    unique_memories = list(set(all_foreign_memories))
    matches = semantic_search(query, unique_memories, top_k=top_k)
    
    # 5. Format as injected system cues
    formatted = []
    for m in matches:
        if not m:
            continue
        sources = sorted(provenance.get(m, {"Unknown persona"}))
        source_label = ", ".join(sources)
        formatted.append(f"[Cross-Persona Insight — source: {source_label}; second-hand]: {m}")
    return formatted