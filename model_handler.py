# model_handler.py — Native C++ Subprocess Engine with JIT Ephemeral Perception Worker & mmproj Auto-Detection
import os
import sys
import time
import threading
import subprocess
import requests
import psutil
import atexit
import re
import glob
from pathlib import Path
import base64
import mimetypes
import traceback
from typing import Dict, Any

from config import BIN_DIR, MODELS_DIR, DEFAULT_HOST, DEFAULT_PORT

class ModelHandler:
    def __init__(self, model_path: str, backend: str = "cuda", n_ctx: int = 16384, is_vision_model: bool = False, mmproj_path: str = None, port: int = DEFAULT_PORT):
        self.model_path = model_path
        self.backend = backend.lower()
        self.n_ctx = n_ctx
        self.port = port
        self.api_url = f"http://127.0.0.1:{self.port}/v1/chat/completions"
        self.server_process = None
        self.log_history = []
        
        self.mmproj_path = mmproj_path or self._find_vision_projector()
        self.is_vision_model = is_vision_model or bool(self.mmproj_path)
        
        atexit.register(self.unload_model)

    def is_active(self) -> bool:
        """Returns True if the native C++ server process is currently running."""
        return self.server_process is not None and self.server_process.poll() is None

    def send(self, packet: Dict[str, Any]) -> str:
        """Sends the structured Overmind prompt packet to the native engine."""
        if not self.is_active():
            raise RuntimeError("llama-server process is not active.")

        system_prompt = packet.get("system", "").strip()
        user_text = packet.get("user", "").strip()
        history = packet.get("history", [])

        sanitized = []
        if history and isinstance(history, list):
            for h in history:
                if isinstance(h, dict):
                    raw_role = str(h.get("role", "user")).lower()
                    content = str(h.get("content", "")).strip()
                    if content and not content.startswith("(LM Studio is offline"):
                        role = "user" if raw_role in ("user", "human") else "assistant"
                        sanitized.append({"role": role, "content": content})

        if user_text:
            if not sanitized or sanitized[-1].get("content") != user_text:
                sanitized.append({"role": "user", "content": user_text})

        collapsed = []
        for turn in sanitized:
            if not collapsed:
                collapsed.append(turn)
            else:
                if turn["role"] == collapsed[-1]["role"]:
                    collapsed[-1]["content"] += f"\n\n{turn['content']}"
                else:
                    collapsed.append(turn)

        # Preserve the system channel as a real system-role message. Models that honor chat
        # roles should receive persona/ETO/OCEAN directives with maximum authority.
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(collapsed)

        if not collapsed:
            messages.append({"role": "user", "content": user_text or "Hello."})
        elif messages[-1]["role"] != "user":
            messages.append({"role": "user", "content": "Continue."})

        model_identifier = os.path.basename(self.model_path) if self.model_path else "local-model"

        payload = {
            "model": model_identifier,
            "messages": messages,
            "temperature": 0.75,
            "repeat_penalty": 1.15,
            "repeat_last_n": 256,
            "presence_penalty": 0.15,
            "max_tokens": 2048,
            "stream": False,
            "stop": [
                "<|im_end|>",
                "<|endoftext|>",
                "<|eot_id|>",
                "<end_of_turn>",
                "\nUser:",
                "\nHuman:",
                "\n[Intervention",
                "\n[User Intervention]"
            ]
        }

        resp = requests.post(self.api_url, json=payload, timeout=90)
        resp.raise_for_status()
        data = resp.json()

        raw_text = data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""

        clean_text = re.sub(r'<\|[a-zA-Z0-9_]+\|>thought.*?<\|[a-zA-Z0-9_]+\|>', '', raw_text, flags=re.DOTALL|re.IGNORECASE)
        clean_text = re.sub(r'<think>.*?</think>', '', clean_text, flags=re.DOTALL|re.IGNORECASE)
        clean_text = re.sub(r'^thought\s*', '', clean_text, flags=re.IGNORECASE)
        clean_text = clean_text.replace("<|channel>", "").replace("<channel|>", "").strip()

        if not clean_text and raw_text.strip():
            clean_text = raw_text.strip()

        return clean_text if clean_text else "(Model completed turn, but returned an empty response.)"

    def _find_vision_projector(self) -> str:
        """Find a likely matching mmproj beside the selected model; never attach an arbitrary projector."""
        if not self.model_path:
            return None

        model_dir = os.path.dirname(os.path.abspath(self.model_path))
        if not os.path.isdir(model_dir):
            return None

        same_dir_matches = [os.path.abspath(p) for p in glob.glob(os.path.join(model_dir, "*mmproj*.gguf"))]
        if not same_dir_matches:
            return None
        if len(same_dir_matches) == 1:
            return same_dir_matches[0]

        model_stem = Path(self.model_path).stem.lower()
        model_tokens = {t for t in re.split(r"[^a-z0-9]+", model_stem) if len(t) >= 3 and t not in {"gguf", "q4", "q5", "q6", "q8"}}
        ranked = []
        for candidate in same_dir_matches:
            cstem = Path(candidate).stem.lower()
            score = sum(1 for t in model_tokens if t in cstem)
            ranked.append((score, candidate))
        ranked.sort(reverse=True)
        return ranked[0][1] if ranked and ranked[0][0] > 0 else None

    def get_server_exe(self):
        exe_path = os.path.join(BIN_DIR, "llama-server.exe")
        if not os.path.exists(exe_path):
            raise FileNotFoundError(f"Missing native C++ engine at: {exe_path}")
        return exe_path

    def _sweep_orphaned_processes(self):
        """Hunts down and terminates any ghost llama-server processes holding our target port."""
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if proc.info['name'] == 'llama-server.exe':
                        cmdline = [str(x) for x in (proc.info.get('cmdline') or [])]
                        # Kill only a llama-server explicitly launched on our target port.
                        # Never treat "has command-line arguments" as proof of ownership.
                        owns_port = any(
                            (arg in ("--port", "-p") and i + 1 < len(cmdline) and cmdline[i + 1] == str(self.port))
                            or arg == f"--port={self.port}"
                            for i, arg in enumerate(cmdline)
                        )
                        if owns_port:
                            print(f"[Zombie Terminator] Terminating ghost engine on port {self.port} (PID: {proc.info['pid']})...")
                            proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as e:
            print(f"[Zombie Terminator Warning]: {e}")

    def _log_streamer(self, pipe, callback):
        """Continuously drains stdout/stderr into memory and updates GUI status to prevent OS pipe blocking."""
        try:
            for line in iter(pipe.readline, ''):
                if not line:
                    break
                clean_line = line.strip()
                self.log_history.append(clean_line)
                if len(self.log_history) > 200:
                    self.log_history.pop(0)

                if callback and clean_line:
                    if any(k in clean_line.lower() for k in ["llama_", "ggml", "model", "load", "vram", "offload", "kv"]):
                        callback(f"[{self.backend.upper()}] {clean_line[:55]}...")
        except Exception:
            pass
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    def load_model(self, log_callback=None) -> None:
        self._sweep_orphaned_processes()
        self.unload_model()
        self.log_history.clear()

        exe = self.get_server_exe()
        bin_dir = os.path.dirname(exe)
        
        abs_model_path = os.path.abspath(self.model_path)
        if not os.path.exists(abs_model_path):
            raise FileNotFoundError(f"Model file does not exist at: {abs_model_path}")

        env = os.environ.copy()
        env["PATH"] = bin_dir + os.path.pathsep + env.get("PATH", "")

        cmd = [
            exe,
            "-m", abs_model_path,
            "--host", "127.0.0.1",
            "--port", str(self.port),
            "-ngl", "99",
            "-c", str(self.n_ctx),
            "-np", "1",
            "-b", "512"
        ]

        if self.mmproj_path and os.path.exists(self.mmproj_path):
            cmd.extend(["--mmproj", os.path.abspath(self.mmproj_path)])
            print(f"[ModelHandler Port {self.port}] Vision Attached: {os.path.basename(self.mmproj_path)}")

        creationflags = 0x08000000 if os.name == "nt" else 0

        try:
            self.server_process = subprocess.Popen(
                cmd,
                cwd=bin_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                text=True,
                encoding="utf-8",
                errors="replace"
            )
        except Exception as e:
            traceback.print_exc()
            raise RuntimeError(f"Failed to spawn subprocess on port {self.port}: {e}")

        drain_thread = threading.Thread(
            target=self._log_streamer, 
            args=(self.server_process.stdout, log_callback), 
            daemon=True
        )
        drain_thread.start()

        ready = False
        start_time = time.time()
        
        while time.time() - start_time < 45:
            if self.server_process.poll() is not None:
                time.sleep(0.2)
                tail_logs = "\n".join(self.log_history[-25:])
                print(f"\n=================== LLAMA-SERVER CRASH LOG ===================")
                print(tail_logs)
                print("==============================================================")
                raise RuntimeError(f"llama-server exited (code {self.server_process.returncode}). Logs:\n{tail_logs}")

            try:
                resp = requests.get(f"http://127.0.0.1:{self.port}/health", timeout=1.0)
                if resp.status_code == 200:
                    ready = True
                    break
            except requests.exceptions.RequestException:
                pass

            time.sleep(0.4)

        if not ready:
            tail_logs = "\n".join(self.log_history[-25:])
            self.unload_model()
            raise RuntimeError(f"Native C++ engine failed to respond within 45s. Logs:\n{tail_logs}")

    def unload_model(self) -> None:
        if self.server_process:
            pid = self.server_process.pid
            
            try:
                self.server_process.terminate()
                self.server_process.wait(timeout=1.5)
            except Exception:
                pass

            try:
                if psutil.pid_exists(pid):
                    parent = psutil.Process(pid)
                    for child in parent.children(recursive=True):
                        child.kill()
                    parent.kill()
            except Exception:
                pass

            try:
                if os.name == "nt" and psutil.pid_exists(pid):
                    os.system(f"taskkill /F /PID {pid} /T >nul 2>&1")
            except Exception:
                pass

            self.server_process = None

    def __del__(self):
        self.unload_model()

def create_model_handler(model_path: str, backend: str = "cuda", n_ctx: int = 16384, is_vision_model: bool = False, mmproj_path: str = None, port: int = DEFAULT_PORT) -> ModelHandler:
    return ModelHandler(model_path=model_path, backend=backend, n_ctx=n_ctx, is_vision_model=is_vision_model, mmproj_path=mmproj_path, port=port)