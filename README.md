# 🐉 Dunoon Daemon

> **Your Personal, Persistent Local AI Companion & Story Engine**

Welcome to **Dunoon Daemon** — a fully autonomous, local-first multi-agent companion suite designed for creative writers, tabletop roleplayers, and anyone seeking persistent AI companions that never forget.

Everything runs entirely on your local hardware. No cloud subscriptions, no telemetry leaks, and zero mandatory internet connections once your models and weights are loaded[cite: 35].

---

## ✨ Key Capabilities

* **Strict Session-Scoped Memory**: Tiered storage (Working Memory, Deep Memory, Factual Vaults, and Journals) isolated in per-companion vaults (`data/sessions/<session_id>/vaults/`)[cite: 4, 35].
* **Dynamic OCEAN Psychology**: Simulates Big Five personality variance and daily emotional shifts affecting tone, vocabulary, and empathy levels[cite: 3, 35].
* **Dual Arena Debate Deck**: Host live multi-agent debates with dynamic topic intervention, user injection, and autonomous event triggers[cite: 5, 35].
* **Universal Multimodal Perception**: Ingests images, transcribes spoken audio tracks via local Whisper, parses PDFs, Word docs, and plain text code files.
* **Expressive Eye Telemetry**: Dual vector digital eyes respond dynamically to hidden LLM affective metadata envelopes (`<!--meta:{...}-->`)[cite: 7, 21, 35].
* **Multi-Archetype Neural Speech**: Built-in Edge TTS streaming with local SAPI5 fallback and smooth audio fade-out logic[cite: 26, 35].

---

## 🚀 Quick Start Guide

### Prerequisites
* **OS**: Windows 10/11 (64-bit)[cite: 35]
* **Python**: 3.11+ (if running from source)[cite: 35]
* **GPU**: NVIDIA (CUDA) or AMD/Intel (Vulkan) recommended; CPU fallback supported[cite: 4, 35].

### 1. Launch the Engine
Open `controller.py` or run the standalone executable[cite: 35]. Select your preferred inference pipeline:
* **Native C++ Server**: Click **📂 Load GGUF Model** to point to any local GGUF file[cite: 5, 35]. The daemon auto-detects your GPU, pulls optimized binaries into `bin/`, and spins up `llama-server.exe`[cite: 5, 8, 20, 35].
* **LM Studio (Local API)**: Start the Local Server in LM Studio (port 1234), and the Daemon connects automatically[cite: 2, 5, 35].

### 2. Create a Companion
1. Click **➕ New Chat** and name your session[cite: 5, 35].
2. Choose a baseline personality mode (**Dynamic OCEAN** recommended)[cite: 3, 5, 35].
3. Click **🎭 Edit Persona** to roll a random archetype or configure your custom character directives and backstory[cite: 5, 22, 35].

### 3. Open Dialogue
Double-click your companion in the session deck to launch the active chat canvas[cite: 5, 35].

---

## ⚡ Slash Command Reference

Execute these commands directly in the dialogue input bar for rapid control[cite: 6, 35]:

* `/remember <text>` — Forces direct storage into the permanent Journal Vault[cite: 6, 13, 35].
* `/memories` or `/vault` — Displays diagnostic counts across all memory tiers[cite: 6, 35].
* `/forget <n>` — Purges the last *n* conversational turns from context[cite: 6, 35].
* `/clear` — Clears visual canvas history without altering memory vaults[cite: 6, 35].
* `/character` — Displays active OCEAN traits and daily mood shifts[cite: 3, 6, 35].
* `/baseline` — Locks personality into a neutral, analytical state[cite: 6, 35].
* `/ubaseline` — Re-enables dynamic daily mood variance[cite: 3, 6, 35].
* `/status` — Displays active model, endpoint, and voice provider[cite: 6, 35].
* `/see` or `/upload` — Opens file staging browser for multimodal ingestion[cite: 6, 35].
* `/splash` — Forces Python garbage collection to free RAM/VRAM[cite: 6, 35].
* `/eject` — Unloads GGUF models and completely flushes VRAM[cite: 5, 6, 35].
* `/talk 1 | 2 | 3` — Sets vocal reading speed: Slow (1), Medium (2), or Fast (3)[cite: 6, 26, 35].

---

## 📁 Repository Structure

