# tts_handler.py — Robust Edge TTS & SAPI5 Voice Handler with Audio Fade & Full Roleplay Support
import os
import threading
import asyncio
import tempfile
import time
import re
import pygame

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False

try:
    import pyttsx3
    PYTTSX3_AVAILABLE = True
except ImportError:
    PYTTSX3_AVAILABLE = False

VOICE_CONFIGS = {
    "Sonia (UK Neural)": {"voice": "en-GB-SoniaNeural", "pitch": "+0Hz", "rate": "+0%"},
    "Ryan (UK Neural)": {"voice": "en-GB-RyanNeural", "pitch": "+0Hz", "rate": "+0%"},
    "Monster / Demon": {"voice": "en-US-ChristopherNeural", "pitch": "-30Hz", "rate": "-15%"},
    "Robot / Synthetic": {"voice": "en-US-GuyNeural", "pitch": "+15Hz", "rate": "+10%"},
    "Goblin / Gremlin": {"voice": "en-GB-MaisieNeural", "pitch": "+30Hz", "rate": "+20%"},
    "Spectre / Deep": {"voice": "en-US-RogerNeural", "pitch": "-20Hz", "rate": "-10%"},
    "Satnav (Local SAPI5)": {"voice": "sapi5", "pitch": "+0Hz", "rate": "+0%"}
}

_WARMED_UP = False


def trickle_warmup_voices():
    """Background trickle to warm up sockets and local audio device on launch."""
    global _WARMED_UP
    if _WARMED_UP:
        return
    _WARMED_UP = True

    def _warmup_worker():
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=24000, size=-16, channels=2, buffer=512)
        except Exception as e:
            print(f"[Voice Warmup Warning] Mixer init failed: {e}")

        if EDGE_TTS_AVAILABLE:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                com = edge_tts.Communicate("Ready", "en-GB-SoniaNeural")
                
                temp_dir = tempfile.gettempdir()
                p = os.path.join(temp_dir, f"warmup_{int(time.time())}.mp3")
                
                loop.run_until_complete(com.save(p))
                loop.close()
                if os.path.exists(p):
                    os.remove(p)
                print("[Voice Trickle] Edge TTS socket pool initialized & warmed up.")
            except Exception as e:
                print(f"[Voice Trickle Notice] Background warmup skipped: {e}")

    threading.Thread(target=_warmup_worker, daemon=True).start()


