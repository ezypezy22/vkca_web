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
from contest_log import ContestLog, cqz_from_call
from plugins.loader import plugin_for, get_all_plugins
from plugins.generic import GenericPlugin
import cosb
import qrz
import radio_udp
import rigctld

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

# Guards every settings-file read-modify-write sequence below (see
# _settings_read_modify_write()) so two roughly-simultaneous writers (e.g.
# adding a log-dir folder while removing QRZ credentials, or a window-close
# geometry save racing a Settings POST) can't each read-modify-write with no
# synchronization and silently clobber one another's change (see issue #61).
# A plain threading.Lock, not asyncio.Lock: callers include both async
# handlers (via run_in_executor, so this runs on a worker thread) and
# genuinely synchronous callbacks (the native window-closing handler).
_settings_lock = threading.Lock()


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


def _settings_read_modify_write(mutate_fn):
    """Atomically load the settings file, let `mutate_fn(settings)` mutate
    the dict in place, save it back, and return `mutate_fn`'s return value —
    all under _settings_lock so the whole read-modify-write sequence is one
    critical section (see issue #61). This function does blocking file I/O;
    call it via run_in_executor from async handlers."""
    with _settings_lock:
        settings = _load_settings()
        result = mutate_fn(settings)
        _save_settings(settings)
        return result


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
        # Spectator Mode: a second, LAN-facing read-only listener, started/
        # stopped on demand via /api/spectator. Deliberately not persisted —
        # see spectator_app below for why. All None while off.
        self._spectator_server                    = None  # uvicorn.Server
        self._spectator_task                      = None  # asyncio.Task running .serve()
        self._spectator_sock                      = None  # its pre-bound listening socket
        self._spectator_url: Optional[str]        = None  # e.g. "http://192.168.1.23:51234/spectator"
        self._webview_window                      = None  # set after webview starts
        self._base_url:     Optional[str]         = None  # set after webview starts; used by /api/popout
        self._hud_window                          = None  # the single Mini HUD window, if open
        self._operator_hud_window                 = None  # the single Operator HUD window, if open
        # Serializes each HUD's check-existing/reuse-or-create sequence below
        # so two concurrent /api/hud (or /api/operator_hud) requests can't
        # both see no existing window and each create one, orphaning the
        # first (see issue #51).
        self._hud_lock                            = asyncio.Lock()
        self._operator_hud_lock                   = asyncio.Lock()
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
        self._shutting_down                       = False   # set by _start_shutdown(); tells _poll_loop() to stop
        # Live radio state from N1MM+'s RadioInfo UDP broadcast (see
        # web/radio_udp.py) — written by the n1mm-udp-listener thread,
        # keyed by "<source_ip>|<radio_nr>". Guarded by self._lock like
        # everything else shared across threads in this class.
        self.radio_info:    dict                  = {}
        self._radio_last_broadcast: float         = 0.0
        # Set by radio_udp.run_radio_info_listener() if it couldn't bind its
        # UDP port at all (most likely cause: another process — including a
        # leftover/second copy of this app — already has it). Surfaced in the
        # UI instead of just logging it, since an empty radio readout with no
        # explanation otherwise looks identical to "N1MM+ just isn't
        # broadcasting yet" and sends the operator chasing the wrong fix.
        self.radio_bind_error: Optional[str]      = None
        # True only for a log created via POST /api/new_log (standalone
        # logging mode — see that endpoint and POST /api/qsos/add). Reset
        # False on every ordinary /api/load, since that's always opening a
        # file this app didn't create and shouldn't ever write into — the
        # single source of truth the Log Entry tab's visibility and its
        # own API's write-gate both check.
        self.is_standalone_log: bool               = False
        # Set by _start_radio_listener() so a Settings-triggered port change
        # can stop the currently-running listener thread before starting a
        # new one on the new port — see that function for why a per-restart
        # stop signal is needed rather than reusing _shutting_down (that one
        # means "whole app is closing", not "just this one listener thread").
        self._radio_listener_thread                = None   # threading.Thread
        self._radio_listener_stop                  = None   # threading.Event
        # rigctld (Hamlib) rig control — standalone Logger mode only, see
        # rigctld.py and _sync_rigctld() below. rigctld_conn is the shared
        # RigctldConnection used both by the poller thread (reads) and by
        # the /api/rig/* write endpoints (set_mode/send_morse/stop_morse);
        # None whenever rig control isn't currently active.
        self.rigctld_conn                          = None
        self._rigctld_thread                       = None   # threading.Thread
        self._rigctld_stop                         = None   # threading.Event
        self.rigctld_status: Optional[str]          = None
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
            my_call  = ContestLog.station_call(path)
            result   = []
            for ct in contests:
                p = plugin_for(str(ct.get("ContestName", "")), my_call)
                result.append({
                    "contest_nr":   ct["ContestNR"],
                    "contest_name": ct.get("ContestName", ""),
                    "display_name": ct.get("DisplayName", ct.get("ContestName", "")),
                    "start_date":   str(ct.get("StartDate", ""))[:10],
                    "qso_count":    ct.get("QSOCount", 0),
                    "plugin":       p.display_name,
                })
            return {"ok": True, "path": path, "contests": result,
                     "is_standalone": ContestLog.is_standalone_marker(path)}
        except Exception as exc:
            log.exception("scan_contests failed")
            return {"error": str(exc)}

    # ── Full load (creates ContestLog + compute_snapshot) ────────────────────

    def load_db(self, path: str, contest_nr: Optional[int] = None,
                plugin=None, standalone: bool = False) -> dict:
        path = str(Path(path).resolve())
        err  = self.validate_path(path)
        if err:
            return {"error": err}
        try:
            cl = ContestLog(path, contest_nr=contest_nr, plugin=plugin)
            # Enrichment + the full compute_snapshot() recompute both run
            # against the local `cl` here, before it's published to
            # self.contest_log — see poll_once()'s own comment just below
            # for why that matters (self._lock is a plain threading.Lock
            # shared with the asyncio event loop's own synchronous
            # `with STATE._lock:` uses elsewhere).
            self._enrich_qsos(cl)
            mtime    = os.path.getmtime(path)
            snapshot = self._compute_snapshot_for(cl)
            with self._lock:
                self.db_path       = path
                self.contest_nr    = contest_nr
                self.plugin        = plugin
                self.contest_log   = cl
                self.last_mtime    = mtime
                self.last_snapshot = snapshot
                # standalone=True from /api/new_log's own call, OR
                # auto-detected from the file itself (VKCA_Meta marker, see
                # ContestLog.create_new_log()) — this is what lets a
                # previously-created standalone log survive an app restart:
                # /api/load never passes standalone=True, but the marker
                # travels with the file and is re-detected on every
                # ordinary open, not just ones explicitly called "new log."
                self.is_standalone_log = standalone or ContestLog.is_standalone_marker(path)
            return {"ok": True, "path": path}
        except Exception as exc:
            log.exception("load_db failed")
            return {"error": str(exc)}

    def _compute_snapshot_for(self, cl) -> dict:
        if not cl:
            return {}
        try:
            return _json_safe(cl.compute_snapshot())
        except Exception as exc:
            log.exception("compute_snapshot failed")
            return {"error": str(exc)}

    def _safe_snapshot(self) -> dict:
        """For callers that already hold self._lock and want to recompute
        from the currently-published self.contest_log in place (e.g. after
        patching a QSO dict or deleting a QSO) — see _compute_snapshot_for()
        for the "not yet published, safe to run outside the lock" variant
        load_db()/poll_once() use instead, so a multi-thousand-QSO log's
        full recompute doesn't hold self._lock — and therefore stall every
        other thread's (and the asyncio event loop's own) `with self._lock`
        — for its entire duration."""
        return self._compute_snapshot_for(self.contest_log)

    def poll_once(self, force: bool = False) -> bool:
        """Check mtime; reload ContestLog if changed (or always, if force).
        Returns True if updated.

        Builds the new ContestLog, enriches it, and runs the full
        compute_snapshot() recompute all *before* touching self._lock —
        only the final publish (four attribute assignments) happens under
        the lock. self._lock is a plain threading.Lock also acquired
        synchronously by ~35 call sites across the async request handlers
        and the radio_info/QRZ broadcast bridges; holding it across a full
        recompute (previously done here) blocked the entire asyncio event
        loop — every websocket, every HTTP request, every open window —
        for however long that recompute took, any time this 5-second poll
        cycle happened to be mid-recompute when something else needed the
        lock. That's very likely why the live radio readout (and every
        other live update) seemed to randomly stall rather than reliably
        lag by a fixed amount."""
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
            self._enrich_qsos(cl)
            snapshot = self._compute_snapshot_for(cl)
            with self._lock:
                self.contest_log   = cl
                self.last_mtime    = mtime
                self.last_snapshot = snapshot
            return True
        except Exception:
            log.exception("poll_once reload failed")
            return False

    def snapshot(self) -> dict:
        with self._lock:
            snap = dict(self.last_snapshot)
            snap["radio_info"] = self._own_and_all_radios()
            return snap

    def _own_and_all_radios(self) -> dict:
        """Must be called with self._lock already held (same convention as
        _enrich_qsos — see its own comment). Returns
        {"own": <entry>|None, "all": {key: entry, ...}, "bind_error": str|None}:
          - "all" is every radio seen recently, live and stale alike — the
            Operator HUD needs the full set to match against every
            operator's own callsign, including a since-gone-stale one it
            can grey out rather than silently drop.
          - "own" is this station's own best-guess radio for the
            single-readout surfaces (Mini HUD / titlebar / Overview panel):
            prefer a loopback-sourced entry (N1MM+'s own default broadcast
            target) with the lowest radio_nr, or the one flagged active
            if there's more than one (SO2R); fall back to the lowest
            radio_nr site-wide if nothing came from loopback (covers a
            LAN-broadcast N1MM+ setup). Only a LIVE (non-stale) entry
            counts for "own", so a disconnected rig reads as "no radio"
            instead of freezing on the last frequency shown.
        """
        now = time.time()
        live = {k: v for k, v in self.radio_info.items()
                if now - v.get("updated_at", 0) < radio_udp.STALE_AFTER_SECS}

        own = None
        loopback = [v for v in live.values() if v.get("source_ip") in ("127.0.0.1", "::1")]
        candidates = loopback or list(live.values())
        if candidates:
            active = [v for v in candidates if v.get("active")]
            pool = active or candidates
            own = min(pool, key=lambda v: v.get("radio_nr", "1"))

        return {"own": own, "all": dict(self.radio_info), "bind_error": self.radio_bind_error}

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
            # Same overlay STATE.snapshot() itself does — this function
            # broadcasts a manually-built snap dict instead of going
            # through snapshot() (see the recompute note above), so it has
            # to repeat the overlay explicitly or every radio_info-driven
            # UI (titlebar chip, Mini HUD tile, Overview panel, Operator
            # HUD badge, DX Cluster "on the air" board) would flicker
            # blank on every QRZ-triggered broadcast — found live: the
            # cluster board showed briefly on a radio-triggered broadcast,
            # then vanished on the very next QRZ one.
            snap["radio_info"] = STATE._own_and_all_radios()
        asyncio.run_coroutine_threadsafe(_broadcast(snap), STATE._main_loop)


