"""
plugins/oceania_dx.py
─────────────────────
Oceania DX Contest plugin (OCEANIASSB / OCEANIACW).

Official rules: https://www.oceaniadxcontest.com/rules

Contest periods (each 24 h, 06:00 UTC Sat → 06:00 UTC Sun):
  Phone (SSB): first full weekend of October
  CW:          second full weekend of October

Bands: 160M, 80M, 40M, 20M, 15M, 10M

Contact points (Oceania station perspective):
  160M → 20 pts   80M → 10 pts   40M → 5 pts
  20M  →  1 pt    15M →  2 pts   10M → 3 pts

Multiplier: unique WPX prefix per band (open-ended, no fixed list).
Final score: sum(contact points) × sum(prefix-band multipliers).
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
# Re-use the WPX prefix helper from the Trans-Tasman plugin
from plugins.vk_transtasman import _wpx_prefix


_OCDX_BAND_POINTS: dict = {
    "160M": 20, "80M": 10, "40M": 5,
    "20M":   1, "15M":  2, "10M": 3,
}

_OCEANIA_PREFIXES: frozenset = frozenset({
    # Australia
    "VK", "VH", "VI", "VJ", "VL", "VK0", "VK9", "AX",
    # New Zealand (incl. subantarctic/Antarctic calls)
    "ZK", "ZL", "ZM",
    # Papua New Guinea
    "P2",
    # Indonesia
    "YB", "YC", "YD", "YE", "YF", "YG", "YH",
    # Philippines
    "DU", "DV", "DW", "DX",
    # US Pacific territories (KH0–KH9 all Oceania for this contest)
    "KH", "KH0", "KH2", "KH3", "KH4", "KH5", "KH6", "KH7", "KH8", "KH9",
    # Japan Pacific outliers
    "JD",
    # Pacific island nations and territories
    "A3",           # Tonga
    "E5",           # Cook Islands
    "FK",           # New Caledonia
    "FO",           # French Polynesia
    "FW",           # Wallis & Futuna
    "H4",           # Solomon Islands
    "T2",           # Tuvalu
    "T30", "T31", "T32", "T33",  # Kiribati / Banaba
    "V6",           # Micronesia
    "V7",           # Marshall Islands
    "YJ",           # Vanuatu
    "3D2",          # Fiji
    "5W",           # Samoa
})


def _is_oceania_call(call: str) -> bool:
    call = call.upper().strip()
    pfx  = _wpx_prefix(call)
    for length in (4, 3, 2):
        if pfx[:length] in _OCEANIA_PREFIXES:
            return True
    return pfx in _OCEANIA_PREFIXES


def _ocdx_prefix(call: str) -> str:
    """
    OCDX multiplier prefix per contest rules.
    Portable designators without a digit get '0' appended (e.g. PA/N8BJQ → PA0).
    /MM, /M, /P, /A, /E, /J, /LH, /QRP do NOT change the prefix.
    """
    call = call.upper().strip()
    stripped = re.sub(r'/(MM?|QRP|AM?|[EJPB]|LH|LGT)$', '', call)
    if '/' in stripped:
        parts = stripped.split('/')
        short = min(parts, key=len)
        long_ = max(parts, key=len)
        if re.match(r'^[A-Z]{2,4}$', short):
            call = short + "0"
        elif re.match(r'^[A-Z]{1,4}\d', short):
            call = short
        else:
            call = long_
    return _wpx_prefix(call)


class OceaniaDXPlugin(ContestPlugin):
    """
    Oceania DX Contest (OCEANIASSB / OCEANIACW).
    24-hour contest: 06:00 UTC Saturday → 06:00 UTC Sunday.
    Scoring: band-dependent points × WPX-prefix band multipliers.
    """

    def identify(self, contest_name: str) -> bool:
        cn = contest_name.upper()
        return "OCEANIASSB" in cn or "OCEANIACW" in cn or (
            "OCEANIA" in cn and "DX" in cn
        )

    @property
    def display_name(self) -> str:
        return "Oceania DX"

    @staticmethod
    def _first_full_weekend_october(year: int) -> date_:
        d = date_(year, 10, 1)
        days_to_sat = (5 - d.weekday()) % 7
        sat = d + timedelta(days=days_to_sat)
        while not (sat.month == 10 and (sat + timedelta(days=1)).month == 10):
            sat += timedelta(weeks=1)
        return sat

    @staticmethod
    def contest_saturday(year: int) -> date_:
        return OceaniaDXPlugin._first_full_weekend_october(year)

    def session_config(self) -> SessionConfig:
        return SessionConfig(duration_mins=1440, num_sessions=1, start_hour=6)

    def mult_list(self) -> list:
        return []

    def mult_label(self) -> str:
        return "WPX Prefix"

    def mult_of_qso(self, q: dict) -> Optional[str]:
        stored = (q.get("mult1") or "").strip().upper()
        if stored and re.match(r'^[A-Z0-9]{1,5}$', stored):
            return stored
        call = q.get("call", "")
        if call:
            return _ocdx_prefix(call)
        return None

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
                continue
            # Oceania↔world only: both parties must not be the same side.
            # Assumes Oceania operator perspective (standard for VK/ZL users):
            # the worked call must be non-Oceania for the QSO to score.
            call = q.get("call", "")
            if _is_oceania_call(call):
                q["pts"] = 0
                continue
            band = (q.get("band") or "").upper()
            q["pts"] = _OCDX_BAND_POINTS.get(band, 1)

    def score(self, qsos: list) -> int:
        mr = self.multipliers(qsos)
        pts = sum(q["pts"] for q in qsos if not q["dupe"])
        return pts * len(mr.primary_mults) if mr.primary_mults else pts

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
                if pfx:
                    primary.add((pfx, q.get("band", "?")))
        return MultResult(primary, set(), "WPX MULTS", "")

    def worked_primary_mults(self, qsos: list) -> set:
        has_m1 = any(q["is_mult1"] is not None for q in qsos)
        if has_m1:
            return {(q["mult1"], q["band"]) for q in qsos
                    if not q["dupe"] and q["is_mult1"] == 1 and q["mult1"]}
        return {(_ocdx_prefix(q["call"]), q["band"]) for q in qsos
                if not q["dupe"] and q.get("call")}

    def band_efficiency(self, qsos: list) -> list:
        band_qsos  = defaultdict(int)
        band_pts   = defaultdict(int)
        band_mults = defaultdict(set)
        for q in qsos:
            if not q["dupe"]:
                b = q.get("band") or "?"
                band_qsos[b]  += 1
                band_pts[b]   += q.get("pts", 0)
                pfx = self.mult_of_qso(q)
                if pfx:
                    band_mults[b].add(pfx)
        time_stats = self._band_time_stats(qsos)
        result = []
        for b in band_qsos:
            qn = band_qsos[b]
            mn = len(band_mults[b])
            ts = time_stats.get(b, {"best_hour_rate": 0, "last_qso_utc": None})
            result.append({
                "band": b, "qsos": qn, "new_shires": mn,
                "pts":          band_pts[b],
                "efficiency":   mn / qn if qn else 0,
                "pts_per_qso":  band_pts[b] / qn if qn else 0,
                **ts,
            })
        return sorted(result, key=lambda x: x["pts_per_qso"], reverse=True)

    def gauge_defs(self, data: dict, total_mults: int) -> list:
        worked   = data.get("worked", 0)
        bm       = data.get("band_mults", 0)
        soft_max = max(worked * 1.25, bm * 1.25, 20)
        valid    = data.get("valid", 1) or 1
        return [
            GaugeDef("TOTAL QSOs",  "total",      "qso_max",   ACCENT(),  "{v}"),
            GaugeDef("VALID QSOs",  "valid",      "qso_max",   GREEN(),   "{v}"),
            GaugeDef("TOTAL SCORE", "score",      "score_max", ACCENT3(), "{v:,}"),
            GaugeDef("WPX WORKED",  "worked",     soft_max,    ACCENT3(), "{v}"),
            GaugeDef("WPX MULTS",   "band_mults", soft_max,    GREEN(),   "{v}"),
            GaugeDef("OC QSOs",     "vk_cnt",     valid,       ACCENT2(), "{v}"),
            GaugeDef("DX QSOs",     "zl_cnt",     valid,       "#64b5f6", "{v}"),
        ]

    def sparkline_mults(self, q: dict, seen: set) -> int:
        pfx = self.mult_of_qso(q)
        if not pfx:
            return 0
        key = (pfx, q.get("band", "?"))
        if key not in seen:
            seen.add(key)
            return 1
        return 0
