"""
plugins/hasprnt.py
───────────────────
Harry Angel Memorial 80m Sprint plugin for the VK Contest Analyzer.

Annual 80m event, first Saturday in May, 10:00–11:46 UTC (106 minutes —
one minute for each year of Harry Angel VK4HA's life).
Open to all VK and ZL amateurs licensed for 80m.

Rules: https://www.wia.org.au/members/contests/harryangel/
N1MM ContestName: HA-SPRINT  (from the official HA-SPRINT.UDC)

──────────────────────────────────────────────────────────────────────────────
EXCHANGE
    Sent    : RST + serial number commencing at 001
    Received: RST + serial number from the worked station
    (No state, zone, or grid — just a serial. The serial is for log-checking
    only and carries no multiplier value.)

SCORING  (rule: "Contest Scoring")
    Phone (SSB/AM/FM)  → 1 point per QSO
    CW                 → 2 points per QSO

DUPE RULE  (DupeType=3 in the UDC)
    Each station may be worked ONCE PER MODE. Working VK4SN on Phone AND
    CW both count (two separate QSOs). Working VK4SN twice on Phone = dupe.

MULTIPLIERS
    None. This is a pure points contest — score = sum of QSO points.
    No multiplier column appears in N1MM's LogInfo for this UDC.

SECTIONS (enter one only)
    PHONE   — Phone contacts only
    CW      — CW contacts only
    MIXED   — Both modes; score = Phone pts + CW pts combined

FINAL SCORE
    Total QSO points (Phone pts × 1 + CW pts × 2) — no multiplier applied.
    The results table shows raw score, not QSOs × mults.

──────────────────────────────────────────────────────────────────────────────
N1MM stores (for any operator):
    Exchange1        → received serial number string (e.g. "042")
    Points           → QSO point value (1 or 2) already correctly set by
                       N1MM's UDC PointsPerContact rule; trusted when present
    Mode             → "CW" or "SSB" / "USB" / "LSB" / "PH"
    IsMultiplier1    → always 0 for this contest (no multipliers)
    IsMultiplier2    → always 0 for this contest
    ContestName      → "HA-SPRINT"

REGIONS
    Since this is a domestic 80m contest, a VK call-area / ZL region
    heat breakdown is genuinely useful — 80m propagation is regional,
    and knowing "I have 12 QSOs in VK2 but only 2 in VK5" reflects
    real band-condition signal. Region = first two characters of the
    call prefix (VK2, VK3, ZL, etc.).
"""

from __future__ import annotations

import re
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


# ═════════════════════════════════════════════════════════════════════════════
# Call-area / region helpers
# ═════════════════════════════════════════════════════════════════════════════

# VK call areas (the digit after "VK") and ZL map to these display regions.
# Used for the Region Heat panel — meaningful for 80m propagation analysis.
_VK_CALL_AREAS = ["VK1", "VK2", "VK3", "VK4", "VK5", "VK6", "VK7", "VK8",
                  "VK9", "ZL"]

_VK_AREA_COLOURS = {
    "VK1": "#4dabf7",   # ACT  – blue
    "VK2": "#74c0fc",   # NSW  – lighter blue
    "VK3": "#ff8787",   # VIC  – red
    "VK4": "#ffd43b",   # QLD  – yellow
    "VK5": "#a9e34b",   # SA   – green
    "VK6": "#da77f2",   # WA   – purple
    "VK7": "#ffa94d",   # TAS  – orange
    "VK8": "#63e6be",   # NT   – teal
    "VK9": "#f783ac",   # External territories – pink
    "ZL":  "#ffe066",   # New Zealand – gold
}

_REGION_TOTALS = {
    # Approximate active HA Sprint participant pool — used only for the
    # "total" denominator in the region heat panel (% of known-active
    # call areas worked). Since HA Sprint has no fixed "all stations"
    # list, these are rough proportional weights rather than exact counts,
    # derived from the historical results pool. They give the heat chart
    # a meaningful completion axis without fabricating precision we don't have.
    "VK1": 5,
    "VK2": 40,
    "VK3": 40,
    "VK4": 35,
    "VK5": 20,
    "VK6": 10,
    "VK7": 10,
    "VK8": 5,
    "VK9": 2,
    "ZL":  10,
}


