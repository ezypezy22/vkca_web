"""
dxcc.py
───────
Callsign → DXCC entity / CQ zone / ITU zone / continent lookup, parsed from a
standard cty.dat-format country file (data/wl_cty.dat), plus the Super Check
Partial callsign list (data/master.scp).

Used by standalone logging mode (contest_log.ContestLog.add_qso) so a QSO
logged here gets the same country/zone/continent fields N1MM would have
written — without these, country/zone-scored contests (CQ WW, WPX, ARRL DX…)
cannot be scored at all.

cty.dat format (one entity = a header line + alias lines ending in ';'):

    Australia:  30:  59:  OC:  -23.70:  -132.33:  -10.0:  VK:
        AX,VI,VJ,VK,VL,=VI9POL,VK6(29)[58],=VK70VHF(29)[58];

Header fields: name, CQ zone, ITU zone, continent, lat, lon, tz, primary prefix.
Alias modifiers: leading '=' = exact callsign, (n) CQ zone override,
[n] ITU zone override, {xx} continent override, <lat/lon>, ~tz~.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Optional

_MOD_RE = {
    "cq":   re.compile(r"\((\d+)\)"),
    "itu":  re.compile(r"\[(\d+)\]"),
    "cont": re.compile(r"\{([A-Za-z]{2})\}"),
    "ll":   re.compile(r"<[^>]*>"),
    "tz":   re.compile(r"~[^~]*~"),
}

# Suffixes that carry no location information.
_NEUTRAL_SUFFIXES = {"P", "M", "QRP", "A", "B", "LH", "T", "R", "LGT", "F"}
# Maritime / aeronautical mobile: no DXCC entity at all.
_NO_ENTITY_SUFFIXES = {"MM", "AM"}


def _data_dir() -> Path:
    """data/ beside this file in dev, under _MEIPASS when frozen."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "data"


