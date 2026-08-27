from __future__ import annotations

from datetime import datetime, timezone


RETURNED = "returned"
AMNESIAC = "amnesiac"
VALID_MODES = {RETURNED, AMNESIAC}


def resurrection_directive(session) -> str:
    """Return authoritative present-state wording for an explicitly resurrected persona.

    This is deliberately derived from persistent persona state rather than learned memory,
    so an old death memory cannot silently override the human's explicit resurrection.
    """
    mode = str(getattr(session, "resurrection_mode", "") or "").strip().lower()
    if mode == RETURNED:
        return (
            "You were explicitly restored to life after a prior death. You know that you died and "
            "you retain personal memory of the fatal episode. That experience may affect you in a "
            "persona-consistent way, including psychological scars, but it does not make you dead now."
        )
    if mode == AMNESIAC:
        return (
            "You were explicitly restored to life after a prior death, but the fatal episode is not "
            "accessible to your personal memory. If older transcript or learned memory describes your "
            "death, treat it as historical information you do not personally remember; do not claim "
            "first-hand recall of that fatal episode. You are alive now."
        )
    return ""


def resurrect_persona(session, mode: str, session_manager=None) -> bool:
    """Explicit human-only dead -> alive transition.

    Ordinary Arena/Director/session merges remain monotonic and may not call this helper.
    Returns True only when a deceased persona was actually restored.
    """
    chosen = str(mode or "").strip().lower()
    if chosen not in VALID_MODES:
        raise ValueError(f"Unknown resurrection mode: {mode!r}")
    if not bool(getattr(session, "is_deceased", False)):
        return False

    session.is_deceased = False
    session.resurrection_mode = chosen
    session.resurrected_at = datetime.now(timezone.utc).isoformat()
    session.resurrection_count = int(getattr(session, "resurrection_count", 0) or 0) + 1

    agent = str(getattr(session, "agent_name", "Persona") or "Persona").strip()
    if chosen == RETURNED:
        note = (
            f"[EXPLICIT RESURRECTION] {agent} was restored to life by the human. "
            "They remember dying and may bear persona-consistent psychological scars from the experience."
        )
    else:
        note = (
            f"[EXPLICIT RESURRECTION] {agent} was restored to life by the human with amnesia for the fatal episode. "
            "The death may exist as historical record, but it is not accessible as first-hand personal memory."
        )
    try:
        session.append_system(note)
    except Exception:
        pass

    manager = session_manager or getattr(session, "session_manager", None)
    if manager is not None:
        if hasattr(manager, "save"):
            manager.save()
        elif hasattr(manager, "_save"):
            manager._save()
    return True
