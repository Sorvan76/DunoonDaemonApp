# -*- mode: python ; coding: utf-8 -*-
import os

block_cipher = None
base_dir = os.path.abspath(SPECPATH)

local_py_files = [
    (os.path.join(base_dir, f), '.') 
    for f in os.listdir(base_dir) 
    if f.endswith('.py') and f != 'controller.py'
]

datas = [
    (os.path.join(base_dir, 'splash_logo.png'), '.'),
    (os.path.join(base_dir, 'icon.ico'), '.')
] + local_py_files

# Explicit root asset mappings for PyInstaller 6+
root_assets = [
    ('splash_logo.png', os.path.join(base_dir, 'splash_logo.png'), 'DATA'),
    ('icon.ico', os.path.join(base_dir, 'icon.ico'), 'DATA')
]

a = Analysis(
    ['controller.py'],
    pathex=[base_dir],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'model_handler', 'brain', 'dunoon_daemon', 'session_manager',
        'overmind', 'memory_api', 'memory_deep', 'memory_integrity',
        'memory_router', 'memory_transfer', 'memory_validation',
        'memory_working', 'memory_embeddings', 'journal_entry',
        'journal_vault', 'vault_auto_repair', 'significance',
        'state_engine', 'skin_manager', 'tts_handler', 'eye_engine',
        'persona', 'prune', 'character', 'bridge', 'fetch_engine', 'config'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DunoonDaemon',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(base_dir, 'icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    root_assets,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DunoonDaemon',
)
