# state_engine.py — Synthetic State + Persistent Dynamic Scene State Engine
import json
import os
import re
import threading
from typing import Dict, Any, Iterable
from config import STATE_MATRIX_FILE
from memory_semantics import semantic_similarity


class SyntheticStateEngine:
    """
    Two deliberately separate jobs live here:

    1) the existing synthetic/personality state matrix (warmth, focus, formality, etc.)
    2) a generic dynamic scene ledger for physical/causal state that changes over time

    The scene ledger never scans narrative vocabulary. It consumes structured semantic
    telemetry produced by the model and stores only compact subject/property/object
    relationships. This lets arbitrary actors, objects, conditions and phenomena progress
    without adding scenario-specific Python rules.
    """

    ALLOWED_STATE_KEYS = {"warmth", "directness", "analytical_depth", "cognitive_focus", "formality"}
    WORLD_DELTA_MAX = 16
    WORLD_STATE_MAX_RELATIONS = 80

    def __init__(self, state_file_path: str = STATE_MATRIX_FILE):
        self.state_file_path = state_file_path
        self._lock = threading.RLock()
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        if os.path.exists(self.state_file_path):
            try:
                with open(self.state_file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
            except Exception:
                return {}
        return {}

    def save_state(self) -> None:
        with self._lock:
            os.makedirs(os.path.dirname(self.state_file_path), exist_ok=True)
            tmp = f"{self.state_file_path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.state_file_path)

    @staticmethod
    def _extract_meta(model_response: str) -> Dict[str, Any]:
        if not model_response:
            return {}
        m = re.search(r'<!--\s*meta\s*:\s*(\{.*?\})\s*-->', str(model_response), flags=re.I | re.S)
        if not m:
            return {}
        try:
            data = json.loads(m.group(1))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _clean_text(value: Any, limit: int = 280) -> str:
        if value is None:
            return ""
        text = " ".join(str(value).strip().split())
        return text[:limit]

    @staticmethod
    def _scene_id(session=None) -> str:
        """Arena participants may share a transient scene_state_id; solo chats fall back to session id."""
        if session is not None:
            shared = getattr(session, "scene_state_id", None)
            if shared:
                return str(shared)
            sid = getattr(session, "id", None) or getattr(session, "session_id", None)
            if sid:
                return f"session:{sid}"
        return "global"

    @staticmethod
    def _relation_key(subject: str, relation: str, obj: str = "", slot: str = "") -> str:
        def norm(v):
            return " ".join(str(v or "").casefold().split())
        canonical_slot = norm(slot)
        if canonical_slot:
            return f"slot|{canonical_slot}"
        return "|".join((norm(subject), norm(relation), norm(obj)))

    @staticmethod
    def _fallback_slot(subject: str, relation: str, obj: str = "") -> str:
        """Create a deterministic visible slot when a model omits one.

        The slot is transport identity, not semantic classification. Once exposed in the
        current-state block the model can reuse it verbatim on subsequent changes.
        """
        def norm(v):
            return "_".join(" ".join(str(v or "").casefold().split()).split())
        bits = [norm(subject), norm(relation), norm(obj)]
        compact = "::".join(bit for bit in bits if bit)
        return ("auto::" + compact)[:180]

    @staticmethod
    def _identity_norm(value: Any) -> str:
        return " ".join(str(value or "").casefold().split())

    @classmethod
    def _relation_similarity(cls, a: str, b: str) -> float:
        """Semantic relation similarity only; no token overlap or phrase taxonomy."""
        a_n = cls._identity_norm(a)
        b_n = cls._identity_norm(b)
        if not a_n or not b_n:
            return 0.0
        if a_n == b_n:
            return 1.0
        score = semantic_similarity(a_n, b_n)
        return max(0.0, score) if score >= 0.0 else 0.0

    def _canonical_slot_for_delta(self, relations: Dict[str, Any], delta: Dict[str, Any]) -> str:
        """Resolve one proposed state change onto a Dunoon-owned existing fact identity.

        Models may paraphrase relation names or invent a fresh slot. Dunoon therefore treats
        model slots as proposals. Exact existing slots win; otherwise a unique existing
        subject/object relation is reused. Ambiguous cases are left separate rather than
        collapsing unrelated facts. This is deliberately vocabulary-agnostic.
        """
        subject = self._clean_text(delta.get("subject"), 120)
        relation = self._clean_text(delta.get("relation") or delta.get("property"), 120)
        obj = self._clean_text(delta.get("object"), 120)
        proposed = self._clean_text(delta.get("slot") or delta.get("state_key"), 180)

        if not subject or not relation:
            return self._fallback_slot(subject, relation, obj)

        # If the proposed slot already exists, it is already a Dunoon-owned identity.
        if proposed and self._relation_key(subject, relation, obj, slot=proposed) in relations:
            return proposed

        s_norm = self._identity_norm(subject)
        o_norm = self._identity_norm(obj)
        candidates = []
        for rec in relations.values():
            if not isinstance(rec, dict):
                continue
            if self._identity_norm(rec.get("subject")) != s_norm:
                continue
            rec_obj = self._identity_norm(rec.get("object"))
            if o_norm:
                if rec_obj != o_norm:
                    continue
            elif rec_obj:
                continue
            slot = self._clean_text(rec.get("slot"), 180)
            if not slot:
                continue
            score = self._relation_similarity(relation, rec.get("relation", ""))
            candidates.append((score, slot))

        # One established fact between this exact subject/object pair is unambiguous.
        if len(candidates) == 1:
            return candidates[0][1]

        # With several facts on the same pair, only reuse a clearly similar relation.
        if candidates:
            candidates.sort(reverse=True)
            best_score, best_slot = candidates[0]
            runner_up = candidates[1][0] if len(candidates) > 1 else 0.0
            if best_score >= 0.62 and (best_score - runner_up) >= 0.12:
                return best_slot

        # A fresh model/referee-proposed slot is never authoritative identity. If it does
        # not already exist, Dunoon assigns the deterministic slot itself.
        return self._fallback_slot(subject, relation, obj)

    def canonicalize_meta_world_state(self, meta: Dict[str, Any], session=None) -> Dict[str, Any]:
        """Return telemetry with model-proposed world deltas mapped onto Dunoon-owned slots."""
        data = dict(meta or {}) if isinstance(meta, dict) else {}
        raw = data.get("world_delta", [])
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list):
            data["world_delta"] = []
            return data

        scene_id = self._scene_id(session)
        with self._lock:
            self.state = self._load_state()
            scene = self._scene_store(scene_id, create=False)
            relations = scene.get("relations", {}) if isinstance(scene, dict) else {}
            if not isinstance(relations, dict):
                relations = {}
            canonical = []
            referee_valid = bool(data.get("_arena_referee_valid", False))
            for item in raw[:self.WORLD_DELTA_MAX]:
                if not isinstance(item, dict):
                    continue
                fixed = dict(item)
                if referee_valid:
                    subject = self._clean_text(fixed.get("subject"), 120)
                    relation = self._clean_text(fixed.get("relation") or fixed.get("property"), 120)
                    basis = self._clean_text(fixed.get("basis"), 260)
                    agency = self._clean_text(fixed.get("agency"), 40).lower()
                    has_state = any(self._clean_text(fixed.get(k), 220) for k in ("current", "change", "status"))
                    try:
                        confidence = float(fixed.get("confidence", 1.0))
                    except (TypeError, ValueError):
                        confidence = 0.0
                    if (not subject or not relation or not basis or not has_state or
                            agency not in {"self", "caused", "observed"} or confidence < 0.60):
                        continue
                fixed["slot"] = self._canonical_slot_for_delta(relations, fixed)
                canonical.append(fixed)
            data["world_delta"] = canonical
        return data

    def _scene_store(self, scene_id: str, create: bool = True) -> Dict[str, Any]:
        scenes = self.state.setdefault("scene_states", {}) if create else self.state.get("scene_states", {})
        if not isinstance(scenes, dict):
            if not create:
                return {}
            scenes = {}
            self.state["scene_states"] = scenes
        if create:
            scene = scenes.setdefault(scene_id, {"turn": 0, "relations": {}})
            if not isinstance(scene, dict):
                scene = {"turn": 0, "relations": {}}
                scenes[scene_id] = scene
            scene.setdefault("turn", 0)
            scene.setdefault("relations", {})
            return scene
        scene = scenes.get(scene_id, {})
        return scene if isinstance(scene, dict) else {}

    def reset_scene(self, scene_id: str) -> None:
        if not scene_id:
            return
        with self._lock:
            self.state = self._load_state()
            scenes = self.state.setdefault("scene_states", {})
            scenes[str(scene_id)] = {"turn": 0, "relations": {}}
            self.save_state()

    def drop_scene(self, scene_id: str) -> None:
        if not scene_id:
            return
        with self._lock:
            self.state = self._load_state()
            scenes = self.state.get("scene_states", {})
            if isinstance(scenes, dict) and str(scene_id) in scenes:
                del scenes[str(scene_id)]
                self.save_state()

    def clear_all_scene_state(self) -> None:
        with self._lock:
            self.state = self._load_state()
            self.state["scene_states"] = {}
            self.save_state()

    # ------------------------------------------------------------------
    # Existing synthetic mood/state telemetry
    # ------------------------------------------------------------------

    def _consume_personality_delta(self, meta: Dict[str, Any]) -> None:
        deltas = meta.get("state_delta", {})
        if not isinstance(deltas, dict):
            return
        bounded = {}
        for key, value in deltas.items():
            if key not in self.ALLOWED_STATE_KEYS:
                continue
            try:
                delta = float(value)
            except (TypeError, ValueError):
                continue
            bounded[key] = max(-0.08, min(0.08, delta))
        if bounded:
            self.update_mood(bounded)

    def update_mood(self, sentiment_delta: Dict[str, float]) -> None:
        with self._lock:
            self.state = self._load_state()
            locks = self.state.get("controller_locks", {})
            if locks.get("freeze_all_moods", False):
                return
            active = self.state.get("active_mood", {})
            locked = locks.get("locked_traits", {})
            try:
                reactivity = float(self.state.get("genetics", {}).get("reactivity", 0.5))
            except (TypeError, ValueError):
                reactivity = 0.5
            reactivity = max(0.0, min(1.0, reactivity))
            changed = False
            for key, delta in sentiment_delta.items():
                if key in active and not locked.get(key, False):
                    try:
                        current = float(active[key])
                        delta = float(delta)
                    except (TypeError, ValueError):
                        continue
                    active[key] = round(max(0.0, min(1.0, current + (delta * reactivity))), 2)
                    changed = True
            if changed:
                self.save_state()

    # ------------------------------------------------------------------
    # Generic dynamic-world telemetry
    # ------------------------------------------------------------------

    def _iter_world_deltas(self, meta: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
        raw = meta.get("world_delta", [])
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list):
            return []
        return [item for item in raw[:self.WORLD_DELTA_MAX] if isinstance(item, dict)]

    def _consume_world_delta(self, meta: Dict[str, Any], session=None) -> None:
        meta = self.canonicalize_meta_world_state(meta, session=session)
        deltas = list(self._iter_world_deltas(meta))
        if not deltas:
            return

        scene_id = self._scene_id(session)
        with self._lock:
            self.state = self._load_state()
            scene = self._scene_store(scene_id, create=True)
            scene["turn"] = int(scene.get("turn", 0) or 0) + 1
            turn_no = scene["turn"]
            relations = scene.setdefault("relations", {})
            if not isinstance(relations, dict):
                relations = {}
                scene["relations"] = relations

            for delta in deltas:
                subject = self._clean_text(delta.get("subject"), 120)
                relation = self._clean_text(delta.get("relation") or delta.get("property"), 120)
                obj = self._clean_text(delta.get("object"), 120)
                slot = self._clean_text(delta.get("slot") or delta.get("state_key"), 180)
                if not slot and subject and relation:
                    slot = self._fallback_slot(subject, relation, obj)
                change = self._clean_text(delta.get("change"), 120)
                current = self._clean_text(delta.get("current"), 220)
                status = self._clean_text(delta.get("status"), 80).lower()
                basis = self._clean_text(delta.get("basis"), 260)

                if not subject or not relation:
                    continue
                if not current and not change and not status:
                    continue

                try:
                    confidence = float(delta.get("confidence", 1.0))
                except (TypeError, ValueError):
                    confidence = 1.0
                confidence = max(0.0, min(1.0, confidence))
                if confidence < 0.55:
                    continue

                key = self._relation_key(subject, relation, obj, slot=slot)
                previous = relations.get(key, {}) if isinstance(relations.get(key), dict) else {}
                advances = int(previous.get("advances", 0) or 0)
                terminal_states = {"completed", "resolved", "interrupted", "ended", "failed"}
                # A canonical slot represents one evolving fact/process. Count every accepted
                # non-terminal update to that same slot as progression even when the model
                # paraphrases the change differently on later turns.
                if previous and status not in terminal_states and (change or current):
                    advances += 1
                elif change or current:
                    advances = 1

                record = {
                    "slot": slot,
                    "subject": subject,
                    "relation": relation,
                    "object": obj,
                    "change": change,
                    "current": current or previous.get("current", ""),
                    "status": status or previous.get("status", "active"),
                    "basis": basis,
                    "confidence": round(confidence, 2),
                    "last_turn": turn_no,
                    "advances": advances,
                }

                initial = self._clean_text(delta.get("initial"), 180)
                if initial:
                    record["initial"] = previous.get("initial") or initial
                elif previous.get("initial"):
                    record["initial"] = previous.get("initial")

                relations[key] = record

            # Keep the freshest relations only. Old resolved relations are useful briefly,
            # but an unbounded scene ledger would become another memory vault.
            if len(relations) > self.WORLD_STATE_MAX_RELATIONS:
                ordered = sorted(relations.items(), key=lambda kv: int(kv[1].get("last_turn", 0) or 0))
                for key, _ in ordered[: len(relations) - self.WORLD_STATE_MAX_RELATIONS]:
                    relations.pop(key, None)

            self.save_state()

    def evaluate_turn_heuristics(self, user_query: str, model_response: str, session=None) -> None:
        """Backward-compatible entry point; consumes structured telemetry only."""
        meta = self._extract_meta(model_response)
        if not meta:
            return
        self._consume_personality_delta(meta)
        self._consume_world_delta(meta, session=session)

    def _format_world_state(self, session=None) -> str:
        scene_id = self._scene_id(session)
        with self._lock:
            self.state = self._load_state()
            scene = self._scene_store(scene_id, create=False)
            relations = scene.get("relations", {}) if isinstance(scene, dict) else {}
            if not isinstance(relations, dict) or not relations:
                return ""

            items = sorted(
                (r for r in relations.values() if isinstance(r, dict)),
                key=lambda r: int(r.get("last_turn", 0) or 0),
                reverse=True,
            )[:24]

        lines = [
            "[CURRENT DYNAMIC WORLD STATE]",
            "This block records causal changes that already happened in the current scene.",
            "It is not collaborative worldbuilding and does not grant permission to invent new facts.",
            "THIS BLOCK IS THE CURRENT REALITY LEDGER. When it conflicts with an older measurement, initial scene snapshot, memory, or transcript wording, use THIS current value.",
            "Do not resurrect or restate a superseded earlier value merely because it appears elsewhere in context. Old values are history, not competing current facts.",
            "If a current relation says an actor/object moved closer, farther, away, toward, entered, exited, advanced, retreated, or otherwise changed relative state, an older exact measurement from the historical scene is no longer a current measurement unless a later authoritative/current fact explicitly re-measures it.",
            "When the exact new measurement is unknown, preserve the qualitative current relation instead of reusing the obsolete old number.",
            "A newer authoritative user/system statement still outranks this block if it explicitly changes the same fact.",
        ]
        for r in reversed(items):
            slot = r.get("slot", "")
            subject = r.get("subject", "Something")
            relation = r.get("relation", "state")
            obj = r.get("object", "")
            current = r.get("current", "")
            change = r.get("change", "")
            status = r.get("status", "")
            advances = int(r.get("advances", 0) or 0)

            target = f" -> {obj}" if obj else ""
            detail_bits = []
            if current:
                detail_bits.append(f"current={current}")
            if change:
                detail_bits.append(f"change={change}")
            if status:
                detail_bits.append(f"status={status}")
            if advances >= 2 and status not in {"completed", "resolved", "interrupted", "ended", "failed"}:
                detail_bits.append(
                    f"advanced repeatedly ({advances} accepted updates): this process is already underway; do not reset its start point or merely restate the same attempt. The next supported continuation must materially advance, complete, fail, or be concretely interrupted"
                )
            slot_prefix = f"slot={slot} | " if slot else ""
            lines.append(f"- {slot_prefix}{subject} | {relation}{target} | " + "; ".join(detail_bits))

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Actor-relative situational gauges
    # ------------------------------------------------------------------

    @staticmethod
    def _situation_actor_key(session=None) -> str:
        if session is None:
            return "global"
        sid = getattr(session, "scene_state_id", None) or getattr(session, "id", None) or getattr(session, "session_id", None)
        if sid:
            return str(sid)
        name = getattr(session, "agent_name", None)
        return f"name:{name}" if name else "global"

    @staticmethod
    def _clean_gauge_level(value: Any) -> str:
        level = str(value or "").strip().casefold()
        return level if level in {"green", "amber", "red"} else ""

    @staticmethod
    def _hysteresis_level(previous: str, proposed: str) -> str:
        """Escalation may be immediate; de-escalation falls by at most one band per accepted assessment."""
        order = {"green": 0, "amber": 1, "red": 2}
        previous = previous if previous in order else "green"
        proposed = proposed if proposed in order else previous
        if order[proposed] >= order[previous]:
            return proposed
        return {2: "amber", 1: "green", 0: "green"}[order[previous]]

    def has_situation(self, session=None) -> bool:
        scene_id = self._scene_id(session)
        actor_key = self._situation_actor_key(session)
        with self._lock:
            self.state = self._load_state()
            scene = self._scene_store(scene_id, create=False)
            situation = scene.get("situation", {}) if isinstance(scene, dict) else {}
            return isinstance(situation, dict) and isinstance(situation.get(actor_key), dict)

    def get_situation(self, session=None) -> Dict[str, Any]:
        """Return this actor's current threat/opportunity gauges; missing assessments stay unassessed."""
        scene_id = self._scene_id(session)
        actor_key = self._situation_actor_key(session)
        with self._lock:
            self.state = self._load_state()
            scene = self._scene_store(scene_id, create=False)
            situation = scene.get("situation", {}) if isinstance(scene, dict) else {}
            rec = situation.get(actor_key, {}) if isinstance(situation, dict) else {}
            if not isinstance(rec, dict):
                rec = {}
            return {
                "threat": dict(rec.get("threat", {})) if isinstance(rec.get("threat"), dict) else {"level": "unassessed", "basis": "No valid situational assessment has been accepted yet.", "confidence": 0.0},
                "opportunity": dict(rec.get("opportunity", {})) if isinstance(rec.get("opportunity"), dict) else {"level": "unassessed", "basis": "No valid situational assessment has been accepted yet.", "confidence": 0.0},
                "assessed": bool(rec),
            }

    def update_situation(self, assessment: Dict[str, Any], session=None, source: str = "semantic") -> Dict[str, Any]:
        """Commit validated actor-relative gauges. Semantic interpretation is external; Python owns continuity."""
        if not isinstance(assessment, dict):
            return self.get_situation(session)

        scene_id = self._scene_id(session)
        actor_key = self._situation_actor_key(session)
        actor_name = str(getattr(session, "agent_name", "") or actor_key)
        with self._lock:
            self.state = self._load_state()
            scene = self._scene_store(scene_id, create=True)
            situation = scene.setdefault("situation", {})
            if not isinstance(situation, dict):
                situation = {}
                scene["situation"] = situation
            previous = situation.get(actor_key, {}) if isinstance(situation.get(actor_key), dict) else {}
            record = dict(previous)
            before_levels = {}
            after_levels = {}

            for gauge in ("threat", "opportunity"):
                incoming = assessment.get(gauge, {})
                if not isinstance(incoming, dict):
                    continue
                proposed = self._clean_gauge_level(incoming.get("level"))
                basis = self._clean_text(incoming.get("basis"), 360)
                try:
                    confidence = float(incoming.get("confidence", 1.0))
                except (TypeError, ValueError):
                    confidence = 1.0
                confidence = max(0.0, min(1.0, confidence))
                if not proposed or not basis:
                    continue

                old = record.get(gauge, {}) if isinstance(record.get(gauge), dict) else {}
                old_level = self._clean_gauge_level(old.get("level"))
                before_levels[gauge] = old_level or "unassessed"

                # Current accepted assessment is current truth. Stability comes from
                # reassessing only after material scene changes, not from colour inertia.
                accepted_level = proposed
                after_levels[gauge] = accepted_level
                record[gauge] = {
                    "level": accepted_level,
                    "basis": basis,
                    "confidence": round(confidence, 2),
                    "source": self._clean_text(source, 80) or "semantic",
                }

            if record and ("threat" in record or "opportunity" in record):
                record["updated_turn"] = int(scene.get("turn", 0) or 0)
                situation[actor_key] = record
                self.save_state()

                changed = any(before_levels.get(g) != after_levels.get(g) for g in after_levels)
                if changed:
                    t = str(record.get("threat", {}).get("level", "unassessed")).upper()
                    o = str(record.get("opportunity", {}).get("level", "unassessed")).upper()
                    print(f"[Situation Gauge] {actor_name}: THREAT={t} | OPPORTUNITY={o}")

            return self.get_situation(session)

    def _format_situation_state(self, session=None) -> str:
        state = self.get_situation(session)
        threat = state.get("threat", {})
        opportunity = state.get("opportunity", {})
        t_level = str(threat.get("level", "unassessed")).upper()
        o_level = str(opportunity.get("level", "unassessed")).upper()
        t_basis = self._clean_text(threat.get("basis"), 360)
        o_basis = self._clean_text(opportunity.get("basis"), 360)
        red_contract = ""
        if t_level == "RED":
            red_contract += (
                "\n[RED THREAT CONTRACT] This is not flavour text. The next decision MUST materially account for the immediate danger. "
                "Do not spend the turn on optional conversation, leisurely observation, speculative searching, or unrelated planning while leaving the danger unaddressed. "
                "RED does not dictate a tactic: flee, advance, fight, defend, rescue, sacrifice, negotiate under pressure, or another persona-consistent direct response may all be valid."
            )
        if o_level == "RED":
            red_contract += (
                "\n[RED OPPORTUNITY CONTRACT] The goal-relevant window is closing now. If this actor cares about the goal, the next decision must exploit the window now or consciously accept that it may be lost. "
                "RED opportunity never forces the actor to value or take the opportunity."
            )
        return (
            "[ACTOR-RELATIVE SITUATIONAL GAUGES]\n"
            f"THREAT: {t_level} — {t_basis}\n"
            f"OPPORTUNITY PRIORITY: {o_level} — {o_basis}\n"
            "Threat measures how urgently this actor must account for credible danger: GREEN = no immediate credible danger; "
            "AMBER = meaningful danger deserves active attention but still allows a comfortable decision window; "
            "RED = severe harm/death/catastrophic failure is a realistic near-term outcome if the actor fails to materially respond now.\n"
            "Opportunity priority measures how quickly a goal-relevant advantage/window must be exploited before it is lost: "
            "GREEN = accessible/easy or can safely wait; AMBER = increasingly important/time-sensitive and deserves active consideration; "
            "RED = one meaningful turn of delay may lose the opportunity.\n"
            "These gauges are Dunoon-owned current scene state. RED is deliberately rare and must not be treated as background context. "
            "UNASSESSED is a transport/assessment failure state, not GREEN and not evidence of safety."
            + red_contract
        )

    def generate_system_prompt_directive(self, session=None) -> str:
        with self._lock:
            self.state = self._load_state()
            mood = self.state.get("active_mood", {})
            directives = []
            vals = {k: float(mood.get(k, 0.5)) for k in self.ALLOWED_STATE_KEYS}
            if vals["warmth"] > 0.7:
                directives.append("Maintain a notably warm, affiliative interpersonal manner.")
            elif vals["warmth"] < 0.3:
                directives.append("Maintain a notably detached interpersonal manner.")
            if vals["directness"] > 0.7:
                directives.append("Prefer concise, direct expression.")
            elif vals["directness"] < 0.3:
                directives.append("Allow more exploratory and indirect expression.")
            if vals["analytical_depth"] > 0.7:
                directives.append("Use deeper technical or conceptual analysis where relevant.")
            if vals["cognitive_focus"] > 0.7:
                directives.append("Stay tightly focused on the active objective and relevant evidence.")
            if vals["formality"] < 0.35:
                directives.append("Use relaxed, natural phrasing.")
            elif vals["formality"] > 0.75:
                directives.append("Use a more formal, deliberate register.")
            goals = [
                g.get("description") for g in self.state.get("long_term_agenda", [])
                if isinstance(g, dict) and g.get("status") == "active" and g.get("description")
            ]

        parts = []
        if directives or goals:
            goal_text = "\nInternal Objectives:\n- " + "\n- ".join(goals[:2]) if goals else ""
            parts.append(f"[SYSTEM STATE DIRECTIVE: {' '.join(directives)}]{goal_text}")

        situation = self._format_situation_state(session=session)
        if situation:
            parts.append(situation)

        world = self._format_world_state(session=session)
        if world:
            parts.append(world)
        return "\n\n".join(parts)
