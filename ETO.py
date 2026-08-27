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
    - coexists with Dunoon-owned actor-relative threat/opportunity priority gauges;
      ETO provides scene meaning while the state engine preserves their continuity
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


    def format_actor_lens_directive(self, actor_name: str = "") -> str:
        """Model-led actor-relative ETO lens.

        Python does not classify scene nouns or decide what can act. The model already
        understands ordinary semantics. This directive asks it to apply that understanding
        to accepted reality while preserving Dunoon's authority boundaries.
        """
        who = str(actor_name or "this actor").strip() or "this actor"
        return "\n".join([
            "[ETO ACTOR-RELATIVE LENS]",
            f"Before choosing {who}'s next voluntary action, interpret the accepted current scene from {who}'s point of view.",
            "Use ordinary real-world/common-sense semantics rather than waiting for explicit labels or hard-coded categories.",
            f"Ask internally: given what {who} is, what matters here now, and what would {who} plausibly do? Do not answer from a generic observer viewpoint.",
            f"Decision path: first perceive what {who} can perceive or reasonably know; then interpret what those perceived facts mean to {who} specifically; only then choose {who}'s voluntary response. Do not jump directly from stimulus strength to action.",
            f"Actor-specific significance: translate perception into meaning through {who}'s nature, needs, instincts, psychology, priorities, current condition and established capabilities. Ask what each relevant thing represents to {who} now, not merely which signal is strongest or most recent.",
            "Urgent action bias: when the situation is materially changing or dangerous and this actor already understands what matters, prefer a concrete voluntary attempt that can change the situation over repeatedly observing, reassessing, reassuring, waiting, or restating the same concern. Maintenance behaviour remains valid when it is itself necessary, effective, or the most plausible action for this actor; do not force action merely for novelty.",
            "Environment: attend to established external conditions, ongoing changes, and things already happening that this actor can perceive or reasonably know about.",
            "Threat: notice what can materially harm, trap, obstruct, expose, overwhelm, or otherwise matter negatively to this actor now, weighted by immediacy, physiology, capabilities, current condition, personality, and priorities.",
            "Opportunity: notice actionable openings, leverage, access, safety, prey/resources/routes/advantages or other useful possibilities that plausibly matter to this actor now. Weight them through this actor's own nature, needs, instincts, psychology, priorities and present condition. Do not assume the strongest sensory signal, newest event, nearest motion, or most recently mentioned thing is automatically the most important. Do not promote a merely interesting or morally salient possibility above a more urgent constraint unless this actor's priorities genuinely support that choice.",
            "Active scene factors: notice established people, groups, creatures, machinery, environmental processes, or other parts of reality whose behaviour or physical evolution can continue changing the situation without waiting for this actor's turn.",
            "Reactive people and creatures are not passive scenery. They may respond plausibly to danger and changing circumstances using only capabilities and materials already established in the scene.",
            "Affordances: established objects and conditions may be usable, blockable, climbable, movable, defensible, exploitable, escapable, or otherwise actionable when ordinary semantics and the scene support it. Never invent a convenient object, person, exit, resource, motive, or capability to create an affordance.",
            "POV controls salience, not truth. Accepted CURRENT REALITY remains authoritative; private thoughts, guesses, metaphors, and another actor's unsupported perceptions do not become shared facts.",
            "This lens shapes attention only. It does not issue goals or commands, does not choose the actor's action, and does not mutate shared reality. The actor still decides; the Director resolves external consequences.",
        ])

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
        """Compact semantic continuity prompt. Python stores facts; the model uses common sense."""
        if is_deceased:
            return (
                "[CURRENT STATE: DECEASED]\n"
                "This character is dead and cannot resume voluntary action or dialogue unless later authoritative input reverses it."
            )

        authoritative_scene = self._authoritative_scene_text()
        lines = ["[SCENE CONTINUITY]"]
        if authoritative_scene:
            lines.append("Authoritative scene facts:")
            lines.append(authoritative_scene)
        else:
            lines.append("No detailed scene has been authoritatively established. Preserve uncertainty instead of inventing essentials.")

        if self.location:
            lines.append(f"Location cue: {self.location}")
        if self.threat:
            lines.append(f"Threat cue: {self.threat}")
        if self.opportunity:
            lines.append(f"Opportunity cue: {self.opportunity}")

        lines.append(f"Physiology: {physiology.strip() if physiology and physiology.strip() else 'not specifically defined'}")
        lines.append(f"Capabilities: {powers.strip() if powers and powers.strip() else 'none additionally established'}")

        active_hazards = [h for h in self.hazards if not h.resolved]
        if active_hazards:
            lines.append("Active pressures: " + "; ".join(h.description for h in active_hazards[:5]))

        lines.extend([
            "Rules:",
            "1. Current accepted state overrides older snapshots where they conflict.",
            "2. Do not conjure consequential objects, exits, people, powers or facts unless collaborative worldbuilding permits it.",
            "3. Apply ordinary causal consequences to established events, bodies, objects and conditions.",
            "4. Intentions, guesses, metaphors and failed attempts do not become completed physical state.",
            "5. In danger, understand the stakes but choose behaviour according to this character's personality and capabilities.",
        ])
        if mortality_enabled:
            lines.append("Mortality is enabled: death/injury may occur only when established events and physiology genuinely support it.")
        return "\n".join(lines)



EventTurnOrchestrator = ETOEngine
