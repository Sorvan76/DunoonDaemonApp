from __future__ import annotations

"""User-controlled campaign lore library and semantic retrieval.

Lore is background/source knowledge, not persona memory and not current-scene authority.
A source is visible to a persona only when the human explicitly assigns it.
"""

import os
import re
import threading
import uuid
from typing import Any

from config import DATA_DIR
from memory_semantics import semantic_rank, semantics_available
from memory_transactions import atomic_save_json, load_json, replace_with_retry

LORE_DIR = os.path.join(DATA_DIR, "lore")
LORE_SOURCES_DIR = os.path.join(LORE_DIR, "sources")
LORE_INDEX_FILE = os.path.join(LORE_DIR, "library.json")
LORE_DEPTHS = ("baseline", "intermediate", "advanced")
_LOCK = threading.RLock()


def _ensure_dirs() -> None:
    os.makedirs(LORE_SOURCES_DIR, exist_ok=True)


def _clean_name(value: str, fallback: str = "Lore source") -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text[:160] or fallback


def _session_id(session: Any) -> str:
    return str(
        getattr(session, "memory_session_id", None)
        or getattr(session, "id", None)
        or getattr(session, "session_id", None)
        or ""
    ).strip()


def _text_path(source_id: str) -> str:
    sid = re.sub(r"[^a-zA-Z0-9_-]", "", str(source_id or ""))
    if not sid:
        raise ValueError("Invalid lore source id")
    return os.path.join(LORE_SOURCES_DIR, sid + ".txt")


def _atomic_write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(str(text or ""))
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except Exception:
            pass
    replace_with_retry(tmp, path)


def _load_index() -> dict:
    _ensure_dirs()
    data = load_json(LORE_INDEX_FILE, {"version": 1, "sources": []})
    if not isinstance(data, dict):
        data = {"version": 1, "sources": []}
    rows = data.get("sources")
    if not isinstance(rows, list):
        rows = []
    clean = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("id") or "").strip()
        if not sid:
            continue
        depth = str(row.get("depth") or "baseline").lower()
        if depth not in LORE_DEPTHS:
            depth = "baseline"
        clean.append({
            "id": sid,
            "name": _clean_name(row.get("name"), "Lore source"),
            "file_name": str(row.get("file_name") or ""),
            "depth": depth,
            "secrets": bool(row.get("secrets", False)),
            "persona_ids": sorted({str(x).strip() for x in (row.get("persona_ids") or []) if str(x).strip()}),
        })
    return {"version": 1, "sources": clean}


def _save_index(data: dict) -> bool:
    _ensure_dirs()
    return atomic_save_json(LORE_INDEX_FILE, data)


