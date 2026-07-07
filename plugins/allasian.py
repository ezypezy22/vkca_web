"""
plugins/allasian.py
────────────────────
JARL All Asian DX Contest (AADX) plugin for the VK Contest Analyzer.

Covers both CW (June) and Phone (September) weekends.
N1MM+ ContestName strings: "ALL-ASIAN-CW", "ALL-ASIAN-DX-CW", "AADX-CW",
"AADX-PH", "ALLASIANCW", "ALL ASIAN" and common variants.

Rules: https://www.jarl.org/English/4_Library/A-4-3_Contests/AA_rule_en.htm

──────────────────────────────────────────────────────────────────────────────
KNOWN DEVIATIONS FROM THE LITERAL "LIST OF ASIAN ENTITIES" TEXT

JARL's published prefix list is occasionally narrower than the real, active
ITU-allocated prefix blocks for an entity.  In three places this plugin
recognises additional real-world prefixes beyond what the rules text states
verbatim, on the basis that excluding genuinely Asian stations from an Asian
DX contest is a worse error than including a couple of extra prefix blocks
the rules document didn't explicitly spell out:

  • West Malaysia — rules say "9M2,4".  9W2/9W4 is the same territory under
    the modern parallel licence-class block letter ("W" vs "M") and is
    confirmed via ITU/MCMC allocation documents.  Added.
  • Republic of Korea — rules say "HL,6K-6N".  DS/DT and D7-D9 are real,
    actively-issued South Korean blocks (834 DS calls, 22 D7 calls per ITU)
    that simply aren't mentioned in JARL's shorthand list.  Added.
  • Asiatic Russia — rules say "UA-UI8,9,0 RA-RZ", which is genuinely
    ambiguous shorthand.  The correct interpretation (confirmed against
    ITU/ARRL prefix allocation references) is digit-based: ANY "R"/"RA"-"RZ"
    or "U"/"UA"-"UI" callsign with call-area digit 8, 9, or 0 is Asiatic
    Russia — not a fixed enumerated list of letter blocks.  Implemented as
    _is_asiatic_russia() rather than a static prefix tuple, since a fixed
    list cannot represent this rule correctly (it would miss real, common
    blocks like RC, RD, RK, RN, RU, RV, RW, RX, RZ at digits 8/9/0).

If you find a log where one of these calls is scoring against the literal
rules text's expectations, this is why — and the relevant entry/function is
the place to adjust.
──────────────────────────────────────────────────────────────────────────────

──────────────────────────────────────────────────────────────────────────────
This plugin is written from the perspective of a NON-ASIAN station (e.g. VK),
which is what section 7(2) of the rules covers:

  QSO Points (non-Asian station working an Asian station — section 7(2)1):
      Only contacts with Asian stations score points.  Non-Asian↔non-Asian
      and Asian↔Asian-from-the-DX-side contacts are not relevant here; a
      non-Asian station simply scores 0 for any non-Asian contact.
      160m → 3 pts   80m → 2 pts   10m → 2 pts   all other bands → 1 pt

  Multipliers (section 7(2)2):
      The total number of different ASIAN PREFIXES (per WPX Contest rules)
      worked, PER BAND.  This is notably different from CQWW-style country
      mults — multiple different prefixes from the *same* DXCC entity (e.g.
      JA1, JA2, JA3… all being "Japan") each count as separate multipliers,
      because AADX uses WPX-style prefix multipliers, not DXCC entities.

  Scoring (section 8):
      All-band: (sum of QSO points across all bands) × (sum of multipliers
      across all bands).  Single-band categories use only that band's
      points × that band's mults — not relevant for the all-band overview
      this analyzer is built around, but the formula degenerates correctly
      if filtered to one band.

  Special case — JD1 (section 7(3)):
      JD1 stations on Ogasawara (Bonin/Volcano Is.) count as Asia.
      JD1 stations on Minami-Torishima (Marcus Is.) count as Oceania, i.e.
      NOT Asian for scoring purposes from a non-Asian station's perspective.
      Both share the JD1 callsign prefix, so they cannot be told apart from
      the callsign alone — N1MM/the operator would need to flag this via
      the exchange or QTH field.  We default JD1 to "Asian" (Ogasawara is
      the far more commonly active of the two) and note this limitation.

  Maritime mobile (section 7(4)):
      Contacts with MM stations score like Asian↔Asian contacts but do NOT
      count as a multiplier.  We detect /MM in the callsign and apply this.

N1MM stores (for a non-Asian operator):
  Exchange1 / mult1  → received age string, e.g. "25" or "01" (not used for
                        scoring — AADX multiplier is the worked station's
                        callsign prefix, derived here from the call itself,
                        not from any exchange field).
  Points             → QSO point value stored by N1MM (trusted when present)
  IsMultiplier1 = 1  → new prefix on this band (when N1MM's AADX module
                        sets it; we fall back to deriving this ourselves
                        when the flag is absent, as for older/foreign logs).
"""

