# -*- mode: python ; coding: utf-8 -*-
#
# VK Contest Analyzer — PyInstaller spec
# Run from the project root: pyinstaller vkca_web.spec --noconfirm
#
# Output: dist\VKContestAnalyzer\VKContestAnalyzer.exe  (one-folder)

import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

ROOT = Path(SPECPATH)

# ── Hidden imports ────────────────────────────────────────────────────────────
hidden = []
hidden += collect_submodules('uvicorn')
hidden += collect_submodules('fastapi')
hidden += collect_submodules('starlette')
hidden += collect_submodules('anyio')
hidden += [
    'uvicorn.logging',
    'uvicorn.loops.asyncio',
    'uvicorn.loops.auto',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.protocols.websockets.websockets_impl',
    'uvicorn.lifespan.on',
    'multiprocessing',
    'multiprocessing.freeze_support',
    'sqlite3',
    'csv',
    'io',
    'winreg',
    'matplotlib',
    'matplotlib.backends.backend_agg',
    'matplotlib.figure',
    'matplotlib.patches',
]

# Add pywebview Windows backend if available
try:
    import webview
    hidden += collect_submodules('webview')
except ImportError:
    pass

# ── Data files ────────────────────────────────────────────────────────────────
datas = []

# ── Data files ────────────────────────────────────────────────────────────────
datas = []

# Web frontend static files (Maps local web/static folder to _internal/static)
datas += [(str(ROOT / 'web' / 'static'), 'static')]

# Plugin directory
datas += [(str(ROOT / 'plugins'), 'plugins')]

# contest_log.py must be beside the exe
datas += [(str(ROOT / 'contest_log.py'), '.')]

# matplotlib data files (fonts, style sheets etc.)
try:
    datas += collect_data_files('matplotlib')
except Exception:
    pass

# pywebview assets
try:
    datas += collect_data_files('webview')
except Exception:
    pass

# ── Hooks path ────────────────────────────────────────────────────────────────
# Only add custom hooks folder if it exists — avoids FileNotFoundError
hooks_dir = ROOT / 'hooks'
hookspath = [str(hooks_dir)] if hooks_dir.exists() else []

# Runtime hook for multiprocessing freeze_support
# Only include if the file actually exists
rthook_path = hooks_dir / 'rthook_multiprocessing.py'
runtime_hooks = [str(rthook_path)] if rthook_path.exists() else []

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    [str(ROOT / 'web' / 'server.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=hookspath,
    hooksconfig={},
    runtime_hooks=runtime_hooks,
    excludes=[
        'tkinter', '_tkinter',
        'PyQt5', 'PyQt6', 'wx',
        'IPython', 'jupyter', 'notebook',
        'test', 'tests',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VKContestAnalyzer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / 'assets' / 'icon.ico') if (ROOT / 'assets' / 'icon.ico').exists() else None,
)

# ── COLLECT ───────────────────────────────────────────────────────────────────
# from PyInstaller.building.api import Tree  # Ensure Tree is imported

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    
    # ── FORCE FOLDERS TO ROOT NEXT TO EXE ─────────────────────────────────────
    Tree(str(ROOT / 'web' / 'static'), prefix='web/static'),
    Tree(str(ROOT / 'plugins'), prefix='plugins'),
    # ──────────────────────────────────────────────────────────────────────────
    
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VKContestAnalyzer',
)