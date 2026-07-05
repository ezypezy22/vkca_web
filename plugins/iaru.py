"""
plugins/iaru.py
────────────────
IARU HF World Championship plugin for the VK Contest Analyzer.

Rules: https://contests.arrl.org/ContestRules/IARU-HF-Rules.pdf (v1.21)
Held the second full weekend in July, 1200 UTC Sat – 1159 UTC Sun.

Exchange: RS(T) + ITU Zone, OR an IARU Member Society abbreviation (HQ
stations), OR "AC"/"R1"/"R2"/"R3" for IARU Administrative Council / Regional
Executive Committee officials. NU1AW (IARU International Secretariat) sends
"IARU".

QSO points (rule 5.1):
  • Own ITU zone                                  → 1 pt
  • IARU HQ or IARU official station (any zone)    → 1 pt
  • Same ITU zone, different continent             → 1 pt
  • Same continent, different ITU zone             → 3 pts
  • Different continent AND different ITU zone     → 5 pts

Multipliers (rule 5.2) — per band, NOT per mode:
  • Every ITU zone worked on each band
  • Every IARU member society HQ station worked on each band
  • IARU officials (AC, R1, R2, R3) worked on each band — max 4 per band
  • HQ/official contacts do NOT also count as zone mults

Final score = total QSO points × total multipliers (rule 5.3).

N1MM quirk this plugin relies on:
  In the IARU HF Championship, N1MM's "Zone" database column (normally CQ
  zone, mapped here as q["cqz"]) is repurposed to hold the *ITU* zone
  instead. mult1 holds either the ITU zone (as a numeric string) for normal
  contacts, or the HQ/official abbreviation (e.g. "ARRL", "IARU", "AC",
  "R1") for HQ/official contacts — directly analogous to how the CQWW
  plugin (plugins/cqww.py) uses mult1 for the country prefix while cqz
  holds the CQ zone. is_mult1 / is_mult2 flags (when present) mark new
  band-mults exactly as in N1MM's own multiplier accounting.

Operator zone: VK stations are split across ITU zones 55 (VK4/VK8), 58
(VK6), 59 (VK1/VK2/VK3/VK5/VK7) and 60 (VK9/VK0 Pacific territories). We
guess the operator's zone from the log's own station-info callsign when
available, defaulting to 59 (the most common VK zone) otherwise. The
op-zone only affects the 1-pt "own zone" / 3-pt "same continent" QSO-point
split — it has no effect on multiplier counting, which is symmetric.
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


# ═════════════════════════════════════════════════════════════════════════════
# ITU zone → continent table
# ═════════════════════════════════════════════════════════════════════════════
# Built directly from the official ITU zone list (EI8IC / RSGB reference,
# https://www.rsgbshop.org/acatalog/PDF/Worked_ITU_Zones_ITU_Zones_List.pdf),
# which enumerates the DXCC prefixes contained in each of the 75 ITU zones.
# Each zone below is assigned the continent of the prefixes it actually
# contains — this is the same table contest log checkers (N1MM, DXLog,
# Win-Test) use to validate IARU same-zone / same-continent / cross-continent
# QSO points.
#
# Zone 75 (high Arctic slivers of Norway/Greenland/Russia/Canada north of
# 80N) genuinely straddles NA/EU/AS and is almost never worked in practice;
# it's left unmapped (None) rather than guessed.

_ITUZ_CONTINENT: dict[int, str] = {
    # 1-13: North America, Caribbean, Central America
    1: "NA", 2: "NA", 3: "NA", 4: "NA", 5: "NA", 6: "NA", 7: "NA",
    8: "NA", 9: "NA", 10: "NA", 11: "NA", 12: "NA", 13: "NA",
    # 14-16: South America
    14: "SA", 15: "SA", 16: "SA",
    # 17-29: Europe (incl. Iceland, Scandinavia, W/E Europe, European Russia/CIS)
    17: "EU", 18: "EU", 19: "EU", 20: "EU", 21: "EU", 22: "EU",
    23: "EU", 24: "EU", 25: "EU", 26: "EU", 27: "EU", 28: "EU", 29: "EU",
    # 30-35: Central Asia / Siberia / Russian Far East / Mongolia / N. China
    30: "AS", 31: "AS", 32: "AS", 33: "AS", 34: "AS", 35: "AS",
    # 36-38: North Africa / Atlantic islands off Africa
    36: "AF", 37: "AF", 38: "AF",
    # 39-41: Middle East / Iran-Afghanistan / South Asia (Pakistan/India)
    39: "AS", 40: "AS", 41: "AS",
    # 42-45: China / Korea / Japan
    42: "AS", 43: "AS", 44: "AS", 45: "AS",
    # 46-48: Sub-Saharan / Central / East Africa
    46: "AF", 47: "AF", 48: "AF",
    # 49: South/SE Asia (Thailand, Andamans, Vietnam, Laos)
    49: "AS",
    # 50-51: SE Asia / Indonesia / Philippines / Pacific (PNG)
    50: "AS", 51: "OC",
    # 52: Central Africa
    52: "AF",
    # 53: East African islands
    53: "AF",
    # 54: Western Indonesia / Christmas & Cocos Is.
    54: "AS",
    # 55-65: Australia, New Zealand, Pacific Islands
    55: "OC", 56: "OC", 57: "AF", 58: "OC", 59: "OC", 60: "OC",
    61: "OC", 62: "OC", 63: "OC", 64: "OC", 65: "OC",
    # 66: Southern Africa (ZD7/8/9 — St Helena, Ascension, Tristan da Cunha)
    66: "AF",
    # 67-74: Antarctica and sub-Antarctic islands
    67: "AN", 68: "AF", 69: "AN", 70: "AN", 71: "AN", 72: "AN", 73: "AN",
    74: "AN",
    # 75: High Arctic — spans NA/EU/AS, left unmapped (see note above)
    # 78: CE0 Salas y Gomez (SA, near Easter Island)
    78: "SA",
    # 90: JD1 Minami Torishima (AS, Japanese Pacific possession)
    90: "AS",
}


def _continent_of_ituz(zone: Optional[int]) -> Optional[str]:
    if zone is None:
        return None
    return _ITUZ_CONTINENT.get(int(zone))


# ── VK call-area → ITU zone (for guessing the operator's own zone) ──────────
_VK_AREA_TO_ITUZ: dict[int, int] = {
    1: 59, 2: 59, 3: 59, 5: 59, 7: 59,   # VK1/2/3/5/7 → ITU 59
    4: 55, 8: 55,                        # VK4/8       → ITU 55
    6: 58,                               # VK6         → ITU 58
    9: 60, 0: 60,                        # VK9/VK0 Pacific territories → ITU 60
}

_DEFAULT_OP_ITUZ = 59   # most common VK zone if we can't determine one

# ── IARU HQ / official abbreviations recognised as non-zone mult1 values ────
# Officials per rule 4.2.2 (max 4 per band). HQ society abbreviations are
# open-ended (one per IARU member society, ~80 societies) so we don't try to
# enumerate them all — any mult1 that isn't a plain ITU zone number is
# treated as an HQ/official contact. NU1AW sends "IARU" per rule 4.2.1.
_OFFICIAL_ABBREVS = frozenset({"AC", "R1", "R2", "R3"})

# All 75 ITU zones (1-75, plus 88/89/90 are obscure/unused by amateurs in
# practice — the IARU rules and every major log checker treat 1-75 as the
# working multiplier universe).
_ALL_ITU_ZONES: list[int] = list(range(1, 76))

# ── Standard IARU/HF band set (display order, low → high) ───────────────────
_IARU_BAND_ORDER: list[str] = ["160M", "80M", "40M", "20M", "15M", "10M"]


def _is_hq_or_official(mult1_val) -> bool:
    """True when mult1 holds an HQ society abbreviation or AC/R1/R2/R3,
    rather than a plain numeric ITU zone."""
    if not mult1_val:
        return False
    s = str(mult1_val).strip().upper()
    if not s:
        return False
    if s in _OFFICIAL_ABBREVS:
        return True
    # Plain ITU zone numbers are 1-2 digit numerics; anything else (3+
    # letters, or letters mixed with digits) is an HQ society abbreviation.
    return not s.isdigit()


# ═════════════════════════════════════════════════════════════════════════════
# Plugin
# ═════════════════════════════════════════════════════════════════════════════

class IARUPlugin(ContestPlugin):
    """
    IARU HF World Championship.

    Primary multiplier  : ITU Zone, per band
    Secondary multiplier: IARU HQ stations + AC/R1/R2/R3 officials, per band
    Exchange            : RS(T) + ITU Zone, or Society Abbreviation / AC / R1 / R2 / R3
    """

    # ── Identity ──────────────────────────────────────────────────────────────

    def identify(self, contest_name: str) -> bool:
        cn = contest_name.upper().replace(" ", "").replace("_", "").replace("-", "")
        keywords = ("IARUHF", "IARU", "IARUHQ", "IARUCHAMPIONSHIP")
        return any(kw in cn for kw in keywords)

    @property
    def display_name(self) -> str:
        return "IARU HF Championship"

    # ── Session / block structure ─────────────────────────────────────────────

    def session_config(self) -> SessionConfig:
        # 24 h total (1200 UTC Sat – 1159 UTC Sun); modelled as 4 × 6-hour
        # chunks purely so the generic rate/session machinery has segments
        # to iterate over. IARU has no rule-defined "block" concept — see
        # uses_block_structure() below.
        return SessionConfig(
            duration_mins=360,     # 6 hours per chunk
            num_sessions=4,
            label_prefix="B",
            start_hour=12,          # 1200 UTC Saturday
        )

    def uses_block_structure(self) -> bool:
        """
        IARU is a single continuous 24-hour contest with no fixed-block
        scoring subdivision. The overview's time panel should show
        whole-contest start/elapsed/remaining instead of a per-block
        countdown.
        """
        return False

    # ── Multiplier contract ───────────────────────────────────────────────────

    def mult_list(self) -> list:
        """All 75 ITU zones — the fixed, enumerable half of the multiplier
        set. HQ/official station mults are open-ended (no fixed list), so
        they're tracked separately via worked_secondary_band_mults()."""
        return _ALL_ITU_ZONES

    def mult_label(self) -> str:
        return "ITU Zone"

    def mult_of_qso(self, q: dict) -> Optional[str]:
        """
        Return the ITU zone as the primary multiplier key. For HQ/official
        contacts (which don't count as zone mults — rule 5.2.2) we return
        None so they're excluded from the zone-multiplier accounting; they
        are picked up instead by worked_secondary_band_mults().
        """
        m1 = q.get("mult1")
        if _is_hq_or_official(m1):
            return None
        zone = q.get("cqz")  # repurposed by N1MM to hold ITU zone for IARU
        if zone is not None:
            return str(int(zone)) if isinstance(zone, (int, float)) else str(zone)
        return str(m1) if m1 else None

    def region_of_mult(self, m: str) -> Optional[str]:
        try:
            return _continent_of_ituz(int(m))
        except (TypeError, ValueError):
            return None

    def region_list(self) -> list:
        return ["NA", "SA", "EU", "AF", "AS", "OC", "AN"]

    # ── Scoring ───────────────────────────────────────────────────────────────

    @staticmethod
    def _guess_op_ituz(qsos: list) -> int:
        """
        Best-effort guess at the operator's own ITU zone, used only to
        classify the 1-pt "own zone" vs 3-pt "same continent" QSO-point
        split when N1MM hasn't already stored a point value.

        We can't read the operator's own callsign reliably from the qso
        rows (those describe the *worked* station), so this stays a fixed
        VK default. If a future loader exposes station-info, swap this for
        a real lookup via _VK_AREA_TO_ITUZ.
        """
        return _DEFAULT_OP_ITUZ

    def uses_cq_zone_scoring(self) -> bool:
        return True

    def recalc_pts(self, qsos: list) -> None:
        """
        Re-derive QSO point values per rule 5.1 when N1MM hasn't already
        stored a usable value (e.g. logs imported from ADIF without the
        Points column, or rows where pts is missing/zero).

        Rules:
          • HQ / official contact (any zone)            → 1 pt
          • Same ITU zone as operator                    → 1 pt
          • Same ITU zone, different continent            → 1 pt
            (covered by the same-zone case above — zone implies continent
            in the vast majority of real-world IARU zone numbering, but we
            keep the rule named distinctly per the official text)
          • Same continent, different ITU zone            → 3 pts
          • Different continent AND different ITU zone    → 5 pts

        We trust N1MM's stored pts when it is already a positive integer;
        IARU has no legitimate 0-pt QSO (unlike CQWW's same-country rule),
        so unlike the CQWW plugin we don't need special dupe-flag repair
        here — a non-dupe QSO with pts==0 just means pts hasn't been
        computed yet, and we fill it in below.
        """
        op_zone      = self._guess_op_ituz(qsos)
        op_continent = _continent_of_ituz(op_zone) or "OC"

        for q in qsos:
            if q["dupe"]:
                continue

            # Trust N1MM's stored value when it's already populated.
            if q.get("pts") and q["pts"] > 0:
                continue

            # HQ / official station → always 1 pt regardless of zone.
            if _is_hq_or_official(q.get("mult1")):
                q["pts"] = 1
                continue

            worked_zone = q.get("cqz")  # ITU zone, per the N1MM IARU quirk
            if worked_zone is None:
                q["pts"] = 1  # unknown — conservative default, matches "own zone"
                continue

            worked_zone = int(worked_zone)
            worked_continent = _continent_of_ituz(worked_zone)

            if worked_zone == op_zone:
                q["pts"] = 1                       # rule 5.1.1 — own zone
            elif worked_continent and worked_continent == op_continent:
                q["pts"] = 3                       # rule 5.1.4 — same continent, diff zone
            elif worked_continent is None:
                q["pts"] = 1                       # unknown continent — conservative
            else:
                q["pts"] = 5                       # rule 5.1.5 — diff continent & zone

    def score(self, qsos: list) -> int:
        """Total QSO points × total multipliers (zone mults + HQ/official
        mults, all bands) — rule 5.3."""
        pts   = sum(q["pts"] for q in qsos if not q["dupe"])
        mr    = self.multipliers(qsos)
        mults = len(mr.primary_mults) + len(mr.secondary_mults)
        return pts * mults if mults else pts

    def multipliers(self, qsos: list) -> MultResult:
        """
        Primary mults   : unique (ITU zone, band) pairs
        Secondary mults : unique (HQ/official callsign-or-abbrev, band) pairs,
                          capped conceptually at 4 officials per band by
                          rule 5.2.1 — we don't hard-cap here since a log
                          legitimately containing AC/R1/R2/R3 all on one
                          band is exactly 4 distinct values already.

        Uses N1MM's IsMultiplier1 / IsMultiplier2 flags (is_mult1 / is_mult2)
        when available, exactly as the CQWW plugin does. Falls back to
        collecting every non-dupe (key, band) pair when the flags are absent
        (e.g. logs loaded from a non-N1MM source).
        """
        zones: set = set()
        hq:    set = set()

        has_m1 = any(q.get("is_mult1") is not None for q in qsos)
        has_m2 = any(q.get("is_mult2") is not None for q in qsos)

        for q in qsos:
            if q["dupe"]:
                continue
            band = q.get("band") or "?"
            m1   = q.get("mult1")

            if _is_hq_or_official(m1):
                # HQ / official station — secondary mult, never a zone mult
                # (rule 5.2.2).
                key = (str(m1).upper(), band)
                if has_m2:
                    if q.get("is_mult2") == 1:
                        hq.add(key)
                else:
                    hq.add(key)
                continue

            zone = q.get("cqz")  # ITU zone, per the N1MM IARU quirk
            if zone is None:
                continue
            zkey = (int(zone), band)
            if has_m1:
                if q.get("is_mult1") == 1:
                    zones.add(zkey)
            else:
                zones.add(zkey)

        return MultResult(
            primary_mults=zones,
            secondary_mults=hq,
            primary_label="ITU Zones",
            secondary_label="HQ/Official Stations",
        )

    # ── "Next QSO" value estimator (Overview tab) ─────────────────────────────

    def qso_value_estimate(self, qsos: list) -> dict:
        """
        Estimate how much the total score would jump for working ONE more
        QSO right now, broken down by band.

        IARU scores as Score = TotalPoints × TotalMultipliers, exactly the
        same shape as CQWW, so the delta formula is identical:

            delta = p * (M + dm) + P * dm

        where p is the QSO's raw point value, M is the current total
        multiplier count, P is the current total QSO points, and dm is how
        many brand-new band-multipliers that QSO brings:
          - 0 → a fill QSO (zone/HQ already worked on that band)
          - 1 → one new band-zone (or one new band-HQ contact)
          - 2 → not possible in IARU on a single QSO — a contact is either
                a zone contact or an HQ/official contact, never both, so we
                expose 0/1 scenarios only (unlike CQWW's 0/1/2).
        """
        valid     = [q for q in qsos if not q["dupe"]]
        total_pts = sum(q["pts"] for q in valid)

        mr          = self.multipliers(qsos)
        total_mults = len(mr.primary_mults) + len(mr.secondary_mults)
        overall_avg = (total_pts / len(valid)) if valid else 0.0

        band_pts: dict = defaultdict(list)
        for q in valid:
            b = (q.get("band") or "?").upper()
            band_pts[b].append(q["pts"])

        def delta(p: float, dm: int) -> float:
            return p * (total_mults + dm) + total_pts * dm

        band_order = list(_IARU_BAND_ORDER)
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
            }

        return {
            "total_pts":   total_pts,
            "total_mults": total_mults,
            "overall_avg": overall_avg,
            "bands":       bands,
            "band_order":  band_order,
            "scenarios":   ["no_mult", "one_mult"],
            "scenario_labels": {
                "no_mult":  "+QSO",
                "one_mult": "+QSO +1 mult (zone or HQ)",
            },
        }

    # ── Exchange columns hint ─────────────────────────────────────────────────

    @property
    def preferred_exchange_columns(self):
        # N1MM's IARU contest module stores the HQ/official abbreviation (or
        # blank for ordinary contacts) in Mult1, and repurposes the Zone
        # column to hold ITU zone instead of CQ zone. Exchange1 generally
        # mirrors whichever of the two was actually received. We force
        # Mult1 first so HQ/official contacts are correctly identified;
        # the base loader's default heuristic (Exchange1 first) would lose
        # the distinction between a zone number and a society abbreviation
        # in some N1MM export variants.
        return ["Mult1", "mult1", "Exchange1", "exchange1"]

    # ── UI hints ──────────────────────────────────────────────────────────────

    def has_missing_tab(self) -> bool:
        return True   # ITU zones are a fixed, enumerable list (1-75)

    def has_region_heat(self) -> bool:
        return True    # continents make a sensible heat breakdown

    def has_state_bars(self) -> bool:
        return True

    def missing_primary_mults(self, qsos: list) -> list:
        """ITU zones not yet worked on any band."""
        worked = {int(m) for m in self.worked_primary_mults(qsos) if str(m).isdigit()}
        return sorted(set(_ALL_ITU_ZONES) - worked)

    def worked_primary_mults(self, qsos: list) -> set:
        """Unique ITU zones worked (any band) — excludes HQ/official contacts."""
        zones: set = set()
        for q in qsos:
            if q["dupe"] or _is_hq_or_official(q.get("mult1")):
                continue
            z = q.get("cqz")
            if z is not None:
                zones.add(int(z))
        return zones

    def worked_primary_band_mults(self, qsos: list) -> set:
        """Unique (ITU zone, band, mode) tuples."""
        result: set = set()
        for q in qsos:
            if q["dupe"] or _is_hq_or_official(q.get("mult1")):
                continue
            z = q.get("cqz")
            if z is not None:
                result.add((int(z), q.get("band", "?"), q.get("mode", "?")))
        return result

    def worked_secondary_band_mults(self, qsos: list) -> set:
        """Unique (HQ/official abbreviation, band, mode) tuples."""
        result: set = set()
        for q in qsos:
            if q["dupe"]:
                continue
            m1 = q.get("mult1")
            if _is_hq_or_official(m1):
                result.add((str(m1).upper(), q.get("band", "?"), q.get("mode", "?")))
        return result

    def post_snapshot(self, snap: dict, qsos: list) -> None:
        """
        Inject IARU-correct display values on top of the standard snapshot
        computed by ContestLog.compute_snapshot().

        compute_snapshot() already sets, using mult_list() = 75 zones:
          worked     = len(worked_primary_mults)        → unique zones, any band ✓
          band_mults = len(worked_primary_band_mults)   → (zone, band) pair count ✓
          pct        = worked / 75 * 100                → % of 75 ITU zones ✓

        We add the HQ/official band-mult count (zone_cnt slot, reused here
        to surface HQ stations rather than CQ zones since IARU has no
        separate CQ-zone concept) and recompute the gauge max for the
        zone-mult gauge to scale with the running band-mult count.
        """
        mr = self.multipliers(qsos)
        zone_band_cnt = len(mr.primary_mults)
        hq_band_cnt   = len(mr.secondary_mults)

        snap["band_mults"] = zone_band_cnt
        snap["zone_cnt"]   = hq_band_cnt   # reused slot: HQ/official band-mults

        import math
        zone_max = max(int(math.ceil(zone_band_cnt * 1.25 / 50) * 50), 50)
        snap["cty_max"] = zone_max

    def gauge_defs(self, data: dict, total_mults: int) -> list:
        zone_max = data.get("cty_max", max(data.get("band_mults", 1), 50))
        hq_band_cnt = data.get("zone_cnt", 0)
        hq_max = max(hq_band_cnt, 10)
        return [
            GaugeDef("TOTAL QSOs",  "total",      "qso_max",   ACCENT(),  "{v}",
                     tooltip=(
                         "TOTAL QSOs\n"
                         "Every logged contact, including dupes.\n"
                         "Max is the highest total seen across sessions."
                     )),
            GaugeDef("VALID QSOs",  "valid",       "qso_max",   GREEN(),   "{v}",
                     tooltip=(
                         "VALID QSOs\n"
                         "Non-dupe contacts that count toward QSO points.\n"
                         "IARU has no 0-point valid contact — every"
                         " non-dupe QSO scores 1, 3, or 5 points."
                     )),
            GaugeDef("TOTAL SCORE", "score",       "score_max", ACCENT3(), "{v:,}",
                     tooltip=(
                         "TOTAL SCORE\n"
                         "QSO points × (ITU zone mults + HQ/official mults).\n"
                         "Formula: Σ pts  ×  (band-zones + band-HQ stations)\n"
                         "Matches N1MM's running score display."
                     )),
            GaugeDef("ITU ZONES",   "worked",      75,          ACCENT3(), "{v}",
                     tooltip=(
                         "ITU ZONES WORKED\n"
                         "Unique ITU zones worked on any band, out of 75.\n"
                         "From VK, zone 59 is home (1 pt); the Americas\n"
                         "(zones 1-13) and parts of Africa/CIS are the\n"
                         "hardest to fill."
                     )),
            GaugeDef("BAND ZONES",  "band_mults",  zone_max,    GREEN(),   "{v}",
                     tooltip=(
                         "BAND ZONE MULTS\n"
                         "Unique ITU zone × band pairs worked — the primary\n"
                         "scoring multiplier. Each new zone on each new band\n"
                         "adds 1 to your multiplier total.\n"
                         "Gauge ceiling auto-scales to 125% of current count."
                     )),
            GaugeDef("HQ STATIONS", "zone_cnt",    hq_max,      "#64b5f6", "{v}",
                     tooltip=(
                         "HQ / OFFICIAL BAND MULTS\n"
                         "Unique (HQ society or AC/R1/R2/R3) × band pairs\n"
                         "worked — the secondary scoring multiplier.\n"
                         "Up to 4 officials (AC, R1, R2, R3) count per band;\n"
                         "HQ societies are otherwise open-ended (~80 societies)."
                     )),
            GaugeDef("% ZONES",     "pct",         100.0,       MUTED(),   "{v:.1f}%",
                     tooltip=(
                         "% ZONES COVERED\n"
                         "Unique ITU zones worked on any band, expressed\n"
                         "as a percentage of all 75 ITU zones.\n"
                         "100% = worked at least one station in every zone."
                     )),
        ]

    # ── Multiplier helper override: region heat by continent ────────────────

    def region_heat(self, qsos: list) -> list:
        """Per-continent breakdown of ITU-zone coverage (zones worked vs.
        zones available in that continent, plus QSO volume)."""
        zone_to_continent = _ITUZ_CONTINENT
        continent_total  = defaultdict(int)
        continent_qsos    = defaultdict(int)
        continent_worked  = defaultdict(set)

        for z in _ALL_ITU_ZONES:
            c = zone_to_continent.get(z)
            if c:
                continent_total[c] += 1

        for q in qsos:
            if q["dupe"] or _is_hq_or_official(q.get("mult1")):
                continue
            z = q.get("cqz")
            if z is None:
                continue
            c = zone_to_continent.get(int(z))
            if c:
                continent_qsos[c] += 1
                continent_worked[c].add(int(z))

        result = []
        for c in continent_total:
            w = len(continent_worked[c])
            t = continent_total[c]
            result.append({
                "state":  c,
                "qsos":   continent_qsos[c],
                "worked": w,
                "total":  t,
                "pct":    w / t * 100 if t else 0,
            })
        return sorted(result, key=lambda x: x["qsos"], reverse=True)

    def band_efficiency(self, qsos: list) -> list:
        """Per-band breakdown: QSOs, new zone mults, new HQ mults, efficiency."""
        band_qsos  = defaultdict(int)
        band_zones = defaultdict(set)
        band_hq    = defaultdict(set)

        for q in qsos:
            if q["dupe"]:
                continue
            b = q.get("band") or "?"
            band_qsos[b] += 1
            m1 = q.get("mult1")
            if _is_hq_or_official(m1):
                band_hq[b].add(str(m1).upper())
            else:
                z = q.get("cqz")
                if z is not None:
                    band_zones[b].add(int(z))

        result = []
        for b in band_qsos:
            qn = band_qsos[b]
            zn = len(band_zones[b])
            hn = len(band_hq[b])
            mn = zn + hn
            result.append({
                "band":        b,
                "qsos":        qn,
                "new_shires":  mn,    # reuses the generic key name
                "new_zones":   zn,
                "new_hq":      hn,
                "efficiency":  mn / qn if qn else 0,
            })
        return sorted(result, key=lambda x: x["efficiency"], reverse=True)

    # ── Sparkline helpers ─────────────────────────────────────────────────────

    def sparkline_mults(self, q: dict, seen: set) -> int:
        """Count new band-zone or new band-HQ multipliers for sparkline."""
        count = 0
        band  = q.get("band", "?")
        mode  = q.get("mode", "?")
        m1    = q.get("mult1")

        if _is_hq_or_official(m1):
            key = (str(m1).upper(), band)
            if q.get("is_mult2") == 1 and key not in seen:
                count += 1
                seen.add(key)
        else:
            z = q.get("cqz")
            if z is not None:
                key = (int(z), band)
                if q.get("is_mult1") == 1 and key not in seen:
                    count += 1
                    seen.add(key)

        return count

    def running_score_for_sparkline(self, qsos_up_to_hour: list) -> int:
        """
        Calculate score for the sparkline using the same multiplier logic
        as multipliers() / score() so the final sparkline point matches the
        TOTAL SCORE gauge exactly.
        """
        pts = sum(q["pts"] for q in qsos_up_to_hour if not q["dupe"])

        zones: set = set()
        hq:    set = set()

        has_m1 = any(q.get("is_mult1") is not None for q in qsos_up_to_hour)
        has_m2 = any(q.get("is_mult2") is not None for q in qsos_up_to_hour)

        for q in qsos_up_to_hour:
            if q["dupe"]:
                continue
            band = q.get("band") or "?"
            m1   = q.get("mult1")

            if _is_hq_or_official(m1):
                key = (str(m1).upper(), band)
                if has_m2:
                    if q.get("is_mult2") == 1:
                        hq.add(key)
                else:
                    hq.add(key)
                continue

            z = q.get("cqz")
            if z is None:
                continue
            zkey = (int(z), band)
            if has_m1:
                if q.get("is_mult1") == 1:
                    zones.add(zkey)
            else:
                zones.add(zkey)

        mults = len(zones) + len(hq)
        return pts * mults if mults else pts
