"""
plugins/arrl_digital.py
────────────────────────
ARRL International Digital Contest plugin for the VK Contest Analyzer.

N1MM+ internal contest name: "ARRLIDC" (dropdown label "ARRL International
Digital Contest"). ContestName strings seen in the wild: "ARRL-DIGI",
"ARRLIDC", "ARRL-INTL-DIGITAL", "ARRLDIGITAL" and common variants.

Scoring (per rules at https://contests.arrl.org/ContestRules/Digital-Rules.pdf
and https://contests.arrl.org/dig/):
  • Bands: 160, 80, 40, 20, 15, 10 and 6 meters. A station may be worked
    once per band, regardless of mode.
  • Exchange: 4-character Maidenhead grid square.
  • QSO points: 1 point, plus 1 additional point for each 500 km between
    the two stations' 4-character grid-square centers, rounded UP to the
    next whole number (minimum 1 distance point if under 500 km).
      e.g. 1565 km apart → 1 + ceil(1565/500) = 1 + 4 = 5 points.
  • Multiplier: NONE. This contest does not use the traditional
    "points × multipliers" formula that almost every other contest this
    app supports uses — final score is simply the SUM of QSO points.
    Grid squares worked are tracked here purely as an informational stat
    (see gauge_defs()), not as a scoring multiplier.

N1MM stores:
  Exchange1 / Mult1 → the exchanged 4-character grid square
  Points            → QSO point value (already includes the distance
                       calculation — see recalc_pts() below)

Session structure: single continuous 30-hour window, Saturday 18:00 UTC –
Sunday 23:59 UTC (Single Op may operate at most 24 of those 30 hours;
Multi-Op may operate the full window) — modelled as 5 × 6-hour chunks for
the generic rate/session machinery, with uses_block_structure() = False so
the overview shows whole-contest elapsed/remaining time rather than a
per-block countdown.
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


# ── ARRL Digital band set (display order, low → high) ──────────────────────────
# 160/80/40/20/15/10/6m — includes 6m (unlike WW DIGI), no WARC bands.
_ARRLDIGI_BAND_ORDER: list[str] = ["160M", "80M", "40M", "20M", "15M", "10M", "6M"]


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


def _grid_square(raw: Optional[str]) -> Optional[str]:
    """First four characters of a Maidenhead grid locator, upper-cased —
    the exchange this contest actually uses (not just the 2-char field)."""
    if not raw:
        return None
    v = raw.strip().upper()
    return v[:4] if len(v) >= 4 else None


# ═════════════════════════════════════════════════════════════════════════════
# Plugin
# ═════════════════════════════════════════════════════════════════════════════

class ARRLDigitalPlugin(ContestPlugin):
    """
    ARRL International Digital Contest.

    No scoring multiplier — final score is the sum of distance-based QSO
    points. Grid squares worked are shown as an informational stat only.
    Exchange: 4-character Maidenhead grid square.
    """

    # ── Identity ──────────────────────────────────────────────────────────────

    def identify(self, contest_name: str) -> bool:
        cn = contest_name.upper().replace(" ", "").replace("_", "").replace("-", "")
        # web/server.py's /api/load re-resolves the plugin from its OWN
        # display_name string (round-tripped from an earlier /api/scan),
        # not just the raw N1MM ContestName — "ARRL International Digital"
        # normalizes to "ARRLINTERNATIONALDIGITAL", which a narrow keyword
        # list wouldn't catch. Match on N1MM's real name OR any string
        # containing both "ARRL" and "DIGI" so the round trip always works.
        if "ARRLIDC" in cn:
            return True
        return "ARRL" in cn and "DIGI" in cn

    @property
    def display_name(self) -> str:
        return "ARRL International Digital"

    # ── Session / block structure ─────────────────────────────────────────────

    def session_config(self) -> SessionConfig:
        # 30 h total window; internally modelled as 5 × 6-hour chunks purely
        # so the generic rate/session machinery has something to iterate
        # over — see uses_block_structure(). Starts Saturday 18:00 UTC.
        return SessionConfig(
            duration_mins=360,     # 6 hours per chunk
            num_sessions=5,
            label_prefix="B",
            start_hour=18,         # Saturday 18:00 UTC
        )

    def uses_block_structure(self) -> bool:
        """
        The 30-hour window (24h max operating time for Single Op) has no
        scoring "block" subdivision — it's an off-time allowance, not a
        per-block reset like VK RD or Trans-Tasman. The overview's time
        panel should show whole-contest start/elapsed/remaining instead of
        a per-block countdown.
        """
        return False

    # ── Multiplier contract ───────────────────────────────────────────────────

    def mult_list(self) -> list:
        """
        No fixed list — see the module docstring: this contest has no
        scoring multiplier at all. Grid squares are open-ended and shown
        for information only.
        """
        return []

    def mult_label(self) -> str:
        return "Grid Square"

    def mult_of_qso(self, q: dict) -> Optional[str]:
        """Return the 4-character grid square stored as mult1 (informational
        only — does not affect score(), see module docstring)."""
        return _grid_square(q.get("mult1"))

    # ── Scoring ───────────────────────────────────────────────────────────────

    def recalc_pts(self, qsos: list) -> None:
        """
        Deliberately a no-op: trust N1MM's stored Points unconditionally.

        The distance-based QSO-point formula (1 + 1 per 500 km, rounded up)
        requires knowing both stations' precise grid-square centers — N1MM
        already computes this correctly per QSO. Same reasoning as
        plugins/wpx_rtty.py's and plugins/cqww_digi.py's recalc_pts().
        """
        return

    def score(self, qsos: list) -> int:
        """
        Final score = SUM of QSO points. Unlike almost every other contest
        this app supports, there is NO multiplier term — see the module
        docstring's "Multiplier: NONE" note, confirmed by the ARRL rules
        text ("final score equals the total QSO points").
        """
        return sum(q["pts"] for q in qsos if not q["dupe"])

    # ── "Next QSO" value estimator (Overview tab) ─────────────────────────────

    def qso_value_estimate(self, qsos: list) -> dict:
        """
        No multiplier term, so a new QSO's value is simply its own raw QSO
        points — no "M+dm" amplification like CQWW/WPX/WW DIGI. ``p`` is
        taken as the average QSO-point value already logged on that band,
        falling back to the overall average for bands with no QSOs yet.
        """
        valid     = [q for q in qsos if not q["dupe"]]
        total_pts = sum(q["pts"] for q in valid)
        overall_avg = (total_pts / len(valid)) if valid else 0.0

        band_pts: dict = defaultdict(list)
        for q in valid:
            b = (q.get("band") or "?").upper()
            band_pts[b].append(q["pts"])

        band_order = list(_ARRLDIGI_BAND_ORDER)
        for b in band_pts:
            if b not in band_order:
                band_order.append(b)

        bands: dict = {}
        for band in band_order:
            pts_list = band_pts.get(band, [])
            n        = len(pts_list)
            avg_p    = (sum(pts_list) / n) if n else overall_avg
            bands[band] = {
                "qsos":    n,
                "avg_pts": avg_p,
                "no_mult": avg_p,   # no multiplier term — QSO value is just its own points
            }

        return {
            "total_pts":   total_pts,
            "total_mults": 0,
            "overall_avg": overall_avg,
            "bands":       bands,
            "band_order":  band_order,
            "scenarios":   ["no_mult"],
            "scenario_labels": {
                "no_mult": "+QSO",
            },
        }

    def multipliers(self, qsos: list) -> MultResult:
        """
        Informational only — grid squares worked, per band. NOT consulted
        by score() (see module docstring). Collected directly from mult1
        values on non-dupe QSOs since ARRL Digital doesn't set
        IsMultiplier1/2 the way traditional-multiplier contests do.
        """
        grids: set = set()
        for q in qsos:
            if q["dupe"]:
                continue
            g = _grid_square(q.get("mult1"))
            if g:
                grids.add((g, q.get("band") or "?"))

        return MultResult(
            primary_mults=grids,
            secondary_mults=set(),
            primary_label="Grid Squares",
            secondary_label="",
        )

    # ── Exchange columns hint ─────────────────────────────────────────────────

    @property
    def preferred_exchange_columns(self):
        # N1MM stores the exchanged 4-character grid square in Exchange1
        # for ARRL Digital (a grid-square contest, not a serial-number
        # one), so the base loader's default heuristic already lands on
        # the right column — declared explicitly for clarity.
        return ["Exchange1", "exchange1", "Mult1", "mult1"]

    # ── UI hints ──────────────────────────────────────────────────────────────

    def has_missing_tab(self) -> bool:
        # No fixed mult list — "missing grid squares" tab doesn't make sense
        return False

    def band_list(self) -> list:
        return list(_ARRLDIGI_BAND_ORDER)

    def has_region_heat(self) -> bool:
        return False

    def has_state_bars(self) -> bool:
        return False

    def efficiency_label(self) -> str:
        # No multiplier concept here — band_efficiency() ranks by points
        # per QSO instead of mults per QSO (see vk_rd.py/hasprnt.py, the
        # other plugins that already do this for the same reason).
        return "pts/qso"

    def post_snapshot(self, snap: dict, qsos: list) -> None:
        """
        Called by compute_snapshot() to inject ARRL Digital-correct display
        values. mult_list() is empty so the base formula's worked/
        band_mults/pct all need overriding, same pattern as
        wpx_rtty.py/cqww_digi.py's post_snapshot() — except here "worked"
        is purely informational (grid squares), never a score multiplier.
        """
        mr        = self.multipliers(qsos)
        grid_cnt  = len(mr.primary_mults)
        total_pts = sum(q["pts"] for q in qsos if not q["dupe"])
        valid     = snap.get("valid", 0)

        snap["worked"]     = grid_cnt
        snap["band_mults"] = grid_cnt
        snap["zone_cnt"]   = 0
        snap["pct"]        = 0.0

        snap["pts_per_qso"] = (total_pts / valid) if valid else 0.0

        valid_times = sorted(q["time"] for q in qsos if not q["dupe"])
        peak_rate   = _peak_rate_per_hour(valid_times, window_minutes=60)
        snap["peak_rate"] = peak_rate

        import math
        snap["grid_max"]      = max(int(math.ceil(grid_cnt * 1.25 / 50) * 50), 50)
        snap["peak_rate_max"] = max(int(math.ceil(peak_rate * 1.25 / 50) * 50), 50)

    def gauge_defs(self, data: dict, total_mults: int) -> list:
        grid_max      = data.get("grid_max", max(data.get("worked", 1), 50))
        peak_rate_max = data.get("peak_rate_max", 50)
        return [
            GaugeDef("TOTAL QSOs",  "total",          "qso_max",   ACCENT(),  "{v}",
                     tooltip=(
                         "TOTAL QSOs\n"
                         "Every logged contact including dupes.\n"
                         "Every valid ARRL Digital QSO scores at least 1 point."
                     )),
            GaugeDef("VALID QSOs",  "valid",           "qso_max",   GREEN(),   "{v}",
                     tooltip=(
                         "VALID QSOs\n"
                         "Non-dupe contacts that count toward your score.\n"
                         "Stations may be worked once per band, regardless\n"
                         "of digital mode."
                     )),
            GaugeDef("TOTAL SCORE", "score",           "score_max", ACCENT3(), "{v:,}",
                     tooltip=(
                         "TOTAL SCORE\n"
                         "Sum of QSO points — this contest has NO multiplier.\n"
                         "Formula: Σ pts, where each QSO = 1 + 1 pt per 500 km\n"
                         "between grid-square centers (rounded up).\n"
                         "Matches N1MM's running score."
                     )),
            GaugeDef("GRID SQUARES", "worked",         grid_max,    ACCENT3(), "{v}",
                     tooltip=(
                         "GRID SQUARES WORKED (informational)\n"
                         "Unique 4-character grid squares worked, counted\n"
                         "once per band. Does NOT multiply your score — this\n"
                         "contest scores purely on distance-based QSO points.\n"
                         "Gauge ceiling auto-scales to 125% of current count."
                     )),
            GaugeDef("PTS / QSO",   "pts_per_qso",     4.0,         MUTED(),   "{v:.2f}",
                     tooltip=(
                         "AVERAGE POINTS PER QSO\n"
                         "Total QSO points ÷ valid QSOs.\n"
                         "Scoring: 1 pt + 1 pt per 500 km between grid-square\n"
                         "centers (rounded up) — long DX contacts are worth\n"
                         "far more here than in most contests."
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
        """Unique grid squares worked (any band) — informational only."""
        return {g for q in qsos if not q["dupe"]
                for g in [_grid_square(q.get("mult1"))] if g}

    def worked_primary_band_mults(self, qsos: list) -> set:
        """Unique (grid square, band, mode) tuples — informational only,
        does not affect score()."""
        result: set = set()
        for q in qsos:
            if q["dupe"]:
                continue
            g = _grid_square(q.get("mult1"))
            if g:
                result.add((g, q.get("band", "?"), q.get("mode", "?")))
        return result

    def worked_secondary_band_mults(self, qsos: list) -> set:
        return set()

    def missing_primary_mults(self, qsos: list) -> list:
        """Not applicable — no fixed grid-square list, and grids aren't a
        scoring multiplier here anyway."""
        return []

    def sparkline_mults(self, q: dict, seen: set) -> int:
        """Count brand-new grid squares for the sparkline marker — purely
        informational, does not affect running_score_for_sparkline()."""
        g   = _grid_square(q.get("mult1"))
        key = (g, q.get("band"), q.get("mode"))
        if g and key not in seen:
            seen.add(key)
            return 1
        return 0

    def running_score_for_sparkline(self, qsos_up_to_hour: list) -> int:
        """Matches score(): sum of QSO points only, no multiplier term."""
        return sum(q["pts"] for q in qsos_up_to_hour if not q["dupe"])

    # ── Band efficiency override ──────────────────────────────────────────────

    def band_efficiency(self, qsos: list) -> list:
        """
        Per-band breakdown: QSOs, points, efficiency ranked by pts/QSO
        (see efficiency_label() override) since there's no multiplier
        concept to rank by here.
        """
        band_qsos = defaultdict(int)
        band_pts  = defaultdict(int)

        for q in qsos:
            if q["dupe"]:
                continue
            b = q.get("band") or "?"
            band_qsos[b] += 1
            band_pts[b]  += q.get("pts", 0) or 0

        result = []
        for b in band_qsos:
            qn = band_qsos[b]
            pn = band_pts[b]
            result.append({
                "band":         b,
                "qsos":         qn,
                "new_shires":   pn,   # reuses the generic key name
                "pts":          pn,
                "efficiency":   pn / qn if qn else 0,
            })
        return sorted(result, key=lambda x: x["efficiency"], reverse=True)


def register() -> ARRLDigitalPlugin:
    return ARRLDigitalPlugin()
