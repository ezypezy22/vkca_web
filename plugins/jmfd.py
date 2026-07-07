"""
plugins/jmfd.py
────────────────
WIA John Moyle Memorial Field Day (JMMFD) plugin.

Official rules: https://www.wia.org.au/members/contests/johnmoyle/
(JMMFD_2027_RULES.pdf, "2026 Onwards" ruleset, last updated 27/4/2026)

Duration:  0100 UTC Saturday – 0059 UTC Sunday (24 hours), 3rd full
           weekend in March.
Bands:     HF — 160, 80, 40, 20, 15, 10m.
           VHF/UHF/SHF — 50 MHz to 241 GHz.
           No WARC bands (30/17/12m) — IARU regulation.
Modes:     Phone (SSB/AM/FM), CW, Mixed.

TIME BLOCKS
    Eight consecutive 3-hour blocks starting at 0100 UTC:
    0100–0400, 0400–0700, 0700–1000, 1000–1300, 1300–1600,
    1600–1900, 1900–2200, 2200–0100.
    Re-working rule: a station is workable once per band per mode
    per block (dupe reset every 3 hours — handled by N1MM's own
    DupeType logic upstream; this plugin trusts the loaded "dupe" flag).

SCORING (per QSO, portable and home stations alike)
    Phone → 1 point,  CW → 2 points.
    This app is built for VK/ZL/P2 operators, so — per the rules'
    Objective section ("All VK, ZL and P2 stations can claim points for
    all contacts, with any station in the world") — every non-dupe QSO
    scores, regardless of who's on the other end.

MULTIPLIER
    "Each new prefix from VK, P2, and ZL stations count as a multiplier
    credit once per band per mode per block." Prefix = WPX-style prefix
    (leading letters + first digit, e.g. VK4, VL4, VJ4, ZL1, ZM1 — all
    given as explicit examples in the rules, confirming VK's club/
    special-event prefix families and ZL/ZM both count).
    Crucially: a QSO only yields a multiplier if the WORKED station is
    VK/ZL/P2 — working JA, W, G, etc. scores points but no multiplier.

HF / VHF+ SPLIT — THE KEY SCORING WRINKLE
    "Add up the Multipliers for each block and multiply by the total
    points. Do this separately for each HF log QSO's and VHF QSO's.
    Do not use mults for VHF when calculating HF scores and vice versa."
    The rules explicitly warn that N1MM's own running score combines
    both, overstating the real (separately-judged) result. This plugin
    computes HF and VHF+ subtotals independently — each as
    (that category's points) × (that category's own prefix/band/mode/
    block mults) — then sums them only for a single "TOTAL SCORE"
    display figure; see score()/post_snapshot() below.

CATEGORIES
    Single-Op / Multi-One / Multi-Multi × Portable/Home × 6h/24h, plus
    a Youth overlay. None of these change the scoring formula itself
    (no power/category-based point bonuses in this contest) except the
    6-hour category's rule that only the first six consecutive hours
    from the first QSO count. That 6-hour clipping isn't modelled here
    (Cabrillo CATEGORY-TIME isn't available from the live N1MM DB this
    app reads) — scores shown reflect the full log; 6-hour entrants
    should compare only their own first-six-hours window by eye.

N1MM+ Logger: ContestName "WIA-JMMFD" (UDC WIA-JMMFD.udc).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date as date_, timedelta
from typing import Optional

from plugins.base import (
    ContestPlugin, SessionConfig, MultResult, GaugeDef,
    ACCENT, ACCENT2, ACCENT3, GREEN, MUTED,
)
# Re-use the WPX-style prefix deriver already shared by vk_transtasman.py /
# oceania_dx.py rather than duplicating the same regex a fourth time.
from plugins.vk_transtasman import _wpx_prefix


# ── Band classification ───────────────────────────────────────────────────────

_HF_BANDS   = frozenset({"160M", "80M", "40M", "20M", "15M", "10M"})
_WARC_BANDS = frozenset({"30M", "17M", "12M"})   # excluded from the contest entirely


def _band_class(band: str) -> str:
    """
    'HF', 'VHF' (50 MHz and up — including any band name this app's
    frequency table doesn't recognise, e.g. raw '432.00MHz'/'1.2G'
    strings for UHF/SHF, which by elimination can only be VHF+ since
    JMFD has exactly two band categories), or 'X' for excluded WARC bands.
    """
    b = (band or "").upper()
    if b in _WARC_BANDS:
        return "X"
    if b in _HF_BANDS:
        return "HF"
    return "VHF"


# ── Multiplier eligibility (VK / ZL / P2 only) ────────────────────────────────
# Same family as vk_rd.py's workable-prefix set: VK's club/special-event
# callsign families (VH/VI/VJ/VL/VM/VN/VZ/AX) plus ZL's family (ZK/ZL/ZM)
# and P2 (PNG). The rules' own examples ("VL4, VJ4, ZM1") confirm each of
# these families counts as its own distinct new prefix.
_JMFD_MULT_PREFIXES = frozenset({
    "VK", "VH", "VI", "VJ", "VL", "VM", "VN", "VZ", "AX",
    "ZK", "ZL", "ZM",
    "P2",
})


def _is_jmfd_mult_eligible(call: str) -> bool:
    call = (call or "").upper().strip()
    for pfx in _JMFD_MULT_PREFIXES:
        if call.startswith(pfx):
            return True
    return False


# ── Time blocks (eight 3-hour blocks starting 0100 UTC) ──────────────────────

def _jmfd_block(t) -> int:
    """0–7 for the QSO's 3-hour block, or -1 if no timestamp.
    Purely hour-of-day based (like vk_rd.py's night-bonus check) since the
    contest never spans more than the one Sat-0100→Sun-0059 UTC window."""
    if t is None:
        return -1
    h = t.hour
    if h == 0:
        return 7   # 0000–0100 UTC Sunday wraps into the final block
    return (h - 1) // 3


def _pts_for_mode(mode: str) -> int:
    """CW = 2 pts, all phone modes (SSB/AM/FM) = 1 pt. No digital modes
    in this contest's rules."""
    return 2 if (mode or "").upper() == "CW" else 1


# ═════════════════════════════════════════════════════════════════════════════
# Plugin
# ═════════════════════════════════════════════════════════════════════════════

class JMFDPlugin(ContestPlugin):
    """
    WIA John Moyle Memorial Field Day.

    24-hour contest, 0100 UTC Saturday – 0059 UTC Sunday, 3rd full
    weekend in March. Scored as two independent categories — HF and
    VHF+ — each (points × that category's own prefix/band/mode/block
    multipliers); see module docstring for why they must never combine.
    """

    def identify(self, contest_name: str) -> bool:
        cn = contest_name.upper().replace(" ", "").replace("_", "").replace("-", "")
        keywords = ("JMMFD", "JMFD", "JOHNMOYLE", "MOYLEFIELDDAY")
        return any(kw in cn for kw in keywords)

    @property
    def display_name(self) -> str:
        return "John Moyle Field Day"

    @staticmethod
    def contest_saturday(year: int) -> date_:
        """Saturday of the third full weekend (Sat+Sun both in March) of March."""
        d = date_(year, 3, 1)
        days_to_sat = (5 - d.weekday()) % 7
        sat = d + timedelta(days=days_to_sat)
        count = 0
        while True:
            sun = sat + timedelta(days=1)
            if sat.month == 3 and sun.month == 3:
                count += 1
                if count == 3:
                    return sat
            sat += timedelta(weeks=1)
            if sat.month > 3:
                raise ValueError(f"Could not find third full weekend in March {year}")

    def session_config(self) -> SessionConfig:
        return SessionConfig(duration_mins=180, num_sessions=8, start_hour=1)

    # ── Multiplier contract ───────────────────────────────────────────────────

    def mult_list(self) -> list:
        return []   # open-ended (any VK/ZL/P2 prefix)

    def mult_label(self) -> str:
        return "Prefix"

    def mult_of_qso(self, q: dict) -> Optional[str]:
        """WPX-style prefix, but only when the worked station is VK/ZL/P2 —
        a JA/W/G/etc. contact scores points (see recalc_pts) but never a
        multiplier."""
        call = q.get("call", "")
        if not call or not _is_jmfd_mult_eligible(call):
            return None
        return _wpx_prefix(call)

    def has_missing_tab(self) -> bool:
        return False

    def has_region_heat(self) -> bool:
        return False

    def has_state_bars(self) -> bool:
        return False

    @property
    def preferred_exchange_columns(self):
        # Serial number only — not used for scoring, just log display.
        return ["Exchange1", "exchange1"]

    # ── Scoring ───────────────────────────────────────────────────────────────

    def recalc_pts(self, qsos: list) -> None:
        for q in qsos:
            if q["dupe"]:
                q["pts"] = 0
                continue
            if _band_class(q.get("band", "")) == "X":
                q["pts"] = 0   # WARC band — excluded from the contest
                continue
            q["pts"] = _pts_for_mode(q.get("mode", ""))

    def _mult_set(self, qsos: list, cls: str) -> set:
        """Unique (prefix, band, mode, block) tuples for QSOs in band
        category *cls* ('HF' or 'VHF') where the worked station is
        VK/ZL/P2 — this exact granularity is what the rules' "once per
        band per mode per block" multiplier credit means."""
        result: set = set()
        for q in qsos:
            if q["dupe"]:
                continue
            band = q.get("band", "")
            if _band_class(band) != cls:
                continue
            pfx = self.mult_of_qso(q)
            if not pfx:
                continue
            block = _jmfd_block(q.get("time"))
            if block < 0:
                continue
            result.add((pfx, band, (q.get("mode") or "").upper(), block))
        return result

    def _subtotal(self, qsos: list, cls: str) -> tuple[int, set]:
        pts = sum(
            q.get("pts", 0) or 0
            for q in qsos
            if not q["dupe"] and _band_class(q.get("band", "")) == cls
        )
        return pts, self._mult_set(qsos, cls)

    def score(self, qsos: list) -> int:
        """HF and VHF+ score independently (points × that category's own
        mults, which is legitimately 0 if no VK/ZL/P2 station was worked
        in that category yet), summed only for this single display figure.
        Never cross-multiplies HF points by VHF mults or vice versa — see
        module docstring."""
        hf_pts,  hf_mults  = self._subtotal(qsos, "HF")
        vhf_pts, vhf_mults = self._subtotal(qsos, "VHF")
        return hf_pts * len(hf_mults) + vhf_pts * len(vhf_mults)

    def multipliers(self, qsos: list) -> MultResult:
        _, hf_mults  = self._subtotal(qsos, "HF")
        _, vhf_mults = self._subtotal(qsos, "VHF")
        return MultResult(hf_mults, vhf_mults, "HF MULTS", "VHF+ MULTS")

    def running_score_for_sparkline(self, qsos_up_to_hour: list) -> int:
        return self.score(qsos_up_to_hour)

    def sparkline_mults(self, q: dict, seen: set) -> int:
        if q.get("dupe"):
            return 0
        pfx = self.mult_of_qso(q)
        if not pfx:
            return 0
        cls = _band_class(q.get("band", ""))
        if cls == "X":
            return 0
        block = _jmfd_block(q.get("time"))
        if block < 0:
            return 0
        key = (cls, pfx, q.get("band", ""), (q.get("mode") or "").upper(), block)
        if key not in seen:
            seen.add(key)
            return 1
        return 0

    # ── UI hints ──────────────────────────────────────────────────────────────

    def post_snapshot(self, snap: dict, qsos: list) -> None:
        hf_pts,  hf_mults  = self._subtotal(qsos, "HF")
        vhf_pts, vhf_mults = self._subtotal(qsos, "VHF")

        snap["hf_score"]  = hf_pts * len(hf_mults)
        snap["vhf_score"] = vhf_pts * len(vhf_mults)
        snap["worked"]     = len(hf_mults)     # "HF MULTS" gauge
        snap["band_mults"] = len(vhf_mults)    # "VHF+ MULTS" gauge

        # % of the fixed 24-hour window elapsed (mult_list() is open-ended,
        # so the base class's worked/len(mult_list) percentage would divide
        # by zero — show contest-time progress instead, same approach as
        # hasprnt.py's 106-minute window).
        times = [q["time"] for q in qsos if not q["dupe"] and q.get("time")]
        if times:
            latest = max(times)
            contest_start = latest.replace(hour=1, minute=0, second=0, microsecond=0)
            if latest.hour == 0:
                contest_start -= timedelta(days=1)
            elapsed_mins = (latest - contest_start).total_seconds() / 60
            snap["pct"] = min(100.0, max(0.0, elapsed_mins / 1440 * 100))
        else:
            snap["pct"] = 0.0

    def band_efficiency(self, qsos: list) -> list:
        """Per-band QSO/mult breakdown, informational only (not block-aware
        — that granularity belongs to score()/multipliers(), not this panel)."""
        band_qsos  = defaultdict(int)
        band_pts   = defaultdict(int)
        band_mults = defaultdict(set)
        for q in qsos:
            if q["dupe"]:
                continue
            b = q.get("band") or "?"
            band_qsos[b] += 1
            band_pts[b]  += q.get("pts", 0) or 0
            pfx = self.mult_of_qso(q)
            if pfx:
                band_mults[b].add(pfx)
        result = []
        for b in band_qsos:
            qn = band_qsos[b]
            mn = len(band_mults[b])
            result.append({
                "band": b, "qsos": qn, "pts": band_pts[b], "new_shires": mn,
                "efficiency": mn / qn if qn else 0,
            })
        return sorted(result, key=lambda x: x["efficiency"], reverse=True)

    def worked_primary_mults(self, qsos: list) -> set:
        """Unique VK/ZL/P2 prefixes worked overall (HF + VHF combined,
        no band/mode/block split) — informational display only."""
        return {self.mult_of_qso(q) for q in qsos
                if not q["dupe"] and self.mult_of_qso(q)}

    def gauge_defs(self, data: dict, total_mults: int) -> list:
        hf_score  = data.get("hf_score", 0)
        vhf_score = data.get("vhf_score", 0)
        worked    = data.get("worked", 0)
        band_mult = data.get("band_mults", 0)
        soft_max  = max(worked * 1.25, band_mult * 1.25, 20)
        return [
            GaugeDef("TOTAL QSOs",  "total",      "qso_max",   ACCENT(),  "{v}"),
            GaugeDef("VALID QSOs",  "valid",      "qso_max",   GREEN(),   "{v}",
                     tooltip="Non-dupe contacts. Re-workable once per band per mode per 3-hour block."),
            GaugeDef("TOTAL SCORE", "score",      "score_max", ACCENT3(), "{v:,}",
                     tooltip=(
                         "TOTAL SCORE\n"
                         "HF score + VHF+ score, each computed separately as\n"
                         "points x that category's own prefix mults — the two\n"
                         "categories are judged independently, per the rules."
                     )),
            GaugeDef("HF SCORE",    "hf_score",   max(hf_score, 1),  ACCENT2(), "{v:,}"),
            GaugeDef("VHF+ SCORE",  "vhf_score",  max(vhf_score, 1), "#64b5f6", "{v:,}"),
            GaugeDef("HF MULTS",    "worked",     soft_max,    ACCENT3(), "{v}",
                     tooltip="Unique VK/ZL/P2 prefix x band x mode x block credits on HF."),
            GaugeDef("VHF+ MULTS",  "band_mults", soft_max,    GREEN(),   "{v}",
                     tooltip="Unique VK/ZL/P2 prefix x band x mode x block credits on VHF and above."),
        ]
