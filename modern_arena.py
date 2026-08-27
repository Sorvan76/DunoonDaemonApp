# 🐉 Silver Wyrm: modern_arena.py — autonomous Arena room
# Auto means auto: silent recovery, deterministic turns, streamed presentation, no Arena TTS.

from __future__ import annotations

from datetime import datetime

import json
import os
import threading
from collections import deque
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from core.arena_engine import ArenaEngine, ArenaRecoverableError
from modern_theme import palette, apply_combobox_theme
from skin_manager import load_skin
from font_controls import FontControlDialog
from ui_preferences import CHAT_TYPEWRITER_DELAY_MS, load_ui_preferences, save_ui_preferences
from last_dirs import get_last_dir, remember_path
from modern_tooltips import register_tooltip, ensure_button_tooltips
from persona_media import avatar_photo
from ui_windowing import center_after_idle, apply_window_icon
from color_emoji import ColorEmojiRenderer, next_rich_token

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except Exception:
    Image = ImageTk = None
    PIL_AVAILABLE = False



def _arena_terminal(message: str) -> None:
    """Timestamp Arena terminal diagnostics so soak-test latency is visible."""
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] {message}")

def _initials(name: str) -> str:
    words = [w for w in str(name or "?").replace("-", " ").split() if w]
    return "".join(w[0].upper() for w in words[:2]) or "?"


