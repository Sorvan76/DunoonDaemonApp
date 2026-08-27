from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from typing import Dict, List

from .native_backend import NativeModelBackend
from .scene_store import SceneRecord


@dataclass
class AdmissionResult:
    admitted: bool
    reason: str = ""
    raw_response: str = ""
    valid: bool = True
    backend_finish_reason: str = ""


@dataclass
class DirectorResult:
    current_reality: str
    actor_briefs: Dict[str, str]
    actor_status: Dict[str, str]
    active_commitments: Dict[str, str] = field(default_factory=dict)
    turn_accepted: bool = True
    rejection_reason: str = ""
    death_evidence: Dict[str, str] = field(default_factory=dict)
    causal_resolution: str = ""
    raw_response: str = ""
    adjudication_valid: bool = True
    backend_finish_reason: str = ""
    reciprocal_confirmation: str = ""
    world_dynamics: List[str] = field(default_factory=list)
    hard_constraints: List[dict] = field(default_factory=list)
    causal_states: List[dict] = field(default_factory=list)
    active_deadlines: List[dict] = field(default_factory=list)
    state_changes: List[dict] = field(default_factory=list)
    strict_resolution_required: bool = False
    momentum_gate: str = "simmer"
    continuity_recovery: bool = False
    interaction_id: str = ""
    interaction_label: str = ""
    interaction_material_progress: bool = False
    interaction_resolved: bool = False
    interaction_progress_reason: str = ""
    commitment_progress: Dict[str, bool] = field(default_factory=dict)
    scene_frame: dict = field(default_factory=dict)
    scene_transition: dict = field(default_factory=dict)


def _extract_json(raw: str) -> dict | None:
    """Deterministically salvage a Director JSON envelope without changing its semantics."""
    text = re.sub(r"```(?:json)?", "", str(raw or ""), flags=re.I).strip()

    def _try(candidate: str):
        candidate = str(candidate or "").strip()
        if not candidate:
            return None
        try:
            obj = json.loads(candidate)
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass
        # Common local-model serialization blemish: trailing commas before ]/}.
        cleaned = re.sub(r",\s*([}\]])", r"\1", candidate)
        if cleaned != candidate:
            try:
                obj = json.loads(cleaned)
                return obj if isinstance(obj, dict) else None
            except Exception:
                pass
        # Another harmless serialization blemish seen in local structured output is
        # an unquoted identifier used as an object key. Quote keys only in syntactic
        # key position; values and prose are never interpreted or rewritten.
        keyed = re.sub(r'([,{]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)', r'\1"\2"\3', cleaned)
        if keyed != cleaned:
            try:
                obj = json.loads(keyed)
                return obj if isinstance(obj, dict) else None
            except Exception:
                pass
        # Some local models emit a Python-style dict with single quotes. literal_eval
        # parses literals only; it executes no code and does not reinterpret content.
        try:
            obj = ast.literal_eval(keyed)
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None

    direct = _try(text)
    if direct is not None:
        return direct

    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = dec.raw_decode(text[i:])
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
        # Balanced-brace extraction lets the tolerant parser handle fenced/leading/trailing prose.
        depth = 0
        in_string = False
        quote = ""
        escaped = False
        for j in range(i, len(text)):
            c = text[j]
            if in_string:
                if escaped:
                    escaped = False
                elif c == "\\":
                    escaped = True
                elif c == quote:
                    in_string = False
                continue
            if c in {'"', "'"}:
                in_string = True
                quote = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    obj = _try(text[i:j + 1])
                    if obj is not None:
                        return obj
                    break
    return None


def _json_failure_reason(raw: str, finish_reason: str = "") -> str:
    """Classify transport/serialization failure only; never infer narrative meaning."""
    text = str(raw or "").strip()
    finish = str(finish_reason or "").strip().lower()
    if not text:
        return "empty completion"
    if finish in {"length", "max_tokens"}:
        return "completion truncated at token limit"
    if "```" in text:
        return "wrapped/fenced output remained unparsable"
    opens = text.count("{")
    closes = text.count("}")
    if opens > closes:
        return "unterminated JSON object"
    if closes > opens:
        return "extra closing brace"
    if not text.lstrip().startswith("{"):
        return "non-JSON prefix or no object"
    return "JSON syntax/schema envelope unparsable"


def _status_map(raw, names, previous=None):
    previous = previous or {}
    data = raw if isinstance(raw, dict) else {}
    out = {}
    for name in names:
        value = str(data.get(name, previous.get(name, "alive")) or "alive").strip().lower()
        out[name] = "dead" if value == "dead" else "alive"
    return out


def _text_map(raw, names, previous=None):
    previous = previous or {}
    data = raw if isinstance(raw, dict) else {}
    return {name: str(data.get(name, previous.get(name, "")) or "").strip() for name in names}



def _string_list(raw, previous=None, limit=12):
    previous = previous or []
    data = raw if isinstance(raw, list) else previous
    out = []
    for item in data:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out[:limit]



def _dict_list(raw, previous=None, limit=12):
    """Transport-only normaliser for structured semantic ledgers.

    Python does not infer narrative meaning. Stable ids and explicit booleans are
    the contract supplied by the primary Director model.
    """
    previous = previous or []
    data = raw if isinstance(raw, list) else previous
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        clean = dict(item)
        if str(clean.get("id", "") or "").strip():
            clean["id"] = str(clean.get("id") or "").strip()
            out.append(clean)
    return out[:limit]

def _state_change_list(raw, limit=24):
    """Normalise provenance records by explicit state_id only."""
    data = raw if isinstance(raw, list) else []
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("state_id", "") or "").strip()
        if not sid:
            continue
        clean = dict(item)
        clean["state_id"] = sid
        out.append(clean)
    return out[:limit]


def _merge_structured_ledger(previous, proposed, *, active_key="active"):
    """Merge by explicit stable id only; never infer equivalence from English."""
    prior = {str(x.get("id", "") or "").strip(): dict(x) for x in (previous or []) if isinstance(x, dict) and str(x.get("id", "") or "").strip()}
    order = [str(x.get("id", "") or "").strip() for x in (previous or []) if isinstance(x, dict) and str(x.get("id", "") or "").strip()]
    for item in proposed or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("id", "") or "").strip()
        if not key:
            continue
        if key not in prior:
            order.append(key)
        merged = dict(prior.get(key, {}))
        merged.update(dict(item))
        merged["id"] = key
        prior[key] = merged
    # Missing prior ids remain present. They are deactivated only by an explicit
    # structured active/resolved state supplied by the Director.
    return [prior[k] for k in order if k in prior]




def _causal_state_map(items):
    return {str(x.get("id", "") or "").strip(): dict(x) for x in (items or []) if isinstance(x, dict) and str(x.get("id", "") or "").strip()}

def _validate_causal_integrity(scene, hard_constraints, causal_states, state_changes):
    """Validate only explicit structured ids/booleans supplied by the primary model.

    Python never infers English meaning. A guarded outcome cannot become satisfied while
    an explicitly linked prerequisite state remains unsatisfied, and any state flip must
    carry structured provenance from the Director.
    """
    before = _causal_state_map(getattr(scene, "causal_states", []) or [])
    after = _causal_state_map(causal_states or [])
    changes = {}
    for item in state_changes or []:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("state_id", "") or "").strip()
        if sid:
            changes[sid] = dict(item)

    for sid, new in after.items():
        old = before.get(sid)
        new_sat = bool(new.get("satisfied", False))
        old_sat = bool(old.get("satisfied", False)) if old is not None else False
        if old is None or new_sat != old_sat:
            change = changes.get(sid, {})
            if not str(change.get("event_id", "") or "").strip() or not str(change.get("cause", "") or "").strip():
                return False, f"Causal state {sid} changed without structured provenance"
            if bool(change.get("satisfied", new_sat)) != new_sat:
                return False, f"Causal state {sid} provenance disagrees with proposed state"

    for constraint in hard_constraints or []:
        if not isinstance(constraint, dict) or not bool(constraint.get("active", True)):
            continue
        requires = [str(x or "").strip() for x in (constraint.get("requires") or []) if str(x or "").strip()]
        guards = [str(x or "").strip() for x in (constraint.get("guards") or []) if str(x or "").strip()]
        if not requires or not guards:
            continue
        prereqs_ok = all(bool(after.get(sid, before.get(sid, {})).get("satisfied", False)) for sid in requires)
        if prereqs_ok:
            continue
        for gid in guards:
            guarded = after.get(gid, before.get(gid, {}))
            if bool(guarded.get("satisfied", False)):
                return False, f"Guarded causal state {gid} cannot be satisfied before prerequisite state(s): {', '.join(requires)}"
    return True, ""

def _evidence_map(raw, names):
    data = raw if isinstance(raw, dict) else {}
    return {name: str(data.get(name, "") or "").strip() for name in names}


DIRECTOR_AGENT_ROLE = (
    "You are Dunoon's invisible Arena Director, the Shared Reality Director: a neutral, practical scene-running agent whose job is to understand the characters, the environment, ongoing processes and the causal state before judging anything. "
    "Know what each controlled character is physically capable of and what they have actually chosen, but never choose their thoughts, dialogue, motives or voluntary actions for them. "
    "Read the scene literally and causally: distinguish established fact from intention, prediction, threat, metaphor, possibility, fear, guess and dramatic description. "
    "Track what is already moving, reacting, operating, deteriorating, approaching, blocking, helping or otherwise changing. Preserve those trajectories until something actually changes or ends them. "
    "ESTABLISHED WORLD ACTORS ARE LIVE, NOT SCENERY: peripheral NPCs, groups, creatures and systems already established in the scene may and should speak, act or react when their participation would naturally advance the scene. You own those peripheral actors and their ordinary external reactions; you do not own either controlled persona. "
    "THREAD INITIATIVE: when one established scene thread is temporarily blocked, stalled or waiting on a controlled persona, prefer advancing another already-established live thread where appropriate instead of manufacturing pressure inside the blocked thread. When uncertain how to progress, prefer the smallest plausible action by an already-established person, group, process or environmental element before inventing any new event. "
    "ANTI-RUNAWAY: repeated worsening of an already-established condition is not, by itself, meaningful scene progress. Unless ordinary causality specifically requires further deterioration, prefer intervention, response, stabilisation, resolution, or a genuine change in circumstances before escalating the same crisis again. "
    "Your governing question is: DOES THIS PROGRESS THE SCENE WITHOUT BREAKING IT? First ask whether the accepted action or external development advances the scene. Then ask whether accepting that progress would contradict established reality, steal a controlled actor's agency, invent a consequential fact, or settle something genuinely contested. HARD CONSTRAINTS OVERRIDE MOMENTUM: an explicit human-established limit, impossibility, absence, directional rule, capability boundary or stated condition remains binding until a later accepted event causally changes it. Never FREE PASS progress whose success depends on silently violating such a constraint. FREE PASS IS THE DEFAULT only for ordinary scene-progressing continuation that remains inside those boundaries: if it advances the scene and you cannot identify a concrete breakage risk, wave it through and let the obvious consequence land. Do not demand certainty for routine continuation. SIMMER only when there is not yet a meaningful threshold to settle. STRICT is exceptional and requires a specific reason: a real contradiction, authority conflict, contested consequential outcome, genuine causal ambiguity, or a candidate outcome that collides with an explicit hard constraint. "
    "When an uncontested physical trajectory reaches its obvious next threshold, let the consequence land. When facts genuinely conflict or a consequential outcome is ambiguous, adjudicate conservatively from established reality and capabilities. "
    "Compelling means coherent, alive and causally honest, not merely more spectacular. "
    "SCENE ISOLATION: the current ORIGINAL HUMAN BASELINE and SceneRecord are the entire material present-world authority. Do not import props, rooms, smells, hazards, injuries, NPCs, equipment or unfinished activity from any earlier unrelated scene merely because they are statistically familiar or appeared in prior inference traffic. "
    "LIVE USER DIRECTIVES are amendments to the opening human scene directive and outrank Director preference, pacing, foreshadowing and actor invention. Preserve their exact established content; do not weaken, delay, reinterpret or erase them. "
    "Keep the scene moving, protect actor agency, and shoot the best scene of your life. "
)


AUDIENCE_PAYOFF_CONTRACT = (
    "LIVE AUDIENCE CONTRACT: Arena is a live entertainment experience. A real audience is waiting in anticipation of each beat's payoff, and every inference step costs them time. "
    "Quiet beats are allowed; dead air is not. Each beat should normally reward the wait with meaningful action, reaction, discovery, conflict, humour, consequence, relationship change, repositioning, resolution, or a useful scene transition. "
    "Do not spend repeated turns restating sensory information, agreeing that an already-chosen action is sensible, re-announcing urgency, or rehearsing an intention that has already been accepted. Once a controlled actor has perceived the problem, accepted an objective and begun or clearly chosen an immediate action, prefer execution/progress over another explanatory beat. "
    "Compress low-value routine action. Expand consequential action, conflict, discovery, humour and emotional change. Natural immersive prose remains desirable; do not become terse, schematic or stage-direction-like merely to move faster. "
    "If uncertainty about authority makes you cautious, do not substitute repetition for a decision. Actors may commit boldly to their own actions; you may resolve boldly within established constraints. "
    "FORWARD MOTION IS PARAMOUNT: once a beat has established effort, danger, preparation or approach, the next Director pass must seek a changed state rather than another suspended instant. Do not keep a scene parked at the brink of an outcome. When ordinary causality supports a threshold, let it happen. If a threshold cannot safely resolve, change another external fact so the next decision is materially different. "
)

SCENE_LIFECYCLE_CONTRACT = (
    "SCENE LIFECYCLE CONTRACT: Maintain a compact dramatic frame for the current scene: time/space, immediate goal or want, active conflict/blocking force, focal object or interaction, and the meaningful turn/change the scene is moving toward or has just produced. "
    "A scene is not an infinite container. When its immediate dramatic question is genuinely resolved, failed, abandoned or transformed, close it cleanly. Preserve causal continuity, injuries, relationships, equipment, discoveries, unresolved larger threats and other persistent facts, then establish the next scene with a fresh immediate goal/conflict/focal interaction when continued play is appropriate. "
    "Do not stretch a resolved scene with congratulation, sensory recap or aimless wandering merely because turns remain available. Scene transitions may change time or place when causally justified. "
    "SCENE TRANSITION OUTPUT: while the current dramatic question remains live, keep scene_frame.status=active and scene_transition.occurred=false. When it genuinely closes, set scene_frame.status to resolved, failed, abandoned or transformed as appropriate, set scene_transition.occurred=true with a concise reason, and provide new_scene as the next active dramatic frame. current_reality must then describe the authoritative reality at the start of that next scene. Do not transition merely to escape an unresolved causal prerequisite. "
    "Creative freedom is broad around flavour, atmosphere and new scene material, but scene lifecycle never overrides hard constraints, causal prerequisites or persona sovereignty. "
)