class Dxcc:
    def __init__(self, cty_path: Optional[str] = None):
        self.entities: list[dict] = []
        self._exact: dict[str, dict] = {}
        self._prefix: dict[str, dict] = {}
        self._maxlen = 0
        self._load(Path(cty_path) if cty_path else _data_dir() / "wl_cty.dat")

    # ── Parsing ───────────────────────────────────────────────────────────────

    def _load(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8", errors="replace")
        header = None
        alias_buf: list[str] = []

        def flush():
            if header is None:
                return
            ent = header
            self.entities.append(ent)
            for tok in "".join(alias_buf).replace("\n", "").split(","):
                tok = tok.strip().rstrip(";").strip()
                if not tok:
                    continue
                exact = tok.startswith("=")
                if exact:
                    tok = tok[1:]
                info = {
                    "country": ent["country"], "prefix": ent["prefix"],
                    "cq": ent["cq"], "itu": ent["itu"], "cont": ent["cont"],
                }
                m = _MOD_RE["cq"].search(tok)
                if m:
                    info["cq"] = int(m.group(1))
                m = _MOD_RE["itu"].search(tok)
                if m:
                    info["itu"] = int(m.group(1))
                m = _MOD_RE["cont"].search(tok)
                if m:
                    info["cont"] = m.group(1).upper()
                for k in ("cq", "itu", "cont", "ll", "tz"):
                    tok = _MOD_RE[k].sub("", tok)
                tok = tok.strip().upper()
                if not tok:
                    continue
                if exact:
                    self._exact[tok] = info
                else:
                    self._prefix[tok] = info
                    self._maxlen = max(self._maxlen, len(tok))

        # The file's '#' comment blocks wrap onto indented continuation lines
        # (ending in ';') that look exactly like alias lines — skip them too.
        in_comment = False
        for line in text.splitlines():
            if in_comment:
                if line.rstrip().endswith(";"):
                    in_comment = False
                continue
            if not line.strip():
                continue
            if line.lstrip().startswith("#"):
                in_comment = not line.rstrip().endswith(";")
                continue
            if not line[0].isspace():
                # New entity header — close the previous one first.
                flush()
                alias_buf = []
                parts = [p.strip() for p in line.split(":")]
                if len(parts) < 8:
                    header = None
                    continue
                header = {
                    "country": parts[0], "cq": int(parts[1]), "itu": int(parts[2]),
                    "cont": parts[3].upper(), "prefix": parts[7].lstrip("*"),
                }
            elif header is not None:
                alias_buf.append(line.strip())
        flush()
        self._apply_overrides()

    def _apply_overrides(self) -> None:
        """wl_cty.dat only mentions these in a '#' comment ("VK6(29)[58],
        VK8(29)[55]"), not as real aliases, so apply them explicitly: VK6
        (Western Australia) and VK8 (Northern Territory) are CQ zone 29;
        every other VK call area stays 30."""
        base = self._prefix.get("VK")
        if not base:
            return
        for pfx in ("AX", "VH", "VI", "VJ", "VK", "VL", "VM", "VN", "VZ"):
            for digit, itu in (("6", 58), ("8", 55)):
                self._prefix[pfx + digit] = {**base, "cq": 29, "itu": itu}
                self._maxlen = max(self._maxlen, len(pfx) + 1)

    # ── Lookup ────────────────────────────────────────────────────────────────

    def _lookup_plain(self, call: str) -> Optional[dict]:
        hit = self._exact.get(call)
        if hit:
            return hit
        for n in range(min(len(call), self._maxlen), 0, -1):
            hit = self._prefix.get(call[:n])
            if hit:
                return hit
        return None

    def lookup(self, call: str) -> Optional[dict]:
        """Return {country, prefix, cq, itu, cont} for a callsign, or None
        (unknown prefix, or a /MM or /AM station with no DXCC entity)."""
        call = (call or "").strip().upper()
        if not call:
            return None
        hit = self._exact.get(call)
        if hit:
            return hit
        if "/" not in call:
            return self._lookup_plain(call)

        parts = [p for p in call.split("/") if p]
        if not parts:
            return None
        if any(p in _NO_ENTITY_SUFFIXES for p in parts[1:]):
            return None
        # Drop location-neutral suffixes (/P, /M, /QRP, ...).
        parts = [parts[0]] + [p for p in parts[1:] if p not in _NEUTRAL_SUFFIXES]
        if len(parts) == 1:
            return self._lookup_plain(parts[0])

        a, b = parts[0], parts[-1]
        # A lone digit replaces the call-area digit: VK6NX/3 → treated as VK3.
        if len(b) == 1 and b.isdigit():
            m = re.match(r"^([A-Z]+|\d[A-Z]+)\d", a)
            if m:
                swapped = self._lookup_plain(m.group(1) + b)
                if swapped:
                    return swapped
            return self._lookup_plain(a)
        # Otherwise the shorter part is the operating-location prefix
        # (VK9/ZL1X → VK9, ZL1X/VK9 → VK9); ties go to the left part.
        loc, home = (a, b) if len(a) <= len(b) else (b, a)
        return self._lookup_plain(loc) or self._lookup_plain(home)


_instance: Optional[Dxcc] = None


def get_dxcc() -> Dxcc:
    global _instance
    if _instance is None:
        _instance = Dxcc()
    return _instance


# ── Super Check Partial ───────────────────────────────────────────────────────

_scp: Optional[list] = None


def load_scp(path: Optional[str] = None) -> list:
    """Sorted list of known callsigns from master.scp (comment lines — '#' or
    '!!' — and blanks skipped)."""
    global _scp
    if _scp is not None and path is None:
        return _scp
    p = Path(path) if path else _data_dir() / "master.scp"
    calls = []
    try:
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip().upper()
            if line and not line.startswith(("#", "!")):
                calls.append(line)
    except OSError:
        calls = []
    calls = sorted(set(calls))
    if path is None:
        _scp = calls
    return calls


def scp_partial(partial: str, limit: int = 30) -> list:
    """Callsigns containing `partial` (substring match, like N1MM's SCP window),
    prefix matches first."""
    partial = (partial or "").strip().upper()
    if len(partial) < 2:
        return []
    calls = load_scp()
    starts = [c for c in calls if c.startswith(partial)]
    if len(starts) >= limit:
        return starts[:limit]
    others = [c for c in calls if partial in c and not c.startswith(partial)]
    return (starts + others)[:limit]
