# modern_tooltips.py — optional, globally switchable modern tooltips.
from __future__ import annotations

import tkinter as tk

from ui_preferences import load_ui_preferences


class OptionalTooltip:
    def __init__(self, widget, text, delay=650):
        self.widget = widget
        self.text = text
        self.delay = int(delay)
        self._job = None
        self._window = None
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Leave>", self._leave, add="+")
        widget.bind("<ButtonPress>", self._leave, add="+")

    def _enabled(self):
        try:
            return bool(load_ui_preferences().get("show_tooltips", False))
        except Exception:
            return False

    def _enter(self, _event=None):
        if not self._enabled():
            return
        self._cancel()
        try:
            self._job = self.widget.after(self.delay, self._show)
        except Exception:
            pass

    def _leave(self, _event=None):
        self._cancel()
        self._hide()

    def _cancel(self):
        if self._job is not None:
            try:
                self.widget.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    def _show(self):
        self._job = None
        if not self._enabled() or self._window is not None:
            return
        text = self.text() if callable(self.text) else self.text
        text = str(text or "").strip()
        if not text:
            return
        try:
            x = self.widget.winfo_rootx() + 14
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 7
            tw = tk.Toplevel(self.widget)
            tw.wm_overrideredirect(True)
            tw.attributes("-topmost", True)
            label = tk.Label(tw, text=text, justify="left", wraplength=330,
                             bg="#22262b", fg="#f2f4f6", relief="solid", bd=1,
                             font=("Segoe UI", 9), padx=8, pady=6)
            label.pack()
            tw.update_idletasks()
            sw, sh = tw.winfo_screenwidth(), tw.winfo_screenheight()
            w, h = tw.winfo_width(), tw.winfo_height()
            x = max(4, min(x, sw - w - 8)); y = max(4, min(y, sh - h - 8))
            tw.geometry(f"+{x}+{y}")
            self._window = tw
        except Exception:
            self._window = None

    def _hide(self):
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None


class OptionalRegionTooltip(OptionalTooltip):
    """One tooltip for a compound control made of several nested Tk widgets.

    Tk emits Leave/Enter events while the pointer crosses from a Frame into one
    of its child Labels.  A normal per-widget tooltip can therefore keep
    cancelling itself on a card-like control.  This class treats the whole card
    as one hover region and anchors a single tooltip to the card.
    """
    def __init__(self, anchor_widget, widgets, text, delay=450):
        self.widget = anchor_widget
        self.text = text
        self.delay = int(delay)
        self._job = None
        self._leave_job = None
        self._window = None
        self._widgets = []
        seen = set()
        for widget in (anchor_widget, *tuple(widgets or ())):
            if widget is None or id(widget) in seen:
                continue
            seen.add(id(widget)); self._widgets.append(widget)
            widget.bind("<Enter>", self._region_enter, add="+")
            widget.bind("<Leave>", self._region_leave, add="+")
            widget.bind("<ButtonPress>", self._region_press, add="+")

    def _cancel_leave(self):
        if self._leave_job is not None:
            try:
                self.widget.after_cancel(self._leave_job)
            except Exception:
                pass
            self._leave_job = None

    def _region_enter(self, _event=None):
        if not self._enabled():
            return
        self._cancel_leave()
        if self._window is None and self._job is None:
            try:
                self._job = self.widget.after(self.delay, self._show)
            except Exception:
                pass

    def _region_leave(self, _event=None):
        # Do not hide immediately. Crossing between children of the same mode
        # card produces Leave events even though the pointer is still on the
        # same logical control.
        self._cancel_leave()
        try:
            self._leave_job = self.widget.after(90, self._check_pointer)
        except Exception:
            self._cancel(); self._hide()

    def _region_press(self, _event=None):
        self._cancel_leave(); self._cancel(); self._hide()

    def _contains_widget(self, candidate):
        cur = candidate
        while cur is not None:
            if cur in self._widgets:
                return True
            try:
                cur = cur.master
            except Exception:
                break
        return False

    def _check_pointer(self):
        self._leave_job = None
        try:
            x, y = self.widget.winfo_pointerxy()
            candidate = self.widget.winfo_containing(x, y)
        except Exception:
            candidate = None
        if self._contains_widget(candidate):
            return
        self._cancel(); self._hide()

    def _hide(self):
        self._cancel_leave()
        super()._hide()


