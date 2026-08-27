# -*- mode: python ; coding: utf-8 -*-
"""Dunoon Daemon portable one-file Windows build."""

import os
from PyInstaller.utils.hooks import collect_all

base_dir = os.path.abspath(SPECPATH)

# The native llama.cpp/CUDA runtime is deliberately NOT embedded in this EXE.
# Public releases ship the proven ./bin directory beside DunoonDaemon.exe.
# config.py resolves BIN_DIR relative to sys.executable when frozen, preserving
# whole-folder / USB portability without a first-run extraction stage.
binaries = []

datas = [
    (os.path.join(base_dir, 'icon.ico'), '.'),
    (os.path.join(base_dir, 'VERSION.txt'), '.'),
]

hiddenimports = []
# Runtime-discovered modules need explicit collection in a frozen app.
for package in ('faster_whisper', 'ctranslate2', 'av', 'tokenizers', 'edge_tts', 'pyttsx3', 'pygame', 'PIL', 'pypdf', 'docx'):
    try:
        package_datas, package_bins, package_hidden = collect_all(package)
        datas += package_datas
        binaries += package_bins
        hiddenimports += package_hidden
    except Exception as exc:
        print(f'[PyInstaller collection warning] {package}: {exc}')

# No local .py files are added as data. Application modules are embedded in PYZ.
a = Analysis(
    ['modern_shell.py'],
    pathex=[base_dir],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='DunoonDaemon',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(base_dir, 'icon.ico'),
    onefile=True,
)
