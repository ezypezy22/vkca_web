"""
plugins/iota.py  —  RSGB IOTA Contest plugin for VK Contest Analyzer
=====================================================================
Contest:   RSGB IOTA Contest
Period:    Last full weekend of July, 1200 UTC Sat to 1200 UTC Sun (24h)
Rules:     https://www.rsgbcc.org/hf/rules/2026/riota.shtml

Validated against: IOTA_2020_VK4SN.s3db (VK4SN, Island Stn OC-001)

N1MM+ field mapping (confirmed from real log)
---------------------------------------------
  The received IOTA reference is stored in the N1MM+ "Sect" column,
  which the main loader maps to qso["mult1"].  Format in the DB is
  "OC001" (no hyphen) — this plugin normalises to "OC-001" for display.

Scoring (Rules 6a / 6b — 2026 edition)
---------------------------------------
  Own = Island Station (OWN_IOTA set):
    Contact with non-island (world) station  →  5 pts
    Contact with island station, same ref    →  5 pts
    Contact with island station, other ref   → 15 pts

  Own = World Station (OWN_IOTA = None):
    Contact with non-island (world) station  →  2 pts
    Contact with any island station          → 15 pts

  N1MM+ already stores the correct per-QSO Points value, so
  recalc_pts() only normalises the mult1 format; it trusts N1MM+'s
  points when OWN_IOTA matches the contest SentExchange.

Multipliers (Rule 6c)
---------------------
  Each unique IOTA reference worked on each band × mode group.
  CW and SSB/Digital are counted separately on every band.
  Mult key: "<REF>/<BAND>/<MODE_GROUP>"  e.g. "OC-001/40M/CW"

  Total score = total QSO points × total unique mult keys

Own-station configuration
-------------------------
  Edit OWN_IOTA near the bottom of this file:
      OWN_IOTA = "OC-001"   # Island Station — use your own IOTA ref
      OWN_IOTA = None        # World Station
"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

from plugins.base import ContestPlugin, SessionConfig, MultResult, GaugeDef

# ══════════════════════════════════════════════════════════════════════════════
# Configuration — edit this before loading if you are an Island Station
# ══════════════════════════════════════════════════════════════════════════════

OWN_IOTA: Optional[str] = None   # e.g. "OC-001"  ← set for Island Station

# ══════════════════════════════════════════════════════════════════════════════
# Internal constants
# ══════════════════════════════════════════════════════════════════════════════

IOTA_BANDS = {"160M", "80M", "40M", "20M", "15M", "10M"}

# Matches both "OC001" (N1MM+ Sect format) and "OC-001" (display format)
_REF_RE = re.compile(r'\b(AF|AN|AS|EU|NA|OC|SA)-?(\d{3})\b', re.IGNORECASE)

# N1MM+ ContestName values this plugin claims
_NAMES = {"IOTA", "IOTA CONTEST", "RSGB IOTA", "IOTA-CONTEST", "RSGB-IOTA"}


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _normalise_ref(raw: str) -> str:
    """
    Convert N1MM+ Sect value to display format.
    "OC001" → "OC-001",  "OC-001" → "OC-001",  "" → ""
    """
    if not raw:
        return ""
    m = _REF_RE.match(raw.strip())
    return f"{m.group(1).upper()}-{m.group(2)}" if m else ""


def _band(b) -> str:
    """Normalise band: 7.0 (MHz float) or "40M" string → "40M"."""
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


def _mode_key(mode: str) -> str:
    return "CW" if str(mode).upper() == "CW" else "SSB"


def _iota_saturday(year: int) -> date:
    """Last Saturday of July for *year*."""
    d = date(year, 7, 31)
    while d.weekday() != 5:
        d = date(year, 7, d.day - 1)
    return d


# ══════════════════════════════════════════════════════════════════════════════
# Plugin
# ══════════════════════════════════════════════════════════════════════════════

class IOTAPlugin(ContestPlugin):
    """RSGB IOTA Contest — scoring, multipliers, analytics."""

    preferred_exchange_columns = [
        "Sect", "sect",                          # confirmed field in N1MM+ DB
        "Comment", "comment",
        "SRX_STRING", "srx_string",
        "Exchange1", "exchange1",
        "RcvExch", "rcvexch",
    ]

    def __init__(self, own_iota: Optional[str] = None):
        raw = own_iota or OWN_IOTA
        self._own_iota: Optional[str] = _normalise_ref(raw) if raw else None

    # ── Identity ──────────────────────────────────────────────────────────────

    def identify(self, contest_name: str) -> bool:
        """Return True for any IOTA ContestName variant."""
        cn = contest_name.strip().upper()
        if cn in _NAMES:
            return True
        # web/server.py's /api/load re-resolves the plugin from its OWN
        # display_name string (round-tripped from an earlier /api/scan),
        # not just the raw N1MM ContestName. display_name is dynamic
        # ("RSGB IOTA Contest [OC-001]" / "... [World Stn]"), so a fixed
        # _NAMES set can't enumerate every variant — fall back to a broad
        # substring match instead.
        return "IOTA" in cn

    @property
    def display_name(self) -> str:
        tag = f" [{self._own_iota}]" if self._own_iota else " [World Stn]"
        return f"RSGB IOTA Contest{tag}"

    # ── Multiplier label ──────────────────────────────────────────────────────

    def mult_label(self) -> str:
        return "IOTA Ref"

    # ── Multiplier list ───────────────────────────────────────────────────────
    # Empty → loader passes raw data through; we decode in recalc_pts / mult_of_qso

    def mult_list(self) -> list:
        return []

    def mult_of_qso(self, q: dict) -> Optional[str]:
        return _normalise_ref(str(q.get("mult1") or "")) or None

    def region_of_mult(self, m: str) -> Optional[str]:
        """Continent prefix of a ref like "OC-001" → "OC"."""
        if not m:
            return None
        parts = m.split("-")
        return parts[0].upper() if len(parts) == 2 else None

    def region_list(self) -> list:
        return ["AF", "AN", "AS", "EU", "NA", "OC", "SA"]

    # ── Session config ────────────────────────────────────────────────────────

    def session_config(self) -> SessionConfig:
        return SessionConfig(
            duration_mins=60,
            num_sessions=24,
            label_prefix="Hr ",
            start_hour=12,    # 1200 UTC Saturday
        )

    def contest_saturday(self, year: int) -> date:
        return _iota_saturday(year)

    # ── Per-QSO points ────────────────────────────────────────────────────────

    def recalc_pts(self, qsos: list) -> None:
        """
        Normalise mult1 to "XX-NNN" display format and ensure per-QSO points
        are correct.

        N1MM+ sets Points=0 for dupes (there is no explicit Dupe column in the
        IOTA s3db).  We treat any QSO whose pts is 0 AND whose dupe flag is not
        already set as a dupe, matching N1MM+'s behaviour.

        For Cabrillo imports where pts may be None/absent we derive points from
        the scoring table.
        """
        seen: set = set()   # (call, band, mode_key) for dupe detection

        for q in qsos:
            # ── Band validation ───────────────────────────────────────────────
            b = _band(q.get("band") or q.get("freq") or "")
            if b not in IOTA_BANDS:
                q["pts"]  = 0
                q["dupe"] = 1
                continue

            # ── Normalise the IOTA reference (Sect column → "XX-NNN") ────────
            raw_ref    = str(q.get("mult1") or "")
            normalised = _normalise_ref(raw_ref)
            q["mult1"] = normalised

            # ── Dupe detection ────────────────────────────────────────────────
            # Strategy (in priority order):
            #   1. dupe flag already set by loader → honour it
            #   2. N1MM+ wrote Points=0 explicitly (its dupe marker) → dupe
            #   3. We've already seen this (call, band, mode) → dupe
            mk  = _mode_key(q.get("mode") or "")
            key = (str(q.get("call") or "").upper(), b, mk)

            raw_pts = q.get("pts")
            already_dupe = bool(q.get("dupe"))
            n1mm_dupe    = (raw_pts == 0 and not already_dupe)
            our_dupe     = (not already_dupe and not n1mm_dupe and key in seen)

            if already_dupe or n1mm_dupe or our_dupe:
                q["pts"]  = 0
                q["dupe"] = 1
                continue

            seen.add(key)

            # ── Points ────────────────────────────────────────────────────────
            # Trust N1MM+ when it gave us a non-zero value.
            # Fall back to _derive_pts for Cabrillo / manual imports where
            # pts is None or missing.
            if raw_pts:
                q["pts"] = int(raw_pts)
            else:
                q["pts"] = self._derive_pts(q)

    def _derive_pts(self, q: dict) -> int:
        """Derive points for a QSO when N1MM+ hasn't set them."""
        own  = "ISLAND" if self._own_iota else "WORLD"
        ref  = q.get("mult1", "")

        if not ref:                         # contacted station is world
            return 2 if own == "WORLD" else 5
        if own == "WORLD":
            return 15
        # Own is island
        if ref == self._own_iota:
            return 5                        # same island
        return 15                           # different island

    # ── Score ─────────────────────────────────────────────────────────────────

    def score(self, qsos: list) -> int:
        pts = sum(q.get("pts", 0) for q in qsos if not q.get("dupe"))
        mr  = self.multipliers(qsos)
        total_mults = len(mr.primary_mults) + len(mr.secondary_mults)
        return pts * total_mults if total_mults else pts

    # ── Multipliers ───────────────────────────────────────────────────────────

    def multipliers(self, qsos: list) -> MultResult:
        """
        Count unique IOTA refs per band per mode group (CW vs SSB).
        Uses is_mult1 flag when present (N1MM+ sets it); falls back to
        presence of a ref in mult1.
        Key format: "OC-001/40M/CW"
        """
        primary: set = set()

        for q in qsos:
            if q.get("dupe"):
                continue
            ref = _normalise_ref(str(q.get("mult1") or ""))
            if not ref:
                continue
            # Trust N1MM+ is_mult1 flag when it exists; otherwise count all refs
            is_m1 = q.get("is_mult1")
            if is_m1 is not None and is_m1 != 1:
                continue
            b  = _band(q.get("band") or q.get("freq") or "")
            mk = _mode_key(q.get("mode") or "")
            primary.add(f"{ref}/{b}/{mk}")

        return MultResult(
            primary_mults=primary,
            secondary_mults=set(),
            primary_label="IOTA Refs",
            secondary_label="",
        )

    # ── Worked helpers ────────────────────────────────────────────────────────

    def worked_primary_mults(self, qsos: list) -> set:
        """Return set of unique normalised IOTA refs worked (not band/mode specific)."""
        worked = set()
        for q in qsos:
            if q.get("dupe") or not q.get("pts"):
                continue
            ref = _normalise_ref(str(q.get("mult1") or ""))
            if ref:
                worked.add(ref)
        return worked

    # ── Region heat map ───────────────────────────────────────────────────────
    # The base class builds region_heat from mult_list() which we return as [].
    # We override to build it dynamically from the QSOs instead.

    def mults_by_region(self, qsos: list) -> dict:
        """Group unique worked IOTA refs by continent prefix."""
        result = {}
        for cont in self.region_list():
            result[cont] = {"worked": [], "missing": []}
        for q in qsos:
            if q.get("dupe") or not q.get("pts"):
                continue
            ref  = _normalise_ref(str(q.get("mult1") or ""))
            cont = self.region_of_mult(ref)
            if cont and ref and cont in result:
                if ref not in result[cont]["worked"]:
                    result[cont]["worked"].append(ref)
        return result

    def region_heat(self, qsos: list) -> list:
        """
        Return per-continent stats for the region heat panel.
        Each entry: {state, qsos, worked, total, pct}
        'total' is the number of unique refs worked in that continent
        (there's no fixed total for IOTA so we use worked as total,
        giving 100% for all — the bar height conveys QSO volume instead).
        """
        from collections import defaultdict
        cont_qsos   = defaultdict(int)
        cont_worked = defaultdict(set)

        for q in qsos:
            if q.get("dupe") or not q.get("pts"):
                continue
            ref  = _normalise_ref(str(q.get("mult1") or ""))
            cont = self.region_of_mult(ref)
            if cont:
                cont_qsos[cont]   += 1
                if ref:
                    cont_worked[cont].add(ref)

        result = []
        for cont in self.region_list():
            w = len(cont_worked[cont])
            q = cont_qsos[cont]
            result.append({
                "state":  cont,
                "qsos":   q,
                "worked": w,
                "total":  max(w, 1),   # avoid div-by-zero; 100% when any worked
                "pct":    100.0 if w else 0.0,
            })
        return sorted(result, key=lambda x: x["qsos"], reverse=True)

    # ── Band efficiency ───────────────────────────────────────────────────────
    # Base class checks q["mult1"] in ml_set — always False when mult_list()=[].
    # We override to count refs directly.

    def band_efficiency(self, qsos: list) -> list:
        from collections import defaultdict
        band_qsos  = defaultdict(int)
        band_pts   = defaultdict(int)
        band_mults = defaultdict(set)
        for q in qsos:
            if q.get("dupe"):
                continue
            b   = _band(q.get("band") or q.get("freq") or "?")
            ref = _normalise_ref(str(q.get("mult1") or ""))
            band_qsos[b] += 1
            band_pts[b]  += q.get("pts", 0) or 0
            if ref:
                band_mults[b].add(ref)

        time_stats = self._band_time_stats(
            qsos, key_fn=lambda q: _band(q.get("band") or q.get("freq") or "?"))
        result = []
        for b in band_qsos:
            qn = band_qsos[b]
            mn = len(band_mults[b])
            ts = time_stats.get(b, {"best_hour_rate": 0, "last_qso_utc": None})
            result.append({
                "band":       b,
                "qsos":       qn,
                "pts":        band_pts[b],
                "new_shires": mn,
                "efficiency": mn / qn if qn else 0,
                **ts,
            })
        return sorted(result, key=lambda x: x["efficiency"], reverse=True)

    # ── Sparkline mults ───────────────────────────────────────────────────────
    # Base class uses is_mult1 flag which N1MM+ sets correctly for IOTA,
    # but we also need to handle Cabrillo imports where the flag is absent.

    def sparkline_mults(self, q: dict, seen: set) -> int:
        if q.get("dupe"):
            return 0
        ref = _normalise_ref(str(q.get("mult1") or ""))
        if not ref:
            return 0
        b  = _band(q.get("band") or q.get("freq") or "")
        mk = _mode_key(q.get("mode") or "")
        key = (ref, b, mk)
        # Trust is_mult1 when present
        is_m1 = q.get("is_mult1")
        if is_m1 is not None:
            if is_m1 == 1 and key not in seen:
                seen.add(key)
                return 1
            return 0
        # Fallback: count first occurrence per ref/band/mode
        if key not in seen:
            seen.add(key)
            return 1
        return 0

    # ── UI hints ──────────────────────────────────────────────────────────────

    def has_missing_tab(self) -> bool:
        return False   # open-ended mult list — any ref can be activated

    def band_list(self) -> list:
        # IOTA is 160-10m — no WARC bands (30/17/12m).
        return ["160M", "80M", "40M", "20M", "15M", "10M"]

    def gauge_defs(self, data: dict, total_mults: int) -> list:
        # Max values — use live data when available, sensible defaults otherwise
        island_max = max(data.get("iota_island_qsos", 0), 10)
        cont_max   = 7   # 7 IOTA continents total (AF AN AS EU NA OC SA)
        return [
            GaugeDef("TOTAL QSOs",    "total",            "qso_max",          "#00d4aa", "{v}"),
            GaugeDef("VALID QSOs",    "valid",            "qso_max",          "#2ed573", "{v}"),
            GaugeDef("TOTAL SCORE",   "score",            "score_max",        "#f0c040", "{v:,}"),
            GaugeDef("IOTA REFS",     "worked",           total_mults,        "#f0c040", "{v}"),
            GaugeDef("BAND MULTS",    "band_mults",       total_mults,        "#2ed573", "{v}"),
            GaugeDef("ISLAND QSOs",   "iota_island_qsos", island_max,         "#ff6b35", "{v}"),
        ]

    def post_snapshot(self, snap: dict, qsos: list) -> None:
        """
        Inject IOTA-specific metrics into the snapshot dict so gauge_defs
        and the overview panels can reference them.

        Keys added:
          iota_island_qsos  — QSOs with island stations (have an IOTA ref)
          iota_world_qsos   — QSOs with world stations (no IOTA ref)
          iota_cont_cnt     — distinct IOTA continents contacted
          iota_pts_per_qso  — average points per valid QSO
        """
        island_qsos = 0
        world_qsos  = 0
        conts: set  = set()
        total_pts   = 0
        valid_count = 0

        for q in qsos:
            if q.get("dupe"):
                continue
            valid_count += 1
            total_pts   += q.get("pts", 0)
            ref  = _normalise_ref(str(q.get("mult1") or ""))
            cont = self.region_of_mult(ref) if ref else None
            if ref:
                island_qsos += 1
                if cont:
                    conts.add(cont)
            else:
                world_qsos += 1

        snap["iota_island_qsos"] = island_qsos
        snap["iota_world_qsos"]  = world_qsos
        snap["iota_cont_cnt"]    = len(conts)
        snap["iota_pts_per_qso"] = (total_pts / valid_count) if valid_count else 0.0


# ══════════════════════════════════════════════════════════════════════════════
# Module-level instance — loader calls register() if defined, otherwise it
# instantiates any concrete ContestPlugin subclass it finds in the module.
# ══════════════════════════════════════════════════════════════════════════════

    # ── Cabrillo ──────────────────────────────────────────────────────────────

    def cabrillo_contest(self) -> str:
        return "IOTA"


# ══════════════════════════════════════════════════════════════════════════════
# Module-level instance — loader calls register() if defined, otherwise it
# instantiates any concrete ContestPlugin subclass it finds in the module.
# ══════════════════════════════════════════════════════════════════════════════

def register() -> IOTAPlugin:
    return IOTAPlugin()
