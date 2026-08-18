# eye_engine.py — Fully Autonomous Expressive Vector Eye Module
import math
import random
import tkinter as tk


class ExpressiveVectorEye(tk.Canvas):
    """Single digital vector eye canvas with smooth lerp pupil gliding."""

    def __init__(self, master, size=36, **kwargs):
        super().__init__(
            master,
            width=size,
            height=size,
            bg="#1a1a1a",
            highlightthickness=0,
            bd=0,
            **kwargs,
        )

        self.size = size
        self.cx = size // 2
        self.cy = size // 2
        self.radius = (size // 2) - 3

 # Change default idle from neon green to pure white
        self.idle_color = "#FFFFFF"       # Was "#00FF55"
        self.current_color = "#FFFFFF"
        self.target_color = "#FFFFFF"

        self.sustain_frames = 0
        self.pupil_scale = 1.0
        self.eyelid_open = 1.0
        self.is_blinking = False

        self.current_px = float(self.cx)
        self.current_py = float(self.cy)
        self.target_px = float(self.cx)
        self.target_py = float(self.cy)

        self.is_expressive_light = True
        self._animate()

    def set_target_gaze(self, target_x: float, target_y: float):
        self.target_px = self.cx + target_x
        self.target_py = self.cy + target_y

    def set_signal(self, hex_color: str, sustain_seconds: float = 3.0, pupil_scale: float = 1.0):
        self.target_color = hex_color
        self.sustain_frames = int(sustain_seconds * 30)
        self.pupil_scale = max(0.4, min(1.6, pupil_scale))

    def trigger_blink(self):
        if not self.is_blinking:
            self.is_blinking = True
            self.eyelid_open = 0.0

    def draw_eye(self):
        self.delete("all")
        lid_h = self.radius * self.eyelid_open

        # 1. Outer Ring
        self.create_oval(
            self.cx - self.radius,
            self.cy - max(1, lid_h),
            self.cx + self.radius,
            self.cy + max(1, lid_h),
            outline="#333333",
            width=2,
        )

        if self.eyelid_open > 0.1:
            # 2. Glowing Iris
            iris_r = self.radius * 0.7
            self.create_oval(
                self.cx - iris_r,
                self.cy - (iris_r * self.eyelid_open),
                self.cx + iris_r,
                self.cy + (iris_r * self.eyelid_open),
                fill=self.current_color,
                outline="",
            )

            # 3. Independent Gliding Pupil
            pupil_r = (iris_r * 0.45) * self.pupil_scale
            self.create_oval(
                self.current_px - pupil_r,
                self.current_py - (pupil_r * self.eyelid_open),
                self.current_px + pupil_r,
                self.current_py + (pupil_r * self.eyelid_open),
                fill="#0d0d0d",
                outline="",
            )

            # 4. Glare Highlight
            glare_r = max(2, pupil_r * 0.35)
            self.create_oval(
                self.current_px - pupil_r + 1,
                self.current_py - (pupil_r * self.eyelid_open) + 1,
                self.current_px - pupil_r + 1 + glare_r,
                self.current_py - (pupil_r * self.eyelid_open) + 1 + glare_r,
                fill="#FFFFFF",
                outline="",
            )

    def _animate(self):
        # Organic Lerp
        self.current_px += (self.target_px - self.current_px) * 0.15
        self.current_py += (self.target_py - self.current_py) * 0.15

        # Eyelid Recovery
        if self.eyelid_open < 1.0:
            self.eyelid_open = min(1.0, self.eyelid_open + 0.25)
            if self.eyelid_open >= 1.0:
                self.is_blinking = False

        if self.sustain_frames > 0:
            self.sustain_frames -= 1
            self.current_color = self.target_color
        else:
            self.current_color = self.idle_color
            self.pupil_scale = 1.0

        self.draw_eye()
        self.after(33, self._animate)


class ExpressiveVectorEyePair(tk.Frame):
    """
    Dual mirrored vector eyes with built-in Light Engine & Signal Management.
    """

    def __init__(self, master, size=36, **kwargs):
        super().__init__(master, bg="#1a1a1a", **kwargs)

        self.left_eye = ExpressiveVectorEye(self, size=size)
        self.right_eye = ExpressiveVectorEye(self, size=size)

        self.left_eye.pack(side=tk.LEFT, padx=3)
        self.right_eye.pack(side=tk.LEFT, padx=3)

        self.is_expressive_light = True
        self.thinking = False
        self.breath_phase = 0.0

        # Light Engine Signal Levels & Palette
        self.signal_levels = {
            "reset": 0.0,
            "deep": 0.0,
            "journal": 0.0,
            "intent": 0.0,
            "working": 0.0,
            "task": 0.0,
            "persona": 0.0,
            "factual": 0.0,
            "retrieval": 0.0,
            "continuation": 0.0,
        }

        self.persona_palette = {
            "idle": "#FFFFFF",          # Swapped idle to pure white
            "thinking": "#00FF55",      # Swapped thinking breath to neon green
            "working": "#00EFFF",
            "deep": "#FF0033",
            "journal": "#FFF700",
            "intent": "#AA00FF",
            "task": "#FF8800",
            "persona": "#FF66CC",
            "factual": "#FFFFFF",
            "continuation": "#FFFF00",
            "reset": "#222222",
            "retrieval": "#0099FF",
        }

        # Start autonomous loops
        self._scheduled_gaze_shift()
        self._scheduled_blink()
        self._update_light_engine()

    # --- High-Level Trigger Methods ---
    def trigger_working(self): self.signal_levels["working"] = 1.0
    def trigger_deep(self): self.signal_levels["deep"] = 1.0
    def trigger_journal(self): self.signal_levels["journal"] = 1.0
    def trigger_intent(self): self.signal_levels["intent"] = 1.0
    def trigger_task(self): self.signal_levels["task"] = 1.0
    def trigger_persona(self): self.signal_levels["persona"] = 1.0
    def trigger_factual(self): self.signal_levels["factual"] = 1.0
    def trigger_continuation(self): self.signal_levels["continuation"] = 1.0
    def trigger_reset(self): self.signal_levels["reset"] = 1.0
    def trigger_retrieval(self): self.signal_levels["retrieval"] = 1.0

    def start_breathing(self): self.thinking = True
    def stop_breathing(self):
        self.thinking = False
        self.breath_phase = 0.0

    def set_signal(self, hex_color: str, sustain_seconds: float = 3.0, pupil_scale: float = 1.0):
        self.left_eye.set_signal(hex_color, sustain_seconds, pupil_scale)
        self.right_eye.set_signal(hex_color, sustain_seconds, pupil_scale)

    # --- Internal Light Decay Engine Loop ---
    def _update_light_engine(self):
        # Decay signal levels
        for key in self.signal_levels:
            self.signal_levels[key] = max(0.0, self.signal_levels[key] - 0.04)

        # Priority calculation
        active_signals = [
            (self.signal_levels["reset"], "reset", 0.5),
            (self.signal_levels["deep"], "deep", 1.4),
            (self.signal_levels["journal"], "journal", 1.2),
            (self.signal_levels["intent"], "intent", 0.8),
            (self.signal_levels["working"], "working", 1.1),
            (self.signal_levels["task"], "task", 0.9),
            (self.signal_levels["persona"], "persona", 1.3),
            (self.signal_levels["factual"], "factual", 0.7),
            (self.signal_levels["retrieval"], "retrieval", 0.6),
            (self.signal_levels["continuation"], "continuation", 1.0),
        ]

        signal_level, signal_key, pupil_dilation = max(active_signals, key=lambda x: x[0])

        if signal_level > 0.05:
            hex_color = self.persona_palette.get(signal_key, "#00FF55")
            self.set_signal(hex_color, sustain_seconds=0.1, pupil_scale=pupil_dilation)
        elif self.thinking:
            self.breath_phase += 0.08
            if math.sin(self.breath_phase) > 0:
                # Triggers your swapped thinking color here
                self.set_signal("#00FF55", sustain_seconds=0.1, pupil_scale=1.2)

        self.after(50, self._update_light_engine)

    # --- Gazing & Blinking Loops ---
    def _scheduled_gaze_shift(self):
        rand = random.random()
        if rand < 0.35: dx, dy = (random.uniform(4.0, 6.5), random.uniform(-1.0, 1.0))
        elif rand < 0.70: dx, dy = (random.uniform(-6.5, -4.0), random.uniform(-1.0, 1.0))
        elif rand < 0.85: dx, dy = (random.uniform(-1.5, 1.5), random.uniform(3.5, 5.0))
        elif rand < 0.92: dx, dy = (random.uniform(-1.5, 1.5), random.uniform(-5.0, -3.5))
        else: dx, dy = (0.0, 0.0)

        self.left_eye.set_target_gaze(dx, dy)
        self.right_eye.set_target_gaze(dx, dy)
        self.after(random.randint(4000, 8000), self._scheduled_gaze_shift)

    def _scheduled_blink(self):
        self.left_eye.trigger_blink()
        self.right_eye.trigger_blink()
        if random.random() < 0.2:
            self.after(300, lambda: (self.left_eye.trigger_blink(), self.right_eye.trigger_blink()))
        self.after(random.randint(5000, 11000), self._scheduled_blink)