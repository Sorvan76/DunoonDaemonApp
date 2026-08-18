# ETO.py — Semantic Environment, Threat & Opportunity Continuity Engine
#
# Design goal:
#   React to arbitrary narrative meaning without trying to enumerate every possible
#   environment, hazard, action, object, creature, weapon, spell, disaster, etc.
#
# Important distinction:
#   - Python preserves authority, continuity, lifecycle and telemetry.
#   - The language model interprets the *meaning* of the scene.
#   - Narrative words are not treated as direct physics/state commands.

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import List, Dict, Any, Optional


@dataclass
class Hazard:
    """Generic externally/semantically registered pressure.

    ETO no longer creates hazards by scanning narrative vocabulary.
    A caller may register a hazard from a structured semantic signal, tool,
    narrator/event system, or future model telemetry.
    """
    description: str
    severity: float = 0.5
    source: str = "structured"
    turn_started: int = 0
    turns_active: int = 0
    resolved: bool = False

    def tick(self) -> None:
        if not self.resolved:
            self.turns_active += 1

    def resolve(self) -> None:
        self.resolved = True


class ETOEngine:
    """
    Semantic ETO engine.

    What it DOES:
    - preserves authoritative scene anchors across long conversations
    - separates environment state from individual entity state
    - gives the model causal/continuity rules
    - preserves explicit location/threat/opportunity configuration
    - accepts generic structured hazards without defining a closed hazard taxonomy
    - uses the model's existing hidden mood/intensity telemetry as a broad
      pressure signal for scene urgency
    - preserves the existing mortality API expected by controller.py

    What it DOES NOT do:
    - scan for lists of fire words, vacuum words, weapons, predators, actions, etc.
    - infer that an entity is submerged merely because water exists
    - infer that an entity is floating merely because zero-G exists
    - treat descriptive language as an automatic state mutation
    - invent a default environment when none has been established
    """

    def __init__(self, location: str = "", threat: str = "", opportunity: str = ""):
        self.location = (location or "").strip()
        self.threat = (threat or "").strip()
        self.opportunity = (opportunity or "").strip()

        self.current_turn = 0
        self.current_context = "routine"
        self.stakes_level = 0.1
        self.stagnation_turns = 0
        self.active_transformation = None  # compatibility field only

        self.hazards: List[Hazard] = []

        # Oldest -> newest. Later authoritative statements supersede older ones only
        # where they actually conflict.
        self.authoritative_scene_anchors: List[str] = []
        if self.location:
            self.authoritative_scene_anchors.append(self.location)

        self.last_pressure = 0.0
        self.last_progress = 1.0

        # Semantic progression memory. These fields deliberately track only broad
        # causal momentum; Python does not try to parse distances, verbs or objects.
        self.progress_debt = 0
        self.low_progress_streak = 0
        self.progression_history: List[str] = []

    # ------------------------------------------------------------------
    # AUTHORITATIVE NARRATIVE
    # ------------------------------------------------------------------

    def observe_narrative_input(self, text: str, authoritative: bool = True) -> None:
        """
        Persist high-authority scene narrative.

        Typical authority policy:
        - direct human input: authoritative
        - explicit User Intervention: authoritative
        - deliberate system/live event: authoritative
        - autonomous Arena peer prose: NOT authoritative

        This method does not parse scene vocabulary into hard-coded states.
        It preserves the narrative itself so the model can reason from meaning.
        """
        if not authoritative or not text or not str(text).strip():
            return

        cleaned = str(text).strip()

        # Strip only Dunoon's transport wrapper, not narrative content.
        intervention = re.search(
            r"\[(?:💥\s*)?User Intervention\]\s*:\s*(.*)",
            cleaned,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if intervention:
            cleaned = intervention.group(1).strip()

        if not cleaned:
            return

        if self.authoritative_scene_anchors and self.authoritative_scene_anchors[-1] == cleaned:
            return

        self.authoritative_scene_anchors.append(cleaned[:3500])
        # Keep the original scene anchor for the life of the session.
        if len(self.authoritative_scene_anchors) > 8:
            self.authoritative_scene_anchors = [
                self.authoritative_scene_anchors[0],
                *self.authoritative_scene_anchors[-7:],
            ]

    def observe_environment(self, authoritative_text: str) -> None:
        """Backward-compatible alias used by older Overmind revisions."""
        self.observe_narrative_input(authoritative_text, authoritative=True)

    def _authoritative_scene_text(self) -> str:
        return "\n".join(self.authoritative_scene_anchors).strip()

    # ------------------------------------------------------------------
    # GENERIC STRUCTURED HAZARD API
    # ------------------------------------------------------------------

    def register_hazard(
        self,
        description: str,
        severity: float = 0.5,
        source: str = "structured",
    ) -> Optional[Hazard]:
        """
        Register a hazard supplied by a semantic/structured source.

        No categories are required. Anything a future user invents can be represented
        without modifying ETO.py.
        """
        if not description or not str(description).strip():
            return None

        desc = str(description).strip()
        sev = max(0.0, min(1.0, float(severity)))

        # Exact normalized dedupe only. We intentionally do not pretend Python can
        # semantically decide that two differently worded hazards are identical.
        key = " ".join(desc.casefold().split())
        for h in self.hazards:
            if not h.resolved and " ".join(h.description.casefold().split()) == key:
                h.severity = max(h.severity, sev)
                return h

        hazard = Hazard(
            description=desc,
            severity=sev,
            source=str(source or "structured"),
            turn_started=self.current_turn,
        )
        self.hazards.append(hazard)
        return hazard

    def resolve_hazard(self, description: str) -> bool:
        """Resolve an explicitly identified hazard without vocabulary guessing."""
        if not description:
            return False

        key = " ".join(str(description).casefold().split())
        changed = False
        for h in self.hazards:
            if " ".join(h.description.casefold().split()) == key and not h.resolved:
                h.resolve()
                changed = True
        return changed

    def clear_resolved_hazards(self) -> None:
        self.hazards = [h for h in self.hazards if not h.resolved]

    # ------------------------------------------------------------------
    # EXISTING DUAL-CHANNEL TELEMETRY
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_meta_envelope(text: str) -> Dict[str, Any]:
        """
        Parse Dunoon's existing hidden <!--meta:{...}--> envelope.

        This is transport parsing, not narrative keyword interpretation.
        """
        if not text:
            return {}

        match = re.search(
            r"<!--\s*meta\s*:\s*(\{.*?\})\s*-->",
            str(text),
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return {}

        try:
            data = json.loads(match.group(1))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def analyze_and_update(self, user_text: str, assistant_text: str) -> None:
        """Advance lifecycle from structured semantic telemetry, never narrative word lists."""
        self.current_turn += 1

        for hazard in self.hazards:
            hazard.tick()
        self.clear_resolved_hazards()

        meta = self._extract_meta_envelope(assistant_text)

        try:
            pressure = float(meta.get("pressure", 0.0))
        except (TypeError, ValueError):
            pressure = 0.0
        try:
            progress = float(meta.get("progress", 1.0))
        except (TypeError, ValueError):
            progress = 1.0

        self.last_pressure = max(0.0, min(1.0, pressure))
        self.last_progress = max(0.0, min(1.0, progress))

        # Accumulate resolution pressure when the model itself reports that turns are
        # failing to materially advance the situation. This is intentionally semantic:
        # no action/object vocabulary and no fake numerical physics.
        if self.last_progress < 0.35:
            self.low_progress_streak += 1
            self.progress_debt = min(6, self.progress_debt + 1)
        elif self.last_progress >= 0.65:
            self.low_progress_streak = 0
            self.progress_debt = max(0, self.progress_debt - 2)
        else:
            self.low_progress_streak = max(0, self.low_progress_streak - 1)
            self.progress_debt = max(0, self.progress_debt - 1)

        if user_text or assistant_text:
            snapshot = (
                f"turn={self.current_turn} progress={self.last_progress:.2f} "
                f"pressure={self.last_pressure:.2f}"
            )
            self.progression_history.append(snapshot)
            self.progression_history = self.progression_history[-6:]

        explicit_threat_floor = 0.65 if self.threat else 0.0
        structured_hazard_pressure = max(
            (h.severity for h in self.hazards if not h.resolved),
            default=0.0,
        )

        self.stakes_level = round(
            max(0.1, explicit_threat_floor, self.last_pressure, structured_hazard_pressure),
            2,
        )
        self.current_context = "active_pressure" if self.stakes_level >= 0.6 else "routine"

        if self.stakes_level >= 0.6 and self.last_progress < 0.25:
            self.stagnation_turns += 1
        else:
            self.stagnation_turns = 0

    # ------------------------------------------------------------------
    # PROMPT / COGNITIVE DIRECTIVE
    # ------------------------------------------------------------------

    def format_directive(
        self,
        mortality_enabled: bool = False,
        is_deceased: bool = False,
        backstory: str = "",
        physiology: str = "",
        powers: str = "",
        recent_context: str = "",
        narrative_freedom: bool = False,
    ) -> str:
        """
        Build a scenario-agnostic continuity directive.

        There is deliberately no hard-coded list of media, hazards, weapons,
        locations, actions, threats or opportunities here.
        """
        if is_deceased:
            return (
                "\n[SCENE STATUS: DECEASED]\n"
                "- This character has already suffered permanent death/defeat.\n"
                "- Remain physically consistent with that established state. "
                "Do not resume normal dialogue or voluntary action unless an authoritative "
                "later event explicitly changes the state.\n"
            )

        authoritative_scene = self._authoritative_scene_text()
        active_phys = (
            physiology.strip()
            if physiology and physiology.strip()
            else "Not specifically defined; infer conservatively from established character facts."
        )
        active_powers = (
            powers.strip()
            if powers and powers.strip()
            else "No additional powers are established beyond the character/scenario context."
        )

        lines = [
            "\n[ETO: SEMANTIC SCENE CONTINUITY]",
            "Interpret the scene from narrative meaning and causal relationships, not from trigger-word matching.",
        ]

        if authoritative_scene:
            lines.extend([
                "\n[AUTHORITATIVE SCENE ANCHORS — OLDEST TO NEWEST]",
                authoritative_scene,
            ])
        else:
            lines.append(
                "\n[AUTHORITATIVE SCENE ANCHORS]\n"
                "No detailed physical scene has yet been authoritatively established. "
                "Do not invent a default location, terrain, atmosphere, medium, threat, or resource."
            )

        if self.location:
            lines.append(f"\n• Explicit Location Cue: {self.location}")
        if self.threat:
            lines.append(f"• Explicit Threat / Pressure Cue: {self.threat}")
        if self.opportunity:
            lines.append(f"• Explicit Opportunity / Leverage Cue: {self.opportunity}")

        lines.extend([
            f"• Physiology / Tolerances: {active_phys}",
            f"• Powers / Capabilities: {active_powers}",
        ])

        active_hazards = [h for h in self.hazards if not h.resolved]
        if active_hazards:
            lines.append("\n[STRUCTURED ACTIVE PRESSURES]")
            for h in active_hazards:
                lines.append(
                    f"• {h.description} | severity={h.severity:.2f} | "
                    f"active_turns={h.turns_active} | source={h.source}"
                )

        if self.current_turn:
            lines.extend([
                "\n[PREVIOUS-TURN SEMANTIC TELEMETRY]",
                f"pressure={self.last_pressure:.2f} | progress={self.last_progress:.2f}",
                "These are semantic summaries, not proof of any particular physical fact."
            ])

        lines.extend([
            "\n[GROUNDING & CONTINUITY RULES]",
            "1. SOURCE AUTHORITY: Direct user/scenario statements and explicit system/live-event interventions establish reality. "
            "Autonomous character prose cannot silently overwrite them by implication, embellishment or metaphor.",

            "2. REASON FROM MEANING: Understand what the narrative says actually happened. Do not reduce the scene to isolated words, "
            "and do not treat the mere mention of a material, place, danger, object or motion as an automatic global state change.",

            "3. ENVIRONMENT ≠ ENTITY STATE: The wider scene and an individual entity's state are different facts. Preserve each entity's "
            "established location, containment, support, posture, orientation, possessions, exposure and relationship to nearby features.",

            "4. CAUSAL TRANSITIONS: Before changing an established physical state, identify the action, event, force, decision or explicit "
            "statement that caused the change. If no plausible transition occurred, retain the established state.",

            "5. SPECIFIC FACTS OUTRANK BROAD INFERENCE: A specific established relation remains true until changed. Broad atmosphere, terrain, "
            "weather, medium, danger or mood must not erase a more specific fact about where an entity is or what condition it is in.",

            "6. CONSEQUENCES FOLLOW CAUSES: Apply realistic consequences to established events, physiology and capabilities, but do not invent "
            "the causal event merely to justify a dramatic consequence.",

            "7. OBJECT & TERRAIN CONTINUITY: Established objects, exits, barriers, distances, damage, transfers, consumption and destruction "
            "remain part of the scene until something actually changes them. Do not conjure convenient new resources.",

            "8. CAPABILITY BOUNDS: Use only abilities, equipment, spells, technology or unusual physiology supported by the persona, backstory, "
            "authoritative scene or explicit powers field.",

            "9. DESCRIPTIVE LANGUAGE IS NOT AUTOMATIC PHYSICS: Metaphor, emotional framing, sensory exaggeration and atmospheric prose do not "
            "by themselves alter depth, location, containment, gravity, breathing status, orientation or bodily condition.",

            "10. UNCERTAINTY: When the narrative does not establish a fact, preserve uncertainty. Do not replace unknowns with convenient defaults.",

            "11. AGENCY & PROGRESS: In active danger or urgent constraint, choose actions consistent with the character's personality and abilities. "
            "Do not confuse compassion, confidence, aggression, fear or calmness with ignorance of obvious physical stakes.",

            "12. EMBODIMENT: Maintain plausible reach, line of sight, movement, support and physical interaction, but avoid repetitive procedural "
            "body narration when nothing materially changes.",

            "13. STATE PROGRESSION: Established actions and processes must change the world when they have a plausible opportunity to do so. "
            "Do not restart an ongoing action from its original state on every turn. If movement, pursuit, opening, climbing, falling, damage, "
            "consumption, escape, approach, retreat, recovery or any other process continues without an established interruption, reflect its "
            "accumulated consequence in the next state.",

            "14. MEASUREMENTS ARE SNAPSHOTS: A distance, position, amount, condition or relationship stated earlier describes that moment. "
            "After a causal transition, do not keep reasserting the old measurement as though it were immutable. When exact recalculation is not "
            "supported, use honest relational progression such as closer, farther, nearly there, within reach, reached, worsening, depleted or resolved "
            "rather than inventing false precision.",

            "15. RESOLVE MATURE ACTIONS: When an intended action has been repeatedly and successfully advanced, and no established obstacle prevents "
            "completion, resolve it or produce its concrete consequence. Do not indefinitely narrate equivalent attempts merely to prolong the scene.",

            "16. CAUSAL LEDGER: Before responding, compare the newest scene state with the immediately preceding one. Ask what materially changed because "
            "of completed or ongoing actions, then continue from that changed state rather than from the original setup.",
        ])

        # Narrative authorship policy is injected independently by Overmind.

        if self.progress_debt >= 2 or self.low_progress_streak >= 2:
            lines.extend([
                "\n[STATE RESOLUTION PRESSURE]",
                f"Recent semantic telemetry indicates repeated weak progression (resolution pressure={self.progress_debt}).",
                "Inspect the actual narrative rather than assuming a particular action. If an established action/process has had enough uninterrupted "
                "opportunity to advance or complete, carry its consequences forward now. Do not repeat the same attempt from the same starting state. "
                "If something genuinely prevents progress, make that established obstruction consequential instead of silently freezing the world."
            ])

        if self.stagnation_turns >= 2 and self.stakes_level >= 0.6:
            lines.extend([
                "\n[ANTI-LOOP GUIDANCE]",
                "Semantic pressure has remained high across several turns. Assess the scene itself: "
                "if the interaction is genuinely repeating without material change, take a consequential action or make a decision "
                "that follows naturally from the character and established situation. If meaningful progress is already occurring, "
                "continue it rather than forcing an unrelated action.",
            ])

        if mortality_enabled:
            lines.extend([
                "\n[MORTALITY PROTOCOL: ACTIVE]",
                "Permanent injury/death is possible when established events and physiology genuinely support it.",
                "Do not grant plot armour, but do not manufacture lethal outcomes merely because the scene feels dramatic.",
                "Death must follow an established cause and must remain permanent unless an authoritative later event genuinely reverses it.",
            ])

        return "\n".join(lines)



EventTurnOrchestrator = ETOEngine
