from __future__ import annotations

from .actor_prompt import build_actor_packet
from .contracts import SourceKind, TurnRequest, TurnResult
from .native_backend import NativeBackendUnavailable, NativeModelBackend


class TurnEngine:
    """One actor-generation brain for every Dunoon persona turn.

    Actor output is prose. World/state
    adjudication lives outside the actor in human authority (solo) or ArenaDirector (Arena).
    """

    ARENA_ACTOR_BUDGETS = (256, 384, 512, 768, 1024, 1280, 1536, 2048)
    SOLO_ACTOR_BUDGETS = ARENA_ACTOR_BUDGETS

    def __init__(self, backend: NativeModelBackend):
        self.backend = backend
        # 🐉 Silver Wyrm: THREE SQUARE MEALS: Arena detail is a live UI-controlled
        # visible-output budget. Read on every actor turn; reasoning remains OFF.
        self.arena_actor_max_tokens = 768
        self.solo_actor_max_tokens = 768

    def set_solo_actor_budget(self, max_tokens: int) -> int:
        try:
            requested = int(max_tokens)
        except Exception:
            requested = 768
        if requested not in self.SOLO_ACTOR_BUDGETS:
            requested = min(self.SOLO_ACTOR_BUDGETS, key=lambda value: abs(value - requested))
        self.solo_actor_max_tokens = requested
        return requested

    def set_arena_actor_budget(self, max_tokens: int) -> int:
        try:
            requested = int(max_tokens)
        except Exception:
            requested = 768
        if requested not in self.ARENA_ACTOR_BUDGETS:
            requested = min(self.ARENA_ACTOR_BUDGETS, key=lambda value: abs(value - requested))
        self.arena_actor_max_tokens = requested
        return requested

    def run(self, request: TurnRequest, *, scene_baseline: str = "", scene_reality: str = "", actor_brief: str = "", actor_commitment: str = "", scene_dynamics=None, scene_authority_snapshot=None, image_path: str = None) -> TurnResult:
        source = SourceKind.coerce(request.source)
        packet = build_actor_packet(
            request.text,
            request.session,
            source=source.value,
            scene_baseline=scene_baseline,
            scene_reality=scene_reality,
            actor_brief=actor_brief,
            actor_commitment=actor_commitment,
            scene_dynamics=scene_dynamics,
            scene_authority_snapshot=scene_authority_snapshot,
        )
        if image_path:
            packet["image_path"] = str(image_path)

        # 🐉 Silver Wyrm: SHUT UP AND ACT / EXTREME TOKEN ACCOUNTANT
        # 🐉 Silver Wyrm: GIVE THEM LUNCH MONEY / 512 ACTOR BUDGET
        # 🐉 Silver Wyrm: THREE SQUARE MEALS / LIVE DETAIL BUDGET
        # Arena actor turns are structurally known to be live performance, not deep
        # adjudication. In the extreme test configuration, give them a deliberately
        # larger but still bounded visible-output allowance and disable hidden reasoning so the model
        # cannot spend thousands of tokens thinking about a routine beat before
        # producing prose. This is role-based budgeting only: no English/vocabulary
        # inference and no secondary model. Ordinary one-to-one chat is unchanged.
        if source is SourceKind.ARENA_PEER:
            arena_tokens = self.set_arena_actor_budget(getattr(self, "arena_actor_max_tokens", 768))
            packet["max_tokens"] = arena_tokens
            packet["disable_reasoning"] = True
            packet["token_accountant"] = f"arena_actor_{arena_tokens}"
            actor_name = str(getattr(request.session, "agent_name", "Persona") or "Persona").strip()
            print(f"[Token Accountant] {actor_name} Arena turn -> {arena_tokens} visible tokens; reasoning OFF")
        elif source is SourceKind.RELATIONSHIP_SUMMARY:
            # Relationship is a bounded internal summary, not live roleplay. Hidden reasoning
            # can otherwise consume the whole completion budget before visible text appears.
            packet["max_tokens"] = 512
            packet["disable_reasoning"] = True
            packet["token_accountant"] = "relationship_summary_512"
        elif source is SourceKind.INTERNAL_CONTROL:
            # Internal control work (including the automatic new-chat greeting) is bounded
            # utility generation, not a place to spend the whole allowance on hidden thought.
            requested = getattr(request.session, "solo_detail_tokens", getattr(self, "solo_actor_max_tokens", 768))
            solo_tokens = self.set_solo_actor_budget(requested)
            packet["max_tokens"] = solo_tokens
            packet["disable_reasoning"] = True
            packet["token_accountant"] = f"solo_internal_{solo_tokens}"
        elif source in {SourceKind.USER, SourceKind.LIVE_EVENT, SourceKind.SYSTEM_EVENT}:
            requested = getattr(request.session, "solo_detail_tokens", getattr(self, "solo_actor_max_tokens", 768))
            solo_tokens = self.set_solo_actor_budget(requested)
            packet["max_tokens"] = solo_tokens
            packet["token_accountant"] = f"solo_actor_{solo_tokens}"

        try:
            raw = self.backend.generate(packet)
        except NativeBackendUnavailable as exc:
            text = f"(Native model backend unavailable: {exc})"
            return TurnResult(text=text, raw_text=text, source=source, finish_reason=None)

        text = self._visible_prose(raw)
        return TurnResult(text=text, raw_text=raw, source=source, finish_reason=self.backend.finish_reason)

    @staticmethod
    def _visible_prose(raw: str) -> str:
        # Compatibility cleanup if a model learned the old Dunoon hidden envelope from prior context.
        import re
        text = str(raw or "")
        text = re.sub(r"(?is)<!--\s*meta\s*:.*?-->", "", text)
        text = re.sub(r"(?is)^\s*```(?:json)?\s*\{.*?\}\s*```\s*", "", text)
        return text.strip()

    def infer(self, text: str, session, source: str = "user", commit_lifecycle: bool = True,
              *, scene_baseline: str = "", scene_reality: str = "", actor_brief: str = "", actor_commitment: str = "", scene_dynamics=None, scene_authority_snapshot=None, image_path: str = None) -> str:
        # commit_lifecycle remains in the public signature for old callers. Actor output itself
        # no longer mutates world state; callers commit memory/history after acceptance.
        return self.run(
            TurnRequest(text=text, session=session, source=SourceKind.coerce(source), commit_lifecycle=commit_lifecycle),
            scene_baseline=scene_baseline,
            scene_reality=scene_reality,
            actor_brief=actor_brief,
            actor_commitment=actor_commitment,
            scene_dynamics=scene_dynamics,
            scene_authority_snapshot=scene_authority_snapshot, image_path=image_path,
        ).text
