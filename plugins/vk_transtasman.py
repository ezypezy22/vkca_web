"""
plugins/vk_transtasman.py
─────────────────────────
WIA VK Trans-Tasman Contest (VKTTRTTY / VKTTSSBCW).

Written rules (wia.org.au/members/contests/transtasman/), verbatim:
  6 hours total: 0800–1400 UTC, 3 × 2-hour blocks.
  "Points are only awarded for valid contacts between VK and ZL stations."
  "Every different Prefix used by VK or ZL stations is a valid multiplier
  and credit can be claimed once per band per block."
  Read literally, both points AND multipliers are VK/ZL-only, and
  multipliers reset every 2-hour block.

RESOLVED AGAINST N1MM'S OWN UDC CONFIG FILE (udc/VKTTRTTY.UDC, author
VK4SN — 2026-07 issue #11 investigation), which is more authoritative than
either the written rules text or one observed log, since it's N1MM's own
declared scoring configuration:
  - `ResetMultsEverySession = 0` — confirms multipliers do NOT reset per
    block, contradicting the written rule. This plugin follows the UDC:
    multipliers are unique (prefix, band) for the whole contest.
  - `CountMultOnlyFor = AX, VI, VJ, VK, VL, ZL, ZM` — confirms multipliers
    ARE restricted to workable stations, matching the written rule. A real
    2025 VK4M log's IsMultiplier1 flags initially looked like they
    contradicted this (non-VK/ZL station N9RV was credited as a
    multiplier there), but reproducing it live in N1MM (a fresh N9RV QSO,
    2026-07-12) confirmed that's a genuine N1MM bug — N1MM not correctly
    enforcing its own declared CountMultOnlyFor — not intended behaviour
    to replicate. This plugin follows the UDC's declared config instead.
Net effect: same as the written rule for mult eligibility (VK/ZL-only),
but no per-block reset. Points (recalc_pts) remain VK/ZL-only either way.

UDC: VKTTRTTY.UDC (author VK4SN)
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date as date_
from datetime import timedelta
from typing import Optional

from plugins.base import (
    ACCENT,
    ACCENT2,
    ACCENT3,
    GREEN,
    MUTED,
    ContestPlugin,
    GaugeDef,
    MultResult,
    SessionConfig,
)

# ── WPX prefix derivation ─────────────────────────────────────────────────────


def _wpx_prefix(call: str) -> str:
    """
    Derive the CQ WPX prefix from a callsign.
    Result = all letters of the prefix + first digit only.
    Examples:  VK2YI→VK2  ZL3AB→ZL3  VJ4K→VJ4  VL5A→VL5  AX3T→AX3
    """
    call = call.upper().strip()
    call = re.sub(r"/(P|M|QRP|MM|AM|A|B|LH|LGT)$", "", call)
    if "/" in call:
        parts = call.split("/")
        for part in sorted(parts, key=len, reverse=True):
            if re.search(r"[A-Z]\d", part):
                call = part
                break
        else:
            call = parts[0]
    m = re.match(r"^([A-Z]{1,4})(\d)", call)
    if m:
        return m.group(1) + m.group(2)
    m2 = re.match(r"^(\d[A-Z]{1,2})(\d)", call)
    if m2:
        return m2.group(1) + m2.group(2)
    return call[:3]


_VKTT_WORKABLE_PREFIXES = frozenset({"AX", "VI", "VJ", "VK", "VL", "ZL", "ZM"})


def _is_vktt_workable(call: str) -> bool:
    """Eligibility for BOTH points and multipliers (VK/ZL/etc.) — matches
    N1MM's own PointsPerContact and CountMultOnlyFor UDC config. See module
    docstring for why this does NOT match N9RV-type multiplier credit seen
    in one real log — that was a reproduced N1MM bug, not intended."""
    call = call.upper().strip()
    for pfx in _VKTT_WORKABLE_PREFIXES:
        if call.startswith(pfx):
            return True
    return False


class VKTransTasmanPlugin(ContestPlugin):
    """
    WIA VK Trans-Tasman Contest (VKTTRTTY / VKTTSSBCW).
    6 hours: 0800–1400 UTC in 3 × 2-hour blocks (block structure affects
    session/rate reporting only — per N1MM's own UDC config, multipliers do
    NOT reset per block despite the written rule; see module docstring).
    Multipliers are unique WPX prefixes per band, VK/ZL stations only.
    Score = total QSO points (VK/ZL-only) × total prefix-band multipliers.
    """

    def identify(self, contest_name: str) -> bool:
        cn = contest_name.upper()
        return "VKTT" in cn or "TRANS-TASMAN" in cn or "TRANSTASMAN" in cn

    @property
    def display_name(self) -> str:
        return "VK Trans-Tasman"

    @staticmethod
    def contest_saturday(year: int) -> date_:
        """Saturday of the third full weekend (Sat+Sun both in July) of July."""
        d = date_(year, 7, 1)
        days_to_sat = (5 - d.weekday()) % 7
        first_sat = d + timedelta(days=days_to_sat)
        count = 0
        sat = first_sat
        while True:
            sun = sat + timedelta(days=1)
            if sat.month == 7 and sun.month == 7:
                count += 1
                if count == 3:
                    return sat
            sat += timedelta(weeks=1)
            if sat.month > 7:
                raise ValueError(f"Could not find third full weekend in July {year}")

    def session_config(self) -> SessionConfig:
        return SessionConfig(duration_mins=120, num_sessions=3, start_hour=8)

    def mult_list(self) -> list:
        return []  # open-ended

    def mult_label(self) -> str:
        return "WPX Prefix"

    def mult_of_qso(self, q: dict) -> Optional[str]:
        stored = (q.get("mult1") or "").strip().upper()
        if stored and re.match(r"^[A-Z]{1,4}\d$", stored):
            return stored
        call = q.get("call", "")
        if call:
            return _wpx_prefix(call)
        return None

    def region_of_mult(self, m: str) -> Optional[str]:
        return None

    def region_list(self) -> list:
        return []

    def has_missing_tab(self) -> bool:
        return False

    def has_region_heat(self) -> bool:
        return False

    def has_state_bars(self) -> bool:
        return False

    @property
    def preferred_exchange_columns(self):
        # N1MM's ADIF export uses "WPXPrefix" (capitalisation varies by
        # exporter version — not1mm writes "wpxprefix"). Both must always
        # be checked because column matching in contest_log.py's load()
        # tests only column *existence*, not population.
        return ["WPXPrefix", "wpxprefix"]

    def recalc_pts(self, qsos: list) -> None:
        for q in qsos:
            if q["dupe"]:
                q["pts"] = 0
            elif _is_vktt_workable(q.get("call", "")):
                q["pts"] = 1
            else:
                q["pts"] = 0

    def score(self, qsos: list) -> int:
        mr = self.multipliers(qsos)
        pts = sum(q["pts"] for q in qsos if not q["dupe"])
        total_mults = len(mr.primary_mults) + len(mr.secondary_mults)
        return pts * total_mults if total_mults else pts

    def multipliers(self, qsos: list) -> MultResult:
        # Unique (prefix, band) pairs for the whole contest, VK/ZL stations
        # only — matches N1MM's own UDC config (CountMultOnlyFor + no
        # per-block reset), not one log's buggy live output. See module
        # docstring.
        primary: set = set()
        for q in qsos:
            if q["dupe"]:
                continue
            pfx = self.mult_of_qso(q)
            if pfx and _is_vktt_workable(q.get("call", "")):
                primary.add((pfx, q["band"]))
        return MultResult(primary, set(), "WPX MULTS", "")

    def worked_primary_mults(self, qsos: list) -> set:
        # Same (pfx, band) pairs as multipliers() — kept as a separate method
        # only because it's part of the ContestPlugin interface.
        return self.multipliers(qsos).primary_mults

    def band_efficiency(self, qsos: list) -> list:
        # Custom override (rather than the base class default) because mults
        # here are WPX prefixes derived per-QSO rather than looked up via
        # the base class's generic `mult1 in ml_set` check, which doesn't
        # apply to VKTT's open-ended, computed-not-stored prefix mults.
        band_qsos = defaultdict(int)
        band_pts = defaultdict(int)
        band_mults = defaultdict(set)
        band_last = {}
        band_hours = defaultdict(lambda: defaultdict(int))
        for q in qsos:
            if q["dupe"]:
                continue
            b = q["band"] or "?"
            band_qsos[b] += 1
            band_pts[b] += q.get("pts", 0) or 0
            if _is_vktt_workable(q.get("call", "")):
                pfx = self.mult_of_qso(q)
                if pfx:
                    band_mults[b].add(pfx)
            t = q.get("time")
            if t is not None:
                if b not in band_last or t > band_last[b]:
                    band_last[b] = t
                h_key = t.replace(minute=0, second=0, microsecond=0)
                band_hours[b][h_key] += 1
        result = []
        for b in band_qsos:
            qn = band_qsos[b]
            mn = len(band_mults[b])
            best = max(band_hours[b].values()) if band_hours[b] else 0
            last = band_last.get(b)
            result.append(
                {
                    "band": b,
                    "qsos": qn,
                    "pts": band_pts[b],
                    "new_shires": mn,
                    "efficiency": mn / qn if qn else 0,
                    "best_hour_rate": best,
                    "last_qso_utc": last.isoformat() if last else None,
                }
            )
        return sorted(result, key=lambda x: x["efficiency"], reverse=True)

    def gauge_defs(self, data: dict, total_mults: int) -> list:
        worked = data.get("worked", 0)
        band_mult = data.get("band_mults", 0)
        soft_max = max(worked * 1.25, band_mult * 1.25, 20)
        valid = data.get("valid", 1) or 1
        return [
            GaugeDef("TOTAL QSOs", "total", "qso_max", ACCENT(), "{v}"),
            GaugeDef("VALID QSOs", "valid", "qso_max", GREEN(), "{v}"),
            GaugeDef("TOTAL SCORE", "score", "score_max", ACCENT3(), "{v:,}"),
            GaugeDef("WPX WORKED", "worked", soft_max, ACCENT3(), "{v}"),
            GaugeDef("WPX MULTS", "band_mults", soft_max, GREEN(), "{v}"),
            GaugeDef("VK CONTACTS", "vk_cnt", valid, ACCENT2(), "{v}"),
            GaugeDef("ZL CONTACTS", "zl_cnt", valid, "#64b5f6", "{v}"),
        ]

    def sparkline_mults(self, q: dict, seen: set) -> int:
        pfx = self.mult_of_qso(q)
        if not pfx:
            return 0
        key = (pfx, q["band"])
        if q.get("is_mult1") and key not in seen:
            seen.add(key)
            return 1
        return 0
