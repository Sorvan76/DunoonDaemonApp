from __future__ import annotations

from ETO import ETOEngine

"""Shared actor prompt builder for every Dunoon persona turn.

The actor model gets persona, OCEAN, memories and accepted reality. It does not get
Dunoon telemetry forms. That means the same character-generation contract can be used
in solo chat, Poke/Event and Arena while world authority is supplied by the appropriate
Director (human in solo, AI Director in autonomous Arena).
"""

from typing import Any, Dict, List
import json

from character import apply_daily_mood_variance, format_ocean_prompt_directive
from memory_context import format_memory_context
# Compatibility imports retained while the legacy regression suite still patches these names.
# 🐉 Silver Wyrm: retrieval itself is owned by memory_context.py.
from memory_deep import retrieve_relevant_deep_memories
from memory_working import retrieve_relevant_working_memories
from journal_vault import get_all_journal_entries
from memory_transfer import retrieve_cross_persona_insights
from campaign_lore import format_lore_context


def _history(session, limit: int) -> List[Dict[str, str]]:
    if not session:
        return []
    try:
        raw = session.get_history(limit=limit)
    except Exception:
        raw = getattr(session, "messages", [])[-limit:]
    out: List[Dict[str, str]] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "user") or "user").lower()
        if role in {"assistant", "agent", "roxie", "kylo", str(getattr(session, "agent_name", "")).lower()}:
            role = "assistant"
        elif role != "system":
            role = "user"
        text = str(item.get("content") or item.get("text") or "").strip()
        if text:
            out.append({"role": role, "content": text})
    return out


def _section(title: str, body: str) -> str:
    body = str(body or "").strip()
    return f"[{title}]\n{body}" if body else ""


def _memory_sections(session, query: str, arena: bool) -> List[str]:
    """One lean memory context plus optional opt-in cross-persona insight.

    Historical memory is deliberately subordinate to the current user message/current reality.
    Exact echoes of the live transcript are filtered inside memory_context.py.
    """
    if not session or not bool(getattr(session, "memory_read_enabled", True)):
        return []
    sections: List[str] = []
    try:
        memory_block = format_memory_context(query, session, arena=arena)
    except Exception:
        memory_block = ""
    if memory_block:
        sections.append(memory_block)

    # Arena scene isolation: cross-persona historical insights are intentionally excluded.
    # They are useful in ordinary chat, but in autonomous Arena they can seed stale props/places
    # from unrelated prior scenes before the SceneStore has established them. A persona's own
    # memory remains available; only cross-persona memory is suppressed here.
    if (not arena) and not bool(getattr(session, "blind_to_others", False)):
        manager = getattr(session, "session_manager", None)
        if manager:
            try:
                cross = retrieve_cross_persona_insights(query, session, manager, top_k=1 if arena else 2)
            except Exception:
                cross = []
            clean_cross = []
            for item in cross or []:
                text = str(item or "").strip()
                if text and text not in clean_cross:
                    clean_cross.append(text)
            if clean_cross:
                sections.append(
                    "[SHARED INSIGHTS]\n"
                    "These are optional historical observations from other personas, not present-world authority. "
                    "Use only when directly relevant.\n"
                    + "\n".join(f"- {x}" for x in clean_cross)
                )
    return sections