from __future__ import annotations

import re
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
# Asian entity prefixes (from the official rules page, "LIST OF ASIAN ENTITIES")
# ═════════════════════════════════════════════════════════════════════════════
# Each entry maps one or more DXCC-style prefix roots to a short entity name.
# This list is used only to decide IS-ASIAN / NOT-ASIAN for scoring — the
# actual multiplier is the WPX prefix itself (see _wpx_prefix below), not
# the entity name.

_ASIAN_ENTITIES: list[tuple[str, tuple[str, ...]]] = [
    ("Spratly Is.",            ()),                       # no current prefix issued
    ("Vietnam",                ("3W", "XV")),
    ("Azerbaijan",             ("4J", "4K")),
    ("Georgia",                ("4L",)),
    ("Sri Lanka",              ("4S",)),
    ("Israel",                 ("4X", "4Z")),
    ("Cyprus",                 ("5B", "C4", "P3")),
    ("Yemen",                  ("7O",)),
    ("Maldives",               ("8Q",)),
    ("Kuwait",                 ("9K",)),
    ("West Malaysia",          ("9M2", "9M4", "9W2", "9W4")),
    ("Nepal",                  ("9N",)),
    ("Singapore",              ("9V",)),
    ("Oman",                   ("A4",)),
    ("Bhutan",                 ("A5",)),
    ("U.A.E.",                 ("A6",)),
    ("Qatar",                  ("A7",)),
    ("Bahrain",                ("A9",)),
    ("Pakistan",               ("AP",)),
    ("Scarborough Reef",       ("BS7",)),
    ("Taiwan",                 ("BV",)),
    ("Pratas Is.",             ("BV9P",)),
    ("China",                  ("B",)),
    ("Palestine",              ("E4",)),
    ("Armenia",                ("EK",)),
    ("Iran",                   ("EP", "EQ")),
    ("Kyrgyzstan",             ("EX",)),
    ("Tajikistan",             ("EY",)),
    ("Turkmenistan",           ("EZ",)),
    ("Republic of Korea",      ("HL", "6K", "6L", "6M", "6N",
                                 "DS", "DT", "D7", "D8", "D9")),
    ("Thailand",               ("HS", "E2")),
    ("Saudi Arabia",           ("HZ",)),
    ("Japan",                  ("JA", "JB", "JC", "JD", "JE", "JF", "JG", "JH",
                                 "JI", "JJ", "JK", "JL", "JM", "JN", "JO", "JP",
                                 "JQ", "JR", "JS",
                                 "7J", "7K", "7L", "7M", "7N",
                                 "8J", "8K", "8L", "8M", "8N")),
    ("Ogasawara",              ("JD1",)),    # see JD1 handling note above
    ("Mongolia",               ("JT", "JU", "JV")),
    ("Jordan",                 ("JY",)),
    ("Lebanon",                ("OD",)),
    ("DPR of Korea",           ("P5",)),
    ("Bangladesh",             ("S2",)),
    ("Turkey",                 ("TA", "TB", "TC")),
    # NOTE: Asiatic Russia is deliberately NOT listed here as a fixed
    # prefix tuple. Unlike every other entity in this table, "R"/"RA"-"RZ"
    # and "U"/"UA"-"UI" Russian callsigns split between Europe and Asia by
    # their CALL-AREA DIGIT (8, 9, 0 = Asiatic; 1-7 = European), not by
    # which specific two-letter block they use. A fixed list like ("UA9",
    # "RA9", ...) misses many real, commonly-active letter blocks (RC, RD,
    # RK, RN, RU, RV, RW, RX, RZ, RO, etc., all of which exist with every
    # digit). See _is_asiatic_russia() below — checked separately in
    # _entity_of_call() before falling through to this static table.
    ("Uzbekistan",             ("UJ", "UK", "UL", "UM")),
    ("Kazakhstan",             ("UN", "UO", "UP", "UQ")),
    ("Hong Kong",              ("VR",)),
    ("India",                  ("VU",)),
    ("Andaman & Nicobar Is.",  ("VU4",)),
    ("Lakshadweep Is.",        ("VU7",)),
    ("Cambodia",               ("XU",)),
    ("Laos",                   ("XW",)),
    ("Macao",                  ("XX9",)),
    ("Myanmar",                ("XY", "XZ")),
    ("Afghanistan",            ("YA",)),
    ("Iraq",                   ("YI",)),
    ("Syria",                  ("YK",)),
    ("UK Sov. Base Cyprus",    ("ZC4",)),
]

