"""
VK Contest Analyzer — Web Server (v3)
======================================
Imports ContestLog directly from contest_log.py (no tkinter/matplotlib mock).
Launched by: python vkcontest_analyzer.py --web [path/to/log.s3db]
Or directly: python web/server.py [path/to/log.s3db]
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import queue
import re
import sys
import threading
import time
import socket
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# ── Path setup (works both normally and when frozen by PyInstaller) ───────────
import sys as _sys

def _get_base_path():
    """Return the base directory whether running normally or as a PyInstaller exe."""
    if getattr(_sys, 'frozen', False) and hasattr(_sys, '_MEIPASS'):
        # Running inside PyInstaller bundle — assets are in _MEIPASS
        return Path(_sys._MEIPASS)
    return Path(__file__).resolve().parent.parent   # normal: project root

_HERE   = Path(__file__).resolve().parent
_ROOT   = _get_base_path()
_STATIC = _ROOT / 'web' / 'static'

# In frozen mode _ROOT is _MEIPASS; in dev mode it's the project root.
sys.path.insert(0, str(_ROOT))

# A windowed (console=False) PyInstaller build has no console, so Windows
# leaves sys.stdout/stderr as None. Anything that calls .write()/.isatty()
# on them — e.g. uvicorn's default logging setup — crashes with
# "AttributeError: 'NoneType' object has no attribute 'isatty'" the moment
# it runs. Give them a harmless no-op stream instead of leaving them None.
if getattr(_sys, 'frozen', False):
    class _NullStream:
        def write(self, *a, **k): pass
        def flush(self, *a, **k): pass
        def isatty(self): return False
    if sys.stdout is None: sys.stdout = _NullStream()
    if sys.stderr is None: sys.stderr = _NullStream()

import uvicorn
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

# Direct import — no tkinter mocking needed
from contest_log import ContestLog
from plugins.loader import plugin_for, get_all_plugins
import cosb
import qrz

log = logging.getLogger(__name__)

def _app_data_dir() -> Path:
    """Per-user-writable app folder. A properly installed exe typically lives
    under Program Files, which standard (non-admin) users can't write to —
    writing files next to the exe there raises PermissionError immediately."""
    if getattr(sys, 'frozen', False):
        if sys.platform == 'win32':
            app_data = os.environ.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
        elif sys.platform == 'darwin':
            app_data = str(Path.home() / 'Library' / 'Application Support')
        else:
            app_data = os.environ.get('XDG_DATA_HOME') or str(Path.home() / '.local' / 'share')
        d = Path(app_data) / "VKContestAnalyzer"
        d.mkdir(parents=True, exist_ok=True)
        return d
    return Path(__file__).resolve().parent


def _setup_logging():
    log_dir = _app_data_dir()
    log_path = log_dir / "vkca_errors.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),   # still goes to console in dev mode
        ]
    )
    log.info(f"Log file: {log_path}")

_setup_logging()


# ── Persisted app settings (currently: user-added log-file folders) ──────────
# Separate from vkcontest_config.json, which belongs to the older tkinter
# desktop app — this is the web app's own small settings store, living
# alongside its log file in the per-user app-data folder.

_SETTINGS_PATH = _app_data_dir() / "vkca_web_settings.json"


def _load_settings() -> dict:
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_settings(settings: dict):
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


# ── QRZ.com lookup cache ──────────────────────────────────────────────────────
# Separate small JSON store (not folded into vkca_web_settings.json) since it
# can grow to one entry per unique callsign ever looked up — keeping it out of
# the settings file means a corrupt/huge cache can't also take down settings
# load/save. Callsign bio data (name/grid/state) rarely changes, so entries
# are cached for a long time (_QRZ_CACHE_TTL_SECS) rather than re-fetched
# every session.

_QRZ_CACHE_PATH = _app_data_dir() / "vkca_qrz_cache.json"
_QRZ_CACHE_TTL_SECS = 30 * 24 * 3600  # 30 days


def _load_qrz_cache() -> dict:
    try:
        with open(_QRZ_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_qrz_cache(cache: dict):
    _QRZ_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_QRZ_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# ── App state ─────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

class AppState:
    def __init__(self):
        self.db_path:       Optional[str]        = None
        self.contest_nr:    Optional[int]         = None
        self.plugin                               = None
        self.contest_log:   Optional[ContestLog]  = None
        self.last_snapshot: dict                  = {}
        self.last_mtime:    float                 = 0.0
        self.poll_interval: float                 = 5.0
        self._lock                                = threading.Lock()
        self._clients:      list                  = []
        self._webview_window                      = None  # set after webview starts
        self._base_url:     Optional[str]         = None  # set after webview starts; used by /api/popout
        self._hud_window                          = None  # the single Mini HUD window, if open
        self.yoy_extra_paths: list                = []    # extra .s3db files added on the YOY tab
        self.pace_extra_paths: list               = []    # [{"path":..., "kind":"s3db"|"adif"|"cabrillo"}]
        self.fatigue_extra_paths: list            = []    # extra .s3db files added on the Fatigue tab
        self.bandeff_extra_paths: list             = []    # extra .s3db files added on the Band Breakdown YoY view
        # Live-ranking lookup cache: {callsign: (fetched_at, result_or_None)}.
        # Keeps the Overview tab's Contest Online ScoreBoard panel from
        # re-scraping on every request — see /api/live_rank.
        self._live_rank_cache: dict               = {}
        self._live_rank_ttl:   float               = 120.0
        # QRZ.com lookup enrichment (see web/qrz.py) — _qrz_client.lookup_one()
        # only ever runs on the single QRZ worker thread (_qrz_worker_loop);
        # set_credentials()/has_credentials() are also called from the main/
        # poll threads (credential endpoints, _enrich_qsos), which is safe
        # since they're plain attribute reads/writes under the GIL, not a
        # network call. Everything else here is shared with those threads and
        # guarded by _qrz_cache_lock.
        self._qrz_client                          = qrz.QRZClient()
        self._qrz_cache:    dict                  = _load_qrz_cache()
        self._qrz_cache_lock                      = threading.Lock()
        self._qrz_queue                           = queue.Queue()
        self._qrz_inflight: set                   = set()   # calls queued/being looked up — dedup
        self._qrz_last_broadcast: float           = 0.0
        self._main_loop                           = None    # set in lifespan(); used by the QRZ worker to broadcast
        # Enrich All batch progress — reset by _qrz_enrich_all() to the size
        # of that batch, then _qrz_batch_remaining counts down as the worker
        # finishes each item (see _qrz_worker_loop). The same worker/queue
        # also processes calls queued by ordinary live enrichment, so if new
        # QSOs trickle in mid-batch this undercounts slightly (remaining can
        # plateau briefly) — fine for a progress indicator, not used for
        # anything correctness-sensitive. Guarded by _qrz_cache_lock.
        self._qrz_batch_total:     int             = 0
        self._qrz_batch_remaining: int             = 0

    # ── Path validation (no DB open) ─────────────────────────────────────────

    # N1MM itself only ever writes .s3db, but the schema (DXLOG/ContestInstance/
    # Contest tables) is just SQLite — compatible loggers like NotN1MM (a Linux
    # N1MM alternative) write the identical schema to a plain .db file. sqlite3
    # doesn't care about extensions at all, so neither should we.
    _VALID_SUFFIXES = (".s3db", ".db", ".sqlite")

    @staticmethod
    def validate_path(path: str) -> Optional[str]:
        """Return an error string, or None if the path looks valid."""
        p = Path(path)
        if not p.exists():
            return f"File not found: {path}"
        if p.is_dir():
            return (f"That is a folder, not a file. "
                    f"Please select a log file inside: {path}")
        if p.suffix.lower() not in AppState._VALID_SUFFIXES:
            return f"Expected a .s3db/.db/.sqlite file, got: {p.name}"
        return None

    # ── Scan contests (read-only, no ContestLog instance created) ────────────

    def scan_contests(self, path: str) -> dict:
        path = str(Path(path).resolve())
        err  = self.validate_path(path)
        if err:
            return {"error": err}
        try:
            contests = ContestLog.available_contests(path)
            result   = []
            for ct in contests:
                p = plugin_for(str(ct.get("ContestName", "")))
                result.append({
                    "contest_nr":   ct["ContestNR"],
                    "contest_name": ct.get("ContestName", ""),
                    "display_name": ct.get("DisplayName", ct.get("ContestName", "")),
                    "start_date":   str(ct.get("StartDate", ""))[:10],
                    "qso_count":    ct.get("QSOCount", 0),
                    "plugin":       p.display_name,
                })
            return {"ok": True, "path": path, "contests": result}
        except Exception as exc:
            log.exception("scan_contests failed")
            return {"error": str(exc)}

    # ── Full load (creates ContestLog + compute_snapshot) ────────────────────

    def load_db(self, path: str, contest_nr: Optional[int] = None,
                plugin=None) -> dict:
        path = str(Path(path).resolve())
        err  = self.validate_path(path)
        if err:
            return {"error": err}
        try:
            cl = ContestLog(path, contest_nr=contest_nr, plugin=plugin)
            with self._lock:
                self.db_path      = path
                self.contest_nr   = contest_nr
                self.plugin       = plugin
                self.contest_log  = cl
                self._enrich_qsos(cl)
                self.last_mtime   = os.path.getmtime(path)
                self.last_snapshot = self._safe_snapshot()
            return {"ok": True, "path": path}
        except Exception as exc:
            log.exception("load_db failed")
            return {"error": str(exc)}

    def _safe_snapshot(self) -> dict:
        if not self.contest_log:
            return {}
        try:
            return _json_safe(self.contest_log.compute_snapshot())
        except Exception as exc:
            log.exception("compute_snapshot failed")
            return {"error": str(exc)}

    def poll_once(self, force: bool = False) -> bool:
        """Check mtime; reload ContestLog if changed (or always, if force).
        Returns True if updated."""
        if not self.db_path or not os.path.isfile(self.db_path):
            return False
        try:
            mtime = os.path.getmtime(self.db_path)
        except OSError:
            return False
        if not force and mtime <= self.last_mtime:
            return False
        try:
            cl = ContestLog(self.db_path,
                            contest_nr=self.contest_nr,
                            plugin=self.plugin)
            with self._lock:
                self.contest_log   = cl
                self._enrich_qsos(cl)
                self.last_mtime    = mtime
                self.last_snapshot = self._safe_snapshot()
            return True
        except Exception:
            log.exception("poll_once reload failed")
            return False

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self.last_snapshot)

    # ── QRZ.com lookup enrichment ─────────────────────────────────────────────
    # Called with self._lock already held (see load_db()/poll_once() above) —
    # ContestLog is rebuilt from scratch on every reload, so every QSO here
    # starts blank and needs its qrz_* fields re-filled from the cache each
    # time, even for calls looked up in a previous cycle.

    def _enrich_qsos(self, cl: ContestLog):
        now = time.time()
        seen_calls = set()
        for call in {(q.get("call") or "").upper() for q in cl.qsos}:
            if not call or call in seen_calls:
                continue
            seen_calls.add(call)
            with self._qrz_cache_lock:
                cached = self._qrz_cache.get(call)
            if cached:
                self._apply_qrz_result(cl, call, cached)
            stale = not cached or (now - cached.get("fetched_at", 0)) > _QRZ_CACHE_TTL_SECS
            if stale and self._qrz_client.has_credentials():
                if not cached:
                    self._set_qrz_status(cl, call, "pending")
                self._qrz_enqueue(call)

    @staticmethod
    def _apply_qrz_result(cl: ContestLog, call: str, entry: dict):
        status = "found" if entry.get("found") else "not_found"
        for q in cl.qsos:
            if (q.get("call") or "").upper() == call:
                q["qrz_name"]  = entry.get("name", "")
                q["qrz_grid"]  = entry.get("grid", "")
                q["qrz_state"] = entry.get("state", "")
                q["qrz_status"] = status

    @staticmethod
    def _set_qrz_status(cl: ContestLog, call: str, status: str):
        for q in cl.qsos:
            if (q.get("call") or "").upper() == call:
                q["qrz_status"] = status

    def _qrz_enqueue(self, call: str):
        with self._qrz_cache_lock:
            if call in self._qrz_inflight:
                return
            self._qrz_inflight.add(call)
        self._qrz_queue.put(call)

    def _qrz_clear_queue(self):
        """Drops every pending lookup — called when credentials are removed
        so the titlebar's 'N left' badge doesn't keep ticking down for
        several more minutes as the worker drains a now-pointless backlog
        (has_credentials() is false, so it would skip every one of them
        anyway — see _qrz_worker_loop). Leaves in-flight network calls (if
        any) to finish naturally; those are already out of the queue."""
        with self._qrz_cache_lock:
            try:
                while True:
                    self._qrz_queue.get_nowait()
                    self._qrz_queue.task_done()
            except queue.Empty:
                pass
            self._qrz_inflight.clear()
            self._qrz_batch_total = 0
            self._qrz_batch_remaining = 0


# ── JSON serialiser ───────────────────────────────────────────────────────────

def _json_safe(obj):
    from datetime import datetime, date
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()
                if not k.startswith("_")}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, float) and obj != obj:  # NaN
        return None
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


# ═══════════════════════════════════════════════════════════════════════════════
# ── FastAPI app ───────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

STATE = AppState()


# ── QRZ.com lookup: cache accessors + background worker ──────────────────────
# See web/qrz.py for the API client itself. Everything here runs off the
# asyncio event loop — the worker is a plain daemon thread — except
# _qrz_maybe_broadcast(), which hops back onto the event loop via
# run_coroutine_threadsafe() since _broadcast() is a coroutine.

def _qrz_cache_get(call: str) -> Optional[dict]:
    with STATE._qrz_cache_lock:
        return STATE._qrz_cache.get(call.upper())


def _qrz_cache_put(call: str, entry: dict):
    with STATE._qrz_cache_lock:
        STATE._qrz_cache[call.upper()] = entry
        snapshot = dict(STATE._qrz_cache)
    _save_qrz_cache(snapshot)  # file I/O outside the lock


def _qrz_maybe_broadcast():
    """Debounced so a big Enrich All batch doesn't flood the WebSocket with
    a broadcast per callsign — coalesces bursts into ~1 update/1.5s, but
    still fires promptly once the queue drains so the last few results
    aren't left waiting for the next poll cycle.

    Recomputes last_snapshot instead of reusing STATE.snapshot()'s cached
    copy: compute_snapshot()'s output (last_worked, etc.) is deep-copied
    into JSON-safe values via _json_safe(), so the cached last_snapshot
    holds no live references back into STATE.contest_log.qsos — patching
    a QSO dict in place (_apply_qrz_result, just above this call in
    _qrz_worker_loop) doesn't retroactively update it. Without this, a
    result the worker just resolved wouldn't reach any client's Overview
    tab (last_worked comes only from this broadcast) until an unrelated
    new QSO happened to trigger poll_once()'s own recompute."""
    now = time.time()
    if now - STATE._qrz_last_broadcast < 1.5 and not STATE._qrz_queue.empty():
        return
    STATE._qrz_last_broadcast = now
    if STATE._main_loop is not None:
        with STATE._lock:
            STATE.last_snapshot = STATE._safe_snapshot()
            snap = dict(STATE.last_snapshot)
        asyncio.run_coroutine_threadsafe(_broadcast(snap), STATE._main_loop)