def _radio_info_maybe_broadcast():
    """Same cross-thread bridge as _qrz_maybe_broadcast() just above, for
    the n1mm-udp-listener thread (web/radio_udp.py). Without this, a live
    frequency change only reaches connected clients (Mini HUD, titlebar,
    etc.) by coincidence — whenever an unrelated QSO or QRZ-driven
    broadcast happens to fire — since radio_info updates independently of
    both (found during manual verification: the titlebar picked up a test
    packet immediately because a QRZ broadcast happened to fire around the
    same time, but the just-opened Mini HUD, which hadn't received that
    broadcast, kept showing "no radio" until the next unrelated one).
    No recompute needed here (unlike QRZ) — STATE.snapshot() already
    overlays the freshest radio_info on every call.

    The debounce window is much shorter than QRZ's 1.5s (which coalesces
    a many-callsign Enrich All batch, where nobody's watching each result
    land individually): this one is watched live while tuning, where every
    step matters. state.radio_info itself is updated in place on every
    single packet regardless — this only throttles how often that gets
    *pushed* — so too long a window silently drops every intermediate
    frequency between broadcasts, e.g. spinning the VFO from 7150 to 7155
    would only ever show the first and last step, never the ones between.

    60ms (~16/s, one "frame" at a typical display refresh rate) is about
    as low as this can usefully go — a human can't perceive anything
    tighter as more responsive, and STATE.snapshot() is cheap post-lock-
    refactor (see poll_once()'s docstring), so the broadcast itself isn't
    the bottleneck this is guarding. It still exists as a hard floor
    against a genuinely pathological flood (a flaky CAT interface
    spamming noise), just no longer tuned as if the broadcast were
    expensive."""
    now = time.time()
    if now - STATE._radio_last_broadcast < 0.06:
        return
    STATE._radio_last_broadcast = now
    if STATE._main_loop is not None:
        asyncio.run_coroutine_threadsafe(_broadcast(STATE.snapshot()), STATE._main_loop)


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


def _start_radio_listener(port: int):
    """(Re)starts the N1MM+ RadioInfo UDP listener on `port`. Safe to call
    while one is already running (a Settings-triggered port change): signals
    the current thread to stop and waits briefly for it to release the old
    socket before binding the new one, so the two never overlap and briefly
    fight over which one owns the port. Runs blocking I/O (thread join) —
    call via run_in_executor from async handlers, same as the settings
    read-modify-write helpers.
    """
    old_thread = STATE._radio_listener_thread
    if old_thread and old_thread.is_alive():
        STATE._radio_listener_stop.set()
        old_thread.join(timeout=2.0)   # loop polls stop_check ~1x/sec (socket timeout)

    with STATE._lock:
        STATE.radio_info = {}   # stale entries from the old port would otherwise
                                 # linger and look like a still-live readout
    stop_event = threading.Event()
    STATE._radio_listener_stop = stop_event
    # _freq_to_band_str is passed in rather than imported by radio_udp.py,
    # which deliberately doesn't import anything from this module (it's
    # imported BY this module to start this thread — importing back would
    # be circular). See radio_udp.py's own module docstring.
    t = threading.Thread(
        target=radio_udp.run_radio_info_listener,
        args=(STATE, _freq_to_band_str,
              lambda: STATE._shutting_down or stop_event.is_set(),
              _radio_info_maybe_broadcast, port),
        daemon=True, name="n1mm-udp-listener",
    )
    STATE._radio_listener_thread = t
    t.start()


def _sync_rigctld():
    """(Re)evaluates whether the rigctld poller should be running — it's
    only ever active for a standalone log (STATE.is_standalone_log) with
    rig control enabled in settings, see rigctld.py's own module docstring
    for why. Called from load_db() (the one place is_standalone_log can
    change) and from the rigctld settings POST handler (toggling/
    reconfiguring while a standalone log is already open). Runs blocking
    I/O (thread join) — call via run_in_executor from async handlers, same
    as _start_radio_listener().
    """
    settings = _load_settings()
    cfg = settings.get("rigctld") or {}
    should_run = STATE.is_standalone_log and bool(cfg.get("enabled"))

    old_thread = STATE._rigctld_thread
    if old_thread and old_thread.is_alive():
        STATE._rigctld_stop.set()
        old_thread.join(timeout=3.0)   # loop polls stop_check ~1x/sec
    STATE._rigctld_thread = None

    if not should_run:
        with STATE._lock:
            STATE.radio_info.pop("rigctld|1", None)   # stale entry would otherwise
            STATE.rigctld_status = None                # linger and look still-live
        return

    host = cfg.get("host") or rigctld.DEFAULT_HOST
    port = cfg.get("port") or rigctld.DEFAULT_PORT
    stop_event = threading.Event()
    STATE._rigctld_stop = stop_event
    t = threading.Thread(
        target=rigctld.run_rigctld_poller,
        args=(STATE, _freq_to_band_str,
              lambda: STATE._shutting_down or stop_event.is_set(),
              _radio_info_maybe_broadcast, host, port),
        daemon=True, name="rigctld-poller",
    )
    STATE._rigctld_thread = t
    t.start()


@asynccontextmanager
async def lifespan(application: FastAPI):
    STATE._main_loop = asyncio.get_running_loop()
    settings = _load_settings()
    creds = settings.get("qrz_credentials")
    if creds:
        STATE._qrz_client.set_credentials(creds.get("username"), creds.get("password"))
    threading.Thread(target=_qrz_worker_loop, daemon=True, name="qrz-worker").start()
    _start_radio_listener(settings.get("radio_port") or radio_udp.DEFAULT_PORT)
    asyncio.create_task(_poll_loop())
    yield


app = FastAPI(title="VK Contest Analyzer Web", lifespan=lifespan)

