# 🐉 Silver Wyrm: modern_daemon.py — Dunoon Daemon modern live conversation shell,
# Keeps the mature chat behaviour while replacing the presentation layer.

import tkinter as tk
from tkinter import ttk, filedialog
from datetime import datetime
import json
import os

from dunoon_daemon import DunoonDaemonApp, _normalize_text_spacing
from eye_engine import ExpressiveVectorEyePair
from skin_manager import SKINS, apply_skin, get_sorted_skin_names, load_skin, save_skin


from modern_theme import palette, apply_combobox_theme
from font_controls import FontControlDialog
from ui_preferences import (
    CHAT_TYPEWRITER_DELAY_MS,
    load_ui_preferences,
    save_ui_preferences,
)
from modern_tooltips import register_tooltip, ensure_button_tooltips
from persona_media import avatar_photo, pin_showcase_quote
from ui_windowing import center_after_idle
from last_dirs import get_last_dir, remember_path
from tts_handler import VOICE_CONFIGS
from color_emoji import ColorEmojiRenderer, next_rich_token, insert_color_emoji


class ModernDunoonDaemonApp(DunoonDaemonApp):
    SOLO_DETAIL_LEVELS = (
        ("minimal", "Minimal", 256),
        ("light", "Light", 384),
        ("low", "Low", 512),
        ("med", "Med", 768),
        ("high", "High", 1024),
        ("very_high", "Very high", 1280),
        ("ultra", "Ultra", 1536),
        ("max", "Max", 2048),
    )

    """Presentation-only replacement for DunoonDaemonApp.

    The inherited send/poke/event/TTS/multimodal/memory paths remain the behavioural control
    during the UI transition. This lets us modernise the app without simultaneously changing cognition.
    """

    def _register_tooltip(self, widget, text):
        # Modern tooltips are globally optional and read the preference at hover time.
        if not hasattr(self, "tooltips"):
            self.tooltips = []
        return register_tooltip(self.tooltips, widget, text)

    def _button(self, parent, text, command, role='normal'):
        p = palette(load_skin())
        bg = p['accent'] if role == 'accent' else p['button']
        fg = p['bg'] if role == 'accent' else p['button_fg']
        b = tk.Button(
            parent, text=text, command=command, relief='flat', bd=0,
            bg=bg, fg=fg, activebackground=p['accent'], activeforeground=p['bg'],
            font=('Segoe UI Semibold', 9), padx=11, pady=7, cursor='hand2'
        )
        self.toolbar_buttons.append(b)
        return b

    def _paste_into_entry(self):
        try:
            text = self.root.clipboard_get()
        except Exception:
            return
        if not str(text or ''):
            return
        try:
            self.entry.delete(0, 'end')
            self.entry.insert(0, text)
            self.entry.focus_set()
        except Exception:
            pass

    def _build_ui(self):
        self.root.geometry('1040x760')
        self.root.minsize(820, 600)
        self.root.rowconfigure(0, weight=0)
        self.root.rowconfigure(1, weight=1)
        self.root.rowconfigure(2, weight=0)
        self.root.columnconfigure(0, weight=1)

        p = palette(load_skin())
        prefs = load_ui_preferences()
        self.chat_font_family = prefs['chat_font_family']
        self.chat_font_size = prefs['chat_font_size']
        self._font_dialog = None
        self._color_emoji = ColorEmojiRenderer(self.root)
        self._solo_event_pending = False
        self.solo_detail_level = str(prefs.get('solo_detail_level') or 'med')
        self._solo_detail_index = tk.IntVar(value=self._detail_index_for_key(self.solo_detail_level))
        self._solo_detail_label = tk.StringVar()
        self._apply_solo_detail_index(self._solo_detail_index.get(), persist=False)

        # Header: identity first, controls second.
        self.top_frame = tk.Frame(self.root, bg=p['bg'], height=76)
        self.top_frame.grid(row=0, column=0, sticky='ew')
        self.top_frame.grid_propagate(False)
        self.top_frame.columnconfigure(1, weight=1)
        self._identity_photo = None
        self._thinking_tick = False
        self.activity_strip = tk.Frame(self.top_frame, bg=p['bg'], height=3)
        # Width follows the final visible status text instead of spanning the whole header.
        self.activity_strip.place(x=0, rely=1.0, width=1, height=3, anchor='sw')

        identity = tk.Frame(self.top_frame, bg=p['bg'])
        identity.grid(row=0, column=0, sticky='w', padx=(18, 8), pady=11)
        self._identity_frame = identity
        agent = getattr(self.session, 'agent_name', 'Persona')
        initials = ''.join(w[0].upper() for w in agent.replace('-', ' ').split()[:2]) or '?'
        self.identity_badge = tk.Label(identity, text=initials, width=3, bg=p['panel2'], fg=p['accent'],
                                       font=('Segoe UI Semibold', 17), padx=5, pady=8)
        self.identity_badge.pack(side='left', padx=(0, 12))
        self._apply_identity_avatar()
        namebox = tk.Frame(identity, bg=p['bg']); namebox.pack(side='left')
        name_line = tk.Frame(namebox, bg=p['bg']); name_line.pack(anchor='w')
        self._name_line = name_line
        self.identity_name = tk.Label(name_line, text=agent, bg=p['bg'], fg=p['text'],
                                      font=('Segoe UI Semibold', 16), anchor='w')
        self.identity_name.pack(side='left', anchor='w')
        # Memory eyes belong to this persona, so keep them beside the persona name.
        self.eyes = ExpressiveVectorEyePair(name_line, size=38, bg=p['bg'])
        try:
            self.session.memory_activity_callback = self.eyes.trigger_retrieval
        except Exception:
            pass
        self.eyes.pack(side='left', padx=(9, 0))
        self.lights_label = self.eyes
        self.toolbar_buttons.append(self.eyes)
        self._register_tooltip(self.eyes, 'Eye colours show this persona’s memory activity: white idle / factual · green thinking · cyan working memory · red deep memory · yellow journal / continuation · purple intent · orange task · pink persona · blue retrieval · grey reset. Wandering is just personality.')
        _mode = getattr(self.session, 'chat_mode', None)
        _subtitle = getattr(self.session, 'name', '')
        if _mode is not None:
            _subtitle = f"{_subtitle}  ·  {_mode.label.upper()}  ·  {_mode.tagline}"
            try:
                self.root.title(f"Dunoon Daemon — {agent} [{_mode.label}]")
            except Exception:
                pass
        self.identity_subtitle = tk.Label(namebox, text=_subtitle, bg=p['bg'], fg=p['muted'],
                                          font=('Segoe UI', 8), anchor='w')
        self.identity_subtitle.pack(anchor='w', pady=(2,0))

        self.thinking_label = tk.Label(self.top_frame, text='', bg=p['bg'], fg=p['muted'], font=('Segoe UI', 9, 'italic'))
        self.thinking_label.grid(row=0, column=1, sticky='w', padx=10)
        # Status text is not a button. Keeping it out of the legacy toolbar skin pass
        # prevents a stray button-coloured/black rectangle in the otherwise seamless header.

        controls = tk.Frame(self.top_frame, bg=p['bg'])
        controls.grid(row=0, column=2, sticky='e', padx=(8, 18), pady=12)
        self._controls_frame = controls

        # Skin menu keeps all legacy flavours.
        self.skin_var = tk.StringVar(value=load_skin())
        skin_menu = ttk.Combobox(controls, values=get_sorted_skin_names(), textvariable=self.skin_var,
                                 state='readonly', width=17)
        skin_menu.pack(side='right', padx=5)
        skin_menu.bind('<<ComboboxSelected>>', lambda _e: self._set_modern_skin(self.skin_var.get()))
        self.skin_menu = skin_menu
        self._register_tooltip(skin_menu, 'Change the interface skin.')

        self.font_button = self._button(controls, f'Aa · {self.chat_font_size}', self._open_font_controls)
        self.font_button.pack(side='right', padx=5)
        self._register_tooltip(self.font_button, 'Change chat font and size.')

        self.detail_control = tk.Frame(controls, bg=p['bg'])
        self.detail_control.pack(side='right', padx=(5, 8))
        self.detail_text = tk.Label(self.detail_control, textvariable=self._solo_detail_label, bg=p['bg'], fg=p['muted'], font=('Segoe UI Semibold', 8))
        self.detail_text.pack(anchor='w')
        self.detail_slider = tk.Scale(
            self.detail_control, from_=0, to=len(self.SOLO_DETAIL_LEVELS) - 1, resolution=1, orient='horizontal', showvalue=False,
            variable=self._solo_detail_index, command=self._on_solo_detail_slide, length=150,
            relief='flat', bd=0, highlightthickness=0, bg=p['bg'], fg=p['text'],
            activebackground=p['accent'], troughcolor=p['button'], sliderlength=16, width=9,
        )
        self.detail_slider.pack(anchor='w')
        self._register_tooltip(self.detail_control, 'Solo response budget: 256 to 2048 visible tokens. Hidden reasoning is unchanged.')
        self._register_tooltip(self.detail_slider, 'Change Solo response detail. Applies on the next turn.')

        # Conversation room.
        chat_outer = tk.Frame(self.root, bg=p['bg'])
        chat_outer.grid(row=1, column=0, sticky='nsew', padx=16, pady=(0, 10))
        chat_outer.rowconfigure(0, weight=1); chat_outer.columnconfigure(0, weight=1)
        self._chat_outer = chat_outer

        self.chat_text = tk.Text(
            chat_outer, bg=p['panel'], fg=p['text'], insertbackground=p['accent'],
            wrap='word', font=(self.chat_font_family, self.chat_font_size), relief='flat', bd=0,
            padx=24, pady=20, spacing1=1, spacing3=5
        )
        self.chat_text.grid(row=0, column=0, sticky='nsew')
        scroll = tk.Scrollbar(chat_outer, orient='vertical', command=self.chat_text.yview, relief='flat', bd=0)
        scroll.grid(row=0, column=1, sticky='ns')
        self.chat_text.configure(yscrollcommand=scroll.set)
        self.chat_scroll = scroll
        self.chat_text.tag_config('you', foreground=p['accent'])
        self.chat_text.tag_config('agent', foreground=p['text'])
        self.chat_text.tag_config('system', foreground=p['muted'])
        self.chat_text.bind('<Button-3>', self._show_chat_context_menu, add='+')

        # Composer: primary actions live inside one visual unit.
        composer_outer = tk.Frame(self.root, bg=p['bg'])
        composer_outer.grid(row=2, column=0, sticky='ew', padx=16, pady=(0, 16))
        composer_outer.columnconfigure(0, weight=1)
        self._composer_outer = composer_outer

        composer = tk.Frame(composer_outer, bg=p['panel2'], highlightbackground=p['border'], highlightthickness=1)
        composer.grid(row=0, column=0, sticky='ew')
        composer.columnconfigure(2, weight=1)
        self._composer = composer

        self.upload_btn = self._button(composer, '＋', self.upload_as_file)
        self.upload_btn.grid(row=0, column=0, padx=(7,3), pady=6)
        self._register_tooltip(self.upload_btn, 'Attach a supported file.')
        emoji_btn = self._button(composer, '😊', self.open_emoji_picker)
        emoji_btn.grid(row=0, column=1, padx=3, pady=6)
        self._register_tooltip(emoji_btn, 'Open emoji palette.')
        try:
            _emoji_photo = self._color_emoji.photo('😊', max(16, int(self.chat_font_size * 1.45)))
            if _emoji_photo is not None:
                emoji_btn.configure(image=_emoji_photo, text='', padx=8, pady=5)
                self._emoji_button_photo = _emoji_photo
        except Exception:
            pass

        self.entry = tk.Entry(composer, bg=p['panel2'], fg=p['entry_fg'], insertbackground=p['accent'],
                              relief='flat', bd=0, font=(self.chat_font_family, self.chat_font_size))
        self.entry.grid(row=0, column=2, sticky='ew', padx=8, ipady=12)
        self.entry.bind('<Return>', self.send_message)

        self.paste_btn = self._button(composer, 'Paste', self._paste_into_entry)
        self.paste_btn.grid(row=0, column=3, padx=3, pady=6)
        self._register_tooltip(self.paste_btn, 'Paste clipboard text.')

        send = self._button(composer, 'Send', self.send_message, role='accent')
        send.grid(row=0, column=4, padx=(3,7), pady=6)
        self.send_button = send
        self._register_tooltip(self.send_button, 'Send this turn to the persona.')

        # Context actions are available but visually subordinate.
        utility = tk.Frame(composer_outer, bg=p['bg'])
        utility.grid(row=1, column=0, sticky='ew', pady=(7,0))
        self._utility = utility
        self.poke_btn = self._button(utility, '👉 Poke', self._handle_poke_click)
        self.poke_btn.pack(side='left', padx=(0,5))
        self._register_tooltip(self.poke_btn, 'Prompt the persona to speak spontaneously from the current conversation.')
        self.event_btn = self._button(utility, '⚡ Event', self._handle_add_event_click)
        self.event_btn.pack(side='left', padx=5)
        self._register_tooltip(self.event_btn, 'Generate a new external event from the current scene, without importing an old scene.')
        self.continue_btn = self._button(utility, '⏩ Continue', lambda: self._force_continue('Please continue.'))
        self.continue_btn.pack(side='left', padx=5)
        self._register_tooltip(self.continue_btn, 'Ask the persona to resume an interrupted or incomplete reply.')
        self.finish_btn = self._button(utility, '⏹ Finish', self._handle_finish_click)
        self.finish_btn.pack(side='left', padx=5)
        self._register_tooltip(self.finish_btn, 'Reveal the remainder of the current typewriter reply immediately.')
        self.export_btn = self._button(utility, 'Export', self.export_transcript)
        self.export_btn.pack(side='left', padx=5)
        self._register_tooltip(self.export_btn, 'Export this conversation as TXT, Markdown or structured JSON.')

        # Narration is one compact control group: Narrator | voice selector | Voice toggle.
        self.speak_button = self._button(utility, '🔊 Voice', self.toggle_speech)
        self.speak_button.pack(side='right', padx=(6,0))
        self._register_tooltip(self.speak_button, 'Toggle automatic narration.')

        voice_options = list(VOICE_CONFIGS.keys())
        self.voice_combo = ttk.Combobox(utility, values=voice_options, state='readonly', width=24)
        selected_voice = str(getattr(self.session, 'voice_mode', 'Sonia (UK Neural)') or 'Sonia (UK Neural)')
        if selected_voice not in VOICE_CONFIGS:
            selected_voice = 'Sonia (UK Neural)'
        self.voice_combo.set(selected_voice)
        self.tts.set_voice_mode(selected_voice)
        self.voice_combo.pack(side='right', padx=(4,0), pady=1)
        self.voice_combo.bind('<<ComboboxSelected>>', self._on_voice_selected)
        self._register_tooltip(self.voice_combo, 'Choose this persona’s narrator voice.')
        self.narrator_label = tk.Label(utility, text='Narrator', bg=p['bg'], fg=p['muted'],
                                       font=('Segoe UI Semibold', 8))
        self.narrator_label.pack(side='right', padx=(10,2))

        self._apply_chat_fonts()

        try:
            self.entry.focus_set()
        except Exception:
            pass
        ensure_button_tooltips(self.root, self.tooltips)


    def _emoji_px(self):
        return max(14, min(34, int(round(getattr(self, 'chat_font_size', 11) * 1.45))))

    def _rich_insert(self, text, tag=None):
        try:
            self._color_emoji.insert(self.chat_text, str(text or ''), tag=tag, target_px=self._emoji_px())
        except Exception:
            self.chat_text.insert(tk.END, str(text or ''), tag) if tag else self.chat_text.insert(tk.END, str(text or ''))

    @classmethod
    def _detail_index_for_key(cls, key: str) -> int:
        wanted = str(key or 'med').strip().lower()
        for index, (value, _label, _tokens) in enumerate(cls.SOLO_DETAIL_LEVELS):
            if value == wanted:
                return index
        return 3

    def _apply_solo_detail_index(self, index, *, persist: bool = True):
        try:
            index = int(round(float(index)))
        except Exception:
            index = self._detail_index_for_key('med')
        index = max(0, min(len(self.SOLO_DETAIL_LEVELS) - 1, index))
        key, label, tokens = self.SOLO_DETAIL_LEVELS[index]
        self.solo_detail_level = key
        try:
            self._solo_detail_index.set(index)
            self._solo_detail_label.set(f'Detail: {label} · {tokens}')
            self.session.solo_detail_tokens = tokens
        except Exception:
            pass
        turn_engine = getattr(getattr(self, 'brain', None), 'turn_engine', None)
        setter = getattr(turn_engine, 'set_solo_actor_budget', None)
        if callable(setter):
            setter(tokens)
        if persist:
            save_ui_preferences(solo_detail_level=key)
        return tokens

    def _on_solo_detail_slide(self, value):
        self._apply_solo_detail_index(value, persist=True)

    def _handle_add_event_click(self):
        if getattr(self, '_solo_event_pending', False):
            return
        self._solo_event_pending = True
        try:
            self.event_btn.configure(text='⚡ Event pending…', state='disabled')
        except Exception:
            pass
        return super()._handle_add_event_click()

    def _deliver_reply(self, raw_reply):
        try:
            return super()._deliver_reply(raw_reply)
        finally:
            if getattr(self, '_solo_event_pending', False):
                self._solo_event_pending = False
                try:
                    self.event_btn.configure(text='⚡ Event', state='normal')
                except Exception:
                    pass

    def _on_voice_selected(self, event=None):
        """Apply and persist the selected narrator voice as persona metadata."""
        selected_voice = str(self.voice_combo.get() or '').strip()
        if selected_voice not in VOICE_CONFIGS:
            return
        self.tts.set_voice_mode(selected_voice)
        try:
            self.session.voice_mode = selected_voice
        except Exception:
            pass
        manager = getattr(self, 'session_manager', None)
        try:
            if manager and hasattr(manager, 'save'):
                manager.save()
            elif manager and hasattr(manager, '_save'):
                manager._save()
        except Exception as exc:
            print(f'[Narrator Voice Save Warning]: {exc}')

    def export_transcript(self):
        try:
            visible = self.chat_text.get('1.0', 'end-1c').rstrip() + '\n'
        except Exception:
            visible = ''
        messages = [dict(m) for m in (getattr(self.session, 'messages', []) or []) if isinstance(m, dict)]
        if not visible.strip() and not messages:
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, initialdir=get_last_dir('solo_transcript_save'), title='Export conversation',
            defaultextension='.txt',
            filetypes=[('Plain text','*.txt'),('Markdown','*.md'),('Structured JSON','*.json'),('All files','*.*')],
        )
        if not path:
            return
        remember_path('solo_transcript_save', path)
        ext = os.path.splitext(path)[1].lower()
        agent = str(getattr(self.session, 'agent_name', 'Persona') or 'Persona')
        mode = getattr(getattr(self.session, 'chat_mode', None), 'label', getattr(self.session, 'chat_mode_key', 'continuation'))
        try:
            if ext == '.json':
                payload = {'format':'dunoon-solo-transcript','version':1,'exported_at':datetime.now().isoformat(),
                           'persona':agent,'chat_mode':str(mode),'messages':messages,'visible_text':visible}
                with open(path,'w',encoding='utf-8') as fh:
                    json.dump(payload,fh,indent=2,ensure_ascii=False)
            elif ext == '.md':
                lines=[f'# Dunoon Daemon Conversation: {agent}', '', f'**Mode:** {mode}', '']
                for m in messages:
                    role=str(m.get('role','user')).lower(); text=str(m.get('text') or m.get('content') or '').strip()
                    if not text: continue
                    who = 'You' if role == 'user' else (agent if role in {'assistant','agent','roxie','kylo'} else 'System')
                    lines.extend([f'## {who}', '', text, ''])
                with open(path,'w',encoding='utf-8') as fh:
                    fh.write('\n'.join(lines).rstrip()+'\n')
            else:
                with open(path,'w',encoding='utf-8') as fh:
                    fh.write(visible)
            self._append_local_system_notice(f'[Export] Transcript saved to {os.path.basename(path)}')
        except Exception as exc:
            self._append_local_system_notice(f'[Export] Failed: {exc}')

    def _chat_tail_is_visible(self):
        try:
            _first, last = self.chat_text.yview()
            return float(last) >= 0.985
        except Exception:
            return True

    def _follow_chat_tail_if_needed(self, follow):
        if follow:
            try:
                self.chat_text.see(tk.END)
            except Exception:
                pass

    def _append_text(self, speaker, text, colour):
        """Modern transcript insertion: ordinary text stays text; emoji become tiny colour images."""
        agent_display = getattr(self.session, 'agent_name', 'Kylo')
        display_speaker = 'You' if speaker in ('Chief', 'You', 'user') else (agent_display if speaker in ('Roxie', 'Kylo', 'assistant', 'roxie') else speaker)
        tag = 'you' if display_speaker == 'You' else ('agent' if display_speaker == agent_display else 'system')
        clean_content = _normalize_text_spacing(text)
        follow_tail = self._chat_tail_is_visible()
        self.chat_text.insert(tk.END, f'{display_speaker}: ', tag)
        self._rich_insert(clean_content, tag)
        self.chat_text.insert(tk.END, '\n\n', tag)
        self._follow_chat_tail_if_needed(follow_tail)

    def _type_out(self, speaker, text, colour, index=0):
        """Typewriter reveal that treats one multi-codepoint emoji as one visual token."""
        agent_display = getattr(self.session, 'agent_name', 'Kylo')
        tag = 'agent'

        if index == 0:
            self.is_typewriting = True
            self.full_current_reply = text
            self.typewriter_cancel_flag = False
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            follow_tail = self._chat_tail_is_visible()
            self.chat_text.insert(tk.END, f'[{timestamp}] {agent_display}:\n', tag)
            self._follow_chat_tail_if_needed(follow_tail)

        if self.typewriter_cancel_flag:
            follow_tail = self._chat_tail_is_visible()
            self._rich_insert(text[index:], tag)
            self.chat_text.insert(tk.END, '\n\n', tag)
            self._follow_chat_tail_if_needed(follow_tail)
            self.is_typewriting = False
            return

        if index < len(text):
            follow_tail = self._chat_tail_is_visible()
            is_emoji, token = next_rich_token(text, index)
            if is_emoji:
                if not insert_color_emoji(self.chat_text, self._color_emoji, token, self._emoji_px(), tag=tag):
                    self.chat_text.insert(tk.END, token, tag)
            else:
                self.chat_text.insert(tk.END, token, tag)
            self._follow_chat_tail_if_needed(follow_tail)
            self.chat_text.update()
            self.root.after(CHAT_TYPEWRITER_DELAY_MS, lambda: self._type_out(speaker, text, colour, index + len(token)))
        else:
            follow_tail = self._chat_tail_is_visible()
            self.chat_text.insert(tk.END, '\n\n')
            self._follow_chat_tail_if_needed(follow_tail)
            self.is_typewriting = False

    def _apply_identity_avatar(self):
        try:
            photo = avatar_photo(self.identity_badge, self.session, 52)
            self._identity_photo = photo
            if photo:
                self.identity_badge.configure(image=photo, text='', width=52, height=52, padx=0, pady=0)
            else:
                agent = getattr(self.session, 'agent_name', 'Persona')
                initials = ''.join(w[0].upper() for w in str(agent).replace('-', ' ').split()[:2]) or '?'
                self.identity_badge.configure(image='', text=initials, width=3, height=1, padx=5, pady=8)
        except Exception:
            pass

    def _show_chat_context_menu(self, event):
        menu = tk.Menu(self.root, tearoff=False)
        try:
            selected = self.chat_text.get('sel.first', 'sel.last').strip()
        except Exception:
            selected = ''
        menu.add_command(label='Pin selection as showcase quote', state='normal' if selected else 'disabled',
                         command=self._pin_selected_quote)
        menu.add_separator()
        menu.add_command(label='Copy', state='normal' if selected else 'disabled',
                         command=lambda: self.root.event_generate('<<Copy>>'))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try: menu.grab_release()
            except Exception: pass

    def _pin_selected_quote(self):
        try:
            selected = self.chat_text.get('sel.first', 'sel.last').strip()
        except Exception:
            selected = ''
        if not selected:
            return
        quote = pin_showcase_quote(self.session, selected)
        if not quote:
            return
        manager = getattr(self, 'session_manager', None)
        try:
            if manager and hasattr(manager, 'save'): manager.save()
            elif manager and hasattr(manager, '_save'): manager._save()
        except Exception as exc:
            print(f'[Showcase Quote Save Warning]: {exc}')
        self._flash_header_note('★  SHOWCASE QUOTE PINNED')

    def _flash_header_note(self, text, ms=1800):
        try:
            p = palette(load_skin())
            self.thinking_label.configure(text=text, fg=p['accent'], font=('Segoe UI Semibold', 9))
            self.root.after(ms, lambda: self.thinking_label.configure(text='', fg=p['muted'], font=('Segoe UI', 9, 'italic')) if not getattr(self, 'thinking_job', None) else None)
        except Exception:
            pass

    def open_emoji_picker(self):
        # Keep the mature palette behaviour, colourise its tiny glyphs, and stop it escaping.
        super().open_emoji_picker()
        try:
            if self.emoji_picker is not None and self.emoji_picker.winfo_exists():
                size = max(18, int(self.chat_font_size * 1.65))
                stack = [self.emoji_picker]
                while stack:
                    parent = stack.pop()
                    try:
                        children = parent.winfo_children()
                    except Exception:
                        children = []
                    stack.extend(children)
                    for child in children:
                        if not isinstance(child, tk.Button):
                            continue
                        glyph = str(child.cget('text') or '')
                        if not glyph:
                            continue
                        photo = self._color_emoji.photo(glyph, size)
                        if photo is not None:
                            child.configure(image=photo, text='', padx=5, pady=5)
                ensure_button_tooltips(self.emoji_picker, self.tooltips)
                center_after_idle(self.emoji_picker, self.root)
        except Exception:
            pass

    def _apply_chat_fonts(self):
        family = getattr(self, 'chat_font_family', 'Segoe UI Emoji')
        size = max(8, min(28, int(getattr(self, 'chat_font_size', 11))))
        try:
            self.chat_text.configure(font=(family, size))
            self.chat_text.tag_config('you', font=(family, max(8, size - 1), 'bold'))
            self.chat_text.tag_config('agent', font=(family, size))
            self.chat_text.tag_config('system', font=(family, max(8, size - 2), 'italic'))
            self.entry.configure(font=(family, size))
        except Exception:
            pass
        try:
            self.font_button.configure(text=f'Aa · {size}')
        except Exception:
            pass

    def _set_chat_font(self, family: str, size: int):
        self.chat_font_family = str(family or 'Segoe UI Emoji')
        self.chat_font_size = max(8, min(28, int(size)))
        save_ui_preferences(chat_font_family=self.chat_font_family, chat_font_size=self.chat_font_size)
        self._apply_chat_fonts()

    def _open_font_controls(self):
        try:
            if self._font_dialog is not None and self._font_dialog.winfo_exists():
                self._font_dialog.lift(); self._font_dialog.focus_force(); return
        except Exception:
            self._font_dialog = None
        self._font_dialog = FontControlDialog(self.root, self.chat_font_family, self.chat_font_size,
                                              self._set_chat_font, palette(load_skin()),
                                              title='Dunoon Daemon chat typography')

    def _update_activity_strip_extent(self):
        """End the activity bar under the right edge of the last visible status text."""
        try:
            self.root.update_idletasks()
            if str(self.thinking_label.cget('text') or '').strip():
                end_x = self.thinking_label.winfo_x() + self.thinking_label.winfo_width()
            else:
                end_x = self._identity_frame.winfo_x() + self._identity_frame.winfo_width()
            self.activity_strip.place_configure(width=max(1, int(end_x)))
        except Exception:
            pass

    def _show_thinking(self, count=0):
        """Strong modern feedback while the persona is generating."""
        if count == 0 and getattr(self, 'thinking_job', None) is not None:
            try:
                self.root.after_cancel(self.thinking_job)
            except Exception:
                pass
            self.thinking_job = None
        p = palette(load_skin())
        agent = getattr(self.session, 'agent_name', 'Persona')
        dots = '.' * ((count % 3) + 1)
        try:
            self.thinking_label.configure(
                text=f'●  {str(agent).upper()} THINKING{dots}',
                fg=p['accent'],
                font=('Segoe UI Semibold', 10),
            )
            # The identity badge itself becomes a second unmistakable activity cue.
            self.identity_badge.configure(bg=p['accent'], fg=p['bg'])
            self._thinking_tick = not getattr(self, '_thinking_tick', False)
            self.activity_strip.configure(bg=p['accent'] if self._thinking_tick else p['text'])
            self._update_activity_strip_extent()
        except Exception:
            pass
        self.thinking_job = self.root.after(320, lambda: self._show_thinking(count + 1))

    def _stop_thinking(self):
        if getattr(self, 'thinking_job', None) is not None:
            try:
                self.root.after_cancel(self.thinking_job)
            except Exception:
                pass
            self.thinking_job = None
        p = palette(load_skin())
        try:
            self.thinking_label.configure(text='', fg=p['muted'], font=('Segoe UI', 9, 'italic'))
            self.identity_badge.configure(bg=p['panel2'], fg=p['accent'])
            self.activity_strip.configure(bg=p['bg'])
            self._update_activity_strip_extent()
        except Exception:
            pass

    def _preflight_situation_gauges(self, context_text: str, source: str = "user"):
        """Actor generation no longer depends on traffic-light gauges."""
        return None

    def _set_modern_skin(self, name: str):
        save_skin(name)
        # Keep legacy skin persistence/synchronisation behaviour, then restore modern hierarchy.
        apply_skin(self, name)
        self._refresh_theme_from_skin(name)
        self.sync_to_controller()

    def _refresh_theme_from_skin(self, skin_name: str):
        # Retain inherited tag/combobox maintenance.
        super()._refresh_theme_from_skin(skin_name)
        p = palette(skin_name)
        apply_combobox_theme(self.root, skin_name)
        try:
            self.root.configure(bg=p['bg'])
            for frame in (self.top_frame, self._identity_frame, self._name_line, self._controls_frame, self.detail_control,
                          self._chat_outer, self._composer_outer, self._utility):
                frame.configure(bg=p['bg'])
            self._composer.configure(bg=p['panel2'], highlightbackground=p['border'])
            self.identity_badge.configure(bg=p['panel2'], fg=p['accent'])
            self.identity_name.configure(bg=p['bg'], fg=p['text'])
            self.identity_subtitle.configure(bg=p['bg'], fg=p['muted'])
            self.detail_text.configure(bg=p['bg'], fg=p['muted'])
            self.detail_slider.configure(bg=p['bg'], fg=p['text'], activebackground=p['accent'], troughcolor=p['button'])
            self.thinking_label.configure(bg=p['bg'], fg=p['muted'])
            self.narrator_label.configure(bg=p['bg'], fg=p['muted'])
            self.activity_strip.configure(bg=p['accent'] if getattr(self, 'thinking_job', None) else p['bg'])
            self.chat_text.configure(bg=p['panel'], fg=p['text'], insertbackground=p['accent'])
            self.chat_text.tag_config('you', foreground=p['accent'])
            self.chat_text.tag_config('agent', foreground=p['text'])
            self.chat_text.tag_config('system', foreground=p['muted'])
            self.entry.configure(bg=p['panel2'], fg=p['entry_fg'], insertbackground=p['accent'])
            self.eyes.set_background(p['bg'])
            for btn in (self.upload_btn, self.paste_btn, self.poke_btn, self.event_btn, self.continue_btn,
                        self.finish_btn, self.export_btn, self.speak_button, self.font_button):
                btn.configure(bg=p['button'], fg=p['button_fg'], activebackground=p['accent'], activeforeground=p['bg'])
            self.send_button.configure(bg=p['accent'], fg=p['bg'], activebackground=p['accent'], activeforeground=p['bg'])
            self._apply_chat_fonts()
        except Exception as exc:
            print(f'[Modern Skin Warning]: {exc}')

