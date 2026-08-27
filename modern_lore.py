from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from campaign_lore import LORE_DEPTHS, LoreLibrary
from last_dirs import get_last_dir, remember_path
from modern_theme import palette, apply_combobox_theme
from modern_tooltips import register_tooltip, ensure_button_tooltips
from ui_windowing import apply_window_icon, center_after_idle


class LoreLibraryDialog(tk.Toplevel):
    """Simple human-owned many-to-many campaign lore assignment surface."""

    def __init__(self, parent, skin_name: str, session_manager, focus_session=None):
        super().__init__(parent)
        apply_window_icon(self)
        self.p = palette(skin_name)
        self.skin_name = skin_name
        self.sm = session_manager
        self.focus_session = focus_session
        self.library = LoreLibrary()
        self._tooltips = []
        self._row_vars = {}
        self.title("Lore")
        self.geometry("900x680")
        self.minsize(720, 500)
        self.configure(bg=self.p["bg"])
        self.transient(parent)
        apply_combobox_theme(self, skin_name)
        self._build()
        center_after_idle(self, parent)

    def _tip(self, widget, text):
        return register_tooltip(self._tooltips, widget, text)

    def _button(self, parent, text, command, accent=False):
        p = self.p
        btn = tk.Button(
            parent, text=text, command=command, relief="flat", bd=0,
            bg=p["accent"] if accent else p["button"],
            fg=p["bg"] if accent else p["button_fg"],
            activebackground=p["accent"], activeforeground=p["bg"],
            font=("Segoe UI Semibold", 9), padx=11, pady=7, cursor="hand2",
        )
        return btn

    def _sessions(self):
        try:
            return list(self.sm.list_sessions())
        except Exception:
            return []

    def _build(self):
        p = self.p
        head = tk.Frame(self, bg=p["bg"]); head.pack(fill="x", padx=20, pady=(18, 10))
        tk.Label(head, text="CAMPAIGN LORE", bg=p["bg"], fg=p["text"], font=("Segoe UI Semibold", 15)).pack(anchor="w")
        tk.Label(
            head,
            text="World knowledge is not automatically character knowledge. Upload sources, then tick only the personas allowed to know each one.",
            bg=p["bg"], fg=p["muted"], font=("Segoe UI", 9), wraplength=850, justify="left",
        ).pack(anchor="w", pady=(3, 0))
        tk.Label(
            head,
            text="Depth is source-level: Baseline = obvious/common knowledge, Intermediate = politics / history / trade, Advanced = obscure / deep knowledge. Secrets is privileged knowledge and is separate from depth.",
            bg=p["bg"], fg=p["muted"], font=("Segoe UI", 8), wraplength=850, justify="left",
        ).pack(anchor="w", pady=(3, 0))

        actions = tk.Frame(self, bg=p["bg"]); actions.pack(fill="x", padx=20, pady=(0, 10))
        upload = self._button(actions, "Upload lore…", self._upload, accent=True); upload.pack(side="left")
        self._tip(upload, "Add a readable lore source to the library. No persona is assigned automatically.")
        close = self._button(actions, "Close", self.destroy); close.pack(side="right")
        self._tip(close, "Close the Lore library. Assignments are saved immediately.")

        wrap = tk.Frame(self, bg=p["bg"]); wrap.pack(fill="both", expand=True, padx=(20, 10), pady=(0, 18))
        self.canvas = tk.Canvas(wrap, bg=p["bg"], highlightthickness=0, bd=0)
        sb = tk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y", padx=(6, 0))
        self.rows = tk.Frame(self.canvas, bg=p["bg"])
        self._window = self.canvas.create_window((0, 0), window=self.rows, anchor="nw")
        self.rows.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._window, width=e.width))
        self._refresh()
        ensure_button_tooltips(self, self._tooltips)

    def _process_file(self, path: str) -> tuple[str, str]:
        from dunoon_daemon import UniversalFileProcessor
        result = UniversalFileProcessor().process_file(path)
        kind = str(result.get("type") or "")
        text = str(result.get("content") or "").strip()
        if kind != "text" or not text:
            raise ValueError("Lore accepts readable text, PDF, DOCX and source / document files. Images require a text description first.")
        if "library not installed" in text.lower() or text.startswith("(Error reading"):
            raise ValueError(text)
        return str(result.get("file_name") or os.path.basename(path)), text

    def _upload(self):
        path = filedialog.askopenfilename(
            parent=self, initialdir=get_last_dir("lore_upload"), title="Upload lore source",
            filetypes=[
                ("Lore documents", "*.txt *.md *.pdf *.docx *.json *.csv *.log *.html *.xml *.py"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        remember_path("lore_upload", path)
        try:
            file_name, text = self._process_file(path)
            name = os.path.splitext(file_name)[0] or file_name
            self.library.add_source(name, text, file_name=file_name)
            self._refresh()
        except Exception as exc:
            messagebox.showerror("Lore upload failed", str(exc), parent=self)

    def _replace(self, source_id: str):
        path = filedialog.askopenfilename(
            parent=self, initialdir=get_last_dir("lore_replace"), title="Replace lore source",
            filetypes=[("Lore documents", "*.txt *.md *.pdf *.docx *.json *.csv *.log *.html *.xml *.py"), ("All files", "*.*")],
        )
        if not path:
            return
        remember_path("lore_replace", path)
        try:
            file_name, text = self._process_file(path)
            self.library.replace_source_text(source_id, text, file_name=file_name)
            self._refresh()
        except Exception as exc:
            messagebox.showerror("Lore replace failed", str(exc), parent=self)

    def _remove(self, source_id: str, name: str):
        if not messagebox.askyesno("Remove lore source?", f"Remove '{name}' from the Lore library?\n\nThis removes the source for every persona assigned to it.", parent=self):
            return
        try:
            self.library.remove_source(source_id)
            self._refresh()
        except Exception as exc:
            messagebox.showerror("Lore remove failed", str(exc), parent=self)

    def _save_meta(self, source_id: str, name_var, depth_var, secrets_var):
        try:
            self.library.update_source(source_id, name=name_var.get(), depth=depth_var.get(), secrets=secrets_var.get())
        except Exception as exc:
            messagebox.showerror("Lore save failed", str(exc), parent=self)

    def _toggle_persona(self, source_id: str, persona_id: str, var):
        try:
            self.library.set_assignment(source_id, persona_id, bool(var.get()))
        except Exception as exc:
            messagebox.showerror("Lore assignment failed", str(exc), parent=self)

    def _refresh(self):
        p = self.p
        for child in self.rows.winfo_children():
            child.destroy()
        self._row_vars.clear()
        sources = self.library.list_sources()
        sessions = self._sessions()
        if not sources:
            tk.Label(self.rows, text="No lore sources yet. Upload a source, then assign it explicitly to one or more personas.", bg=p["bg"], fg=p["muted"], font=("Segoe UI", 10), wraplength=760, justify="left").pack(anchor="w", pady=18)
            return

        focus_id = str(getattr(self.focus_session, "id", "") or getattr(self.focus_session, "session_id", "") or "")
        ordered_sessions = sorted(sessions, key=lambda s: (0 if str(getattr(s, "id", "")) == focus_id else 1, str(getattr(s, "agent_name", "")).casefold()))
        for source in sources:
            card = tk.Frame(self.rows, bg=p["panel"], highlightbackground=p["border"], highlightthickness=1)
            card.pack(fill="x", pady=(0, 10))
            top = tk.Frame(card, bg=p["panel"]); top.pack(fill="x", padx=12, pady=(10, 7))
            name_var = tk.StringVar(value=source["name"])
            name_entry = tk.Entry(top, textvariable=name_var, bg=p["panel2"], fg=p["text"], insertbackground=p["accent"], relief="flat", bd=0, font=("Segoe UI Semibold", 9))
            name_entry.pack(side="left", fill="x", expand=True, ipady=5)
            self._tip(name_entry, "Edit the library name for this source. Press Save source to persist it.")
            depth_var = tk.StringVar(value=source.get("depth", "baseline"))
            depth = ttk.Combobox(top, textvariable=depth_var, values=list(LORE_DEPTHS), state="readonly", width=13)
            depth.pack(side="left", padx=(8, 4))
            self._tip(depth, "Set the knowledge depth represented by this source.")
            secrets_var = tk.BooleanVar(value=bool(source.get("secrets", False)))
            secrets = tk.Checkbutton(top, text="Secrets", variable=secrets_var, bg=p["panel"], fg=p["text"], activebackground=p["panel"], activeforeground=p["text"], selectcolor=p["panel2"], font=("Segoe UI", 8), cursor="hand2")
            secrets.pack(side="left", padx=4)
            self._tip(secrets, "Mark this source as privileged / secret knowledge. Assignment remains entirely human-controlled.")
            save = self._button(top, "Save source", lambda sid=source["id"], nv=name_var, dv=depth_var, sv=secrets_var: self._save_meta(sid, nv, dv, sv))
            save.pack(side="left", padx=(4, 0)); self._tip(save, "Save this source name, depth and Secrets flag.")

            meta = tk.Frame(card, bg=p["panel"]); meta.pack(fill="x", padx=12, pady=(0, 6))
            original = source.get("file_name") or "Stored text"
            tk.Label(meta, text=f"Source: {original}", bg=p["panel"], fg=p["muted"], font=("Segoe UI", 8)).pack(side="left")
            replace = self._button(meta, "Replace…", lambda sid=source["id"]: self._replace(sid)); replace.pack(side="right", padx=(6, 0))
            self._tip(replace, "Replace the stored text while preserving assignments and source settings.")
            remove = self._button(meta, "Remove", lambda sid=source["id"], nm=source["name"]: self._remove(sid, nm)); remove.pack(side="right")
            self._tip(remove, "Remove this lore source and all of its persona assignments.")

            assign = tk.Frame(card, bg=p["panel2"]); assign.pack(fill="x", padx=12, pady=(0, 10))
            tk.Label(assign, text="PERSONAS ALLOWED TO KNOW THIS SOURCE", bg=p["panel2"], fg=p["muted"], font=("Segoe UI Semibold", 8)).pack(anchor="w", padx=9, pady=(7, 3))
            assigned = set(source.get("persona_ids") or [])
            if not ordered_sessions:
                tk.Label(assign, text="No personas exist yet.", bg=p["panel2"], fg=p["muted"], font=("Segoe UI", 8)).pack(anchor="w", padx=9, pady=(0, 7))
            for sess in ordered_sessions:
                pid = str(getattr(sess, "id", None) or getattr(sess, "session_id", "") or "")
                if not pid:
                    continue
                var = tk.BooleanVar(value=pid in assigned)
                label = str(getattr(sess, "agent_name", "Persona") or "Persona")
                cb = tk.Checkbutton(assign, text=label, variable=var, command=lambda sid=source["id"], p_id=pid, v=var: self._toggle_persona(sid, p_id, v), bg=p["panel2"], fg=p["text"], activebackground=p["panel2"], activeforeground=p["text"], selectcolor=p["panel"], font=("Segoe UI", 8), cursor="hand2")
                cb.pack(side="left", padx=(9, 5), pady=(0, 7))
                self._tip(cb, f"Allow {label} to retrieve relevant excerpts from this source.")
        ensure_button_tooltips(self, self._tooltips)
