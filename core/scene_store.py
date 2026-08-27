from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, List

from config import DATA_DIR


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SceneRecord:
    scene_id: str
    initial_prompt: str
    current_reality: str
    participants: List[str] = field(default_factory=list)
    actor_briefs: Dict[str, str] = field(default_factory=dict)
    actor_status: Dict[str, str] = field(default_factory=dict)
    active_commitments: Dict[str, str] = field(default_factory=dict)
    commitment_age: Dict[str, int] = field(default_factory=dict)
    simmer_streak: int = 0
    mandatory_progress_lock: bool = False
    mandatory_progress_reason: str = ""
    interaction_thread_key: str = ""
    interaction_thread_label: str = ""
    interaction_thread_age: int = 0
    interaction_thread_id: str = ""
    interaction_thread_progress_reason: str = ""
    provisional_povs: Dict[str, str] = field(default_factory=dict)
    provisional_authority_verified: Dict[str, bool] = field(default_factory=dict)
    world_dynamics: List[str] = field(default_factory=list)
    hard_constraints: List[dict] = field(default_factory=list)
    causal_states: List[dict] = field(default_factory=list)
    active_deadlines: List[dict] = field(default_factory=list)
    scene_frame: dict = field(default_factory=dict)
    live_directives: List[dict] = field(default_factory=list)
    revision: int = 0
    log: List[dict] = field(default_factory=list)
    updated_at: str = field(default_factory=_now)

    def add_log(self, kind: str, text: str, actor: str = "") -> None:
        self.log.append({"kind": kind, "actor": actor, "text": str(text or "").strip(), "timestamp": _now()})
        self.log = self.log[-500:]


class SceneStore:
    """One persisted owner of autonomous Arena reality."""

    def __init__(self, base_dir: str | None = None):
        self.base_dir = base_dir or os.path.join(DATA_DIR, "scenes")
        os.makedirs(self.base_dir, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, scene_id: str) -> str:
        safe = "".join(ch for ch in str(scene_id) if ch.isalnum() or ch in "-_.") or "scene"
        return os.path.join(self.base_dir, f"{safe}.json")

    def save(self, scene: SceneRecord) -> None:
        scene.updated_at = _now()
        with self._lock:
            path = self._path(scene.scene_id)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(asdict(scene), f, indent=2, ensure_ascii=False)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
            os.replace(tmp, path)

    def load(self, scene_id: str) -> SceneRecord | None:
        path = self._path(scene_id)
        if not os.path.exists(path):
            return None
        with self._lock:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data.setdefault("actor_status", {})
                data.setdefault("active_commitments", {})
                data.setdefault("commitment_age", {})
                data.setdefault("simmer_streak", 0)
                data.setdefault("mandatory_progress_lock", False)
                data.setdefault("mandatory_progress_reason", "")
                data.setdefault("interaction_thread_key", "")
                data.setdefault("interaction_thread_label", "")
                data.setdefault("interaction_thread_age", 0)
                data.setdefault("interaction_thread_id", data.get("interaction_thread_key", ""))
                data.setdefault("interaction_thread_progress_reason", "")
                data.setdefault("provisional_povs", {})
                data.setdefault("provisional_authority_verified", {})
                data.setdefault("world_dynamics", [])
                data.setdefault("hard_constraints", [])
                data.setdefault("causal_states", [])
                data.setdefault("active_deadlines", [])
                data.setdefault("scene_frame", {})
                data.setdefault("live_directives", [])
                data.setdefault("log", [])
                return SceneRecord(**data)
            except Exception:
                return None

    def delete(self, scene_id: str) -> None:
        with self._lock:
            try:
                os.remove(self._path(scene_id))
            except FileNotFoundError:
                pass
