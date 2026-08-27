from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

from config import DATA_DIR


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def log_arena_diagnostic(event: str, **fields: Any) -> None:
    """🐉 Silver Wyrm diagnostic: temporary Arena admission / causality observability.

    This is intentionally append-only, local, concise and disposable. It exists so we can
    prove why a candidate/Director decision was accepted, rejected or crystallised rather
    than adding speculative runtime machinery.
    """
    try:
        directory = os.path.join(DATA_DIR, "diagnostics")
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "arena_causal_timeline.log")
        payload: Dict[str, Any] = {"ts": _now(), "event": str(event)}
        payload.update(fields)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        # Diagnostics must never become another Arena failure mode.
        pass
