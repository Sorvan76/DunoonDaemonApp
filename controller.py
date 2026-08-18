# controller.py — Dunoon Daemon Central Controller (Precision UI, Arena Engine & Isolated Session Management)
import os
import sys
import time
import requests
import threading
import math
import zipfile
import io
import shutil
import glob
import json
import random
import psutil
import subprocess
import tkinter as tk
import model_handler
from model_handler import create_model_handler, ModelHandler
from tkinter import ttk, filedialog, messagebox, simpledialog, colorchooser
import tkinter.font as tkfont
from datetime import datetime, timezone
from PIL import Image, ImageTk
from persona import roll_persona
from session_manager import SessionManager
from brain import Brain
from dunoon_daemon import (
    DunoonDaemonApp, 
    UniversalFileProcessor, 
    send_multimodal_message, 
    _extract_dual_channel_meta, 
    _normalize_text_spacing
)
from tts_handler import trickle_warmup_voices
from eye_engine import ExpressiveVectorEyePair
from skin_manager import (
    SKINS, apply_skin, load_skin, save_skin, style_dialog_window, get_sorted_skin_names,
    FONT_HEADER, FONT_BODY, FONT_CODE, PAD_X_MED, PAD_Y_SMALL
)
from config import (
    BASE_DIR, BIN_DIR, SESSIONS_DIR, DEFAULT_HOST, DEFAULT_PORT,
    get_session_vault_paths, ensure_dirs
)
from ETO import ETOEngine

ensure_dirs()

CUSTOM_CTX_FILE = os.path.join(BASE_DIR, "custom_context.json")
LAST_DIRS_FILE = os.path.join(BASE_DIR, "last_dirs.json")
STANDARD_CONTEXT_OPTIONS = [4096, 8192, 16384, 24576, 32768, 65536]


# ============================================================
# TOOLTIP HELPER CLASS
# ============================================================
class Tooltip:
    """Provides hover tooltips with a configurable delay."""
    def __init__(self, widget, text_getter, delay=1000):
        self.widget = widget
        self.text_getter = text_getter
        self.delay = delay
        self.tipwindow = None
        self.id = None
        self.x = self.y = 0
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