_STATIC = _HERE / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.middleware("http")
async def _no_cache_headers(request, call_next):
    """WebView2's storage_path (see launch_webview()) keeps a *persistent*
    HTTP cache in %LOCALAPPDATA%\\VKContestAnalyzer\\webview_storage across
    app restarts AND reinstalls/upgrades — and FileResponse/StaticFiles set
    no Cache-Control header, so absent this, Chromium's heuristic freshness
    can silently keep serving a previous version's cached index.html/JS/CSS
    even after the exe on disk has been rebuilt and relaunched. This is a
    loopback-only app with no real caching upside, so just always
    revalidate rather than let a stale UI linger invisibly after an update."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache"
    return response


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


@app.get("/operator_hud")
async def operator_hud_page():
    """Same SPA-serving trick as /hud above, for the per-operator HUD."""
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

    def _mutate(settings):
        dirs = settings.setdefault("log_dirs", [])
        key = os.path.normcase(os.path.normpath(resolved))
        if not any(os.path.normcase(os.path.normpath(d)) == key for d in dirs):
            dirs.append(resolved)
        return dirs

    dirs = await asyncio.get_event_loop().run_in_executor(
        None, _settings_read_modify_write, _mutate)
    return {"ok": True, "dirs": dirs}


@app.delete("/api/settings/log_dirs")
async def api_remove_log_dir(body: dict):
    path = (body.get("path") or "").strip()

    def _mutate(settings):
        dirs = settings.setdefault("log_dirs", [])
        key = os.path.normcase(os.path.normpath(path))
        dirs[:] = [d for d in dirs if os.path.normcase(os.path.normpath(d)) != key]
        return dirs

    dirs = await asyncio.get_event_loop().run_in_executor(
        None, _settings_read_modify_write, _mutate)
    return {"ok": True, "dirs": dirs}


# ── Radio Setup (N1MM+ RadioInfo UDP listener port) ───────────────────────────
# Default is 12060, matching N1MM+'s own Config → Configure Ports →
# Broadcast Data → Radio default — but that's a well-known enough port that
# other ham radio software sometimes binds it for an unrelated feature (e.g.
# SmartSDR's "Focus Helper" defaults to the same 12060). Letting the user
# move this app's own listener elsewhere gives them a way out without
# needing to touch the other program at all — they just also repoint N1MM+'s
# own broadcast port to match.

@app.get("/api/settings/radio_port")
async def api_radio_port_get():
    port = _load_settings().get("radio_port") or radio_udp.DEFAULT_PORT
    with STATE._lock:
        bind_error = STATE.radio_bind_error
    return {"port": port, "default_port": radio_udp.DEFAULT_PORT, "bind_error": bind_error}


@app.post("/api/settings/radio_port")
async def api_radio_port_post(body: dict):
    try:
        port = int(body.get("port"))
    except (TypeError, ValueError):
        return JSONResponse({"error": "Port must be a number."}, status_code=400)
    if not (1 <= port <= 65535):
        return JSONResponse({"error": "Port must be between 1 and 65535."}, status_code=400)

    def _mutate(settings):
        settings["radio_port"] = port

    await asyncio.get_event_loop().run_in_executor(
        None, _settings_read_modify_write, _mutate)
    await asyncio.get_event_loop().run_in_executor(None, _start_radio_listener, port)
    # run_radio_info_listener()'s bind() attempt happens synchronously at the
    # very start of the thread — this just gives it a moment to actually run
    # before reading back whether it succeeded.
    await asyncio.sleep(0.3)
    with STATE._lock:
        bind_error = STATE.radio_bind_error
    return {"ok": True, "port": port, "bind_error": bind_error}


# ── Rig Control (Hamlib rigctld) — standalone Logger mode only ────────────────
# See rigctld.py's own module docstring for the read side (radio_info
# entries, fed by the poller thread _sync_rigctld() starts/stops). This
# section is Settings persistence plus the write-side /api/rig/* endpoints
# (mode change, F-key CW macros) — every one gated on STATE.is_standalone_log
# so this app never sends a rig command outside its own standalone Logger
# mode (see the plan's safety-boundary rationale).

_RIGCTLD_MACRO_DEFAULTS = {
    "1": "CQ TEST {CALL}",   # F1 CQ
    "2": "5NN",              # F2 Contest
    "3": "TU",               # F3 TNX
    "5": "{HISCALL}",        # F5 His Call — sends whatever's currently typed
                             # in the Call field (see api_rig_send_morse)
    "7": "QRZ?",             # F7 QRZ?
    "8": "AGN?",             # F8 Agn?
    "9": "ZONE?",            # F9 Zone?
}

# The bands every plugin's band_list() actually returns (see e.g.
# plugins/allasian.py, plugins/cqww.py) — a fixed set of per-band QSY
# default frequencies, left unset (no numeric default) until the operator
# configures them in Settings. Deliberately NOT pre-filled with this app's
# own guess at band-plan segment edges — an assumed default a few kHz
# outside the operator's actual license privileges is a real-world
# transmit-out-of-band risk, not just a UI nicety to get "close enough".
_RIGCTLD_BAND_KEYS = ["160M", "80M", "40M", "20M", "15M", "10M"]


@app.get("/api/settings/rigctld")
async def api_rigctld_get():
    cfg = _load_settings().get("rigctld") or {}
    macros = dict(_RIGCTLD_MACRO_DEFAULTS)
    macros.update(cfg.get("macros") or {})
    band_defaults_in = cfg.get("band_defaults") or {}
    band_defaults = {b: band_defaults_in.get(b) for b in _RIGCTLD_BAND_KEYS if band_defaults_in.get(b)}
    with STATE._lock:
        status    = STATE.rigctld_status
        connected = STATE.rigctld_conn is not None and status is None
    return {
        "enabled":       bool(cfg.get("enabled")),
        "host":          cfg.get("host") or rigctld.DEFAULT_HOST,
        "port":          cfg.get("port") or rigctld.DEFAULT_PORT,
        "macros":        macros,
        "band_defaults": band_defaults,
        "status":        status,
        "connected":     connected,
    }


@app.post("/api/settings/rigctld")
async def api_rigctld_post(body: dict):
    enabled = bool(body.get("enabled"))
    host    = (body.get("host") or rigctld.DEFAULT_HOST).strip()
    try:
        port = int(body.get("port") or rigctld.DEFAULT_PORT)
    except (TypeError, ValueError):
        return JSONResponse({"error": "Port must be a number."}, status_code=400)
    if not (1 <= port <= 65535):
        return JSONResponse({"error": "Port must be between 1 and 65535."}, status_code=400)
    macros_in = body.get("macros") or {}
    macros = {k: str(v) for k, v in macros_in.items() if k in _RIGCTLD_MACRO_DEFAULTS}

    band_defaults_in = body.get("band_defaults") or {}
    band_defaults = {}
    for b in _RIGCTLD_BAND_KEYS:
        raw = band_defaults_in.get(b)
        if raw in (None, ""):
            continue
        try:
            hz = int(float(raw) * 1000)   # operator enters kHz (e.g. 3535 = 3.535 MHz)
        except (TypeError, ValueError):
            return JSONResponse({"error": f"{b} default frequency must be a number (kHz)."}, status_code=400)
        if hz <= 0:
            return JSONResponse({"error": f"{b} default frequency must be positive."}, status_code=400)
        band_defaults[b] = hz

    def _mutate(settings):
        settings["rigctld"] = {"enabled": enabled, "host": host, "port": port,
                                "macros": macros, "band_defaults": band_defaults}

    await asyncio.get_event_loop().run_in_executor(
        None, _settings_read_modify_write, _mutate)
    await asyncio.get_event_loop().run_in_executor(None, _sync_rigctld)
    # Mirrors /api/settings/radio_port's own settle-then-report pattern —
    # the poller's first connect attempt happens synchronously at thread
    # start, so a brief pause lets a bad host/port show up as a real error
    # instead of always reporting "connecting..." on the first read-back.
    await asyncio.sleep(0.3)
    with STATE._lock:
        status    = STATE.rigctld_status
        connected = STATE.rigctld_conn is not None and status is None
    return {"ok": True, "status": status, "connected": connected}


def _rig_control_guard() -> Optional[JSONResponse]:
    if not STATE.is_standalone_log:
        return JSONResponse(
            {"error": "Rig control is only available for a standalone log (Logger mode)."},
            status_code=400)
    if STATE.rigctld_conn is None:
        return JSONResponse({"error": "rigctld is not connected."}, status_code=503)
    return None


@app.post("/api/rig/set_mode")
async def api_rig_set_mode(body: dict):
    guard = _rig_control_guard()
    if guard:
        return guard
    mode = (body.get("mode") or "").strip().upper()
    if not mode:
        return JSONResponse({"error": "No mode supplied."}, status_code=400)
    conn = STATE.rigctld_conn
    ok, err = await asyncio.get_event_loop().run_in_executor(None, conn.set_mode, mode)
    if not ok:
        return JSONResponse({"error": err}, status_code=502)
    return {"ok": True}


@app.post("/api/rig/set_freq")
async def api_rig_set_freq(body: dict):
    """Body: {freq_hz}. Used both for the band buttons' QSY-on-click (see
    entrywindow.js — the frequency itself, remembered-per-band or a
    Settings-configured default, is computed client-side, never guessed
    here) and the direct frequency-entry field."""
    guard = _rig_control_guard()
    if guard:
        return guard
    try:
        freq_hz = int(body.get("freq_hz"))
    except (TypeError, ValueError):
        return JSONResponse({"error": "freq_hz must be a number."}, status_code=400)
    if freq_hz <= 0:
        return JSONResponse({"error": "freq_hz must be positive."}, status_code=400)
    conn = STATE.rigctld_conn
    ok, err = await asyncio.get_event_loop().run_in_executor(None, conn.set_freq, freq_hz)
    if not ok:
        return JSONResponse({"error": err}, status_code=502)
    return {"ok": True}


@app.post("/api/rig/send_morse")
async def api_rig_send_morse(body: dict):
    """Body: {fkey: "1".."11", his_call: <optional, currently-typed Call
    field>}. Macro text (Settings → Rig Control) supports {CALL} (own
    callsign, from the log's Station table) and {HISCALL} (the his_call
    passed in, for the F5 "His Call" macro)."""
    guard = _rig_control_guard()
    if guard:
        return guard
    fkey = str(body.get("fkey") or "")
    cfg = _load_settings().get("rigctld") or {}
    macros = dict(_RIGCTLD_MACRO_DEFAULTS)
    macros.update(cfg.get("macros") or {})
    text = (macros.get(fkey) or "").strip()
    if not text:
        return JSONResponse({"error": f"No macro configured for F{fkey}."}, status_code=400)
    my_call  = getattr(STATE.contest_log, "my_call", None) or ""
    his_call = (body.get("his_call") or "").strip().upper()
    text = text.replace("{CALL}", my_call).replace("{HISCALL}", his_call).strip()
    if not text:
        return JSONResponse(
            {"error": "Macro resolved to empty text (e.g. His Call with nothing typed in Call yet)."},
            status_code=400)
    conn = STATE.rigctld_conn
    ok, err = await asyncio.get_event_loop().run_in_executor(None, conn.send_morse, text)
    if not ok:
        return JSONResponse({"error": err}, status_code=502)
    return {"ok": True, "sent": text}


@app.post("/api/rig/stop_morse")
async def api_rig_stop_morse():
    guard = _rig_control_guard()
    if guard:
        return guard
    conn = STATE.rigctld_conn
    # Best-effort — not every rig backend supports aborting mid-send, so a
    # failure here is reported but the caller (entrywindow.js) shouldn't
    # treat it as an alarming hard error.
    ok, err = await asyncio.get_event_loop().run_in_executor(None, conn.stop_morse)
    return {"ok": ok, "error": None if ok else err}


# ── Overview panel layout (drag-reorder + hide/show) ──────────────────────────
# Persists what was previously localStorage-only (overview.js's tile reorder/
# hide system) so a custom layout survives a fresh profile/cache clear, same
# durability guarantee every other setting here already has. One flat dict
# keyed by section — {"spark":[...tileKeys], "info":[...], "ea":[...],
# "gauge":[...], "hidden":[...tileKeys]} — written as a whole on every save
# since these are infrequent, user-driven edits (drag end / hide toggle).

@app.get("/api/settings/panel_layout")
async def api_panel_layout_get():
    return {"layout": _load_settings().get("panel_layout") or {}}


@app.post("/api/settings/panel_layout")
async def api_panel_layout_post(body: dict):
    layout = body.get("layout")
    if not isinstance(layout, dict):
        return JSONResponse({"error": "Invalid layout."}, status_code=400)

    def _mutate(settings):
        settings["panel_layout"] = layout

    await asyncio.get_event_loop().run_in_executor(
        None, _settings_read_modify_write, _mutate)
    return {"ok": True}


# ── Overview canvas layout (freeform drag/resize grid, "Canvas Mode") ────────
# Separate key from panel_layout, not a variant of it — the two modes' saved
# shapes are structurally different (panel_layout: per-section ordered
# tileKey arrays; this: per-tileKey {x,y,w,h} plus one `enabled` flag).
# Switching modes never has to touch or invalidate the other's saved state.

@app.get("/api/settings/canvas_layout")
async def api_canvas_layout_get():
    return {"layout": _load_settings().get("canvas_layout") or {}}


@app.post("/api/settings/canvas_layout")
async def api_canvas_layout_post(body: dict):
    layout = body.get("layout")
    if not isinstance(layout, dict):
        return JSONResponse({"error": "Invalid layout."}, status_code=400)

    def _mutate(settings):
        settings["canvas_layout"] = layout

    await asyncio.get_event_loop().run_in_executor(
        None, _settings_read_modify_write, _mutate)
    return {"ok": True}


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

    def _mutate(settings):
        settings["qrz_credentials"] = {"username": username, "password": password}

    _settings_read_modify_write(_mutate)
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
    def _mutate(settings):
        settings.pop("qrz_credentials", None)

    await asyncio.get_event_loop().run_in_executor(
        None, _settings_read_modify_write, _mutate)
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
async def api_scan_known_locations(check_standalone: bool = False):
    """Look for contest databases in N1MM's default folder plus any
    user-added folders, so the user doesn't have to browse to/type a path
    for the common case. check_standalone opts into an extra per-file
    SQLite open (ContestLog.is_standalone_marker()) to flag which of these
    are this app's own previously-created standalone logs — off by default
    so the plain "Detected Databases" list (Analyzer's normal open flow)
    sees zero added cost; Logger mode's "resume a previous log" list is the
    only caller that passes it."""
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
                    **({"is_standalone": ContestLog.is_standalone_marker(str(f))} if check_standalone else {}),
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

    async with STATE._hud_lock:
        return await _do_open_hud()


async def _do_open_hud():
    existing = STATE._hud_window
    if existing is not None:
        def _restore():
            try:
                existing.show()   # pairs with _HudApi.close()'s hide() — see its docstring
            except Exception:
                pass
        await asyncio.get_event_loop().run_in_executor(None, _restore)
        return {"ok": True, "reused": True}

    def _open():
        import webview as _wv

        # Minimal counterpart to launch_webview()'s _WindowApi — just enough
        # to drag and close this one tiny bar (no minimize/maximize/resize,
        # it's a fixed-size glanceable window). Kept separate from the main
        # window's API/closure entirely: this is a different pywebview window
        # with its own js_api, wired up client-side in app.js's HUD-frame IIFE.
        class _HudApi:
            def get_position(self):
                return {"x": win.x, "y": win.y}

            def move_to(self, x, y):
                # Same Linux multi-monitor-offset bypass as the main window's
                # _move_window() — see its docstring for why native.move() is
                # needed there instead of window.move().
                if sys.platform.startswith("linux") and getattr(win, "native", None) is not None:
                    win.native.move(int(x), int(y))
                else:
                    win.move(int(x), int(y))

            def close(self):
                # Deliberately does NOT call win.destroy(): this window is
                # frameless (see create_window() below), and the main
                # window's own _WindowApi.close() already documented that
                # destroy() on a frameless window goes through pywebview's
                # GTK glib.idle_add(...)/close_window() path, observed to
                # hang indefinitely with the native 'closing'/'closed'
                # events never firing. The main window can just hard-exit
                # the whole process around that hang (os._exit in
                # _start_shutdown()) — this window can't, since the app
                # must keep running after the HUD closes. hide()/show()
                # sidesteps the native destroy teardown entirely: the
                # window object stays valid, so STATE._hud_window never
                # points at a zombie, and the reuse path above (existing.
                # show()) just un-hides the same window instead of
                # restoring one that may never have finished closing.
                win.hide()

            def focus_main(self):
                # Double-click brings the main window back to the front —
                # .show() on an already-visible window still calls the
                # underlying WinForms .Activate() (see winforms.py's own
                # show()), so this works whether the main window is merely
                # behind other apps or was minimized.
                main_win = STATE._webview_window
                if main_win is not None:
                    try:
                        main_win.show()
                    except Exception:
                        pass

            def resize(self, width, height):
                # Backs the horizontal/vertical orientation toggle — snaps
                # the window to a shape that actually suits the requested
                # layout instead of just rearranging content inside
                # whatever shape the window already happened to be.
                # fix_point defaults to NORTH|WEST (top-left stays put),
                # which is what you want here: the window doesn't jump to
                # a different screen position just because its size changed.
                try:
                    win.resize(int(width), int(height))
                except Exception:
                    pass

        win = _wv.create_window(
            title="VK Contest Analyzer — HUD",
            url=f"{STATE._base_url}/hud",
            # Tall enough for the field row to wrap onto a second line
            # without clipping — the HUD grew from 5 to 7 fields (mults,
            # session added), plus 4 of those got a mini sparkline canvas
            # under the value, and doesn't all fit on one row at this
            # width any more. Physical height doesn't map 1:1 to CSS px
            # (measured ~131 CSS px at height=170 on this dev machine's
            # display scaling) — sized up further with real margin rather
            # than chasing an exact ratio that'll differ per user anyway.
            width=780, height=210,
            # Lowered from (360, 120): the vertical orientation resizes
            # this window down to a genuinely narrow column (see resize()
            # above and HUD_ORIENTATIONS in overview.js), which needs a
            # smaller floor than the horizontal layout ever did on its own.
            min_size=(150, 120),
            background_color="#0d1117",
            on_top=True,
            frameless=True,
            js_api=_HudApi(),
        )
        STATE._hud_window = win
        win.events.closed += lambda: setattr(STATE, "_hud_window", None)

    try:
        await asyncio.get_event_loop().run_in_executor(None, _open)
        return {"ok": True}
    except Exception as exc:
        log.exception("hud failed")
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/operator_hud")
async def api_operator_hud():
    """Open the per-operator HUD (/operator_hud) in its own always-on-top
    pywebview window — one card per operator (QSOs, current rate, on-air %,
    sparkline), useful in a Multi-Multi contest where several operators are
    running simultaneously. Mirrors /api/hud's window-lifecycle exactly
    (reuse/restore via hide()/show(), never destroy() — see _HudApi.close()'s
    docstring above for why) but as a separate window/API/state slot, since
    both HUDs can reasonably be open at once."""
    if STATE._webview_window is None or not STATE._base_url:
        return JSONResponse({"error": "PyWebView window not ready"}, status_code=503)

    async with STATE._operator_hud_lock:
        return await _do_open_operator_hud()


async def _do_open_operator_hud():
    existing = STATE._operator_hud_window
    if existing is not None:
        def _restore():
            try:
                existing.show()
            except Exception:
                pass
        await asyncio.get_event_loop().run_in_executor(None, _restore)
        return {"ok": True, "reused": True}

    def _open():
        import webview as _wv

        # Deliberately a separate class from _HudApi above, not a
        # parameterized shared one — _HudApi is a closure over its own `win`
        # laced with platform-specific workarounds (Linux move offset, GTK
        # destroy-hang), and duplicating ~50 lines here is a smaller risk
        # than threading a second window through that fragile code.
        class _OperatorHudApi:
            def get_position(self):
                return {"x": win.x, "y": win.y}

            def move_to(self, x, y):
                if sys.platform.startswith("linux") and getattr(win, "native", None) is not None:
                    win.native.move(int(x), int(y))
                else:
                    win.move(int(x), int(y))

            def close(self):
                # See _HudApi.close()'s docstring above — same hide()-not-
                # destroy() reasoning applies to every frameless window here.
                win.hide()

            def focus_main(self):
                main_win = STATE._webview_window
                if main_win is not None:
                    try:
                        main_win.show()
                    except Exception:
                        pass

        win = _wv.create_window(
            title="VK Contest Analyzer — Operator HUD",
            url=f"{STATE._base_url}/operator_hud",
            # Narrow and tall rather than wide — cards stack in a single
            # vertical column (see #operator-hud-cards in style.css) full
            # window width each, so even a 1-2 operator log fills the window
            # instead of floating as a small box in a mostly-empty wide one.
            # Tall enough for ~2 cards at once; more scroll via the window's
            # own overflow-y:auto.
            width=360, height=560,
            min_size=(300, 240),
            background_color="#0d1117",
            on_top=True,
            frameless=True,
            js_api=_OperatorHudApi(),
        )
        STATE._operator_hud_window = win
        win.events.closed += lambda: setattr(STATE, "_operator_hud_window", None)

    try:
        await asyncio.get_event_loop().run_in_executor(None, _open)
        return {"ok": True}
    except Exception as exc:
        log.exception("operator_hud failed")
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
    plugin      = None
    if plugin_name:
        # station_call() disambiguates plugins that claim the same contest
        # name (e.g. ARRL DX's DX-station vs W/VE-station plugins — see
        # issue #40); a quick standalone read, done before the full
        # ContestLog (and its own Station.Call read) is constructed.
        my_call = await asyncio.get_event_loop().run_in_executor(
            None, ContestLog.station_call, path
        )
        plugin = plugin_for(plugin_name, my_call)

    result = await asyncio.get_event_loop().run_in_executor(
        None, STATE.load_db, path, contest_nr, plugin
    )
    if "ok" in result:
        await asyncio.get_event_loop().run_in_executor(None, _sync_rigctld)
        await _broadcast(STATE.snapshot())
    return result


# ── Standalone logging mode ───────────────────────────────────────────────────
# A second, opt-in way to get QSOs into this app besides opening an existing
# N1MM log: create a brand-new .s3db this app is the sole writer of, then log
# contacts into it via /api/qsos/add. Never writes into a file that wasn't
# created this way (STATE.is_standalone_log, set only by load_db(...,
# standalone=True) below) — this app has no precedent anywhere for a second
# process (N1MM) also writing to the same SQLite file at the same time, and
# a brand-new file sidesteps that risk entirely rather than trying to solve it.

@app.get("/api/contest_types")
async def api_contest_types():
    """List every registered contest plugin's display_name, for the "+ New
    Log" contest-type picker. A chosen name round-trips back through
    plugin_for() exactly like scan_contests()'s own `plugin` field already
    does for an opened file — plugins/loader.py's own startup self-check
    already guarantees that round-trip for every registered plugin, so no
    separate name-to-plugin mapping is needed here."""
    names = sorted(p.display_name for p in get_all_plugins() if not isinstance(p, GenericPlugin))
    return {"contests": names}


@app.post("/api/new_log")
async def api_new_log(body: dict):
    """Create a brand-new standalone contest log and load it, exactly like
    opening an existing one. Body: {path, contest_display_name, my_call}."""
    path                  = (body.get("path") or "").strip()
    contest_display_name  = (body.get("contest_display_name") or "").strip()
    my_call               = (body.get("my_call") or "").strip()
    if not path:
        return JSONResponse({"error": "No path supplied"}, status_code=400)
    if not contest_display_name:
        return JSONResponse({"error": "No contest type selected"}, status_code=400)
    if not my_call:
        return JSONResponse({"error": "No callsign supplied"}, status_code=400)

    p = Path(path)
    if p.exists():
        return JSONResponse({"error": f"File already exists: {path}"}, status_code=400)
    if p.suffix.lower() not in AppState._VALID_SUFFIXES:
        return JSONResponse(
            {"error": f"Expected a .s3db/.db/.sqlite file, got: {p.name}"}, status_code=400)

    plugin  = plugin_for(contest_display_name, my_call)
    cq_zone = cqz_from_call(my_call) or 0

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.get_event_loop().run_in_executor(
            None, ContestLog.create_new_log, str(p), contest_display_name, my_call, cq_zone)
    except Exception as exc:
        log.exception("create_new_log failed")
        return JSONResponse({"error": str(exc)}, status_code=500)

    result = await asyncio.get_event_loop().run_in_executor(
        None, STATE.load_db, str(p), 1, plugin, True)
    if "ok" in result:
        await asyncio.get_event_loop().run_in_executor(None, _sync_rigctld)
        await _broadcast(STATE.snapshot())
    return result


def _add_qso(call: str, band: str, mode: str, rst_sent: str, rst_rcvd: str, exchange: str,
              is_run: bool = False) -> dict:
    with STATE._lock:
        cl = STATE.contest_log
        if not cl or not STATE.is_standalone_log:
            return {"error": "Logging is only available for a log created via + New Log."}
        try:
            new_id = cl.add_qso(call, band, mode, rst_sent, rst_rcvd, exchange, is_run)
        except Exception as e:
            log.exception("add_qso failed")
            return {"error": str(e)}
    # Reload (not just append to cl.qsos in place) so the existing dupe/
    # scoring pipeline recomputes the new QSO exactly as it would for one
    # N1MM had logged — no second, parallel dupe-checking implementation
    # here. Mirrors _delete_qsos()'s own "recompute the cached snapshot
    # immediately, don't wait for the next poll" reasoning.
    result = STATE.load_db(STATE.db_path, STATE.contest_nr, STATE.plugin, True)
    if "error" in result:
        return result
    return {"ok": True, "qso_id": new_id}


@app.post("/api/qsos/add")
async def api_qsos_add(body: dict):
    """Log one new QSO into the current standalone log. Body: {call, band,
    mode, rst_sent, rst_rcvd, exchange, is_run}. is_run is optional (default
    False) — only the N1MM-style Entry Window's Run/S&P toggle sends it; the
    plain Log Entry tab form never does, so its QSOs are unaffected. 400s if
    the currently-loaded log isn't one this app created
    (STATE.is_standalone_log) — the guardrail that keeps this feature from
    ever writing into an opened N1MM file."""
    call = (body.get("call") or "").strip()
    band = (body.get("band") or "").strip()
    mode = (body.get("mode") or "").strip()
    if not call or not band or not mode:
        return JSONResponse({"error": "Call, band, and mode are required."}, status_code=400)

    result = await asyncio.get_event_loop().run_in_executor(
        None, _add_qso, call, band, mode,
        body.get("rst_sent") or "", body.get("rst_rcvd") or "", body.get("exchange") or "",
        bool(body.get("is_run")))
    if "error" in result:
        return JSONResponse(result, status_code=400)
    await _broadcast(STATE.snapshot())
    return result


def _update_qso(qso_id: str, call: str, band: str, mode: str, rst_sent: str, rst_rcvd: str,
                 exchange: str, is_run: bool = False) -> dict:
    with STATE._lock:
        cl = STATE.contest_log
        if not cl or not STATE.is_standalone_log:
            return {"error": "Editing is only available for a log created via + New Log."}
        if not any(q.get("qso_id") == qso_id for q in cl.qsos):
            return {"error": "QSO not found."}
        try:
            cl.update_qso(qso_id, call, band, mode, rst_sent, rst_rcvd, exchange, is_run)
        except Exception as e:
            log.exception("update_qso failed")
            return {"error": str(e)}
    # Reload so the existing dupe/scoring pipeline recomputes from scratch,
    # exactly as _add_qso() already does — no second, parallel implementation.
    result = STATE.load_db(STATE.db_path, STATE.contest_nr, STATE.plugin, True)
    if "error" in result:
        return result
    return {"ok": True, "qso_id": qso_id}


@app.post("/api/qsos/update")
async def api_qsos_update(body: dict):
    """Edit an existing QSO in the current standalone log. Body: {qso_id,
    call, band, mode, rst_sent, rst_rcvd, exchange, is_run}. Same
    is_standalone_log guardrail as /api/qsos/add — this never writes into
    an opened N1MM file, only a log this app created."""
    qso_id = (body.get("qso_id") or "").strip()
    call   = (body.get("call") or "").strip()
    band   = (body.get("band") or "").strip()
    mode   = (body.get("mode") or "").strip()
    if not qso_id:
        return JSONResponse({"error": "No qso_id supplied."}, status_code=400)
    if not call or not band or not mode:
        return JSONResponse({"error": "Call, band, and mode are required."}, status_code=400)

    result = await asyncio.get_event_loop().run_in_executor(
        None, _update_qso, qso_id, call, band, mode,
        body.get("rst_sent") or "", body.get("rst_rcvd") or "", body.get("exchange") or "",
        bool(body.get("is_run")))
    if "error" in result:
        return JSONResponse(result, status_code=400)
    await _broadcast(STATE.snapshot())
    return result


@app.get("/api/browse_save_file")
async def api_browse_save_file():
    """Trigger the OS native save-file dialog via pywebview — used to pick
    where a new standalone log gets created. Mirrors api_browse_folder/the
    existing OPEN-dialog browse endpoint exactly, just with SAVE instead."""
    win = STATE._webview_window
    if win is None:
        return JSONResponse({"error": "PyWebView window not ready"}, status_code=503)
    try:
        import webview as _wv
        result = win.create_file_dialog(
            dialog_type=_wv.FileDialog.SAVE,
            save_filename="new_contest.s3db",
            file_types=("Contest Log Files (*.s3db)", "All files (*.*)"),
        )
        if not result:
            return {"path": None}
        chosen = str(result if isinstance(result, str) else result[0])
        return {"path": chosen}
    except Exception as exc:
        log.exception("browse_save_file failed")
        return JSONResponse({"error": str(exc)}, status_code=500)


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

    # COSB has no real per-callsign-and-contest query (see cosb.fetch_live_
    # rank's docstring) — it can land on a DIFFERENT contest than the one
    # currently loaded, e.g. the loaded contest hasn't started yet (or
    # already ended) so COSB's "featured"/other-active scan finds a
    # separate contest the same callsign happens to be posting to. Only
    # trust the match when the loaded plugin's own identify() would also
    # claim the COSB-scraped contest label, so a same-callsign-but-
    # different-contest result never gets shown as if it were live
    # ranking for the loaded log.
    plugin    = getattr(cl, "plugin", None)
    cosb_name = result.get("contest_name", "")
    if plugin is not None and not isinstance(plugin, GenericPlugin):
        try:
            same_contest = plugin.identify(cosb_name)
        except Exception:
            same_contest = True   # don't hide data over an unrelated plugin bug
        if not same_contest:
            return {"available": False, "reason": "different_contest",
                     "call": call, "other_contest": cosb_name}

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
            qsos_by_hour  = dict(STATE.contest_log.rate_by_hour())
            mults_by_hour = dict(STATE.contest_log.mults_by_hour())
            hours = sorted(set(qsos_by_hour) | set(mults_by_hour))
            return [
                {"hour": h.isoformat(), "qsos": qsos_by_hour.get(h, 0), "mults": mults_by_hour.get(h, 0)}
                for h in hours
            ]
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
            return {"by_band": {}, "by_call": {}, "rule_text": ""}
        try:
            by_band, by_call = STATE.contest_log.dupe_analysis()
            return {
                "by_band": dict(by_band),
                "by_call": dict(sorted(by_call.items(),
                                       key=lambda x: x[1], reverse=True)[:50]),
                "rule_text": STATE.contest_log.plugin.dupe_rule_text,
            }
        except Exception:
            return {"by_band": {}, "by_call": {}, "rule_text": ""}

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


@app.get("/api/radio_info")
async def api_radio_info():
    """Live radio state from N1MM+'s RadioInfo UDP broadcast (see
    web/radio_udp.py). {"own": <entry>|None, "all": {key: entry, ...}}."""
    snap = STATE.snapshot()
    return snap.get("radio_info", {"own": None, "all": {}})







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
        if deleted:
            # Recompute the cached snapshot immediately (mirrors poll_once()'s
            # own reload path) — without this, connected clients keep seeing
            # the deleted QSOs until the next poll cycle notices the DB's
            # mtime changed, which can lag several seconds (see issue #52).
            STATE.last_snapshot = STATE._safe_snapshot()
        return {"deleted": deleted, "errors": errors}


@app.post("/api/qsos/delete")
async def api_qsos_delete(body: dict):
    """Permanently delete one or more QSOs from the database. Body: {qso_ids: [...]}"""
    qso_ids = body.get("qso_ids") or []
    if not qso_ids:
        return JSONResponse({"error": "No qso_ids supplied"}, status_code=400)
    result = await asyncio.get_event_loop().run_in_executor(None, _delete_qsos, qso_ids)
    if result.get("deleted"):
        await _broadcast(STATE.snapshot())
    return result


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

    # Per-band QSO mix — lets the Year-on-Year tab show whether this year's
    # band strategy (e.g. mostly 20m/15m vs. spread across 40/20/15/10) has
    # shifted from prior years, alongside the score/QSO/mult trajectories
    # above. Built off `valid` (every QSO, not just the once-per-hour
    # `acc` snapshots) so it's an exact final tally, not a bucket sample.
    band_counts: dict = {}
    for q in valid:
        b = (q.get("band") or "?").upper()
        band_counts[b] = band_counts.get(b, 0) + 1

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
        "final_band_counts": band_counts,
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
    - rework_window_hours: hours before a station may be reworked on the
      same band/mode, for contests with a rolling per-contact dupe timer
      instead of a fixed operating-block schedule — null if N/A (see
      ContestPlugin.rework_window_hours). Drives the Worked tab's
      "Time Left to Work" vs "Next Block In" countdown column.
    - cabrillo_contest_id: sponsor-defined CONTEST: id for a Cabrillo
      submission — null if unknown (see ContestPlugin.cabrillo_contest_id).
    - my_call: the logging station's own callsign, read from the log's
      Station table — null if unavailable. Both feed the Cabrillo export
      dialog's pre-filled fields.
    - is_standalone_log: True only for a log created via POST /api/new_log
      (see STATE.is_standalone_log) — gates the Log Entry tab's visibility.
    - rigctld_connected: True if the rigctld rig-control poller is currently
      live (see rigctld.py) — gates the Log Entry form's mode buttons and
      F-key CW macros.
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
        "rework_window_hours": getattr(p, "rework_window_hours", None),
        "cabrillo_contest_id": getattr(p, "cabrillo_contest_id", None),
        "my_call":          getattr(STATE.contest_log, "my_call", None),
        "is_standalone_log": STATE.is_standalone_log,
        "rigctld_connected": STATE.rigctld_conn is not None and STATE.rigctld_status is None,
    }


# ── DX Cluster ──────────────────────────────────────────────────────────────
import socket as _socket
import re as _re

_SPOT_RE = _re.compile(
    r"DX\s+de\s+(\S+?):?\s+(\d+(?:\.\d+)?)\s+(\S+)\s+(.*?)\s*(\d{4})Z?\s*$",
    _re.IGNORECASE,
)
# Strips stray control bytes (e.g. a trailing BEL some clusters append to
# live spot announcements) that would otherwise defeat the $ anchor above.
_CTRL_RE = _re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffd]")

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

# Cluster spot lines have no distinct mode field — mode (if present at all)
# shows up as a free-text token in the comment (e.g. "CQ TEST CW"). Only an
# explicit keyword is trusted; sub-band conventions vary too much by region
# to guess from frequency alone.
_MODE_TOKENS = {
    "CW": "CW", "SSB": "SSB", "USB": "USB", "LSB": "LSB", "FM": "FM", "AM": "AM",
    "RTTY": "RTTY", "FT8": "FT8", "FT4": "FT4", "PSK31": "PSK31", "PSK": "PSK",
    "JT65": "JT65", "JT9": "JT9", "MSK144": "MSK144", "JS8": "JS8",
    "OLIVIA": "OLIVIA", "DIGI": "DIGI", "DATA": "DIGI",
}

def _guess_mode(comment: str) -> str:
    for token in comment.upper().split():
        tok = token.strip(".,;:-")
        if tok in _MODE_TOKENS:
            return _MODE_TOKENS[tok]
    return ""

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
    # mult_list()/worked_*_mults() are typed per-plugin (e.g. IARU's ITU
    # zones are ints, most others are strings) — normalize to str for
    # membership tests so classification doesn't silently fail on type
    # mismatches.
    ml_set = {str(m) for m in p.mult_list()}

    mult_val = None
    comment_upper = comment.strip().upper()
    for token in comment_upper.split():
        tok = token.strip(".,;:-")
        # Bare numbers ("tnx 4 the Q", signal reports, serial numbers) are
        # far too common in free-text spotter comments to trust as a
        # confirmed exchange value (e.g. IARU's ITU-zone mult list is just
        # "1".."75" — almost any short number would false-positive match).
        if tok.isdigit():
            continue
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
        # Same ambiguity as the direct scan above: mult_of_qso() was fed the
        # *entire* free-text comment as mult1, so a comment that happens to
        # be nothing but a bare number (e.g. a lone signal-report digit)
        # can come back looking like a confirmed exchange value. Distrust it.
        if mult_val is not None and str(mult_val).isdigit():
            mult_val = None

    if mult_val is None or str(mult_val) not in ml_set:
        return "NOT_MULT", "", ""

    region = p.region_of_mult(mult_val) or ""
    worked = {str(m) for m in cl.worked_mults()}
    if str(mult_val) not in worked:
        return "NEW_MULT", mult_val, region

    band_wkd = cl.worked_primary_band_mults()
    on_this_band = any(str(m) == str(mult_val) and b == band for m, b, _mode in band_wkd)
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

    async def _teardown():
        """Stop the current connection and its reader task, and wait for
        the reader to actually finish before returning — not just close()
        + cancel() and move on.

        close() alone from a different thread doesn't reliably unblock a
        concurrent blocking recv() (notably on Windows), so the old
        _read_tcp() task could still be blocked in
        loop.run_in_executor(None, tcp.recv, 1024) for up to its 30s
        socket timeout after we've already moved on to a new connection.
        When it finally does unblock, it sends its own "Disconnected"
        status — which can arrive on the SAME websocket after a newer
        connection's "Connected" status, flipping the UI to the wrong
        state (see issue #26). shutdown(SHUT_RDWR) reliably unblocks that
        recv() promptly cross-platform, and awaiting the (now cancelled)
        task afterward guarantees its cleanup message is fully sent
        before this function returns, so callers can safely proceed to
        open a new connection right after.
        """
        nonlocal tcp, reader_task
        old_tcp, old_task = tcp, reader_task
        tcp = None
        if old_tcp:
            try:
                old_tcp.shutdown(_socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                old_tcp.close()
            except Exception:
                pass
        if old_task:
            old_task.cancel()
            try:
                # Bounded wait even though shutdown() above should unblock
                # the reader almost immediately — never let a pathological
                # platform/socket edge case hang the whole handler.
                await asyncio.wait_for(old_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass
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
                    text = _CTRL_RE.sub("", line.decode("utf-8", errors="replace")).strip()
                    if not text:
                        continue
                    msg = {"type": "raw", "line": text}
                    m   = _SPOT_RE.search(text)
                    if m:
                        freq    = float(m.group(2))
                        dx_call = m.group(3)
                        comment = m.group(4).strip()
                        status, mult_val, region = _classify_spot(dx_call, freq, comment)
                        # Best-effort prefix lookup (same table map_data uses for
                        # worked stations) — lets the World Map plot live spots
                        # alongside worked QSOs. None for anything unresolvable
                        # (odd/nonstandard calls) rather than a wrong guess.
                        latlon = _call_to_latlon(dx_call)
                        msg = {
                            "type":    "spot",
                            "spotter": m.group(1),
                            "freq":    freq,
                            "dx":      dx_call,
                            "comment": comment,
                            "time":    m.group(5),
                            "band":    _freq_to_band_str(freq),
                            "mode":    _guess_mode(comment),
                            "status":  status,
                            "mult":    mult_val,
                            "region":  region,
                            "lat":     latlon[0] if latlon else None,
                            "lon":     latlon[1] if latlon else None,
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
                await _teardown()
                host = cmd.get("host","")
                call = cmd.get("callsign","VK2YI")
                try:
                    # int() moved inside the try: a non-numeric port used to
                    # raise before this block, bypassing the except below
                    # entirely and silently killing the whole session via
                    # the outer catch-all instead of sending a normal
                    # "invalid port" status message (see issue #62).
                    port = int(cmd.get("port", 7300))
                    loop = asyncio.get_event_loop()
                    tcp  = await loop.run_in_executor(
                        None, lambda: _socket.create_connection((host,port), timeout=10))
                    tcp.settimeout(30)
                    reader_task = asyncio.create_task(_read_tcp())
                    await asyncio.sleep(1)
                    # sendall() is blocking (tcp.settimeout(30) covers it too,
                    # same as recv()) — off-loaded so a congested/hung peer
                    # can't stall the single event loop for up to 30s and
                    # freeze every other window/request in the app.
                    await loop.run_in_executor(None, tcp.sendall, (call+"\n").encode())
                    await asyncio.sleep(1)
                    await loop.run_in_executor(None, tcp.sendall, b"SET/DX\n")
                    await ws.send_text(json.dumps({
                        "type":"status","connected":True,
                        "msg":f"Connected to {host}:{port}"}))
                except Exception as e:
                    await ws.send_text(json.dumps({
                        "type":"status","connected":False,"msg":str(e)}))

            elif cmd.get("cmd") == "send" and tcp:
                try:
                    await asyncio.get_event_loop().run_in_executor(
                        None, tcp.sendall, (cmd.get("text","")+"\n").encode())
                except Exception:
                    pass

            elif cmd.get("cmd") == "disconnect":
                await _teardown()
                break

    except (WebSocketDisconnect, Exception):
        pass
    finally:
        await _teardown()


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


# DXCC/country name per prefix — same key set as _PFX above, since a "Top
# Countries Worked" list needs a human-readable name rather than a
# coordinate. Deliberately independent of any plugin's own mult1 (which
# means a country prefix for CQWW-style contests, but a US state, VK shire,
# CQ zone, etc. for others) — resolving straight from the callsign means
# this works the same way for every contest, not just DXCC-mult ones.
_PFX_COUNTRY = {
    "KH6": "Hawaii", "KH8": "American Samoa", "KP4": "Puerto Rico",
    "FK8": "New Caledonia", "FK7": "New Caledonia", "FO8": "French Polynesia",
    "KH0": "Mariana Islands", "KH2": "Guam", "KL7": "Alaska",
    "P29": "Papua New Guinea", "ZK2": "Niue", "3D2": "Fiji", "5W1": "Samoa",
    "T30": "Kiribati", "V63": "Micronesia", "V73": "Marshall Islands",
    "YJ8": "Vanuatu", "E51": "Cook Islands", "E52": "Cook Islands",
    "ZL8": "Kermadec Islands", "ZL9": "New Zealand Subantarctic Islands",
    "FK": "New Caledonia", "FG": "Guadeloupe", "FH": "Mayotte",
    "FM": "Martinique", "FO": "French Polynesia", "FP": "St. Pierre & Miquelon",
    "FR": "Reunion Island", "FW": "Wallis & Futuna", "FY": "French Guiana",
    "ZL": "New Zealand", "ZS": "South Africa", "ZP": "Paraguay",
    "ZA": "Albania", "ZB": "Gibraltar", "ZF": "Cayman Islands",
    "ZK": "New Zealand", "ZD": "St. Helena",
    "VE": "Canada", "VK": "Australia", "VO": "Canada", "VR": "Hong Kong",
    "VU": "India", "V3": "Belize", "V5": "Namibia", "V6": "Micronesia",
    "V7": "Marshall Islands", "V8": "Brunei",
    "G": "England", "GM": "Scotland", "GW": "Wales", "GD": "Isle of Man",
    "GJ": "Jersey", "GU": "Guernsey",
    "DL": "Germany", "DJ": "Germany", "DK": "Germany", "DA": "Germany",
    "DB": "Germany", "DC": "Germany", "DF": "Germany", "DG": "Germany",
    "DH": "Germany",
    "JA": "Japan", "JE": "Japan", "JH": "Japan", "JR": "Japan",
    "JD": "Ogasawara",
    "BY": "China", "BG": "China", "BH": "China", "BV": "Taiwan", "BU": "Taiwan",
    "UA": "Russia", "RA": "Russia", "RK": "Russia", "RL": "Russia",
    "RM": "Russia", "RN": "Russia", "RO": "Russia", "RQ": "Russia",
    "RT": "Russia", "RU": "Russia", "RV": "Russia", "RW": "Russia",
    "RX": "Russia", "RY": "Russia", "RZ": "Russia", "UA9": "Russia",
    "UI": "Russia", "UK": "Uzbekistan", "UN": "Kazakhstan", "UR": "Ukraine",
    "OH": "Finland", "OG": "Finland", "OZ": "Denmark", "OX": "Greenland",
    "OY": "Faroe Islands", "OE": "Austria", "OK": "Czech Republic",
    "OL": "Czech Republic", "OM": "Slovakia",
    "ON": "Belgium", "OO": "Belgium", "OP": "Belgium", "OQ": "Belgium",
    "OR": "Belgium", "OS": "Belgium", "OT": "Belgium",
    "SM": "Sweden", "SK": "Sweden", "SP": "Poland", "SN": "Poland",
    "SQ": "Poland", "SV": "Greece", "SW": "Greece",
    "PA": "Netherlands", "PB": "Netherlands", "PD": "Netherlands",
    "PE": "Netherlands", "PH": "Netherlands",
    "PY": "Brazil", "PP": "Brazil", "PQ": "Brazil", "PR": "Brazil",
    "PS": "Brazil", "PU": "Brazil", "PW": "Brazil", "PX": "Brazil",
    "EA": "Spain", "EB": "Spain", "EC": "Spain", "EI": "Ireland",
    "EJ": "Ireland", "EK": "Armenia", "EP": "Iran", "ER": "Moldova",
    "ES": "Estonia", "EU": "Belarus", "EW": "Belarus", "EX": "Kyrgyzstan",
    "EY": "Tajikistan", "EZ": "Turkmenistan",
    "HA": "Hungary", "HB": "Switzerland", "HC": "Ecuador", "HH": "Haiti",
    "HI": "Dominican Republic", "HK": "Colombia", "HL": "South Korea",
    "DS": "South Korea", "HP": "Panama", "HR": "Honduras", "HS": "Thailand",
    "HV": "Vatican", "HZ": "Saudi Arabia",
    "LA": "Norway", "LB": "Norway", "LC": "Norway",
    "LU": "Argentina", "LV": "Argentina", "LW": "Argentina",
    "LX": "Luxembourg", "LY": "Lithuania", "LZ": "Bulgaria",
    "I": "Italy", "IS": "Sardinia", "IG": "Italy",
    "YA": "Afghanistan", "YB": "Indonesia", "YC": "Indonesia", "YI": "Iraq",
    "YJ": "Vanuatu", "YK": "Syria", "YL": "Latvia", "YN": "Nicaragua",
    "YO": "Romania", "YT": "Serbia", "YU": "Serbia", "YV": "Venezuela",
    "TA": "Turkey", "TF": "Iceland", "TI": "Costa Rica", "TK": "Corsica",
    "TL": "Central African Republic", "TN": "Congo", "TR": "Gabon",
    "TT": "Chad", "TU": "Ivory Coast", "TY": "Benin", "TZ": "Mali",
    "XE": "Mexico", "XW": "Laos", "XV": "Vietnam", "XU": "Cambodia",
    "XT": "Burkina Faso",
    "4X": "Israel", "4Z": "Israel",
    "5A": "Libya", "5B": "Cyprus", "5H": "Tanzania", "5N": "Nigeria",
    "5R": "Madagascar", "5T": "Mauritania", "5U": "Niger", "5V": "Togo",
    "5W": "Samoa", "5X": "Uganda", "5Z": "Kenya",
    "6W": "Senegal", "6Y": "Jamaica",
    "7P": "Lesotho", "7Q": "Malawi", "7X": "Algeria",
    "8P": "Barbados", "8Q": "Maldives", "8R": "Guyana",
    "9A": "Croatia", "9G": "Ghana", "9H": "Malta", "9J": "Zambia",
    "9K": "Kuwait", "9L": "Sierra Leone", "9M": "Malaysia", "9N": "Nepal",
    "9Q": "DR Congo", "9V": "Singapore", "9W": "Malaysia", "9X": "Rwanda",
    "9Y": "Trinidad & Tobago",
    "A2": "Botswana", "A3": "Tonga", "A4": "Oman", "A5": "Bhutan",
    "A6": "United Arab Emirates", "A7": "Qatar", "A9": "Bahrain",
    "CE": "Chile", "CO": "Cuba", "CT": "Portugal", "CU": "Azores",
    "CX": "Uruguay",
    "D2": "Angola", "D4": "Cape Verde", "D6": "Comoros",
    "E7": "Bosnia-Herzegovina",
    "OA": "Peru", "OB": "Peru",
    "P2": "Papua New Guinea", "P4": "Aruba",
    "T7": "San Marino", "JT": "Mongolia",
    "F": "France", "W": "United States", "K": "United States",
    "N": "United States", "R": "Russia",
}


def _call_to_country(callsign: str):
    """Best-effort callsign to DXCC/country name — mirrors _call_to_latlon's
    longest-prefix-first matching (same tables), just resolving a name
    instead of coordinates. See its own module-level docstring/comment for
    why this exists independently of any plugin's mult1."""
    call = callsign.upper().strip()

    if call[:1] in ("W", "K", "N") and len(call) > 1 and call[1] in _US_CALL_AREA:
        return "United States"
    if (len(call) > 2 and call[0] == "P" and call[1] in _BR_LETTERS
            and call[2] in _BR_CALL_AREA):
        return "Brazil"
    if call[:2] in ("XE", "XF") and len(call) > 2 and call[2] in _MX_CALL_AREA:
        return "Mexico"
    if call[:2] in _AU_PREFIXES and len(call) > 2 and call[2] in _AU_CALL_AREA:
        return "Australia"

    for n in [4, 3, 2, 1]:
        if n <= len(call) and call[:n] in _PFX_COUNTRY:
            return _PFX_COUNTRY[call[:n]]
    if call[:2] in _AU_PREFIXES:
        return "Australia"
    return None


@app.get("/api/top_countries")
async def api_top_countries():
    """Top worked DXCC/countries by QSO count — resolved straight from each
    QSO's callsign (see _call_to_country), not from mult1, so this works
    the same way regardless of what the loaded contest's own multiplier is."""
    with STATE._lock:
        if not STATE.contest_log:
            return []
        qsos = list(STATE.contest_log.qsos)
    counts: dict = {}
    for q in qsos:
        if q.get("dupe"):
            continue
        call = q.get("call", "")
        if not call:
            continue
        country = _call_to_country(call)
        if not country:
            continue
        counts[country] = counts.get(country, 0) + 1
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:18]
    return [{"country": c, "qsos": n} for c, n in top]


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
                         "mult": q.get("mult1", ""),
                         "country": _call_to_country(call) or ""}
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
    """Sends are awaited one at a time, each under its own short timeout —
    without that timeout, a single client whose socket isn't draining fast
    enough (a minimized/OS-throttled HUD popout, a half-dead connection
    that hasn't errored out yet) stalls this whole loop, delaying every
    *other* client's update — including the main window's live radio
    readout — until it clears. Same category of bug as the DX Cluster's
    own socket blocking the app for up to 30s on a slow/hung peer (#41);
    this is the general /ws/live broadcast path that fix didn't cover."""
    msg  = json.dumps({"type": "snapshot", "data": data})
    dead = []
    for ws in list(STATE._clients):
        try:
            await asyncio.wait_for(ws.send_text(msg), timeout=2.0)
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
        if STATE._shutting_down:
            return
        try:
            changed = await asyncio.get_event_loop().run_in_executor(
                None, STATE.poll_once
            )
        except RuntimeError:
            # The flag check above closes the common case, but shutdown's
            # executor teardown (see _start_shutdown()) can still race it by
            # a hair — ThreadPoolExecutor.submit() raises exactly this when
            # called after the executor's own shutdown() — so this is the
            # same "stop cleanly" outcome as the flag check catching it.
            return
        if changed:
            await _broadcast(STATE.snapshot())


