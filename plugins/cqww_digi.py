"""
plugins/cqww_digi.py
─────────────────────
CQ World Wide DIGI Contest plugin for the VK Contest Analyzer.

N1MM+ internal contest name: "WWDIGI" (dropdown label "WW Digi FT8/FT4
Contest"). ContestName strings seen in the wild: "CQ-WW-DIGI", "CQWWDIGI",
"WW-DIGI", "WWDIGI". This is the FT4/FT8 successor to the old CQ/RJ WW RTTY
contest and uses a COMPLETELY DIFFERENT scoring system (grid-based, not
zone/country-based) — deliberately not matched by this plugin's identify()
so a legacy CQWWRTTY log is never misclassified as WWDIGI.

Scoring (per rules at https://ww-digi.com/rules/):
  • Bands: 1.8, 3.5, 7, 14, 21, 28 MHz only (160/80/40/20/15/10m — no WARC,
    no 6m).
  • QSO points: 1 point, plus 1 additional point for each 3000 km between
    the two stations' grid-square centers (e.g. 5541 km apart = 2 pts).
  • Multiplier: one (1) for each different 2-character Grid FIELD (the
    first two characters of the worked station's 4-character Maidenhead
    exchange, e.g. "OI16" → field "OI") worked on EACH band — i.e. grid
    fields stack per band, same shape as CQWW's country/zone mults.
  • Final score = total QSO points × total grid-field-band multipliers.

N1MM stores:
  Exchange1 / Mult1 → the exchanged 4-character grid square (we take the
                       first 2 characters as the scoring "grid field")
  IsMultiplier1      → 1 = new grid field on this band
  Points             → QSO point value (already includes the distance
                        calculation — see recalc_pts() below)

Session structure: single continuous 24-hour contest, Saturday 12:00 UTC –
Sunday 11:59:59 UTC (NOT the 48-hour Saturday-00:00 window used by CQWW
CW/SSB/WPX) — modelled as 2 × 12-hour chunks for the generic rate/session
machinery, with uses_block_structure() = False so the overview shows
whole-contest elapsed/remaining time rather than a per-block countdown.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Optional

from plugins.base import (
    ContestPlugin,
    GaugeDef,
    MultResult,
    SessionConfig,
    ACCENT,
    ACCENT3,
    GREEN,
    MUTED,
)


# ── WW DIGI band set (display order, low → high) ───────────────────────────────
# 160/80/40/20/15/10m only — no WARC, no 6m (unlike ARRL Digital).
_WWDIGI_BAND_ORDER: list[str] = ["160M", "80M", "40M", "20M", "15M", "10M"]


def _peak_rate_per_hour(times: list, window_minutes: int = 60) -> int:
    """
    Best sliding-window QSO rate, expressed as QSOs/hour, matching N1MM's
    "Max Rates" report (Window menu) for the given window size.
    """
    if not times:
        return 0
    window = timedelta(minutes=window_minutes)
    n = len(times)
    best = 0
    j = 0
    for i in range(n):
        if j < i:
            j = i
        while j < n and times[j] - times[i] <= window:
            j += 1
        count = j - i
        if count > best:
            best = count
    return round(best * 60.0 / window_minutes)


def _grid_field(raw: Optional[str]) -> Optional[str]:
    """First two letters of a Maidenhead grid square, upper-cased — the
    "grid field" that WW DIGI counts as a multiplier. Returns None for
    anything that doesn't look like a grid (need >=2 alpha characters)."""
    if not raw:
        return None
    v = raw.strip().upper()
    if len(v) >= 2 and v[0].isalpha() and v[1].isalpha():
        return v[:2]
    return None


# ═════════════════════════════════════════════════════════════════════════════
# Plugin
# ═════════════════════════════════════════════════════════════════════════════

