# brain.py — Emergent Persona Edition
# Dunoon Daemon — Unified Brain Layer

import os
import psutil

from model_handler import create_model_handler
from overmind import overmind


class Brain:
    """
    Central cognitive routing engine for Dunoon Daemon Controller.
    """
    def __init__(self, model_handler=None):
        self.model_handler = model_handler

    def infer(self, user_text: str, session) -> str:
        return overmind(user_text, session, model_handler=self.model_handler)

    # ------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------

    def ask(self, user_text: str, session) -> str:
        """
        Unified inference entry point.
        Uses Overmind for cognitive fusion and the model handler for inference.
        """
        return overmind(user_text, session, model_handler=self.model_handler)

    # ------------------------------------------------------------
    # CPU Affinity
    # ------------------------------------------------------------

    def detect_p_cores(self):
        """
        Detect performance cores on modern CPUs.
        Fallback: use all cores.
        """
        try:
            info = psutil.cpu_freq(percpu=True)
            freqs = [c.current for c in info]

            p_cores = list(range(psutil.cpu_count()))

            print(f"[Brain] Detected P-cores: {p_cores}")
            return p_cores if p_cores else list(range(psutil.cpu_count()))
        except Exception as e:
            print(f"[Brain] P-core detection failed: {e}")
            return list(range(psutil.cpu_count()))

    def set_affinity(self, cores):
        """
        Pin the controller process to P-cores.
        """
        try:
            p = psutil.Process(os.getpid())
            p.cpu_affinity(cores)
            print(f"[Brain] Affinity set to cores: {cores}")
        except Exception as e:
            print(f"[Brain] Affinity failed: {e}")