def load_saved_custom_context() -> int | None:
    try:
        if os.path.exists(CUSTOM_CTX_FILE):
            with open(CUSTOM_CTX_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                val = int(data.get("custom_n_ctx", 0))
                return val if val > 0 else None
    except Exception:
        pass
    return None


def save_saved_custom_context(n_ctx: int | None):
    try:
        if n_ctx and n_ctx > 0:
            with open(CUSTOM_CTX_FILE, "w", encoding="utf-8") as f:
                json.dump({"custom_n_ctx": int(n_ctx)}, f, indent=2)
        elif os.path.exists(CUSTOM_CTX_FILE):
            os.remove(CUSTOM_CTX_FILE)
    except Exception:
        pass


def load_last_model_dir() -> str:
    try:
        if os.path.exists(LAST_DIRS_FILE):
            with open(LAST_DIRS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                d = data.get("last_model_dir")
                if d and os.path.exists(d):
                    return d
    except Exception:
        pass
    return os.path.expanduser("~")


def save_last_model_dir(dir_path: str):
    try:
        data = {}
        if os.path.exists(LAST_DIRS_FILE):
            with open(LAST_DIRS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        data["last_model_dir"] = dir_path
        with open(LAST_DIRS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def calculate_recommended_n_ctx(model_path: str, vram_gb: int = 24) -> int:
    if not model_path or not os.path.exists(model_path):
        return 16384

    file_size_gb = os.path.getsize(model_path) / (1024 ** 3)
    free_vram_gb = max(1.0, vram_gb - file_size_gb - 2.0)

    if file_size_gb > 18:
        max_safe_ctx = int((free_vram_gb / 0.6) * 1024)
    elif file_size_gb > 10:
        max_safe_ctx = int((free_vram_gb / 0.4) * 1024)
    else:
        max_safe_ctx = int((free_vram_gb / 0.2) * 1024)

    if max_safe_ctx >= 65536: return 65536
    if max_safe_ctx >= 32768: return 32768
    if max_safe_ctx >= 24576: return 24576
    if max_safe_ctx >= 16384: return 16384
    if max_safe_ctx >= 8192:  return 8192
    return 4096


class LoadingSplashScreen:
    def __init__(self, root, title="DUNOON DAEMON", status="Initializing core modules..."):
        self.root = root
        self.top = tk.Toplevel(root)
        self.top.title(title)
        self.top.geometry("480x360")
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)

        self.top.update_idletasks()
        ws = self.top.winfo_screenwidth()
        hs = self.top.winfo_screenheight()
        x = (ws / 2) - (480 / 2)
        y = (hs / 2) - (360 / 2)
        self.top.geometry(f"480x360+{int(x)}+{int(y)}")
        self.top.deiconify()
        self.top.lift()

        self.phase = 0.0
        self.is_running = True

        self.frame = tk.Frame(self.top, bg="#111111", padx=20, pady=15)
        self.frame.pack(fill=tk.BOTH, expand=True)

        self.logo_img = None
        self.logo_lbl = None
        logo_path = os.path.join(BASE_DIR, "splash_logo.png")
        if os.path.exists(logo_path):
            try:
                pil_img = Image.open(logo_path).convert("RGBA")
                pil_img.thumbnail((128, 128), Image.Resampling.LANCZOS)
                self.logo_img = ImageTk.PhotoImage(pil_img)
                self.logo_lbl = tk.Label(self.frame, image=self.logo_img, bg="#111111")
                self.logo_lbl.pack(pady=(5, 5))
            except Exception as e:
                print(f"[Splash Logo Warning]: {e}")

        self.title_lbl = tk.Label(
            self.frame,
            text=title,
            fg="#00eaff",
            bg="#111111",
            font=("Segoe UI Emoji", 13, "bold")
        )
        self.title_lbl.pack(pady=(0, 4))

        self.status_lbl = tk.Label(
            self.frame,
            text=status,
            fg="#ffffff",
            bg="#111111",
            font=("Segoe UI Emoji", 9)
        )
        self.status_lbl.pack(pady=(4, 10))

        self.progress = ttk.Progressbar(self.frame, mode="indeterminate", length=380)
        self.progress.pack(pady=5)
        self.progress.start(12)

        self._animate_background()

    def update_status(self, text: str):
        def _safe_update():
            try:
                if self.is_running and self.top.winfo_exists():
                    self.status_lbl.config(text=text)
                    self.top.update_idletasks()
            except Exception:
                pass
                
        try:
            self.root.after(0, _safe_update)
        except Exception:
            pass

    def _animate_background(self):
        if not self.is_running:
            return

        self.phase += 0.05
        r = int(15 + math.sin(self.phase) * 10)
        g = int(15 + math.cos(self.phase) * 10)
        b = int(35 + math.sin(self.phase) * 15)
        hex_color = f"#{r:02x}{g:02x}{b:02x}"

        try:
            if self.top.winfo_exists():
                self.frame.config(bg=hex_color)
                self.title_lbl.config(bg=hex_color)
                self.status_lbl.config(bg=hex_color)
                if self.logo_lbl:
                    self.logo_lbl.config(bg=hex_color)
                self.top.after(50, self._animate_background)
        except Exception:
            pass

    def close(self):
        self.is_running = False
        try:
            if self.top.winfo_exists():
                self.top.destroy()
        except Exception:
            pass


class ControllerApp:
    def __init__(self, root, splash=None):
        self.root = root
        self.splash = splash

        self.root.title("Dunoon Daemon — Central Controller")
        self.root.geometry("1020x580")
        self.root.withdraw()

        self.current_backend = tk.StringVar(value="LM Studio (Local API)")
        self.selected_model_path = tk.StringVar(value="⚠️ Action Required: Load a GGUF model or connect to LM Studio.")
        self.actual_model_path = ""
        self.active_chat_apps = {}
        self.arena_active_sessions = set()
        self.active_arena_instance = None

        self.custom_ctx_enabled = tk.BooleanVar(value=False)
        self.custom_ctx_value = load_saved_custom_context()

        initial_ctx = self.custom_ctx_value if self.custom_ctx_value else 16384
        if self.custom_ctx_value:
            self.custom_ctx_enabled.set(True)

        self.context_size_var = tk.IntVar(value=initial_ctx)
        self.context_menu = None
        self.chk_custom_ctx = None
        self.gpu_name = "CUDA/Vulkan"
        self.right_panel_buttons = []
        self.tooltips = []
        self.tooltips_enabled = tk.BooleanVar(value=True)

        self.is_flashing_persona = False
        self.persona_flash_job = None
        self.persona_flash_phase = 0
        self.btn_edit_persona = None

        def on_app_exit():
            try:
                if hasattr(self.brain, "model_handler") and self.brain.model_handler:
                    self.brain.model_handler.unload_model()
            except Exception:
                pass
            self.root.destroy()
            sys.exit(0)

        self.root.protocol("WM_DELETE_WINDOW", on_app_exit)

        self._boot_sequence()

    def _center_on_parent(self, window, width, height):
        self.root.update_idletasks()
        rx = self.root.winfo_x()
        ry = self.root.winfo_y()
        rw = self.root.winfo_width()
        rh = self.root.winfo_height()

        x = rx + max(0, int((rw - width) / 2))
        y = ry + max(0, int((rh - height) / 2))
        window.geometry(f"{width}x{height}+{x}+{y}")

    def _get_gpu_name(self):
        try:
            cmd = ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"]
            creationflags = 0x08000000 if os.name == "nt" else 0
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                text=True
            )
            stdout, _ = proc.communicate(timeout=3)
            lines = [line.strip() for line in stdout.split('\n') if line.strip()]
            if lines:
                return lines[0]
        except Exception:
            pass
        return "NVIDIA / Vulkan"

    def _download_native_engine(self):
        candidate_paths = [
            os.path.join(BIN_DIR, "llama-server.exe"),
            os.path.join(BASE_DIR, "bin", "llama-server.exe"),
        ]

        for path in candidate_paths:
            if os.path.exists(path):
                print(f"[Native Engine]: Found existing binary at -> {path}. Running offline!")
                if self.splash:
                    self.splash.update_status("Found offline C++ engine. Starting...")
                return

        if self.splash:
            self.splash.update_status("Detecting hardware architecture...")
        
        time.sleep(0.3)
        os.makedirs(BIN_DIR, exist_ok=True)
        has_nvidia = "NVIDIA" in self.gpu_name.upper()

        if self.splash:
            self.splash.update_status("Querying GitHub for latest native binaries...")

        url = None
        try:
            api_url = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
            headers = {"User-Agent": "DunoonDaemonApp"}
            resp = requests.get(api_url, headers=headers, timeout=5)
            
            if resp.status_code == 200:
                data = resp.json()
                target_pattern = "bin-win-cuda" if has_nvidia else "bin-win-vulkan"
                
                for asset in data.get("assets", []):
                    asset_name = asset.get("name", "").lower()
                    if asset_name.startswith("cudart-"):
                        continue
                    if target_pattern in asset_name and asset_name.endswith(".zip") and "x64" in asset_name:
                        url = asset.get("browser_download_url")
                        break
        except Exception as e:
            print(f"[GitHub API Warning]: {e}")

        if not url:
            if has_nvidia:
                url = "https://github.com/ggml-org/llama.cpp/releases/download/b10425/llama-b10425-bin-win-cuda-cu12.4-x64.zip"
            else:
                url = "https://github.com/ggml-org/llama.cpp/releases/download/b10425/llama-b10425-bin-win-vulkan-x64.zip"

        try:
            if self.splash:
                self.splash.update_status(f"Downloading official {'CUDA' if has_nvidia else 'Vulkan'} C++ engine...")

            response = requests.get(url, stream=True, timeout=120)
            response.raise_for_status()

            with zipfile.ZipFile(io.BytesIO(response.content)) as zip_ref:
                for member in zip_ref.namelist():
                    filename = os.path.basename(member)
                    if not filename:
                        continue
                    source = zip_ref.open(member)
                    target = open(os.path.join(BIN_DIR, filename), "wb")
                    with source, target:
                        shutil.copyfileobj(source, target)
                            
            if self.splash:
                self.splash.update_status("Engine & CUDA libraries successfully installed!")
            time.sleep(0.5)

        except Exception as e:
            print(f"[Engine Download Failed]: {e}")
            if self.splash:
                self.splash.update_status("Offline mode / Fallback active.")
            time.sleep(1.0)

    def _boot_sequence(self):
        def task():
            if self.splash:
                self.splash.update_status("Detecting hardware architecture...")
            self.gpu_name = self._get_gpu_name()
            time.sleep(0.35)

            if self.splash:
                self.splash.update_status("Initializing Session Manager & Brain...")
            self.sm = SessionManager()
            self.brain = Brain()
            self.sm.controller_instance = self
            time.sleep(0.35)

            if self.splash:
                self.splash.update_status("Warming up voice pipeline...")
            trickle_warmup_voices()
            time.sleep(0.4)

            self.root.after(0, self._finish_boot)

            def run_async_vault_maintenance():
                try:
                    from vault_auto_repair import repair_vaults
                    from memory_integrity import check_memory_integrity
                    repair_vaults()
                    check_memory_integrity()
                except Exception as e:
                    print(f"[Boot Warning]: Vault check error: {e}")

            threading.Thread(target=run_async_vault_maintenance, daemon=True).start()

        threading.Thread(target=task, daemon=True).start()

    def _finish_boot(self):
        self._build_ui()
        self._refresh_sessions()
        self._refresh_theme_from_skin(load_skin())
        self._test_lmstudio_connection(silent=True)

        if self.splash:
            self.splash.close()

        self.root.deiconify()

        ico_path = os.path.join(BASE_DIR, "icon.ico")
        if os.path.exists(ico_path):
            try:
                self.root.iconbitmap(ico_path)
            except Exception:
                pass

    def _register_tooltip(self, widget, text):
        tip = Tooltip(widget, text, delay=1000)
        try:
            tip.enabled = bool(self.tooltips_enabled.get())
        except Exception:
            tip.enabled = True
        self.tooltips.append(tip)
        return tip

    def _toggle_tooltips(self):
        state = self.tooltips_enabled.get()
        for tip in self.tooltips:
            tip.enabled = state

    def _start_persona_flash(self):
        if self.is_flashing_persona or not self.btn_edit_persona:
            return
        self.is_flashing_persona = True
        self.persona_flash_phase = 0
        self._pulse_persona_loop()

    def _stop_persona_flash(self):
        if not self.is_flashing_persona:
            return
        self.is_flashing_persona = False
        if self.persona_flash_job:
            try:
                self.root.after_cancel(self.persona_flash_job)
            except Exception:
                pass
            self.persona_flash_job = None

        skin = SKINS.get(load_skin(), {})
        btn_bg = skin.get("button_bg", "#333333")
        btn_fg = skin.get("button_fg", "#ffffff")
        if self.btn_edit_persona:
            try:
                self.btn_edit_persona.config(bg=btn_bg, fg=btn_fg)
            except Exception:
                pass

    def _pulse_persona_loop(self):
        if not self.is_flashing_persona or not self.btn_edit_persona:
            return

        skin = SKINS.get(load_skin(), {})
        accent_col = skin.get("accent", "#00eaff")
        btn_bg = skin.get("button_bg", "#333333")
        btn_fg = skin.get("button_fg", "#ffffff")

        if self.persona_flash_phase % 2 == 0:
            self.btn_edit_persona.config(bg=accent_col, fg="#ffffff")
        else:
            self.btn_edit_persona.config(bg=btn_bg, fg=btn_fg)

        self.persona_flash_phase += 1
        self.persona_flash_job = self.root.after(450, self._pulse_persona_loop)

    def _refresh_theme_from_skin(self, skin_name: str):
        base = SKINS.get(skin_name, SKINS["Dark"])
        bg_color = base.get("button_bg", base.get("bg", "#333333"))
        fg_color = base.get("button_fg", base.get("fg", "#ffffff"))
        accent_color = base.get("accent", "#007acc")
        window_bg = base.get("bg", "#111111")
        entry_bg = base.get("entry_bg", "#1e1e1e")
        entry_fg = base.get("entry_fg", "#ffffff")

        try:
            self.root.configure(bg=window_bg)
        except Exception:
            pass

        try:
            style = ttk.Style()
            style.theme_use("clam")
            style.configure(
                "TCombobox",
                fieldbackground=entry_bg,
                background=bg_color,
                foreground=entry_fg,
                selectbackground=accent_color,
                selectforeground="#ffffff",
                darkcolor=bg_color,
                lightcolor=bg_color,
                bordercolor=accent_color
            )
            style.map(
                "TCombobox",
                fieldbackground=[("readonly", entry_bg)],
                foreground=[("readonly", entry_fg)],
                selectbackground=[("readonly", accent_color)],
                selectforeground=[("readonly", "#ffffff")]
            )
        except Exception as e:
            print(f"[Combobox Style Error]: {e}")

        for btn in self.right_panel_buttons:
            try:
                btn.configure(
                    bg=bg_color,
                    fg=fg_color,
                    activebackground=accent_color,
                    activeforeground="#ffffff",
                    relief="flat",
                    bd=0
                )
            except Exception as e:
                print(f"[Controller Button Skin Error]: {e}")

    def _get_context_options(self) -> list[int]:
        opts = list(STANDARD_CONTEXT_OPTIONS)
        if self.custom_ctx_value and self.custom_ctx_value > 0:
            if self.custom_ctx_value in opts:
                opts.remove(self.custom_ctx_value)
            opts.insert(0, self.custom_ctx_value)
        return opts

    def _toggle_custom_context(self):
        if self.custom_ctx_enabled.get():
            initial = str(self.custom_ctx_value or self.context_size_var.get() or 32768)
            val = simpledialog.askinteger(
                "Custom Context Window",
                "Enter target context size in tokens (e.g. 49152, 65536, 131072):",
                parent=self.root,
                initialvalue=int(initial),
                minvalue=1024,
                maxvalue=524288
            )

            if val and val > 0:
                self.custom_ctx_value = int(val)
                save_saved_custom_context(self.custom_ctx_value)
                self.context_size_var.set(self.custom_ctx_value)
            else:
                if not self.custom_ctx_value:
                    self.custom_ctx_enabled.set(False)
        else:
            self.custom_ctx_value = None
            save_saved_custom_context(None)
            if self.context_size_var.get() not in STANDARD_CONTEXT_OPTIONS:
                self.context_size_var.set(16384)

        if self.context_menu:
            opts = self._get_context_options()
            self.context_menu.config(values=opts)

    def _build_ui(self):
        top_bar = tk.Frame(self.root, bg="#1e1e1e", padx=10, pady=10)
        top_bar.pack(side=tk.TOP, fill=tk.X)

        tk.Label(
            top_bar,
            text="Engine:",
            fg="#ffffff",
            bg="#1e1e1e",
            font=("Segoe UI Emoji", 10)
        ).pack(side=tk.LEFT, padx=(0, 6))

        backend_options = [
            "LM Studio (Local API)",
            f"Native C++ Server ({self.gpu_name})",
        ]

        self.backend_menu = ttk.Combobox(
            top_bar,
            textvariable=self.current_backend,
            values=backend_options,
            state="readonly",
            width=24
        )
        self.backend_menu.pack(side=tk.LEFT, padx=(0, 10))
        self.backend_menu.bind("<<ComboboxSelected>>", self._on_backend_change)
        self._register_tooltip(self.backend_menu, "Select Local API (LM Studio) or Native GPU acceleration.")

        load_model_btn = tk.Button(
            top_bar,
            text="📂 Load GGUF Model",
            bg="#007acc",
            fg="#ffffff",
            font=("Segoe UI Emoji", 9),
            relief="flat",
            bd=0,
            padx=10,
            pady=4,
            cursor="hand2",
            command=self._trigger_file_dialog
        )
        load_model_btn.pack(side=tk.LEFT, padx=(0, 2))
        self.right_panel_buttons.append(load_model_btn)
        self._register_tooltip(load_model_btn, "Load a local GGUF model file into VRAM.")

        eject_main_btn = tk.Button(
            top_bar,
            text="⏏️",
            bg="#333333",
            fg="#ff5555",
            font=("Segoe UI Emoji", 9),
            relief="flat",
            bd=0,
            padx=6,
            pady=4,
            cursor="hand2",
            command=self.eject_main_model
        )
        eject_main_btn.pack(side=tk.LEFT, padx=(0, 10))
        self.right_panel_buttons.append(eject_main_btn)
        self._register_tooltip(eject_main_btn, "Eject current GGUF model and clear VRAM.")

        tk.Label(
            top_bar,
            text="Context:",
            fg="#ffffff",
            bg="#1e1e1e",
            font=("Segoe UI Emoji", 9)
        ).pack(side=tk.LEFT, padx=(0, 4))

        context_options = self._get_context_options()
        self.context_menu = ttk.Combobox(
            top_bar,
            textvariable=self.context_size_var,
            values=context_options,
            state="readonly",
            width=9
        )
        self.context_menu.pack(side=tk.LEFT, padx=(0, 4))
        self._register_tooltip(self.context_menu, "Set token context window size for inference.")

        self.chk_custom_ctx = tk.Checkbutton(
            top_bar,
            text="Custom",
            variable=self.custom_ctx_enabled,
            command=self._toggle_custom_context,
            bg="#1e1e1e",
            fg="#00eaff",
            selectcolor="#111111",
            activebackground="#1e1e1e",
            activeforeground="#00eaff",
            font=("Segoe UI Emoji", 9),
            bd=0
        )
        self.chk_custom_ctx.pack(side=tk.LEFT, padx=(0, 10))
        self._register_tooltip(self.chk_custom_ctx, "Specify an arbitrary custom context size (in tokens).")

        chk_help = tk.Checkbutton(
            top_bar,
            text="❓ Help",
            variable=self.tooltips_enabled,
            command=self._toggle_tooltips,
            bg="#1e1e1e",
            fg="#ffcc00",
            selectcolor="#111111",
            activebackground="#1e1e1e",
            activeforeground="#ffcc00",
            font=("Segoe UI Emoji", 9),
            bd=0
        )
        chk_help.pack(side=tk.LEFT, padx=(0, 10))
        self._register_tooltip(chk_help, "Enable/disable 1-second hover help tooltips.")

        connect_btn = tk.Button(
            top_bar,
            text="🖥️ Specs & Telemetry",
            bg="#333333",
            fg="#00ff55",
            font=("Segoe UI Emoji", 9),
            relief="flat",
            bd=0,
            padx=10,
            pady=4,
            command=self._show_hardware_diagnostics
        )
        connect_btn.pack(side=tk.RIGHT, padx=5)
        self._register_tooltip(connect_btn, "Inspect live CPU, GPU, RAM, and VRAM system telemetry.")

        status_bar = tk.Frame(self.root, bg="#161616", padx=12, pady=6)
        status_bar.pack(side=tk.TOP, fill=tk.X)

        tk.Label(
            status_bar,
            text="Status:",
            fg="#888888",
            bg="#161616",
            font=("Segoe UI Emoji", 9)
        ).pack(side=tk.LEFT, padx=(0, 6))

        self.model_status_label = tk.Label(
            status_bar,
            textvariable=self.selected_model_path,
            fg="#ffcc00",
            bg="#161616",
            font=("Segoe UI Emoji", 9)
        )
        self.model_status_label.pack(side=tk.LEFT, padx=5)

        workspace = tk.Frame(self.root, bg="#111111", padx=10, pady=10)
        workspace.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        session_frame = tk.LabelFrame(
            workspace, 
            text=" Chat Sessions ", 
            fg="#ffffff", 
            bg="#111111", 
            font=("Segoe UI Emoji", 10)
        )
        session_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        self.tree = ttk.Treeview(session_frame, columns=("ID", "Backend", "Created"), show="headings")
        self.tree.heading("ID", text="Session Name")
        self.tree.heading("Backend", text="Hardware / Model")
        self.tree.heading("Created", text="Created At")
        self.tree.column("ID", width=200)
        self.tree.column("Backend", width=180)
        self.tree.column("Created", width=120)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tree_scroll = ttk.Scrollbar(session_frame, orient="vertical", command=self.tree.yview)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.bind("<Double-1>", lambda e: self.open_chat())
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        control_frame = tk.Frame(workspace, bg="#111111", padx=10)
        control_frame.pack(side=tk.RIGHT, fill=tk.Y)

        def make_action_button(parent, text, command, tip_text=""):
            btn = tk.Button(
                parent,
                text=text,
                command=command,
                bg="#333333",
                fg="#ffffff",
                font=("Segoe UI Emoji", 9),
                relief="flat",
                bd=0,
                width=18,
                pady=6,
                activebackground="#444444",
                activeforeground="#ffffff"
            )
            btn.pack(side=tk.TOP, pady=6)
            self.right_panel_buttons.append(btn)
            if tip_text:
                self._register_tooltip(btn, tip_text)
            return btn

        btn_new = make_action_button(control_frame, "➕ New Chat", self.create_new_session, "Initialize a new autonomous companion session.")
        btn_open = make_action_button(control_frame, "💬 Open Chat", self.open_chat, "Launch active dialogue with the selected persona.")
        self.btn_edit_persona = make_action_button(control_frame, "🎭 Edit Persona", self.edit_system_prompt, "Configure custom directives, name, and persona settings.")
        btn_ren = make_action_button(control_frame, "✏️ Rename", self.rename_session, "Rename the selected session.")
        btn_del = make_action_button(control_frame, "🗑️ Delete Chat", self.delete_session, "Permanently delete session history and isolated memory vaults.")

        spacer = tk.Frame(control_frame, bg="#111111", height=10)
        spacer.pack(side=tk.TOP)

        btn_arena = make_action_button(control_frame, "⚔️ Dual Arena", self.open_dual_arena, "Launch the multi-agent live debate deck.")

        spacer2 = tk.Frame(control_frame, bg="#111111", height=10)
        spacer2.pack(side=tk.TOP)

        btn_purge = make_action_button(
            control_frame, 
            "⚠️ Master Purge", 
            self.execute_master_purge,
            "Reset and wipe all session vaults and memory databases across all personas."
        )

    def _show_hardware_diagnostics(self):
        cpu_count_phys = psutil.cpu_count(logical=False)
        cpu_count_log = psutil.cpu_count(logical=True)
        ram = psutil.virtual_memory()
        ram_total_gb = ram.total / (1024 ** 3)
        ram_used_gb = ram.used / (1024 ** 3)
        ram_pct = ram.percent

        vram_info = "Detection via CIM"
        try:
            cmd = 'powershell -NoProfile -Command "Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM"'
            raw = os.popen(cmd).read().strip()
            vram_info = raw if raw else self.gpu_name
        except Exception:
            pass

        diag_msg = (
            f"=== 🖥️ HARDWARE TELEMETRY REPORT ===\n\n"
            f"• CPU Architecture : {psutil.cpu_freq().max:.0f}MHz ({cpu_count_phys} P/E Cores | {cpu_count_log} Threads)\n"
            f"• System RAM       : {ram_used_gb:.1f} GB / {ram_total_gb:.1f} GB ({ram_pct}% Utilized)\n"
            f"• Primary GPU      : {self.gpu_name}\n"
            f"• Native Binaries  : {'Available in bin/' if os.path.exists(os.path.join(BIN_DIR, 'llama-server.exe')) else 'Not Installed'}\n"
            f"• Active Backend   : {self.current_backend.get()}\n"
            f"• Target Context   : {self.context_size_var.get()} Tokens\n\n"
            f"Detailed Adapter Telemetry:\n{vram_info}"
        )
        messagebox.showinfo("Hardware Diagnostics", diag_msg)

    def open_dual_arena(self):
        """Launches the Dual Agent Arena with fitted palette, Event injections, continue attention pulse, and speaker-locked resume."""
        sessions = self.sm.list_sessions()
        if len(sessions) < 2:
            messagebox.showinfo("Dual Arena", "You need at least 2 chat sessions created to launch the Arena, chief!")
            return

        for session_id, app_instance in list(self.active_chat_apps.items()):
            try:
                if hasattr(app_instance, "root") and app_instance.root.winfo_exists():
                    app_instance.root.destroy()
            except Exception as e:
                print(f"[Arena Launch Auto-Close Error]: {e}")
        self.active_chat_apps.clear()

        active_model = getattr(self, "actual_model_path", "")
        target_n_ctx = self.context_size_var.get()
        if active_model and os.path.exists(active_model):
            handler = getattr(self.brain, "model_handler", None)
            if not (handler and handler.is_active()):
                try:
                    from model_handler import create_model_handler
                    handler = create_model_handler(active_model, n_ctx=target_n_ctx)
                    handler.load_model()
                    self.brain.model_handler = handler
                except Exception as e:
                    print(f"[Arena Native Spool Error]: {e}")

        dialog = tk.Toplevel(self.root)
        dialog.title("Dual Agent Arena — Live Debate Deck")
        dialog.geometry("920x720")
        self._center_on_parent(dialog, 920, 720)

        current_skin_name = load_skin() if callable(globals().get("load_skin")) else "Dark"
        init_skin = SKINS.get(current_skin_name, SKINS.get("Dark", {}))
        
        app_font_fam = getattr(self, "font_family_var", None)
        app_font_fam = app_font_fam.get() if app_font_fam else init_skin.get("font_family", "Segoe UI")
        app_font_sz = getattr(self, "font_size_var", None)
        app_font_sz = int(app_font_sz.get()) if app_font_sz else int(init_skin.get("font_size", 11))

        current_font_family = [app_font_fam]
        current_font_size = [app_font_sz]

        arena_sessions_tuple = [sessions[0], sessions[1]]
        self.arena_active_sessions.add(sessions[0].id)
        self.arena_active_sessions.add(sessions[1].id)

        is_auto_running = [False]
        auto_loop_job = [None]
        is_closed = [False]
        is_typewriting = [False]
        cancel_typewriter = [False]
        is_generating = [False]
        is_flashing_continue = [False]
        continue_flash_job = [None]
        continue_flash_phase = [0]
        active_turn = [0]
        last_exchange = ["Let the debate commence."]
        staged_upload = [None]
        thinking_job = [None]
        emoji_picker = [None]

        empty_stall_count = {sessions[0].id: 0, sessions[1].id: 0}

        top_bar = tk.Frame(dialog, padx=8, pady=6)
        top_bar.pack(side=tk.TOP, fill=tk.X)

        header_frame = tk.Frame(dialog, padx=10, pady=6)
        header_frame.pack(side=tk.TOP, fill=tk.X)

        lbl_a1 = tk.Label(header_frame, text="Agent 1:")
        lbl_a1.pack(side=tk.LEFT, padx=4)
        sess_names = [f"{s.name} ({getattr(s, 'agent_name', 'Kylo')})" for s in sessions]
        
        c1 = ttk.Combobox(header_frame, values=sess_names, state="readonly", width=22, style="DarkArena.TCombobox")
        c1.current(0)
        c1.pack(side=tk.LEFT, padx=6)
        self._register_tooltip(c1, "Choose the first Arena persona.")

        lbl_vs = tk.Label(header_frame, text="VS")
        lbl_vs.pack(side=tk.LEFT, padx=8)

        lbl_a2 = tk.Label(header_frame, text="Agent 2:")
        lbl_a2.pack(side=tk.LEFT, padx=4)
        c2 = ttk.Combobox(header_frame, values=sess_names, state="readonly", width=22, style="DarkArena.TCombobox")
        c2.current(1 if len(sessions) > 1 else 0)
        c2.pack(side=tk.LEFT, padx=6)
        self._register_tooltip(c2, "Choose the second Arena persona.")

        def on_agent_select(event=None):
            self.arena_active_sessions.clear()
            s1 = sessions[c1.current()]
            s2 = sessions[c2.current()]
            arena_sessions_tuple[0] = s1
            arena_sessions_tuple[1] = s2
            self.arena_active_sessions.add(s1.id)
            self.arena_active_sessions.add(s2.id)

        c1.bind("<<ComboboxSelected>>", on_agent_select)
        c2.bind("<<ComboboxSelected>>", on_agent_select)

        thinking_label = tk.Label(top_bar, text="")
        thinking_label.pack(side=tk.LEFT, padx=8)

        def _show_thinking(agent_name, count=0):
            if is_closed[0]: return
            dots = "." * ((count % 3) + 1)
            thinking_label.configure(text=f"{agent_name} is formulating response{dots}")
            thinking_job[0] = dialog.after(500, lambda: _show_thinking(agent_name, count + 1))

        def _stop_thinking():
            if thinking_job[0] is not None:
                try: dialog.after_cancel(thinking_job[0])
                except Exception: pass
                thinking_job[0] = None
            thinking_label.configure(text="")

        canvas_frame = tk.Frame(dialog, padx=10, pady=6)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(canvas_frame, orient="vertical")
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        arena_canvas = tk.Text(
            canvas_frame,
            wrap="word",
            relief="flat",
            bd=0,
            yscrollcommand=scrollbar.set,
            padx=12,
            pady=12
        )
        arena_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._register_tooltip(arena_canvas, "Live Arena transcript: agent turns, interventions, and injected events.")
        scrollbar.config(command=arena_canvas.yview)

        input_deck = tk.Frame(dialog, padx=10, pady=10)
        input_deck.pack(side=tk.BOTTOM, fill=tk.X)

        for i in range(8):
            input_deck.columnconfigure(i, weight=1)

        entry_intervene = tk.Entry(
            input_deck,
            relief="flat",
            bd=0
        )
        entry_intervene.grid(row=0, column=0, columnspan=6, sticky="nsew", padx=6, pady=6)
        self._register_tooltip(entry_intervene, "Type a moderator intervention or scene instruction here.")

        def _stop_arena_continue_flash():
            if not is_flashing_continue[0]:
                return
            is_flashing_continue[0] = False
            if continue_flash_job[0]:
                try: dialog.after_cancel(continue_flash_job[0])
                except Exception: pass
                continue_flash_job[0] = None

            sk = SKINS.get(load_skin(), {})
            btn_continue.config(bg=sk.get("button_bg", "#333333"), fg=sk.get("button_fg", "#ffffff"))

        def _pulse_arena_continue():
            if not is_flashing_continue[0] or is_closed[0]:
                return
            sk = SKINS.get(load_skin(), {})
            accent_col = sk.get("accent", "#ff0055")
            btn_bg = sk.get("button_bg", "#333333")
            btn_fg = sk.get("button_fg", "#ffffff")

            if continue_flash_phase[0] % 2 == 0:
                btn_continue.config(bg=accent_col, fg="#ffffff")
            else:
                btn_continue.config(bg=btn_bg, fg=btn_fg)

            continue_flash_phase[0] += 1
            continue_flash_job[0] = dialog.after(450, _pulse_arena_continue)

        def _start_arena_continue_flash():
            if is_flashing_continue[0] or is_auto_running[0]:
                return
            is_flashing_continue[0] = True
            continue_flash_phase[0] = 0
            _pulse_arena_continue()

        def insert_emoji(e_char):
            entry_intervene.insert(tk.END, e_char)

        def open_arena_emoji():
            if emoji_picker[0] is not None and emoji_picker[0].winfo_exists():
                emoji_picker[0].destroy()
                emoji_picker[0] = None
                return

            em_top = tk.Toplevel(dialog)
            emoji_picker[0] = em_top
            em_top.title("Emoji Palette")
            em_top.geometry("380x320")
            em_top.resizable(False, True)

            sk = SKINS.get(load_skin(), {})
            bg = sk.get("bg", "#222222")
            btn_bg = sk.get("button_bg", "#333333")
            btn_fg = sk.get("button_fg", "#ffffff")
            accent_col = sk.get("accent", "#007acc")

            em_top.configure(bg=bg)

            container = tk.Frame(em_top, bg=bg)
            container.pack(fill="both", expand=True, padx=6, pady=6)

            canvas = tk.Canvas(container, bg=bg, highlightthickness=0, bd=0)
            scroller = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
            scroll_frame = tk.Frame(canvas, bg=bg)

            scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            c_win = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
            canvas.bind("<Configure>", lambda e: canvas.itemconfig(c_win, width=e.width))
            canvas.configure(yscrollcommand=scroller.set)

            canvas.pack(side="left", fill="both", expand=True)
            scroller.pack(side="right", fill="y")

            emojis = [
                "😀", "😃", "😄", "😁", "😆", "😅", "😂", "🤣", "🥺", "😊",
                "😇", "🙂", "🙃", "😉", "😌", "😍", "🥰", "😘", "😗", "😙",
                "😚", "😋", "😛", "😝", "😜", "🤪", "🤨", "🧐", "🤓", "😎",
                "🥸", "🤩", "🥳", "😏", "😒", "😞", "😔", "😟", "😕", "🙁",
                "😣", "😖", "😫", "😩", "🥺", "😢", "😭", "😮‍💨", "😤", "😠",
                "😡", "🤬", "🤯", "😳", "🥵", "🥶", "😱", "😨", "😰", "😥",
                "😓", "🤗", "🤔", "🫣", "🤭", "🫡", "🤫", "🫠", "🤥", "😶",
                "🔥", "✨", "🌟", "💫", "💥", "💯", "⚔️", "🍵", "🤖", "👀",
                "👏", "🧐", "💀", "🤣", "🤔", "👑", "🚀", "🍿", "☕", "🍺"
            ]

            cols = 6
            for idx, em in enumerate(emojis):
                r = idx // cols
                c = idx % cols
                tk.Button(
                    scroll_frame,
                    text=em,
                    font=(current_font_family[0], 14),
                    bg=btn_bg,
                    fg=btn_fg,
                    activebackground=accent_col,
                    activeforeground="#ffffff",
                    relief="flat",
                    bd=0,
                    padx=4,
                    pady=4,
                    command=lambda char=em: insert_emoji(char)
                ).grid(row=r, column=c, padx=3, pady=3, sticky="nsew")

            for c in range(cols):
                scroll_frame.columnconfigure(c, weight=1)

        btn_emoji = tk.Button(input_deck, text="😊", relief="flat", bd=0, padx=8, pady=4, command=open_arena_emoji)
        btn_emoji.grid(row=0, column=6, sticky="nsew", padx=4, pady=6)
        self._register_tooltip(btn_emoji, "Open the Arena emoji palette.")

        def _type_out_arena(header, body, tag_head, tag_body, idx=0):
            if is_closed[0]: return
            if idx == 0:
                is_typewriting[0] = True
                cancel_typewriter[0] = False
                if dialog.winfo_exists() and arena_canvas.winfo_exists():
                    arena_canvas.insert(tk.END, header, tag_head)
                    arena_canvas.see(tk.END)

            if cancel_typewriter[0]:
                rem = body[idx:]
                if dialog.winfo_exists() and arena_canvas.winfo_exists():
                    arena_canvas.insert(tk.END, f"{rem}\n\n", tag_body)
                    arena_canvas.see(tk.END)
                is_typewriting[0] = False
                if is_auto_running[0] and not is_closed[0]:
                    auto_loop_job[0] = dialog.after(2000, step_turn)
                return

            if idx < len(body):
                if dialog.winfo_exists() and arena_canvas.winfo_exists():
                    arena_canvas.insert(tk.END, body[idx], tag_body)
                    arena_canvas.see(tk.END)
                    arena_canvas.update()
                    dialog.after(12, lambda: _type_out_arena(header, body, tag_head, tag_body, idx + 1))
            else:
                if dialog.winfo_exists() and arena_canvas.winfo_exists():
                    arena_canvas.insert(tk.END, "\n\n")
                    arena_canvas.see(tk.END)
                is_typewriting[0] = False
                if is_auto_running[0] and not is_closed[0]:
                    auto_loop_job[0] = dialog.after(2000, step_turn)

        def step_turn(force_same_speaker=False):
            if is_closed[0] or is_typewriting[0] or is_generating[0]:
                return
            is_generating[0] = True
            _stop_arena_continue_flash()

            s1 = arena_sessions_tuple[0]
            s2 = arena_sessions_tuple[1]
            
            if force_same_speaker and active_turn[0] > 0:
                turn_idx = active_turn[0] - 1
            else:
                turn_idx = active_turn[0]

            speaker_sess = s1 if turn_idx % 2 == 0 else s2
            target_sess = s2 if turn_idx % 2 == 0 else s1

            speaker_name = getattr(speaker_sess, "agent_name", "Kylo")
            target_name = getattr(target_sess, "agent_name", "Companion")

            tag_head = "a1_head" if turn_idx % 2 == 0 else "a2_head"
            tag_body = "a1_body" if turn_idx % 2 == 0 else "a2_body"

            _show_thinking(speaker_name)

            base_prompt = last_exchange[0]
            if force_same_speaker:
                prompt = (
                    f"[SCENE DIRECTIVE: Continue your previous thought without repeating yourself. "
                    f"Address {target_name} directly by name as {speaker_name}.]"
                )
            else:
                prompt = (
                    f"[SCENE DIRECTIVE: You are in an active debate/scene with {target_name}. "
                    f"Address {target_name} directly by name, reacting in character to what they just said. Do not address the User/Moderator unless they directly intervene.]\n\n"
                    f"{target_name}: {base_prompt}"
                )

            def worker():
                try:
                    if hasattr(self, "brain") and self.brain:
                        reply = self.brain.infer(prompt, speaker_sess)
                    else:
                        from overmind import overmind
                        reply = overmind(prompt, speaker_sess)
                except Exception as e:
                    reply = f"({speaker_name} pauses in contemplation: {e})"

                if is_closed[0]:
                    is_generating[0] = False
                    return

                meta_data, clean = _extract_dual_channel_meta(str(reply))

                clean = clean.strip()
                if clean.endswith("--") or clean.endswith("-"): clean = clean.rstrip("-") + "..."
                if clean.count('"') % 2 != 0: clean += '"'
                if clean.count('*') % 2 != 0: clean += '*'

                # Permadeath comes from structured semantic telemetry, not phrase matching.
                fatal_this_turn = bool(meta_data.get("fatal", False))
                if getattr(speaker_sess, "mortality_enabled", False) and fatal_this_turn:
                    speaker_sess.is_deceased = True
                    self.sm._save()

                    if getattr(target_sess, "is_deceased", False):
                        last_exchange[0] = (
                            f"*{speaker_name} falls lifeless beside {target_name}.* "
                            f"[MUTUAL ANNIHILATION: Both combatants have perished. The arena falls silent.]"
                        )
                    else:
                        try:
                            from memory_deep import save_deep_memory_journal
                            save_deep_memory_journal(
                                f"[WITNESSED COMBAT PERMADEATH]: {speaker_name} perished during the encounter.",
                                session_id=target_sess.id
                            )
                        except Exception:
                            pass

                        last_exchange[0] = (
                            f"*{speaker_name} collapses, lifeless on the ground.* "
                            f"[WITNESS NOTIFICATION: {speaker_name} has died. React to the corpse and your survival.]"
                        )
                else:
                    last_exchange[0] = clean

                is_empty = False
                if not clean or "completed turn, but returned an empty response" in clean:
                    is_empty = True
                    empty_stall_count[speaker_sess.id] = empty_stall_count.get(speaker_sess.id, 0) + 1
                    
                    if empty_stall_count[speaker_sess.id] >= 2:
                        clean = f"({speaker_name} returned no usable response; engine will retry this speaker without inventing an in-world action.)"
                        empty_stall_count[speaker_sess.id] = 0
                    else:
                        clean = f"({speaker_name} completed turn, but returned an empty response.)"
                else:
                    empty_stall_count[speaker_sess.id] = 0

                if not force_same_speaker and not is_empty:
                    active_turn[0] += 1

                def ui_deliver():
                    is_generating[0] = False
                    if is_closed[0]: return
                    _stop_thinking()
                    
                    if is_empty:
                        _start_arena_continue_flash()
                    else:
                        _stop_arena_continue_flash()

                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    head_txt = f"[{timestamp}] {speaker_name}:\n"
                    _type_out_arena(head_txt, clean, tag_head, tag_body)

                dialog.after(0, ui_deliver)

            threading.Thread(target=worker, daemon=True).start()

        def handle_event_injection():
            _stop_arena_continue_flash()
            s1 = arena_sessions_tuple[0]
            s2 = arena_sessions_tuple[1]
            n1 = getattr(s1, "agent_name", "Agent 1")
            n2 = getattr(s2, "agent_name", "Agent 2")

            event_prompt = (
                f"[DIRECTIVE: NARRATIVE EVENT INJECTION]\n"
                f"Invent an instant, high-stakes external occurrence unfolding right in the middle of {n1} and {n2}'s debate. "
                f"Describe the immediate spectacle (2 sentences) and force both agents to react! "
                f"Do not write dialogue for {n1}, {n2}, or the User."
            )

            _show_thinking("Narrator")

            def worker():
                try:
                    if hasattr(self, "brain") and self.brain:
                        reply = self.brain.infer(event_prompt, s1)
                    else:
                        from overmind import overmind
                        reply = overmind(event_prompt, s1)
                except Exception as e:
                    reply = f"⚡ A sudden, violent shockwave rattles the arena grounds between {n1} and {n2}!"

                if is_closed[0]: return
                _, clean = _extract_dual_channel_meta(str(reply))

                clean = clean.strip()
                if not clean or "offline" in clean.lower() or "completed turn, but returned an empty" in clean.lower():
                    clean = f"⚡ A sudden blinding flash tears across the sky, shaking the ground between {n1} and {n2}!"

                last_exchange[0] = f"[💥 Live Event]: {clean}"

                def ui_deliver():
                    _stop_thinking()
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    arena_canvas.insert(tk.END, f"\n[{timestamp}] [⚡ Live Dynamic Event]:\n", "sys")
                    arena_canvas.insert(tk.END, f"{clean}\n\n", "user_body")
                    arena_canvas.see(tk.END)
                    step_turn()

                dialog.after(0, ui_deliver)

            threading.Thread(target=worker, daemon=True).start()

        def trigger_intervention(event=None):
            _stop_arena_continue_flash()
            msg = _normalize_text_spacing(entry_intervene.get().strip())
            att_path = staged_upload[0]
            if not msg and not att_path: return

            entry_intervene.delete(0, tk.END)
            staged_upload[0] = None
            btn_upload.config(text="📁 Upload")

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            arena_canvas.insert(tk.END, f"[{timestamp}] [💥 User Intervention]:\n", "user_head")
            if msg:
                arena_canvas.insert(tk.END, f"{msg}\n", "user_body")
            if att_path:
                arena_canvas.insert(tk.END, f"📎 Ingested Artifact: {os.path.basename(att_path)}\n", "sys")
            arena_canvas.insert(tk.END, "\n")
            arena_canvas.see(tk.END)

            intervene_payload = f"[User Intervention]: {msg}"
            if att_path:
                parsed = UniversalFileProcessor().process_file(att_path)
                intervene_payload += f"\n\n[Artifact Data]: {parsed.get('content', '')[:3000]}"

            last_exchange[0] = intervene_payload
            step_turn()

        entry_intervene.bind("<Return>", trigger_intervention)
        btn_send = tk.Button(input_deck, text="💥 Send / Intervene", relief="flat", bd=0, padx=10, pady=6, command=trigger_intervention)
        btn_send.grid(row=0, column=7, sticky="nsew", padx=6, pady=6)
        self._register_tooltip(btn_send, "Send your text as an authoritative user intervention into the live Arena.")

        def handle_upload():
            p = filedialog.askopenfilename(title="Upload Artifact to Duel")
            if p and os.path.exists(p):
                staged_upload[0] = p
                fn = os.path.basename(p)
                btn_upload.config(text=f"📎 {fn[:10]}")

        def handle_finish():
            if is_typewriting[0]:
                cancel_typewriter[0] = True

        def toggle_auto_loop():
            if is_auto_running[0]:
                is_auto_running[0] = False
                if auto_loop_job[0] is not None:
                    try:
                        dialog.after_cancel(auto_loop_job[0])
                    except Exception:
                        pass
                    auto_loop_job[0] = None
                refresh_arena_skin_elements(load_skin())
            else:
                _stop_arena_continue_flash()
                is_auto_running[0] = True
                sk = SKINS.get(load_skin(), {})
                btn_auto.config(text="⏹️ Stop Loop", bg=sk.get("accent", "#ff0055"), fg="#ffffff")
                step_turn()

        btn_upload = tk.Button(input_deck, text="📁 Upload", command=handle_upload, relief="flat", bd=0, padx=6, pady=4)
        btn_upload.grid(row=1, column=0, sticky="nsew", padx=3, pady=4)
        self._register_tooltip(btn_upload, "Stage a file or artifact to accompany your next Arena intervention.")

        btn_finish = tk.Button(input_deck, text="⏹️ Finish", command=handle_finish, relief="flat", bd=0, padx=6, pady=4)
        btn_finish.grid(row=1, column=1, sticky="nsew", padx=3, pady=4)
        self._register_tooltip(btn_finish, "Finish the current typewriter animation immediately.")

        btn_continue = tk.Button(input_deck, text="⏩ Continue", command=lambda: step_turn(force_same_speaker=True), relief="flat", bd=0, padx=6, pady=4)
        btn_continue.grid(row=1, column=2, sticky="nsew", padx=3, pady=4)
        self._register_tooltip(btn_continue, "Ask the same persona to continue its previous turn.")

        btn_event = tk.Button(input_deck, text="⚡ Event", command=handle_event_injection, relief="flat", bd=0, padx=6, pady=4)
        btn_event.grid(row=1, column=3, sticky="nsew", padx=3, pady=4)
        self._register_tooltip(btn_event, "Generate and inject an external narrative event for both personas to react to.")

        btn_step = tk.Button(input_deck, text="⚔️ Step Turn", command=lambda: step_turn(force_same_speaker=False), relief="flat", bd=0, padx=8, pady=4)
        btn_step.grid(row=1, column=4, columnspan=2, sticky="nsew", padx=3, pady=4)
        self._register_tooltip(btn_step, "Advance the Arena by one normal alternating agent turn.")

        btn_auto = tk.Button(input_deck, text="▶️ Auto Loop", command=toggle_auto_loop, relief="flat", bd=0, padx=8, pady=4)
        btn_auto.grid(row=1, column=6, columnspan=2, sticky="nsew", padx=3, pady=4)
        self._register_tooltip(btn_auto, "Start or stop autonomous alternating Arena turns.")

        def set_arena_font(name):
            current_font_family[0] = name
            refresh_arena_skin_elements(skin_var.get())

        def set_arena_font_size(sz):
            try:
                current_font_size[0] = int(sz)
                refresh_arena_skin_elements(skin_var.get())
            except Exception: pass

        def set_arena_skin(sk_name):
            refresh_arena_skin_elements(sk_name)

        def pick_text_color():
            col = colorchooser.askcolor(title="Arena Text Color")[1]
            if col:
                entry_intervene.config(fg=col, insertbackground=col)

        def toggle_bold():
            fn = tkfont.Font(font=entry_intervene.cget("font"))
            fn.configure(weight="bold" if fn.cget("weight") != "bold" else "normal")
            entry_intervene.config(font=fn)

        def toggle_italic():
            fn = tkfont.Font(font=entry_intervene.cget("font"))
            fn.configure(slant="italic" if fn.cget("slant") != "italic" else "roman")
            entry_intervene.config(font=fn)

        available_fonts = sorted(tkfont.families())
        font_var = tk.StringVar(value=current_font_family[0])
        font_menu = tk.OptionMenu(top_bar, font_var, *available_fonts, command=set_arena_font)
        font_menu.pack(side=tk.RIGHT, padx=4)
        self._register_tooltip(font_menu, "Choose the Arena font family.")

        size_var = tk.StringVar(value=str(current_font_size[0]))
        size_menu = tk.OptionMenu(top_bar, size_var, *[8, 9, 10, 11, 12, 14, 16, 18, 20], command=set_arena_font_size)
        size_menu.pack(side=tk.RIGHT, padx=4)
        self._register_tooltip(size_menu, "Choose the Arena text size.")

        skin_var = tk.StringVar(value=load_skin())
        skin_menu = tk.OptionMenu(top_bar, skin_var, *get_sorted_skin_names(), command=set_arena_skin)
        skin_menu.pack(side=tk.RIGHT, padx=4)
        self._register_tooltip(skin_menu, "Change the Arena skin/theme.")

        btn_col = tk.Button(top_bar, text="Colour", relief="flat", bd=0, padx=8, pady=4, command=pick_text_color)
        btn_col.pack(side=tk.RIGHT, padx=4)
        self._register_tooltip(btn_col, "Choose the text colour for your Arena intervention input.")
        btn_b = tk.Button(top_bar, text="B", relief="flat", bd=0, padx=8, pady=4, command=toggle_bold)
        btn_b.pack(side=tk.RIGHT, padx=4)
        self._register_tooltip(btn_b, "Toggle bold styling for Arena intervention text.")
        btn_i = tk.Button(top_bar, text="I", relief="flat", bd=0, padx=8, pady=4, command=toggle_italic)
        btn_i.pack(side=tk.RIGHT, padx=4)
        self._register_tooltip(btn_i, "Toggle italic styling for Arena intervention text.")

        def refresh_arena_skin_elements(s_name):
            sk = SKINS.get(s_name, SKINS["Dark"])
            bg_col = sk.get("bg", "#111111")
            frame_bg = sk.get("frame_bg", "#1a1a1a")
            btn_bg = sk.get("button_bg", "#333333")
            btn_fg = sk.get("button_fg", "#ffffff")
            accent_col = sk.get("accent", "#00eaff")
            entry_bg = sk.get("entry_bg", "#161616")
            entry_fg = sk.get("fg", "#ffffff")
            you_col = sk.get("you_colour", "#ff5555")

            fam = current_font_family[0]
            sz = current_font_size[0]
            btn_sz = max(8, sz - 2)

            dialog.configure(bg=bg_col)
            top_bar.configure(bg=frame_bg)
            header_frame.configure(bg=bg_col)
            canvas_frame.configure(bg=bg_col)
            input_deck.configure(bg=bg_col)

            lbl_a1.configure(bg=bg_col, fg=accent_col, font=(fam, sz, "bold"))
            lbl_vs.configure(bg=bg_col, fg=accent_col if accent_col != "#00eaff" else "#ffcc00", font=(fam, sz, "bold"))
            lbl_a2.configure(bg=bg_col, fg=you_col, font=(fam, sz, "bold"))
            thinking_label.configure(bg=frame_bg, fg=entry_fg, font=(fam, sz - 1, "italic"))

            style = ttk.Style(dialog)
            style.configure(
                "DarkArena.TCombobox",
                fieldbackground=entry_bg,
                background=btn_bg,
                foreground=entry_fg,
                darkcolor=btn_bg,
                lightcolor=btn_bg,
                bordercolor=accent_col,
                arrowcolor=accent_col,
                padding=3,
                font=(fam, sz)
            )
            style.map(
                "DarkArena.TCombobox",
                fieldbackground=[("readonly", entry_bg)],
                foreground=[("readonly", entry_fg)],
                background=[("readonly", btn_bg)],
                selectbackground=[("readonly", accent_col)],
                selectforeground=[("readonly", "#ffffff")]
            )

            if hasattr(self, "_refresh_theme_from_skin"):
                self._refresh_theme_from_skin(s_name)
            if callable(globals().get("apply_skin")):
                apply_skin(self, s_name)

            dialog.option_add("*TCombobox*Listbox.background", entry_bg)
            dialog.option_add("*TCombobox*Listbox.foreground", entry_fg)
            dialog.option_add("*TCombobox*Listbox.selectBackground", accent_col)
            dialog.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
            dialog.option_add("*TCombobox*Listbox.font", (fam, sz))

            arena_canvas.configure(
                bg=entry_bg,
                fg=entry_fg,
                insertbackground=accent_col,
                font=(fam, sz)
            )
            
            arena_canvas.tag_config("a1_head", foreground=accent_col, font=(fam, sz, "bold"))
            arena_canvas.tag_config("a2_head", foreground=you_col, font=(fam, sz, "bold"))
            arena_canvas.tag_config("a1_body", foreground=entry_fg, font=(fam, sz))
            arena_canvas.tag_config("a2_body", foreground=entry_fg, font=(fam, sz))
            arena_canvas.tag_config("user_head", foreground=accent_col if accent_col != "#ffcc00" else you_col, font=(fam, sz, "bold"))
            arena_canvas.tag_config("user_body", foreground=entry_fg, font=(fam, sz))
            arena_canvas.tag_config("sys", foreground=sk.get("muted", "#888888"), font=(fam, max(8, sz - 2), "italic"))

            entry_intervene.configure(
                bg=entry_bg, 
                fg=entry_fg, 
                insertbackground=accent_col,
                font=(fam, sz)
            )

            for b in [btn_upload, btn_finish, btn_continue, btn_emoji, btn_col, btn_b, btn_i]:
                b.configure(
                    bg=btn_bg, 
                    fg=btn_fg, 
                    activebackground=accent_col, 
                    activeforeground="#ffffff", 
                    font=(fam, btn_sz, "bold")
                )

            btn_send.configure(
                bg=accent_col, 
                fg="#ffffff", 
                activebackground=btn_bg, 
                activeforeground=accent_col, 
                font=(fam, btn_sz, "bold")
            )
            btn_step.configure(
                bg=btn_bg, 
                fg=accent_col, 
                activebackground=accent_col, 
                activeforeground="#ffffff", 
                font=(fam, btn_sz, "bold")
            )
            btn_event.configure(
                bg=btn_bg, 
                fg=you_col, 
                activebackground=you_col, 
                activeforeground="#ffffff", 
                font=(fam, btn_sz, "bold")
            )

            if not is_auto_running[0]:
                btn_auto.configure(
                    text="▶️ Auto Loop", 
                    bg=btn_bg, 
                    fg=btn_fg, 
                    activebackground=accent_col, 
                    activeforeground="#ffffff", 
                    font=(fam, btn_sz, "bold")
                )
            else:
                btn_auto.configure(
                    text="⏹️ Stop Loop", 
                    bg=accent_col, 
                    fg="#ffffff", 
                    activebackground=btn_bg, 
                    activeforeground=accent_col, 
                    font=(fam, btn_sz, "bold")
                )

            for m in [font_menu, size_menu, skin_menu]:
                m.configure(
                    bg=btn_bg, 
                    fg=btn_fg, 
                    activebackground=accent_col, 
                    activeforeground="#ffffff", 
                    font=(fam, btn_sz),
                    relief="flat", 
                    bd=0, 
                    highlightthickness=0
                )
                m["menu"].configure(
                    bg=entry_bg, 
                    fg=entry_fg, 
                    activebackground=accent_col, 
                    activeforeground="#ffffff",
                    font=(fam, btn_sz)
                )

        self.active_arena_instance = {
            "dialog": dialog,
            "refresh_func": refresh_arena_skin_elements
        }

        refresh_arena_skin_elements(load_skin() if callable(globals().get("load_skin")) else "Dark")

        def on_arena_close():
            is_closed[0] = True
            is_auto_running[0] = False
            if auto_loop_job[0] is not None:
                try:
                    dialog.after_cancel(auto_loop_job[0])
                except Exception:
                    pass
                auto_loop_job[0] = None
            is_generating[0] = False
            _stop_arena_continue_flash()
            self.active_arena_instance = None
            self.arena_active_sessions.clear()
            dialog.destroy()

        if hasattr(self, "root") and self.root.winfo_exists():
            current_active_skin = load_skin() if callable(globals().get("load_skin")) else "Dark"
            if hasattr(self, "_refresh_theme_from_skin"):
                self._refresh_theme_from_skin(current_active_skin)
            if callable(globals().get("apply_skin")):
                apply_skin(self, current_active_skin)

        dialog.protocol("WM_DELETE_WINDOW", on_arena_close)

    def eject_main_model(self):
        if hasattr(self.brain, "model_handler") and self.brain.model_handler:
            if hasattr(self.brain.model_handler, "unload_model"):
                self.brain.model_handler.unload_model()
            self.brain.model_handler = None

        self.actual_model_path = ""
        self.selected_model_path.set("⚠️ Main Model Ejected (VRAM Cleared)")
        self.model_status_label.config(fg="#ff5555")
        messagebox.showinfo("Eject Complete", "Primary GGUF model unloaded from VRAM.")

    def execute_master_purge(self):
        confirm = messagebox.askyesno(
            "⚠️ MASTER PURGE WARNING",
            "Are you sure you want to completely clear ALL memory files and session vaults across ALL personas?\n\n"
            "This will reset all character histories to blank slates. This action CANNOT be undone!",
            icon=messagebox.WARNING
        )
        if not confirm:
            return

        try:
            purged_count = 0

            if os.path.exists(SESSIONS_DIR):
                for folder in os.listdir(SESSIONS_DIR):
                    folder_path = os.path.join(SESSIONS_DIR, folder)
                    if os.path.isdir(folder_path):
                        shutil.rmtree(folder_path)
                        purged_count += 1

            for session_id, app_instance in list(self.active_chat_apps.items()):
                try:
                    if hasattr(app_instance, "root") and app_instance.root.winfo_exists():
                        app_instance.root.destroy()
                except Exception:
                    pass
            self.active_chat_apps.clear()

            self._refresh_sessions()

            messagebox.showinfo(
                "Master Purge Complete",
                f"Successfully reset {purged_count} storage targets. All persona memory vaults are now clean slates."
            )

        except Exception as e:
            messagebox.showerror("Purge Error", f"Failed to execute master purge: {e}")

    def _trigger_file_dialog(self):
        initial_dir = load_last_model_dir()
        path = filedialog.askopenfilename(
            initialdir=initial_dir,
            title="Select Local GGUF Model",
            filetypes=[("GGUF Models", "*.gguf"), ("All Files", "*.*")]
        )
        if path:
            save_last_model_dir(os.path.dirname(path))
            current_val = self.context_size_var.get()
            if not current_val or (not self.custom_ctx_enabled.get() and current_val == 16384):
                n_ctx = calculate_recommended_n_ctx(path)
                self.context_size_var.set(n_ctx)
            else:
                n_ctx = current_val

            self.actual_model_path = path
            self.selected_model_path.set(f"🟢 Model Loaded: {os.path.basename(path)} ({n_ctx // 1024}k Context)")
            self.model_status_label.config(fg="#00ff55")
            self.load_local_model(path)
            self.current_backend.set(f"Native C++ Server ({self.gpu_name})")

    def _refresh_sessions(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        sessions = self.sm.list_sessions()
        for s in sessions:
            created = s.created_at[:16].replace("T", " ") if hasattr(s, "created_at") and s.created_at else "Unknown"
            backend_info = getattr(s, "backend", "LM Studio")
            model_path_val = getattr(s, "model_path", "")
            if model_path_val and "Target:" not in model_path_val and "Ready:" not in model_path_val:
                model_name = os.path.basename(model_path_val)
                backend_info = f"{backend_info.split()[0]} ({model_name})"

            self.tree.insert("", tk.END, iid=s.id, values=(s.name, backend_info, created))

    def _on_tree_select(self, event=None):
        session = self.get_selected_session(silent=True)
        if not session:
            return
            
        backend = getattr(session, "backend", "LM Studio")
        
        active_handler = getattr(self.brain, "model_handler", None)
        live_model = getattr(active_handler, "model_path", "") if (active_handler and active_handler.is_active()) else self.actual_model_path

        if "Native" in backend or "CUDA" in backend or "Vulkan" in backend:
            self.current_backend.set(f"Native C++ Server ({self.gpu_name})")
            target_model = live_model or getattr(session, "model_path", "")
            
            if target_model and os.path.exists(target_model):
                self.actual_model_path = target_model
                ctx_k = self.context_size_var.get() // 1024
                
                has_vision = False
                if active_handler and active_handler.is_active():
                    has_vision = getattr(active_handler, "is_vision_model", False)
                else:
                    from model_handler import ModelHandler
                    has_vision = bool(ModelHandler(target_model).mmproj_path)
                
                vision_tag = " | 👁️ Vision" if has_vision else " | 💬 Text"
                
                self.selected_model_path.set(f"🟢 Model Loaded: {os.path.basename(target_model)} ({ctx_k}k Context{vision_tag})")
                self.model_status_label.config(fg="#00ff55")
            else:
                self.selected_model_path.set("⚠️ Action Required: Load a GGUF model.")
                self.model_status_label.config(fg="#ffcc00")
        else:
            self.current_backend.set("LM Studio (Local API)")
            self.selected_model_path.set("🟢 Bridge Connected: LM Studio Local API")
            self.model_status_label.config(fg="#00ff55")

    def create_new_session(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("New Chat Session")
        dialog.configure(bg="#1e1e1e")
        self._center_on_parent(dialog, 340, 140)

        tk.Label(dialog, text="Enter Chat Session Name:", fg="#ffffff", bg="#1e1e1e", font=("Segoe UI Emoji", 10)).pack(pady=(12, 4))
        entry_name = tk.Entry(dialog, width=32, bg="#111111", fg="#ffffff", insertbackground="#ffffff", font=("Segoe UI Emoji", 10))
        entry_name.pack(pady=6)
        entry_name.focus_set()

        session_confirmed = [False]
        custom_name_container = [""]

        def on_confirm():
            custom_name_container[0] = entry_name.get().strip()
            session_confirmed[0] = True
            dialog.destroy()

        tk.Button(dialog, text="Continue", command=on_confirm, bg="#007acc", fg="#ffffff", relief="flat", padx=12, pady=4).pack(pady=6)
        self.root.wait_window(dialog)

        if not session_confirmed[0]:
            return

        custom_name = custom_name_container[0] or None

        skin_name = load_skin()
        skin = SKINS.get(skin_name, SKINS["Dark"])

        bg_col = skin.get("bg", "#111111")
        fg_col = skin.get("fg", "#ffffff")
        accent_col = skin.get("accent", "#00eaff")
        entry_bg = skin.get("entry_bg", "#1a1a1a")

        seeding_dialog = tk.Toplevel(self.root)
        style_dialog_window(seeding_dialog, title="Personality Seeding")
        self._center_on_parent(seeding_dialog, 490, 300)

        seeding_confirmed = [False]
        selected_profile = ["ocean_sensitive"]
        var_choice = tk.StringVar(value="ocean_sensitive")

        tk.Label(
            seeding_dialog, 
            text="Select Psychological Personality Baseline:", 
            fg=accent_col, 
            bg=bg_col, 
            font=FONT_HEADER
        ).pack(pady=(16, 10))

        options = [
            ("1. Dynamic OCEAN (Mood-Sensitive Gaussian Curve) [Recommended]", "ocean_sensitive", accent_col),
            ("2. Dynamic OCEAN (Mood-Exempt / Static Gaussian Curve)", "ocean_static", "#ffcc00"),
            ("3. Grey Person (Mood-Sensitive / Balanced Baseline)", "grey_sensitive", fg_col),
            ("4. Grey Person (Mood-Exempt / Pure Analytical)", "grey_analytical", "#aaffaa"),
        ]

        for text, value, color in options:
            rb = tk.Radiobutton(
                seeding_dialog, 
                text=text, 
                variable=var_choice, 
                value=value, 
                bg=bg_col, 
                fg=color, 
                selectcolor=entry_bg, 
                activebackground=bg_col, 
                activeforeground=color, 
                font=FONT_BODY
            )
            rb.pack(anchor="w", padx=24, pady=4)

        def on_confirm_seeding():
            seeding_confirmed[0] = True
            selected_profile[0] = var_choice.get()
            seeding_dialog.destroy()

        btn_confirm = tk.Button(
            seeding_dialog, 
            text="Confirm & Create", 
            command=on_confirm_seeding, 
            bg=accent_col, 
            fg="#ffffff", 
            font=FONT_HEADER, 
            relief="flat", 
            padx=PAD_X_MED, 
            pady=PAD_Y_SMALL,
            cursor="hand2"
        )
        btn_confirm.pack(pady=16)

        self.root.wait_window(seeding_dialog)

        if not seeding_confirmed[0]:
            return

        profile_choice = selected_profile[0]
        weighted = ("ocean" in profile_choice)
        current_bk = self.current_backend.get()

        sess = self.sm.create_session(
            weighted_ocean=weighted, 
            primacy_enabled=True
        )
        
        sess.psychology_mode = profile_choice
        if custom_name:
            sess.name = custom_name

        sess.backend = current_bk
        if "Native" in current_bk:
            sess.model_path = getattr(self, "actual_model_path", "")
        else:
            sess.model_path = "Target: http://localhost:1234"
            
        self.sm._save()
        self._refresh_sessions()
        self.tree.selection_set(sess.id)

        self._start_persona_flash()

    def get_selected_session(self, silent=False):
        selected = self.tree.selection()
        if not selected:
            if not silent:
                messagebox.showwarning("Select Session", "Please select a chat session from the list.")
            return None
        session_id = selected[0]
        return self.sm.get(session_id)

    def open_chat(self):
        # Window validation check: purge dead arena locks automatically
        if self.active_arena_instance is not None:
            arena_dlg = self.active_arena_instance.get("dialog")
            if arena_dlg is None or not arena_dlg.winfo_exists():
                self.active_arena_instance = None
                self.arena_active_sessions.clear()
            else:
                messagebox.showwarning(
                    "Arena In Progress",
                    "⚠️ The Dual Agent Arena is currently active!\n\n"
                    "Please conclude or close the Arena deck before launching individual chat sessions, chief."
                )
                return

        session = self.get_selected_session()
        if not session:
            return

        # Hardened Soul Retrieval & Timeline Reconciliation
        if getattr(session, "is_deceased", False):
            agent_name = getattr(session, "agent_name", "Kylo")
            
            resurrect_box = tk.Toplevel(self.root)
            resurrect_box.title(f"⚠️ Soul Retrieval: {agent_name}")
            resurrect_box.geometry("460x240")
            self._center_on_parent(resurrect_box, 460, 240)
            resurrect_box.configure(bg="#111111")

            tk.Label(
                resurrect_box,
                text=f"💀 {agent_name} is Deceased",
                fg="#ff5555",
                bg="#111111",
                font=("Segoe UI Emoji", 12, "bold")
            ).pack(pady=(16, 6))

            tk.Label(
                resurrect_box,
                text="How shall their consciousness be rekindled?",
                fg="#cccccc",
                bg="#111111",
                font=("Segoe UI", 10)
            ).pack(pady=(0, 14))

            choice_result = [0]

            def choose_mode(mode):
                choice_result[0] = mode
                resurrect_box.destroy()

            btn_remembers = tk.Button(
                resurrect_box,
                text="1. The Returned (Knows they died — bears psychological scars)",
                command=lambda: choose_mode(1),
                bg="#2a1530",
                fg="#d7a8ff",
                activebackground="#9b4dca",
                activeforeground="#ffffff",
                relief="flat",
                font=("Segoe UI", 9, "bold"),
                pady=6
            )
            btn_remembers.pack(fill=tk.X, padx=20, pady=4)

            btn_amnesia = tk.Button(
                resurrect_box,
                text="2. The Amnesiac (Erase fatal turn & reconcile timeline)",
                command=lambda: choose_mode(2),
                bg="#1f3d1f",
                fg="#8bc34a",
                activebackground="#4caf50",
                activeforeground="#ffffff",
                relief="flat",
                font=("Segoe UI", 9, "bold"),
                pady=6
            )
            btn_amnesia.pack(fill=tk.X, padx=20, pady=4)

            btn_leave_dead = tk.Button(
                resurrect_box,
                text="Leave in repose (Cancel)",
                command=lambda: choose_mode(0),
                bg="#222222",
                fg="#888888",
                relief="flat",
                pady=4
            )
            btn_leave_dead.pack(pady=(8, 0))

            self.root.wait_window(resurrect_box)

            if choice_result[0] == 0:
                return

            if choice_result[0] == 1:
                session.is_deceased = False
                session.append_system(f"*[Consciousness Rekindled]: {agent_name} stirs back to life, gasping with the fresh memory of their own death.*")
                self.sm._save()

            elif choice_result[0] == 2:
                session.is_deceased = False
                if hasattr(session, "messages") and len(session.messages) >= 2:
                    session.messages = session.messages[:-2]

                try:
                    from memory_integrity import check_memory_integrity
                    check_memory_integrity(session_id=session.id)
                except Exception:
                    pass

                for s in self.sm.list_sessions():
                    if s.id != session.id:
                        try:
                            from memory_deep import save_deep_memory_journal
                            save_deep_memory_journal(
                                f"[TIMELINE RECONCILIATION]: {agent_name} is alive and active. "
                                f"Any past reports of their death appear to have been false alarms, near-misses, or miraculous recoveries.",
                                session_id=s.id
                            )
                        except Exception:
                            pass

                session.append_system(f"*[Consciousness Rekindled]: {agent_name} awakens as if from a sudden, heavy slumber, unaware of their brush with oblivion.*")
                self.sm._save()

        # Sticky Arena Session Validation & Force-Unlock Override
        if session.id in self.arena_active_sessions:
            if self.active_arena_instance is None:
                self.arena_active_sessions.discard(session.id)
            else:
                agent_name = getattr(session, "agent_name", "Kylo")
                force_unlock = messagebox.askyesno(
                    "Agent Engaged",
                    f"⚠️ '{agent_name}' ({session.name}) is flagged as locked in combat in the Arena!\n\n"
                    f"Would you like to force-unlock this persona and launch solo chat?",
                    icon=messagebox.WARNING
                )
                if force_unlock:
                    self.arena_active_sessions.discard(session.id)
                else:
                    return

        if self.context_menu:
            self.context_menu.config(state="disabled")
        if self.chk_custom_ctx:
            self.chk_custom_ctx.config(state="disabled")

        if session.id in self.active_chat_apps:
            existing_app = self.active_chat_apps[session.id]
            if hasattr(existing_app, "root") and existing_app.root.winfo_exists():
                existing_app.root.deiconify()
                existing_app.root.lift()
                existing_app.root.focus_force()
                return

        splash = LoadingSplashScreen(
            self.root,
            title=f"SPOOLING UP: {session.name.upper()}",
            status="Initializing session state..."
        )

        def boot():
            splash.update_status("Loading chat history & OCEAN profile...")
            time.sleep(0.12)

            backend = getattr(session, "backend", "LM Studio (Local API)")
            model_path = getattr(session, "model_path", "")

            active_model = getattr(self, "actual_model_path", "")
            target_n_ctx = self.context_size_var.get()

            handler_ctx = getattr(getattr(self.brain, "model_handler", None), "n_ctx", None)
            needs_respawn = (handler_ctx != target_n_ctx)
            
            if (hasattr(self.brain, "model_handler") and 
                self.brain.model_handler and 
                self.brain.model_handler.is_active() and 
                not needs_respawn):
                
                session.backend = f"Native C++ Server ({self.gpu_name})"
                session.model_path = self.brain.model_handler.model_path
                self.sm._save()
            elif active_model and os.path.exists(active_model):
                try:
                    splash.update_status(f"Spawning native C++ server ({target_n_ctx // 1024}k tokens)...")
                    from model_handler import create_model_handler
                    
                    handler = create_model_handler(active_model, n_ctx=target_n_ctx)
                    handler.load_model(log_callback=splash.update_status)
                    self.brain.model_handler = handler
                    
                    session.backend = f"Native C++ Server ({self.gpu_name})"
                    session.model_path = active_model
                    self.sm._save()
                except Exception as e:
                    print(f"[Native Engine Error]: {e}")
                    splash.update_status("Native launch failed. Bridging to API.")
                    self.brain.model_handler = None
            else:
                if "Native" not in getattr(session, "backend", ""):
                    self.brain.model_handler = None

            messages = getattr(session, "messages", [])
            has_dialogue = any(
                m.get("role") in ("user", "roxie", "assistant", "agent", "Kylo", getattr(session, "agent_name", "Kylo"))
                for m in messages if isinstance(m, dict)
            )

            if not has_dialogue:
                agent_display = getattr(session, "agent_name", "Kylo")
                splash.update_status(f"{agent_display} is awakening...")
                try:
                    ready = False
                    for _ in range(40):
                        try:
                            port = getattr(getattr(self.brain, "model_handler", None), "port", DEFAULT_PORT)
                            check_resp = requests.get(f"http://{DEFAULT_HOST}:{port}/health", timeout=0.5)
                            if check_resp.status_code == 200:
                                ready = True
                                break
                        except Exception:
                            pass
                        time.sleep(0.25)

                    greeting_prompt = (
                        f"Initiate this interaction with a brief, punchy in-character greeting (1-2 sentences). "
                        f"Speak strictly in your natural cadence, vocabulary, and disposition as {agent_display}. "
                        f"Do not mention system rules or prompt instructions."
                    )
                    from overmind import overmind
                    from memory_api import save_working_memory
                    from memory_deep import save_deep_memory_journal

                    if hasattr(self, "brain") and self.brain:
                        raw_reply = self.brain.infer(greeting_prompt, session)
                    else:
                        raw_reply = overmind(greeting_prompt, session)

                    meta_data, clean_reply = _extract_dual_channel_meta(str(raw_reply))
                    
                    clean_reply = clean_reply.strip()
                    if not clean_reply or "completed turn, but returned an empty response" in clean_reply:
                        clean_reply = f"*{agent_display} stirs quietly into awareness, looking your way.*"

                    session.append_roxie(clean_reply)
                    self.sm._save()

                    session_id = getattr(session, "id", None)
                    target_vault = meta_data.get("vault", "working")
                    significance = float(meta_data.get("significance", 0.5))

                    if target_vault == "deep" or significance >= 0.75:
                        save_deep_memory_journal(clean_reply, session_id=session_id)
                    else:
                        save_working_memory(clean_reply, session_id=session_id)

                except Exception as e:
                    print(f"[Greeting Pre-Warm Error]: {e}")

            splash.update_status("Spooling up chat canvas & voice engine...")
            time.sleep(0.12)

            def launch_window():
                new_root = tk.Toplevel(self.root)
                chat_app = DunoonDaemonApp(
                    new_root,
                    session=session,
                    session_manager=self.sm,
                    brain=self.brain
                )
                self.active_chat_apps[session.id] = chat_app

                def on_window_close():
                    if session.id in self.active_chat_apps:
                        del self.active_chat_apps[session.id]
                    new_root.destroy()
                    if not self.active_chat_apps:
                        if self.context_menu:
                            self.context_menu.config(state="readonly")
                        if self.chk_custom_ctx:
                            self.chk_custom_ctx.config(state="normal")

                new_root.protocol("WM_DELETE_WINDOW", on_window_close)

                try:
                    apply_skin(chat_app, load_skin())
                except Exception:
                    pass

                splash.close()

            self.root.after(0, launch_window)

        threading.Thread(target=boot, daemon=True).start()

    def edit_system_prompt(self):
        self._stop_persona_flash()
        session = self.get_selected_session()
        if not session:
            return

        dialog = tk.Toplevel(self.root)
        style_dialog_window(dialog, title=f"Edit Persona — {session.name}")
        self._center_on_parent(dialog, 600, 720)

        skin_name = load_skin()
        skin = SKINS.get(skin_name, SKINS["Dark"])

        bg_col = skin.get("bg", "#111111")
        entry_bg = skin.get("entry_bg", "#1a1a1a")
        entry_fg = skin.get("entry_fg", "#ffffff")
        btn_bg = skin.get("button_bg", "#333333")
        btn_fg = skin.get("button_fg", "#ffffff")
        accent_col = skin.get("accent", "#00eaff")

        action_frame = tk.Frame(dialog, bg=bg_col)
        action_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=16, pady=(0, 16))

        chk_frame = tk.Frame(dialog, bg=bg_col)
        chk_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=16, pady=(4, 8))

        share_var = tk.BooleanVar(value=getattr(session, "share_insights", False))
        chk_share = tk.Checkbutton(
            chk_frame,
            text="Can lend insights to other personas?",
            variable=share_var,
            bg=bg_col,
            fg=accent_col,
            selectcolor=entry_bg,
            activebackground=bg_col,
            activeforeground=accent_col,
            font=FONT_BODY,
            bd=0
        )
        chk_share.pack(anchor="w")
        self._register_tooltip(chk_share, "Allows memory transfer routines to share high-significance takeaways with other sessions.")

        blind_var = tk.BooleanVar(value=getattr(session, "blind_to_others", False))
        chk_blind = tk.Checkbutton(
            chk_frame,
            text="Blind to other personas? (Total memory isolation)",
            variable=blind_var,
            bg=bg_col,
            fg="#ff5555",
            selectcolor=entry_bg,
            activebackground=bg_col,
            activeforeground="#ff5555",
            font=FONT_BODY,
            bd=0
        )
        chk_blind.pack(anchor="w", pady=(2, 0))
        self._register_tooltip(chk_blind, "Enforces complete memory isolation; ignores insights shared by other personas.")

        eto_var = tk.BooleanVar(value=getattr(session, "eto_enabled", True))
        chk_eto = tk.Checkbutton(
            chk_frame,
            text="Enable ETO Engine (Environment, Threat, Opportunity)",
            variable=eto_var,
            bg=bg_col,
            fg="#00eaff",
            selectcolor=entry_bg,
            activebackground=bg_col,
            activeforeground="#00eaff",
            font=FONT_BODY,
            bd=0
        )
        chk_eto.pack(anchor="w", pady=(2, 0))
        self._register_tooltip(chk_eto, "Keeps the character grounded in established scene facts, physical limits, threats, and opportunities.")

        narrative_var = tk.BooleanVar(value=getattr(session, "narrative_freedom", False))
        chk_narrative = tk.Checkbutton(
            chk_frame,
            text="Allow Collaborative Plot / Worldbuilding",
            variable=narrative_var,
            bg=bg_col,
            fg="#ffcc00",
            selectcolor=entry_bg,
            activebackground=bg_col,
            activeforeground="#ffcc00",
            font=FONT_BODY,
            bd=0
        )
        chk_narrative.pack(anchor="w", pady=(2, 0))
        self._register_tooltip(
            chk_narrative,
            "When enabled, this persona may invent reasonable unstated plot and world details. "
            "When disabled, consequential unknown facts are left for you to establish."
        )

        mortality_var = tk.BooleanVar(value=getattr(session, "mortality_enabled", False))
        chk_mortality = tk.Checkbutton(
            chk_frame,
            text="Enable Mortality (Permanent Defeat / Lethal Stakes)",
            variable=mortality_var,
            bg=bg_col,
            fg="#ff5555",
            selectcolor=entry_bg,
            activebackground=bg_col,
            activeforeground="#ff5555",
            font=FONT_BODY,
            bd=0
        )
        chk_mortality.pack(anchor="w", pady=(2, 0))
        self._register_tooltip(chk_mortality, "Removes plot armor and parses permanent death/defeat during lethal encounters.")

        def save():
            new_name = entry_agent_name.get().strip() or "Kylo"
            new_prompt = txt.get("1.0", tk.END).strip()
            new_backstory = txt_hist.get("1.0", tk.END).strip()

            session.agent_name = new_name
            session.system_prompt = new_prompt
            session.backstory = new_backstory
            session.share_insights = share_var.get()
            session.blind_to_others = blind_var.get()
            session.eto_enabled = eto_var.get()
            session.narrative_freedom = narrative_var.get()
            session.mortality_enabled = mortality_var.get()
            session.physiology = entry_phys.get().strip() or "Normal (Standard Organic humanoid)"
            session.powers = entry_powers.get().strip() or "None (Standard human baseline)"

            if hasattr(self.sm, "save_sessions"):
                self.sm.save_sessions()
            elif hasattr(self.sm, "_save"):
                self.sm._save()

            dialog.destroy()

        btn_save = tk.Button(
            action_frame,
            text="💾 Save Settings",
            command=save,
            bg=accent_col,
            fg="#ffffff",
            font=FONT_HEADER,
            relief="flat",
            padx=PAD_X_MED,
            pady=PAD_Y_SMALL,
            cursor="hand2"
        )
        btn_save.pack(side=tk.RIGHT, padx=(8, 0))

        btn_cancel = tk.Button(
            action_frame,
            text="Cancel",
            command=dialog.destroy,
            bg=btn_bg,
            fg=btn_fg,
            font=FONT_BODY,
            relief="flat",
            padx=PAD_X_MED,
            pady=PAD_Y_SMALL
        )
        btn_cancel.pack(side=tk.RIGHT)

        name_frame = tk.Frame(dialog, bg=bg_col)
        name_frame.pack(side=tk.TOP, fill=tk.X, padx=16, pady=(16, 4))

        tk.Label(
            name_frame,
            text="🤖 Agent Display Name:",
            font=FONT_HEADER,
            fg=accent_col,
            bg=bg_col
        ).pack(anchor="w")

        entry_agent_name = tk.Entry(
            name_frame,
            bg=entry_bg,
            fg=entry_fg,
            insertbackground=entry_fg,
            font=FONT_BODY,
            bd=0,
            relief="flat"
        )
        entry_agent_name.insert(0, getattr(session, "agent_name", "Kylo"))
        entry_agent_name.pack(fill=tk.X, pady=(4, 2), ipady=3)
        self._register_tooltip(entry_agent_name, "Sets the character's primary identity and in-dialogue speaker name.")

        roll_frame = tk.Frame(dialog, bg=bg_col)
        roll_frame.pack(fill=tk.X, padx=16, pady=2)

        entry_seed = tk.Entry(roll_frame, bg=entry_bg, fg="#888888", insertbackground=entry_fg, bd=0, font=FONT_BODY)
        entry_seed.insert(0, "Keywords (e.g. cybernetic, scholar, sarcastic)")
        entry_seed.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=3)
        self._register_tooltip(entry_seed, "Seed words used to roll a procedurally generated persona directive.")

        def roll_random_persona():
            seed_text = entry_seed.get().strip()
            name, directive = roll_persona(seed_keywords=seed_text)
            
            entry_agent_name.delete(0, tk.END)
            entry_agent_name.insert(0, name)
            txt.delete("1.0", tk.END)
            txt.insert("1.0", directive)

        btn_roll = tk.Button(
            roll_frame, 
            text="🎲 Roll Persona", 
            command=roll_random_persona, 
            bg="#442266", 
            fg="#ffccff", 
            font=FONT_HEADER, 
            relief="flat", 
            padx=10, 
            pady=2,
            cursor="hand2"
        )
        btn_roll.pack(side=tk.RIGHT, padx=(8, 0))
        self._register_tooltip(btn_roll, "Generate a random archetype and prompt based on the seed keywords.")

        # Character Sheet Specifics (Physiology & Powers)
        sheet_fields_frame = tk.Frame(dialog, bg=bg_col)
        sheet_fields_frame.pack(fill=tk.X, padx=16, pady=6)

        tk.Label(sheet_fields_frame, text="🧬 Physiology:", font=FONT_BODY, fg="#aaffaa", bg=bg_col).grid(row=0, column=0, sticky="w", pady=3)
        entry_phys = tk.Entry(sheet_fields_frame, bg=entry_bg, fg=entry_fg, insertbackground=entry_fg, font=FONT_BODY, bd=0)
        entry_phys.insert(0, getattr(session, "physiology", "") or "Normal (Standard Organic humanoid)")
        entry_phys.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=3)
        self._register_tooltip(entry_phys, "Biological limits, breathing needs, natural locomotion, and passive immunities (e.g. 'Amphibious aquatic predator', 'Vacuum-sealed cyborg').")

        tk.Label(sheet_fields_frame, text="⚡ Powers / Skills:", font=FONT_BODY, fg="#00eaff", bg=bg_col).grid(row=1, column=0, sticky="w", pady=3)
        entry_powers = tk.Entry(sheet_fields_frame, bg=entry_bg, fg=entry_fg, insertbackground=entry_fg, font=FONT_BODY, bd=0)
        entry_powers.insert(0, getattr(session, "powers", "") or "None (Standard human baseline)")
        entry_powers.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=3)
        self._register_tooltip(entry_powers, "Hard operational limits for supernatural powers, spells, technology, or combat abilities.")

        sheet_fields_frame.columnconfigure(1, weight=1)

        prompt_frame = tk.Frame(dialog, bg=bg_col)
        prompt_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=16, pady=4)

        prompt_paned = tk.PanedWindow(prompt_frame, orient=tk.VERTICAL, bg=bg_col, bd=0, sashwidth=4)
        prompt_paned.pack(fill=tk.BOTH, expand=True)

        dir_frame = tk.Frame(prompt_paned, bg=bg_col)
        tk.Label(dir_frame, text="⚙️ Core Persona Directives:", font=FONT_HEADER, fg=accent_col, bg=bg_col).pack(anchor="w", pady=(0, 2))
        
        txt = tk.Text(dir_frame, wrap="word", bg=entry_bg, fg=entry_fg, insertbackground=entry_fg, font=FONT_CODE, bd=0, padx=8, pady=8, height=6)
        txt.pack(fill=tk.BOTH, expand=True)
        prompt_paned.add(dir_frame)
        self._register_tooltip(txt, "Foundational behavioral directives, voice, tone, ethics, and conversational cadence.")

        hist_frame = tk.Frame(prompt_paned, bg=bg_col)
        tk.Label(hist_frame, text="📜 Backstory / History (Optional):", font=FONT_HEADER, fg="#ffcc00", bg=bg_col).pack(anchor="w", pady=(4, 2))
        
        txt_hist = tk.Text(hist_frame, wrap="word", bg=entry_bg, fg=entry_fg, insertbackground=entry_fg, font=FONT_CODE, bd=0, padx=8, pady=8, height=4)
        txt_hist.pack(fill=tk.BOTH, expand=True)
        prompt_paned.add(hist_frame)
        self._register_tooltip(txt_hist, "Biographical lore, relationships, past experiences, and lived history.")

        current_prompt = getattr(session, "system_prompt", "")
        if current_prompt:
            txt.insert("1.0", current_prompt)
            
        current_backstory = getattr(session, "backstory", "")
        if current_backstory:
            txt_hist.insert("1.0", current_backstory)

    def rename_session(self):
        session = self.get_selected_session()
        if not session:
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Rename Session")
        dialog.configure(bg="#1e1e1e")
        self._center_on_parent(dialog, 320, 130)

        tk.Label(dialog, text="New Session Name:", fg="#ffffff", bg="#1e1e1e", font=("Segoe UI Emoji", 9)).pack(pady=(12, 4))
        e = tk.Entry(dialog, width=32, bg="#111111", fg="#ffffff", insertbackground="#ffffff", font=("Segoe UI Emoji", 9))
        e.insert(0, session.name)
        e.pack(pady=6)
        e.focus_set()

        def confirm():
            new_name = e.get().strip()
            if new_name:
                self.sm.rename_session(session.id, new_name)
                self._refresh_sessions()
            dialog.destroy()

        tk.Button(dialog, text="Save", command=confirm, bg="#0088ff", fg="#ffffff", relief="flat", padx=12, pady=4).pack(pady=6)

    def delete_session(self):
        session = self.get_selected_session()
        if not session:
            return

        session_name = session.name
        session_id = session.id

        if messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete '{session_name}' and its isolated vault?"):
            if session_id in self.active_chat_apps:
                try:
                    app = self.active_chat_apps[session_id]
                    if hasattr(app, "root") and app.root.winfo_exists():
                        app.root.destroy()
                except Exception as e:
                    print(f"[Auto-Kill Chat Window Error]: {e}")
                del self.active_chat_apps[session_id]

            self.sm.delete_session(session_id)

            session_dir = os.path.join(SESSIONS_DIR, str(session_id))
            if os.path.exists(session_dir):
                try:
                    shutil.rmtree(session_dir)
                except Exception as e:
                    print(f"[Session Folder Delete Error]: {e}")

            self._refresh_sessions()

            prev_status = self.selected_model_path.get()
            prev_color = self.model_status_label.cget("fg")

            self.selected_model_path.set(f"🗑️ {session_name}'s memory logs deleted")
            self.model_status_label.config(fg="#ffcc00")

            def revert():
                self.selected_model_path.set(prev_status)
                self.model_status_label.config(fg=prev_color)

            self.root.after(3000, revert)

    def _on_backend_change(self, event=None):
        selection = self.current_backend.get()

        if "LM Studio" in selection:
            has_native_vram = False
            vram_note = ""

            if hasattr(self.brain, "model_handler") and self.brain.model_handler:
                handler = self.brain.model_handler
                if getattr(handler, "server_process", None) and handler.server_process.poll() is None:
                    has_native_vram = True
                    if getattr(handler, "model_path", "") and os.path.exists(handler.model_path):
                        gb = os.path.getsize(handler.model_path) / (1024 ** 3)
                        vram_note = f" (Note: Native C++ model still holding ~{gb:.1f} GB VRAM)"
                    else:
                        vram_note = " (Note: Native C++ model still holding VRAM)"

            if has_native_vram:
                self.selected_model_path.set(f"🟢 Bridge Connected: LM Studio{vram_note}")
                self.model_status_label.config(fg="#ffcc00")
            else:
                self.selected_model_path.set("🟢 Bridge Connected: LM Studio Local API")
                self.model_status_label.config(fg="#00ff55")

            self._test_lmstudio_connection()
        else:
            if self.actual_model_path and os.path.exists(self.actual_model_path):
                self.selected_model_path.set(f"🟢 Model Loaded: {os.path.basename(self.actual_model_path)} ({self.context_size_var.get() // 1024}k Context)")
                self.model_status_label.config(fg="#00ff55")
            else:
                self.selected_model_path.set("⚠️ Action Required: Please load a GGUF model.")
                self.model_status_label.config(fg="#ffcc00")

    def _test_lmstudio_connection(self, verbose=False, silent=False):
        try:
            resp = requests.get("http://127.0.0.1:1234/v1/models", timeout=2)
            if resp.status_code == 200:
                if "holding" not in self.selected_model_path.get():
                    self.selected_model_path.set("🟢 Bridge Connected: LM Studio Local API")
                    self.model_status_label.config(fg="#00ff55")
            else:
                self.selected_model_path.set("⚠️ LM Studio: Unexpected Response")
                self.model_status_label.config(fg="#ff5555")
        except Exception:
            self.selected_model_path.set("⚠️ LM Studio: Offline (Port 1234)")
            self.model_status_label.config(fg="#ff5555")

    def load_local_model(self, model_path: str):
        exe_path = os.path.join(BIN_DIR, "llama-server.exe")
        
        if not os.path.exists(exe_path):
            self._download_native_engine()

        self.actual_model_path = model_path
        model_name = os.path.basename(model_path)
        n_ctx = self.context_size_var.get()

        splash = LoadingSplashScreen(
            self.root,
            title="LOADING LOCAL MODEL",
            status=f"Allocating VRAM natively ({n_ctx // 1024}k tokens) for {model_name}..."
        )

        def worker():
            try:
                splash.update_status(f"Starting native C++ executable ({n_ctx // 1024}k tokens)...")
                from model_handler import create_model_handler
                handler = create_model_handler(model_path, n_ctx=n_ctx)
                
                handler.load_model(log_callback=splash.update_status)

                self.brain.model_handler = handler

                selected_sess = self.get_selected_session(silent=True)
                if selected_sess:
                    selected_sess.backend = f"Native ({model_name})"
                    selected_sess.model_path = model_path
                    self.sm._save()

                splash.update_status("Model successfully offloaded natively!")
                time.sleep(0.2)
                
                ctx_k = n_ctx // 1024
                vision_tag = " | 👁️ Vision" if getattr(handler, "is_vision_model", False) else " | 💬 Text"
                self.root.after(0, lambda: self.selected_model_path.set(
                    f"🟢 Model Loaded: {model_name} ({ctx_k}k Context{vision_tag})"
                ))
                self.root.after(0, lambda: self.model_status_label.config(fg="#00ff55"))
                self.root.after(0, self._refresh_sessions)
            except Exception as e:
                err_msg = str(e)
                print(f"[Model Load Error]: {err_msg}")
                self.root.after(0, lambda msg=err_msg: self.selected_model_path.set(f"⚠️ Load Error: {msg}"))
                self.root.after(0, lambda: self.model_status_label.config(fg="#ff5555"))
            finally:
                self.root.after(0, splash.close)

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    
    root = tk.Tk()

    icon_png_path = os.path.join(BASE_DIR, "splash_logo.png")
    icon_ico_path = os.path.join(BASE_DIR, "icon.ico")

    if os.path.exists(icon_ico_path):
        try:
            root.iconbitmap(icon_ico_path)
        except Exception as e:
            print(f"[Iconbitmap Warning]: {e}")

    if os.path.exists(icon_png_path):
        try:
            img = Image.open(icon_png_path)
            photo_icon = ImageTk.PhotoImage(img)
            root.iconphoto(True, photo_icon)
            root._icon_ref = photo_icon
        except Exception as e:
            print(f"[Iconphoto Warning]: {e}")

    splash = LoadingSplashScreen(root)
    app = ControllerApp(root, splash=splash)
    root.mainloop()