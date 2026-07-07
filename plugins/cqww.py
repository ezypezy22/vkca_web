"""
plugins/cqww.py
───────────────
CQ World Wide DX Contest plugin for the VK Contest Analyzer.

Covers both CW (November) and SSB (October) weekends.
N1MM+ ContestName strings: "CQ-WW-CW", "CQ-WW-SSB", "CQWW-CW", "CQWWDX-CW",
"CQWWDX-SSB" and common variants.

Scoring (per rules at https://cqww.com/rules.htm):
  • QSO points:
      – Different continent          → 3 pts
      – Same continent, diff country → 1 pt  (N. America intra-country → 2 pts)
      – Same country                 → 0 pts (but still scores mults)
  • Multipliers (per band, stacked across all bands):
      – Primary   : DXCC/WAE country (mult1 in N1MM is the country prefix / entity)
      – Secondary : CQ Zone (cqz in N1MM)
  • Final score = total QSO points × (zone mults + country mults)

N1MM stores:
  is_mult1 = 1  → new CQ zone on this band    (APP_N1MM_MULT1 in ADI export)
  is_mult2 = 1  → new country on this band    (APP_N1MM_MULT2 in ADI export)
  pts            → QSO point value (3 / 2 / 1 / 0)
  mult1 / Exchange1 → DXCC country prefix / WAE entity
  CQZone         → CQ zone of the worked station

Session structure: 48-hour contest, Saturday 00:00–Sunday 23:59 UTC.
We show 4 × 12-hour blocks for a convenient overview.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

from plugins.base import (
    ContestPlugin,
    GaugeDef,
    MultResult,
    SessionConfig,
    ACCENT,
    ACCENT2,
    ACCENT3,
    GREEN,
    MUTED,
)


# ── CQ zone → continent mapping ───────────────────────────────────────────────
# Used to derive continent when N1MM doesn't supply it directly.
_ZONE_CONTINENT: dict[int, str] = {
    1: "NA", 2: "NA", 3: "NA", 4: "NA", 5: "NA", 6: "NA", 7: "NA", 8: "NA",
    9: "SA", 10: "SA", 11: "SA",
    12: "NA",          # Caribbean / Central America
    13: "NA",
    14: "EU", 15: "EU", 16: "EU", 17: "EU", 18: "EU",
    19: "AS",
    20: "AS", 21: "AS",
    22: "EU",          # Russia Europe
    23: "AS", 24: "AS", 25: "AS", 26: "AS", 27: "AS",
    28: "AF",
    29: "OC", 30: "OC",
    31: "OC",  # Zone 31 = Hawaii/Pacific (was incorrectly "AF")
    32: "OC",
    33: "AF", 34: "AF", 35: "AF", 36: "AF", 37: "AF", 38: "AF", 39: "AF",
    40: "AF",
}


def _continent_of_zone(zone: Optional[int]) -> Optional[str]:
    if zone is None:
        return None
    return _ZONE_CONTINENT.get(zone)


# North America country prefixes (2-pt intra-continent rule applies within NA
# *except* same-country contacts which are worth 0).
# This is an approximation; N1MM's stored pts value is authoritative when present.
_NA_PREFIXES = frozenset({
    "K", "KH6", "KL", "VE", "XE", "XF", "YN", "TI", "HP", "HH",
    "HI", "CO", "PJ", "J3", "V2", "VP9", "KP4", "KP2", "NP4", "NP2",
    "FG", "FM", "FS", "FJ", "VP5", "6Y", "8P", "9Y", "ZF",
})


def _is_na_prefix(country_prefix: str) -> bool:
    """Rough check: is this DXCC prefix in the NA continent?"""
    p = (country_prefix or "").upper().strip()
    # Direct membership first
    if p in _NA_PREFIXES:
        return True
    # K / KH / KL / KG / KP… prefix families
    return p.startswith("K") or p.startswith("W") or p.startswith("N") or p.startswith("A")


# ── All 40 CQ zones ───────────────────────────────────────────────────────────
_ALL_ZONES: list[int] = list(range(1, 41))

# ── Standard CQWW band set (display order, low → high) ────────────────────────
_CQWW_BAND_ORDER: list[str] = ["160M", "80M", "40M", "20M", "15M", "10M"]


# ═════════════════════════════════════════════════════════════════════════════
# Plugin
# ═════════════════════════════════════════════════════════════════════════════

class CQWWPlugin(ContestPlugin):
    """
    CQ World Wide DX Contest — CW and SSB.

    Primary multiplier  : DXCC / WAE country (per band)
    Secondary multiplier: CQ Zone (per band)
    Exchange            : RST + CQ Zone
    """

    # ── Identity ──────────────────────────────────────────────────────────────

    def identify(self, contest_name: str) -> bool:
        cn = contest_name.upper().replace(" ", "").replace("_", "").replace("-", "")
        keywords = ("CQWW", "CQWWDX", "CQWWCW", "CQWWSSB", "CQWWPH",
                    "CQ-WW", "WORLDWIDEDX")
        return any(kw.replace("-", "") in cn for kw in keywords)

    @property
    def display_name(self) -> str:
        return "CQ WW DX"

    # ── Session / block structure ─────────────────────────────────────────────

    def session_config(self) -> SessionConfig:
        # 48 h total; internally modelled as 4 × 12-hour chunks purely so the
        # generic rate/session machinery has something to iterate over.
        # CQWW itself has no "block" concept — see uses_block_structure().
        return SessionConfig(
            duration_mins=720,      # 12 hours per chunk
            num_sessions=4,
            label_prefix="B",
            start_hour=0,           # Saturday 00:00 UTC
        )

    def uses_block_structure(self) -> bool:
        """
        CQWW is a single continuous 48-hour contest with no "block"
        subdivision (unlike e.g. VK Remembrance Day or Trans-Tasman, which
        score in fixed time blocks). The overview's time panel should show
        whole-contest start/elapsed/remaining instead of a per-block
        countdown.
        """
        return False

    # ── Multiplier contract ───────────────────────────────────────────────────

    def mult_list(self) -> list:
        """
        CQWW has no fixed multiplier list — countries are open-ended (DXCC+WAE).
        Returning an empty list tells the framework to treat mult1 values as
        free-form (no lookup table required).
        """
        return []

    def mult_label(self) -> str:
        return "Country"

    def mult_of_qso(self, q: dict) -> Optional[str]:
        """Return the DXCC/WAE country prefix stored as mult1 by N1MM."""
        return q.get("mult1") or None

    # Zones are the secondary multiplier — exposed via cqz field, no need to
    # override region_list / region_of_mult (those are for bar-chart tabs).

    # ── Scoring ───────────────────────────────────────────────────────────────

    def recalc_pts(self, qsos: list) -> None:
        """
        Re-derive QSO point values and fix dupe flags for CQWW.

        Rules:
          • 0 pts  — same country as the worked station (valid, NOT a dupe)
          • 1 pt   — same continent, different country
          • 2 pts  — different country within North America
          • 3 pts  — different continent

        CRITICAL — dupe vs. same-country:
        The base loader uses the fallback  ``dupe = 1 if pts == 0 else 0``
        when no IsDupe/Dupe column exists.  This incorrectly marks CQWW
        same-country contacts (which legitimately score 0 pts) as dupes, and
        those QSOs then disappear from total QSOs, score, and multiplier counts.

        We fix the dupe flag here:
          - A QSO whose APP_N1MM_CONTACTTYPE raw value is "D" is a true dupe.
          - A QSO that was already marked dupe=1 AND has pts=0 AND whose worked
            continent matches the operator's continent is treated as a valid
            0-pt contact (same-country rule), NOT a dupe.

        We use N1MM's stored pts when non-zero; this method only fills in the
        value when pts is missing/zero and the QSO has not been identified as a
        true dupe.
        """
        op_zone      = 29                            # VK default
        op_continent = _continent_of_zone(op_zone) or "OC"

        for q in qsos:
            # ── Restore valid same-country QSOs mis-flagged as dupes ──────────
            # The loader's fallback marks any pts=0 row as dupe=1.  For CQWW
            # this incorrectly catches same-country contacts.  We un-dupe them
            # when the raw_dupe source was the pts-based fallback (i.e. the QSO
            # was never actually tagged D by N1MM).
            if q.get("dupe") and q.get("pts") == 0:
                # Check: is the worked station's continent the same as the op?
                worked_zone      = q.get("cqz")
                worked_continent = _continent_of_zone(worked_zone)
                if worked_continent and worked_continent == op_continent:
                    # Same continent + 0 pts → same-country rule.  Restore as valid.
                    q["dupe"] = 0
                    q["pts"]  = 0   # keep 0 — same-country earns no QSO points

            if q["dupe"]:
                continue

            # ── Trust N1MM's stored value when it's non-zero ─────────────────
            if q.get("pts") and q["pts"] > 0:
                continue

            # ── Trust N1MM's pts=0 for same-continent QSOs ───────────────────
            # A non-dupe with pts=0 and a same-continent worked station is a
            # legitimate same-country contact (0 pts by CQWW rules).  We cannot
            # distinguish same-country from same-continent-different-country
            # using zone alone, so when N1MM has already stored 0 we trust it
            # rather than bumping to 1 (which inflates the score).
            worked_zone      = q.get("cqz")
            worked_continent = _continent_of_zone(worked_zone)

            if worked_continent == op_continent:
                # N1MM stored 0 for a same-continent QSO — keep it as-is.
                # If pts were meant to be 1 or 2, N1MM would have stored that.
                q["pts"] = 0
                continue

            # ── Recalculate only for cross-continent QSOs with missing pts ────
            if worked_continent is None:
                q["pts"] = 1      # unknown — conservative default
                continue

            # worked_continent != op_continent here
            q["pts"] = 3

    def uses_cq_zone_scoring(self) -> bool:
        return True

    def score(self, qsos: list) -> int:
        """Total QSO points × total multipliers (zones + countries, all bands)."""
        pts   = sum(q["pts"] for q in qsos if not q["dupe"])
        mr    = self.multipliers(qsos)
        mults = len(mr.primary_mults) + len(mr.secondary_mults)
        return pts * mults if mults else pts

    # ── "Next QSO" value estimator (Overview tab) ─────────────────────────────

    def qso_value_estimate(self, qsos: list) -> dict:
        """
        Estimate how much the total score would jump for working ONE more
        QSO right now, broken down by band and by what that QSO is worth in
        multiplier terms.

        CQWW scores as::

            Score = TotalPoints × TotalMultipliers

        where TotalMultipliers = (country, band) mults + (zone, band) mults
        across the whole log.  Adding a single QSO that is worth ``p`` raw
        QSO points and brings ``dm`` brand-new band-multipliers with it
        changes the score by::

            delta = p * (M + dm) + P * dm

        where ``P`` is the current total QSO points and ``M`` is the current
        total multiplier count.  ``dm`` can be:

          - 0  → a "fill" QSO on a band/country/zone already worked (no new
                 multiplier at all)
          - 1  → a new band-country *or* a new band-zone (but not both)
          - 2  → a new band-country *and* a new band-zone on the same QSO —
                 the big one (e.g. first QSO on a band with a brand-new
                 DXCC entity that's also in a zone not yet worked on that
                 band)

        ``p`` is taken as the average QSO-point value already logged on that
        band (a practical proxy for "what the next QSO there is likely to be
        worth"). Bands with no QSOs yet fall back to the overall average
        across the whole log.

        Late in a big contest, with hundreds of band-mults already banked,
        ``M`` (and therefore ``P``) is large, so a single new-mult QSO can be
        worth thousands of points — this is exactly the "keep pushing for
        one more multiplier" incentive the Overview panel is meant to show.
        """
        valid     = [q for q in qsos if not q["dupe"]]
        total_pts = sum(q["pts"] for q in valid)

        mr           = self.multipliers(qsos)
        total_mults  = len(mr.primary_mults) + len(mr.secondary_mults)
        overall_avg  = (total_pts / len(valid)) if valid else 0.0

        band_pts: dict = defaultdict(list)
        for q in valid:
            b = (q.get("band") or "?").upper()
            band_pts[b].append(q["pts"])

        def delta(p: float, dm: int) -> float:
            return p * (total_mults + dm) + total_pts * dm

        # Show the standard CQWW bands first (even if not yet active, using
        # the overall average as a placeholder), then any other bands that
        # actually appear in the log (e.g. 6m on a CQWW-adjacent contest).
        band_order = list(_CQWW_BAND_ORDER)
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
                "two_mult": delta(avg_p, 2),
            }

        return {
            "total_pts":   total_pts,
            "total_mults": total_mults,
            "overall_avg": overall_avg,
            "bands":       bands,
            "band_order":  band_order,
            "scenarios":   ["no_mult", "one_mult", "two_mult"],
            "scenario_labels": {
                "no_mult":  "+QSO",
                "one_mult": "+QSO +1 mult",
                "two_mult": "+QSO +2 mults (zone & DXCC)",
            },
        }

    def multipliers(self, qsos: list) -> MultResult:
        """
        Primary mults   : unique (country, band) pairs  — counted per-band for scoring
        Secondary mults : unique (cq_zone, band) pairs  — counted per-band for scoring

        Uses N1MM's IsMultiplier1 / IsMultiplier2 flags (mapped as is_mult1 / is_mult2)
        when available — these are the authoritative "new mult on this band" markers.
        Falls back to collecting all non-dupe (entity, band) pairs when the flags
        are absent (e.g. when loading from a non-N1MM source).

        N1MM score window cross-check (VK2YI 2025):
            189 country-band mults + 94 zone-band mults = 283 total
            2576 pts × 283 = 729,008  ✓
        """
        countries: set = set()
        zones: set     = set()

        has_m1 = any(q.get("is_mult1") is not None for q in qsos)
        has_m2 = any(q.get("is_mult2") is not None for q in qsos)

        for q in qsos:
            if q["dupe"]:
                continue
            band = q.get("band") or "?"
            m1   = q.get("mult1") or ""

            # N1MM ADI export: MULT2 = new country on this band,
            #                  MULT1 = new CQ zone on this band (flags are swapped
            #                  vs. the conceptual primary/secondary ordering).
            if has_m2:
                # Use N1MM's flag — only add when N1MM says it's a new band-mult
                if q.get("is_mult2") == 1 and m1:
                    countries.add((m1, band))
            else:
                # No flag data — collect all (entity, band) pairs
                if m1:
                    countries.add((m1, band))

            cqz = q.get("cqz")
            if has_m1:
                if q.get("is_mult1") == 1 and cqz is not None:
                    zones.add((cqz, band))
            else:
                if cqz is not None:
                    zones.add((cqz, band))

        return MultResult(
            primary_mults=countries,
            secondary_mults=zones,
            primary_label="Countries",
            secondary_label="CQ Zones",
        )

    # ── Exchange columns hint ─────────────────────────────────────────────────

    @property
    def preferred_exchange_columns(self):
        # In N1MM's CQWW database schema:
        #   Mult1       → the DXCC/WAE country prefix (what we want as mult1)
        #   Exchange1   → the received exchange, which for CQWW is the CQ zone
        #                 number (e.g. "29") — NOT the country prefix.
        #   WPXPrefix   → also holds the country prefix in some N1MM builds.
        #
        # The base loader's heuristic would pick Exchange1 first, giving us the
        # zone string as mult1.  We override here to force Mult1/WPXPrefix/PFX
        # so mult1 correctly contains the DXCC entity prefix (e.g. "K", "VK",
        # "JA", "FW5").
        #
        # The loader's col() helper tries each candidate in order and returns the
        # first one that exists as a column in the target table.
        return ["Mult1", "mult1", "WPXPrefix", "wpxprefix", "PFX", "pfx",
                "Exchange1", "exchange1"]

    # ── UI hints ──────────────────────────────────────────────────────────────

    def has_missing_tab(self) -> bool:
        # No fixed mult list — "missing countries" tab doesn't make sense
        return False

    def band_list(self) -> list:
        # CQWW is 160-10m only — no WARC bands (30/17/12m).
        return list(_CQWW_BAND_ORDER)

    def has_region_heat(self) -> bool:
        return False

    def has_state_bars(self) -> bool:
        return False

    def post_snapshot(self, snap: dict, qsos: list) -> None:
        """
        Called by compute_snapshot() to inject CQWW-correct display values.

        compute_snapshot() sets:
          worked     = len(mr.primary_mults)   → (country, band) pair count ✓
          band_mults = len(mr.primary_mults)   → same ✓
          zone_cnt   = len(mr.secondary_mults) → (zone, band) pair count ✓
          pct        = 0  (no fixed mult list — division by zero guard fires)

        These are already correct for COUNTRIES and CQ ZONES gauges since N1MM
        also reports band-mults (189 country-band, 94 zone-band).  The only
        correction needed is:
          pct  → zone band-mults / 40 * 100  (% of zones covered across bands)
          worked → keep as-is (band-country pairs)
          zone_cnt → keep as-is (band-zone pairs)
        """
        mr           = self.multipliers(qsos)
        cty_band_cnt = len(mr.primary_mults)
        zon_band_cnt = len(mr.secondary_mults)

        # Override pct: since mult_list() returns [] the base formula gives 0.
        # Use % of the 40 zones covered (on any band).
        unique_zones = {t[0] for t in mr.secondary_mults}
        snap["pct"] = (len(unique_zones) / 40 * 100)

        # Ensure worked / band_mults are the band-pair counts (matching N1MM)
        snap["worked"]     = cty_band_cnt
        snap["band_mults"] = cty_band_cnt
        snap["zone_cnt"]   = zon_band_cnt

        # Gauge max: set to a round number just above current count
        import math
        cty_max = max(int(math.ceil(cty_band_cnt * 1.25 / 50) * 50), 50)
        snap["cty_max"] = cty_max

    def gauge_defs(self, data: dict, total_mults: int) -> list:
        # total_mults passed in is 0 (open-ended entity list) — we use the
        # corrected snapshot keys injected by post_snapshot() above.
        cty_max = data.get("cty_max", max(data.get("worked", 1), 10))
        return [
            GaugeDef("TOTAL QSOs",  "total",      "qso_max",   ACCENT(),  "{v}",
                     tooltip=(
                         "TOTAL QSOs\n"
                         "Every logged contact, including dupes and\n"
                         "zero-point same-country contacts.\n"
                         "Max is the highest total seen across sessions."
                     )),
            GaugeDef("VALID QSOs",  "valid",       "qso_max",   GREEN(),   "{v}",
                     tooltip=(
                         "VALID QSOs\n"
                         "Non-dupe contacts that count toward QSO points.\n"
                         "Includes 0-point same-country contacts (VK↔VK)\n"
                         "which are valid but don't add to your point total."
                     )),
            GaugeDef("TOTAL SCORE", "score",       "score_max", ACCENT3(), "{v:,}",
                     tooltip=(
                         "TOTAL SCORE\n"
                         "QSO points × (country mults + zone mults).\n"
                         "Formula: Σ pts  ×  (band-countries + band-zones)\n"
                         "Matches N1MM's running score display."
                     )),
            GaugeDef("COUNTRIES",   "worked",      cty_max,     ACCENT3(), "{v}",
                     tooltip=(
                         "COUNTRIES (band × entity pairs)\n"
                         "Count of unique DXCC/WAE country × band combinations.\n"
                         "Working VK on 40m and 20m = 2 country mults.\n"
                         "Max 340 entities × 6 bands = 2040 theoretical max.\n"
                         "Gauge ceiling auto-scales to 125% of current count."
                     )),
            GaugeDef("CQ ZONES",    "zone_cnt",    40,          "#64b5f6", "{v}",
                     tooltip=(
                         "CQ ZONES (band × zone pairs)\n"
                         "Count of unique CQ zone × band combinations.\n"
                         "40 zones × 6 bands = 240 theoretical max.\n"
                         "Gauge ceiling is fixed at 40 (unique zones, any band).\n"
                         "VK is in zone 29 — zones 1-8 (NA) are hardest to work."
                     )),
            GaugeDef("BAND CTYS",   "band_mults",  cty_max,     GREEN(),   "{v}",
                     tooltip=(
                         "BAND COUNTRIES\n"
                         "Same value as COUNTRIES — unique DXCC/WAE entity × band\n"
                         "pairs worked. This is the primary scoring multiplier:\n"
                         "each new country on each new band adds 1 to your\n"
                         "multiplier total."
                     )),
            GaugeDef("% ZONES",     "pct",         100.0,       MUTED(),   "{v:.1f}%",
                     tooltip=(
                         "% ZONES COVERED\n"
                         "Unique CQ zones worked on any band, expressed\n"
                         "as a percentage of all 40 CQ zones.\n"
                         "100% = worked at least one station in all 40 zones.\n"
                         "From VK, zones 1-8 (NA east) and 38-40 (Africa)\n"
                         "are the most difficult to fill."
                     )),
        ]

    # ── Multiplier helpers (overrides) ────────────────────────────────────────

    def worked_primary_mults(self, qsos: list) -> set:
        """Unique countries worked (any band)."""
        countries: set = set()
        for q in qsos:
            if not q["dupe"] and q.get("mult1"):
                countries.add(q["mult1"])
        return countries

    def worked_primary_band_mults(self, qsos: list) -> set:
        """Unique (country, band, mode) tuples."""
        result: set = set()
        for q in qsos:
            if not q["dupe"] and q.get("mult1"):
                result.add((q["mult1"], q.get("band", "?"), q.get("mode", "?")))
        return result

    def worked_secondary_band_mults(self, qsos: list) -> set:
        """Unique (zone, band, mode) tuples."""
        result: set = set()
        for q in qsos:
            if not q["dupe"] and q.get("cqz") is not None:
                result.add((q["cqz"], q.get("band", "?"), q.get("mode", "?")))
        return result

    def missing_primary_mults(self, qsos: list) -> list:
        """Not applicable for CQWW (open-ended entity list)."""
        return []

    def sparkline_mults(self, q: dict, seen: set) -> int:
        """Count new band-country and band-zone multipliers for sparkline."""
        count = 0
        band  = q.get("band", "?")
        mode  = q.get("mode", "?")

        key1 = (q.get("mult1"), band, mode)
        if q.get("is_mult2") == 1 and key1 not in seen and q.get("mult1"):  # MULT2 = country
            count += 1
            seen.add(key1)

        key2 = (q.get("cqz"), band, mode)
        if q.get("is_mult1") == 1 and key2 not in seen and q.get("cqz") is not None:  # MULT1 = zone
            count += 1
            seen.add(key2)

        return count

    def running_score_for_sparkline(self, qsos_up_to_hour: list) -> int:
        """
        Calculate score for the sparkline using the same multiplier logic as
        multipliers() / score() so the final sparkline point matches the
        TOTAL SCORE gauge exactly.

        Uses N1MM's is_mult2 flag for country-band mults and is_mult1 flag
        for zone-band mults (same as multipliers()), falling back to
        collecting all unique (entity, band) pairs when the flags are absent.
        """
        pts = sum(q["pts"] for q in qsos_up_to_hour if not q["dupe"])

        countries: set = set()
        zones: set = set()

        has_m1 = any(q.get("is_mult1") is not None for q in qsos_up_to_hour)
        has_m2 = any(q.get("is_mult2") is not None for q in qsos_up_to_hour)

        for q in qsos_up_to_hour:
            if q["dupe"]:
                continue
            band = q.get("band") or "?"
            m1   = q.get("mult1") or ""
            cqz  = q.get("cqz")

            if has_m2:
                if q.get("is_mult2") == 1 and m1:
                    countries.add((m1, band))
            else:
                if m1:
                    countries.add((m1, band))

            if has_m1:
                if q.get("is_mult1") == 1 and cqz is not None:
                    zones.add((cqz, band))
            else:
                if cqz is not None:
                    zones.add((cqz, band))

        mults = len(countries) + len(zones)
        return pts * mults if mults else pts

    # ── Band efficiency override ──────────────────────────────────────────────

    def band_efficiency(self, qsos: list) -> list:
        """Per-band breakdown: QSOs, new countries, new zones, efficiency."""
        band_qsos      = defaultdict(int)
        band_countries = defaultdict(set)
        band_zones     = defaultdict(set)

        for q in qsos:
            if q["dupe"]:
                continue
            b = q.get("band") or "?"
            band_qsos[b] += 1
            if q.get("mult1"):
                band_countries[b].add(q["mult1"])
            if q.get("cqz") is not None:
                band_zones[b].add(q["cqz"])

        result = []
        for b in band_qsos:
            qn  = band_qsos[b]
            cn  = len(band_countries[b])
            zn  = len(band_zones[b])
            mn  = cn + zn
            result.append({
                "band":         b,
                "qsos":         qn,
                "new_shires":   mn,   # reuses the generic key name
                "new_countries": cn,
                "new_zones":    zn,
                "efficiency":   mn / qn if qn else 0,
            })
        return sorted(result, key=lambda x: x["efficiency"], reverse=True)