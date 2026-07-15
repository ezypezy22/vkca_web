"""
plugins/wpx.py
──────────────
CQ World Wide WPX Contest plugin for the VK Contest Analyzer.

Covers both CW (May) and SSB (March) weekends.
N1MM+ ContestName strings: "CQ-WPX-CW", "CQ-WPX-SSB", "CQWPXCW", "CQWPXSSB"
and common variants. CQ WPX RTTY uses different QSO-point values and is
deliberately NOT matched by this plugin (identify() returns False for any
name containing "RTTY") — see plugins/wpx_rtty.py, which owns it instead.

Scoring (per rules at https://cqwpx.com/rules/):
  • QSO points (same for CW and SSB):
      – Different continent          → 3 pts on 10/15/20m, 6 pts on 40/80/160m
      – Same continent, diff country → 1 pt  on 10/15/20m, 2 pts on 40/80/160m
        (NA-NA exception: 2 pts / 4 pts — not relevant for a VK operator)
      – Same country                 → 1 pt, any band
  • Multiplier: WPX prefix (callsign prefix, e.g. "VK2", "W1", "JA3").
      Each prefix counts ONCE for the whole contest — NOT per band, unlike
      CQWW's country/zone mults.
  • Final score = total QSO points × total unique prefixes worked.

N1MM stores:
  WPXPrefix      → the WPX prefix string (preferred mult1 source — see
                   preferred_exchange_columns below)
  IsMultiplier1  → 1 = new prefix (first time worked, any band)
  pts            → QSO point value (1 / 2 / 3 / 4 / 6)
  CQZone / ZN    → CQ zone of the worked station (used here only as a
                   continent lookup for the recalc_pts() fallback)

Session structure: 48-hour contest, Saturday 00:00–Sunday 23:59 UTC, same
shape as CQWW — modelled as 4 × 12-hour chunks for the generic rate/session
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


# ── Standard WPX band set (display order, low → high) ─────────────────────────
_WPX_BAND_ORDER: list[str] = ["160M", "80M", "40M", "20M", "15M", "10M"]


def _peak_rate_per_hour(times: list, window_minutes: int = 60) -> int:
    """
    Best sliding-window QSO rate, expressed as QSOs/hour, matching N1MM's
    "Max Rates" report (Window menu) for the given window size.

    For each QSO time ``t``, counts how many QSOs (including ``t`` itself)
    fall within ``[t, t + window_minutes]``, takes the maximum over all
    ``t``, and scales that count to a per-hour rate. ``times`` must already
    be sorted ascending and contain only valid (non-dupe) QSO timestamps.

    With the default 60-minute window the scale factor is 1, so the
    returned value is simply the QSO count in the single busiest rolling
    hour — the figure most operators mean by "my best rate".
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


# ═════════════════════════════════════════════════════════════════════════════
# Plugin
# ═════════════════════════════════════════════════════════════════════════════