class LoreLibrary:
    def list_sources(self) -> list[dict]:
        with _LOCK:
            return [dict(x) for x in _load_index()["sources"]]

    def add_source(self, name: str, text: str, *, file_name: str = "", depth: str = "baseline", secrets: bool = False) -> dict:
        body = str(text or "").strip()
        if not body:
            raise ValueError("Lore source contains no readable text.")
        depth = str(depth or "baseline").lower()
        if depth not in LORE_DEPTHS:
            depth = "baseline"
        source_id = uuid.uuid4().hex
        row = {
            "id": source_id,
            "name": _clean_name(name, os.path.basename(file_name) or "Lore source"),
            "file_name": str(file_name or ""),
            "depth": depth,
            "secrets": bool(secrets),
            "persona_ids": [],
        }
        with _LOCK:
            _atomic_write_text(_text_path(source_id), body)
            data = _load_index()
            data["sources"].append(row)
            if not _save_index(data):
                try:
                    os.remove(_text_path(source_id))
                except Exception:
                    pass
                raise OSError("Could not save lore library index.")
        return dict(row)

    def update_source(self, source_id: str, *, name=None, depth=None, secrets=None, persona_ids=None) -> dict:
        with _LOCK:
            data = _load_index()
            for row in data["sources"]:
                if row["id"] != str(source_id):
                    continue
                if name is not None:
                    row["name"] = _clean_name(name, row["name"])
                if depth is not None:
                    chosen = str(depth or "baseline").lower()
                    if chosen not in LORE_DEPTHS:
                        raise ValueError("Unsupported lore depth.")
                    row["depth"] = chosen
                if secrets is not None:
                    row["secrets"] = bool(secrets)
                if persona_ids is not None:
                    row["persona_ids"] = sorted({str(x).strip() for x in persona_ids if str(x).strip()})
                if not _save_index(data):
                    raise OSError("Could not save lore library index.")
                return dict(row)
        raise KeyError(source_id)

    def set_assignment(self, source_id: str, persona_id: str, allowed: bool) -> dict:
        pid = str(persona_id or "").strip()
        if not pid:
            raise ValueError("Invalid persona id.")
        with _LOCK:
            data = _load_index()
            for row in data["sources"]:
                if row["id"] != str(source_id):
                    continue
                ids = set(row.get("persona_ids") or [])
                if allowed:
                    ids.add(pid)
                else:
                    ids.discard(pid)
                row["persona_ids"] = sorted(ids)
                if not _save_index(data):
                    raise OSError("Could not save lore assignment.")
                return dict(row)
        raise KeyError(source_id)

    def replace_source_text(self, source_id: str, text: str, *, file_name: str = "") -> dict:
        body = str(text or "").strip()
        if not body:
            raise ValueError("Lore source contains no readable text.")
        with _LOCK:
            data = _load_index()
            for row in data["sources"]:
                if row["id"] != str(source_id):
                    continue
                _atomic_write_text(_text_path(source_id), body)
                if file_name:
                    row["file_name"] = str(file_name)
                if not _save_index(data):
                    raise OSError("Could not save lore library index.")
                return dict(row)
        raise KeyError(source_id)

    def remove_source(self, source_id: str) -> bool:
        sid = str(source_id or "")
        with _LOCK:
            data = _load_index()
            before = len(data["sources"])
            data["sources"] = [row for row in data["sources"] if row["id"] != sid]
            if len(data["sources"]) == before:
                return False
            if not _save_index(data):
                raise OSError("Could not save lore library index.")
            try:
                os.remove(_text_path(sid))
            except FileNotFoundError:
                pass
            return True

    def read_source(self, source_id: str) -> str:
        try:
            with open(_text_path(source_id), "r", encoding="utf-8") as fh:
                return fh.read()
        except Exception:
            return ""

    def assigned_sources(self, session: Any) -> list[dict]:
        pid = _session_id(session)
        if not pid:
            return []
        return [row for row in self.list_sources() if pid in set(row.get("persona_ids") or [])]


def _chunks(text: str, target: int = 900) -> list[str]:
    """Paragraph-preserving chunks. Selection remains semantic; this only bounds prompt size."""
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n+", raw) if p.strip()]
    out: list[str] = []
    buf = ""
    for para in paras:
        if len(para) > target * 2:
            if buf:
                out.append(buf); buf = ""
            start = 0
            while start < len(para):
                out.append(para[start:start + target].strip())
                start += target
            continue
        candidate = (buf + "\n" + para).strip() if buf else para
        if buf and len(candidate) > target:
            out.append(buf)
            buf = para
        else:
            buf = candidate
    if buf:
        out.append(buf)
    return [x for x in out if x]


def format_lore_context(query: str, session: Any, *, top_k: int = 4) -> str:
    """Return only semantically relevant excerpts from sources explicitly assigned to session.

    There is deliberately no lexical/keyword fallback. If the primary semantic judge is not
    available, no lore is injected rather than guessing relevance.
    """
    if not session or not str(query or "").strip() or not semantics_available():
        return ""
    library = LoreLibrary()
    sources = library.assigned_sources(session)
    if not sources:
        return ""

    candidates: list[str] = []
    for source in sources:
        body = library.read_source(source["id"])
        if not body.strip():
            continue
        depth_label = str(source.get("depth") or "baseline").title()
        access = f"{depth_label} + Secrets" if source.get("secrets") else depth_label
        for chunk in _chunks(body):
            candidates.append(f"{source['name']} | {access} | {chunk}")
    if not candidates:
        return ""

    ranked = semantic_rank(str(query), candidates, top_k=max(1, int(top_k)), min_score=0.18, purpose="lore")
    if not ranked:
        return ""
    lines = []
    for item in ranked:
        try:
            source_name, access, excerpt = item.split(" | ", 2)
        except ValueError:
            source_name, access, excerpt = "Assigned source", "Lore", item
        lines.append(f"- [LORE · {source_name} · {access}] {excerpt}")
    return (
        "[LORE]\n"
        "Human-assigned campaign source knowledge. This is background/reference knowledge the persona is allowed to know. "
        "It is not a personal memory and does not prove that a person, object, location, hazard or event is physically present in the current scene. "
        "Current human/Director reality remains authoritative.\n"
        + "\n".join(lines)
    )
