"""
web/radio_udp.py — N1MM+ Logger "RadioInfo" UDP broadcast listener.

N1MM+ can broadcast a small XML packet describing the live radio state
(frequency, band, mode, operator callsign) — enabled per-install under
Config > Config Ports... > Broadcast Data tab > "Radio" checkbox, default
port 12060. It's sent every 10s, or immediately after anything in it
changes. Format (confirmed against N1MM+'s own docs, sample packet below):

    <RadioInfo>
      <StationName>CW-80m</StationName>
      <RadioNr>1</RadioNr>
      <Freq>352211</Freq>        <!-- tens of Hz, no decimal point -->
      <TXFreq>352211</TXFreq>
      <Mode>CW</Mode>
      <OpCall>W1ABC</OpCall>
      <ActiveRadioNr>1</ActiveRadioNr>
      ...
    </RadioInfo>

352211 -> 3,522,110 Hz -> 3.522110 MHz, which is in the 80m band — matching
the <StationName>CW-80m</StationName> label in that same sample packet.

This module intentionally does not import anything from web.server — it's
started by server.py's lifespan() handler, which passes in a band-lookup
callable (server.py already has one, used for DX Cluster spot classification)
rather than this module importing it back, to avoid a circular import.
"""

from __future__ import annotations

import logging
import socket
import time
import xml.etree.ElementTree as ET
from typing import Callable, Optional

log = logging.getLogger(__name__)

DEFAULT_PORT = 12060

# Entries older than this are treated as stale (radio disconnected, N1MM+
# closed, or the broadcast was turned off) — about 2x N1MM+'s own 10s
# broadcast interval, with margin for a missed packet or two.
STALE_AFTER_SECS = 20.0


def parse_radio_info(raw: bytes) -> Optional[dict]:
    """
    Parse one RadioInfo UDP packet. Returns None for anything that isn't a
    well-formed RadioInfo packet with a usable frequency — defensive,
    since other UDP traffic could in principle land on the same port, and
    a malformed/partial packet (e.g. rig not connected, Freq blank) must
    not be treated as "radio at 0 Hz".
    """
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    if root.tag != "RadioInfo":
        return None

    def text(tag: str) -> str:
        el = root.find(tag)
        return (el.text or "").strip() if el is not None else ""

    freq_raw = text("Freq")
    try:
        freq_hz = int(freq_raw) * 10
    except ValueError:
        return None
    if freq_hz <= 0:
        return None

    return {
        "radio_nr": text("RadioNr") or "1",
        "freq_hz": freq_hz,
        "mode": text("Mode").upper(),
        "op_call": text("OpCall").upper(),
        "station_name": text("StationName"),
        "active": text("ActiveRadioNr") == (text("RadioNr") or "1"),
    }


def run_radio_info_listener(
    state,
    band_lookup: Callable[[float], str],
    stop_check: Callable[[], bool],
    notify: Optional[Callable[[], None]] = None,
    port: int = DEFAULT_PORT,
) -> None:
    """
    Blocking loop — run this on its own daemon thread. Binds a UDP socket
    on 0.0.0.0:`port` (0.0.0.0 so packets sent either to loopback, per
    N1MM+'s single-PC default, or to a LAN broadcast address in a
    multi-station setup, are both received) and writes each parsed packet
    into `state.radio_info` under `state._lock`, keyed by
    "<source_ip>|<radio_nr>" — not radio_nr alone, since in a multi-PC
    Multi-Multi setup several stations could each be broadcasting their own
    "RadioNr 1" to the same subnet, and keying on radio_nr alone would let
    them clobber each other.

    `stop_check()` is polled every socket-read timeout (1s) so the thread
    exits promptly when the app is shutting down; `daemon=True` (set by the
    caller) means this isn't strictly required for the process to exit
    cleanly, but avoids relying on that.

    `notify()`, if given, is called after every successfully-parsed packet.
    Radio state changes independently of QSO logging and QRZ lookups — the
    app's only other two live-update triggers — so without this, a
    frequency change only reaches already-connected clients (Mini HUD,
    titlebar, etc.) by coincidence, whenever one of those unrelated
    triggers happens to also fire a broadcast. The caller (web/server.py)
    passes in its own debounced cross-thread broadcast bridge, the same
    pattern already used for QRZ worker updates.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", port))
    except OSError as exc:
        # Most likely another process (or another instance of this app) has
        # the port already — this must not take down the whole app, the
        # radio readout just silently stays empty.
        log.warning("radio_udp: could not bind UDP port %d (%s) — live radio "
                    "readout disabled for this session", port, exc)
        sock.close()
        return

    sock.settimeout(1.0)
    log.info("Listening for N1MM+ RadioInfo broadcasts on 0.0.0.0:%d", port)
    try:
        while not stop_check():
            try:
                raw, (source_ip, _src_port) = sock.recvfrom(8192)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                entry = parse_radio_info(raw)
            except Exception:
                log.debug("radio_udp: failed to parse packet from %s", source_ip, exc_info=True)
                continue
            if entry is None:
                continue
            entry["source_ip"] = source_ip
            entry["band"] = band_lookup(entry["freq_hz"] / 1000.0)
            entry["updated_at"] = time.time()
            key = f"{source_ip}|{entry['radio_nr']}"
            with state._lock:
                state.radio_info[key] = entry
            if notify is not None:
                try:
                    notify()
                except Exception:
                    log.warning("radio_udp: notify callback raised", exc_info=True)
    finally:
        sock.close()
        log.info("Listener stopped")
