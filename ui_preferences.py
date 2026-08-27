# ui_preferences.py — persistent modern UI preferences.
from __future__ import annotations
import json, os, threading
from config import DATA_DIR

CHAT_TYPEWRITER_DELAY_MS = 12

_PREF_FILE = os.path.join(DATA_DIR, 'ui_preferences.json')
_LOCK = threading.RLock()
_DEFAULTS = {
    'chat_font_family': 'Segoe UI Emoji',
    'chat_font_size': 11,
    # 🐉 Silver Wyrm: fresh installs expose hover help by default; users can still disable it.
    'show_tooltips': True,
    'last_skin': '',
    # 🐉 Silver Wyrm: OFF means the Director may actively author plausible external developments.
    'block_director_creative_freedom': False,
    # 🐉 Silver Wyrm: live Arena actor detail/pacing control.
    'arena_detail_level': 'med',
    # 🐉 Silver Wyrm: Solo detail mirrors Arena's visible token-budget scale.
    'solo_detail_level': 'med',
    # 🐉 Silver Wyrm: Solo/native model context selected in the modern shell.
    'solo_context_tokens': 16384,
    'autosave_recovery': True,
    'autoskin_enabled': False,
    'autoskin_speed': 'slow',
}


def load_ui_preferences():
    prefs = dict(_DEFAULTS)
    with _LOCK:
        try:
            with open(_PREF_FILE, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                prefs.update(raw)
        except Exception:
            pass
    family = str(prefs.get('chat_font_family') or _DEFAULTS['chat_font_family']).strip() or _DEFAULTS['chat_font_family']
    try:
        size = int(prefs.get('chat_font_size', 11))
    except Exception:
        size = 11
    prefs['chat_font_family'] = family
    prefs['chat_font_size'] = max(8, min(28, size))
    prefs['show_tooltips'] = bool(prefs.get('show_tooltips', True))
    prefs['last_skin'] = str(prefs.get('last_skin') or '').strip()
    prefs['block_director_creative_freedom'] = bool(prefs.get('block_director_creative_freedom', False))
    prefs['autosave_recovery'] = bool(prefs.get('autosave_recovery', True))
    # 🐉 Silver Wyrm: Autoskin retired during feature-freeze testing. Keep the key readable
    # for old preference files, but never allow a stale saved value to reactivate it.
    prefs['autoskin_enabled'] = False
    prefs['autoskin_speed'] = str(prefs.get('autoskin_speed') or 'slow').lower() if str(prefs.get('autoskin_speed') or 'slow').lower() in {'slow','medium','fast'} else 'slow'
    level = str(prefs.get('arena_detail_level') or 'med').strip().lower()
    prefs['arena_detail_level'] = level if level in {'minimal', 'light', 'low', 'med', 'high', 'very_high', 'ultra', 'max'} else 'med'
    solo_level = str(prefs.get('solo_detail_level') or 'med').strip().lower()
    prefs['solo_detail_level'] = solo_level if solo_level in {'minimal', 'light', 'low', 'med', 'high', 'very_high', 'ultra', 'max'} else 'med'
    try:
        ctx = int(prefs.get('solo_context_tokens', 16384))
    except Exception:
        ctx = 16384
    prefs['solo_context_tokens'] = max(1024, min(131072, ctx))
    return prefs


def save_ui_preferences(*, chat_font_family=None, chat_font_size=None, show_tooltips=None, last_skin=None, block_director_creative_freedom=None, arena_detail_level=None, solo_detail_level=None, solo_context_tokens=None, autosave_recovery=None, autoskin_enabled=None, autoskin_speed=None):
    prefs = load_ui_preferences()
    if chat_font_family is not None:
        family = str(chat_font_family or '').strip()
        if family:
            prefs['chat_font_family'] = family
    if chat_font_size is not None:
        try:
            prefs['chat_font_size'] = max(8, min(28, int(chat_font_size)))
        except Exception:
            pass
    if show_tooltips is not None:
        prefs['show_tooltips'] = bool(show_tooltips)
    if last_skin is not None:
        prefs['last_skin'] = str(last_skin or '').strip()
    if block_director_creative_freedom is not None:
        prefs['block_director_creative_freedom'] = bool(block_director_creative_freedom)
    if autosave_recovery is not None: prefs['autosave_recovery']=bool(autosave_recovery)
    if autoskin_enabled is not None: prefs['autoskin_enabled']=False
    if autoskin_speed is not None:
        _sp=str(autoskin_speed).lower()
        if _sp in {'slow','medium','fast'}: prefs['autoskin_speed']=_sp
    if arena_detail_level is not None:
        level = str(arena_detail_level or '').strip().lower()
        if level in {'minimal', 'light', 'low', 'med', 'high', 'very_high', 'ultra', 'max'}:
            prefs['arena_detail_level'] = level
    if solo_detail_level is not None:
        level = str(solo_detail_level or '').strip().lower()
        if level in {'minimal', 'light', 'low', 'med', 'high', 'very_high', 'ultra', 'max'}:
            prefs['solo_detail_level'] = level
    if solo_context_tokens is not None:
        try:
            prefs['solo_context_tokens'] = max(1024, min(131072, int(solo_context_tokens)))
        except Exception:
            pass
    with _LOCK:
        try:
            os.makedirs(os.path.dirname(_PREF_FILE), exist_ok=True)
            tmp = _PREF_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(prefs, f, indent=2, ensure_ascii=False)
                f.flush()
                try: os.fsync(f.fileno())
                except Exception: pass
            os.replace(tmp, _PREF_FILE)
        except Exception as exc:
            print(f'[UI Preferences Warning]: {exc}')
    return prefs


def english_ui(uk_text, us_text):
    """Compatibility helper: dunoon daemon uses UK interface spelling."""
    return uk_text
