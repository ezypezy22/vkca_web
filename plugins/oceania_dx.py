"""
plugins/oceania_dx.py
─────────────────────
Oceania DX Contest plugin (OCEANIASSB / OCEANIACW).

Official rules: https://www.oceaniadxcontest.com/rules

Contest periods (each 24 h, 06:00 UTC Sat → 06:00 UTC Sun):
  Phone (SSB): first full weekend of October
  CW:          second full weekend of October

Bands: 160M, 80M, 40M, 20M, 15M, 10M

Contact points (2026 rules, section 10):
  160M → 20 pts   80M → 10 pts   40M → 5 pts
  20M  →  1 pt    15M →  2 pts   10M → 3 pts
  A station counts once per band for contact points.

Multiplier: unique prefix per band (open-ended, no fixed list).
Final score: sum(contact points) × sum(prefix-band multipliers).

Which contacts score: an Oceania station scores every contact, inside AND
outside Oceania (2026 rules sections 4a and 10). The only contacts that
score nothing are those between two NON-Oceania stations (section 4b).
Verified against N1MM's own scoring of a real OCEANIASSB log
(vk2yi.s3db ContestNR 16, VK2YI): Oceania contacts such as ZL3YB scored
their band points and a multiplier; the only zero-point rows were dupes.
An earlier version zeroed every Oceania-to-Oceania contact and so
under-scored that log by ~3.6x — do not reintroduce that filter.

Known limitation: the non-Oceania-operator case (section 4b) is not
implemented — this app has no reliable Oceania/non-Oceania classifier
(that needs the full DXCC continent table) and its users are VK/ZL
stations. A non-Oceania operator would see contacts with other
non-Oceania stations scored here when N1MM/the contest would score them 0.
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


_OCDX_BAND_POINTS: dict = {
    "160M": 20, "80M": 10, "40M": 5,
    "20M":   1, "15M":  2, "10M": 3,
}

# Leading "prefix" of a plain call: optional leading digit, letters, then the
# WHOLE first run of digits (S52BT -> S52, OE25X -> OE25, 3D2AB -> 3D2).
_PREFIX_RE = re.compile(r'^(\d?[A-Z]+\d+)')


def _base_prefix(call: str) -> str:
    """
    Prefix of a plain (no "/") call per 2026 rules section 9: the
    letter/numeral combination at the start of the call, keeping ALL the
    numerals — the rules list HG19, OE25 and LY1000 as distinct valid
    prefixes, "any difference in the numbering, lettering, or order shall
    count as a separate prefix". (The shared _wpx_prefix helper keeps only
    the first digit, which is right for Trans-Tasman but would merge
    S52/S53/S58 into "S5" here.) A call with no numeral at all gets a zero
    after its first two letters (XEFTJW -> XE0).
    """
    m = _PREFIX_RE.match(call)
    if m:
        return m.group(1)
    return call[:2] + "0"


def _ocdx_prefix(call: str) -> str:
    """
    OCDX multiplier prefix per the 2026 rules (section 9).
    - Maritime mobile, mobile, /A, /E, /J, /P do not count as prefixes
      (/QRP, /LH, /LGT, /B are stripped too — not in the rules text, but
      they are not prefixes either).
    - Otherwise the portable designator becomes the prefix
      (N8BJQ/KH9 -> KH9, KH6XXX/W8 -> W8).
    - A portable designator without a numeral gets a zero after its second
      letter (PA/N8BJQ -> PA0).
    - A bare-digit designator replaces the call's own digit
      (RD7LB/3 -> RD3) — matches what N1MM logs for that call.
    """
    call = call.upper().strip()
    stripped = re.sub(r'/(MM?|QRP|AM?|[EJPB]|LH|LGT)$', '', call)
    if '/' in stripped:
        parts = stripped.split('/')
        short = min(parts, key=len)
        long_ = max(parts, key=len)
        if re.match(r'^\d$', short):
            m = re.match(r'^(\d?[A-Z]+)\d+', long_)
            return (m.group(1) + short) if m else _base_prefix(long_)
        if re.match(r'^[A-Z]{2,4}$', short):
            return short[:2] + "0"
        if re.match(r'^\d?[A-Z]+\d', short):
            return _base_prefix(short)
        return _base_prefix(long_)
    return _base_prefix(stripped)


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

    def picker_names(self) -> list:
        # Phone and CW are separate 24 h events on different weekends
        # (2026: 3-4 Oct and 10-11 Oct), so a new log has to say which.
        return ["Oceania DX SSB", "Oceania DX CW"]

    def contest_mode(self, contest_name: str) -> Optional[str]:
        cn = (contest_name or "").upper()
        if "CW" in cn:
            return "CW"
        if "SSB" in cn or "PHONE" in cn:
            return "SSB"
        return None

    @staticmethod
    def _first_full_weekend_october(year: int) -> date_:
        d = date_(year, 10, 1)
        days_to_sat = (5 - d.weekday()) % 7
        sat = d + timedelta(days=days_to_sat)
        while not (sat.month == 10 and (sat + timedelta(days=1)).month == 10):
            sat += timedelta(weeks=1)
        return sat

    @staticmethod
    def contest_saturday(year: int, contest_name: Optional[str] = None) -> date_:
        """Phone is the first full October weekend, CW the second (2026
        rules section 2: 3 Oct and 10 Oct). A log with no recognisable mode
        in its contest name keeps the Phone date, as before."""
        sat = OceaniaDXPlugin._first_full_weekend_october(year)
        if "CW" in (contest_name or "").upper():
            sat += timedelta(weeks=1)
        return sat

    def session_config(self) -> SessionConfig:
        return SessionConfig(duration_mins=1440, num_sessions=1, start_hour=6)

    def mult_list(self) -> list:
        return []

    def mult_label(self) -> str:
        return "WPX Prefix"

    def mult_of_qso(self, q: dict) -> Optional[str]:
        call = (q.get("call") or "").upper().strip()
        stored = (q.get("mult1") or "").strip().upper()
        # Trust N1MM's own WPXPrefix value only when it is genuinely a
        # prefix of this call. A log created by this app's standalone
        # logger has no WPXPrefix, so the loader falls back to the exchange
        # column — a serial number like "001" — which used to be accepted
        # here as if it were a prefix, making every QSO a "new multiplier".
        if stored and call.startswith(stored):
            return stored
        if call:
            return _ocdx_prefix(call)
        return None

    def band_list(self) -> list:
        # 2026 rules section 5: 160M, 80M, 40M, 20M, 15M, 10M — no WARC bands.
        return ["160M", "80M", "40M", "20M", "15M", "10M"]

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
            # Every non-dupe QSO scores its band points — including
            # Oceania-to-Oceania (see the module docstring for the rules
            # reference and the N1MM evidence).
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
            # vk_cnt / zl_cnt are the snapshot's plain VK-prefix and ZL/ZM
            # counts — not Oceania/DX totals, which the snapshot doesn't
            # compute. These were previously labelled "OC QSOs"/"DX QSOs".
            GaugeDef("VK QSOs",     "vk_cnt",     valid,       ACCENT2(), "{v}"),
            GaugeDef("ZL QSOs",     "zl_cnt",     valid,       "#64b5f6", "{v}"),
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