class TTSHandler:
    def __init__(self, provider="edge", voice="en-GB-SoniaNeural"):
        self.provider = provider if EDGE_TTS_AVAILABLE else "sapi5"
        self.voice_name = voice
        self.pitch_offset = 0
        self.archetype_rate_offset = 0
        self.speed_level = 2
        self.speed_rate_offset = 0
        self.is_playing = False
        self.current_mode_name = "Sonia (UK Neural)"
        self._lock = threading.Lock()
        
        self._init_mixer()
        self.set_voice_mode("Sonia (UK Neural)")

    def _init_mixer(self):
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=24000, size=-16, channels=2, buffer=512)
        except Exception as e:
            print(f"[Mixer Init Warning]: {e}")

    def set_speed(self, level: int):
        self.speed_level = max(1, min(3, int(level)))
        rate_offsets = {1: -20, 2: 0, 3: 25}
        self.speed_rate_offset = rate_offsets.get(self.speed_level, 0)

    def set_voice_mode(self, mode_name: str):
        self.current_mode_name = mode_name
        cfg = VOICE_CONFIGS.get(mode_name, VOICE_CONFIGS["Sonia (UK Neural)"])
        if cfg["voice"] == "sapi5":
            self.provider = "sapi5"
        else:
            self.provider = "edge" if EDGE_TTS_AVAILABLE else "sapi5"
            self.voice_name = cfg["voice"]
            
            pitch_str = cfg.get("pitch", "+0Hz")
            m_pitch = re.search(r'([+-]?\d+)', pitch_str)
            self.pitch_offset = int(m_pitch.group(1)) if m_pitch else 0

            rate_str = cfg.get("rate", "+0%")
            m_rate = re.search(r'([+-]?\d+)', rate_str)
            self.archetype_rate_offset = int(m_rate.group(1)) if m_rate else 0

    def _get_combined_ssml_params(self):
        total_rate = self.archetype_rate_offset + self.speed_rate_offset
        rate_str = f"+{total_rate}%" if total_rate >= 0 else f"{total_rate}%"
        pitch_str = f"+{self.pitch_offset}Hz" if self.pitch_offset >= 0 else f"{self.pitch_offset}Hz"
        return pitch_str, rate_str

    def stop(self, fade_ms: int = 350):
        """Smoothly fades out ongoing speech playback instead of an abrupt cut."""
        def _fade_worker():
            try:
                if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                    steps = 10
                    delay = (fade_ms / 1000.0) / steps
                    for i in range(steps, -1, -1):
                        vol = i / float(steps)
                        pygame.mixer.music.set_volume(vol)
                        time.sleep(delay)

                    pygame.mixer.music.stop()
                    pygame.mixer.music.set_volume(1.0)
                    if hasattr(pygame.mixer.music, "unload"):
                        pygame.mixer.music.unload()
            except Exception:
                try:
                    pygame.mixer.music.stop()
                except Exception:
                    pass
            finally:
                self.is_playing = False

        self.is_playing = False
        threading.Thread(target=_fade_worker, daemon=True).start()

    def speak(self, text: str, progress_callback=None, on_start_callback=None):
        if not text or not str(text).strip():
            return

        def _worker():
            with self._lock:
                self.is_playing = True
                if progress_callback:
                    progress_callback(0.0)

                # Clean markdown, HTML/XML tags, and internal metadata envelopes
                # Keep text inside parentheses intact for narrative roleplay!
                clean_text = re.sub(r'[*_#`~]', '', text).strip()
                clean_text = re.sub(r'<[^>]+>', '', clean_text).strip()
                clean_text = re.sub(r'<!--.*?-->', '', clean_text, flags=re.DOTALL).strip()

                if not clean_text:
                    self.is_playing = False
                    if progress_callback:
                        progress_callback(1.0)
                    return

                if self.provider == "edge" and EDGE_TTS_AVAILABLE:
                    temp_path = None
                    try:
                        if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                            pygame.mixer.music.stop()
                            if hasattr(pygame.mixer.music, "unload"):
                                pygame.mixer.music.unload()

                        self._init_mixer()
                        pygame.mixer.music.set_volume(1.0)

                        pitch_str, rate_str = self._get_combined_ssml_params()

                        temp_dir = tempfile.gettempdir()
                        temp_path = os.path.join(temp_dir, f"tts_{os.getpid()}_{int(time.time()*1000)}.mp3")

                        async def _gen():
                            communicate = edge_tts.Communicate(
                                clean_text, 
                                self.voice_name, 
                                pitch=pitch_str, 
                                rate=rate_str
                            )
                            await communicate.save(temp_path)

                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(_gen())
                        loop.close()

                        if on_start_callback:
                            on_start_callback()

                        if pygame.mixer.get_init() and os.path.exists(temp_path):
                            pygame.mixer.music.load(temp_path)
                            pygame.mixer.music.play()
                            while pygame.mixer.music.get_busy() and self.is_playing:
                                time.sleep(0.05)

                            if hasattr(pygame.mixer.music, "unload"):
                                pygame.mixer.music.unload()

                    except Exception as e:
                        print(f"[Edge TTS Error -> Fallback SAPI5]: {e}")
                        if on_start_callback:
                            on_start_callback()
                        self._fallback_sapi5(clean_text)
                    finally:
                        if temp_path and os.path.exists(temp_path):
                            try:
                                time.sleep(0.05)
                                os.remove(temp_path)
                            except Exception:
                                pass
                else:
                    if on_start_callback:
                        on_start_callback()
                    self._fallback_sapi5(clean_text)

                self.is_playing = False
                if progress_callback:
                    progress_callback(1.0)

        threading.Thread(target=_worker, daemon=True).start()

    def _fallback_sapi5(self, text: str):
        if PYTTSX3_AVAILABLE:
            try:
                engine = pyttsx3.init()
                sapi_rates = {1: 135, 2: 180, 3: 235}
                engine.setProperty('rate', sapi_rates.get(self.speed_level, 180))
                engine.say(text)
                engine.runAndWait()
            except Exception as e:
                print(f"[SAPI5 TTS Error]: {e}")