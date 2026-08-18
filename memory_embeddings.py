# memory_embeddings.py — Thread-Safe, Session-Scoped Vector Embeddings Engine
import os
import json
import threading
import numpy as np
from config import get_session_vault_paths, EMBEDDING_STORE_FILE, BASE_DIR, ensure_dirs

ensure_dirs()

EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

_model = None
_model_lock = threading.Lock()
_embed_db_lock = threading.Lock()


def _get_model():
    """Thread-safe lazy loader for SentenceTransformer."""
    global _model
    with _model_lock:
        if _model is None:
            try:
                from sentence_transformers import SentenceTransformer
                _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
            except Exception as e:
                print(f"[MemoryEmbeddings Warning] Could not load SentenceTransformer: {e}")
                _model = False
        return _model if _model is not False else None


def _resolve_store_path(session_id: str = None) -> str:
    if session_id:
        try:
            return get_session_vault_paths(str(session_id)).get(
                "embeddings",
                os.path.join(get_session_vault_paths(str(session_id))["vault_dir"], "embeddings.json")
            )
        except Exception:
            pass
    return EMBEDDING_STORE_FILE


def _load_db(file_path: str) -> dict:
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _flush_db(file_path: str, data: dict):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    tmp_path = f"{file_path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, file_path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def embed(text: str) -> list:
    """Generates normalized vector embedding for given text."""
    if not text or not str(text).strip():
        return []
    model = _get_model()
    if model is None:
        return []
    try:
        vec = model.encode(str(text).strip(), convert_to_numpy=True)
        return vec.tolist()
    except Exception:
        return []


def store_embedding(memory_text: str, session_id: str = None):
    """Computes and commits embedding to session store under thread-lock."""
    if not memory_text or not str(memory_text).strip():
        return

    clean_text = str(memory_text).strip()
    store_file = _resolve_store_path(session_id)

    with _embed_db_lock:
        db = _load_db(store_file)
        if clean_text not in db:
            vec = embed(clean_text)
            if vec:
                db[clean_text] = vec
                _flush_db(store_file, db)


def prune_embeddings(valid_texts: list, session_id: str = None):
    """Removes orphaned embeddings from store."""
    store_file = _resolve_store_path(session_id)
    with _embed_db_lock:
        db = _load_db(store_file)
        new_db = {t: db[t] for t in valid_texts if t in db}
        _flush_db(store_file, new_db)


def get_embedding(memory_text: str, session_id: str = None):
    """Retrieves embedding vector or creates it on-demand."""
    if not memory_text:
        return None

    clean_text = str(memory_text).strip()
    store_file = _resolve_store_path(session_id)

    with _embed_db_lock:
        db = _load_db(store_file)
        vec = db.get(clean_text)

    if vec is None:
        vec = embed(clean_text)
        if vec:
            with _embed_db_lock:
                db = _load_db(store_file)
                db[clean_text] = vec
                _flush_db(store_file, db)

    return np.array(vec) if vec else None


def cosine_similarity(a, b) -> float:
    if a is None or b is None:
        return -1.0

    try:
        a = np.array(a)
        b = np.array(b)

        if a.size == 0 or b.size == 0:
            return -1.0

        denom = float(np.linalg.norm(a) * np.linalg.norm(b))
        if denom == 0.0:
            return -1.0

        return float(np.dot(a, b) / denom)
    except Exception:
        return -1.0


def semantic_search(query: str, memory_texts: list, top_k: int = 5, session_id: str = None) -> list:
    """Executes vector cosine rank with keyword fallback."""
    if not memory_texts or not query:
        return []

    clean_texts = [str(m).strip() for m in memory_texts if m and str(m).strip()]
    if not clean_texts:
        return []

    query_vec = embed(query)
    if not query_vec:
        query_words = [w for w in query.lower().split() if len(w) > 2]
        matches = [m for m in clean_texts if any(w in m.lower() for w in query_words)]
        return matches[:top_k]

    scored = []
    for text in clean_texts:
        vec = get_embedding(text, session_id=session_id)
        score = cosine_similarity(query_vec, vec)
        scored.append((text, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [t for t, s in scored[:top_k] if s > 0.1]