def _qrz_worker_loop():
    """Single background worker — processes one callsign at a time so a
    pileup with many new unique calls at once doesn't hammer QRZ's servers
    (they throttle abusive usage). Runs for the lifetime of the process; the
    app has no graceful-shutdown path (os._exit on window close, see
    _on_closed() in launch_webview()), so this daemon thread needs no
    explicit stop signal."""
    while True:
        call = STATE._qrz_queue.get()
        try:
            if not STATE._qrz_client.has_credentials():
                continue
            result = STATE._qrz_client.lookup_one(call)  # blocking network call
            if result is None:
                # Transient failure — leave uncached so the next poll
                # cycle's _enrich_qsos() naturally re-queues it.
                continue
            entry = {**result, "fetched_at": time.time()}
            _qrz_cache_put(call, entry)
            with STATE._lock:
                if STATE.contest_log:
                    STATE._apply_qrz_result(STATE.contest_log, call, entry)
            _qrz_maybe_broadcast()
        except Exception:
            log.exception("QRZ worker failed processing %s", call)
        finally:
            with STATE._qrz_cache_lock:
                STATE._qrz_inflight.discard(call)
                if STATE._qrz_batch_remaining > 0:
                    STATE._qrz_batch_remaining -= 1
            STATE._qrz_queue.task_done()
            time.sleep(1.0)  # politeness delay between requests


@asynccontextmanager
async def lifespan(application: FastAPI):
    STATE._main_loop = asyncio.get_running_loop()
    creds = _load_settings().get("qrz_credentials")
    if creds:
        STATE._qrz_client.set_credentials(creds.get("username"), creds.get("password"))
    threading.Thread(target=_qrz_worker_loop, daemon=True, name="qrz-worker").start()
    asyncio.create_task(_poll_loop())
    yield


app = FastAPI(title="VK Contest Analyzer Web", lifespan=lifespan)

_STATIC = _HERE / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(_STATIC / "index.html"))


@app.get("/hud")
async def hud_page():
    """Serves the same SPA — index.html's bootstrap script detects this path
    and renders hud-mode instead. A dedicated path (not a query string) is
    used because pywebview/WebView2 was observed dropping query strings
    entirely when navigating a secondary window created via create_window()."""
    return FileResponse(str(_STATIC / "index.html"))


@app.get("/popout/{key:path}")
async def popout_page(key: str):
    """Serves the same SPA — index.html's bootstrap script detects this path
    and isolates the matching tile. See hud_page() for why this is a path,
    not a query string."""
    return FileResponse(str(_STATIC / "index.html"))


# ── Status ────────────────────────────────────────────────────────────────────

@app.get("/api/status")
async def api_status():
    return {
        "loaded":     STATE.contest_log is not None,
        "db_path":    STATE.db_path,
        "contest_nr": STATE.contest_nr,
        "plugin":     getattr(STATE.plugin, "display_name", None),
    }


# ── Supported contest plugins (shown on the splash screen) ───────────────────

@app.get("/api/plugins")
async def api_plugins():
    try:
        plugins = get_all_plugins()
    except Exception:
        log.exception("get_all_plugins failed")
        plugins = []
    return [
        {
            "display_name": getattr(p, "display_name", type(p).__name__),
            "class_name":    type(p).__name__,
        }
        for p in plugins
    ]


# ── Native file browse (pywebview) ────────────────────────────────────────────

@app.get("/api/browse")
async def api_browse():
    """Trigger the OS native file-open dialog via pywebview."""
    win = STATE._webview_window
    if win is None:
        return JSONResponse({"error": "PyWebView window not ready"}, status_code=503)
    try:
        import webview as _wv
        # OPEN_DIALOG = 10  (FOLDER_DIALOG = 20 — that was the old bug)
        result = win.create_file_dialog(
            dialog_type=_wv.FileDialog.OPEN,
            allow_multiple=False,
            file_types=("Contest Log Files (*.s3db;*.db;*.sqlite)", "All files (*.*)")
        )
        if not result:
            return {"path": None}
        chosen = str(result[0])
        # Guard: pywebview may return a directory if the user didn't select a file
        if os.path.isdir(chosen):
            return JSONResponse(
                {"error": f"Selected a folder, not a log file: {chosen}"},
                status_code=400)
        return {"path": chosen}
    except Exception as exc:
        log.exception("browse failed")
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/browse_folder")
async def api_browse_folder():
    """Trigger the OS native folder-open dialog via pywebview — used to add a
    custom folder to search for contest databases (see /api/settings/log_dirs).
    Falls back to manual path entry in the UI if pywebview isn't available."""
    win = STATE._webview_window
    if win is None:
        return JSONResponse({"error": "PyWebView window not ready"}, status_code=503)
    try:
        import webview as _wv
        result = win.create_file_dialog(dialog_type=_wv.FileDialog.FOLDER)
        if not result:
            return {"path": None}
        return {"path": str(result[0])}
    except Exception as exc:
        log.exception("browse_folder failed")
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Auto-discover contest databases in well-known + user-added locations ─────
# N1MM Logger+ always keeps user contest databases in this folder alongside a
# handful of its own internal system databases (admin log, packet spot cache)
# — those aren't contest logs, so they're filtered out by name. Other loggers
# (e.g. NotN1MM on Linux) don't share that folder, so users can add their own
# via /api/settings/log_dirs — persisted in _SETTINGS_PATH, not hardcoded.

_N1MM_SYSTEM_DBS = {"n1mm admin.s3db", "n1mm dxlog.s3db", "n1mm packet spots.s3db"}


def _default_log_dir() -> Path:
    return Path.home() / "Documents" / "N1MM Logger+" / "Databases"


def _not1mm_default_log_dir() -> Optional[Path]:
    """not1mm (the Linux-native N1MM-alike) keeps ham.db under the XDG data
    dir — same XDG_DATA_HOME convention as _app_data_dir() above."""
    if not sys.platform.startswith("linux"):
        return None
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "not1mm"


def _custom_log_dirs() -> list:
    return list(_load_settings().get("log_dirs", []))


def _known_log_dirs() -> list:
    """Default N1MM folder, default not1mm folder (Linux only), plus every
    user-added folder, de-duplicated."""
    defaults = [str(_default_log_dir())]
    not1mm_dir = _not1mm_default_log_dir()
    if not1mm_dir is not None:
        defaults.append(str(not1mm_dir))
    seen, dirs = set(), []
    for raw in defaults + _custom_log_dirs():
        key = os.path.normcase(os.path.normpath(raw))
        if key in seen:
            continue
        seen.add(key)
        dirs.append(Path(raw))
    return dirs


@app.get("/api/settings/log_dirs")
async def api_get_log_dirs():
    """List user-added folders to search for contest databases, plus whether
    each still exists on disk (shown greyed-out/removable in the UI if not)."""
    not1mm_dir = _not1mm_default_log_dir()
    return {
        "default_dir": str(_default_log_dir()),
        "not1mm_default_dir": str(not1mm_dir) if not1mm_dir is not None else None,
        "dirs": [{"path": d, "exists": Path(d).is_dir()} for d in _custom_log_dirs()],
    }


@app.post("/api/settings/log_dirs")
async def api_add_log_dir(body: dict):
    """Add a folder to search for contest databases (e.g. where NotN1MM or
    another non-N1MM logger keeps its .db files)."""
    path = (body.get("path") or "").strip()
    if not path:
        return JSONResponse({"error": "No path supplied"}, status_code=400)
    p = Path(path).expanduser()
    if not p.is_dir():
        return JSONResponse({"error": f"Not a folder: {path}"}, status_code=400)
    resolved = str(p.resolve())
    settings = _load_settings()
    dirs = settings.setdefault("log_dirs", [])
    key = os.path.normcase(os.path.normpath(resolved))
    if not any(os.path.normcase(os.path.normpath(d)) == key for d in dirs):
        dirs.append(resolved)
        _save_settings(settings)
    return {"ok": True, "dirs": dirs}


@app.delete("/api/settings/log_dirs")
async def api_remove_log_dir(body: dict):
    path = (body.get("path") or "").strip()
    settings = _load_settings()
    dirs = settings.setdefault("log_dirs", [])
    key = os.path.normcase(os.path.normpath(path))
    dirs[:] = [d for d in dirs if os.path.normcase(os.path.normpath(d)) != key]
    _save_settings(settings)
    return {"ok": True, "dirs": dirs}


# ── QRZ.com lookup settings ───────────────────────────────────────────────────
# See web/qrz.py for the API client and the _qrz_* helpers/worker above STATE
# for the enrichment pipeline itself. Credentials live in the same plaintext
# settings store as everything else here (log_dirs, window_geometry) — same
# trust model as N1MM's own unencrypted database.

@app.get("/api/qrz/credentials")
async def api_qrz_credentials_get():
    creds = _load_settings().get("qrz_credentials")
    return {"configured": bool(creds), "username": (creds or {}).get("username")}


def _qrz_test_and_save(username: str, password: str) -> dict:
    """Runs in a thread executor — attempts a real QRZ login before saving,
    so a typo'd password fails loudly in the settings dialog instead of
    silently failing later in the background worker."""
    try:
        qrz.login(username, password)
    except qrz.QRZAuthError as e:
        return {"error": str(e) or "Invalid QRZ username/password."}
    except qrz.QRZError as e:
        return {"error": f"Could not reach QRZ.com: {e}"}
    settings = _load_settings()
    settings["qrz_credentials"] = {"username": username, "password": password}
    _save_settings(settings)
    STATE._qrz_client.set_credentials(username, password)
    return {"ok": True, "username": username}


@app.post("/api/qrz/credentials")
async def api_qrz_credentials_post(body: dict):
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not password:
        # Blank password with credentials already saved means "keep the
        # existing one" — GET /api/qrz/credentials never sends the real
        # password back to the frontend for it to resubmit, so this is the
        # only way to e.g. re-test the connection or change just the
        # username without retyping a password the user may not have handy.
        existing = _load_settings().get("qrz_credentials") or {}
        password = existing.get("password") or ""
    if not username or not password:
        return JSONResponse({"error": "Username and password required"}, status_code=400)
    result = await asyncio.get_event_loop().run_in_executor(
        None, _qrz_test_and_save, username, password)
    if "error" in result:
        return JSONResponse(result, status_code=400)
    return result


@app.delete("/api/qrz/credentials")
async def api_qrz_credentials_delete():
    settings = _load_settings()
    settings.pop("qrz_credentials", None)
    _save_settings(settings)
    STATE._qrz_client.set_credentials(None, None)
    STATE._qrz_clear_queue()
    return {"ok": True}


def _qrz_enrich_all() -> dict:
    with STATE._lock:
        cl = STATE.contest_log
        if not cl:
            return {"queued": 0, "already_cached": 0, "total_calls": 0, "error": "No log loaded"}
        calls = {(q.get("call") or "").upper() for q in cl.qsos if q.get("call")}
    queued = cached_n = 0
    for call in calls:
        if _qrz_cache_get(call) is not None:
            cached_n += 1
            continue
        STATE._qrz_enqueue(call)
        queued += 1
    with STATE._qrz_cache_lock:
        STATE._qrz_batch_total = queued
        STATE._qrz_batch_remaining = queued
    return {"queued": queued, "already_cached": cached_n, "total_calls": len(calls)}


@app.post("/api/qrz/enrich_all")
async def api_qrz_enrich_all():
    if not STATE._qrz_client.has_credentials():
        return JSONResponse({"error": "QRZ credentials not configured"}, status_code=400)
    return await asyncio.get_event_loop().run_in_executor(None, _qrz_enrich_all)


@app.get("/api/qrz/status")
async def api_qrz_status():
    with STATE._qrz_cache_lock:
        cache_size      = len(STATE._qrz_cache)
        in_flight       = len(STATE._qrz_inflight)
        batch_total     = STATE._qrz_batch_total
        batch_remaining = STATE._qrz_batch_remaining
    return {
        "configured": STATE._qrz_client.has_credentials(),
        "queue_depth": STATE._qrz_queue.qsize(),
        "in_flight": in_flight,
        "cache_size": cache_size,
        # Enrich All batch progress (0/0 if no batch has run this session).
        # The worker throttles to ~1 lookup/sec (see _qrz_worker_loop), so
        # batch_remaining also doubles as a rough ETA in seconds.
        "batch_total": batch_total,
        "batch_remaining": batch_remaining,
    }


@app.get("/api/scan_known_locations")
async def api_scan_known_locations():
    """Look for contest databases in N1MM's default folder plus any
    user-added folders, so the user doesn't have to browse to/type a path
    for the common case."""
    found = []
    for d in _known_log_dirs():
        if not d.is_dir():
            continue
        for suffix in AppState._VALID_SUFFIXES:
            for f in d.glob(f"*{suffix}"):
                if f.name.lower() in _N1MM_SYSTEM_DBS:
                    continue
                try:
                    st = f.stat()
                except OSError:
                    continue
                found.append({
                    "path":  str(f),
                    "name":  f.name,
                    "size":  st.st_size,
                    "mtime": st.st_mtime,
                })
    found.sort(key=lambda r: r["mtime"], reverse=True)
    return {"databases": found, "os": sys.platform}


# ── Pop-out tile window (pywebview) ───────────────────────────────────────────

