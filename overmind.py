# overmind.py — Context Fusion, Session Vault Isolation & ETO Hazard Routing Engine
import json
import os
import traceback
from config import ensure_dirs, get_session_vault_paths
from journal_vault import get_all_journal_entries
from memory_working import retrieve_relevant_working_memories
from memory_deep import retrieve_relevant_deep_memories
from bridge import lmstudio_reply, LMStudioOfflineError
from state_engine import SyntheticStateEngine
from memory_transfer import retrieve_cross_persona_insights
from character import format_ocean_prompt_directive, apply_daily_mood_variance
from ETO import ETOEngine

ensure_dirs()

DUAL_CHANNEL_SYSTEM_DIRECTIVE = (
    "\n[SYSTEM PROTOCOL: DUAL-CHANNEL COGNITIVE TELEMETRY]\n"
    "At the very start of every response, prepend one hidden JSON meta envelope exactly in this form:\n"
    '<!--meta:{"mood":"<mood_cue>","intensity":0.0,"pressure":0.0,"progress":1.0,"fatal":false,"vault":"working","significance":0.0,"state_delta":{"warmth":0.0,"directness":0.0,"analytical_depth":0.0,"cognitive_focus":0.0,"formality":0.0}}-->\n'
    "This envelope is structured semantic telemetry, never visible dialogue.\n"
    "- mood: closest existing Dunoon UI mood cue.\n"
    "- intensity: emotional/cognitive intensity, 0.0 to 1.0.\n"
    "- pressure: how strongly the established situation forces, threatens, constrains, or risks consequential action, 0.0 to 1.0.\n"
    "- progress: how much this turn materially advances or changes the active situation, 0.0 to 1.0.\n"
    "- fatal: true only if this character is explicitly dead by the end of this turn from established causal events.\n"
    "- vault: working, deep, intent, task, or factual according to payload meaning.\n"
    "- significance: long-term importance, 0.0 to 1.0.\n"
    "- state_delta: optional small numeric shifts, each between -0.08 and +0.08; use 0.0 if no meaningful shift occurred.\n"
    "Never expose or discuss the meta envelope in character dialogue."
)

def _load(path):
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []

def get_session_history(session, limit=10):
    raw_history = []
    if hasattr(session, "get_history"):
        raw_history = session.get_history(limit=limit)
    else:
        raw_history = getattr(session, "messages", [])[-limit:]

    normalized_history = []
    for m in raw_history:
        if isinstance(m, dict):
            role = m.get("role", "user")
            if role in ("roxie", "fred", "fiona", "agent", "assistant", "Kylo", getattr(session, "agent_name", "Kylo")):
                role = "assistant"
            elif role != "system":
                role = "user"

            text = m.get("text") or m.get("content") or ""
            if text.strip():
                normalized_history.append({"role": role, "content": text.strip()})

        elif isinstance(m, str) and m.strip():
            normalized_history.append({"role": "user", "content": m.strip()})

    return normalized_history

# Active Session ETO Instance Cache
_SESSION_ETO_CACHE = {}

def get_session_eto(session) -> ETOEngine:
    """Retrieves or creates an isolated ETOEngine instance for the active session."""
    session_id = getattr(session, "id", None) or getattr(session, "session_id", None) or "global"
    if session_id not in _SESSION_ETO_CACHE:
        _SESSION_ETO_CACHE[session_id] = ETOEngine(
            location=getattr(session, "location", "") or "",
            threat=getattr(session, "threat", "") or "",
            opportunity=getattr(session, "opportunity", "") or ""
        )
    else:
        inst = _SESSION_ETO_CACHE[session_id]
        # Only overwrite persistent ETO fields when the session actually carries a value.
        # Blank/default attributes must not erase a scene already grounded by earlier turns.
        location = getattr(session, "location", "") or ""
        threat = getattr(session, "threat", "") or ""
        opportunity = getattr(session, "opportunity", "") or ""
        if location:
            inst.location = location
        if threat:
            inst.threat = threat
        if opportunity:
            inst.opportunity = opportunity

    return _SESSION_ETO_CACHE[session_id]