def _call_region(call: str) -> Optional[str]:
    """
    Return the region key for a callsign (e.g. "VK2" for VK2SN,
    "ZL" for ZL4RO, "VK9" for VK9XY).

    Handles portable suffixes (VK4SN/P → VK4) and club prefixes
    (VJ2A → VK2, VL4A → VK4, VK4M → VK4) including the special
    VJ/VL/VZ prefixes that all map to their corresponding VK area.
    """
    c = (call or "").upper().strip().split("/")[0]

    # ZL (New Zealand)
    if c.startswith("ZL") or c.startswith("ZM"):
        return "ZL"

    # VK: handles VK, VJ, VL, VZ prefixes — all are Australian, call area
    # encoded in the digit immediately after the two-letter prefix.
    m = re.match(r"^V[JKLZ](\d)", c)
    if m:
        digit = m.group(1)
        return f"VK{digit}"

    # VK with standard prefix
    m2 = re.match(r"^VK(\d)", c)
    if m2:
        return f"VK{m2.group(1)}"

    return None


def _pts_for_mode(mode: str) -> int:
    """CW = 2 pts, all phone modes = 1 pt."""
    return 2 if (mode or "").upper() == "CW" else 1


def _is_cw(mode: str) -> bool:
    return (mode or "").upper() == "CW"


# ═════════════════════════════════════════════════════════════════════════════
# Plugin
# ═════════════════════════════════════════════════════════════════════════════

