from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import tempfile
import threading
import zipfile
from datetime import datetime, timezone

from config import DATA_DIR, BASE_DIR, SESSIONS_DIR, SESSIONS_FILE
from memory_transactions import memory_transaction

BACKUP_DIR = os.path.join(DATA_DIR, 'backups')
AUTOSAVE_DIR = os.path.join(DATA_DIR, 'recovery')
RECOVERY_MANIFEST = os.path.join(AUTOSAVE_DIR, 'manifest.json')
RECOVERY_REGISTRY = os.path.join(AUTOSAVE_DIR, 'sessions.autosave.json')
RECOVERY_SESSION_ROOT = os.path.join(AUTOSAVE_DIR, 'sessions')
_RECOVERY_LOCK = threading.RLock()


def _stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def _write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + '.tmp.', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except Exception:
                pass
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass
        raise


def _atomic_copy_file(src: str, dst: str):
    directory = os.path.dirname(dst) or '.'
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(dst) + '.tmp.', dir=directory)
    os.close(fd)
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        raise


def _archive_name(path: str) -> str:
    """Return a stable forward-slash archive path for app-owned files."""
    return str(path or '').replace('\\', '/').replace(os.sep, '/')


def _session_registry_snapshot(session_manager=None):
    """Capture the durable persona registry and the persona ids it authorises."""
    lock = getattr(session_manager, '_registry_lock', None)

    def capture():
        if session_manager is not None:
            saver = getattr(session_manager, '_save_unlocked', None)
            if callable(saver):
                if not saver():
                    raise OSError('Could not persist the persona registry before backup.')
            else:
                saver = getattr(session_manager, 'save', None)
                if callable(saver) and not saver():
                    raise OSError('Could not persist the persona registry before backup.')
        if not os.path.exists(SESSIONS_FILE):
            raise FileNotFoundError('Persona registry is missing; a complete backup cannot be created.')
        with open(SESSIONS_FILE, 'rb') as fh:
            raw = fh.read()
        try:
            payload = json.loads(raw.decode('utf-8'))
        except Exception as exc:
            raise ValueError('Persona registry is unreadable; backup aborted.') from exc
        rows = payload.get('sessions') if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ValueError('Persona registry is malformed; backup aborted.')
        ids = []
        for row in rows:
            if isinstance(row, dict):
                sid = str(row.get('id') or '').strip()
                if sid and sid not in ids:
                    ids.append(sid)
        return raw, ids

    if lock is None:
        return capture()
    with lock:
        return capture()


