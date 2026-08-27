from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile

_ALLOWED_FIELDS = {
    'agent_name': str,
    'system_prompt': str,
    'ocean_profile': dict,
    'psychology_mode': str,
    'share_insights': bool,
    'blind_to_others': bool,
    'backstory': str,
    'eto_enabled': bool,
    'mortality_enabled': bool,
    'physiology': str,
    'powers': str,
    'narrative_freedom': bool,
    'dream_guidance': str,
    'ocean_controls_locked': bool,
}


def _coerce_field(name, value):
    expected = _ALLOWED_FIELDS[name]
    if expected is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value or '').strip().casefold()
        if text in {'true', '1', 'yes', 'on'}:
            return True
        if text in {'false', '0', 'no', 'off', ''}:
            return False
        raise ValueError(f'Invalid boolean value for {name}: {value!r}')
    if expected is str:
        return str(value or '')
    if expected is dict:
        return dict(value) if isinstance(value, dict) else {}
    return value


def export_persona(session, path, include_memories=False):
    data = session.to_dict() if hasattr(session, 'to_dict') else dict(session.__dict__)
    data.pop('messages', None)
    payload = {key: data.get(key) for key in _ALLOWED_FIELDS}
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('persona.json', json.dumps(payload, indent=2, ensure_ascii=False))
        avatar = str(getattr(session, 'avatar_path', '') or '')
        if avatar and os.path.isfile(avatar):
            z.write(avatar, 'avatar' + os.path.splitext(avatar)[1].lower())
        if include_memories:
            from config import get_session_vault_dir
            vault_dir = get_session_vault_dir(getattr(session, 'id', ''))
            for root, _, files in os.walk(vault_dir):
                for fn in files:
                    z.write(os.path.join(root, fn), os.path.join('memories', fn))
    return path


def import_persona_package(session, path):
    """Import only approved persona fields. Session identity/history can never be overwritten."""
    with zipfile.ZipFile(path, 'r') as z:
        names = set(z.namelist())
        if 'persona.json' not in names:
            raise ValueError('Persona package does not contain persona.json')
        data = json.loads(z.read('persona.json').decode('utf-8'))
        if not isinstance(data, dict):
            raise ValueError('persona.json must contain an object')
        for key, value in data.items():
            if key not in _ALLOWED_FIELDS:
                continue
            setattr(session, key, _coerce_field(key, value))

        avatar_names = [
            n for n in names
            if os.path.basename(n).lower().startswith('avatar.')
            and '/' not in n.strip('/') and '\\' not in n.strip('\\')
        ]
        if avatar_names:
            from persona_media import set_persona_avatar
            member = avatar_names[0]
            suffix = os.path.splitext(member)[1].lower()
            if suffix not in {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}:
                raise ValueError('Unsupported avatar type in persona package')
            td = tempfile.mkdtemp(prefix='dunoonpersona_')
            try:
                avatar_path = os.path.join(td, 'avatar' + suffix)
                with open(avatar_path, 'wb') as fh:
                    fh.write(z.read(member))
                set_persona_avatar(session, avatar_path)
            finally:
                shutil.rmtree(td, ignore_errors=True)
    return session
