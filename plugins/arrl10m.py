"""
plugins/arrl10m.py
───────────────────
ARRL 10-Meter Contest plugin for the VK Contest Analyzer.

Single mixed-mode weekend, second full weekend of December.
N1MM+ ContestName strings: "ARRL-10", "ARRL10", "ARRL-10M", "10-METER",
"10METER" and common variants.

Rules: https://contests.arrl.org/ContestRules/10M-Rules.pdf
Multiplier abbreviations: https://contests.arrl.org/contestmultipliers.php

──────────────────────────────────────────────────────────────────────────────
This plugin is written from the perspective of a DX station (e.g. VK), which
is the only role that makes sense for an Australian operator — W/VE and
Mexican stations have a different exchange (state/province instead of a
serial number) and aren't the target audience here.

Bands and Modes (rule 2.3, "Bands and Modes"):
    28 MHz (10m) ONLY — this is a single-band contest. CW must be below
    28.3 MHz (rule 6.2); above that is Phone.

Exchange (rule 4):
    Sent (DX → everyone)   : RST + serial number
    Received (everyone → DX): RST + whatever the worked station sends —
        W/VE          → state/province abbreviation (DC for D.C.)
        Mexican (XE)  → state abbreviation
        DX (inc. VK)  → serial number (not a multiplier-bearing value)
        Maritime mobile → ITU region (1, 2, or 3)
    Hawaii (KH6) and Alaska (KL7) explicitly count as US states, NOT as
    separate DXCC entities, despite being separate DXCC entities under
    normal DXCC rules (rule 5.2.2.1) — N1MM's received-exchange value
    (the actual state/territory abbreviation sent) is trusted directly
    rather than re-derived from the callsign, since the rules define the
    multiplier by what's exchanged, not by prefix.

QSO Points (rule 5.1):
    Phone → 2 points
    CW    → 4 points
    (Flat, no per-band variation — there's only one band.)

Multipliers (rule 5.2 — ALL OF THE FOLLOWING FEED ONE COMBINED POOL):
    • US states + DC (50 + 1 = 51)
    • Canadian provinces/territories (13 — NB, NS, PE, QC, ON, MB, SK, AB,
      BC, NT, YT, NU, NL — Newfoundland & Labrador is one combined
      multiplier per the standard ARRL/RAC section list; the rules text's
      "...Territories plus Labrador" is read as clarifying that Labrador
      is included within NL, not as a separate 14th entry — there is no
      officially separate "Labrador" abbreviation in the ARRL section
      list this plugin could validate against)
    • Mexican states (32 — see _MEXICAN_STATES)
    • DXCC entities (open-ended — every DXCC entity VK works, including
      W/VE/XE since they're also DXCC entities, counts here too)
    • ITU regions (1, 2, 3 — maritime mobile stations only)

    Each multiplier counts ONCE PER MODE (rule 5.2.1) — there's no "per
    band" counting here since there's only one band, so the per-mode
    distinction takes the structural place that "per band" plays in
    CQWW/IARU/JIDX/AADX. Working the same state on both CW and Phone
    earns 2 separate multiplier credits.

Scoring (rule 5.3):
    Final score = total QSO points × total multipliers (all categories,
    both modes, summed together — NOT split into primary/secondary the
    way CQWW splits country/zone; ARRL 10M has one flat multiplier pool).

    Worked example from the rules text (KA1RWY):
        6330 pts × (83 phone mults + 57 CW mults) = 6330 × 140 = 886,200

N1MM stores (for a DX operator):
    Exchange1 / mult1  → the received exchange string. For W/VE/XE
                          stations this is the state/province/DC
                          abbreviation (e.g. "CA", "ON", "DC", "HI",
                          "AK"). For other DX stations it's a serial
                          number (not multiplier-bearing on its own —
                          the multiplier there is the worked station's
                          DXCC entity, derived from the callsign).
    CountryPrefix      → DXCC entity prefix of the worked station —
                          used as the DXCC-entity multiplier value.
    Mode               → "CW" or any phone mode (USB/LSB/PH/SSB) —
                          used both for point value and per-mode
                          multiplier bucketing.
    Points             → QSO point value stored by N1MM (trusted when
                          already populated and non-zero).
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
# Multiplier tables
# ═════════════════════════════════════════════════════════════════════════════

# US states + DC (51). Hawaii (HI) and Alaska (AK) are included here per
# rule 5.2.2.1 — they explicitly count as US states for this contest.
_US_STATES: list[str] = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
]

# Canadian provinces and territories (13). NL = Newfoundland & Labrador
# (combined, standard ARRL/RAC section abbreviation).
_VE_PROVINCES: list[str] = [
    "NB", "NS", "PE", "QC", "ON", "MB", "SK", "AB", "BC", "NT",
    "YT", "NU", "NL",
]

# Mexican states (32 — 31 states + Mexico City/CDMX).
# Abbreviations per the Grupo DXXE Mexican States map referenced in the
# ARRL 10-Meter Contest rules' "Additional Information" section.
_MEXICAN_STATES: list[str] = [
    "AGS", "BC", "BCS", "CAM", "CHIS", "CHIH", "CDMX", "COAH", "COL",
    "DGO", "GTO", "GRO", "HGO", "JAL", "MEX", "MICH", "MOR", "NAY",
    "NL", "OAX", "PUE", "QRO", "QROO", "SLP", "SIN", "SON", "TAB",
    "TAMPS", "TLAX", "VER", "YUC", "ZAC",
]

# ITU regions (maritime mobile only).
_ITU_REGIONS: list[str] = ["1", "2", "3"]

# All W/VE/XE/ITU-region multiplier values in one set, for fast membership
# tests when classifying a received exchange. NOTE: Mexico's "NL" (Nuevo
# Leon) and Canada's "NL" (Newfoundland & Labrador) collide as bare
# strings — see _classify_exchange() below for how the worked station's
# DXCC entity (not just the bare abbreviation) disambiguates this.
_US_SET   = set(_US_STATES)
_VE_SET   = set(_VE_PROVINCES)
_XE_SET   = set(_MEXICAN_STATES)
_ITU_SET  = set(_ITU_REGIONS)

# Combined fixed-list multipliers (everything except open-ended DXCC
# entities) — used for mult_list()/missing-mults tracking. DXCC entities
# are NOT included here since that list is open-ended and contest-wide,
# same reasoning as CQWW's country list.
_ALL_FIXED_MULTS: list[str] = (
    [f"US:{s}" for s in _US_STATES] +
    [f"VE:{p}" for p in _VE_PROVINCES] +
    [f"XE:{s}" for s in _MEXICAN_STATES] +
    [f"ITU:{r}" for r in _ITU_REGIONS]
)


def _pts_for_mode(mode: str, call: str = "") -> int:
    """QSO point value per rule 5.1:
      Phone = 2, CW = 4.
      Exception: CW QSO with a US Novice/Technician station signing /N or /T
      on 28.1–28.3 MHz = 8 pts (rule 5.1 bonus).
    """
    if _is_cw(mode):
        # /N or /T suffix indicates Novice/Tech station (8-pt bonus)
        c = (call or "").upper()
        if c.endswith("/N") or c.endswith("/T"):
            return 8
        return 4
    return 2   # USB, LSB, PH, SSB, FM, AM — all "Phone" for this contest


def _is_cw(mode: str) -> bool:
    # Prefix match, not equality: not1mm logs CW contacts as "CW-L"/"CW-U"
    # (sideband-tagged submode) rather than plain "CW". An equality check
    # silently priced every not1mm CW QSO as Phone (2 pts instead of 4) and
    # bucketed it under the "PHONE" mode key for multiplier/dupe purposes —
    # see issue #8.
    return (mode or "").upper().startswith("CW")


# WAE/DXCC-prefix-style callsign parser — reused pattern from other
# plugins for deriving a DXCC entity prefix from a callsign when needed
# as a fallback (CountryPrefix column is preferred when present).
_PORTABLE_SUFFIXES = frozenset({"P", "M", "MM", "AM", "QRP", "A", "E", "J", "LGT"})


def _entity_prefix_from_call(call: str) -> Optional[str]:
    """
    Crude DXCC-style entity prefix fallback, used only when N1MM's
    CountryPrefix column isn't available. Not a full DXCC prefix table —
    just enough to get a consistent, stable grouping key per callsign so
    "DXCC entities worked" still produces sensible (if occasionally
    imprecise) counts without that column.
    """
    c = (call or "").upper().strip()
    if not c:
        return None
    parts = [p for p in c.split("/") if p]
    if not parts:
        return None
    home = max(parts, key=len)
    others = [p for p in parts if p != home]
    portable = None
    for o in others:
        if o in _PORTABLE_SUFFIXES:
            continue
        portable = o
        break
    base = portable if portable else home
    m = re.match(r"^(\d{0,2}[A-Z]+)\d", base)
    if m:
        return m.group(1)
    m2 = re.match(r"^([A-Z]{1,2})", base)
    if m2:
        return m2.group(1)
    return base or None


def _extract_code(raw_ex: str, code_set: frozenset) -> Optional[str]:
    """
    Resolve a fixed-list exchange code (US state, VE province, XE state)
    from the received-exchange text. Tries an exact match first (N1MM's
    Exchange1 holding just the bare code), then falls back to scanning
    alphabetic tokens split on whitespace/digits — covers exchanges
    logged with the RST or serial number glued on in the same field
    (e.g. "5NN TX", "059 TX", "TX599"), which real-world N1MM logs
    commonly produce for this contest's single free-text exchange box.
    """
    if raw_ex in code_set:
        return raw_ex
    for token in re.findall(r"[A-Z]+", raw_ex):
        if token in code_set:
            return token
    return None


def _is_maritime_mobile(call: str) -> bool:
    c = (call or "").upper().strip()
    return c.endswith("/MM") or "/MM/" in c


def _entity_family(prefix: str) -> str:
    """
    Strip a trailing call-area digit from a DXCC-style/WPX-style prefix
    so two prefixes from the same entity but different call areas compare
    equal (e.g. "VK2" and "VK5" are both Australia; "W7" and "K5" are
    both the United States in this contest's bucketing since W/K/N/A-prefixes
    are pooled at the "United States" branch already, not per-call-area).

    Used only for the same-entity exclusion (own_entity comparison) — NOT
    used anywhere multiplier *identity* is determined, since e.g. distinct
    US states must stay distinct there.
    """
    p = (prefix or "").upper().strip()
    m = re.match(r"^([A-Z]+)\d*$", p)
    return m.group(1) if m else p


def _own_entity_prefix(qsos: list) -> Optional[str]:
    """
    Best-effort guess at the operator's own DXCC entity prefix, used only
    to exclude same-country contacts from multiplier credit (confirmed
    against a real N1MM-generated ARRL 10M log: VK5T working other VK
    stations shows IsMultiplier1=0 AND IsMultiplier2=0 for those QSOs —
    working your own country is correctly not a multiplier).

    We can't read a dedicated "my callsign" field from the qso rows
    (those describe the *worked* station), so this uses the "operator"
    field the loader already populates per-QSO — reliable for the
    overwhelming majority of single-op logs, since the keyed-in operator
    callsign and the contest station are the same. For genuine multi-op
    logs with several operator callsigns under one contest call, this is
    a best-effort fallback rather than a guarantee — same honest
    limitation as IARUPlugin._guess_op_ituz.
    """
    for q in qsos:
        op = str(q.get("operator") or "").upper().strip()
        if op:
            return _entity_prefix_from_call(op)
    return None


def _classify_exchange(q: dict, own_entity: Optional[str] = None) -> Optional[str]:
    """
    Return the resolved multiplier KEY for this QSO, or None if it isn't
    a multiplier-bearing contact (e.g. another DX station with no
    distinguishing W/VE/XE/ITU-region value AND no usable DXCC-entity
    info — extremely rare, but possible with malformed data — OR a
    contact with a station in the operator's own DXCC entity, which
    never counts as a multiplier).

    Multiplier keys are namespaced ("US:CA", "VE:ON", "XE:NL", "ITU:2",
    "DXCC:JA") so the Mexican "NL" (Nuevo Leon) and Canadian "NL"
    (Newfoundland & Labrador) abbreviations never collide, and so a
    state/province match never shadows a coincidentally-identical DXCC
    prefix.

    Resolution order, per rule 4 (what each station type sends) and rule
    5.2 (what counts as a multiplier):
      0. Worked station shares the operator's own DXCC entity (e.g. a
         VK station working another VK) → never a multiplier, confirmed
         against real N1MM output (both MULT1 and MULT2 flags are 0 for
         these QSOs even though the QSO itself still scores points).
      1. Maritime mobile (/MM in the callsign) → ITU region, from the
         received exchange (rule 4.4). This takes priority over any
         country-prefix-based DXCC classification, since rule 5.2.4
         (DXCC) and 5.2.4 (ITU region) are mutually exclusive in
         practice — a maritime mobile station isn't "in" any DXCC
         entity for contest purposes.
      2. Worked station's DXCC entity is the United States or its
         KH6/KL7 callsign areas → US state/DC, from the received
         exchange (rule 5.2.2.1: Hawaii/Alaska count as US states).
      3. Worked station's DXCC entity is Canada → VE province/territory,
         from the received exchange.
      4. Worked station's DXCC entity is Mexico → Mexican state, from
         the received exchange.
      5. Otherwise → DXCC entity multiplier, keyed by the worked
         station's DXCC entity prefix (CountryPrefix column, falling
         back to a derived prefix from the callsign).
    """
    call    = str(q.get("call") or "").upper()
    raw_ex  = str(q.get("mult1") or q.get("shire") or "").strip().upper()
    country = str(q.get("country_prefix") or "").strip().upper()

    # Resolve the worked station's DXCC entity early so the same-entity
    # exclusion can run before any other classification.
    entity_prefix = country or _entity_prefix_from_call(call) or ""

    if own_entity and entity_prefix and _entity_family(entity_prefix) == _entity_family(own_entity):
        return None   # working your own DXCC entity is never a multiplier

    if _is_maritime_mobile(call):
        # Received exchange should be "1", "2", or "3" (rule 4.4).
        digits = re.sub(r"[^0-9]", "", raw_ex)
        if digits and digits[0] in _ITU_SET:
            return f"ITU:{digits[0]}"
        return None   # malformed MM exchange — not a usable multiplier

    # United States (incl. Hawaii/Alaska, which use KH6/KL7 prefixes but
    # count as US states per rule 5.2.2.1) — trust the received exchange
    # value directly rather than re-deriving the state from the call,
    # since the rules define the multiplier by what was exchanged.
    if entity_prefix in ("K", "W", "N", "AA", "AB", "AC", "AD", "AE", "AF",
                          "AG", "AI", "AJ", "AK", "AL", "KH6", "KL7"):
        code = _extract_code(raw_ex, _US_SET)
        if code:
            return f"US:{code}"
        return None   # US station but exchange didn't parse to a known state

    # Canada
    if entity_prefix in ("VE", "VA", "VO", "VY", "CY", "CF", "CG", "CH",
                          "CI", "CJ", "CK", "CZ", "XJ", "XK", "XL", "XM",
                          "XN", "XO"):
        code = _extract_code(raw_ex, _VE_SET)
        if code:
            return f"VE:{code}"
        return None

    # Mexico
    if entity_prefix in ("XE", "XF", "XA", "XB", "XC", "4A", "4B", "6D",
                          "6E", "6F", "6G", "6H", "6I", "6J"):
        code = _extract_code(raw_ex, _XE_SET)
        if code:
            return f"XE:{code}"
        return None

    # Everyone else: DXCC entity multiplier.
    if entity_prefix:
        return f"DXCC:{entity_prefix}"
    return None


# ═════════════════════════════════════════════════════════════════════════════
# Plugin
# ═════════════════════════════════════════════════════════════════════════════

class ARRL10MPlugin(ContestPlugin):
    """
    ARRL 10-Meter Contest — single-band (28 MHz), mixed-mode.

    Written for a DX operator (e.g. VK). Multiplier = US states+DC +
    Canadian provinces/territories + Mexican states + DXCC entities +
    ITU regions (maritime mobile), each counted ONCE PER MODE rather
    than once per band (there is only one band in this contest).
    """

    # ── Identity ──────────────────────────────────────────────────────────────

    def identify(self, contest_name: str) -> bool:
        cn = contest_name.upper().replace(" ", "").replace("_", "").replace("-", "")
        keywords = ("ARRL10", "ARRL10M", "10METER", "TENMETER")
        return any(kw in cn for kw in keywords)

    @property
    def display_name(self) -> str:
        return "ARRL 10M"

    # ── Session / block structure ─────────────────────────────────────────────

    def session_config(self) -> SessionConfig:
        # 48-hour contest, Saturday 00:00 UTC – Sunday 23:59 UTC (operate
        # up to 36 of the 48 hours; off-times don't change the window
        # shown here). 4 x 12-hour blocks, matching CQWW's convention.
        return SessionConfig(
            duration_mins=720,
            num_sessions=4,
            label_prefix="B",
            start_hour=0,
        )

    # ── Multiplier contract ───────────────────────────────────────────────────

    def mult_list(self) -> list:
        """
        Fixed-list multipliers only (US states+DC, VE provinces, Mexican
        states, ITU regions). DXCC entities are open-ended and not
        included here, same reasoning as CQWW's country list — there is
        no fixed "missing DXCC entities" roster to track against.
        """
        return list(_ALL_FIXED_MULTS)

    def mult_label(self) -> str:
        return "Multiplier"

    def mult_of_qso(self, q: dict) -> Optional[str]:
        """
        Resolved, namespaced multiplier key for this QSO (see
        _classify_exchange for the full resolution order).

        NOTE: this base-class hook only receives a single QSO, so it
        can't resolve own_entity (which needs the full log to infer the
        operator's own callsign/entity) and therefore can't apply the
        same-DXCC-entity exclusion. This only affects callers of this
        specific method, not the actual scoring path — multipliers()
        and score() call _classify_exchange() directly with own_entity
        already resolved, so they're unaffected.
        """
        return _classify_exchange(q)

    # ── Dupe scope ──────────────────────────────────────────────────────────────
    # Rule 5.2.1: a station may be worked once per band per MODE (once on
    # Phone, once on CW) — not once per band overall. See issue #8: not1mm's
    # own dupe-checking doesn't appear to make this distinction and zeroes
    # Points for a legitimate different-mode rework the same way it would
    # for a genuine same-mode dupe, so ContestLog.load() needs this to
    # un-flag the false positives before recalc_pts() runs.
    mode_scoped_dupes = True

    def dupe_mode_key(self, qso: dict) -> str:
        return "CW" if _is_cw(qso.get("mode")) else "PHONE"

    @property
    def dupe_rule_text(self) -> str:
        return ("Per rule 5.2.1: a station may be worked once per band PER MODE "
                "(once on Phone, once on CW). Dupes score 0 pts and are not penalised.")

    # ── Exchange column hint ──────────────────────────────────────────────────

    @property
    def preferred_exchange_columns(self):
        # The received exchange (state/province/serial/ITU-region) lives
        # in Exchange1 in N1MM's standard schema for this contest.
        # not1mm's ARRL 10M plugin (plugins/arrl_10m.py's set_contact_vars())
        # writes the received exchange into the NR column instead and never
        # touches Exchange1 at all — leaving mult1 permanently blank (and
        # every US/VE/XE multiplier permanently "missing") for not1mm logs
        # unless NR is tried as a last-resort fallback here.
        return ["Exchange1", "exchange1", "RcvExch", "rcvexch", "NR", "nr"]

    # ── Scoring ───────────────────────────────────────────────────────────────

    def recalc_pts(self, qsos: list) -> None:
        """
        Re-derive QSO point values per rule 5.1: Phone = 2, CW = 4. Flat
        scale, no per-band variation (single-band contest) and no
        same-country/different-continent logic like CQWW — every valid
        contact scores, regardless of who's worked.

        We trust N1MM's stored pts when already populated and non-zero;
        we only fill in missing/zero values here.
        """
        for q in qsos:
            if q["dupe"]:
                continue
            if q.get("pts") and q["pts"] > 0:
                continue
            q["pts"] = _pts_for_mode(q.get("mode"), q.get("call", ""))

    def score(self, qsos: list) -> int:
        """Total QSO points × total multipliers (all categories, both
        modes, summed as one flat pool — rule 5.3)."""
        pts   = sum(q["pts"] for q in qsos if not q["dupe"])
        mr    = self.multipliers(qsos)
        mults = len(mr.primary_mults) + len(mr.secondary_mults)
        return pts * mults if mults else pts

    def multipliers(self, qsos: list) -> MultResult:
        """
        Primary mults : unique (multiplier_key, mode) pairs worked —
                         "once per phone, once per CW" per rule 5.2.1.

        IMPORTANT: N1MM internally tracks this contest's multipliers
        across TWO separate flag slots — IsMultiplier1 for US
        state/Canadian province/Mexican state, IsMultiplier2 for DXCC
        entity — verified against a real N1MM-generated ARRL 10M log
        (VK5T, Dec 2023: 2 QSOs flagged IsMultiplier1=1, 43 flagged
        IsMultiplier2=1, total 45 — exactly matching 334 pts × 45 mults
        = 15,030, the log's own claimed score). A QSO flagged on EITHER
        slot counts. All categories still pool into one combined set
        here (matching the rules text, which doesn't split a
        primary/secondary score component the way CQWW does) —
        secondary_mults stays empty; this is purely about reading both
        of N1MM's flag columns rather than just one.

        Falls back to collecting every valid (mult_key, mode) pair via
        _classify_exchange() when neither flag is present (e.g. a
        non-N1MM import) — that function already excludes same-DXCC-
        entity contacts (e.g. VK-to-VK), which N1MM's own flags also
        correctly never set.
        """
        combined: set = set()
        own_entity = _own_entity_prefix(qsos)
        has_flags = any(
            q.get("is_mult1") is not None or q.get("is_mult2") is not None
            for q in qsos
        )

        for q in qsos:
            if q["dupe"]:
                continue
            mult_key = _classify_exchange(q, own_entity)
            if not mult_key:
                continue
            mode_key = "CW" if _is_cw(q.get("mode")) else "PHONE"

            if has_flags:
                if q.get("is_mult1") == 1 or q.get("is_mult2") == 1:
                    combined.add((mult_key, mode_key))
            else:
                combined.add((mult_key, mode_key))

        return MultResult(
            primary_mults=combined,
            secondary_mults=set(),
            primary_label="Multipliers",
            secondary_label="",
        )

    # ── UI hints ──────────────────────────────────────────────────────────────

    def has_missing_tab(self) -> bool:
        return True   # fixed-list portion (US/VE/XE/ITU) supports this

    def band_list(self) -> list:
        # 28 MHz (10m) ONLY — this is a single-band contest (rule 2.3).
        return ["10M"]

    def has_region_heat(self) -> bool:
        return False

    def has_state_bars(self) -> bool:
        return False

    def post_snapshot(self, snap: dict, qsos: list) -> None:
        """
        Correct/augment the standard snapshot for ARRL 10M's flat,
        per-mode multiplier pool (rather than the generic per-band model
        most other plugins assume).

        % gauge: shown as % of the FIXED-LIST multipliers (US states+DC,
        VE provinces, Mexican states, ITU regions — 51+13+32+3 = 99
        possible values, doubled for two modes = 198) that have been
        worked. DXCC entities are intentionally excluded from this
        percentage (same reasoning as CQWW/AADX — open-ended, no fixed
        ceiling to measure against), so this is a genuine, bounded
        completion percentage rather than the always-0% trap that bit
        the AADX plugin before its post_snapshot fix.
        """
        mr = self.multipliers(qsos)
        fixed_set = set(_ALL_FIXED_MULTS)
        worked_fixed = {(k, m) for (k, m) in mr.primary_mults if k in fixed_set}
        max_fixed = len(_ALL_FIXED_MULTS) * 2   # × 2 modes

        snap["worked"]     = len(mr.primary_mults)
        snap["band_mults"] = len(mr.primary_mults)
        snap["zone_cnt"]   = len(worked_fixed)
        snap["pct"]        = (len(worked_fixed) / max_fixed * 100) if max_fixed else 0.0

    def gauge_defs(self, data: dict, total_mults: int) -> list:
        max_fixed_x2 = len(_ALL_FIXED_MULTS) * 2
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
                    "Non-dupe contacts on 10m. CW and Phone contacts with\n"
                    "the same station both count (mixed-mode credit)."
                ),
            ),
            GaugeDef(
                "TOTAL SCORE", "score", "score_max", ACCENT3(), "{v:,}",
                tooltip=(
                    "TOTAL SCORE\n"
                    "QSO points × total multipliers (all categories, both\n"
                    "modes, summed as one pool).\n"
                    "Phone = 2 pts/QSO, CW = 4 pts/QSO."
                ),
            ),
            GaugeDef(
                "MULTS (×MODE)", "band_mults", max(total_mults, 1), ACCENT3(), "{v}",
                tooltip=(
                    "MULTIPLIERS × MODE\n"
                    "Count of unique (multiplier, mode) pairs worked — the\n"
                    "actual figure used in the scoring formula. Working the\n"
                    "same state/entity on CW AND Phone counts twice here."
                ),
            ),
            GaugeDef(
                "FIXED WORKED", "zone_cnt", max_fixed_x2, GREEN(), "{v}",
                tooltip=(
                    "FIXED-LIST MULTIPLIERS WORKED\n"
                    "US states+DC, Canadian provinces/territories, Mexican\n"
                    "states, and ITU regions worked, counted per mode.\n"
                    f"Maximum = {max_fixed_x2} (99 fixed values × 2 modes).\n"
                    "DXCC entities are open-ended and excluded from this\n"
                    "count — see TOTAL DXCC below."
                ),
            ),
            GaugeDef(
                "% FIXED", "pct", 100.0, MUTED(), "{v:.1f}%",
                tooltip=(
                    "% OF FIXED-LIST MULTIPLIERS WORKED\n"
                    "FIXED WORKED ÷ maximum possible (99 × 2 modes).\n"
                    "Excludes open-ended DXCC entities, same reasoning as\n"
                    "the % gauges in the CQWW/AADX plugins."
                ),
            ),
        ]

    # ── Multiplier helpers (overrides) ────────────────────────────────────────

    def worked_primary_mults(self, qsos: list) -> set:
        """Unique multiplier keys worked (any mode) — for the missing-mults
        tab. Only the fixed-list portion is meaningful here; DXCC-entity
        keys are included in the set but missing_primary_mults() below
        only diffs against the fixed list."""
        result: set = set()
        own_entity = _own_entity_prefix(qsos)
        for q in qsos:
            if q["dupe"]:
                continue
            mult_key = _classify_exchange(q, own_entity)
            if mult_key:
                result.add(mult_key)
        return result

    def missing_primary_mults(self, qsos: list) -> list:
        """Fixed-list multipliers (US/VE/XE/ITU) not yet worked on
        EITHER mode. DXCC entities are excluded — open-ended, no fixed
        roster to diff against (same reasoning as CQWW)."""
        worked = self.worked_primary_mults(qsos)
        fixed_set = set(_ALL_FIXED_MULTS)
        return sorted(fixed_set - worked)

    def worked_primary_band_mults(self, qsos: list) -> set:
        """Unique (mult_key, mode, mode) tuples — for band/mode-breakdown
        panels. The mode appears twice (band-slot and mode-slot) since
        this contest has no real "band" axis distinct from mode; this
        keeps the tuple shape consistent with what the UI expects from
        plugins that do have a band axis."""
        result: set = set()
        own_entity = _own_entity_prefix(qsos)
        has_flags = any(
            q.get("is_mult1") is not None or q.get("is_mult2") is not None
            for q in qsos
        )
        for q in qsos:
            if q["dupe"]:
                continue
            mult_key = _classify_exchange(q, own_entity)
            if not mult_key:
                continue
            mode = q.get("mode", "?")
            if has_flags:
                if q.get("is_mult1") == 1 or q.get("is_mult2") == 1:
                    result.add((mult_key, mode, mode))
            else:
                result.add((mult_key, mode, mode))
        return result

    def worked_secondary_band_mults(self, qsos: list) -> set:
        """ARRL 10M has no secondary multiplier type — always empty."""
        return set()

    def sparkline_mults(self, q: dict, seen: set) -> int:
        """
        Count a new (mult_key, mode) multiplier for the running
        new-mults-rate chart.

        Honors EITHER N1MM flag (IsMultiplier1 for state/province,
        IsMultiplier2 for DXCC entity) — see multipliers() for why both
        matter; a real log showed 43 of 45 real multipliers living in
        the MULT2 slot alone.

        NOTE: this base-class hook only receives a single QSO (no list
        access), so it can't resolve own_entity and therefore can't
        exclude same-DXCC-entity contacts (e.g. VK-to-VK) the way
        multipliers()/score() do. This only affects this minor "new
        mults per hour" rate chart, not the actual score/mult counts.
        """
        mult_key = _classify_exchange(q)
        if not mult_key:
            return 0
        mode = "CW" if _is_cw(q.get("mode")) else "PHONE"
        key  = (mult_key, mode)
        has_flags = q.get("is_mult1") is not None or q.get("is_mult2") is not None
        if has_flags:
            if (q.get("is_mult1") == 1 or q.get("is_mult2") == 1) and key not in seen:
                seen.add(key)
                return 1
        elif key not in seen:
            seen.add(key)
            return 1
        return 0

    def running_score_for_sparkline(self, qsos_up_to_hour: list) -> int:
        pts   = sum(q["pts"] for q in qsos_up_to_hour if not q["dupe"])
        mr    = self.multipliers(qsos_up_to_hour)
        mults = len(mr.primary_mults) + len(mr.secondary_mults)
        return pts * mults if mults else pts

    # ── Band/mode efficiency override ─────────────────────────────────────────

    def band_efficiency(self, qsos: list) -> list:
        """
        Per-MODE breakdown (CW vs Phone), reusing the "band efficiency"
        panel slot since this contest has no per-band axis to show
        instead. Shows QSOs, new multipliers, and efficiency for each
        mode — directly answers "is CW or Phone earning more mults per
        QSO right now," which is the single-band equivalent of CQWW's
        per-band efficiency view.
        """
        mode_qsos  = defaultdict(int)
        mode_pts   = defaultdict(int)
        mode_mults = defaultdict(set)
        own_entity = _own_entity_prefix(qsos)

        def _mode_label(q):
            return "CW" if _is_cw(q.get("mode")) else "Phone"

        for q in qsos:
            if q["dupe"]:
                continue
            mode_label = _mode_label(q)
            mode_qsos[mode_label] += 1
            mode_pts[mode_label]  += q.get("pts", 0) or 0
            mult_key = _classify_exchange(q, own_entity)
            if mult_key:
                mode_mults[mode_label].add(mult_key)

        time_stats = self._band_time_stats(qsos, key_fn=_mode_label)
        result = []
        for m in mode_qsos:
            qn = mode_qsos[m]
            mn = len(mode_mults[m])
            ts = time_stats.get(m, {"best_hour_rate": 0, "last_qso_utc": None})
            result.append({
                "band":        m,          # generic key expected by the UI
                "qsos":        qn,
                "pts":         mode_pts[m],
                "new_shires":  mn,
                "efficiency":  mn / qn if qn else 0,
                "pts_per_qso": _pts_for_mode("CW" if m == "CW" else "SSB"),
                **ts,
            })
        return sorted(result, key=lambda x: x["efficiency"], reverse=True)
