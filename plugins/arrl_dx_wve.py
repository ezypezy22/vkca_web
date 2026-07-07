"""
plugins/arrl_dx_wve.py  —  ARRL International DX Contest (W/VE Station)
========================================================================
For stations operating in the contiguous United States, DC, and Canadian
provinces/territories (excluding KH6, KL7, CY9, CYØ — those operate as DX).

Contest periods:
  CW:    Third full weekend in February, 0000–2359 UTC Saturday–Sunday
  Phone: First full weekend in March,    0000–2359 UTC Saturday–Sunday

Rules: https://contests.arrl.org/ContestRules/DX-Rules.pdf

Scoring (Rule 5, W/VE perspective)
-----------------------------------
  Every QSO = 3 points.
  Multipliers = unique DXCC entities contacted, counted once per band.
  Final score = total QSO points × total band-multiplier count.

Exchange (Rule 4, W/VE)
------------------------
  Send: signal report + state/province abbreviation.
  Receive: signal report + power (number or abbreviation).
  The received exchange does NOT contribute a multiplier from the W/VE side —
  the DXCC entity is derived from the contacted station's call sign prefix
  and is stored in the CountryPrefix / mult1 field by N1MM+.

Multiplier source
-----------------
  N1MM+ writes the DXCC entity abbreviation into the Sect / mult1 field
  (e.g. "DL", "JA", "VK") and sets IsMultiplier1=1 for new entities per band.
  This plugin trusts those flags; it only derives multipliers from mult1 when
  is_mult1 is absent (Cabrillo import fallback).

  W/VE stations do NOT count USA or Canada as multipliers (Rule 5.2.2).

Install
-------
  Copy this file to your plugins/ directory. The loader auto-discovers it.
  N1MM+ ContestName values recognised: see MATCH_KEYS below.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

from plugins.base import ContestPlugin, SessionConfig, MultResult, GaugeDef


# ── Configuration ─────────────────────────────────────────────────────────────
# No user-editable settings for W/VE — the station type is fixed by the plugin.

# ── Contest date helpers ───────────────────────────────────────────────────────

def _nth_full_weekend_saturday(year: int, month: int, n: int) -> date:
    """
    Return the Saturday of the Nth *full* weekend (Sat+Sun both in month)
    of the given month and year.  "Full weekend" means the Saturday is not
    the first day of the month (i.e. both Sat and Sun fall within the month).
    """
    # Find first Saturday on or after the 1st that still leaves a Sunday in-month
    saturdays = []
    for day in range(1, 29):
        try:
            d = date(year, month, day)
        except ValueError:
            break
        if d.weekday() == 5 and d.day + 1 <= _days_in_month(year, month):
            saturdays.append(d)
    return saturdays[n - 1]  # 1-indexed

def _days_in_month(year: int, month: int) -> int:
    import calendar
    return calendar.monthrange(year, month)[1]

def _cw_saturday(year: int) -> date:
    """Third full weekend in February."""
    return _nth_full_weekend_saturday(year, 2, 3)

def _phone_saturday(year: int) -> date:
    """First full weekend in March."""
    return _nth_full_weekend_saturday(year, 3, 1)


# ── Multiplier data ────────────────────────────────────────────────────────────
# W/VE stations exclude USA (W/VE call areas) and Canada from mult count.
# Everything else in the DXCC list is a valid mult.
# We don't hardcode the full DXCC list (3XX+ entities) — instead we exclude
# the W/VE prefixes and trust that any non-W/VE entity in mult1 is valid.

# N1MM+ prefixes that represent W/VE (not counted as mults for W/VE stations)
_WVE_DXCC_PREFIXES = {
    # Contiguous US call areas / prefixes
    "W", "K", "N", "AA", "AB", "AC", "AD", "AE", "AF", "AG", "AI", "AJ",
    "AK", "WA", "WB", "WC", "WD", "WE", "WF", "WG", "WH", "WI", "WJ",
    "WK", "WL", "WM", "WN", "WO", "WP", "WQ", "WR", "WS", "WT", "WU",
    "WV", "WX", "WY", "WZ",
    "KA", "KB", "KC", "KD", "KE", "KF", "KG", "KI", "KJ", "KK",
    "KM", "KN", "KO", "KP", "KQ", "KR", "KS", "KT", "KU", "KV",
    "KW", "KX", "KY", "KZ",
    # Canada
    "VE", "VA", "VO", "VY",
}

# N1MM+ DXCC abbreviations that represent W/VE entities (excluded as mults)
# These are what N1MM+ writes into the CountryPrefix / Sect / mult1 field.
_WVE_DXCC_ABBREVS = {
    "W", "VE",              # contiguous US and Canada
    "KP2", "KP4",          # US Caribbean territories (count as DX for this contest)
    # Note: KH6 and KL7 operate as DX stations — they ARE valid mults for W/VE
}

# Valid contest bands
ARRL_DX_BANDS = {"160M", "80M", "40M", "20M", "15M", "10M"}

def _band(b) -> str:
    try:
        mhz = float(b)
        if   1.8  <= mhz <  2.0:  return "160M"
        elif 3.5  <= mhz <  4.0:  return "80M"
        elif 7.0  <= mhz <  7.3:  return "40M"
        elif 14.0 <= mhz < 14.35: return "20M"
        elif 21.0 <= mhz < 21.45: return "15M"
        elif 28.0 <= mhz < 29.7:  return "10M"
        return str(b)
    except (TypeError, ValueError):
        s = str(b).upper().strip()
        return s if s.endswith("M") else s + "M"

def _is_wve_entity(entity: str) -> bool:
    """Return True if the DXCC entity abbreviation is a W/VE entity (not a valid mult)."""
    e = (entity or "").strip().upper()
    return e in {"W", "VE", ""}


# ── Plugin ─────────────────────────────────────────────────────────────────────

class ARRLDXWVEPlugin(ContestPlugin):
    """
    ARRL International DX Contest — W/VE Station perspective.
    Works DX stations; multipliers are unique DXCC entities per band.
    """

    MATCH_KEYS = {
        "ARRL-DX-CW",
        "ARRL-DX-SSB",
        "ARRL-DX-PH",
        "ARRL DX CW",
        "ARRL DX SSB",
        "ARRL DX PH",
        "ARRL DX",
        "ARRLDX-CW",
        "ARRLDX-SSB",
        "ARRLDXCW",
        "ARRLDXSSB",
    }

    preferred_exchange_columns = [
        # N1MM+ writes DXCC entity into these fields
        "CountryPrefix", "countryprefix",
        "Sect", "sect",
        "Exchange1", "exchange1",
        "Comment", "comment",
    ]

    # ── Identity ──────────────────────────────────────────────────────────────

    def identify(self, contest_name: str) -> bool:
        return contest_name.strip().upper() in {k.upper() for k in self.MATCH_KEYS}

    @property
    def display_name(self) -> str:
        return "ARRL International DX [W/VE Station]"

    # ── Multiplier label ──────────────────────────────────────────────────────

    def mult_label(self) -> str:
        return "DXCC Entity"

    # ── Multiplier list ───────────────────────────────────────────────────────
    # Not pre-defined — any valid DXCC entity (except W/VE) is a mult.

    def mult_list(self) -> list:
        return []

    def mult_of_qso(self, q: dict) -> Optional[str]:
        entity = str(q.get("mult1") or q.get("country_prefix") or "").strip().upper()
        return entity if entity and not _is_wve_entity(entity) else None

    def region_of_mult(self, m: str) -> Optional[str]:
        """No region grouping for W/VE — all entities are peers."""
        return None

    def region_list(self) -> list:
        return []

    # ── Session config ────────────────────────────────────────────────────────
    # 48-hour contest (0000–2359 UTC Sat–Sun), 1-hour rate buckets

    def session_config(self) -> SessionConfig:
        return SessionConfig(
            duration_mins=60,
            num_sessions=48,
            label_prefix="Hr ",
            start_hour=0,
        )

    def contest_saturday(self, year: int, mode: str = "CW") -> date:
        if mode.upper() == "SSB" or mode.upper() == "PH":
            return _phone_saturday(year)
        return _cw_saturday(year)

    # ── Per-QSO points ────────────────────────────────────────────────────────

    def recalc_pts(self, qsos: list) -> None:
        """
        Every valid non-dupe QSO = 3 points.
        Dupe detection: N1MM+ writes Points=0 for dupes.
        """
        seen: set = set()

        for q in qsos:
            b = _band(q.get("band") or q.get("freq") or "")
            if b not in ARRL_DX_BANDS:
                q["pts"] = 0
                q["dupe"] = 1
                continue

            raw_pts  = q.get("pts")
            key      = (str(q.get("call") or "").upper(), b)

            # Dupe detection (N1MM+ sets Points=0 for dupes)
            if q.get("dupe") or raw_pts == 0 or key in seen:
                q["pts"]  = 0
                q["dupe"] = 1
                continue

            seen.add(key)
            q["pts"] = 3   # ARRL DX: all QSOs = 3 pts

    # ── Score ─────────────────────────────────────────────────────────────────

    def score(self, qsos: list) -> int:
        pts  = sum(q.get("pts", 0) for q in qsos if not q.get("dupe"))
        mr   = self.multipliers(qsos)
        mults = len(mr.primary_mults) + len(mr.secondary_mults)
        return pts * mults if mults else pts

    # ── Multipliers ───────────────────────────────────────────────────────────

    def multipliers(self, qsos: list) -> MultResult:
        """Unique DXCC entities per band (Rule 5.2.2)."""
        primary: set = set()

        for q in qsos:
            if q.get("dupe") or not q.get("pts"):
                continue
            entity = str(q.get("mult1") or "").strip().upper()
            if not entity or _is_wve_entity(entity):
                continue
            # Trust is_mult1 if present
            is_m1 = q.get("is_mult1")
            if is_m1 is not None and is_m1 != 1:
                continue
            b = _band(q.get("band") or q.get("freq") or "")
            primary.add(f"{entity}/{b}")

        return MultResult(
            primary_mults=primary,
            secondary_mults=set(),
            primary_label="DXCC Entities",
            secondary_label="",
        )

    # ── UI hints ──────────────────────────────────────────────────────────────

    def has_missing_tab(self) -> bool:
        return False   # DXCC list is open — any entity could be activated

    def band_list(self) -> list:
        # ARRL DX is 160-10m — no WARC bands (30/17/12m).
        return ["160M", "80M", "40M", "20M", "15M", "10M"]

    def gauge_defs(self, data: dict, total_mults: int) -> list:
        return [
            GaugeDef("TOTAL QSOs",     "total",     "qso_max",   "#00d4aa", "{v}"),
            GaugeDef("VALID QSOs",     "valid",     "qso_max",   "#2ed573", "{v}"),
            GaugeDef("TOTAL SCORE",    "score",     "score_max", "#f0c040", "{v:,}"),
            GaugeDef("DXCC ENTITIES",  "worked",    total_mults, "#f0c040", "{v}"),
            GaugeDef("BAND MULTS",     "band_mults",total_mults, "#2ed573", "{v}"),
            GaugeDef("% COMPLETE",     "pct",       100.0,       "#8b949e", "{v:.1f}%"),
        ]

    # ── Cabrillo ──────────────────────────────────────────────────────────────

    def cabrillo_contest(self) -> str:
        return "ARRL-DX-CW"   # or ARRL-DX-SSB; overridden at submission time


def register() -> ARRLDXWVEPlugin:
    return ARRLDXWVEPlugin()
