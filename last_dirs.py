from __future__ import annotations

"""Persistent per-use-case file-dialog directories for Dunoon Daemon.

Each file-picker use-case remembers its own last successful directory so model loading,
avatars and attachments stop yanking the user back to an unrelated folder.
"""

import json
import os
import tempfile
from typing import Dict

from config import BASE_DIR

LAST_DIRS_FILE = os.path.join(BASE_DIR, "last_dirs.json")


def _read() -> Dict[str, str]:
    try:
        with open(LAST_DIRS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if v}
    except Exception:
        pass
    return {}


def _write(data: Dict[str, str]) -> None:
    os.makedirs(os.path.dirname(LAST_DIRS_FILE) or BASE_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="last_dirs_", suffix=".json.tmp", dir=os.path.dirname(LAST_DIRS_FILE) or BASE_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp, LAST_DIRS_FILE)
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass


def get_last_dir(use_case: str, fallback: str | None = None) -> str:
    """Return the last existing directory for one picker use-case."""
    key = str(use_case or "general").strip().lower()
    data = _read()
    path = data.get(key, "")
    if not path and key == "model":
        path = data.get("last_model_dir", "")  # legacy controller compatibility
    if path and os.path.isdir(path):
        return path
    fallback = fallback or os.path.expanduser("~")
    return fallback if os.path.isdir(fallback) else BASE_DIR


def remember_path(use_case: str, path: str) -> None:
    """Persist the directory containing *path* (or *path* itself if it is a directory)."""
    if not path:
        return
    candidate = os.path.abspath(os.path.expanduser(str(path)))
    directory = candidate if os.path.isdir(candidate) else os.path.dirname(candidate)
    if not directory or not os.path.isdir(directory):
        return
    key = str(use_case or "general").strip().lower()
    data = _read()
    data[key] = directory
    if key == "model":
        data["last_model_dir"] = directory  # legacy controller compatibility
    _write(data)
