from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, filedialog

from chat_modes import CHAT_MODES
from memory_lifecycle import persona_memory_counts, purge_persona_memories
from modern_theme import palette
from ui_preferences import load_ui_preferences, save_ui_preferences
from ui_windowing import center_after_idle, apply_window_icon
from modern_tooltips import register_tooltip, register_region_tooltip, ensure_button_tooltips


class ChatModeDialog(tk.Toplevel):
    def __init__(self, parent, skin_name: str, persona_name: str):
        super().__init__(parent)
        apply_window_icon(self)
        self.result = None
        self.p = palette(skin_name)
        self._tooltips = []
        self.title(f"Open {persona_name}")
        self.configure(bg=self.p['bg'])
        self.resizable(False, False)
        self.transient(parent)
        self.protocol('WM_DELETE_WINDOW', self._cancel)
        self._build(persona_name)
        ensure_button_tooltips(self, self._tooltips)
        center_after_idle(self, parent)
        self.grab_set()
        self.focus_force()

    def _build(self, persona_name: str):
        p = self.p
        header = tk.Frame(self, bg=p['bg'])
        header.pack(fill='x', padx=22, pady=(20, 12))
        tk.Label(header, text=f'OPEN {persona_name.upper()}', bg=p['bg'], fg=p['text'],
                 font=('Segoe UI Semibold', 15)).pack(anchor='w')
        tk.Label(header, text='Choose what this chat is allowed to remember and bring with it.',
                 bg=p['bg'], fg=p['muted'], font=('Segoe UI', 9)).pack(anchor='w', pady=(3,0))

        grid = tk.Frame(self, bg=p['bg'])
        grid.pack(fill='both', padx=18, pady=(0, 16))
        for col in range(2): grid.columnconfigure(col, weight=1, uniform='mode')
        for row in range(2): grid.rowconfigure(row, weight=1, uniform='mode')

        use_case_help = {
            'continuation': 'Use this for your real ongoing relationship with this character. Previous conversation and learned memories are available, and new memories can be kept.',
            'sandbox': "Use this to test the version of the character you've built over time without changing them. Learned memories are available, but this chat cannot write new long-term memories.",
            'canvas': 'Use this to continue the current conversation while temporarily withholding learned long-term memories. New memories from this session can still be kept.',
            'bubble': 'Use this for a clean-room encounter with the base persona. No prior conversation or learned memory comes in, and nothing from this chat is kept.',
        }
        order = ['continuation', 'sandbox', 'canvas', 'bubble']
        for index, key in enumerate(order):
            spec = CHAT_MODES[key]
            row, col = divmod(index, 2)
            card = tk.Frame(grid, bg=p['panel'], highlightbackground=p['border'], highlightthickness=1,
                            cursor='hand2', width=315, height=150)
            card.grid(row=row, column=col, sticky='nsew', padx=6, pady=6)
            card.grid_propagate(False)
            title = tk.Label(card, text=spec.label.upper(), bg=p['panel'], fg=p['accent'],
                             font=('Segoe UI Semibold', 11), cursor='hand2')
            title.pack(anchor='w', padx=14, pady=(13,2))
            tag = tk.Label(card, text=spec.tagline, bg=p['panel'], fg=p['text'],
                           font=('Segoe UI Semibold', 8), cursor='hand2')
            tag.pack(anchor='w', padx=14)
            desc = tk.Label(card, text=spec.description, wraplength=280, justify='left',
                            bg=p['panel'], fg=p['muted'], font=('Segoe UI', 8), cursor='hand2')
            desc.pack(anchor='w', fill='x', padx=14, pady=(7,10))
            hover_widgets = (card, title, tag, desc)
            for widget in hover_widgets:
                widget.bind('<Button-1>', lambda _e, k=key: self._choose(k))
            # One logical hover region per card. This survives the pointer moving
            # between the Frame and its child Labels, which previously cancelled
            # the timer before the conversation-mode tooltip could appear.
            register_region_tooltip(self._tooltips, card, hover_widgets, use_case_help[key], delay=350)

        footer = tk.Frame(self, bg=p['bg'])
        footer.pack(fill='x', padx=24, pady=(0,18))
        tk.Label(footer, text='Persona + OCEAN always persist in every mode.', bg=p['bg'], fg=p['muted'],
                 font=('Segoe UI', 8, 'italic')).pack(side='left')
        tk.Button(footer, text='Cancel', command=self._cancel, relief='flat', bd=0,
                  bg=p['button'], fg=p['button_fg'], activebackground=p['accent'], activeforeground=p['bg'],
                  font=('Segoe UI Semibold', 9), padx=12, pady=6).pack(side='right')

    def _choose(self, key: str):
        self.result = key
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


