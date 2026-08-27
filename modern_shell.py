# 🐉 Silver Wyrm: modern_shell.py — Dunoon Daemon modern home shell,
# Run with: python modern_shell.py

import math
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from brain import Brain
from config import DEFAULT_CONTEXT
from model_handler import create_model_handler
from modern_daemon import ModernDunoonDaemonApp
from chat_modes import ChatSessionView, get_chat_mode
from modern_dialogs import choose_chat_mode, PersonaMemoryDialog, InterfacePreferencesDialog, DreamReportDialog, prompt_text
from modern_arena import ModernArenaFrame
from modern_theme import palette, apply_combobox_theme, contrast_text
from modern_tooltips import register_tooltip, ensure_button_tooltips
from persona_media import avatar_photo, set_persona_avatar, clear_persona_avatar, showcase_quote
from modern_persona import PersonaEditorDialog
from modern_lore import LoreLibraryDialog
from dream_engine import dream_need, run_dream
from session_manager import SessionManager
from skin_manager import SKINS, get_sorted_skin_names, load_skin, save_skin
from ui_windowing import center_after_idle, apply_window_icon
from ui_preferences import load_ui_preferences, save_ui_preferences
from last_dirs import get_last_dir, remember_path
from resurrection import RETURNED, AMNESIAC, resurrect_persona


SOLO_CONTEXT_LEVELS = (1024, 2048, 4096, 8192, 16384, 24576, 32768, 49152, 65536, 98304, 131072)


def _context_label(tokens: int) -> str:
    tokens = int(tokens)
    if tokens % 1024 == 0:
        return f"{tokens // 1024}K"
    return f"{tokens:,}"


def initials(name):
    words = [w for w in str(name or '?').replace('-', ' ').split() if w]
    return ''.join(w[0].upper() for w in words[:2]) or '?'


class PersonaCard(tk.Frame):
    def __init__(self, parent, session, command, skin_name, dream_command=None):
        self.session = session
        self.command = command
        self.dream_command = dream_command
        self._photo = None
        p = palette(skin_name)
        super().__init__(parent, bg=p['panel'], highlightbackground=p['border'], highlightthickness=1, cursor='hand2')
        self.columnconfigure(1, weight=1)
        self.badge = tk.Label(self, text=initials(session.agent_name), width=3, bg=p['panel2'], fg=p['accent'],
                              font=('Segoe UI Semibold', 13), padx=7, pady=7)
        self.badge.grid(row=0, column=0, rowspan=2, padx=(9,7), pady=8)
        self._apply_avatar()
        self.name = tk.Label(self, text=session.agent_name, anchor='w', bg=p['panel'], fg=p['text'], font=('Segoe UI Semibold', 9))
        self.name.grid(row=0, column=1, sticky='sew', padx=(0,6))
        self.subtitle = tk.Label(self, text=session.name, anchor='w', bg=p['panel'], fg=p['muted'], font=('Segoe UI', 7))
        self.subtitle.grid(row=1, column=1, sticky='new', padx=(0,6))
        status_fg = '#65d48a' if not getattr(session, 'is_deceased', False) else '#ff6b6b'
        self.status = tk.Label(self, text='●', bg=p['panel'], fg=status_fg, font=('Segoe UI', 10))
        self.status.grid(row=0, column=2, rowspan=2, padx=(4,3))
        self.dream_button = None
        need = dream_need(session)
        if need.get('maintenance_due'):
            state = 'disabled' if need.get('cooldown') else 'normal'
            self.dream_button = tk.Button(self, text='☾', width=2, command=lambda: self.dream_command(self.session) if self.dream_command else None,
                                          state=state, relief='flat', bd=0, bg=p['panel'], fg=p['accent'],
                                          disabledforeground=p['muted'], activebackground=p['panel2'], activeforeground=p['accent'],
                                          font=('Segoe UI Symbol', 10), cursor='hand2' if state == 'normal' else 'arrow')
            self.dream_button.grid(row=0, column=3, rowspan=2, padx=(0,6))
        for w in (self, self.badge, self.name, self.subtitle, self.status):
            w.bind('<Button-1>', lambda _e: self.command(self.session))

    def _apply_avatar(self):
        photo = avatar_photo(self.badge, self.session, 44)
        self._photo = photo
        if photo:
            self.badge.configure(image=photo, text='', width=44, height=44, padx=0, pady=0)
        else:
            self.badge.configure(image='', text=initials(self.session.agent_name), width=3, height=1, padx=7, pady=7)

    def recolour(self, skin_name):
        p = palette(skin_name)
        self.configure(bg=p['panel'], highlightbackground=p['border'])
        self.badge.configure(bg=p['panel2'], fg=p['accent'])
        self.name.configure(bg=p['panel'], fg=p['text'])
        self.subtitle.configure(bg=p['panel'], fg=p['muted'])
        self.status.configure(bg=p['panel'])
        if self.dream_button is not None:
            self.dream_button.configure(bg=p['panel'], fg=p['accent'], disabledforeground=p['muted'], activebackground=p['panel2'], activeforeground=p['accent'])