@app.post("/api/popout")
async def api_popout(body: dict):
    """Open a single Overview tile in its own pywebview window (/popout/<key>)."""
    key = (body.get("key") or "").strip()
    if not key:
        return JSONResponse({"error": "No key supplied"}, status_code=400)
    if STATE._webview_window is None or not STATE._base_url:
        return JSONResponse({"error": "PyWebView window not ready"}, status_code=503)

    title  = (body.get("title") or "Tile").strip()
    width  = int(body.get("width")  or 480)
    height = int(body.get("height") or 380)

    def _open():
        import webview as _wv
        from urllib.parse import quote
        _wv.create_window(
            title=f"{title} — VK Contest Analyzer",
            url=f"{STATE._base_url}/popout/{quote(key, safe='')}",
            width=width, height=height,
            min_size=(240, 180),
            background_color="#0d1117",
        )

    try:
        await asyncio.get_event_loop().run_in_executor(None, _open)
        return {"ok": True}
    except Exception as exc:
        log.exception("popout failed")
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/hud")
async def api_hud():
    """Open the tiny always-on-top score/rate HUD (/hud) in its own
    pywebview window. Reuses/restores the existing HUD window instead of
    spawning a new one if one is already open."""
    if STATE._webview_window is None or not STATE._base_url:
        return JSONResponse({"error": "PyWebView window not ready"}, status_code=503)

    existing = STATE._hud_window
    if existing is not None:
        def _restore():
            try:
                existing.restore()
            except Exception:
                pass
        await asyncio.get_event_loop().run_in_executor(None, _restore)
        return {"ok": True, "reused": True}

    def _open():
        import webview as _wv
        win = _wv.create_window(
            title="VK Contest Analyzer — HUD",
            url=f"{STATE._base_url}/hud",
            width=700, height=110,
            min_size=(360, 76),
            background_color="#0d1117",
            on_top=True,
        )
        STATE._hud_window = win
        win.events.closed += lambda: setattr(STATE, "_hud_window", None)

    try:
        await asyncio.get_event_loop().run_in_executor(None, _open)
        return {"ok": True}
    except Exception as exc:
        log.exception("hud failed")
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/upload_log")
async def api_upload_log(file: UploadFile = File(...)):
    """Browser-fallback file picker (no pywebview window available): saves
    the uploaded file to a temp path on this same machine and hands back
    that path, so the rest of the load/scan flow can treat it exactly like
    a path chosen via the native dialog."""
    import tempfile
    import shutil
    try:
        name = os.path.basename(file.filename or "upload")
        tmp_dir = Path(tempfile.gettempdir()) / "vkca_uploads"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        dest = tmp_dir / name
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)
        return {"path": str(dest)}
    except Exception as exc:
        log.exception("upload failed")
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Scan contests in a .s3db (no full load) ───────────────────────────────────

@app.post("/api/scan")
async def api_scan(body: dict):
    """Validate path and list contests — does NOT load QSOs."""
    path = (body.get("path") or "").strip()
    if not path:
        return JSONResponse({"error": "No path supplied"}, status_code=400)
    result = await asyncio.get_event_loop().run_in_executor(
        None, STATE.scan_contests, path
    )
    return result


# ── Full load ─────────────────────────────────────────────────────────────────

@app.post("/api/load")
async def api_load(body: dict):
    """Load QSOs for a specific contest.  Body: {path, contest_nr, plugin_name}"""
    path = (body.get("path") or "").strip()
    if not path:
        return JSONResponse({"error": "No path supplied"}, status_code=400)

    contest_nr  = body.get("contest_nr")
    plugin_name = body.get("plugin_name") or ""
    plugin      = plugin_for(plugin_name) if plugin_name else None

    result = await asyncio.get_event_loop().run_in_executor(
        None, STATE.load_db, path, contest_nr, plugin
    )
    if "ok" in result:
        await _broadcast(STATE.snapshot())
    return result


# ── Data endpoints ────────────────────────────────────────────────────────────

@app.get("/api/snapshot")
async def api_snapshot():
    if STATE.db_path:
        await asyncio.get_event_loop().run_in_executor(None, STATE.poll_once, True)
    return STATE.snapshot()


def _live_rank_state() -> dict:
    """Look up the loaded log's own callsign on Contest Online ScoreBoard,
    using a short-TTL cache so the Overview panel's poll doesn't hit COSB on
    every request. Runs in a thread executor — fetch_live_rank() is a
    blocking network call."""
    with STATE._lock:
        cl = STATE.contest_log
    call = getattr(cl, "my_call", None) if cl else None
    if not call:
        return {"available": False, "reason": "no_callsign"}

    cached = STATE._live_rank_cache.get(call)
    now = time.time()
    if cached and (now - cached[0]) < STATE._live_rank_ttl:
        result = cached[1]
    else:
        result = cosb.fetch_live_rank(call)
        STATE._live_rank_cache[call] = (now, result)

    if result is None:
        return {"available": False, "reason": "no_live_data", "call": call}
    return {"available": True, "call": call, **result}


@app.get("/api/live_rank")
async def api_live_rank():
    return await asyncio.get_event_loop().run_in_executor(None, _live_rank_state)


# ── Replay scrubber ───────────────────────────────────────────────────────────

@app.get("/api/scrub_range")
async def api_scrub_range():
    """Returns the [earliest, latest] QSO timestamps — the scrubber's bounds."""
    with STATE._lock:
        cl = STATE.contest_log
        if not cl or not cl.qsos:
            return {"start": None, "end": None}
        times = [q["time"] for q in cl.qsos]
        return {"start": min(times).isoformat(), "end": max(times).isoformat()}


@app.get("/api/scrub")
async def api_scrub(t: str):
    """Recompute the Overview snapshot using only QSOs at or before time `t`
    (ISO 8601, naive UTC) — powers dragging the replay scrubber."""
    try:
        cutoff = datetime.fromisoformat(t)
    except ValueError:
        return JSONResponse({"error": "Invalid time"}, status_code=400)
    with STATE._lock:
        cl = STATE.contest_log
        if not cl:
            return JSONResponse({"error": "No contest loaded"}, status_code=400)
        try:
            snap = cl.compute_snapshot_at(cutoff)
        except Exception as exc:
            log.exception("scrub failed")
            return JSONResponse({"error": str(exc)}, status_code=500)
    return _json_safe(snap)


@app.get("/api/missing")
async def api_missing():
    with STATE._lock:
        if not STATE.contest_log:
            return []
        try:
            mbr = STATE.contest_log.mults_by_region()
        except Exception:
            return []
    rows = []
    for region, data in mbr.items():
        for m in data.get("missing", []):
            rows.append({"mult": m, "region": region})
    rows.sort(key=lambda r: (r["region"], r["mult"]))
    return rows


@app.post("/api/replay_whatif")
async def api_replay_whatif(body: dict):
    """'What if I worked this missing mult on this band right now?' The
    synthetic QSO is scored in total isolation via recalc_pts() on a
    one-item list and then discarded — the real QSO list is never mutated
    or even copied into the same list as the synthetic entry, since several
    plugins' recalc_pts() mutates QSO dicts in place."""
    mult = (body.get("mult") or "").strip()
    band = (body.get("band") or "").strip().upper()
    zone = body.get("zone")
    if not mult or not band:
        return JSONResponse({"error": "mult and band are required"}, status_code=400)

    with STATE._lock:
        if not STATE.contest_log:
            return JSONResponse({"error": "No log loaded"}, status_code=400)
        plugin = STATE.contest_log.plugin
        qsos   = list(STATE.contest_log.qsos)

    try:
        valid_mults = set(plugin.mult_list())
    except Exception:
        valid_mults = set()
    if valid_mults and mult not in valid_mults:
        return JSONResponse({"error": f"'{mult}' is not a recognized multiplier for this contest"}, status_code=400)

    try:
        zone_int = int(zone) if zone not in (None, "") else None
    except (TypeError, ValueError):
        zone_int = None

    try:
        is_new_mult = mult not in plugin.worked_primary_mults(qsos)
    except Exception:
        is_new_mult = True

    # Dominant mode already logged, as a sane default for the synthetic QSO.
    mode_counts: dict = {}
    for q in qsos:
        m = q.get("mode")
        if m:
            mode_counts[m] = mode_counts.get(m, 0) + 1
    default_mode = max(mode_counts, key=mode_counts.get) if mode_counts else "CW"

    synthetic = {
        "call": "WHATIF", "band": band, "mode": default_mode,
        "mult1": mult, "mult2": mult, "cqz": zone_int, "raw_mult": mult,
        "dupe": False, "is_mult1": 1, "is_mult2": 1 if zone_int is not None else 0,
        "time": datetime.utcnow(), "pts": 0,
    }

    caveat = None
    try:
        plugin.recalc_pts([synthetic])
    except Exception:
        log.exception("what-if replay: recalc_pts failed for plugin %s", getattr(plugin, "display_name", "?"))
        caveat = "Could not estimate an exact point value for this contest type — treat as approximate."

    pts_delta = synthetic.get("pts") or 0
    if pts_delta <= 0 and caveat is None:
        caveat = "This contest's scoring doesn't expose a per-QSO point estimate here — treat the point delta as approximate."
    if zone_int is None and plugin.uses_cq_zone_scoring():
        zone_note = "Enter a CQ zone for exact scoring in this contest."
        caveat = f"{caveat} {zone_note}" if caveat else zone_note

    return {
        "band": band, "mult": mult, "pts_delta": pts_delta,
        "is_new_mult": is_new_mult, "caveat": caveat,
    }


@app.get("/api/bands")
async def api_bands():
    return STATE.snapshot().get("band_efficiency", [])


@app.get("/api/band_advice")
async def api_band_advice():
    """Best-value band right now, using the same per-band QSO value estimate
    that feeds the Overview tab's 'QSO VALUE' panel — CQWW's own model where
    the plugin implements one, otherwise ContestLog's generic
    points-times-mults fallback that works for any contest type."""
    with STATE._lock:
        if not STATE.contest_log:
            return {"recommended_band": None}
        cl     = STATE.contest_log
        plugin = cl.plugin
        qsos   = list(cl.qsos)
    try:
        est = cl._qso_value_estimate(qsos, plugin)
    except Exception:
        est = None
    if not est:
        return {"recommended_band": None}

    current_band = None
    timed = [(q["time"], q["band"]) for q in qsos
             if not q.get("dupe") and q.get("time") and q.get("band")]
    if timed:
        current_band = max(timed, key=lambda t: t[0])[1]

    best_band, best_val = None, -1.0
    for band, data in est.get("bands", {}).items():
        if band == current_band:
            continue
        val = data.get("one_mult", 0) or 0
        if val > best_val:
            best_band, best_val = band, val

    if best_band is None:
        return {"recommended_band": None}
    return {
        "recommended_band": best_band,
        "avg_pts":  est["bands"][best_band].get("avg_pts", 0),
        "one_mult_value": best_val,
        "reason": f"Working a new mult on {best_band} is currently worth ~{round(best_val):,} pts",
    }


@app.get("/api/worked")
async def api_worked():
    return STATE.snapshot().get("last_worked", [])



@app.get("/api/rate")
async def api_rate():
    with STATE._lock:
        if not STATE.contest_log:
            return []
        try:
            raw = STATE.contest_log.rate_by_hour()
            return [{"hour": h.isoformat(), "qsos": n} for h, n in raw]
        except Exception:
            return []

@app.get("/api/sessions")
async def api_sessions():
    with STATE._lock:
        if not STATE.contest_log:
            return []
        try:
            return _json_safe(STATE.contest_log.rate_by_session())
        except Exception:
            return []

@app.get("/api/dupes")
async def api_dupes():
    with STATE._lock:
        if not STATE.contest_log:
            return {"by_band": {}, "by_call": {}}
        try:
            by_band, by_call = STATE.contest_log.dupe_analysis()
            return {
                "by_band": dict(by_band),
                "by_call": dict(sorted(by_call.items(),
                                       key=lambda x: x[1], reverse=True)[:50]),
                "rule_text": STATE.contest_log.plugin.dupe_rule_text,
            }
        except Exception:
            return {"by_band": {}, "by_call": {}}

@app.get("/api/qsos")
async def api_qsos():
    """Full QSO list (all fields, sorted by time)."""
    with STATE._lock:
        if not STATE.contest_log:
            return []
        try:
            return _json_safe(STATE.contest_log.qso_timeline())
        except Exception:
            return []

@app.get("/api/operators")
async def api_operators():
    snap = STATE.snapshot()
    return snap.get("operator_times", [])


def _delete_qsos(qso_ids: list) -> dict:
    with STATE._lock:
        cl = STATE.contest_log
        if not cl:
            return {"deleted": [], "errors": ["No contest log loaded"]}
        deleted, errors = [], []
        for qid in qso_ids:
            match = next((q for q in cl.qsos if q.get("qso_id") == qid), None)
            if not match:
                errors.append(f"{qid}: not found")
                continue
            try:
                cl.delete_qso(qid, match.get("_table", "DXLOG"))
                deleted.append(qid)
            except Exception as e:
                log.exception("Delete failed for QSO %s", qid)
                errors.append(f"{qid}: {e}")
        return {"deleted": deleted, "errors": errors}


@app.post("/api/qsos/delete")
async def api_qsos_delete(body: dict):
    """Permanently delete one or more QSOs from the database. Body: {qso_ids: [...]}"""
    qso_ids = body.get("qso_ids") or []
    if not qso_ids:
        return JSONResponse({"error": "No qso_ids supplied"}, status_code=400)
    return await asyncio.get_event_loop().run_in_executor(None, _delete_qsos, qso_ids)


def _yoy_build_trajectory(cl: "ContestLog") -> Optional[dict]:
    """
    Hourly-resolution score/QSO/mult trajectory + per-hour rate for one
    ContestLog, for the Year-on-Year overlay chart.

    Mirrors the old desktop app's _yoy_build_trajectory, but buckets by
    elapsed contest-hour (like compute_snapshot's running_score sparkline)
    instead of recomputing the score once per QSO — same O(hours) cost as
    the rest of this codebase's sparklines instead of O(qsos²), which matters
    here because the YOY endpoint may build this for many contest-years at once.
    """
    valid = sorted([q for q in cl.qsos if not q.get("dupe")], key=lambda q: q["time"])
    if not valid:
        return None

    cs = cl.contest_start()
    earliest = valid[0]["time"]
    if cs is None or cs > earliest:
        cs = earliest.replace(minute=0, second=0, microsecond=0)

    total_hrs = (valid[-1]["time"] - cs).total_seconds() / 3600.0
    n_buckets = max(1, int(math.ceil(max(total_hrs, 0))) + 1)

    plugin = cl.plugin
    seen_mults = set()
    acc: list = []
    elapsed_hrs, utc_hrs = [], []
    cum_score, cum_qsos, cum_mults = [], [], []
    rate_counts     = [0] * n_buckets
    utc_rate_counts = [0] * 24

    vi = 0
    for h in range(n_buckets):
        bucket_end = cs + timedelta(hours=h + 1)
        while vi < len(valid) and valid[vi]["time"] < bucket_end:
            q = valid[vi]
            acc.append(q)
            rate_counts[h] += 1
            utc_rate_counts[q["time"].hour] += 1
            plugin.sparkline_mults(q, seen_mults)
            vi += 1
        mid = cs + timedelta(hours=h + 0.5)
        elapsed_hrs.append(h + 1.0)
        utc_hrs.append(mid.hour + mid.minute / 60.0)
        cum_qsos.append(len(acc))
        cum_score.append(plugin.running_score_for_sparkline(acc))
        cum_mults.append(len(seen_mults))

    # Any QSOs landing after the nominal window still count toward the final point.
    if vi < len(valid):
        for q in valid[vi:]:
            acc.append(q)
            utc_rate_counts[q["time"].hour] += 1
            plugin.sparkline_mults(q, seen_mults)
        if cum_qsos:
            rate_counts[-1] += len(valid) - vi
            cum_qsos[-1]  = len(acc)
            cum_score[-1] = plugin.running_score_for_sparkline(acc)
            cum_mults[-1] = len(seen_mults)

    return {
        "elapsed_hrs":     elapsed_hrs,
        "utc_hrs":         utc_hrs,
        "cum_score":       cum_score,
        "cum_qsos":        cum_qsos,
        "cum_mults":       cum_mults,
        "rate_hrs":        [b + 0.5 for b in range(n_buckets)],
        "rate_counts":     rate_counts,
        "utc_rate_hrs":    [h + 0.5 for h in range(24)],
        "utc_rate_counts": utc_rate_counts,
        "final_score":     cum_score[-1] if cum_score else 0,
        "final_qsos":      cum_qsos[-1]  if cum_qsos  else 0,
        "final_mults":     cum_mults[-1] if cum_mults else 0,
        "total_hrs":       total_hrs,
    }