def create_state_backup(destination=None, session_manager=None):
    """Create a restorable snapshot of personas, memory, lore and app-owned state."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = destination or os.path.join(BACKUP_DIR, f'dunoon-backup-{_stamp()}.zip')

    registry_raw, registry_ids = _session_registry_snapshot(session_manager)
    registry_arc = _archive_name(os.path.relpath(SESSIONS_FILE, BASE_DIR))
    skip_roots = {os.path.realpath(BACKUP_DIR), os.path.realpath(AUTOSAVE_DIR), os.path.realpath(SESSIONS_DIR)}

    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        # 🐉 Silver Wyrm: the registry is the map from persona identity to every persona-scoped
        # vault and media directory. A backup without it preserves treasure but loses its owners.
        z.writestr(registry_arc, registry_raw)

        if os.path.isdir(DATA_DIR):
            # 🐉 Silver Wyrm: non-persona state can be copied directly; persona directories are
            # copied separately under their memory transaction so each vault snapshot is coherent.
            for root, dirs, files in os.walk(DATA_DIR):
                real_root = os.path.realpath(root)
                dirs[:] = [
                    d for d in dirs
                    if not any(
                        os.path.realpath(os.path.join(root, d)) == skip
                        or os.path.realpath(os.path.join(root, d)).startswith(skip + os.sep)
                        for skip in skip_roots
                    )
                ]
                if any(real_root == skip or real_root.startswith(skip + os.sep) for skip in skip_roots):
                    continue
                for fn in files:
                    src = os.path.join(root, fn)
                    if os.path.realpath(src) == os.path.realpath(path):
                        continue
                    arc = _archive_name(os.path.relpath(src, BASE_DIR))
                    z.write(src, arc)

        for sid in registry_ids:
            sess_dir = os.path.join(SESSIONS_DIR, sid)
            if not os.path.isdir(sess_dir):
                continue
            with memory_transaction(sid):
                for root, _, files in os.walk(sess_dir):
                    for fn in files:
                        src = os.path.join(root, fn)
                        arc = _archive_name(os.path.relpath(src, BASE_DIR))
                        z.write(src, arc)

        for fn in ('skin.json', 'custom_skins.json'):
            src = os.path.join(BASE_DIR, fn)
            if os.path.exists(src):
                z.write(src, fn)
    return path


def _allowed_backup_member(member: str) -> bool:
    norm = os.path.normpath(str(member or '').replace('\\', '/')).replace('\\', '/')
    if not norm or norm.startswith('../') or norm == '..' or os.path.isabs(norm):
        return False
    return norm == 'data' or norm.startswith('data/') or norm in {'skin.json', 'custom_skins.json'}


def restore_state_backup(path):
    """Restore a complete app-state backup without allowing archive paths to escape app data."""
    registry_arc = _archive_name(os.path.relpath(SESSIONS_FILE, BASE_DIR))
    with zipfile.ZipFile(path, 'r') as z:
        infos = z.infolist()
        members = {_archive_name(os.path.normpath(str(info.filename or '').replace('\\', '/'))) for info in infos}
        if registry_arc not in members:
            raise ValueError('Backup is incomplete: persona registry is missing. Personas cannot be restored from this archive.')

        for info in infos:
            if not _allowed_backup_member(info.filename):
                raise ValueError(f'Backup contains disallowed path: {info.filename}')
            # 🐉 Silver Wyrm: a friendly-looking archive entry must never become a filesystem escape hatch.
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise ValueError(f'Backup contains symlink entry: {info.filename}')

        try:
            registry_payload = json.loads(z.read(registry_arc).decode('utf-8'))
        except Exception as exc:
            raise ValueError('Backup persona registry is unreadable.') from exc
        if not isinstance(registry_payload, dict) or not isinstance(registry_payload.get('sessions'), list):
            raise ValueError('Backup persona registry is malformed.')

        z.extractall(BASE_DIR)
    return True


def create_diagnostics_bundle(destination=None, include_private=False):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = destination or os.path.join(BACKUP_DIR, f'dunoon-diagnostics-{_stamp()}.zip')
    payload = {
        'created_at': datetime.now(timezone.utc).isoformat(),
        'python': sys.version,
        'platform': platform.platform(),
        'machine': platform.machine(),
        'include_private': bool(include_private),
    }
    try:
        from config import ACTIVE_HARDWARE_BACKEND
        payload['hardware_backend'] = ACTIVE_HARDWARE_BACKEND
    except Exception:
        pass
    try:
        version_path = os.path.join(BASE_DIR, 'VERSION.txt')
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            bundled_version = os.path.join(sys._MEIPASS, 'VERSION.txt')
            if os.path.exists(bundled_version):
                version_path = bundled_version
        with open(version_path, 'r', encoding='utf-8') as f:
            payload['version'] = f.read().strip()
    except Exception:
        pass
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('diagnostics.json', json.dumps(payload, indent=2, ensure_ascii=False))
        for fn in ('VERSION.txt', 'ui_preferences.py', 'requirements.txt'):
            src = os.path.join(BASE_DIR, fn)
            if os.path.exists(src):
                z.write(src, fn)
        if include_private and os.path.exists(SESSIONS_DIR):
            for root, _, files in os.walk(SESSIONS_DIR):
                for fn in files:
                    src = os.path.join(root, fn)
                    z.write(src, os.path.join('private', os.path.relpath(src, SESSIONS_DIR)))
    return path


def autosave_recovery(session_manager, session_id=None):
    """Write a last-accepted-turn crash checkpoint without mutating canonical state."""
    with _RECOVERY_LOCK:
        os.makedirs(AUTOSAVE_DIR, exist_ok=True)
        try:
            if hasattr(session_manager, '_save'):
                session_manager._save()
        except Exception as exc:
            print(f'[Recovery Autosave Warning] Registry save failed before checkpoint: {exc}')

        if not os.path.exists(SESSIONS_FILE):
            return ''

        _atomic_copy_file(SESSIONS_FILE, RECOVERY_REGISTRY)

        sid = str(session_id or '').strip()
        if sid:
            src_dir = os.path.realpath(os.path.join(SESSIONS_DIR, sid))
            base = os.path.realpath(SESSIONS_DIR)
            if os.path.isdir(src_dir) and os.path.commonpath([base, src_dir]) == base:
                os.makedirs(RECOVERY_SESSION_ROOT, exist_ok=True)
                dst = os.path.join(RECOVERY_SESSION_ROOT, sid)
                # Snapshot all vault files at one coherent persona-memory boundary.
                with memory_transaction(sid):
                    temp_dst = tempfile.mkdtemp(prefix=sid + '.tmp.', dir=RECOVERY_SESSION_ROOT)
                    try:
                        shutil.rmtree(temp_dst)
                        shutil.copytree(src_dir, temp_dst)
                        if os.path.exists(dst):
                            shutil.rmtree(dst, ignore_errors=True)
                        os.replace(temp_dst, dst)
                        temp_dst = None
                    finally:
                        if temp_dst:
                            shutil.rmtree(temp_dst, ignore_errors=True)

        _write_json(RECOVERY_MANIFEST, {
            'created_at': datetime.now(timezone.utc).isoformat(),
            'clean_shutdown': False,
            'session_id': sid,
        })
        return RECOVERY_REGISTRY


def mark_clean_shutdown():
    with _RECOVERY_LOCK:
        return _mark_clean_shutdown_unlocked()


def _mark_clean_shutdown_unlocked():
    os.makedirs(AUTOSAVE_DIR, exist_ok=True)
    manifest = {}
    try:
        with open(RECOVERY_MANIFEST, 'r', encoding='utf-8') as fh:
            raw = json.load(fh)
            if isinstance(raw, dict):
                manifest.update(raw)
    except Exception:
        pass
    manifest['clean_shutdown'] = True
    manifest['clean_at'] = datetime.now(timezone.utc).isoformat()
    _write_json(RECOVERY_MANIFEST, manifest)


def recovery_available() -> bool:
    try:
        with open(RECOVERY_MANIFEST, 'r', encoding='utf-8') as fh:
            manifest = json.load(fh)
        return bool(isinstance(manifest, dict) and not manifest.get('clean_shutdown') and os.path.exists(RECOVERY_REGISTRY))
    except Exception:
        return False


def restore_recovery_checkpoint() -> bool:
    with _RECOVERY_LOCK:
        if not recovery_available():
            return False
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        _atomic_copy_file(RECOVERY_REGISTRY, SESSIONS_FILE)
        if os.path.isdir(RECOVERY_SESSION_ROOT):
            for sid in os.listdir(RECOVERY_SESSION_ROOT):
                src = os.path.realpath(os.path.join(RECOVERY_SESSION_ROOT, sid))
                base = os.path.realpath(RECOVERY_SESSION_ROOT)
                if not os.path.isdir(src) or os.path.commonpath([base, src]) != base:
                    continue
                dst = os.path.realpath(os.path.join(SESSIONS_DIR, sid))
                sessions_base = os.path.realpath(SESSIONS_DIR)
                if os.path.commonpath([sessions_base, dst]) != sessions_base:
                    continue
                with memory_transaction(sid):
                    temp_dst = tempfile.mkdtemp(prefix=sid + '.recovery.', dir=SESSIONS_DIR)
                    try:
                        shutil.rmtree(temp_dst)
                        shutil.copytree(src, temp_dst)
                        if os.path.isdir(dst):
                            shutil.rmtree(dst)
                        os.replace(temp_dst, dst)
                        temp_dst = None
                    finally:
                        if temp_dst:
                            shutil.rmtree(temp_dst, ignore_errors=True)
        _mark_clean_shutdown_unlocked()
        return True


def discard_recovery_checkpoint():
    mark_clean_shutdown()


def model_capabilities(model_handler):
    out = {'loaded': False, 'vision': False, 'context': None, 'reasoning': 'unknown'}
    if not model_handler:
        return out
    try:
        out['loaded'] = bool(model_handler.is_active())
    except Exception:
        out['loaded'] = False
    out['vision'] = bool(getattr(model_handler, 'is_vision_model', False) or getattr(model_handler, 'mmproj_path', None))
    try:
        ctx = int(getattr(model_handler, 'n_ctx', 0) or 0)
        out['context'] = ctx or None
    except Exception:
        pass
    if out['loaded']:
        # Dunoon's native transport can explicitly disable hidden reasoning on bounded
        # internal calls; whether a particular GGUF elects to reason in normal chat remains model-defined.
        out['reasoning'] = 'runtime-controllable'
    return out