class ModernArenaFrame(tk.Frame):
    """Live Arena UI. The Director is visible only as quiet status, never transcript prose."""

    ARENA_DETAIL_LEVELS = (
        ("minimal", "Minimal", 256),
        ("light", "Light", 384),
        ("low", "Low", 512),
        ("med", "Med", 768),
        ("high", "High", 1024),
        ("very_high", "Very high", 1280),
        ("ultra", "Ultra", 1536),
        ("max", "Max", 2048),
    )

    def __init__(self, parent, brain, session_manager, skin_name=None):
        self.skin_name = skin_name or load_skin()
        self.brain = brain
        self.sm = session_manager
        # 🐉 Silver Wyrm: live Arena defaults to the bounded inference budget. Legacy/unit
        # callers can still construct ArenaEngine without it for forensic regression tests.
        self.engine = ArenaEngine(brain, session_manager, latency_budget=True)
        self.autoloop = False
        self.busy = False
        self.alive = True
        self._label_to_session = {}
        self._last_scene = None
        self._font_dialog = None
        self._activity_job = None
        self._activity_tick = False
        self._activity_active = False
        self._activity_text = "READY"
        self._tooltips = []
        self._step_pulse_job = None
        self._step_pulse_tick = False
        self._pending_human_action = None  # legacy compatibility marker; queue below owns live inputs
        self._pending_human_actions = deque()
        self._guidance_pulse_job = None
        self._guidance_pulse_tick = False
        self._guidance_pending_kind = ""
        self._staged_upload = None
        self._arena_embedded_assets = []
        self._scene_pulse_job = None
        self._scene_pulse_tick = False
        self._pending_scene_save_path = None
        prefs = load_ui_preferences()
        self.block_director_var = tk.BooleanVar(master=parent, value=bool(prefs.get("block_director_creative_freedom", False)))
        self.engine.set_block_director_creative_freedom(bool(self.block_director_var.get()))
        self.arena_detail_level = str(prefs.get("arena_detail_level") or "med")
        self.chat_font_family = prefs["chat_font_family"]
        self.chat_font_size = prefs["chat_font_size"]
        super().__init__(parent, bg=palette(self.skin_name)["panel"])
        self._color_emoji = ColorEmojiRenderer(self)
        self._arena_detail_index = tk.IntVar(value=self._detail_index_for_key(self.arena_detail_level))
        self._arena_detail_label = tk.StringVar()
        self._apply_arena_detail_index(self._arena_detail_index.get(), persist=False)
        self.pack(fill="both", expand=True)
        self._build()

    def _p(self):
        return palette(self.skin_name)

    def _button(self, parent, text, command, accent=False, width=None):
        p = self._p()
        return tk.Button(
            parent, text=text, command=command, relief="flat", bd=0,
            bg=p["accent"] if accent else p["button"],
            fg=p["bg"] if accent else p["button_fg"],
            activebackground=p["accent"], activeforeground=p["bg"],
            font=("Segoe UI Semibold", 9), padx=11, pady=7, cursor="hand2", width=width,
        )

    def _tip(self, widget, text):
        return register_tooltip(self._tooltips, widget, text)

    def _paste_into(self, widget):
        """Replace the target field with clipboard text for a predictable one-click paste."""
        try:
            text = self.clipboard_get()
        except Exception:
            self._set_activity("CLIPBOARD EMPTY", active=False)
            return
        if not str(text or ""):
            return
        try:
            if isinstance(widget, tk.Text):
                widget.delete("1.0", "end")
                widget.insert("1.0", text)
            else:
                widget.delete(0, "end")
                widget.insert(0, text)
            widget.focus_set()
            if widget is getattr(self, "scenario", None):
                self._scene_text_changed()
        except Exception:
            pass

    def _build(self):
        p = self._p()
        apply_combobox_theme(self.winfo_toplevel(), self.skin_name)
        self.configure(bg=p["panel"])
        self.activity_strip = tk.Frame(self, bg=p["panel"], height=3)
        self.activity_strip.pack(fill="x", side="top")

        self.header = tk.Frame(self, bg=p["panel"])
        self.header.pack(fill="x", padx=22, pady=(18, 10))
        self.title = tk.Label(self.header, text="ARENA", bg=p["panel"], fg=p["text"], font=("Segoe UI Semibold", 20))
        self.title.pack(side="left")
        self.director_status = tk.Label(self.header, text="Director  •  waiting for a scene", bg=p["panel"], fg=p["muted"], font=("Segoe UI", 9))
        self.director_status.pack(side="left", padx=(14, 8))
        self.activity_pill = tk.Label(self.header, text="● READY", bg=p["panel2"], fg=p["muted"], font=("Segoe UI Semibold", 8), padx=10, pady=5)
        self.activity_pill.pack(side="left", padx=6)

        self.font_btn = self._button(self.header, f"Aa · {self.chat_font_size}", self._open_font_controls)
        self.font_btn.pack(side="right", padx=(6, 0)); self._tip(self.font_btn, "Change Arena text font and size.")
        self.reality_btn = self._button(self.header, "Reality", self._show_reality)
        self.reality_btn.pack(side="right", padx=6); self._tip(self.reality_btn, "View the Director's accepted shared reality.")
        self.scene_tools = tk.Frame(self, bg=p["panel"])
        self.scene_tools.pack(fill="x", padx=22, pady=(0, 6))
        self.scene_tools_label = tk.Label(self.scene_tools, text="SESSION TOOLS", bg=p["panel"], fg=p["muted"], font=("Segoe UI Semibold", 8))
        self.scene_tools_label.pack(side="left")
        self.save_transcript_btn = self._button(self.scene_tools, "Export transcript", self.save_transcript)
        self.save_transcript_btn.pack(side="right", padx=(6, 0)); self._tip(self.save_transcript_btn, "Export the Arena transcript as TXT, Markdown or structured JSON.")
        self.load_transcript_btn = self._button(self.scene_tools, "Open transcript", self.open_transcript)
        self.load_transcript_btn.pack(side="right", padx=6); self._tip(self.load_transcript_btn, "Open a saved transcript for read-only reference.")
        self.save_scene_btn = self._button(self.scene_tools, "Save scene", self.save_scene)
        self.save_scene_btn.pack(side="right", padx=6); self._tip(self.save_scene_btn, "Save the current Arena checkpoint.")
        self.load_scene_btn = self._button(self.scene_tools, "Load scene", self.load_scene)
        self.load_scene_btn.pack(side="right", padx=6); self._tip(self.load_scene_btn, "Load a saved Arena checkpoint.")
        self.detail_control = tk.Frame(self.scene_tools, bg=p["panel"])
        self.detail_control.pack(side="right", padx=(6, 2))
        self.detail_text = tk.Label(self.detail_control, textvariable=self._arena_detail_label, bg=p["panel"], fg=p["muted"], font=("Segoe UI Semibold", 8))
        self.detail_text.pack(side="left", padx=(0, 4))
        self.detail_slider = tk.Scale(
            self.detail_control, from_=0, to=len(self.ARENA_DETAIL_LEVELS) - 1, resolution=1, orient="horizontal", showvalue=False,
            variable=self._arena_detail_index, command=self._on_arena_detail_slide, length=190,
            relief="flat", bd=0, highlightthickness=0, bg=p["panel"], fg=p["text"],
            activebackground=p["accent"], troughcolor=p["button"], sliderlength=16, width=10,
        )
        self.detail_slider.pack(side="left")
        self._tip(self.detail_control, "Arena response budget: 256 to 2048 visible tokens. Reasoning stays off.")
        self._tip(self.detail_slider, "Change actor detail. Applies on the next turn.")
        self.block_director_check = tk.Checkbutton(
            self.scene_tools, text="Block Director creativity", variable=self.block_director_var,
            command=self._on_block_director_changed, bg=p["panel"], fg=p["text"],
            activebackground=p["panel"], activeforeground=p["text"], selectcolor=p["panel2"],
            font=("Segoe UI", 8), cursor="hand2", bd=0, highlightthickness=0,
        )
        self.block_director_check.pack(side="right", padx=(8, 4))
        self._tip(self.block_director_check, "Keep the Director conservative; no optional new world events.")
        self.auto_btn = self._button(self.header, "▶ Auto", self.toggle_auto, accent=True)
        self.auto_btn.pack(side="right", padx=6); self._tip(self.auto_btn, "Start Auto. The button becomes Pause while running.")
        self.step_btn = self._button(self.header, "Step", self.step)
        self.step_btn.pack(side="right", padx=6); self._tip(self.step_btn, "Generate one accepted actor turn.")

        self.participant_row = tk.Frame(self, bg=p["panel"])
        self.participant_row.pack(fill="x", padx=22, pady=(0, 10))
        self.participant_row.columnconfigure(0, weight=1)
        self.participant_row.columnconfigure(1, weight=0)
        self.participant_row.columnconfigure(2, weight=1)
        self.actor_a_panel = self._actor_panel(self.participant_row, 0)
        self.vs_label = tk.Label(self.participant_row, text="VS", bg=p["panel"], fg=p["muted"], font=("Segoe UI Semibold", 9))
        self.vs_label.grid(row=0, column=1, padx=12)
        self.actor_b_panel = self._actor_panel(self.participant_row, 2)

        self.setup = tk.Frame(self, bg=p["bg"], highlightbackground=p["border"], highlightthickness=1)
        self.setup.pack(fill="x", padx=22, pady=(0, 10))
        top = tk.Frame(self.setup, bg=p["bg"])
        top.pack(fill="x", padx=14, pady=(12, 8))
        tk.Label(top, text="START A SCENE", bg=p["bg"], fg=p["muted"], font=("Segoe UI Semibold", 8)).pack(side="left")
        self.start_btn = self._button(top, "Establish scene", self.start_scene, accent=True)
        self.start_btn.pack(side="right"); self._tip(self.start_btn, "Set the starting reality and begin the scene.")

        picks = tk.Frame(self.setup, bg=p["bg"])
        picks.pack(fill="x", padx=14, pady=(0, 8))
        picks.columnconfigure(0, weight=1)
        picks.columnconfigure(1, weight=1)
        self.persona_a = ttk.Combobox(picks, state="readonly")
        self.persona_b = ttk.Combobox(picks, state="readonly")
        self.persona_a.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.persona_b.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self._refresh_personas()

        self.scenario = tk.Text(self.setup, height=5, wrap="word", relief="flat", bd=0, bg=p["panel2"], fg=p["text"], insertbackground=p["accent"], font=(self.chat_font_family, self.chat_font_size), padx=12, pady=10)
        self.scenario.pack(fill="x", padx=14, pady=(0, 6))
        self.scenario.bind("<KeyRelease>", self._scene_text_changed, add="+")
        scenario_tools = tk.Frame(self.setup, bg=p["bg"])
        scenario_tools.pack(fill="x", padx=14, pady=(0, 14))
        self.scenario_paste_btn = self._button(scenario_tools, "Paste from clipboard", lambda: self._paste_into(self.scenario))
        self.scenario_paste_btn.pack(side="right")
        self._tip(self.scenario_paste_btn, "Replace the scene text with clipboard text.")
        self.scenario.insert("1.0", "Place two personas in a situation. The human establishes the starting reality; the Director maintains it once autoloop begins.")
        self.scenario.bind("<FocusIn>", self._clear_scenario_hint)
        self._start_scene_entry_pulse()

        self.transcript_outer = tk.Frame(self, bg=p["bg"], highlightbackground=p["border"], highlightthickness=1)
        self.transcript_outer.pack(fill="both", expand=True, padx=22, pady=(0, 10))
        self.transcript_outer.rowconfigure(0, weight=1)
        self.transcript_outer.columnconfigure(0, weight=1)
        self.transcript = tk.Text(self.transcript_outer, wrap="word", state="disabled", relief="flat", bd=0, bg=p["bg"], fg=p["text"], font=(self.chat_font_family, self.chat_font_size), padx=20, pady=18, spacing1=1, spacing3=6)
        self.transcript.grid(row=0, column=0, sticky="nsew")
        sb = tk.Scrollbar(self.transcript_outer, orient="vertical", command=self.transcript.yview, relief="flat", bd=0)
        sb.grid(row=0, column=1, sticky="ns")
        self.transcript.configure(yscrollcommand=sb.set)
        self.transcript.tag_config("actor_a_name", foreground=p["accent"], font=("Segoe UI Semibold", 9))
        self.transcript.tag_config("actor_b_name", foreground=p["accent2"], font=("Segoe UI Semibold", 9))
        self.transcript.tag_config("body", foreground=p["text"], font=(self.chat_font_family, self.chat_font_size))
        self.transcript.tag_config("human", foreground=p["accent"], font=("Segoe UI Semibold", 9))
        self.transcript.tag_config("system", foreground=p["muted"], font=("Segoe UI", 9, "italic"))

        # Keep intervention controls inside the expanding transcript container as a fixed bottom row.
        # This prevents short/high-DPI Windows layouts from starving the entire strip off-screen.
        self.intervene_outer = tk.Frame(self.transcript_outer, bg=p["panel"])
        self.intervene_outer.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(4, 10))
        self.intervene_box = tk.Frame(self.intervene_outer, bg=p["panel2"], highlightbackground=p["accent"], highlightthickness=1)
        self.intervene_box.pack(fill="x")
        self.intervene_box.columnconfigure(1, weight=1)
        self.intervene_label = tk.Label(self.intervene_box, text="GUIDE YOUR STORY", bg=p["panel2"], fg=p["accent"], font=("Segoe UI Semibold", 8))
        self.intervene_label.grid(row=0, column=0, padx=(10, 5), sticky="w")
        self.intervene_entry = tk.Entry(self.intervene_box, bg=p["panel2"], fg=p["text"], insertbackground=p["accent"], relief="flat", bd=0, font=(self.chat_font_family, self.chat_font_size))
        self.intervene_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=6, ipady=10)
        self.intervene_entry.bind("<Return>", lambda _e: self.user_input())

        self.intervene_actions = tk.Frame(self.intervene_box, bg=p["panel2"])
        self.intervene_actions.grid(row=0, column=2, padx=(2, 4), pady=0, sticky="e")
        self.paste_btn = self._button(self.intervene_actions, "Paste", lambda: self._paste_into(self.intervene_entry))
        self.paste_btn.pack(side="left", padx=(0, 4), pady=6); self._tip(self.paste_btn, "Replace this field with clipboard text.")
        self.upload_btn = self._button(self.intervene_actions, "Upload", self.upload)
        self.upload_btn.pack(side="left", padx=4, pady=6); self._tip(self.upload_btn, "Attach a supported file to the next Send.")
        self.user_input_btn = self._button(self.intervene_actions, "Send", self.user_input, accent=True)
        self.user_input_btn.pack(side="left", padx=4, pady=6); self._tip(self.user_input_btn, "Guide the live scene at highest user authority.")
        self.event_btn = self._button(self.intervene_actions, "Event", self.event)
        self.event_btn.pack(side="left", padx=(4, 0), pady=6); self._tip(self.event_btn, "Add an authoritative scene event, or generate one if blank.")

        self._apply_chat_fonts()
        self._set_controls(started=False)
        self._set_activity("READY", active=False)
        ensure_button_tooltips(self, self._tooltips)

    @classmethod
    def _detail_index_for_key(cls, key: str) -> int:
        wanted = str(key or "med").strip().lower()
        for index, (value, _label, _tokens) in enumerate(cls.ARENA_DETAIL_LEVELS):
            if value == wanted:
                return index
        return 3

    def _apply_arena_detail_index(self, index, *, persist: bool = True):
        try:
            index = int(round(float(index)))
        except Exception:
            index = self._detail_index_for_key("med")
        index = max(0, min(len(self.ARENA_DETAIL_LEVELS) - 1, index))
        key, label, tokens = self.ARENA_DETAIL_LEVELS[index]
        self.arena_detail_level = key
        try:
            self._arena_detail_index.set(index)
            self._arena_detail_label.set(f"Detail: {label} · {tokens}")
        except Exception:
            pass
        turn_engine = getattr(self.brain, "turn_engine", None)
        setter = getattr(turn_engine, "set_arena_actor_budget", None)
        if callable(setter):
            setter(tokens)
        if persist:
            save_ui_preferences(arena_detail_level=key)
        return tokens

    def _on_arena_detail_slide(self, value):
        # tk.Scale may deliver a string/float while dragging. Snap to the four
        # supported budgets; the selected value is read afresh on the next actor turn.
        tokens = self._apply_arena_detail_index(value, persist=True)
        self._set_activity(f"DETAIL {tokens}", active=False)

    def _on_block_director_changed(self):
        blocked = bool(self.block_director_var.get())
        self.engine.set_block_director_creative_freedom(blocked)
        save_ui_preferences(block_director_creative_freedom=blocked)
        self._set_activity("DIRECTOR BLOCKED" if blocked else "DIRECTOR CREATIVE", active=False)

    def _apply_chat_fonts(self):
        family = getattr(self, "chat_font_family", "Segoe UI Emoji")
        size = max(8, min(28, int(getattr(self, "chat_font_size", 11))))
        try:
            self.transcript.configure(font=(family, size))
            self.transcript.tag_config("actor_a_name", font=(family, max(8, size - 1), "bold"))
            self.transcript.tag_config("actor_b_name", font=(family, max(8, size - 1), "bold"))
            self.transcript.tag_config("body", font=(family, size))
            self.transcript.tag_config("human", font=(family, max(8, size - 1), "bold"))
            self.transcript.tag_config("system", font=(family, max(8, size - 2), "italic"))
            self.scenario.configure(font=(family, size))
            self.intervene_entry.configure(font=(family, size))
        except Exception:
            pass
        try:
            self.font_btn.configure(text=f"Aa · {size}")
        except Exception:
            pass

    def _set_chat_font(self, family: str, size: int):
        self.chat_font_family = str(family or "Segoe UI Emoji")
        self.chat_font_size = max(8, min(28, int(size)))
        save_ui_preferences(chat_font_family=self.chat_font_family, chat_font_size=self.chat_font_size)
        self._apply_chat_fonts()

    def _open_font_controls(self):
        try:
            if self._font_dialog is not None and self._font_dialog.winfo_exists():
                self._font_dialog.lift()
                self._font_dialog.focus_force()
                return
        except Exception:
            self._font_dialog = None
        self._font_dialog = FontControlDialog(self, self.chat_font_family, self.chat_font_size, self._set_chat_font, self._p(), title="Arena typography")

    def _actor_panel(self, parent, col):
        p = self._p()
        frame = tk.Frame(parent, bg=p["bg"], highlightbackground=p["border"], highlightthickness=1)
        frame.grid(row=0, column=col, sticky="ew")
        badge = tk.Label(frame, text="?", width=3, bg=p["panel2"], fg=p["accent"], font=("Segoe UI Semibold", 14), padx=6, pady=6)
        badge.pack(side="left", padx=9, pady=8)
        box = tk.Frame(frame, bg=p["bg"])
        box.pack(side="left", fill="x", expand=True)
        name = tk.Label(box, text="Choose persona", bg=p["bg"], fg=p["text"], font=("Segoe UI Semibold", 9))
        name.pack(anchor="w")
        status = tk.Label(box, text="not in scene", bg=p["bg"], fg=p["muted"], font=("Segoe UI", 8))
        status.pack(anchor="w")
        frame._badge = badge
        frame._photo = None
        frame._name = name
        frame._status = status
        frame._box = box
        return frame

    def _refresh_personas(self):
        sessions = list(self.sm.list_sessions())
        self._label_to_session = {}
        labels = []
        for s in sessions:
            label = f"{getattr(s, 'agent_name', 'Persona')}  ·  {getattr(s, 'name', '')}"
            if label in self._label_to_session:
                label += f"  [{str(getattr(s, 'id', ''))[:6]}]"
            self._label_to_session[label] = s
            labels.append(label)
        self.persona_a.configure(values=labels)
        self.persona_b.configure(values=labels)
        if labels:
            self.persona_a.set(labels[0])
        if len(labels) > 1:
            self.persona_b.set(labels[1])
        elif labels:
            self.persona_b.set(labels[0])
        self._preview_selected()
        self.persona_a.bind("<<ComboboxSelected>>", lambda _e: self._preview_selected())
        self.persona_b.bind("<<ComboboxSelected>>", lambda _e: self._preview_selected())

    def _selected_sessions(self):
        return self._label_to_session.get(self.persona_a.get()), self._label_to_session.get(self.persona_b.get())

    def _preview_selected(self):
        a, b = self._selected_sessions()
        a_state = "dead" if a and bool(getattr(a, "is_deceased", False)) else ("alive" if a else "not in scene")
        b_state = "dead" if b and bool(getattr(b, "is_deceased", False)) else ("alive" if b else "not in scene")
        self._set_actor_panel(self.actor_a_panel, a, a_state)
        self._set_actor_panel(self.actor_b_panel, b, b_state)

    def _set_actor_panel(self, panel, session, status):
        p = self._p()
        name = getattr(session, "agent_name", "Choose persona") if session else "Choose persona"
        photo = avatar_photo(panel._badge, session, 44) if session else None
        panel._photo = photo
        if photo:
            panel._badge.configure(image=photo, text="", width=44, height=44, padx=0, pady=0)
        else:
            panel._badge.configure(image="", text=_initials(name), width=3, height=1, padx=6, pady=6)
        panel._name.configure(text=name)
        dead = str(status).lower() == "dead"
        thinking = "thinking" in str(status).lower() or "speaking" in str(status).lower() or "retry" in str(status).lower() or "director" in str(status).lower()
        if dead:
            fg = "#ff6b6b"
        elif thinking:
            fg = p["accent"]
        elif status == "alive":
            fg = "#65d48a"
        else:
            fg = p["muted"]
        panel._status.configure(text="dead" if dead else status, fg=fg)
        panel.configure(highlightbackground=p["accent"] if thinking else p["border"], highlightthickness=2 if thinking else 1)

    def _set_actor_activity(self, actor_name: str, text: str):
        if not self.engine.sessions:
            return
        for panel, sess in ((self.actor_a_panel, self.engine.sessions[0]), (self.actor_b_panel, self.engine.sessions[1])):
            name = self.engine._name(sess)
            state = self.engine.scene.actor_status.get(name, "alive") if self.engine.scene else "alive"
            self._set_actor_panel(panel, sess, text if name == actor_name and state != "dead" else state)

    @staticmethod
    def _scenario_hint_text():
        return "Place two personas in a situation. The human establishes the starting reality; the Director maintains it once autoloop begins."

    def _scenario_has_user_text(self):
        try:
            value = self.scenario.get("1.0", "end-1c").strip()
        except Exception:
            return False
        return bool(value and value != self._scenario_hint_text())

    def _scene_text_changed(self, _event=None):
        if self._scenario_has_user_text():
            self._stop_scene_entry_pulse()
        elif not self.engine.started:
            self._start_scene_entry_pulse()

    def _start_scene_entry_pulse(self):
        if self.engine.started or self._scenario_has_user_text() or self._scene_pulse_job is not None:
            return
        self._scene_pulse_tick = False
        self._pulse_scene_entry()

    def _pulse_scene_entry(self):
        if not self.alive or self.engine.started or self._scenario_has_user_text():
            self._scene_pulse_job = None
            try:
                p = self._p()
                self.scenario.configure(bg=p["panel2"], fg=p["text"])
            except Exception:
                pass
            return
        self._scene_pulse_tick = not self._scene_pulse_tick
        p = self._p()
        # Keep the surface stable and pulse the hint text instead. This preserves
        # readability on skins where the former flashing background could collide
        # with the fixed foreground colour.
        try:
            self.scenario.configure(
                bg=p["panel2"],
                fg=p["accent"] if self._scene_pulse_tick else p["text"],
            )
        except Exception:
            pass
        self._scene_pulse_job = self.after(650, self._pulse_scene_entry)

    def _stop_scene_entry_pulse(self):
        if self._scene_pulse_job is not None:
            try:
                self.after_cancel(self._scene_pulse_job)
            except Exception:
                pass
        self._scene_pulse_job = None
        try:
            p = self._p()
            self.scenario.configure(bg=p["panel2"], fg=p["text"])
        except Exception:
            pass

    def _tail_is_visible(self, widget):
        try:
            _first, last = widget.yview()
            return float(last) >= 0.985
        except Exception:
            return True

    def _follow_tail_if_needed(self, widget, follow):
        if follow:
            try:
                widget.see("end")
            except Exception:
                pass

    def _clear_scenario_hint(self, _event=None):
        hint = self._scenario_hint_text()
        if self.scenario.get("1.0", "end-1c").strip() == hint:
            self.scenario.delete("1.0", "end")
            self._start_scene_entry_pulse()

    def _set_controls(self, started: bool):
        state = "normal" if started else "disabled"
        for b in (self.step_btn, self.auto_btn, self.reality_btn, self.save_scene_btn, self.save_transcript_btn, self.load_transcript_btn, self.user_input_btn, self.event_btn, self.paste_btn, self.upload_btn):
            b.configure(state=state)
        # Loading/opening reference material is useful before a scene exists and remains available while paused.
        self.load_scene_btn.configure(state="normal")
        self.load_transcript_btn.configure(state="normal")
        self.intervene_entry.configure(state=state)

    def _emoji_px(self):
        return max(14, min(34, int(round(getattr(self, 'chat_font_size', 11) * 1.45))))

    def _rich_insert(self, widget, text, tag=None):
        try:
            self._color_emoji.insert(widget, str(text or ''), tag=tag, target_px=self._emoji_px())
        except Exception:
            widget.insert('end', str(text or ''), tag) if tag else widget.insert('end', str(text or ''))

    def _append(self, who, text, tag="body", image_path=None):
        if not self.alive:
            return
        follow_tail = self._tail_is_visible(self.transcript)
        self.transcript.configure(state="normal")
        self.transcript.insert("end", f"{who}\n", tag)
        body_tag = "body" if tag != "system" else "system"
        self._rich_insert(self.transcript, str(text).strip(), body_tag)
        if image_path:
            self._append_image_thumbnail(image_path, body_tag)
        self.transcript.insert("end", "\n\n", body_tag)
        self.transcript.configure(state="disabled")
        self._follow_tail_if_needed(self.transcript, follow_tail)

    def _append_image_thumbnail(self, image_path, body_tag="body"):
        """Embed a compact clickable image preview in the Arena transcript."""
        path = str(image_path or "").strip()
        if not path or not os.path.exists(path):
            return
        if not PIL_AVAILABLE:
            self.transcript.insert("end", f"\n[Attached Image: {os.path.basename(path)}]", body_tag)
            return
        try:
            pil_img = Image.open(path)
            pil_img.thumbnail((150, 150), Image.Resampling.LANCZOS)
            tk_img = ImageTk.PhotoImage(pil_img)
            self._arena_embedded_assets.append(tk_img)
            p = self._p()
            frame = tk.Frame(self.transcript, bg=p["panel2"], padx=5, pady=5, cursor="hand2")
            image_label = tk.Label(frame, image=tk_img, bg=p["panel2"], cursor="hand2")
            image_label.pack(side="left")
            caption = tk.Label(
                frame, text=f"  {os.path.basename(path)}\n  Click to view",
                bg=p["panel2"], fg=p["accent"], font=("Segoe UI Semibold", 8),
                justify="left", cursor="hand2"
            )
            caption.pack(side="left", padx=5)

            def _open(_event=None, target=path):
                try:
                    os.startfile(target)
                except AttributeError:
                    import subprocess
                    subprocess.Popen(["xdg-open", target])
                except Exception:
                    pass

            for widget in (frame, image_label, caption):
                widget.bind("<Button-1>", _open)
            self.transcript.insert("end", "\n", body_tag)
            self.transcript.window_create("end", window=frame)
        except Exception:
            self.transcript.insert("end", f"\n[Attached Image: {os.path.basename(path)}]", body_tag)

    def _stream_append(self, who, text, tag, on_complete=None):
        """Present a completed model response gradually; inference itself is never artificially delayed."""
        if not self.alive:
            return
        body = str(text or "").strip()
        follow_tail = self._tail_is_visible(self.transcript)
        self.transcript.configure(state="normal")
        self.transcript.insert("end", f"{who}\n", tag)
        self.transcript.configure(state="disabled")
        self._follow_tail_if_needed(self.transcript, follow_tail)
        n = len(body)
        # Cosmetic patch: match the single-agent chat's typewriter cadence.
        # Inference is already complete; this controls presentation only.
        delay = CHAT_TYPEWRITER_DELAY_MS
        chunk = 1

        def tick(i=0):
            if not self.alive:
                return
            if i >= n:
                keep_following = self._tail_is_visible(self.transcript)
                self.transcript.configure(state="normal")
                self.transcript.insert("end", "\n\n", "body")
                self.transcript.configure(state="disabled")
                self._follow_tail_if_needed(self.transcript, keep_following)
                if on_complete:
                    on_complete()
                return
            keep_following = self._tail_is_visible(self.transcript)
            self.transcript.configure(state="normal")
            j = i
            visual = 0
            while j < n and visual < chunk:
                _is_emoji, token = next_rich_token(body, j)
                if not token:
                    break
                self._rich_insert(self.transcript, token, "body")
                j += len(token)
                visual += 1
            self.transcript.configure(state="disabled")
            self._follow_tail_if_needed(self.transcript, keep_following)
            self.after(delay, lambda: tick(j))

        tick()

    def _set_director(self, text, active=False):
        if not self.alive:
            return
        p = self._p()
        self.director_status.configure(text=f"Director  •  {text}", fg=p["accent"] if active else p["muted"])

    def _set_activity(self, text: str, active=False):
        if not self.alive:
            return
        self._activity_text = str(text or "READY").upper()
        self._activity_active = bool(active)
        p = self._p()
        self.activity_pill.configure(text=("● " if active else "• ") + self._activity_text, bg=p["panel2"], fg=p["accent"] if active else p["muted"])
        self.activity_strip.configure(bg=p["accent"] if active else p["panel"])
        if active and self._activity_job is None:
            self._pulse_activity()
        elif not active and self._activity_job is not None:
            try:
                self.after_cancel(self._activity_job)
            except Exception:
                pass
            self._activity_job = None

    def _pulse_activity(self):
        if not self.alive or not self._activity_active:
            self._activity_job = None
            return
        self._activity_tick = not self._activity_tick
        p = self._p()
        self.activity_pill.configure(fg=p["accent"] if self._activity_tick else p["text"])
        self.activity_strip.configure(bg=p["accent"] if self._activity_tick else p["text"])
        self._activity_job = self.after(320, self._pulse_activity)

    def _start_step_pulse(self):
        self._stop_step_pulse(reset=False)
        self._step_pulse_tick = False
        self._pulse_step_button()

    def _pulse_step_button(self):
        if not self.alive or not self.engine.started or self.busy or self.autoloop:
            self._step_pulse_job = None
            return
        self._step_pulse_tick = not self._step_pulse_tick
        p = self._p()
        if self._step_pulse_tick:
            self.step_btn.configure(bg=p["accent"], fg=p["bg"])
        else:
            self.step_btn.configure(bg=p["button"], fg=p["button_fg"])
        self._step_pulse_job = self.after(420, self._pulse_step_button)

    def _stop_step_pulse(self, reset=True):
        if self._step_pulse_job is not None:
            try:
                self.after_cancel(self._step_pulse_job)
            except Exception:
                pass
        self._step_pulse_job = None
        if reset and hasattr(self, "step_btn"):
            p = self._p()
            try:
                self.step_btn.configure(bg=p["button"], fg=p["button_fg"])
            except Exception:
                pass

    def _progress(self, phase, actor=""):
        if not self.alive:
            return
        if phase == "actor":
            self._set_director(f"{actor} has the turn")
            self._set_activity(f"{actor} thinking", active=True)
            self._set_actor_activity(actor, "● thinking…")
        elif phase == "director":
            self._set_director("resolving shared reality", active=True)
            self._set_activity("Director resolving", active=True)
            if actor:
                self._set_actor_activity(actor, "director resolving…")
        elif phase == "retry":
            self._set_director(f"quietly re-grounding {actor}", active=True)
            self._set_activity(f"{actor} retrying", active=True)
            self._set_actor_activity(actor, "↻ retrying…")
        elif phase == "intervention":
            self._set_director("integrating your intervention", active=True)
            self._set_activity("Director integrating", active=True)

    def start_scene(self):
        if self.busy:
            return
        a, b = self._selected_sessions()
        scenario = self.scenario.get("1.0", "end-1c").strip()
        if not self._scenario_has_user_text():
            self._set_activity("DESCRIBE THE SCENE FIRST", active=True)
            self._start_scene_entry_pulse()
            return
        if not a or not b:
            self._set_activity("CHOOSE TWO PERSONAS", active=True)
            return
        if a is b:
            self._set_activity("CHOOSE DIFFERENT PERSONAS", active=True)
            return
        self.busy = True
        self._stop_scene_entry_pulse()
        self._set_director("analyzing scene", active=True)
        self._set_activity("Director establishing scene", active=True)
        self.start_btn.configure(state="disabled")

        def work():
            try:
                scene = self.engine.start(a, b, scenario)
                err = None
            except Exception as exc:
                scene, err = None, exc
            if self.alive:
                self.after(0, lambda: self._started(scene, err))
        threading.Thread(target=work, daemon=True).start()

    def _started(self, scene, err):
        self.busy = False
        self.start_btn.configure(state="normal")
        if err:
            _arena_terminal(f"[ARENA][START ERROR] {err}")
            self._set_director("scene failed")
            self._set_activity("SCENE FAILED", active=False)
            return
        self._last_scene = scene
        self._set_controls(started=True)
        self._set_director("scene established")
        self._set_activity("READY", active=False)
        self.setup.pack_forget()
        self._append("SYSTEM", "Scene established. The Director now owns shared external reality; each persona owns only themselves.", "system")
        self._update_actor_status(scene)
        self._start_step_pulse()
        self.intervene_entry.focus_set()

    def _combo_select_session(self, combo, session):
        wanted = str(getattr(session, "id", "") or "")
        for label, candidate in self._label_to_session.items():
            if candidate is session or (wanted and str(getattr(candidate, "id", "") or "") == wanted):
                combo.set(label)
                return

    def _replay_loaded_scene(self, scene):
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.configure(state="disabled")
        self._append("SYSTEM", f"Scene loaded at revision {scene.revision}. Shared reality and turn ownership restored.", "system")
        a_name = self.engine._name(self.engine.sessions[0]) if self.engine.sessions else ""
        for item in list(getattr(scene, "log", []) or []):
            kind = str(item.get("kind", "") or "")
            text = str(item.get("text", "") or "").strip()
            actor = str(item.get("actor", "") or "").strip()
            if not text:
                continue
            if kind == "actor":
                self._append(actor or "Persona", text, "actor_a_name" if actor == a_name else "actor_b_name")
            elif kind == "user_input":
                self._append("YOU", text, "human")
            elif kind == "intervention":
                self._append("YOU · EVENT", text, "human")

    def _transcript_text(self):
        try:
            return self.transcript.get("1.0", "end-1c").rstrip() + "\n"
        except Exception:
            return ""

    def save_transcript(self):
        text = self._transcript_text()
        if not text.strip():
            return
        path = filedialog.asksaveasfilename(
            parent=self.winfo_toplevel(), initialdir=get_last_dir("arena_transcript_save"), title="Export Arena Transcript", defaultextension=".txt",
            filetypes=[("Plain text", "*.txt"), ("Markdown", "*.md"), ("Structured JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        remember_path("arena_transcript_save", path)
        try:
            ext = os.path.splitext(path)[1].lower()
            if ext == '.json':
                scene = self.engine.scene
                payload = {
                    'format': 'dunoon-arena-transcript', 'version': 1,
                    'exported_at': datetime.now().isoformat(),
                    'scene_id': getattr(scene, 'scene_id', '') if scene else '',
                    'revision': int(getattr(scene, 'revision', 0) or 0) if scene else 0,
                    'participants': list(getattr(scene, 'participants', []) or []) if scene else [],
                    'entries': list(getattr(scene, 'log', []) or []) if scene else [],
                    'visible_text': text,
                }
                with open(path, 'w', encoding='utf-8') as fh:
                    json.dump(payload, fh, indent=2, ensure_ascii=False)
            elif ext == '.md':
                scene = self.engine.scene
                names = ' vs '.join(list(getattr(scene, 'participants', []) or [])) if scene else 'Arena'
                body = text.replace('\r\n','\n')
                with open(path, 'w', encoding='utf-8') as fh:
                    fh.write(f'# Dunoon Daemon Arena Transcript\n\n**{names}**\n\n```text\n{body}```\n')
            else:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
            self._set_activity("TRANSCRIPT EXPORTED", active=False)
        except Exception as exc:
            _arena_terminal(f"[ARENA][TRANSCRIPT EXPORT ERROR] {exc}")
            self._set_activity("TRANSCRIPT EXPORT FAILED", active=False)

    def open_transcript(self):
        path = filedialog.askopenfilename(
            parent=self.winfo_toplevel(), initialdir=get_last_dir("arena_transcript_open"), title="Open Arena Transcript",
            filetypes=[("Arena Transcript", "*.arena.txt"), ("Text", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        remember_path("arena_transcript_open", path)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except Exception as exc:
            _arena_terminal(f"[ARENA][TRANSCRIPT OPEN ERROR] {exc}")
            self._set_activity("TRANSCRIPT OPEN FAILED", active=False)
            return
        p = self._p()
        win = tk.Toplevel(self.winfo_toplevel())
        apply_window_icon(win)
        win.title("Arena Transcript · Read Only")
        win.geometry("820x640")
        win.minsize(560, 360)
        win.configure(bg=p["bg"])
        outer = tk.Frame(win, bg=p["bg"]); outer.pack(fill="both", expand=True, padx=16, pady=16)
        tk.Label(outer, text="ARENA TRANSCRIPT", bg=p["bg"], fg=p["accent"], font=("Segoe UI Semibold", 12)).pack(anchor="w")
        tk.Label(outer, text="Read-only reference. Opening a transcript never changes SceneStore, memory or turn ownership.", bg=p["bg"], fg=p["muted"], font=("Segoe UI", 8)).pack(anchor="w", pady=(2, 8))
        box_frame = tk.Frame(outer, bg=p["panel"], highlightbackground=p["border"], highlightthickness=1); box_frame.pack(fill="both", expand=True)
        box = tk.Text(box_frame, wrap="word", relief="flat", bd=0, bg=p["bg"], fg=p["text"], font=(self.chat_font_family, self.chat_font_size), padx=14, pady=12)
        scroll = tk.Scrollbar(box_frame, orient="vertical", command=box.yview, relief="flat", bd=0)
        box.configure(yscrollcommand=scroll.set); box.pack(side="left", fill="both", expand=True); scroll.pack(side="right", fill="y")
        box.insert("1.0", text); box.configure(state="disabled")
        tk.Button(outer, text="Close", command=win.destroy, relief="flat", bd=0, bg=p["button"], fg=p["button_fg"], activebackground=p["accent"], activeforeground=p["bg"], font=("Segoe UI Semibold", 9), padx=14, pady=7).pack(anchor="e", pady=(10, 0))
        center_after_idle(win, self.winfo_toplevel())

    def _commit_scene_save(self, path):
        try:
            self.engine.save_scene_snapshot(path)
            self._set_director(f"scene saved · revision {self.engine.scene.revision}")
            self._set_activity("SCENE SAVED", active=False)
            self._append("SYSTEM", f"Scene checkpoint saved at revision {self.engine.scene.revision}.", "system")
        except Exception as exc:
            _arena_terminal(f"[ARENA][SAVE ERROR] {exc}")
            self._set_activity("SCENE SAVE FAILED", active=False)
            self._append("SYSTEM", f"Scene checkpoint save failed: {exc}", "system")

    def _flush_pending_scene_save(self):
        path = self._pending_scene_save_path
        if not path or self.busy or not self.engine.started or not self.engine.scene:
            return False
        self._pending_scene_save_path = None
        self._commit_scene_save(path)
        return True

    def save_scene(self):
        if not self.engine.started or not self.engine.scene:
            return
        path = filedialog.asksaveasfilename(
            parent=self.winfo_toplevel(), initialdir=get_last_dir("arena_scene_save"), title="Save Arena Scene", defaultextension=".arena.json",
            filetypes=[("ArenaScene", "*.arena.json"), ("JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        remember_path("arena_scene_save", path)
        if self.busy:
            # Do not freeze/interrupt a speaking actor. Queue the snapshot and commit it at
            # the next safe UI boundary, after the current turn presentation completes.
            self._pending_scene_save_path = path
            self._append("YOU · SAVE", "Scene checkpoint requested; it will save at the next safe Arena boundary.", "human")
            self._set_activity("SCENE SAVE QUEUED", active=True)
            return
        self._commit_scene_save(path)

    def load_scene(self):
        if self.busy:
            return
        self.pause()
        path = filedialog.askopenfilename(
            parent=self.winfo_toplevel(), initialdir=get_last_dir("arena_scene_load"), title="Load Arena Scene",
            filetypes=[("ArenaScene", "*.arena.json"), ("JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        remember_path("arena_scene_load", path)
        try:
            scene = self.engine.load_scene_snapshot(path, list(self.sm.list_sessions()))
        except Exception as exc:
            _arena_terminal(f"[ARENA][LOAD ERROR] {exc}")
            reason = str(exc)
            self._set_director(reason)
            self._set_activity("SCENE LOAD FAILED", active=False)
            messagebox.showerror("Scene load failed", reason, parent=self.winfo_toplevel())
            return
        self._last_scene = scene
        self._refresh_personas()
        if len(self.engine.sessions) == 2:
            self._combo_select_session(self.persona_a, self.engine.sessions[0])
            self._combo_select_session(self.persona_b, self.engine.sessions[1])
        self._preview_selected()
        self.scenario.delete("1.0", "end")
        self.scenario.insert("1.0", scene.initial_prompt)
        self._stop_scene_entry_pulse()
        self.setup.pack_forget()
        self._set_controls(started=True)
        self._replay_loaded_scene(scene)
        self._update_actor_status(scene)
        self._set_director(f"scene loaded · revision {scene.revision}")
        self._set_activity("PAUSED · SCENE RESTORED", active=False)
        self._start_step_pulse()

    def step(self):
        if self.busy or not self.engine.started:
            return
        self._stop_step_pulse()
        self.busy = True
        self.step_btn.configure(state="disabled")
        self._set_director("calling next actor")

        def work():
            try:
                def progress(phase, actor):
                    if self.alive:
                        self.after(0, lambda ph=phase, a=actor: self._progress(ph, a))
                turn = self.engine.step(progress=progress)
                err = None
            except Exception as exc:
                turn, err = None, exc
            if self.alive:
                self.after(0, lambda: self._step_done(turn, err))
        threading.Thread(target=work, daemon=True).start()

    def _step_done(self, turn, err):
        if err:
            self.busy = False
            self.step_btn.configure(state="normal")
            # A save requested during speech should not become stranded merely because the
            # generation ended in a recoverable/runtime error. The last committed revision is
            # still a safe snapshot boundary.
            self._flush_pending_scene_save()
            if isinstance(err, ArenaRecoverableError):
                _arena_terminal(f"[ARENA][RECOVERABLE] {err.actor_name}: {err}")
                if err.actor_name == "Director":
                    self._set_director("causal outcome due · Director retrying under lock", active=True)
                    self._set_activity("DIRECTOR RETRYING", active=True)
                else:
                    self._set_director(f"retrying {err.actor_name} quietly")
                    self._set_activity(f"{err.actor_name} retrying", active=True)
                    self._set_actor_activity(err.actor_name, "↻ retrying…")
                if self.autoloop:
                    self.after(650, self.step)
                return
            _arena_terminal(f"[ARENA][STOPPED] {type(err).__name__}: {err}")
            self.autoloop = False
            self.auto_btn.configure(text="▶ Auto")
            self._set_director("backend / runtime stopped")
            self._set_activity("ARENA STOPPED", active=False)
            self._append("SYSTEM", f"Arena stopped: {err}", "system")
            return
        if not turn:
            self.busy = False
            self.step_btn.configure(state="normal")
            self._flush_pending_scene_save()
            return

        self._last_scene = turn.scene
        a_name = self.engine._name(self.engine.sessions[0]) if self.engine.sessions else ""
        tag = "actor_a_name" if turn.actor_name == a_name else "actor_b_name"
        self._set_activity(f"{turn.actor_name} speaking", active=True)
        self._set_actor_activity(turn.actor_name, "▶ speaking…")

        def presented():
            self.busy = False
            self.step_btn.configure(state="normal")
            self._update_actor_status(turn.scene)
            if getattr(turn, "resolution_pending", False):
                self._set_director("causal outcome due · Director has resolution lock", active=True)
                self._set_activity("DIRECTOR RESOLUTION LOCK", active=True)
            else:
                self._set_director(f"reality updated · revision {turn.scene.revision}")
                self._set_activity("READY", active=False)
            self._flush_pending_scene_save()
            if turn.ended:
                self.autoloop = False
                self.auto_btn.configure(text="▶ Auto")
                self._append("SYSTEM", "No living participants remain. Autoloop stopped.", "system")
                return
            if self._dispatch_next_pending_human():
                return
            if self.autoloop:
                self.after(180, self.step)

        self._stream_append(turn.actor_name, turn.text, tag, on_complete=presented)

    def toggle_auto(self):
        if not self.engine.started:
            return
        self._stop_step_pulse()
        self.autoloop = not self.autoloop
        self.auto_btn.configure(text="❚❚ Pause" if self.autoloop else "▶ Auto")
        self._set_activity("AUTO RUNNING" if self.autoloop else "PAUSED", active=self.autoloop)
        if self.autoloop and not self.busy:
            self.step()

    def pause(self):
        self.autoloop = False
        self.auto_btn.configure(text="▶ Auto")
        self._set_director("paused by human")
        self._set_activity("PAUSED", active=False)

    def _take_human_text(self):
        text = self.intervene_entry.get().strip()
        if text:
            self.intervene_entry.delete(0, "end")
        return text

    def upload(self):
        path = filedialog.askopenfilename(
            parent=self.winfo_toplevel(), initialdir=get_last_dir("arena_upload"),
            title="Upload to Arena",
            filetypes=[
                ("Supported", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.mp3 *.wav *.m4a *.flac *.ogg *.pdf *.docx *.txt *.py *.md *.json *.csv *.log *.js *.cpp"),
                ("Images", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"),
                ("Documents", "*.pdf *.docx *.txt *.md *.csv *.log"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        remember_path("arena_upload", path)
        self._staged_upload = path
        name = os.path.basename(path)
        short = name if len(name) <= 18 else name[:15] + "…"
        self.upload_btn.configure(text=f"📎 {short}")
        self._set_activity("ATTACHMENT STAGED", active=False)

    def _consume_human_payload(self):
        """Return (authoritative_text, image_path, display_text).

        Image paths are kept structured and never exposed as narrative text. The primary
        model receives the actual image bytes through the native multimodal transport.
        """
        text = self._take_human_text()
        path = self._staged_upload
        self._staged_upload = None
        try:
            self.upload_btn.configure(text="Upload")
        except Exception:
            pass
        if not path:
            return text, None, text
        try:
            from dunoon_daemon import UniversalFileProcessor
            parsed = UniversalFileProcessor().process_file(path)
            content = str(parsed.get("content", "") or "").strip()
            name = str(parsed.get("file_name", "") or os.path.basename(path))
            kind = str(parsed.get("type", "file") or "file")
            if kind == "image":
                attachment = f"[Attached Image: {name}]"
                authoritative = (text + "\n\n" + attachment).strip() if text else attachment
                return authoritative, path, text or attachment
            attachment = content or f"[Attached File: {name}]"
        except Exception as exc:
            attachment = f"[Attached File: {os.path.basename(path)}] [ingestion error: {exc}]"
        authoritative = (text + "\n\n" + attachment).strip() if text else attachment
        return authoritative, None, authoritative

    def _set_guidance_pending(self, pending: bool, kind: str = "guidance"):
        if self._guidance_pulse_job is not None:
            try:
                self.after_cancel(self._guidance_pulse_job)
            except Exception:
                pass
            self._guidance_pulse_job = None
        self._guidance_pending_kind = str(kind or "guidance") if pending else ""
        self._guidance_pulse_tick = False
        p = self._p()
        if not pending:
            try:
                self.intervene_label.configure(text="GUIDE YOUR STORY", fg=p["accent"])
                self.intervene_box.configure(highlightbackground=p["accent"])
            except Exception:
                pass
            return

        label = "EVENT PENDING…" if kind.startswith("event") else "GUIDANCE PENDING…"

        def pulse():
            if not self.alive or not self._guidance_pending_kind:
                return
            self._guidance_pulse_tick = not self._guidance_pulse_tick
            colour = p.get("accent2", p["accent"]) if self._guidance_pulse_tick else p["accent"]
            try:
                self.intervene_label.configure(text=label, fg=colour)
                self.intervene_box.configure(highlightbackground=colour)
            except Exception:
                return
            self._guidance_pulse_job = self.after(420, pulse)

        pulse()

    def user_input(self):
        if not self.engine.started:
            return
        text, image_path, display_text = self._consume_human_payload()
        if text:
            self._queue_or_dispatch_human("user_input", text, image_path=image_path, display_text=display_text)

    def event(self):
        if not self.engine.started:
            return
        text = self._take_human_text()
        if text:
            self._queue_or_dispatch_human("event", text)
        else:
            # Match Solo: acknowledge the asynchronous Event in the transcript immediately.
            self._append("SYSTEM", "⚡ Event pending…", "system")
            self._queue_or_dispatch_human("event_generate", "")

    def _random_event_done(self, text, scene, err):
        if err:
            self._intervention_done(None, err, kind="event")
            return
        self._append("DIRECTOR · EVENT", text, "human")
        self._intervention_done(scene, None, kind="event")

    def intervene(self):
        """Compatibility alias: Event is the authoritative external-change control."""
        self.event()

    def _queue_or_dispatch_human(self, kind, text, image_path=None, display_text=None):
        if not self.engine.started:
            return
        label_kind = "event" if str(kind).startswith("event") else "guidance"
        if self.busy:
            # Never overwrite human steering while Auto is thinking/streaming. Every submitted
            # instruction is preserved in FIFO order and applied at the next safe boundary.
            self._pending_human_actions.append((kind, text, image_path, display_text))
            if label_kind == "event":
                self._append("SYSTEM", "Event queued. Auto remains active; it will enter at the next safe Arena boundary.", "system")
            else:
                self._append("SYSTEM", "Guidance queued. Auto remains active; your live scene edit will enter at the next safe Arena boundary.", "system")
            self._set_guidance_pending(True, label_kind)
            self._set_activity(f"{label_kind.upper()} QUEUED · AUTO CONTINUES", active=self.autoloop)
            return
        self._set_guidance_pending(True, label_kind)
        self._dispatch_human_action(kind, text, image_path=image_path, display_text=display_text)

    def _dispatch_next_pending_human(self):
        """Apply queued human steering in order; never let Auto overwrite/drop it."""
        if not self._pending_human_actions:
            return False
        kind, text, image_path, display_text = self._pending_human_actions.popleft()
        label_kind = "event" if str(kind).startswith("event") else "guidance"
        # Keep the visual pending state alive while more human work is being drained.
        self._set_guidance_pending(True, label_kind)
        self.after(0, lambda k=kind, t=text, ip=image_path, dt=display_text: self._dispatch_human_action(k, t, image_path=ip, display_text=dt))
        return True

    def _dispatch_human_action(self, kind, text, image_path=None, display_text=None):
        if kind == "user_input":
            self._append("YOU", display_text if display_text is not None else text, "human", image_path=image_path)
            try:
                scene = self.engine.user_input(text, image_path=image_path)
            except Exception as exc:
                self._intervention_done(None, exc, kind="input")
                return
            self._intervention_done(scene, None, kind="input")
            return

        if kind == "event":
            self._append("YOU · EVENT", text, "human")
            try:
                scene = self.engine.apply_event(text)
            except Exception as exc:
                self._intervention_done(None, exc, kind="event")
                return
            self._intervention_done(scene, None, kind="event")
            return

        # Contextual generated Event: exactly one primary-model call, then deterministic
        # authoritative application. Auto stays logically enabled throughout.
        self.busy = True
        self._set_director("generating contextual scene event", active=True)
        self._set_activity("EVENT GENERATING · AUTO ARMED" if self.autoloop else "EVENT GENERATING", active=True)

        def work():
            try:
                generated = self.engine.generate_random_event()
                scene = self.engine.apply_event(generated)
                err = None
            except Exception as exc:
                generated, scene, err = "", None, exc
            if self.alive:
                self.after(0, lambda: self._random_event_done(generated, scene, err))
        threading.Thread(target=work, daemon=True).start()

    def _intervention_done(self, scene, err, kind="event"):
        self.busy = False
        self._set_guidance_pending(False)
        if err:
            _arena_terminal(f"[ARENA][HUMAN {kind.upper()} ERROR] {err}")
            self._set_director(f"human {kind} failed")
            self._set_activity("AUTO RUNNING" if self.autoloop else f"{kind.upper()} FAILED", active=self.autoloop)
            if self._dispatch_next_pending_human():
                return
            if self.autoloop:
                self.after(180, self.step)
            return
        self._last_scene = scene
        self._update_actor_status(scene)
        if kind == "input":
            self._append("SYSTEM", "Guidance applied as an authoritative live edit of the Arena scenario.", "system")
            self._set_director(f"guidance applied · revision {scene.revision}")
        else:
            self._append("SYSTEM", "Event applied to authoritative shared reality.", "system")
            self._set_director(f"event accepted · revision {scene.revision}")
        self._set_activity("AUTO RUNNING" if self.autoloop else "READY", active=self.autoloop)
        if self._dispatch_next_pending_human():
            return
        if self.autoloop:
            self.after(180, self.step)

    def _update_actor_status(self, scene):
        if not self.engine.sessions:
            return
        a, b = self.engine.sessions
        self._set_actor_panel(self.actor_a_panel, a, scene.actor_status.get(self.engine._name(a), "alive"))
        self._set_actor_panel(self.actor_b_panel, b, scene.actor_status.get(self.engine._name(b), "alive"))

    def _show_reality(self):
        scene = self.engine.scene or self._last_scene
        if not scene:
            return
        p = self._p()
        win = tk.Toplevel(self)
        apply_window_icon(win)
        win.title("Current Reality")
        win.geometry("660x500")
        win.configure(bg=p["bg"])
        tk.Label(win, text=f"CURRENT REALITY · REVISION {scene.revision}", bg=p["bg"], fg=p["muted"], font=("Segoe UI Semibold", 8)).pack(anchor="w", padx=18, pady=(16, 8))
        box = tk.Text(win, wrap="word", relief="flat", bd=0, bg=p["panel"], fg=p["text"], font=(self.chat_font_family, self.chat_font_size), padx=14, pady=12)
        box.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        body = scene.current_reality
        directives = [x for x in (getattr(scene, "live_directives", []) or []) if isinstance(x, dict) and bool(x.get("active", True)) and str(x.get("text", "") or "").strip()]
        if directives:
            body += "\n\nLIVE USER DIRECTIVES · AUTHORITATIVE\n" + "\n".join(f"• {str(x.get('text', '') or '').strip()}" for x in directives[-12:])
        commitments = {k: v for k, v in getattr(scene, "active_commitments", {}).items() if str(v).strip()}
        if commitments:
            body += "\n\nUNFINISHED PHYSICAL ACTIONS\n" + "\n".join(f"• {k}: {v}" for k, v in commitments.items())
        box.insert("1.0", body)
        box.configure(state="disabled")
        tk.Label(win, text="Read-only. Opening this window does not alter the scene.", bg=p["bg"], fg=p["muted"], font=("Segoe UI", 8)).pack(anchor="w", padx=18, pady=(0, 14))
        center_after_idle(win, self)

    def apply_skin(self, skin_name):
        self.skin_name = skin_name
        p = self._p()
        apply_combobox_theme(self.winfo_toplevel(), skin_name)
        self.configure(bg=p["panel"])
        self.activity_strip.configure(bg=p["accent"] if self._activity_active else p["panel"])
        for frame in (self.header, self.participant_row, self.intervene_outer, self.scene_tools, self.detail_control):
            frame.configure(bg=p["panel"])
        self.title.configure(bg=p["panel"], fg=p["text"])
        self.director_status.configure(bg=p["panel"], fg=p["muted"])
        self.activity_pill.configure(bg=p["panel2"], fg=p["accent"] if self._activity_active else p["muted"])
        self.vs_label.configure(bg=p["panel"], fg=p["muted"])
        for panel in (self.actor_a_panel, self.actor_b_panel):
            panel.configure(bg=p["bg"], highlightbackground=p["border"])
            panel._box.configure(bg=p["bg"])
            panel._badge.configure(bg=p["panel2"], fg=p["accent"])
            panel._name.configure(bg=p["bg"], fg=p["text"])
            panel._status.configure(bg=p["bg"])
        self.setup.configure(bg=p["bg"], highlightbackground=p["border"])
        for child in self.setup.winfo_children():
            if isinstance(child, tk.Frame):
                child.configure(bg=p["bg"])
                for sub in child.winfo_children():
                    if isinstance(sub, tk.Label):
                        sub.configure(bg=p["bg"], fg=p["muted"])
        self.scenario.configure(bg=p["panel2"], fg=p["text"], insertbackground=p["accent"])
        self.scene_tools.configure(bg=p["panel"])
        self.scene_tools_label.configure(bg=p["panel"], fg=p["muted"])
        self.detail_control.configure(bg=p["panel"])
        self.detail_text.configure(bg=p["panel"], fg=p["muted"])
        self.detail_slider.configure(bg=p["panel"], fg=p["text"], troughcolor=p["button"], activebackground=p["accent"])
        self.block_director_check.configure(bg=p["panel"], fg=p["text"], activebackground=p["panel"], activeforeground=p["text"], selectcolor=p["panel2"])
        self.transcript_outer.configure(bg=p["bg"], highlightbackground=p["border"])
        self.transcript.configure(bg=p["bg"], fg=p["text"])
        self.transcript.tag_config("actor_a_name", foreground=p["accent"])
        self.transcript.tag_config("actor_b_name", foreground=p["accent2"])
        self.transcript.tag_config("body", foreground=p["text"])
        self.transcript.tag_config("human", foreground=p["accent"])
        self.transcript.tag_config("system", foreground=p["muted"])
        self.intervene_box.configure(bg=p["panel2"], highlightbackground=p["accent"])
        self.intervene_actions.configure(bg=p["panel2"])
        self.intervene_label.configure(bg=p["panel2"], fg=p["accent"])
        self.intervene_entry.configure(bg=p["panel2"], fg=p["text"], insertbackground=p["accent"])
        for btn in (self.font_btn, self.reality_btn, self.save_scene_btn, self.load_scene_btn, self.save_transcript_btn, self.load_transcript_btn, self.step_btn, self.event_btn, self.paste_btn, self.upload_btn, self.scenario_paste_btn):
            btn.configure(bg=p["button"], fg=p["button_fg"], activebackground=p["accent"], activeforeground=p["bg"])
        for btn in (self.auto_btn, self.start_btn, self.user_input_btn):
            btn.configure(bg=p["accent"], fg=p["bg"], activebackground=p["accent"], activeforeground=p["bg"])
        self._apply_chat_fonts()

    def shutdown(self):
        self.alive = False
        self.autoloop = False
        self._stop_step_pulse()
        self._stop_scene_entry_pulse()
        if self._activity_job is not None:
            try:
                self.after_cancel(self._activity_job)
            except Exception:
                pass
            self._activity_job = None
