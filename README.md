# 🐉 Dunoon Daemon v2.1.0

**Dunoon Daemon** is a free, open-source, local-first Windows AI character, companion and autonomous roleplay app built around local GGUF models.

It is aimed at tabletop roleplayers, GMs, writers and anyone who wants persistent local characters rather than a hosted chatbot. The configured GGUF is the app's primary semantic brain; Python owns deterministic state, persistence and authority boundaries.

## What v2.1.0 does

- Persistent personas with OCEAN personality profiles, backstory, physiology, powers and relationships.
- Four Solo conversation modes: Continuation, Sandbox, Canvas and Bubble.
- Persona-scoped learned memory with Working, Deep, Journal, Intent, Task, Factual, Continuation, Reset and superseded-history handling.
- **Campaign Lore**: upload source material and explicitly assign which personas are allowed to retrieve it.
- **Arena**: two autonomous personas share a Director-governed SceneStore so actor prose cannot simply declare objective reality.
- Environment, Threat and Opportunity (ETO) grounding.
- Vision with compatible GGUF + `mmproj`, document upload, local/OS narration, transcript export, skins and tooltips.
- Dream maintenance, optional mortality/resurrection, crash recovery, Backup/Restore and Master Purge.
- Native `llama.cpp` / `llama-server` inference. There is no LM Studio fallback in the current architecture.

## Portable Windows release

The public v2.1.0 package is distributed as a normal ZIP rather than a giant self-extracting executable.

```text
DunoonDaemon_v2.1.0/
├── DunoonDaemon.exe
├── bin/                 # proven llama.cpp / CUDA / backend runtime
├── data/                # writable app state
├── models/              # optional place for your GGUF files
├── Dunoon_Daemon_App_THE_TOME_v2.1.0_PARCHMENT_EDITION.pdf
└── The_Goblins_Guide_to_Dunoon_Daemon_App_v2.1.0_PARCHMENT_EDITION.pdf
```

**Extract the whole ZIP before running it. Keep `bin` beside `DunoonDaemon.exe`.** No separate Python installation is required for the packaged release.

The entire Dunoon Daemon folder can be moved to another writable location or USB drive. The app resolves its writable state and native runtime relative to the executable.

The large native `bin/` runtime is intentionally not stored in normal Git history. It is bundled with the public portable release package.

## Five-minute start

1. Download a compatible GGUF instruct/chat model. Q4 or Q4_K_M is a sensible first try when available.
2. Extract the complete Dunoon Daemon release ZIP.
3. Keep `DunoonDaemon.exe` and `bin/` together.
4. Run `DunoonDaemon.exe`.
5. Create a persona, optionally Randomise its OCEAN profile, and save it.
6. Load your `.gguf` model.
7. Open **Continuation** and say hello.

For the beginner version, read **The Goblin's Guide**. For the full system, read **The Tome**. Both parchment PDFs are distributed with the portable release package.

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

`DunoonDaemon_portable.spec` freezes `modern_shell.py`, the imported Dunoon Daemon modules, Python and the required Python packages into a windowed `DunoonDaemon.exe`. It **does not** embed the large native `bin/` directory. The final release ZIP supplies that directory beside the EXE.

## Source layout

- `modern_shell.py` — modern application entry point.
- `dunoon_daemon.py`, `modern_daemon.py` — Solo conversation UI/behaviour.
- `modern_arena.py` and `core/` — Arena, Director, SceneStore and turn authority.
- `campaign_lore.py`, `modern_lore.py` — Campaign Lore library and retrieval UI.
- `memory_*.py`, `journal_*.py`, `release_support.py` — persistent memory, journaling, backup/recovery and diagnostics.
- `model_handler.py` — local `llama-server` lifecycle and GGUF loading.
- `persona*.py`, `character.py` — persona identity, import/export and OCEAN behaviour.
- `modern_theme.py`, `custom_skins.py`, `skin_manager.py` — interface theming.
- `DunoonDaemon_portable.spec`, `build_portable_exe.ps1` — Windows frozen build recipe.

Runtime-created JSON state, GGUF weights, build output and the large native runtime are ignored by Git.

## Authority rule in one paragraph

In Solo, the human establishes and can correct current external reality while the persona owns its own speech, intentions and voluntary actions. In Arena, the human establishes the starting scenario, then the Director owns shared external reality while each controlled persona owns itself. Learned memory is historical evidence, not present-world authority; current accepted reality outranks memory.

## Documentation

The portable release package includes:

- `Dunoon_Daemon_App_THE_TOME_v2.1.0_PARCHMENT_EDITION.pdf` - full operator's manual and systems guide.
- `The_Goblins_Guide_to_Dunoon_Daemon_App_v2.1.0_PARCHMENT_EDITION.pdf` - one-page beginner quickstart.

The current parchment PDFs are kept in the repository for reference and are also distributed with the portable release package.

## License

MIT License. See `LICENSE`.

Created by **sorvan76 (Kepler365) and ChatGPT — Human / AI Fusion (2026)**.

Dedicated to the loyal companions who walk with us through every realm, and the code that keeps their echoes alive. **For Kylo.**
