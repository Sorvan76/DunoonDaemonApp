from __future__ import annotations

"""Shared persona-scoped memory transaction primitives.

All learned-memory writers for a persona should use the same re-entrant lock. Atomic
os.replace prevents torn files; this module additionally prevents lost-update races where
multiple writers read the same old file and later overwrite each other's changes.
"""

import json
import os
import tempfile
import threading
import time
import errno
from contextlib import contextmanager

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_GENERATIONS: dict[str, int] = {}


def _key(session_id) -> str:
    return str(session_id or "__global__")


def get_memory_lock(session_id=None) -> threading.RLock:
    key = _key(session_id)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


def get_memory_generation(session_id=None) -> int:
    key = _key(session_id)
    with _LOCKS_GUARD:
        return int(_GENERATIONS.get(key, 0))


def bump_memory_generation(session_id=None) -> int:
    """Invalidate background work that began against an older memory state."""
    key = _key(session_id)
    with _LOCKS_GUARD:
        value = int(_GENERATIONS.get(key, 0)) + 1
        _GENERATIONS[key] = value
        return value


@contextmanager
def memory_transaction(session_id=None):
    lock = get_memory_lock(session_id)
    with lock:
        yield


def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data
    except Exception:
        # Return a fresh value for the mutable defaults used by Dunoon.
        if isinstance(default, list):
            return list(default)
        if isinstance(default, dict):
            return dict(default)
        return default


def replace_with_retry(src: str, dst: str, *, attempts: int = 10, base_delay: float = 0.015) -> None:
    """Replace ``dst`` atomically, tolerating brief Windows sharing/AV locks.

    Windows can transiently reject ``os.replace`` with WinError 5 while another thread,
    scanner, backup reader, or antivirus process has the destination open.  Retrying the same
    already-fsynced temp file is safe and prevents a successful write from being discarded
    merely because the destination was momentarily busy.  Non-permission failures still raise
    immediately.
    """
    attempts = max(1, int(attempts))
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except OSError as exc:
            transient = isinstance(exc, PermissionError) or getattr(exc, "errno", None) in {errno.EACCES, errno.EPERM}
            if not transient or attempt >= attempts - 1:
                raise
            time.sleep(min(0.20, float(base_delay) * (attempt + 1)))


def atomic_save_json(path: str, data) -> bool:
    """Durably replace one JSON file. Returns True on success, False on failure."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=os.path.basename(path) + ".tmp.", dir=directory)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except Exception:
                pass
        replace_with_retry(tmp_path, path)
        return True
    except Exception as exc:
        print(f"[Memory Persistence Warning] Failed to save {path}: {exc}")
        if tmp_path:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
        return False