class CQWPXPlugin(ContestPlugin):
    """
    CQ World Wide WPX Contest — CW and SSB.

    Multiplier : WPX prefix, counted once for the whole log (not per band).
    Exchange   : RS(T) + serial number.
    """

    # ── Identity ──────────────────────────────────────────────────────────────

    def identify(self, contest_name: str) -> bool:
        cn = contest_name.upper().replace(" ", "").replace("_", "").replace("-", "")
        if "RTTY" in cn:
            # WPX RTTY has different QSO-point values (2/4 same-continent,
            # 1/2 same-country) — not handled by this plugin.
            return False
        keywords = ("CQWPX", "WPXSSB", "WPXCW", "WORLDWIDEPREFIX")
        return any(kw in cn for kw in keywords)

    @property
    def display_name(self) -> str:
        return "CQ WPX"

    # ── Session / block structure ─────────────────────────────────────────────

    def session_config(self) -> SessionConfig:
        # 48 h total; modelled as 4 × 12-hour chunks purely so the generic
        # rate/session machinery has something to iterate over — see
        # uses_block_structure().
        return SessionConfig(
            duration_mins=720,     # 12 hours per chunk
            num_sessions=4,
            label_prefix="B",
            start_hour=0,          # Saturday 00:00 UTC
        )

    def uses_block_structure(self) -> bool:
        """
        WPX is a single continuous 48-hour contest with no "block"
        subdivision (same as CQWW). The overview's time panel should show
        whole-contest start/elapsed/remaining instead of a per-block
        countdown.
        """
        return False

    # ── Multiplier contract ───────────────────────────────────────────────────

    def mult_list(self) -> list:
        """
        WPX prefixes are open-ended (thousands of possible prefixes,
        including one-off special-event calls). Returning an empty list
        tells the framework to treat mult1 values as free-form (no lookup
        table / missing-mults tab).
        """
        return []

    def mult_label(self) -> str:
        return "Prefix"

    def mult_of_qso(self, q: dict) -> Optional[str]:
        """Return the WPX prefix stored as mult1 (see preferred_exchange_columns)."""
        return q.get("mult1") or None

    # ── Scoring ───────────────────────────────────────────────────────────────

    def recalc_pts(self, qsos: list) -> None:
        """
        Deliberately a no-op: trust N1MM's stored Points unconditionally.

        An earlier draft of this method tried to "fix up" pts==1 QSOs by
        re-deriving the worked station's continent from its CQ zone and
        recomputing 1/2/3/6 from the continent + band. That re-derivation
        is WRONG for several common DXCC entities whose CQ zone suggests
        one continent but whose DXCC CONTINENT (the field WPX scoring
        actually uses) is different — most importantly for a VK operator:

          • Indonesia (YB-YH, CQ zone 28) → CQ zone 28 covers parts of
            continental Asia, but Indonesia's DXCC continent is OC.
          • Philippines (DU/DX, CQ zone 27) → likewise DXCC continent OC.
          • Hawaii (KH6, CQ zone 31) → DXCC continent OC.

        N1MM correctly scores VK<->these-entities QSOs as same-continent
        (1 pt on 10/15/20m, 2 pts on 40/80/160m) using its own DXCC table.
        The zone-based re-derivation instead classified them as a
        different continent (3/6 pts), silently inflating a real log's
        score by ~6% (119 of 1281 QSOs changed, total points 3529 -> 3761,
        score 2,442,068 -> 2,602,612 — confirmed against N1MM's own
        per-band report for this log).

        WPX also has no legitimate 0-point QSO (minimum is 1 pt for a
        same-country contact on any band), so the base loader's
        ``dupe = 1 if pts == 0 else 0`` fallback — and its accompanying
        "pts == 0 -> 1" floor for non-dupe QSOs — are already correct for
        WPX. There is nothing for this method to safely improve on without
        a real DXCC continent/country table, so it does nothing.
        """
        return

    def score(self, qsos: list) -> int:
        """Total QSO points × total unique WPX prefixes worked (any band)."""
        pts   = sum(q["pts"] for q in qsos if not q["dupe"])
        mr    = self.multipliers(qsos)
        mults = len(mr.primary_mults)
        return pts * mults if mults else pts

    # ── "Next QSO" value estimator (Overview tab) ─────────────────────────────

    def qso_value_estimate(self, qsos: list) -> dict:
        """
        Estimate how much the total score would jump for working ONE more
        QSO right now, by band.

        WPX scores as::

            Score = TotalPoints × TotalPrefixes

        Adding a single QSO worth ``p`` raw QSO points changes the score by::

            delta = p * (M + dm) + P * dm

        where ``P`` is the current total QSO points, ``M`` is the current
        prefix count, and ``dm`` is 0 (fill QSO — prefix already worked) or
        1 (brand-new WPX prefix). Unlike CQWW there's no "two new mults on
        one QSO" case — WPX has only one multiplier type — so only the
        no-mult and one-mult scenarios are produced.

        ``p`` is taken as the average QSO-point value already logged on that
        band, falling back to the overall average for bands with no QSOs yet.
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

        band_order = list(_WPX_BAND_ORDER)
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
                "one_mult": "+QSO +1 prefix",
            },
        }

    def multipliers(self, qsos: list) -> MultResult:
        """
        Primary mults: unique WPX prefixes worked, counted ONCE across the
        whole log (not per band — see module docstring).

        We collect every distinct non-empty mult1 value from non-dupe QSOs
        directly, rather than relying on N1MM's IsMultiplier1 flag. This is
        deliberately more robust than flag-based counting: if IsMultiplier1
        is missing/zero for an entire imported log (as has been observed for
        other contest types in this database), a flag-based count would
        silently come out as zero. Direct collection of mult1 values gives
        the correct prefix count regardless of whether the flags were ever
        populated.

        secondary_mults is always empty — WPX has only one multiplier type.
        """
        prefixes: set = set()
        for q in qsos:
            if q["dupe"]:
                continue
            if q.get("mult1"):
                prefixes.add(q["mult1"])

        return MultResult(
            primary_mults=prefixes,
            secondary_mults=set(),
            primary_label="Prefixes",
            secondary_label="",
        )

    # ── Exchange columns hint ─────────────────────────────────────────────────

    @property
    def preferred_exchange_columns(self):
        # N1MM's WPX database schema stores the computed WPX prefix directly
        # in WPXPrefix (e.g. "VK2", "W1", "JA3", "VP8"). We force that column
        # first so mult1 holds the WPX prefix rather than the raw exchange
        # (serial number), which the base loader's default heuristic would
        # otherwise pick up via Exchange1.
        return ["WPXPrefix", "wpxprefix", "Mult1", "mult1",
                "Exchange1", "exchange1"]

    # ── UI hints ──────────────────────────────────────────────────────────────

    def has_missing_tab(self) -> bool:
        # No fixed mult list — "missing prefixes" tab doesn't make sense
        return False

    def band_list(self) -> list:
        # WPX CW/SSB is 160-10m — no WARC bands (30/17/12m).
        return list(_WPX_BAND_ORDER)

    def has_region_heat(self) -> bool:
        return False

    def has_state_bars(self) -> bool:
        return False

    def post_snapshot(self, snap: dict, qsos: list) -> None:
        """
        Called by compute_snapshot() to inject WPX-correct display values.

        compute_snapshot() sets worked/band_mults from mult_list() (empty
        for WPX) and pct from worked / len(mult_list), which divides by
        zero and is guarded to 0. We override:

          worked        → unique WPX prefix count (matches score()/multipliers())
          band_mults    → same value (WPX has no separate per-band mult count)
          zone_cnt      → 0 (WPX has no secondary/zone multiplier)
          pct           → 0.0 (no fixed total to express a percentage of)
          pfx_max       → gauge ceiling, a round number just above the current count
          pts_per_qso   → total QSO points / valid QSOs (N1MM's "Pt/Q" column)
          qsos_per_mult → valid QSOs / prefixes (N1MM's "1 Mult = N Q's" line)
          peak_rate     → best 60-minute rolling QSO rate, in QSOs/hour
                          (matches N1MM's "Max Rates" report for a 60-minute
                          window — see _peak_rate_per_hour())
          peak_rate_max → gauge ceiling for peak_rate
        """
        mr        = self.multipliers(qsos)
        pfx_cnt   = len(mr.primary_mults)
        total_pts = sum(q["pts"] for q in qsos if not q["dupe"])
        valid     = snap.get("valid", 0)

        snap["worked"]     = pfx_cnt
        snap["band_mults"] = pfx_cnt
        snap["zone_cnt"]   = 0
        snap["pct"]        = 0.0

        snap["pts_per_qso"]   = (total_pts / valid) if valid else 0.0
        snap["qsos_per_mult"] = (valid / pfx_cnt) if pfx_cnt else 0.0

        valid_times = sorted(q["time"] for q in qsos if not q["dupe"])
        peak_rate   = _peak_rate_per_hour(valid_times, window_minutes=60)
        snap["peak_rate"] = peak_rate

        import math
        snap["pfx_max"]       = max(int(math.ceil(pfx_cnt * 1.25 / 50) * 50), 50)
        snap["peak_rate_max"] = max(int(math.ceil(peak_rate * 1.25 / 50) * 50), 50)

    def gauge_defs(self, data: dict, total_mults: int) -> list:
        pfx_max       = data.get("pfx_max", max(data.get("worked", 1), 50))
        peak_rate_max = data.get("peak_rate_max", 50)
        return [
            GaugeDef("TOTAL QSOs",  "total",          "qso_max",   ACCENT(),  "{v}",
                     tooltip=(
                         "TOTAL QSOs\n"
                         "Every logged contact including dupes.\n"
                         "WPX has no 0-point contacts — minimum is 1 pt\n"
                         "for a same-country QSO on any band."
                     )),
            GaugeDef("VALID QSOs",  "valid",           "qso_max",   GREEN(),   "{v}",
                     tooltip=(
                         "VALID QSOs\n"
                         "Non-dupe contacts that count toward your score.\n"
                         "Unlike CQWW, every valid WPX QSO scores at\n"
                         "least 1 point (same-country, 10/15/20m)."
                     )),
            GaugeDef("TOTAL SCORE", "score",           "score_max", ACCENT3(), "{v:,}",
                     tooltip=(
                         "TOTAL SCORE\n"
                         "Total QSO points × unique WPX prefixes worked.\n"
                         "Formula: Σ pts  ×  unique_prefixes\n"
                         "Prefixes count ONCE for the whole log — not per band.\n"
                         "Matches N1MM's running score."
                     )),
            GaugeDef("PREFIXES",    "worked",          pfx_max,     ACCENT3(), "{v}",
                     tooltip=(
                         "WPX PREFIXES\n"
                         "Unique callsign prefixes worked (e.g. VK2, W1, JA3).\n"
                         "Each prefix counts ONCE regardless of how many bands\n"
                         "you work them on — unlike CQWW country/zone mults.\n"
                         "Gauge ceiling auto-scales to 125% of current count."
                     )),
            GaugeDef("PTS / QSO",   "pts_per_qso",     6.0,         MUTED(),   "{v:.2f}",
                     tooltip=(
                         "AVERAGE POINTS PER QSO\n"
                         "Total QSO points ÷ valid QSOs — matches N1MM's 'Pt/Q'.\n"
                         "Scoring: 6 pts (diff continent, 40/80/160m)\n"
                         "         3 pts (diff continent, 10/15/20m)\n"
                         "         2 pts (same continent, 40/80/160m)\n"
                         "         1 pt  (same continent or same country)\n"
                         "From VK, targeting 40/80m EU/NA contacts maximises this."
                     )),
            GaugeDef("QSOs / MULT", "qsos_per_mult",   10.0,        MUTED(),   "{v:.1f}",
                     tooltip=(
                         "QSOs PER MULTIPLIER\n"
                         "Valid QSOs ÷ unique prefixes — matches N1MM's\n"
                         "'1 Mult = N Q's' efficiency indicator.\n"
                         "Lower = better: each prefix is earning you more\n"
                         "QSO points relative to your mult count.\n"
                         "Gauge ceiling is 10 (10 QSOs per prefix worked)."
                     )),
            GaugeDef("PEAK RATE/HR", "peak_rate",      peak_rate_max, GREEN(), "{v}",
                     tooltip=(
                         "PEAK RATE (QSOs/hr)\n"
                         "Best 60-minute rolling QSO rate across the contest.\n"
                         "Matches N1MM's 'Max Rates' (Window menu) for a\n"
                         "60-minute window — the rate most operators mean\n"
                         "when they say 'my best rate was X/hr'."
                     )),
        ]

    # ── Multiplier helpers (overrides) ────────────────────────────────────────

    def worked_primary_mults(self, qsos: list) -> set:
        """Unique WPX prefixes worked (any band)."""
        return {q["mult1"] for q in qsos if not q["dupe"] and q.get("mult1")}

    def worked_primary_band_mults(self, qsos: list) -> set:
        """
        Unique (prefix, band, mode) tuples — for informational per-band
        display only (e.g. Band Breakdown tab). Does NOT affect scoring:
        WPX prefix mults count once overall regardless of how many bands
        they appear on (see multipliers()).
        """
        result: set = set()
        for q in qsos:
            if not q["dupe"] and q.get("mult1"):
                result.add((q["mult1"], q.get("band", "?"), q.get("mode", "?")))
        return result

    def worked_secondary_band_mults(self, qsos: list) -> set:
        """WPX has no secondary multiplier type."""
        return set()

    def missing_primary_mults(self, qsos: list) -> list:
        """Not applicable for WPX (open-ended prefix list)."""
        return []

    def sparkline_mults(self, q: dict, seen: set) -> int:
        """
        Count brand-new WPX prefixes for the sparkline.

        Note: ``seen`` holds bare prefix strings here (not band/mode tuples
        as in CQWW), since WPX prefixes are global, not per-band.
        """
        pfx = q.get("mult1")
        if pfx and pfx not in seen:
            seen.add(pfx)
            return 1
        return 0

    def running_score_for_sparkline(self, qsos_up_to_hour: list) -> int:
        """
        Calculate score for the sparkline using the same logic as
        multipliers() / score(), so the final sparkline point matches the
        TOTAL SCORE gauge exactly.
        """
        pts = sum(q["pts"] for q in qsos_up_to_hour if not q["dupe"])

        prefixes: set = set()
        for q in qsos_up_to_hour:
            if q["dupe"]:
                continue
            if q.get("mult1"):
                prefixes.add(q["mult1"])

        mults = len(prefixes)
        return pts * mults if mults else pts

    # ── Band efficiency override ──────────────────────────────────────────────

    def band_efficiency(self, qsos: list) -> list:
        """
        Per-band breakdown: QSOs, distinct prefixes seen on that band, and
        efficiency (prefixes-on-band / QSOs-on-band).

        This is informational only — "new_prefixes" here means "distinct
        prefixes worked on this band", not "prefixes first worked anywhere
        on this band" (WPX prefix mults aren't per-band, so there's no
        scoring-relevant "new on this band" concept to show).
        """
        band_qsos     = defaultdict(int)
        band_pts      = defaultdict(int)
        band_prefixes = defaultdict(set)

        for q in qsos:
            if q["dupe"]:
                continue
            b = q.get("band") or "?"
            band_qsos[b] += 1
            band_pts[b]  += q.get("pts", 0) or 0
            if q.get("mult1"):
                band_prefixes[b].add(q["mult1"])

        time_stats = self._band_time_stats(qsos)
        result = []
        for b in band_qsos:
            qn = band_qsos[b]
            pn = len(band_prefixes[b])
            ts = time_stats.get(b, {"best_hour_rate": 0, "last_qso_utc": None})
            result.append({
                "band":          b,
                "qsos":          qn,
                "pts":           band_pts[b],
                "new_shires":    pn,   # reuses the generic key name
                "new_prefixes":  pn,
                "efficiency":    pn / qn if qn else 0,
                **ts,
            })
        return sorted(result, key=lambda x: x["efficiency"], reverse=True)
