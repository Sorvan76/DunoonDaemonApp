from __future__ import annotations

"""🐉 Silver Wyrm diagnostic: temporary eye / memory timeline; remove once release behaviour is verified."""

from datetime import datetime
import os
import threading
from config import DATA_DIR

ENABLED = True
LOG_FILE = os.path.join(DATA_DIR, "diagnostics", "eye_state_timeline.log")
_LOCK = threading.RLock()

def _stamp():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")

def _write(kind: str, detail: str):
    if not ENABLED:
        return
    clean = str(detail or "").replace("\n", " ")[:1200]
    line = f"{_stamp()}  {kind:<10}  {clean}\n"
    with _LOCK:
        try:
            os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass

def log_eye_state(state: str, colour: str, reason: str = ""):
    _write("EYES", f"state={state} colour={colour} reason={reason or 'state_change'}")

def log_dialogue(role: str, text: str, persona: str = "", chat_mode: str = ""):
    who = f" persona={persona}" if persona else ""
    mode = f" mode={chat_mode}" if chat_mode else ""
    _write(str(role or "DIALOGUE").upper(), f"{who}{mode} text={str(text or '').strip()}")