# Flatten to a prefix -> entity-name lookup, longest-prefix-first for matching.
_ASIAN_PREFIX_TO_ENTITY: dict[str, str] = {}
for _entity, _prefixes in _ASIAN_ENTITIES:
    for _pfx in _prefixes:
        _ASIAN_PREFIX_TO_ENTITY[_pfx] = _entity

# Sorted longest-first so e.g. "JD1" is checked before the bare "JD" stem
# (JD1 has no separate "JD" entry above, but this keeps future edits safe).
_ASIAN_PREFIXES_BY_LENGTH = sorted(_ASIAN_PREFIX_TO_ENTITY.keys(),
                                    key=len, reverse=True)

# Marcus Island (Minami-Torishima) — shares the JD1 prefix with Ogasawara but
# counts as Oceania, NOT Asia, per rule 7(3)2.  Cannot be distinguished from
# the callsign alone.  Listed here for documentation; see module docstring.
_JD1_MARCUS_NOTE = "JD1 Minami-Torishima (Marcus Is.) is Oceania, not Asia — see module docstring."


def _is_asiatic_russia(base_call: str) -> bool:
    """
    Return True if base_call is a Russian amateur callsign in the Asiatic
    region (call-area digit 8, 9, or 0), per the official ITU/Russian
    allocation: any "R" or "RA"-"RZ" prefix, or any "U"/"UA"-"UI" prefix,
    followed immediately by a single digit of 8, 9, or 0.

    European Russia (digits 1, 2, 3, 4, 6 — 5 and 7 are unused) is
    correctly excluded.  Examples: RC0L, UA9ABC, RA8AA, R0AAA -> True;
    RW3FO, UA3ABC, R1ABC -> False.
    """
    m = re.match(r"^(R[A-Z]?|U[A-I]?)([0-9])", base_call)
    if not m:
        return False
    return m.group(2) in ("8", "9", "0")


def _entity_of_call(call: str) -> Optional[str]:
    """
    Return the Asian entity name for a callsign, or None if it isn't a
    recognised Asian-entity prefix.
    """
    c = (call or "").upper().strip()
    if not c:
        return None
    # Strip a leading home-call when operating portable in another call area,
    # e.g. N8BJQ/JA1 — the portable designator determines the entity.
    parts = [p for p in c.split("/") if p]
    if not parts:
        return None
    # Prefer a portable designator over the home call if present (mirrors
    # the WPX-prefix portable handling — see _wpx_prefix below for the
    # full portable-suffix logic, duplicated minimally here for entity ID).
    candidates = parts if len(parts) == 1 else sorted(parts, key=len)
    for cand in candidates:
        if _is_asiatic_russia(cand):
            return "Asiatic Russia"
        for pfx in _ASIAN_PREFIXES_BY_LENGTH:
            if cand.startswith(pfx):
                return _ASIAN_PREFIX_TO_ENTITY[pfx]
    return None


def _is_asian_call(call: str) -> bool:
    """Return True if this callsign belongs to an Asian DXCC entity."""
    return _entity_of_call(call) is not None