def _yoy_collect_series(db_path: str, existing_keys: set, current_plugin_type=None) -> list:
    """Load every real contest (with QSOs) from db_path into YOY series dicts.

    current_plugin_type, when given, restricts results to contests handled by
    the SAME plugin class as the currently-loaded log (e.g. CQWWPlugin covers
    both the CW and SSB weekends) — mirrors _pace_collect_same_contest's
    "auto" reference matching, used by the Report tab so its YoY comparison
    only ever shows other years of the contest actually loaded, not every
    contest type ever logged in the database.
    """
    out = []
    try:
        contests = ContestLog.available_contests(db_path)
    except Exception:
        log.exception("YOY: available_contests failed for %s", db_path)
        return out

    for ci in contests:
        if not ci.get("QSOCount", 0):
            continue
        contest_name = str(ci.get("ContestName", "")).strip()
        if contest_name.upper() in ("DX", "DELETEDQS", ""):
            continue
        key = f"{db_path}::{ci['ContestNR']}"
        if key in existing_keys:
            continue
        try:
            p = plugin_for(contest_name)
            if current_plugin_type is not None and type(p) is not current_plugin_type:
                continue
            cl = ContestLog(db_path, contest_nr=ci["ContestNR"], plugin=p)
            if not cl.qsos:
                continue
            traj = _yoy_build_trajectory(cl)
            if traj is None:
                continue

            sd = str(ci.get("StartDate", ""))[:4]
            start_yr = int(sd) if sd.isdigit() else 0
            qso_yr   = cl.qsos[0]["time"].year if cl.qsos else 0
            year = qso_yr if (start_yr and qso_yr and abs(start_yr - qso_yr) > 1) else (start_yr or qso_yr)

            display = str(ci.get("DisplayName") or contest_name or "?").strip()
            out.append({
                "key": key, "year": year,
                "label": f"{year} — {display}",
                "contest_name": contest_name, "display_name": display,
                "db_path": db_path, "contest_nr": ci["ContestNR"],
                **traj,
            })
            existing_keys.add(key)
        except Exception:
            log.exception("YOY: failed loading ContestNR %s from %s", ci.get("ContestNR"), db_path)
    return out


def _yoy_full_state(same_contest: bool = False) -> dict:
    existing_keys: set = set()
    series = []
    with STATE._lock:
        primary = STATE.db_path
        cl      = STATE.contest_log
        extra_paths = list(STATE.yoy_extra_paths)
    current_plugin_type = type(cl.plugin) if (same_contest and cl) else None
    if primary:
        series.extend(_yoy_collect_series(primary, existing_keys, current_plugin_type))
    for p in extra_paths:
        series.extend(_yoy_collect_series(p, existing_keys, current_plugin_type))
    return {"series": _json_safe(series), "extra_paths": extra_paths}


@app.get("/api/yoy")
async def api_yoy(same_contest: bool = False):
    """Year-on-Year comparison: trajectories for every contest-year found in
    the current .s3db plus any extra logs added via /api/yoy/add_log.

    ?same_contest=true restricts to contest-years handled by the same plugin
    as the currently-loaded log (used by the Report tab — see _yoy_collect_series)."""
    return await asyncio.get_event_loop().run_in_executor(None, _yoy_full_state, same_contest)


@app.post("/api/yoy/add_log")
async def api_yoy_add_log(body: dict):
    """Add another .s3db file's contests to the Year-on-Year comparison."""
    path = (body.get("path") or "").strip()
    if not path:
        return JSONResponse({"error": "No path supplied"}, status_code=400)
    err = STATE.validate_path(path)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    path = str(Path(path).resolve())
    with STATE._lock:
        is_primary = STATE.db_path and os.path.normcase(path) == os.path.normcase(STATE.db_path)
        if not is_primary and path not in STATE.yoy_extra_paths:
            STATE.yoy_extra_paths.append(path)
    return await asyncio.get_event_loop().run_in_executor(None, _yoy_full_state)


@app.post("/api/yoy/clear_logs")
async def api_yoy_clear_logs():
    """Remove all extra logs added on the Year-on-Year tab (primary log stays)."""
    with STATE._lock:
        STATE.yoy_extra_paths = []
    return await asyncio.get_event_loop().run_in_executor(None, _yoy_full_state)


# ── Pace Tracker ──────────────────────────────────────────────────────────────

def _pace_trajectory_from_times(times: list, contest_start) -> Optional[dict]:
    """
    Given a sorted list of valid-QSO datetimes and a contest-start datetime,
    build the elapsed-hours cumulative-QSO trajectory plus hourly rate buckets
    used by the Pace chart. Shared by the live log, .s3db references, and the
    ADIF/Cabrillo reference parsers below.
    """
    elapsed_hrs, cum_qsos = [], []
    for t in times:
        e = (t - contest_start).total_seconds() / 3600.0
        if e < 0:
            continue
        elapsed_hrs.append(e)
        cum_qsos.append(len(cum_qsos) + 1)
    if not elapsed_hrs:
        return None

    max_e = elapsed_hrs[-1]
    n_buckets = max(1, int(max_e) + 1)
    rate_counts = [0] * n_buckets
    for e in elapsed_hrs:
        b = min(int(e), n_buckets - 1)
        rate_counts[b] += 1
    rate_hrs = [b + 0.5 for b in range(n_buckets)]

    return {
        "elapsed_hrs": elapsed_hrs, "cum_qsos": cum_qsos,
        "rate_hrs": rate_hrs, "rate_counts": rate_counts,
        "final_qsos": cum_qsos[-1], "total_hrs": max_e,
    }


def _pace_trajectory_for_log(cl: "ContestLog") -> Optional[dict]:
    valid = sorted([q for q in cl.qsos if not q.get("dupe")], key=lambda q: q["time"])
    cs = cl.contest_start()
    if not cs or not valid:
        return None
    return _pace_trajectory_from_times([q["time"] for q in valid], cs)


def _pace_collect_same_contest(db_path: str, current_contest_nr, current_plugin_type,
                                existing_keys: set) -> list:
    """Auto-load other contest-years owned by the SAME plugin from the primary
    .s3db — mirrors the old desktop app's auto-load in _refresh_pace, so the
    chart doesn't fill up with unrelated contests."""
    out = []
    try:
        contests = ContestLog.available_contests(db_path)
    except Exception:
        log.exception("Pace: available_contests failed for %s", db_path)
        return out
    for ci in contests:
        if not ci.get("QSOCount", 0) or ci["ContestNR"] == current_contest_nr:
            continue
        contest_name = str(ci.get("ContestName", "")).strip()
        ci_plugin = plugin_for(contest_name)
        if type(ci_plugin) is not current_plugin_type:
            continue
        key = f"{db_path}::{ci['ContestNR']}"
        if key in existing_keys:
            continue
        try:
            cl = ContestLog(db_path, contest_nr=ci["ContestNR"], plugin=ci_plugin)
            if not cl.qsos:
                continue
            traj = _pace_trajectory_for_log(cl)
            if traj is None:
                continue
            sd = str(ci.get("StartDate", ""))[:4]
            start_yr = int(sd) if sd.isdigit() else 0
            qso_yr   = cl.qsos[0]["time"].year if cl.qsos else 0
            year = qso_yr if (start_yr and qso_yr and abs(start_yr - qso_yr) > 1) else (start_yr or qso_yr)
            display = str(ci.get("DisplayName") or contest_name or "?").strip()
            out.append({
                "key": key, "year": year, "label": f"{year} — {display}",
                "contest_name": contest_name, "display_name": display, "source": "auto",
                "db_path": db_path, "contest_nr": ci["ContestNR"], **traj,
            })
            existing_keys.add(key)
        except Exception:
            log.exception("Pace: failed loading ContestNR %s from %s", ci.get("ContestNR"), db_path)
    return out


def _pace_collect_all_from_db(db_path: str, existing_keys: set) -> list:
    """Load every real contest from a manually-added reference .s3db file."""
    out = []
    try:
        contests = ContestLog.available_contests(db_path)
    except Exception:
        log.exception("Pace: available_contests failed for %s", db_path)
        return out
    for ci in contests:
        if not ci.get("QSOCount", 0):
            continue
        contest_name = str(ci.get("ContestName", "")).strip()
        if contest_name.upper() in ("DX", "DELETEDQS", ""):
            continue
        key = f"{db_path}::{ci['ContestNR']}"
        if key in existing_keys:
            continue
        try:
            p  = plugin_for(contest_name)
            cl = ContestLog(db_path, contest_nr=ci["ContestNR"], plugin=p)
            if not cl.qsos:
                continue
            traj = _pace_trajectory_for_log(cl)
            if traj is None:
                continue
            sd = str(ci.get("StartDate", ""))[:4]
            start_yr = int(sd) if sd.isdigit() else 0
            qso_yr   = cl.qsos[0]["time"].year if cl.qsos else 0
            year = qso_yr if (start_yr and qso_yr and abs(start_yr - qso_yr) > 1) else (start_yr or qso_yr)
            display = str(ci.get("DisplayName") or contest_name or "?").strip()
            out.append({
                "key": key, "year": year, "label": f"{year} — {display}",
                "contest_name": contest_name, "display_name": display, "source": "manual",
                "db_path": db_path, "contest_nr": ci["ContestNR"], **traj,
            })
            existing_keys.add(key)
        except Exception:
            log.exception("Pace: failed loading ContestNR %s from %s", ci.get("ContestNR"), db_path)
    return out


_ADIF_TAG_RE = re.compile(r"<([^:>]+)(?::(\d+)(?::[^>]*)?)?>", re.IGNORECASE)

def _parse_adif_times(text: str) -> list:
    """Yield QSO datetimes from an ADIF file (QSO_DATE + TIME_ON fields)."""
    pos, text_len = 0, len(text)
    eoh = re.search(r"<EOH>", text, re.IGNORECASE)
    if eoh:
        pos = eoh.end()
    times = []
    record = {}
    while pos < text_len:
        m = _ADIF_TAG_RE.search(text, pos)
        if not m:
            break
        tag, lstr = m.group(1).upper(), m.group(2)
        pos = m.end()
        if tag == "EOR":
            date_str = record.get("QSO_DATE", "").strip()
            time_str = record.get("TIME_ON", "").strip().ljust(6, "0")[:6]
            if date_str:
                try:
                    times.append(datetime.strptime(date_str + time_str, "%Y%m%d%H%M%S"))
                except ValueError:
                    try:
                        times.append(datetime.strptime(date_str + time_str[:4], "%Y%m%d%H%M"))
                    except ValueError:
                        pass
            record = {}
            continue
        if lstr is None:
            continue
        length = int(lstr)
        record[tag] = text[pos:pos + length]
        pos += length
    return times


def _pace_load_adif(path: str, existing_keys: set) -> Optional[dict]:
    key = f"adif::{path}"
    if key in existing_keys:
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception:
        log.exception("Pace: could not read ADIF %s", path)
        return None

    times = sorted(_parse_adif_times(text))
    if not times:
        return None

    contest_start = times[0].replace(minute=0, second=0, microsecond=0)
    traj = _pace_trajectory_from_times(times, contest_start)
    if traj is None:
        return None

    year  = contest_start.year
    fname = os.path.splitext(os.path.basename(path))[0]
    label = f"{year} — {fname} (ADIF)"
    existing_keys.add(key)
    return {
        "key": key, "year": year, "label": label, "contest_name": fname,
        "display_name": fname, "source": "manual", "db_path": None, "contest_nr": None, **traj,
    }