# ═══════════════════════════════════════════════════════════════════════════════
# ── Spectator Mode ────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════
# A second, minimal FastAPI app — not a flag/middleware bolted onto `app` —
# because `app` has zero auth/access-control anywhere (no CORS/token/IP
# checks; its whole security model is "loopback bind = trusted") and carries
# every mutating route (/api/qsos/delete, /api/load, /api/settings/*, ...).
# spectator_app's route table only ever contains the three routes registered
# below, so there is nothing for a future middleware bug or forgotten
# allowlist entry to accidentally expose to the LAN — safety is structural.

def _get_lan_ip() -> Optional[str]:
    """Best-effort discovery of this machine's LAN-facing IPv4 address.
    Connecting a UDP socket sends no packets (UDP is connectionless) — it
    only forces the OS routing table to pick a source interface/IP, which is
    exactly the adapter this machine would use to reach another device on
    the LAN. Works even with no real internet uplink (common at a
    contest site on an isolated LAN), since 8.8.8.8 never actually needs to
    respond. Returns None if there's no route at all (Wi-Fi/Ethernet off)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


spectator_app = FastAPI(title="VK Contest Analyzer — Spectator")
spectator_app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")
spectator_app.middleware("http")(_no_cache_headers)


@spectator_app.get("/spectator")
async def spectator_page():
    return FileResponse(str(_STATIC / "index.html"))


# Same handler object the main app uses for /ws/live — same STATE._clients
# list, same _broadcast() fan-out. A spectator connection is indistinguishable
# from a HUD popout's connection from the server's point of view; any future
# fix to ws_live (timeouts, ping cadence, etc.) applies to both automatically.
spectator_app.add_api_websocket_route("/ws/live", ws_live)


async def _start_spectator_server() -> dict:
    if STATE._spectator_server is not None:
        return {"ok": True, "enabled": True, "url": STATE._spectator_url}
    lan_ip = _get_lan_ip()
    if not lan_ip:
        return {"error": "Could not detect a Wi-Fi/LAN address on this machine."}
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", 0))   # OS-assigned ephemeral port — a fresh URL
                                     # each toggle-on is fine, it's always read
                                     # live from the titlebar popover, never
                                     # bookmarked or persisted (see no-persist
                                     # decision below)
        sock.listen(128)
    except OSError as exc:
        sock.close()
        return {"error": f"Could not open a port for Spectator Mode: {exc}"}
    port = sock.getsockname()[1]
    config = uvicorn.Config(
        spectator_app, host="0.0.0.0", port=port,
        log_level="warning", loop="asyncio", log_config=None,
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve(sockets=[sock]))
    STATE._spectator_server = server
    STATE._spectator_task = task
    STATE._spectator_sock = sock
    STATE._spectator_url = f"http://{lan_ip}:{port}/spectator"
    return {"ok": True, "enabled": True, "url": STATE._spectator_url}


async def _stop_spectator_server() -> dict:
    server, task = STATE._spectator_server, STATE._spectator_task
    if server is None:
        return {"ok": True, "enabled": False}
    STATE._spectator_server = None
    STATE._spectator_task = None
    STATE._spectator_sock = None
    STATE._spectator_url = None
    server.should_exit = True
    if task:
        try:
            await asyncio.wait_for(task, timeout=3.0)
        except asyncio.TimeoutError:
            server.force_exit = True
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except asyncio.TimeoutError:
                pass
    return {"ok": True, "enabled": False}


@app.get("/api/spectator")
async def api_spectator_status():
    """Loopback-only status/control endpoint — deliberately absent from
    spectator_app, so a LAN visitor can't discover or toggle this themselves."""
    return {"enabled": STATE._spectator_server is not None, "url": STATE._spectator_url}