def _is_maritime_mobile(call: str) -> bool:
    """Return True if the callsign carries a /MM (maritime mobile) suffix."""
    c = (call or "").upper().strip()
    return c.endswith("/MM") or "/MM/" in c


# ═════════════════════════════════════════════════════════════════════════════
# WPX-style prefix extraction (the AADX multiplier for non-Asian stations)
# ═════════════════════════════════════════════════════════════════════════════
# Per WPX contest rules: "A PREFIX is the letter/numeral combination which
# forms the first part of the amateur call... Any difference in the
# numbering, lettering, or order of same shall count as a separate prefix."
# Portable operation: the portable designator becomes the prefix.  Calls
# with no digit get a 0 appended after the first two letters.

_NON_PREFIX_PORTABLE_SUFFIXES = frozenset({
    "P", "M", "MM", "AM", "QRP", "A", "E", "J", "LGT",
})


def _wpx_prefix(call: str) -> Optional[str]:
    """
    Derive the WPX-style prefix multiplier for a callsign.

    Examples:
        JA1ABC      -> JA1
        7K4XYZ      -> 7K4
        8N3HQ       -> 8N3
        VK4SN       -> VK4
        XEFTJW      -> XE0     (no digit -> append 0)
        PA/N8BJQ    -> PA0     (portable designator with no digit)
        N8BJQ/KH9   -> KH9     (portable designator becomes the prefix)
        VK4SN/P     -> VK4     (/P /M /MM /QRP etc. are NOT prefixes)
        JA1ABC/4    -> JA4     (bare call-area digit combines with home prefix)
    """
    c = (call or "").upper().strip()
    if not c:
        return None
    parts = [p for p in c.split("/") if p]
    if not parts:
        return None

    home   = max(parts, key=len)
    others = [p for p in parts if p != home]

    portable = None
    for o in others:
        if o in _NON_PREFIX_PORTABLE_SUFFIXES:
            continue
        if o.isdigit():
            # Bare call-area digit portable, e.g. "/4" — combine with the
            # home call's leading letters rather than treating the lone
            # digit as a prefix by itself.
            m = re.match(r"^([A-Z]+)", home)
            if m:
                portable = m.group(1) + o
            break
        portable = o
        break

    base = portable if portable else home

    # Letters (optionally with 1-2 leading digits, e.g. "7K", "8N") + digits.
    m = re.match(r"^(\d{0,2}[A-Z]+\d+)", base)
    if m:
        return m.group(1)
    # No digit anywhere in the base -> append "0" after the first two letters.
    m2 = re.match(r"^([A-Z]{1,2})", base)
    if m2:
        return m2.group(1) + "0"
    return base or None


def _looks_like_prefix(s: str) -> bool:
    """
    Loose sanity check that a string plausibly looks like a WPX prefix
    (letters/digits, no spaces, reasonable length) rather than something
    else that ended up in the same field (e.g. a blank string, an age
    number with no letters, or garbage).
    """
    if not s:
        return False
    s = s.strip().upper()
    if not (1 <= len(s) <= 8):
        return False
    if " " in s:
        return False
    return any(ch.isalpha() for ch in s)


def _resolved_prefix(q: dict) -> Optional[str]:
    """
    Return the best available WPX-style prefix for this QSO.

    Prefers N1MM's own pre-computed WPXPrefix value — loaded into
    q["mult1"] via preferred_exchange_columns — since N1MM has more
    context (and a maintained ruleset) than a callsign regex.  Falls back
    to deriving it from the callsign when mult1 is missing, blank, or
    doesn't look like a prefix (e.g. an older export where the loader
    picked up the exchange/age field instead, or a non-N1MM source).
    """
    stored = str(q.get("mult1") or "").strip().upper()
    if _looks_like_prefix(stored):
        return stored
    return _wpx_prefix(str(q.get("call") or ""))


def _pts_for_band(band: str) -> int:
    """QSO point value for a non-Asian station working an Asian station."""
    b = (band or "").upper()
    if b == "160M":
        return 3
    if b == "80M":
        return 2
    if b == "10M":
        return 2
    return 1   # 40M, 20M, 15M and anything else


