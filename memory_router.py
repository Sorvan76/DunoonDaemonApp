# memory_router.py — Session-Scoped Semantic Intent Router
import os
import json
from datetime import datetime, timezone
from config import (
    WORKING_MEMORY_FILE, DEEP_MEMORY_FILE, INTENT_MEMORY_FILE,
    TASK_MEMORY_FILE, FACTUAL_MEMORY_FILE, CONTINUATION_MEMORY_FILE, RESET_MEMORY_FILE,
    get_session_vault_paths
)
from memory_embeddings import embed, semantic_search, cosine_similarity
from significance import score_significance
from memory_validation import validate_memory

def _load_list(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []

def _save_list(path, data):
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

VAULT_SEMANTIC_DEFINITIONS = {
    "intent": "A desired outcome, goal, request, plan, direction, or intention that should influence what should be achieved.",
    "task": "A concrete action, commitment, obligation, work item, procedure, next step, or unfinished piece of work.",
    "factual": "A stable reusable fact about a person, character, relationship, preference, project, world, object, rule, capability, or history.",
    "continuation": "A cue whose primary meaning is to resume, extend, continue, or pick up an already active thread.",
    "reset": "An explicit intention to abandon, reset, discard, or replace the currently active topic, state, plan, or context.",
}

VAULT_PATHS = {
    "intent": INTENT_MEMORY_FILE,
    "task": TASK_MEMORY_FILE,
    "factual": FACTUAL_MEMORY_FILE,
    "continuation": CONTINUATION_MEMORY_FILE,
    "reset": RESET_MEMORY_FILE,
    "working": WORKING_MEMORY_FILE,
    "deep": DEEP_MEMORY_FILE,
}

_VAULT_VECTOR_CACHE = {}

def _definition_vector(vault_name):
    if vault_name not in _VAULT_VECTOR_CACHE:
        definition=VAULT_SEMANTIC_DEFINITIONS.get(vault_name,"")
        _VAULT_VECTOR_CACHE[vault_name]=embed(definition) if definition else []
    return _VAULT_VECTOR_CACHE[vault_name]

def detect_vault(text):
    text_vec=embed(text)
    if not text_vec: return None,0.0
    best_vault=None; best_score=-1.0
    for vault in VAULT_SEMANTIC_DEFINITIONS:
        v=_definition_vector(vault)
        if not v: continue
        score=cosine_similarity(text_vec,v)
        if score>best_score: best_score=score; best_vault=vault
    return best_vault,max(0.0,best_score)

def analyse_semantic_relations(text, vault_path):
    memories = _load_list(vault_path)
    if not memories:
        return 1.0, 0.0, 0.0

    results = semantic_search(text, memories, top_k=5)
    if not results:
        return 1.0, 0.0, 0.0

    text_vec = embed(text)
    top_scores = [cosine_similarity(text_vec, embed(r)) for r in results]
    reinforcement = sum(s for s in top_scores if s > 0.75) / len(top_scores)
    contradiction = sum(1 - s for s in top_scores if s < 0.25) / len(top_scores)
    novelty = 1 - max(top_scores)

    return novelty, reinforcement, contradiction

def save_to_vault(vault, text, session_id=None):
    if session_id:
        paths = get_session_vault_paths(session_id)
        # Map shorthand vault names to dictionary keys
        vault_key = f"{vault}_memory" if not vault.endswith("_memory") and vault in ["working", "deep", "intent", "task", "factual", "continuation", "reset"] else vault
        path = paths.get(vault_key, paths.get(vault, VAULT_PATHS.get(vault)))
    else:
        path = VAULT_PATHS.get(vault, WORKING_MEMORY_FILE)

    data = _load_list(path)
    if text not in data:
        data.append(text)
    _save_list(path, data)

def route_memory(text, session=None, is_user=True):
    if not validate_memory(text):
        return {
            "vault": None,
            "reason": "validation_failed",
            "significance": 0.0,
            "novelty": 0.0,
            "reinforcement": 0.0,
            "contradiction": 0.0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    session_id = getattr(session, "session_id", None) or getattr(session, "id", None) if session else None
    vault, vault_score = detect_vault(text)

    if vault_score < 0.45:
        vault = "working" if is_user else "deep"

    if session_id:
        paths = get_session_vault_paths(session_id)
        vault_key = f"{vault}_memory" if f"{vault}_memory" in paths else vault
        target_path = paths.get(vault_key, VAULT_PATHS[vault])
    else:
        target_path = VAULT_PATHS[vault]

    novelty, reinforcement, contradiction = analyse_semantic_relations(text, target_path)
    significance = score_significance(text, session_id=session_id)
    save_to_vault(vault, text, session_id=session_id)

    return {
        "vault": vault,
        "reason": f"semantic_definition_match:{vault_score:.2f}",
        "significance": significance,
        "novelty": novelty,
        "reinforcement": reinforcement,
        "contradiction": contradiction,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }