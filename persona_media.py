# persona_media.py — portable avatar and showcase-quote helpers.
from __future__ import annotations

import os
import shutil

from config import BASE_DIR, SESSIONS_DIR

try:
    from PIL import Image, ImageOps, ImageTk
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _sid(session):
    return str(getattr(session, "id", None) or getattr(session, "session_id", "persona"))


def _base_session(session):
    return getattr(session, "base_session", None) or getattr(session, "_base_session", None) or session


def persona_media_dir(session):
    path = os.path.join(SESSIONS_DIR, _sid(_base_session(session)), "media")
    os.makedirs(path, exist_ok=True)
    return path


def resolve_avatar_path(session):
    base = _base_session(session)
    raw = str(getattr(base, "avatar_path", "") or "").strip()
    if not raw:
        return ""
    path = raw if os.path.isabs(raw) else os.path.join(BASE_DIR, raw)
    return path if os.path.isfile(path) else ""


def set_persona_avatar(session, source_path):
    base = _base_session(session)
    source_path = os.path.abspath(str(source_path or ""))
    ext = os.path.splitext(source_path)[1].lower()
    if not os.path.isfile(source_path) or ext not in _IMAGE_EXTS:
        raise ValueError("Choose a PNG, JPG, WEBP or BMP image.")
    folder = persona_media_dir(base)
    for name in os.listdir(folder):
        if name.lower().startswith("avatar."):
            try: os.remove(os.path.join(folder, name))
            except Exception: pass
    dest = os.path.join(folder, "avatar" + ext)
    shutil.copy2(source_path, dest)
    rel = os.path.relpath(dest, BASE_DIR)
    setattr(base, "avatar_path", rel)
    return dest


def clear_persona_avatar(session):
    base = _base_session(session)
    path = resolve_avatar_path(base)
    if path:
        try: os.remove(path)
        except Exception: pass
    setattr(base, "avatar_path", "")


def avatar_photo(master, session, size=96):
    if not PIL_AVAILABLE:
        return None
    path = resolve_avatar_path(session)
    if not path:
        return None
    try:
        with Image.open(path) as im:
            im = im.convert("RGBA")
            resampling = getattr(Image, "Resampling", Image)
            im = ImageOps.fit(im, (int(size), int(size)), method=resampling.LANCZOS, centering=(0.5, 0.5))
            return ImageTk.PhotoImage(im, master=master)
    except Exception as exc:
        print(f"[Avatar Warning] {exc}")
        return None


def normalize_quote(text, max_chars=360):
    text = " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split()).strip()
    if not text:
        return ""
    if len(text) > max_chars:
        text = text[:max_chars - 1].rstrip() + "…"
    return text


def pin_showcase_quote(session, text, max_quotes=8):
    base = _base_session(session)
    quote = normalize_quote(text)
    if not quote:
        return ""
    existing = list(getattr(base, "pinned_quotes", []) or [])
    existing = [normalize_quote(x) for x in existing if normalize_quote(x) and normalize_quote(x) != quote]
    existing.insert(0, quote)
    setattr(base, "pinned_quotes", existing[:max_quotes])
    setattr(base, "showcase_quote", quote)
    return quote


def showcase_quote(session):
    base = _base_session(session)
    quote = normalize_quote(getattr(base, "showcase_quote", ""))
    if quote:
        return quote
    pins = list(getattr(base, "pinned_quotes", []) or [])
    for item in pins:
        q = normalize_quote(item)
        if q:
            return q
    return ""
