from __future__ import annotations

"""Tiny colour-emoji renderer for Tk text widgets.

Dunoon keeps ordinary typography as text and replaces only emoji clusters with small RGBA
images rendered from the operating system's colour emoji font. No emoji font files are shipped.
If the host cannot render colour emoji, callers simply fall back to the original glyph.
"""

import os
import sys
from functools import lru_cache
from typing import Iterator, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

ZWJ = "\u200d"
VS15 = "\ufe0e"
VS16 = "\ufe0f"
KEYCAP = "\u20e3"


def _is_regional(cp: int) -> bool:
    return 0x1F1E6 <= cp <= 0x1F1FF


def _is_skin(cp: int) -> bool:
    return 0x1F3FB <= cp <= 0x1F3FF


def _is_emoji_base(cp: int) -> bool:
    return (
        0x1F000 <= cp <= 0x1FAFF
        or 0x2600 <= cp <= 0x26FF
        or 0x2700 <= cp <= 0x27BF
        or cp in {0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139, 0x3030, 0x303D, 0x3297, 0x3299}
    )


def emoji_cluster_at(text: str, index: int) -> str | None:
    """Return one emoji grapheme-ish cluster beginning at *index*, or None.

    This intentionally covers the emoji forms Dunoon uses most: faces, symbols, flags,
    skin tones, variation selectors and ZWJ sequences. It avoids an extra regex dependency.
    """
    if not text or index < 0 or index >= len(text):
        return None
    ch = text[index]
    cp = ord(ch)

    # Keycap sequences: 1️⃣, #️⃣, *️⃣
    if ch in "0123456789#*":
        j = index + 1
        if j < len(text) and text[j] == VS16:
            j += 1
        if j < len(text) and text[j] == KEYCAP:
            return text[index:j + 1]
        return None

    if not _is_emoji_base(cp):
        return None

    j = index + 1

    # Flags are pairs of regional indicators.
    if _is_regional(cp) and j < len(text) and _is_regional(ord(text[j])):
        j += 1

    def take_modifiers(pos: int) -> int:
        while pos < len(text):
            c = text[pos]
            oc = ord(c)
            if c in (VS15, VS16, KEYCAP) or _is_skin(oc):
                pos += 1
                continue
            break
        return pos

    j = take_modifiers(j)

    # Family / profession / gender / compound emoji.
    while j < len(text) and text[j] == ZWJ:
        if j + 1 >= len(text):
            break
        nxt = ord(text[j + 1])
        if not _is_emoji_base(nxt):
            break
        j += 2
        j = take_modifiers(j)

    return text[index:j]


def iter_rich_segments(text: str) -> Iterator[Tuple[bool, str]]:
    """Yield (is_emoji, segment), coalescing ordinary text for efficient Tk insertion."""
    text = str(text or "")
    i = 0
    plain_start = 0
    while i < len(text):
        cluster = emoji_cluster_at(text, i)
        if cluster:
            if plain_start < i:
                yield False, text[plain_start:i]
            yield True, cluster
            i += len(cluster)
            plain_start = i
        else:
            i += 1
    if plain_start < len(text):
        yield False, text[plain_start:]


def next_rich_token(text: str, index: int) -> Tuple[bool, str]:
    cluster = emoji_cluster_at(text, index)
    if cluster:
        return True, cluster
    if index < len(text):
        return False, text[index]
    return False, ""


@lru_cache(maxsize=1)
def find_color_emoji_font() -> str | None:
    candidates = []
    windir = os.environ.get("WINDIR", r"C:\\Windows")
    candidates.extend([
        os.path.join(windir, "Fonts", "seguiemj.ttf"),
        r"C:\Windows\Fonts\seguiemj.ttf",
        "/System/Library/Fonts/Apple Color Emoji.ttc",
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
        "/usr/share/fonts/truetype/ancient-scripts/Symbola_hint.ttf",
    ])
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def _ensure_emoji_alt_tag(text_widget) -> None:
    """Keep Unicode behind colour sprites without adding layout width.

    Tk Text images are visual objects and are omitted by ordinary ``get``/copy operations.
    A zero-width elided Unicode twin makes the transcript remain lossless text while the
    user still sees the colour sprite.
    """
    try:
        text_widget.tag_configure('_dunoon_emoji_alt', elide=True)
    except Exception:
        pass


