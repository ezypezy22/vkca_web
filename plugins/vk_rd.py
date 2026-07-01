"""
plugins/vk_rd.py
────────────────
WIA Remembrance Day Contest plugin.

Official rules (wia.org.au/members/contests/rdcontest/):
  Duration:   0300 UTC Saturday – 0300 UTC Sunday (24 hours)
  Date:       Weekend closest to 15 August
  Workable:   VK call areas, ZL (ZM), P29 (Papua New Guinea)
              WARC bands (10, 18, 24 MHz) excluded
  Dupe rule:  Not less than 3 hours between contacts on same band and mode
              (SSB and FM count as one mode; CW and RTTY count as one mode)

QSO point values (all bonuses are multiplicative):
  160m:            2 pts  (base)
  23cm or above:   2 pts  (base; i.e. ≥ 1296 MHz)
  All other bands: 1 pt   (base)
  CW or RTTY:      × 2   (mode bonus, applies regardless of band)
  0100–0600 LOCAL: × 3   (night bonus; assumed AEST = UTC+10 — corresponds
                           to 1500–2000 UTC Saturday within the contest)

Example: CW on 160m during night hours = 2 × 2 × 3 = 12 pts per QSO.

Score: Sum of all valid QSO points. There are NO multipliers.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date as date_, timedelta
from typing import Optional

from plugins.base import (
    ContestPlugin, SessionConfig, MultResult, GaugeDef,
    ACCENT, ACCENT2, ACCENT3, GREEN, MUTED,
)


# ── Band classification ───────────────────────────────────────────────────────
# Bands worth 2 base points (160m and 23cm/1296 MHz and above)
_TWO_PT_BANDS = frozenset({
    "160M", "160m",
    "23CM", "23cm", "1296",
    "13CM", "13cm", "2304", "2320",
    "9CM",  "9cm",  "3400",
    "6CM",  "6cm",  "5760",
    "3CM",  "3cm",  "10G",  "10GHZ",
    "1.25CM", "24G",
})
# WARC bands are excluded from the contest entirely
_WARC_BANDS = frozenset({"30M", "30m", "17M", "17m", "12M", "12m"})

# Night bonus window: 0100–0600 AEST (UTC+10) = 1500–2000 UTC on Saturday.
# Note: VK operators in ACST (UTC+9.5) or AWST (UTC+8) have slightly shifted
# windows — this implementation uses AEST as the standard reference.
_NIGHT_UTC_START = 15   # 15:00 UTC
_NIGHT_UTC_END   = 20   # 20:00 UTC (exclusive)

_VK_RD_WORKABLE_PREFIXES = frozenset({
    "VK", "VH", "VI", "VJ", "VL", "VM", "VN", "VZ",
    "AX",
    "ZK", "ZL", "ZM",
    "P2",
})


def _is_vkrd_workable(call: str) -> bool:
    call = call.upper().strip()
    for pfx in _VK_RD_WORKABLE_PREFIXES:
        if call.startswith(pfx):
            return True
    return False


def _vkrd_band_pts(band: str) -> int:
    """Base QSO points for the band (before mode/night multipliers)."""
    b = (band or "").upper()
    if b in _WARC_BANDS:
        return 0
    if b in _TWO_PT_BANDS:
        return 2
    return 1


def _vkrd_mode_mult(mode: str) -> int:
    """2× for CW or RTTY; 1× for phone/FM/digital."""
    m = (mode or "").upper()
    if m == "CW" or "RTTY" in m or "FSK" in m:
        return 2
    return 1


def _in_night_bonus(t) -> bool:
    """True if the QSO time falls in the 1500–2000 UTC night-bonus window."""
    if t is None:
        return False
    try:
        return _NIGHT_UTC_START <= t.hour < _NIGHT_UTC_END
    except AttributeError:
        return False


def _vkrd_qso_pts(q: dict) -> int:
    """Total points for one valid (non-dupe, workable) RD QSO."""
    band = q.get("band", "")
    if (band or "").upper() in _WARC_BANDS:
        return 0
    base = _vkrd_band_pts(band)
    if base == 0:
        return 0
    pts = base * _vkrd_mode_mult(q.get("mode", ""))
    if _in_night_bonus(q.get("time")):
        pts *= 3
    return pts


class VKRDPlugin(ContestPlugin):
    """
    WIA Remembrance Day Contest (VK_RD_RTTY / VK_RD_SSBCW).

    24-hour contest 0300 UTC Saturday – 0300 UTC Sunday.
    Score = sum of individual QSO point values (no multiplier).
    QSO points vary by band (160m/23cm+ = 2pts, others = 1pt),
    mode (CW/RTTY doubles), and time (night bonus × 3).
    """

    def identify(self, contest_name: str) -> bool:
        cn = contest_name.upper()
        return "VK_RD" in cn or "VKRD" in cn or "REMEMBRANCE" in cn

    @property
    def display_name(self) -> str:
        return "WIA Remembrance Day"

    @staticmethod
    def contest_saturday(year: int) -> date_:
        """Saturday of the weekend closest to 15 August."""
        aug15 = date_(year, 8, 15)
        wd = aug15.weekday()
        days_to_prev_sat = (wd - 5) % 7
        prev_sat = aug15 - timedelta(days=days_to_prev_sat)
        next_sat = prev_sat + timedelta(weeks=1)
        if abs((next_sat - aug15).days) < abs((prev_sat - aug15).days):
            return next_sat
        return prev_sat

    def session_config(self) -> SessionConfig:
        # 24h contest starting 0300 UTC, shown as 4 × 6h blocks.
        # The night bonus window (1500–2000 UTC) falls in the third block.
        return SessionConfig(duration_mins=360, num_sessions=4, start_hour=3)

    def mult_list(self) -> list:
        return []   # No multipliers in this contest

    def mult_label(self) -> str:
        return "QSO"

    def mult_of_qso(self, q: dict) -> Optional[str]:
        return None   # No multipliers

    def has_missing_tab(self) -> bool:
        return False

    def has_region_heat(self) -> bool:
        return False

    def has_state_bars(self) -> bool:
        return False

    def recalc_pts(self, qsos: list) -> None:
        for q in qsos:
            if q["dupe"] or not _is_vkrd_workable(q.get("call", "")):
                q["pts"] = 0
            else:
                q["pts"] = _vkrd_qso_pts(q)

    def score(self, qsos: list) -> int:
        return sum(
            q.get("pts", 0) or 0
            for q in qsos
            if not q["dupe"] and _is_vkrd_workable(q.get("call", ""))
        )

    def multipliers(self, qsos: list) -> MultResult:
        # No formal multipliers — expose unique worked callsigns so gauges
        # and the band-efficiency panel have something to display.
        worked = {q.get("call", "") for q in qsos
                  if not q["dupe"] and _is_vkrd_workable(q.get("call", ""))}
        return MultResult(worked, set(), "WORKED", "")

    def worked_primary_mults(self, qsos: list) -> set:
        return {q["call"] for q in qsos
                if not q["dupe"] and _is_vkrd_workable(q.get("call", ""))}

    def band_efficiency(self, qsos: list) -> list:
        band_qsos: dict = defaultdict(int)
        band_pts:  dict = defaultdict(int)
        band_last: dict = {}
        band_hours: dict = defaultdict(lambda: defaultdict(int))
        for q in qsos:
            if not q["dupe"] and _is_vkrd_workable(q.get("call", "")):
                b = q.get("band") or "?"
                pts = q.get("pts", 0) or 0
                band_qsos[b] += 1
                band_pts[b]  += pts
                t = q.get("time")
                if t is not None:
                    if b not in band_last or t > band_last[b]:
                        band_last[b] = t
                    h_key = t.replace(minute=0, second=0, microsecond=0)
                    band_hours[b][h_key] += 1
        result = []
        for b in band_qsos:
            qn   = band_qsos[b]
            pts  = band_pts[b]
            best = max(band_hours[b].values()) if band_hours[b] else 0
            last = band_last.get(b)
            result.append({
                "band": b, "qsos": qn, "pts": pts, "new_shires": 0,
                "efficiency": pts / qn if qn else 0,
                "best_hour_rate": best,
                "last_qso_utc": last.isoformat() if last else None,
            })
        return sorted(result, key=lambda x: x["pts"], reverse=True)

    def sparkline_mults(self, q: dict, seen: set) -> int:
        return 0   # No multipliers

    def running_score_for_sparkline(self, qsos_up_to_hour: list) -> int:
        return self.score(qsos_up_to_hour)

    def gauge_defs(self, data: dict, total_mults: int) -> list:
        valid = data.get("valid", 1) or 1
        return [
            GaugeDef("TOTAL QSOs",  "total",  "qso_max",   ACCENT(),  "{v}"),
            GaugeDef("VALID QSOs",  "valid",  "qso_max",   GREEN(),   "{v}"),
            GaugeDef("TOTAL SCORE", "score",  "score_max", ACCENT3(), "{v:,}"),
            GaugeDef("VK CONTACTS", "vk_cnt", valid,       ACCENT2(), "{v}"),
            GaugeDef("ZL CONTACTS", "zl_cnt", valid,       "#64b5f6", "{v}"),
        ]
