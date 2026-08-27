# overmind.py — Context Fusion, Session Vault Isolation & ETO Hazard Routing Engine
import json
import os
import re
import traceback
from config import ensure_dirs, get_session_vault_paths
from journal_vault import get_all_journal_entries
from memory_working import retrieve_relevant_working_memories
from memory_context import format_memory_context
from memory_deep import retrieve_relevant_deep_memories
from state_engine import SyntheticStateEngine
from memory_transfer import retrieve_cross_persona_insights
from character import format_ocean_prompt_directive, apply_daily_mood_variance
from ETO import ETOEngine

ensure_dirs()

DUAL_CHANNEL_SYSTEM_DIRECTIVE = (
    "\n[DUNOON HIDDEN TURN META]\n"
    "Start every reply with ONE hidden JSON comment, then write the normal visible response:\n"
    '<!--meta:{"mood":"neutral","intensity":0.0,"pressure":0.0,"progress":1.0,'
    '"fatal":false,"mortality_delta":[],"vault":"working","significance":0.0,'
    '"state_delta":{},"world_delta":[],"authority_claims":[],"handoff":""}-->\n'
    "For mood, prefer one concise label from: neutral, calm, tense, fearful, angry, joyful, sad, affectionate. "
    "Use intensity and pressure as 0.0-1.0 semantic estimates of the current turn. "
    "Keep it small. world_delta records only completed, materially useful changes from THIS actor's turn; "
    "mortality_delta records only explicit completed death/alive changes; handoff is 1-2 factual third-person "
    "sentences about THIS actor's externally observable speech/action. Never put another controlled actor's "
    "fresh voluntary action, thought, speech, decision or reaction into telemetry. If nothing changed, use empty lists. "
    "The meta comment is internal and must never be discussed in visible dialogue."
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
    session_id = getattr(session, "scene_state_id", None) or getattr(session, "id", None) or getattr(session, "session_id", None) or "global"
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

def format_participant_ownership_directive(session, source: str = "user") -> str:
    """Compact universal participant boundary. Models already understand ordinary agency."""
    agent = str(getattr(session, "agent_name", "the assistant") if session else "the assistant").strip() or "the assistant"
    source_key = str(source or "user").strip().lower()

    if source_key == "arena_peer":
        incoming = "The current input describes the other Arena participant or the shared scene. It is context, not your identity."
    elif source_key in {"live_event", "system_event"}:
        incoming = "The current input is authoritative external scene information."
    elif source_key == "internal_control":
        incoming = "The current input is an internal correction instruction, not in-world dialogue."
    else:
        incoming = "The human user's first-person words and actions belong to the human, not to you."

    return (
        "[AGENCY]\n"
        f"You are {agent}. {incoming}\n"
        "Control your own speech, thoughts, decisions, emotions and voluntary actions. "
        "Do not invent another controlled participant's new speech, thoughts, decisions, emotions or voluntary actions. "
        "You may observe established facts and describe direct non-voluntary consequences of your own completed action."
    )


def build_overmind_packet(user_text: str, session, state_engine=None, source: str = "user"):

    if session:
        if apply_daily_mood_variance(session):
            if hasattr(session, "session_manager") and session.session_manager:
                session.session_manager._save()

    source_key = str(source or "user").strip().lower()
    arena_mode = source_key == "arena_peer"
    history = get_session_history(session, limit=4 if arena_mode else 10)
    session_id = getattr(session, "memory_session_id", None) or getattr(session, "id", None) or getattr(session, "session_id", None)
    memory_read_enabled = bool(getattr(session, "memory_read_enabled", True))
    paths = get_session_vault_paths(session_id) if (session_id and memory_read_enabled) else None

    # Generated Solo Events are deliberately scene-local. Historical memory remains
    # available to ordinary Solo turns, but it must not seed a fresh physical event premise.
    event_scene_local = source_key == "system_event"
    try:
        memory_block = format_memory_context(user_text, session, arena=arena_mode) if (memory_read_enabled and not event_scene_local) else ""
    except Exception:
        memory_block = ""

    # Cross-Persona Insight Isolation Check
    cross_insights = []
    is_blind = getattr(session, "blind_to_others", False)
    if memory_read_enabled and not event_scene_local and not is_blind:
        sm = getattr(session, "session_manager", None)
        if sm:
            cross_insights = retrieve_cross_persona_insights(user_text, session, sm, top_k=1 if arena_mode else 2)
    

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

    narrative_directive = format_narrative_authority_directive(session)
    if narrative_directive:
        system_prompt_parts.append(narrative_directive)

    participant_directive = format_participant_ownership_directive(session, source=source)
    if participant_directive:
        system_prompt_parts.append(participant_directive)

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
        phys_txt = getattr(session, "physiology", "") or "Normal (standard organic humanoid)"
        powers_txt = getattr(session, "powers", "") or "None (standard human baseline capabilities)"
        recent_corpus = " ".join([m.get("content", "") for m in history[-4:]]) + f" {user_text}"

        eto_block = eto_inst.format_directive(
            mortality_enabled=mortality_on,
            is_deceased=deceased_on,
            backstory=backstory_txt,
            physiology=phys_txt,
            powers=powers_txt,
            recent_context=recent_corpus,
            narrative_freedom=bool(getattr(session, "narrative_freedom", False)),
        )
        if eto_block:
            system_prompt_parts.append(eto_block)

    # Relevance-first memory context. Historical memory is subordinate to live/current reality.
    if memory_block:
        system_prompt_parts.append(memory_block)
    if cross_insights:
        system_prompt_parts.append(
            "[SHARED INSIGHTS]\nThese are optional historical observations from other personas, not present-world authority. "
            "Use only when directly relevant.\n" + "\n".join(cross_insights)
        )

    # Put mutable current-state truth LAST so stale historical memories or initial
    # measurements cannot accidentally regain precedence by prompt position.
    if state_engine:
        state_directive = state_engine.generate_system_prompt_directive(session=session)
        if state_directive:
            system_prompt_parts.append(state_directive)

    return {
        "system": "\n\n".join(system_prompt_parts),
        "history": history,
        "user": user_text,
    }

def commit_completed_turn(user_text: str, reply: str, session=None, source: str = "user") -> None:
    """Commit ETO and dynamic scene state only after a turn has been accepted as complete."""
    if not reply or str(reply).startswith("("):
        return
    if session and getattr(session, "eto_enabled", True):
        try:
            get_session_eto(session).analyze_and_update(user_text, reply)
        except Exception as e:
            print(f"[ETO Turn Lifecycle Error]: {e}")
    if state_engine:
        try:
            state_engine.evaluate_turn_heuristics(user_text, reply, session=session)
        except Exception as e:
            print(f"[State Telemetry Error]: {e}")


def authority_claim_violations(meta_data: dict, session=None) -> list[str]:
    """Return unsupported consequential external claims when collaborative worldbuilding is disabled.

    The language model performs semantic classification in hidden telemetry; Python only enforces
    the declared authority result. This keeps the validator scenario-agnostic and avoids keyword lists.
    """
    if session is not None and bool(getattr(session, "narrative_freedom", False)):
        return []
    data = meta_data if isinstance(meta_data, dict) else {}
    raw = data.get("authority_claims", [])
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    violations = []
    for item in raw[:16]:
        if isinstance(item, dict):
            claim = str(item.get("claim", "") or "").strip()
            kind = str(item.get("kind", "") or "").strip()
            if claim:
                violations.append(f"{kind + ': ' if kind else ''}{claim}")
        elif isinstance(item, str) and item.strip():
            violations.append(item.strip())
    return violations


def filter_arena_world_delta(meta_data: dict, speaker_aliases, target_aliases) -> tuple[dict, list]:
    """
    Protocol-level trust filter for Arena telemetry.

    This does not interpret narrative verbs or scenario vocabulary. It only enforces
    actor ownership using runtime actor identities plus the explicit `agency` field:
      - speaker-owned state changes are allowed;
      - target-owned state changes are allowed only when marked agency="caused"
        and carry a basis that names the current speaker;
      - other subjects remain available for ordinary object/environment state.
    Unsupported target-owned deltas are dropped rather than allowed to mutate reality.
    """
    data = dict(meta_data or {})
    deltas = data.get("world_delta", [])
    if not isinstance(deltas, list):
        data["world_delta"] = []
        return data, ["world_delta was not a list"]

    def _norm(v):
        return " ".join(str(v or "").strip().lower().split())

    speaker_set = {_norm(x) for x in (speaker_aliases or []) if _norm(x)}
    target_set = {_norm(x) for x in (target_aliases or []) if _norm(x)}

    def _actor_match(subject, aliases):
        if not subject:
            return False
        for alias in aliases:
            if subject == alias:
                return True
            # Runtime names often vary only by descriptive prefixes (e.g.
            # "The Shark" vs "Great White Shark"). Use containment only for
            # non-trivial aliases, without interpreting story vocabulary.
            if len(alias) >= 4 and (subject.endswith(alias) or alias.endswith(subject)):
                return True
        return False

    kept = []
    dropped = []

    for item in deltas:
        if not isinstance(item, dict):
            dropped.append("non-dict world_delta item")
            continue

        subject = _norm(item.get("subject"))
        if not subject:
            dropped.append("world_delta item missing subject")
            continue

        if _actor_match(subject, target_set):
            agency = _norm(item.get("agency"))
            basis = _norm(item.get("basis"))
            basis_names_speaker = any(alias and alias in basis for alias in speaker_set)
            if agency != "caused" or not basis_names_speaker:
                dropped.append(
                    f"target-owned delta rejected for subject={item.get('subject')!r}; "
                    "requires agency='caused' plus a basis naming the current speaker"
                )
                continue

        kept.append(item)

    data["world_delta"] = kept

    mortality = data.get("mortality_delta", [])
    if isinstance(mortality, dict):
        mortality = [mortality]
    if not isinstance(mortality, list):
        mortality = []
        dropped.append("mortality_delta was not a list")

    kept_mortality = []
    for item in mortality[:8]:
        if not isinstance(item, dict):
            dropped.append("non-dict mortality_delta item")
            continue
        subject = _norm(item.get("subject"))
        state = _norm(item.get("state"))
        agency = _norm(item.get("agency"))
        basis = _norm(item.get("basis"))
        if not subject or state not in {"alive", "dead"}:
            dropped.append("mortality_delta item missing subject or valid state")
            continue
        try:
            confidence = float(item.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        if confidence < 0.70:
            dropped.append(f"low-confidence mortality_delta for subject={item.get('subject')!r}")
            continue

        is_speaker = _actor_match(subject, speaker_set)
        is_target = _actor_match(subject, target_set)
        if is_speaker:
            if agency not in {"self", "observed"}:
                dropped.append(f"speaker mortality_delta rejected for subject={item.get('subject')!r}; invalid agency")
                continue
        elif is_target:
            basis_names_speaker = any(alias and alias in basis for alias in speaker_set)
            if agency != "caused" or not basis_names_speaker:
                dropped.append(
                    f"target mortality_delta rejected for subject={item.get('subject')!r}; "
                    "requires agency='caused' plus a basis naming the current speaker"
                )
                continue
        else:
            dropped.append(f"mortality_delta subject is not a controlled Arena actor: {item.get('subject')!r}")
            continue
        kept_mortality.append(dict(item))

    data["mortality_delta"] = kept_mortality
    # A bare fatal boolean is intentionally ignored by Arena callers. It is too ambiguous
    # to identify a victim in multi-agent play and remains only for legacy solo-chat use.
    return data, dropped



SITUATION_GAUGE_DEBUG = False


def _situation_backend_call(system_prompt: str, user_prompt: str, model_handler=None):
    if model_handler is not None and getattr(model_handler, "is_active", lambda: False)():
        return model_handler.send({"system": system_prompt, "history": [], "user": user_prompt})
    raise RuntimeError("No Dunoon Daemon-managed GGUF model is active.")


def _parse_json_object(raw: str):
    text = re.sub(r"```(?:json)?", "", str(raw or ""), flags=re.I).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        pass
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            data, _ = decoder.raw_decode(text[i:])
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return None


def _gauge_level(value):
    v = str(value or "").strip().casefold()
    return v if v in {"green", "amber", "red"} else ""


def _coerce_gauge_pair(data):
    if not isinstance(data, dict):
        return None
    threat = _gauge_level(data.get("threat"))
    opportunity = _gauge_level(data.get("opportunity"))
    if not threat or not opportunity:
        return None
    return {
        "threat": {"level": threat, "basis": "Common-sense assessment of accepted current reality.", "confidence": 1.0},
        "opportunity": {"level": opportunity, "basis": "Common-sense assessment of accepted current reality.", "confidence": 1.0},
    }


def assess_actor_situation(context_text: str, session, actor_name: str = "", model_handler=None, source: str = "user"):
    actor = str(actor_name or getattr(session, "agent_name", "the actor") or "the actor").strip()
    try:
        authoritative = get_session_eto(session)._authoritative_scene_text() if session else ""
    except Exception:
        authoritative = ""
    try:
        current_world = state_engine._format_world_state(session=session) if state_engine else ""
    except Exception:
        current_world = ""

    system_prompt = (
        "Assess immediate practical danger and opportunity for one actor using ordinary common sense. "
        "Do not roleplay. Return JSON only."
    )
    user_prompt = f"""ACTOR: {actor}

ACCEPTED REALITY:
{authoritative or '(none)'}
{current_world or ''}
{str(context_text or '')[:5000]}

THREAT:
green = no immediate credible danger
amber = credible danger, but a comfortable response window remains
red = severe harm could plausibly occur within the next ordinary action/decision window if nothing materially changes

OPPORTUNITY:
green = can safely wait
amber = becoming time-sensitive
red = a useful safety/escape/goal window may be lost by one ordinary turn of delay

Judge danger TO the actor, not danger posed BY the actor.
Return exactly: {{"threat":"green|amber|red","opportunity":"green|amber|red"}}"""

    try:
        raw = _situation_backend_call(system_prompt, user_prompt, model_handler=model_handler)
        clean = _coerce_gauge_pair(_parse_json_object(raw))
    except Exception as e:
        if SITUATION_GAUGE_DEBUG:
            print(f"[Situation Gauge Warning]: {e}")
        return None
    if clean:
        state_engine.update_situation(clean, session=session, source=source)
    return clean


def assess_arena_situation(context_text: str, session_1, actor_1: str, session_2, actor_2: str,
                           model_handler=None, source: str = "arena_preflight"):
    """One small common-sense call for both fixed Arena participants."""
    try:
        authoritative = get_session_eto(session_1)._authoritative_scene_text() if session_1 else ""
    except Exception:
        authoritative = ""
    try:
        current_world = state_engine._format_world_state(session=session_1) if state_engine else ""
    except Exception:
        current_world = ""

    def actor_context(sess, name):
        return (
            f"{name}; physiology={getattr(sess, 'physiology', '') or 'not specified'}; "
            f"capabilities={getattr(sess, 'powers', '') or 'none additionally established'}"
        )

    system_prompt = (
        "Use ordinary common sense to assess immediate practical danger and opportunity for two actors. "
        "Do not roleplay, continue the scene, or referee writing. Return JSON only."
    )
    user_prompt = f"""ARENA_1: {actor_context(session_1, actor_1)}
ARENA_2: {actor_context(session_2, actor_2)}

ACCEPTED CURRENT REALITY:
{authoritative or '(none)'}
{current_world or ''}
{str(context_text or '')[:5000]}

For EACH actor:
THREAT green = no immediate credible danger.
THREAT amber = credible danger, but a comfortable response window remains.
THREAT red = severe harm could plausibly occur within the next ordinary action/decision window if nothing materially changes.
OPPORTUNITY green = can safely wait.
OPPORTUNITY amber = becoming time-sensitive.
OPPORTUNITY red = a useful safety/escape/goal window may be lost by one ordinary turn of delay.

Threat means danger TO that actor, not danger posed BY that actor.
Return exactly:
{{"ARENA_1":{{"threat":"green|amber|red","opportunity":"green|amber|red"}},
"ARENA_2":{{"threat":"green|amber|red","opportunity":"green|amber|red"}}}}"""

    try:
        raw = _situation_backend_call(system_prompt, user_prompt, model_handler=model_handler)
        parsed = _parse_json_object(raw)
        one = _coerce_gauge_pair(parsed.get("ARENA_1")) if isinstance(parsed, dict) else None
        two = _coerce_gauge_pair(parsed.get("ARENA_2")) if isinstance(parsed, dict) else None
    except Exception as e:
        if SITUATION_GAUGE_DEBUG:
            print(f"[Situation Gauge Warning]: {e}")
        return None

    if not one or not two:
        if SITUATION_GAUGE_DEBUG:
            print(f"[Situation Gauge Warning] malformed assessment: {raw!r}")
        return None

    state_engine.update_situation(one, session=session_1, source=source)
    state_engine.update_situation(two, session=session_2, source=source)
    return {"ARENA_1": one, "ARENA_2": two}


ARENA_REFEREE_DEBUG = False


def arena_referee_review(visible_reply: str, session, speaker_name: str, target_name: str,
                         model_handler=None, established_context: str = ""):
    """Tiny authority check: one question, one job."""
    if not visible_reply or not str(visible_reply).strip():
        return {"violation": False, "reason": ""}

    try:
        authoritative = get_session_eto(session)._authoritative_scene_text() if session else ""
    except Exception:
        authoritative = ""
    try:
        current_state = state_engine._format_world_state(session=session) if state_engine else ""
    except Exception:
        current_state = ""

    system_prompt = (
        "You are a boundary checker, not a story referee. Decide only whether ACTOR_A's candidate itself "
        "assigns ACTOR_B a NEW voluntary speech, thought, decision, emotion, reaction, or action. "
        "Observation or repetition of ACTOR_B behaviour already established in the supplied context is allowed. "
        "Direct non-voluntary consequences caused by ACTOR_A's own completed action are allowed. "
        "Return exactly YES or NO."
    )
    user_prompt = f"""ACTOR_A = {speaker_name}
ACTOR_B = {target_name}

ESTABLISHED CONTEXT:
{authoritative or '(none)'}
{current_state or ''}
{str(established_context or '')[:2500]}

CANDIDATE FROM ACTOR_A:
{str(visible_reply)[:5000]}

Did this candidate itself give ACTOR_B a NEW voluntary speech/thought/decision/emotion/reaction/action?
Answer YES or NO only."""

    packet = {"system": system_prompt, "history": [], "user": user_prompt}
    try:
        if model_handler is not None and getattr(model_handler, "is_active", lambda: False)():
            raw = model_handler.send(packet)
        else:
            raise RuntimeError("No Dunoon Daemon-managed GGUF model is active.")
    except Exception as e:
        if ARENA_REFEREE_DEBUG:
            print(f"[Arena Boundary Check Warning]: {e}")
        return None

    token = re.sub(r"[^A-Za-z]", "", str(raw or "").strip()).upper()
    if token.startswith("YES"):
        return {"violation": True, "reason": "assigned the other controlled actor a fresh voluntary state/action"}
    if token.startswith("NO"):
        return {"violation": False, "reason": ""}

    if ARENA_REFEREE_DEBUG:
        print(f"[Arena Boundary Check Warning] non-binary response: {raw!r}")
    return None

def neutral_summarize(text: str, model_handler=None) -> str:
    """Run factual compression through Dunoon's active native GGUF only."""
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
            return "(Native model backend failed during memory consolidation.)"
    return "(Native model backend unavailable for memory consolidation.)"

def overmind(user_text: str, session=None, model_handler=None, source: str = "user", commit_lifecycle: bool = True):
    """Compatibility entry point. Native GGUF only; no silent secondary backend."""
    packet = build_overmind_packet(user_text, session, state_engine=state_engine, source=source)

    if model_handler is None or not getattr(model_handler, "is_active", lambda: False)():
        return "(Native model backend unavailable. Load a GGUF model from Home.)"

    try:
        reply = model_handler.send(packet)
    except Exception as e:
        print("\n[Overmind Native Engine Exception]:")
        traceback.print_exc()
        return f"(Native model backend error: {e})"

    if commit_lifecycle:
        commit_completed_turn(user_text, reply, session=session, source=source)

    return reply
