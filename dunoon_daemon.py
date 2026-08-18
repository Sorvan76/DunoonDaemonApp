# dunoon_daemon.py — Autonomous Eye Telemetry, Unified Ingestion & Streamlined Slash Commands
import time
import tkinter as tk
from tkinter import ttk, filedialog, colorchooser, messagebox
import tkinter.font as tkfont
from datetime import datetime, timezone
from tts_handler import TTSHandler
import threading
import os
import glob
import json
import base64
import mimetypes
import requests
import pyttsx3
import math
import re
import traceback
import asyncio
import pygame

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from config import (
    BASE_DIR,
    AUDIO_CACHE_DIR,
    SESSIONS_DIR,
    DEFAULT_HOST,
    DEFAULT_PORT,
    get_session_vault_paths,
    ensure_dirs
)

from prune import run_session_sleep_cycle
from eye_engine import ExpressiveVectorEyePair
from memory_api import save_working_memory

try:
    from memory_api import load_working_memory
except ImportError:
    def load_working_memory(session_id=None, limit=20):
        try:
            paths = get_session_vault_paths(session_id or "default_session")
            vault_file = paths.get("working_memory")
            if vault_file and os.path.exists(vault_file):
                with open(vault_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data[-limit:]
        except Exception:
            pass
        return []

from memory_router import route_memory
from memory_deep import save_deep_memory_journal
from memory_validation import validate_memory
from memory_integrity import check_memory_integrity
from skin_manager import SKINS, apply_skin, load_skin, get_sorted_skin_names
from overmind import overmind

ensure_dirs()

_LAST_UPLOAD_DIRS = {
    "all": None,
    "image": None,
    "audio": None,
    "document": None
}

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False

try:
    from vault_auto_repair import repair_vaults
except ImportError:
    repair_vaults = lambda session_id=None: None

try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

try:
    import docx
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

print("LOADED DAEMON FROM:", __file__)

MODEL_NAME = None
MODEL_SUPPORTS_VISION = True
MODEL_SUPPORTS_AUDIO = True
MODEL_SUPPORTS_VIDEO = True


class Tooltip:
    """Provides hover tooltips with a configurable delay."""
    def __init__(self, widget, text_getter, delay=1000):
        self.widget = widget
        self.text_getter = text_getter
        self.delay = delay
        self.tipwindow = None
        self.id = None
        self.enabled = True

        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)
        self.widget.bind("<ButtonPress>", self.leave)

    def enter(self, event=None):
        if not self.enabled:
            return
        self.schedule()

    def leave(self, event=None):
        self.unschedule()
        self.hidetip()

    def schedule(self):
        self.unschedule()
        self.id = self.widget.after(self.delay, self.showtip)

    def unschedule(self):
        id_ = self.id
        self.id = None
        if id_:
            self.widget.after_cancel(id_)

    def showtip(self, event=None):
        if not self.enabled:
            return
        text = self.text_getter() if callable(self.text_getter) else self.text_getter
        if not text:
            return

        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5

        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)

        label = tk.Label(
            tw,
            text=text,
            justify=tk.LEFT,
            background="#2b2b2b",
            foreground="#00eaff",
            relief=tk.SOLID,
            borderwidth=1,
            font=("Segoe UI", 9),
            padx=6,
            pady=4
        )
        label.pack(ipadx=1)

    def hidetip(self):
        tw = self.tipwindow
        self.tipwindow = None
        if tw:
            tw.destroy()