state_engine = SyntheticStateEngine()

def format_narrative_authority_directive(session) -> str:
    """Per-persona authorship policy. Always active, even when ETO is disabled."""
    collaborative = bool(getattr(session, "narrative_freedom", False)) if session else False
    if collaborative:
        return (
            "[COLLABORATIVE WORLDBUILDING: ENABLED]\n"
            "You may reasonably fill genuine narrative gaps with new external details, discoveries, "
            "document contents, background facts, complications, locations, NPC actions, or plot "
            "developments when they naturally grow from the established scene.\n"
            "This is collaborative authorship, not unlimited control. Never contradict authoritative "
            "facts, erase established consequences, invent convenient unsupported powers/resources, "
            "or dictate another participant's private thoughts, choices, speech, or reactions."
        )
    return (
        "[NARRATIVE AUTHORITY: USER-LED]\n"
        "Control your own speech, thoughts, emotions, decisions, and voluntary actions freely, but "
        "do not turn consequential unknown external facts into established reality merely to keep "
        "the story moving.\n"
        "Unseen or unread information, unspecified document contents, hidden history, major off-screen "
        "events, new threats/resources, new locations/routes, NPC decisions, and plot-changing "
        "discoveries remain unknown until established by the user/system.\n"
        "You may make clearly uncertain guesses, suspicions, questions, and interpretations. Minor "
        "non-consequential descriptive texture is allowed when it does not create new plot obligations."
    )

def build_overmind_packet(user_text: str, session, state_engine=None, source: str = "user"):

    if session:
        if apply_daily_mood_variance(session):
            if hasattr(session, "session_manager") and session.session_manager:
                session.session_manager._save()

    history = get_session_history(session, limit=10)
    session_id = getattr(session, "id", None) or getattr(session, "session_id", None)
    paths = get_session_vault_paths(session_id) if session_id else None

    working = retrieve_relevant_working_memories(user_text, session_id=session_id, top_k=5)
    deep = retrieve_relevant_deep_memories(user_text, session_id=session_id, top_k=5)
    
    # Cross-Persona Insight Isolation Check
    cross_insights = []
    is_blind = getattr(session, "blind_to_others", False)
    if not is_blind:
        sm = getattr(session, "session_manager", None)
        if sm:
            cross_insights = retrieve_cross_persona_insights(user_text, session, sm, top_k=2)
    
    intent = _load(paths["intent_memory"])[-5:] if paths else []
    task = _load(paths["task_memory"])[-5:] if paths else []
    factual = _load(paths["factual_memory"])[-5:] if paths else []

    all_journals = get_all_journal_entries(session)
    journal_entries = [j.text for j in all_journals[-3:]] if all_journals else []

    custom_prompt = getattr(session, "system_prompt", "").strip() if session else ""
    agent_display = getattr(session, "agent_name", "Kylo") if session else "Kylo"
    base_directive = custom_prompt if custom_prompt else f"You are {agent_display}, a capable local AI assistant."

    ocean_profile = getattr(session, "ocean_profile", {}) if session else {}
    ocean_directive = format_ocean_prompt_directive(ocean_profile)

    system_prompt_parts = [
        f"[Base Directives]\n{base_directive}",
        ocean_directive,
        DUAL_CHANNEL_SYSTEM_DIRECTIVE
    ]

    # State Matrix Directives
    if state_engine:
        state_directive = state_engine.generate_system_prompt_directive()
        if state_directive:
            system_prompt_parts.append(state_directive)

    narrative_directive = format_narrative_authority_directive(session)
    if narrative_directive:
        system_prompt_parts.append(narrative_directive)

    # Inject ETO Anti-Hallucination, Physiology & Powers Grounding Block
    if session and getattr(session, "eto_enabled", True):
        eto_inst = get_session_eto(session)

        # Source authority is explicit; no prompt-word guessing.
        source_key = (source or "user").strip().lower()
        source_is_authoritative = source_key in {"user", "live_event", "system_event"}
        eto_inst.observe_narrative_input(user_text, authoritative=source_is_authoritative)

        mortality_on = getattr(session, "mortality_enabled", False)
        deceased_on = getattr(session, "is_deceased", False)
        backstory_txt = getattr(session, "backstory", "") or ""
        phys_txt = getattr(session, "physiology", "") or "Normal (Standard Organic humanoid)"
        powers_txt = getattr(session, "powers", "") or "None (Standard human baseline capabilities)"
        recent_corpus = " ".join([m.get("content", "") for m in history[-4:]]) + f" {user_text}"

        eto_block = eto_inst.format_directive(
            mortality_enabled=mortality_on,
            is_deceased=deceased_on,
            backstory=backstory_txt,
            physiology=phys_txt,
            powers=powers_txt,
            recent_context=recent_corpus
        )
        if eto_block:
            system_prompt_parts.append(eto_block)

    # Injected Memory Vaults
    if deep:
        system_prompt_parts.append("[Deep Memory]\n" + "\n".join(deep))
    if cross_insights:
        system_prompt_parts.append("[Cross-Persona Insights]\n" + "\n".join(cross_insights))
    if journal_entries:
        system_prompt_parts.append("[Journal Entries]\n" + "\n".join(journal_entries))
    if intent:
        system_prompt_parts.append("[Intent Memory]\n" + "\n".join(intent))
    if task:
        system_prompt_parts.append("[Task Memory]\n" + "\n".join(task))
    if factual:
        system_prompt_parts.append("[Factual Memory]\n" + "\n".join(factual))
    if working:
        system_prompt_parts.append("[Working Memory]\n" + "\n".join(working))

    return {
        "system": "\n\n".join(system_prompt_parts),
        "history": history,
        "user": user_text,
    }

