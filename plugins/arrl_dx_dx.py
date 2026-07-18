"""
plugins/arrl_dx_dx.py  —  ARRL International DX Contest (DX Station)
======================================================================
For stations operating OUTSIDE the contiguous USA and Canada.
This includes KH6 (Hawaii), KL7 (Alaska), CY9 (St Paul Is.), CYØ (Sable Is.)
which all participate as DX stations per Rule 2.3.

Contest periods:
  CW:    Third full weekend in February, 0000–2359 UTC Saturday–Sunday
  Phone: First full weekend in March,    0000–2359 UTC Saturday–Sunday

Rules: https://contests.arrl.org/ContestRules/DX-Rules.pdf

Scoring (Rule 5, DX perspective)
----------------------------------
  Every QSO = 3 points.
  Multipliers = unique US states + DC + Canadian provinces/territories
                per band.  VO1 and VO2 count separately (Rule 5.2.3).
  Final score = total QSO points × total band-multiplier count.

Exchange (Rule 4, DX)
----------------------
  Send: signal report + power (watts or abbreviation, e.g. "100" or "KW").
  Receive: signal report + state/province abbreviation.
  The received state/province IS the multiplier — stored in mult1 (Sect).

Multiplier list (Rule 5.2.3)
-----------------------------
  48 US states  (not AK or HI — those are DX entities)
  + DC
  + 14 Canadian provinces/territories
  + LB (Labrador, counted separately from NF)
  = 64 total multipliers × 6 bands = 384 maximum band-mults

Notes
-----
  • VO1 = Newfoundland  (NF in N1MM+)
  • VO2 = Labrador      (LB in N1MM+ — counted separately by tradition)
  • AK and HI are DXCC entities — they do NOT count as state mults.
  • DC counts as a separate multiplier.

Install
-------
  Copy this file to your plugins/ directory.
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Optional

from plugins.base import ContestPlugin, SessionConfig, MultResult, GaugeDef
from plugins.loader import looks_like_w_ve_call


# ── Contest date helpers ───────────────────────────────────────────────────────

def _nth_full_weekend_saturday(year: int, month: int, n: int) -> date:
    saturdays = []
    days_in = calendar.monthrange(year, month)[1]
    for day in range(1, days_in):
        d = date(year, month, day)
        if d.weekday() == 5 and d.day + 1 <= days_in:
            saturdays.append(d)
    return saturdays[n - 1]

def _cw_saturday(year: int) -> date:
    return _nth_full_weekend_saturday(year, 2, 3)

def _phone_saturday(year: int) -> date:
    return _nth_full_weekend_saturday(year, 3, 1)


# ── Multiplier tables (Rule 5.2.3) ────────────────────────────────────────────

# 48 contiguous US states + DC (no AK or HI)
_US_STATES = {
    "AL", "AZ", "AR", "CA", "CO", "CT", "DC", "DE", "FL", "GA",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA",
    "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM",
    "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD",
    "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
}

# Canadian provinces/territories + LB (Labrador separate)
_CA_PROVINCES = {
    "AB", "BC", "LB", "MB", "NB", "NF", "NS", "NT", "NU",
    "ON", "PE", "QC", "SK", "YT",
}

# Full valid multiplier set
_ALL_MULTS: set = _US_STATES | _CA_PROVINCES

# Region groupings for heat map
_REGION_MAP = {
    # US regions
    "AL": "US-SE", "FL": "US-SE", "GA": "US-SE", "MS": "US-SE",
    "NC": "US-SE", "SC": "US-SE", "TN": "US-SE", "VA": "US-SE",
    "KY": "US-SE", "WV": "US-SE", "DC": "US-SE", "MD": "US-SE",
    "DE": "US-NE", "CT": "US-NE", "MA": "US-NE", "ME": "US-NE",
    "NH": "US-NE", "NJ": "US-NE", "NY": "US-NE", "PA": "US-NE",
    "RI": "US-NE", "VT": "US-NE",
    "IA": "US-MW", "IL": "US-MW", "IN": "US-MW", "KS": "US-MW",
    "MI": "US-MW", "MN": "US-MW", "MO": "US-MW", "NE": "US-MW",
    "ND": "US-MW", "OH": "US-MW", "SD": "US-MW", "WI": "US-MW",
    "AR": "US-SC", "LA": "US-SC", "OK": "US-SC", "TX": "US-SC",
    "AZ": "US-W",  "CO": "US-W",  "ID": "US-W",  "MT": "US-W",
    "NM": "US-W",  "NV": "US-W",  "OR": "US-W",  "UT": "US-W",
    "WA": "US-W",  "WY": "US-W",  "CA": "US-W",
    # Canada
    "AB": "CA", "BC": "CA", "LB": "CA", "MB": "CA", "NB": "CA",
    "NF": "CA", "NS": "CA", "NT": "CA", "NU": "CA", "ON": "CA",
    "PE": "CA", "QC": "CA", "SK": "CA", "YT": "CA",
}

# Valid bands
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


# ── Plugin ─────────────────────────────────────────────────────────────────────

class ARRLDXDXPlugin(ContestPlugin):
    """
    ARRL International DX Contest — DX Station perspective.
    Works W/VE stations only; multipliers are US states + DC + CA provinces per band.
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
        # web/server.py's /api/load re-resolves the plugin from its OWN
        # display_name string (round-tripped from an earlier /api/scan),
        # not just the raw N1MM ContestName — include it so that round
        # trip doesn't fall through to GenericPlugin.
        "ARRL INTERNATIONAL DX [DX STATION]",
    }

    preferred_exchange_columns = [
        "Sect", "sect",               # N1MM+ writes state/prov here
        "Exchange1", "exchange1",
        "RcvExch", "rcvexch",
        "Comment", "comment",
    ]

    # ── Identity ──────────────────────────────────────────────────────────────

    def identify(self, contest_name: str) -> bool:
        return contest_name.strip().upper() in {k.upper() for k in self.MATCH_KEYS}

    def matches_station(self, my_call: Optional[str]) -> bool:
        # Loses the tiebreak only when my_call is confidently a mainland
        # US/Canadian call — ARRLDXWVEPlugin.matches_station() is the
        # mirror image of this check. See issue #40.
        return not looks_like_w_ve_call(my_call)

    @property
    def display_name(self) -> str:
        return "ARRL International DX [DX Station]"

    # ── Multiplier label ──────────────────────────────────────────────────────

    def mult_label(self) -> str:
        return "State/Province"

    # ── Multiplier list ───────────────────────────────────────────────────────

    def mult_list(self) -> list:
        return sorted(_ALL_MULTS)

    def mult_of_qso(self, q: dict) -> Optional[str]:
        m = str(q.get("mult1") or "").strip().upper()
        return m if m in _ALL_MULTS else None

    def region_of_mult(self, m: str) -> Optional[str]:
        return _REGION_MAP.get((m or "").strip().upper())

    def region_list(self) -> list:
        return sorted({
            "US-NE", "US-SE", "US-MW", "US-SC", "US-W", "CA"
        })

    # ── Session config ────────────────────────────────────────────────────────

    def session_config(self) -> SessionConfig:
        return SessionConfig(
            duration_mins=60,
            num_sessions=48,
            label_prefix="Hr ",
            start_hour=0,
        )

    def contest_saturday(self, year: int, mode: str = "CW") -> date:
        if str(mode).upper() in {"SSB", "PH"}:
            return _phone_saturday(year)
        return _cw_saturday(year)

    # ── Per-QSO points ────────────────────────────────────────────────────────

    def recalc_pts(self, qsos: list) -> None:
        """Every non-dupe QSO with a W/VE (North America) station on a
        valid band = 3 points (rule 5.2.1). Contacts with other DX
        stations (e.g. VK working JA or another VK) are logged but
        non-scoring — N1MM itself flags these Points=0, ContactType='N',
        Continent != 'NA'; skip crediting them rather than letting the
        generic loader's "0-pt non-dupe -> 1 pt" fallback (meant for
        contests like CQWW) leak a false point value in here."""
        seen: set = set()

        for q in qsos:
            b = _band(q.get("band") or q.get("freq") or "")
            if b not in ARRL_DX_BANDS:
                q["pts"] = 0
                q["dupe"] = 1
                continue

            raw_pts   = q.get("pts")
            call      = str(q.get("call") or "").upper()
            continent = q.get("continent") or ""
            key       = (call, b)

            # Non-NA contacts are logged but non-scoring, not dupes — check
            # this before the raw_pts==0 dupe heuristic below, since N1MM
            # legitimately zeroes Points for these too (see issue #50).
            if continent and continent != "NA":
                q["pts"] = 0
                continue

            if q.get("dupe") or raw_pts == 0 or key in seen:
                q["pts"]  = 0
                q["dupe"] = 1
                continue

            seen.add(key)
            # Normalise state/province to uppercase
            m = str(q.get("mult1") or "").strip().upper()
            q["mult1"] = m if m in _ALL_MULTS else ""
            q["pts"]   = 3

    # ── Score ─────────────────────────────────────────────────────────────────

    def score(self, qsos: list) -> int:
        pts   = sum(q.get("pts", 0) for q in qsos if not q.get("dupe"))
        mr    = self.multipliers(qsos)
        mults = len(mr.primary_mults) + len(mr.secondary_mults)
        return pts * mults if mults else pts

    # ── Multipliers ───────────────────────────────────────────────────────────

    def multipliers(self, qsos: list) -> MultResult:
        """Unique states/provinces per band (Rule 5.2.3)."""
        primary: set = set()

        for q in qsos:
            if q.get("dupe") or not q.get("pts"):
                continue
            m = str(q.get("mult1") or "").strip().upper()
            if m not in _ALL_MULTS:
                continue
            is_m1 = q.get("is_mult1")
            if is_m1 is not None and is_m1 != 1:
                continue
            b = _band(q.get("band") or q.get("freq") or "")
            primary.add(f"{m}/{b}")

        return MultResult(
            primary_mults=primary,
            secondary_mults=set(),
            primary_label="States/Provinces",
            secondary_label="",
        )

    # ── Worked / missing helpers ──────────────────────────────────────────────

    def worked_primary_mults(self, qsos: list) -> set:
        worked = set()
        for q in qsos:
            if not q.get("dupe") and q.get("pts"):
                m = str(q.get("mult1") or "").strip().upper()
                if m in _ALL_MULTS:
                    worked.add(m)
        return worked

    def missing_primary_mults(self, qsos: list) -> list:
        return sorted(_ALL_MULTS - self.worked_primary_mults(qsos))

    def post_snapshot(self, snap: dict, qsos: list) -> None:
        """compute_snapshot()'s generic worked/missing/pct math assumes
        primary_mults entries are either a flat value or a (value, ...)
        tuple, but multipliers() here returns band-scoped compound strings
        like "NSW/40M" for the (already-correct) BAND MULTS gauge — so that
        generic math treats every band-mult as a distinct "missing" entry
        forever and can push pct over 100% (see issue #42). Recompute
        worked/missing/pct from the unique-state worked_primary_mults()/
        missing_primary_mults() helpers instead — already correct
        elsewhere, e.g. the Missing Mults tab. band_mults is untouched:
        the generic band-pair count is correct for that gauge."""
        worked_states = self.worked_primary_mults(qsos)
        total_states  = len(_ALL_MULTS)
        snap["worked"]  = len(worked_states)
        snap["missing"] = total_states - len(worked_states)
        snap["pct"]     = (len(worked_states) / total_states * 100) if total_states else 0.0

    def has_missing_tab(self) -> bool:
        return True   # 64 defined mults — missing tab is very useful

    def band_list(self) -> list:
        # ARRL DX is 160-10m — no WARC bands (30/17/12m).
        return ["160M", "80M", "40M", "20M", "15M", "10M"]

    # ── Region heat map ───────────────────────────────────────────────────────

    def mults_by_region(self, qsos: list) -> dict:
        worked = self.worked_primary_mults(qsos)
        result = {}
        for m in _ALL_MULTS:
            reg = self.region_of_mult(m) or "__other__"
            if reg not in result:
                result[reg] = {"worked": [], "missing": []}
            if m in worked:
                result[reg]["worked"].append(m)
            else:
                result[reg]["missing"].append(m)
        return result

    # ── UI hints ──────────────────────────────────────────────────────────────

    def gauge_defs(self, data: dict, total_mults: int) -> list:
        return [
            GaugeDef("TOTAL QSOs",       "total",      "qso_max",    "#00d4aa", "{v}"),
            GaugeDef("VALID QSOs",       "valid",      "qso_max",    "#2ed573", "{v}"),
            GaugeDef("TOTAL SCORE",      "score",      "score_max",  "#f0c040", "{v:,}"),
            GaugeDef("STATES/PROVS",     "worked",      63,           "#f0c040", "{v}"),  # 48+DC+14CA=63
            GaugeDef("BAND MULTS",       "band_mults",  378,          "#2ed573", "{v}"),  # 63×6 bands
            GaugeDef("% STATES",         "pct",         100.0,        "#8b949e", "{v:.1f}%"),
        ]

    # ── Cabrillo ──────────────────────────────────────────────────────────────

    def cabrillo_contest(self) -> str:
        return "ARRL-DX-CW"


def register() -> ARRLDXDXPlugin:
    return ARRLDXDXPlugin()