def register_tooltip(collection, widget, text, delay=650):
    try:
        setattr(widget, "_dunoon_tooltip_registered", True)
    except Exception:
        pass
    tip = OptionalTooltip(widget, text, delay=delay)
    if collection is not None:
        try:
            collection.append(tip)
        except Exception:
            pass
    return tip


def register_region_tooltip(collection, anchor_widget, widgets, text, delay=450):
    tip = OptionalRegionTooltip(anchor_widget, widgets, text, delay=delay)
    if collection is not None:
        try:
            collection.append(tip)
        except Exception:
            pass
    return tip


def _button_fallback_text(label: str) -> str:
    raw = str(label or "").strip()
    key = raw.casefold().replace("…", "").strip()
    mapping = {
        "close": "Close this window.",
        "cancel": "Close without applying this pending action.",
        "create": "Create the item using the values shown here.",
        "remove": "Remove this item after confirmation.",
        "replace": "Replace this item while preserving its surrounding settings where possible.",
        "save": "Save the current changes.",
        "save persona": "Save this persona and its current settings.",
        "undo": "Restore the previous editor state.",
        "send": "Submit the current text or guidance.",
        "event": "Submit an authoritative scene event, or generate one when the field is blank.",
        "upload": "Choose a supported file to attach or import.",
        "paste": "Paste clipboard text into this field.",
        "reality": "Open the current accepted shared-reality view.",
        "step": "Generate one accepted Arena actor turn.",
        "▶ auto": "Start automatic Arena turn progression.",
        "❚❚ pause": "Pause automatic Arena turn progression after the current safe boundary.",
        "home": "Return to the selected persona home view.",
        "arena": "Open the two-persona Arena.",
        "persona": "Open this persona's identity and OCEAN editor.",
        "memory": "Inspect this persona's learned memory.",
        "lore": "Open the campaign Lore library and persona assignments.",
        "settings": "Open application settings.",
        "master purge": "Permanently remove all live personas and app-owned history after two confirmations.",
    }
    if key in mapping:
        return mapping[key]
    if key.startswith("aa"):
        return "Change text font and size."
    if key.startswith("set avatar"):
        return "Choose an avatar image for this persona."
    if key.startswith("clear avatar"):
        return "Remove this persona's current avatar image."
    if key.startswith("open conversation"):
        return "Choose a Solo conversation mode for this persona."
    if key.startswith("load gguf"):
        return "Choose and load a local GGUF model."
    if key.startswith("eject"):
        return "Unload the active local model from memory."
    if key.startswith("back up"):
        return "Create a backup of app-owned state."
    if key.startswith("restore"):
        return "Restore app-owned state from a backup."
    if key.startswith("diagnostics"):
        return "Create a diagnostics bundle without chat/persona contents by default."
    if key.startswith("model check"):
        return "Show capabilities of the currently loaded local model."
    if key.startswith("randomise") or key.startswith("randomize"):
        return "Generate a fresh weighted OCEAN baseline."
    if key.startswith("relationships"):
        return "Summarise current evidence-backed relationships with other personas."
    if key.startswith("export"):
        return "Export the current data to a file."
    if key.startswith("import"):
        return "Import supported data from a file."
    return "Activate this control's action."


def ensure_button_tooltips(root, collection=None):
    """Safety-net audit: every Tk Button under root gets a tooltip exactly once.

    Explicit tooltips remain preferred. This catches secondary/child-dialog buttons that
    otherwise drift out of coverage as the UI evolves.
    """
    stack = [root]
    seen = set()
    while stack:
        widget = stack.pop()
        if id(widget) in seen:
            continue
        seen.add(id(widget))
        try:
            stack.extend(widget.winfo_children())
        except Exception:
            pass
        if not isinstance(widget, tk.Button):
            continue
        if bool(getattr(widget, "_dunoon_tooltip_registered", False)):
            continue
        try:
            label = widget.cget("text")
        except Exception:
            label = ""
        register_tooltip(collection, widget, _button_fallback_text(label))
    return collection
