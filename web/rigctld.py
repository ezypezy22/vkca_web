"""
web/rigctld.py — Hamlib rigctld TCP client for standalone Logger-mode rig
control (frequency/mode/PTT reading + mode/CW-macro writing).

rigctld ("rig control daemon") is a small TCP server most CAT-capable ham
software can already point at — this app is just another client of it,
the same role WSJT-X/N1MM's own Hamlib backend play. No serial/per-rig
driver code lives here; rigctld itself owns the actual CAT link.

Deliberately mirrors web/radio_udp.py's own shape (dict entries written
into state.radio_info, same keys) so every existing consumer of that
structure — AppState._own_and_all_radios(), app.js's formatRadio(), the
titlebar/HUD/Overview/Operator-HUD readouts, entrywindow.js's
updateHeader() — needs zero changes to also work from rigctld instead of
N1MM+'s own UDP broadcast.

Only ever active for a standalone log (STATE.is_standalone_log) — see
server.py's _sync_rigctld() — so this app never contends with N1MM+ (or
anything else) for the same rig.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Callable, Optional

log = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4532

# rigctld is polled roughly once a second (cheap local TCP, unlike N1MM+'s
# 10s UDP broadcast interval), so a much shorter staleness window than
# radio_udp's 20s is appropriate here.
STALE_AFTER_SECS = 10.0

_CONNECT_TIMEOUT = 2.0
_RECV_TIMEOUT = 2.0
_POLL_INTERVAL = 1.0
_MAX_BACKOFF = 10.0


def _rprt_ok(lines: list[str]) -> tuple[bool, Optional[str]]:
    """Every rigctld SET-type command (set_mode, send_morse, stop_morse)
    ends its response with a "RPRT <code>" line — 0 means success,
    anything else (including negative Hamlib error codes) means failure."""
    if not lines:
        return False, "no response from rigctld"
    last = lines[-1]
    if not last.startswith("RPRT"):
        return False, f"unexpected response from rigctld: {last!r}"
    parts = last.split()
    try:
        code = int(parts[1])
    except (IndexError, ValueError):
        return False, f"malformed RPRT line from rigctld: {last!r}"
    if code == 0:
        return True, None
    return False, f"rigctld reported error {code}"


class RigctldConnection:
    """One TCP connection to rigctld, shared by the background poller
    (reads) and on-demand write commands (F-key macros, mode changes) via
    `_lock` — rigctld is strictly request/response per connection, so the
    two must never interleave a command/response pair. Reconnects lazily
    on the next command after any I/O error."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self._lock = threading.Lock()
        self._sock: Optional[socket.socket] = None
        self._rfile = None

    def close(self):
        with self._lock:
            self._close_locked()

    def _close_locked(self):
        if self._rfile is not None:
            try:
                self._rfile.close()
            except Exception:
                pass
            self._rfile = None
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def _connect_locked(self):
        if self._sock is not None:
            return
        sock = socket.create_connection((self.host, self.port), timeout=_CONNECT_TIMEOUT)
        sock.settimeout(_RECV_TIMEOUT)
        self._sock = sock
        self._rfile = sock.makefile("r", encoding="ascii", newline="\n")

    def _cmd_locked(self, text: str, expect_lines: int = 0) -> list[str]:
        """Send one long-form rigctld command (e.g. "\\get_freq") and
        return its response lines. For a GET command, pass the exact
        number of value lines it returns (1 for get_freq/get_ptt, 2 for
        get_mode+passband) — rigctld's plain GET responses have no
        terminator line, so the caller must know the count. For a
        SET-type command, pass 0 (the default) — reads until the
        "RPRT <code>" line every set command always ends with."""
        self._connect_locked()
        self._sock.sendall((text + "\n").encode("ascii"))
        lines: list[str] = []
        if expect_lines:
            for _ in range(expect_lines):
                line = self._rfile.readline()
                if not line:
                    raise ConnectionError("rigctld closed the connection")
                lines.append(line.rstrip("\n"))
            return lines
        while True:
            line = self._rfile.readline()
            if not line:
                raise ConnectionError("rigctld closed the connection")
            line = line.rstrip("\n")
            lines.append(line)
            if line.startswith("RPRT"):
                return lines

    def _run(self, text: str, expect_lines: int = 0) -> list[str]:
        with self._lock:
            try:
                return self._cmd_locked(text, expect_lines)
            except Exception:
                self._close_locked()   # force a reconnect on the next attempt
                raise

    # ── Reads (used by the poller thread) ───────────────────────────────
    def get_freq_hz(self) -> int:
        return int(self._run("\\get_freq", expect_lines=1)[0].strip())

    def get_mode(self) -> str:
        return self._run("\\get_mode", expect_lines=2)[0].strip().upper()

    def get_ptt(self) -> bool:
        return self._run("\\get_ptt", expect_lines=1)[0].strip() == "1"

    # ── Writes (used by /api/rig/* handlers) ────────────────────────────
    def set_mode(self, mode: str) -> tuple[bool, Optional[str]]:
        try:
            lines = self._run(f"\\set_mode {mode} 0")
        except Exception as exc:
            return False, str(exc)
        return _rprt_ok(lines)

    def send_morse(self, text: str) -> tuple[bool, Optional[str]]:
        try:
            lines = self._run(f"\\send_morse {text}")
        except Exception as exc:
            return False, str(exc)
        return _rprt_ok(lines)

    def stop_morse(self) -> tuple[bool, Optional[str]]:
        # Best-effort — not every rig backend supports aborting mid-send;
        # the server.py endpoint treats a failure here as non-fatal.
        try:
            lines = self._run("\\stop_morse")
        except Exception as exc:
            return False, str(exc)
        return _rprt_ok(lines)

    def set_freq(self, freq_hz: int) -> tuple[bool, Optional[str]]:
        try:
            lines = self._run(f"\\set_freq {int(freq_hz)}")
        except Exception as exc:
            return False, str(exc)
        return _rprt_ok(lines)


