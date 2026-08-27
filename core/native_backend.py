from __future__ import annotations

from typing import Any, Dict, Optional

from bridge import get_last_finish_reason


class NativeBackendUnavailable(RuntimeError):
    pass


class NativeModelBackend:
    """Single inference authority for Dunoon.

    This wrapper deliberately has no LM Studio fallback. The active ModelHandler owns
    llama-server and its local OpenAI-compatible endpoint.
    """

    def __init__(self, handler=None):
        self.handler = handler

    def is_ready(self) -> bool:
        return bool(self.handler and getattr(self.handler, "is_active", lambda: False)())

    def set_handler(self, handler) -> None:
        self.handler = handler

    def clear_handler(self) -> None:
        self.handler = None

    def generate(self, packet: Dict[str, Any]) -> str:
        if not self.is_ready():
            raise NativeBackendUnavailable(
                "No Dunoon Daemon-managed GGUF model is active. Load a GGUF model from the Home screen."
            )
        return self.handler.send(packet)

    @property
    def finish_reason(self) -> Optional[str]:
        return get_last_finish_reason()