@app.post("/api/spectator")
async def api_spectator_toggle(body: dict):
    if body.get("enabled"):
        result = await _start_spectator_server()
    else:
        result = await _stop_spectator_server()
    if "error" in result:
        return JSONResponse(result, status_code=400)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# ── PyWebView launcher ────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

_PREFERRED_PORT = 58631   # arbitrary, in the dynamic/private range (49152-65535)

def _bind_server_socket(port: Optional[int] = None) -> tuple[socket.socket, int]:
    """Bind and start listening on the preferred fixed port so the pywebview
    window's origin — and therefore every localStorage-backed preference
    (theme, zoom, tile layout, the Pace tab's target score, etc.) — stays
    the same across app restarts; a different port each launch means a
    different origin, which WebView2 treats as a brand-new site with empty
    storage even with private_mode=False and a persistent storage_path (see
    launch_webview()). Falls back to a random free port only if the
    preferred one is actually taken (e.g. a second instance already
    running), rather than failing outright.

    SO_REUSEADDR matters here: this app hard-exits via os._exit() on close
    (see _start_shutdown()), skipping the graceful connection teardown that
    would normally let the OS release the port immediately. That leaves the
    previous session's connections lingering in TIME_WAIT, which blocks a
    plain bind() on the same port for up to a minute — exactly the
    close-then-relaunch window a user is likely to hit. Without this, a
    quick restart silently lands on a random fallback port instead, which
    is a different origin to the embedded browser and starts with empty
    localStorage — i.e. it looks like the theme/zoom/tile-layout prefs this
    fixed port exists to preserve just got wiped.

    Returns the actual bound-and-listening socket together with its port.
    Callers must hand this same socket straight to uvicorn's
    ``Server.serve(sockets=[...])`` rather than letting uvicorn bind its
    own — closing this probe socket and having uvicorn bind a fresh one a
    moment later would leave a small window where another process could
    steal the port in between (see issue #23). Holding the one socket from
    bind through serve closes that window entirely.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", port or _PREFERRED_PORT))
    except OSError:
        if port:
            # Caller asked for a specific port — don't silently substitute
            # a different one out from under them.
            raise
        s.close()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
    s.listen(128)
    return s, s.getsockname()[1]


# ── Native desktop toast notifications (Windows) ────────────────────────────
# WebView2's own Notification API (the standard web approach) is auto-denied
# in this frameless embedded window — confirmed by direct testing:
# Notification.requestPermission() resolves straight to "denied" with no
# prompt ever shown, since there's no browser chrome for WebView2 to render
# one against. This bypasses the browser API entirely and shows a real
# Windows tray balloon notification via the same Shell_NotifyIcon technique
# libraries like win10toast use internally — no new dependency needed,
# since pywin32 is already pulled in by pywebview's own Windows backend.
_TOAST_CLASS_NAME = "VKCA_ToastNotifier"
_toast_wndclass_atom = None
_toast_class_lock = threading.Lock()


def _show_toast_notification(title: str, message: str, duration_secs: float = 5.0) -> None:
    """Fire-and-forget a native Windows balloon notification. Runs its own
    tiny message loop on a dedicated background thread (PumpMessages()
    blocks until WM_QUIT, which the cleanup timer posts once the balloon's
    had time to show) so this never blocks the request handling it's
    called from."""
    if sys.platform != "win32":
        return

    def _worker():
        try:
            import win32api
            import win32con
            import win32gui

            global _toast_wndclass_atom
            hinst = win32api.GetModuleHandle(None)

            # Cleanup must run as a message handled by this window's own
            # thread — DestroyWindow() cannot be called cross-thread (Win32
            # forbids destroying a window from a thread that didn't create
            # it; it fails silently rather than raising), so the Timer below
            # posts WM_APP_CLEANUP instead of touching the window directly.
            WM_APP_CLEANUP = win32con.WM_APP + 1

            def _on_cleanup(hwnd, msg, wparam, lparam):
                try:
                    win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (hwnd, 0))
                except Exception:
                    pass
                win32gui.DestroyWindow(hwnd)
                return 0

            with _toast_class_lock:
                if _toast_wndclass_atom is None:
                    wc = win32gui.WNDCLASS()
                    wc.hInstance = hinst
                    wc.lpszClassName = _TOAST_CLASS_NAME
                    wc.lpfnWndProc = {
                        win32con.WM_DESTROY: lambda hwnd, msg, wparam, lparam: (
                            win32gui.PostQuitMessage(0), 0)[1],
                        WM_APP_CLEANUP: _on_cleanup,
                    }
                    _toast_wndclass_atom = win32gui.RegisterClass(wc)

            hwnd = win32gui.CreateWindow(
                _toast_wndclass_atom, "VKCA notify",
                win32con.WS_OVERLAPPED, 0, 0, 0, 0, 0, 0, hinst, None,
            )
            win32gui.UpdateWindow(hwnd)

            WM_TRAYICON = win32con.WM_USER + 20
            hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)

            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, (
                hwnd, 0,
                win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
                WM_TRAYICON, hicon, "VK Contest Analyzer",
            ))
            win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY, (
                hwnd, 0, win32gui.NIF_INFO, WM_TRAYICON, hicon,
                "VK Contest Analyzer", message, 200, title,
            ))

            def _request_cleanup():
                try:
                    win32gui.PostMessage(hwnd, WM_APP_CLEANUP, 0, 0)
                except Exception:
                    pass

            timer = threading.Timer(duration_secs, _request_cleanup)
            timer.daemon = True
            timer.start()

            win32gui.PumpMessages()
        except Exception:
            log.exception("Native toast notification failed")

    threading.Thread(target=_worker, daemon=True, name="toast-notify").start()


@app.post("/api/notify")
async def api_notify(body: dict):
    """Show a native desktop notification. Called from the Overview/HUD's
    own celebration logic (new personal best, score milestone) for the
    case neither window is actually on screen — see notifyOS() in
    overview.js. title/message are short, plugin-generated strings (a
    milestone number, a rate) — never raw log/network-derived free text,
    so there's no injection surface here to worry about."""
    # NOTIFYICONDATA caps szInfoTitle at 63 chars and szInfo at 255 (both
    # WCHAR[N] with a null terminator) — truncate to those limits ourselves
    # rather than let the OS reject or mangle an oversized string.
    title = str(body.get("title") or "VK Contest Analyzer")[:63]
    message = str(body.get("message") or "")[:255]
    if not message:
        return {"ok": False}
    _show_toast_notification(title, message)
    return {"ok": True}