class PersonaMemoryDialog(tk.Toplevel):
    def __init__(self, parent, skin_name: str, session):
        super().__init__(parent)
        apply_window_icon(self)
        self.parent = parent
        self.session = session
        self.p = palette(skin_name)
        self.title(f"Memory · {getattr(session, 'agent_name', 'Persona')}")
        self.configure(bg=self.p['bg'])
        self.geometry('560x390')
        self.minsize(520, 360)
        self.transient(parent)
        self._status_var = tk.StringVar(value='')
        self._tooltips = []
        self._build()
        self._refresh_counts()
        ensure_button_tooltips(self, self._tooltips)
        center_after_idle(self, parent)

    @property
    def session_id(self):
        return str(getattr(self.session, 'id', None) or getattr(self.session, 'session_id', ''))

    def _build(self):
        p = self.p
        outer = tk.Frame(self, bg=p['bg'])
        outer.pack(fill='both', expand=True, padx=22, pady=20)
        tk.Label(outer, text='LEARNED MEMORY', bg=p['bg'], fg=p['text'],
                 font=('Segoe UI Semibold', 15)).pack(anchor='w')
        tk.Label(outer,
                 text='These vaults are what the persona has learned across interactions. Clearing them does not alter the persona, OCEAN profile, backstory, voice or saved conversation transcript.',
                 wraplength=505, justify='left', bg=p['bg'], fg=p['muted'], font=('Segoe UI', 9)).pack(anchor='w', pady=(5,14))

        self.count_panel = tk.Frame(outer, bg=p['panel'], highlightbackground=p['border'], highlightthickness=1)
        self.count_panel.pack(fill='x', pady=(0,14))
        self.count_labels = {}
        labels = [('working_memory','Working'),('deep_memory','Deep'),('journal_memory','Journal'),
                  ('intent_memory','Intent'),('task_memory','Task'),('factual_memory','Factual'),('embeddings','Embeddings')]
        for i, (key, label) in enumerate(labels):
            row = tk.Frame(self.count_panel, bg=p['panel'])
            row.grid(row=i//2, column=i%2, sticky='ew', padx=14, pady=7)
            self.count_panel.columnconfigure(i%2, weight=1)
            tk.Label(row, text=label, bg=p['panel'], fg=p['muted'], font=('Segoe UI', 9)).pack(side='left')
            value = tk.Label(row, text='0', bg=p['panel'], fg=p['text'], font=('Segoe UI Semibold', 9))
            value.pack(side='right')
            self.count_labels[key] = value

        warning = tk.Frame(outer, bg=p['panel2'], highlightbackground=p['border'], highlightthickness=1)
        warning.pack(fill='x')
        tk.Label(warning, text='INDIVIDUAL PURGE', bg=p['panel2'], fg=p['accent'],
                 font=('Segoe UI Semibold', 9)).pack(anchor='w', padx=13, pady=(11,2))
        tk.Label(warning, text='Forget learned memories for this persona only. Conversation history is left intact.',
                 bg=p['panel2'], fg=p['text'], font=('Segoe UI', 9)).pack(anchor='w', padx=13, pady=(0,9))
        tk.Button(warning, text='Forget learned memories…', command=self._purge, relief='flat', bd=0,
                  bg='#6f3030', fg='#ffffff', activebackground='#963f3f', activeforeground='#ffffff',
                  font=('Segoe UI Semibold', 9), padx=12, pady=7).pack(anchor='w', padx=13, pady=(0,12))

        tk.Label(outer, textvariable=self._status_var, bg=p['bg'], fg=p['accent'],
                 font=('Segoe UI Semibold', 8)).pack(anchor='w', pady=(10,0))
        tk.Button(outer, text='Close', command=self.destroy, relief='flat', bd=0,
                  bg=p['button'], fg=p['button_fg'], activebackground=p['accent'], activeforeground=p['bg'],
                  font=('Segoe UI Semibold', 9), padx=14, pady=7).pack(anchor='e', pady=(8,0))

    def _refresh_counts(self):
        counts = persona_memory_counts(self.session_id)
        for key, label in self.count_labels.items():
            label.configure(text=str(counts.get(key, 0)))

    def _purge(self):
        agent = getattr(self.session, 'agent_name', 'this persona')
        ok = messagebox.askyesno(
            'Forget learned memories?',
            f'Clear all learned memory vaults for {agent}?\n\nPersona, OCEAN profile, backstory and saved conversation transcript will remain unchanged.',
            parent=self, icon='warning',
        )
        if not ok: return
        before = purge_persona_memories(self.session_id)
        self._refresh_counts()
        total = sum(before.values())
        self._status_var.set(f'Forgot {total} stored memory / index entries for {agent}.')


class DreamReportDialog(tk.Toplevel):
    def __init__(self, parent, skin_name: str, result: dict):
        super().__init__(parent)
        apply_window_icon(self)
        self.p = palette(skin_name)
        self.title(f"Dream · {result.get('persona', 'Persona')}")
        self.geometry('590x430')
        self.minsize(540, 390)
        self.configure(bg=self.p['bg'])
        self.transient(parent)
        self._tooltips = []
        self._build(result)
        ensure_button_tooltips(self, self._tooltips)
        center_after_idle(self, parent)

    def _build(self, result):
        p=self.p; outer=tk.Frame(self,bg=p['bg']); outer.pack(fill='both',expand=True,padx=22,pady=20)
        tk.Label(outer,text='DREAM COMPLETE',bg=p['bg'],fg=p['accent'],font=('Segoe UI Semibold',15)).pack(anchor='w')
        tk.Label(outer,text=result.get('story',''),wraplength=535,justify='left',bg=p['bg'],fg=p['text'],font=('Segoe UI',10,'italic')).pack(anchor='w',fill='x',pady=(10,16))
        c=result.get('changes',{}); before=result.get('before',{}); after=result.get('after',{})
        card=tk.Frame(outer,bg=p['panel'],highlightbackground=p['border'],highlightthickness=1); card.pack(fill='x')
        rows=[('Working memory',f"{before.get('working',0)}  →  {after.get('working',0)}"),('Repeated fragments removed',str(c.get('working_removed',0))),('Stale embedding traces removed',str(c.get('embeddings_removed',0))),('Guidance-protected memories',str(result.get('guidance_hits',0)))]
        for label,value in rows:
            row=tk.Frame(card,bg=p['panel']); row.pack(fill='x',padx=14,pady=7); tk.Label(row,text=label,bg=p['panel'],fg=p['muted'],font=('Segoe UI',9)).pack(side='left'); tk.Label(row,text=value,bg=p['panel'],fg=p['text'],font=('Segoe UI Semibold',9)).pack(side='right')
        tk.Label(outer,text='A snapshot was written before maintenance. Dream V1 does not semantically rewrite factual or deep memory.',wraplength=535,justify='left',bg=p['bg'],fg=p['muted'],font=('Segoe UI',8)).pack(anchor='w',pady=(14,0))
        tk.Button(outer,text='Close',command=self.destroy,relief='flat',bd=0,bg=p['button'],fg=p['button_fg'],activebackground=p['accent'],activeforeground=p['bg'],font=('Segoe UI Semibold',9),padx=14,pady=7).pack(anchor='e',pady=(14,0))


class InterfacePreferencesDialog(tk.Toplevel):
    """Global UI, recovery and support settings kept out of the main interaction surfaces."""
    def __init__(self, parent, skin_name: str, brain=None, session_manager=None, on_master_purge=None, on_restore=None):
        super().__init__(parent)
        apply_window_icon(self)
        self.p = palette(skin_name)
        self.brain = brain
        self.session_manager = session_manager
        self.on_master_purge = on_master_purge
        self.on_restore = on_restore
        prefs = load_ui_preferences()
        self.show_tooltips = tk.BooleanVar(value=bool(prefs.get('show_tooltips', False)))
        self.autosave_recovery = tk.BooleanVar(value=bool(prefs.get('autosave_recovery', True)))
        self._tooltips = []
        self.title('Settings')
        self.geometry('560x500'); self.resizable(False, False); self.configure(bg=self.p['bg']); self.transient(parent)
        self._build(); ensure_button_tooltips(self, self._tooltips); center_after_idle(self, parent)

    def _build(self):
        p=self.p; outer=tk.Frame(self,bg=p['bg']); outer.pack(fill='both',expand=True,padx=22,pady=18)
        tk.Label(outer,text='SETTINGS',bg=p['bg'],fg=p['text'],font=('Segoe UI Semibold',15)).pack(anchor='w')
        tk.Label(outer,text='Global appearance, recovery and support. Persona and Arena behaviour stays where it belongs.',bg=p['bg'],fg=p['muted'],font=('Segoe UI',8),wraplength=500,justify='left').pack(anchor='w',pady=(4,12))
        card=tk.Frame(outer,bg=p['panel'],highlightbackground=p['border'],highlightthickness=1); card.pack(fill='x')
        for label,var,desc in (
            ('Show tooltips',self.show_tooltips,'Hover help across Home, chat and Arena.'),
            ('Autosave crash recovery',self.autosave_recovery,'Keep a lightweight recoverable copy of current session state.'),
        ):
            cb=tk.Checkbutton(card,text=label,variable=var,command=self._apply,bg=p['panel'],fg=p['text'],activebackground=p['panel'],activeforeground=p['text'],selectcolor=p['panel2'],font=('Segoe UI Semibold',9),cursor='hand2'); cb.pack(anchor='w',padx=14,pady=(9,0))
            tk.Label(card,text=desc,bg=p['panel'],fg=p['muted'],font=('Segoe UI',8),wraplength=470,justify='left').pack(anchor='w',padx=35,pady=(0,6))

        support=tk.Frame(outer,bg=p['panel'],highlightbackground=p['border'],highlightthickness=1); support.pack(fill='x',pady=(12,0))
        tk.Label(support,text='Data & support',bg=p['panel'],fg=p['accent'],font=('Segoe UI Semibold',10)).pack(anchor='w',padx=14,pady=(10,6))
        buttons=tk.Frame(support,bg=p['panel']); buttons.pack(fill='x',padx=14,pady=(0,10))
        for text,cmd in [('Back up…',self._backup),('Restore…',self._restore),('Diagnostics…',self._diagnostics),('Model check',self._model_check)]:
            tk.Button(buttons,text=text,command=cmd,relief='flat',bd=0,bg=p['button'],fg=p['button_fg'],font=('Segoe UI Semibold',8),padx=10,pady=6).pack(side='left',padx=(0,6))
        danger=tk.Frame(support,bg=p['panel']); danger.pack(fill='x',padx=14,pady=(0,8))
        tk.Button(danger,text='MASTER PURGE…',command=self._master_purge,relief='flat',bd=0,bg='#5a1d1d',fg='#ffffff',activebackground='#7a2424',activeforeground='#ffffff',font=('Segoe UI Semibold',8),padx=10,pady=6).pack(side='left')
        tk.Label(danger,text='Deletes every live persona, transcript, memory vault, Arena scene and recovery checkpoint.',bg=p['panel'],fg=p['muted'],font=('Segoe UI',8),wraplength=360,justify='left').pack(side='left',padx=(10,0))
        tk.Label(support,text='Diagnostics excludes chats / persona contents unless you explicitly choose a private bundle later.',bg=p['panel'],fg=p['muted'],font=('Segoe UI',8),wraplength=480,justify='left').pack(anchor='w',padx=14,pady=(0,10))
        tk.Button(outer,text='Close',command=self.destroy,relief='flat',bd=0,bg=p['button'],fg=p['button_fg'],font=('Segoe UI Semibold',9),padx=14,pady=7).pack(anchor='e',pady=(14,0))

    def _apply(self):
        save_ui_preferences(show_tooltips=self.show_tooltips.get(), autosave_recovery=self.autosave_recovery.get(), autoskin_enabled=False)
    def _backup(self):
        from release_support import create_state_backup
        path=filedialog.asksaveasfilename(parent=self,defaultextension='.zip',filetypes=[('ZIP backup','*.zip')],initialfile='dunoon-backup.zip')
        if path:
            create_state_backup(path, session_manager=self.session_manager); messagebox.showinfo('Backup complete',f'Saved {path}',parent=self)
    def _restore(self):
        from release_support import restore_state_backup
        path=filedialog.askopenfilename(parent=self,filetypes=[('ZIP backup','*.zip')])
        if not path:return
        if messagebox.askyesno('Restore backup?','This will replace matching app data files. Continue?',parent=self):
            restore_state_backup(path)
            if self.session_manager is not None and hasattr(self.session_manager, 'reload_from_disk'):
                self.session_manager.reload_from_disk()
            if callable(self.on_restore):
                self.on_restore()
            messagebox.showinfo('Restore complete','Backup restored. Restart Dunoon Daemon to refresh every restored setting.',parent=self)
    def _diagnostics(self):
        from release_support import create_diagnostics_bundle
        path=filedialog.asksaveasfilename(parent=self,defaultextension='.zip',filetypes=[('ZIP bundle','*.zip')],initialfile='dunoon-diagnostics.zip')
        if path:
            create_diagnostics_bundle(path,include_private=False); messagebox.showinfo('Diagnostics ready',f'Saved {path}',parent=self)
    def _master_purge(self):
        if self.session_manager is None:
            messagebox.showerror('Master purge','Session manager is unavailable.',parent=self)
            return
        first = messagebox.askyesno(
            'MASTER PURGE?',
            'Delete ALL personas and live history on this Dunoon Daemon installation?\n\nThis includes chat transcripts, learned memories, Arena scenes and crash-recovery checkpoints.',
            parent=self, icon='warning'
        )
        if not first:
            return
        second = messagebox.askyesno(
            'FINAL CONFIRMATION',
            'This is the second and final confirmation.\n\nThere is no in-app undo. Continue with MASTER PURGE?',
            parent=self, icon='warning'
        )
        if not second:
            return
        try:
            self.session_manager.master_purge()
            if callable(self.on_master_purge):
                self.on_master_purge()
            messagebox.showinfo('Master purge complete','All live personas and history were removed. A blank persona has been created.',parent=self)
        except Exception as exc:
            messagebox.showerror('Master purge failed',str(exc),parent=self)

    def _model_check(self):
        handler=None
        try: handler=getattr(self.brain,'model_handler',None)
        except Exception: pass
        from release_support import model_capabilities
        caps=model_capabilities(handler)
        messagebox.showinfo('Model compatibility',f"Loaded: {caps['loaded']}\nVision: {caps['vision']}\nContext: {caps['context'] or 'unknown'}\nReasoning capability: {caps['reasoning']}",parent=self)


class TextPromptDialog(tk.Toplevel):
    def __init__(self, parent, skin_name: str, title: str, prompt: str):
        super().__init__(parent)
        apply_window_icon(self)
        self.result = None
        self.p = palette(skin_name)
        self.title(title)
        self.geometry('430x175')
        self.resizable(False, False)
        self.configure(bg=self.p['bg'])
        self.transient(parent)
        self._tooltips = []
        self._build(prompt)
        ensure_button_tooltips(self, self._tooltips)
        center_after_idle(self, parent)
        self.grab_set(); self.focus_force()

    def _build(self, prompt):
        p=self.p
        outer=tk.Frame(self,bg=p['bg']); outer.pack(fill='both',expand=True,padx=20,pady=18)
        tk.Label(outer,text=prompt,bg=p['bg'],fg=p['text'],font=('Segoe UI',10)).pack(anchor='w')
        self.entry=tk.Entry(outer,bg=p['panel2'],fg=p['text'],insertbackground=p['accent'],relief='flat',bd=0,font=('Segoe UI',10))
        self.entry.pack(fill='x',pady=(10,14),ipady=8); self.entry.bind('<Return>',lambda _e:self._ok())
        row=tk.Frame(outer,bg=p['bg']); row.pack(fill='x')
        tk.Button(row,text='Cancel',command=self.destroy,relief='flat',bd=0,bg=p['button'],fg=p['button_fg'],font=('Segoe UI Semibold',9),padx=12,pady=6).pack(side='right')
        tk.Button(row,text='Create',command=self._ok,relief='flat',bd=0,bg=p['accent'],fg=p['bg'],font=('Segoe UI Semibold',9),padx=12,pady=6).pack(side='right',padx=(0,8))
        self.entry.focus_set()
    def _ok(self):
        value=self.entry.get().strip()
        if value: self.result=value
        self.destroy()


def choose_chat_mode(parent, skin_name: str, persona_name: str):
    dlg = ChatModeDialog(parent, skin_name, persona_name)
    parent.wait_window(dlg)
    return dlg.result


def prompt_text(parent, skin_name: str, title: str, prompt: str):
    dlg = TextPromptDialog(parent, skin_name, title, prompt)
    parent.wait_window(dlg)
    return dlg.result
