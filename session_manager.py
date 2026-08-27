# session_manager.py — Master Session Registry & Persistence Engine
import os
import json
import uuid
import shutil
import threading
import tempfile
from datetime import datetime, timezone
from character import create_ocean_profile
from config import DATA_DIR, SESSIONS_FILE, SESSIONS_DIR, ensure_dirs
from memory_transactions import replace_with_retry

ensure_dirs()

# Session registries are process-global state. Share one re-entrant lock even if a test,
# dialog, or future subsystem creates more than one SessionManager instance.
_SESSION_REGISTRY_LOCK = threading.RLock()

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
            agent_name=data.get("agent_name", ""),
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
            physiology=data.get("physiology", ""),
            powers=data.get("powers", ""),
            location=data.get("location", ""),
            threat=data.get("threat", ""),
            opportunity=data.get("opportunity", ""),
            is_deceased=data.get("is_deceased", False),
            narrative_freedom=data.get("narrative_freedom", False),
            avatar_path=data.get("avatar_path", ""),
            showcase_quote=data.get("showcase_quote", ""),
            pinned_quotes=data.get("pinned_quotes", []),
            voice_mode=data.get("voice_mode", "Sonia (UK Neural)"),
            dream_guidance=data.get("dream_guidance", ""),
            last_dream_at=data.get("last_dream_at", ""),
            last_dream_report=data.get("last_dream_report", {}),
            ocean_controls_locked=data.get("ocean_controls_locked", False),
            resurrection_mode=data.get("resurrection_mode", ""),
            resurrected_at=data.get("resurrected_at", ""),
            resurrection_count=data.get("resurrection_count", 0)
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
            "agent_name": getattr(self, "agent_name", ""),
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
            "physiology": getattr(self, "physiology", ""),
            "powers": getattr(self, "powers", ""),
            "location": getattr(self, "location", ""),
            "threat": getattr(self, "threat", ""),
            "opportunity": getattr(self, "opportunity", ""),
            "is_deceased": getattr(self, "is_deceased", False),
            "narrative_freedom": getattr(self, "narrative_freedom", False),
            "avatar_path": getattr(self, "avatar_path", ""),
            "showcase_quote": getattr(self, "showcase_quote", ""),
            "pinned_quotes": list(getattr(self, "pinned_quotes", []) or []),
            "voice_mode": getattr(self, "voice_mode", "Sonia (UK Neural)"),
            "last_mood_update": getattr(self, "last_mood_update", None),
            "dream_guidance": getattr(self, "dream_guidance", ""),
            "last_dream_at": getattr(self, "last_dream_at", ""),
            "last_dream_report": getattr(self, "last_dream_report", {}),
            "ocean_controls_locked": bool(getattr(self, "ocean_controls_locked", False)),
            "resurrection_mode": str(getattr(self, "resurrection_mode", "") or ""),
            "resurrected_at": str(getattr(self, "resurrected_at", "") or ""),
            "resurrection_count": int(getattr(self, "resurrection_count", 0) or 0)
        }

    def __init__(self, id=None, name=None, messages=None, created_at=None, private=False, 
                 system_prompt="", agent_name="", ocean_profile=None, primacy_count=0, 
                 primacy_enabled=True, backend="Native C++ Server (NVIDIA)", 
                 model_path="", psychology_mode="ocean_sensitive", share_insights=False,
                 blind_to_others=False, backstory="", eto_enabled=True, mortality_enabled=False,
                 physiology="",
                 powers="", location="", threat="",
                 opportunity="", is_deceased=False, narrative_freedom=False, avatar_path="",
                 showcase_quote="", pinned_quotes=None, voice_mode="Sonia (UK Neural)",
                 dream_guidance="", last_dream_at="", last_dream_report=None,
                 ocean_controls_locked=False, resurrection_mode="", resurrected_at="",
                 resurrection_count=0):
        
        self.window = None
        self.id = id or str(uuid.uuid4())
        self.name = name or f"Chat {self.id[:6]}"
        self.messages = messages or []
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.private = private
        self.system_prompt = system_prompt
        self.agent_name = str(agent_name or "")
        self.psychology_mode = psychology_mode
        self.share_insights = share_insights
        self.blind_to_others = blind_to_others
        self.backstory = backstory or ""
        self.eto_enabled = bool(eto_enabled)
        self.mortality_enabled = bool(mortality_enabled)
        self.physiology = str(physiology or "")
        self.powers = str(powers or "")
        self.location = location or ""
        self.threat = threat or ""
        self.opportunity = opportunity or ""
        self.is_deceased = bool(is_deceased)
        # OFF by default: the user owns unstated consequential world facts unless
        # collaborative worldbuilding is explicitly enabled for this persona.
        self.narrative_freedom = bool(narrative_freedom)
        self.avatar_path = str(avatar_path or "")
        self.showcase_quote = str(showcase_quote or "")
        self.pinned_quotes = list(pinned_quotes or [])
        self.voice_mode = str(voice_mode or "Sonia (UK Neural)")
        self.dream_guidance = str(dream_guidance or "")
        self.last_dream_at = str(last_dream_at or "")
        self.last_dream_report = dict(last_dream_report or {})
        # Human-edit guard only. The daily mood engine intentionally ignores it.
        self.ocean_controls_locked = bool(ocean_controls_locked)
        self.resurrection_mode = str(resurrection_mode or "")
        self.resurrected_at = str(resurrected_at or "")
        self.resurrection_count = int(resurrection_count or 0)

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
        self._registry_lock = _SESSION_REGISTRY_LOCK
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
        # 🐉 Silver Wyrm: fresh installs start with an intentionally blank persona.
        # Nothing in Persona & OCEAN is silently authored for the user.
        self.sessions = {}
        starter = Session(
            name="New persona",
            agent_name="",
            system_prompt="",
            physiology="",
            powers="",
            psychology_mode="ocean_sensitive"
        )
        self.sessions[starter.id] = starter
        self._save()

    def _save(self):
        with self._registry_lock:
            return self._save_unlocked()

    def _save_unlocked(self):
        data = {"sessions": [s.to_dict() for s in self.sessions.values() if not s.private]}
        target = SESSIONS_FILE
        tmp = None
        backup = f"{target}.bak"
        try:
            directory = os.path.dirname(target) or "."
            os.makedirs(directory, exist_ok=True)
            if os.path.exists(target):
                try:
                    with open(target, "r", encoding="utf-8") as existing:
                        current_data = json.load(existing)
                    if isinstance(current_data, dict) and isinstance(current_data.get("sessions", []), list):
                        shutil.copy2(target, backup)
                except Exception:
                    # Never overwrite a known-good backup with a damaged registry.
                    pass
            fd, tmp = tempfile.mkstemp(prefix=os.path.basename(target) + ".tmp.", dir=directory)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
            replace_with_retry(tmp, target)
            tmp = None
            return True
        except Exception as e:
            try:
                if tmp and os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
            print(f"[SessionManager Error] Save failed: {e}")
            return False

    def create_session(self, name=None, private=False, weighted_ocean=True, primacy_enabled=True):
        mode = "ocean_sensitive" if weighted_ocean else "grey_analytical"
        s = Session(name=name, private=private, primacy_enabled=primacy_enabled, psychology_mode=mode)
        s.append_system("New session initialized.")
        self.sessions[s.id] = s
        self._save()
        return s

    def delete_session(self, session_id):
        sid = str(session_id or "")
        if not sid:
            return False
        try:
            from memory_transactions import bump_memory_generation
            bump_memory_generation(sid)
        except Exception:
            pass
        with self._registry_lock:
            if sid not in self.sessions:
                return False
            del self.sessions[sid]
            self._save_unlocked()
        # The UI promises permanent deletion. Remove the persona-scoped data only after
        # the registry has safely stopped referring to it. UUID-like session ids cannot escape.
        base = os.path.realpath(SESSIONS_DIR)
        target = os.path.realpath(os.path.join(base, sid))
        try:
            if os.path.commonpath([base, target]) == base and target != base:
                shutil.rmtree(target, ignore_errors=False) if os.path.isdir(target) else None
        except Exception as exc:
            print(f"[SessionManager Warning] Persona registry deleted but data folder cleanup failed for {sid}: {exc}")
            return False
        return True

    def master_purge(self):
        """Erase all live persona/history state and reseed one blank persona.

        Exported backups outside Dunoon's data directory are intentionally untouched.
        """
        with self._registry_lock:
            old_ids = list(self.sessions.keys())
            for sid in old_ids:
                try:
                    from memory_transactions import bump_memory_generation
                    bump_memory_generation(str(sid))
                except Exception:
                    pass
            self.sessions = {}

            # Remove every app-owned live-history subtree. This includes session registries,
            # persona vaults/media, Arena SceneStore state, diagnostics, recovery snapshots,
            # audio cache and any legacy vault directory. Manual exports outside DATA_DIR survive.
            for name in ('sessions','scenes','recovery','diagnostics','audio_cache','vaults','backups'):
                target = os.path.realpath(os.path.join(DATA_DIR, name))
                base = os.path.realpath(DATA_DIR)
                try:
                    if os.path.commonpath([base, target]) == base and target != base and os.path.exists(target):
                        shutil.rmtree(target, ignore_errors=False)
                except FileNotFoundError:
                    pass
            ensure_dirs()
            self._seed_default_companion()
            for sess in self.sessions.values():
                sess.session_manager = self
        return True

    def rename_session(self, session_id, new_name):
        if session_id in self.sessions:
            self.sessions[session_id].name = new_name
            self._save()

    def save(self):
        """Persist persona/session metadata and report whether the durable write succeeded."""
        return self._save()

    def reload_from_disk(self):
        """Reload the durable persona registry after an external state restore."""
        with self._registry_lock:
            self.sessions = {}
            self._load()
            for sess in self.sessions.values():
                sess.session_manager = self
        return True

    def list_sessions(self):
        return sorted(self.sessions.values(), key=lambda x: x.created_at)

    def get(self, session_id):
        return self.sessions.get(session_id)