def _parse_cabrillo_times(text: str) -> tuple:
    """Returns (header_dict, sorted_qso_datetimes) from a Cabrillo v2/v3 log."""
    header, times = {}, []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("START-OF-LOG") or line.startswith("END-OF-LOG"):
            continue
        if line.upper().startswith("QSO:"):
            parts = line[4:].split()
            if len(parts) < 8:
                continue
            date_s = parts[2].replace("/", "-")
            time_s = parts[3].replace(":", "")
            try:
                times.append(datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H%M"))
            except ValueError:
                continue
        elif ":" in line:
            k, _, v = line.partition(":")
            header[k.strip().upper()] = v.strip()
    return header, sorted(times)


def _pace_load_cabrillo(path: str, existing_keys: set) -> Optional[dict]:
    key = f"cabrillo::{path}"
    if key in existing_keys:
        return None

    text = None
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            with open(path, "r", encoding=enc, errors="strict") as f:
                text = f.read()
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        log.warning("Pace: could not decode Cabrillo file %s", path)
        return None

    upper = text[:500].upper()
    if "START-OF-LOG" not in upper and "QSO:" not in upper:
        log.warning("Pace: %s does not look like a Cabrillo log", path)
        return None

    header, times = _parse_cabrillo_times(text)
    if not times:
        return None

    contest_start = None
    start_hdr = header.get("QSO-DATE-START") or header.get("DATE-START")
    if start_hdr:
        for fmt in ("%Y-%m-%d %H%M", "%Y-%m-%d", "%Y-%m-%d %H:%M"):
            try:
                contest_start = datetime.strptime(start_hdr.strip()[:16], fmt)
                break
            except ValueError:
                continue
    if contest_start is None:
        contest_start = times[0].replace(hour=0, minute=0, second=0, microsecond=0)

    traj = _pace_trajectory_from_times(times, contest_start)
    if traj is None:
        return None

    year         = contest_start.year
    contest_name = header.get("CONTEST", "") or header.get("CONTEST-ID", "")
    fname        = os.path.splitext(os.path.basename(path))[0]
    display_name = contest_name if contest_name else fname
    label        = f"{year} — {display_name} (Cabrillo)"
    existing_keys.add(key)
    return {
        "key": key, "year": year, "label": label, "contest_name": display_name,
        "display_name": display_name, "source": "manual", "db_path": None,
        "contest_nr": None, **traj,
    }


def _pace_full_state() -> dict:
    with STATE._lock:
        primary            = STATE.db_path
        cl                  = STATE.contest_log
        current_contest_nr  = STATE.contest_nr
        extra               = list(STATE.pace_extra_paths)

    existing_keys: set = set()
    refs = []
    if primary and cl:
        refs.extend(_pace_collect_same_contest(primary, current_contest_nr, type(cl.plugin), existing_keys))

    for item in extra:
        path, kind = item["path"], item["kind"]
        try:
            if kind == "s3db":
                refs.extend(_pace_collect_all_from_db(path, existing_keys))
            elif kind == "adif":
                r = _pace_load_adif(path, existing_keys)
                if r:
                    refs.append(r)
            elif kind == "cabrillo":
                r = _pace_load_cabrillo(path, existing_keys)
                if r:
                    refs.append(r)
        except Exception:
            log.exception("Pace: failed loading extra reference %s", path)

    live = _pace_trajectory_for_log(cl) if cl else None
    return {
        "live": _json_safe(live),
        "refs": _json_safe(refs),
        "extra_paths": [it["path"] for it in extra],
    }


@app.get("/api/pace")
async def api_pace():
    """Pace Tracker: live cumulative-QSO trajectory plus auto-loaded same-contest
    reference years from the current .s3db, plus any manually-added .s3db/ADIF/
    Cabrillo reference logs."""
    return await asyncio.get_event_loop().run_in_executor(None, _pace_full_state)


@app.get("/api/pace/live")
async def api_pace_live():
    """Cheap periodic poll target for the pace alarm — just the live
    trajectory, without re-walking any reference .s3db/ADIF/Cabrillo files."""
    with STATE._lock:
        cl = STATE.contest_log
    live = _pace_trajectory_for_log(cl) if cl else None
    return _json_safe(live)


@app.post("/api/pace/add_log")
async def api_pace_add_log(body: dict):
    """Add a reference log for the Pace tab. Accepts .s3db/.db/.sqlite, .adi/.adif,
    or Cabrillo .log/.cbr/.txt files."""
    path = (body.get("path") or "").strip()
    if not path:
        return JSONResponse({"error": "No path supplied"}, status_code=400)
    p = Path(path)
    if not p.exists():
        return JSONResponse({"error": f"File not found: {path}"}, status_code=400)
    if p.is_dir():
        return JSONResponse({"error": f"That is a folder, not a file: {path}"}, status_code=400)

    ext = p.suffix.lower()
    if ext in (".s3db", ".db", ".sqlite"):
        kind = "s3db"
    elif ext in (".adi", ".adif"):
        kind = "adif"
    elif ext in (".log", ".cbr", ".txt"):
        kind = "cabrillo"
    else:
        return JSONResponse({"error": f"Unsupported file type: {p.name}"}, status_code=400)

    path = str(p.resolve())
    with STATE._lock:
        is_primary = STATE.db_path and os.path.normcase(path) == os.path.normcase(STATE.db_path)
        already = any(os.path.normcase(it["path"]) == os.path.normcase(path) for it in STATE.pace_extra_paths)
        if not is_primary and not already:
            STATE.pace_extra_paths.append({"path": path, "kind": kind})
    return await asyncio.get_event_loop().run_in_executor(None, _pace_full_state)


@app.post("/api/pace/clear_refs")
async def api_pace_clear_refs():
    """Remove manually-added Pace reference logs (auto-loaded same-contest years
    from the primary log are unaffected and will reappear)."""
    with STATE._lock:
        STATE.pace_extra_paths = []
    return await asyncio.get_event_loop().run_in_executor(None, _pace_full_state)


# ── Fatigue (cross-year hourly rate) ──────────────────────────────────────────

def _fatigue_build_contest_entry(cl: "ContestLog", ci: dict, db_path: str) -> Optional[dict]:
    """Per-contest UTC-hour-of-day QSO counts (all bands + per band), for the
    cross-year fatigue overlay. Bucketed by real UTC hour (not elapsed contest
    hour) so different years' day/night patterns line up on the same x-axis."""
    valid = [q for q in cl.qsos if not q.get("dupe")]
    if not valid:
        return None

    hour_all = [0] * 24
    by_band: dict = {}
    for q in valid:
        h = q["time"].hour
        hour_all[h] += 1
        b = q.get("band") or "?"
        by_band.setdefault(b, [0] * 24)[h] += 1

    sd   = str(ci.get("StartDate", ""))[:4]
    year = int(sd) if sd.isdigit() else (valid[0]["time"].year if valid else 0)
    name = str(ci.get("DisplayName") or ci.get("ContestName") or "?").strip()

    return {
        "key": f"{db_path}::{ci['ContestNR']}", "year": year, "name": name,
        "label": f"{year}  {name}", "db_path": db_path, "contest_nr": ci["ContestNR"],
        "qso_count": len(valid), "hour_all": hour_all, "hour_by_band": by_band,
    }


def _fatigue_collect_from_db(db_path: str, existing_keys: set) -> list:
    """Load every contest (any type) with QSOs from db_path — unlike Pace's
    auto-load, Fatigue mixes everything in by default and lets the operator
    narrow to one contest type via the client-side filter dropdown."""
    out = []
    try:
        contests = ContestLog.available_contests(db_path)
    except Exception:
        log.exception("Fatigue: available_contests failed for %s", db_path)
        return out
    for ci in contests:
        if not ci.get("QSOCount", 0):
            continue
        key = f"{db_path}::{ci['ContestNR']}"
        if key in existing_keys:
            continue
        try:
            p   = plugin_for(str(ci.get("ContestName", "")))
            cl  = ContestLog(db_path, contest_nr=ci["ContestNR"], plugin=p)
            entry = _fatigue_build_contest_entry(cl, ci, db_path)
            if entry is None:
                continue
            out.append(entry)
            existing_keys.add(key)
        except Exception:
            log.exception("Fatigue: failed loading ContestNR %s from %s", ci.get("ContestNR"), db_path)
    return out


def _fatigue_full_state() -> dict:
    with STATE._lock:
        primary = STATE.db_path
        extra   = list(STATE.fatigue_extra_paths)

    existing_keys: set = set()
    contests = []
    if primary:
        contests.extend(_fatigue_collect_from_db(primary, existing_keys))
    for p in extra:
        contests.extend(_fatigue_collect_from_db(p, existing_keys))
    return {"contests": _json_safe(contests), "extra_paths": extra}


@app.get("/api/fatigue")
async def api_fatigue():
    """Cross-year fatigue data: UTC-hour QSO-rate arrays for every contest in
    the primary .s3db plus any extra logs added via /api/fatigue/add_log."""
    return await asyncio.get_event_loop().run_in_executor(None, _fatigue_full_state)


@app.post("/api/fatigue/add_log")
async def api_fatigue_add_log(body: dict):
    """Add another .s3db file's contests to the Fatigue cross-year analysis."""
    path = (body.get("path") or "").strip()
    if not path:
        return JSONResponse({"error": "No path supplied"}, status_code=400)
    err = STATE.validate_path(path)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    path = str(Path(path).resolve())
    with STATE._lock:
        is_primary = STATE.db_path and os.path.normcase(path) == os.path.normcase(STATE.db_path)
        already = any(os.path.normcase(p) == os.path.normcase(path) for p in STATE.fatigue_extra_paths)
        if not is_primary and not already:
            STATE.fatigue_extra_paths.append(path)
    return await asyncio.get_event_loop().run_in_executor(None, _fatigue_full_state)


@app.post("/api/fatigue/clear_logs")
async def api_fatigue_clear_logs():
    """Remove all extra logs added on the Fatigue tab (primary log stays)."""
    with STATE._lock:
        STATE.fatigue_extra_paths = []
    return await asyncio.get_event_loop().run_in_executor(None, _fatigue_full_state)


# ── Band efficiency (cross-year, same contest series) ────────────────────────
# Mirrors the Fatigue cross-year mechanism above, but calls each historical
# contest's plugin.band_efficiency() instead of hourly-binning. Scoped to the
# primary log's contest series (auto-loaded, like Pace's YoY) rather than
# blending across contest types, since "efficiency" and even the "band" field
# itself mean different things for different plugins (see efficiency_label()).

def _bandeff_build_contest_entry(cl: "ContestLog", ci: dict, db_path: str) -> Optional[dict]:
    if not cl.qsos:
        return None
    try:
        rows = cl.plugin.band_efficiency(cl.qsos)
    except Exception:
        return None
    if not rows:
        return None

    sd   = str(ci.get("StartDate", ""))[:4]
    year = int(sd) if sd.isdigit() else (cl.qsos[0]["time"].year if cl.qsos else 0)
    name = str(ci.get("DisplayName") or ci.get("ContestName") or "?").strip()

    return {
        "key": f"{db_path}::{ci['ContestNR']}", "year": year, "name": name,
        "label": f"{year}  {name}", "db_path": db_path, "contest_nr": ci["ContestNR"],
        "efficiency_label": cl.plugin.efficiency_label(),
        "bands": rows,
    }


def _bandeff_collect_from_db(db_path: str, plugin_type_filter, existing_keys: set) -> list:
    """Load contests from db_path. When plugin_type_filter is given (the
    primary log's auto-load), only contests resolving to that same plugin
    class are included — mirrors _pace_collect_same_contest's approach of
    matching by plugin type rather than by contest_nr/ContestName string,
    since STATE.contest_nr is often None (ContestLog auto-picks the latest
    contest without writing the resolved number back). Manually-added extra
    logs pass plugin_type_filter=None and include every contest in the file,
    same as Pace's manual reference logs."""
    out = []
    try:
        contests = ContestLog.available_contests(db_path)
    except Exception:
        log.exception("BandEff YoY: available_contests failed for %s", db_path)
        return out
    for ci in contests:
        if not ci.get("QSOCount", 0):
            continue
        key = f"{db_path}::{ci['ContestNR']}"
        if key in existing_keys:
            continue
        cname = str(ci.get("ContestName", ""))
        p     = plugin_for(cname)
        if plugin_type_filter is not None and type(p) is not plugin_type_filter:
            continue
        try:
            cl    = ContestLog(db_path, contest_nr=ci["ContestNR"], plugin=p)
            entry = _bandeff_build_contest_entry(cl, ci, db_path)
            if entry is None:
                continue
            out.append(entry)
            existing_keys.add(key)
        except Exception:
            log.exception("BandEff YoY: failed loading ContestNR %s from %s", ci.get("ContestNR"), db_path)
    return out


def _bandeff_full_state() -> dict:
    with STATE._lock:
        primary = STATE.db_path
        extra   = list(STATE.bandeff_extra_paths)
        cl      = STATE.contest_log

    current_plugin_type = type(cl.plugin) if cl else None

    existing_keys: set = set()
    contests = []
    if primary:
        contests.extend(_bandeff_collect_from_db(primary, current_plugin_type, existing_keys))
    for p in extra:
        contests.extend(_bandeff_collect_from_db(p, None, existing_keys))
    return {"contests": _json_safe(contests), "extra_paths": extra}


@app.get("/api/bandeff_yoy")
async def api_bandeff_yoy():
    """Cross-year band-efficiency data, scoped to the primary log's contest
    series, for the Band Breakdown tab's year-over-year comparison."""
    return await asyncio.get_event_loop().run_in_executor(None, _bandeff_full_state)


@app.post("/api/bandeff_yoy/add_log")
async def api_bandeff_yoy_add_log(body: dict):
    """Add another .s3db file's matching contests to the band-efficiency YoY view."""
    path = (body.get("path") or "").strip()
    if not path:
        return JSONResponse({"error": "No path supplied"}, status_code=400)
    err = STATE.validate_path(path)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    path = str(Path(path).resolve())
    with STATE._lock:
        is_primary = STATE.db_path and os.path.normcase(path) == os.path.normcase(STATE.db_path)
        already = any(os.path.normcase(p) == os.path.normcase(path) for p in STATE.bandeff_extra_paths)
        if not is_primary and not already:
            STATE.bandeff_extra_paths.append(path)
    return await asyncio.get_event_loop().run_in_executor(None, _bandeff_full_state)


@app.post("/api/bandeff_yoy/clear_logs")
async def api_bandeff_yoy_clear_logs():
    """Remove all extra logs added to the band-efficiency YoY view (primary log stays)."""
    with STATE._lock:
        STATE.bandeff_extra_paths = []
    return await asyncio.get_event_loop().run_in_executor(None, _bandeff_full_state)


@app.get("/api/plugin_meta")
async def api_plugin_meta():
    """
    Return plugin-driven UI metadata so the frontend can adapt:
    - gauge_defs: list of gauge definitions with keys, labels, maxes, tooltips
    - has_missing_tab: whether Missing Mults tab should be shown
    - has_region_heat: whether Region Heat panel should be shown
    - has_state_bars: whether Region Completion bars should be shown
    - mult_label: label for the multiplier column
    - display_name: plugin display name
    - bands: ordered list of bands this contest's rules allow, for the
      "What if?" band dropdown (see ContestPlugin.band_list())
    """
    if not STATE.contest_log:
        return {"loaded": False}

    p    = STATE.contest_log.plugin
    snap = STATE.snapshot()
    total_mults = snap.get("_total_mults", snap.get("band_mults", 0))

    # gauge_defs returns GaugeDef dataclass instances
    try:
        raw_defs = p.gauge_defs(snap, total_mults)
    except Exception:
        raw_defs = []

    gauge_list = []
    for g in raw_defs:
        # GaugeDef fields: label, value_key, max_key, colour, fmt, tooltip=""
        max_val = g.max_key
        # max_key may be a string (snap key) or a numeric literal
        if isinstance(max_val, str):
            max_val = snap.get(max_val, 1)
        gauge_list.append({
            "label":     g.label,
            "value_key": g.value_key,
            "max_val":   max_val,
            "colour":    g.colour if isinstance(g.colour, str) else "#00d4aa",
            "fmt":       g.fmt,
            "tooltip":   getattr(g, "tooltip", ""),
        })

    return {
        "loaded":           True,
        "display_name":     getattr(p, "display_name", "Generic"),
        "has_missing_tab":  getattr(p, "has_missing_tab", lambda: True)(),
        "has_region_heat":  getattr(p, "has_region_heat", lambda: False)(),
        "has_state_bars":   getattr(p, "has_state_bars",  lambda: False)(),
        "mult_label":       getattr(p, "mult_label",      lambda: "Mult")(),
        "uses_cq_zone_scoring": getattr(p, "uses_cq_zone_scoring", lambda: False)(),
        "gauge_defs":       gauge_list,
        "bands":            getattr(p, "band_list", lambda: [])(),
    }


# ── DX Cluster ──────────────────────────────────────────────────────────────
import socket as _socket
import re as _re

_SPOT_RE = _re.compile(
    r"DX\s+de\s+(\S+?):?\s+(\d+(?:\.\d+)?)\s+(\S+)\s+(.*?)\s+(\d{4})Z?\s*$",
    _re.IGNORECASE,
)

_CLUSTER_PRESETS = [
    {"label": "VK2RCG (VK)",   "host": "vk2rcg.ampr.org",    "port": 7300},
    {"label": "VK4RBD (VK)",   "host": "vk4rbd.dyndns.org",  "port": 7300},
    {"label": "VE7CC (NA)",    "host": "dx.ve7cc.net",        "port": 7300},
    {"label": "DL9GTB (EU)",   "host": "cluster.dl9gtb.de",   "port": 7300},
    {"label": "GB7MBC (EU)",   "host": "gb7mbc.spoo.org",     "port": 7300},
    {"label": "K3LR (NA)",     "host": "cluster.k3lr.com",    "port": 7300},
    {"label": "WA9PIE (NA)",   "host": "hrd.wa9pie.net",      "port": 8000},
]

_CLUSTER_BAND_EDGES = [
    (1800,    2000,    "160M"),
    (3500,    4000,     "80M"),
    (5330,    5410,     "60M"),
    (7000,    7300,     "40M"),
    (10100,   10150,    "30M"),
    (14000,   14350,    "20M"),
    (18068,   18168,    "17M"),
    (21000,   21450,    "15M"),
    (24890,   24990,    "12M"),
    (28000,   29700,    "10M"),
    (50000,   54000,     "6M"),
    (144000,  148000,    "2M"),
]

def _freq_to_band_str(freq_khz: float) -> str:
    for lo, hi, name in _CLUSTER_BAND_EDGES:
        if lo <= freq_khz <= hi:
            return name
    return f"{freq_khz:.0f}kHz"

def _classify_spot(dx_call: str, freq_khz: float, comment: str) -> tuple:
    """
    Returns (status, mult_value, region) where:
      status : "NEW_MULT" | "NEW_BAND" | "WORKED" | "NOT_MULT" | "NO_LOG"
    Mirrors the old desktop app's _classify_spot: scan comment tokens against
    plugin.mult_list() first, fall back to plugin.mult_of_qso() with a fake
    QSO dict, then compare against worked_mults()/worked_primary_band_mults().
    """
    with STATE._lock:
        cl = STATE.contest_log
    if not cl:
        return "NO_LOG", "", ""

    band = _freq_to_band_str(freq_khz)
    p    = cl.plugin
    ml_set = set(p.mult_list())

    mult_val = None
    comment_upper = comment.strip().upper()
    for token in comment_upper.split():
        tok = token.strip(".,;:-")
        if tok in ml_set:
            mult_val = tok
            break

    if mult_val is None:
        fake_q = {
            "call": dx_call.upper(), "mult1": comment_upper, "band": band,
            "mode": "SSB", "pts": 1, "dupe": False,
            "is_mult1": None, "is_mult2": None, "cqz": None,
            "time": datetime.utcnow(),
        }
        try:
            mult_val = p.mult_of_qso(fake_q)
        except Exception:
            mult_val = None

    if mult_val is None or mult_val not in ml_set:
        return "NOT_MULT", "", ""

    region = p.region_of_mult(mult_val) or ""
    worked = cl.worked_mults()
    if mult_val not in worked:
        return "NEW_MULT", mult_val, region

    band_wkd = cl.worked_primary_band_mults()
    on_this_band = any(m == mult_val and b == band for m, b, _mode in band_wkd)
    if not on_this_band:
        return "NEW_BAND", mult_val, region
    return "WORKED", mult_val, region

@app.get("/api/cluster/presets")
async def api_cluster_presets():
    return _CLUSTER_PRESETS

@app.websocket("/ws/cluster")
async def ws_cluster(ws: WebSocket):
    """
    Browser connects here; we open a raw TCP socket to the DX cluster and
    proxy data bidirectionally. The browser sends JSON commands:
      {"cmd": "connect", "host": "...", "port": 7300, "callsign": "VK2YI"}
      {"cmd": "send", "text": "SH/DX 20\n"}
      {"cmd": "disconnect"}
    We push JSON back:
      {"type": "raw",       "line": "..."}
      {"type": "spot",      "spotter":..., "freq":..., "dx":..., "comment":..., "time":...}
      {"type": "status",    "connected": bool, "msg": "..."}
    """
    await ws.accept()
    tcp: _socket.socket | None = None
    reader_task = None

    async def _read_tcp():
        nonlocal tcp
        loop = asyncio.get_event_loop()
        buf  = b""
        while tcp:
            try:
                chunk = await loop.run_in_executor(None, tcp.recv, 1024)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    text = line.decode("utf-8", errors="replace").strip()
                    if not text:
                        continue
                    msg = {"type": "raw", "line": text}
                    m   = _SPOT_RE.match(text)
                    if m:
                        freq    = float(m.group(2))
                        dx_call = m.group(3)
                        comment = m.group(4).strip()
                        status, mult_val, region = _classify_spot(dx_call, freq, comment)
                        msg = {
                            "type":    "spot",
                            "spotter": m.group(1),
                            "freq":    freq,
                            "dx":      dx_call,
                            "comment": comment,
                            "time":    m.group(5),
                            "band":    _freq_to_band_str(freq),
                            "status":  status,
                            "mult":    mult_val,
                            "region":  region,
                        }
                    await ws.send_text(json.dumps(msg))
            except Exception:
                break
        try:
            await ws.send_text(json.dumps({"type":"status","connected":False,"msg":"Disconnected"}))
        except Exception:
            pass

    try:
        while True:
            raw = await ws.receive_text()
            cmd = json.loads(raw)

            if cmd.get("cmd") == "connect":
                if tcp:
                    try: tcp.close()
                    except: pass
                if reader_task:
                    reader_task.cancel()
                host = cmd.get("host","")
                port = int(cmd.get("port", 7300))
                call = cmd.get("callsign","VK2YI")
                try:
                    loop = asyncio.get_event_loop()
                    tcp  = await loop.run_in_executor(
                        None, lambda: _socket.create_connection((host,port), timeout=10))
                    tcp.settimeout(30)
                    reader_task = asyncio.create_task(_read_tcp())
                    await asyncio.sleep(1)
                    tcp.sendall((call+"\n").encode())
                    await asyncio.sleep(1)
                    tcp.sendall(b"SET/DX\n")
                    await ws.send_text(json.dumps({
                        "type":"status","connected":True,
                        "msg":f"Connected to {host}:{port}"}))
                except Exception as e:
                    await ws.send_text(json.dumps({
                        "type":"status","connected":False,"msg":str(e)}))

            elif cmd.get("cmd") == "send" and tcp:
                try: tcp.sendall((cmd.get("text","")+"\n").encode())
                except: pass

            elif cmd.get("cmd") == "disconnect":
                if tcp:
                    try: tcp.close()
                    except: pass
                    tcp = None
                break

    except (WebSocketDisconnect, Exception):
        pass
    finally:
        if tcp:
            try: tcp.close()
            except: pass
        if reader_task:
            reader_task.cancel()


# ── Themes ────────────────────────────────────────────────────────────────────
_THEMES = {
    "Dark (Default)": {
        "bg":"#0d1117","bg2":"#161b22","bg3":"#21262d",
        "accent":"#00d4aa","accent2":"#ff6b35","accent3":"#f0c040",
        "red":"#ff4757","green":"#2ed573","muted":"#8b949e","fg":"#e6edf3",
    },
    "Light": {
        "bg":"#f5f6fa","bg2":"#ffffff","bg3":"#e8ecf0",
        "accent":"#0077aa","accent2":"#cc4400","accent3":"#886600",
        "red":"#cc0022","green":"#117733","muted":"#6b7280","fg":"#1a1d23",
    },
    "High Contrast": {
        "bg":"#000000","bg2":"#0a0a0a","bg3":"#1a1a1a",
        "accent":"#ffff00","accent2":"#ff8800","accent3":"#ffffff",
        "red":"#ff4444","green":"#00ff88","muted":"#bbbbbb","fg":"#ffffff",
    },
    "Deuteranopia-Safe": {
        "bg":"#0d1117","bg2":"#161b22","bg3":"#21262d",
        "accent":"#56b4e9","accent2":"#e69f00","accent3":"#f0e442",
        "red":"#cc79a7","green":"#0072b2","muted":"#8b949e","fg":"#e6edf3",
    },
    "Protanopia-Safe": {
        "bg":"#0d1117","bg2":"#161b22","bg3":"#21262d",
        "accent":"#00b4d8","accent2":"#fca311","accent3":"#e9c46a",
        "red":"#a8dadc","green":"#2196f3","muted":"#8b949e","fg":"#e6edf3",
    },
}

@app.get("/api/themes")
async def api_themes():
    return {"themes": list(_THEMES.keys()), "palette": _THEMES}

# ── Export CSV ─────────────────────────────────────────────────────────────────
from fastapi.responses import StreamingResponse
import csv, io

@app.get("/api/export/csv/{dataset}")
async def api_export_csv(dataset: str):
    """Export dataset as CSV. dataset: qsos | missing | bands | rate | dupes"""
    with STATE._lock:
        if not STATE.contest_log:
            return JSONResponse({"error": "No log loaded"}, status_code=400)
        cl = STATE.contest_log

    rows, headers = [], []
    fname = f"vkcontest_{dataset}.csv"

    if dataset == "qsos":
        headers = ["call","band","mode","mult1","pts","dupe","time"]
        rows    = [[q.get(h,"") for h in headers] for q in cl.qsos]

    elif dataset == "missing":
        mbr = cl.mults_by_region()
        headers = ["mult","region"]
        for region, data in mbr.items():
            for m in data.get("missing",[]):
                rows.append([m, region])

    elif dataset == "bands":
        be = cl.band_efficiency()
        if be:
            headers = list(be[0].keys())
            rows    = [[r.get(h,"") for h in headers] for r in be]

    elif dataset == "rate":
        rh = cl.rate_by_hour()
        headers = ["hour","qsos"]
        rows    = [[str(h), n] for h, n in rh]

    elif dataset == "dupes":
        by_band, by_call = cl.dupe_analysis()
        headers = ["type","key","count"]
        for b, n in by_band.items(): rows.append(["band", b, n])
        for c, n in by_call.items(): rows.append(["call", c, n])

    buf = io.StringIO()
    w   = csv.writer(buf)
    w.writerow(headers)
    w.writerows(rows)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )

