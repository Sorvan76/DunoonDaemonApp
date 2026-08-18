# skin_manager.py — Unified Skin Engine for Dunoon Daemon + Controller
import json
import os
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from config import SKIN_FILE

FONT_TITLE   = ("Segoe UI", 13, "bold")
FONT_HEADER  = ("Segoe UI", 10, "bold")
FONT_BODY    = ("Segoe UI", 10)
FONT_CAPTION = ("Segoe UI", 9, "italic")
FONT_CODE    = ("Consolas", 10)

PAD_X_SMALL = 6
PAD_Y_SMALL = 4
PAD_X_MED   = 12
PAD_Y_MED   = 8

SKINS = {
    "Fallout": {
        "bg": "#020d04", "fg": "#1bfd00", "accent": "#ffcc00",
        "button_bg": "#0b290d", "button_fg": "#1bfd00",
        "entry_bg": "#051807", "entry_fg": "#1bfd00",
        "frame_bg": "#020d04", "tree_bg": "#051807", "tree_fg": "#1bfd00",
        "tree_header_bg": "#0b290d", "tree_header_fg": "#ffcc00",
        "scroll_bg": "#0b290d", "scroll_trough": "#020d04",
    },
    "Star Wars": {
        "bg": "#0b0c0e", "fg": "#e0e6ed", "accent": "#ff1a1a",
        "button_bg": "#1d2127", "button_fg": "#00eaff",
        "entry_bg": "#15181d", "entry_fg": "#e0e6ed",
        "frame_bg": "#0b0c0e", "tree_bg": "#15181d", "tree_fg": "#e0e6ed",
        "tree_header_bg": "#1d2127", "tree_header_fg": "#ff1a1a",
        "scroll_bg": "#1d2127", "scroll_trough": "#0b0c0e",
    },
    "Baldurs Gate 3": {
        "bg": "#0d0b09", "fg": "#e2c8a0", "accent": "#bf3b2b",
        "button_bg": "#2b1e16", "button_fg": "#f5e3be",
        "entry_bg": "#17120e", "entry_fg": "#f5e3be",
        "frame_bg": "#0d0b09", "tree_bg": "#120f0c", "tree_fg": "#e2c8a0",
        "tree_header_bg": "#231812", "tree_header_fg": "#ffcc66",
        "scroll_bg": "#2b1e16", "scroll_trough": "#0d0b09",
    },
    "Cyberpunk2077": {
        "bg": "#0d0f12", "fg": "#ffe600", "accent": "#00f0ff",
        "button_bg": "#ffe600", "button_fg": "#000000",
        "entry_bg": "#1a1d24", "entry_fg": "#00f0ff",
        "frame_bg": "#0d0f12", "tree_bg": "#14171d", "tree_fg": "#ffe600",
        "tree_header_bg": "#222730", "tree_header_fg": "#00f0ff",
        "scroll_bg": "#ffe600", "scroll_trough": "#0d0f12",
    },
    "Matrix": {
        "bg": "#050a05", "fg": "#00ff66", "accent": "#33ff88",
        "button_bg": "#003311", "button_fg": "#00ff66",
        "entry_bg": "#001a08", "entry_fg": "#00ff66",
        "frame_bg": "#050a05", "tree_bg": "#081208", "tree_fg": "#00ff66",
        "tree_header_bg": "#00260c", "tree_header_fg": "#33ff88",
        "scroll_bg": "#003311", "scroll_trough": "#050a05",
    },
 "Dark": {
         "bg": "#111111",
         "fg": "#ffffff",
         "accent": "#ff5555",
         "button_bg": "#333333",
         "button_fg": "#ffffff",
         "entry_bg": "#222222",
         "entry_fg": "#ff5555",
         "frame_bg": "#111111",
         "tree_bg": "#1a1a1a",
         "tree_fg": "#ffffff",
         "tree_header_bg": "#333333",
         "tree_header_fg": "#ffffff",
         "scroll_bg": "#333333",
         "scroll_trough": "#222222",
     },
 
     "Light": {
         "bg": "#f0f0f0",
         "fg": "#000000",
         "accent": "#cc0000",
         "button_bg": "#dddddd",
         "button_fg": "#000000",
         "entry_bg": "#ffffff",
         "entry_fg": "#cc0000",
         "frame_bg": "#f0f0f0",
         "tree_bg": "#ffffff",
         "tree_fg": "#000000",
         "tree_header_bg": "#e0e0e0",
         "tree_header_fg": "#000000",
         "scroll_bg": "#cccccc",
         "scroll_trough": "#bbbbbb",
     },
 
     "NASA Punk": {
         "bg": "#f2f2f2",
         "fg": "#0a1a2f",
         "accent": "#ff7f11",
         "button_bg": "#0a1a2f",
         "button_fg": "#f2f2f2",
         "entry_bg": "#ffffff",
         "entry_fg": "#0a1a2f",
         "frame_bg": "#e6e6e6",
         "tree_bg": "#e6e6e6",
         "tree_fg": "#0a1a2f",
         "tree_header_bg": "#cfcfcf",
         "tree_header_fg": "#0a1a2f",
         "scroll_bg": "#cfcfcf",
         "scroll_trough": "#bfbfbf",
     },
 
     "CRT_Amber": {
         "bg": "#000000",
         "fg": "#ffb000",
         "accent": "#ffcc33",
         "button_bg": "#1a1a1a",
         "button_fg": "#ffb000",
         "entry_bg": "#1a1a1a",
         "entry_fg": "#ffb000",
         "frame_bg": "#000000",
         "tree_bg": "#000000",
         "tree_fg": "#ffb000",
         "tree_header_bg": "#1a1a1a",
         "tree_header_fg": "#ffb000",
         "scroll_bg": "#1a1a1a",
         "scroll_trough": "#000000",
     },
 
     "Pastel": {
         "bg": "#f7eaff",
         "fg": "#5a4b81",
         "accent": "#b19cd9",
         "button_bg": "#ffd6e0",
         "button_fg": "#5a4b81",
         "entry_bg": "#ffeef7",
         "entry_fg": "#5a4b81",
         "frame_bg": "#fdf7ff",
         "tree_bg": "#fdf7ff",
         "tree_fg": "#5a4b81",
         "tree_header_bg": "#ffd6e0",
         "tree_header_fg": "#5a4b81",
         "scroll_bg": "#ffd6e0",
         "scroll_trough": "#f7eaff",
     },
 
     "Obsidian": {
         "bg": "#0a0a0a",
         "fg": "#e0e0e0",
         "accent": "#00eaff",
         "button_bg": "#111111",
         "button_fg": "#00eaff",
         "entry_bg": "#111111",
         "entry_fg": "#00eaff",
         "frame_bg": "#0a0a0a",
         "tree_bg": "#0a0a0a",
         "tree_fg": "#e0e0e0",
         "tree_header_bg": "#111111",
         "tree_header_fg": "#00eaff",
         "scroll_bg": "#111111",
         "scroll_trough": "#0a0a0a",
     },
 
     "Forest": {
         "bg": "#0f1f0f",
         "fg": "#d4e6c3",
         "accent": "#c2a86b",
         "button_bg": "#2e4a2e",
         "button_fg": "#d4e6c3",
         "entry_bg": "#2e4a2e",
         "entry_fg": "#d4e6c3",
         "frame_bg": "#0f1f0f",
         "tree_bg": "#0f1f0f",
         "tree_fg": "#d4e6c3",
         "tree_header_bg": "#2e4a2e",
         "tree_header_fg": "#d4e6c3",
         "scroll_bg": "#2e4a2e",
         "scroll_trough": "#0f1f0f",
     },
 
     "Neon Arcade": {
         "bg": "#1a0033",
         "fg": "#00ffff",
         "accent": "#ff00ff",
         "button_bg": "#ff00ff",
         "button_fg": "#ffffff",
         "entry_bg": "#330066",
         "entry_fg": "#00ffff",
         "frame_bg": "#1a0033",
         "tree_bg": "#1a0033",
         "tree_fg": "#ff99ff",
         "tree_header_bg": "#330066",
         "tree_header_fg": "#00ffff",
         "scroll_bg": "#330066",
         "scroll_trough": "#1a0033",
     },
 
     "Steampunk": {
         "bg": "#2b1d0e",
         "fg": "#e2c28e",
         "accent": "#cfa76e",
         "button_bg": "#4a2f14",
         "button_fg": "#e2c28e",
         "entry_bg": "#4a2f14",
         "entry_fg": "#e2c28e",
         "frame_bg": "#2b1d0e",
         "tree_bg": "#2b1d0e",
         "tree_fg": "#e2c28e",
         "tree_header_bg": "#4a2f14",
         "tree_header_fg": "#e2c28e",
         "scroll_bg": "#4a2f14",
         "scroll_trough": "#2b1d0e",
     },
 
     "Abyss": {
         "bg": "#00111a",
         "fg": "#cceeff",
         "accent": "#00aaff",
         "button_bg": "#003344",
         "button_fg": "#cceeff",
         "entry_bg": "#003344",
         "entry_fg": "#cceeff",
         "frame_bg": "#00111a",
         "tree_bg": "#00111a",
         "tree_fg": "#cceeff",
         "tree_header_bg": "#003344",
         "tree_header_fg": "#cceeff",
         "scroll_bg": "#003344",
         "scroll_trough": "#00111a",
     },
 
     "Cherry": {
         "bg": "#2b0a12",
         "fg": "#ffccd5",
         "accent": "#ff4d6d",
         "button_bg": "#b80f32",
         "button_fg": "#fff0f3",
         "entry_bg": "#5c1426",
         "entry_fg": "#ffccd5",
         "frame_bg": "#2b0a12",
         "tree_bg": "#3d0f19",
         "tree_fg": "#ffccd5",
         "tree_header_bg": "#4a0f1f",
         "tree_header_fg": "#ffffff",
         "scroll_bg": "#3d0f19",
         "scroll_trough": "#1a0a0f"
     },
 
     "Apple": {
         "bg": "#0f2e0f",
         "fg": "#e8ffe8",
         "accent": "#81c784",
         "button_bg": "#4caf50",
         "button_fg": "#ffffff",
         "entry_bg": "#2e632e",
         "entry_fg": "#e8ffe8",
         "frame_bg": "#0f2e0f",
         "tree_bg": "#1a401a",
         "tree_fg": "#e8ffe8",
         "tree_header_bg": "#245224",
         "tree_header_fg": "#ffffff",
         "scroll_bg": "#1a401a",
         "scroll_trough": "#0f2e0f"
     },
 
     "Coconut": {
         "bg": "#3b2f2f",
         "fg": "#fffaf2",
         "accent": "#b8a48a",
         "button_bg": "#d7c9b1",
         "button_fg": "#3b2f2f",
         "entry_bg": "#6b5a5a",
         "entry_fg": "#fffaf2",
         "frame_bg": "#3b2f2f",
         "tree_bg": "#4a3c3c",
         "tree_fg": "#fffaf2",
         "tree_header_bg": "#5a4a4a",
         "tree_header_fg": "#ffffff",
         "scroll_bg": "#4a3c3c",
         "scroll_trough": "#3b2f2f"
     },
 
     "Banana": {
         "bg": "#3a3000",
         "fg": "#fff9c4",
         "accent": "#ffeb3b",
         "button_bg": "#fdd835",
         "button_fg": "#3a3000",
         "entry_bg": "#6e5a00",
         "entry_fg": "#fff9c4",
         "frame_bg": "#3a3000",
         "tree_bg": "#4a3e00",
         "tree_fg": "#fff9c4",
         "tree_header_bg": "#5c4c00",
         "tree_header_fg": "#ffffff",
         "scroll_bg": "#4a3e00",
         "scroll_trough": "#3a3000"
     },
 
     "Kiwi": {
         "bg": "#1a2e1a",
         "fg": "#e6ffe6",
         "accent": "#aed581",
         "button_bg": "#7cb342",
         "button_fg": "#ffffff",
         "entry_bg": "#3a633a",
         "entry_fg": "#e6ffe6",
         "frame_bg": "#1a2e1a",
         "tree_bg": "#243f24",
         "tree_fg": "#e6ffe6",
         "tree_header_bg": "#2e512e",
         "tree_header_fg": "#ffffff",
         "scroll_bg": "#243f24",
         "scroll_trough": "#1a2e1a"
     },
 
     "Watermelon": {
         "bg": "#1f3d1f",
         "fg": "#ffe6eb",
         "accent": "#8bc34a",
         "button_bg": "#ff5c8a",
         "button_fg": "#1f3d1f",
         "entry_bg": "#3d7a3d",
         "entry_fg": "#ffe6eb",
         "frame_bg": "#1f3d1f",
         "tree_bg": "#2a512a",
         "tree_fg": "#ffe6eb",
         "tree_header_bg": "#336633",
         "tree_header_fg": "#ffffff",
         "scroll_bg": "#2a512a",
         "scroll_trough": "#1f3d1f"
     },
 
     "Berry": {
         "bg": "#1a0f1f",
         "fg": "#f8e6ff",
         "accent": "#d7a8ff",
         "button_bg": "#9b4dca",
         "button_fg": "#ffffff",
         "entry_bg": "#4a2350",
         "entry_fg": "#f8e6ff",
         "frame_bg": "#1a0f1f",
         "tree_bg": "#2a1530",
         "tree_fg": "#f8e6ff",
         "tree_header_bg": "#3a1c40",
         "tree_header_fg": "#ffffff",
         "scroll_bg": "#2a1530",
         "scroll_trough": "#1a0f1f"
     },
 
     "Mango": {
         "bg": "#3a1f00",
         "fg": "#fff2d6",
         "accent": "#ffcc80",
         "button_bg": "#ffa726",
         "button_fg": "#3a1f00",
         "entry_bg": "#6e3800",
         "entry_fg": "#fff2d6",
         "frame_bg": "#3a1f00",
         "tree_bg": "#4a2600",
         "tree_fg": "#fff2d6",
         "tree_header_bg": "#5c2f00",
         "tree_header_fg": "#ffffff",
         "scroll_bg": "#4a2600",
         "scroll_trough": "#3a1f00"
     },
 
     "Pineapple": {
         "bg": "#2a3d00",
         "fg": "#fff9d1",
         "accent": "#cddc39",
         "button_bg": "#ffd54f",
         "button_fg": "#2a3d00",
         "entry_bg": "#4b7300",
         "entry_fg": "#fff9d1",
         "frame_bg": "#2a3d00",
         "tree_bg": "#354f00",
         "tree_fg": "#fff9d1",
         "tree_header_bg": "#406100",
         "tree_header_fg": "#ffffff",
         "scroll_bg": "#354f00",
         "scroll_trough": "#2a3d00"
     },
 
     "Grape": {
         "bg": "#1b0a2e",
         "fg": "#f5e6ff",
         "accent": "#b39ddb",
         "button_bg": "#7e57c2",
         "button_fg": "#ffffff",
         "entry_bg": "#3e1364",
         "entry_fg": "#f5e6ff",
         "frame_bg": "#1b0a2e",
         "tree_bg": "#260d40",
         "tree_fg": "#f5e6ff",
         "tree_header_bg": "#321052",
         "tree_header_fg": "#ffffff",
         "scroll_bg": "#260d40",
         "scroll_trough": "#1b0a2e"
     },
 
     "Dragonfruit": {
         "bg": "#33001f",
         "fg": "#ffe6f2",
         "accent": "#c8ff5a",
         "button_bg": "#ff1e8c",
         "button_fg": "#33001f",
         "entry_bg": "#66003d",
         "entry_fg": "#ffe6f2",
         "frame_bg": "#33001f",
         "tree_bg": "#440029",
         "tree_fg": "#ffe6f2",
         "tree_header_bg": "#550033",
         "tree_header_fg": "#ffffff",
         "scroll_bg": "#440029",
         "scroll_trough": "#33001f"
     },
 
     "Blue Raspberry": {
         "bg": "#001f3d",
         "fg": "#d6f0ff",
         "accent": "#81d4fa",
         "button_bg": "#29b6f6",
         "button_fg": "#001f3d",
         "entry_bg": "#00407a",
         "entry_fg": "#d6f0ff",
         "frame_bg": "#001f3d",
         "tree_bg": "#002a52",
         "tree_fg": "#d6f0ff",
         "tree_header_bg": "#003566",
         "tree_header_fg": "#ffffff",
         "scroll_bg": "#002a52",
         "scroll_trough": "#001f3d"
     },

     "Nebula": {
         "bg": "#12001f",
         "fg": "#f3e6ff",
         "accent": "#ff9dff",
         "button_bg": "#b44cff",
         "button_fg": "#12001f",
         "entry_bg": "#320052",
         "entry_fg": "#f3e6ff",
         "frame_bg": "#12001f",
         "tree_bg": "#1c0030",
         "tree_fg": "#f3e6ff",
         "tree_header_bg": "#260040",
         "tree_header_fg": "#ffffff",
         "scroll_bg": "#1c0030",
         "scroll_trough": "#12001f"
     },
 
     "Void": {
         "bg": "#000014",
         "fg": "#d6e6ff",
         "accent": "#64b5f6",
         "button_bg": "#1e88e5",
         "button_fg": "#000014",
         "entry_bg": "#000033",
         "entry_fg": "#d6e6ff",
         "frame_bg": "#000014",
         "tree_bg": "#00001f",
         "tree_fg": "#d6e6ff",
         "tree_header_bg": "#000029",
         "tree_header_fg": "#ffffff",
         "scroll_bg": "#00001f",
         "scroll_trough": "#000014"
     },
 
     "Aurora": {
         "bg": "#001a1f",
         "fg": "#e6faff",
         "accent": "#99ffe6",
         "button_bg": "#66ffcc",
         "button_fg": "#001a1f",
         "entry_bg": "#00404c",
         "entry_fg": "#e6faff",
         "frame_bg": "#001a1f",
         "tree_bg": "#00262e",
         "tree_fg": "#e6faff",
         "tree_header_bg": "#00333d",
         "tree_header_fg": "#ffffff",
         "scroll_bg": "#00262e",
         "scroll_trough": "#001a1f"
     },
 
     "Autumn": {
         "bg": "#2a1400",
         "fg": "#ffe6cc",
         "accent": "#ffb74d",
         "button_bg": "#ff8f00",
         "button_fg": "#2a1400",
         "entry_bg": "#5a2c00",
         "entry_fg": "#ffe6cc",
         "frame_bg": "#2a1400",
         "tree_bg": "#3a1c00",
         "tree_fg": "#ffe6cc",
         "tree_header_bg": "#4a2400",
         "tree_header_fg": "#ffffff",
         "scroll_bg": "#3a1c00",
         "scroll_trough": "#2a1400"
     },
 
     "Winter": {
         "bg": "#001f33",
         "fg": "#e6f7ff",
         "accent": "#b3e5fc",
         "button_bg": "#81d4fa",
         "button_fg": "#001f33",
         "entry_bg": "#003d66",
         "entry_fg": "#e6f7ff",
         "frame_bg": "#001f33",
         "tree_bg": "#002944",
         "tree_fg": "#e6f7ff",
         "tree_header_bg": "#003355",
         "tree_header_fg": "#ffffff",
         "scroll_bg": "#002944",
         "scroll_trough": "#001f33"
     },
 
     "Spring": {
         "bg": "#1a2e1a",
         "fg": "#f2fff2",
         "accent": "#c8e6c9",
         "button_bg": "#ffb3d9",
         "button_fg": "#1a2e1a",
         "entry_bg": "#386338",
         "entry_fg": "#f2fff2",
         "frame_bg": "#1a2e1a",
         "tree_bg": "#243f24",
         "tree_fg": "#f2fff2",
         "tree_header_bg": "#2e512e",
         "tree_header_fg": "#ffffff",
         "scroll_bg": "#243f24",
         "scroll_trough": "#1a2e1a"
     },
 
     "Summer": {
         "bg": "#002f4d",
         "fg": "#fffde7",
         "accent": "#fff176",
         "button_bg": "#ffeb3b",
         "button_fg": "#002f4d",
         "entry_bg": "#00507a",
         "entry_fg": "#fffde7",
         "frame_bg": "#002f4d",
         "tree_bg": "#003a5c",
         "tree_fg": "#fffde7",
         "tree_header_bg": "#00456b",
         "tree_header_fg": "#ffffff",
         "scroll_bg": "#003a5c",
         "scroll_trough": "#002f4d"
     }
}