class CQWWDigiPlugin(ContestPlugin):
    """
    CQ World Wide DIGI Contest (FT4/FT8).

    Multiplier : 2-character Grid Field, counted once PER BAND (stacks
                 across bands, same shape as CQWW's country/zone mults).
    Exchange   : 4-character Maidenhead grid square.
    """

    # ── Identity ──────────────────────────────────────────────────────────────

    def identify(self, contest_name: str) -> bool:
        cn = contest_name.upper().replace(" ", "").replace("_", "").replace("-", "")
        return "WWDIGI" in cn

    @property
    def display_name(self) -> str:
        return "CQ WW DIGI"

    # ── Session / block structure ─────────────────────────────────────────────

    def session_config(self) -> SessionConfig:
        # 24 h total; internally modelled as 2 × 12-hour chunks purely so the
        # generic rate/session machinery has something to iterate over — see
        # uses_block_structure(). Starts Saturday 12:00 UTC (NOT 00:00 like
        # CQWW CW/SSB/WPX).
        return SessionConfig(
            duration_mins=720,     # 12 hours per chunk
            num_sessions=2,
            label_prefix="B",
            start_hour=12,         # Saturday 12:00 UTC
        )

    def uses_block_structure(self) -> bool:
        """
        WW DIGI is a single continuous 24-hour contest with no "block"
        subdivision (same shape as CQWW CW/SSB). The overview's time panel
        should show whole-contest start/elapsed/remaining instead of a
        per-block countdown.
        """
        return False

    # ── Multiplier contract ───────────────────────────────────────────────────

    def mult_list(self) -> list:
        """
        Grid fields are technically enumerable (18×18 = 324 possible
        two-letter fields), but — same call as CQWW's open-ended country
        list — we treat them as free-form here rather than building a
        fixed lookup table, since a "missing grid fields" tab isn't
        operationally useful (most fields are over open ocean).
        """
        return []

    def mult_label(self) -> str:
        return "Grid Field"

    def mult_of_qso(self, q: dict) -> Optional[str]:
        """Return the 2-character grid field derived from the exchanged
        grid square stored as mult1."""
        return _grid_field(q.get("mult1"))

    # ── Scoring ───────────────────────────────────────────────────────────────

    def recalc_pts(self, qsos: list) -> None:
        """
        Deliberately a no-op: trust N1MM's stored Points unconditionally.

        WW DIGI's QSO-point formula (1 + 1 per 3000 km between grid-square
        centers) requires knowing both stations' precise grid centers —
        N1MM already computes this correctly per QSO, and there is nothing
        for this method to safely re-derive without duplicating a full
        Maidenhead distance calculation this app doesn't otherwise need.

        Same reasoning as plugins/wpx_rtty.py's recalc_pts().
        """
        return

    def score(self, qsos: list) -> int:
        """Total QSO points × total unique (grid field, band) pairs."""
        pts   = sum(q["pts"] for q in qsos if not q["dupe"])
        mr    = self.multipliers(qsos)
        mults = len(mr.primary_mults)
        return pts * mults if mults else pts

    # ── "Next QSO" value estimator (Overview tab) ─────────────────────────────

    def qso_value_estimate(self, qsos: list) -> dict:
        """
        Same shape as CQWW/WPX RTTY's estimator: Score = TotalPoints ×
        TotalMults, so a new QSO worth ``p`` raw points that brings ``dm``
        brand-new grid-field-band multipliers changes the score by
        ``p * (M + dm) + P * dm``.
        """
        valid     = [q for q in qsos if not q["dupe"]]
        total_pts = sum(q["pts"] for q in valid)

        mr          = self.multipliers(qsos)
        total_mults = len(mr.primary_mults)
        overall_avg = (total_pts / len(valid)) if valid else 0.0

        band_pts: dict = defaultdict(list)
        for q in valid:
            b = (q.get("band") or "?").upper()
            band_pts[b].append(q["pts"])

        def delta(p: float, dm: int) -> float:
            return p * (total_mults + dm) + total_pts * dm

        band_order = list(_WWDIGI_BAND_ORDER)
        for b in band_pts:
            if b not in band_order:
                band_order.append(b)

        bands: dict = {}
        for band in band_order:
            pts_list = band_pts.get(band, [])
            n        = len(pts_list)
            avg_p    = (sum(pts_list) / n) if n else overall_avg
            bands[band] = {
                "qsos":     n,
                "avg_pts":  avg_p,
                "no_mult":  delta(avg_p, 0),
                "one_mult": delta(avg_p, 1),
            }

        return {
            "total_pts":   total_pts,
            "total_mults": total_mults,
            "overall_avg": overall_avg,
            "bands":       bands,
            "band_order":  band_order,
            "scenarios":   ["no_mult", "one_mult"],
            "scenario_labels": {
                "no_mult":  "+QSO",
                "one_mult": "+QSO +1 grid field",
            },
        }

    def multipliers(self, qsos: list) -> MultResult:
        """
        Primary mults: unique (grid field, band) pairs. Uses N1MM's
        IsMultiplier1 flag when available — the authoritative "new mult on
        this band" marker — falling back to collecting all non-dupe
        (grid field, band) pairs when the flag is absent.

        secondary_mults is always empty — WW DIGI has only one multiplier
        type.
        """
        fields: set = set()

        has_m1 = any(q.get("is_mult1") is not None for q in qsos)

        for q in qsos:
            if q["dupe"]:
                continue
            band = q.get("band") or "?"
            gf   = _grid_field(q.get("mult1"))
            if not gf:
                continue
            if has_m1:
                if q.get("is_mult1") == 1:
                    fields.add((gf, band))
            else:
                fields.add((gf, band))

        return MultResult(
            primary_mults=fields,
            secondary_mults=set(),
            primary_label="Grid Fields",
            secondary_label="",
        )

    # ── Exchange columns hint ─────────────────────────────────────────────────

    @property
    def preferred_exchange_columns(self):
        # N1MM stores the exchanged 4-character grid square in Exchange1
        # for WW DIGI (a grid-square contest, not a serial-number one), so
        # the base loader's default heuristic already lands on the right
        # column — declared explicitly here for clarity and to pin the
        # priority order.
        return ["Exchange1", "exchange1", "Mult1", "mult1"]

    # ── UI hints ──────────────────────────────────────────────────────────────

    def has_missing_tab(self) -> bool:
        # No fixed mult list — "missing grid fields" tab doesn't make sense
        return False

    def band_list(self) -> list:
        return list(_WWDIGI_BAND_ORDER)

    def has_region_heat(self) -> bool:
        return False

    def has_state_bars(self) -> bool:
        return False

    def post_snapshot(self, snap: dict, qsos: list) -> None:
        """
        Called by compute_snapshot() to inject WW DIGI-correct display
        values, following the same pattern as wpx_rtty.py's post_snapshot()
        (open-ended single-mult-type contest: mult_list() is empty, so the
        base formula's worked/band_mults/pct all need overriding).
        """
        mr         = self.multipliers(qsos)
        field_cnt  = len(mr.primary_mults)
        total_pts  = sum(q["pts"] for q in qsos if not q["dupe"])
        valid      = snap.get("valid", 0)

        snap["worked"]     = field_cnt
        snap["band_mults"] = field_cnt
        snap["zone_cnt"]   = 0
        snap["pct"]        = 0.0

        snap["pts_per_qso"]   = (total_pts / valid) if valid else 0.0
        snap["qsos_per_mult"] = (valid / field_cnt) if field_cnt else 0.0

        valid_times = sorted(q["time"] for q in qsos if not q["dupe"])
        peak_rate   = _peak_rate_per_hour(valid_times, window_minutes=60)
        snap["peak_rate"] = peak_rate

        import math
        snap["fld_max"]       = max(int(math.ceil(field_cnt * 1.25 / 50) * 50), 50)
        snap["peak_rate_max"] = max(int(math.ceil(peak_rate * 1.25 / 50) * 50), 50)

    def gauge_defs(self, data: dict, total_mults: int) -> list:
        fld_max       = data.get("fld_max", max(data.get("worked", 1), 50))
        peak_rate_max = data.get("peak_rate_max", 50)
        return [
            GaugeDef("TOTAL QSOs",  "total",          "qso_max",   ACCENT(),  "{v}",
                     tooltip=(
                         "TOTAL QSOs\n"
                         "Every logged contact including dupes.\n"
                         "WW DIGI has no 0-point contacts — every valid QSO\n"
                         "scores at least 1 point."
                     )),
            GaugeDef("VALID QSOs",  "valid",           "qso_max",   GREEN(),   "{v}",
                     tooltip=(
                         "VALID QSOs\n"
                         "Non-dupe contacts that count toward your score."
                     )),
            GaugeDef("TOTAL SCORE", "score",           "score_max", ACCENT3(), "{v:,}",
                     tooltip=(
                         "TOTAL SCORE\n"
                         "Total QSO points × unique grid-field-band multipliers.\n"
                         "Formula: Σ pts  ×  (grid fields × bands worked)\n"
                         "Matches N1MM's running score."
                     )),
            GaugeDef("GRID FIELDS", "worked",          fld_max,     ACCENT3(), "{v}",
                     tooltip=(
                         "GRID FIELDS (band pairs)\n"
                         "Unique 2-character Maidenhead grid fields worked,\n"
                         "counted once per band (e.g. OI on 20m and OI on\n"
                         "40m = 2 multipliers).\n"
                         "Gauge ceiling auto-scales to 125% of current count."
                     )),
            GaugeDef("PTS / QSO",   "pts_per_qso",     3.0,         MUTED(),   "{v:.2f}",
                     tooltip=(
                         "AVERAGE POINTS PER QSO\n"
                         "Total QSO points ÷ valid QSOs.\n"
                         "Scoring: 1 pt + 1 pt per 3000 km between grid-square\n"
                         "centers — long DX contacts are worth more."
                     )),
            GaugeDef("QSOs / MULT", "qsos_per_mult",   10.0,        MUTED(),   "{v:.1f}",
                     tooltip=(
                         "QSOs PER MULTIPLIER\n"
                         "Valid QSOs ÷ unique grid-field-band multipliers.\n"
                         "Lower = better: each grid field is earning you more\n"
                         "QSO points relative to your mult count."
                     )),
            GaugeDef("PEAK RATE/HR", "peak_rate",      peak_rate_max, GREEN(), "{v}",
                     tooltip=(
                         "PEAK RATE (QSOs/hr)\n"
                         "Best 60-minute rolling QSO rate across the contest.\n"
                         "Matches N1MM's 'Max Rates' (Window menu) for a\n"
                         "60-minute window."
                     )),
        ]

    # ── Multiplier helpers (overrides) ────────────────────────────────────────

    def worked_primary_mults(self, qsos: list) -> set:
        """Unique grid fields worked (any band)."""
        return {gf for q in qsos if not q["dupe"]
                for gf in [_grid_field(q.get("mult1"))] if gf}

    def worked_primary_band_mults(self, qsos: list) -> set:
        """Unique (grid field, band, mode) tuples — matches multipliers()'s
        scoring identity, unlike the base class default which would use the
        raw (un-truncated) exchange value."""
        result: set = set()
        for q in qsos:
            if q["dupe"]:
                continue
            gf = _grid_field(q.get("mult1"))
            if gf:
                result.add((gf, q.get("band", "?"), q.get("mode", "?")))
        return result

    def worked_secondary_band_mults(self, qsos: list) -> set:
        """WW DIGI has no secondary multiplier type."""
        return set()

    def missing_primary_mults(self, qsos: list) -> list:
        """Not applicable for WW DIGI (open-ended grid-field treatment)."""
        return []

    def sparkline_mults(self, q: dict, seen: set) -> int:
        gf  = _grid_field(q.get("mult1"))
        key = (gf, q.get("band"), q.get("mode"))
        if gf and key not in seen:
            seen.add(key)
            return 1
        return 0

    def running_score_for_sparkline(self, qsos_up_to_hour: list) -> int:
        """
        Calculate score for the sparkline using the same logic as
        multipliers() / score(), so the final sparkline point matches the
        TOTAL SCORE gauge exactly.
        """
        pts = sum(q["pts"] for q in qsos_up_to_hour if not q["dupe"])

        fields: set = set()
        has_m1 = any(q.get("is_mult1") is not None for q in qsos_up_to_hour)
        for q in qsos_up_to_hour:
            if q["dupe"]:
                continue
            band = q.get("band") or "?"
            gf   = _grid_field(q.get("mult1"))
            if not gf:
                continue
            if has_m1:
                if q.get("is_mult1") == 1:
                    fields.add((gf, band))
            else:
                fields.add((gf, band))

        mults = len(fields)
        return pts * mults if mults else pts

    # ── Band efficiency override ──────────────────────────────────────────────

    def band_efficiency(self, qsos: list) -> list:
        """Per-band breakdown: QSOs, distinct grid fields, efficiency."""
        band_qsos   = defaultdict(int)
        band_fields = defaultdict(set)

        for q in qsos:
            if q["dupe"]:
                continue
            b  = q.get("band") or "?"
            gf = _grid_field(q.get("mult1"))
            band_qsos[b] += 1
            if gf:
                band_fields[b].add(gf)

        result = []
        for b in band_qsos:
            qn = band_qsos[b]
            fn = len(band_fields[b])
            result.append({
                "band":          b,
                "qsos":          qn,
                "new_shires":    fn,   # reuses the generic key name
                "new_fields":    fn,
                "efficiency":    fn / qn if qn else 0,
            })
        return sorted(result, key=lambda x: x["efficiency"], reverse=True)


def register() -> CQWWDigiPlugin:
    return CQWWDigiPlugin()
