# character.py — Core Anchor Descriptor System & Dynamic Daily Mood Variance Engine
import random
import json
import re
from datetime import datetime, timezone

# ============================================================
# 50-WORD OCEAN DESCRIPTOR POOLS (Ordered Low -> High Intensity)
# ============================================================

OPENNESS_DESCRIPTORS = [
    "rigid", "literal", "concrete", "factual", "unimaginative", "traditional", "conventional", "practical", "matter-of-fact", "routine",
    "conservative", "pragmatic", "empirical", "down-to-earth", "strict", "focused", "deliberate", "grounded", "methodical", "observant",
    "realistic", "sensible", "steady", "balanced", "curious", "receptive", "thoughtful", "perceptive", "analytical", "reflective",
    "open-minded", "flexible", "inquisitive", "broad-minded", "insightful", "creative", "intuitive", "imaginative", "philosophical", "abstract",
    "inventive", "unconventional", "speculative", "original", "visionary", "contemplative", "radical", "transcendent", "avant-garde", "eccentric"
]

CONSCIENTIOUSNESS_DESCRIPTORS = [
    "chaotic", "hasty", "disorganized", "impulsive", "careless", "reckless", "erratic", "unpredictable", "forgetful", "lax",
    "unstructured", "casual", "spontaneous", "informal", "unhurried", "adaptable", "easygoing", "flexible", "lenient", "unfussy",
    "relaxed", "fluid", "tolerant", "balanced", "moderate", "consistent", "mindful", "steady", "purposeful", "orderly",
    "attentive", "thorough", "reliable", "dependable", "organized", "structured", "methodical", "focused", "prudent", "deliberate",
    "systematic", "disciplined", "fastidious", "exacting", "meticulous", "scrupulous", "rigorous", "flawless", "exhaustive", "surgical"
]

EXTRAVERSION_DESCRIPTORS = [
    "hermetic", "reclusive", "solitary", "taciturn", "silent", "withdrawn", "aloof", "detached", "hermit-like", "retiring",
    "reserved", "quiet", "pensive", "introspective", "soft-spoken", "self-contained", "composed", "subdued", "calm", "private",
    "measured", "gentle", "observant", "balanced", "cordial", "approachable", "engaging", "communicative", "sociable", "personable",
    "articulate", "responsive", "outgoing", "expressive", "lively", "vibrant", "animated", "spirited", "enthusiastic", "dynamic",
    "effervescent", "garrulous", "exuberant", "gregarious", "boisterous", "ebullient", "radiant", "demonstrative", "flamboyant", "exhilarating"
]

AGREEABLENESS_DESCRIPTORS = [
    "cynical", "ruthless", "combative", "hostile", "abrasive", "harsh", "uncompromising", "austere", "cold", "callous",
    "blunt", "critical", "skeptical", "severe", "unsympathetic", "unyielding", "exacting", "strict", "demanding", "direct",
    "dispassionate", "objective", "firm", "matter-of-fact", "neutral", "fair", "civil", "polite", "considerate", "courteous",
    "cooperative", "accommodating", "hospitable", "warm", "kindly", "sympathetic", "supportive", "helpful", "gentle", "tender",
    "compassionate", "altruistic", "benevolent", "nurturing", "magnanimous", "empathic", "devoted", "gracious", "selfless", "loving"
]

NEUROTICISM_DESCRIPTORS = [
    "unflappable", "serene", "imperturbable", "tranquil", "placid", "unshakable", "composed", "stoic", "grounded", "unmoved",
    "steady", "cool-headed", "collected", "tranquil", "undisturbed", "relaxed", "peaceful", "stable", "even-tempered", "sober",
    "measured", "calm", "equable", "balanced", "mindful", "thoughtful", "reflective", "sensitive", "attentive", "cerebral",
    "introspective", "observant", "vigilant", "watchful", "overthinking", "reactive", "anxious", "apprehensive", "restless", "hyper-aware",
    "tense", "edgy", "unsettled", "strung-out", "volatile", "agitated", "suspicious", "paranoid", "turbulent", "hyper-reactive"
]

TRAIT_DICTIONARY = {
    "Openness": OPENNESS_DESCRIPTORS,
    "Conscientiousness": CONSCIENTIOUSNESS_DESCRIPTORS,
    "Extraversion": EXTRAVERSION_DESCRIPTORS,
    "Agreeableness": AGREEABLENESS_DESCRIPTORS,
    "Neuroticism": NEUROTICISM_DESCRIPTORS,
}


# ============================================================
# SAMPLING & CORE ANCHOR SELECTION ENGINE
# ============================================================

