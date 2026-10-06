# -*- mode: python ; coding: utf-8 -*-
#
# VK Contest Analyzer — PyInstaller spec
# Run from the project root: pyinstaller vkca_web.spec --noconfirm
#
# Output: dist\VKContestAnalyzer\VKContestAnalyzer.exe  (one-folder)

import sys
import os
import re
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

ROOT = Path(SPECPATH)

# ── Hidden imports ────────────────────────────────────────────────────────────
hidden = []
hidden += collect_submodules('uvicorn')
hidden += collect_submodules('fastapi')
hidden += collect_submodules('starlette')
hidden += collect_submodules('anyio')
hidden += collect_submodules('multipart')
# bs4's parser backends (e.g. bs4.builder._htmlparser) are picked at runtime
# by name, which static analysis can miss — used by web/cosb.py's live-rank
# scraper (Contest Online ScoreBoard lookup).
hidden += collect_submodules('bs4')
hidden += collect_submodules('requests')
hidden += [
    'multipart',   # python-multipart — starlette imports it lazily on first
                    # form/file upload, so static analysis alone can miss it
    'uvicorn.logging',
    'uvicorn.loops.asyncio',
    'uvicorn.loops.auto',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.protocols.websockets.websockets_impl',
    'uvicorn.lifespan.on',
    'multiprocessing',
    'sqlite3',
    'csv',
    'io',
    'winreg',
]

# Add pywebview Windows backend if available
try:
    import webview
    hidden += collect_submodules('webview')
except ImportError:
    pass

# Add pywebview's GTK/WebKit2 backend on Linux, if available — lets the
# embedded window work instead of falling back to the default browser.
try:
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('WebKit2', '4.1')
    from gi.repository import Gtk, WebKit2
    hidden += ['gi', 'gi.repository.Gtk', 'gi.repository.WebKit2', 'gi.repository.Gdk', 'gi.repository.GLib']
except (ImportError, ValueError):
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

# Single canonical version file (see web/server.py's own VERSION read) —
# must land at _MEIPASS root, same as contest_log.py above.
datas += [(str(ROOT / 'VERSION'), '.')]

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
    pathex=[str(ROOT), str(ROOT / 'web')],
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
        # Only ever used by the removed /api/snapshot_png endpoint, which
        # nothing in the frontend calls — server.py has no other use of
        # any of these. Together they're over half the installed size.
        'matplotlib', 'numpy', 'PIL', 'contourpy', 'kiwisolver',
        # uvicorn[standard] extras we don't exercise: no --reload (no
        # watchfiles), h11 (already required) covers our HTTP parsing so
        # we don't need the httptools alternative, and we configure
        # logging ourselves (log_config=None) rather than via a YAML file.
        'watchfiles', 'httptools', 'yaml',
        # plugins/base.py does a try/except-guarded `import vkcontest_analyzer`
        # just to read theme colour constants — static analysis follows that
        # into vkcontest_analyzer.py's top-level `scipy` import. scipy needs
        # numpy (excluded above) to function, so it can never actually import
        # at runtime here; it's ~30MB of dead weight.
        'scipy',
        # Leaked in from the Linux build venv's --system-site-packages (needed
        # for GTK/WebKit2) via pygments.plugin's try/except pkg_resources
        # fallback (mako pulls in pygments too) — nothing in this app imports
        # any of these. Worse, on Debian/Ubuntu the system pkg_resources ships
        # a stripped _vendor tree (its jaraco deps are split into separate
        # apt packages that aren't installed here), so bundling it crashes
        # pyi_rth_pkgres.py at startup with "ImportError: The 'jaraco'
        # package is required".
        'pkg_resources', 'setuptools', 'pygments', 'mako', 'rich',
    ],
    noarchive=False,
)

# The gi/GTK hook pulls in every icon theme and GTK theme installed on the
# build machine's desktop (Mint-Y/Mint-L/Mint-X, Adwaita, Papirus, Bibata
# cursors, etc. — ~1.4GB uncompressed) because the venv has
# --system-site-packages access to them. pywebview's GTK backend only sets
# the window icon from our own file (Gtk.Window.set_icon_from_file) — it
# never resolves icons by theme name — so none of this is needed at runtime.
a.datas = [d for d in a.datas if not (d[0].startswith('share/icons' + os.sep)
                                      or d[0].startswith('share/themes' + os.sep)
                                      or d[0].startswith('share/icons/')
                                      or d[0].startswith('share/themes/'))]

# The gi hook also bundles libgtk-3/libgdk-3/libcairo/libpango/libglib/libatk
# etc. as shared libraries. WebKit2's actual rendering happens in separate
# WebKitWebProcess/WebKitNetworkProcess helper binaries owned by the
# system's libwebkit2gtk package — never bundled here, always loaded from
# /usr/lib — and those helpers inherit our process's LD_LIBRARY_PATH. If our
# bundled GTK/cairo/glib copies are found first, WebKit's compositor ends up
# talking to a different GTK/cairo build than the one its own libwebkit2gtk.so
# was compiled against, which reliably renders as a solid black window with
# no error on either side. Since libwebkit2gtk itself is never bundled (only
# available via the system's GI typelib), the whole GTK stack it depends on
# has to come from the system too — so drop our copies and let the dynamic
# linker fall through to /usr/lib for all of them.
_system_gtk_stack = re.compile(
    r'^lib(gtk|gdk|cairo|pango|glib|gobject|gio|atk|harfbuzz|epoxy|'
    r'fontconfig|freetype|fribidi|graphene|webkit)'
)
a.binaries = [b for b in a.binaries if not _system_gtk_stack.match(os.path.basename(b[0]))]

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