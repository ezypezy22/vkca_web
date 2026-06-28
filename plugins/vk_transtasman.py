"""
plugins/vk_transtasman.py
─────────────────────────
WIA VK Trans-Tasman Contest (VKTTRTTY / VKTTSSBCW).

Contest rules:
  6 hours total: 0800–1400 UTC.
  2 sessions × 200 minutes (DupeType 3 = once per session per band).
  Multiplier: unique WPX prefixes per band — open-ended, no fixed list.
  Score: total valid points × total WPX-prefix band mults.
  Only VK / ZL / VJ / VL / AX contacts score 1 point each.

UDC: VKTTRTTY.UDC (author VK4SN)
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


# ── WPX prefix derivation ─────────────────────────────────────────────────────

def _wpx_prefix(call: str) -> str:
    """
    Derive the CQ WPX prefix from a callsign.
    Result = all letters of the prefix + first digit only.
    Examples:  VK2YI→VK2  ZL3AB→ZL3  VJ4K→VJ4  VL5A→VL5  AX3T→AX3
    """
    call = call.upper().strip()
    call = re.sub(r'/(P|M|QRP|MM|AM|A|B|LH|LGT)$', '', call)
    if '/' in call:
        parts = call.split('/')
        for part in sorted(parts, key=len, reverse=True):
            if re.search(r'[A-Z]\d', part):
                call = part
                break
        else:
            call = parts[0]
    m = re.match(r'^([A-Z]{1,4})(\d)', call)
    if m:
        return m.group(1) + m.group(2)
    m2 = re.match(r'^(\d[A-Z]{1,2})(\d)', call)
    if m2:
        return m2.group(1) + m2.group(2)
    return call[:3]


_VKTT_WORKABLE_PREFIXES = frozenset({"AX", "VI", "VJ", "VK", "VL", "ZL", "ZM"})


def _is_vktt_workable(call: str) -> bool:
    call = call.upper().strip()
    for pfx in _VKTT_WORKABLE_PREFIXES:
        if call.startswith(pfx):
            return True
    return False


class VKTransTasmanPlugin(ContestPlugin):
    """
    WIA VK Trans-Tasman Contest (VKTTRTTY / VKTTSSBCW).
    6 hours total: 0800–1400 UTC.
    2 sessions × 200 minutes (DupeType 3 = once per session per band).
    Multiplier: unique WPX prefixes per band — open-ended, no fixed list.
    Score: total valid points × total WPX-prefix band mults.
    Only VK / ZL / VJ / VL / AX contacts score 1 point each.
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
        return []   # open-ended

    def mult_label(self) -> str:
        return "WPX Prefix"

    def mult_of_qso(self, q: dict) -> Optional[str]:
        stored = (q.get("mult1") or "").strip().upper()
        if stored and re.match(r'^[A-Z]{1,4}\d$', stored):
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
        has_m1 = any(q["is_mult1"] is not None for q in qsos)
        if has_m1:
            primary = {
                (q["mult1"], q["band"])
                for q in qsos
                if not q["dupe"] and q["is_mult1"] == 1 and q["mult1"]
            }
        else:
            primary = set()
            for q in qsos:
                if q["dupe"]:
                    continue
                pfx = self.mult_of_qso(q)
                if pfx and _is_vktt_workable(q.get("call", "")):
                    primary.add((pfx, q["band"]))
        return MultResult(primary, set(), "WPX MULTS", "")

    def worked_primary_mults(self, qsos: list) -> set:
        has_m1 = any(q["is_mult1"] is not None for q in qsos)
        if has_m1:
            return {(q["mult1"], q["band"]) for q in qsos
                    if not q["dupe"] and q["is_mult1"] == 1 and q["mult1"]}
        return {(self.mult_of_qso(q), q["band"]) for q in qsos
                if not q["dupe"] and _is_vktt_workable(q.get("call", ""))
                and self.mult_of_qso(q)}

    def band_efficiency(self, qsos: list) -> list:
        band_qsos  = defaultdict(int)
        band_mults = defaultdict(set)
        for q in qsos:
            if not q["dupe"]:
                b = q["band"] or "?"
                band_qsos[b] += 1
                pfx = self.mult_of_qso(q)
                if pfx:
                    band_mults[b].add(pfx)
        result = []
        for b in band_qsos:
            qn = band_qsos[b]
            mn = len(band_mults[b])
            result.append({"band": b, "qsos": qn, "new_shires": mn,
                           "efficiency": mn / qn if qn else 0})
        return sorted(result, key=lambda x: x["efficiency"], reverse=True)

    def gauge_defs(self, data: dict, total_mults: int) -> list:
        worked   = data.get("worked", 0)
        band_mult = data.get("band_mults", 0)
        soft_max = max(worked * 1.25, band_mult * 1.25, 20)
        valid    = data.get("valid", 1) or 1
        return [
            GaugeDef("TOTAL QSOs",  "total",      "qso_max",   ACCENT(),  "{v}"),
            GaugeDef("VALID QSOs",  "valid",      "qso_max",   GREEN(),   "{v}"),
            GaugeDef("TOTAL SCORE", "score",      "score_max", ACCENT3(), "{v:,}"),
            GaugeDef("WPX WORKED",  "worked",     soft_max,    ACCENT3(), "{v}"),
            GaugeDef("WPX MULTS",   "band_mults", soft_max,    GREEN(),   "{v}"),
            GaugeDef("VK CONTACTS", "vk_cnt",     valid,       ACCENT2(), "{v}"),
            GaugeDef("ZL CONTACTS", "zl_cnt",     valid,       "#64b5f6", "{v}"),
        ]

    def sparkline_mults(self, q: dict, seen: set) -> int:
        pfx = self.mult_of_qso(q)
        if not pfx:
            return 0
        key = (pfx, q["band"])
        if q.get("is_mult1") == 1 and key not in seen:
            seen.add(key)
            return 1
        return 0
