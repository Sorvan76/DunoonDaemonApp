# bridge.py — transport completion state shared by Dunoon's native model backend
import threading

_reply_state = threading.local()


def reset_last_finish_reason() -> None:
    _reply_state.finish_reason = None


def get_last_finish_reason():
    return getattr(_reply_state, "finish_reason", None)


def set_last_finish_reason(reason) -> None:
    _reply_state.finish_reason = reason
