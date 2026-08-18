# state_engine.py — Structured Synthetic State Engine
import json
import os
import re
from typing import Dict, Any
from config import STATE_MATRIX_FILE


class SyntheticStateEngine:
    """Mutable state driven by structured numeric telemetry, never raw-text keyword heuristics."""

    ALLOWED_STATE_KEYS = {"warmth", "directness", "analytical_depth", "cognitive_focus", "formality"}

    def __init__(self, state_file_path: str = STATE_MATRIX_FILE):
        self.state_file_path = state_file_path
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        if os.path.exists(self.state_file_path):
            try:
                with open(self.state_file_path, 'r', encoding='utf-8') as f:
                    data=json.load(f)
                    return data if isinstance(data,dict) else {}
            except Exception:
                return {}
        return {}

    def save_state(self) -> None:
        os.makedirs(os.path.dirname(self.state_file_path), exist_ok=True)
        tmp=f"{self.state_file_path}.tmp"
        with open(tmp,'w',encoding='utf-8') as f:
            json.dump(self.state,f,indent=2)
        os.replace(tmp,self.state_file_path)

    @staticmethod
    def _extract_meta(model_response: str) -> Dict[str, Any]:
        if not model_response:
            return {}
        m=re.search(r'<!--\s*meta\s*:\s*(\{.*?\})\s*-->',str(model_response),flags=re.I|re.S)
        if not m:
            return {}
        try:
            data=json.loads(m.group(1)); return data if isinstance(data,dict) else {}
        except Exception:
            return {}

    def evaluate_turn_heuristics(self, user_query: str, model_response: str) -> None:
        """Backward-compatible name; consumes only optional `state_delta` telemetry."""
        meta=self._extract_meta(model_response)
        deltas=meta.get('state_delta',{})
        if not isinstance(deltas,dict):
            return
        bounded={}
        for key,value in deltas.items():
            if key not in self.ALLOWED_STATE_KEYS:
                continue
            try: delta=float(value)
            except (TypeError,ValueError): continue
            bounded[key]=max(-0.08,min(0.08,delta))
        if bounded:
            self.update_mood(bounded)

    def update_mood(self, sentiment_delta: Dict[str,float]) -> None:
        locks=self.state.get('controller_locks',{})
        if locks.get('freeze_all_moods',False): return
        active=self.state.get('active_mood',{})
        locked=locks.get('locked_traits',{})
        try: reactivity=float(self.state.get('genetics',{}).get('reactivity',0.5))
        except (TypeError,ValueError): reactivity=0.5
        reactivity=max(0.0,min(1.0,reactivity))
        changed=False
        for key,delta in sentiment_delta.items():
            if key in active and not locked.get(key,False):
                try: current=float(active[key]); delta=float(delta)
                except (TypeError,ValueError): continue
                active[key]=round(max(0.0,min(1.0,current+(delta*reactivity))),2); changed=True
        if changed: self.save_state()

    def generate_system_prompt_directive(self) -> str:
        self.state=self._load_state()
        mood=self.state.get('active_mood',{})
        directives=[]
        vals={k:float(mood.get(k,0.5)) for k in self.ALLOWED_STATE_KEYS}
        if vals['warmth']>0.7: directives.append('Maintain a notably warm, affiliative interpersonal manner.')
        elif vals['warmth']<0.3: directives.append('Maintain a notably detached interpersonal manner.')
        if vals['directness']>0.7: directives.append('Prefer concise, direct expression.')
        elif vals['directness']<0.3: directives.append('Allow more exploratory and indirect expression.')
        if vals['analytical_depth']>0.7: directives.append('Use deeper technical or conceptual analysis where relevant.')
        if vals['cognitive_focus']>0.7: directives.append('Stay tightly focused on the active objective and relevant evidence.')
        if vals['formality']<0.35: directives.append('Use relaxed, natural phrasing.')
        elif vals['formality']>0.75: directives.append('Use a more formal, deliberate register.')
        goals=[g.get('description') for g in self.state.get('long_term_agenda',[]) if isinstance(g,dict) and g.get('status')=='active' and g.get('description')]
        goal_text='\nInternal Objectives:\n- '+'\n- '.join(goals[:2]) if goals else ''
        return f"[SYSTEM STATE DIRECTIVE: {' '.join(directives)}]{goal_text}"