_SINGLE_INSTANCE_MUTEX_NAME = r"Global\VKContestAnalyzer_SingleInstance_Mutex"
_single_instance_mutex_handle = None   # keeps the mutex alive for the process lifetime


def _is_first_instance() -> bool:
    """True if this is the only running copy of the app; False if another
    instance already holds the single-instance mutex.

    This does NOT use _bind_server_socket()/the preferred TCP port as the
    detection signal, even though "port already taken" looks like an
    obvious proxy for "another instance is running" — SO_REUSEADDR (needed
    there for the close-then-quick-relaunch TIME_WAIT case) has a
    Windows-specific quirk, confirmed by direct testing: a SECOND socket
    with SO_REUSEADDR set can successfully bind() AND listen() on a port
    another process is already actively listening on, with no error at
    all. Relying on that as a "someone else is already here" signal would
    silently miss the case entirely (and worse — two listeners on the same
    port on Windows can starve one of them of incoming connections, which
    is a bigger problem than the settings.json race this was meant to
    prevent). A named mutex has no such loophole: CreateMutexW's
    ERROR_ALREADY_EXISTS is unambiguous.
    """
    global _single_instance_mutex_handle
    if sys.platform != "win32":
        return True   # no equivalent no-extra-dependency check on other platforms
    try:
        import ctypes
        ERROR_ALREADY_EXISTS = 183
        handle = ctypes.windll.kernel32.CreateMutexW(
            None, False, _SINGLE_INSTANCE_MUTEX_NAME)
        already_running = ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS
        _single_instance_mutex_handle = handle   # keep alive; process exit releases it
        return not already_running
    except Exception:
        log.exception("Single-instance mutex check failed — proceeding as first instance")
        return True