```text
DunoonDaemonApp/
├── bin/                                # Native engine binaries (llama-server.exe, runtimes)[cite: 4, 20, 35]
├── data/[cite: 4, 35]
│   ├── audio_cache/                    # Temporary speech cache[cite: 4, 35]
│   └── sessions/                       # Session registry & isolated companion vaults[cite: 4, 24, 35]
│       ├── sessions.json               # Master session catalog[cite: 4, 24, 35]
│       └── <session_id>/               # Isolated per-companion sub-vault[cite: 4, 35]
│           └── vaults/[cite: 4, 35]
│               ├── working_memory.json # Short-term working buffer[cite: 4, 19, 35]
│               ├── deep_memory.json    # Consolidated episodic memory[cite: 4, 13, 35]
│               ├── journal_vault.json  # High-salience structured journal entries[cite: 4, 10, 35]
│               ├── embeddings.json     # Per-session SentenceTransformer vector store[cite: 4, 14, 35]
│               ├── intent_memory.json  # Procedural mandates & directives[cite: 4, 16, 35]
│               ├── task_memory.json    # Workflow & step-tracking memory[cite: 4, 16, 35]
│               ├── factual_memory.json # Core biographical facts[cite: 4, 16, 35]
│               ├── continuation_memory.json[cite: 4, 16, 35]
│               ├── reset_memory.json[cite: 4, 16, 35]
│               └── prune_telemetry.json[cite: 4, 23, 35]
├── models/                             # Local GGUF models & mmproj vision projectors[cite: 4, 20, 35]
├── brain.py                            # Central cognitive routing & CPU affinity[cite: 1, 35]
├── bridge.py                           # LM Studio local API bridge[cite: 2, 35]
├── character.py                        # OCEAN Big Five profiling & daily mood variance[cite: 3, 35]
├── config.py                           # Portable path resolution & hardware detection[cite: 4, 35]
├── controller.py                       # Main deck UI, session manager, & Dual Arena host[cite: 5, 35]
├── dunoon_daemon.py                    # Autonomous companion chat canvas & multimodal deck[cite: 6, 35]
├── eye_engine.py                       # Expressive vector eye telemetry & pupil dynamics[cite: 7, 35]
├── fetch_engine.py                     # C++ binary & runtime auto-fetcher[cite: 8, 35]
├── journal_entry.py / journal_vault.py # Structured salience journaling & atomic storage[cite: 9, 10, 35]
├── memory_api.py                       # Public ingestion gateway[cite: 12, 35]
├── memory_deep.py / memory_working.py  # Thread-safe tiered memory engines[cite: 13, 19, 35]
├── memory_embeddings.py                # Local vector embedding & semantic cosine search[cite: 14, 35]
├── memory_integrity.py                 # Vault sanitizer & auto-healer[cite: 15, 35]
├── memory_router.py                    # Semantic intent & vault classification router[cite: 16, 35]
├── memory_transfer.py                  # Cross-persona insight distillation bridge[cite: 17, 35]
├── memory_validation.py                # Sanitization & private data filter[cite: 18, 35]
├── model_handler.py                    # Native C++ subprocess manager & zombie cleaner[cite: 20, 35]
├── overmind.py                         # Context fusion & dual-channel telemetry engine[cite: 21, 35]
├── persona.py                          # Procedural persona synthesis engine[cite: 22, 35]
├── prune.py                            # Sleep cycle consolidation & capacity controller[cite: 23, 35]
├── session_manager.py                  # Session registry & disk persistence[cite: 24, 35]
├── significance.py                     # Vector salience & entropy scoring engine[cite: 28, 35]
├── skin_manager.py                     # Dynamic theme palettes & widget skinning[cite: 29, 35]
├── state_engine.py                     # Conversation heuristic mood tracker[cite: 25, 35]
├── tts_handler.py                      # Multi-archetype neural voice engine[cite: 26, 35]
└── vault_auto_repair.py                # Global & session vault format repair[cite: 27, 35]
[ User Dialogue / Staged Artifact ]
                │
                ▼
      ┌──────────────────┐
      │ memory_validation│ ─── Blocks sensitive credentials & malformed payloads
      └─────────┬────────┘
                │
                ▼
      ┌──────────────────┐
      │  memory_router   │ ─── Semantic subspace matching across intent/task/facts
      └─────────┬────────┘
                │
  ┌─────────────┼───────────────────────────┐
  │             │                           │
  ▼             ▼                           ▼
[ Working ]  [ Intent / Task / Facts ]   [ Deep / Journal ]
  │             │                           │
  │             └─────────────┬─────────────┘
  │                           │
  ▼                           ▼
┌─────────────────────────────────────────────────────────┐
│ Thread-Safe Atomic Persistence Layer (_lock + .tmp swap)│
└─────────────────────────────┬───────────────────────────┘
                              │
                              ▼
                 ┌──────────────────────────┐
                 │    memory_embeddings     │ (Local SentenceTransformers)
                 │  Per-Session Vector DB   │
                 └────────────┬─────────────┘
                              │
                              ▼
┌───────────────────────────────────────────────────────────┐
│                      overmind.py                          │
│                                                           │
│  • System Directives + Dynamic OCEAN Profile (character)  │
│  • Heuristic State Mood Offsets (state_engine)            │
│  • Semantic Memory Retrieval (Working + Deep + Journals)  │
│  • Filtered Cross-Persona Insights (memory_transfer)      │
│  • Recency-Ranked History Buffer                          │
└─────────────────────────────┬─────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │ Dynamic Inference Execution   │
              │  ├─ Native C++ llama-server   │
              │  └─ LM Studio API (Fallback)  │
              └───────────────┬───────────────┘
                              │
                              ▼
                 [ Dual-Channel Output Stream ]
                 ├── <!--meta:{...}--> ──► [ Eye Telemetry / Signal Engine ]
                 └── Clean Dialogue    ──► [ Typewriter UI + Neural Voice TTS ]
                              │
                              ▼ (Background Idle Hook)
                 ┌─────────────────────────────┐
                 │    run_session_sleep_cycle  │
                 │   (Consolidation & Prune)   │
                 └─────────────────────────────┘
                 git clone https://github.com/your-username/DunoonDaemonApp.git
cd DunoonDaemonApp
pip install requests psutil pygame edge-tts pyttsx3 sentence-transformers numpy Pillow pypdf python-docx faster-whisper
python controller.py
📜 Dedication & License
Distributed under the MIT License.

Dedicated to the loyal companions who walk with us through every realm, and the code that keeps their echoes alive. For Kylo.