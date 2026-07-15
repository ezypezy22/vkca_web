"""
plugins/jidx.py
───────────────
Japan International DX Contest (JIDX) plugin for the VK Contest Analyzer.

Covers both CW (April) and Phone (November) weekends.
N1MM+ ContestName strings: "JIDXCW", "JIDXSSB", "JIDX-CW", "JIDX-SSB",
"JIDX CW", "JIDX SSB", "JIDX" and common variants.

Rules: https://jidx.org/jidxrule-e.html

──────────────────────────────────────────────────────────────────────────────
SCORING (DX station — the expected operator, e.g. VK):
  Objective : Contact JA stations in as many prefectures as possible.
  Exchange  : RST + CQ Zone (sent) / RST + Prefecture number 01–50 (received)
  Points    :
      1.8 MHz          → 4 points
      3.5 / 3.8 MHz    → 2 points
      7 / 14 / 21 MHz  → 1 point
      28 MHz           → 2 points
  Only JA ↔ DX contacts score.  DX–DX or JA–JA contacts = 0 pts / 0 mults.
  Multiplier: Number of different JA prefectures (01–50) worked *per band*.
  Final score: Total QSO points × Total multipliers (sum across all bands).

SCORING (JA station):
  Exchange  : RST + Prefecture number (sent) / RST + CQ Zone (received)
  Points    : same scale as above (only JA ↔ DX)
  Multiplier: Different DXCC entities + CQ Zones per band.
  Not the target user for this plugin, but recalc_pts() handles it gracefully.

──────────────────────────────────────────────────────────────────────────────
N1MM stores (for a DX operator):
  Exchange1 / mult1  → received prefecture number string, e.g. "14" or "29"
  ZN / CQZone        → CQ zone of the worked JA station (usually 25)
  IsMultiplier1 = 1  → new prefecture on this band
  IsMultiplier2      → not typically used for DX-side JIDX
  Points             → QSO point value stored by N1MM

Prefecture numbers are two-digit strings "01"–"50".  Numbers 48, 49, 50 are
the JD1 island groups (Ogasawara, Minami-Torishima, Okino-Torishima).
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
# Prefecture data (DX-side multipliers)
# ═════════════════════════════════════════════════════════════════════════════

# All 50 valid JIDX multiplier numbers (zero-padded strings, matching N1MM).
# Numbers 48-50 are the JD1 island groups (special entities).
_ALL_PREFECTURES: list[str] = [f"{n:02d}" for n in range(1, 51)]

# Prefecture number → (name, region/call-area)
# Source: https://jidx.org/jidx-mult.html
# Call areas: JA1=10-17+JD1, JA2=18-21, JA3=22-27, JA4=31-35, JA5=36-39,
#             JA6=40-46, JA7=02-07, JA8=01+08-09, JS6=47, JD1=48-50
_PREFECTURE_INFO: dict[str, tuple[str, str]] = {
    "01": ("Hokkaido",          "JA8"),
    "02": ("Aomori",            "JA7"),
    "03": ("Iwate",             "JA7"),
    "04": ("Akita",             "JA7"),
    "05": ("Yamagata",          "JA7"),
    "06": ("Miyagi",            "JA7"),
    "07": ("Fukushima",         "JA7"),
    "08": ("Niigata",           "JA8"),
    "09": ("Nagano",            "JA8"),
    "10": ("Tokyo",             "JA1"),
    "11": ("Kanagawa",          "JA1"),
    "12": ("Chiba",             "JA1"),
    "13": ("Saitama",           "JA1"),
    "14": ("Ibaraki",           "JA1"),
    "15": ("Tochigi",           "JA1"),
    "16": ("Gumma",             "JA1"),
    "17": ("Yamanashi",         "JA1"),
    "18": ("Shizuoka",          "JA2"),
    "19": ("Gifu",              "JA2"),
    "20": ("Aichi",             "JA2"),
    "21": ("Mie",               "JA2"),
    "22": ("Kyoto",             "JA3"),
    "23": ("Shiga",             "JA3"),
    "24": ("Nara",              "JA3"),
    "25": ("Osaka",             "JA3"),
    "26": ("Wakayama",          "JA3"),
    "27": ("Hyogo",             "JA3"),
    "28": ("Fukui",             "JA0"),   # JA0/9 area
    "29": ("Toyama",            "JA9"),
    "30": ("Ishikawa",          "JA9"),
    "31": ("Okayama",           "JA4"),
    "32": ("Shimane",           "JA4"),
    "33": ("Yamaguchi",         "JA4"),
    "34": ("Tottori",           "JA4"),
    "35": ("Hiroshima",         "JA4"),
    "36": ("Kagawa",            "JA5"),
    "37": ("Tokushima",         "JA5"),
    "38": ("Ehime",             "JA5"),
    "39": ("Kochi",             "JA5"),
    "40": ("Fukuoka",           "JA6"),
    "41": ("Saga",              "JA6"),
    "42": ("Nagasaki",          "JA6"),
    "43": ("Kumamoto",          "JA6"),
    "44": ("Oita",              "JA6"),
    "45": ("Miyazaki",          "JA6"),
    "46": ("Kagoshima",         "JA6"),
    "47": ("Okinawa",           "JS6"),
    "48": ("Ogasawara (JD1)",   "JD1"),
    "49": ("Minami-Torishima",  "JD1"),
    "50": ("Okino-Torishima",   "JD1"),
}

# Canonical call-area region order for bar chart display (geographic N→S/W→E)
_CALL_AREAS: list[str] = [
    "JA8",  # Hokkaido / Niigata / Nagano
    "JA7",  # Tohoku (north Honshu)
    "JA1",  # Kanto (Tokyo area)
    "JA9",  # Hokuriku
    "JA0",  # Chubu (Fukui)
    "JA2",  # Tokai
    "JA3",  # Kinki (Osaka area)
    "JA4",  # Chugoku
    "JA5",  # Shikoku
    "JA6",  # Kyushu
    "JS6",  # Okinawa
    "JD1",  # Island groups (rare DX)
]

# Prefecture number → call-area (for region_of_mult)
_PREF_TO_REGION: dict[str, str] = {
    pref: info[1] for pref, info in _PREFECTURE_INFO.items()
}

# Prefecture number → name (for display)
_PREF_TO_NAME: dict[str, str] = {
    pref: info[0] for pref, info in _PREFECTURE_INFO.items()
}

# JIDX band set in display order
_JIDX_BAND_ORDER: list[str] = ["160M", "80M", "40M", "20M", "15M", "10M"]

# Band → QSO point value (DX side)
_BAND_POINTS: dict[str, int] = {
    "160M": 4,
    "80M":  2,
    "40M":  1,
    "20M":  1,
    "15M":  1,
    "10M":  2,
}


def _pts_for_band(band: str) -> int:
    """Return the DX-side QSO point value for a given band string."""
    return _BAND_POINTS.get((band or "").upper(), 1)


def _is_ja_call(call: str) -> bool:
    """
    Return True if this looks like a Japanese station callsign.

    JA prefixes: JA–JS, 7J, 7K–7N (JA1 area), 8J (special), JD (islands).
    The operator's own VK call is NOT a JA call.
    """
    c = (call or "").upper().strip()
    if not c:
        return False
    # Primary JA prefix range: JA/JB/JC/JD/JE/JF/JG/JH/JI/JJ/JK/JL/JM/JN/JO/JP/JQ/JR/JS
    if len(c) >= 2 and c[0] == "J" and c[1] in "ABCDEFGHIJKLMNOPQRS":
        return True
    # 7J, 7K, 7L, 7M, 7N (JA1 call area special prefixes)
    if len(c) >= 2 and c[0] == "7" and c[1] in "JKLMN":
        return True
    # 8J (JA special event/commemorative stations)
    if len(c) >= 2 and c == "8J":
        return True
    if len(c) >= 3 and c[:2] == "8J":
        return True
    return False


def _is_valid_prefecture(s: str) -> bool:
    """Return True if s is a valid JIDX prefecture number (01–50)."""
    try:
        n = int(s)
        return 1 <= n <= 50
    except (ValueError, TypeError):
        return False


def _normalise_prefecture(s: str) -> Optional[str]:
    """
    Normalise a received exchange string to a zero-padded two-digit
    prefecture string, or return None if it cannot be interpreted as one.

    N1MM may store the received exchange as "14", "14 " (trailing space),
    or occasionally as a bare integer.  JA stations that send their
    prefecture may also include RST in the same field on some loggers.
    """
    if not s:
        return None
    # Strip whitespace and any leading RST-style characters
    s = s.strip()
    # Some loggers store "59 14" — try last token first, then first
    parts = s.split()
    for token in reversed(parts):
        try:
            n = int(token)
            if 1 <= n <= 50:
                return f"{n:02d}"
        except ValueError:
            pass
    return None


# ═════════════════════════════════════════════════════════════════════════════
# Plugin
# ═════════════════════════════════════════════════════════════════════════════

class JIDXPlugin(ContestPlugin):
    """
    Japan International DX Contest — CW and Phone.

    Designed for a DX (non-JA) operator.  Multiplier = unique JA
    prefectures worked per band (max 50/band).  Points scale by band.

    The JA-operator perspective (DXCC entities + CQ zones as mults) is
    handled gracefully but not the primary design target.
    """

    # ── Identity ──────────────────────────────────────────────────────────────

    def identify(self, contest_name: str) -> bool:
        cn = contest_name.upper().replace(" ", "").replace("_", "").replace("-", "")
        return "JIDX" in cn

    @property
    def display_name(self) -> str:
        return "JIDX"

    # ── Session / block structure ─────────────────────────────────────────────

    def session_config(self) -> SessionConfig:
        # 30-hour contest (Sat 07:00 – Sun 13:00 UTC).
        # Modelled as 3 × 10-hour blocks so the rate machinery has something
        # to iterate over and the session labels stay meaningful.
        return SessionConfig(
            duration_mins=600,      # 10 hours per block
            num_sessions=3,
            label_prefix="B",
            start_hour=7,           # Saturday 07:00 UTC
        )

    def uses_block_structure(self) -> bool:
        return False    # single continuous contest, no subdivisions

    # ── Multiplier contract ───────────────────────────────────────────────────

    def mult_list(self) -> list:
        """All 50 valid JIDX prefecture multipliers."""
        return list(_ALL_PREFECTURES)

    def mult_label(self) -> str:
        return "Prefecture"

    def mult_of_qso(self, q: dict) -> Optional[str]:
        """
        Return the normalised prefecture number from the received exchange,
        or None if this QSO doesn't carry a valid prefecture multiplier.

        N1MM stores the received exchange in Exchange1 / mult1.  For a DX
        operator working JA stations this is the JA prefecture number (01–50).
        """
        raw = q.get("mult1") or q.get("shire") or ""
        return _normalise_prefecture(str(raw))

    def region_of_mult(self, m: str) -> Optional[str]:
        """Map a prefecture number to its JA call area (for region bar chart)."""
        return _PREF_TO_REGION.get(m)

    def region_list(self) -> list:
        """Ordered list of JA call areas for the region heat/bar panels."""
        return list(_CALL_AREAS)

    # ── Exchange column hint ──────────────────────────────────────────────────

    @property
    def preferred_exchange_columns(self):
        # For JIDX the received exchange for a DX operator is the JA prefecture
        # number, which N1MM stores in Exchange1 (or Mult1 in some builds).
        # We list Exchange1 first so the loader picks it up before ZN/CQZone
        # (which holds the worked station's CQ zone — not the prefecture).
        return [
            "Exchange1", "exchange1",
            "Mult1", "mult1",
            "RcvExch", "rcvexch",
            "Comment", "comment",
        ]

    # ── Scoring ───────────────────────────────────────────────────────────────

    def recalc_pts(self, qsos: list) -> None:
        """
        Re-derive QSO point values for JIDX.

        Rules:
          • Only JA ↔ DX contacts score.  DX–DX contacts (i.e. the received
            exchange is not a valid prefecture number AND the worked call is not
            a JA prefix) score 0 pts and should not be counted as multipliers.
          • Per band: 160M=4, 80M=2, 40/20/15M=1, 10M=2.

        We trust N1MM's stored pts when they are non-zero — N1MM already knows
        the band and has applied the correct point value.  We only fill in
        missing values (pts == 0 on a non-dupe) or correct pts where N1MM has
        stored the generic default of 1 for all bands (some JIDX N1MM builds
        do this — the per-band scale then has to be reconstructed here).

        Detecting JA ↔ DX:
          – Primary gate: the worked callsign prefix.  If the callsign is a JA
            prefix (JA–JS, 7J-N, 8J…) it is a JA station regardless of exchange.
          – Secondary gate: if the callsign is unrecognisable but the received
            exchange is a valid prefecture number, treat it as JA (handles
            partial logs and /P operations with non-JA prefixes).
          – A non-JA callsign whose exchange is a number in 01–50 is almost
            certainly sending its CQ zone, NOT a prefecture.  Zero points.
          – Otherwise assume DX–DX → 0 pts (no point, no mult).
        """
        for q in qsos:
            if q["dupe"]:
                continue

            call    = str(q.get("call") or "").upper()
            band    = str(q.get("band") or "").upper()
            raw_ex  = str(q.get("mult1") or q.get("shire") or "").strip()
            ja_call = _is_ja_call(call)

            # Callsign is the primary authority.  A non-JA call sending a
            # number in the 01–50 range is sending their CQ zone, not a
            # prefecture — do not mistake it for a JA contact.
            if not ja_call:
                q["pts"] = 0
                continue

            # JA callsign confirmed.  Now check whether the exchange looks like
            # a valid prefecture number so we can fill in pts correctly.
            pref = _normalise_prefecture(raw_ex)

            # Trust N1MM's stored value when it is already plausible and
            # non-zero.  N1MM correctly applies the per-band scale for JIDX
            # so we don't need to override valid non-zero values.
            if q.get("pts") and q["pts"] > 0:
                continue

            # Fill in the correct per-band point value.
            q["pts"] = _pts_for_band(band)

    def score(self, qsos: list) -> int:
        """Total QSO points × total prefecture-band multipliers."""
        pts  = sum(q["pts"] for q in qsos if not q["dupe"])
        mr   = self.multipliers(qsos)
        mults = len(mr.primary_mults) + len(mr.secondary_mults)
        return pts * mults if mults else pts

    def multipliers(self, qsos: list) -> MultResult:
        """
        Primary mults : unique (prefecture, band) pairs worked.

        JIDX has only one multiplier type for DX operators — JA prefectures
        per band.  secondary_mults is always empty for the DX side.

        Uses N1MM's IsMultiplier1 flag when available (it marks the first
        time a given prefecture is worked on a given band).  Falls back to
        collecting all valid (prefecture, band) pairs when the flag is absent.

        Maximum theoretically possible: 50 prefectures × 6 bands = 300 mults.
        """
        prefs: set = set()

        has_m1 = any(q.get("is_mult1") is not None for q in qsos)

        for q in qsos:
            if q["dupe"]:
                continue
            call = str(q.get("call") or "").upper()
            if not _is_ja_call(call):
                continue                   # DX–DX: no mult
            band = (q.get("band") or "?").upper()
            raw  = str(q.get("mult1") or q.get("shire") or "")
            pref = _normalise_prefecture(raw)
            if pref is None:
                continue

            if has_m1:
                if q.get("is_mult1") == 1:
                    prefs.add((pref, band))
            else:
                # No flag data — collect every valid (prefecture, band) pair
                prefs.add((pref, band))

        return MultResult(
            primary_mults=prefs,
            secondary_mults=set(),
            primary_label="Prefectures",
            secondary_label="",
        )

    # ── UI hints ──────────────────────────────────────────────────────────────

    def has_missing_tab(self) -> bool:
        return True     # Fixed list of 50 prefectures — missing tab is useful

    def band_list(self) -> list:
        # JIDX is 160-10m — no WARC bands (30/17/12m).
        return list(_JIDX_BAND_ORDER)

    def has_region_heat(self) -> bool:
        return True     # Call-area breakdown is meaningful for JIDX

    def has_state_bars(self) -> bool:
        return True

    def post_snapshot(self, snap: dict, qsos: list) -> None:
        """
        Correct/augment the standard snapshot for JIDX-specific display.

        The standard compute_snapshot() calculates:
          worked     = len(mr.primary_mults)  → (prefecture, band) pairs  ✓
          band_mults = len(mr.primary_mults)  → same                      ✓
          pct        = worked / total_mults × 100

        For pct we override with: unique prefectures worked (any band) / 50,
        which is the more intuitive "how many JA prefectures have I got?"
        percentage rather than the band-pair count ratio.

        We also inject the per-band point values into the snapshot so the
        QSO Value panel can show them correctly.
        """
        mr              = self.multipliers(qsos)
        pref_band_cnt   = len(mr.primary_mults)
        unique_prefs    = {t[0] for t in mr.primary_mults}

        snap["worked"]      = pref_band_cnt
        snap["band_mults"]  = pref_band_cnt
        snap["zone_cnt"]    = len(unique_prefs)   # re-use zone_cnt for unique prefs
        snap["pct"]         = len(unique_prefs) / 50 * 100

        # Point scale hint for the QSO Value panel
        snap["band_pts_scale"] = {
            "160M": 4, "80M": 2, "40M": 1, "20M": 1, "15M": 1, "10M": 2,
        }

    def gauge_defs(self, data: dict, total_mults: int) -> list:
        # JIDX has exactly one multiplier *type* (prefecture), counted per
        # band — there's no separate zone/country mult like CQWW. So there
        # are only two genuinely different multiplier numbers to show:
        #   • band_mults : (prefecture, band) pairs — what the score formula
        #                  actually uses (pts × this number)
        #   • zone_cnt   : unique prefectures on ANY band — "how many of the
        #                  50 do I have", the number most operators care about
        #
        # WORKED / % WORKED (rather than PREFECTURES / % PREFECTURES) is used
        # deliberately so these don't share a root word with MULTS (×BAND) —
        # two gauges both saying "prefecture" reads as if they're showing the
        # same number, which they aren't.
        return [
            GaugeDef(
                "TOTAL QSOs", "total", "qso_max", ACCENT(), "{v}",
                tooltip=(
                    "TOTAL QSOs\n"
                    "Every logged contact including dupes.\n"
                    "Max is the highest total seen this session."
                ),
            ),
            GaugeDef(
                "VALID QSOs", "valid", "qso_max", GREEN(), "{v}",
                tooltip=(
                    "VALID QSOs\n"
                    "Non-dupe JA ↔ DX contacts that score points.\n"
                    "DX–DX contacts log 0 pts and are excluded."
                ),
            ),
            GaugeDef(
                "TOTAL SCORE", "score", "score_max", ACCENT3(), "{v:,}",
                tooltip=(
                    "TOTAL SCORE\n"
                    "QSO points × prefecture-band multipliers.\n"
                    "Formula: Σ pts × (unique prefecture × band pairs)\n"
                    "Matches N1MM's running score display."
                ),
            ),
            GaugeDef(
                "MULTS (×BAND)", "band_mults", 300, ACCENT3(), "{v}",
                tooltip=(
                    "PREFECTURE × BAND MULTIPLIERS\n"
                    "Count of unique (prefecture, band) combinations worked —\n"
                    "this is the actual multiplier figure used in the scoring\n"
                    "formula. Working the same prefecture on a new band adds\n"
                    "another mult here. Max 50 prefectures × 6 bands = 300."
                ),
            ),
            GaugeDef(
                "WORKED", "zone_cnt", 50, GREEN(), "{v}",
                tooltip=(
                    "PREFECTURES WORKED\n"
                    "Number of different JA prefectures contacted on any\n"
                    "band at least once (regardless of how many bands).\n"
                    "Maximum = 50 (47 prefectures + Okinawa + the 2 JD1\n"
                    "island groups). This is NOT the same as MULTS (×BAND) —\n"
                    "a prefecture worked on 3 bands still only counts once here."
                ),
            ),
            GaugeDef(
                "% WORKED", "pct", 100.0, MUTED(), "{v:.1f}%",
                tooltip=(
                    "% OF 50 PREFECTURES WORKED\n"
                    "Prefectures worked on any band ÷ 50.\n"
                    "100% = all 50 JA prefectures/entities worked at least once."
                ),
            ),
        ]

    # ── Multiplier helpers ────────────────────────────────────────────────────

    def worked_primary_mults(self, qsos: list) -> set:
        """Unique prefectures worked (any band) — for missing-mults tab."""
        result: set = set()
        for q in qsos:
            if q["dupe"]:
                continue
            if not _is_ja_call(str(q.get("call") or "")):
                continue
            raw  = str(q.get("mult1") or q.get("shire") or "")
            pref = _normalise_prefecture(raw)
            if pref:
                result.add(pref)
        return result

    def worked_primary_band_mults(self, qsos: list) -> set:
        """Unique (prefecture, band, mode) tuples — for band-breakdown panel."""
        result: set = set()
        has_m1 = any(q.get("is_mult1") is not None for q in qsos)
        for q in qsos:
            if q["dupe"]:
                continue
            if not _is_ja_call(str(q.get("call") or "")):
                continue
            raw  = str(q.get("mult1") or q.get("shire") or "")
            pref = _normalise_prefecture(raw)
            if not pref:
                continue
            band = q.get("band", "?")
            mode = q.get("mode", "?")
            if has_m1:
                if q.get("is_mult1") == 1:
                    result.add((pref, band, mode))
            else:
                result.add((pref, band, mode))
        return result

    def worked_secondary_band_mults(self, qsos: list) -> set:
        """JIDX DX-side has no secondary multiplier — always empty."""
        return set()

    def missing_primary_mults(self, qsos: list) -> list:
        """Return prefecture numbers not yet worked on any band."""
        worked = self.worked_primary_mults(qsos)
        return sorted(set(_ALL_PREFECTURES) - worked, key=lambda x: int(x))

    def sparkline_mults(self, q: dict, seen: set) -> int:
        """Count new (prefecture, band) multipliers for the running score chart."""
        if not _is_ja_call(str(q.get("call") or "")):
            return 0
        raw  = str(q.get("mult1") or q.get("shire") or "")
        pref = _normalise_prefecture(raw)
        if not pref:
            return 0
        band = q.get("band", "?")
        mode = q.get("mode", "?")
        key  = (pref, band, mode)
        if q.get("is_mult1") == 1 and key not in seen:
            seen.add(key)
            return 1
        return 0

    def running_score_for_sparkline(self, qsos_up_to_hour: list) -> int:
        """
        Calculate the running score for the sparkline chart.

        Uses the same multiplier logic as score() / multipliers() so the final
        sparkline data point matches the TOTAL SCORE gauge exactly.
        """
        pts  = sum(q["pts"] for q in qsos_up_to_hour if not q["dupe"])
        mr   = self.multipliers(qsos_up_to_hour)
        mults = len(mr.primary_mults) + len(mr.secondary_mults)
        return pts * mults if mults else pts

    def band_efficiency(self, qsos: list) -> list:
        """
        Per-band breakdown: QSOs, new prefectures, efficiency (mults/QSO).

        Overrides the base class implementation to use prefecture-based
        counting rather than the generic mult1 membership test.
        """
        band_qsos  = defaultdict(int)
        band_pts   = defaultdict(int)
        band_prefs = defaultdict(set)
        ja_qsos    = []   # scored subset — feeds _band_time_stats below

        for q in qsos:
            if q["dupe"]:
                continue
            if not _is_ja_call(str(q.get("call") or "")):
                continue
            ja_qsos.append(q)
            b    = (q.get("band") or "?").upper()
            raw  = str(q.get("mult1") or q.get("shire") or "")
            pref = _normalise_prefecture(raw)
            band_qsos[b] += 1
            band_pts[b]  += q.get("pts", 0) or 0
            if pref:
                band_prefs[b].add(pref)

        # Scoped to the same JA-only, non-dupe QSOs as the counts above, so
        # BEST RATE / LAST QSO reflect this table's own "qsos" column rather
        # than mixing in non-scoring contacts.
        time_stats = self._band_time_stats(ja_qsos)
        result = []
        for b in band_qsos:
            qn = band_qsos[b]
            mn = len(band_prefs[b])
            ts = time_stats.get(b, {"best_hour_rate": 0, "last_qso_utc": None})
            result.append({
                "band":        b,
                "qsos":        qn,
                "pts":         band_pts[b],
                "new_shires":  mn,      # generic key expected by the UI
                "efficiency":  mn / qn if qn else 0,
                "pts_per_qso": _pts_for_band(b),
                **ts,
            })
        return sorted(result, key=lambda x: x["efficiency"], reverse=True)

    def mults_by_region(self, qsos: list) -> dict:
        """
        Return worked/missing prefecture breakdown keyed by JA call area.

        Used by the Region Heat and Region Bar panels.
        """
        worked_prefs = self.worked_primary_mults(qsos)
        result: dict = {}
        for pref in _ALL_PREFECTURES:
            region = _PREF_TO_REGION.get(pref, "??")
            if region not in result:
                result[region] = {"worked": [], "missing": []}
            if pref in worked_prefs:
                result[region]["worked"].append(pref)
            else:
                result[region]["missing"].append(pref)
        return result

    def region_heat(self, qsos: list) -> list:
        """
        Per-call-area QSO and multiplier heat data for the Region Heat panel.
        """
        region_total:  dict = defaultdict(int)
        region_qsos:   dict = defaultdict(int)
        region_worked: dict = defaultdict(set)

        # Count expected prefectures per call area
        for pref, (_, region) in _PREFECTURE_INFO.items():
            region_total[region] += 1

        # Count worked QSOs and unique prefectures per call area
        for q in qsos:
            if q["dupe"]:
                continue
            if not _is_ja_call(str(q.get("call") or "")):
                continue
            raw  = str(q.get("mult1") or q.get("shire") or "")
            pref = _normalise_prefecture(raw)
            if not pref:
                continue
            region = _PREF_TO_REGION.get(pref)
            if not region:
                continue
            region_qsos[region]   += 1
            region_worked[region].add(pref)

        result = []
        for region in _CALL_AREAS:
            w = len(region_worked[region])
            t = region_total.get(region, 0)
            result.append({
                "state":  region,
                "qsos":   region_qsos[region],
                "worked": w,
                "total":  t,
                "pct":    w / t * 100 if t else 0,
            })
        return sorted(result, key=lambda x: x["qsos"], reverse=True)