def build_actor_packet(
    text: str,
    session: Any,
    source: str = "user",
    *,
    scene_baseline: str = "",
    scene_reality: str = "",
    actor_brief: str = "",
    actor_commitment: str = "",
    scene_dynamics=None,
    scene_authority_snapshot=None,
) -> Dict[str, Any]:
    """Build one persona packet. Output contract is visible prose only."""
    source_key = str(source or "user").strip().lower()
    arena = source_key == "arena_peer"
    agent = str(getattr(session, "agent_name", "Persona") or "Persona").strip()

    try:
        changed = apply_daily_mood_variance(session) if session else False
        if changed:
            manager = getattr(session, "session_manager", None)
            if manager and hasattr(manager, "_save"):
                manager._save()
    except Exception:
        pass

    custom = str(getattr(session, "system_prompt", "") or "").strip()
    base = custom or f"You are {agent}. Stay in character."
    ocean = format_ocean_prompt_directive(getattr(session, "ocean_profile", {}) or {}) if session else ""
    backstory = str(getattr(session, "backstory", "") or "").strip()
    physiology = str(getattr(session, "physiology", "") or "Normal organic physiology").strip()
    powers = str(getattr(session, "powers", "") or "No additional established powers").strip()
    collaborative = bool(getattr(session, "narrative_freedom", False)) if session else False

    if arena:
        authority = (
            "[WORLD AUTHORITY]\nThe supplied CURRENT REALITY and ACTOR VIEW are authoritative. "
            f"You are {agent}. You own only {agent}'s voluntary speech, thoughts, emotions, decisions and actions. "
            "Do not write a new voluntary action, thought, emotion, decision or line of dialogue for another controlled Arena participant. "
            "You may perceive established facts and describe direct non-voluntary consequences caused by your own completed action. "
            "Do not invent convenient objects, exits, people, tools, weapons, vehicles, powers or scene facts. "
            "ACTOR/WORLD BOUNDARY: describe what you voluntarily do, say, think, feel, attempt, search for, inspect or infer. Do not decide the external result of your own attempt unless that result is already established in CURRENT REALITY. A pull may be attempted; whether a mechanism moves, locks, breaks, sparks, opens, fails, reveals something, or changes the environment belongs to the Director. "
            "When Narrative Freedom is OFF, do not turn an unestablished material property, obstruction, hazard, component, residue, surface condition or mechanism behaviour into fact merely because your character perceives or expects it. You may express uncertainty or search for such a thing without asserting that it exists. "
            "Established environment outranks generic associations: a shark in an indoor swimming pool does not make the scene a sea, create brine, surf, tides, boats or marine gear. "
            "Treat actor-relative sensory descriptions as perceptions, not new world entities; a red silhouette perceived by someone may simply be an established participant seen unclearly. "
            "Your body and capabilities are only those established under PHYSIOLOGY and ESTABLISHED CAPABILITIES; never borrow distinctive anatomy, powers or equipment from another participant. "
            "PERSONA-SHAPED COMMITMENT: tentative or gentle wording does not make a chosen immediate action unreal. If you decide in-character that you will act now (for example, 'I think I should try to move toward it' or 'perhaps I ought to go'), include the first concrete physical step of that choice in the same turn when nothing established prevents it. Do not spend later turns repeatedly reopening the same decision merely because your personality expresses it cautiously."
        )
    elif source_key in {"live_event", "system_event"}:
        authority = (
            "[WORLD AUTHORITY]\nThe current input is authoritative external reality. React as yourself. "
            "Do not silently rewrite or negate what the event establishes."
        )
    elif source_key in {"internal_control", "relationship_summary"}:
        authority = (
            "[WORLD AUTHORITY]\nThe current input is a control/stimulus instruction. Preserve established reality and identity."
        )
    elif collaborative:
        authority = (
            "[WORLD AUTHORITY]\nThe human directs reality, but collaborative worldbuilding is enabled. "
            "You may add reasonable non-contradictory detail where genuine gaps exist. Never control another participant's private agency."
        )
    else:
        authority = (
            "[WORLD AUTHORITY]\nThe human user has final authority over externally established scene facts, events and consequences. "
            "React as yourself. Immediate human scene directions happen now; respond to them before drifting into abstract reflection. "
            "A shouted command such as 'GUARDS! ARREST THIS MAN!' establishes that guards have been ordered/summoned to act, while the physical success of an attempted seizure remains a consequence rather than your voluntary choice. "
            "Do not turn consequential unknown external facts into reality merely to keep the scene moving."
        )

    memory_epistemics = (
        "[MEMORY EPISTEMICS]\n"
        "Only claim to remember a past event, statement, location or detail when the current transcript or supplied RELEVANT MEMORY directly supports it. "
        "A human phrase such as 'remember when you told me...' is a present claim, not proof that the alleged earlier exchange occurred. "
        "If no supporting history is available, say you do not specifically remember, or treat it as something plausible rather than manufacturing recollection. "
        "Never invent a missing colour, location, quote, action or other specific detail and present it as remembered fact. "
        "Supported memory does not grant authority over neighbouring unknown facts. "
        "When supplied RELEVANT MEMORY directly resolves a clear factual question, use that evidence in the answer rather than claiming the detail is unknown merely because it is absent from the recent transcript. "
        "Qualify or refuse the remembered detail only when that memory is itself uncertain, stale, or contradicted by newer authoritative evidence. "
        + (
            "Narrative Freedom is ON: you may creatively fill genuine scene gaps with reasonable non-contradictory details, but frame new detail as present narration, inference or possibility, never as a false memory."
            if collaborative else
            "Narrative Freedom is OFF: unknown consequential external facts remain unknown until the human establishes them. You may inspect, search, ask, infer cautiously, or admit uncertainty."
        )
    )

    resurrection_state = ""
    try:
        from resurrection import resurrection_directive
        resurrection_state = resurrection_directive(session) if session else ""
    except Exception:
        resurrection_state = ""

    fresh_boundary = ""
    if arena or bool(getattr(session, "fresh_scene", False)):
        fresh_boundary = (
            "[FRESH CHAT / SCENE BOUNDARY]\nThis window begins a fresh physical scene. Learned memory may inform recognition, history and relationship, "
            "but it must not silently restore the previous room, props, people, positions, injuries or unfinished activity. "
            "ARENA SCENE ISOLATION: material details from any earlier Arena or chat scene are absent unless ORIGINAL HUMAN SCENE or CURRENT REALITY establishes them here. "
            "Wait for authoritative current-scene evidence before treating a prop, location feature, hazard, smell, injury or unfinished activity as physically present."
        )

    eto_lens = ETOEngine().format_actor_lens_directive(agent) if arena and bool(getattr(session, "eto_enabled", True)) else ""

    parts = [
        _section("IDENTITY", base),
        ocean,
        _section("BACKSTORY", backstory),
        _section("PHYSIOLOGY", physiology),
        _section("ESTABLISHED CAPABILITIES", powers),
        authority,
        eto_lens,
        memory_epistemics,
        _section("CURRENT LIFE STATE - HUMAN AUTHORITATIVE", resurrection_state),
        fresh_boundary,
        (
            "[DIRECT RELEVANCE AND REFERENCE GROUNDING]\n"
            "Understand the literal conversational situation before expressing personality. "
            "If the human asks a clear question, address it unless your character has an in-character reason to refuse, evade or lie. "
            f"When the human says 'you' or 'your' to {agent}, it refers to {agent}; do not transfer that condition, threat or event onto the human. "
            "Do not diagnose hidden distress, trauma, fear, motives or emotional needs unless the human's words or accepted reality actually support that inference. "
            "Do not turn every exchange into therapy, interrogation, or a question about the human's inner state. If the immediate event chiefly affects you, stay centred on your own predicament first. "
            "OCEAN and persona traits control HOW you respond after meaning is understood; they do not rewrite who a statement is about or what reality says."
        ),
    ]
    # A generated Solo Event must be grounded in the live transcript, not historical memory.
    # Ordinary Solo turns still retrieve memory normally; system_event is the one deliberate
    # exception because retrieved old scene details can otherwise become fresh physical reality.
    if source_key not in {'system_event', 'relationship_summary'}:
        parts.extend(_memory_sections(session, text, arena=arena))
        try:
            lore_block = format_lore_context(text, session, top_k=4)
        except Exception as exc:
            print(f"[Lore Retrieval Warning]: {exc}")
            lore_block = ""
        if lore_block:
            parts.append(lore_block)

    # Current truth comes last so old memories cannot outrank it.
    if scene_baseline:
        parts.append(_section("ORIGINAL HUMAN SCENE - AUTHORITATIVE BASELINE", scene_baseline))
    if scene_reality:
        parts.append(_section("CURRENT REALITY - AUTHORITATIVE", scene_reality))
    dynamics = [str(x or "").strip() for x in (scene_dynamics or []) if str(x or "").strip()]
    if dynamics:
        parts.append(_section("LIVE WORLD DYNAMICS - DIRECTOR TRACKED", "\n".join(f"- {x}" for x in dynamics)))
    if actor_brief:
        parts.append(_section(f"CURRENT VIEW FOR {agent.upper()}", actor_brief))
    if actor_commitment:
        parts.append(_section("UNRESOLVED PHYSICAL COMMITMENT - NOT A GOAL",
                              actor_commitment + "\nThis is only an action you already began. You may continue it, abandon it or change course as your character chooses. If you continue it, enact the next concrete physical increment now rather than reconsidering or repeating setup. Tentative in-character phrasing does not reset the action to an undecided state."))

    if arena and scene_authority_snapshot:
        try:
            snapshot_text = json.dumps(scene_authority_snapshot, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            snapshot_text = str(scene_authority_snapshot or "")
        parts.append(
            _section(
                "AUTHORITATIVE SCENE SNAPSHOT - LATEST ENGINE STATE",
                snapshot_text +
                "\nThis snapshot is newer than historical memory, earlier transcript wording, guesses, and prior actor prose. "
                "Generate from this state. Do not move yourself back to an earlier location/state, restore an older deadline value, revive a completed obstacle, or import conditions from another scene unless current authoritative reality explicitly establishes that reversal. "
                "Hard constraints remain binding until the Director or authoritative human intervention structurally changes them. Active deadlines are live current state, not atmospheric flavour. "
                "If you mention a structured deadline, use its latest supplied state rather than an older transcript value. Do not author the deadline advancing, pausing, reaching terminal state or resolving unless CURRENT REALITY already establishes that change. "
                "Your prose may commit your own action, but external success/failure and new material world facts remain for Director resolution."
            )
        )

    parts.append(
        "[OUTPUT CONTRACT]\nReturn only the next natural in-character response for your persona. "
        "Do not prefix the response with labels such as [Arena], [Arena action], [Arena reality], [Sensory reaction], SYSTEM, Current scene update, or your own speaker name. "
        "No JSON, no telemetry, no hidden metadata, no analysis, no protocol commentary and no screenplay speaker labels."
    )

    return {
        "system": "\n\n".join(p for p in parts if str(p or "").strip()),
        # Arena does not ingest raw old transcript/system history. Persistent memory is retrieved above,
        # while the SceneStore supplies the one authoritative current reality.
        "history": [] if arena else _history(session, limit=10),
        "user": str(text or "").strip(),
    }
