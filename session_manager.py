# session_manager.py — Master Session Registry & Persistence Engine
import os
import json
import uuid
import shutil
from datetime import datetime, timezone
from character import create_ocean_profile
from config import SESSIONS_FILE, ensure_dirs

ensure_dirs()

class Session:
    @classmethod
    def from_dict(cls, data):
        s = cls(
            id=data.get("id"),
            name=data.get("name"),
            messages=data.get("messages", []),
            created_at=data.get("created_at"),
            private=data.get("private", False),
            system_prompt=data.get("system_prompt", ""),
            agent_name=data.get("agent_name", "Kylo"),
            ocean_profile=data.get("ocean_profile"),
            primacy_count=data.get("primacy_count", 0),
            primacy_enabled=data.get("primacy_enabled", True),
            backend=data.get("backend", "Native C++ Server (NVIDIA)"),
            model_path=data.get("model_path", ""),
            psychology_mode=data.get("psychology_mode", "ocean_sensitive"),
            share_insights=data.get("share_insights", False),
            blind_to_others=data.get("blind_to_others", False),
            backstory=data.get("backstory", ""),
            eto_enabled=data.get("eto_enabled", True),
            mortality_enabled=data.get("mortality_enabled", False),
            physiology=data.get("physiology", "Normal (Standard Organic humanoid)"),
            powers=data.get("powers", "None (Standard human baseline capabilities)"),
            location=data.get("location", ""),
            threat=data.get("threat", ""),
            opportunity=data.get("opportunity", ""),
            is_deceased=data.get("is_deceased", False),
            narrative_freedom=data.get("narrative_freedom", False)
        )
        s.last_mood_update = data.get("last_mood_update", None)
        return s

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "messages": self.messages,
            "created_at": self.created_at,
            "private": self.private,
            "system_prompt": self.system_prompt,
            "agent_name": getattr(self, "agent_name", "Kylo"),
            "ocean_profile": self.ocean_profile,
            "primacy_count": self.primacy_count,
            "primacy_enabled": self.primacy_enabled,
            "backend": self.backend,
            "model_path": self.model_path,
            "psychology_mode": getattr(self, "psychology_mode", "ocean_sensitive"),
            "share_insights": getattr(self, "share_insights", False),
            "blind_to_others": getattr(self, "blind_to_others", False),
            "backstory": getattr(self, "backstory", ""),
            "eto_enabled": getattr(self, "eto_enabled", True),
            "mortality_enabled": getattr(self, "mortality_enabled", False),
            "physiology": getattr(self, "physiology", "Normal (Standard Organic humanoid)"),
            "powers": getattr(self, "powers", "None (Standard human baseline capabilities)"),
            "location": getattr(self, "location", ""),
            "threat": getattr(self, "threat", ""),
            "opportunity": getattr(self, "opportunity", ""),
            "is_deceased": getattr(self, "is_deceased", False),
            "narrative_freedom": getattr(self, "narrative_freedom", False),
            "last_mood_update": getattr(self, "last_mood_update", None)
        }

    def __init__(self, id=None, name=None, messages=None, created_at=None, private=False, 
                 system_prompt="", agent_name="Kylo", ocean_profile=None, primacy_count=0, 
                 primacy_enabled=True, backend="Native C++ Server (NVIDIA)", 
                 model_path="", psychology_mode="ocean_sensitive", share_insights=False,
                 blind_to_others=False, backstory="", eto_enabled=True, mortality_enabled=False,
                 physiology="Normal (Standard Organic humanoid)",
                 powers="None (Standard human baseline capabilities)", location="", threat="",
                 opportunity="", is_deceased=False, narrative_freedom=False):
        
        self.window = None
        self.id = id or str(uuid.uuid4())
        self.name = name or f"Chat {self.id[:6]}"
        self.messages = messages or []
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.private = private
        self.system_prompt = system_prompt
        self.agent_name = agent_name or "Kylo"
        self.psychology_mode = psychology_mode
        self.share_insights = share_insights
        self.blind_to_others = blind_to_others
        self.backstory = backstory or ""
        self.eto_enabled = bool(eto_enabled)
        self.mortality_enabled = bool(mortality_enabled)
        self.physiology = physiology or "Normal (Standard Organic humanoid)"
        self.powers = powers or "None (Standard human baseline capabilities)"
        self.location = location or ""
        self.threat = threat or ""
        self.opportunity = opportunity or ""
        self.is_deceased = bool(is_deceased)
        # OFF by default: the user owns unstated consequential world facts unless
        # collaborative worldbuilding is explicitly enabled for this persona.
        self.narrative_freedom = bool(narrative_freedom)

        if self.psychology_mode == "grey_analytical":
            self.ocean_profile = {
                "traits": {
                    "Openness": {"score": 50.0, "base_score": 50.0, "descriptors": ["Analytical"], "core_descriptor": "Analytical"},
                    "Conscientiousness": {"score": 50.0, "base_score": 50.0, "descriptors": ["Methodical"], "core_descriptor": "Methodical"},
                    "Extraversion": {"score": 50.0, "base_score": 50.0, "descriptors": ["Reserved"], "core_descriptor": "Reserved"},
                    "Agreeableness": {"score": 50.0, "base_score": 50.0, "descriptors": ["Objective"], "core_descriptor": "Objective"},
                    "Neuroticism": {"score": 50.0, "base_score": 50.0, "descriptors": ["Calm"], "core_descriptor": "Calm"},
                },
                "stabilization_enabled": True,
                "enabled": True
            }
        else:
            weighted = ("ocean" in self.psychology_mode)
            self.ocean_profile = ocean_profile or create_ocean_profile(weighted=weighted)

        self.primacy_count = primacy_count
        self.primacy_enabled = primacy_enabled
        self.backend = backend
        self.model_path = model_path
        self.last_mood_update = None

    def _append(self, role, text):
        self.messages.append({
            "role": role,
            "text": text,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    def append_user(self, text):
        self._append("user", text)

    def append_roxie(self, text):
        self._append("assistant", text)

    def append_system(self, text):
        self._append("system", text)

    def get_history(self, limit=12):
        history = []
        for m in self.messages[-limit:]:
            if isinstance(m, dict):
                role = m.get("role", "user")
                if role in ("roxie", "Kylo", "agent", "assistant"):
                    role = "assistant"
                elif role != "system":
                    role = "user"
                
                text = m.get("text") or m.get("content") or ""
                if text.strip():
                    history.append({"role": role, "content": text.strip()})
        return history


class SessionManager:
    def __init__(self):
        self.sessions = {}
        self.controller_instance = None
        self._load()

    def _load(self):
        if not os.path.exists(SESSIONS_FILE):
            self._seed_default_companion()
            return

        data = None
        load_error = None
        for candidate in (SESSIONS_FILE, f"{SESSIONS_FILE}.bak"):
            if not os.path.exists(candidate):
                continue
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    raw = f.read().strip()
                if not raw:
                    raise ValueError("empty session registry")
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and isinstance(parsed.get("sessions", []), list):
                    data = parsed
                    if candidate.endswith(".bak"):
                        print("[SessionManager] Recovered sessions from backup registry.")
                    break
            except Exception as e:
                load_error = e

        if data is None:
            print(f"[SessionManager Warning] Registry unreadable: {load_error}")
            self._seed_default_companion()
            return

        loaded_sessions = data.get("sessions", [])
        if not loaded_sessions:
            self._seed_default_companion()
            return

        for record in loaded_sessions:
            try:
                sess = Session.from_dict(record)
                self.sessions[sess.id] = sess
            except Exception as e:
                print(f"[SessionManager Warning] Skipped damaged session record: {e}")

        if not self.sessions:
            self._seed_default_companion()

    def _seed_default_companion(self):
        self.sessions = {}
        kylo_sess = Session(
            name="Kylo (Primary Autonomous Companion)",
            agent_name="Kylo",
            system_prompt="You are Kylo, an insightful, adaptive, and highly loyal local AI assistant.",
            psychology_mode="ocean_sensitive"
        )
        kylo_sess.append_system("Kylo assistant initialized. Ready to collaborate, Traveller!")
        self.sessions[kylo_sess.id] = kylo_sess
        self._save()

    def _save(self):
        data = {"sessions": [s.to_dict() for s in self.sessions.values() if not s.private]}
        target = SESSIONS_FILE
        tmp = f"{target}.tmp"
        backup = f"{target}.bak"
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if os.path.exists(target):
                try:
                    with open(target, "r", encoding="utf-8") as existing:
                        current_data = json.load(existing)
                    if isinstance(current_data, dict) and isinstance(current_data.get("sessions", []), list):
                        shutil.copy2(target, backup)
                except Exception:
                    # Never overwrite a known-good backup with a damaged registry.
                    pass
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
            os.replace(tmp, target)
        except Exception as e:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
            print(f"[SessionManager Error] Save failed: {e}")

    def create_session(self, name=None, private=False, weighted_ocean=True, primacy_enabled=True):
        mode = "ocean_sensitive" if weighted_ocean else "grey_analytical"
        s = Session(name=name, private=private, primacy_enabled=primacy_enabled, psychology_mode=mode)
        s.append_system("New session initialized.")
        self.sessions[s.id] = s
        self._save()
        return s

    def delete_session(self, session_id):
        if session_id in self.sessions:
            del self.sessions[session_id]
            self._save()

    def rename_session(self, session_id, new_name):
        if session_id in self.sessions:
            self.sessions[session_id].name = new_name
            self._save()

    def list_sessions(self):
        return sorted(self.sessions.values(), key=lambda x: x.created_at)

    def get(self, session_id):
        return self.sessions.get(session_id)