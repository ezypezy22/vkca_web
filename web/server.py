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
import os
import sys
import threading
import time
import socket
from contextlib import asynccontextmanager
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

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

# Direct import — no tkinter mocking needed
from contest_log import ContestLog
from plugins.loader import plugin_for

log = logging.getLogger(__name__)

def _setup_logging():
    """Write logs to a file next to the exe (or script) — visible when frozen."""
    if getattr(sys, 'frozen', False):
        log_dir = Path(sys.executable).parent
    else:
        log_dir = Path(__file__).resolve().parent
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

    # ── Path validation (no DB open) ─────────────────────────────────────────

    @staticmethod
    def validate_path(path: str) -> Optional[str]:
        """Return an error string, or None if the path looks valid."""
        p = Path(path)
        if not p.exists():
            return f"File not found: {path}"
        if p.is_dir():
            return (f"That is a folder, not a file. "
                    f"Please select a .s3db file inside: {path}")
        if p.suffix.lower() != ".s3db":
            return f"Expected a .s3db file, got: {p.name}"
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

    def poll_once(self) -> bool:
        """Check mtime; reload ContestLog if changed. Returns True if updated."""
        if not self.db_path or not os.path.isfile(self.db_path):
            return False
        try:
            mtime = os.path.getmtime(self.db_path)
        except OSError:
            return False
        if mtime <= self.last_mtime:
            return False
        try:
            cl = ContestLog(self.db_path,
                            contest_nr=self.contest_nr,
                            plugin=self.plugin)
            with self._lock:
                self.contest_log   = cl
                self.last_mtime    = mtime
                self.last_snapshot = self._safe_snapshot()
            return True
        except Exception:
            log.exception("poll_once reload failed")
            return False

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self.last_snapshot)


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


@asynccontextmanager
async def lifespan(application: FastAPI):
    asyncio.create_task(_poll_loop())
    yield


app = FastAPI(title="VK Contest Analyzer Web", lifespan=lifespan)

_STATIC = _HERE / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.get("/")
async def index():
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
            file_types=("N1MM Log Files (*.s3db)", "All files (*.*)")
        )
        if not result:
            return {"path": None}
        chosen = str(result[0])
        # Guard: pywebview may return a directory if the user didn't select a file
        if os.path.isdir(chosen):
            return JSONResponse(
                {"error": f"Selected a folder, not a .s3db file: {chosen}"},
                status_code=400)
        return {"path": chosen}
    except Exception as exc:
        log.exception("browse failed")
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
    return STATE.snapshot()


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


@app.get("/api/bands")
async def api_bands():
    return STATE.snapshot().get("band_efficiency", [])


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


@app.get("/api/yoy")
async def api_yoy():
    """
    Year-on-Year comparison: load every past instance of the same contest
    from the same .s3db and return their final scores + QSO/mult totals.
    """
    if not STATE.db_path or not STATE.contest_log:
        return []
    try:
        current_name = getattr(STATE.contest_log, '_contest_name', None)
        if not current_name:
            # Derive from available_contests
            all_ct = ContestLog.available_contests(STATE.db_path)
            this   = next((c for c in all_ct
                           if c['ContestNR'] == STATE.contest_nr), None)
            if not this:
                return []
            current_name = this['ContestName']

        all_ct = ContestLog.available_contests(STATE.db_path)
        same   = [c for c in all_ct if c['ContestName'] == current_name]

        results = []
        for ct in same:
            try:
                cl   = ContestLog(STATE.db_path,
                                  contest_nr=ct['ContestNR'],
                                  plugin=plugin_for(current_name))
                snap = cl.compute_snapshot()
                results.append({
                    "contest_nr":  ct['ContestNR'],
                    "start_date":  str(ct.get('StartDate',''))[:10],
                    "year":        str(ct.get('StartDate',''))[:4],
                    "qsos":        snap.get('valid', 0),
                    "mults":       snap.get('worked', 0),
                    "score":       snap.get('score', 0),
                    "band_mults":  snap.get('band_mults', 0),
                    "is_current":  ct['ContestNR'] == STATE.contest_nr,
                })
            except Exception:
                log.exception("YOY: failed loading ContestNR %s", ct['ContestNR'])
        results.sort(key=lambda r: r['start_date'])
        return results
    except Exception:
        log.exception("api_yoy failed")
        return []


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
        "gauge_defs":       gauge_list,
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
                        freq = float(m.group(2))
                        msg = {
                            "type":    "spot",
                            "spotter": m.group(1),
                            "freq":    freq,
                            "dx":      m.group(3),
                            "comment": m.group(4).strip(),
                            "time":    m.group(5),
                            "band":    _freq_to_band_str(freq),
                        }
                    await ws.send_text(json.dumps(msg))
            except Exception:
                break
        try:
            await ws.send_text(json.dumps({"type":"status","connected":False,"msg":"Disconnected"}))
        except Exception:
            pass

    def _freq_to_band_str(f):
        if f > 1800:   return "160M"
        if f > 3500:   return "80M"
        if f > 7000:   return "40M"
        if f > 10100:  return "30M"
        if f > 14000:  return "20M"
        if f > 18068:  return "17M"
        if f > 21000:  return "15M"
        if f > 24890:  return "12M"
        if f > 28000:  return "10M"
        if f > 50000:  return "6M"
        return "?"

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