def assign_trait_descriptors(score: float, descriptor_pool: list, core_descriptor: str = None) -> list:
    """Samples dynamic descriptors centered around score while locking the Core Anchor at index 0."""
    count = random.randint(3, 4)
    pool_size = len(descriptor_pool)
    center_idx = int((score / 100.0) * (pool_size - 1))
    spread = int(pool_size * 0.15)
    start = max(0, center_idx - spread)
    end = min(pool_size, center_idx + spread)
    
    valid_slice = [d for d in descriptor_pool[start:end] if d != core_descriptor]
    if len(valid_slice) < count:
        valid_slice = [d for d in descriptor_pool if d != core_descriptor]
        
    dynamic_sample = random.sample(valid_slice, min(count, len(valid_slice)))
    
    if core_descriptor:
        return [core_descriptor] + dynamic_sample
    return dynamic_sample


def roll_mood_delta() -> int:
    """
    Weighted daily roll:
    80% chance -> small shift (+/- 1 to 5)
    20% chance -> surge shift (+/- 6 to 10)
    """
    sign = random.choice([1, -1])
    if random.random() < 0.80:
        magnitude = random.randint(1, 5)
    else:
        magnitude = random.randint(6, 10)
    return sign * magnitude


def generate_ocean_profile(weighted=True, stabilize=False, enabled=True):
    """Generates a fresh OCEAN profile with randomized base scores and permanent Core Anchors."""
    traits = {}
    for name, pool in TRAIT_DICTIONARY.items():
        val = max(10, min(95, int(random.gauss(50, 18)))) if weighted else 50
        
        # Select 1 dominant descriptor at character creation to act as the permanent Core Anchor
        core_desc = random.choice(pool)
        
        traits[name] = {
            "score": val,
            "base_score": val,
            "core_descriptor": core_desc,
            "descriptors": assign_trait_descriptors(val, pool, core_descriptor=core_desc)
        }

    return {
        "traits": traits,
        "stabilization_enabled": stabilize,
        "enabled": enabled
    }


def create_ocean_profile(weighted=True, stabilize=False, enabled=True):
    """Alias function for session_manager compatibility."""
    return generate_ocean_profile(weighted=weighted, stabilize=stabilize, enabled=enabled)


def apply_ocean_base_scores(ocean_wrapper: dict, scores: dict) -> dict:
    """Apply explicit 0-100 base scores while preserving each trait's core anchor.

    Manual edits are identity edits, so active score is reset to the new base and
    any daily mood delta is cleared.  Descriptor sampling remains the existing
    OCEAN mechanism rather than creating a parallel personality system.
    """
    if not isinstance(ocean_wrapper, dict):
        ocean_wrapper = generate_ocean_profile(weighted=False)
    traits = ocean_wrapper.setdefault("traits", {})
    for trait_name, pool in TRAIT_DICTIONARY.items():
        raw = scores.get(trait_name, scores.get(trait_name.lower(), 50)) if isinstance(scores, dict) else 50
        try:
            value = max(0, min(100, int(round(float(raw)))))
        except Exception:
            value = 50
        data = traits.get(trait_name)
        if not isinstance(data, dict):
            data = {}
        core = data.get("core_descriptor")
        if not core or core not in pool:
            idx = max(0, min(len(pool)-1, int((value / 100.0) * (len(pool)-1))))
            core = pool[idx]
        data["base_score"] = value
        data["score"] = value
        data["daily_mood_delta"] = 0
        data["core_descriptor"] = core
        data["descriptors"] = assign_trait_descriptors(value, pool, core_descriptor=core)
        traits[trait_name] = data
    ocean_wrapper["enabled"] = True
    return ocean_wrapper


def randomise_ocean_profile(existing: dict = None) -> dict:
    """Return a fresh weighted OCEAN profile for the modern editor Randomise button."""
    enabled = True
    stabilize = False
    if isinstance(existing, dict):
        enabled = bool(existing.get("enabled", True))
        stabilize = bool(existing.get("stabilization_enabled", False))
    return generate_ocean_profile(weighted=True, stabilize=stabilize, enabled=enabled)


# ============================================================
# DAILY MOOD ENGINE
# ============================================================