class HASprint80mPlugin(ContestPlugin):
    """
    Harry Angel Memorial 80m Sprint (HA Sprint).

    Pure points contest — no multipliers. Score = Σ QSO points.
    Phone = 1 pt, CW = 2 pts. Each station workable once per mode.
    106-minute contest window (10:00–11:46 UTC, first Saturday in May).
    """

    # ── Identity ──────────────────────────────────────────────────────────────

    def identify(self, contest_name: str) -> bool:
        cn = contest_name.upper().replace(" ", "").replace("_", "").replace("-", "")
        # N1MM UDC defines Name=HA-SPRINT → stored as "HA-SPRINT" in the DB.
        # Also catches common variants someone might type manually.
        keywords = ("HASPRINT", "HARRYANGELPRINT", "HARRYANGEL", "HASPR")
        return any(kw in cn for kw in keywords)

    @property
    def display_name(self) -> str:
        return "Harry Angel 80m Sprint"

    # ── Session / block structure ─────────────────────────────────────────────

    def session_config(self) -> SessionConfig:
        # 106-minute contest, shown as a single session. The rate panel
        # will still show QSOs/hour over the window, which is useful.
        return SessionConfig(
            duration_mins=106,
            num_sessions=1,
            label_prefix="HA",
            start_hour=10,      # 10:00 UTC start
        )

    # ── Multiplier contract ───────────────────────────────────────────────────

    def mult_list(self) -> list:
        """No multipliers — return empty list."""
        return []

    def mult_label(self) -> str:
        return "QSO"   # there are no mults; "QSO" reads clearly in the UI

    def mult_of_qso(self, q: dict) -> Optional[str]:
        """No multiplier to return — always None."""
        return None

    def region_of_mult(self, m: str) -> Optional[str]:
        return None

    def region_list(self) -> list:
        return []   # no multiplier-based region heat; see region_heat() override

    # ── Scoring ───────────────────────────────────────────────────────────────

    def recalc_pts(self, qsos: list) -> None:
        """
        Re-derive QSO point values: Phone = 1, CW = 2.
        Trusts N1MM's stored value when already non-zero (the UDC
        PointsPerContact rule handles this correctly).
        """
        for q in qsos:
            if q["dupe"]:
                continue
            if q.get("pts") and q["pts"] > 0:
                continue
            q["pts"] = _pts_for_mode(q.get("mode"))

    def score(self, qsos: list) -> int:
        """Total QSO points — no multiplier (rule: "score = points only")."""
        return sum(q["pts"] for q in qsos if not q["dupe"])

    def multipliers(self, qsos: list) -> MultResult:
        """No multipliers — both sets always empty."""
        return MultResult(
            primary_mults=set(),
            secondary_mults=set(),
            primary_label="",
            secondary_label="",
        )

    # ── Dupe scope ────────────────────────────────────────────────────────────
    # DupeType=3 in the UDC: a station may be worked ONCE PER MODE (once on
    # Phone, once on CW) — not once per band overall (there's only one band
    # here anyway). N1MM's own dupe-checking doesn't appear to make this
    # distinction and zeroes Points for a legitimate different-mode rework
    # the same way it would for a genuine same-mode dupe, so ContestLog.load()
    # needs this to un-flag the false positives before recalc_pts() runs.
    mode_scoped_dupes = True

    def dupe_mode_key(self, qso: dict) -> str:
        return "CW" if _is_cw(qso.get("mode")) else "PHONE"

    @property
    def dupe_rule_text(self) -> str:
        return ("Each station may be worked once PER MODE (once on Phone, once "
                "on CW). Dupes score 0 pts and are not penalised.")

    # ── Exchange column hint ──────────────────────────────────────────────────

    @property
    def preferred_exchange_columns(self):
        # The received serial number lives in Exchange1.
        # Not used for scoring — just for log display.
        return ["Exchange1", "exchange1"]

    # ── UI hints ──────────────────────────────────────────────────────────────

    def has_missing_tab(self) -> bool:
        return False   # no fixed mult list to track "missing" against

    def has_region_heat(self) -> bool:
        return True    # VK call-area breakdown IS useful for 80m propagation

    def has_state_bars(self) -> bool:
        return True

    def gauge_defs(self, data: dict, total_mults: int) -> list:
        return [
            GaugeDef(
                "TOTAL QSOs", "total", "qso_max", ACCENT(), "{v}",
                tooltip=(
                    "TOTAL QSOs\n"
                    "Every logged contact including dupes.\n"
                    "106-minute contest window."
                ),
            ),
            GaugeDef(
                "VALID QSOs", "valid", "qso_max", GREEN(), "{v}",
                tooltip=(
                    "VALID QSOs\n"
                    "Non-dupe contacts. Each station workable\n"
                    "once per mode (Phone and CW count separately)."
                ),
            ),
            GaugeDef(
                "TOTAL SCORE", "score", "score_max", ACCENT3(), "{v:,}",
                tooltip=(
                    "TOTAL SCORE\n"
                    "Sum of QSO points: Phone = 1 pt, CW = 2 pts.\n"
                    "No multiplier — this is the final contest score."
                ),
            ),
            GaugeDef(
                "PHONE QSOs", "worked", "qso_max", ACCENT2(), "{v}",
                tooltip=(
                    "PHONE QSOs\n"
                    "Valid (non-dupe) Phone contacts logged.\n"
                    "Each scores 1 point."
                ),
            ),
            GaugeDef(
                "CW QSOs", "band_mults", "qso_max", "#64b5f6", "{v}",
                tooltip=(
                    "CW QSOs\n"
                    "Valid (non-dupe) CW contacts logged.\n"
                    "Each scores 2 points."
                ),
            ),
            GaugeDef(
                "RATE /HR", "zone_cnt", 200, MUTED(), "{v}",
                tooltip=(
                    "CURRENT RATE\n"
                    "Approximate QSOs per hour based on the\n"
                    "last 10 minutes of the contest window.\n"
                    "Max shown = 200 QSOs/hr."
                ),
            ),
        ]

    def post_snapshot(self, snap: dict, qsos: list) -> None:
        """
        Populate the HA-Sprint-specific gauge values:
          worked    → phone QSO count (not "worked mults" as in a mult contest)
          band_mults → CW QSO count
          zone_cnt  → current rate (QSOs/hr over last 10 min)
          pct       → % of contest time elapsed (106-minute window)
        """
        valid = [q for q in qsos if not q["dupe"]]
        phone_cnt = sum(1 for q in valid if not _is_cw(q.get("mode")))
        cw_cnt    = sum(1 for q in valid if _is_cw(q.get("mode")))

        snap["worked"]     = phone_cnt
        snap["band_mults"] = cw_cnt

        # Current rate: QSOs in the last 10 minutes × 6
        from datetime import datetime, timedelta
        times = [q["time"] for q in valid if q.get("time")]
        if times:
            latest = max(times)
            window_start = latest - timedelta(minutes=10)
            recent = sum(1 for q in valid
                         if q.get("time") and q["time"] >= window_start)
            snap["zone_cnt"] = recent * 6
        else:
            snap["zone_cnt"] = 0

        # % of 106-minute contest elapsed
        if times:
            from datetime import timezone
            contest_start = latest.replace(
                hour=10, minute=0, second=0, microsecond=0
            )
            elapsed = (latest - contest_start).total_seconds() / 60
            snap["pct"] = min(100.0, max(0.0, elapsed / 106 * 100))
        else:
            snap["pct"] = 0.0

    # ── Region heat (VK call-area breakdown) ──────────────────────────────────

    def region_heat(self, qsos: list) -> list:
        """
        Per-VK-call-area QSO breakdown — shows which parts of Australia
        (and NZ) you're hearing on 80m. More meaningful than a mult-based
        region heat since HA Sprint has no geographical multiplier; instead
        this reflects actual 80m propagation coverage.
        """
        area_qsos   = defaultdict(int)
        area_worked = defaultdict(set)   # unique calls per area

        for q in qsos:
            if q["dupe"]:
                continue
            region = _call_region(q.get("call", ""))
            if region:
                area_qsos[region]   += 1
                area_worked[region].add(q.get("call", ""))

        result = []
        for region in _VK_CALL_AREAS:
            qn = area_qsos.get(region, 0)
            unique = len(area_worked.get(region, set()))
            total  = _REGION_TOTALS.get(region, 10)
            result.append({
                "state":  region,
                "qsos":   qn,
                "worked": unique,
                "total":  total,
                "pct":    min(100.0, unique / total * 100) if total else 0,
            })

        return sorted(result, key=lambda x: x["qsos"], reverse=True)

    def mults_by_region(self, qsos: list) -> dict:
        """
        No multiplier-based region breakdown — but return a worked/total
        structure keyed by VK call area so the State Bars panel can render
        a contact-count breakdown, which is useful context for an 80m
        domestic contest even without multipliers.
        """
        area_calls  = defaultdict(set)

        for q in qsos:
            if q["dupe"]:
                continue
            region = _call_region(q.get("call", ""))
            if region:
                area_calls[region].add(q.get("call", ""))

        result = {}
        for region in _VK_CALL_AREAS:
            worked  = sorted(area_calls.get(region, set()))
            total_n = _REGION_TOTALS.get(region, 10)
            # "missing" is a rough placeholder (estimated_pool − worked);
            # not meaningful the same way as a fixed mult list, but gives
            # the bars panel a denominator to render against.
            missing_n = max(0, total_n - len(worked))
            result[region] = {
                "worked":  worked,
                "missing": [f"~{missing_n} more"] if missing_n else [],
            }
        return result

    # ── Band efficiency (mode breakdown for a single-band contest) ────────────

    def efficiency_label(self) -> str:
        return "pts/qso"

    def band_efficiency(self, qsos: list) -> list:
        """
        Per-mode breakdown (Phone vs CW), mirroring the ARRL 10M approach —
        since there's only one band, the "band efficiency" panel naturally
        becomes a mode efficiency panel: which mode is producing more QSOs
        and points per unit of operating time?
        """
        mode_qsos  = defaultdict(int)
        mode_pts   = defaultdict(int)

        def _mode_label(q):
            return "CW" if _is_cw(q.get("mode")) else "Phone"

        for q in qsos:
            if q["dupe"]:
                continue
            mode_label = _mode_label(q)
            mode_qsos[mode_label] += 1
            mode_pts[mode_label]  += q.get("pts", _pts_for_mode(q.get("mode")))

        time_stats = self._band_time_stats(qsos, key_fn=_mode_label)
        result = []
        for m in mode_qsos:
            qn = mode_qsos[m]
            pn = mode_pts[m]
            ts = time_stats.get(m, {"best_hour_rate": 0, "last_qso_utc": None})
            result.append({
                "band":        m,
                "qsos":        qn,
                "pts":         pn,
                "new_shires":  pn,          # points — "new_shires" is the generic UI key
                "efficiency":  pn / qn if qn else 0,
                "pts_per_qso": _pts_for_mode("CW" if m == "CW" else "SSB"),
                **ts,
            })
        return sorted(result, key=lambda x: x["efficiency"], reverse=True)

    # ── Sparklines ────────────────────────────────────────────────────────────

    def sparkline_mults(self, q: dict, seen: set) -> int:
        """No multipliers — always 0."""
        return 0

    def running_score_for_sparkline(self, qsos_up_to_hour: list) -> int:
        """Running total of QSO points — no multiplier applied."""
        return sum(q["pts"] for q in qsos_up_to_hour if not q["dupe"])
