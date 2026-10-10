"""
plugins/vk_vhfuhf.py
────────────────────
WIA VHF/UHF Field Day plugin (Summer, Winter and Spring events — one set of
rules, run three times a year). Rules: "2026 Spring VHF-UHF Field Day Rules"
(wia.org.au/members/contests/vhfuhf/); N1MM definition: WIA_VHFUHF.udc by VK2QJ
(vk4sn.com/Contests/N1MMVK).

Exchange     RS(T) + serial number + 6-character grid locator.
Scoring      Distance only, from sub-square centre to sub-square centre:
               1 point per km x the band multiplier (Table 1 below); on 6m, 2m
               and 70cm only, distance beyond 700 km counts 1 point per 100 km
               ("flattening"). Each contact is rounded up to a whole point; a
               contact inside the same sub-square scores nothing. Score is the
               sum of the contact points (no other multiplier).
Re-working   A station may be worked again on a band after 2 hours (any mode).
             If either station is in a different 4-character square, the
             repeat may be made immediately; moving back to an earlier square
             restores the 2-hour limit for stations already worked from there.
Roaming      Portable stations may move during the contest, so every QSO
             carries the operator's own locator at the time (DXLOG
             RoverLocation, the column N1MM uses for a rover's position).

Where the N1MM UDC and the rules differ we follow the rules (what the VK Log
Checker scores): the UDC's distance table flattens every band and has typos
(e.g. "10501/10600/700", "9901/9000/783").
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date as date_, datetime, timedelta
from typing import Optional

import maidenhead
from plugins.base import (
    ContestPlugin,
    GaugeDef,
    MultResult,
    SessionConfig,
    ACCENT,
    ACCENT2,
    ACCENT3,
    GREEN,
)

# ── Rules, Table 1: band scoring multiplier ──────────────────────────────────
BAND_MULT = {
    "6M": 1.7, "2M": 1.0, "70CM": 2.7, "23CM": 3.7, "13CM": 4.4, "9CM": 5.4,
    "6CM": 6.4, "3CM": 7.4,
    # "24 GHz & up" — all score 10.
    "1.2CM": 10.0, "6MM": 10.0, "4MM": 10.0, "2.5MM": 10.0, "2MM": 10.0, "1MM": 10.0,
}
# Bands where distance beyond 700 km is flattened to 1 pt per 100 km.
_FLATTEN_BANDS = {"6M", "2M", "70CM"}
_FLATTEN_AFTER_KM = 700.0
_REWORK = timedelta(hours=2)


def contact_points(km: Optional[float], band: str) -> Optional[int]:
    """Points for one contact of `km` kilometres on `band`, or None if the
    band has no multiplier (so the caller keeps whatever it had)."""
    mult = BAND_MULT.get((band or "").upper())
    if km is None or mult is None:
        return None
    if (band or "").upper() in _FLATTEN_BANDS and km > _FLATTEN_AFTER_KM:
        base = _FLATTEN_AFTER_KM + (km - _FLATTEN_AFTER_KM) / 100.0
    else:
        base = km
    return int(math.ceil(round(base * mult, 6)))


def _nth_saturday(year: int, month: int, n: int) -> date_:
    d = date_(year, month, 1)
    first = d + timedelta(days=(5 - d.weekday()) % 7)
    return first + timedelta(weeks=n - 1)


def _season_of(contest_name: Optional[str]) -> Optional[str]:
    cn = (contest_name or "").upper()
    for s in ("SUMMER", "WINTER", "SPRING"):
        if s in cn:
            return s
    return None


def _season_saturday(year: int, season: str) -> date_:
    """Saturday the event starts. Winter / Spring: third weekend of June /
    September. Summer: first weekend of January up to 2026, second full weekend
    from 2027 (the rules move it to dodge the New Year clash)."""
    if season == "WINTER":
        return _nth_saturday(year, 6, 3)
    if season == "SPRING":
        return _nth_saturday(year, 9, 3)
    return _nth_saturday(year, 1, 2 if year >= 2027 else 1)


class VKVHFUHFPlugin(ContestPlugin):
    """WIA VHF/UHF Field Day — distance-scored, roaming-friendly."""

    roaming_locator   = True
    vhf_band_names    = True
    rework_window_hours = 2.0
    rework_by_mode    = False
    cabrillo_contest_id = "WIA_VHFUHF"   # the UDC's CabrilloName

    # ── Identity ──────────────────────────────────────────────────────────────

    def identify(self, contest_name: str) -> bool:
        cn = re.sub(r"[^A-Z0-9]", "", (contest_name or "").upper())
        return "VHFUHF" in cn

    @property
    def display_name(self) -> str:
        return "WIA VHF/UHF Field Day"

    def picker_names(self) -> list:
        return ["WIA VHF-UHF Field Day Summer", "WIA VHF-UHF Field Day Winter",
                "WIA VHF-UHF Field Day Spring"]

    @property
    def dupe_rule_text(self) -> str:
        return ("A station may be worked again on a band after 2 hours (any mode). "
                "If either station is in a different 4-character square, you may work "
                "them again immediately; if a station moves back to an earlier square, "
                "the 2-hour limit applies again to anyone already worked from there.")

    # ── Dates / session ───────────────────────────────────────────────────────

    @staticmethod
    def contest_saturday(year: int, contest_name: Optional[str] = None) -> Optional[date_]:
        """Start date for a log created here (named with its season). An N1MM
        log's ContestName (WIA_VHFUHF) carries no season, so return None and let
        the log's own stored start date decide."""
        season = _season_of(contest_name)
        return _season_saturday(year, season) if season else None

    def new_log_start(self, contest_name: str, now: datetime) -> Optional[datetime]:
        """Start of the next (or current) running of this season's event."""
        season = _season_of(contest_name)
        if not season:
            return None
        for y in (now.year, now.year + 1):
            sat = _season_saturday(y, season)
            start = datetime(sat.year, sat.month, sat.day, 1, 0, 0)
            if start + timedelta(days=1, hours=1) >= now:
                return start
        return None

    def start_hour_for(self, my_call: Optional[str], contest_name: Optional[str] = None) -> int:
        """0100 UTC Saturday; VK6 starts later (0300 Winter, 0400 otherwise)."""
        if (my_call or "").upper().startswith("VK6"):
            return 3 if _season_of(contest_name) == "WINTER" else 4
        return 1

    def session_config(self) -> SessionConfig:
        # One continuous 24 h event: 0100 UTC Saturday to 0059 UTC Sunday.
        return SessionConfig(duration_mins=1440, num_sessions=1, label_prefix="D", start_hour=1)

    def uses_block_structure(self) -> bool:
        return False

    # ── Entry form ────────────────────────────────────────────────────────────

    def entry_fields(self) -> Optional[dict]:
        return {"rcvd_nr": True, "rcvd_grid": True, "sent_grid": True}

    def band_list(self) -> list:
        return ["6M", "2M", "70CM", "23CM", "13CM", "9CM", "6CM", "3CM", "1.2CM"]

    # ── Multiplier contract (there is no multiplier; squares are informational) ──

    def mult_list(self) -> list:
        return []

    def mult_label(self) -> str:
        return "Square"

    def mult_of_qso(self, q: dict) -> Optional[str]:
        return maidenhead.square4(q.get("grid")) or None

    def has_missing_tab(self) -> bool:
        return False

    def has_region_heat(self) -> bool:
        return False

    def has_state_bars(self) -> bool:
        return False

    # ── Re-working (dupes) ────────────────────────────────────────────────────

    @staticmethod
    def _same_squares(a_my, a_their, b_my, b_their) -> bool:
        return (maidenhead.square4(a_my) == maidenhead.square4(b_my)
                and maidenhead.square4(a_their) == maidenhead.square4(b_their))

    def is_repeat_contact(self, new: dict, prior: list) -> bool:
        for q in prior:
            if q["dupe"] or q["call"] != new["call"] or q["band"] != new["band"]:
                continue
            if not self._same_squares(q.get("my_grid"), q.get("grid"),
                                      new.get("my_grid"), new.get("grid")):
                continue
            if q.get("time") is None or new.get("time") is None or \
                    (new["time"] - q["time"]) < _REWORK:
                return True
        return False

    # ── Scoring ───────────────────────────────────────────────────────────────

    def recalc_pts(self, qsos: list) -> None:
        # Dupes, from the QSOs' own timestamps and squares — N1MM's UDC can only
        # express "same call + band within 120 minutes", with no way to let a
        # move to a new square reopen the station (DupeType=2, DupeQSOMinutesAgo=120).
        groups: dict = defaultdict(list)
        for q in qsos:
            if q.get("time") is not None:
                groups[(q["call"], q["band"])].append(q)
        for group in groups.values():
            group.sort(key=lambda q: q["time"])
            valid: list = []
            for q in group:
                q["dupe"] = 1 if self.is_repeat_contact(q, valid) else 0
                if not q["dupe"]:
                    valid.append(q)

        for q in qsos:
            km = maidenhead.distance_km(q.get("my_grid"), q.get("grid"))
            q["km"] = km
            if q["dupe"]:
                q["pts"] = 0
                continue
            same_subsquare = (maidenhead.is_full_locator(q.get("grid"))
                              and q.get("grid") == q.get("my_grid"))
            if same_subsquare:
                q["pts"] = 0
                continue
            pts = contact_points(km, q.get("band"))
            if pts is not None:
                q["pts"] = pts
            # else: no locator / unknown band — keep whatever the log recorded.

    def score(self, qsos: list) -> int:
        return sum((q.get("pts") or 0) for q in qsos if not q["dupe"])

    def multipliers(self, qsos: list) -> MultResult:
        squares = {(maidenhead.square4(q.get("grid")), q.get("band"))
                   for q in qsos if not q["dupe"] and maidenhead.square4(q.get("grid"))}
        return MultResult(squares, set(), "Squares", "")

    def worked_primary_mults(self, qsos: list) -> set:
        return {maidenhead.square4(q.get("grid")) for q in qsos
                if not q["dupe"] and maidenhead.square4(q.get("grid"))}

    def sparkline_mults(self, q: dict, seen: set) -> int:
        return 0

    def running_score_for_sparkline(self, qsos_up_to_hour: list) -> int:
        return self.score(qsos_up_to_hour)

    def post_snapshot(self, snap: dict, qsos: list) -> None:
        valid = [q for q in qsos if not q["dupe"]]
        kms = [q["km"] for q in valid if q.get("km") is not None]
        snap["squares"]    = len(self.worked_primary_mults(qsos))
        snap["best_km"]    = int(round(max(kms))) if kms else 0
        snap["avg_km"]     = int(round(sum(kms) / len(kms))) if kms else 0
        snap["bands_cnt"]  = len({q["band"] for q in valid})

    def efficiency_label(self) -> str:
        return "pts/qso"

    def band_efficiency(self, qsos: list) -> list:
        band_qsos: dict = defaultdict(int)
        band_pts: dict = defaultdict(int)
        band_last: dict = {}
        band_hours: dict = defaultdict(lambda: defaultdict(int))
        for q in qsos:
            if q["dupe"]:
                continue
            b = q.get("band") or "?"
            band_qsos[b] += 1
            band_pts[b] += q.get("pts", 0) or 0
            t = q.get("time")
            if t is not None:
                if b not in band_last or t > band_last[b]:
                    band_last[b] = t
                band_hours[b][t.replace(minute=0, second=0, microsecond=0)] += 1
        out = []
        for b, qn in band_qsos.items():
            last = band_last.get(b)
            out.append({
                "band": b, "qsos": qn, "pts": band_pts[b], "new_shires": 0,
                "efficiency": band_pts[b] / qn if qn else 0,
                "best_hour_rate": max(band_hours[b].values()) if band_hours[b] else 0,
                "last_qso_utc": last.isoformat() if last else None,
            })
        return sorted(out, key=lambda x: x["pts"], reverse=True)

    def gauge_defs(self, data: dict, total_mults: int) -> list:
        return [
            GaugeDef("TOTAL QSOs",  "total",     "qso_max",   ACCENT(),  "{v}"),
            GaugeDef("VALID QSOs",  "valid",     "qso_max",   GREEN(),   "{v}"),
            GaugeDef("TOTAL SCORE", "score",     "score_max", ACCENT3(), "{v:,}"),
            GaugeDef("SQUARES",     "squares",   max(data.get("squares", 0) * 1.25, 20), ACCENT2(), "{v}"),
            GaugeDef("BEST KM",     "best_km",   max(data.get("best_km", 0) * 1.25, 500), "#64b5f6", "{v:,}"),
            GaugeDef("AVG KM",      "avg_km",    max(data.get("avg_km", 0) * 1.5, 300), GREEN(), "{v:,}"),
        ]

    # ── Standalone logging ────────────────────────────────────────────────────

    def standalone_qso_fields(self, call, band, mode, exchange, prior_qsos, my_call, fields=None):
        """Distance and points for a QSO logged in this app. `fields` carries
        the worked station's locator (GridSquare) and ours (RoverLocation)."""
        fields = fields or {}
        theirs, mine = fields.get("GridSquare"), fields.get("RoverLocation")
        km = maidenhead.distance_km(mine, theirs)
        out: dict = {}
        if km is not None:
            out["_distance_km"] = km
            if maidenhead.is_full_locator(theirs) and maidenhead.norm(theirs) == maidenhead.norm(mine):
                out["Points"] = 0
            else:
                pts = contact_points(km, band)
                if pts is not None:
                    out["Points"] = pts
        return out


def register() -> VKVHFUHFPlugin:
    return VKVHFUHFPlugin()