def _normalize_text_spacing(text: str) -> str:
    """Collapses duplicate blank lines and normalizes paragraph spacing."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Clean whitespace at end of lines
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    # Collapse 3+ consecutive newlines to clean double newline
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _extract_dual_channel_meta(raw_text: str) -> tuple[dict, str]:
    """
    Extracts cognitive JSON metadata from any tag format:
    - <meta:{"mood":...}> or <meta: {...}>
    - <!--meta:{"mood":...}-->
    And thoroughly sanitizes visible dialogue.
    """
    meta_dict = {
        "mood": "neutral",
        "intensity": 0.0,
        "vault": "working",
        "significance": 0.5
    }
    
    if not raw_text:
        return meta_dict, ""

    clean_text = str(raw_text)

    # 1. Search for JSON metadata in both angle-bracket and HTML comment formats
    meta_pattern = r'(?:<!--|<)\s*meta:\s*(\{.*?\})\s*(?:-->|>)'
    match = re.search(meta_pattern, clean_text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict):
                meta_dict.update(parsed)
        except Exception:
            pass

    # 2. Strip all variations of metadata tags
    clean_text = re.sub(r'<!--\s*meta:\s*\{.*?\}\s*-->', '', clean_text, flags=re.DOTALL)
    clean_text = re.sub(r'<\s*meta:\s*\{.*?\}\s*>', '', clean_text, flags=re.DOTALL)
    clean_text = re.sub(r'<!--.*?-->', '', clean_text, flags=re.DOTALL)

    # 3. Strip deep-think / internal monologue / channel markers
    clean_text = re.sub(r'<\|[a-zA-Z0-9_]+\|>thought.*?<\|[a-zA-Z0-9_]+\|>', '', clean_text, flags=re.DOTALL | re.IGNORECASE)
    clean_text = re.sub(r'<think>.*?</think>', '', clean_text, flags=re.DOTALL | re.IGNORECASE)
    clean_text = re.sub(r'^thought\s*', '', clean_text, flags=re.IGNORECASE)
    clean_text = clean_text.replace("<|channel>", "").replace("<channel|>", "").replace("<|im_end|>", "")

    # 4. Normalize paragraph line spacing
    clean_text = _normalize_text_spacing(clean_text)

    return meta_dict, clean_text


def send_multimodal_message(text, file_path=None, endpoint=None):
    if not endpoint:
        endpoint = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}/v1/chat/completions"

    b64 = ""
    mime = "image/png"
    if file_path:
        with open(file_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")

        mime, _ = mimetypes.guess_type(file_path)
        if mime not in ("image/png", "image/jpeg", "image/webp"):
            mime = "image/png"

    if "/api/v1/chat" in endpoint:
        payload = {
            "model": MODEL_NAME or "local-model",
            "input": text,
        }
        if b64:
            payload["images"] = [f"data:{mime};base64,{b64}"]
    else:
        content = [{"type": "text", "text": text}]
        if b64:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"}
            })

        payload = {
            "model": MODEL_NAME or "local-model",
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 2048,
            "temperature": 0.7
        }

    try:
        resp = requests.post(endpoint, json=payload, timeout=90)
        resp.raise_for_status()
        data = resp.json()

        if "choices" in data and len(data["choices"]) > 0:
            return data["choices"][0]["message"]["content"]
        return data.get("output_text") or "(No reply returned, chief.)"

    except Exception as e:
        return f"[Multimodal Error: {e}]"


def detect_model_name():
    try:
        info = requests.get(f"http://{DEFAULT_HOST}:{DEFAULT_PORT}/v1/models", timeout=0.5).json()
        models = info.get("data", [])
        if models:
            return models[0].get("id", "local-model")
    except Exception:
        pass

    try:
        info = requests.get("http://localhost:1234/api/v1/models", timeout=0.5).json()
        model = info["data"][0]
        name = model.get("id") or model.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    except Exception:
        pass

    return "local-model"


class _MiniSession:
    def __init__(self, name="Standalone Chat", agent_name="Kylo"):
        self.id = "default_session"
        self.name = name
        self.agent_name = agent_name
        self.messages = []
        self.system_prompt = ""
        self.backstory = ""

    def _append(self, role, text):
        self.messages.append({
            "role": role,
            "text": text,
            "ts": datetime.now(timezone.utc).isoformat(),
        })

    def append_user(self, text):
        self._append("user", text)

    def append_roxie(self, text):
        self._append("roxie", text)

    def append_system(self, text):
        self._append("system", text)

    def get_history(self, limit=12):
        history = []
        for m in self.messages[-limit:]:
            text = m.get("text", "").strip()
            if text:
                history.append(text)
        return history


class UniversalFileProcessor:
    def __init__(self, whisper_model_size="small.en", device="cuda"):
        self.whisper = None
        self.whisper_model_size = whisper_model_size
        self.device = device

    def process_file(self, file_path: str) -> dict:
        if not os.path.exists(file_path):
            return {"type": "error", "content": "File path does not exist, chief.", "file_name": ""}

        file_name = os.path.basename(file_path)
        ext = os.path.splitext(file_name)[1].lower()

        image_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
        if ext in image_exts:
            mime, _ = mimetypes.guess_type(file_path)
            return {
                "type": "image",
                "content": file_path,
                "mime": mime or "image/png",
                "file_name": file_name,
            }

        audio_exts = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"}
        if ext in audio_exts:
            transcript = self._transcribe_audio(file_path)
            return {
                "type": "text",
                "content": f"[AUDIO PERCEPTION DIRECTIVE: THE USER HAS PLAYED/ATTACHED AN AUDIO TRACK ENTITLED '{file_name}':\nTranscribed Lyrics / Audio Telemetry:\n\"{transcript}\"\n\nReact directly and in character to this sound/song.]",
                "file_name": file_name,
            }

        if ext == ".pdf":
            pdf_text = self._extract_pdf(file_path)
            return {
                "type": "text",
                "content": f"[PDF DOCUMENT: '{file_name}']\n{pdf_text}",
                "file_name": file_name,
            }

        if ext == ".docx":
            docx_text = self._extract_docx(file_path)
            return {
                "type": "text",
                "content": f"[WORD DOCUMENT: '{file_name}']\n{docx_text}",
                "file_name": file_name,
            }

        text_exts = {".txt", ".py", ".md", ".json", ".csv", ".log", ".html", ".xml", ".c", ".cpp", ".js", ".css", ".sh", ".bat"}
        if ext in text_exts or ext == "":
            raw_text = self._read_text_file(file_path)
            return {
                "type": "text",
                "content": f"[FILE CONTENT: '{file_name}']\n{raw_text}",
                "file_name": file_name,
            }

        try:
            raw_text = self._read_text_file(file_path)
            return {
                "type": "text",
                "content": f"[FILE CONTENT: '{file_name}']\n{raw_text}",
                "file_name": file_name,
            }
        except Exception:
            return {
                "type": "unsupported",
                "content": f"Unsupported file format '{ext}' for '{file_name}'.",
                "file_name": file_name,
            }

    def _transcribe_audio(self, path: str) -> str:
        if not WHISPER_AVAILABLE:
            return "(faster-whisper not installed. Spoken audio text could not be extracted)."

        if self.whisper is None:
            try:
                self.whisper = WhisperModel(self.whisper_model_size, device=self.device, compute_type="float16")
                print(f"[Universal Perception] Loaded local Whisper '{self.whisper_model_size}' on {self.device}.")
            except Exception:
                try:
                    self.whisper = WhisperModel(self.whisper_model_size, device="cpu", compute_type="int8")
                    print(f"[Universal Perception] Loaded local Whisper '{self.whisper_model_size}' on CPU fallback.")
                except Exception as e:
                    print(f"[Universal Perception Warning] Could not load Whisper: {e}")
                    return f"(Error loading Whisper model: {e})"

        try:
            segments, _ = self.whisper.transcribe(path, beam_size=5, vad_filter=True)
            text = " ".join([seg.text.strip() for seg in segments]).strip()
            return text if text else "(No spoken words detected in audio track.)"
        except Exception as e:
            return f"(Error transcribing audio file: {e})"

    def _extract_pdf(self, path: str) -> str:
        if not PYPDF_AVAILABLE:
            return "(pypdf library not installed. Install via `pip install pypdf` to read PDF files)."
        try:
            reader = PdfReader(path)
            pages_text = []
            for idx, page in enumerate(reader.pages):
                txt = page.extract_text() or ""
                pages_text.append(f"--- Page {idx + 1} ---\n{txt}")
            return "\n\n".join(pages_text).strip()
        except Exception as e:
            return f"(Error reading PDF file: {e})"

    def _extract_docx(self, path: str) -> str:
        if not DOCX_AVAILABLE:
            return "(python-docx library not installed. Install via `pip install python-docx` to read .docx files)."
        try:
            doc = docx.Document(path)
            full_text = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n".join(full_text).strip()
        except Exception as e:
            return f"(Error reading Word document: {e})"

    def _read_text_file(self, path: str) -> str:
        for encoding in ("utf-8", "latin-1", "cp1252"):
            try:
                with open(path, "r", encoding=encoding) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
        raise ValueError("Could not decode plain text file.")


class DunoonDaemonApp:
    def __init__(self, root, session, session_manager=None, brain=None):
        self.brain = brain
        self.root = root
        self.session = session
        self.session_manager = session_manager
        self.session.session_manager = session_manager
        self.idle_reset_job = None

        self.tts = TTSHandler(provider="edge", voice="en-GB-SoniaNeural")
        self.speech_enabled = False
        self.last_reply = ""

        self.staged_file = None
        self.is_flashing_continue = False
        self.continue_flash_job = None
        self.continue_flash_phase = 0
        self.empty_stall_count = 0

        self.is_typewriting = False
        self.full_current_reply = ""
        self.typewriter_cancel_flag = False

        self._chat_embedded_assets = []
        self.tooltips = []

        self.file_processor = UniversalFileProcessor(whisper_model_size="small.en", device="cuda")

        global MODEL_NAME
        MODEL_NAME = detect_model_name() or MODEL_NAME or "local-model"

        skin_name = load_skin()
        base = SKINS.get(skin_name, SKINS["Dark"])

        self.theme = {
            "background": base.get("frame_bg", base.get("bg", "#111111")),
            "chat_bg": base.get("frame_bg", base.get("bg", "#111111")),
            "chat_fg": base.get("fg", "#ffffff"),
            "cursor": base.get("accent", base.get("fg", "#ffffff")),
            "you_colour": base.get("accent", "#ff5555"),
            "agent_colour": base.get("fg", "#ffffff"),
            "system_colour": base.get("fg", "#ffffff"),
        }
        self.theme.update(base)

        agent_display = getattr(self.session, "agent_name", "Kylo")
        session_name = getattr(self.session, "name", "Dunoon Daemon")
        self.root.title(f"Dunoon Daemon — {agent_display} [{session_name}]")

        # --- Window & Taskbar Icon Setup ---
        icon_png_path = os.path.join(BASE_DIR, "splash_logo.png")
        icon_ico_path = os.path.join(BASE_DIR, "icon.ico")

        if os.path.exists(icon_ico_path):
            try:
                self.root.iconbitmap(icon_ico_path)
            except Exception as e:
                print(f"[Iconbitmap Daemon Warning]: {e}")

        if os.path.exists(icon_png_path) and PIL_AVAILABLE:
            try:
                img = Image.open(icon_png_path)
                photo_icon = ImageTk.PhotoImage(img)
                self.root.iconphoto(True, photo_icon)
                self._icon_ref = photo_icon
            except Exception as e:
                print(f"[Iconphoto Daemon Warning]: {e}")

        self.toolbar_buttons = []
        self.thinking_job = None
        self.chat_messages = []
        self.chat_y_offset = 10
        self.emoji_picker = None

        self._build_ui()

        apply_skin(self, skin_name)
        self._refresh_theme_from_skin(skin_name)
        self._load_initial_session()

    def get_active_endpoint(self):
        controller = getattr(self.session_manager, "controller_instance", None) if self.session_manager else None
        brain_obj = getattr(self, "brain", None) or (controller.brain if controller else None)

        if brain_obj and hasattr(brain_obj, "model_handler") and brain_obj.model_handler:
            if getattr(brain_obj.model_handler, "server_process", None) is not None:
                return f"http://{DEFAULT_HOST}:{DEFAULT_PORT}/v1/chat/completions"

        try:
            resp = requests.get(f"http://{DEFAULT_HOST}:{DEFAULT_PORT}/v1/models", timeout=0.5)
            if resp.status_code == 200:
                return f"http://{DEFAULT_HOST}:{DEFAULT_PORT}/v1/chat/completions"
        except Exception:
            pass

        try:
            resp = requests.get("http://localhost:1234/api/v1/models", timeout=0.5)
            if resp.status_code == 200:
                return "http://localhost:1234/api/v1/chat"
        except Exception:
            pass

        return f"http://{DEFAULT_HOST}:{DEFAULT_PORT}/v1/chat/completions"

    def _register_tooltip(self, widget, text):
        tip = Tooltip(widget, text, delay=1000)
        self.tooltips.append(tip)
        return tip

    def _render_embedded_media_badge(self, file_path: str, media_type: str = "image"):
        if not os.path.exists(file_path):
            return

        file_name = os.path.basename(file_path)
        skin = SKINS.get(load_skin(), {})
        accent_col = skin.get("accent", "#00eaff")
        bg_col = skin.get("entry_bg", "#1a1a1a")

        if media_type == "image":
            if not PIL_AVAILABLE:
                self._append_local_system_notice(f"📁 Image Attached: {file_name}")
                return

            try:
                pil_img = Image.open(file_path)
                pil_img.thumbnail((120, 120), Image.Resampling.LANCZOS)
                tk_img = ImageTk.PhotoImage(pil_img)
                self._chat_embedded_assets.append(tk_img)

                thumb_frame = tk.Frame(self.chat_text, bg=bg_col, padx=4, pady=4, cursor="hand2")
                lbl_thumb = tk.Label(thumb_frame, image=tk_img, bg=bg_col, cursor="hand2")
                lbl_thumb.pack(side=tk.LEFT)

                lbl_caption = tk.Label(
                    thumb_frame, 
                    text=f" 🔍 {file_name}\n (Click to View)", 
                    bg=bg_col, 
                    fg=accent_col, 
                    font=("Segoe UI Emoji", 9, "bold"),
                    justify="left",
                    cursor="hand2"
                )
                lbl_caption.pack(side=tk.LEFT, padx=6)

                def _open_image(event=None, p=file_path):
                    try:
                        os.startfile(p)
                    except Exception as err:
                        print(f"[Viewer Launch Error]: {err}")

                thumb_frame.bind("<Button-1>", _open_image)
                lbl_thumb.bind("<Button-1>", _open_image)
                lbl_caption.bind("<Button-1>", _open_image)

                self.chat_text.insert(tk.END, "\n")
                self.chat_text.window_create(tk.END, window=thumb_frame)
                self.chat_text.insert(tk.END, "\n\n")
                self.chat_text.see(tk.END)

            except Exception as e:
                self._append_local_system_notice(f"📁 Attached Image: {file_name} [Thumb Error: {e}]")

        elif media_type == "audio":
            try:
                audio_frame = tk.Frame(self.chat_text, bg=bg_col, padx=8, pady=4, cursor="hand2")
                
                play_btn = tk.Label(
                    audio_frame,
                    text=f"▶️ Play Audio: {file_name}",
                    fg=accent_col,
                    bg=bg_col,
                    font=("Segoe UI Emoji", 9, "bold"),
                    cursor="hand2"
                )
                play_btn.pack(side=tk.LEFT)

                def _play_audio(event=None, p=file_path):
                    try:
                        if not pygame.mixer.get_init():
                            pygame.mixer.init()
                        if pygame.mixer.music.get_busy():
                            pygame.mixer.music.stop()
                            play_btn.config(text=f"▶️ Play Audio: {file_name}")
                        else:
                            pygame.mixer.music.load(p)
                            pygame.mixer.music.play()
                            play_btn.config(text=f"⏹️ Stop Audio: {file_name}")
                    except Exception as err:
                        print(f"[Audio Playback Error]: {err}")

                audio_frame.bind("<Button-1>", _play_audio)
                play_btn.bind("<Button-1>", _play_audio)

                self.chat_text.insert(tk.END, "\n")
                self.chat_text.window_create(tk.END, window=audio_frame)
                self.chat_text.insert(tk.END, "\n\n")
                self.chat_text.see(tk.END)

            except Exception as e:
                self._append_local_system_notice(f"🎵 Attached Audio: {file_name} [Audio Error: {e}]")

    def upload_as_file(self):
        initial_dir = _LAST_UPLOAD_DIRS.get("all") or os.path.expanduser("~")
        path = filedialog.askopenfilename(
            initialdir=initial_dir,
            title="Stage File for Context (Code, Documents, Images, Audio)",
            filetypes=[
                ("All Supported Files", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.mp3 *.wav *.m4a *.flac *.ogg *.pdf *.docx *.txt *.py *.md *.json *.csv *.log *.js *.cpp"),
                ("Images (Vision)", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"),
                ("Audio (Perception)", "*.mp3 *.wav *.m4a *.flac *.ogg"),
                ("Code & Vaults", "*.py *.json *.js *.cpp *.c *.h"),
                ("Documents", "*.pdf *.docx *.txt *.md *.csv *.log"),
                ("All Files", "*.*")
            ]
        )
        if path and os.path.exists(path):
            chosen_dir = os.path.dirname(path)
            _LAST_UPLOAD_DIRS["all"] = chosen_dir
            
            ext = os.path.splitext(path)[1].lower()
            if ext in ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif'):
                _LAST_UPLOAD_DIRS["image"] = chosen_dir
            elif ext in ('.mp3', '.wav', '.m4a', '.flac', '.ogg', '.aac'):
                _LAST_UPLOAD_DIRS["audio"] = chosen_dir
            else:
                _LAST_UPLOAD_DIRS["document"] = chosen_dir

            self.staged_file = path
            fname = os.path.basename(path)
            short_name = (fname[:10] + '..') if len(fname) > 12 else fname
            self.upload_btn.config(text=f"📎 {short_name}", bg="#007acc", fg="#ffffff")
            self._append_local_system_notice(f"[Staged Attachment]: '{fname}' queued. Type your context and press Send.")

    def _start_continue_flash(self):
        if self.is_flashing_continue:
            return
        self.is_flashing_continue = True
        self.continue_flash_phase = 0
        self._pulse_continue_loop()

    def _stop_continue_flash(self):
        if not self.is_flashing_continue:
            return
        self.is_flashing_continue = False
        if self.continue_flash_job:
            try:
                self.root.after_cancel(self.continue_flash_job)
            except Exception:
                pass
            self.continue_flash_job = None

        skin = SKINS.get(load_skin(), {})
        btn_bg = skin.get("button_bg", "#333333")
        btn_fg = skin.get("button_fg", "#ffffff")
        try:
            self.continue_btn.config(bg=btn_bg, fg=btn_fg)
        except Exception:
            pass

    def _pulse_continue_loop(self):
        if not self.is_flashing_continue:
            return

        skin = SKINS.get(load_skin(), {})
        accent_col = skin.get("accent", "#ff0055")
        btn_bg = skin.get("button_bg", "#333333")
        btn_fg = skin.get("button_fg", "#ffffff")

        if self.continue_flash_phase % 2 == 0:
            self.continue_btn.config(bg=accent_col, fg="#ffffff")
        else:
            self.continue_btn.config(bg=btn_bg, fg=btn_fg)

        self.continue_flash_phase += 1
        self.continue_flash_job = self.root.after(450, self._pulse_continue_loop)

    def _refresh_theme_from_skin(self, skin_name: str):
        base = SKINS.get(skin_name, SKINS["Dark"])
        self.theme.update({
            "background": base.get("frame_bg", base.get("bg", "#111111")),
            "chat_bg": base.get("frame_bg", base.get("bg", "#111111")),
            "chat_fg": base.get("fg", "#ffffff"),
            "cursor": base.get("accent", base.get("fg", "#ffffff")),
            "you_colour": base.get("accent", "#ff5555"),
            "agent_colour": base.get("fg", "#ffffff"),
            "system_colour": base.get("fg", "#ffffff"),
        })
        self.theme.update(base)

        try:
            style = ttk.Style()
            style.theme_use('default')
            
            bg_color = base.get("button_bg", "#333333")
            fg_color = base.get("button_fg", "#ffffff")
            accent_color = base.get("accent", "#007acc")

            style.configure(
                "TCombobox",
                fieldbackground=bg_color,
                background=bg_color,
                foreground=fg_color,
                darkcolor=bg_color,
                lightcolor=bg_color,
                arrowcolor=fg_color,
                bordercolor=bg_color,
                relief="flat",
            )
            style.map(
                "TCombobox",
                fieldbackground=[("readonly", bg_color)],
                foreground=[("readonly", fg_color)],
                background=[("readonly", bg_color)],
                selectbackground=[("readonly", accent_color)],
                selectforeground=[("readonly", fg_color)],
            )
            
            self.root.option_add('*TCombobox*Listbox.background', bg_color)
            self.root.option_add('*TCombobox*Listbox.foreground', fg_color)
            self.root.option_add('*TCombobox*Listbox.selectBackground', accent_color)
            self.root.option_add('*TCombobox*Listbox.selectForeground', fg_color)
        except Exception as e:
            print(f"[Combobox Skin Error]: {e}")

        try:
            self.chat_text.configure(
                bg=self.theme["chat_bg"],
                fg=self.theme["chat_fg"],
                insertbackground=self.theme["cursor"],
            )
            self.chat_text.tag_config("you", foreground=self.theme["you_colour"])
            self.chat_text.tag_config("agent", foreground=self.theme["agent_colour"])
            self.chat_text.tag_config("system", foreground=self.theme["system_colour"])
        except Exception:
            pass

    def _build_ui(self):
        self.root.rowconfigure(0, weight=0)
        self.root.rowconfigure(1, weight=1)
        self.root.rowconfigure(2, weight=0)
        self.root.columnconfigure(0, weight=1)

        self.top_frame = tk.Frame(self.root, bg="#1a1a1a")
        self.top_frame.grid(row=0, column=0, sticky="ew")

        self._build_toolbar()
        self._build_chat_canvas()
        self._build_input_area()

    def _build_toolbar(self):
        available_fonts = sorted(tkfont.families())

        def set_font(name):
            try:
                cur_sz = int(self.entry.cget("font").split()[1]) if len(self.entry.cget("font").split()) > 1 else 11
                self.entry.config(font=(name, cur_sz))
                self.chat_text.config(font=(name, cur_sz))
                if self.session_manager and getattr(self.session_manager, "controller_instance", None):
                    c_inst = self.session_manager.controller_instance
                    if hasattr(c_inst, "entry"):
                        c_inst.entry.config(font=(name, cur_sz))
            except Exception:
                pass

        def set_font_size(size):
            try:
                sz = int(size)
                cur_font = self.entry.cget("font").split()[0]
                self.entry.config(font=(cur_font, sz))
                self.chat_text.config(font=(cur_font, sz))
                if self.session_manager and getattr(self.session_manager, "controller_instance", None):
                    c_inst = self.session_manager.controller_instance
                    if hasattr(c_inst, "entry"):
                        c_inst.entry.config(font=(cur_font, sz))
            except Exception:
                pass

        def set_skin(n):
            apply_skin(self, n)
            self._refresh_theme_from_skin(n)
            self.sync_to_controller()

        current_skin = load_skin()
        skin_var = tk.StringVar(value=current_skin)

        font_var = tk.StringVar(value="Segoe UI Emoji")
        font_menu = tk.OptionMenu(self.top_frame, font_var, *available_fonts, command=set_font)
        font_menu.configure(bg="#333333", fg="#ffffff", activebackground="#444444", activeforeground="#ffffff", relief="flat", bd=0, highlightthickness=0)
        font_menu.pack(side=tk.RIGHT, padx=6)
        self.toolbar_buttons.append(font_menu)
        self._register_tooltip(font_menu, "Change global font across entry and chat history.")

        size_var = tk.StringVar(value="11")
        size_menu = tk.OptionMenu(self.top_frame, size_var, *[8, 9, 10, 11, 12, 14, 16, 18, 20, 24], command=set_font_size)
        size_menu.configure(bg="#333333", fg="#ffffff", activebackground="#444444", activeforeground="#ffffff", relief="flat", bd=0, highlightthickness=0)
        size_menu.pack(side=tk.RIGHT, padx=6)
        self.toolbar_buttons.append(size_menu)
        self._register_tooltip(size_menu, "Change text scale size.")

        sorted_skins = get_sorted_skin_names()
        skin_menu = tk.OptionMenu(self.top_frame, skin_var, *sorted_skins, command=set_skin)
        skin_menu.configure(bg="#333333", fg="#ffffff", activebackground="#444444", activeforeground="#ffffff", relief="flat", bd=0, highlightthickness=0)
        skin_menu.pack(side=tk.RIGHT, padx=6)
        self.toolbar_buttons.append(skin_menu)
        self._register_tooltip(skin_menu, "Select aesthetic visual color skin.")

        def pick_colour():
            colour = colorchooser.askcolor(title="Pick text colour")[1]
            if colour:
                self.entry.config(fg=colour, insertbackground=colour)
                self.sync_to_controller()

        colour_btn = tk.Button(self.top_frame, text="Colour", bg="#333333", fg="#ffffff", relief="flat", bd=0, padx=10, pady=6, command=pick_colour)
        colour_btn.pack(side=tk.RIGHT, padx=6)
        self.toolbar_buttons.append(colour_btn)
        self._register_tooltip(colour_btn, "Customize input font color.")

        def toggle_bold():
            font = tkfont.Font(font=self.entry.cget("font"))
            font.configure(weight="bold" if font.cget("weight") != "bold" else "normal")
            self.entry.config(font=font)
            self.chat_text.config(font=font)
            if self.session_manager and getattr(self.session_manager, "controller_instance", None):
                c_inst = self.session_manager.controller_instance
                if hasattr(c_inst, "entry"):
                    c_inst.entry.config(font=font)

        def toggle_italic():
            font = tkfont.Font(font=self.entry.cget("font"))
            font.configure(slant="italic" if font.cget("slant") != "italic" else "roman")
            self.entry.config(font=font)
            self.chat_text.config(font=font)
            if self.session_manager and getattr(self.session_manager, "controller_instance", None):
                c_inst = self.session_manager.controller_instance
                if hasattr(c_inst, "entry"):
                    c_inst.entry.config(font=font)

        bold_btn = tk.Button(self.top_frame, text="B", bg="#333333", fg="#ffffff", relief="flat", bd=0, padx=10, pady=6, command=toggle_bold)
        bold_btn.pack(side=tk.RIGHT, padx=6)
        self.toolbar_buttons.append(bold_btn)
        self._register_tooltip(bold_btn, "Toggle bold font weight.")

        italic_btn = tk.Button(self.top_frame, text="I", bg="#333333", fg="#ffffff", relief="flat", bd=0, padx=10, pady=6, command=toggle_italic)
        italic_btn.pack(side=tk.RIGHT, padx=6)
        self.toolbar_buttons.append(italic_btn)
        self._register_tooltip(italic_btn, "Toggle italic font slant.")

        self.eyes = ExpressiveVectorEyePair(self.top_frame, size=36)
        self.eyes.pack(side=tk.RIGHT, padx=6)
        self.lights_label = self.eyes
        self.toolbar_buttons.append(self.eyes)

        self.thinking_label = tk.Label(self.top_frame, text="", fg="#ffffff", bg="#1a1a1a", font=("Segoe UI", 10, "italic"))
        self.thinking_label.pack(side=tk.LEFT, padx=6)
        self.toolbar_buttons.append(self.thinking_label)

    def _build_chat_canvas(self):
        chat_frame = tk.Frame(self.root, bg=self.theme["background"])
        chat_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)

        chat_frame.rowconfigure(0, weight=1)
        chat_frame.columnconfigure(0, weight=1)

        scrollbar = tk.Scrollbar(chat_frame, orient="vertical")
        scrollbar.grid(row=0, column=1, sticky="ns")

        self.chat_text = tk.Text(
            chat_frame,
            bg=self.theme["chat_bg"],
            fg=self.theme["chat_fg"],
            insertbackground=self.theme["cursor"],
            wrap="word",
            yscrollcommand=scrollbar.set,
            font=("Segoe UI Emoji", 11),
            relief="flat",
            bd=0,
        )
        self.chat_text.grid(row=0, column=0, sticky="nsew")
        scrollbar.config(command=self.chat_text.yview)

        self.chat_text.tag_config("you", foreground=self.theme["you_colour"])
        self.chat_text.tag_config("agent", foreground=self.theme["agent_colour"])
        self.chat_text.tag_config("system", foreground=self.theme["system_colour"])

    def _build_input_area(self):
        try:
            input_frame = tk.Frame(self.root, bg="#111111")
            input_frame.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))

            for i in range(8):
                input_frame.columnconfigure(i, weight=1)

            self.entry = tk.Entry(
                input_frame,
                bg="#222222",
                fg="#ff5555",
                insertbackground="#ff5555",
                font=("Segoe UI Emoji", 11),
            )
            self.entry.grid(row=0, column=0, columnspan=6, sticky="nsew", padx=6, pady=6)
            self.entry.bind("<Return>", self.send_message)

            emoji_btn = tk.Button(input_frame, text="😊", font=("Segoe UI Emoji", 18), bg="#333333", fg="#ffffff", relief="flat", bd=0, padx=10, pady=6, command=self.open_emoji_picker)
            emoji_btn.grid(row=0, column=6, sticky="nsew", padx=6, pady=6)
            self.toolbar_buttons.append(emoji_btn)
            self._register_tooltip(emoji_btn, "Open emoji palette.")

            send_button = tk.Button(input_frame, text="Send", bg="#444444", fg="#ffffff", relief="flat", bd=0, padx=10, pady=6, command=self.send_message)
            send_button.grid(row=0, column=7, sticky="nsew", padx=6, pady=6)
            self.toolbar_buttons.append(send_button)
            self._register_tooltip(send_button, "Send dialogue turn to agent.")

            def mkbtn(text, cmd, col, bg="#333333", fg="#ffffff", activebg="#888888", tip_text=""):
                btn = tk.Button(
                    input_frame, text=text, command=cmd, bg=bg, fg=fg, 
                    activebackground=activebg, activeforeground="#ffffff", 
                    relief="flat", bd=0, padx=8, pady=6
                )
                btn.grid(row=1, column=col, sticky="nsew", padx=3, pady=6)
                self.toolbar_buttons.append(btn)
                if tip_text:
                    self._register_tooltip(btn, tip_text)
                return btn

            self.upload_btn = mkbtn("📁 Upload", self.upload_as_file, 0, tip_text="Stage an image, audio file, or document.")
            self.finish_btn = mkbtn("⏹️ Finish", self._handle_finish_click, 1, tip_text="Instantly complete ongoing typewriter streaming.")
            self.continue_btn = mkbtn("⏩ Continue", lambda: self._force_continue("Please continue."), 2, tip_text="Prompt agent to resume speaking.")
            self.poke_btn = mkbtn("👉 Poke", self._handle_poke_click, 3, tip_text="Prompt agent to speak spontaneously.")
            self.event_btn = mkbtn("⚡ Event", self._handle_add_event_click, 4, bg="#553311", fg="#ffaa00", tip_text="Inject an unfolding narrative situation from recent memories.")

            voice_options = [
                "Sonia (UK Neural)",
                "Ryan (UK Neural)",
                "Monster / Demon",
                "Robot / Synthetic",
                "Goblin / Gremlin",
                "Spectre / Deep",
                "Satnav (Local SAPI5)"
            ]
            self.voice_combo = ttk.Combobox(input_frame, values=voice_options, state="readonly", width=16, style="TCombobox")
            self.voice_combo.current(0)
            self.voice_combo.grid(row=1, column=5, columnspan=2, sticky="nsew", padx=3, pady=6)
            self.voice_combo.bind("<<ComboboxSelected>>", self._on_voice_selected)
            self._register_tooltip(self.voice_combo, "Select vocal archetype.")

            self.speak_button = mkbtn("Speak", self.toggle_speech, 7, tip_text="Toggle automatic text-to-speech reading.")

            try:
                self.entry.focus_set()
            except Exception:
                pass

        except Exception:
            print("\n\nINPUT AREA CRASHED, CHIEF:")
            traceback.print_exc()

    def _update_voice_progress_ui(self, progress: float):
        def gui_update():
            skin_name = load_skin()
            base = SKINS.get(skin_name, SKINS["Dark"])
            default_bg = base.get("button_bg", "#333333")
            default_fg = base.get("button_fg", "#ffffff")
            accent_color = base.get("accent", "#00eaff")

            if progress < 1.0 and self.tts.provider == "edge":
                self.speak_button.config(bg=accent_color, fg="#ffffff")
            else:
                self.speak_button.config(bg=default_bg, fg=default_fg)

        self.root.after(0, gui_update)

    def _on_voice_selected(self, event=None):
        selected_voice = self.voice_combo.get()
        self.tts.set_voice_mode(selected_voice)

    def _append_text(self, speaker, text, colour):
        agent_display = getattr(self.session, "agent_name", "Kylo")
        display_speaker = "You" if speaker in ("Chief", "You", "user") else (agent_display if speaker in ("Roxie", "Kylo", "assistant", "roxie") else speaker)
        tag = "you" if display_speaker == "You" else ("agent" if display_speaker == agent_display else "system")

        clean_content = _normalize_text_spacing(text)
        self.chat_text.insert(tk.END, f"{display_speaker}: {clean_content}\n\n", tag)
        self.chat_text.see(tk.END)

    def _type_out(self, speaker, text, colour, index=0):
        agent_display = getattr(self.session, "agent_name", "Kylo")
        tag = "agent"

        if index == 0:
            self.is_typewriting = True
            self.full_current_reply = text
            self.typewriter_cancel_flag = False

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            header = f"[{timestamp}] {agent_display}:\n"
            self.chat_text.insert(tk.END, header, tag)
            self.chat_text.see(tk.END)

        if self.typewriter_cancel_flag:
            remaining_text = text[index:]
            self.chat_text.insert(tk.END, f"{remaining_text}\n\n", tag)
            self.chat_text.see(tk.END)
            self.is_typewriting = False
            return

        if index < len(text):
            self.chat_text.insert(tk.END, text[index], tag)
            self.chat_text.see(tk.END)
            self.chat_text.update()
            self.root.after(12, lambda: self._type_out(speaker, text, colour, index + 1))
        else:
            self.chat_text.insert(tk.END, "\n\n")
            self.chat_text.see(tk.END)
            self.is_typewriting = False

    def _handle_finish_click(self):
        if self.is_typewriting:
            self.typewriter_cancel_flag = True

    def _handle_poke_click(self):
        self._stop_continue_flash()
        agent_display = getattr(self.session, "agent_name", "Kylo")
        session_id = getattr(self.session, "id", None) or getattr(self.session, "session_id", None)

        self.eyes.set_signal("#00eaff", sustain_seconds=1.5, pupil_scale=1.3)
        self._show_thinking()
        self.eyes.start_breathing()

        def worker():
            working_mems = load_working_memory(session_id=session_id)
            context_hint = ""
            if working_mems:
                last_mems = [m.get("text", "") if isinstance(m, dict) else str(m) for m in working_mems[-4:]]
                context_hint = " Recent topics / thoughts: " + " | ".join(last_mems)

            poke_prompt = (
                f"[DIRECTIVE: POKE]: Without referencing this prompt, speak up spontaneously. Make an unprompted remark, "
                f"share a perspective, or ask a question stemming naturally from our current flow.{context_hint} "
                f"Stay strictly in character as {agent_display} (1-2 sentences)."
            )

            try:
                controller = getattr(self.session_manager, "controller_instance", None) if self.session_manager else None
                if controller and hasattr(controller, "brain") and controller.brain:
                    reply = controller.brain.infer(poke_prompt, self.session)
                else:
                    reply = overmind(poke_prompt, self.session)
            except Exception as e:
                reply = f"({agent_display} tilts their head, waiting for you to lead.)"

            self.root.after(0, lambda: self._deliver_reply(reply))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_add_event_click(self):
        self._stop_continue_flash()
        agent_display = getattr(self.session, "agent_name", "Kylo")
        session_id = getattr(self.session, "id", None) or getattr(self.session, "session_id", None)

        self.eyes.set_signal("#ff8800", sustain_seconds=2.0, pupil_scale=1.4)
        self._show_thinking()
        self.eyes.start_breathing()

        def worker():
            working_mems = load_working_memory(session_id=session_id, limit=10)
            mem_block = ""
            if working_mems:
                parsed_mems = [m.get("text", "") if isinstance(m, dict) else str(m) for m in working_mems]
                mem_block = "\n".join(parsed_mems)

            event_prompt = (
                f"[DIRECTIVE: NARRATIVE EVENT INJECTION]\n"
                f"Scan these recent context memories:\n{mem_block}\n\n"
                f"Invent an instant, high-stakes external event or sudden occurrence unfolding right now in the scene. "
                f"React to it immediately in character as {agent_display} (2-3 sentences). Force a reaction from the User!"
            )

            try:
                controller = getattr(self.session_manager, "controller_instance", None) if self.session_manager else None
                if controller and hasattr(controller, "brain") and controller.brain:
                    reply = controller.brain.infer(event_prompt, self.session)
                else:
                    reply = overmind(event_prompt, self.session)
            except Exception as e:
                reply = f"({agent_display} suddenly stops: An unexpected commotion echoes nearby!)"

            self.root.after(0, lambda: self._deliver_reply(reply))

        threading.Thread(target=worker, daemon=True).start()

    def _persist_session(self, role, text):
        try:
            clean_text = _normalize_text_spacing(text)
            if hasattr(self.session, "append_user"):
                if role == "user":
                    self.session.append_user(clean_text)
                elif role in ("roxie", "assistant", "agent", "Kylo"):
                    self.session.append_roxie(clean_text)
                else:
                    self.session.append_system(clean_text)
            elif hasattr(self.session, "messages") and isinstance(self.session.messages, list):
                self.session.messages.append({
                    "role": role,
                    "text": clean_text,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })

            if self.session_manager:
                if hasattr(self.session_manager, "_save"):
                    self.session_manager._save()
                elif hasattr(self.session_manager, "save_sessions"):
                    self.session_manager.save_sessions()
        except Exception as e:
            self._append_local_system_notice(f"Session save failed, chief: {e}")

    def toggle_speech(self):
        self.speech_enabled = not self.speech_enabled
        if not self.speech_enabled:
            self.tts.stop()
            self.speak_button.config(text="Speak")
        else:
            self.speak_button.config(text="Spk On")

    def speak(self, text):
        if self.speech_enabled:
            self.voice_combo.set("⏳ PLEASE WAIT...")

            def _on_playback_started():
                self.root.after(0, lambda: self.voice_combo.set(self.tts.current_mode_name))

            def _on_progress(progress):
                self._update_voice_progress_ui(progress)
                if progress >= 1.0:
                    self.root.after(0, lambda: self.voice_combo.set(self.tts.current_mode_name))

            self.tts.speak(
                text, 
                progress_callback=_on_progress,
                on_start_callback=_on_playback_started
            )

    def _show_thinking(self, count=0):
        dots = "." * ((count % 3) + 1)
        agent_display = getattr(self.session, "agent_name", "Kylo")
        text = f"{agent_display} is thinking{dots}"
        self.thinking_label.configure(text=text)
        self.thinking_job = self.root.after(500, lambda: self._show_thinking(count + 1))

    def _stop_thinking(self):
        if self.thinking_job is not None:
            try:
                self.root.after_cancel(self.thinking_job)
            except Exception:
                pass
            self.thinking_job = None
        self.thinking_label.configure(text="")

    def send_message(self, event=None):
        self._stop_continue_flash()
        
        if hasattr(self, "tts"):
            self.tts.stop(fade_ms=350)
            
        user_text = self.entry.get().strip()
        attached_path = self.staged_file

        if not user_text and not attached_path:
            return

        if user_text.startswith("/"):
            self.entry.delete(0, tk.END)
            self._handle_slash_command(user_text)
            return

        if self.emoji_picker is not None and self.emoji_picker.winfo_exists():
            try:
                self.emoji_picker.destroy()
            except Exception:
                pass
            self.emoji_picker = None

        self.entry.delete(0, tk.END)

        self.staged_file = None
        skin_name = load_skin()
        base = SKINS.get(skin_name, SKINS["Dark"])
        self.upload_btn.config(text="📁 Upload", bg=base.get("button_bg", "#333333"), fg=base.get("button_fg", "#ffffff"))

        if user_text:
            self._append_text("You", user_text, "#ff5555")

        if attached_path:
            lower_path = attached_path.lower()
            fname = os.path.basename(attached_path)
            if lower_path.endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif')):
                self._render_embedded_media_badge(attached_path, media_type="image")
            elif lower_path.endswith(('.mp3', '.wav', '.m4a', '.flac', '.ogg', '.aac')):
                self._render_embedded_media_badge(attached_path, media_type="audio")
            else:
                self._append_local_system_notice(f"📁 Ingested Document: {fname}")

        self._show_thinking()
        self.eyes.start_breathing()

        def worker():
            agent_display = getattr(self.session, "agent_name", "Kylo")
            sys_prompt = getattr(self.session, "system_prompt", "").strip() or f"You are {agent_display}."

            try:
                if attached_path:
                    lower_p = attached_path.lower()
                    if lower_p.endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif')):
                        endpoint = self.get_active_endpoint()
                        context_directive = user_text if user_text else "Please inspect and react to this visual telemetry from your perspective."
                        full_prompt = (
                            f"{sys_prompt}\n\n"
                            f"[CRITICAL DIRECTIVE]: Stay 100% in character as {agent_display}. Never produce a sterile report, markdown headers, or break tone.\n\n"
                            f"User note: {context_directive}"
                        )
                        self._persist_session("user", f"[Attached Image: {os.path.basename(attached_path)}] {user_text}")
                        reply = send_multimodal_message(full_prompt, file_path=attached_path, endpoint=endpoint)
                    else:
                        parsed = self.file_processor.process_file(attached_path)
                        content = parsed.get("content", "")
                        combined_text = f"{user_text}\n\n{content}" if user_text else content

                        routing_info = route_memory(combined_text, session=self.session, is_user=True)
                        self.eyes.trigger_working()

                        controller = getattr(self.session_manager, "controller_instance", None) if self.session_manager else None
                        if controller and hasattr(controller, "brain") and controller.brain:
                            reply = controller.brain.infer(combined_text, self.session)
                        else:
                            reply = overmind(combined_text, self.session)
                else:
                    routing_info = route_memory(user_text, session=self.session, is_user=True)
                    self.eyes.trigger_working()

                    controller = getattr(self.session_manager, "controller_instance", None) if self.session_manager else None
                    if controller and hasattr(controller, "brain") and controller.brain:
                        reply = controller.brain.infer(user_text, self.session)
                    else:
                        reply = overmind(user_text, self.session)
            except Exception as e:
                reply = f"(Error talking to {agent_display}: {e})"

            self.root.after(0, lambda: self._deliver_reply(reply))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_slash_command(self, cmd_str: str):
        parts = cmd_str.strip().split()
        main_cmd = parts[0].lower()
        args = parts[1:]

        if main_cmd == "/about":
            self._append_local_system_notice("Dunoon Daemon Suite — to the loyal companions who walk with us through every realm, and the code that keeps their echoes alive. For Kylo. Made by RK (Kepler365), Gemini, ChatGPT and Copilot (2026) 🐕.")

        elif main_cmd == "/talk":
            if args and args[0] in ("1", "2", "3"):
                lvl = int(args[0])
                self.tts.set_speed(lvl)
                desc = {1: "Slow / Deliberate", 2: "Medium / Standard", 3: "Fast / Rapid Pace"}[lvl]
                self._append_local_system_notice(f"[Voice Engine] Speech speed set to Level {lvl} ({desc}).")
            else:
                self._append_local_system_notice("[Voice Engine] Usage: /talk 1 (Slow), /talk 2 (Medium), /talk 3 (Fast)")

        elif main_cmd == "/forget":
            turns = 1
            if args and args[0].isdigit():
                turns = int(args[0])
            
            if hasattr(self.session, "messages") and isinstance(self.session.messages, list):
                remove_count = min(turns * 2, len(self.session.messages))
                if remove_count > 0:
                    self.session.messages = self.session.messages[:-remove_count]
                    if self.session_manager:
                        self.session_manager._save()
                    self._append_local_system_notice(f"[System] Cleared last {turns} conversational turn(s) from context window.")
                else:
                    self._append_local_system_notice("[System] No message turns available to forget.")

        elif main_cmd in ("/see", "/look", "/upload"):
            self.upload_as_file()

        elif main_cmd == "/remember":
            if args:
                note_text = " ".join(args)
                session_id = getattr(self.session, "id", None) or getattr(self.session, "session_id", None)
                save_deep_memory_journal(note_text, session_id=session_id)
                self.eyes.set_signal("#ffff00", sustain_seconds=2.5, pupil_scale=1.4)
                self._append_local_system_notice(f"[Journal Vault] Forced direct memory injection: '{note_text}'")
            else:
                self._append_local_system_notice("[Journal Vault] Usage: /remember [key text to remember]")

        elif main_cmd in ("/memories", "/vault"):
            self._display_memories_breakdown()

        elif main_cmd == "/character":
            self._display_character_breakdown()

        elif main_cmd == "/baseline":
            self.session.psychology_mode = "grey_sensitive"
            self._append_local_system_notice("[Psychology Engine] Reverted to Grey Person Baseline (Mood-Sensitive).")

        elif main_cmd == "/ubaseline":
            self.session.psychology_mode = "ocean_sensitive"
            self._append_local_system_notice("[Psychology Engine] Dynamic Big Five (OCEAN) profile unlocked.")

        elif main_cmd == "/splash":
            import gc
            gc.collect()
            self._append_local_system_notice("[System] RAM / VRAM allocations garbage collected.")

        elif main_cmd == "/eject":
            controller = getattr(self.session_manager, "controller_instance", None) if self.session_manager else None
            if controller and hasattr(controller, "eject_main_model"):
                controller.eject_main_model()
                self._append_local_system_notice("[System] Native C++ engine ejected from VRAM.")

        elif main_cmd == "/status":
            ep = self.get_active_endpoint()
            self._append_local_system_notice(f"[System Diagnostic]\n• Active Model: {MODEL_NAME}\n• Endpoint: {ep}\n• Speech Provider: {self.tts.provider}\n• Backend: {getattr(self.session, 'backend', 'LM Studio')}")

        elif main_cmd == "/clear":
            self.chat_text.delete("1.0", tk.END)
            self._append_local_system_notice("[Canvas Cleared]")

        else:
            self._append_local_system_notice(f"[System] Unknown command '{main_cmd}'. Try /about, /talk 1-3, /forget x, /remember, /memories, /character, /status, or /clear.")

    def _display_character_breakdown(self):
        try:
            agent_display = getattr(self.session, "agent_name", "Kylo")
            mode = getattr(self.session, "psychology_mode", "ocean_sensitive")

            if mode == "grey_analytical":
                self._append_local_system_notice(
                    f"[System Diagnostic] Psychological Profile for '{agent_display}':\n"
                    "• Mode: Pure Analytical (Grey Person)\n"
                    "• State: Mood Shifts Disabled / Fixed 50-Point Anchor\n"
                    "• Openness          : ██████████░░░░░░░░░░ (50/100 [±0 pts]) → (Analytical)\n"
                    "• Conscientiousness : ██████████░░░░░░░░░░ (50/100 [±0 pts]) → (Methodical)\n"
                    "• Extraversion      : ██████████░░░░░░░░░░ (50/100 [±0 pts]) → (Reserved)\n"
                    "• Agreeableness     : ██████████░░░░░░░░░░ (50/100 [±0 pts]) → (Objective)\n"
                    "• Neuroticism       : ██████████░░░░░░░░░░ (50/100 [±0 pts]) → (Calm)"
                )
                return

            ocean_wrapper = getattr(self.session, "ocean_profile", None) or getattr(self.session, "ocean", None)
            
            if not ocean_wrapper or not isinstance(ocean_wrapper, dict):
                info = f"[System Diagnostic] '{agent_display}' is running on a neutral baseline profile."
            else:
                traits = ocean_wrapper.get("traits", ocean_wrapper)
                last_update = getattr(self.session, "last_mood_update", "Unlocked")
                lines = [f"[System Diagnostic] Psychological Profile (OCEAN) for '{agent_display}' [Date: {last_update}]:"]
                
                for trait_name in ["Openness", "Conscientiousness", "Extraversion", "Agreeableness", "Neuroticism"]:
                    data = next((v for k, v in traits.items() if k.lower() == trait_name.lower()), 50)
                    
                    if isinstance(data, dict):
                        active_val = float(data.get("score", 50.0))
                        base_val = float(data.get("base_score", active_val))
                        descriptors_list = list(data.get("descriptors", []))
                        core_desc = data.get("core_descriptor", "")
                    else:
                        active_val = float(data)
                        base_val = active_val
                        descriptors_list = []
                        core_desc = ""

                    delta = active_val - base_val
                    base_blocks = int(round(base_val / 5.0))
                    active_blocks = int(round(active_val / 5.0))
                    
                    if delta >= 0:
                        shadow_blocks = active_blocks - base_blocks
                        empty_blocks = max(0, 20 - active_blocks)
                        bar = ("█" * base_blocks) + ("▓" * shadow_blocks) + ("░" * empty_blocks)
                        delta_str = f"+{delta:.0f} pts" if delta > 0 else "±0 pts"
                        state_tag = "[INTENSIFIED]" if delta >= 5 else "[ANCHOR]"
                    else:
                        suppressed_blocks = base_blocks - active_blocks
                        empty_blocks = max(0, 20 - base_blocks)
                        bar = ("█" * active_blocks) + ("▒" * suppressed_blocks) + ("░" * empty_blocks)
                        delta_str = f"{delta:.0f} pts"
                        state_tag = "[MUTED]" if delta <= -5 else "[ANCHOR]"

                    formatted_descs = []
                    for idx, desc in enumerate(descriptors_list):
                        if core_desc and desc == core_desc and idx == 0:
                            formatted_descs.append(f"★{desc} {state_tag}")
                        else:
                            formatted_descs.append(desc)

                    desc_str = f" → ({', '.join(formatted_descs)})" if formatted_descs else ""
                    lines.append(f"• {trait_name:<17}: {bar} ({active_val:.0f}/100 [{delta_str}]){desc_str}")

                info = "\n".join(lines)
        except Exception as e:
            info = f"[System Diagnostic] Error reading OCEAN profile: {e}"

        self._append_local_system_notice(info)

    def _display_memories_breakdown(self):
        try:
            session_id = getattr(self.session, "id", None) or getattr(self.session, "session_id", None) or "default_session"
            session_paths = get_session_vault_paths(session_id)

            lines = [f"[System Diagnostic] Memory Vault Audit for '{self.session.name}':"]
            total_memories = 0

            for vault_name, file_path in session_paths.items():
                if vault_name == "vault_dir":
                    continue
                count = 0
                sample = ""
                if os.path.exists(file_path):
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            if isinstance(data, list):
                                count = len(data)
                                if data:
                                    last_item = data[-1]
                                    if isinstance(last_item, dict) and "text" in last_item:
                                        sample = last_item["text"][:60]
                                    elif isinstance(last_item, str):
                                        sample = last_item[:60]
                    except Exception:
                        pass

                clean_vault_name = vault_name.replace("_memory", "").replace("_", " ").title()
                preview = f' (Latest: "{sample}...")' if sample else ""
                lines.append(f"• {clean_vault_name:<16}: {count} records{preview}")
                total_memories += count

            lines.append(f"\n📊 Total Vault Entries: {total_memories}")
            info = "\n".join(lines)
        except Exception as e:
            info = f"[System Diagnostic] Error reading memory vaults: {e}"

        self._append_local_system_notice(info)

    def _append_local_system_notice(self, text: str):
        try:
            clean_content = _normalize_text_spacing(text)
            self.chat_text.insert(tk.END, f"\n{clean_content}\n\n", "system")
            self.chat_text.see(tk.END)
        except Exception as e:
            print(f"[System Notice Error]: {e}")

    def _force_idle(self):
        self.eyes.stop_breathing()

        threading.Thread(
            target=run_session_sleep_cycle, 
            args=(self.session,), 
            daemon=True
        ).start()

    def _deliver_reply(self, raw_reply):
        self._stop_thinking()
        self.eyes.stop_breathing()

        agent_display = getattr(self.session, "agent_name", "Kylo")

        is_empty_response = False
        raw_str = str(raw_reply).strip() if raw_reply is not None else ""

        if not raw_str or "completed turn, but returned an empty response" in raw_str:
            is_empty_response = True
            self.empty_stall_count += 1
        else:
            self.empty_stall_count = 0

        meta_data, clean_reply = _extract_dual_channel_meta(raw_str)

        # --- Dangling Token Sanitizer & Anti-Stall Recovery ---
        clean_reply = clean_reply.strip()
        if clean_reply.endswith("--") or clean_reply.endswith("-"):
            clean_reply = clean_reply.rstrip("-") + "..."
        if clean_reply.count('"') % 2 != 0:
            clean_reply += '"'
        if clean_reply.count('*') % 2 != 0:
            clean_reply += '*'

        if is_empty_response:
            if self.empty_stall_count >= 2:
                clean_reply = f"*{agent_display} blinks and refocuses.* \"Right, where were we? Let's get straight to it.\""
                self.empty_stall_count = 0
                is_empty_response = False
            else:
                clean_reply = f"({agent_display} pauses in thought. Press ⏩ Continue or send another prompt to proceed.)"

        self.last_reply = clean_reply
        self._type_out(agent_display, clean_reply, "#b300ff")

        if is_empty_response:
            self._start_continue_flash()
        else:
            self._stop_continue_flash()

        # Persist only genuine replies
        if not is_empty_response:
            session_id = getattr(self.session, "id", None) or getattr(self.session, "session_id", None)
            target_vault = meta_data.get("vault", "working")
            significance = float(meta_data.get("significance", 0.5))

            if target_vault == "deep" or significance >= 0.75:
                primacy_count = getattr(self.session, "primacy_count", 0)
                primacy_enabled = getattr(self.session, "primacy_enabled", True)
                save_deep_memory_journal(clean_reply, session_id=session_id, primacy_count=primacy_count, primacy_enabled=primacy_enabled)
                self.eyes.trigger_deep()
                self.eyes.trigger_journal()
            else:
                save_working_memory(clean_reply, session_id=session_id)
                self.eyes.trigger_working()

            self._persist_session("assistant", clean_reply)

            if self.speech_enabled:
                self.speak(clean_reply)

        if self.idle_reset_job is not None:
            try:
                self.root.after_cancel(self.idle_reset_job)
            except Exception:
                pass

        self.idle_reset_job = self.root.after(3000, self._force_idle)

    def _force_continue(self, prompt="Please continue."):
        self._stop_continue_flash()
        if hasattr(self, "tts"):
            self.tts.stop(fade_ms=350)
            
        self._append_text("You", prompt, "#ff5555")

        self._show_thinking()
        self.eyes.start_breathing()

        def worker():
            agent_display = getattr(self.session, "agent_name", "Kylo")
            try:
                routing_info = route_memory(prompt, session=self.session, is_user=True)
                self.eyes.trigger_working()

                controller = getattr(self.session_manager, "controller_instance", None) if self.session_manager else None
                if controller and hasattr(controller, "brain") and controller.brain:
                    reply = controller.brain.infer(prompt, self.session)
                else:
                    reply = overmind(prompt, self.session)
            except Exception as e:
                reply = f"(Error talking to {agent_display}: {e})"

            self.root.after(0, lambda: self._deliver_reply(reply))

        threading.Thread(target=worker, daemon=True).start()

    def open_emoji_picker(self):
        if self.emoji_picker is not None and self.emoji_picker.winfo_exists():
            self.emoji_picker.destroy()
            self.emoji_picker = None
            return

        picker = tk.Toplevel(self.root)
        self.emoji_picker = picker
        picker.title("Emoji Palette")
        picker.geometry("360x320")
        picker.resizable(False, True)

        skin = SKINS.get(load_skin(), {})
        bg = skin.get("bg", "#222222")
        btn_bg = skin.get("button_bg", "#333333")
        btn_fg = skin.get("button_fg", "#ffffff")
        accent_color = skin.get("accent", "#007acc")

        picker.configure(bg=bg)

        container = tk.Frame(picker, bg=bg)
        container.pack(fill="both", expand=True, padx=6, pady=6)

        canvas = tk.Canvas(container, bg=bg, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)

        scrollable_frame = tk.Frame(canvas, bg=bg)

        def _on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        scrollable_frame.bind("<Configure>", _on_frame_configure)
        canvas_frame_id = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        def _on_canvas_configure(event):
            canvas.itemconfig(canvas_frame_id, width=event.width)

        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)

        def _on_mousewheel(event):
            try:
                if canvas and canvas.winfo_exists():
                    canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except Exception:
                pass

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _on_close():
            try:
                canvas.unbind_all("<MouseWheel>")
            except Exception:
                pass
            picker.destroy()
            self.emoji_picker = None

        picker.protocol("WM_DELETE_WINDOW", _on_close)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        emojis = [
            "😀", "😃", "😄", "😁", "😆", "😅", "😂", "🤣", "🥺", "😊",
            "😇", "🙂", "🙃", "😉", "😌", "😍", "🥰", "😘", "😗", "😙",
            "😚", "😋", "😛", "😝", "😜", "🤪", "🤨", "🧐", "🤓", "😎",
            "🥸", "🤩", "🥳", "😏", "😒", "😞", "😔", "😟", "😕", "🙁",
            "😣", "😖", "😫", "😩", "🥺", "😢", "😭", "😮‍💨", "😤", "😠",
            "😡", "🤬", "🤯", "😳", "🥵", "🥶", "😱", "😨", "😰", "😥",
            "😓", "🤗", "🤔", "🫣", "🤭", "🫡", "🤫", "🫠", "🤥", "😶",
            "😐", "😑", "😬", "🙄", "😯", "😦", "😮", "😲", "🥱", "😴",
            "🤤", "😪", "😵", "🤐", "🥴", "🤢", "🤮", "🤧", "😷", "🤒",
            "🤑", "🤠", "😈", "👿", "👹", "👺", "💀", "👻", "👽", "🤖",
            "👋", "🤚", "🖐️", "✋", "🖖", "👌", "🤌", "🤏", "✌️", "🤞",
            "🤟", "🤘", "🤙", "👈", "👉", "👆", "🖕", "👇", "☝️", "👍",
            "👎", "✊", "👊", "🤛", "🤜", "👏", "🙌", "👐", "🤲", "🤝",
            "🙏", "✍️", "💅", "💪", "🧠", "👀", "👁️", "👄",
            "🔥", "✨", "🌟", "💫", "💥", "💯", "❤️", "🧡", "💛", "💚",
            "💙", "💜", "🖤", "🤍", "🤎", "💔", "❣️", "💕", "💞", "💓",
            "💗", "💖", "💘", "💝", "🎉", "🎊", "🚀", "🏴‍☠️", "☕", "🍺"
        ]

        cols = 6
        for i, emoji in enumerate(emojis):
            r = i // cols
            c = i % cols
            btn = tk.Button(
                scrollable_frame,
                text=emoji,
                font=("Segoe UI Emoji", 15),
                bg=btn_bg,
                fg=btn_fg,
                activebackground=accent_color,
                activeforeground="#ffffff",
                relief="flat",
                bd=0,
                padx=4,
                pady=4,
                command=lambda e=emoji: self._insert_emoji(e),
            )
            btn.grid(row=r, column=c, padx=3, pady=3, sticky="nsew")

        for c in range(cols):
            scrollable_frame.columnconfigure(c, weight=1)

    def _insert_emoji(self, emoji):
        self.entry.insert(tk.END, emoji)

    def sync_to_controller(self):
        if not self.session_manager or not getattr(self.session_manager, "controller_instance", None):
            return

        controller = self.session_manager.controller_instance

        try:
            skin = load_skin()
            if hasattr(controller, "_refresh_theme_from_skin"):
                controller._refresh_theme_from_skin(skin)

            apply_skin(controller, skin)
            
            if getattr(controller, "active_arena_instance", None):
                arena = controller.active_arena_instance
                if arena.get("dialog") and arena["dialog"].winfo_exists():
                    arena["refresh_func"](skin)
                    
            controller.root.update_idletasks()
        except Exception as e:
            print(f"[Skin Sync Error]: {e}")

        try:
            controller.entry.config(
                fg=self.entry.cget("fg"),
                insertbackground=self.entry.cget("fg"),
                font=self.entry.cget("font"),
            )
        except Exception:
            pass

    def _load_initial_session(self):
        agent_display = getattr(self.session, "agent_name", "Kylo")
        messages = getattr(self.session, "messages", [])

        safe_messages = []
        has_dialogue = False

        for m in messages:
            try:
                role = m.get("role", "system")
                text = m.get("text", "")
                if not isinstance(text, str):
                    text = str(text)
                
                if role in ("user", "roxie", "assistant", "Kylo", agent_display):
                    has_dialogue = True
                    
                safe_messages.append((role, text))
            except Exception:
                continue

        if has_dialogue:
            for role, text in safe_messages:
                if role == "user":
                    self._append_text("You", text, "#ff5555")
                elif role in ("roxie", "assistant", "Kylo", agent_display):
                    self._append_text(agent_display, text, "#b300ff")
                else:
                    self._append_local_system_notice(text)
            return

        for role, text in safe_messages:
            if role == "system":
                self._append_local_system_notice(text)

        self._show_thinking()
        self.eyes.start_breathing()

        def greeting_worker():
            try:
                greeting_prompt = (
                    f"Initiate this interaction with a brief, punchy in-character greeting (1-2 sentences). "
                    f"Speak strictly in your natural cadence, vocabulary, and disposition as {agent_display}. "
                    f"Do not mention system rules or prompt instructions."
                )

                controller = getattr(self.session_manager, "controller_instance", None) if self.session_manager else None
                if controller and hasattr(controller, "brain") and controller.brain:
                    reply = controller.brain.infer(greeting_prompt, self.session)
                else:
                    reply = overmind(greeting_prompt, self.session)

            except Exception as e:
                reply = f"({agent_display} stirs quietly into awareness.)"

            self.root.after(0, lambda: self._deliver_reply(reply))

        threading.Thread(target=greeting_worker, daemon=True).start()


def run_daemon(session=None, session_manager=None):
    if session is None:
        session = _MiniSession()

    root = tk.Tk()

    # --- Standalone Process Icon Hook ---
    icon_png_path = os.path.join(BASE_DIR, "splash_logo.png")
    icon_ico_path = os.path.join(BASE_DIR, "icon.ico")

    if os.path.exists(icon_ico_path):
        try:
            root.iconbitmap(icon_ico_path)
        except Exception:
            pass

    if os.path.exists(icon_png_path) and PIL_AVAILABLE:
        try:
            img = Image.open(icon_png_path)
            photo_icon = ImageTk.PhotoImage(img)
            root.iconphoto(True, photo_icon)
            root._icon_ref = photo_icon
        except Exception:
            pass

    app = DunoonDaemonApp(root, session, session_manager=session_manager)
    root.mainloop()


if __name__ == "__main__":
    try:
        repair_vaults()
        check_memory_integrity()
    except Exception as e:
        print(f"(Vault repair/integrity check failed, chief: {e})")

    try:
        run_daemon()
    except Exception as e:
        print(f"Dunoon Daemon encountered an error: {e}")