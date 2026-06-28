"""
plugins/vk_rd.py
────────────────
WIA Remembrance Day Contest plugin.

Contest rules:
  Workable: VK/AX, ZL/ZM, P2 (Papua New Guinea) only.
  Points: 1 per valid contact.
  Sessions: 3 × 2-hour blocks: B1 0800–1000, B2 1000–1200, B3 1200–1400 UTC.
  DupeType 3: same call workable once per 2-hour window per band.
  Scoring per block: total valid QSOs × unique prefixes worked (all bands combined).
  Final score = B1 + B2 + B3.
  Date: Saturday of the weekend closest to 15 August.

UDC: VK_RD_RTTY.UDC (author VK4SN)
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


def _vkrd_prefix(call: str) -> str:
    """
    Derive the RD contest prefix.  External territories keep their own prefix
    and do NOT collapse to plain 'VK'.
    """
    call = call.upper().strip()
    call = re.sub(r'/(P|M|QRP|MM|AM|A|B|LH)$', '', call)
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
    return call[:3]


class VKRDPlugin(ContestPlugin):
    """
    WIA Remembrance Day Contest (VK_RD_RTTY / VK_RD_SSBCW).
    3 × 2-hour blocks: 0800–1000, 1000–1200, 1200–1400 UTC.
    Score per block = total valid QSOs × unique prefixes (all bands combined).
    Final score = sum of three block scores.
    Date: weekend closest to 15 August, 0300 Sat – 0300 Sun UTC.
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
        return SessionConfig(duration_mins=120, num_sessions=3, start_hour=8)

    def mult_list(self) -> list:
        return []

    def mult_label(self) -> str:
        return "Prefix"

    def mult_of_qso(self, q: dict) -> Optional[str]:
        call = q.get("call", "")
        if call and _is_vkrd_workable(call):
            return _vkrd_prefix(call)
        return None

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
                q["pts"] = 1

    @staticmethod
    def _block_score(qsos_in_block: list) -> int:
        total_qsos = 0
        all_pfx: set = set()
        for q in qsos_in_block:
            if q["dupe"] or not _is_vkrd_workable(q.get("call", "")):
                continue
            total_qsos += 1
            pfx = _vkrd_prefix(q.get("call", ""))
            if pfx:
                all_pfx.add(pfx)
        return total_qsos * len(all_pfx)

    def score(self, qsos: list) -> int:
        blocks: dict = defaultdict(list)
        for q in qsos:
            t = q.get("time")
            if t is None:
                continue
            h = t.hour
            if   8 <= h < 10: blocks[0].append(q)
            elif 10 <= h < 12: blocks[1].append(q)
            elif 12 <= h < 14: blocks[2].append(q)
        return sum(self._block_score(blocks[b]) for b in range(3))

    def multipliers(self, qsos: list) -> MultResult:
        primary = set()
        for q in qsos:
            if q["dupe"] or not _is_vkrd_workable(q.get("call", "")):
                continue
            pfx = _vkrd_prefix(q.get("call", ""))
            if pfx:
                primary.add((pfx, q.get("band", "?")))
        return MultResult(primary, set(), "PREFIX MULTS", "")

    def worked_primary_mults(self, qsos: list) -> set:
        return {_vkrd_prefix(q["call"]) for q in qsos
                if not q["dupe"] and _is_vkrd_workable(q.get("call", ""))
                and q.get("call")}

    def band_efficiency(self, qsos: list) -> list:
        band_qsos: dict = defaultdict(int)
        band_pfx:  dict = defaultdict(set)
        for q in qsos:
            if not q["dupe"] and _is_vkrd_workable(q.get("call", "")):
                b = q.get("band") or "?"
                band_qsos[b] += 1
                band_pfx[b].add(_vkrd_prefix(q.get("call", "")))
        result = []
        for b in band_qsos:
            qn = band_qsos[b]
            mn = len(band_pfx[b])
            result.append({"band": b, "qsos": qn, "new_shires": mn,
                           "efficiency": mn / qn if qn else 0})
        return sorted(result, key=lambda x: x["efficiency"], reverse=True)

    def sparkline_mults(self, q: dict, seen: set) -> int:
        if not _is_vkrd_workable(q.get("call", "")):
            return 0
        pfx = _vkrd_prefix(q.get("call", ""))
        key = (pfx, q.get("band", "?"))
        if key not in seen:
            seen.add(key)
            return 1
        return 0

    def running_score_for_sparkline(self, qsos_up_to_hour: list) -> int:
        return self.score(qsos_up_to_hour)

    def gauge_defs(self, data: dict, total_mults: int) -> list:
        worked   = data.get("worked", 0)
        band_mult = data.get("band_mults", 0)
        soft_max = max(worked * 1.25, band_mult * 1.25, 20)
        valid    = data.get("valid", 1) or 1
        return [
            GaugeDef("TOTAL QSOs",  "total",      "qso_max",   ACCENT(),  "{v}"),
            GaugeDef("VALID QSOs",  "valid",      "qso_max",   GREEN(),   "{v}"),
            GaugeDef("TOTAL SCORE", "score",      "score_max", ACCENT3(), "{v:,}"),
            GaugeDef("PFX WORKED",  "worked",     soft_max,    ACCENT3(), "{v}"),
            GaugeDef("PFX MULTS",   "band_mults", soft_max,    GREEN(),   "{v}"),
            GaugeDef("VK CONTACTS", "vk_cnt",     valid,       ACCENT2(), "{v}"),
            GaugeDef("ZL CONTACTS", "zl_cnt",     valid,       "#64b5f6", "{v}"),
        ]