def get_sorted_skin_names():
    return sorted(list(SKINS.keys()))

def load_skin():
    try:
        if os.path.exists(SKIN_FILE):
            with open(SKIN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data.get("current_skin", "Dark")
    except Exception:
        pass
    return "Dark"

def save_skin(name):
    try:
        with open(SKIN_FILE, "w", encoding="utf-8") as f:
            json.dump({"current_skin": name}, f, indent=2)
    except Exception:
        pass

def _apply_ttk_styles(style: ttk.Style, skin: dict):
    style.theme_use("default")
    style.configure("Treeview", background=skin["tree_bg"], foreground=skin["tree_fg"], fieldbackground=skin["tree_bg"], bordercolor=skin["tree_bg"], borderwidth=1, rowheight=22)
    style.configure("Treeview.Heading", background=skin["tree_header_bg"], foreground=skin["tree_header_fg"], relief="flat")
    style.configure("Vertical.TScrollbar", background=skin["scroll_bg"], troughcolor=skin["scroll_trough"], arrowcolor=skin["fg"], bordercolor=skin["scroll_bg"])
    style.configure("Horizontal.TScrollbar", background=skin["scroll_bg"], troughcolor=skin["scroll_trough"], arrowcolor=skin["fg"], bordercolor=skin["scroll_bg"])
    style.configure("TMenubutton", background=skin["button_bg"], foreground=skin["button_fg"], relief="flat", padding=4)

def _apply_widget_skin(widget, skin):
    if getattr(widget, "is_expressive_light", False):
        return

    if isinstance(widget, (tk.Tk, tk.Toplevel)):
        widget.configure(bg=skin["bg"])
        return

    if isinstance(widget, tk.Frame):
        widget.configure(bg=skin.get("frame_bg", skin["bg"]))
        return

    if isinstance(widget, tk.LabelFrame):
        widget.configure(bg=skin.get("frame_bg", skin["bg"]), fg=skin["fg"], font=FONT_HEADER)
        return

    if isinstance(widget, tk.Label):
        widget.configure(bg=skin.get("frame_bg", skin["bg"]), fg=skin["fg"])
        return

    if isinstance(widget, tk.Button):
        widget.configure(bg=skin["button_bg"], fg=skin["button_fg"], activebackground=skin["accent"], activeforeground="#ffffff", relief="flat", bd=0)
        return

    if isinstance(widget, tk.Entry):
        widget.configure(bg=skin["entry_bg"], fg=skin["entry_fg"], insertbackground=skin["entry_fg"], relief="flat", font=FONT_BODY)
        return

    if isinstance(widget, (tk.Text, ScrolledText)):
        widget.configure(bg=skin["bg"], fg=skin["fg"], insertbackground=skin["fg"], relief="flat", font=FONT_CODE)
        return

    for child in widget.winfo_children():
        _apply_widget_skin(child, skin)

def apply_skin(app, name):
    if name not in SKINS:
        name = "Dark"

    skin = SKINS[name]
    save_skin(name)

    style = ttk.Style()
    _apply_ttk_styles(style, skin)
    _apply_widget_skin(app.root, skin)

    if hasattr(app, "toolbar_buttons"):
        for btn in app.toolbar_buttons:
            if getattr(btn, "is_expressive_light", False):
                continue
            try:
                btn.configure(bg=skin["button_bg"], fg=skin["button_fg"], activebackground=skin["button_bg"], activeforeground=skin["button_fg"])
            except Exception:
                pass

    if hasattr(app, "tree"):
        try:
            app.tree.configure(background=skin["tree_bg"], foreground=skin["tree_fg"])
        except Exception:
            pass

def style_dialog_window(window, title=""):
    if title:
        window.title(title)
    skin_name = load_skin()
    skin = SKINS.get(skin_name, SKINS["Dark"])
    try:
        window.configure(bg=skin["bg"])
    except Exception:
        pass

    for widget in window.winfo_children():
        _apply_widget_skin(widget, skin)
        if isinstance(widget, tk.Label):
            current_font = widget.cget("font")
            if "16" in str(current_font) or "14" in str(current_font) or "12" in str(current_font):
                widget.configure(font=FONT_TITLE)
            elif "italic" in str(current_font) or "8" in str(current_font):
                widget.configure(font=FONT_CAPTION)
            else:
                widget.configure(font=FONT_BODY)
        elif isinstance(widget, tk.Button):
            widget.configure(font=FONT_HEADER, padx=PAD_X_MED, pady=PAD_Y_SMALL, relief="flat", bd=0)
        elif isinstance(widget, tk.Entry):
            widget.configure(font=FONT_BODY, relief="flat")
        elif isinstance(widget, tk.Text):
            widget.configure(font=FONT_CODE, relief="flat", padx=8, pady=8)