def _confirm_second_instance() -> bool:
    """Another instance is already running (see _is_first_instance(), the
    only caller — which only returns False on win32, so this is only ever
    reached there). Previously this was silent: a second instance would
    just launch anyway, leaving two independent server+window stacks that
    both read/write the same settings.json with no locking — whichever
    closes last silently clobbers the other's saved preferences (see issue
    #21). Ask before doing that instead of doing it silently.

    Returns True if the caller should proceed launching a second instance
    anyway, False if it should exit without launching anything.
    """
    message = (
        "VK Contest Analyzer appears to already be running.\n\n"
        "Launching a second copy will use a fresh window that doesn't "
        "share settings (theme, layout, etc.) with the first, and the two "
        "copies may overwrite each other's saved preferences on close.\n\n"
        "Launch another copy anyway?"
    )
    try:
        import ctypes
        MB_YESNO = 0x04
        MB_ICONWARNING = 0x30
        MB_TOPMOST = 0x40000
        IDYES = 6
        result = ctypes.windll.user32.MessageBoxW(
            None, message, "VK Contest Analyzer — Already Running",
            MB_YESNO | MB_ICONWARNING | MB_TOPMOST,
        )
        return result == IDYES
    except Exception:
        log.exception("Could not show already-running dialog — proceeding anyway")
        return True