def insert_color_emoji(text_widget, renderer, emoji: str, target_px: int = 18, tag=None) -> bool:
    """Insert a colour sprite plus hidden Unicode fallback. Return True on sprite success."""
    photo = renderer.photo(emoji, target_px)
    if photo is None:
        return False
    try:
        text_widget.image_create('end', image=photo, align='baseline', padx=1)
        _ensure_emoji_alt_tag(text_widget)
        # The original grapheme remains canonical for Text.get(), clipboard copy and export.
        if tag:
            text_widget.insert('end', emoji, (tag, '_dunoon_emoji_alt'))
        else:
            text_widget.insert('end', emoji, '_dunoon_emoji_alt')
        return True
    except Exception:
        return False


class ColorEmojiRenderer:
    """Render and cache tiny colour emoji PhotoImages for one Tk interpreter."""

    def __init__(self, master):
        self.master = master
        self._photo_cache = {}
        self.font_path = find_color_emoji_font()

    @property
    def available(self) -> bool:
        return bool(PIL_AVAILABLE and self.font_path)

    def _load_font(self, desired_px: int):
        if not self.available:
            return None
        # Segoe UI Emoji is scalable on current Windows. Noto Color Emoji on many Linux
        # distros exposes a bitmap strike (commonly 109 px), so try both strategies.
        attempts = []
        for size in (max(18, desired_px * 4), 109, 128, 96, 64, 48, 32, 24, 20):
            if size not in attempts:
                attempts.append(size)
        for size in attempts:
            try:
                return ImageFont.truetype(self.font_path, size=size), size
            except Exception:
                continue
        return None

    def _render_rgba(self, emoji: str, target_px: int):
        loaded = self._load_font(target_px)
        if not loaded:
            return None
        font, source_px = loaded
        canvas_side = max(160, int(source_px * 2.0))
        try:
            im = Image.new("RGBA", (canvas_side, canvas_side), (0, 0, 0, 0))
            draw = ImageDraw.Draw(im)
            draw.text((canvas_side // 12, canvas_side // 12), emoji, font=font, embedded_color=True)
            bbox = im.getbbox()
            if not bbox:
                return None
            glyph = im.crop(bbox)
            # Preserve proportions but fit inside a small square matching the current line height.
            target_px = max(12, int(target_px))
            glyph.thumbnail((target_px, target_px), Image.Resampling.LANCZOS)
            out = Image.new("RGBA", (target_px, target_px), (0, 0, 0, 0))
            x = (target_px - glyph.width) // 2
            y = (target_px - glyph.height) // 2
            out.alpha_composite(glyph, (x, y))
            return out
        except Exception:
            return None

    def photo(self, emoji: str, target_px: int = 18):
        key = (str(emoji), int(target_px))
        if key in self._photo_cache:
            return self._photo_cache[key]
        if not self.available:
            self._photo_cache[key] = None
            return None
        rgba = self._render_rgba(str(emoji), int(target_px))
        if rgba is None:
            self._photo_cache[key] = None
            return None
        try:
            photo = ImageTk.PhotoImage(rgba, master=self.master)
        except Exception:
            photo = None
        self._photo_cache[key] = photo
        return photo

    def insert(self, text_widget, text: str, tag=None, target_px: int = 18) -> None:
        """Insert mixed text and colour emoji into a Tk Text widget."""
        for is_emoji, segment in iter_rich_segments(text):
            if is_emoji:
                if insert_color_emoji(text_widget, self, segment, target_px, tag=tag):
                    continue
            if tag:
                text_widget.insert("end", segment, tag)
            else:
                text_widget.insert("end", segment)