# ── Snapshot (PNG of current overview) — returns JSON data for client-side render
@app.get("/api/snapshot_data")
async def api_snapshot_data():
    """Return full snapshot for client-side screenshot rendering."""
    return STATE.snapshot()


# ── OS Theme detection ────────────────────────────────────────────────────────
import subprocess as _subprocess

@app.get("/api/os_theme")
async def api_os_theme():
    """Detect OS dark/light mode preference."""
    import platform
    system = platform.system()
    try:
        if system == "Windows":
            import winreg
            key  = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return {"theme": "Light" if val == 1 else "Dark (Default)"}
        elif system == "Darwin":
            result = _subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True, text=True)
            return {"theme": "Dark (Default)" if "Dark" in result.stdout else "Light"}
        else:
            # Linux: check GTK settings
            result = _subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                capture_output=True, text=True)
            return {"theme": "Dark (Default)" if "dark" in result.stdout.lower() else "Light"}
    except Exception:
        return {"theme": "Dark (Default)"}

# ── Save notification helper ──────────────────────────────────────────────────
@app.get("/api/save_location")
async def api_save_location():
    """Return the default downloads/documents folder for the current OS."""
    import platform, os
    system = platform.system()
    if system == "Windows":
        folder = os.path.join(os.path.expanduser("~"), "Downloads")
    elif system == "Darwin":
        folder = os.path.join(os.path.expanduser("~"), "Downloads")
    else:
        folder = os.path.join(os.path.expanduser("~"), "Downloads")
    return {"folder": folder, "os": system}

# ── Map data endpoint ─────────────────────────────────────────────────────────
# Simple prefix→lat/lon lookup for major DXCC prefixes

import subprocess as _subprocess

@app.get("/api/os_theme")
async def api_os_theme():
    import platform
    system = platform.system()
    try:
        if system == "Windows":
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return {"theme": "Light" if val == 1 else "Dark (Default)"}
        elif system == "Darwin":
            r = _subprocess.run(["defaults","read","-g","AppleInterfaceStyle"],
                capture_output=True, text=True)
            return {"theme": "Dark (Default)" if "Dark" in r.stdout else "Light"}
        else:
            r = _subprocess.run(["gsettings","get","org.gnome.desktop.interface","color-scheme"],
                capture_output=True, text=True)
            return {"theme": "Dark (Default)" if "dark" in r.stdout.lower() else "Light"}
    except Exception:
        return {"theme": "Dark (Default)"}

@app.get("/api/save_location")
async def api_save_location():
    import platform, os
    return {"folder": os.path.join(os.path.expanduser("~"), "Downloads"), "os": platform.system()}

# Prefix lat/lon lookup (ASCII minus only)
# DXCC prefix lookup — longer prefixes listed first to take priority over shorter ones
# e.g. "FK8" (New Caledonia) matched BEFORE "F" (France)
_PFX = {}

# 4-char prefixes
for k,v in [("KH6 ",(21,-158)),("KH8 ",(-14,-171)),("KP4 ",(18,-67))]:
    _PFX[k.strip()] = v

# Pacific / Oceania 3-char (BEFORE shorter prefixes like F)
for k,v in [
    ("FK8",(-22,167)),  # New Caledonia
    ("FK7",(-19,158)),  # Chesterfield Is
    ("FO8",(-18,-149)), # French Polynesia
    ("KH6",(21,-158)),  # Hawaii
    ("KH0",(15,146)),   # Mariana Is
    ("KH2",(13,145)),   # Guam
    ("KL7",(61,-150)),  # Alaska
    ("KP4",(18,-67)),   # Puerto Rico
    ("P29",(-9,148)),   # Papua New Guinea
    ("ZK2",(-19,-170)), # Niue
    ("3D2",(-18,178)),  # Fiji
    ("5W1",(-14,-172)), # Samoa
    ("T30",(0,174)),    # W Kiribati
    ("V63",(7,158)),    # Micronesia
    ("V73",(9,168)),    # Marshall Is
    ("YJ8",(-15,168)),  # Vanuatu
    ("E51",(-10,-161)), # N Cook Is
    ("E52",(-20,-158)), # S Cook Is
    ("ZL8",(-29,-178)), # Kermadec
    ("ZL9",(-53,169)),  # Subantarctic NZ
]:
    _PFX[k] = v