@app.get("/api/snapshot_png")
async def api_snapshot_png():
    """Server-side PNG of current gauges using matplotlib Agg backend."""
    import io, math as _math
    snap = STATE.snapshot()
    if not snap:
        return JSONResponse({"error": "No data loaded"}, status_code=400)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.figure as _mplf
        import matplotlib.patches as _mplp
        import matplotlib.patheffects as _mplpe

        with STATE._lock:
            plugin = STATE.contest_log.plugin if STATE.contest_log else None
        total_mults = snap.get("band_mults", snap.get("worked", 0))
        try:
            gdefs = plugin.gauge_defs(snap, total_mults) if plugin else []
        except Exception:
            gdefs = []

        n  = max(len(gdefs), 1)
        BG = "#0d1117"; BG2 = "#161b22"; BG3 = "#21262d"
        MUTED = "#8b949e"; FG = "#e6edf3"

        fig = _mplf.Figure(figsize=(n*2.4+0.4, 3.6), facecolor=BG, dpi=120)
        fig.patch.set_facecolor(BG)

        for i, g in enumerate(gdefs):
            ax = fig.add_subplot(1, n, i+1, aspect="equal")
            ax.set_facecolor(BG2); ax.axis("off")
            ax.set_xlim(-1.3, 1.3); ax.set_ylim(-0.9, 1.3)
            for sp in ax.spines.values(): sp.set_visible(False)

            val    = snap.get(g.value_key, 0) or 0
            maxVal = (snap.get(g.max_key, 1) if isinstance(g.max_key, str) else g.max_key) or 1
            frac   = min(max(float(val)/float(maxVal), 0), 1)
            col    = g.colour if isinstance(g.colour, str) else "#00d4aa"

            # Arc geometry: theta1=-30 (5-oclock), theta2=210 (7-oclock), 240° span
            # Fill from -30 to (-30 + frac*240)
            theta1, theta2 = -30, 210
            fill_end = theta1 + frac * 240
            ro, ri = 1.0, 0.72
            mid = (ro+ri)/2

            # Background arc
            ax.add_patch(_mplp.Arc((0,0), 2*mid, 2*mid, angle=0,
                theta1=theta1, theta2=theta2, color=BG3, lw=18, zorder=1))
            # Filled arc
            if frac > 0.001:
                ax.add_patch(_mplp.Arc((0,0), 2*mid, 2*mid, angle=0,
                    theta1=theta1, theta2=fill_end, color=col, lw=18,
                    solid_capstyle="round", zorder=2))
                # Tip dot
                tx = mid * _math.cos(_math.radians(fill_end))
                ty = mid * _math.sin(_math.radians(fill_end))
                ax.plot(tx, ty, "o", color="white", ms=5, zorder=3)

            # Tick marks
            for tf in [0, 0.25, 0.5, 0.75, 1.0]:
                ta = _math.radians(theta1 + tf*240)
                ax.plot([ri*0.88*_math.cos(ta), ri*_math.cos(ta)],
                        [ri*0.88*_math.sin(ta), ri*_math.sin(ta)],
                        color=MUTED, lw=1.2, zorder=4)

            # Value text
            try: vstr = g.fmt.format(v=val)
            except: vstr = f"{round(val):,}" if val >= 1000 else str(round(val))
            fs = 13 if len(vstr) <= 5 else max(7, int(13*5/len(vstr)))
            ax.text(0, 0.08, vstr, ha="center", va="center",
                    fontsize=fs, fontweight="bold", color=col, fontfamily="monospace", zorder=5)
            ax.text(0, -0.32, g.label, ha="center", va="center",
                    fontsize=6.5, color=MUTED, fontfamily="monospace", zorder=5)
            # Min/max
            for tf, label in [(0,"0"),(1,f"{maxVal:,.0f}" if maxVal>=1000 else str(round(maxVal)))]:
                ta = _math.radians(theta1 + tf*240)
                ax.text(1.12*_math.cos(ta), 1.12*_math.sin(ta), label,
                        ha="center", va="center", fontsize=5.5, color=MUTED, fontfamily="monospace")

        plugin_name = snap.get("_plugin_name","")
        fig.suptitle(
            f"VK Contest Analyzer  {'· ' + plugin_name if plugin_name else ''}  "
            f"  {snap.get('valid',0):,} QSOs  ·  {snap.get('score',0):,} pts",
            color=FG, fontfamily="monospace", fontsize=8.5, y=0.97)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                    facecolor=BG, edgecolor="none")
        buf.seek(0)

        return StreamingResponse(iter([buf.getvalue()]), media_type="image/png",
            headers={"Content-Disposition": 'attachment; filename="vkcontest_snapshot.png"'})

    except ImportError:
        return JSONResponse({"error": "matplotlib not installed. Run: pip install matplotlib"}, status_code=500)
    except Exception as exc:
        log.exception("snapshot_png failed")
        return JSONResponse({"error": str(exc)}, status_code=500)



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

