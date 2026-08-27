from __future__ import annotations

"""🐉 Silver Wyrm diagnostic: temporary memory admission / retrieval audit.

This module is deliberately observational. It must never influence routing, ranking,
chat-mode semantics, or eye state. Remove or disable it after longitudinal memory
behaviour is understood.
"""

from datetime import datetime
import json
import os
import threading

from config import DATA_DIR

ENABLED = True
LOG_FILE = os.path.join(DATA_DIR, "diagnostics", "memory_audit.log")
_LOCK = threading.RLock()


def _stamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _clean(value, limit: int = 500) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ").strip()[:limit]


def _write(kind: str, payload: dict) -> None:
    if not ENABLED:
        return
    row = {"ts": _stamp(), "kind": str(kind), **payload}
    with _LOCK:
        try:
            os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        except Exception:
            # Diagnostics are never allowed to affect product behaviour.
            pass


def log_admission(*, session_id="", is_user=True, semantic="", confidence=0.0,
                  significance=0.0, vault="", novelty=0.0, reinforcement=0.0,
                  contradiction=0.0, wrote=False, reason="", text="") -> None:
    _write("admission", {
        "session": _clean(session_id, 120),
        "source": "user" if is_user else "actor",
        "semantic": _clean(semantic, 80) or "none",
        "confidence": round(float(confidence or 0.0), 4),
        "significance": round(float(significance or 0.0), 4),
        "vault": _clean(vault, 80) or None,
        "novelty": round(float(novelty or 0.0), 4),
        "reinforcement": round(float(reinforcement or 0.0), 4),
        "contradiction": round(float(contradiction or 0.0), 4),
        "wrote": bool(wrote),
        "reason": _clean(reason, 240),
        "text": _clean(text),
    })


def log_retrieval(*, session_id="", query="", arena=False, fresh_scene=False,
                  selected=(), candidate_count=0, blocked_count=0) -> None:
    rows = []
    for item in selected or ():
        try:
            label, text = item
        except Exception:
            continue
        rows.append({"source": _clean(label, 80), "text": _clean(text)})
    _write("retrieval", {
        "session": _clean(session_id, 120),
        "arena": bool(arena),
        "fresh_scene": bool(fresh_scene),
        "candidate_count": int(candidate_count or 0),
        "blocked_count": int(blocked_count or 0),
        "selected_count": len(rows),
        "query": _clean(query),
        "selected": rows,
    })
