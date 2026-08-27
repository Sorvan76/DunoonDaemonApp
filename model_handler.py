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
from bridge import set_last_finish_reason
from inference_gate import PRIMARY_INFERENCE_LOCK

class ModelHandler:
    def __init__(self, model_path: str, backend: str = "auto", n_ctx: int = 16384, is_vision_model: bool = False, mmproj_path: str = None, port: int = DEFAULT_PORT):
        self.model_path = model_path
        self.backend = backend.lower()
        self.n_ctx = n_ctx
        self.port = port
        self.api_url = f"http://127.0.0.1:{self.port}/v1/chat/completions"
        self.server_process = None
        self.log_history = []
        # 🐉 Silver Wyrm: native JSON-object decoding is opportunistic per model/server
        # session. If it ever yields an empty usable completion, stop requesting the
        # transport constraint for the rest of this ModelHandler lifetime. This avoids
        # paying a same-cycle retry while allowing later Director calls to use the
        # already-proven compact prompt-only JSON path.
        self._native_json_constraint_disabled = False
        
        self.mmproj_path = mmproj_path or self._find_vision_projector()
        self.is_vision_model = is_vision_model or bool(self.mmproj_path)
        
        atexit.register(self.unload_model)

    def is_active(self) -> bool:
        """Returns True if the native C++ server process is currently running."""
        return self.server_process is not None and self.server_process.poll() is None

    def get_model_weight_gb(self):
        """Exact on-disk GGUF weight footprint; vendor/API/model-name agnostic."""
        try:
            if self.model_path and os.path.exists(self.model_path):
                return os.path.getsize(self.model_path) / (1024 ** 3)
        except Exception:
            pass
        return None

    def get_runtime_memory_telemetry(self):
        """Best-effort llama-server memory telemetry; WDDM on Windows is vendor-neutral."""
        result = {
            "model_weight_gb": self.get_model_weight_gb(),
            "gpu_dedicated_gb": None,
            "gpu_shared_gb": None,
            "process_ram_gb": None,
        }
        if not self.is_active() or not self.server_process:
            return result
        pid = int(self.server_process.pid)
        try:
            result["process_ram_gb"] = psutil.Process(pid).memory_info().rss / (1024 ** 3)
        except Exception:
            pass
        if os.name == "nt":
            try:
                ps = (
                    "$pidTarget=" + str(pid) + ";"
                    "$samples=(Get-Counter '\\GPU Process Memory(*)\\Dedicated Usage','\\GPU Process Memory(*)\\Shared Usage' -ErrorAction SilentlyContinue).CounterSamples | "
                    "Where-Object { $_.InstanceName -match ('pid_' + $pidTarget + '_') };"
                    "$d=($samples | Where-Object {$_.Path -like '*Dedicated Usage'} | Measure-Object CookedValue -Sum).Sum;"
                    "$s=($samples | Where-Object {$_.Path -like '*Shared Usage'} | Measure-Object CookedValue -Sum).Sum;"
                    "Write-Output (([double]$d).ToString([Globalization.CultureInfo]::InvariantCulture) + ',' + ([double]$s).ToString([Globalization.CultureInfo]::InvariantCulture))"
                )
                proc = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=3.0,
                    creationflags=0x08000000,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    parts = proc.stdout.strip().split(",")
                    if len(parts) >= 2:
                        dedicated = float(parts[0] or 0.0)
                        shared = float(parts[1] or 0.0)
                        if dedicated > 0:
                            result["gpu_dedicated_gb"] = dedicated / (1024 ** 3)
                        if shared > 0:
                            result["gpu_shared_gb"] = shared / (1024 ** 3)
            except Exception:
                pass
        return result

    def send(self, packet: Dict[str, Any]) -> str:
        """Serialize every Dunoon request through the one configured primary model."""
        with PRIMARY_INFERENCE_LOCK:
            return self._send_unlocked(packet)

    def _send_unlocked(self, packet: Dict[str, Any]) -> str:
        """Sends the structured Overmind prompt packet to the native engine."""
        set_last_finish_reason(None)
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
                    if content and not content.startswith("(Native model backend unavailable"):
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

        # 🐉 Silver Wyrm: HARD CONSEQUENCE LOCK can request an isolated single-turn transport.
        # This deliberately avoids the normal Director chat envelope: no history, no
        # standalone system role, and no narrative stop strings. The same primary model
        # still supplies all semantics; this is only a cleaner transport shape for one
        # emergency objective-world-change call.
        minimal_single_turn = bool(packet.get("minimal_single_turn", False))
        if minimal_single_turn:
            combined = ""
            if system_prompt:
                combined += "[DIRECTIVE]\n" + system_prompt.strip()
            if user_text:
                combined += ("\n\n" if combined else "") + "[FACTS]\n" + user_text.strip()
            messages = [{"role": "user", "content": combined or "State one completed objective external change."}]
        else:
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

        # Arena/other callers may attach one local image to the current inference. Keep
        # the path out of prose; the native OpenAI-compatible llama-server receives the
        # actual image as a data URL. No secondary vision model is introduced.
        image_path = str(packet.get("image_path", "") or "").strip()
        if image_path and os.path.exists(image_path) and self.is_vision_model:
            try:
                mime, _ = mimetypes.guess_type(image_path)
                if mime not in ("image/png", "image/jpeg", "image/webp"):
                    mime = "image/png"
                with open(image_path, "rb") as fh:
                    encoded = base64.b64encode(fh.read()).decode("ascii")
                if messages and messages[-1].get("role") == "user":
                    text_content = messages[-1].get("content", "")
                    if isinstance(text_content, str):
                        messages[-1]["content"] = [
                            {"type": "text", "text": text_content},
                            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
                        ]
            except Exception as exc:
                print(f"[ModelHandler Port {self.port}] Vision attachment skipped: {exc}")

        model_identifier = os.path.basename(self.model_path) if self.model_path else "local-model"

        # Callers may request narrower sampling for structured internal work (e.g. Arena Director JSON).
        # Defaults preserve the established actor/chat behaviour.
        payload = {
            "model": model_identifier,
            "messages": messages,
            "temperature": float(packet.get("temperature", 0.75)),
            "repeat_penalty": float(packet.get("repeat_penalty", 1.15)),
            "repeat_last_n": int(packet.get("repeat_last_n", 256)),
            "presence_penalty": float(packet.get("presence_penalty", 0.15)),
            "max_tokens": int(packet.get("max_tokens", 2048)),
            "stream": False,
            "stop": (
                ["<|im_end|>", "<|endoftext|>", "<|eot_id|>", "<end_of_turn>"]
                if minimal_single_turn else
                [
                    "<|im_end|>",
                    "<|endoftext|>",
                    "<|eot_id|>",
                    "<end_of_turn>",
                    "\nUser:",
                    "\nHuman:",
                    "\n[Intervention",
                    "\n[User Intervention]"
                ]
            )
        }
        if minimal_single_turn and os.environ.get("DUNOON_NATIVE_DEBUG") == "1":
            print("[Native Emergency Path] isolated single-turn primary-model inference")

        # 🐉 Silver Wyrm: CUT THE MONOLOGUE: small structured/internal Arena calls do not need
        # hundreds of hidden reasoning tokens before emitting a tiny decision. Recent
        # llama.cpp server builds expose a per-request OpenAI-compatible reasoning switch
        # plus the template-level enable_thinking variable. Send both when a caller opts
        # in so the model spends its completion budget on the answer instead of exhausting
        # max_tokens inside reasoning_content. Ordinary actor/chat calls are untouched.
        disable_reasoning = bool(packet.get("disable_reasoning", False))
        if disable_reasoning:
            payload["reasoning_effort"] = "none"
            payload["chat_template_kwargs"] = {"enable_thinking": False}
            if os.environ.get("DUNOON_NATIVE_DEBUG") == "1":
                print("[Native Reasoning Budget] reasoning disabled for bounded internal call")

        # Structured internal callers (notably the Arena Director) can request native
        # JSON-object constrained decoding. llama.cpp/OpenAI-compatible builds that
        # support response_format will then prevent prose/fences from being sampled at all.
        # Older builds are handled by a transport-local fallback below; narrative calls
        # are untouched unless they explicitly request this field.
        response_format = packet.get("response_format")
        native_json_requested = isinstance(response_format, dict) and bool(response_format)
        if native_json_requested and not self._native_json_constraint_disabled:
            payload["response_format"] = dict(response_format)

        def _post_native(req_payload):
            return requests.post(self.api_url, json=req_payload, timeout=90)

        resp = _post_native(payload)

        # Some older llama-server builds do not implement OpenAI response_format.
        # If the transport rejects only that optional constraint, retry immediately
        # without it. This is not a second semantic inference: the rejected request
        # produced no completion and preserves the established latency budget.
        if "response_format" in payload and int(getattr(resp, "status_code", 0) or 0) in {400, 404, 422}:
            try:
                resp.raise_for_status()
            except requests.exceptions.HTTPError:
                unconstrained_payload = dict(payload)
                unconstrained_payload.pop("response_format", None)
                if os.environ.get("DUNOON_NATIVE_DEBUG") == "1":
                    print("[Native JSON Constraint] response_format rejected; retrying without transport constraint")
                fallback_resp = _post_native(unconstrained_payload)
                if fallback_resp.ok:
                    resp = fallback_resp
                    payload = unconstrained_payload

        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError:
            # Some GGUF chat templates (notably strict alternation templates) reject
            # a standalone system role. Retry once by folding Dunoon's system prompt
            # into the first user message while preserving user/assistant alternation.
            response_text = ""
            try:
                response_text = resp.text or ""
            except Exception:
                response_text = ""

            alternation_error = (
                resp.status_code == 400
                and "Conversation roles must alternate user/assistant" in response_text
            )
            transient_server_error = 500 <= int(getattr(resp, "status_code", 0) or 0) <= 599

            if transient_server_error:
                # A malformed native-format generation can surface as a one-off llama-server
                # 5xx even though the process and model remain healthy. Inference has not yet
                # committed any turn state here, so one transport-local retry is safe.
                if os.environ.get("DUNOON_NATIVE_DEBUG") == "1":
                    print(f"[Native Transport Recovery] HTTP {resp.status_code}; retrying once")
                time.sleep(0.15)
                retry_resp = _post_native(payload)
                try:
                    retry_resp.raise_for_status()
                    resp = retry_resp
                except requests.exceptions.HTTPError:
                    try:
                        response_text = retry_resp.text or response_text
                    except Exception:
                        pass
                    resp = retry_resp
                    total_chars = sum(len(str(m.get("content", ""))) for m in messages if isinstance(m, dict))
                    print("\n================ NATIVE REQUEST REJECTED ================")
                    print(f"HTTP status: {resp.status_code} (after one transient retry)")
                    print(f"Endpoint: {self.api_url}")
                    print(f"Model: {model_identifier}")
                    print(f"Messages: {len(messages)}")
                    print(f"Approx prompt characters: {total_chars}")
                    print(f"Configured context: {self.n_ctx}")
                    print(f"Requested max_tokens: {payload.get('max_tokens')}")
                    print("llama-server response:")
                    print(response_text[:4000] if response_text else "<empty response>")
                    print("=========================================================\n")
                    raise
            elif alternation_error and system_prompt:
                fallback_messages = [dict(m) for m in collapsed]

                # Ensure there is a leading user turn to carry the Dunoon system block.
                if not fallback_messages:
                    fallback_messages = [{"role": "user", "content": user_text or "Hello."}]
                elif fallback_messages[0].get("role") != "user":
                    fallback_messages.insert(0, {"role": "user", "content": ""})

                first_user = str(fallback_messages[0].get("content", "") or "").strip()
                fallback_messages[0]["content"] = (
                    "[DUNOON SYSTEM DIRECTIVES]\n"
                    + system_prompt
                    + "\n\n[CURRENT USER INPUT]\n"
                    + (first_user or "Hello.")
                )

                # Re-collapse defensively in case the synthetic leading user caused
                # same-role adjacency. The resulting list must alternate strictly.
                strict_messages = []
                for turn in fallback_messages:
                    role = turn.get("role")
                    content = str(turn.get("content", "") or "").strip()
                    if role not in {"user", "assistant"} or not content:
                        continue
                    if strict_messages and strict_messages[-1]["role"] == role:
                        strict_messages[-1]["content"] += "\n\n" + content
                    else:
                        strict_messages.append({"role": role, "content": content})

                if not strict_messages or strict_messages[0]["role"] != "user":
                    strict_messages.insert(0, {
                        "role": "user",
                        "content": "[DUNOON SYSTEM DIRECTIVES]\n" + system_prompt
                    })

                if strict_messages[-1]["role"] != "user":
                    strict_messages.append({"role": "user", "content": "Continue."})

                retry_payload = dict(payload)
                retry_payload["messages"] = strict_messages

                if os.environ.get("DUNOON_NATIVE_DEBUG") == "1":
                    print("[Native Template Compatibility] strict-role template retry")
                resp = _post_native(retry_payload)
                resp.raise_for_status()
                payload = retry_payload
            else:
                # Surface the actual rejection instead of collapsing every HTTP failure
                # into a generic requests traceback.
                total_chars = sum(len(str(m.get("content", ""))) for m in messages if isinstance(m, dict))
                print("\n================ NATIVE REQUEST REJECTED ================")
                print(f"HTTP status: {resp.status_code}")
                print(f"Endpoint: {self.api_url}")
                print(f"Model: {model_identifier}")
                print(f"Messages: {len(messages)}")
                print(f"Approx prompt characters: {total_chars}")
                print(f"Configured context: {self.n_ctx}")
                print(f"Requested max_tokens: {payload.get('max_tokens')}")
                print("llama-server response:")
                print(response_text[:4000] if response_text else "<empty response>")
                print("=========================================================\n")
                raise

        data = resp.json()
        choices = data.get("choices", [])
        if choices:
            set_last_finish_reason(choices[0].get("finish_reason"))

        message = choices[0].get("message", {}) if choices else {}
        raw_text = (message.get("content", "") if isinstance(message, dict) else "") or ""
        reasoning_len = len(str(message.get("reasoning_content", "") or "")) if isinstance(message, dict) else 0
        finish_reason = choices[0].get("finish_reason") if choices else None
        if not raw_text.strip() and reasoning_len and str(finish_reason or "") == "length":
            print(
                "[Native Reasoning Budget] visible content starved by reasoning "
                f"(finish=length, reasoning_chars={reasoning_len}, reasoning_disabled={disable_reasoning})"
            )

        clean_text = re.sub(r'<\|[a-zA-Z0-9_]+\|>thought.*?<\|[a-zA-Z0-9_]+\|>', '', raw_text, flags=re.DOTALL|re.IGNORECASE)
        clean_text = re.sub(r'<think>.*?</think>', '', clean_text, flags=re.DOTALL|re.IGNORECASE)
        clean_text = re.sub(r'^thought\s*', '', clean_text, flags=re.IGNORECASE)
        clean_text = clean_text.replace("<|channel>", "").replace("<channel|>", "").strip()

        if not clean_text and raw_text.strip():
            clean_text = raw_text.strip()

        # 🐉 Silver Wyrm: if the isolated hard-consequence chat request returns no final
        # content, probe the SAME primary llama-server through its raw /completion
        # endpoint. This is deliberately transport-only: no second model, no semantic
        # classifier, and no change to actor/chat traffic. It tells us whether the
        # empty result is being introduced by the model/chat-template path.
        if minimal_single_turn and not clean_text:
            finish = finish_reason
            print(
                "[Native Emergency Bait] chat completion empty "
                f"(finish={finish!s}, reasoning_chars={reasoning_len}) -> probing raw /completion"
            )
            raw_url = f"http://127.0.0.1:{self.port}/completion"
            raw_prompt = combined or user_text or system_prompt or "State one completed objective external change."
            # Seed the single output channel without asking Python to interpret any English.
            if not raw_prompt.rstrip().endswith("WORLD_CHANGE:"):
                raw_prompt = raw_prompt.rstrip() + "\n\nWORLD_CHANGE:"
            raw_payload = {
                "prompt": raw_prompt,
                "temperature": float(packet.get("temperature", 0.16)),
                "repeat_penalty": float(packet.get("repeat_penalty", 1.0)),
                "repeat_last_n": int(packet.get("repeat_last_n", 64)),
                "n_predict": int(packet.get("max_tokens", 128)),
                "stream": False,
                "stop": ["<|im_end|>", "<|endoftext|>", "<|eot_id|>", "<end_of_turn>"],
            }
            try:
                raw_resp = requests.post(raw_url, json=raw_payload, timeout=90)
                raw_resp.raise_for_status()
                raw_data = raw_resp.json()
                raw_candidate = str(raw_data.get("content", "") or "").strip()
                # Raw /completion may expose llama.cpp/model chat-control markers that
                # chat parsing normally removes. Strip protocol tokens only; do not infer
                # or rewrite English meaning.
                raw_candidate = re.sub(r"<\|/?(?:channel|assistant|analysis|final|thought)[^>]*\|>", "", raw_candidate, flags=re.IGNORECASE)
                raw_candidate = raw_candidate.replace("<channel|>", "").replace("<|channel>", "").strip()
                if "WORLD_CHANGE:" in raw_candidate:
                    # The emergency channel has exactly one schema label. If a malformed
                    # preamble precedes a later label, keep the final protocol payload.
                    raw_candidate = "WORLD_CHANGE:" + raw_candidate.rsplit("WORLD_CHANGE:", 1)[1].strip()
                if raw_candidate:
                    clean_text = raw_candidate
                    raw_text = raw_candidate
                    raw_finish = "length" if raw_data.get("stopped_limit") else "stop"
                    set_last_finish_reason(raw_finish)
                    print(
                        "[Native Emergency Bait] raw /completion produced "
                        f"{len(raw_candidate)} chars -> chat-template path implicated"
                    )
                else:
                    print(
                        "[Native Emergency Bait] raw /completion also empty -> "
                        "empty generation is below the chat-template layer"
                    )
            except Exception as exc:
                print(f"[Native Emergency Bait] raw /completion probe failed: {type(exc).__name__}: {exc}")

        # 🐉 Silver Wyrm: some model/llama-server combinations accept response_format but can
        # occasionally terminate immediately with no usable content. Do not retry that
        # semantic turn here. Instead, remember the transport incompatibility for this
        # model-server session so the NEXT structured call uses Dunoon's compact
        # prompt-only JSON contract. This is purely transport state; no narrative meaning
        # is inferred and actor/chat calls are unaffected.
        if "response_format" in payload and not clean_text:
            self._native_json_constraint_disabled = True
            print("[Native JSON Constraint] empty completion; disabled for this model session (compact prompt JSON will be used next call)")

        # Empty generation is transport state, not persona prose. Returning a synthetic
        # sentence here lets downstream acceptance/memory machinery mistake an engine
        # artefact for a genuine actor turn. Callers already own one repair/retry path.
        return clean_text

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

    def _supports_auto_gpu_fit(self, exe: str) -> bool:
        """Detect modern llama.cpp automatic VRAM fitting without assuming a binary version."""
        try:
            creationflags = 0x08000000 if os.name == "nt" else 0
            proc = subprocess.run(
                [exe, "--help"],
                cwd=os.path.dirname(exe),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
            )
            help_text = proc.stdout or ""
            return "--fit" in help_text and ("n-gpu-layers" in help_text or "gpu-layers" in help_text)
        except Exception:
            return False

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
            "-c", str(self.n_ctx),
            "-np", "1",
            "-b", "512"
        ]

        # Modern llama.cpp can automatically fit as much of the model as possible in
        # available device memory and leave the remainder in system RAM. Older bundled
        # binaries retain the previous numeric full-offload request for compatibility.
        if self._supports_auto_gpu_fit(exe):
            cmd.extend(["-ngl", "auto", "--fit", "on"])
            if log_callback:
                log_callback("[Runtime] Adaptive GPU offload enabled (VRAM first, RAM remainder).")
        else:
            cmd.extend(["-ngl", "99"])
            if log_callback:
                log_callback("[Runtime] Legacy GPU offload mode detected.")

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

def create_model_handler(model_path: str, backend: str = "auto", n_ctx: int = 16384, is_vision_model: bool = False, mmproj_path: str = None, port: int = DEFAULT_PORT) -> ModelHandler:
    return ModelHandler(model_path=model_path, backend=backend, n_ctx=n_ctx, is_vision_model=is_vision_model, mmproj_path=mmproj_path, port=port)