# 3-char VK states
for k,v in [("VK1",(-35,149)),("VK2",(-34,151)),("VK3",(-38,145)),
            ("VK4",(-28,153)),("VK5",(-35,139)),("VK6",(-32,116)),
            ("VK7",(-43,147)),("VK8",(-13,131)),("VK9",(-14,126))]:
    _PFX[k] = v

# VL = alternate VK prefix (VL4 = VK4, etc)
for k,v in [("VL1",(-35,149)),("VL2",(-34,151)),("VL3",(-38,145)),
            ("VL4",(-28,153)),("VL5",(-35,139)),("VL6",(-32,116)),
            ("VL7",(-43,147)),("VL8",(-13,131))]:
    _PFX[k] = v

# Pacific / Oceania 3-char (BEFORE shorter prefixes like F)
for k,v in [
    ("FK8",(-22,167)),  # New Caledonia
    ("FK7",(-12,167)),  # Chesterfield Is
    ("FO8",(-18,-149)), # French Polynesia
    ("KH6",(21,-158)),  # Hawaii
    ("KH0",(15,146)),   # Mariana Is
    ("KH2",(13,145)),   # Guam
    ("KL7",(61,-150)),  # Alaska
    ("KP4",(18,-67)),   # Puerto Rico
    ("P29",(-9,148)),   # Papua New Guinea
    ("ZK2",(-19,170)),  # Niue
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
    ("ZK",(-19,170)),   ("ZD",(-16,-6)),
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
    # Australian special/alternate callsigns
    ("VJ",(-25,134)), ("VN",(-25,134)),
    ("AX",(-25,134)),  # AX = special Australian
    # 1-char LAST — only matched if nothing longer matched
    ("F",(47,2)),       # France
    ("W",(39,-98)),     # USA
    ("K",(39,-98)),     # USA
    ("N",(39,-98)),     # USA
    ("R",(56,38)),      # Russia
]:
    _PFX[k] = v


def _call_to_latlon(callsign: str):
    """Best-effort callsign to [lat, lon]. Tries prefixes longest-first."""
    call = callsign.upper().strip()
    # Try 4, 3, 2, 1 char prefixes
    for n in [4, 3, 2, 1]:
        if n <= len(call) and call[:n] in _PFX:
            return _PFX[call[:n]]
    # Ultimate fallback for anything Australian-looking
    if call.startswith("VK") or call.startswith("VL") or call.startswith("VN"):
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
    import webview
    import signal as _signal

    port = port or _find_free_port()
    url  = f"http://127.0.0.1:{port}"

    # Pre-load if a valid file was passed on the command line
    if db_path and os.path.isfile(db_path):
        STATE.load_db(db_path)

    config = uvicorn.Config(
        app, host="127.0.0.1", port=port,
        log_level="warning", loop="asyncio",
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

    window = webview.create_window(
        title="VK Contest Analyzer",
        url=url,
        width=1400,
        height=860,
        min_size=(900, 600),
        background_color="#0d1117",
    )

    def _on_loaded():
        STATE._webview_window = window

    def _on_closed():
        """Called by pywebview on the GUI thread when the window is destroyed."""
        log.info("Window closed — shutting down")

        # Redirect stderr to suppress the noisy WebView2/Chromium window-class
        # unregister error that Windows logs during teardown:
        #   "Failed to unregister class Chrome_WidgetWin_0. Error = 1411"
        # This is benign (the class was already unregistered by the time the
        # renderer tries again) but confusing in logs.
        import io
        _devnull = open(os.devnull, "w")
        os.dup2(_devnull.fileno(), 2)   # redirect fd 2 (stderr) to /dev/null

        # Close WebSocket clients gracefully
        try:
            loop = asyncio.get_event_loop()
            for ws in list(STATE._clients):
                try:
                    asyncio.run_coroutine_threadsafe(ws.close(), loop)
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

    # Register the closing callback BEFORE webview.start()
    window.events.closed += _on_closed

    # webview.start() blocks here until the window closes.
    # _on_closed will call os._exit(0) so execution never returns here
    # under normal circumstances.
    try:
        webview.start(_on_loaded, debug=False)
    except Exception:
        pass

    # Fallback for non-PyWebView / browser-direct mode
    server.should_exit = True
    sys.exit(0)


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else None
    launch_webview(db_path=db)