_AADX_BAND_ORDER: list[str] = ["160M", "80M", "40M", "20M", "15M", "10M"]


# ═════════════════════════════════════════════════════════════════════════════
# Plugin
# ═════════════════════════════════════════════════════════════════════════════

class AllAsianPlugin(ContestPlugin):
    """
    JARL All Asian DX Contest — CW and Phone.

    Written for a NON-ASIAN operator (e.g. VK).  Only QSOs with Asian
    stations score.  Multiplier = unique WPX-style prefix worked per band
    (NOT DXCC entity — AADX explicitly uses WPX prefix rules for the
    non-Asian side, unlike CQWW's per-entity multiplier).
    """

    # ── Identity ──────────────────────────────────────────────────────────────

    def identify(self, contest_name: str) -> bool:
        cn = contest_name.upper().replace(" ", "").replace("_", "").replace("-", "")
        # N1MM's actual stored ContestName for this contest is "ALLASIACW" /
        # "ALLASIASSB" — note NO trailing "N" before the mode suffix (i.e.
        # NOT "ALLASIANCW"), confirmed against a real N1MM .s3db export.
        # "ALLASIA" alone (without requiring the "N") is therefore the most
        # reliable match; the other keywords are kept as a safety net for
        # other export formats/abbreviations (e.g. Cabrillo CONTEST tags or
        # older N1MM builds) that may spell it out differently.
        keywords = ("ALLASIA", "AADX", "JARLAADX")
        return any(kw in cn for kw in keywords)

    @property
    def display_name(self) -> str:
        return "All Asian DX"

    # ── Session / block structure ─────────────────────────────────────────────

    def session_config(self) -> SessionConfig:
        # 48-hour contest, Saturday 00:00 UTC – Sunday 24:00 UTC.
        # Shown as 4 x 12-hour blocks, matching the CQWW plugin's convention.
        return SessionConfig(
            duration_mins=720,      # 12 hours per block
            num_sessions=4,
            label_prefix="B",
            start_hour=0,
        )

    # ── Multiplier contract ───────────────────────────────────────────────────

    def mult_list(self) -> list:
        """
        AADX prefixes are open-ended (any WPX-style prefix that turns up),
        same as CQWW's country list.  Empty list tells the framework to
        treat mult1/derived-prefix values as free-form.
        """
        return []

    def mult_label(self) -> str:
        return "Prefix"

    def mult_of_qso(self, q: dict) -> Optional[str]:
        """
        Return the WPX-style prefix of the worked station.  Prefers N1MM's
        own pre-computed WPXPrefix (loaded into q["mult1"] — see
        preferred_exchange_columns), falling back to deriving it from the
        callsign when that isn't available.
        """
        call = q.get("call") or ""
        if not _is_asian_call(call):
            return None
        return _resolved_prefix(q)

    # ── Scoring ───────────────────────────────────────────────────────────────

    def recalc_pts(self, qsos: list) -> None:
        """
        Re-derive QSO point values for AADX (non-Asian operator perspective).

        Rules:
          • Only contacts with Asian stations score.  A non-Asian↔non-Asian
            contact (this operator working e.g. a ZL or W station) is 0 pts
            and not a multiplier.
          • Maritime-mobile (/MM) contacts score like a normal Asian contact
            for points, but never count as a multiplier (handled in
            multipliers(), not here).
          • Per-band point scale: 160m=3, 80m=2, 10m=2, all other bands=1.

        We trust N1MM's stored pts when already populated and non-zero —
        N1MM's AADX module (if present) applies the per-band scale
        correctly.  We only fill in missing/zero values.
        """
        for q in qsos:
            if q["dupe"]:
                continue

            call = str(q.get("call") or "")
            band = str(q.get("band") or "").upper()

            if not _is_asian_call(call):
                q["pts"] = 0
                continue

            if q.get("pts") and q["pts"] > 0:
                continue

            q["pts"] = _pts_for_band(band)

    def score(self, qsos: list) -> int:
        """Total QSO points × total WPX-prefix-band multipliers."""
        pts   = sum(q["pts"] for q in qsos if not q["dupe"])
        mr    = self.multipliers(qsos)
        mults = len(mr.primary_mults) + len(mr.secondary_mults)
        return pts * mults if mults else pts

    def multipliers(self, qsos: list) -> MultResult:
        """
        Primary mults : unique (WPX prefix, band) pairs worked with Asian
                         stations.  Maritime-mobile contacts are excluded
                         from multiplier credit per rule 7(4), even though
                         they score points.

        AADX has only one multiplier type for the non-Asian side —
        secondary_mults is always empty.
        """
        prefixes: set = set()
        has_m1 = any(q.get("is_mult1") is not None for q in qsos)

        for q in qsos:
            if q["dupe"]:
                continue
            call = str(q.get("call") or "")
            if not _is_asian_call(call):
                continue
            if _is_maritime_mobile(call):
                continue   # scores points, but never a multiplier (rule 7(4))

            band = (q.get("band") or "?").upper()
            pfx  = _resolved_prefix(q)
            if not pfx:
                continue

            if has_m1:
                if q.get("is_mult1") == 1:
                    prefixes.add((pfx, band))
            else:
                prefixes.add((pfx, band))

        return MultResult(
            primary_mults=prefixes,
            secondary_mults=set(),
            primary_label="Prefixes",
            secondary_label="",
        )

    def post_snapshot(self, snap: dict, qsos: list) -> None:
        """
        Correct the % gauge for AADX.

        compute_snapshot()'s generic formula is `pct = worked / len(mult_list())
        * 100`.  AADX's mult_list() deliberately returns [] (prefixes are
        open-ended, same reasoning as CQWW's country list), so that generic
        formula always divides by zero and pct is permanently stuck at 0% —
        not just unclear, but actively wrong, regardless of how the contest
        is going.

        Unlike CQWW (40 fixed zones) or JIDX (50 fixed prefectures), AADX
        has no fixed roster to measure "% complete" against — any number of
        distinct WPX prefixes could turn up. So instead of a completion
        percentage, % ASIAN shows the % of this operator's LOGGED QSOs that
        were actually Asian (i.e. scoring) contacts — a well-defined, useful
        number for this contest: it answers "how much of my operating time
        was on-target for AADX" rather than an undefined "% of an unbounded
        list."
        """
        valid = [q for q in qsos if not q["dupe"]]
        if not valid:
            snap["pct"] = 0.0
            return
        asian_qsos = sum(1 for q in valid if _is_asian_call(str(q.get("call") or "")))
        snap["pct"] = asian_qsos / len(valid) * 100

    # ── Exchange column hint ──────────────────────────────────────────────────

    @property
    def preferred_exchange_columns(self):
        # N1MM pre-computes the WPX-style prefix into its own WPXPrefix
        # column for every QSO — point the loader at it directly so
        # q["mult1"] holds the correct prefix (e.g. "JA1", "BY2") rather
        # than falling through to Exchange1 (the operator's age, which is
        # not used for AADX scoring and would otherwise end up displayed
        # as the multiplier in QSO tables/exports).
        #
        # _resolved_prefix() still falls back to deriving the prefix from
        # the callsign if WPXPrefix is absent (e.g. an older log, a
        # non-N1MM import, or a build that didn't populate this column),
        # so this is a strict improvement with no new failure mode.
        return ["WPXPrefix", "wpxprefix", "WPX_Prefix", "wpx_prefix"]

    # ── UI hints ──────────────────────────────────────────────────────────────

    def has_missing_tab(self) -> bool:
        # No fixed prefix list — "missing prefixes" doesn't make sense
        # (open-ended, same as CQWW's country list).
        return False

    def band_list(self) -> list:
        # All Asian DX is 160-10m — no WARC bands (30/17/12m).
        return list(_AADX_BAND_ORDER)

    def has_region_heat(self) -> bool:
        return False

    def has_state_bars(self) -> bool:
        return False

    def gauge_defs(self, data: dict, total_mults: int) -> list:
        return [
            GaugeDef("TOTAL QSOs",  "total",      "qso_max",   ACCENT(),  "{v}"),
            GaugeDef("VALID QSOs",  "valid",      "qso_max",   GREEN(),   "{v}"),
            GaugeDef("TOTAL SCORE", "score",      "score_max", ACCENT3(), "{v:,}"),
            GaugeDef("PREFIXES",    "worked",     total_mults, ACCENT3(), "{v}"),
            GaugeDef("BAND PFXS",   "band_mults", total_mults, GREEN(),   "{v}"),
            # % of logged (non-dupe) QSOs that were Asian/scoring contacts —
            # see post_snapshot() above for why this (rather than a
            # completion-percentage) is what AADX's % gauge shows.
            GaugeDef("% ASIAN",     "pct",        100.0,       MUTED(),   "{v:.1f}%"),
        ]

    # ── Multiplier helpers (overrides) ────────────────────────────────────────

    def worked_primary_mults(self, qsos: list) -> set:
        """Unique WPX prefixes worked (any band), Asian contacts only."""
        result: set = set()
        for q in qsos:
            if q["dupe"]:
                continue
            call = str(q.get("call") or "")
            if not _is_asian_call(call) or _is_maritime_mobile(call):
                continue
            pfx = _resolved_prefix(q)
            if pfx:
                result.add(pfx)
        return result

    def worked_primary_band_mults(self, qsos: list) -> set:
        """Unique (prefix, band, mode) tuples — for band-breakdown panel."""
        result: set = set()
        for q in qsos:
            if q["dupe"]:
                continue
            call = str(q.get("call") or "")
            if not _is_asian_call(call) or _is_maritime_mobile(call):
                continue
            pfx = _resolved_prefix(q)
            if not pfx:
                continue
            result.add((pfx, q.get("band", "?"), q.get("mode", "?")))
        return result

    def worked_secondary_band_mults(self, qsos: list) -> set:
        """AADX non-Asian side has no secondary multiplier — always empty."""
        return set()

    def missing_primary_mults(self, qsos: list) -> list:
        """Not applicable — AADX prefixes are open-ended, not a fixed list."""
        return []

    def sparkline_mults(self, q: dict, seen: set) -> int:
        """Count a new (prefix, band) multiplier for the running score chart."""
        call = str(q.get("call") or "")
        if not _is_asian_call(call) or _is_maritime_mobile(call):
            return 0
        pfx = _resolved_prefix(q)
        if not pfx:
            return 0
        band = q.get("band", "?")
        mode = q.get("mode", "?")
        key  = (pfx, band, mode)
        if q.get("is_mult1") == 1 and key not in seen:
            seen.add(key)
            return 1
        if q.get("is_mult1") is None and key not in seen:
            # No N1MM flag data available — fall back to "first time we see
            # this pair" as the new-mult signal (matches multipliers()'s
            # own fallback behaviour when has_m1 is False).
            seen.add(key)
            return 1
        return 0

    def running_score_for_sparkline(self, qsos_up_to_hour: list) -> int:
        pts   = sum(q["pts"] for q in qsos_up_to_hour if not q["dupe"])
        mr    = self.multipliers(qsos_up_to_hour)
        mults = len(mr.primary_mults) + len(mr.secondary_mults)
        return pts * mults if mults else pts

    # ── Band efficiency override ──────────────────────────────────────────────

    def band_efficiency(self, qsos: list) -> list:
        """Per-band breakdown: Asian QSOs, new prefixes, efficiency."""
        band_qsos = defaultdict(int)
        band_pfxs = defaultdict(set)

        for q in qsos:
            if q["dupe"]:
                continue
            call = str(q.get("call") or "")
            if not _is_asian_call(call):
                continue   # only Asian contacts are scoring QSOs at all
            b = (q.get("band") or "?").upper()
            band_qsos[b] += 1
            if _is_maritime_mobile(call):
                continue   # counts as a QSO but never a multiplier
            pfx = _resolved_prefix(q)
            if pfx:
                band_pfxs[b].add(pfx)

        result = []
        for b in band_qsos:
            qn = band_qsos[b]
            mn = len(band_pfxs[b])
            result.append({
                "band":        b,
                "qsos":        qn,
                "new_shires":  mn,     # generic key expected by the UI
                "efficiency":  mn / qn if qn else 0,
                "pts_per_qso": _pts_for_band(b),
            })
        return sorted(result, key=lambda x: x["efficiency"], reverse=True)
