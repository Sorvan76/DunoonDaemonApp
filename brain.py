# brain.py — Dunoon Daemon unified cognitive boundary

import os
import psutil

from core.native_backend import NativeModelBackend
from core.turn_engine import TurnEngine


class Brain:
    """Single public cognitive entry point for every Dunoon interaction mode.

    The UI may still call infer()/ask() exactly as before. Model transport is now owned by
    one native backend and the TurnEngine, so chat/Arena/event/poke code no longer decides
    which inference service to use.
    """

    def __init__(self, model_handler=None):
        self.backend = NativeModelBackend(model_handler)
        self.turn_engine = TurnEngine(self.backend)
        if model_handler is not None:
            try:
                from memory_semantics import set_primary_model_handler
                set_primary_model_handler(model_handler)
            except Exception as exc:
                print(f"[Memory Semantics Warning] Could not register primary model: {exc}")

    @property
    def model_handler(self):
        # 🐉 Silver Wyrm: Compatibility for controller/dunoon_daemon while UI surgery is staged.
        return self.backend.handler

    @model_handler.setter
    def model_handler(self, handler):
        self.backend.set_handler(handler)
        try:
            from memory_semantics import set_primary_model_handler, clear_primary_model_handler
            if handler is None:
                clear_primary_model_handler()
            else:
                set_primary_model_handler(handler)
        except Exception as exc:
            print(f"[Memory Semantics Warning] Could not update primary model registration: {exc}")

    def infer(self, user_text: str, session, source: str = "user", commit_lifecycle: bool = True,
              *, scene_reality: str = "", actor_brief: str = "") -> str:
        return self.turn_engine.infer(
            user_text, session, source=source, commit_lifecycle=commit_lifecycle,
            scene_reality=scene_reality, actor_brief=actor_brief
        )

    def ask(self, user_text: str, session, source: str = "user", commit_lifecycle: bool = True) -> str:
        return self.infer(user_text, session, source=source, commit_lifecycle=commit_lifecycle)

    def detect_p_cores(self):
        try:
            # Preserve the existing behaviour for now; affinity is an optional runtime tuning layer.
            psutil.cpu_freq(percpu=True)
            p_cores = list(range(psutil.cpu_count()))
            print(f"[Brain] Detected P-cores: {p_cores}")
            return p_cores if p_cores else list(range(psutil.cpu_count()))
        except Exception as e:
            print(f"[Brain] P-core detection failed: {e}")
            return list(range(psutil.cpu_count()))

    def set_affinity(self, cores):
        try:
            p = psutil.Process(os.getpid())
            p.cpu_affinity(cores)
            print(f"[Brain] Affinity set to cores: {cores}")
        except Exception as e:
            print(f"[Brain] Affinity failed: {e}")