# All remaining 2-char and common prefixes
for k,v in [
    ("FK",(-22,167)),   # New Caledonia (all FK)
    ("FG",(16,-62)),    ("FH",(-13,45)),   ("FM",(14,-61)),
    ("FO",(-18,-149)),  ("FP",(47,-56)),   ("FR",(-21,56)),
    ("FW",(-14,-178)),  ("FY",(4,-53)),
    ("ZL",(-41,174)),   ("ZS",(-30,26)),   ("ZP",(-23,-58)),
    ("ZA",(41,20)),     ("ZB",(36,-5)),    ("ZF",(19,-81)),
    ("ZK",(-19,-170)),  ("ZD",(-16,-6)),
    ("VE",(45,-76)),    ("VK",(-25,134)),  ("VO",(47,-53)),
    ("VR",(22,114)),    ("VU",(21,78)),    ("V3",(17,-89)),
    ("V5",(-22,17)),    ("V6",(7,158)),    ("V7",(9,168)),
    ("V8",(5,115)),
    ("G", (52,-1)),     ("GM",(57,-4)),    ("GW",(52,-4)),
    ("GD",(54,-4)),     ("GJ",(49,-2)),    ("GU",(50,-3)),
    ("DL",(51,10)),     ("DJ",(51,10)),    ("DK",(51,10)),
    ("DA",(51,10)),     ("DB",(51,10)),    ("DC",(51,10)),
    ("DF",(51,10)),     ("DG",(51,10)),    ("DH",(51,10)),
    ("JA",(36,138)),    ("JE",(36,138)),   ("JH",(36,138)),
    ("JR",(36,138)),    ("JD",(27,142)),
    ("BY",(35,105)),    ("BG",(35,105)),   ("BH",(35,105)),
    ("BV",(25,122)),    ("BU",(25,122)),   # Taiwan
    ("UA",(56,38)),     ("RA",(56,38)),    ("RK",(56,38)),
    ("RL",(56,38)),     ("RM",(56,38)),    ("RN",(56,38)),
    ("RO",(56,38)),     ("RQ",(56,38)),    ("RT",(56,38)),
    ("RU",(56,38)),     ("RV",(56,38)),    ("RW",(56,38)),
    ("RX",(56,38)),     ("RY",(56,38)),    ("RZ",(56,38)),
    ("UA9",(56,60)),    # Asiatic Russia (overridden by 3-char below)
    ("UI",(56,60)),     ("UK",(41,64)),    ("UN",(51,71)),    ("UR",(50,31)),
    ("OH",(62,26)),     ("OG",(62,26)),    ("OZ",(56,10)),
    ("OX",(64,-51)),    ("OY",(62,-7)),    ("OE",(48,14)),
    ("OK",(50,16)),     ("OL",(50,16)),    ("OM",(48,17)),
    ("ON",(51,4)),    ("OO",(51,4)),    ("OP",(51,4)),    ("OQ",(51,4)),
    ("OR",(51,4)),    ("OS",(51,4)),    ("OT",(51,4)),
    ("SM",(60,15)),     ("SK",(60,15)),
    ("SP",(52,20)),     ("SN",(52,20)),    ("SQ",(52,20)),
    ("SV",(38,24)),     ("SW",(38,24)),
    ("PA",(52,5)),      ("PB",(52,5)),     ("PD",(52,5)),
    ("PE",(52,5)),      ("PH",(52,5)),
    ("PY",(-10,-55)),   ("PP",(-10,-55)),  ("PQ",(-10,-55)),
    ("PR",(-10,-55)),   ("PS",(-10,-55)),  ("PU",(-10,-55)),
    ("PW",(-10,-55)),   ("PX",(-10,-55)),
    ("EA",(40,-4)),     ("EB",(40,-4)),    ("EC",(40,-4)),
    ("EI",(53,-8)),     ("EJ",(53,-8)),    ("EK",(40,45)),
    ("EP",(33,54)),     ("ER",(47,29)),    ("ES",(59,25)),
    ("EU",(53,28)),     ("EW",(53,28)),    ("EX",(43,75)),
    ("EY",(39,71)),     ("EZ",(38,58)),
    ("HA",(47,19)),     ("HB",(47,8)),     ("HC",(-2,-78)),
    ("HH",(19,-72)),    ("HI",(19,-70)),   ("HK",(4,-74)),
    ("HL",(37,127)),    ("DS",(37,127)),
    ("HP",(9,-80)),     ("HR",(15,-87)),   ("HS",(15,101)),
    ("HV",(42,12)),     ("HZ",(24,45)),
    ("LA",(60,10)),     ("LB",(60,10)),    ("LC",(60,10)),
    ("LU",(-34,-64)),   ("LV",(-34,-64)),  ("LW",(-34,-64)),
    ("LX",(50,6)),      ("LY",(56,24)),    ("LZ",(43,25)),
    ("I", (43,12)),     ("IS",(40,9)),     ("IG",(37,14)),
    ("YA",(34,69)),     ("YB",(-7,110)),   ("YC",(-7,110)),
    ("YI",(33,44)),     ("YJ",(-17,168)),  ("YK",(35,38)),
    ("YL",(57,25)),     ("YN",(12,-86)),   ("YO",(45,25)),
    ("YT",(44,21)),     ("YU",(44,21)),    ("YV",(10,-67)),
    ("TA",(39,35)),     ("TF",(65,-18)),   ("TI",(10,-84)),
    ("TK",(42,9)),      ("TL",(6,19)),     ("TN",(-4,15)),
    ("TR",(0,12)),      ("TT",(12,15)),    ("TU",(7,-6)),
    ("TY",(10,2)),      ("TZ",(13,-2)),
    ("XE",(20,-100)),   ("XW",(18,103)),   ("XV",(16,108)),
    ("XU",(12,105)),    ("XT",(13,-2)),
    ("4X",(31,35)),     ("4Z",(31,35)),
    ("5A",(27,17)),     ("5B",(35,33)),    ("5H",(-6,35)),
    ("5N",(9,8)),       ("5R",(-19,47)),   ("5T",(18,-16)),
    ("5U",(14,8)),      ("5V",(8,1)),      ("5W",(-14,-172)),
    ("5X",(1,32)),      ("5Z",(1,38)),
    ("6W",(15,-14)),    ("6Y",(18,-77)),
    ("7P",(-29,28)),    ("7Q",(-14,34)),   ("7X",(28,3)),
    ("8P",(13,-59)),    ("8Q",(4,74)),     ("8R",(5,-59)),
    ("9A",(45,16)),     ("9G",(8,-2)),     ("9H",(35,14)),
    ("9J",(-15,28)),    ("9K",(29,47)),    ("9L",(8,-12)),
    ("9M",(4,108)),     ("9N",(28,84)),    ("9Q",(-4,24)),
    ("9V",(1,104)),     ("9W",(4,108)),    ("9X",(-2,30)),
    ("9Y",(10,-61)),
    ("A2",(-22,24)),    ("A3",(-21,-175)), ("A4",(23,58)),
    ("A5",(27,90)),     ("A6",(24,54)),    ("A7",(25,51)),
    ("A9",(26,51)),
    ("CE",(-30,-71)),   ("CO",(22,-80)),
    ("CT",(39,-9)),     ("CU",(38,-28)),   ("CX",(-33,-56)),
    ("D2",(-8,18)),     ("D4",(16,-24)),   ("D6",(-12,44)),
    ("E7",(44,17)),
    ("OA",(-12,-77)),   ("OB",(-12,-77)),
    ("P2",(-9,147)),    ("P4",(12,-70)),
    ("T7",(44,12)),
    ("CE",(-30,-71)),
    ("JT",(47,106)),
    ("VE",(45,-76)),
    # 1-char LAST — only matched if nothing longer matched
    ("F",(47,2)),       # France
    ("W",(39,-98)),     # USA
    ("K",(39,-98)),     # USA
    ("N",(39,-98)),     # USA
    ("R",(56,38)),      # Russia
]:
    _PFX[k] = v


# ── Call-area digit refinement ────────────────────────────────────────────────
# A single country-wide centroid is far too coarse for geographically huge
# countries where the call-area digit itself names the region (e.g. K6 =
# California, not "somewhere in the contiguous US"). These tables are checked
# before the generic _PFX lookup so the digit wins when present.
_US_CALL_AREA = {
    "0": (41, -98),   # CO/IA/KS/MN/MO/NE/ND/SD
    "1": (43, -71),   # New England
    "2": (41, -74),   # NY/NJ
    "3": (39, -77),   # PA/DE/MD/DC
    "4": (33, -84),   # AL/FL/GA/KY/NC/SC/TN/VA
    "5": (32, -97),   # AR/LA/MS/NM/OK/TX
    "6": (37, -120),  # CA
    "7": (44, -114),  # AZ/ID/MT/NV/OR/UT/WA/WY
    "8": (40, -82),   # MI/OH/WV
    "9": (41, -89),   # IL/IN/WI
}

# Brazilian amateur prefixes use second-letter P..Y (PP, PQ, PR, PS, PT, PU,
# PV, PW, PX, PY); the digit names the call area/state. Approximation: the
# canonical PY-digit regions are used for every P[P-Y] block, which is exact
# for PY itself and a reasonable regional approximation for the others.
_BR_CALL_AREA = {
    "0": (-3.85, -32.4),   # oceanic (Fernando de Noronha etc.)
    "1": (-22.9, -43.2),   # Rio de Janeiro
    "2": (-23.5, -46.6),   # Sao Paulo
    "3": (-30.0, -51.2),   # Rio Grande do Sul
    "4": (-19.9, -43.9),   # Minas Gerais
    "5": (-25.4, -49.3),   # Parana
    "6": (-12.9, -38.5),   # Bahia
    "7": (-8.1, -34.9),    # Pernambuco
    "8": (-1.5, -48.5),    # Para
    "9": (-15.6, -56.1),   # Mato Grosso
}
_BR_LETTERS = set("PQRSTUVWXY")

_MX_CALL_AREA = {
    "1": (19.4, -99.1),    # Central (CDMX)
    "2": (28.0, -110.0),   # Northwest
    "3": (19.0, -92.0),    # Southeast
}

# Australia allocates AX/VH/VI/VJ/VK/VL/VM/VN/VZ as one ITU block. VK is the
# standard prefix; VI and AX substitute for VK on special-event callsigns
# (Bicentennial, Olympics, Australia Day, etc); VJ/VK/VL are the official
# "2x1" contest-callsign prefixes (e.g. VJ5W). All of them use the SAME
# call-area digit -> state/territory mapping as standard VK callsigns.
_AU_PREFIXES = ("VK", "VH", "VI", "VJ", "VL", "VM", "VN", "VZ", "AX")
_AU_CALL_AREA = {
    "0": (-54.5, 158.9),  # Macquarie Is / Antarctic stations
    "1": (-35, 149),      # ACT
    "2": (-34, 151),      # NSW
    "3": (-38, 145),      # VIC
    "4": (-28, 153),      # QLD
    "5": (-35, 139),      # SA
    "6": (-32, 116),      # WA
    "7": (-43, 147),      # TAS
    "8": (-13, 131),      # NT
    "9": (-14, 126),      # external territories (Christmas I. etc)
}


def _call_to_latlon(callsign: str):
    """Best-effort callsign to [lat, lon]. Tries prefixes longest-first."""
    call = callsign.upper().strip()

    if call[:1] in ("W", "K", "N") and len(call) > 1 and call[1] in _US_CALL_AREA:
        return _US_CALL_AREA[call[1]]
    if (len(call) > 2 and call[0] == "P" and call[1] in _BR_LETTERS
            and call[2] in _BR_CALL_AREA):
        return _BR_CALL_AREA[call[2]]
    if call[:2] in ("XE", "XF") and len(call) > 2 and call[2] in _MX_CALL_AREA:
        return _MX_CALL_AREA[call[2]]
    if call[:2] in _AU_PREFIXES and len(call) > 2 and call[2] in _AU_CALL_AREA:
        return _AU_CALL_AREA[call[2]]

    # Try 4, 3, 2, 1 char prefixes
    for n in [4, 3, 2, 1]:
        if n <= len(call) and call[:n] in _PFX:
            return _PFX[call[:n]]
    # Ultimate fallback for an Australian-looking call with no usable digit
    if call[:2] in _AU_PREFIXES:
        return [-25, 134]
    return None



@app.get("/api/map_data")
async def api_map_data():
    with STATE._lock:
        if not STATE.contest_log:
            return []
        qsos = list(STATE.contest_log.qsos)
    agg = {}
    for q in qsos:
        if q.get("dupe"):
            continue
        call = q.get("call", "").upper()
        if not call:
            continue
        ll = _call_to_latlon(call)
        if not ll:
            continue
        if call not in agg:
            agg[call] = {"call": call, "band": q.get("band", "?"),
                         "lat": ll[0], "lon": ll[1], "count": 0,
                         "mult": q.get("mult1", "")}
        agg[call]["count"] += 1
    return list(agg.values())


# ── WebSocket live feed ───────────────────────────────────────────────────────