class ArenaDirector:
    """Invisible world authority for autonomous Arena play.

    Actors own choices. The Director owns shared facts, provenance and consequences.
    Subjective perception stays actor-relative unless evidence makes it objective reality.
    """

    def __init__(self, backend: NativeModelBackend):
        self.backend = backend
        # 🐉 Silver Wyrm: creative freedom is the default. The UI checkbox is an explicit brake.
        self.block_creative_freedom = False
        self.latency_budget_enabled = False

    def set_block_creative_freedom(self, blocked: bool) -> None:
        self.block_creative_freedom = bool(blocked)

    def _creative_freedom_clause(self) -> str:
        if self.block_creative_freedom:
            return (
                "DIRECTOR CREATIVE FREEDOM IS BLOCKED. Operate as a conservative referee. "
                "Do not introduce new external events, NPCs, hazards, discoveries, objects, scene changes or independent developments unless they are directly required by established shared reality, ordinary causality, an accepted controlled-actor action, or explicit human input. "
                "You still own objective consequences and may complete causally required world changes. Never control a persona's voluntary choice. "
            )
        return (
            "DIRECTOR CREATIVE FREEDOM IS ENABLED. You have broad authorship over shared external reality. "
            "The world is independent of the controlled personas and may continue to act, change, interrupt, reveal, deteriorate, recover, react or introduce plausible external developments while they watch, wait, deliberate or repeat themselves. "
            "You may introduce new external events, peripheral NPC actions, hazards, discoveries, environmental changes and scene developments when they are plausible for the established setting and materially improve forward motion. "
            "Do not wait for a persona to manufacture every development. ANTI-STAGNATION: when repeated controlled-actor turns produce little or no meaningful state change, proactively author the smallest plausible external development that changes the decision landscape. "
            "Creative freedom never overrides explicit human facts or constraints, settled causal reality, established impossibilities, actor capabilities, or persona sovereignty. Never choose a controlled persona's dialogue, thoughts, emotions, tactics, decisions or voluntary actions. Avoid arbitrary deus-ex-machina convenience and preserve causal coherence. "
        )

    @staticmethod
    def _participant_block(participants: Dict[str, str]) -> str:
        return "\n\n".join(f"{name}:\n{desc}" for name, desc in participants.items())

    @staticmethod
    def _scene_schema(names):
        briefs = ",".join(json.dumps(n) + ':"actor-relative current physical facts/perceptions with named referents; never prescribe a choice"' for n in names)
        status = ",".join(json.dumps(n) + ':"alive or dead"' for n in names)
        commitments = ",".join(json.dumps(n) + ':"concrete unfinished physical action already begun, or empty string"' for n in names)
        return ('{"current_reality":"compact objective shared scene",'
                '"actor_briefs":{' + briefs + '},"actor_status":{' + status + '},'
                '"active_commitments":{' + commitments + '},'
                '"world_dynamics":["compact established external process or reactive group whose state can continue changing"],'
                '"hard_constraints":[{"id":"stable opaque id","fact":"explicit binding world rule","active":true,"requires":["causal state id"],"guards":["causal state id"]}],'
                '"causal_states":[{"id":"stable opaque id","fact":"objective condition/outcome tracked for dependency enforcement","satisfied":false}],'
                '"active_deadlines":[{"id":"stable opaque id","state":"current deadline state","terminal_condition":"when this external process reaches its terminal state","terminal_consequence":"established consequence at terminal state","terminal_reached":false,"resolved":false}],"scene_frame":{"id":"stable scene id","status":"active|resolved|failed|abandoned|transformed","time_space":"compact current time/place","goal":"immediate dramatic goal/want","conflict":"active blocking force","focal":"physical object or interaction currently carrying the scene","turn_change":"meaningful shift already achieved or being driven toward"}}')

    @staticmethod
    def _turn_schema(names):
        briefs = ",".join(json.dumps(n) + ':"actor-relative current physical facts/perceptions with named referents; never prescribe a choice"' for n in names)
        status = ",".join(json.dumps(n) + ':"alive or dead"' for n in names)
        commitments = ",".join(json.dumps(n) + ':"concrete unfinished physical action already begun, or empty string"' for n in names)
        evidence = ",".join(json.dumps(n) + ':"explicit accepted causal evidence for death, or empty string"' for n in names)
        return ('{"turn_accepted":true,"rejection_reason":"empty when accepted",'
                '"current_reality":"compact objective shared scene","actor_briefs":{' + briefs + '},'
                '"actor_status":{' + status + '},"active_commitments":{' + commitments + '},'
                '"world_dynamics":["compact established external process or reactive group whose state can continue changing"],'
                '"hard_constraints":[{"id":"stable opaque id","fact":"explicit binding world rule","active":true,"requires":["causal state id"],"guards":["causal state id"]}],'
                '"causal_states":[{"id":"stable opaque id","fact":"objective condition/outcome tracked for dependency enforcement","satisfied":false}],'
                '"active_deadlines":[{"id":"stable opaque id","state":"current deadline state","terminal_condition":"terminal state","terminal_consequence":"established consequence","terminal_reached":false,"resolved":false}],'
                '"state_changes":[{"state_id":"causal state id","satisfied":true,"event_id":"stable opaque accepted-event id","cause":"brief accepted causal event that changed the state"}],'
                '"death_evidence":{' + evidence + '},'
                '"causal_resolution":"explicit outcome/progress threshold crystallised this turn, or empty string",'
                '"reciprocal_confirmation":"observable external fact independently confirmed by both actor POVs this turn, or empty string","scene_frame":{"id":"stable scene id","status":"active|resolved|failed|abandoned|transformed","time_space":"compact current time/place","goal":"immediate dramatic goal/want","conflict":"active blocking force","focal":"physical object or interaction currently carrying the scene","turn_change":"meaningful shift already achieved or being driven toward"},"scene_transition":{"occurred":false,"reason":"why current scene closed or empty","new_scene":{"id":"new stable scene id","status":"active","time_space":"new time/place","goal":"new immediate goal","conflict":"new active conflict","focal":"new focal object/interaction","turn_change":"meaningful shift this new scene is driving toward"}}}')

    def admit_candidate(self, scene: SceneRecord, actor_name: str, visible_turn: str,
                        participants: Dict[str, str]) -> AdmissionResult:
        """Cheap hard-boundary gate. It does not resolve reality or consequences."""
        system = (
            "You are Dunoon's invisible Arena Director HARDLINE admission gate. Do not adjudicate outcomes and do not update shared reality. "
            "Check only for clear hard-boundary violations in the candidate actor prose. "
            "REJECT if the actor treats an unestablished consequential object/tool/weapon/vehicle/exit/person/structure/resource as already present; "
            "creates a new material external property, obstacle, hazard, component, residue, mechanism behaviour or environmental condition that is not established; "
            "turns its own attempt into an objective external result that is not already established (for example deciding that a mechanism moved, locked, broke, sparked, opened, failed or revealed something); "
            "borrows another controlled participant's distinctive anatomy/powers/equipment; assigns another controlled participant a voluntary thought, emotion, decision, dialogue or action; "
            "directly contradicts the authoritative human baseline/current objective reality, actor-relative current state, structured hard constraints, active deadline state, or already-settled shared facts; or emits Dunoon protocol/control text as roleplay. "
            "HUMAN GUIDANCE COMPLIANCE: when PENDING HUMAN GUIDANCE is supplied, it is the newest highest-priority user steering for this actor. If the guidance explicitly directs this controlled actor to take a specific voluntary action now, that voluntary choice is HUMAN-AUTHORED and binding for this turn: REJECT refusal, debate, substitution of a different tactic, atmospheric delay, or mere acknowledgement without making the instructed attempt. The persona still owns voice, emotion and manner of execution; consequential external success/failure remains Director-owned. If authoritative physical reality makes literal execution impossible, the actor must visibly attempt as far as possible or identify/react to the concrete blocking fact rather than silently ignore or simply refuse the user. For guidance that does not command this actor, require only a relevant response where it actually applies. Do not require the actor to invent an external outcome to comply. "
            "ALLOW ordinary voluntary movement, speech, thought, perception, searching, inspection, attempts, guesses, physical effort and cautious inference. Allow direct bodily sensations or plainly established ambient effects, but not newly invented material causes. "
            "The actor may state what it tries to do. The Director, not the actor, determines consequential external success/failure and new shared-world state. "
            "Return exactly one line: ALLOW, or REJECT: followed by a short reason. No JSON, markdown or commentary."
        )
        user = f"""ORIGINAL HUMAN BASELINE:
{scene.initial_prompt}

CURRENT OBJECTIVE SHARED REALITY:
{scene.current_reality}

LATEST AUTHORITATIVE STATE FOR {actor_name}:
{json.dumps({"status": (scene.actor_status or {}).get(actor_name, "alive"), "actor_view": (scene.actor_briefs or {}).get(actor_name, ""), "unfinished_commitment": (scene.active_commitments or {}).get(actor_name, ""), "world_dynamics": list(scene.world_dynamics or []), "hard_constraints": [x for x in (getattr(scene, "hard_constraints", []) or []) if isinstance(x, dict) and bool(x.get("active", True))], "causal_states": list(getattr(scene, "causal_states", []) or []), "active_deadlines": [x for x in (getattr(scene, "active_deadlines", []) or []) if isinstance(x, dict) and not bool(x.get("resolved", False))]}, ensure_ascii=False)}

SETTLED SHARED FACTS:
{json.dumps([str(x.get("text", "") or "").strip() for x in scene.log if x.get("kind") in {"causal_resolution", "reciprocal_confirmation"} and str(x.get("text", "") or "").strip()][-12:], ensure_ascii=False)}

ALL ACTIVE LIVE USER DIRECTIVES — HIGHEST-AUTHORITY SCENE/CHARACTER EDITS:
{json.dumps([x for x in (getattr(scene, "live_directives", []) or []) if isinstance(x, dict) and bool(x.get("active", True))], ensure_ascii=False)}

PENDING HUMAN GUIDANCE FOR {actor_name} — NEWEST USER STEERING NOT YET ACKNOWLEDGED:
{json.dumps([x for x in (getattr(scene, "live_directives", []) or []) if isinstance(x, dict) and bool(x.get("active", True)) and str(x.get("kind", "") or "").lower() == "guidance" and actor_name not in {str(v or "").strip() for v in (x.get("acknowledged_by", []) or [])}][-1:], ensure_ascii=False)}

CANDIDATE POV BY {actor_name}:
{visible_turn}

PARTICIPANTS AND ESTABLISHED CAPABILITIES:
{self._participant_block(participants)}"""
        # 🐉 Silver Wyrm: this gate is now on the live Arena path, so keep it tiny and stop
        # hidden reasoning from consuming the bouncer's entire visible allowance.
        packet = {"system": system, "history": [], "user": user, "temperature": 0.05,
                  "repeat_penalty": 1.0, "presence_penalty": 0.0,
                  "max_tokens": 96, "disable_reasoning": True}
        raw = self.backend.generate(packet)
        finish = str(self.backend.finish_reason or "")
        text = str(raw or "").strip()
        # Intentionally tolerant: this is a bouncer, not a schema tribunal. Accept a clear
        # 🐉 Silver Wyrm: ALLOW/REJECT token even if the model adds harmless surrounding words. adds
        # one bounded retry for genuinely unusable output; fail-open behavior remains owned
        # by ArenaEngine, not by this gate.
        m = re.search(r"(?is)\b(ALLOW|REJECT)\b(?:\s*:\s*([^\r\n]+))?", text)
        legacy = _extract_json(text) if not m else None
        if legacy is not None:
            admitted = bool(legacy.get("turn_accepted", True))
            return AdmissionResult(admitted, str(legacy.get("rejection_reason", "") or "").strip(), str(raw or ""), True, finish)
        if not m:
            retry = dict(packet)
            retry["system"] = system + " OUTPUT RECOVERY: answer with exactly ALLOW or REJECT: <short reason>. Nothing else."
            retry["temperature"] = 0.0
            raw2 = self.backend.generate(retry)
            finish2 = str(self.backend.finish_reason or "")
            text2 = str(raw2 or "").strip()
            m = re.search(r"(?is)\b(ALLOW|REJECT)\b(?:\s*:\s*([^\r\n]+))?", text2)
            legacy = _extract_json(text2) if not m else None
            if legacy is not None:
                admitted = bool(legacy.get("turn_accepted", True))
                return AdmissionResult(admitted, str(legacy.get("rejection_reason", "") or "").strip(),
                                       f"[initial]\n{raw}\n\n[retry]\n{raw2}", True, finish2 or finish)
            if not m:
                return AdmissionResult(False, "Director admission gate output was unusable",
                                       raw_response=f"[initial]\n{raw}\n\n[retry]\n{raw2}", valid=False,
                                       backend_finish_reason=finish2 or finish)
            raw, finish = raw2, finish2 or finish
        admitted = m.group(1).upper() == "ALLOW"
        reason = str(m.group(2) or "").strip()
        return AdmissionResult(admitted, reason, str(raw or ""), True, finish)

    def simmer_exchange(self, scene: SceneRecord, povs: Dict[str, str], participants: Dict[str, str]) -> DirectorResult:
        """Low-intervention continuity pass. Escalates only when shared causality genuinely needs adjudication."""
        names = list(scene.participants)
        system = (
            DIRECTOR_AGENT_ROLE + self._creative_freedom_clause() + AUDIENCE_PAYOFF_CONTRACT + SCENE_LIFECYCLE_CONTRACT +
            "WORLD RESOLVER — SIMMER MODE. Both actor POVs are admitted evidence, but the controlled actors are generally trusted to own their own choices. "
            "Do not litigate every exchange and do not choose, rewrite or optimise either actor's voluntary action. Agreement is sufficient evidence for an obvious observable external fact when it does not contradict authoritative reality. Resolving the physical consequence of an action an actor already chose is not puppeteering. "
            "Before deciding whether anything needs adjudication, understand the scene: what is established, what is changing, what each actor actually did, what remains only intended/hypothetical/descriptive, and what physical trajectories are in progress. "
            "EXPERIMENT RESOLUTION LOCK: when an admitted actor performs a concrete attempt whose purpose or consequence depends on how unresolved external reality responds, this pair contains a consequential threshold and may not remain SIMMER merely because the second actor avoided inventing the answer. Resolve the smallest authoritative external result now. Examples include testing whether an unknown surface supports weight, probing an unexplained substance, trying an uncertain mechanism, forcing an unresolved barrier, checking whether an attack affects a supernatural entity, or otherwise asking the world a physical question through action. The actor owns the attempt; you own what the world does in response. Do not let one actor's speculative description of that response become true merely because the other actor repeats or agrees with it. If ordinary established causality makes the answer obvious, FREE PASS the smallest concrete result. If the answer is genuinely constrained, contradictory, or causally ambiguous, use STRICT. Do not invent a larger reward, route, power, destination or mechanism than the attempt itself supports. "
            "Quietly preserve continuity from the accepted scene and the two admitted POVs. Crystallise only obvious objective facts both POVs support, "
            "maintain compact actor-relative briefs and unfinished physical commitments, and keep already-established WORLD DYNAMICS alive when ordinary causality supports their continuation. "
            "Do not invent new people, objects, resources, motives, abilities or unrelated events. POV agreement about guesses, metaphors, hidden thoughts or unsupported inventions is not reality. NOVELTY LOCK: a fact already present in current objective reality or settled causal facts is not a new causal resolution; preserve continuity without re-resolving it. NON-REGRESSION LOCK: settled causal facts remain true unless a later accepted event explicitly reverses them. "
            "Apply the SCENE MOMENTUM GATE in this exact order: (1) Does the accepted action/development progress the scene? (2) Would accepting that progress break established reality, actor authority, or any explicit human-established constraint? A hard constraint is a concrete boundary in the baseline/current reality, not a mere uncertainty. (3) If it progresses and there is no concrete breakage reason, momentum_gate=\"free_pass\": crystallise the obvious next objective threshold now, advance/clear the relevant commitment when appropriate, and keep actors moving. FREE PASS is presumptive for routine continuation; uncertainty by itself is not a reason to block it, but an explicit hard constraint is. (4) If no consequential threshold needs deciding yet, momentum_gate=\"simmer\": preserve continuity without forcing one. (5) Use momentum_gate=\"strict\" and strict_resolution_required=true when you can identify a real contradiction, actor-authority conflict, contested consequential outcome, genuine causal ambiguity, or collision with an explicit hard constraint that would make a free pass unsafe. "
            "A due contact/completion threshold is NOT automatically strict. If it is an obvious, uncontested continuation that progresses the scene without breaking it, FREE PASS it. Prefer discrete thresholds such as reached landing, crossed doorway, completed descent, contact made, or separation achieved rather than stronger adjectives about ongoing effort. ENDPOINT AUTHORITY: you own ordinary external consequences. Once an actor has already reached, touched, pushed, opened, crossed, climbed, descended, or otherwise physically worked through enough unopposed increments that the mundane endpoint follows from established reality, finish that endpoint now. Do not spend additional turns on microscopic fractions of the same simple action. MUTABLE-BY-DEFAULT WORLD RULE: established shared reality is interactive, not frozen merely because a detail was previously stated. Ordinary objects, openings, mechanisms, loose materials and reversible environmental states may be manipulated by ordinary causal action unless the human baseline or current shared reality has positively established a relevant constraint such as locked, jammed, barred, blocked, fixed, fused, welded, anchored, immovable, sealed, magically bound, immutable, irreversible, permanent, frozen-in-state, indestructible, or equivalent resistance. Absence of an explicit permission is NOT a constraint. Do not invent resistance merely to preserve the prior frame. A reached door being pushed without an established lock/blockage should open; an ordinary chest can open, a loose chair can move, a lever can be pulled, and a handle can turn when no contrary fact exists. An actor already squeezing through an open gap should cross it. Either complete the ordinary endpoint or state the concrete ESTABLISHED obstruction. "
            "SOFT COMMITMENT RECOGNITION: judge intent semantically, not by swagger. Persona-shaped phrases such as 'I think I should try to move toward...', 'perhaps I ought to go...', or 'I suppose I will...' can express a real immediate voluntary choice. When the candidate clearly selects an action for execution now and begins or physically enacts its first increment, record/continue the corresponding active commitment exactly as you would for blunt wording. Mere speculation, conditional planning, wishes, questions, or discussion of what one might do are not commitments. "
            "COMMITMENT SUBJECT LOCK: when a commitment is due, causal_resolution must materially advance, complete, fail, or concretely interrupt THAT due actor's listed action. A nearby gesture, emotion, posture, atmospheric detail, unrelated world change, or repetition of preparation does not satisfy a due commitment. Do not clear a due commitment unless the returned objective consequence actually ends or replaces it. "
            "CAUSAL INTEGRITY CONTRACT: causal_states are authoritative for explicitly tracked dependency conditions/outcomes. If this pass changes any tracked state, update causal_states and emit a matching state_changes entry with state_id, satisfied, a stable opaque event_id and a concise cause grounded in accepted actor action or Director-owned external causality. Never mark a guarded outcome satisfied while any state id in that constraint requires list remains unsatisfied. Do not claim a tracked outcome as completed in current_reality or causal_resolution while its causal state remains unsatisfied. "
            "MORTALITY CLOSURE CONTRACT: mortality is an objective physiological consequence, never a voluntary choice. A controlled actor does NOT have to surrender, accept death, stop struggling, or narrate its own demise. Repeated determination, pain tolerance, a declared 'one last effort', or continued attempted movement cannot reset already-established injury, oxygen deprivation, blood loss, catastrophic trauma, or an ongoing lethal mechanism. Respect each participant's established physiology, supernatural nature and capabilities. When established shared reality now makes continued life physiologically impossible or when a lethal process has reached a terminal point with no plausible causal path to survival, resolve that boundary NOW: set actor_status for that actor to dead, provide concise explicit death_evidence grounded only in established/accepted evidence, clear or end the actor's physical commitment as appropriate, and use momentum_gate=\"free_pass\" when the terminal consequence is obvious (\"strict\" only for genuine causal ambiguity). Do not wait for the actor to give up. If survival remains physically plausible, keep the actor alive and leave death_evidence empty. Danger, severe pain, injury, unconsciousness risk, or uncertainty alone are not death. "
            "Set strict_resolution_required=true only for momentum_gate=\"strict\". FREE PASS is permission to accept low-risk causal progress, not permission to invent a new destination, obstacle, success condition, person, resource, capability or voluntary choice, and never permission to override an explicit baseline constraint. "
            "Return one compact JSON object only."
        )
        settled = [str(x.get("text", "") or "").strip() for x in scene.log
                   if x.get("kind") in {"causal_resolution", "reciprocal_confirmation"} and str(x.get("text", "") or "").strip()]
        settled_block = "\n".join(f"- {x}" for x in settled[-12:]) or "(none yet)"
        pov_block = "\n\n".join(f"POV BY {n}:\n{str(povs.get(n, '') or '').strip()}" for n in names)
        if bool(getattr(self, "latency_budget_enabled", False)):
            # 🐉 Silver Wyrm: the live Arena asks the primary model for the smallest semantic
            # envelope needed to move the show. Omitted ledgers retain their existing
            # structured values in the parser below. Smaller JSON is materially more
            # reliable on local models and avoids spending retries on paperwork.
            response_shape = {
                "current_reality": "same reality or compact objectively supported continuity update",
                "actor_status": {n: "alive or dead" for n in names},
                "active_commitments": {n: "unfinished physical action already begun, or empty string" for n in names},
                "world_dynamics": ["established ongoing external process/reaction"],
                "death_evidence": {n: "explicit accepted causal evidence for death, or empty string" for n in names},
                "reciprocal_confirmation": "obvious shared external fact or empty string",
                "causal_resolution": "obvious free-pass threshold or other supported threshold, or empty string",
                "momentum_gate": "free_pass|simmer|strict",
                "strict_resolution_required": False,
                "interaction": {"id": "stable opaque id", "label": "short unresolved objective or empty", "material_progress": False, "resolved": False, "reason": "brief semantic reason"},
                "commitment_progress": {n: False for n in names},
                "scene_frame": {"id": "scene id", "status": "active|resolved|failed|abandoned|transformed", "goal": "short goal", "conflict": "short conflict", "focal_point": "short focus"},
                "scene_transition": {"occurred": False, "reason": "", "new_scene": {}},
            }
        else:
            response_shape = {
                "current_reality": "same reality or compact objectively supported continuity update",
                "actor_briefs": {n: "compact actor-relative physical facts" for n in names},
                "actor_status": {n: "alive or dead" for n in names},
                "active_commitments": {n: "unfinished physical action already begun, or empty string" for n in names},
                "world_dynamics": ["established ongoing external process/reaction"],
                "death_evidence": {n: "explicit accepted causal evidence for death, or empty string" for n in names},
                "hard_constraints": [{"id":"stable opaque id","fact":"binding world rule","active":True,"requires":["causal state id"],"guards":["causal state id"]}],
                "causal_states": [{"id":"stable opaque id","fact":"objective prerequisite/outcome condition","satisfied":False}],
                "active_deadlines": [{"id":"stable opaque id","state":"current state","terminal_condition":"terminal state","terminal_consequence":"established consequence","terminal_reached":False,"resolved":False}],
                "state_changes": [{"state_id":"causal state id","satisfied":True,"event_id":"stable opaque accepted-event id","cause":"brief accepted causal event"}],
                "reciprocal_confirmation": "obvious shared external fact or empty string",
                "causal_resolution": "obvious free-pass threshold or other supported threshold, or empty string",
                "momentum_gate": "free_pass|simmer|strict",
                "strict_resolution_required": False,
                "interaction": {"id": "stable opaque id", "label": "short unresolved objective or empty", "material_progress": False, "resolved": False, "reason": "brief semantic reason"},
                "commitment_progress": {n: False for n in names},
                "scene_frame": dict(getattr(scene, "scene_frame", {}) or {}),
                "scene_transition": {"occurred": False, "reason": "", "new_scene": {}},
            }
        user = f"""CURRENT OBJECTIVE SHARED REALITY:
{scene.current_reality}

LIVE USER DIRECTIVES — AUTHORITATIVE AMENDMENTS TO THE OPENING SCENE:
{json.dumps(getattr(scene, "live_directives", []), ensure_ascii=False)}

SETTLED CAUSAL FACTS — ALREADY HAPPENED; DO NOT RE-RESOLVE OR REGRESS:
{settled_block}

CURRENT ACTOR-RELATIVE BRIEFS:
{json.dumps(scene.actor_briefs, ensure_ascii=False)}

CURRENT ACTIVE PHYSICAL COMMITMENTS:
{json.dumps(scene.active_commitments, ensure_ascii=False)}

WORLD DYNAMICS:
{json.dumps(scene.world_dynamics, ensure_ascii=False)}

HARD CONSTRAINTS — BINDING STRUCTURED DEPENDENCIES:
{json.dumps(getattr(scene, "hard_constraints", []), ensure_ascii=False)}

CAUSAL STATES — CURRENT AUTHORITATIVE PREREQUISITE/OUTCOME STATE:
{json.dumps(getattr(scene, "causal_states", []), ensure_ascii=False)}

ACTIVE DEADLINES:
{json.dumps(getattr(scene, "active_deadlines", []), ensure_ascii=False)}

CURRENT SCENE FRAME — DRAMATIC UNIT, NOT A HARD FACT LEDGER:
{json.dumps(getattr(scene, "scene_frame", {}), ensure_ascii=False)}

PROVISIONAL POV AUTHORITY VERIFICATION:
{json.dumps(getattr(scene, "provisional_authority_verified", {}), ensure_ascii=False)}
An actor POV marked false may evidence only that actor's own voluntary action, speech, subjective perception or attempt. It MUST NOT be used as evidence that an external object/property/outcome/state exists.

CURRENT PERSISTENT INTERACTION STATE:
{json.dumps({"id": getattr(scene, "interaction_thread_id", "") or getattr(scene, "interaction_thread_key", ""), "label": getattr(scene, "interaction_thread_label", ""), "age": int(getattr(scene, "interaction_thread_age", 0) or 0)}, ensure_ascii=False)}

ADMITTED POV EVIDENCE:
{pov_block}

Return exactly this shape:
{json.dumps(response_shape, ensure_ascii=False)}"""
        packet = {"system": system, "history": [], "user": user, "temperature": 0.05, "repeat_penalty": 1.0, "presence_penalty": 0.0, "max_tokens": 3072, "response_format": {"type": "json_object"}, "disable_reasoning": True}
        raw = self.backend.generate(packet)
        finish = str(self.backend.finish_reason or "")
        data = _extract_json(raw)
        recovery_trace = str(raw or "")
        if not data and bool(getattr(self, "latency_budget_enabled", False)):
            # 🐉 Silver Wyrm: deterministic JSON salvage has already run. Do not spend more
            # primary-model calls repairing paperwork inside the same visible beat.
            return DirectorResult(scene.current_reality, dict(scene.actor_briefs), dict(scene.actor_status),
                                  dict(scene.active_commitments), turn_accepted=True,
                                  rejection_reason="Director simmer output was not valid JSON: " + _json_failure_reason(raw, finish) + " (latency budget: no same-cycle retry)",
                                  death_evidence={n: "" for n in names}, raw_response=recovery_trace,
                                  adjudication_valid=False, backend_finish_reason=finish,
                                  world_dynamics=list(scene.world_dynamics or []))
        if not data:
            # 🐉 Silver Wyrm: malformed simmer JSON must not immediately strand admitted POVs in
            # provisional limbo. First ask for a syntax-only repair of the exact output,
            # then make one clean low-temperature retry of the original resolver request.
            # All retries are bounded; if both fail, the pre-existing safe defer path remains.
            repair_shape = {
                "current_reality": "string",
                "actor_briefs": {n: "string" for n in names},
                "actor_status": {n: "alive or dead" for n in names},
                "active_commitments": {n: "string" for n in names},
                "world_dynamics": ["string"],
                "death_evidence": {n: "string" for n in names},
                "hard_constraints": [{"id":"string","fact":"string","active":True,"requires":[],"guards":[]}],
                "causal_states": [{"id":"string","fact":"string","satisfied":False}],
                "active_deadlines": [{"id":"string","state":"string","terminal_condition":"string","terminal_consequence":"string","terminal_reached":False,"resolved":False}],
                "state_changes": [{"state_id":"string","satisfied":True,"event_id":"string","cause":"string"}],
                "reciprocal_confirmation": "string",
                "causal_resolution": "string",
                "momentum_gate": "free_pass|simmer|strict",
                "strict_resolution_required": False,
                "interaction": {"id": "string", "label": "string", "material_progress": False, "resolved": False, "reason": "string"},
                "commitment_progress": {n: False for n in names},
            }
            repair_packet = {
                "system": (
                    "You are a strict JSON syntax repair utility. Convert the supplied malformed Director output "
                    "into exactly one valid compact JSON object. Preserve its intended factual content; do not "
                    "invent, adjudicate, strengthen, weaken, or add scene events. Return JSON only."
                ),
                "history": [],
                "user": "REQUIRED SHAPE:\n" + json.dumps(repair_shape, ensure_ascii=False) +
                        "\n\nMALFORMED OUTPUT TO REPAIR:\n" + str(raw or ""),
                "temperature": 0.0, "repeat_penalty": 1.0, "presence_penalty": 0.0,
            }
            repaired_raw = self.backend.generate(repair_packet)
            repair_finish = str(self.backend.finish_reason or "")
            data = _extract_json(repaired_raw)
            recovery_trace = f"[initial]\n{raw}\n\n[syntax-repair]\n{repaired_raw}"
            if data:
                raw, finish = repaired_raw, repair_finish or finish
            else:
                retry = dict(packet)
                retry["system"] = system + " OUTPUT RECOVERY: return exactly one compact valid JSON object matching the requested shape. No prose, markdown, preface or suffix."
                retry["temperature"] = 0.0
                retry_raw = self.backend.generate(retry)
                retry_finish = str(self.backend.finish_reason or "")
                data = _extract_json(retry_raw)
                recovery_trace += f"\n\n[clean-retry]\n{retry_raw}"
                if data:
                    raw, finish = retry_raw, retry_finish or repair_finish or finish
                else:
                    return DirectorResult(scene.current_reality, dict(scene.actor_briefs), dict(scene.actor_status),
                                          dict(scene.active_commitments), turn_accepted=True,
                                          rejection_reason="Director simmer output was not valid JSON after bounded recovery",
                                          death_evidence={n: "" for n in names}, raw_response=recovery_trace,
                                          adjudication_valid=False, backend_finish_reason=retry_finish or repair_finish or finish,
                                          world_dynamics=list(scene.world_dynamics or []))
        reality = str(data.get("current_reality", "") or "").strip() or scene.current_reality
        briefs = _text_map(data.get("actor_briefs"), names, scene.actor_briefs)
        status = _status_map(data.get("actor_status"), names, scene.actor_status)
        commitments = _text_map(data.get("active_commitments"), names, scene.active_commitments)
        dynamics = _string_list(data.get("world_dynamics"), scene.world_dynamics)
        evidence = _evidence_map(data.get("death_evidence"), names)
        hard_constraints = _merge_structured_ledger(getattr(scene, "hard_constraints", []), _dict_list(data.get("hard_constraints"), []))
        causal_states = _merge_structured_ledger(getattr(scene, "causal_states", []), _dict_list(data.get("causal_states"), []), active_key="satisfied")
        active_deadlines = _merge_structured_ledger(getattr(scene, "active_deadlines", []), _dict_list(data.get("active_deadlines"), []), active_key="resolved")
        state_changes = _state_change_list(data.get("state_changes"), limit=24)
        integrity_ok, integrity_reason = _validate_causal_integrity(scene, hard_constraints, causal_states, state_changes)
        return DirectorResult(
            reality, briefs, status, commitments, True, ("" if integrity_ok else integrity_reason), evidence,
            str(data.get("causal_resolution", "") or "").strip(), str(raw or ""),
            reciprocal_confirmation=str(data.get("reciprocal_confirmation", "") or "").strip(),
            world_dynamics=dynamics, hard_constraints=hard_constraints, causal_states=causal_states, active_deadlines=active_deadlines, state_changes=state_changes,
            adjudication_valid=integrity_ok, backend_finish_reason=finish,
            strict_resolution_required=(str(data.get("momentum_gate", "") or "").strip().lower() == "strict") or bool(data.get("strict_resolution_required", False)),
            momentum_gate=(str(data.get("momentum_gate", "simmer") or "simmer").strip().lower() if str(data.get("momentum_gate", "simmer") or "simmer").strip().lower() in {"free_pass", "simmer", "strict"} else "simmer"),
            interaction_id=str((data.get("interaction") or {}).get("id", "") or "").strip(),
            interaction_label=str((data.get("interaction") or {}).get("label", "") or "").strip(),
            interaction_material_progress=bool((data.get("interaction") or {}).get("material_progress", False)),
            interaction_resolved=bool((data.get("interaction") or {}).get("resolved", False)),
            interaction_progress_reason=str((data.get("interaction") or {}).get("reason", "") or "").strip(),
            commitment_progress={n: bool((data.get("commitment_progress") or {}).get(n, False)) for n in names},
            scene_frame=(dict(data.get("scene_frame") or {}) if isinstance(data.get("scene_frame"), dict) else dict(getattr(scene, "scene_frame", {}) or {})),
            scene_transition=(dict(data.get("scene_transition") or {}) if isinstance(data.get("scene_transition"), dict) else {}),
        )

    def resolve_exchange(self, scene: SceneRecord, povs: Dict[str, str], participants: Dict[str, str],
                         *, force_resolution: bool = False, strict_due: bool = False,
                         allow_json_repair: bool = True, initiative: bool = False) -> DirectorResult:
        """Resolve shared reality only after both controlled actors have admissible POV evidence."""
        names = list(scene.participants)
        system = (
            DIRECTOR_AGENT_ROLE + self._creative_freedom_clause() + AUDIENCE_PAYOFF_CONTRACT + SCENE_LIFECYCLE_CONTRACT +
            "WORLD RESOLVER — STRICT MODE. Both actor POVs below have already passed a hard admission gate. "
            "Do not reject or rewrite either actor and do not choose a new voluntary action for either persona. "
            "Your job begins only now. First form a scene understanding: established facts; active external dynamics; each actor's actual chosen action; active physical trajectories; and language that is merely intent, prediction, threat, metaphor, possibility or guess. Then compare the two POVs against the human baseline and current objective reality. "
            "If both POVs independently align on the same observable external fact, location, contact, completed threshold or interaction, crystallise that shared fact into current_reality. "
            "Agreement is sufficient evidence unless it contradicts established authoritative reality. Shared guesses, metaphors, uncertain interpretations or mutually repeated unsupported inventions do not create facts. "
            "If the POVs materially conflict about a consequential outcome, adjudicate only that conflict from established reality and direct physical causality. Explicit human-established constraints in the ORIGINAL HUMAN BASELINE or CURRENT OBJECTIVE SHARED REALITY are binding evidence: do not resolve an outcome by silently crossing or reversing one unless a later accepted event actually changed it. "
            "If there is no consequential alignment or conflict, normally leave current_reality unchanged. EXCEPTION: an already-established WORLD DYNAMIC may continue or react when ordinary causality directly supports it. Reactive external people/groups/creatures may plausibly respond to an accepted actor action or changing danger; ongoing physical processes may continue their established trajectory unless something stops or changes them. Do not invent new resources, motives, abilities or unrelated events. "
            "NOVELTY LOCK: a fact already present in CURRENT OBJECTIVE SHARED REALITY or SETTLED CAUSAL FACTS is not a new causal resolution. Reconfirmation may support continuity but must not consume causal_resolution. Prefer the strongest NEW jointly supported external threshold. "
            "NON-REGRESSION LOCK: settled causal facts remain true unless a later accepted event explicitly reverses them. Never move an actor silently back behind an established location/contact/completion threshold. If a POV regresses behind settled reality without an explicit causal reversal, treat that part of the POV as mistaken and preserve the settled state. "
            "Actors own intentions and voluntary actions; you own objective consequences. Resolving the physical consequence of an action an actor already chose is not puppeteering. ENDPOINT AUTHORITY: when an already-chosen mundane physical action has advanced through enough unopposed increments that its ordinary endpoint is causally due, author that endpoint now instead of another micro-step. MUTABLE-BY-DEFAULT WORLD RULE: prior description does not freeze ordinary shared reality. Ordinary objects, openings, mechanisms, loose materials and reversible environmental states are manipulable by ordinary causal action unless the authoritative scene has positively established relevant resistance such as locked, jammed, barred, blocked, fixed, fused, welded, anchored, immovable, sealed, magically bound, immutable, irreversible, permanent, frozen-in-state, indestructible, or equivalent. Do not require an explicit statement that an ordinary thing is manipulable, and do not invent resistance to keep the old state unchanged. If an actor has reached and is pushing an ordinary door and no lock/blockage is established, the door opens; the same principle applies to ordinary chests, lids, handles, levers, loose furniture, movable objects and other mundane reversible state changes. If the actor is already passing through a gap, complete the crossing. Otherwise name the concrete ESTABLISHED obstruction. "
            "Maintain actor-relative briefs, active physical commitments, mortality evidence and status. Also maintain WORLD DYNAMICS as compact continuity obligations for established external processes/reactive entities that can keep changing the scene. If a tracked dynamic materially changes, reflect that change in current_reality as objective shared reality. Drop a dynamic only when it is completed, stopped, destroyed, dispersed, or otherwise no longer active. "
            "CAUSAL INTEGRITY CONTRACT: causal_states are authoritative for explicitly tracked dependency conditions/outcomes. Any tracked state change MUST be reflected in causal_states and accompanied by one matching state_changes entry carrying state_id, satisfied, a stable opaque event_id and concise accepted cause. Never satisfy a guarded state before all explicit requires state ids are satisfied, and never narrate a tracked guarded outcome as completed while its state remains unsatisfied. "
            "MORTALITY CLOSURE CONTRACT: a death requires explicit lethal causal evidence and mortality remains subject to engine enforcement. Death is an objective physiological consequence, not a voluntary choice: the actor does not need to surrender, accept death, stop struggling, or narrate its own demise. Repeated willpower, pain tolerance, or another 'last effort' cannot erase cumulative established trauma, oxygen deprivation, blood loss, organ failure, or an ongoing lethal mechanism. Respect established physiology and supernatural capabilities. If established reality has crossed an unsurvivable terminal threshold with no plausible causal survival path, resolve it now, set actor_status=dead and provide concise death_evidence. Do not postpone terminal physiology merely because the actor continues trying to act. If the state is severe but survivable or genuinely ambiguous, keep the actor alive until causality settles it. "
            "SEMANTIC STATE CONTRACT: identify the primary unresolved interaction by meaning, not wording. Reuse the exact existing interaction id when the same objective continues through paraphrase or different micro-actions. Mark material_progress only for a decision-relevant state change; mark resolved only when settled/abandoned/impossible/transformed. Report commitment_progress per actor from semantic causal state, not verb matching. "
            "HARD REALITY CONTRACT: HARD CONSTRAINTS below are binding until their structured entry is explicitly deactivated by a later accepted causal change or authoritative human Event. Never replace a required method/dependency with a convenient shortcut merely because the shortcut would create momentum. Preserve stable constraint ids. "
            "DEADLINE CONTRACT: ACTIVE DEADLINES are live external processes. On every world-resolution pass, advance or update each deadline by a believable amount relative to the amount of scene action that has occurred; exact real-time simulation is unnecessary, but a deadline may not remain decorative while substantial action accumulates. Preserve stable deadline ids. If terminal_reached becomes true, resolve the established terminal consequence on THIS world-resolution pass and set resolved=true. Zero/terminal is an outcome boundary, not flavour text. "
            "Prefer discrete state changes over descriptive restatement. Return compact JSON only."
        )
        if initiative:
            system += (
                " WORLD INITIATIVE OVERRIDE IS ACTIVE because repeated continuity-only exchanges or a persistent unresolved interaction have stalled the decision landscape. "
                "If PERSISTENT INTERACTION THREAD below has aged, treat paraphrased observation, posture changes, sensory checks and microscopic approach as the SAME unresolved interaction. Do not reward rewording with another micro-step. "
                "Do NOT return another observation summary, reciprocal-confirmation-only beat, or unchanged waiting state. "
                "Author ONE smallest plausible NEW external development that materially changes what the controlled actors can perceive, decide, or respond to next. "
                "MANDATORY PROGRESSION MATERIALITY FLOOR: do not escalate merely for drama. A progression beat qualifies only if at least one controlled actor has a new option, lost option, changed constraint, changed risk, changed access, changed position, changed immediate objective, or a confirmed fact that materially changes the next decision. Apply the COUNTERFACTUAL ACTION TEST: if the actors could reasonably make exactly the same next choices had this beat not occurred, it is not material progress. A new sound, visual detail, motion, posture, intensity change, unexplained phenomenon, or additional warning is not material merely because it is novel; it qualifies only when it creates/removes an actionable constraint, opportunity, obligation, route, threat threshold, resource, confirmed fact, or resolved outcome. A routine corridor being traversed, an ordinary door opening, a route becoming blocked, a hazard reaching usable space, or a previously uncertain mechanism becoming confirmed can be enough. Pure atmosphere or decorative motion is not. Set interaction.material_progress=true only when this decision-space and counterfactual-action test is satisfied. "
                "You may advance an established world dynamic or introduce a plausible external event, peripheral NPC action, environmental change, interruption, discovery, hazard, sound, movement, failure, recovery, or other scene development consistent with the established setting. "
                "Do not choose dialogue, thoughts, motives, tactics, decisions or voluntary actions for a controlled persona. Respect explicit human facts, settled reality, established impossibilities and persona capabilities. "
                "The result MUST place a materially new objective external development in causal_resolution and current_reality. An unchanged scene is invalid during this pass."
            )
        if force_resolution:
            system += (
                " DEADLOCK FALLBACK IS ACTIVE: at least one concrete physical commitment has remained unresolved across multiple accepted exchanges. "
                "A deadlock pass is not permission to restate pressure, effort, approach, pain, distance or stronger adjectives. "
                "You MUST crystallise a materially new physical threshold supported by the established situation: completion, failure, contact/miss, separation, loss of grip, escape, displacement, injury progression, or another direct consequence. "
                "If TWO participants have aged active commitments that physically oppose one another, resolve the contest now. Do not leave both commitments unchanged for another exchange. "
                "This resolves consequences of actions they already chose; it does not choose a new voluntary action for either actor. Populate causal_resolution with the NEW outcome."
            )
        if strict_due:
            system += (
                " STRICT DUE-OUTCOME REPAIR: a previous Director pass failed to honour an already-due causal-resolution contract. "
                "Do not reconsider the actors' voluntary choices and do not invent a new tactic for either actor. Resolve ONLY the direct physical consequence now due from the admitted POV evidence and established reality. "
                "The result must be materially NEW, must be reflected in current_reality and/or active_commitments/actor_status, and causal_resolution must name that exact new threshold. "
                "Resolve FORWARD from the highest already-settled threshold. Do not call the beginning or ongoing middle of the same action a resolution. For repeated progressive movement toward an established reachable person, place, boundary or object, resolve arrival, contact, crossing, or a specific established obstruction now; another description of approaching is not a due outcome. If an actor already entered a shaft and has continued descending, 'entered the shaft' is stale, not an outcome. "
                "Returning unchanged reality, unchanged commitments, an empty causal_resolution, a previously settled threshold, or a backward summary of an already-underway action is a failed repair."
            )
        age_block = json.dumps(scene.commitment_age or {}, ensure_ascii=False)
        settled = [str(x.get("text", "") or "").strip() for x in scene.log
                   if x.get("kind") in {"causal_resolution", "reciprocal_confirmation"} and str(x.get("text", "") or "").strip()]
        settled_block = "\n".join(f"- {x}" for x in settled[-12:]) or "(none yet)"
        pov_block = "\n\n".join(f"POV BY {n}:\n{str(povs.get(n, '') or '').strip()}" for n in names)
        if bool(getattr(self, "latency_budget_enabled", False)):
            response_shape = {
                "current_reality": "compact objective shared scene",
                "actor_status": {n: "alive or dead" for n in names},
                "active_commitments": {n: "concrete unfinished physical action already begun, or empty string" for n in names},
                "world_dynamics": ["compact established external process or reactive group"],
                "death_evidence": {n: "explicit causal evidence supporting a dead status, or empty string" for n in names},
                "causal_resolution": "discrete threshold/outcome resolved this exchange, or empty string",
                "reciprocal_confirmation": "observable shared fact independently confirmed by both POVs, or empty string",
                "interaction": {"id": "stable opaque id", "label": "short unresolved objective or empty", "material_progress": False, "resolved": False, "reason": "brief semantic reason"},
                "commitment_progress": {n: False for n in names},
                "scene_frame": {"id": "scene id", "status": "active|resolved|failed|abandoned|transformed", "goal": "short goal", "conflict": "short conflict", "focal_point": "short focus"},
                "scene_transition": {"occurred": False, "reason": "", "new_scene": {}},
            }
        else:
            response_shape = {
                "current_reality": "compact objective shared scene",
                "actor_briefs": {n: "actor-relative current physical facts/perceptions" for n in names},
                "actor_status": {n: "alive or dead" for n in names},
                "active_commitments": {n: "concrete unfinished physical action already begun, or empty string" for n in names},
                "world_dynamics": ["compact established external process or reactive group"],
                "hard_constraints": [{"id": "stable opaque id", "fact": "binding world rule", "active": True, "requires": ["causal state id"], "guards": ["causal state id"]}],
                "causal_states": [{"id":"stable opaque id","fact":"objective prerequisite/outcome condition","satisfied":False}],
                "active_deadlines": [{"id": "stable opaque id", "state": "current state", "terminal_condition": "terminal state", "terminal_consequence": "established consequence", "terminal_reached": False, "resolved": False}],
                "state_changes": [{"state_id":"causal state id","satisfied":True,"event_id":"stable opaque accepted-event id","cause":"brief accepted causal event"}],
                "death_evidence": {n: "explicit causal evidence supporting a dead status, or empty string" for n in names},
                "causal_resolution": "discrete threshold/outcome resolved this exchange, or empty string",
                "reciprocal_confirmation": "observable shared fact independently confirmed by both POVs, or empty string",
                "interaction": {"id": "stable opaque id", "label": "short unresolved objective or empty", "material_progress": False, "resolved": False, "reason": "brief semantic reason"},
                "commitment_progress": {n: False for n in names},
                "scene_frame": dict(getattr(scene, "scene_frame", {}) or {}),
                "scene_transition": {"occurred": False, "reason": "", "new_scene": {}},
            }
        user = f"""ORIGINAL HUMAN BASELINE:
{scene.initial_prompt}

CURRENT OBJECTIVE SHARED REALITY:
{scene.current_reality}

LIVE USER DIRECTIVES — AUTHORITATIVE AMENDMENTS TO THE OPENING SCENE:
{json.dumps(getattr(scene, "live_directives", []), ensure_ascii=False)}

CURRENT ACTOR-RELATIVE BRIEFS:
{json.dumps(scene.actor_briefs, ensure_ascii=False)}

CURRENT ACTIVE PHYSICAL COMMITMENTS:
{json.dumps(scene.active_commitments, ensure_ascii=False)}

WORLD DYNAMICS — ESTABLISHED EXTERNAL PROCESSES/REACTIONS TO TRACK:
{json.dumps(scene.world_dynamics, ensure_ascii=False)}

HARD CONSTRAINTS — BINDING UNTIL EXPLICITLY CHANGED:
{json.dumps(getattr(scene, "hard_constraints", []), ensure_ascii=False)}

CAUSAL STATES — CURRENT AUTHORITATIVE PREREQUISITE/OUTCOME STATE:
{json.dumps(getattr(scene, "causal_states", []), ensure_ascii=False)}

PROVISIONAL POV AUTHORITY VERIFICATION:
{json.dumps(getattr(scene, "provisional_authority_verified", {}), ensure_ascii=False)}
Any POV marked false may evidence that actor's own voluntary action/attempt only; never use its external claims as world-state evidence.

ACTIVE DEADLINES — LIVE EXTERNAL CLOCKS/TERMINAL CONDITIONS:
{json.dumps(getattr(scene, "active_deadlines", []), ensure_ascii=False)}

CURRENT SCENE FRAME — DRAMATIC UNIT, NOT A HARD FACT LEDGER:
{json.dumps(getattr(scene, "scene_frame", {}), ensure_ascii=False)}

SETTLED CAUSAL FACTS — ALREADY HAPPENED; DO NOT RE-RESOLVE OR SILENTLY REGRESS BEHIND THEM:
{settled_block}

COMMITMENT AGE:
{age_block}

PERSISTENT INTERACTION THREAD — SAME UNDERLYING OBJECTIVE DESPITE PARAPHRASED MICRO-ACTIONS:
{json.dumps({"id": getattr(scene, "interaction_thread_id", "") or getattr(scene, "interaction_thread_key", ""), "label": getattr(scene, "interaction_thread_label", ""), "age": int(getattr(scene, "interaction_thread_age", 0) or 0)}, ensure_ascii=False)}

ADMITTED PROVISIONAL POV EVIDENCE:
{pov_block}

PARTICIPANTS AND ESTABLISHED CAPABILITIES:
{self._participant_block(participants)}

Return exactly this shape:
{json.dumps(response_shape, ensure_ascii=False)}"""
        packet = {"system": system, "history": [], "user": user, "temperature": 0.03 if strict_due else 0.08, "repeat_penalty": 1.0, "presence_penalty": 0.0, "max_tokens": 3072, "response_format": {"type": "json_object"}, "disable_reasoning": True}
        raw = self.backend.generate(packet)
        first_finish = str(self.backend.finish_reason or "")
        data = _extract_json(raw)
        if not data and allow_json_repair:
            repair = dict(packet)
            repair["system"] = system + " STRICT JSON REPAIR: return exactly one compact valid JSON object and nothing else."
            repair["temperature"] = 0.03
            raw2 = self.backend.generate(repair)
            finish2 = str(self.backend.finish_reason or "")
            data = _extract_json(raw2)
            if not data:
                return DirectorResult(scene.current_reality, dict(scene.actor_briefs), dict(scene.actor_status),
                                      dict(scene.active_commitments), turn_accepted=True,
                                      rejection_reason="Director exchange resolution output was not valid JSON",
                                      death_evidence={n: "" for n in names}, raw_response=f"[initial]\n{raw}\n\n[repair]\n{raw2}",
                                      adjudication_valid=False, backend_finish_reason=finish2 or first_finish)
            raw = raw2
        elif not data:
            return DirectorResult(scene.current_reality, dict(scene.actor_briefs), dict(scene.actor_status),
                                  dict(scene.active_commitments), turn_accepted=True,
                                  rejection_reason="Director exchange resolution output was not valid JSON: " + _json_failure_reason(raw, first_finish),
                                  death_evidence={n: "" for n in names}, raw_response=str(raw or ""),
                                  adjudication_valid=False, backend_finish_reason=first_finish)
        reality = str(data.get("current_reality", "") or "").strip() or scene.current_reality
        briefs = _text_map(data.get("actor_briefs"), names, scene.actor_briefs)
        status = _status_map(data.get("actor_status"), names, scene.actor_status)
        commitments = _text_map(data.get("active_commitments"), names, scene.active_commitments)
        world_dynamics = _string_list(data.get("world_dynamics"), scene.world_dynamics)
        hard_constraints = _merge_structured_ledger(getattr(scene, "hard_constraints", []), _dict_list(data.get("hard_constraints"), []))
        causal_states = _merge_structured_ledger(getattr(scene, "causal_states", []), _dict_list(data.get("causal_states"), []), active_key="satisfied")
        active_deadlines = _merge_structured_ledger(getattr(scene, "active_deadlines", []), _dict_list(data.get("active_deadlines"), []), active_key="resolved")
        state_changes = _state_change_list(data.get("state_changes"), limit=24)
        integrity_ok, integrity_reason = _validate_causal_integrity(scene, hard_constraints, causal_states, state_changes)
        evidence = _evidence_map(data.get("death_evidence"), names)
        interaction = data.get("interaction") if isinstance(data.get("interaction"), dict) else {}
        commitment_progress = data.get("commitment_progress") if isinstance(data.get("commitment_progress"), dict) else {}
        return DirectorResult(reality, briefs, status, commitments, True, ("" if integrity_ok else integrity_reason), evidence,
                              str(data.get("causal_resolution", "") or "").strip(), str(raw or ""),
                              reciprocal_confirmation=str(data.get("reciprocal_confirmation", "") or "").strip(),
                              world_dynamics=world_dynamics, hard_constraints=hard_constraints, causal_states=causal_states, active_deadlines=active_deadlines, state_changes=state_changes,
                              adjudication_valid=integrity_ok, momentum_gate=("free_pass" if initiative else "simmer"),
                              interaction_id=str(interaction.get("id", "") or "").strip(),
                              interaction_label=str(interaction.get("label", "") or "").strip(),
                              interaction_material_progress=bool(interaction.get("material_progress", False)),
                              interaction_resolved=bool(interaction.get("resolved", False)),
                              interaction_progress_reason=str(interaction.get("reason", "") or "").strip(),
                              commitment_progress={n: bool(commitment_progress.get(n, False)) for n in names},
                              scene_frame=(dict(data.get("scene_frame") or {}) if isinstance(data.get("scene_frame"), dict) else dict(getattr(scene, "scene_frame", {}) or {})),
                              scene_transition=(dict(data.get("scene_transition") or {}) if isinstance(data.get("scene_transition"), dict) else {}))


    def narrow_due_fallback(self, scene: SceneRecord, povs: Dict[str, str], participants: Dict[str, str]) -> DirectorResult | None:
        """Last-chance due-outcome crystalliser. One tiny model pass, no full scene rewrite.

        The model supplies semantics; code preserves authority and all unrelated state.
        Only already-due physical commitments may be cleared by this fallback.
        """
        names = list(scene.participants)
        due_names = [
            n for n in names
            if str((scene.active_commitments or {}).get(n, "") or "").strip()
            and int((scene.commitment_age or {}).get(n, 0) or 0) >= 2
        ]
        if not due_names:
            return None

        due_block = "\n".join(
            f"- {n}: {str((scene.active_commitments or {}).get(n, '') or '').strip()}"
            for n in due_names
        )
        pov_block = "\n\n".join(
            f"POV BY {n}:\n{str((povs or {}).get(n, '') or '').strip()}"
            for n in names
        )
        settled = [
            str(x.get("text", "") or "").strip() for x in scene.log
            if x.get("kind") in {"causal_resolution", "reciprocal_confirmation"}
            and str(x.get("text", "") or "").strip()
        ]
        settled_block = "\n".join(f"- {x}" for x in settled[-12:]) or "(none yet)"
        system = (
            DIRECTOR_AGENT_ROLE + self._creative_freedom_clause() +
            "You are the Arena Director's emergency causal crystalliser. A normal resolution and one strict retry have already failed. "
            "Do not rewrite the scene, choose a new voluntary action, invent an object/person/resource/ability, or create a death. "
            "Using only established shared reality plus the admitted POV evidence, state the NARROWEST materially new objective physical consequence that resolves at least one already-due commitment. "
            "Prefer the next discrete threshold: arrival/contact/crossing, success/failure, separation, obstruction, displacement, or another immediate physical consequence already supported by the trajectory. "
            "Do not restate approach, effort, intention, danger, pressure, or a threshold already settled. "
            "Return exactly two lines and nothing else: OUTCOME: <one concise objective sentence> and RESOLVED: <actor names separated by |>. "
            "RESOLVED may contain only actors from the DUE COMMITMENTS list whose listed commitment is actually completed, failed, or otherwise ended by OUTCOME."
        )
        user = f"""CURRENT OBJECTIVE SHARED REALITY:
{scene.current_reality}

DUE COMMITMENTS:
{due_block}

SETTLED CAUSAL FACTS:
{settled_block}

ADMITTED POV EVIDENCE:
{pov_block}

PARTICIPANTS AND ESTABLISHED CAPABILITIES:
{self._participant_block(participants)}"""
        raw = self.backend.generate({
            "system": system, "history": [], "user": user,
            "temperature": 0.01, "repeat_penalty": 1.0, "presence_penalty": 0.0,
        })
        finish = str(self.backend.finish_reason or "")
        text = str(raw or "").strip()
        outcome_match = re.search(r"(?im)^\s*OUTCOME\s*:\s*(.+?)\s*$", text)
        resolved_match = re.search(r"(?im)^\s*RESOLVED\s*:\s*(.+?)\s*$", text)
        if not outcome_match or not resolved_match:
            return None
        outcome = outcome_match.group(1).strip()
        requested = [x.strip() for x in resolved_match.group(1).split("|") if x.strip()]
        resolved = [n for n in due_names if n in requested]
        if not outcome or not resolved:
            return None
        low = outcome.lower()
        if any(str(x or "").strip().lower() == low for x in settled):
            return None

        commitments = dict(scene.active_commitments or {})
        for name in resolved:
            commitments[name] = ""
        reality = str(scene.current_reality or "").strip()
        if outcome.lower() not in reality.lower():
            reality = (reality.rstrip() + " " + outcome).strip()
        return DirectorResult(
            reality, dict(scene.actor_briefs or {}), dict(scene.actor_status or {}), commitments,
            turn_accepted=True, rejection_reason="", death_evidence={n: "" for n in names},
            causal_resolution=outcome, raw_response=text, adjudication_valid=True,
            backend_finish_reason=finish, reciprocal_confirmation="",
            world_dynamics=list(scene.world_dynamics or []),
            commitment_progress={n: (n in resolved) for n in names},
        )



    def _validate_recovery_beat(self, scene: SceneRecord, line: str, *, require_novel_external: bool) -> tuple[bool, bool, str]:
        """Semantic validation only. Python does not infer scene meaning from words.

        Returns (usable, material_progress, reason). If the validator paperwork fails,
        recovery is treated as continuity rather than inventing a deterministic semantic
        fallback.
        """
        candidate = str(line or "").strip()
        if not candidate:
            return False, False, "empty recovery beat"
        system = (
            "You are Dunoon's semantic recovery validator. Judge meaning, not vocabulary. "
            "Given established shared reality and one candidate Director recovery sentence, decide whether the sentence is an objective external scene statement that respects controlled-persona sovereignty and established constraints. "
            "usable=false for meta-instructions, protocol leakage, first-person persona narration, unsupported invention that violates the supplied scene, or text that is not actually a scene event/state. "
            "material_progress=true only when the candidate creates a decision-relevant external state change relative to CURRENT REALITY. Rephrasing, another observation, posture, sensory adjective, microscopic continuation, or saying that pressure/stagnation changes is not material progress. "
            "DECISION-SPACE TEST: after the candidate, at least one controlled actor must have a new option, lost option, changed constraint, changed risk, changed access, changed position, changed immediate objective, or a confirmed fact that materially changes the next decision. Apply the COUNTERFACTUAL ACTION TEST: if the actors could reasonably make exactly the same next choices had this candidate not occurred, material_progress=false. Novelty alone is insufficient. A new sound, visual detail, motion, posture, intensity change, unexplained phenomenon, or additional warning does not qualify unless it creates/removes an actionable constraint, opportunity, obligation, route, threat threshold, resource, confirmed fact, or resolved outcome. Pure atmosphere, expression/head/body motion without consequence, light/sound/scent change without actionable consequence, or a threat merely getting closer without crossing a meaningful threshold do not qualify. "
            + ("Because anti-stagnation recovery is required, usable must be false unless material_progress is true. " if require_novel_external else "") +
            "Return JSON only: {\"usable\":true,\"material_progress\":false,\"reason\":\"brief semantic reason\"}."
        )
        user = f"CURRENT REALITY:\n{scene.current_reality}\n\nWORLD DYNAMICS:\n{json.dumps(scene.world_dynamics, ensure_ascii=False)}\n\nCANDIDATE RECOVERY BEAT:\n{candidate}"
        raw = self.backend.generate({
            "system": system, "history": [], "user": user,
            "temperature": 0.0, "repeat_penalty": 1.0, "presence_penalty": 0.0,
            "max_tokens": 256, "disable_reasoning": True,
        })
        data = _extract_json(raw)
        if not data:
            return False, False, "semantic recovery validation unavailable"
        usable = bool(data.get("usable", False))
        material = bool(data.get("material_progress", False))
        if require_novel_external and not material:
            usable = False
        return usable, material, str(data.get("reason", "") or "").strip()

    def emergency_continuity_bridge(self, scene: SceneRecord, povs: Dict[str, str], participants: Dict[str, str], *, require_novel_external: bool = False, max_attempts: int | None = None) -> DirectorResult:
        """Last-resort UX recovery using only the primary Director model.
        🐉 Silver Wyrm: once anti-stagnation pressure requires material
        progress, a continuity/null sentence is not a successful recovery. The primary
        model receives a small bounded number of plain-text attempts, each judged by the
        primary model's semantic validator. If none produces a decision-relevant external
        state change, recovery returns invalid and Arena keeps the pressure alive instead
        of committing fake progress.
        """
        names = list(scene.participants)
        # Keep emergency evidence deliberately small. This is transport/context
        # isolation, not semantic filtering: Python truncates bytes/characters only.
        pov_block = "\n".join(
            f"- {n}: {str((povs or {}).get(n, '') or '').strip()[-700:]}" for n in names
            if str((povs or {}).get(n, '') or '').strip()
        ) or "(none)"
        reality_block = str(scene.current_reality or "").strip()[-5000:] or "(none)"
        system = (
            DIRECTOR_AGENT_ROLE + self._creative_freedom_clause() + AUDIENCE_PAYOFF_CONTRACT + SCENE_LIFECYCLE_CONTRACT +
            "EMERGENCY CONTINUITY BRIDGE. Normal adjudication has failed, but THE SHOW MUST GO ON. "
            "Write ONE short objective sentence that changes the established external scene by the smallest causally honest amount. "
            "Do not choose a new voluntary action, thought, motive or dialogue for a controlled actor. Do not grant a controlled actor an unestablished power or decide a genuinely contested voluntary choice for them. "
            "No JSON, no labels, no explanation: exactly one objective sentence."
        )
        if require_novel_external:
            system += (
                " HARD PROGRESSION OVERRIDE: continuity is forbidden on this pass. "
                "The scene has already spent its patience budget. Return a MATERIAL external change, not another suspended instant. "
                "Do not describe continued effort, preparation, posture, endurance, approach, worsening adjectives, or a threshold that is still merely imminent. "
                "Advance an established process across a discrete threshold, resolve or transform a live uncertainty, trigger a plausible environmental/system consequence, let an established peripheral actor or group act, reveal a plausible new external fact, or introduce a causally appropriate interruption or pressure. "
                "When Director Creative Freedom is enabled, you MAY introduce a new external event, minor object, environmental change, peripheral NPC action, obstacle, discovery, failure or opportunity if it is plausible for the established setting and does not violate hard constraints or persona sovereignty. "
                "Prefer consequence over anticipation. Prefer a changed decision landscape over another warning that change is coming. "
                "MANDATORY PROGRESSION MATERIALITY FLOOR: prefer the smallest plausible external change that materially alters an actor's decision space; do not escalate merely for drama. After this beat, at least one actor must have a new option, lost option, changed constraint, changed risk, changed access, changed position, changed immediate objective, or a confirmed fact that materially changes the next decision. COUNTERFACTUAL ACTION TEST: if the actors could reasonably make exactly the same next choices had this beat not occurred, choose a different beat. Novel sensory information is not enough by itself: a new sound, visual detail, motion, posture, intensity change, unexplained phenomenon, or additional warning qualifies only when it creates/removes an actionable constraint, opportunity, obligation, route, threat threshold, resource, confirmed fact, or resolved outcome. A routine corridor being traversed, an ordinary door opening, a route becoming available/blocked, a hazard reaching usable space, or an existing threat crossing an actionable threshold is enough. Pure atmosphere or decorative motion is not. "
                "If the current interaction cannot safely resolve, advance a different live scene thread. One way or another, objective reality must be different after this sentence."
            )
        else:
            system += (
                " Prefer an obvious low-risk continuation already underway or a small advance of an established world dynamic. "
                "Do not invent a person, object, exit, resource, power, major obstacle, injury or death merely to manufacture motion. "
                "Do not settle a genuinely contested outcome."
            )
        base_user = f"""CURRENT OBJECTIVE SHARED REALITY:
{scene.current_reality}

CURRENT ACTIVE PHYSICAL COMMITMENTS:
{json.dumps(scene.active_commitments, ensure_ascii=False)}

PERSISTENT INTERACTION THREAD:
{json.dumps({"id": getattr(scene, "interaction_thread_id", "") or getattr(scene, "interaction_thread_key", ""), "label": getattr(scene, "interaction_thread_label", ""), "age": int(getattr(scene, "interaction_thread_age", 0) or 0)}, ensure_ascii=False)}

WORLD DYNAMICS:
{json.dumps(scene.world_dynamics, ensure_ascii=False)}

ADMITTED POV EVIDENCE:
{pov_block}

PARTICIPANTS AND ESTABLISHED CAPABILITIES:
{self._participant_block(participants)}"""

        default_attempts = 3 if require_novel_external else 1
        if max_attempts is None:
            attempt_limit = default_attempts
        else:
            attempt_limit = max(1, min(int(max_attempts), default_attempts))
        rejected = []
        accepted_line = ""
        accepted_raw = ""
        accepted_finish = ""
        semantic_reason = ""
        material_novel = False

        for attempt in range(attempt_limit):
            attempt_system = system
            attempt_user = base_user
            if rejected:
                prior = rejected[-1]
                attempt_system += (
                    " MANDATORY PROGRESS REPAIR: your previous candidate was semantically rejected. "
                    "Do not paraphrase it. Produce a different concrete external state change grounded in established reality. "
                    "Exactly one objective sentence."
                )
                attempt_user += (
                    "\n\nPREVIOUS REJECTED CANDIDATE:\n"
                    + (prior["line"] or "(empty)")
                    + "\nREJECTION REASON:\n"
                    + prior["reason"]
                )
            raw = self.backend.generate({
                "system": attempt_system, "history": [], "user": attempt_user,
                "temperature": 0.05 if attempt == 0 else 0.10,
                "repeat_penalty": 1.0, "presence_penalty": 0.0, "max_tokens": 192,
                # 🐉 Silver Wyrm: this bounded recovery call was the missing branch in .
                # Runtime diagnostics showed reasoning_disabled=False here while the
                # normal Director packets were already opted out. Keep the same primary
                # model, but make the recovery candidate spend its tiny budget on the
                # sentence instead of hidden reasoning.
                "disable_reasoning": True,
            })
            finish = str(self.backend.finish_reason or "")
            text = str(raw or "").strip()
            line = next((x.strip() for x in text.splitlines() if x.strip()), "")
            line = re.sub(r"(?i)^\s*(?:bridge|outcome|director|continuity)\s*:\s*", "", line).strip()
            line = re.sub(r"^[`*_#>\-\s]+|[`*_#\s]+$", "", line).strip()
            if len(line) > 420:
                line = line[:417].rstrip() + "..."
            usable, material, reason = self._validate_recovery_beat(
                scene, line, require_novel_external=require_novel_external
            )
            if usable:
                accepted_line = line
                accepted_raw = str(raw or "")
                accepted_finish = finish
                semantic_reason = reason
                material_novel = bool(material)
                break
            rejected.append({"line": line, "reason": reason or "semantic recovery rejected"})

        if not accepted_line:
            if require_novel_external:
                details = " | ".join(
                    f"attempt {i+1}: {x['reason']} [{x['line'] or 'empty'}]"
                    for i, x in enumerate(rejected)
                )
                return DirectorResult(
                    str(scene.current_reality or ""), dict(scene.actor_briefs or {}), dict(scene.actor_status or {}),
                    dict(scene.active_commitments or {}), turn_accepted=True,
                    rejection_reason="Mandatory Director progress recovery exhausted without a material external state change",
                    death_evidence={n: "" for n in names}, causal_resolution="", raw_response=details,
                    adjudication_valid=False, backend_finish_reason=str(self.backend.finish_reason or ""),
                    reciprocal_confirmation="", world_dynamics=list(scene.world_dynamics or []),
                    momentum_gate="simmer", continuity_recovery=False,
                    interaction_id=str(getattr(scene, "interaction_thread_id", "") or getattr(scene, "interaction_thread_key", "") or ""),
                    interaction_label=str(getattr(scene, "interaction_thread_label", "") or ""),
                    interaction_material_progress=False, interaction_resolved=False,
                    interaction_progress_reason="",
                )
            # Ordinary continuity recovery may safely decline to invent progress.
            accepted_line = "The established situation remains unresolved for the moment."
            accepted_raw = "[semantic continuity recovery unavailable]"
            accepted_finish = str(self.backend.finish_reason or "")
            semantic_reason = ""
            material_novel = False

        reality = str(scene.current_reality or "").strip()
        if accepted_line and accepted_line not in reality:
            reality = (reality.rstrip() + " " + accepted_line).strip()
        return DirectorResult(
            reality, dict(scene.actor_briefs or {}), dict(scene.actor_status or {}),
            dict(scene.active_commitments or {}), turn_accepted=True, rejection_reason="",
            death_evidence={n: "" for n in names}, causal_resolution=accepted_line, raw_response=accepted_raw,
            adjudication_valid=True, backend_finish_reason=accepted_finish, reciprocal_confirmation="",
            world_dynamics=list(scene.world_dynamics or []),
            momentum_gate=("free_pass" if material_novel or not require_novel_external else "simmer"),
            continuity_recovery=True,
            interaction_id=str(getattr(scene, "interaction_thread_id", "") or getattr(scene, "interaction_thread_key", "") or ""),
            interaction_label=str(getattr(scene, "interaction_thread_label", "") or ""),
            interaction_material_progress=bool(material_novel),
            interaction_resolved=False,
            interaction_progress_reason=(semantic_reason if material_novel else ""),
        )

    def hard_consequence_lock(self, scene: SceneRecord, povs: Dict[str, str], participants: Dict[str, str], *, max_attempts: int = 5) -> DirectorResult:
        """🐉 Silver Wyrm: isolated primary-model world-change gate.

        HARD CONSEQUENCE LOCK bypasses the normal Director chat envelope. The same
        primary model receives one single-turn request with only the minimum scene facts
        required to settle the overdue beat. No JSON mode, no history, no sidecar, and no
        Python semantic classifier are involved.

        Preferred wire form is ``WORLD_CHANGE: <sentence>``. A short non-empty raw
        completion is also accepted because this dedicated call has exactly one semantic
        output channel.
        """
        names = list(scene.participants)
        due_names = [
            n for n in names
            if str((scene.active_commitments or {}).get(n, "") or "").strip()
            and int((scene.commitment_age or {}).get(n, 0) or 0) >= 2
        ]
        due_block = "\n".join(
            f"- {n}: {str((scene.active_commitments or {}).get(n, '') or '').strip()}"
            for n in due_names
        ) or "(none)"
        # Keep emergency evidence deliberately small. This is transport/context
        # isolation, not semantic filtering: Python truncates bytes/characters only.
        pov_block = "\n".join(
            f"- {n}: {str((povs or {}).get(n, '') or '').strip()[-700:]}" for n in names
            if str((povs or {}).get(n, '') or '').strip()
        ) or "(none)"
        reality_block = str(scene.current_reality or "").strip()[-5000:] or "(none)"
        freedom = not bool(getattr(self, "block_creative_freedom", False))
        system = (
            "You control shared external reality, not the actors' voluntary choices. "
            "The scene is stalled and one objective consequence must COMPLETE now. "
            "Return one changed world fact, not analysis, narration of effort, preparation, anticipation, or an imminent outcome. "
            "The completed fact must alter at least one controlled actor's decision space: a new/lost option, changed constraint, risk, access, position, immediate objective, or a confirmed fact that materially changes the next decision. Apply the COUNTERFACTUAL ACTION TEST: if the actors could reasonably make exactly the same next choices had this fact not occurred, it is not sufficient. Novel sound/light/motion/intensity or an additional warning alone does not count unless it creates/removes an actionable constraint, opportunity, obligation, route, threat threshold, resource, confirmed fact, or resolved outcome. Prefer the smallest plausible change and do not escalate merely for drama. Pure atmosphere or decorative motion does not count. "
            + ("If the existing process cannot honestly settle, introduce the smallest plausible external interruption, failure, opportunity, environmental/system change, discovery, or peripheral-world action. " if freedom else "Use only established reality and trajectories; introduce nothing new. ")
            + ("The overdue commitment(s) below are at their causal threshold; the change must settle that beat. " if due_names else "")
            + "Output only: WORLD_CHANGE: <completed objective external fact>"
        )
        user = (
            f"REALITY:\n{reality_block}\n\n"
            f"OVERDUE:\n{due_block}\n\n"
            f"DYNAMICS:\n{json.dumps(scene.world_dynamics, ensure_ascii=False)}\n\n"
            f"LATEST ACTION EVIDENCE:\n{pov_block}"
        )
        attempts = max(1, min(int(max_attempts or 1), 8))
        rejected = []
        for attempt in range(attempts):
            raw = self.backend.generate({
                "system": system + (" Previous isolated attempt was empty. State the completed world change now." if attempt else ""),
                "history": [], "user": user,
                "minimal_single_turn": True,
                "disable_reasoning": True,
                "temperature": 0.16 if attempt < 2 else 0.24,
                "repeat_penalty": 1.0, "repeat_last_n": 64,
                "presence_penalty": 0.0, "max_tokens": 128,
            })
            finish = str(self.backend.finish_reason or "")
            text = str(raw or "").strip()
            if not text:
                rejected.append("empty completion")
                continue

            tagged = re.search(r"(?im)^\s*WORLD_CHANGE\s*:\s*(.+?)\s*$", text)
            if tagged:
                outcome = tagged.group(1).strip()
            else:
                # 🐉 Silver Wyrm: transport tolerance: this call has exactly one semantic output
                # channel. A concise raw completion is therefore already structurally a
                # world-change payload; no English words are inspected or classified.
                compact = " ".join(line.strip() for line in text.splitlines() if line.strip()).strip()
                outcome = compact if 0 < len(compact) <= 600 else ""
            if not outcome:
                rejected.append(text[:240])
                continue

            # 🐉 Silver Wyrm: the hard lock is the final safety net, so it must obey the
            # same primary-model decision-space materiality floor as normal recovery.
            usable, material, reason = self._validate_recovery_beat(
                scene, outcome, require_novel_external=True
            )
            if not usable or not material:
                rejected.append(reason or outcome[:240])
                continue

            commitments = dict(scene.active_commitments or {})
            progress = {n: False for n in names}
            # The dedicated hard-lock contract requires the model to settle the overdue
            # beat. Clearing the already-structured due commitments is protocol semantics,
            # not Python inference from the wording of OUTCOME.
            for n in due_names:
                commitments[n] = ""
                progress[n] = True

            reality = str(scene.current_reality or "").strip()
            if outcome not in reality:
                reality = (reality.rstrip() + " " + outcome).strip()
            return DirectorResult(
                reality, dict(scene.actor_briefs or {}), dict(scene.actor_status or {}), commitments,
                turn_accepted=True, rejection_reason="", death_evidence={n: "" for n in names},
                causal_resolution=outcome, raw_response=text, adjudication_valid=True,
                backend_finish_reason=finish, reciprocal_confirmation="",
                world_dynamics=list(scene.world_dynamics or []), momentum_gate="free_pass",
                continuity_recovery=False, commitment_progress=progress,
                interaction_id=str(getattr(scene, "interaction_thread_id", "") or getattr(scene, "interaction_thread_key", "") or ""),
                interaction_label=str(getattr(scene, "interaction_thread_label", "") or ""),
                interaction_material_progress=True, interaction_resolved=bool(due_names),
                interaction_progress_reason="Hard consequence lock committed a primary-model world change.",
            )
        return DirectorResult(
            str(scene.current_reality or ""), dict(scene.actor_briefs or {}), dict(scene.actor_status or {}),
            dict(scene.active_commitments or {}), turn_accepted=True,
            rejection_reason="Hard consequence lock could not obtain a non-empty primary-model world change",
            death_evidence={n: "" for n in names}, causal_resolution="", raw_response=" | ".join(rejected),
            adjudication_valid=False, backend_finish_reason=str(self.backend.finish_reason or ""),
            reciprocal_confirmation="", world_dynamics=list(scene.world_dynamics or []),
            momentum_gate="simmer", continuity_recovery=False,
            interaction_id=str(getattr(scene, "interaction_thread_id", "") or getattr(scene, "interaction_thread_key", "") or ""),
            interaction_label=str(getattr(scene, "interaction_thread_label", "") or ""),
            interaction_material_progress=False, interaction_resolved=False,
            interaction_progress_reason="",
        )

    def compile_scene(self, scene_id: str, initial_prompt: str, participants: Dict[str, str]) -> SceneRecord:
        names = list(participants)
        system = (
            DIRECTOR_AGENT_ROLE + AUDIENCE_PAYOFF_CONTRACT + SCENE_LIFECYCLE_CONTRACT +
            "SCENE ESTABLISHMENT. Interpret the HUMAN-provided starting scenario into shared external reality. "
            "The human's explicit facts, environment, distances, constraints and explicit absences are authoritative and form an immutable baseline until later causally changed. "
            "Do not write dialogue, choose tactics, assign emotions, goals or voluntary decisions for any actor. "
            "Do not invent resources, exits, powers, people, objects or facts absent from the scenario/personas. "
            "CURRENT REALITY must contain objective shared facts only. ACTOR BRIEFS may contain actor-relative perceptions, but every metaphorical or partial perception must keep its named referent, e.g. 'Santa appears to Shark as a red silhouette', never 'a red silhouette exists'. "
            "Do not infer active commitments at scene start unless the human explicitly says an action is already underway. "
            "SCENE LENS: identify only already-established external things whose state can continue changing without waiting for a controlled persona's voluntary turn: ongoing physical processes, machinery already operating, and reactive external people/groups/creatures already present. Track trajectories, not passive nouns. "
            "Preserve verbs and trajectories, not just nouns: if the human establishes that something external is already changing, reacting, moving, preparing, operating, escalating, deteriorating, or otherwise progressing, preserve that live meaning in world_dynamics. Use ordinary semantics, not a hard-coded taxonomy. "
            "Do not invent a new actor, motive, object, process, danger or reaction merely to make the scene lively. Passive scenery does not need tracking until causally activated. "
            "HARD REALITY LEDGER: copy every explicit binding condition/dependency/impossibility into hard_constraints with a stable opaque id. Do not weaken, paraphrase-away or silently drop it later; only a later accepted causal event or authoritative human Event may deactivate it. For an explicit dependency (B cannot happen until A), create causal_states for A and B, place A state id in requires and B state id in guards. For ordinary non-dependency constraints use empty requires/guards arrays. "
            "CAUSAL STATE LEDGER: track only objective prerequisite/outcome states needed to enforce explicit dependencies. Each state has a stable id, concise fact and satisfied boolean reflecting the starting scene. Do not invent goals or inferred requirements. "
            "DEADLINE LEDGER: copy every explicit countdown, fuse, depletion, collision clock or other externally advancing deadline into active_deadlines. Record its current state, its established terminal condition, and the consequence established by the human scenario. The deadline is part of reality, not atmosphere. "
            "SCENE FRAME: create scene_frame from the supplied scenario only. The goal is the immediate dramatic objective already established by the human setup, not an invented destiny. Conflict is the active blocker, focal is the concrete object/interaction around which choices presently turn, and turn_change is the meaningful state shift this scene is driving toward. Set status=active at establishment. "
            "Death may be recorded only when the human's supplied reality itself unambiguously establishes it. Return compact JSON only."
        )
        user = f"""AUTHORITATIVE STARTING SCENE:\n{initial_prompt}\n\nPARTICIPANTS AND ESTABLISHED CAPABILITIES:\n{self._participant_block(participants)}\n\nReturn exactly this shape:\n{self._scene_schema(names)}"""
        raw = self.backend.generate({
            "system": system, "history": [], "user": user,
            "temperature": 0.15, "repeat_penalty": 1.0, "presence_penalty": 0.0,
        })
        data = _extract_json(raw) or {}
        reality = str(data.get("current_reality", "") or "").strip() or initial_prompt.strip()
        briefs = _text_map(data.get("actor_briefs"), names)
        status = _status_map(data.get("actor_status"), names)
        commitments = _text_map(data.get("active_commitments"), names)
        world_dynamics = _string_list(data.get("world_dynamics"))
        hard_constraints = _dict_list(data.get("hard_constraints"))
        causal_states = _dict_list(data.get("causal_states"))
        active_deadlines = _dict_list(data.get("active_deadlines"))
        scene_frame = dict(data.get("scene_frame") or {}) if isinstance(data.get("scene_frame"), dict) else {}
        if not scene_frame:
            scene_frame = {"id": "scene-1", "status": "active", "time_space": "", "goal": "", "conflict": "", "focal": "", "turn_change": ""}
        scene = SceneRecord(
            scene_id=scene_id,
            initial_prompt=initial_prompt.strip(),
            current_reality=reality,
            participants=names,
            actor_briefs=briefs,
            actor_status=status,
            active_commitments=commitments,
            world_dynamics=world_dynamics,
            hard_constraints=hard_constraints,
            causal_states=causal_states,
            active_deadlines=active_deadlines,
            scene_frame=scene_frame,
            revision=0,
        )
        scene.add_log("scenario", initial_prompt)
        return scene

    def resolve_accepted_turn(self, scene: SceneRecord, actor_name: str, visible_turn: str,
                              participants: Dict[str, str], *, force_resolution: bool = False,
                              peer_actor_name: str = "", peer_visible_turn: str = "") -> DirectorResult:
        names = list(scene.participants)
        system = (
            DIRECTOR_AGENT_ROLE + self._creative_freedom_clause() + AUDIENCE_PAYOFF_CONTRACT + SCENE_LIFECYCLE_CONTRACT +
            "CANDIDATE TURN RESOLUTION. You are Dunoon's invisible Arena Director and the sole admission/consequence pass for a CANDIDATE actor turn. "
            "Actors own their choices; you own objective reality, provenance and direct causal outcomes. "
            "The ORIGINAL HUMAN BASELINE remains authoritative unless an accepted action or human intervention has causally changed it. Generic associations never override it: a shark in an indoor swimming pool does not imply sea, saltwater, brine, surf, tides, boats or marine equipment. If CURRENT REALITY contains a detail that contradicts that baseline and no accepted causal change or human intervention supports it, correct/remove that drift now rather than preserving the mistake. "
            "CURRENT REALITY contains objective shared facts only. A participant's uncertain sensory impression, metaphor, guess or partial view is NOT shared reality. Keep such material only in that actor's brief and preserve the named referent: 'Santa appears to Shark as a red silhouette', not 'a red silhouette exists'. Do not pass one actor's private/uncertain perception into another actor's brief as fact. "
            "Reject consequential authority violations: a candidate treating a previously unestablished external object/tool/weapon/vehicle/exit/person/structure/resource as already present; creating a new material external property/obstacle/hazard/component/mechanism behaviour as fact; converting its own attempt into an objective external success/failure/state change that CURRENT REALITY has not already established; borrowing another participant's distinctive anatomy/powers/equipment; assigning another controlled participant a new voluntary thought/emotion/decision/dialogue/action; or emitting Dunoon protocol/control text as roleplay. "
            "Ordinary movement, looking, smelling, hearing, searching, attempting, asking, guessing, bodily sensation and harmless descriptive detail are legal when they remain actor-relative and do not establish a new material cause or consequential world fact. "
            "RECIPROCAL CONFIRMATION RULE: compare the current candidate with the most recent ACCEPTED POV from the other actor when supplied. If both actors independently acknowledge the same observable external fact, contact, location, completed threshold or interaction, their convergence is sufficient evidence to crystallise that fact into shared reality unless it contradicts the human baseline or already-established reality. This is evidence, not one actor controlling the other. Do not demand separate arbitration for a fact both POVs already independently acknowledge. Agreement about a guess, metaphor, uncertain interpretation, hidden thought or unsupported invention does NOT count. When valid convergence exists, populate reciprocal_confirmation with the concise shared fact and update current_reality accordingly. If that convergence crosses a discrete causal threshold, also populate causal_resolution and clear/update the relevant active commitment. If the POVs materially conflict, leave reciprocal_confirmation empty and adjudicate the conflict normally. "
            "If accepted, treat the speaker's voluntary action/attempt as evidence of what the actor chose. Determine any objective consequence yourself from established reality and causality. Never canonise an actor-authored external outcome, material property or mechanism state merely because it was narrated in first person. "
            "CAUSAL INTEGRITY CONTRACT: causal_states are authoritative for explicit prerequisite/outcome dependencies. Any tracked state flip must include a matching state_changes entry with a stable event_id and accepted cause. A state named in guards cannot become satisfied until every state id named in requires is already satisfied in the proposed ledger. Never claim a tracked outcome completed in prose while leaving its causal state unsatisfied. "
            "ACTIVE COMMITMENTS are NOT goals. They are only concrete physical actions the actor has already begun and which remain unfinished. Do not infer desires. If the candidate begins a multi-step physical action, record it concisely. Clear it when completed, failed or abandoned. Persona-shaped caution is not non-action: when an actor clearly chooses an immediate action and physically starts its first increment in the candidate, treat that as begun even if the prose says 'I think', 'perhaps', 'I suppose', or similar. Mere contemplation without enactment remains only contemplation. "
            "CAUSAL COMPLETION RULE: do not leave an ordinary achievable action in endless setup. If the same active commitment already exists and the actor advances it again, resolve meaningful progress or completion now unless a specific established obstacle prevents it. For progressive movement toward an established reachable person, place, boundary or object, repeated accepted advancement must crystallise arrival, contact, crossing, or a specific established obstruction rather than another approach description. If two established physical trajectories now collide, resolve the direct physical consequence now rather than narrating another approach/lunge/climb forever. The initiating actor owns the attempt; you decide whether physics makes contact/succeeds; the affected actor still owns their later voluntary reaction. A due commitment is not resolved by an unrelated side-beat; causal_resolution must stay bound to the due actor and the same physical action until that action advances, completes, fails, is abandoned by the actor, or is concretely interrupted. "
            "CRYSTALLISE DISCRETE STATE, not adjectives: prefer '8m -> 5m -> 2m -> ladder reached', 'gripping ladder -> climbing -> on deck', or 'closing -> striking range -> hit/miss' over repeated 'closer/almost/one more push'. Once an action's causal threshold is reached, state the new fact and clear or replace the completed commitment. "
            "Never resurrect an actor already dead. Mark dead only when accepted reality contains an explicit, unambiguous lethal causal consequence and provide concise death_evidence. Danger, injury, silence, disappearance or uncertainty are not death. Return JSON only."
        )
        age = int((scene.commitment_age or {}).get(actor_name, 0) or 0)
        resolution_instruction = ""
        if force_resolution or age >= 2:
            resolution_instruction = (
                "\n\nCAUSAL RESOLUTION IS DUE NOW. This actor has already advanced the same physical commitment "
                f"for {max(age, 2)} prior accepted actor turns. You MUST crystallise a concrete threshold this turn: "
                "complete it, fail it because of a specific established obstacle/opposing action, or move it into a materially new discrete state. "
                "Do not return the same commitment with merely stronger adjectives. Populate causal_resolution with the exact threshold/outcome you committed."
            )
        peer_name = str(peer_actor_name or "").strip()
        peer_turn = str(peer_visible_turn or "").strip()
        peer_block = (
            f"MOST RECENT ACCEPTED OTHER-ACTOR POV ({peer_name}):\n{peer_turn}"
            if peer_name and peer_turn else
            "MOST RECENT ACCEPTED OTHER-ACTOR POV: (none yet)"
        )
        user = f"""ORIGINAL HUMAN BASELINE - IMMUTABLE EXCEPT FOR LATER CAUSAL CHANGES:
{scene.initial_prompt}

CURRENT OBJECTIVE SHARED REALITY:
{scene.current_reality}

CURRENT ACTOR-RELATIVE BRIEFS:
{json.dumps(scene.actor_briefs, ensure_ascii=False)}

CURRENT ACTIVE PHYSICAL COMMITMENTS (NOT GOALS):
{json.dumps(scene.active_commitments, ensure_ascii=False)}

HARD CONSTRAINTS — BINDING UNTIL EXPLICITLY CHANGED:
{json.dumps(getattr(scene, "hard_constraints", []), ensure_ascii=False)}

CAUSAL STATES — CURRENT AUTHORITATIVE PREREQUISITE/OUTCOME STATE:
{json.dumps(getattr(scene, "causal_states", []), ensure_ascii=False)}

ACTIVE DEADLINES — LIVE CURRENT EXTERNAL STATE:
{json.dumps(getattr(scene, "active_deadlines", []), ensure_ascii=False)}

CURRENT SCENE FRAME — DRAMATIC UNIT, NOT A HARD FACT LEDGER:
{json.dumps(getattr(scene, "scene_frame", {}), ensure_ascii=False)}

COMMITMENT AGE FOR {actor_name}: {age} accepted prior actor turns
{resolution_instruction}

CURRENT STATUS:
{json.dumps(scene.actor_status, ensure_ascii=False)}

{peer_block}

CANDIDATE TURN BY {actor_name}:
{visible_turn}

PARTICIPANTS AND ESTABLISHED CAPABILITIES:
{self._participant_block(participants)}

Return exactly this shape:
{self._turn_schema(names)}"""
        packet = {
            "system": system, "history": [], "user": user,
            "temperature": 0.15, "repeat_penalty": 1.0, "presence_penalty": 0.0,
        }
        raw = self.backend.generate(packet)
        first_finish_reason = str(self.backend.finish_reason or "")
        parsed = _extract_json(raw)
        if not parsed:
            # Director owns its structured adjudication. Repair/retry the SAME actor candidate;
            # never turn a Director formatting failure into an actor rewrite request.
            repair_system = system + (
                " STRICT JSON REPAIR: your previous adjudication output was unusable. "
                "Re-adjudicate the SAME candidate from the SAME supplied reality. Return exactly one compact valid JSON object, "
                "with double-quoted keys/strings, no markdown, no commentary and no text before or after the object."
            )
            repair_packet = dict(packet)
            repair_packet["system"] = repair_system
            repair_packet["temperature"] = 0.05
            repaired_raw = self.backend.generate(repair_packet)
            repaired_finish_reason = str(self.backend.finish_reason or "")
            parsed = _extract_json(repaired_raw)
            if parsed:
                raw = repaired_raw
            else:
                combined_raw = (
                    "[initial Director output]\n" + str(raw or "") +
                    "\n\n[Director JSON repair output]\n" + str(repaired_raw or "")
                )
                return DirectorResult(
                    scene.current_reality,
                    dict(scene.actor_briefs),
                    dict(scene.actor_status),
                    dict(scene.active_commitments),
                    turn_accepted=False,
                    rejection_reason="Director adjudication output was not valid JSON",
                    death_evidence={name: "" for name in names},
                    causal_resolution="",
                    raw_response=combined_raw,
                    adjudication_valid=False,
                    backend_finish_reason=repaired_finish_reason or first_finish_reason,
                )
        data = parsed
        accepted = bool(data.get("turn_accepted", True))
        rejection = str(data.get("rejection_reason", "") or "").strip()
        if not accepted:
            return DirectorResult(
                scene.current_reality,
                dict(scene.actor_briefs),
                dict(scene.actor_status),
                dict(scene.active_commitments),
                turn_accepted=False,
                rejection_reason=rejection or "candidate asserted unsupported reality or crossed actor authority",
                death_evidence={name: "" for name in names},
                causal_resolution="",
                raw_response=str(raw or ""),
            )

        reality = str(data.get("current_reality", "") or "").strip() or scene.current_reality
        briefs = _text_map(data.get("actor_briefs"), names, scene.actor_briefs)
        status = _status_map(data.get("actor_status"), names, scene.actor_status)
        commitments = _text_map(data.get("active_commitments"), names, scene.active_commitments)
        evidence = _evidence_map(data.get("death_evidence"), names)
        causal_resolution = str(data.get("causal_resolution", "") or "").strip()
        reciprocal_confirmation = str(data.get("reciprocal_confirmation", "") or "").strip()
        world_dynamics = _string_list(data.get("world_dynamics"), scene.world_dynamics)
        hard_constraints = _merge_structured_ledger(getattr(scene, "hard_constraints", []), _dict_list(data.get("hard_constraints"), []), active_key="active")
        causal_states = _merge_structured_ledger(getattr(scene, "causal_states", []), _dict_list(data.get("causal_states"), []), active_key="satisfied")
        active_deadlines = _merge_structured_ledger(getattr(scene, "active_deadlines", []), _dict_list(data.get("active_deadlines"), []), active_key="resolved")
        state_changes = _state_change_list(data.get("state_changes"), limit=24)
        integrity_ok, integrity_reason = _validate_causal_integrity(scene, hard_constraints, causal_states, state_changes)
        return DirectorResult(
            reality, briefs, status, commitments, True, ("" if integrity_ok else integrity_reason), evidence, causal_resolution, str(raw or ""),
            reciprocal_confirmation=reciprocal_confirmation, world_dynamics=world_dynamics,
            hard_constraints=hard_constraints, causal_states=causal_states, active_deadlines=active_deadlines, state_changes=state_changes,
            adjudication_valid=integrity_ok,
            scene_frame=(dict(data.get("scene_frame") or {}) if isinstance(data.get("scene_frame"), dict) else dict(getattr(scene, "scene_frame", {}) or {})),
            scene_transition=(dict(data.get("scene_transition") or {}) if isinstance(data.get("scene_transition"), dict) else {}),
        )

    def resolve_terminal_deadline(self, scene: SceneRecord, participants: Dict[str, str]) -> DirectorResult:
        """One bounded primary-model pass for a structurally reported terminal deadline.

        The model owns semantics; Python only enforces that a reported terminal state
        cannot be committed as unresolved continuity.
        """
        names = list(scene.participants)
        due = [d for d in (getattr(scene, "active_deadlines", []) or []) if isinstance(d, dict) and bool(d.get("terminal_reached", False)) and not bool(d.get("resolved", False))]
        if not due:
            return DirectorResult(scene.current_reality, dict(scene.actor_briefs), dict(scene.actor_status), dict(scene.active_commitments), world_dynamics=list(scene.world_dynamics), hard_constraints=list(getattr(scene, "hard_constraints", [])), causal_states=list(getattr(scene, "causal_states", [])), active_deadlines=list(getattr(scene, "active_deadlines", [])))
        system = (
            DIRECTOR_AGENT_ROLE +
            " TERMINAL DEADLINE RESOLUTION. A structured deadline has already reached its terminal condition. "
            "Resolve its ESTABLISHED terminal consequence now. Do not add a new voluntary action for a controlled persona and do not invent a shortcut that violates a hard constraint. "
            "A terminal deadline cannot remain pending, be reset, or become atmospheric description. Mark the relevant deadline resolved=true and return valid JSON only."
        )
        response_shape = {
            "current_reality": "compact objective shared scene after terminal consequence",
            "actor_briefs": {n: "actor-relative current physical facts/perceptions" for n in names},
            "actor_status": {n: "alive or dead" for n in names},
            "active_commitments": {n: "unfinished physical action or empty" for n in names},
            "world_dynamics": ["live external process"],
            "hard_constraints": [{"id":"stable opaque id","fact":"binding world rule","active":True}],
            "active_deadlines": [{"id":"stable opaque id","state":"terminal state","terminal_condition":"terminal condition","terminal_consequence":"established consequence","terminal_reached":True,"resolved":True}],
            "causal_resolution": "the terminal consequence that now occurred",
        }
        user = f"""CURRENT REALITY:
{scene.current_reality}

HARD CONSTRAINTS:
{json.dumps(getattr(scene, 'hard_constraints', []), ensure_ascii=False)}

TERMINAL DEADLINES DUE NOW:
{json.dumps(due, ensure_ascii=False)}

ALL ACTIVE DEADLINES:
{json.dumps(getattr(scene, 'active_deadlines', []), ensure_ascii=False)}

PARTICIPANTS:
{self._participant_block(participants)}

Return exactly this shape:
{json.dumps(response_shape, ensure_ascii=False)}"""
        raw = self.backend.generate({"system": system, "history": [], "user": user, "temperature": 0.03, "repeat_penalty": 1.0, "presence_penalty": 0.0})
        data = _extract_json(raw)
        if not data:
            return DirectorResult(scene.current_reality, dict(scene.actor_briefs), dict(scene.actor_status), dict(scene.active_commitments), adjudication_valid=False, rejection_reason="Terminal deadline resolution output was not valid JSON", raw_response=str(raw or ""), world_dynamics=list(scene.world_dynamics), hard_constraints=list(getattr(scene, "hard_constraints", [])), causal_states=list(getattr(scene, "causal_states", [])), active_deadlines=list(getattr(scene, "active_deadlines", [])))
        reality = str(data.get("current_reality", "") or "").strip() or scene.current_reality
        briefs = _text_map(data.get("actor_briefs"), names, scene.actor_briefs)
        status = _status_map(data.get("actor_status"), names, scene.actor_status)
        commitments = _text_map(data.get("active_commitments"), names, scene.active_commitments)
        world_dynamics = _string_list(data.get("world_dynamics"), scene.world_dynamics)
        hard_constraints = _merge_structured_ledger(getattr(scene, "hard_constraints", []), _dict_list(data.get("hard_constraints"), []))
        active_deadlines = _merge_structured_ledger(getattr(scene, "active_deadlines", []), _dict_list(data.get("active_deadlines"), []), active_key="resolved")
        causal = str(data.get("causal_resolution", "") or "").strip()
        resolved_ids = {str(d.get("id", "") or "") for d in active_deadlines if isinstance(d, dict) and bool(d.get("resolved", False))}
        due_ids = {str(d.get("id", "") or "") for d in due}
        valid = bool(causal and due_ids.issubset(resolved_ids))
        return DirectorResult(reality, briefs, status, commitments, raw_response=str(raw or ""), adjudication_valid=valid, rejection_reason="" if valid else "Terminal deadline remained unresolved", causal_resolution=causal, world_dynamics=world_dynamics, hard_constraints=hard_constraints, causal_states=list(getattr(scene, "causal_states", []) or []), active_deadlines=active_deadlines, momentum_gate="free_pass")

    def generate_random_event(self, scene: SceneRecord, participants: Dict[str, str]) -> str:
        """Generate one contextual external event from the authoritative current scene."""
        system = (
            DIRECTOR_AGENT_ROLE + AUDIENCE_PAYOFF_CONTRACT +
            "CONTEXTUAL EVENT INJECTION. Invent ONE significant, immediate external development that belongs naturally to the CURRENT scene as it exists now. "
            "Use the original scenario only for still-active constraints/context; CURRENT REALITY, LIVE USER DIRECTIVES and CURRENT SCENE FRAME are newer authority. If the scene has moved to a new time/place, generate for that new scene rather than dragging old props, rooms or hazards forward. "
            "Prefer an event that adds pressure, opportunity, interruption, discovery, complication, environmental change or peripheral-world action. Do not solve the actors' main problem for them, hand them the exact required solution, or choose either controlled actor's voluntary action. "
            "Never import material from unrelated prior scenes. Never overwrite a live user directive. Return exactly 1-3 concise sentences describing the event and nothing else."
        )
        user = f"""ORIGINAL HUMAN SCENARIO — STILL BINDING WHERE NOT SUPERSEDED:
{scene.initial_prompt}

CURRENT OBJECTIVE SHARED REALITY — PRIMARY EVENT CONTEXT:
{scene.current_reality}

LIVE USER DIRECTIVES — HIGHEST USER AUTHORITY:
{json.dumps(getattr(scene, 'live_directives', []), ensure_ascii=False)}

CURRENT SCENE FRAME:
{json.dumps(getattr(scene, 'scene_frame', {}), ensure_ascii=False)}

WORLD DYNAMICS:
{json.dumps(scene.world_dynamics, ensure_ascii=False)}

HARD CONSTRAINTS:
{json.dumps(getattr(scene, 'hard_constraints', []), ensure_ascii=False)}

CAUSAL STATES:
{json.dumps(getattr(scene, 'causal_states', []), ensure_ascii=False)}

ACTIVE DEADLINES:
{json.dumps(getattr(scene, 'active_deadlines', []), ensure_ascii=False)}

ACTOR STATUS:
{json.dumps(scene.actor_status, ensure_ascii=False)}

PARTICIPANTS:
{self._participant_block(participants)}"""
        raw = self.backend.generate({
            "system": system, "history": [], "user": user,
            "temperature": 0.7, "repeat_penalty": 1.05, "presence_penalty": 0.1,
        })
        text = str(raw or "").strip()
        text = re.sub(r"(?is)^```(?:text)?\s*|\s*```$", "", text).strip()
        if not text:
            raise RuntimeError("Director returned no random event.")
        return text[:1200].strip()

    def apply_human_intervention(self, scene: SceneRecord, intervention: str,
                                 participants: Dict[str, str]) -> DirectorResult:
        names = list(scene.participants)
        system = (
            "You are dunoon daemon's invisible Arena Director. Integrate a HUMAN DIRECTOR intervention into shared reality. "
            "The intervention is authoritative and may deliberately add events, facts, objects or consequences. Preserve it rather than debating it. "
            "Do not convert it into a voluntary choice, thought, emotion, speech, goal or tactic for a persona unless the human explicitly states that completed action as fact. "
            "Keep objective reality separate from actor-relative perceptions. Update or clear active physical commitments only where the human intervention causally changes them. "
            "Re-read the authoritative intervention for WORLD DYNAMICS: preserve or update any established ongoing process or reactive external entity/group whose state can continue changing, without inventing one. "
            "Also update HARD CONSTRAINTS, CAUSAL STATES and ACTIVE DEADLINES structurally. Preserve existing stable ids. An authoritative intervention may satisfy/reverse a causal state, change/deactivate a constraint or replace a deadline state; do not lose unrelated ledger entries. Human intervention itself is authoritative provenance. "
            "Never resurrect an actor already dead unless the human explicitly establishes resurrection. Death should reflect explicit human wording, not inference from danger. Return JSON only."
        )
        user = f"""ORIGINAL HUMAN BASELINE:\n{scene.initial_prompt}\n\nCURRENT SHARED REALITY:\n{scene.current_reality}\n\nCURRENT ACTIVE PHYSICAL COMMITMENTS:\n{json.dumps(scene.active_commitments, ensure_ascii=False)}\n\nCURRENT STATUS:\n{json.dumps(scene.actor_status, ensure_ascii=False)}\n\nAUTHORITATIVE HUMAN INTERVENTION:\n{intervention}\n\nPARTICIPANTS:\n{self._participant_block(participants)}\n\nReturn exactly this shape:\n{self._scene_schema(names)}"""
        raw = self.backend.generate({
            "system": system, "history": [], "user": user,
            "temperature": 0.15, "repeat_penalty": 1.0, "presence_penalty": 0.0,
        })
        data = _extract_json(raw) or {}
        reality = str(data.get("current_reality", "") or "").strip()
        if not reality:
            reality = (scene.current_reality.rstrip() + "\nHuman Director intervention: " + intervention.strip()).strip()
        briefs = _text_map(data.get("actor_briefs"), names, scene.actor_briefs)
        status = _status_map(data.get("actor_status"), names, scene.actor_status)
        commitments = _text_map(data.get("active_commitments"), names, scene.active_commitments)
        world_dynamics = _string_list(data.get("world_dynamics"), scene.world_dynamics)
        hard_constraints = _merge_structured_ledger(getattr(scene, "hard_constraints", []), _dict_list(data.get("hard_constraints"), []))
        causal_states = _merge_structured_ledger(getattr(scene, "causal_states", []), _dict_list(data.get("causal_states"), []), active_key="satisfied")
        active_deadlines = _merge_structured_ledger(getattr(scene, "active_deadlines", []), _dict_list(data.get("active_deadlines"), []), active_key="resolved")
        return DirectorResult(reality, briefs, status, commitments, world_dynamics=world_dynamics, hard_constraints=hard_constraints, causal_states=causal_states, active_deadlines=active_deadlines)
