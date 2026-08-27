from __future__ import annotations

from datetime import datetime

import copy
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from typing import Dict, Optional

from memory_api import save_working_memory  # compatibility import for older tests/tools
from memory_router import route_memory
from .director import ArenaDirector, DirectorResult
from .arena_diagnostics import log_arena_diagnostic
from .scene_store import SceneRecord, SceneStore


@dataclass
class ArenaTurn:
    actor_name: str
    text: str
    scene: SceneRecord
    ended: bool = False
    resolution_pending: bool = False


class ArenaRecoverableError(RuntimeError):
    """A bad candidate generation. Auto may silently retry the same actor."""
    def __init__(self, actor_name: str, message: str):
        super().__init__(message)
        self.actor_name = actor_name


class ArenaEngine:
    """Autonomous two-persona Arena built on one Director-owned SceneRecord."""

    # 🐉 Silver Wyrm: Arena keeps a small set of hard-won invariants in one place:
    # bounded actor budgets, POV quarantine, one-microbeat pacing, decision-space
    # recovery, isolated consequence resolution, and monotonic mortality closure.
    ARENA_BUILD = "08.2.87 SILVER WYRM RELEASE CANDIDATE"

    def __init__(self, brain, session_manager, scene_store: SceneStore | None = None, *, latency_budget: bool = False):
        self.brain = brain
        self.session_manager = session_manager
        self.store = scene_store or SceneStore()
        self.director = ArenaDirector(brain.backend)
        self.scene: Optional[SceneRecord] = None
        self.sessions = []
        self.turn_index = 0
        self.started = False
        self.recoverable_failures = 0
        self.resolution_lock_failures = 0
        # 🐉 Silver Wyrm: POV QUARANTINE: actor prose must pass the cheap semantic HARDLINE
        # boundary before another actor or the Director may use it as evidence. The old
        # latency fast-admission path let unsupported external claims become provisional
        # evidence and then get laundered into shared reality by peer repetition.
        self.latency_budget_enabled = bool(latency_budget)
        self.latency_budget_fast_admission = False
        self.director.latency_budget_enabled = bool(latency_budget)

    def set_block_director_creative_freedom(self, blocked: bool) -> None:
        """Explicit UI brake. False is the normal creative-Director mode."""
        self.director.set_block_creative_freedom(bool(blocked))

    @staticmethod
    def _name(session) -> str:
        return str(getattr(session, "agent_name", "Persona") or "Persona").strip()

    def _participants(self) -> Dict[str, str]:
        out = {}
        for sess in self.sessions:
            name = self._name(sess)
            out[name] = "\n".join(x for x in [
                str(getattr(sess, "system_prompt", "") or "").strip(),
                f"Backstory: {getattr(sess, 'backstory', '') or 'not specified'}",
                f"Physiology: {getattr(sess, 'physiology', '') or 'not specified'}",
                f"Established capabilities: {getattr(sess, 'powers', '') or 'none additionally established'}",
                f"Mortality enabled: {bool(getattr(sess, 'mortality_enabled', False))}",
            ] if x)
        return out

    def _debug(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{stamp}] [ARENA] {message}")

    def start(self, session_a, session_b, scenario: str) -> SceneRecord:
        if not self.brain.backend.is_ready():
            raise RuntimeError("Load a Dunoon Daemon-managed GGUF model before starting Arena.")
        if session_a is session_b or getattr(session_a, "id", None) == getattr(session_b, "id", None):
            raise ValueError("Arena requires two different personas.")
        if getattr(session_a, "is_deceased", False) or getattr(session_b, "is_deceased", False):
            raise ValueError("A persona already marked deceased cannot enter a new Arena.")
        scenario = str(scenario or "").strip()
        if not scenario:
            raise ValueError("Enter an Arena scenario first.")

        self.sessions = [session_a, session_b]
        for sess in self.sessions:
            sess.session_manager = self.session_manager
        names = [self._name(x) for x in self.sessions]
        if names[0].lower() == names[1].lower():
            raise ValueError("Arena personas need distinct display names so authority remains unambiguous.")

        scene_id = f"arena-{uuid.uuid4().hex[:12]}"
        scene = self.director.compile_scene(scene_id, scenario, self._participants())
        scene.active_commitments = {name: str(scene.active_commitments.get(name, "") or "") for name in names}
        scene.commitment_age = {name: 0 for name in names}
        scene.simmer_streak = 0
        scene.mandatory_progress_lock = False
        scene.mandatory_progress_reason = ""
        scene.interaction_thread_key = ""
        scene.interaction_thread_id = ""
        scene.interaction_thread_label = ""
        scene.interaction_thread_progress_reason = ""
        scene.interaction_thread_age = 0
        for sess in self.sessions:
            name = self._name(sess)
            if getattr(sess, "is_deceased", False):
                scene.actor_status[name] = "dead"
            elif bool(getattr(sess, "mortality_enabled", False)) and scene.actor_status.get(name) == "dead":
                sess.is_deceased = True
            else:
                scene.actor_status[name] = "alive"

        self.scene = scene
        self.turn_index = 0
        self.started = True
        self.recoverable_failures = 0
        self.resolution_lock_failures = 0
        self.store.save(scene)
        self._debug(f"scene established · {names[0]} vs {names[1]}")
        if scene.world_dynamics:
            self._debug("world dynamics tracked -> " + " | ".join(scene.world_dynamics))
        if getattr(scene, "hard_constraints", None):
            self._debug(f"hard reality ledger -> {len(scene.hard_constraints)} binding constraint(s)")
        if getattr(scene, "causal_states", None):
            self._debug(f"causal state ledger -> {len(scene.causal_states)} tracked prerequisite/outcome state(s)")
        if getattr(scene, "active_deadlines", None):
            self._debug(f"deadline ledger -> {len(scene.active_deadlines)} active deadline(s)")
        if getattr(scene, "scene_frame", None):
            self._debug("scene director frame -> " + str(scene.scene_frame.get("id", "scene")) + " · " + str(scene.scene_frame.get("status", "active")))
        return scene

    def _living_indices(self):
        if not self.scene:
            return []
        return [i for i, s in enumerate(self.sessions) if self.scene.actor_status.get(self._name(s), "alive") != "dead"]

    def _current_session(self):
        """Choose the next living actor WITHOUT consuming the turn."""
        living = self._living_indices()
        if not living:
            return None, None
        n = len(self.sessions)
        for offset in range(n):
            idx = (self.turn_index + offset) % n
            if idx in living:
                return idx, self.sessions[idx]
        idx = living[0]
        return idx, self.sessions[idx]

    def _commit_turn_advance(self, accepted_index: int) -> None:
        """Turn order changes once, and only after an accepted/committed turn."""
        if self.sessions:
            self.turn_index = (accepted_index + 1) % len(self.sessions)


    def _update_interaction_thread_from_result(self, result: DirectorResult) -> None:
        """Persist Director-declared semantic interaction identity.

        Python owns the counter and identity continuity contract; the Director supplies the
        semantic identity/progress judgment. No action verbs, targets or synonyms are parsed.
        """
        if not self.scene:
            return
        new_id = str(getattr(result, "interaction_id", "") or "").strip()
        label = str(getattr(result, "interaction_label", "") or "").strip()
        material = bool(getattr(result, "interaction_material_progress", False))
        resolved = bool(getattr(result, "interaction_resolved", False))
        reason = str(getattr(result, "interaction_progress_reason", "") or "").strip()
        old_id = str(getattr(self.scene, "interaction_thread_id", "") or getattr(self.scene, "interaction_thread_key", "") or "").strip()

        if resolved:
            self._reset_interaction_thread(reason or "semantic interaction resolved")
            return
        if not new_id:
            # No semantic interaction reported. Preserve an existing unresolved thread rather
            # than letting missing model paperwork silently erase anti-stagnation pressure.
            return
        if new_id == old_id:
            if material:
                self.scene.interaction_thread_age = 0
                self._debug(f"interaction thread progressed -> {label or new_id}; age reset")
            else:
                self.scene.interaction_thread_age = int(getattr(self.scene, "interaction_thread_age", 0) or 0) + 1
                self._debug(f"interaction thread continues -> {label or new_id} age {self.scene.interaction_thread_age}")
        else:
            self.scene.interaction_thread_id = new_id
            self.scene.interaction_thread_key = new_id  # backward-compatible saved-scene field
            self.scene.interaction_thread_label = label
            self.scene.interaction_thread_age = 0 if material else 1
            self._debug(f"interaction thread -> {label or new_id} age {self.scene.interaction_thread_age}")
        self.scene.interaction_thread_progress_reason = reason
        if label:
            self.scene.interaction_thread_label = label

    def _reset_interaction_thread(self, reason: str = "material progress") -> None:
        if not self.scene:
            return
        if int(getattr(self.scene, "interaction_thread_age", 0) or 0):
            self._debug(f"interaction thread resolved/reset -> {reason}")
        self.scene.interaction_thread_key = ""
        self.scene.interaction_thread_id = ""
        self.scene.interaction_thread_label = ""
        self.scene.interaction_thread_progress_reason = ""
        self.scene.interaction_thread_age = 0

    def _update_commitment_age(self, previous: Dict[str, str], result: DirectorResult) -> None:
        if not self.scene:
            return
        ages = dict(getattr(self.scene, "commitment_age", {}) or {})
        new_map = result.active_commitments or {}
        progress_map = dict(getattr(result, "commitment_progress", {}) or {})
        for name in self.scene.participants:
            old = str(previous.get(name, "") or "").strip()
            new = str(new_map.get(name, "") or "").strip()
            if not new:
                ages[name] = 0
            elif not old:
                ages[name] = 1
            elif bool(progress_map.get(name, False)):
                ages[name] = 0
            else:
                ages[name] = int(ages.get(name, 0) or 0) + 1
        self.scene.commitment_age = ages

    @staticmethod
    def _other_label_violation(text: str, other_name: str) -> bool:
        return bool(re.search(rf"(?im)^\s*{re.escape(other_name)}\s*:", str(text or "")))

    @staticmethod
    def _sanitize_actor_prose(text: str, own_name: str = "") -> str:
        out = str(text or "").strip()
        out = re.sub(r"(?im)^\s*\[(?:Arena(?:\s+(?:reality|action))?|Arena action|Arena reality)\]\s*", "", out)
        out = re.sub(r"(?im)^\s*\[Sensory reaction\s*:\s*([^\]]+)\]\s*", lambda m: ((m.group(1).strip()[:1].upper() + m.group(1).strip()[1:]) + ". ") if m.group(1).strip() else "", out)
        out = re.sub(r"(?im)^\s*\[(?:SYSTEM|Director|World authority|Current reality)\]\s*", "", out)
        out = re.sub(r"(?im)^\s*Current\s+scene\s+update\s*:\s*", "", out)
        if own_name:
            out = re.sub(rf"(?i)^\s*{re.escape(own_name)}\s*:\s*", "", out, count=1)
        return re.sub(r"\n{3,}", "\n\n", out).strip()

    def _recent_actor_turns(self, actor_name: str, limit: int = 3):
        if not self.scene:
            return []
        vals = [x.get("text", "") for x in self.scene.log if x.get("kind") == "actor" and x.get("actor") == actor_name]
        return vals[-limit:]

    def _latest_other_actor_turn(self, actor_name: str):
        """Return the most recent accepted POV from the other controlled actor.

        Evidence only: this lets the Director recognise reciprocal causal confirmation
        without creating a second world authority or allowing one actor to puppet another.
        """
        if not self.scene:
            return "", ""
        for item in reversed(self.scene.log):
            if item.get("kind") != "actor":
                continue
            peer = str(item.get("actor", "") or "").strip()
            text = str(item.get("text", "") or "").strip()
            if peer and peer != actor_name and text:
                return peer, text
        return "", ""

    def _settled_facts(self, limit: int = 12):
        """Existing Arena log is the authority ledger; no parallel progress subsystem."""
        if not self.scene:
            return []
        out = []
        for item in self.scene.log:
            if item.get("kind") not in {"causal_resolution", "reciprocal_confirmation"}:
                continue
            text = str(item.get("text", "") or "").strip()
            if text and text not in out:
                out.append(text)
        return out[-limit:]

    def _already_settled(self, fact: str) -> bool:
        fact = str(fact or "").strip()
        if not fact:
            return False
        # Exact identity is deterministic bookkeeping. Semantic equivalence belongs to
        # the primary Director model and its structured state, never a sidecar model.
        return any(fact == old for old in self._settled_facts(limit=24))

    def _repetition_reason(self, actor_name: str, candidate: str) -> str:
        candidate = str(candidate or "").strip()
        if not candidate:
            return ""
        # Catch only byte-for-byte replay locally. Semantic repetition is handled by
        # the Director-owned interaction thread/progress contract.
        for old in self._recent_actor_turns(actor_name):
            if candidate == old:
                return "the draft exactly repeats a recent turn instead of advancing, completing, abandoning or changing the action"
        return ""

    def _authoritative_actor_snapshot(self, actor_name: str) -> dict:
        """Compact latest shared-state feed for one actor generation.

        No English meaning is inferred here. Python only serialises Director-owned structured
        state that already exists in SceneRecord. The primary model interprets it.
        """
        if not self.scene:
            return {}
        active_constraints = [
            dict(item) for item in (getattr(self.scene, "hard_constraints", []) or [])
            if isinstance(item, dict) and bool(item.get("active", True))
        ]
        active_deadlines = [
            dict(item) for item in (getattr(self.scene, "active_deadlines", []) or [])
            if isinstance(item, dict) and not bool(item.get("resolved", False))
        ]
        return {
            "scene_revision": int(getattr(self.scene, "revision", 0) or 0),
            "current_reality": str(getattr(self.scene, "current_reality", "") or "").strip(),
            "your_actor": actor_name,
            "your_status": str((getattr(self.scene, "actor_status", {}) or {}).get(actor_name, "alive") or "alive"),
            "your_current_view": str((getattr(self.scene, "actor_briefs", {}) or {}).get(actor_name, "") or "").strip(),
            "your_unresolved_commitment": str((getattr(self.scene, "active_commitments", {}) or {}).get(actor_name, "") or "").strip(),
            "live_world_dynamics": list(getattr(self.scene, "world_dynamics", []) or []),
            "hard_constraints": active_constraints,
            "causal_states": list(getattr(self.scene, "causal_states", []) or []),
            "active_deadlines": active_deadlines,
            "scene_frame": dict(getattr(self.scene, "scene_frame", {}) or {}),
            "live_user_directives": [dict(x) for x in (getattr(self.scene, "live_directives", []) or []) if isinstance(x, dict) and bool(x.get("active", True))][-12:],
            "settled_shared_facts": self._settled_facts(limit=12),
        }

    def _latest_live_image_path(self):
        for item in reversed(list(getattr(self.scene, "live_directives", []) or [])):
            if not isinstance(item, dict) or not bool(item.get("active", True)):
                continue
            path = str(item.get("image_path", "") or "").strip()
            if path and os.path.exists(path):
                return path
        return None

    def _generate_actor(self, sess, stimulus: str) -> str:
        if not self.scene:
            raise RuntimeError("Arena has no active scene.")
        name = self._name(sess)
        snapshot = self._authoritative_actor_snapshot(name)
        text = self.brain.turn_engine.infer(
            stimulus,
            sess,
            source="arena_peer",
            commit_lifecycle=False,
            scene_baseline=self.scene.initial_prompt,
            scene_reality=self.scene.current_reality,
            actor_brief=self.scene.actor_briefs.get(name, ""),
            actor_commitment=self.scene.active_commitments.get(name, ""),
            scene_dynamics=self.scene.world_dynamics,
            scene_authority_snapshot=snapshot,
            image_path=self._latest_live_image_path(),
        ).strip()
        return self._sanitize_actor_prose(text, name)

    def _rewrite_actor(self, sess, rejected: str, reason: str, attempt: int = 1) -> str:
        name = self._name(sess)
        prompt = (
            f"Your previous candidate Arena turn could not be admitted because {reason}. "
            f"Generate a fresh natural in-character turn as {name}. "
            "Use only the original human scene, current objective reality, your own actor-relative view and your own body/capabilities. "
            "Do not mention this correction. Preserve your actual intention when it is still possible, but remove unsupported props/people/places, invented external conditions, or actor-authored external outcomes. State what you attempt; leave consequential external success/failure and new world facts for the Director. "
            "If you are already in the middle of a concrete physical action, either make real progress, complete it if unobstructed, abandon it, or choose something else. Do not repeat setup forever. "
            "Do not spend the rewrite re-describing already-established sensations or re-arguing for an action already chosen. Compress routine setup and make the beat earn the audience wait. "
            "Return prose only."
        )
        if attempt <= 1:
            prompt += "\n\nRejected draft for context only:\n" + rejected
        prompt += self._pending_guidance_clause(name)
        return self._generate_actor(sess, prompt)

    def _actor_turn(self, sess, retry_reason: str = "") -> str:
        if not self.scene:
            raise RuntimeError("Arena has no active scene.")
        name = self._name(sess)
        other = next(self._name(s) for s in self.sessions if s is not sess)
        if self.scene.actor_status.get(name, "alive") == "dead":
            raise RuntimeError(f"{name} is dead and cannot receive another turn.")
        stimulus = (
            "Take your next Arena turn now. Respond only as yourself to authoritative current reality. "
            "Do not narrate a new voluntary action/dialogue for the other controlled participant. "
            "If you previously began a concrete physical action, you may continue it, abandon it or change course; if you continue it, make concrete progress rather than repeating preparation. "
            "A live audience is waiting through inference latency for this beat. Quiet character moments are welcome, but dead air is not. Do not re-explain sensory facts, urgency, agreement or an intention already established merely to fill the turn. Once you have decided to act, act. Compress routine setup into the same beat while keeping natural, immersive, in-character prose. "
            "Earn the audience wait with meaningful action, reaction, humour, conflict, discovery, relationship change, repositioning, or a consequential choice. You still control only yourself and must leave external outcomes to the Director."
        )
        peer_name, peer_turn = self._latest_other_actor_turn(name)
        live_directives = self._active_live_directives()
        if live_directives:
            directive_text = "\n".join(f"- {str(x.get('text', '') or '').strip()}" for x in live_directives)
            stimulus += (
                "\n\nRECENT HUMAN INTERJECTION / GUIDE YOUR STORY — AUTHORITATIVE LIVE SCENE EDITS, HIGHEST USER AUTHORITY:\n" + directive_text +
                "\nThese are live amendments to the opening scene directive. Treat explicit user-established facts, events, conditions and objects as true now. Do not weaken, delay, reinterpret or replace them. If the user explicitly directs YOUR next voluntary action, that choice is binding for this turn: attempt it immediately if physically possible. You may express your personality in how you do it, but do not refuse, debate, substitute a different tactic, or merely acknowledge the command. Consequential external success/failure remains Director-owned. Newer directives outrank older conflicting ones. The Director may resolve consequences, but may not erase the user's edit."
            )
        own_recent = self._recent_actor_turns(name, limit=2)
        if own_recent:
            stimulus += (
                "\n\nYOUR OWN RECENT ACCEPTED POV — CONTINUITY OF YOURSELF, NOT WORLD AUTHORITY:\n"
                + "\n---\n".join(str(x or "").strip() for x in own_recent if str(x or "").strip())
                + "\nRemember your own voluntary actions, position and what you were already trying to hold/use. "
                  "Do not repeatedly restart or reacquire the same personal action/object unless authoritative current reality says it was lost, unavailable or the attempt failed. "
                  "External success/failure claims in these old POVs remain unverified unless they also appear in authoritative shared reality or settled facts."
            )
        settled = self._settled_facts()
        if settled:
            stimulus += (
                "\n\nSETTLED SHARED FACTS — AUTHORITATIVE, ALREADY HAPPENED:\n- " + "\n- ".join(settled) +
                "\nDo not narrate yourself as being back before these facts unless CURRENT OBJECTIVE REALITY explicitly contains a later event that reversed them."
            )
        if peer_name and peer_turn:
            peer_verified = bool((getattr(self.scene, "provisional_authority_verified", {}) or {}).get(peer_name, False))
            if peer_verified:
                stimulus += (
                    f"\n\nPROVISIONAL OTHER-ACTOR POV ({peer_name}) — PASSED AUTHORITY GATE; STILL NOT OBJECTIVE REALITY:\n{peer_turn}\n"
                    "You may react to the other actor's admitted speech/action/subjective experience, but consequential external results remain Director-owned until resolved. "
                    "EXPERIMENT HOLD: if the other actor is probing, testing, touching, forcing, activating, entering, crossing, striking, or otherwise trying to discover how unresolved external reality responds, do NOT supply, confirm, strengthen, quantify, or elaborate the world's reaction from their POV. You may react to the attempt itself and take your own defensive/voluntary action, but leave the external result unresolved until the Director settles it after this pair. "
                    "Your own independent observation may confirm an already-authoritative external event, but it must not bootstrap a new result from the other actor's provisional experiment. It must not bootstrap a new result from the other actor's unverified experiment either; unverified raw prose is quarantined entirely."
                )
            else:
                stimulus += (
                    f"\n\nPROVISIONAL OTHER-ACTOR POV ({peer_name}) IS QUARANTINED. "
                    "Its raw prose is deliberately withheld because the authority gate did not verify it. "
                    "Do not infer, repeat, confirm or elaborate any new external fact from that turn. Respond only to authoritative shared reality and your own actor state."
                )
        if retry_reason:
            stimulus += f"\nA previous draft was not admitted. Quietly correct this issue: {retry_reason}"
        # Recency matters to local models. Put any not-yet-answered human guidance at the
        # absolute end of the actor stimulus so later continuity material cannot dilute it.
        stimulus += self._pending_guidance_clause(name)
        text = self._generate_actor(sess, stimulus)
        if self._other_label_violation(text, other):
            reason = f"it used {other}'s speaker label and attempted to write the other participant's turn"
            log_arena_diagnostic(
                "actor_draft_rejected", actor=name, rejection_stage="speaker_label",
                candidate=text, rejection_reason=reason,
            )
            text = self._rewrite_actor(sess, text, reason)
        reason = self._repetition_reason(name, text)
        if reason:
            log_arena_diagnostic(
                "actor_draft_rejected", actor=name, rejection_stage="repetition",
                candidate=text, rejection_reason=reason,
            )
            text = self._rewrite_actor(sess, text, reason)
        if text.startswith("(Native model backend unavailable"):
            # Backend loss is not a bad actor draft; Auto must stop rather than retry forever.
            raise RuntimeError(text)
        if not text:
            reason = f"{name} returned no usable prose."
            log_arena_diagnostic(
                "actor_draft_rejected", actor=name, rejection_stage="empty_generation",
                candidate=text, rejection_reason=reason,
            )
            raise ArenaRecoverableError(name, reason)
        return text

    def _death_supported(self, name: str, result: DirectorResult, candidate: str = "") -> bool:
        """Mortality is accepted only from structured Director semantics, never prose scanning."""
        evidence = str((result.death_evidence or {}).get(name, "") or "").strip()
        proposed = str((result.actor_status or {}).get(name, "") or "").strip().lower()
        # Structured death_evidence is itself an explicit Director verdict. Accept it even
        # if the model inconsistently leaves actor_status as alive in the same JSON.
        return bool(evidence) and proposed in {"alive", "dead", ""}

    def _merge_status(self, result: DirectorResult, candidate: str = "") -> None:
        if not self.scene:
            return
        for sess in self.sessions:
            name = self._name(sess)
            old = self.scene.actor_status.get(name, "alive")
            proposed = str(result.actor_status.get(name, old) or old).lower()
            # 🐉 Silver Wyrm: STATE SEAL: persistent persona death is monotonic. Scene-local model
            # output can confirm death, but no later Director pass may silently revive it.
            if old == "dead" or bool(getattr(sess, "is_deceased", False)):
                self.scene.actor_status[name] = "dead"
                sess.is_deceased = True
                self.scene.active_commitments[name] = ""
                self.scene.provisional_povs.pop(name, None)
                self.scene.provisional_authority_verified.pop(name, None)
            elif bool(getattr(sess, "mortality_enabled", False)) and self._death_supported(name, result):
                self.scene.actor_status[name] = "dead"
                sess.is_deceased = True
                self.scene.active_commitments[name] = ""
                self.scene.provisional_povs.pop(name, None)
                self.scene.provisional_authority_verified.pop(name, None)
                self._debug(f"mortality committed -> {name} deceased; removed from turn rotation")
            else:
                self.scene.actor_status[name] = "alive"

    def _active_live_directives(self, limit: int = 12):
        """Exact user-authored live scene edits, highest semantic authority after engine safety."""
        if not self.scene:
            return []
        out = []
        for item in (getattr(self.scene, "live_directives", []) or []):
            if not isinstance(item, dict) or not bool(item.get("active", True)):
                continue
            text = str(item.get("text", "") or "").strip()
            if text:
                out.append(dict(item))
        return out[-max(1, int(limit or 12)):]

    def _latest_human_input(self):
        """Compatibility helper returning the newest authoritative live guidance text."""
        directives = self._active_live_directives(limit=1)
        return str(directives[-1].get("text", "") or "").strip() if directives else ""

    def _pending_guidance_for_actor(self, actor_name: str):
        """Newest user guidance this actor has not yet visibly answered."""
        if not self.scene:
            return None
        name = str(actor_name or "").strip()
        for item in reversed(list(getattr(self.scene, "live_directives", []) or [])):
            if not isinstance(item, dict) or not bool(item.get("active", True)):
                continue
            if str(item.get("kind", "") or "").strip().lower() != "guidance":
                continue
            acknowledged = {str(x or "").strip() for x in (item.get("acknowledged_by", []) or [])}
            if name and name not in acknowledged:
                return item
        return None

    def _pending_guidance_clause(self, actor_name: str) -> str:
        item = self._pending_guidance_for_actor(actor_name)
        if not item:
            return ""
        text = str(item.get("text", "") or "").strip()
        if not text:
            return ""
        return (
            "\n\nLATEST HUMAN GUIDANCE — IMMEDIATE HIGHEST-PRIORITY STEERING FOR YOUR NEXT TURN:\n" + text +
            "\nThis is newer than every transcript beat, prior intention, and older guidance. If it explicitly tells YOU to take a voluntary action now, the user has chosen that action for this turn: attempt it immediately if physically possible. "
            "Do not refuse, debate, substitute another tactic, postpone it for atmosphere, merely acknowledge it, or repeat your previous plan instead. Your personality still controls voice, emotion and manner of execution. "
            "If authoritative physical reality makes literal execution impossible, attempt as far as possible or react explicitly to the concrete blocking fact rather than ignoring the instruction. "
            "Consequential external outcomes remain Director-owned; a user command to attack/escape/use an object binds the attempt, not an unearned success result."
        )

    def _acknowledge_guidance_for_actor(self, actor_name: str) -> None:
        """Mark the newest pending guidance answered only after an actor turn is admitted."""
        item = self._pending_guidance_for_actor(actor_name)
        if not item:
            return
        acknowledged = [str(x or "").strip() for x in (item.get("acknowledged_by", []) or []) if str(x or "").strip()]
        name = str(actor_name or "").strip()
        if name and name not in acknowledged:
            acknowledged.append(name)
            item["acknowledged_by"] = acknowledged

    def _persist_experience(self, speaker, reply: str) -> None:
        """Persist the actor's experience without copying Director/control prose into character history."""
        try:
            speaker.append_roxie(reply)
            route_memory(reply, session=speaker, is_user=False)
        except Exception:
            pass
        try:
            self.session_manager._save()
        except Exception:
            pass

    def _admit_candidate(self, sess, name: str, reply: str, progress=None):
        """Hard boundary only. No world resolution occurs here."""
        candidate = reply
        last_reason = ""
        for attempt in range(3):
            if progress:
                progress("director", name)
            gate = self.director.admit_candidate(self.scene, name, candidate, self._participants())
            log_arena_diagnostic(
                "hardline_admission", actor=name, candidate=candidate, admitted=bool(gate.admitted),
                rejection_reason=gate.reason, raw_director=gate.raw_response,
                adjudication_valid=bool(gate.valid), backend_finish_reason=gate.backend_finish_reason,
            )
            if not gate.valid:
                # 🐉 Silver Wyrm: malformed bouncer paperwork cannot deadlock a sane actor turn.
                # Deterministic speaker-label/protocol sanitation has already run; a valid future gate can still reject hard violations.
                self._debug(f"hardline gate unusable for {name}; fail-open actor POV preserved as UNVERIFIED external evidence")
                self.scene.provisional_authority_verified[name] = False
                return candidate
            if gate.admitted:
                self.scene.provisional_authority_verified[name] = True
                if attempt:
                    self._debug(f"{name} admitted after silent rewrite #{attempt}")
                return candidate
            last_reason = gate.reason or "candidate crossed a hard Arena authority boundary"
            self._debug(f"admission rejected {name}: {last_reason}")
            if progress:
                progress("retry", name)
            candidate = self._rewrite_actor(sess, candidate, last_reason, attempt=attempt + 1)
            if not candidate:
                break
        raise ArenaRecoverableError(name, last_reason or "candidate could not be admitted")

    def _pending_pair_complete(self) -> bool:
        if not self.scene:
            return False
        pending = dict(getattr(self.scene, "provisional_povs", {}) or {})
        return bool(self.scene.participants) and all(str(pending.get(name, "") or "").strip() for name in self.scene.participants)

    def _director_safe_pending_povs(self, pending: Dict[str, str]) -> Dict[str, str]:
        """Return only authority-verified POV prose to world-resolution calls.

        Verification is structured state produced by the primary Director gate. Python
        does not inspect English meaning here. If a gate is unusable, the visible actor
        turn may remain in the transcript, but its raw prose cannot become world evidence.
        """
        verified = dict(getattr(self.scene, "provisional_authority_verified", {}) or {}) if self.scene else {}
        safe = {}
        for name in (self.scene.participants if self.scene else pending.keys()):
            text = str(pending.get(name, "") or "").strip()
            if text and bool(verified.get(name, False)):
                safe[name] = text
            elif text:
                safe[name] = "[POV QUARANTINED: authority gate did not verify this actor turn; do not use it as external evidence.]"
            else:
                safe[name] = ""
        return safe

    def _resolution_due(self) -> tuple[bool, bool]:
        """Return (due, contested_due) from the one existing commitment-age mechanism."""
        if not self.scene:
            return False, False
        commitments = self.scene.active_commitments or {}
        ages = self.scene.commitment_age or {}
        aged = [
            name for name in self.scene.participants
            if str(commitments.get(name, "") or "").strip() and int(ages.get(name, 0) or 0) >= 2
        ]
        return bool(aged), len(aged) >= 2

    def _resolution_lock_active(self) -> bool:
        due, _ = self._resolution_due()
        hard_progress = bool(getattr(self.scene, "mandatory_progress_lock", False)) if self.scene else False
        return (due or hard_progress) and self._pending_pair_complete()

    def _resolve_pending_exchange(self, trigger_actor: str, progress=None):
        """Resolve only after both controlled actors have admissible provisional POVs."""
        if not self.scene:
            return None
        pending = dict(getattr(self.scene, "provisional_povs", {}) or {})
        if any(not str(pending.get(name, "") or "").strip() for name in self.scene.participants):
            return None
        director_povs = self._director_safe_pending_povs(pending)
        if progress:
            progress("director", trigger_actor)
        due, contested_due = self._resolution_due()
        if contested_due:
            self._debug("contested commitment deadlock due -> Director must crystallise an outcome")
        old_reality = self.scene.current_reality
        previous_commitments = dict(self.scene.active_commitments or {})
        previous_status = dict(self.scene.actor_status or {})
        previous_world_dynamics = list(self.scene.world_dynamics or [])
        previous_hard_constraints = copy.deepcopy(getattr(self.scene, "hard_constraints", []) or [])
        previous_causal_states = copy.deepcopy(getattr(self.scene, "causal_states", []) or [])
        previous_active_deadlines = copy.deepcopy(getattr(self.scene, "active_deadlines", []) or [])

        def _normalise_due_result(candidate):
            # Novelty lock is part of the due-outcome contract too: an old threshold cannot
            # satisfy a new overdue causal resolution merely by being paraphrased.
            if candidate.causal_resolution and self._already_settled(candidate.causal_resolution):
                self._debug(f"novelty lock suppressed repeated causal resolution -> {candidate.causal_resolution}")
                candidate.causal_resolution = ""
            if candidate.reciprocal_confirmation and self._already_settled(candidate.reciprocal_confirmation):
                self._debug(f"novelty lock suppressed repeated reciprocal confirmation -> {candidate.reciprocal_confirmation}")
                candidate.reciprocal_confirmation = ""
            return candidate

        def _due_outcome_materialised(candidate):
            """A due result must semantically advance the due commitment.

            Meaning comes from structured Director commitment_progress, not word overlap.
            """
            if not due:
                return (
                    str(candidate.current_reality or "").strip() != str(old_reality or "").strip()
                    or dict(candidate.active_commitments or {}) != previous_commitments
                    or dict(candidate.actor_status or {}) != previous_status
                )
            due_names = [
                n for n in self.scene.participants
                if str(previous_commitments.get(n, "") or "").strip()
                and int((self.scene.commitment_age or {}).get(n, 0) or 0) >= 2
            ]
            progress_map = dict(getattr(candidate, "commitment_progress", {}) or {})
            after_commitments = dict(candidate.active_commitments or {})
            after_status = dict(candidate.actor_status or {})
            for due_name in due_names:
                if bool(progress_map.get(due_name, False)):
                    return True
                if str(after_status.get(due_name, "") or "") != str(previous_status.get(due_name, "") or ""):
                    return True
                if str(after_commitments.get(due_name, "") or "").strip() != str(previous_commitments.get(due_name, "") or "").strip():
                    return True
            return False

        # 🐉 Silver Wyrm: DIRECTOR SIMMER: routine exchanges get a compact continuity pass.
        # Heavy adjudication is reserved for due outcomes or when the semantic Director
        # explicitly flags a genuine consequential conflict/threshold.
        thread_due = int(getattr(self.scene, "interaction_thread_age", 0) or 0) >= 4
        # 🐉 Silver Wyrm: PACING CLAMP: one routine SIMMER beat is the entire grace period.
        # If the next actor pair still does not create material progress, force Director
        # initiative immediately instead of tolerating a second microbeat. Persistent
        # interaction-thread protection remains as a separate backstop.
        initiative_forced = (
            not bool(getattr(self.director, "block_creative_freedom", False))
            and (int(getattr(self.scene, "simmer_streak", 0) or 0) >= 1 or thread_due or bool(getattr(self.scene, "mandatory_progress_lock", False)))
        )
        if initiative_forced:
            if thread_due:
                self._debug(f"Director interaction-thread override -> {self.scene.interaction_thread_label or self.scene.interaction_thread_key} age {self.scene.interaction_thread_age}")
            else:
                self._debug(f"Director world initiative override -> SIMMER streak {int(getattr(self.scene, 'simmer_streak', 0) or 0)}")
            log_arena_diagnostic(
                "director_world_initiative", actor=trigger_actor, provisional_povs=pending,
                simmer_streak=int(getattr(self.scene, "simmer_streak", 0) or 0), resolution_due=due,
            )
            # 🐉 Silver Wyrm: GOBLIN RECOVERY: once anti-stagnation has escalated to a
            # mandatory initiative, JSON repair is no longer optional latency polish.
            # The overnight 5090/4090/5060 runs proved that releasing the actor pair
            # after malformed Director paperwork can create hundreds of equivalent
            # turns while SIMMER pressure climbs forever. Spend one bounded structured
            # repair here before considering the initiative failed.
            result = self.director.resolve_exchange(
                self.scene, director_povs, self._participants(), force_resolution=False,
                allow_json_repair=True, initiative=True,
            )
            result.momentum_gate = "free_pass"
            # 🐉 Silver Wyrm: NO-NULL OVERRIDE: initiative is an anti-stagnation obligation, not
            # merely a valid JSON obligation. A syntactically valid initiative that reports
            # no material progress/resolution is the same failure as invalid paperwork.
            # 🐉 Silver Wyrm: THE SHOW MUST GO ON: structured progress can be expressed in
            # more than the interaction bookkeeping flags. A non-empty causal_resolution,
            # explicit state change, or scene transition is already the primary model
            # semantically declaring that the world changed. Do not throw that progress
            # away merely because interaction.material_progress was omitted/false.
            # 🐉 Silver Wyrm: DECISION-SPACE FLOOR: a forced initiative cannot satisfy
            # anti-stagnation merely by filling causal_resolution with decorative motion.
            # The primary Director already returns structured semantic progress flags;
            # Python trusts those flags/state transitions and does not inspect English.
            initiative_material = bool(
                getattr(result, "interaction_material_progress", False)
                or getattr(result, "interaction_resolved", False)
                or list(getattr(result, "state_changes", []) or [])
                or bool((getattr(result, "scene_transition", {}) or {}).get("occurred", False))
                or dict(getattr(result, "actor_status", {}) or {}) != previous_status
                or any(str(v or "").strip() for v in dict(getattr(result, "death_evidence", {}) or {}).values())
            )
            if not getattr(result, "adjudication_valid", True) or not initiative_material:
                if not getattr(result, "adjudication_valid", True):
                    self._debug("Director initiative JSON invalid -> mandatory progress recovery")
                else:
                    self._debug("Director initiative produced no material progress -> mandatory progress recovery")
                log_arena_diagnostic(
                    "director_world_initiative_recovery", actor=trigger_actor, provisional_povs=pending,
                    simmer_streak=int(getattr(self.scene, "simmer_streak", 0) or 0),
                    prior_raw_director=getattr(result, "raw_response", ""),
                    initiative_material=initiative_material,
                )
                # 🐉 Silver Wyrm: mandatory progress outranks the normal one-call latency
                # ceiling. Use one tightly bounded plain-text recovery candidate plus
                # primary-model semantic validation. This is still a single-brain path:
                # no Python vocabulary inference and no sidecar model.
                # 🐉 Silver Wyrm: at mandatory-progress pressure, latency is no longer the
                # governing objective. Spend the bridge's full bounded attempt budget.
                # Three short candidates are preferable to another actor pair describing
                # the same unresolved state for minutes or hours.
                if bool(getattr(self, "latency_budget_enabled", False)):
                    self._debug("THE SHOW MUST GO ON -> mandatory progress gets full bounded continuity recovery")
                result = self.director.emergency_continuity_bridge(
                    self.scene, director_povs, self._participants(), require_novel_external=True,
                    max_attempts=3,
                )
                if getattr(result, "adjudication_valid", True):
                    self._debug(f"[DIRECTOR INITIATIVE RECOVERY] -> {result.causal_resolution}")
                else:
                    self._debug("[DIRECTOR INITIATIVE RECOVERY] exhausted without material progress -> HARD CONSEQUENCE LOCK")
                    hard_lock = getattr(self.director, "hard_consequence_lock", None)
                    if callable(hard_lock):
                        result = hard_lock(self.scene, director_povs, self._participants(), max_attempts=5)
                        if getattr(result, "adjudication_valid", True):
                            self._debug(f"THE SHOW MUST GO OOOOOOOOON -> {result.causal_resolution}")
                        else:
                            self.scene.mandatory_progress_lock = True
                            self.scene.mandatory_progress_reason = result.rejection_reason or "mandatory consequence pending"
                            self._debug("HARD CONSEQUENCE LOCK retained -> actors remain frozen")
        else:
            # 🐉 Silver Wyrm: SCENE MOMENTUM GATE: even when a commitment is due, let the
            # semantic Director ask the governing question first: does accepting this
            # progress the scene without breaking established reality or actor authority?
            # FREE PASS can crystallise an obvious uncontested threshold immediately.
            result = self.director.simmer_exchange(self.scene, director_povs, self._participants())
            # 🐉 Silver Wyrm: malformed SIMMER paperwork must not strand admitted POVs for
            # multiple actor turns. Recover in this resolver cycle. Once one continuity
            # SIMMER has already occurred, malformed output is treated as anti-stagnation
            # pressure and the recovery must attempt a concrete grounded world beat.
            if not getattr(result, "adjudication_valid", True):
                require_novel = int(getattr(self.scene, "simmer_streak", 0) or 0) >= 1 and not bool(getattr(self.director, "block_creative_freedom", False))
                self._debug("Director SIMMER JSON invalid -> same-cycle continuity recovery" + (" with grounded initiative pressure" if require_novel else ""))
                log_arena_diagnostic(
                    "director_simmer_same_cycle_recovery", actor=trigger_actor, provisional_povs=pending,
                    simmer_streak=int(getattr(self.scene, "simmer_streak", 0) or 0),
                    require_novel_external=require_novel, prior_raw_director=getattr(result, "raw_response", ""),
                )
                if bool(getattr(self, "latency_budget_enabled", False)):
                    self._debug("latency budget -> no same-cycle SIMMER recovery call; canon preserved")
                else:
                    result = self.director.emergency_continuity_bridge(
                        self.scene, director_povs, self._participants(), require_novel_external=require_novel
                    )
                    if not require_novel:
                        result.momentum_gate = "simmer"
                    self._debug(f"[DIRECTOR SIMMER RECOVERY] -> {result.causal_resolution}")
            gate = str(getattr(result, "momentum_gate", "simmer") or "simmer").strip().lower()
            if gate == "free_pass" and getattr(result, "adjudication_valid", True):
                self._debug("Director FREE PASS -> scene progress accepted")
                log_arena_diagnostic(
                    "director_free_pass", actor=trigger_actor, provisional_povs=pending,
                    resolution_due=due, causal_resolution=result.causal_resolution, raw_director=result.raw_response,
                )
            elif getattr(result, "strict_resolution_required", False) or gate == "strict":
                self._debug("Director momentum gate -> STRICT adjudication required")
                log_arena_diagnostic(
                    "director_simmer_escalate", actor=trigger_actor, provisional_povs=pending,
                    raw_director=result.raw_response,
                )
                result = self.director.resolve_exchange(
                    self.scene, director_povs, self._participants(), force_resolution=due,
                    allow_json_repair=False,
                )
            elif getattr(result, "adjudication_valid", True):
                self._debug("Director momentum gate -> SIMMER continuity")
        result = _normalise_due_result(result)
        log_arena_diagnostic(
            "exchange_resolution", actor=trigger_actor, provisional_povs=pending, resolution_due=due, contested_deadlock=contested_due,
            causal_resolution=result.causal_resolution, reciprocal_confirmation=result.reciprocal_confirmation,
            raw_director=result.raw_response, adjudication_valid=bool(getattr(result, "adjudication_valid", True)),
            backend_finish_reason=str(getattr(result, "backend_finish_reason", "") or ""),
        )

        # 🐉 Silver Wyrm: DUE MEANS DUE. A syntactically valid Director response is not enough
        # when the causal contract has matured. If it omits a NEW materialised outcome,
        # give the Director one strict consequence-only repair on the same admitted POVs.
        # Never rewrite either actor for Director procrastination.
        if due and (not getattr(result, "adjudication_valid", True) or not _due_outcome_materialised(result)):
            reason = "invalid Director resolution" if not getattr(result, "adjudication_valid", True) else "due causal outcome omitted"
            self._debug(f"{reason} -> one strict Director-only consequence repair")
            log_arena_diagnostic(
                "due_resolution_retry", actor=trigger_actor, provisional_povs=pending, resolution_due=True,
                retry_reason=reason, prior_causal_resolution=result.causal_resolution,
                prior_reciprocal_confirmation=result.reciprocal_confirmation, prior_raw_director=result.raw_response,
            )
            repaired = self.director.resolve_exchange(
                self.scene, director_povs, self._participants(), force_resolution=True, strict_due=True,
                allow_json_repair=False,
            )
            result = _normalise_due_result(repaired)
            log_arena_diagnostic(
                "due_resolution_repair", actor=trigger_actor, provisional_povs=pending, resolution_due=True,
                causal_resolution=result.causal_resolution, reciprocal_confirmation=result.reciprocal_confirmation,
                raw_director=result.raw_response, adjudication_valid=bool(getattr(result, "adjudication_valid", True)),
                backend_finish_reason=str(getattr(result, "backend_finish_reason", "") or ""),
            )
            if not getattr(result, "adjudication_valid", True) or not _due_outcome_materialised(result):
                if bool(getattr(self, "latency_budget_enabled", False)):
                    # 🐉 Silver Wyrm: HARD CONSEQUENCE LOCK: once a due outcome has survived the
                    # normal strict repair, latency loses jurisdiction. Do not hand the same
                    # unresolved beat back to the actors. Ask the primary Director for one
                    # tiny completed consequence and keep the scheduler frozen if even that
                    # transport/protocol path cannot answer.
                    self._debug("strict consequence repair failed -> HARD CONSEQUENCE LOCK; latency overruled")
                    result = self.director.hard_consequence_lock(
                        self.scene, director_povs, self._participants(), max_attempts=5
                    )
                    if getattr(result, "adjudication_valid", True):
                        result = _normalise_due_result(result)
                        self._debug(f"THE SHOW MUST GO OOOOOOOOON -> {result.causal_resolution}")
                    else:
                        self.scene.mandatory_progress_lock = True
                        self.scene.mandatory_progress_reason = result.rejection_reason or "due consequence pending"
                        log_arena_diagnostic(
                            "hard_consequence_lock_retained", actor=trigger_actor, provisional_povs=pending, resolution_due=True,
                            prior_raw_director=getattr(result, "raw_response", ""),
                        )
                else:
                    self._debug("strict consequence repair failed -> semantic narrow consequence fallback")
                    log_arena_diagnostic(
                        "due_resolution_narrow_fallback", actor=trigger_actor, provisional_povs=pending, resolution_due=True,
                        prior_raw_director=getattr(result, "raw_response", ""),
                    )
                    fallback = self.director.narrow_due_fallback(self.scene, director_povs, self._participants())
                    if fallback is not None:
                        result = _normalise_due_result(fallback)
                    if fallback is None or not _due_outcome_materialised(result):
                        self._debug("narrow causal fallback failed -> emergency continuity bridge; show goes on")
                        log_arena_diagnostic(
                            "director_emergency_continuity", actor=trigger_actor, provisional_povs=pending,
                            resolution_due=True, prior_raw_director=getattr(result, "raw_response", ""),
                        )
                        result = self.director.emergency_continuity_bridge(self.scene, director_povs, self._participants(), require_novel_external=initiative_forced)
                        self._debug(f"[DIRECTOR RECOVERY] continuity bridge -> {result.causal_resolution}")


        # 🐉 Silver Wyrm: HARD REALITY LOCK: the primary Director model reports deadline semantics
        # structurally. Python never parses English meaning; it only refuses to let an
        # explicitly reported terminal state drift onward unresolved.
        candidate_deadlines = list(getattr(result, "active_deadlines", None) or previous_active_deadlines or [])
        terminal_due = [d for d in candidate_deadlines if isinstance(d, dict) and bool(d.get("terminal_reached", False)) and not bool(d.get("resolved", False))]
        if getattr(result, "adjudication_valid", True) and terminal_due:
            self._debug("terminal deadline reached -> mandatory consequence resolution")
            terminal_scene = copy.deepcopy(self.scene)
            terminal_scene.current_reality = result.current_reality
            terminal_scene.actor_briefs = dict(result.actor_briefs or self.scene.actor_briefs)
            terminal_scene.actor_status = dict(result.actor_status or self.scene.actor_status)
            terminal_scene.active_commitments = dict(result.active_commitments or self.scene.active_commitments)
            terminal_scene.world_dynamics = list(getattr(result, "world_dynamics", None) or self.scene.world_dynamics or [])
            terminal_scene.hard_constraints = list(getattr(result, "hard_constraints", None) or previous_hard_constraints or [])
            terminal_scene.causal_states = list(getattr(result, "causal_states", None) or previous_causal_states or [])
            terminal_scene.active_deadlines = candidate_deadlines
            terminal_scene.scene_frame = dict(getattr(result, "scene_frame", {}) or getattr(self.scene, "scene_frame", {}) or {})
            terminal_result = self.director.resolve_terminal_deadline(terminal_scene, self._participants())
            if getattr(terminal_result, "adjudication_valid", True):
                result = terminal_result
                self._debug(f"terminal consequence -> {result.causal_resolution}")
            else:
                # Persist the structural terminal fact so the next Arena step cannot forget
                # that the boundary has been reached. No actor is allowed to wash it away.
                self.scene.current_reality = terminal_scene.current_reality
                self.scene.world_dynamics = terminal_scene.world_dynamics
                self.scene.hard_constraints = terminal_scene.hard_constraints
                self.scene.causal_states = terminal_scene.causal_states
                self.scene.active_deadlines = terminal_scene.active_deadlines
                self.scene.scene_frame = dict(getattr(terminal_scene, "scene_frame", {}) or {})
                self.scene.add_log("terminal_pending", terminal_result.rejection_reason or "terminal consequence pending", actor="Director")
                self.store.save(self.scene)
                self._debug("terminal consequence resolution failed -> terminal pressure retained")
                return None

        if not getattr(result, "adjudication_valid", True):
            self._debug(f"world resolution deferred: {result.rejection_reason}")
            self.scene.add_log("director_deferred", result.rejection_reason or "world resolution deferred", actor="Director")
            if bool(getattr(self.scene, "mandatory_progress_lock", False)):
                # 🐉 Silver Wyrm: confirmed stagnation owns scheduler authority. Keep the admitted
                # witness pair intact so the very next step is Director-only. Actors cannot
                # generate another brace/hold cycle while reality is unchanged.
                self._debug("HARD CONSEQUENCE LOCK -> provisional POVs retained; actor scheduler frozen")
            elif bool(getattr(self, "latency_budget_enabled", False)) and not due:
                self.scene.provisional_povs = {}
                self.scene.provisional_authority_verified = {}
                self.scene.simmer_streak = int(getattr(self.scene, "simmer_streak", 0) or 0) + 1
                self._debug(f"latency budget release -> provisional POVs cleared; SIMMER pressure {self.scene.simmer_streak}")
            return None


        gate_now = str(getattr(result, "momentum_gate", "simmer") or "simmer").strip().lower()
        structured_material = bool(
            str(getattr(result, "causal_resolution", "") or "").strip()
            or list(getattr(result, "state_changes", []) or [])
            or bool((getattr(result, "scene_transition", {}) or {}).get("occurred", False))
            or getattr(result, "interaction_material_progress", False)
            or getattr(result, "interaction_resolved", False)
            or dict(getattr(result, "actor_status", {}) or {}) != previous_status
            or any(str(v or "").strip() for v in dict(getattr(result, "death_evidence", {}) or {}).values())
        )
        if bool(getattr(self.scene, "mandatory_progress_lock", False)) and gate_now != "simmer" and structured_material:
            self.scene.mandatory_progress_lock = False
            self.scene.mandatory_progress_reason = ""
            self._debug("HARD CONSEQUENCE LOCK satisfied -> actor scheduler may resume")
        self._update_interaction_thread_from_result(result)

        # A SIMMER-labelled result is continuity by definition, including same-cycle
        # malformed-JSON recovery text. Do not let explanatory continuity prose reset
        # anti-stagnation pressure merely because causal_resolution is non-empty.
        continuity_only = gate_now == "simmer"
        if continuity_only:
            self.scene.simmer_streak = int(getattr(self.scene, "simmer_streak", 0) or 0) + 1
            self._debug(f"Director SIMMER streak -> {self.scene.simmer_streak}")
        else:
            if int(getattr(self.scene, "simmer_streak", 0) or 0):
                self._debug("Director SIMMER streak reset -> 0")
            self.scene.simmer_streak = 0

        self._resolving_actor = trigger_actor
        self.scene.current_reality = result.current_reality
        self.scene.actor_briefs = result.actor_briefs
        self.scene.active_commitments = result.active_commitments or dict(self.scene.active_commitments)
        self.scene.world_dynamics = list(getattr(result, "world_dynamics", None) or self.scene.world_dynamics or [])
        self.scene.hard_constraints = list(getattr(result, "hard_constraints", None) or previous_hard_constraints or [])
        self.scene.causal_states = list(getattr(result, "causal_states", None) or previous_causal_states or [])
        self.scene.active_deadlines = list(getattr(result, "active_deadlines", None) or previous_active_deadlines or [])
        result_frame = dict(getattr(result, "scene_frame", {}) or {})
        if result_frame:
            self.scene.scene_frame = result_frame
        transition = dict(getattr(result, "scene_transition", {}) or {})
        if bool(transition.get("occurred", False)) and isinstance(transition.get("new_scene"), dict) and transition.get("new_scene"):
            old_frame = dict(getattr(self.scene, "scene_frame", {}) or {})
            new_frame = dict(transition.get("new_scene") or {})
            new_frame.setdefault("status", "active")
            self.scene.scene_frame = new_frame
            reason = str(transition.get("reason", "") or "scene resolved").strip()
            self.scene.add_log("scene_transition", reason, actor="Director")
            self._debug(f"scene transition -> {old_frame.get('id', 'scene')} -> {new_frame.get('id', 'next scene')} · {reason}")
        self._update_commitment_age(previous_commitments, result)
        if getattr(result, "continuity_recovery", False):
            # The emergency bridge keeps canon safe by preserving unresolved commitments,
            # but releases resolution pressure so actors regain the floor instead of looping
            # immediately back into Resolution Lock.
            for n in self.scene.participants:
                if str((self.scene.active_commitments or {}).get(n, "") or "").strip():
                    self.scene.commitment_age[n] = 0
            self.scene.add_log("director_recovery", result.causal_resolution or "emergency continuity bridge", actor="Director")
            log_arena_diagnostic(
                "director_emergency_continuity_committed", actor=trigger_actor,
                causal_resolution=result.causal_resolution, commitment_age=dict(self.scene.commitment_age or {}),
            )
        combined = "\n".join(str(pending.get(n, "") or "") for n in self.scene.participants)
        mortality_hits = {n: str(v or "").strip() for n, v in dict(getattr(result, "death_evidence", {}) or {}).items() if str(v or "").strip()}
        if mortality_hits:
            self._debug("mortality closure evidence -> " + " | ".join(f"{n}: {v}" for n, v in mortality_hits.items()))
        self._merge_status(result, combined)
        try:
            self.session_manager._save()
        except Exception:
            pass
        self.scene.provisional_povs = {}
        self.scene.provisional_authority_verified = {}
        self.scene.add_log("director", self.scene.current_reality)
        if result.reciprocal_confirmation:
            self.scene.add_log("reciprocal_confirmation", result.reciprocal_confirmation, actor="Director")
            self._debug(f"reciprocal confirmation -> {result.reciprocal_confirmation}")
        if result.causal_resolution and not getattr(result, "continuity_recovery", False):
            self.scene.add_log("causal_resolution", result.causal_resolution, actor="Director")
            self._debug(f"causal resolution -> {result.causal_resolution}")
        elif result.causal_resolution and getattr(result, "continuity_recovery", False):
            self._debug(f"Director recovery beat -> {result.causal_resolution}")
        if previous_world_dynamics != self.scene.world_dynamics:
            self._debug("world dynamics updated -> " + (" | ".join(self.scene.world_dynamics) if self.scene.world_dynamics else "none active"))
        if previous_hard_constraints != self.scene.hard_constraints:
            self._debug("hard reality ledger updated")
        if previous_causal_states != self.scene.causal_states:
            self._debug("causal state ledger updated")
        if previous_active_deadlines != self.scene.active_deadlines:
            self._debug("deadline ledger updated")
        if old_reality != self.scene.current_reality:
            self._debug("world resolver committed shared reality")
        else:
            self._debug("world resolver found no shared-state change")
        return result

    def step(self, progress=None) -> ArenaTurn:
        if not self.started or not self.scene:
            raise RuntimeError("Start an Arena first.")

        # 🐉 Silver Wyrm: a terminal deadline persisted from a failed consequence pass owns
        # the next scheduler step before either controlled actor can continue.
        terminal_due = [d for d in (getattr(self.scene, "active_deadlines", []) or []) if isinstance(d, dict) and bool(d.get("terminal_reached", False)) and not bool(d.get("resolved", False))]
        if terminal_due:
            self._debug("terminal deadline pending -> Director retains world authority")
            terminal_result = self.director.resolve_terminal_deadline(self.scene, self._participants())
            if not getattr(terminal_result, "adjudication_valid", True):
                raise ArenaRecoverableError("Director", "Terminal deadline consequence could not be resolved yet.")
            self.scene.current_reality = terminal_result.current_reality
            self.scene.actor_briefs = terminal_result.actor_briefs
            self.scene.active_commitments = terminal_result.active_commitments or dict(self.scene.active_commitments)
            # Terminal-deadline resolution must travel through the same monotonic mortality
            # seal as normal world resolution. Direct actor_status assignment could otherwise
            # revive an already-dead persona or fail to persist a newly confirmed death.
            self._merge_status(terminal_result)
            try:
                self.session_manager._save()
            except Exception:
                pass
            self.scene.world_dynamics = list(getattr(terminal_result, "world_dynamics", None) or self.scene.world_dynamics or [])
            self.scene.hard_constraints = list(getattr(terminal_result, "hard_constraints", None) or self.scene.hard_constraints or [])
            self.scene.causal_states = list(getattr(terminal_result, "causal_states", None) or self.scene.causal_states or [])
            self.scene.active_deadlines = list(getattr(terminal_result, "active_deadlines", None) or self.scene.active_deadlines or [])
            self.scene.add_log("causal_resolution", terminal_result.causal_resolution, actor="Director")
            self.scene.revision += 1
            self.store.save(self.scene)
            self._debug(f"terminal consequence -> {terminal_result.causal_resolution}")

        # 🐉 Silver Wyrm: RESOLUTION LOCK. Once an existing commitment is due and both admitted
        # witnesses are present, the scheduler is not allowed to generate another actor turn
        # until the Director produces a genuinely new materialised consequence.
        if self._resolution_lock_active():
            selected_index, locked_sess = self._current_session()
            trigger = self._name(locked_sess) if locked_sess is not None else "Director"
            self._debug("resolution lock entered -> Director retains control; actors frozen")
            log_arena_diagnostic(
                "resolution_lock_enter", actor=trigger, provisional_povs=dict(self.scene.provisional_povs or {}),
                commitment_age=dict(self.scene.commitment_age or {}), active_commitments=dict(self.scene.active_commitments or {}),
            )
            resolved = self._resolve_pending_exchange(trigger, progress=progress)
            if resolved is None:
                # 🐉 Silver Wyrm: THE SHOW MUST GO OOOOOOOOON: never solve Director failure by
                # returning unchanged reality to the actors. Persist the lock and surface a
                # recoverable Director retry. Auto may retry, but no persona receives the
                # floor until a real external consequence is committed.
                self.resolution_lock_failures = int(getattr(self, "resolution_lock_failures", 0) or 0) + 1
                self.scene.mandatory_progress_lock = True
                self.scene.mandatory_progress_reason = "Director consequence still pending"
                self.scene.add_log("director_recovery", "Hard consequence lock retained; actors remain frozen until shared reality changes.", actor="Director")
                self.store.save(self.scene)
                self._debug("HARD CONSEQUENCE LOCK retained -> no actor release")
                log_arena_diagnostic(
                    "resolution_lock_retained", actor=trigger,
                    provisional_povs=dict(self.scene.provisional_povs or {}),
                    commitment_age=dict(self.scene.commitment_age or {}),
                    failures=self.resolution_lock_failures,
                )
                raise ArenaRecoverableError("Director", "Hard consequence lock retained; retrying Director before actors may continue.")
            if resolved is not False:
                self.resolution_lock_failures = 0
                self.scene.revision += 1
                self.store.save(self.scene)
                if selected_index is not None:
                    self._commit_turn_advance(selected_index)
                self._debug(f"resolution lock released -> revision {self.scene.revision}")
                log_arena_diagnostic("resolution_lock_release", actor=trigger, revision=self.scene.revision, causal_resolution=resolved.causal_resolution)

        selected_index, sess = self._current_session()
        if sess is None:
            return ArenaTurn("Director", "No living participants remain.", self.scene, ended=True)
        name = self._name(sess)
        self._debug(f"next actor -> {name}")
        if progress:
            progress("actor", name)
        reply = self._actor_turn(sess)
        reply = self._admit_candidate(sess, name, reply, progress=progress)

        # ADMISSION COMMIT: visible actor prose is accepted as that actor's POV evidence only.
        # It is not objective shared reality until the post-pair world resolver crystallises it.
        self.scene.add_log("actor", reply, actor=name)
        self.scene.provisional_povs[name] = reply
        self._acknowledge_guidance_for_actor(name)
        self._persist_experience(sess, reply)

        # Only after both actors have admissible POV evidence do we ask the heavy Director to resolve the world.
        resolved = self._resolve_pending_exchange(name, progress=progress)
        resolution_pending = bool(self._resolution_lock_active() and resolved is None)

        self.scene.revision += 1
        self.store.save(self.scene)
        # A due unresolved consequence freezes scheduler ownership on the actor whose admitted
        # turn completed the witness pair. The next step is Director-only.
        if not resolution_pending:
            self._commit_turn_advance(selected_index)
        else:
            self._debug("due consequence unresolved -> actor scheduler frozen behind resolution lock")
            log_arena_diagnostic("resolution_lock_arm", actor=name, revision=self.scene.revision)
        self.recoverable_failures = 0
        pending_count = len([v for v in (self.scene.provisional_povs or {}).values() if str(v or "").strip()])
        self._debug(f"turn admitted -> revision {self.scene.revision}; provisional POVs={pending_count}")
        return ArenaTurn(name, reply, self.scene, ended=len(self._living_indices()) == 0, resolution_pending=resolution_pending)

    def save_scene_snapshot(self, path: str) -> str:
        """Save a portable Arena checkpoint. No model call and no state mutation."""
        if not self.started or not self.scene:
            raise RuntimeError("Start an Arena before saving it.")
        path = os.path.abspath(str(path or "").strip())
        if not path:
            raise ValueError("Choose a file path for the Arena scene.")
        payload = {
            "format": "dunoon-arena-scene",
            "version": 1,
            "turn_index": int(self.turn_index),
            "participant_ids": [str(getattr(s, "id", "") or "") for s in self.sessions],
            "participant_names": [self._name(s) for s in self.sessions],
            "scene": asdict(self.scene),
        }
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp, path)
        self._debug(f"scene checkpoint saved -> {path}")
        return path

    def load_scene_snapshot(self, path: str, available_sessions) -> SceneRecord:
        """Restore a portable Arena checkpoint using the user's existing personas."""
        path = os.path.abspath(str(path or "").strip())
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if payload.get("format") != "dunoon-arena-scene" or int(payload.get("version", 0) or 0) != 1:
            raise ValueError("This is not a supported Dunoon Daemon Arena scene file.")
        raw_scene = payload.get("scene")
        if not isinstance(raw_scene, dict):
            raise ValueError("Arena scene file is missing scene state.")
        ids = [str(x or "") for x in payload.get("participant_ids", [])]
        names = [str(x or "") for x in payload.get("participant_names", [])]
        sessions = list(available_sessions or [])
        chosen = []
        missing = []
        for i in range(2):
            wanted_id = ids[i] if i < len(ids) else ""
            wanted_name = names[i] if i < len(names) else ""
            match = next((s for s in sessions if wanted_id and str(getattr(s, "id", "") or "") == wanted_id), None)
            # Never silently bind a modern saved ID to a different persona merely because
            # somebody later reused the same display name. Name fallback is legacy-only.
            if match is None and not wanted_id:
                match = next((s for s in sessions if wanted_name and self._name(s) == wanted_name), None)
            if match is None:
                missing.append(wanted_name or wanted_id or "unknown persona")
            else:
                chosen.append(match)
        if missing:
            raise ValueError("Saved Arena scene is missing persona" + ("s" if len(missing) != 1 else "") + ": " + ", ".join(missing))
        if chosen[0] is chosen[1] or getattr(chosen[0], "id", None) == getattr(chosen[1], "id", None):
            raise ValueError("Saved Arena scene does not contain two distinct personas.")
        allowed = set(SceneRecord.__dataclass_fields__)
        clean = {k: v for k, v in raw_scene.items() if k in allowed}
        for key, default in (("actor_status", {}), ("active_commitments", {}), ("commitment_age", {}), ("provisional_povs", {}), ("provisional_authority_verified", {}), ("world_dynamics", []), ("hard_constraints", []), ("causal_states", []), ("active_deadlines", []), ("live_directives", []), ("log", []), ("interaction_thread_key", ""), ("interaction_thread_id", ""), ("interaction_thread_label", ""), ("interaction_thread_progress_reason", ""), ("interaction_thread_age", 0), ("mandatory_progress_lock", False), ("mandatory_progress_reason", "")):
            clean.setdefault(key, default)
        scene = SceneRecord(**clean)
        if len(scene.participants) != 2:
            raise ValueError("Saved Arena scene does not contain exactly two participants.")
        self.sessions = chosen
        for sess in self.sessions:
            sess.session_manager = self.session_manager
        self.scene = scene
        # Saved checkpoints cannot roll persistent mortality backwards. Conversely, a dead
        # status stored in the checkpoint must propagate back to the persona registry.
        for sess in self.sessions:
            name = self._name(sess)
            saved_dead = str((self.scene.actor_status or {}).get(name, "alive") or "alive").lower() == "dead"
            if bool(getattr(sess, "is_deceased", False)):
                self.scene.actor_status[name] = "dead"
                self.scene.active_commitments[name] = ""
            elif saved_dead and bool(getattr(sess, "mortality_enabled", False)):
                sess.is_deceased = True
                self.scene.actor_status[name] = "dead"
                self.scene.active_commitments[name] = ""
        try:
            self.session_manager._save()
        except Exception:
            pass
        self.scene.simmer_streak = int(getattr(self.scene, "simmer_streak", 0) or 0)
        self.scene.mandatory_progress_lock = bool(getattr(self.scene, "mandatory_progress_lock", False))
        self.scene.mandatory_progress_reason = str(getattr(self.scene, "mandatory_progress_reason", "") or "")
        self.scene.interaction_thread_key = str(getattr(self.scene, "interaction_thread_key", "") or "")
        self.scene.interaction_thread_id = str(getattr(self.scene, "interaction_thread_id", "") or self.scene.interaction_thread_key or "")
        self.scene.interaction_thread_label = str(getattr(self.scene, "interaction_thread_label", "") or "")
        self.scene.interaction_thread_progress_reason = str(getattr(self.scene, "interaction_thread_progress_reason", "") or "")
        self.scene.interaction_thread_age = int(getattr(self.scene, "interaction_thread_age", 0) or 0)
        self.turn_index = int(payload.get("turn_index", 0) or 0) % 2
        self.started = True
        self.recoverable_failures = 0
        self.resolution_lock_failures = 0
        self.store.save(scene)
        self._debug(f"BUILD {self.ARENA_BUILD}")
        self._debug(f"scene checkpoint loaded · {self._name(chosen[0])} vs {self._name(chosen[1])} · revision {scene.revision}")
        return scene

    def generate_random_event(self) -> str:
        if not self.started or not self.scene:
            raise RuntimeError("Start an Arena first.")
        return self.director.generate_random_event(self.scene, self._participants())

    def _apply_live_directive(self, text: str, *, kind: str, image_path: str = None) -> SceneRecord:
        """Apply an exact user/world directive without another semantic inference call.

        Python does not infer the English meaning. It records provenance, makes the exact
        directive part of the authoritative scene packet, and lets the primary model reason
        about it on subsequent actor/Director calls.
        """
        if not self.started or not self.scene:
            raise RuntimeError("Start an Arena first.")
        text = str(text or "").strip()
        if not text:
            raise ValueError("Live directive is empty.")
        self.scene.revision += 1
        directive = {
            "id": f"user-r{self.scene.revision}",
            "text": text,
            "kind": str(kind or "guidance"),
            "source": "user",
            "authority": "highest",
            "active": True,
            "revision": int(self.scene.revision),
            "acknowledged_by": [],
        }
        image_path = str(image_path or "").strip()
        if image_path:
            directive["image_path"] = image_path
            directive["media_type"] = "image"
        self.scene.live_directives = list(getattr(self.scene, "live_directives", []) or [])[-31:] + [directive]
        # Keep the exact text in its own authoritative ledger. We deliberately do not
        # rewrite current_reality here: that avoids deterministic prose concatenation
        # masquerading as semantic integration while still giving the primary model
        # the live edit as higher-priority structured context on every later call.
        self.scene.add_log("user_input" if kind == "guidance" else "intervention", text, actor="Human" if kind == "guidance" else "Human Director")
        # Any half-pair predating this live edit is stale evidence for world resolution.
        # Clearing it does not interrupt Auto; it simply starts the next post-edit pair cleanly.
        self.scene.provisional_povs = {}
        self.scene.provisional_authority_verified = {}
        self.scene.simmer_streak = 0
        self._reset_interaction_thread(f"user {kind}")
        self.resolution_lock_failures = 0
        self.store.save(self.scene)
        self._debug(f"{'GUIDANCE APPLIED' if kind == 'guidance' else 'EVENT APPLIED'} -> revision {self.scene.revision}")
        return self.scene

    def user_input(self, text: str, image_path: str = None) -> SceneRecord:
        """Highest-priority live edit of the opening scene directive."""
        return self._apply_live_directive(text, kind="guidance", image_path=image_path)

    def apply_event(self, text: str) -> SceneRecord:
        """Accept an Event as exact shared reality with no second integration inference."""
        return self._apply_live_directive(text, kind="event")

    def intervene(self, text: str) -> SceneRecord:
        if not self.started or not self.scene:
            raise RuntimeError("Start an Arena first.")
        text = str(text or "").strip()
        if not text:
            raise ValueError("Intervention is empty.")
        result = self.director.apply_human_intervention(self.scene, text, self._participants())
        self.scene.current_reality = result.current_reality
        self.scene.actor_briefs = result.actor_briefs
        self.scene.active_commitments = result.active_commitments or dict(self.scene.active_commitments)
        self.scene.world_dynamics = list(getattr(result, "world_dynamics", None) or self.scene.world_dynamics or [])
        self.scene.hard_constraints = list(getattr(result, "hard_constraints", None) or getattr(self.scene, "hard_constraints", []) or [])
        self.scene.causal_states = list(getattr(result, "causal_states", None) or getattr(self.scene, "causal_states", []) or [])
        self.scene.active_deadlines = list(getattr(result, "active_deadlines", None) or getattr(self.scene, "active_deadlines", []) or [])
        self.scene.commitment_age = {name: 0 for name in self.scene.participants}
        self.scene.simmer_streak = 0
        self._reset_interaction_thread("human intervention")
        # An authoritative Event changes the world baseline for subsequent testimony; discard any pre-event POV half-pair.
        self.scene.provisional_povs = {}
        self.resolution_lock_failures = 0
        for sess in self.sessions:
            name = self._name(sess)
            old = self.scene.actor_status.get(name, "alive")
            proposed = str(result.actor_status.get(name, old) or old).lower()
            # Persistent mortality is monotonic. A later Director/intervention response that
            # casually emits "alive" must never resurrect a persona already recorded dead.
            if old == "dead" or bool(getattr(sess, "is_deceased", False)):
                self.scene.actor_status[name] = "dead"
                self.scene.active_commitments[name] = ""
                sess.is_deceased = True
            elif proposed == "dead" and bool(getattr(sess, "mortality_enabled", False)):
                self.scene.actor_status[name] = "dead"
                self.scene.active_commitments[name] = ""
                sess.is_deceased = True
            else:
                self.scene.actor_status[name] = "alive"
        self.scene.revision += 1
        self.scene.add_log("intervention", text, actor="Human Director")
        self.store.save(self.scene)
        self._debug(f"human intervention accepted -> revision {self.scene.revision}")
        try:
            self.session_manager._save()
        except Exception:
            pass
        return self.scene