def neutral_summarize(text: str, model_handler=None) -> str:
    """Run factual compression without persona, OCEAN, ETO, memories, or roleplay state."""
    system_prompt = (
        "You are a neutral memory consolidation engine. Summarize only information supported by "
        "the supplied logs. Do not roleplay, invent missing events, or add interpretations as facts."
    )
    packet = {"system": system_prompt, "history": [], "user": text}
    if model_handler is not None and getattr(model_handler, "is_active", lambda: False)():
        try:
            return model_handler.send(packet)
        except Exception:
            traceback.print_exc()
    try:
        return lmstudio_reply(system_prompt, text, history=[])
    except LMStudioOfflineError:
        return "(LM Studio is offline and no native GGUF model is loaded, chief.)"
    except Exception as e:
        traceback.print_exc()
        return f"(API Error: {e})"

def overmind(user_text: str, session=None, model_handler=None, source: str = "user"):
    packet = build_overmind_packet(user_text, session, state_engine=state_engine, source=source)
    reply = ""

    # 1. Route to Native C++ model_handler if loaded & active
    if model_handler is not None and getattr(model_handler, "is_active", lambda: False)():
        try:
            if hasattr(model_handler, "send"):
                reply = model_handler.send(packet)
        except Exception as e:
            print("\n[Overmind Native Engine Exception]:")
            traceback.print_exc()
            # Leave reply empty so the documented LM Studio fallback actually runs.
            reply = ""

    # 2. Fall back to LM Studio API
    if not reply:
        try:
            reply = lmstudio_reply(packet["system"], user_text, history=packet["history"])
        except LMStudioOfflineError:
            reply = "(LM Studio is offline and no native GGUF model is loaded, chief.)"
        except Exception as e:
            print("\n[Overmind Fallback Exception]:")
            traceback.print_exc()
            reply = f"(API Error: {e})"

    # 3. Post-generation ETO Hazard and Anti-Stagnation Lifecycle Tick
    if session and getattr(session, "eto_enabled", True):
        try:
            if reply and not reply.startswith("("):
                eto_inst = get_session_eto(session)
                eto_inst.analyze_and_update(user_text, reply)
        except Exception as e:
            print(f"[ETO Turn Lifecycle Error]: {e}")

    if state_engine and reply and not reply.startswith("("):
        try:
            state_engine.evaluate_turn_heuristics(user_text, reply)
        except Exception as e:
            print(f"[State Telemetry Error]: {e}")

    return reply