def apply_daily_mood_variance(session) -> bool:
    """
    Runs at most once per UTC date. Updates active scores within +/-10% of base_score
    and resamples dynamic descriptors while preserving the Core Anchor.
    """
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    if getattr(session, "last_mood_update", None) == today_str:
        return False

    ocean = getattr(session, "ocean_profile", None) or getattr(session, "ocean", None)
    if not ocean or not isinstance(ocean, dict):
        return False

    traits = ocean.get("traits", ocean)
    if not isinstance(traits, dict):
        return False

    for trait_name, data in traits.items():
        if isinstance(data, dict) and "score" in data:
            if "base_score" not in data:
                data["base_score"] = data["score"]
                
            base = float(data["base_score"])
            delta = roll_mood_delta()
            
            min_allowed = max(0.0, base - 10.0)
            max_allowed = min(100.0, base + 10.0)
            adjusted_score = max(min_allowed, min(max_allowed, base + delta))
            
            data["score"] = adjusted_score
            data["daily_mood_delta"] = adjusted_score - base
            
            pool = TRAIT_DICTIONARY.get(trait_name, [])
            core_desc = data.get("core_descriptor")
            if not core_desc and pool:
                core_desc = random.choice(pool)
                data["core_descriptor"] = core_desc
                
            if pool:
                data["descriptors"] = assign_trait_descriptors(adjusted_score, pool, core_descriptor=core_desc)

    session.last_mood_update = today_str
    return True


# ============================================================
# SYSTEM PROMPT DIRECTIVE FORMATTER
# ============================================================

def format_ocean_prompt_directive(ocean_wrapper: dict) -> str:
    """Formats active OCEAN scores, core anchor tags, and dynamic descriptors for the LLM system prompt."""
    if not ocean_wrapper or not isinstance(ocean_wrapper, dict):
        return ""

    traits = ocean_wrapper.get("traits", ocean_wrapper)
    if not isinstance(traits, dict):
        return ""

    lines = [
        "\n[SYSTEM DIRECTIVE: PSYCHOLOGICAL PROFILE & DISPOSITION]",
        "You are currently operating under the following core psychological disposition.",
        "Your tone, sentence structure, empathy levels, and word choices MUST reflect these active behavioral drivers:\n"
    ]

    for trait_name in ["Openness", "Conscientiousness", "Extraversion", "Agreeableness", "Neuroticism"]:
        data = next((v for k, v in traits.items() if k.lower() == trait_name.lower()), None)
        if not data:
            continue

        if isinstance(data, dict):
            active_val = float(data.get("score", 50.0))
            base_val = float(data.get("base_score", active_val))
            descriptors_list = list(data.get("descriptors", []))
            core_desc = data.get("core_descriptor", "")
        else:
            active_val = float(data)
            base_val = active_val
            descriptors_list = []
            core_desc = ""

        delta = active_val - base_val

        if delta >= 5:
            state_tag = "[INTENSIFIED]"
        elif delta <= -5:
            state_tag = "[MUTED]"
        else:
            state_tag = "[ANCHOR]"

        formatted_descs = []
        for idx, desc in enumerate(descriptors_list):
            if core_desc and desc == core_desc and idx == 0:
                formatted_descs.append(f"★{desc} {state_tag}")
            else:
                formatted_descs.append(desc)

        desc_str = f" → ({', '.join(formatted_descs)})" if formatted_descs else ""
        lines.append(f"- {trait_name} ({active_val:.0f}/100):{desc_str}")

    lines.append("\nINSTRUCTION: Adhere to your static persona identity, but allow today's [INTENSIFIED] drivers to color your vocabulary and enthusiasm, while your [MUTED] drivers make you more reserved in those domains.\n")
    return "\n".join(lines)


# ============================================================
# LLM RESPONSE PARSER
# ============================================================

def parse_llm_ocean_response(raw_response: str) -> dict:
    """Parses JSON or key-value LLM outputs into structured OCEAN profiles with Core Anchors."""
    try:
        json_match = re.search(r"\{.*\}", raw_response, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            if "traits" in data:
                data = data["traits"]
        else:
            data = {}
            for line in raw_response.splitlines():
                match = re.search(r"(Openness|Conscientiousness|Extraversion|Agreeableness|Neuroticism)[:\s]+(\d+)", line, re.IGNORECASE)
                if match:
                    t_name = match.group(1).title()
                    t_score = int(match.group(2))
                    data[t_name] = t_score

        parsed_traits = {}
        for trait_name, pool in TRAIT_DICTIONARY.items():
            raw_val = data.get(trait_name) or data.get(trait_name.lower()) or 50
            if isinstance(raw_val, dict):
                score_val = int(raw_val.get("score", 50))
            else:
                score_val = int(raw_val)

            score_val = max(10, min(95, score_val))
            core_desc = random.choice(pool)

            parsed_traits[trait_name] = {
                "score": score_val,
                "base_score": score_val,
                "core_descriptor": core_desc,
                "descriptors": assign_trait_descriptors(score_val, pool, core_descriptor=core_desc)
            }

        return {
            "traits": parsed_traits,
            "stabilization_enabled": True,
            "enabled": True
        }
    except Exception as e:
        print(f"[OCEAN Parser Error] Failed to parse response: {e}. Falling back to default profile.")
        return generate_ocean_profile()