class ModernShell:
    def __init__(self, root):
        self.root = root
        # A dirty recovery checkpoint means the previous process did not reach clean shutdown.
        try:
            from release_support import recovery_available, restore_recovery_checkpoint, discard_recovery_checkpoint
            if recovery_available():
                recover = messagebox.askyesno(
                    'Recover previous session?',
                    'Dunoon Daemon found a last-accepted-turn checkpoint from an interrupted run. Recover it?',
                    parent=root, icon='warning'
                )
                if recover:
                    restore_recovery_checkpoint()
                else:
                    discard_recovery_checkpoint()
        except Exception as exc:
            print(f'[Recovery Startup Warning]: {exc}')
        self.sm = SessionManager()
        self.brain = Brain()
        self.sm.controller_instance = self
        for _sess in self.sm.list_sessions():
            _sess.session_manager = self.sm
        self.active_chat_apps = {}
        self.active_arena_instance = None
        self.selected = self.sm.list_sessions()[0] if self.sm.list_sessions() else None
        self.model_path = ''
        self.model_loading = False
        self.skin_name = load_skin()
        self._tooltips = []
        self._showcase_photo = None
        self._header_photo = None
        self._model_nudge_job = None
        self._model_nudge_phase = 0.0
        self.model_btn = None
        self._persona_nudge_job = None
        self._persona_nudge_phase = 0
        self._persona_nudge_session_id = (
            str(getattr(self.selected, 'id', '') or '')
            if self.selected is not None and not str(getattr(self.selected, 'agent_name', '') or '').strip()
            else ''
        )
        self.persona_btn = None
        prefs = load_ui_preferences()
        wanted_ctx = int(prefs.get('solo_context_tokens', DEFAULT_CONTEXT) or DEFAULT_CONTEXT)
        self.solo_context_tokens = min(SOLO_CONTEXT_LEVELS, key=lambda n: abs(n - wanted_ctx))
        self._solo_context_index = tk.IntVar(value=SOLO_CONTEXT_LEVELS.index(self.solo_context_tokens))
        self._solo_context_label = tk.StringVar(value=f'Context: {_context_label(self.solo_context_tokens)}')
        self.root.title('Dunoon Daemon')
        self.root.geometry('1180x760')
        self.root.minsize(980,650)
        self._cards = []
        self.current_view = 'home'
        self._build()
        self.show_home()
        self._ensure_model_nudge()
        self._ensure_persona_nudge()
        self.root.protocol('WM_DELETE_WINDOW', self.close)

    def _p(self): return palette(self.skin_name)

    def _button(self, parent, text, command, accent=False):
        p=self._p(); bg=p['accent'] if accent else p['button']; fg=p['bg'] if accent else p['button_fg']
        return tk.Button(parent,text=text,command=command,relief='flat',bd=0,bg=bg,fg=fg,
                         activebackground=p['accent'],activeforeground=p['bg'],font=('Segoe UI Semibold',9),padx=12,pady=7,cursor='hand2')

    def _tip(self, widget, text):
        return register_tooltip(self._tooltips, widget, text)

    def _build(self):
        p=self._p(); self.root.configure(bg=p['bg']); apply_combobox_theme(self.root, self.skin_name)
        self.top=tk.Frame(self.root,bg=p['bg'],height=64); self.top.pack(fill='x'); self.top.pack_propagate(False)
        self.brand_block=tk.Frame(self.top,bg=p['bg']); self.brand_block.pack(side='left',padx=(22,4),pady=(7,5))
        brand_line=tk.Frame(self.brand_block,bg=p['bg']); brand_line.pack(anchor='w')
        self.brand_a=tk.Label(brand_line,text='DUNOON',bg=p['bg'],fg=p['text'],font=('Segoe UI Semibold',18)); self.brand_a.pack(side='left')
        self.brand_b=tk.Label(brand_line,text='DAEMON  v2.1.0',bg=p['bg'],fg=p['accent'],font=('Segoe UI',18)); self.brand_b.pack(side='left',padx=(4,0))
        self.brand_credit=tk.Label(self.brand_block,text='by sorvan76 (Kepler365) and ChatGPT',bg=p['bg'],fg=p['muted'],font=('Segoe UI',7),anchor='w')
        self.brand_credit.pack(anchor='w',pady=(0,1))
        self.runtime_label=tk.Label(self.top,text='●  No model loaded',bg=p['bg'],fg=p['muted'],font=('Segoe UI',9)); self.runtime_label.pack(side='right',padx=(10,22))
        self.interface_btn=self._button(self.top,'⚙',self.open_interface_settings); self.interface_btn.pack(side='right',padx=(5,2),pady=15)
        self._tip(self.interface_btn,'Open interface settings.')
        self.skin_var=tk.StringVar(value=self.skin_name)
        self.skin_combo=ttk.Combobox(self.top,values=get_sorted_skin_names(),textvariable=self.skin_var,state='readonly',width=16)
        self.skin_combo.pack(side='right',padx=6,pady=17)
        self.skin_combo.bind('<<ComboboxSelected>>',lambda _e:self.set_skin(self.skin_var.get()))
        self._tip(self.skin_combo,'Change the interface skin.')

        body=tk.Frame(self.root,bg=p['bg']); body.pack(fill='both',expand=True,padx=16,pady=(0,16)); self.body=body
        self.rail=tk.Frame(body,bg=p['panel'],width=274,highlightbackground=p['border'],highlightthickness=1); self.rail.pack(side='left',fill='y',padx=(0,12)); self.rail.pack_propagate(False)
        nav=tk.Frame(self.rail,bg=p['panel']); nav.pack(fill='x',padx=10,pady=(12,6)); self.nav=nav
        self.home_btn=self._button(nav,'Home',self.show_home); self.home_btn.pack(side='left',fill='x',expand=True,padx=(0,4)); self._tip(self.home_btn,'Return to the selected persona.')
        self.arena_btn=self._button(nav,'Arena',self.show_arena); self.arena_btn.pack(side='left',fill='x',expand=True,padx=(4,0)); self._tip(self.arena_btn,'Open Arena with two personas.')
        self.personas_label=tk.Label(self.rail,text='PERSONAS',bg=p['panel'],fg=p['muted'],font=('Segoe UI Semibold',8)); self.personas_label.pack(anchor='w',padx=14,pady=(12,6))
        outer=tk.Frame(self.rail,bg=p['panel']); outer.pack(fill='both',expand=True,padx=10); self.rail_outer=outer
        self.canvas=tk.Canvas(outer,bg=p['panel'],highlightthickness=0); self.persona_scrollbar=ttk.Scrollbar(outer,orient='vertical',command=self.canvas.yview)
        self.persona_list=tk.Frame(self.canvas,bg=p['panel']); self.persona_list.bind('<Configure>',lambda _e:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        win=self.canvas.create_window((0,0),window=self.persona_list,anchor='nw'); self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(win,width=e.width)); self.canvas.configure(yscrollcommand=self.persona_scrollbar.set)
        self.canvas.pack(side='left',fill='both',expand=True); self.persona_scrollbar.pack(side='right',fill='y')
        self._bind_persona_scroll_widget(self.canvas)
        self._bind_persona_scroll_widget(self.persona_list)
        self._rebuild_cards()
        persona_actions=tk.Frame(self.rail,bg=p['panel']); persona_actions.pack(fill='x',padx=10,pady=10); self.persona_actions=persona_actions
        self.create_btn=self._button(persona_actions,'+  Create',self.create_persona); self.create_btn.pack(side='left',fill='x',expand=True,padx=(0,4)); self._tip(self.create_btn,'Create a persona.')
        self.delete_btn=self._button(persona_actions,'Delete',self.delete_persona); self.delete_btn.pack(side='left',fill='x',expand=True,padx=(4,0)); self._tip(self.delete_btn,'Delete this persona after confirmation.')
        self._update_persona_action_state()
        self.main=tk.Frame(body,bg=p['panel'],highlightbackground=p['border'],highlightthickness=1); self.main.pack(side='left',fill='both',expand=True)
        ensure_button_tooltips(self.root, self._tooltips)

    def _bind_persona_scroll_widget(self, widget):
        # Persona-card rails are a local scroll surface. Bind the wheel to the widgets
        # themselves rather than bind_all(), so scrolling the library never hijacks chat/editor windows.
        def on_mousewheel(event):
            delta = getattr(event, 'delta', 0)
            if delta:
                steps = -1 if delta > 0 else 1
                # High-resolution wheels/trackpads may report multiples of 120 on Windows.
                if abs(delta) >= 120:
                    steps = -int(delta / 120)
                self.canvas.yview_scroll(steps, 'units')
            return 'break'
        def on_button4(_event):
            self.canvas.yview_scroll(-1, 'units'); return 'break'
        def on_button5(_event):
            self.canvas.yview_scroll(1, 'units'); return 'break'
        try:
            widget.bind('<MouseWheel>', on_mousewheel, add='+')
            widget.bind('<Button-4>', on_button4, add='+')
            widget.bind('<Button-5>', on_button5, add='+')
        except Exception:
            pass

    def _bind_persona_scroll_tree(self, widget):
        self._bind_persona_scroll_widget(widget)
        try:
            for child in widget.winfo_children():
                self._bind_persona_scroll_tree(child)
        except Exception:
            pass

    def _update_persona_action_state(self):
        if hasattr(self, 'delete_btn'):
            self.delete_btn.configure(state='normal' if self.selected is not None else 'disabled')

    def _rebuild_cards(self):
        for w in self.persona_list.winfo_children(): w.destroy()
        self._cards=[]
        for s in self.sm.list_sessions():
            c=PersonaCard(self.persona_list,s,self.select_persona,self.skin_name,self.dream_persona); c.pack(fill='x',pady=4); self._cards.append(c)
            self._bind_persona_scroll_tree(c)
            if c.dream_button is not None:
                need=dream_need(s)
                tip=(f"{s.agent_name} has already dreamed recently. Try again later." if need.get('cooldown') else f"{s.agent_name} could use a Dream. Memory consolidation is recommended.")
                self._tip(c.dream_button,tip)
        self.canvas.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))
        self._update_persona_action_state()

    def clear_main(self):
        if self.active_arena_instance is not None:
            try: self.active_arena_instance.shutdown()
            except Exception: pass
            self.active_arena_instance = None
        for w in self.main.winfo_children(): w.destroy()

    def select_persona(self, session):
        self.selected=session; self.show_home()

    def show_home(self):
        self.current_view='home'; self.clear_main(); p=self._p(); s=self.selected
        if not s: return

        header=tk.Frame(self.main,bg=p['panel']); header.pack(fill='x',padx=28,pady=(24,13)); self.home_header=header
        self.home_badge=tk.Label(header,text=initials(s.agent_name),bg=p['panel2'],fg=p['accent'],font=('Segoe UI Semibold',18),width=3,height=2)
        self.home_badge.pack(side='left',padx=(0,15))
        self._header_photo=avatar_photo(self.home_badge,s,58)
        if self._header_photo: self.home_badge.configure(image=self._header_photo,text='',width=58,height=58)
        box=tk.Frame(header,bg=p['panel']); box.pack(side='left',fill='x',expand=True)
        tk.Label(box,text=s.agent_name,bg=p['panel'],fg=p['text'],font=('Segoe UI Semibold',21),anchor='w').pack(fill='x')
        tk.Label(box,text=s.name,bg=p['panel'],fg=p['muted'],font=('Segoe UI',9),anchor='w').pack(fill='x',pady=(2,0))

        actions=tk.Frame(self.main,bg=p['panel']); actions.pack(fill='x',padx=28,pady=(0,16))
        open_btn=self._button(actions,'Open conversation',lambda:self.choose_chat(s),accent=True); open_btn.pack(side='left',padx=(0,8)); self._tip(open_btn,'Choose a conversation mode.')
        model_btn=self._button(actions,'Load GGUF',self.load_model); model_btn.pack(side='left',padx=8); self._tip(model_btn,'Load a local GGUF model using the selected context window.')
        self.model_btn = model_btn
        self._apply_model_button_state()
        ctx_box=tk.Frame(actions,bg=p['panel']); ctx_box.pack(side='left',padx=(8,6))
        ctx_label=tk.Label(ctx_box,textvariable=self._solo_context_label,bg=p['panel'],fg=p['muted'],font=('Segoe UI Semibold',8)); ctx_label.pack(anchor='w')
        ctx_slider=tk.Scale(ctx_box,from_=0,to=len(SOLO_CONTEXT_LEVELS)-1,orient='horizontal',showvalue=False,resolution=1,variable=self._solo_context_index,command=self._on_solo_context_slide,length=165,relief='flat',bd=0,highlightthickness=0,bg=p['panel'],fg=p['text'],activebackground=p['accent'],troughcolor=p['button'],sliderlength=16,width=9)
        ctx_slider.pack(anchor='w')
        self._tip(ctx_box,'Solo / native model context window: 1K to 128K tokens. Applies the next time a GGUF is loaded.')
        self._tip(ctx_slider,'Choose the context window for Solo / native model loading. Default is 16K; larger values use more memory.')
        memory_btn=self._button(actions,'Memory',lambda:self.open_memory(s)); memory_btn.pack(side='left',padx=8); self._tip(memory_btn,'Inspect or purge this persona’s learned memory.')
        self.persona_btn=self._button(actions,'Persona',lambda:self.open_persona(s)); self.persona_btn.pack(side='left',padx=8); self._tip(self.persona_btn,'Edit persona and OCEAN settings.')
        self._apply_persona_button_state()
        lore_btn=self._button(actions,'Lore',lambda:self.open_lore(s)); lore_btn.pack(side='left',padx=8); self._tip(lore_btn,'Open campaign lore and assign knowledge sources to personas.')

        tk.Frame(self.main,bg=p['border'],height=1).pack(fill='x',padx=28)
        content=tk.Frame(self.main,bg=p['panel']); content.pack(fill='both',expand=True,padx=28,pady=22)
        content.columnconfigure(0,weight=5); content.columnconfigure(1,weight=4); content.rowconfigure(0,weight=1)

        left=tk.Frame(content,bg=p['bg'],highlightbackground=p['border'],highlightthickness=1); left.grid(row=0,column=0,sticky='nsew',padx=(0,10))
        tk.Label(left,text='CONVERSATION MODES',bg=p['bg'],fg=p['muted'],font=('Segoe UI Semibold',8)).pack(anchor='w',padx=16,pady=(14,6))
        modes=[
            ('Continuation','same chat · memories in / out','Continue the existing conversation. Transcript and learned memories are available, and accepted turns may write new memories.'),
            ('Sandbox','fresh testbox · memories in / nothing out','Start a fresh transcript with learned memories available for reference. Nothing from the Sandbox is written back to learned memory.'),
            ('Canvas','same chat · long-term memories withheld','Keep the existing transcript but withhold learned long-term memory retrieval. Accepted turns can still create new memories.'),
            ('Bubble','fresh sealed chat · no memories in / out','Start completely fresh: no learned memories are read and nothing from the Bubble is written to learned memory.'),
        ]
        for name,desc,tip in modes:
            row=tk.Frame(left,bg=p['bg']); row.pack(fill='x',padx=16,pady=5)
            name_label=tk.Label(row,text=name,bg=p['bg'],fg=p['text'],font=('Segoe UI Semibold',9),width=13,anchor='w'); name_label.pack(side='left')
            desc_label=tk.Label(row,text=desc,bg=p['bg'],fg=p['muted'],font=('Segoe UI',9),anchor='w'); desc_label.pack(side='left',fill='x',expand=True)
            self._tip(row,tip); self._tip(name_label,tip); self._tip(desc_label,tip)
        tk.Frame(left,bg=p['border'],height=1).pack(fill='x',padx=16,pady=(14,10))
        tk.Label(left,text='LOCAL ENGINE',bg=p['bg'],fg=p['muted'],font=('Segoe UI Semibold',8)).pack(anchor='w',padx=16,pady=(0,6))
        status='Ready' if self.brain.backend.is_ready() else 'No model loaded'
        for k,v in [('Runtime','Dunoon Daemon native GGUF'),('Backend','CUDA / Vulkan / CPU fallback'),('Status',status),('Next-load context',_context_label(self.solo_context_tokens)),('Solo world authority','Human')]:
            r=tk.Frame(left,bg=p['bg']); r.pack(fill='x',padx=16,pady=5)
            tk.Label(r,text=k,bg=p['bg'],fg=p['muted'],font=('Segoe UI',9)).pack(side='left')
            tk.Label(r,text=v,bg=p['bg'],fg=p['text'],font=('Segoe UI Semibold',9)).pack(side='right')

        # The old empty right-hand area is now a quiet character showcase.
        show=tk.Frame(content,bg=p['panel2'],highlightbackground=p['border'],highlightthickness=1); show.grid(row=0,column=1,sticky='nsew',padx=(10,0))
        tk.Label(show,text='CHARACTER',bg=p['panel2'],fg=p['muted'],font=('Segoe UI Semibold',8)).pack(anchor='w',padx=16,pady=(14,4))
        self.showcase_avatar=tk.Label(show,text=initials(s.agent_name),bg=p['bg'],fg=p['accent'],font=('Segoe UI Semibold',35),width=6,height=3)
        self.showcase_avatar.pack(pady=(12,8))
        self._showcase_photo=avatar_photo(self.showcase_avatar,s,190)
        if self._showcase_photo: self.showcase_avatar.configure(image=self._showcase_photo,text='',width=190,height=190)
        tk.Label(show,text=s.agent_name,bg=p['panel2'],fg=p['text'],font=('Segoe UI Semibold',14)).pack(pady=(2,2))
        quote=showcase_quote(s)
        if quote:
            quote_text=f'“{quote}”'
            quote_fg=p['text']
        else:
            quote_text='No showcase quote pinned yet. Select a character line in chat, right-click it, and pin it here.'
            quote_fg=p['muted']
        self.showcase_quote_label=tk.Label(show,text=quote_text,wraplength=350,justify='center',bg=p['panel2'],fg=quote_fg,font=('Segoe UI',10,'italic'))
        self.showcase_quote_label.pack(fill='x',padx=28,pady=(12,16))
        media_row=tk.Frame(show,bg=p['panel2']); media_row.pack(pady=(0,16))
        avatar_btn=self._button(media_row,'Set avatar',lambda:self.set_avatar(s)); avatar_btn.pack(side='left',padx=4); self._tip(avatar_btn,'Choose this persona’s avatar.')
        if getattr(s,'avatar_path',''):
            clear_btn=self._button(media_row,'Clear avatar',lambda:self.clear_avatar(s)); clear_btn.pack(side='left',padx=4); self._tip(clear_btn,'Remove the avatar.')
        self._ensure_model_nudge()
        self._ensure_persona_nudge()
        ensure_button_tooltips(self.main, self._tooltips)

    def show_arena(self):
        self.current_view='arena'; self.clear_main()
        self.active_arena_instance=ModernArenaFrame(self.main,brain=self.brain,session_manager=self.sm,skin_name=self.skin_name)

    def _offer_resurrection(self, session):
        if not bool(getattr(session, 'is_deceased', False)):
            return False
        p=self._p(); agent=str(getattr(session,'agent_name','Persona') or 'Persona')
        win=tk.Toplevel(self.root); apply_window_icon(win)
        win.title(f'Resurrect · {agent}'); win.configure(bg=p['bg']); win.resizable(False,False); win.transient(self.root)
        accepted={'mode':None}
        body=tk.Frame(win,bg=p['bg']); body.pack(fill='both',expand=True,padx=22,pady=20)
        tk.Label(body,text=f'💀 {agent} is deceased',bg=p['bg'],fg=p['text'],font=('Segoe UI Semibold',13)).pack(anchor='w')
        tk.Label(body,text='Only an explicit human choice here may reverse death. Arena, Director output, old checkpoints and model prose cannot.',bg=p['bg'],fg=p['muted'],font=('Segoe UI',9),wraplength=510,justify='left').pack(anchor='w',fill='x',pady=(5,14))

        def choose(mode): accepted['mode']=mode; win.destroy()
        returned=tk.Button(body,text='The returned',command=lambda:choose(RETURNED),bg=p['accent'],fg=p['bg'],relief='flat',bd=0,font=('Segoe UI Semibold',9),padx=14,pady=8)
        returned.pack(fill='x')
        tk.Label(body,text='Knows they died and keeps the memory. Psychological scars may remain.',bg=p['bg'],fg=p['muted'],font=('Segoe UI',8),wraplength=500,justify='left').pack(anchor='w',pady=(3,11))
        amnesiac=tk.Button(body,text='The amnesiac',command=lambda:choose(AMNESIAC),bg=p['button'],fg=p['button_fg'],relief='flat',bd=0,font=('Segoe UI Semibold',9),padx=14,pady=8)
        amnesiac.pack(fill='x')
        tk.Label(body,text='Returns alive but cannot personally remember the fatal episode.',bg=p['bg'],fg=p['muted'],font=('Segoe UI',8),wraplength=500,justify='left').pack(anchor='w',pady=(3,11))
        tk.Button(body,text='Leave in repose',command=win.destroy,bg=p['button'],fg=p['button_fg'],relief='flat',bd=0,font=('Segoe UI Semibold',9),padx=14,pady=8).pack(fill='x')
        ensure_button_tooltips(win, self._tooltips)
        center_after_idle(win,self.root)
        try: win.grab_set()
        except Exception: pass
        self.root.wait_window(win)
        mode=accepted['mode']
        if not mode: return False
        if not resurrect_persona(session,mode,self.sm): return False
        self._rebuild_cards(); self.show_home()
        title='Returned to life' if mode==RETURNED else 'Returned with amnesia'
        detail=('They remember the death.' if mode==RETURNED else 'They do not personally remember the fatal episode.')
        messagebox.showinfo(title,f'{agent} is alive again.\n\n{detail}',parent=self.root)
        return True

    def choose_chat(self, session):
        if bool(getattr(session, 'is_deceased', False)):
            self._offer_resurrection(session)
            return
        mode_key=choose_chat_mode(self.root,self.skin_name,getattr(session,'agent_name','Persona'))
        if mode_key: self.open_chat(session,mode_key=mode_key)

    def open_chat(self, session, mode_key='continuation'):
        if bool(getattr(session, 'is_deceased', False)):
            messagebox.showinfo('Persona deceased',f"{getattr(session,'agent_name','This persona')} is deceased. Return to the home screen and choose Open conversation to access the explicit resurrection options.",parent=self.root)
            return
        spec=get_chat_mode(mode_key); chat_session=ChatSessionView(session,self.sm,spec)
        win=tk.Toplevel(self.root)
        apply_window_icon(win)
        app=ModernDunoonDaemonApp(win,chat_session,session_manager=self.sm,brain=self.brain)
        center_after_idle(win,self.root)
        chat_key=f"{session.id}:{spec.key}:{id(win)}"; self.active_chat_apps[chat_key]=app
        win.protocol('WM_DELETE_WINDOW',lambda key=chat_key,w=win:self._close_chat(key,w))

    def _close_chat(self,key,win):
        self.active_chat_apps.pop(key,None); win.destroy();
        if self.current_view=='home': self.show_home()

    def open_memory(self, session): PersonaMemoryDialog(self.root,self.skin_name,session)
    def open_lore(self, session=None): LoreLibraryDialog(self.root, self.skin_name, self.sm, focus_session=session or self.selected)
    def open_persona(self, session):
        if str(getattr(session, 'id', '') or '') == str(self._persona_nudge_session_id or ''):
            self._stop_persona_nudge()
        PersonaEditorDialog(self.root,self.skin_name,session,self.sm,on_saved=lambda _s:self._persona_saved(), brain=self.brain)
    def _persona_saved(self):
        self._rebuild_cards(); self.show_home()
    def dream_persona(self, session):
        # Dream can spend noticeable time deduplicating/index-pruning on a large vault.
        # Keep the UI responsive and make the maintenance transaction visibly active.
        p=self._p()
        progress=tk.Toplevel(self.root)
        apply_window_icon(progress)
        progress.title(f"Dream · {getattr(session, 'agent_name', 'Persona')}")
        progress.geometry('430x170')
        progress.resizable(False, False)
        progress.configure(bg=p['bg'])
        progress.transient(self.root)
        progress.protocol('WM_DELETE_WINDOW', lambda: None)
        body=tk.Frame(progress,bg=p['bg']); body.pack(fill='both',expand=True,padx=22,pady=20)
        tk.Label(body,text='DREAMING…',bg=p['bg'],fg=p['accent'],font=('Segoe UI Semibold',14)).pack(anchor='w')
        status_var=tk.StringVar(value='Snapshotting memory and checking repeated fragments…')
        tk.Label(body,textvariable=status_var,bg=p['bg'],fg=p['muted'],font=('Segoe UI',9),wraplength=380,justify='left').pack(anchor='w',fill='x',pady=(7,13))
        bar=ttk.Progressbar(body,mode='indeterminate',length=370)
        bar.pack(fill='x'); bar.start(12)
        center_after_idle(progress,self.root)
        try: progress.grab_set()
        except Exception: pass

        def finish(result):
            try: bar.stop()
            except Exception: pass
            try: progress.grab_release()
            except Exception: pass
            try: progress.destroy()
            except Exception: pass
            status=result.get('status')
            if status == 'complete':
                self._rebuild_cards()
                if self.selected is session and self.current_view == 'home': self.show_home()
                DreamReportDialog(self.root,self.skin_name,result)
            elif status in ('cooldown','not_needed'):
                messagebox.showinfo('Dream',result.get('message','Dream is not available yet.'),parent=self.root)
            else:
                messagebox.showerror('Dream',result.get('message','Dream could not complete.'),parent=self.root)

        def worker():
            try:
                result=run_dream(session)
            except Exception as exc:
                result={'status':'error','message':f'Dream could not complete: {exc}'}
            self.root.after(0,lambda r=result: finish(r))

        threading.Thread(target=worker,daemon=True).start()
    def open_interface_settings(self): InterfacePreferencesDialog(self.root,self.skin_name,brain=self.brain,session_manager=self.sm,on_master_purge=self._after_master_purge,on_restore=self._after_master_purge)

    def _after_master_purge(self):
        # Close live consumers before rebuilding against the new blank registry.
        for app in list(self.active_chat_apps.values()):
            try: app.root.destroy()
            except Exception: pass
        self.active_chat_apps.clear()
        try:
            if self.active_arena_instance is not None:
                self.active_arena_instance.destroy()
        except Exception:
            pass
        self.active_arena_instance = None
        sessions = self.sm.list_sessions()
        self.selected = sessions[0] if sessions else None
        if self.selected is not None:
            self._persona_nudge_session_id = str(getattr(self.selected, 'id', '') or '')
            self._persona_nudge_phase = 0
        self._rebuild_cards()
        self.show_home()

    def create_persona(self):
        name=prompt_text(self.root,self.skin_name,'Create persona','Session name:')
        if not name: return
        s=self.sm.create_session(name=name); s.session_manager=self.sm; self.selected=s
        self._persona_nudge_session_id = str(getattr(s, 'id', '') or '')
        self._persona_nudge_phase = 0
        self._rebuild_cards(); self.show_home()
        # A newly-created persona may land below the previous viewport; make it visible immediately.
        self.root.after_idle(lambda: self.canvas.yview_moveto(1.0))

    def delete_persona(self):
        session=self.selected
        if session is None:
            return
        sid=str(getattr(session,'id','') or '')
        name=str(getattr(session,'agent_name','') or getattr(session,'name','') or 'this persona')

        # Do not delete an object while a live view is still using it.
        if self.current_view == 'arena' and self.active_arena_instance is not None:
            messagebox.showinfo('Delete persona','Leave the current Arena before deleting a persona.',parent=self.root)
            return
        if any(str(key).startswith(sid + ':') for key in self.active_chat_apps):
            messagebox.showinfo('Delete persona',f'Close {name}\'s open conversation window before deleting this persona.',parent=self.root)
            return

        confirmed=messagebox.askyesno(
            'Delete persona',
            f'Permanently delete {name}?\n\nThis removes the persona / session from the app and cannot be undone.',
            parent=self.root,
            icon='warning'
        )
        if not confirmed:
            return

        sessions_before=self.sm.list_sessions()
        try:
            old_index=next((i for i,s in enumerate(sessions_before) if str(getattr(s,'id','')) == sid),0)
        except Exception:
            old_index=0
        self.sm.delete_session(sid)
        remaining=self.sm.list_sessions()
        if remaining:
            self.selected=remaining[min(old_index,len(remaining)-1)]
            self.selected.session_manager=self.sm
        else:
            self.selected=None
        self._rebuild_cards()
        self.show_home()

    def set_avatar(self, session):
        path=filedialog.askopenfilename(parent=self.root,initialdir=get_last_dir('avatar'),title=f'Set avatar · {session.agent_name}',filetypes=[('Images','*.png *.jpg *.jpeg *.webp *.bmp'),('All Files','*.*')])
        if not path: return
        remember_path('avatar', path)
        try:
            set_persona_avatar(session,path); self.sm.save(); self._rebuild_cards(); self.show_home()
        except Exception as exc:
            messagebox.showerror('Avatar Error',str(exc),parent=self.root)

    def clear_avatar(self, session):
        clear_persona_avatar(session); self.sm.save(); self._rebuild_cards(); self.show_home()

    def _on_solo_context_slide(self, value):
        try:
            index = int(round(float(value)))
        except Exception:
            index = SOLO_CONTEXT_LEVELS.index(16384)
        index = max(0, min(len(SOLO_CONTEXT_LEVELS) - 1, index))
        tokens = SOLO_CONTEXT_LEVELS[index]
        self.solo_context_tokens = tokens
        try:
            self._solo_context_index.set(index)
            self._solo_context_label.set(f'Context: {_context_label(tokens)}')
        except Exception:
            pass
        save_ui_preferences(solo_context_tokens=tokens)

    def load_model(self):
        if self.model_loading: return
        path=filedialog.askopenfilename(parent=self.root,initialdir=get_last_dir('model'),title='Select local GGUF model',filetypes=[('GGUF Models','*.gguf'),('All Files','*.*')])
        if not path: return
        remember_path('model', path)
        self.model_loading=True; self.model_path=path; self._stop_model_nudge(); self.runtime_label.config(text=f'◌  Loading {os.path.basename(path)}…',fg=self._p()['accent'])
        self._apply_model_button_state()
        def work():
            try:
                handler=create_model_handler(path,backend='auto',n_ctx=int(self.solo_context_tokens)); handler.load_model(); self.brain.model_handler=handler
                self.root.after(0,lambda:self._model_ready(path))
            except Exception as exc: self.root.after(0,lambda e=exc:self._model_failed(e))
        threading.Thread(target=work,daemon=True).start()

    def _model_ready(self,path):
        self.model_loading=False
        handler = getattr(self.brain, 'model_handler', None)
        handler_ctx = getattr(handler, 'n_ctx', self.solo_context_tokens)
        bits = [os.path.basename(path), f'{_context_label(handler_ctx)} ctx']
        try:
            weight = handler.get_model_weight_gb() if handler else None
            if weight:
                bits.append(f'{weight:.1f} GB')
        except Exception:
            pass
        try:
            if handler and bool(getattr(handler, 'is_vision_model', False)):
                bits.append('vision ready')
        except Exception:
            pass
        # Do not guess GPU/offload depth here. llama.cpp owns adaptive placement and the
        # terminal remains the authoritative source for layer/device telemetry.
        self.runtime_label.config(text='●  ' + ' · '.join(bits),fg='#65d48a')
        self._stop_model_nudge(); self.show_home()
    def _model_failed(self,exc):
        self.model_loading=False; self.runtime_label.config(text='●  Model failed to load',fg='#ff6b6b'); self._ensure_model_nudge(); messagebox.showerror('Model Load Error',str(exc),parent=self.root)

    def _apply_model_button_state(self):
        """Quietly signal that a GGUF is still required without turning Home into an alarm panel."""
        btn = getattr(self, 'model_btn', None)
        if btn is None:
            return
        p = self._p()
        try:
            if self.model_loading:
                btn.configure(text='Loading GGUF…', bg=p['button'], fg=p['accent'])
            elif self.brain.backend.is_ready():
                btn.configure(text='GGUF loaded', bg=p['button'], fg=p['button_fg'])
            else:
                wave = (math.sin(float(self._model_nudge_phase)) + 1.0) * 0.5
                amount = 0.12 + (0.34 * wave)
                def blend(a, b, t):
                    try:
                        aa=a.lstrip('#'); bb=b.lstrip('#')
                        av=[int(aa[i:i+2],16) for i in (0,2,4)]
                        bv=[int(bb[i:i+2],16) for i in (0,2,4)]
                        vals=[round(x+(y-x)*t) for x,y in zip(av,bv)]
                        return '#' + ''.join(f'{v:02x}' for v in vals)
                    except Exception:
                        return a
                bg = blend(p['button'], p['accent'], amount)
                btn.configure(text='Load GGUF', bg=bg, fg=contrast_text(bg), activebackground=p['accent'], activeforeground=contrast_text(p['accent']))
        except Exception:
            pass

    def _model_nudge_tick(self):
        self._model_nudge_job = None
        if self.model_loading or self.brain.backend.is_ready():
            self._model_nudge_phase = 0.0
            self._apply_model_button_state()
            return
        self._model_nudge_phase = (float(self._model_nudge_phase) + 0.22) % math.tau
        self._apply_model_button_state()
        try:
            self._model_nudge_job = self.root.after(90, self._model_nudge_tick)
        except Exception:
            self._model_nudge_job = None

    def _ensure_model_nudge(self):
        if self.model_loading or self.brain.backend.is_ready():
            self._stop_model_nudge()
            return
        if self._model_nudge_job is None:
            self._model_nudge_tick()

    def _stop_model_nudge(self):
        if self._model_nudge_job is not None:
            try:
                self.root.after_cancel(self._model_nudge_job)
            except Exception:
                pass
        self._model_nudge_job = None
        self._model_nudge_phase = 0.0
        self._apply_model_button_state()

    def _apply_persona_button_state(self):
        btn = getattr(self, 'persona_btn', None)
        if btn is None:
            return
        p = self._p()
        selected_id = str(getattr(self.selected, 'id', '') or '') if self.selected is not None else ''
        nudging = bool(self._persona_nudge_session_id and selected_id == str(self._persona_nudge_session_id))
        try:
            if nudging:
                lit = (int(self._persona_nudge_phase) % 2) == 0
                bg = p['accent'] if lit else p['button']
                fg = contrast_text(bg) if lit else p['button_fg']
                btn.configure(bg=bg, fg=fg, activebackground=p['accent'], activeforeground=contrast_text(p['accent']))
            else:
                btn.configure(bg=p['button'], fg=p['button_fg'], activebackground=p['accent'], activeforeground=p['bg'])
        except Exception:
            pass

    def _persona_nudge_tick(self):
        self._persona_nudge_job = None
        if not self._persona_nudge_session_id:
            self._persona_nudge_phase = 0
            self._apply_persona_button_state()
            return
        self._persona_nudge_phase = int(self._persona_nudge_phase) + 1
        self._apply_persona_button_state()
        try:
            self._persona_nudge_job = self.root.after(450, self._persona_nudge_tick)
        except Exception:
            self._persona_nudge_job = None

    def _ensure_persona_nudge(self):
        if not self._persona_nudge_session_id:
            self._apply_persona_button_state()
            return
        if self._persona_nudge_job is None:
            self._persona_nudge_tick()

    def _stop_persona_nudge(self):
        if self._persona_nudge_job is not None:
            try:
                self.root.after_cancel(self._persona_nudge_job)
            except Exception:
                pass
        self._persona_nudge_job = None
        self._persona_nudge_phase = 0
        self._persona_nudge_session_id = ''
        self._apply_persona_button_state()

    def _info(self,title,text): messagebox.showinfo(title,text,parent=self.root)

    def set_skin(self,name):
        if name not in SKINS: return
        self.skin_name=name; save_skin(name); self._recolour_shell()
        for app in list(self.active_chat_apps.values()):
            try: app._set_modern_skin(name)
            except Exception: pass

    def _refresh_theme_from_skin(self,name):
        if name in SKINS:
            self.skin_name=name; self.skin_var.set(name); self._recolour_shell()

    def _recolour_shell(self):
        p=self._p(); self.root.configure(bg=p['bg']); apply_combobox_theme(self.root, self.skin_name); self.top.configure(bg=p['bg']); self.body.configure(bg=p['bg'])
        self.brand_block.configure(bg=p['bg'])
        for _w in self.brand_block.winfo_children():
            try:
                _w.configure(bg=p['bg'])
            except Exception:
                pass
        self.brand_a.configure(bg=p['bg'],fg=p['text']); self.brand_b.configure(bg=p['bg'],fg=p['accent']); self.brand_credit.configure(bg=p['bg'],fg=p['muted']); self.runtime_label.configure(bg=p['bg'])
        self.rail.configure(bg=p['panel'],highlightbackground=p['border']); self.nav.configure(bg=p['panel']); self.personas_label.configure(bg=p['panel'],fg=p['muted']); self.rail_outer.configure(bg=p['panel']); self.canvas.configure(bg=p['panel']); self.persona_list.configure(bg=p['panel']); self.persona_actions.configure(bg=p['panel']); self.main.configure(bg=p['panel'],highlightbackground=p['border'])
        for c in self._cards: c.recolour(self.skin_name)
        for btn in (self.home_btn,self.arena_btn,self.create_btn,self.delete_btn,self.interface_btn):
            btn.configure(bg=p['button'],fg=p['button_fg'],activebackground=p['accent'],activeforeground=p['bg'])
        self._apply_model_button_state()
        if self.current_view=='arena' and self.active_arena_instance is not None:
            try: self.active_arena_instance.apply_skin(self.skin_name)
            except Exception: pass
        else: self.show_home()

    def close(self):
        try:
            from ui_preferences import load_ui_preferences
            if load_ui_preferences().get('autosave_recovery', True):
                from release_support import autosave_recovery
                autosave_recovery(self.sm, session_id=getattr(self.selected, 'id', None))
        except Exception as exc:
            print(f'[Recovery Autosave Warning]: {exc}')
        try:
            save_skin(self.skin_name)
        except Exception:
            pass
        try:
            from release_support import mark_clean_shutdown
            mark_clean_shutdown()
        except Exception as exc:
            print(f'[Recovery Shutdown Warning]: {exc}')
        self._stop_model_nudge()
        self._stop_persona_nudge()
        try:
            if self.brain.model_handler: self.brain.model_handler.unload_model()
        except Exception: pass
        self.root.destroy()


def main():
    # One GUI process at a time. Two Dunoon instances can race on persona/memory/state
    # files even when each individual write is atomic, so acquire the process guard before
    # Tk, SessionManager, model handlers, or background workers are created.
    from single_instance import SingleInstanceGuard, show_already_running_message
    guard = SingleInstanceGuard("DunoonDaemon")
    if not guard.acquire():
        show_already_running_message()
        return
    try:
        root=tk.Tk(); apply_window_icon(root, set_default=True); ModernShell(root); root.mainloop()
    finally:
        guard.release()

if __name__=='__main__': main()
