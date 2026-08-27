<div align="center">

# 🐉 Dunoon Daemon v2.1.0

### Local AI characters with memory, authority and a world that stays put

**Windows 10/11 · Local GGUF · Open Source · MIT License**

</div>

Dunoon Daemon is a free, open-source, local-first Windows AI character, companion and autonomous roleplay app built around local GGUF models.

It is designed for tabletop roleplayers, GMs, writers and anyone who wants persistent local characters rather than a hosted chatbot. Your configured GGUF is the app's primary semantic brain. Python owns deterministic state, persistence and authority boundaries.

## Why Dunoon Daemon is different

Dunoon Daemon is not just a chat window around a model.

- **Persistent personas** with OCEAN personality profiles, backstory, physiology, powers and relationships.
- **Persona-scoped learned memory** with Working, Deep, Journal, Intent, Task, Factual, Continuation, Reset and superseded-history handling.
- **Authority boundaries** so characters can be imaginative without casually rewriting the physical world or stealing another character's decisions.
- **SceneStore + Director Arena** for two autonomous personas sharing one governed external reality.
- **Environment, Threat and Opportunity grounding** to keep characters aware of what is actually present and happening.
- **Campaign Lore** for explicitly assigned reference material that selected personas are allowed to retrieve.
- **Local inference** through `llama.cpp` / `llama-server`, with no LM Studio fallback in the current architecture.
- **Vision, document upload, speech, transcript export, skins, tooltips, crash recovery, Backup/Restore, Dream maintenance and optional mortality/resurrection.**

## v2.1.0 highlights

- Modern application shell and persona workflow.
- Four Solo conversation modes: Continuation, Sandbox, Canvas and Bubble.
- Reworked memory lifecycle, semantic admission, transactions and recovery.
- Campaign Lore library and retrieval controls.
- Director-governed Arena with SceneStore authority.
- Improved ETO grounding and POV quarantine.
- Single-instance handling and portable path resolution.
- New parchment editions of **The Tome** and **The Goblin's Guide**.
- New portable Windows build recipe with the large native runtime kept outside the EXE.

## Portable Windows release

The public v2.1.0 package is distributed as a normal ZIP rather than a giant self-extracting executable.

```text
DunoonDaemon_v2.1.0/
├── DunoonDaemon.exe
├── bin/                 # llama.cpp / CUDA / backend runtime
├── data/                # writable app state
├── models/              # optional home for your GGUF files
├── Dunoon_Daemon_App_THE_TOME_v2.1.0_PARCHMENT_EDITION.pdf
└── The_Goblins_Guide_to_Dunoon_Daemon_App_v2.1.0_PARCHMENT_EDITION.pdf
```

> 🐉 **Portable rule:** extract the whole ZIP before running it and keep `bin` beside `DunoonDaemon.exe`.

No separate Python installation is required for the packaged release. The entire Dunoon Daemon folder can be moved to another writable location or USB drive as one unit.

The large native `bin/` runtime is intentionally not stored in normal Git history. It is bundled with the public portable release package.

## Five-minute start

1. Download a compatible GGUF instruct/chat model. Q4 or Q4_K_M is a sensible first try when available.
2. Extract the complete Dunoon Daemon release ZIP.
3. Keep `DunoonDaemon.exe` and `bin/` together.
4. Run `DunoonDaemon.exe`.
5. Create a persona, optionally Randomise its OCEAN profile, and save it.
6. Load your `.gguf` model.
7. Open **Continuation** and say hello.

## Documentation

Start here if you are new:

- [The Goblin's Guide to Dunoon Daemon v2.1.0](The_Goblins_Guide_to_Dunoon_Daemon_App_v2.1.0_PARCHMENT_EDITION.pdf) - one-page beginner quickstart.
- [Dunoon Daemon App: The Tome v2.1.0](Dunoon_Daemon_App_THE_TOME_v2.1.0_PARCHMENT_EDITION.pdf) - full operator's manual and systems guide.

## How authority works

In Solo, the human establishes and can correct current external reality while the persona owns its own speech, intentions and voluntary actions.

In Arena, the human establishes the starting scenario, then the Director owns shared external reality while each controlled persona owns itself.

Learned memory is historical evidence, not present-world authority. Current accepted reality outranks memory.

## Running from source

Windows 10/11 and Python 3.10+ are recommended.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python .\modern_shell.py
```

Source runs still need a compatible `bin/llama-server.exe` runtime beside the source tree. GGUF models are not included in the repository.

## Building the windowed EXE

Install PyInstaller in the build environment, then run:

```powershell
.\build_portable_exe.ps1
```

`DunoonDaemon_portable.spec` freezes `modern_shell.py`, the imported Dunoon Daemon modules, Python and required Python packages into a windowed `DunoonDaemon.exe`.

It deliberately **does not embed the large native `bin/` directory**. The final release ZIP supplies that directory beside the EXE.

## Source layout

```text
modern_shell.py                 modern application entry point
modern_daemon.py                Solo conversation UI
modern_arena.py                 Arena UI and orchestration
core/                           Director, SceneStore and turn authority
campaign_lore.py                Campaign Lore library
modern_lore.py                  Campaign Lore UI
memory_*.py                     persistent memory system
journal_*.py                    structured journal storage
release_support.py              backup, recovery and diagnostics
model_handler.py                llama-server lifecycle and GGUF loading
persona*.py / character.py      persona identity, import/export and OCEAN
modern_theme.py                 base visual theme
custom_skins.py / skin_manager.py
DunoonDaemon_portable.spec      PyInstaller build recipe
build_portable_exe.ps1          Windows build helper
```

Runtime-created JSON state, GGUF weights, build output and the large native runtime are ignored by Git.

## Local-first by design

Ordinary inference runs on your own machine. Persona conversations, memories and local state remain local unless you choose to move or share those files yourself.

There is no per-message cloud meter once your local model is downloaded.

## License

Dunoon Daemon is distributed under the [MIT License](LICENSE).

Created by **sorvan76 (Kepler365) and ChatGPT - Human / AI Fusion (2026)**.

Dedicated to the loyal companions who walk with us through every realm, and the code that keeps their echoes alive. **For Kylo.**
