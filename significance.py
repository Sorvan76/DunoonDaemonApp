# significance.py — Primary-model semantic significance engine
from __future__ import annotations

from memory_semantics import assess_memory


def infer_ambient_mood_color(text: str, default_hex: str = '#00eaff') -> tuple[str, float]:
    """Legacy API retained for compatibility; semantic significance is handled elsewhere."""
    return default_hex, 0.0


def calculate_significance_score(text: str, session_id: str = None) -> tuple[float, list[str]]:
    if not str(text or '').strip():
        return 0.0, []
    assessment = assess_memory(text)
    score = float(assessment.get('significance', 0.0) or 0.0)
    signals = ['primary_model:semantic_significance'] if score > 0.0 else ['primary_model:semantics_unavailable']
    return round(max(0.0, min(1.0, score)), 2), signals


def get_significance_directive(text: str, session_id: str = None) -> str:
    score, signals = calculate_significance_score(text, session_id=session_id)
    if score < 0.40:
        return ''
    return f"\\n[SYSTEM NOTICE: Semantic Significance ({score:.2f}) | Signals: {', '.join(signals)}]"


def score_significance(text: str, session_id: str = None) -> float:
    return calculate_significance_score(text, session_id=session_id)[0]
