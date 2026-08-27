# ui_windowing.py — predictable child-window placement for the modern Dunoon shell.
from __future__ import annotations

import json
import os
import re
import sys
import threading

from config import BASE_DIR, DATA_DIR

_WINDOW_POSITIONS_FILE = os.path.join(DATA_DIR, "window_positions.json")
_WINDOW_POSITIONS_LOCK = threading.RLock()



def _window_position_key(child):
    """Stable-enough key for remembering one position per child-window type."""
    try:
        cls = child.__class__.__name__
    except Exception:
        cls = 'Toplevel'
    if cls != 'Toplevel':
        return cls
    try:
        title = str(child.title() or '').strip()
    except Exception:
        title = ''
    # Raw Toplevels are used for several tools. Keep the stable prefix while
    # discarding persona/session-specific suffixes.
    for sep in (' · ', ' — ', ' [', ': '):
        if sep in title:
            title = title.split(sep, 1)[0].strip()
            break
    title = re.sub(r'[^A-Za-z0-9 _.-]+', '', title).strip()
    return f'Toplevel:{title or "child"}'


def _load_window_positions():
    with _WINDOW_POSITIONS_LOCK:
        try:
            with open(_WINDOW_POSITIONS_FILE, 'r', encoding='utf-8') as fh:
                raw = json.load(fh)
            return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}


def _save_window_position(key, x, y):
    if not key:
        return
    with _WINDOW_POSITIONS_LOCK:
        data = _load_window_positions()
        data[str(key)] = {'x': int(x), 'y': int(y)}
        try:
            os.makedirs(os.path.dirname(_WINDOW_POSITIONS_FILE), exist_ok=True)
            tmp = _WINDOW_POSITIONS_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp, _WINDOW_POSITIONS_FILE)
        except Exception:
            pass


def _remember_window_on_destroy(child, key):
    if getattr(child, '_dunoon_position_binding', False):
        return
    try:
        child._dunoon_position_binding = True
    except Exception:
        pass

    def _capture(event=None):
        try:
            if event is not None and getattr(event, 'widget', None) is not child:
                return
            x = int(child.winfo_x()); y = int(child.winfo_y())
            _save_window_position(key, x, y)
        except Exception:
            pass

    try:
        child.bind('<Destroy>', _capture, add='+')
    except Exception:
        pass


def _place_saved_or_center(child, parent=None, *, min_margin=12):
    try:
        child.update_idletasks()
    except Exception:
        return
    key = _window_position_key(child)
    saved = _load_window_positions().get(key, {})
    try:
        width = max(int(child.winfo_width()), int(child.winfo_reqwidth()), 1)
        height = max(int(child.winfo_height()), int(child.winfo_reqheight()), 1)
    except Exception:
        width, height = 500, 400
    try:
        work_parent = parent.winfo_toplevel() if parent is not None else child
    except Exception:
        work_parent = child
    left, top, right, bottom = _work_area_for_parent(work_parent)
    if isinstance(saved, dict) and 'x' in saved and 'y' in saved:
        try:
            x = int(saved['x']); y = int(saved['y'])
            max_x = max(left + min_margin, right - width - min_margin)
            max_y = max(top + min_margin, bottom - height - min_margin)
            x = min(max(x, left + min_margin), max_x)
            y = min(max(y, top + min_margin), max_y)
            child.geometry(f'+{x}+{y}')
            _remember_window_on_destroy(child, key)
            return
        except Exception:
            pass
    center_window(child, parent, min_margin=min_margin)
    _remember_window_on_destroy(child, key)

def _work_area_for_parent(parent):
    """Return (left, top, right, bottom) for the monitor containing parent when possible."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes

            MONITOR_DEFAULTTONEAREST = 2

            class RECT(ctypes.Structure):
                _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                            ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
                            ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]

            hwnd = int(parent.winfo_id())
            user32 = ctypes.windll.user32
            monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(info)
            if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                r = info.rcWork
                return int(r.left), int(r.top), int(r.right), int(r.bottom)
        except Exception:
            pass
    try:
        return 0, 0, int(parent.winfo_screenwidth()), int(parent.winfo_screenheight())
    except Exception:
        return 0, 0, 1920, 1080


def center_window(child, parent=None, *, min_margin=12):
    """Center *child* over *parent* and clamp it to the active monitor work area."""
    try:
        child.update_idletasks()
    except Exception:
        return

    try:
        top_parent = parent.winfo_toplevel() if parent is not None else None
    except Exception:
        top_parent = parent

    try:
        width = max(int(child.winfo_width()), int(child.winfo_reqwidth()), 1)
        height = max(int(child.winfo_height()), int(child.winfo_reqheight()), 1)
    except Exception:
        width, height = 500, 400

    if top_parent is not None:
        try:
            top_parent.update_idletasks()
            px = int(top_parent.winfo_rootx())
            py = int(top_parent.winfo_rooty())
            pw = max(int(top_parent.winfo_width()), 1)
            ph = max(int(top_parent.winfo_height()), 1)
            x = px + (pw - width) // 2
            y = py + (ph - height) // 2
            work_parent = top_parent
        except Exception:
            top_parent = None

    if top_parent is None:
        try:
            sw = int(child.winfo_screenwidth())
            sh = int(child.winfo_screenheight())
        except Exception:
            sw, sh = 1920, 1080
        x = (sw - width) // 2
        y = (sh - height) // 2
        work_parent = child

    left, top, right, bottom = _work_area_for_parent(work_parent)
    max_x = max(left + min_margin, right - width - min_margin)
    max_y = max(top + min_margin, bottom - height - min_margin)
    x = min(max(x, left + min_margin), max_x)
    y = min(max(y, top + min_margin), max_y)
    try:
        child.geometry(f"+{int(x)}+{int(y)}")
    except Exception:
        pass


def center_after_idle(child, parent=None):
    """Show a completed child window at its last position, without startup flash.

    Existing callers may keep using this historical function name. First use centers
    over the parent; later uses restore the last closed position and clamp it to the
    current monitor work area.
    """
    try:
        child.withdraw()
    except Exception:
        pass

    def _finish():
        try:
            _place_saved_or_center(child, parent)
            child.deiconify()
            child.lift()
        except Exception:
            try:
                child.deiconify()
            except Exception:
                pass

    try:
        child.after_idle(_finish)
    except Exception:
        _finish()


def apply_window_icon(window, *, set_default: bool = False) -> bool:
    """Apply Dunoon's icon.ico to a Tk/Toplevel window.

    On Windows, ``default=True`` also establishes the icon as Tk's default for
    future child windows/message dialogs. Failures remain non-fatal so Linux/macOS
    ports are never blocked by a Windows .ico quirk.
    """
    icon_path = os.path.join(BASE_DIR, "icon.ico")
    if not os.path.exists(icon_path):
        return False
    applied = False
    try:
        window.iconbitmap(icon_path)
        applied = True
    except Exception:
        pass
    if set_default:
        try:
            window.iconbitmap(default=icon_path)
            applied = True
        except Exception:
            pass
    try:
        window._dunoon_icon_path = icon_path
    except Exception:
        pass
    return applied


def make_toplevel(parent, *args, **kwargs):
    """Create a normal Dunoon child window with icon.ico applied immediately."""
    import tkinter as tk
    win = tk.Toplevel(parent, *args, **kwargs)
    apply_window_icon(win)
    return win