def launch_webview(db_path: Optional[str] = None, port: Optional[int] = None):
    if not _is_first_instance() and not _confirm_second_instance():
        return
    sock, port = _bind_server_socket(port)
    url = f"http://127.0.0.1:{port}"
    STATE._base_url = url

    # Pre-load if a valid file was passed on the command line
    if db_path and os.path.isfile(db_path):
        STATE.load_db(db_path)
        _sync_rigctld()

    config = uvicorn.Config(
        app, host="127.0.0.1", port=port,
        log_level="warning", loop="asyncio",
        log_config=None,   # use our own logging setup, not uvicorn's default
                            # (its formatter calls sys.stdout.isatty(), which
                            # is None in a windowed/console=False build)
    )
    server = uvicorn.Server(config)

    def _run_server():
        # Passing our already-bound socket (see _bind_server_socket) instead
        # of letting uvicorn bind its own host/port — avoids the TOCTOU
        # close-then-rebind gap issue #23 flagged.
        asyncio.run(server.serve(sockets=[sock]))

    server_thread = threading.Thread(target=_run_server, daemon=True, name="uvicorn")
    server_thread.start()

    # Wait until the server is accepting connections (max 10 seconds).
    # server_ready tracks whether the loop actually succeeded — previously
    # discarded, so a server that was still starting up (AV scanning the
    # freshly-extracted bundle, cold disk cache, etc.) on a slow machine
    # would silently fall through into opening the window anyway, showing a
    # blank/connection-refused page with nothing in the log distinguishing
    # it from the genuinely different "WebView2 Runtime missing" failure
    # mode below (see issue #22).
    server_ready = False
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                server_ready = True
                break
        except OSError:
            time.sleep(0.1)

    if not server_ready:
        log.warning(
            "Local server on port %d did not start accepting connections "
            "within 10s — opening the window anyway, but it may show a "
            "blank or connection-refused page if the server is still "
            "starting. Check the log above this line for the uvicorn "
            "startup sequence.", port,
        )

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
                def _mutate(settings):
                    if _maximized and _pre_max_geom:
                        x, y, w, h = _pre_max_geom
                        settings["window_geometry"] = {"x": x, "y": y, "width": w, "height": h, "maximized": True}
                    else:
                        settings["window_geometry"] = {
                            "x": window.x, "y": window.y,
                            "width": window.width, "height": window.height,
                            "maximized": False,
                        }
                _settings_read_modify_write(_mutate)
            except Exception:
                log.exception("Failed to save window geometry")

        def _start_shutdown():
            """Closes WebSocket clients, stops uvicorn, hard-exits. Runs in a
            background thread since this is called directly from the GUI
            thread (either as window.events.closed or from _WindowApi.close())
            and the actual work below — notably server_thread.join() — must
            never block that thread's event loop."""
            log.info("Window closed — shutting down")
            # Set first, before anything else — _poll_loop() checks this after
            # waking from its sleep and stops rather than calling
            # run_in_executor() against a thread pool that server_thread.join()
            # below may have already torn down (observed as a stray
            # "RuntimeError: cannot schedule new futures after shutdown"
            # during the up-to-2s graceful-uvicorn-stop window before the
            # final os._exit()).
            STATE._shutting_down = True

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

                # Signal uvicorn to stop (both the main server and, if it's
                # running, the LAN-facing Spectator Mode listener)
                server.should_exit = True
                if STATE._spectator_server:
                    STATE._spectator_server.should_exit = True

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

        def _reset_gravity():
            """resize_to() (edge/corner drag resizing, below) sets the GTK
            window's gravity to whichever corner is opposite the dragged
            edge (e.g. SOUTH_EAST for a north-west corner drag) so that
            corner stays fixed while resizing — and it persists on the
            window afterward; nothing resets it back automatically.
            move()'s (x, y) target is interpreted relative to whatever
            corner the CURRENT gravity designates, so calling it while a
            stale non-default gravity is still set silently repositions
            the wrong corner to (x, y) instead of the top-left — often
            landing far off-screen, clamped to (0, 0) by the WM.

            Resetting gravity via a plain resize() call (as an earlier
            version of this code did) isn't safe here: resizing to the
            maximize/restore target BEFORE moving there means the window
            transiently has the NEW (near-full-monitor or windowed) size
            while still sitting at its OLD position, which can itself
            overlap a monitor edge and retrigger the WM's edge-tiling/
            snap-assist (see toggle_maximize() below) before the
            subsequent move() ever runs. Resetting gravity directly, with
            no size/position side effect, avoids that risk — the actual
            move()-then-resize() order below is otherwise unchanged."""
            if sys.platform.startswith("linux") and getattr(window, "native", None) is not None:
                try:
                    from gi.repository import Gdk
                    window.native.set_gravity(Gdk.Gravity.NORTH_WEST)
                    log.info("_reset_gravity: set_gravity(NORTH_WEST) succeeded")
                except Exception:
                    log.exception("_reset_gravity: set_gravity() failed")

        def _move_resize_window(x, y, w, h):
            """vkca_errors.log from a real repro showed why doing this as two
            sequential calls (either order) can't work: moving to the
            *target* (x, y) BEFORE resizing means the window is still its
            OLD, much larger size at that moment — e.g. moving a still-
            fullscreen-sized window to a small windowed position would hang
            most of it off the right/bottom edge of the monitor, and Muffin
            was observed silently refusing that move outright, leaving the
            window sitting at its old (on-screen) position instead. The
            other order (resize before move) has the opposite problem: the
            window transiently has the NEW size at its OLD position, which
            can overlap a monitor edge and retrigger Muffin's edge-tiling/
            snap-assist (see toggle_maximize() below) before the move ever
            runs. Gdk.Window.move_resize() sets both in a single request —
            the WM never sees an intermediate wrong-size/wrong-position
            state at all, avoiding both failure modes. Falls back to the
            separate move()+resize() calls if unavailable/non-Linux."""
            if sys.platform.startswith("linux") and getattr(window, "native", None) is not None:
                try:
                    gdk_win = window.native.get_window()
                    if gdk_win is not None:
                        gdk_win.move_resize(int(x), int(y), int(w), int(h))
                        return
                except Exception:
                    log.exception("_move_resize_window: Gdk move_resize failed, falling back")
            _move_window(x, y)
            window.resize(w, h)

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
                    _reset_gravity()
                    _move_resize_window(x, y, w, h)
                    log.info("toggle_maximize: after move_resize — actual=%s", (window.x, window.y, window.width, window.height))
                elif _pre_max_geom:
                    x, y, w, h = _pre_max_geom
                    log.info("toggle_maximize: restoring — target=%s", (x, y, w, h))
                    _reset_gravity()
                    _move_resize_window(x, y, w, h)
                    log.info("toggle_maximize: after move_resize — actual=%s", (window.x, window.y, window.width, window.height))
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
                #
                # hide() first, before anything else: measured directly (an
                # /api/debug_close route calling _start_shutdown() with the
                # graceful-wait entirely removed, os._exit(0) fired
                # immediately) still took ~2.2s for the process to actually
                # disappear from Task Manager — so the lag isn't in our own
                # websocket/uvicorn teardown at all, it's WebView2's own
                # process-tree teardown on Windows, outside what server.py
                # can bound. Hiding the window immediately makes the CLOSE
                # feel instant regardless — the ~2s of backend teardown
                # then happens invisibly while the window is already gone.
                window.hide()
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
        # private_mode defaults to True in pywebview — per its own docstring,
        # "cookies and local storage are not preserved" — which silently
        # wiped every localStorage-based preference (theme, tile layout,
        # zoom, Pace tab's target score, etc.) on each app restart. storage_path
        # points the persistent profile at the same per-user app-data folder
        # already used for settings.json/logs (see _app_data_dir()), rather
        # than pywebview's default location.
        webview.start(_on_loaded, debug=False, private_mode=False,
                       storage_path=str(_app_data_dir() / "webview_storage"))

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