@app.websocket("/ws/live")
async def ws_live(ws: WebSocket):
    await ws.accept()
    STATE._clients.append(ws)
    try:
        await ws.send_text(json.dumps({
            "type": "snapshot",
            "data": STATE.snapshot(),
        }))
        while True:
            try:
                await asyncio.wait_for(ws.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                await ws.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("WebSocket error")
    finally:
        try:
            STATE._clients.remove(ws)
        except ValueError:
            pass


async def _broadcast(data: dict):
    msg  = json.dumps({"type": "snapshot", "data": data})
    dead = []
    for ws in list(STATE._clients):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        try:
            STATE._clients.remove(ws)
        except ValueError:
            pass


async def _poll_loop():
    while True:
        await asyncio.sleep(STATE.poll_interval)
        changed = await asyncio.get_event_loop().run_in_executor(
            None, STATE.poll_once
        )
        if changed:
            await _broadcast(STATE.snapshot())


# ═══════════════════════════════════════════════════════════════════════════════
# ── PyWebView launcher ────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def launch_webview(db_path: Optional[str] = None, port: Optional[int] = None):
    port = port or _find_free_port()
    url  = f"http://127.0.0.1:{port}"
    STATE._base_url = url

    # Pre-load if a valid file was passed on the command line
    if db_path and os.path.isfile(db_path):
        STATE.load_db(db_path)

    config = uvicorn.Config(
        app, host="127.0.0.1", port=port,
        log_level="warning", loop="asyncio",
        log_config=None,   # use our own logging setup, not uvicorn's default
                            # (its formatter calls sys.stdout.isatty(), which
                            # is None in a windowed/console=False build)
    )
    server = uvicorn.Server(config)

    def _run_server():
        asyncio.run(server.serve())

    server_thread = threading.Thread(target=_run_server, daemon=True, name="uvicorn")
    server_thread.start()

    # Wait until the server is accepting connections (max 5 seconds)
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                break
        except OSError:
            time.sleep(0.1)

    # If pywebview can't start for ANY reason (missing .NET Framework,
    # missing WebView2 Runtime, etc.), log the real error and fall back to
    # the system browser instead of failing with no visible error at all.
    try:
        import webview

        # pywebview's WebView2 backend silently cancels every download unless
        # this is explicitly enabled (default False) — without it, CSV/report
        # exports via the in-page <a download> click do nothing with no error.
        webview.settings['ALLOW_DOWNLOADS'] = True

        # Frameless: the OS title bar (and its minimize/maximize/close buttons)
        # is gone, so the frontend draws its own (#window-controls in
        # index.html) and calls back into _WindowApi below via pywebview's
        # js_api bridge. easy_drag is explicitly OFF — pywebview's easy_drag
        # makes mousedown+move ANYWHERE in the page drag the window, which
        # would fight the tile drag-to-reorder feature and the zoom slider.
        # Instead, only elements with the 'pywebview-drag-region' class
        # (the titlebar logo/title — see index.html) act as a drag handle.
        #
        # toggle_maximize deliberately does NOT use window.maximize()/restore().
        # WinForms' native maximize sizes the window to Screen.Bounds (the full
        # monitor rectangle) instead of Screen.WorkingArea once FormBorderStyle
        # is None (i.e. frameless) — a long-standing WinForms quirk where a
        # borderless form's maximize no longer accounts for the taskbar, so it
        # visibly doesn't "fill" the usable screen correctly. Instead we move
        # window .resize()/.move() to the real work-area rect ourselves.
        from webview.window import FixPoint

        _MIN_W, _MIN_H = 900, 600   # keep in sync with min_size below

        # ── Restore window geometry from the previous session ────────────────
        # Saved by _on_closing() below into the same small JSON store used for
        # log-folder settings. Anything missing or out of sane bounds (e.g. a
        # position from a monitor that's no longer connected) is discarded in
        # favor of pywebview's own default placement/size, rather than risking
        # an off-screen or too-small window the user can't get back from.
        _saved_geom = _load_settings().get("window_geometry") or {}

        def _valid_dim(v, lo, hi):
            return isinstance(v, (int, float)) and lo <= v <= hi

        def _matches_monitor_bounds(w, h):
            """A saved "windowed" size that's within a few pixels of some
            connected monitor's full width AND height is corrupt, not a
            real user-resized window: seen in practice after an earlier
            build let a Linux window get latched at full-monitor size by
            the WM's edge-tiling/snap-assist (see toggle_maximize()) while
            this app's own _maximized flag still read False, so
            _save_window_geometry() saved that stuck full-monitor size as
            the plain windowed geometry on close. Every subsequent
            "restore" then correctly returned to that already-fullscreen-
            looking size, forever, which is indistinguishable from the
            original bug to the user even once the toggle itself works."""
            try:
                for s in webview.screens:
                    if w >= s.width - 5 and h >= s.height - 5:
                        return True
            except Exception:
                pass
            return False

        _saved_w, _saved_h = _saved_geom.get("width"), _saved_geom.get("height")
        if (_valid_dim(_saved_w, _MIN_W, 10000) and _valid_dim(_saved_h, _MIN_H, 10000)
                and _matches_monitor_bounds(_saved_w, _saved_h)):
            log.info("Discarding saved window geometry %sx%s — matches a monitor's full bounds", _saved_w, _saved_h)
            _saved_geom = {k: v for k, v in _saved_geom.items() if k not in ("width", "height")}

        _init_w = int(_saved_geom["width"]) if _valid_dim(_saved_geom.get("width"), _MIN_W, 10000) else 1400
        _init_h = int(_saved_geom["height"]) if _valid_dim(_saved_geom.get("height"), _MIN_H, 10000) else 860
        _init_x = _saved_geom.get("x")
        _init_y = _saved_geom.get("y")
        _has_init_pos = _valid_dim(_init_x, -100, 10000) and _valid_dim(_init_y, -100, 10000)
        _initial_maximized = bool(_saved_geom.get("maximized"))

        _maximized     = False   # starts windowed regardless of _initial_maximized — see _on_loaded below
        _pre_max_geom  = None    # (x, y, width, height) to restore back to

        def _save_window_geometry():
            """Shared by the native 'closing' event and the custom titlebar's
            close button (_WindowApi.close(), which bypasses window.destroy()
            entirely — see its docstring) — both need this written before the
            process exits."""
            try:
                settings = _load_settings()
                if _maximized and _pre_max_geom:
                    x, y, w, h = _pre_max_geom
                    settings["window_geometry"] = {"x": x, "y": y, "width": w, "height": h, "maximized": True}
                else:
                    settings["window_geometry"] = {
                        "x": window.x, "y": window.y,
                        "width": window.width, "height": window.height,
                        "maximized": False,
                    }
                _save_settings(settings)
            except Exception:
                log.exception("Failed to save window geometry")

        def _start_shutdown():
            """Closes WebSocket clients, stops uvicorn, hard-exits. Runs in a
            background thread since this is called directly from the GUI
            thread (either as window.events.closed or from _WindowApi.close())
            and the actual work below — notably server_thread.join() — must
            never block that thread's event loop."""
            log.info("Window closed — shutting down")

            def _shutdown():
                # Redirect stderr to suppress the noisy WebView2/Chromium window-class
                # unregister error that Windows logs during teardown:
                #   "Failed to unregister class Chrome_WidgetWin_0. Error = 1411"
                # This is benign (the class was already unregistered by the time the
                # renderer tries again) but confusing in logs.
                _devnull = open(os.devnull, "w")
                os.dup2(_devnull.fileno(), 2)   # redirect fd 2 (stderr) to /dev/null

                # Close WebSocket clients gracefully — STATE._main_loop (the
                # actual running uvicorn event loop, set in lifespan()) is
                # required here: asyncio.get_event_loop() from this thread
                # would hand back a fresh, never-running loop, silently
                # dropping every ws.close() onto a loop nothing ever drives.
                try:
                    if STATE._main_loop:
                        for ws in list(STATE._clients):
                            try:
                                asyncio.run_coroutine_threadsafe(ws.close(), STATE._main_loop)
                            except Exception:
                                pass
                except Exception:
                    pass
                STATE._clients.clear()

                # Signal uvicorn to stop
                server.should_exit = True

                # Give uvicorn up to 2 seconds to finish in-flight requests
                server_thread.join(timeout=2.0)

                # Hard exit — releases port binding and removes from Task Manager.
                # os._exit skips atexit/finally blocks that can hang on Windows.
                os._exit(0)

            threading.Thread(target=_shutdown, daemon=True, name="shutdown").start()

        def _current_screen():
            """The monitor the window is actually on, not always screens[0] —
            on a multi-monitor Linux setup, maximizing a window sitting on
            monitor 2 previously moved/resized it onto monitor 1's bounds
            instead, since it always used screens[0]."""
            try:
                cx = window.x + window.width // 2
                cy = window.y + window.height // 2
                for s in webview.screens:
                    if s.x <= cx < s.x + s.width and s.y <= cy < s.y + s.height:
                        return s
            except Exception:
                pass
            return webview.screens[0]

        def _move_window(x, y):
            """pywebview's GTK backend (webview/platforms/gtk.py) captures
            monitor 0's origin once at window-creation time and adds it to
            every move() call, regardless of which monitor the window is
            currently on or being moved to. That silently mis-places the
            window on any multi-monitor Linux setup where monitor 0 isn't at
            (0, 0) — go through the real GTK window directly (window.native,
            set by pywebview once the window is shown) to bypass it, since
            Gtk.Window.move() already takes absolute root-window coordinates
            with no extra offset needed."""
            if sys.platform.startswith("linux") and getattr(window, "native", None) is not None:
                window.native.move(int(x), int(y))
            else:
                window.move(int(x), int(y))

        class _WindowApi:
            def minimize(self):
                window.minimize()

            def is_maximized(self):
                return _maximized

            def toggle_maximize(self):
                nonlocal _maximized, _pre_max_geom
                if not _maximized:
                    _pre_max_geom = (window.x, window.y, window.width, window.height)
                    screen = _current_screen()
                    work = getattr(screen, 'frame', None)
                    if work is not None and hasattr(work, 'Width'):
                        x, y, w, h = work.X, work.Y, work.Width, work.Height
                    else:
                        x, y, w, h = screen.x, screen.y, screen.width, screen.height
                    if sys.platform.startswith("linux"):
                        # Confirmed via vkca_errors.log on Cinnamon/Muffin:
                        # gtk_window_is_maximized() stayed False the entire
                        # time (before AND after calling native.unmaximize()),
                        # so this was never a GTK/EWMH-tracked maximize state
                        # to begin with — that ruled out the WM-auto-maximize
                        # theory an earlier version of this code chased.
                        # What actually happened: the window got permanently
                        # wedged at the full-monitor size — every subsequent
                        # "maximize" logged the *previous* maximize's size as
                        # its pre_geom, meaning the resize-back never took
                        # visual effect even once. That matches Muffin's
                        # edge-tiling/snap-assist, which silently latches a
                        # window once its edges exactly coincide with a
                        # monitor's bounds on all four sides — a state
                        # outside GTK's own maximize tracking entirely, so
                        # nothing on the GTK side can detect or clear it.
                        # Undershooting the target by a pixel keeps the
                        # window from ever exactly touching the monitor
                        # edges, avoiding that WM heuristic in the first
                        # place — imperceptible on screen, but the window
                        # stays a normal, freely resizable one.
                        w -= 1
                        h -= 1
                    log.info("toggle_maximize: maximizing — pre_geom=%s target=%s", _pre_max_geom, (x, y, w, h))
                    # resize() BEFORE move(): resize_to() (edge/corner drag
                    # resizing, above) sets the GTK window's gravity to
                    # whatever corner is opposite the dragged edge (e.g.
                    # SOUTH_EAST for a north-west corner drag) and that
                    # gravity persists on the window afterward — it's not
                    # reset until the next resize() call. window.resize()
                    # here uses the default NORTH_WEST fix point, which DOES
                    # reset it. Calling move() first would target x,y under
                    # whatever gravity was last left set, positioning some
                    # OTHER corner of the window there instead of the
                    # top-left — often landing far off (frequently clamped
                    # to 0,0), which is what "restore homes to top-left"
                    # was. Resizing first resets gravity to NORTH_WEST so
                    # the following move() is correctly interpreted as a
                    # top-left-corner target.
                    window.resize(w, h)
                    _move_window(x, y)
                elif _pre_max_geom:
                    x, y, w, h = _pre_max_geom
                    log.info("toggle_maximize: restoring — target=%s", (x, y, w, h))
                    window.resize(w, h)
                    _move_window(x, y)
                _maximized = not _maximized
                return _maximized

            def close(self):
                # Deliberately does NOT call window.destroy(): on this
                # (frameless, custom-titlebar) window that call goes through
                # pywebview's GTK glib.idle_add(...)/close_window() path,
                # which was observed to hang indefinitely — the native
                # 'closing'/'closed' events never even fired (checked via
                # the window_geometry save's mtime never updating), so
                # whatever's stuck is inside that native teardown, before
                # our own code runs at all. Since the process hard-exits
                # via os._exit() either way, there's nothing gained by
                # routing through GTK's WebView-destroy machinery for this
                # button — save geometry and shut down directly instead.
                _save_window_geometry()
                _start_shutdown()

            def get_size(self):
                # One-shot snapshot the frontend reads at the start of an
                # edge/corner drag (see wireResizeHandles in app.js) — the
                # rest of the drag computes absolute sizes from this origin
                # instead of round-tripping on every mousemove.
                return {'width': window.width, 'height': window.height}

            def resize_to(self, width, height, edge):
                # 'edge' is which border/corner is being dragged ('n', 'sw',
                # etc). FixPoint anchors the *opposite* side so e.g. dragging
                # the left edge grows the window leftward instead of
                # pywebview's default top-left-anchored growth.
                nonlocal _maximized
                _maximized = False
                width  = max(_MIN_W, int(width))
                height = max(_MIN_H, int(height))
                horiz = FixPoint.EAST if 'w' in edge else FixPoint.WEST
                vert  = FixPoint.SOUTH if 'n' in edge else FixPoint.NORTH
                window.resize(width, height, horiz | vert)

            def get_position(self):
                # Same one-shot-snapshot pattern as get_size(): the frontend
                # reads this once at the start of a titlebar drag (see
                # wireDragRegions in app.js) and computes the rest of the
                # drag itself from mouse deltas (screenX/screenY), sending
                # incremental move_to() calls on its own throttle.
                #
                # This bypasses pywebview's own built-in drag-region handling
                # (the 'pywebview-drag-region' class + easy_drag machinery)
                # entirely. That built-in path is unreliable on the Linux
                # GTK/WebKit2 backend: with easy_drag=False (required here so
                # dragging doesn't fight the zoom slider / tile reordering),
                # window movement falls back to a bridge that derives the
                # new position from MouseEvent.screenX/screenY combined with
                # platforms/gtk.py's move() re-adding the screen origin,
                # which snaps the window toward the top-left the instant a
                # drag starts.
                return {'x': window.x, 'y': window.y}

            def move_to(self, x, y):
                nonlocal _maximized
                _maximized = False
                _move_window(x, y)

            def open_external(self, url):
                # window.open() from inside pywebview's embedded WebView is
                # unreliable — notably on the Linux GTK/WebKit2 backend it
                # silently no-ops instead of launching a browser (same class
                # of native-shell fragility as the drag handling above), so
                # buttons meant to open an external URL (Report Issue submit,
                # AI-assist links) appear to do nothing. webbrowser.open()
                # shells out to the OS (xdg-open/open/start) instead, which
                # works the same way the app's own restart-into-browser path
                # (see webbrowser.open(url) elsewhere in this file) already
                # relies on.
                if not (isinstance(url, str) and url.startswith(("http://", "https://"))):
                    return
                import webbrowser
                webbrowser.open(url)

        _window_api = _WindowApi()
        _create_kwargs = dict(
            title="VK Contest Analyzer",
            url=url,
            width=_init_w,
            height=_init_h,
            min_size=(900, 600),
            background_color="#0d1117",
            frameless=True,
            easy_drag=False,
            js_api=_window_api,
        )
        if _has_init_pos:
            _create_kwargs['x'] = int(_init_x)
            _create_kwargs['y'] = int(_init_y)
        window = webview.create_window(**_create_kwargs)

        def _on_loaded():
            STATE._webview_window = window
            # Applied here rather than passed to create_window(): maximizing
            # is manual work-area math (see toggle_maximize() above, re the
            # WinForms taskbar quirk) that needs the window's real geometry
            # to already exist, which isn't settled until after creation.
            if _initial_maximized:
                _window_api.toggle_maximize()

        # These native events are the fallback path for any close route that
        # isn't our custom titlebar button — e.g. a window manager/taskbar
        # close, Alt+F4, or 'q' via some accessibility tool. The button
        # itself calls _save_window_geometry()/_start_shutdown() directly
        # (see _WindowApi.close()) without going through window.destroy(),
        # since that path was observed to hang indefinitely on Linux/GTK.
        window.events.closing += _save_window_geometry
        window.events.closed  += _start_shutdown

        # webview.start() blocks here until the window closes.
        # _on_closed will call os._exit(0) so execution never returns here
        # under normal circumstances.
        webview.start(_on_loaded, debug=False)

        # Fallback for non-PyWebView / browser-direct mode
        server.should_exit = True
        sys.exit(0)
        return
    except Exception:
        log.exception(
            "Embedded window failed to start — falling back to the default "
            "browser. Common causes: the bundled .NET runtime failed to load "
            "(see preceding log entry), or the Microsoft Edge WebView2 "
            "Runtime is missing on this machine."
        )

    import webbrowser
    webbrowser.open(url)
    log.info("Opened %s in the default browser — close this process via Task Manager to stop the server.", url)
    try:
        server_thread.join()
    except KeyboardInterrupt:
        pass
    server.should_exit = True


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else None
    launch_webview(db_path=db)