def run_rigctld_poller(
    state,
    band_lookup: Callable[[float], str],
    stop_check: Callable[[], bool],
    notify: Optional[Callable[[], None]],
    host: str,
    port: int,
) -> None:
    """
    Blocking loop — run this on its own daemon thread (see server.py's
    _sync_rigctld()). Polls freq/mode/ptt roughly once a second and writes
    one entry into state.radio_info["rigctld|1"], in the exact same shape
    radio_udp.py's own listener uses (see this module's docstring for why
    that means every existing consumer needs zero changes to also read
    from rigctld).

    `stop_check()` is polled every loop iteration so the thread exits
    promptly when rig control is disabled or a non-standalone log is
    loaded. `notify()`, if given, is the same debounced cross-thread
    broadcast bridge radio_udp.py's listener uses.
    """
    conn = RigctldConnection(host, port)
    state.rigctld_conn = conn
    backoff = 1.0
    log.info("rigctld poller connecting to %s:%d", host, port)
    try:
        while not stop_check():
            try:
                freq_hz = conn.get_freq_hz()
                mode = conn.get_mode()
                ptt = conn.get_ptt()
            except Exception as exc:
                with state._lock:
                    state.rigctld_status = f"Could not reach rigctld at {host}:{port} ({exc})"
                time.sleep(min(backoff, _MAX_BACKOFF))
                backoff = min(backoff * 2, _MAX_BACKOFF)
                continue
            backoff = 1.0
            with state._lock:
                state.rigctld_status = None
                state.radio_info["rigctld|1"] = {
                    "radio_nr":     "1",
                    "freq_hz":      freq_hz,
                    "mode":         mode,
                    "op_call":      "",
                    "station_name": "",
                    "active":       True,
                    "source_ip":    "rigctld",
                    "band":         band_lookup(freq_hz / 1000.0),
                    "updated_at":   time.time(),
                    "ptt":          ptt,
                }
            if notify is not None:
                try:
                    notify()
                except Exception:
                    log.warning("rigctld: notify callback raised", exc_info=True)
            time.sleep(_POLL_INTERVAL)
    finally:
        conn.close()
        with state._lock:
            if state.rigctld_conn is conn:
                state.rigctld_conn = None
        log.info("rigctld poller stopped")
