from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox

from character import TRAIT_DICTIONARY, apply_ocean_base_scores, randomise_ocean_profile
from memory_lifecycle import purge_persona_memories
from persona import roll_persona
from last_dirs import get_last_dir, remember_path
from modern_theme import palette
from modern_tooltips import register_tooltip, ensure_button_tooltips
from persona_import import IMPORT_MODES, PersonaImportError, import_persona_from_source, is_image_file
from persona_media import set_persona_avatar
from ui_windowing import center_after_idle, apply_window_icon

TRAITS = ["Openness", "Conscientiousness", "Extraversion", "Agreeableness", "Neuroticism"]


class PersonaEditorDialog(tk.Toplevel):
    """Modern-shell persona editor with scrolling, undo and guarded OCEAN editing."""

    def __init__(self, parent, skin_name, session, session_manager, on_saved=None, brain=None):
        super().__init__(parent)
        apply_window_icon(self)
        self.session = session
        self.sm = session_manager
        self.on_saved = on_saved
        self.brain = brain
        self.p = palette(skin_name)
        self._random_profile = None
        self._tooltips = []
        self._ocean_controls = []
        self._undo_stack = []
        self._restoring = False
        self._pending_avatar_source_path = ""
        self._pending_import_notes = ""
        self._pending_import_source_name = ""
        self._pending_avatar_temp_path = ""
        agent = str(getattr(session, "agent_name", "") or "").strip()
        self.title(f"Persona · {agent or 'Untitled'}")
        self.geometry("880x790")
        self.minsize(740, 590)
        self.configure(bg=self.p["bg"])
        self.transient(parent)
        self._build()
        ensure_button_tooltips(self, self._tooltips)
        self.after_idle(self._arm_undo_tracking)
        center_after_idle(self, parent)

    def _tip(self, widget, text):
        return register_tooltip(self._tooltips, widget, text)

    def _label(self, parent, text, *, accent=False, size=9):
        return tk.Label(
            parent,
            text=text,
            bg=self.p["bg"],
            fg=self.p["accent"] if accent else self.p["text"],
            font=("Segoe UI Semibold", size),
        )

    def _entry(self, parent, value=""):
        e = tk.Entry(
            parent,
            bg=self.p["panel2"],
            fg=self.p["text"],
            insertbackground=self.p["accent"],
            relief="flat",
            bd=0,
            font=("Segoe UI", 9),
        )
        if value:
            e.insert(0, value)
        return e

    def _scroll_text(self, parent, *, height=6):
        wrap = tk.Frame(parent, bg=self.p["panel2"])
        text = tk.Text(
            wrap,
            height=height,
            wrap="word",
            undo=True,
            maxundo=100,
            bg=self.p["panel2"],
            fg=self.p["text"],
            insertbackground=self.p["accent"],
            relief="flat",
            bd=0,
            font=("Segoe UI", 9),
            padx=7,
            pady=7,
        )
        sb = tk.Scrollbar(wrap, orient="vertical", command=text.yview, relief="flat", bd=0)
        text.configure(yscrollcommand=sb.set)
        text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return wrap, text

    def _bind_mousewheel(self, _widget):
        self.bind("<MouseWheel>", self._on_mousewheel, add="+")
        self.bind("<Button-4>", lambda _e: self.body_canvas.yview_scroll(-1, "units"), add="+")
        self.bind("<Button-5>", lambda _e: self.body_canvas.yview_scroll(1, "units"), add="+")

    def _on_mousewheel(self, event):
        # Let a focused multiline editor consume its own wheel first.
        try:
            focus = self.focus_get()
            if focus in (getattr(self, "phys", None), getattr(self, "powers", None)):
                delta = int(event.delta)
                if delta:
                    focus.yview_scroll(int(-delta / 120) or (-1 if delta > 0 else 1), "units")
                    return "break"
        except Exception:
            pass
        try:
            delta = int(event.delta)
            if delta:
                self.body_canvas.yview_scroll(int(-delta / 120) or (-1 if delta > 0 else 1), "units")
        except Exception:
            pass

    def _build(self):
        p = self.p

        header = tk.Frame(self, bg=p["bg"])
        header.pack(fill="x", padx=20, pady=(18, 8))
        tk.Label(header, text="PERSONA & OCEAN", bg=p["bg"], fg=p["text"], font=("Segoe UI Semibold", 15)).pack(anchor="w")
        tk.Label(
            header,
            text="Edit identity, behaviour and memory guidance. OCEAN affects style, not world authority.",
            bg=p["bg"], fg=p["muted"], font=("Segoe UI", 9), wraplength=830, justify="left"
        ).pack(anchor="w", pady=(3, 0))

        body_wrap = tk.Frame(self, bg=p["bg"])
        body_wrap.pack(fill="both", expand=True, padx=(20, 10), pady=(4, 0))
        self.body_canvas = tk.Canvas(body_wrap, bg=p["bg"], highlightthickness=0, bd=0)
        self.body_scrollbar = tk.Scrollbar(body_wrap, orient="vertical", command=self.body_canvas.yview)
        self.body_canvas.configure(yscrollcommand=self.body_scrollbar.set)
        self.body_canvas.pack(side="left", fill="both", expand=True)
        self.body_scrollbar.pack(side="right", fill="y", padx=(6, 0))

        body = tk.Frame(self.body_canvas, bg=p["bg"])
        self._body_window = self.body_canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _e: self.body_canvas.configure(scrollregion=self.body_canvas.bbox("all")))
        self.body_canvas.bind("<Configure>", lambda e: self.body_canvas.itemconfigure(self._body_window, width=e.width))
        self._bind_mousewheel(self.body_canvas)

        body.columnconfigure(0, weight=1, uniform="persona_cols")
        body.columnconfigure(1, weight=1, uniform="persona_cols")
        left = tk.Frame(body, bg=p["bg"])
        right = tk.Frame(body, bg=p["bg"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12), pady=(2, 12))
        right.grid(row=0, column=1, sticky="nsew", padx=(12, 0), pady=(2, 12))

        identity_head = self._label(left, "Identity", accent=True)
        identity_head.pack(anchor="w")

        name_label = self._label(left, "Display name")
        name_label.pack(anchor="w", pady=(8, 2))
        self.name = self._entry(left, str(getattr(self.session, "agent_name", "") or ""))
        self.name.pack(fill="x", ipady=6)
        self._tip(self.name, "Name shown for this persona.")

        prompt_label = self._label(left, "Core persona directives")
        prompt_label.pack(anchor="w", pady=(9, 2))
        self.prompt = tk.Text(left, height=7, wrap="word", undo=True, maxundo=100, bg=p["panel2"], fg=p["text"], insertbackground=p["accent"], relief="flat", bd=0, font=("Segoe UI", 9), padx=7, pady=7)
        self.prompt.pack(fill="x")
        self.prompt.insert("1.0", str(getattr(self.session, "system_prompt", "") or ""))
        self._tip(self.prompt, "Strongest voice and behaviour instructions.")

        seedrow = tk.Frame(left, bg=p["bg"])
        seedrow.pack(fill="x", pady=(6, 0))
        self.seed = self._entry(seedrow, "")
        self.seed.pack(side="left", fill="x", expand=True, ipady=5)
        self.roll_button = tk.Button(seedrow, text="🎲 Roll persona", command=self._roll, bg=p["button"], fg=p["button_fg"], relief="flat", bd=0, font=("Segoe UI Semibold", 8), padx=8, pady=5)
        self.roll_button.pack(side="left", padx=(6, 0))
        self.import_button = tk.Button(seedrow, text="Import from file…", command=self._import_from_file, bg=p["button"], fg=p["button_fg"], relief="flat", bd=0, font=("Segoe UI Semibold", 8), padx=8, pady=5)
        self.import_button.pack(side="left", padx=(6, 0))
        self.import_status = tk.Label(left, text="", wraplength=385, justify="left", bg=p["bg"], fg=p["muted"], font=("Segoe UI", 8))
        self.import_status.pack(anchor="w", pady=(5, 0))
        self._tip(self.seed, "Optional seed for the persona roller.")
        self._tip(self.roll_button, "Generate a name and core directive.")
        self._tip(self.import_button, "Populate the editor from a character sheet, lore file, stat block or reference image.")

        backstory_label = self._label(left, "Backstory / history")
        backstory_label.pack(anchor="w", pady=(9, 2))
        self.backstory = tk.Text(left, height=5, wrap="word", undo=True, maxundo=100, bg=p["panel2"], fg=p["text"], insertbackground=p["accent"], relief="flat", bd=0, font=("Segoe UI", 9), padx=7, pady=7)
        self.backstory.pack(fill="x")
        self.backstory.insert("1.0", str(getattr(self.session, "backstory", "") or ""))
        self._tip(self.backstory, "Established history for this persona.")

        phys_label = self._label(left, "Physiology")
        phys_label.pack(anchor="w", pady=(9, 2))
        phys_wrap, self.phys = self._scroll_text(left, height=6)
        phys_wrap.pack(fill="x")
        self.phys.insert("1.0", str(getattr(self.session, "physiology", "") or ""))
        self._tip(self.phys, "Physical form and biological constraints.")

        powers_label = self._label(left, "Powers / skills")
        powers_label.pack(anchor="w", pady=(9, 2))
        powers_wrap, self.powers = self._scroll_text(left, height=6)
        powers_wrap.pack(fill="x")
        self.powers.insert("1.0", str(getattr(self.session, "powers", "") or ""))
        self._tip(self.powers, "Established powers, equipment and trained skills.")

        guidance_label = self._label(left, "Dream preservation guidance")
        guidance_label.pack(anchor="w", pady=(9, 2))
        self.guidance = self._entry(left, str(getattr(self.session, "dream_guidance", "") or ""))
        self.guidance.pack(fill="x", ipady=5)
        guidance_note = tk.Label(left, text="Optional subjects, relationships or themes Dream should preserve carefully.", wraplength=385, justify="left", bg=p["bg"], fg=p["muted"], font=("Segoe UI", 8))
        guidance_note.pack(anchor="w", pady=(2, 0))
        self._tip(self.guidance, "Extra guidance for Dream memory maintenance.")

        # All persona-level switches live together at the top of the right column.
        options_head = self._label(right, "Persona options", accent=True)
        options_head.pack(anchor="w", pady=(0, 4))
        options_note = tk.Label(
            right,
            text="Persistent switches for this persona. Human and accepted-world authority still outrank them.",
            wraplength=385, justify="left", bg=p["bg"], fg=p["muted"], font=("Segoe UI", 8),
        )
        options_note.pack(anchor="w", pady=(0, 5))

        self.eto = tk.BooleanVar(value=bool(getattr(self.session, "eto_enabled", True)))
        self.nf = tk.BooleanVar(value=bool(getattr(self.session, "narrative_freedom", False)))
        self.mortality = tk.BooleanVar(value=bool(getattr(self.session, "mortality_enabled", False)))
        self.share = tk.BooleanVar(value=bool(getattr(self.session, "share_insights", False)))
        self.blind = tk.BooleanVar(value=bool(getattr(self.session, "blind_to_others", False)))
        self.ocean_locked = tk.BooleanVar(value=bool(getattr(self.session, "ocean_controls_locked", False)))

        option_defs = [
            ("Enable ETO engine", self.eto, "Use Environment, Threat and Opportunity grounding."),
            ("Allow collaborative plot / worldbuilding", self.nf, "Allow plausible scene invention without overriding established reality."),
            ("Mortality enabled", self.mortality, "Allow accepted lethal evidence to make this persona deceased."),
            ("Share learned insights with other personas", self.share, "Allow eligible learned insights to be shared."),
            ("Blind to other personas' shared insights", self.blind, "Do not receive shared insights from other personas."),
            ("Lock OCEAN controls", self.ocean_locked, "Prevent accidental manual OCEAN edits; daily mood still works."),
        ]
        self._option_checks = []
        for text, var, tip in option_defs:
            cb = tk.Checkbutton(
                right, text=text, variable=var,
                command=(self._apply_ocean_lock_state if var is self.ocean_locked else (self._refresh_relationship_button if var is self.blind else None)),
                bg=p["bg"], fg=p["text"], selectcolor=p["panel2"],
                activebackground=p["bg"], activeforeground=p["text"],
                font=("Segoe UI", 8), cursor="hand2",
            )
            cb.pack(anchor="w", pady=1)
            self._option_checks.append(cb)
            self._tip(cb, tip)

        self.lock_state_label = tk.Label(right, text="", bg=p["bg"], fg=p["muted"], font=("Segoe UI", 8))
        self.lock_state_label.pack(anchor="w", padx=(20, 0), pady=(1, 5))

        head = tk.Frame(right, bg=p["bg"])
        head.pack(fill="x", pady=(10, 0))
        ocean_head = self._label(head, "OCEAN base profile", accent=True)
        ocean_head.pack(side="left")
        self.randomise_button = tk.Button(head, text="Randomise", command=self._randomise_ocean, bg=p["button"], fg=p["button_fg"], relief="flat", bd=0, font=("Segoe UI Semibold", 8), padx=9, pady=5)
        self.randomise_button.pack(side="right")
        self._ocean_controls.append(self.randomise_button)
        self._tip(ocean_head, "Stable Big Five baseline.")
        self._tip(self.randomise_button, "Generate a fresh OCEAN baseline.")

        ocean_note = tk.Label(right, text="Manual scores reset today's temporary mood delta.", wraplength=385, justify="left", bg=p["bg"], fg=p["muted"], font=("Segoe UI", 8))
        ocean_note.pack(anchor="w", pady=(3, 8))

        self.trait_vars = {}
        self.trait_value_labels = {}
        self._trait_scales = []
        profile = getattr(self.session, "ocean_profile", {}) or {}
        traits = profile.get("traits", {}) if isinstance(profile, dict) else {}
        for trait in TRAITS:
            data = traits.get(trait, {}) if isinstance(traits, dict) else {}
            val = int(round(float(data.get("base_score", data.get("score", 50))))) if isinstance(data, dict) else 50
            card = tk.Frame(right, bg=p["panel"], highlightbackground=p["border"], highlightthickness=1)
            card.pack(fill="x", pady=4)
            top = tk.Frame(card, bg=p["panel"])
            top.pack(fill="x", padx=10, pady=(8, 0))
            trait_label = tk.Label(top, text=trait, bg=p["panel"], fg=p["text"], font=("Segoe UI Semibold", 9))
            trait_label.pack(side="left")
            lab = tk.Label(top, text=str(val), bg=p["panel"], fg=p["accent"], font=("Segoe UI Semibold", 9))
            lab.pack(side="right")
            var = tk.DoubleVar(value=val)
            self.trait_vars[trait] = var
            self.trait_value_labels[trait] = lab
            scale = tk.Scale(card, from_=0, to=100, orient="horizontal", variable=var, showvalue=False, resolution=1, bg=p["panel"], fg=p["text"], highlightthickness=0, troughcolor=p["panel2"], activebackground=p["accent"], command=lambda value, t=trait: self.trait_value_labels[t].configure(text=str(int(float(value)))))
            scale.pack(fill="x", padx=8, pady=(0, 6))
            self._ocean_controls.append(scale)
            self._trait_scales.append(scale)
            pool = TRAIT_DICTIONARY[trait]
            descriptor = tk.Label(card, text=f"{pool[0]}  ←                         →  {pool[-1]}", bg=p["panel"], fg=p["muted"], font=("Segoe UI", 9))
            descriptor.pack(fill="x", padx=9, pady=(0, 7))
            self._tip(scale, f"Adjust the stable {trait.lower()} baseline.")

        self._apply_ocean_lock_state()
        self._refresh_import_status()

        foot = tk.Frame(self, bg=p["bg"])
        foot.pack(fill="x", padx=20, pady=(10, 14))
        cancel = tk.Button(foot, text="Cancel", command=self.destroy, bg=p["button"], fg=p["button_fg"], relief="flat", bd=0, font=("Segoe UI Semibold", 9), padx=12, pady=7)
        cancel.pack(side="right")
        self._tip(cancel, "Close without saving persona changes.")
        self.save_button = tk.Button(foot, text="Save persona", command=self._save, bg=p["accent"], fg=p["bg"], relief="flat", bd=0, font=("Segoe UI Semibold", 9), padx=14, pady=7)
        self.save_button.pack(side="right", padx=(0, 8))
        self._tip(self.save_button, "Save this persona.")
        self.purge_button = tk.Button(foot, text="Purge memory…", command=self._purge_memory, bg=p["button"], fg=p["button_fg"], relief="flat", bd=0, font=("Segoe UI Semibold", 9), padx=12, pady=7)
        self.purge_button.pack(side="left")
        self._tip(self.purge_button, "Clear learned memory for this persona only.")
        self.undo_button = tk.Button(foot, text="Undo", command=self._undo, state="disabled", bg=p["button"], fg=p["button_fg"], relief="flat", bd=0, font=("Segoe UI Semibold", 9), padx=12, pady=7)
        self.undo_button.pack(side="left", padx=(8, 0))
        self._tip(self.undo_button, "Undo the most recent editor change.")
        self.relationship_button = tk.Button(foot, text="Relationships…", command=self._show_relationships, bg=p["button"], fg=p["button_fg"], relief="flat", bd=0, font=("Segoe UI Semibold", 9), padx=12, pady=7)
        self.relationship_button.pack(side="left", padx=(8, 0))
        self._tip(self.relationship_button, "Summarise this persona's current feelings toward other personas from available shared experience.")
        self.export_button = tk.Button(foot, text="Export…", command=self._export_persona_package, bg=p["button"], fg=p["button_fg"], relief="flat", bd=0, font=("Segoe UI Semibold", 9), padx=10, pady=7)
        self.export_button.pack(side="left", padx=(8,0))
        self._tip(self.export_button, "Export this persona as a portable Dunoon Daemon persona package.")
        self.import_pkg_button = tk.Button(foot, text="Import package…", command=self._import_persona_package, bg=p["button"], fg=p["button_fg"], relief="flat", bd=0, font=("Segoe UI Semibold", 9), padx=10, pady=7)
        self.import_pkg_button.pack(side="left", padx=(8,0))
        self._tip(self.import_pkg_button, "Import settings from a Dunoon Daemon persona package.")
        self._refresh_relationship_button()

    def _refresh_relationship_button(self):
        try:
            if bool(self.blind.get()): self.relationship_button.pack_forget()
            elif not self.relationship_button.winfo_manager(): self.relationship_button.pack(side="left", padx=(8,0))
        except Exception: pass

    def _show_relationships(self):
        if bool(self.blind.get()): return
        sm=getattr(self.session,'session_manager',None) or self.session_manager
        others=[x for x in sm.list_sessions() if getattr(x,'id',None)!=getattr(self.session,'id',None)] if sm else []
        if not others:
            messagebox.showinfo('Relationships','No other personas are available yet.',parent=self); return
        lines=[]
        try:
            from memory_transfer import retrieve_cross_persona_insights
            for other in others:
                evidence=retrieve_cross_persona_insights(str(getattr(other,'agent_name','Persona')),self.session,sm,top_k=3)
                lines.append(f"{getattr(other,'agent_name','Persona')}: " + ('; '.join(evidence) if evidence else 'No shared evidence yet.'))
            if self.brain:
                prompt=("Without changing memory, summarise in first person how I currently feel about each named persona. "
                        "Use only the supplied shared evidence and established persona character. If evidence is absent, say the relationship is not yet established. Be concise.\n\n"+'\n'.join(lines))
                text=self.brain.ask(prompt,self.session,source='relationship_summary',commit_lifecycle=False)
                if not str(text or '').strip():
                    # Never leave the Relationship viewer blank if a model exhausts its visible budget.
                    # Evidence is already filtered by cross-persona privacy/provenance rules.
                    text='Relationship summary unavailable; shared evidence follows:\n\n'+'\n'.join(lines)
            else: text='\n\n'.join(lines)
        except Exception as exc: text=f'Relationship summary unavailable: {exc}'
        top=tk.Toplevel(self); apply_window_icon(top); top.title('Relationships'); top.geometry('620x430'); top.configure(bg=self.p['bg']); top.transient(self)
        box=tk.Text(top,wrap='word',bg=self.p['panel'],fg=self.p['text'],insertbackground=self.p['accent'],relief='flat'); box.pack(fill='both',expand=True,padx=14,pady=14); box.insert('1.0',text); box.configure(state='disabled')
        center_after_idle(top, self)

    def _export_persona_package(self):
        from tkinter import filedialog
        from persona_package import export_persona
        name=(self.name.get().strip() or 'persona').replace('/','_').replace('\\','_')
        path=filedialog.asksaveasfilename(parent=self,defaultextension='.dunoonpersona',initialfile=name+'.dunoonpersona',filetypes=[('Dunoon Daemon persona','*.dunoonpersona')])
        if path:
            export_persona(self.session,path,include_memories=False); messagebox.showinfo('Persona exported',f'Saved {path}',parent=self)

    def _import_persona_package(self):
        from tkinter import filedialog
        from persona_package import import_persona_package
        path=filedialog.askopenfilename(parent=self,filetypes=[('Dunoon Daemon persona','*.dunoonpersona'),('All files','*.*')])
        if not path:return
        import_persona_package(self.session,path); self.session_manager._save(); messagebox.showinfo('Persona imported','Package applied. Reopen the Persona editor to review all fields.',parent=self)

    def _apply_ocean_lock_state(self):
        locked = bool(self.ocean_locked.get())
        state = "disabled" if locked else "normal"
        for widget in self._ocean_controls:
            try:
                widget.configure(state=state)
            except Exception:
                pass
        self.lock_state_label.configure(text="OCEAN edits locked · mood still active" if locked else "OCEAN edits enabled")

    def _refresh_import_status(self):
        bits = []
        if self._pending_import_source_name:
            bits.append(f"Imported from {self._pending_import_source_name}.")
        if self._pending_avatar_source_path:
            bits.append(f"Avatar queued: {os.path.basename(self._pending_avatar_source_path)}")
        if self._pending_import_notes:
            bits.append(self._pending_import_notes)
        self.import_status.configure(text=" ".join(bits))

    def _snapshot_form(self):
        if not hasattr(self, "trait_vars"):
            return None
        return {
            "name": self.name.get(),
            "prompt": self.prompt.get("1.0", "end-1c"),
            "seed": self.seed.get(),
            "backstory": self.backstory.get("1.0", "end-1c"),
            "phys": self.phys.get("1.0", "end-1c"),
            "powers": self.powers.get("1.0", "end-1c"),
            "guidance": self.guidance.get(),
            "eto": self.eto.get(),
            "nf": self.nf.get(),
            "mortality": self.mortality.get(),
            "share": self.share.get(),
            "blind": self.blind.get(),
            "ocean_locked": self.ocean_locked.get(),
            "pending_avatar_source": self._pending_avatar_source_path,
            "pending_avatar_temp": self._pending_avatar_temp_path,
            "pending_import_notes": self._pending_import_notes,
            "pending_import_source_name": self._pending_import_source_name,
            "traits": {t: float(self.trait_vars[t].get()) for t in TRAITS},
        }

    def _remember_undo(self, _event=None):
        if self._restoring:
            return
        snap = self._snapshot_form()
        if snap is None:
            return
        if not self._undo_stack or self._undo_stack[-1] != snap:
            self._undo_stack.append(snap)
            self._undo_stack = self._undo_stack[-60:]
        try:
            self.undo_button.configure(state="normal")
        except Exception:
            pass

    def _arm_undo_tracking(self):
        # Capture state immediately before edits. Roll/randomise also checkpoint explicitly.
        for widget in (self.name, self.seed, self.guidance):
            widget.bind("<KeyPress>", self._remember_undo, add="+")
            widget.bind("<<Paste>>", self._remember_undo, add="+")
            widget.bind("<<Cut>>", self._remember_undo, add="+")
        for widget in (self.prompt, self.backstory, self.phys, self.powers):
            widget.bind("<KeyPress>", self._remember_undo, add="+")
            widget.bind("<<Paste>>", self._remember_undo, add="+")
            widget.bind("<<Cut>>", self._remember_undo, add="+")
        for widget in self._option_checks + self._trait_scales:
            widget.bind("<ButtonPress-1>", self._remember_undo, add="+")

    @staticmethod
    def _set_entry(widget, value):
        widget.delete(0, "end")
        widget.insert(0, value)

    @staticmethod
    def _set_text(widget, value):
        widget.delete("1.0", "end")
        widget.insert("1.0", value)

    def _undo(self):
        if not self._undo_stack:
            return
        snap = self._undo_stack.pop()
        current_temp = self._pending_avatar_temp_path
        restoring_temp = snap.get("pending_avatar_temp", "")
        if current_temp and current_temp != restoring_temp:
            self._cleanup_temp_import_image(current_temp)
        self._restoring = True
        try:
            self._set_entry(self.name, snap["name"])
            self._set_text(self.prompt, snap["prompt"])
            self._set_entry(self.seed, snap["seed"])
            self._set_text(self.backstory, snap["backstory"])
            self._set_text(self.phys, snap["phys"])
            self._set_text(self.powers, snap["powers"])
            self._set_entry(self.guidance, snap["guidance"])
            self.eto.set(snap["eto"])
            self.nf.set(snap["nf"])
            self.mortality.set(snap["mortality"])
            self.share.set(snap["share"])
            self.blind.set(snap["blind"])
            self.ocean_locked.set(snap["ocean_locked"])
            self._pending_avatar_source_path = snap.get("pending_avatar_source", "")
            self._pending_avatar_temp_path = snap.get("pending_avatar_temp", "")
            self._pending_import_notes = snap.get("pending_import_notes", "")
            self._pending_import_source_name = snap.get("pending_import_source_name", "")
            for trait, value in snap["traits"].items():
                self.trait_vars[trait].set(value)
                self.trait_value_labels[trait].configure(text=str(int(round(value))))
            self._random_profile = None
            self._apply_ocean_lock_state()
            self._refresh_import_status()
        finally:
            self._restoring = False
        self.undo_button.configure(state="normal" if self._undo_stack else "disabled")

    def _roll(self):
        self._remember_undo()
        name, directive = roll_persona(self.seed.get().strip())
        self._set_entry(self.name, name)
        self._set_text(self.prompt, directive)

    def _choose_import_options(self):
        result = {"ok": False, "mode": "Character", "enrich": False, "auto_image": True}
        win = tk.Toplevel(self)
        apply_window_icon(win)
        win.title("Import persona")
        win.configure(bg=self.p["bg"])
        win.transient(self)
        win.resizable(False, False)
        win.grab_set()

        tk.Label(win, text="IMPORT PERSONA", bg=self.p["bg"], fg=self.p["text"], font=("Segoe UI Semibold", 13)).pack(anchor="w", padx=18, pady=(16, 3))
        tk.Label(win, text="Choose how the app should interpret the source.", bg=self.p["bg"], fg=self.p["muted"], font=("Segoe UI", 9)).pack(anchor="w", padx=18, pady=(0, 10))

        mode_var = tk.StringVar(value="Character")
        for mode in IMPORT_MODES:
            tip = {
                "Character": "Full individual: biography, voice, motives and relationships.",
                "NPC": "Compact interactable role: motives, loyalties, knowledge and voice.",
                "Monster / creature": "Bestiary / stat-block mode: instincts, physiology, powers and limitations.",
            }[mode]
            row = tk.Frame(win, bg=self.p["bg"])
            row.pack(fill="x", padx=18, pady=2)
            tk.Radiobutton(row, text=mode, variable=mode_var, value=mode, bg=self.p["bg"], fg=self.p["text"], selectcolor=self.p["panel2"], activebackground=self.p["bg"], activeforeground=self.p["text"], font=("Segoe UI Semibold", 9)).pack(anchor="w")
            tk.Label(row, text=tip, bg=self.p["bg"], fg=self.p["muted"], font=("Segoe UI", 8), wraplength=430, justify="left").pack(anchor="w", padx=(22, 0))

        enrich_var = tk.BooleanVar(value=False)
        auto_image_var = tk.BooleanVar(value=True)
        tk.Checkbutton(win, text="Enrich a known character using model knowledge", variable=enrich_var, bg=self.p["bg"], fg=self.p["text"], selectcolor=self.p["panel2"], activebackground=self.p["bg"], activeforeground=self.p["text"], font=("Segoe UI", 9)).pack(anchor="w", padx=18, pady=(10, 2))
        tk.Label(win, text="Leave off for homebrew characters, private lore and most stat blocks.", bg=self.p["bg"], fg=self.p["muted"], font=("Segoe UI", 8)).pack(anchor="w", padx=40)
        tk.Checkbutton(win, text="Auto-detect an embedded portrait in PDF / DOCX", variable=auto_image_var, bg=self.p["bg"], fg=self.p["text"], selectcolor=self.p["panel2"], activebackground=self.p["bg"], activeforeground=self.p["text"], font=("Segoe UI", 9)).pack(anchor="w", padx=18, pady=(8, 10))

        buttons = tk.Frame(win, bg=self.p["bg"])
        buttons.pack(fill="x", padx=18, pady=(4, 16))
        def accept():
            result.update(ok=True, mode=mode_var.get(), enrich=bool(enrich_var.get()), auto_image=bool(auto_image_var.get()))
            win.destroy()
        tk.Button(buttons, text="Cancel", command=win.destroy, bg=self.p["button"], fg=self.p["button_fg"], relief="flat", bd=0, padx=12, pady=6).pack(side="right")
        tk.Button(buttons, text="Continue", command=accept, bg=self.p["accent"], fg=self.p["bg"], relief="flat", bd=0, padx=14, pady=6).pack(side="right", padx=(0, 8))
        ensure_button_tooltips(win, self._tooltips)
        center_after_idle(win, self)
        self.wait_window(win)
        return result if result["ok"] else None

    @staticmethod
    def _confidence_label(value):
        try:
            n = int(value)
        except Exception:
            return "not scored"
        if n >= 80:
            band = "high"
        elif n >= 55:
            band = "medium"
        else:
            band = "low"
        return f"{n}% · {band}"

    def _show_import_preview(self, result):
        accepted = {"value": False}
        win = tk.Toplevel(self)
        apply_window_icon(win)
        win.title(f"Import preview · {result.import_mode}")
        win.geometry("760x720")
        win.minsize(650, 560)
        win.configure(bg=self.p["bg"])
        win.transient(self)
        win.grab_set()

        head = tk.Frame(win, bg=self.p["bg"])
        head.pack(fill="x", padx=18, pady=(16, 8))
        tk.Label(head, text="IMPORT PREVIEW", bg=self.p["bg"], fg=self.p["text"], font=("Segoe UI Semibold", 14)).pack(anchor="w")
        subtitle = f"{result.import_mode} · {result.source_name}"
        if result.used_image_path:
            subtitle += f" · avatar: {os.path.basename(result.used_image_path)}"
            if result.image_origin == "embedded-document":
                subtitle += " (auto-detected)"
        tk.Label(head, text=subtitle, bg=self.p["bg"], fg=self.p["muted"], font=("Segoe UI", 8), wraplength=720, justify="left").pack(anchor="w", pady=(2, 0))

        canvas_wrap = tk.Frame(win, bg=self.p["bg"])
        canvas_wrap.pack(fill="both", expand=True, padx=(18, 8))
        canvas = tk.Canvas(canvas_wrap, bg=self.p["bg"], highlightthickness=0)
        sb = tk.Scrollbar(canvas_wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        body = tk.Frame(canvas, bg=self.p["bg"])
        wid = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(wid, width=e.width))

        fields = [
            ("Display name", "display_name", result.display_name),
            ("Core persona directives", "core_persona_directives", result.core_persona_directives),
            ("Backstory / history", "backstory", result.backstory),
            ("Physiology", "physiology", result.physiology),
            ("Powers / skills", "powers_skills", result.powers_skills),
            ("Dream preservation guidance", "dream_guidance", result.dream_guidance),
        ]
        for title, key, value in fields:
            card = tk.Frame(body, bg=self.p["panel"], highlightbackground=self.p["border"], highlightthickness=1)
            card.pack(fill="x", pady=4)
            top = tk.Frame(card, bg=self.p["panel"])
            top.pack(fill="x", padx=10, pady=(8, 2))
            tk.Label(top, text=title, bg=self.p["panel"], fg=self.p["text"], font=("Segoe UI Semibold", 9)).pack(side="left")
            tk.Label(top, text=self._confidence_label(result.confidence.get(key)), bg=self.p["panel"], fg=self.p["accent"], font=("Segoe UI", 8)).pack(side="right")
            preview = value.strip() if str(value or "").strip() else "[left blank]"
            tk.Label(card, text=preview, bg=self.p["panel"], fg=self.p["muted"] if preview == "[left blank]" else self.p["text"], font=("Segoe UI", 8), wraplength=680, justify="left", anchor="w").pack(fill="x", padx=10, pady=(0, 8))

        ocean_card = tk.Frame(body, bg=self.p["panel"], highlightbackground=self.p["border"], highlightthickness=1)
        ocean_card.pack(fill="x", pady=4)
        tk.Label(ocean_card, text=f"Suggested OCEAN · {self._confidence_label(result.confidence.get('ocean'))}", bg=self.p["panel"], fg=self.p["text"], font=("Segoe UI Semibold", 9)).pack(anchor="w", padx=10, pady=(8, 2))
        ocean_text = " · ".join(f"{k.title()} {v}" for k, v in (result.ocean or {}).items()) or "[not scored]"
        tk.Label(ocean_card, text=ocean_text, bg=self.p["panel"], fg=self.p["text"], font=("Segoe UI", 8), wraplength=680, justify="left").pack(anchor="w", padx=10, pady=(0, 8))

        if result.import_notes:
            tk.Label(body, text=f"Importer notes: {result.import_notes}", bg=self.p["bg"], fg=self.p["muted"], font=("Segoe UI", 8), wraplength=690, justify="left").pack(anchor="w", pady=(8, 4))

        foot = tk.Frame(win, bg=self.p["bg"])
        foot.pack(fill="x", padx=18, pady=(10, 16))
        def accept():
            accepted["value"] = True
            win.destroy()
        tk.Button(foot, text="Cancel", command=win.destroy, bg=self.p["button"], fg=self.p["button_fg"], relief="flat", bd=0, padx=12, pady=7).pack(side="right")
        tk.Button(foot, text="Apply import", command=accept, bg=self.p["accent"], fg=self.p["bg"], relief="flat", bd=0, padx=14, pady=7).pack(side="right", padx=(0, 8))
        ensure_button_tooltips(win, self._tooltips)
        center_after_idle(win, self)
        self.wait_window(win)
        return bool(accepted["value"])

    def _cleanup_temp_import_image(self, path=None):
        target = str(path or self._pending_avatar_temp_path or "").strip()
        if target and os.path.basename(target).startswith("dunoon_persona_import_"):
            try:
                os.remove(target)
            except Exception:
                pass
        if target == self._pending_avatar_temp_path:
            self._pending_avatar_temp_path = ""

    def _import_from_file(self):
        handler = getattr(getattr(self, "brain", None), "model_handler", None)
        if not (handler and getattr(handler, "is_active", lambda: False)()):
            messagebox.showwarning("Model required", "Load a local GGUF model before importing a persona from source material.", parent=self)
            return

        options = self._choose_import_options()
        if not options:
            return

        source_path = filedialog.askopenfilename(
            parent=self,
            initialdir=get_last_dir('persona_import_source'),
            title='Import persona from file',
            filetypes=[
                ('Supported', '*.txt *.md *.markdown *.pdf *.docx *.json *.csv *.log *.py *.js *.cpp *.png *.jpg *.jpeg *.webp *.bmp'),
                ('Documents', '*.txt *.md *.markdown *.pdf *.docx *.json *.csv *.log *.py *.js *.cpp'),
                ('Images', '*.png *.jpg *.jpeg *.webp *.bmp'),
                ('All Files', '*.*'),
            ],
        )
        if not source_path:
            return
        remember_path('persona_import_source', source_path)

        chosen_avatar = source_path if is_image_file(source_path) else ""
        if not chosen_avatar:
            attach_avatar = messagebox.askyesno(
                'Add a separate avatar?',
                "Would you like to choose a separate avatar image?\n\nChoose No to let the app try the PDF / DOCX embedded portrait automatically if that option is enabled.",
                parent=self,
            )
            if attach_avatar:
                avatar_path = filedialog.askopenfilename(
                    parent=self,
                    initialdir=get_last_dir('persona_import_avatar'),
                    title='Choose avatar image',
                    filetypes=[('Images', '*.png *.jpg *.jpeg *.webp *.bmp'), ('All Files', '*.*')],
                )
                if avatar_path:
                    remember_path('persona_import_avatar', avatar_path)
                    chosen_avatar = avatar_path

        progress = tk.Toplevel(self)
        apply_window_icon(progress)
        progress.title('Importing persona…')
        progress.configure(bg=self.p['bg'])
        progress.transient(self)
        progress.resizable(False, False)
        tk.Label(progress, text='Reading source material and drafting persona fields…', bg=self.p['bg'], fg=self.p['text'], font=('Segoe UI Semibold', 10), padx=18, pady=16).pack()
        progress.update_idletasks()
        center_after_idle(progress, self)
        try:
            result = import_persona_from_source(
                handler, source_path,
                allow_known_character_enrichment=options['enrich'],
                image_path=chosen_avatar,
                import_mode=options['mode'],
                auto_extract_embedded_image=options['auto_image'],
            )
        except PersonaImportError as exc:
            progress.destroy()
            messagebox.showerror('Import failed', str(exc), parent=self)
            return
        except Exception as exc:
            progress.destroy()
            messagebox.showerror('Import failed', f'Unexpected error while importing persona:\n\n{exc}', parent=self)
            return
        progress.destroy()

        if not self._show_import_preview(result):
            if result.image_origin == 'embedded-document':
                self._cleanup_temp_import_image(result.used_image_path)
            return

        self._remember_undo()
        # If a previous accepted preview had a temporary embedded image queued, discard it.
        if self._pending_avatar_temp_path and self._pending_avatar_temp_path != result.used_image_path:
            self._cleanup_temp_import_image(self._pending_avatar_temp_path)

        if result.display_name:
            self._set_entry(self.name, result.display_name)
        if result.core_persona_directives:
            self._set_text(self.prompt, result.core_persona_directives)
        if result.backstory:
            self._set_text(self.backstory, result.backstory)
        if result.physiology:
            self._set_text(self.phys, result.physiology)
        if result.powers_skills:
            self._set_text(self.powers, result.powers_skills)
        if result.dream_guidance:
            self._set_entry(self.guidance, result.dream_guidance)

        if result.ocean and not self.ocean_locked.get():
            keymap = {'Openness':'openness', 'Conscientiousness':'conscientiousness', 'Extraversion':'extraversion', 'Agreeableness':'agreeableness', 'Neuroticism':'neuroticism'}
            for trait in TRAITS:
                key = keymap[trait]
                if key in result.ocean:
                    value = int(result.ocean[key])
                    self.trait_vars[trait].set(value)
                    self.trait_value_labels[trait].configure(text=str(value))
            self._random_profile = None

        self._pending_avatar_source_path = result.used_image_path if result.used_image_path and os.path.exists(result.used_image_path) else ''
        self._pending_avatar_temp_path = result.used_image_path if result.image_origin == 'embedded-document' else ''
        self._pending_import_notes = str(result.import_notes or '').strip()
        self._pending_import_source_name = str(result.source_name or os.path.basename(source_path))
        self._refresh_import_status()
        messagebox.showinfo('Persona imported', 'Import applied to the editor. Review anything you like, then save the persona when ready.', parent=self)

    def _randomise_ocean(self):
        if self.ocean_locked.get():
            return
        self._remember_undo()
        self._random_profile = randomise_ocean_profile(getattr(self.session, "ocean_profile", {}))
        for trait in TRAITS:
            value = int(self._random_profile["traits"][trait]["base_score"])
            self.trait_vars[trait].set(value)
            self.trait_value_labels[trait].configure(text=str(value))

    def _purge_memory(self):
        agent = self.name.get().strip() or str(getattr(self.session, "agent_name", "") or "this persona")
        ok = messagebox.askyesno(
            "Purge learned memory?",
            f"Clear all learned memory for {agent}?\n\nPersona settings, OCEAN, backstory and conversation history will remain unchanged.",
            parent=self,
            icon="warning",
        )
        if not ok:
            return
        sid = str(getattr(self.session, "id", None) or getattr(self.session, "session_id", ""))
        before = purge_persona_memories(sid)
        total = sum(int(v or 0) for v in before.values())
        messagebox.showinfo("Memory purged", f"Cleared {total} stored memory / index entries for {agent}.", parent=self)

    def destroy(self):
        self._cleanup_temp_import_image()
        super().destroy()

    def _save(self):
        s = self.session
        # Blank is a valid unconfigured state. The editor no longer invents defaults.
        s.agent_name = self.name.get().strip()
        s.system_prompt = self.prompt.get("1.0", "end").strip()
        s.backstory = self.backstory.get("1.0", "end").strip()
        s.physiology = self.phys.get("1.0", "end").strip()
        s.powers = self.powers.get("1.0", "end").strip()
        s.dream_guidance = self.guidance.get().strip()
        s.share_insights = self.share.get()
        s.blind_to_others = self.blind.get()
        s.eto_enabled = self.eto.get()
        s.narrative_freedom = self.nf.get()
        s.mortality_enabled = self.mortality.get()
        s.ocean_controls_locked = bool(self.ocean_locked.get())
        s.psychology_mode = "ocean_sensitive"

        if not s.ocean_controls_locked:
            base = self._random_profile if self._random_profile is not None else getattr(s, "ocean_profile", {})
            s.ocean_profile = apply_ocean_base_scores(base, {t: self.trait_vars[t].get() for t in TRAITS})
            s.last_mood_update = None
        if self._pending_avatar_source_path:
            try:
                set_persona_avatar(s, self._pending_avatar_source_path)
            except Exception as exc:
                messagebox.showerror('Avatar import failed', str(exc), parent=self)
                return
        if self.sm.save() is False:
            messagebox.showerror(
                'Persona save failed',
                'The persona could not be saved durably. Your editor remains open so you can retry.',
                parent=self,
            )
            return
        if self.on_saved:
            self.on_saved(s)
        self.destroy()
