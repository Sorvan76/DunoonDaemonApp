# significance.py — Semantic Significance & Novelty Engine
import math
import threading
import numpy as np
from memory_embeddings import embed

EMA_ALPHA=0.72
_trajectory_vectors={}
_trajectory_lock=threading.Lock()
_anchor_vectors=None
_anchor_lock=threading.Lock()

SIGNIFICANCE_CONCEPTS=(
    "Information establishing a durable fact, preference, identity detail, relationship, capability, rule, world fact, project fact, or recurring context worth remembering later.",
    "A meaningful decision, commitment, promise, objective, plan, constraint, requirement, instruction, change of direction, or consequence affecting what should happen next.",
    "A major emotional, interpersonal, narrative, or character-development moment whose meaning would matter if recalled later.",
    "A material change in the state of a project, task, story, environment, problem, investigation, or ongoing situation, including an important discovery or resolution.",
    "A high-consequence event, risk, failure, breakthrough, urgent development, or exceptional outcome whose omission would materially reduce continuity.",
)
MOOD_CONCEPTS={
    '#FF2244':'Strongly tense, threatening, confrontational, fearful, or agitated emotional character.',
    '#FFAA00':'Strongly warm, joyful, friendly, affectionate, playful, or celebratory emotional character.',
    '#00EFFF':'Strongly focused, analytical, investigative, curious, technical, or discovery-oriented character.',
    '#9933FF':'Strongly melancholic, solemn, reflective, mournful, mysterious, or quietly sad emotional character.',
}

def _vec(text):
    v=embed(text)
    if not v: return None
    a=np.asarray(v,dtype=np.float64); n=np.linalg.norm(a)
    return a/n if n else None

def _sim(a,b):
    if a is None or b is None: return 0.0
    d=float(np.linalg.norm(a)*np.linalg.norm(b))
    return float(np.dot(a,b)/d) if d else 0.0

def _anchors():
    global _anchor_vectors
    with _anchor_lock:
        if _anchor_vectors is None:
            _anchor_vectors={'sig':[v for v in (_vec(x) for x in SIGNIFICANCE_CONCEPTS) if v is not None], 'mood':{k:v for k,v in ((k,_vec(x)) for k,x in MOOD_CONCEPTS.items()) if v is not None}}
        return _anchor_vectors

def _length_signal(text):
    return max(0.0,min(1.0,math.log1p(len(text.strip()))/math.log1p(600)))

def infer_ambient_mood_color(text: str, default_hex: str='#00eaff') -> tuple[str,float]:
    x=_vec(text)
    if x is None: return default_hex,0.0
    moods=_anchors()['mood']
    if not moods: return default_hex,0.0
    colour,score=max(((c,_sim(x,v)) for c,v in moods.items()),key=lambda z:z[1])
    intensity=max(0.0,min(1.0,(score-0.20)/0.55))
    return (colour,intensity) if intensity>=0.08 else (default_hex,0.0)

def calculate_significance_score(text: str, session_id: str=None) -> tuple[float,list[str]]:
    if not text or not text.strip(): return 0.0,[]
    x=_vec(text)
    if x is None: return round(0.15+0.20*_length_signal(text),2),['semantic_embedding_unavailable']
    semantic=max((_sim(x,a) for a in _anchors()['sig']),default=0.0)
    key=str(session_id) if session_id else '__global__'
    with _trajectory_lock: prior=_trajectory_vectors.get(key)
    novelty=0.5 if prior is None else max(0.0,min(1.0,1.0-_sim(x,prior)))
    structure=_length_signal(text)
    score=round(max(0.0,min(1.0,0.62*semantic+0.25*novelty+0.13*structure)),2)
    with _trajectory_lock:
        cur=_trajectory_vectors.get(key)
        updated=x if cur is None else EMA_ALPHA*cur+(1.0-EMA_ALPHA)*x
        n=np.linalg.norm(updated)
        _trajectory_vectors[key]=updated/n if n else updated
    signals=[]
    if semantic>=0.38: signals.append('semantic:durable_relevance')
    if novelty>=0.55: signals.append('semantic:context_shift')
    if structure>=0.65: signals.append('structure:developed')
    return score,signals

def get_significance_directive(text: str, session_id: str=None) -> str:
    score,signals=calculate_significance_score(text,session_id=session_id)
    if score<0.40: return ''
    return f"\\n[SYSTEM NOTICE: Semantic Significance ({score:.2f}) | Signals: {', '.join(signals) if signals else 'semantic:moderate'}]"

def score_significance(text: str, session_id: str=None) -> float:
    return calculate_significance_score(text,session_id=session_id)[0]
