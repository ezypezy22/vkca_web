"""
plugins/base.py
───────────────
Abstract base class for all VK Contest Analyzer contest plugins, plus the
shared dataclasses (SessionConfig, MultResult, GaugeDef) that every plugin
and the main app depend on.

Plugins import from here:
    from plugins.base import ContestPlugin, SessionConfig, MultResult, GaugeDef

Theme colours (ACCENT, ACCENT3, GREEN, MUTED) are resolved lazily from the
main app's module namespace so plugins don't hard-code hex values.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from datetime import date as date_, timedelta
from typing import Optional


# ── Colour shim ───────────────────────────────────────────────────────────────
# Plugins reference theme colours by name.  The values live in vkcontest_
# analyzer.py's module namespace and are rebound when the user switches
# themes.  We read that module directly at call time so changes propagate
# automatically without needing to scan every loaded module.

def _colour(name: str, fallback: str) -> str:
    try:
        import vkcontest_analyzer as _va
    except ImportError:
        return fallback
    val = getattr(_va, name, None)
    if isinstance(val, str) and val.startswith("#") and len(val) in (7, 9):
        return val
    return fallback

def ACCENT()  -> str: return _colour("ACCENT",  "#00d4aa")
def ACCENT2() -> str: return _colour("ACCENT2", "#ff6b35")
def ACCENT3() -> str: return _colour("ACCENT3", "#f0c040")
def GREEN()   -> str: return _colour("GREEN",   "#2ed573")
def MUTED()   -> str: return _colour("MUTED",   "#8b949e")


# ═════════════════════════════════════════════════════════════════════════════
# Shared dataclasses
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class SessionConfig:
    """Describes the block/session structure of a contest."""
    duration_mins: int
    num_sessions:  int
    label_prefix:  str = "B"
    start_hour:    int = None


@dataclass
class MultResult:
    """Multiplier totals returned by a plugin."""
    primary_mults:   set
    secondary_mults: set
    primary_label:   str
    secondary_label: str


@dataclass
class GaugeDef:
    """One arc gauge on the overview dashboard."""
    label:     str
    value_key: str
    max_key:   str
    colour:    str
    fmt:       str = "{v}"
    tooltip:   str = ""


# ═════════════════════════════════════════════════════════════════════════════
# Abstract plugin base
# ═════════════════════════════════════════════════════════════════════════════

class ContestPlugin(ABC):
    """
    Abstract base for all contest plug-ins.

    A plugin owns everything that differs between contests:
      - multiplier identification and counting
      - scoring formula
      - session/block structure
      - which overview panels make sense
      - gauge labels and maxima

    ContestLog calls the plugin; App calls ContestLog.
    Neither ContestLog nor App contains any per-contest logic.
    """

    # ── Identity ──────────────────────────────────────────────────────────────

    @abstractmethod
    def identify(self, contest_name: str) -> bool:
        """Return True when this plugin owns the given N1MM ContestName string."""
        ...

    @property
    def display_name(self) -> str:
        return self.__class__.__name__.replace("Plugin", "")

    # ── Session / block structure ─────────────────────────────────────────────

    @abstractmethod
    def session_config(self) -> SessionConfig: ...

    # ── Multiplier contract ───────────────────────────────────────────────────

    @abstractmethod
    def mult_list(self) -> list: ...

    @abstractmethod
    def mult_label(self) -> str: ...

    @abstractmethod
    def mult_of_qso(self, q: dict) -> Optional[str]: ...

    def region_of_mult(self, m: str) -> Optional[str]:
        return None

    def region_list(self) -> list:
        return []

    # ── Scoring ───────────────────────────────────────────────────────────────

    @abstractmethod
    def score(self, qsos: list) -> int: ...

    @abstractmethod
    def multipliers(self, qsos: list) -> MultResult: ...

    def recalc_pts(self, qsos: list) -> None:
        pass

    # True for contests where a station may legitimately be worked once per
    # band PER MODE (e.g. ARRL 10M rule 5.2.1: once per phone, once per CW)
    # rather than once per band overall (the WPX-style default every other
    # plugin here assumes). When True, ContestLog.load() cross-checks the
    # source log's own zero-points-implies-dupe signal against per-
    # (call, band, dupe_mode_key) history before trusting it — needed
    # because not1mm's own dupe-checking is not known to make this
    # distinction, and will zero out Points for a legitimate different-mode
    # rework just as it would for a genuine same-mode dupe.
    mode_scoped_dupes: bool = False

    def dupe_mode_key(self, qso: dict) -> str:
        """Mode bucket used for the mode_scoped_dupes check above. Only
        consulted when mode_scoped_dupes is True — override to reuse
        whatever CW/Phone/Digital classifier the plugin already has for
        scoring/multipliers, so dupe-scoping agrees with them (e.g. so
        "CW", "CW-L", "CW-U" all land in the same bucket rather than being
        treated as different modes)."""
        return str(qso.get("mode") or "").strip().upper()

    @property
    def dupe_rule_text(self) -> str:
        """One-line rule description shown on the Dupes tab. Generic
        default rather than any specific contest's name — this used to be
        hardcoded to WPX's wording regardless of the active contest (see
        issue #8), which read as flatly wrong for anything else. Override
        per-plugin where the actual rule differs (e.g. mode_scoped_dupes
        contests like ARRL 10M)."""
        return "A station may be worked once per band. Dupes score 0 pts and are not penalised."

    def post_snapshot(self, snap: dict, qsos: list) -> None:
        """
        Called by ContestLog.compute_snapshot() after the standard calculation.
        Plugins override this to correct or augment display values in *snap*
        without duplicating the full snapshot logic.

        Default: no-op.
        """
        pass

    @property
    def preferred_exchange_columns(self):
        return None

    # ── UI hints ──────────────────────────────────────────────────────────────

    def band_list(self) -> list:
        """
        Ordered list of bands legal for this contest (low → high), used by
        the frontend's "What if?" band dropdown so it doesn't offer a band
        the contest's own rules exclude (e.g. WARC bands in a CQWW-style
        DX contest). Default is the full band plan this app otherwise knows
        about — override with a narrower list once a plugin's rules have
        been checked for an explicit band restriction; leave unoverridden
        if that hasn't been verified yet.
        """
        return ["160M", "80M", "60M", "40M", "30M", "20M", "17M", "15M",
                "12M", "10M", "6M", "2M", "70CM"]

    def gauge_defs(self, data: dict, total_mults: int) -> list:
        ml = self.mult_label()
        return [
            GaugeDef("TOTAL QSOs",            "total",      "qso_max",   ACCENT(),  "{v}"),
            GaugeDef("VALID QSOs",            "valid",      "qso_max",   GREEN(),   "{v}"),
            GaugeDef("TOTAL SCORE",           "score",      "score_max", ACCENT3(), "{v:,}"),
            GaugeDef(f"{ml.upper()}S WORKED", "worked",     total_mults, ACCENT3(), "{v}"),
            GaugeDef(f"{ml.upper()} MULTS",   "band_mults", total_mults, GREEN(),   "{v}"),
            GaugeDef("CQ ZONES",              "zone_cnt",   40,          "#64b5f6", "{v}"),
            GaugeDef("% COMPLETE",            "pct",        100.0,       MUTED(),   "{v:.1f}%"),
        ]

    def has_missing_tab(self) -> bool:
        return True

    def has_region_heat(self) -> bool:
        return bool(self.region_list())

    def has_state_bars(self) -> bool:
        return bool(self.region_list())

    # ── Multiplier helpers ────────────────────────────────────────────────────

    def worked_primary_mults(self, qsos: list) -> set:
        # Delegates to mult_of_qso() rather than checking q["mult1"] against
        # mult_list() directly, so plugins with extra per-QSO resolution logic
        # beyond a literal mult1 match (e.g. vk_shires.py's short-form-to-full
        # shire code resolution via callsign area) are correctly counted as
        # worked here too, not just in their own overrides.
        result: set = set()
        for q in qsos:
            if q["dupe"]:
                continue
            m = self.mult_of_qso(q)
            if m:
                result.add(m)
        return result

    def worked_primary_band_mults(self, qsos: list) -> set:
        # Delegates to mult_of_qso() for the multiplier's identity, same as
        # worked_primary_mults() above and for the same reason (see its
        # comment): a plugin's mult_of_qso() may resolve a value beyond a
        # literal mult1 match (e.g. vk_shires.py's short-form-to-full shire
        # code resolution via callsign area). Previously this method used
        # raw q["mult1"] directly, so any plugin relying on it (instead of
        # overriding it, as most already do) could silently score wrong —
        # two QSOs whose raw exchange text differs but resolve to the same
        # true multiplier would count as two band-mults instead of one,
        # inflating the score for any plugin whose score()/multipliers()
        # calls this method directly (see issue #29).
        #
        # The is_mult1 flag (when the source's own DB provides it) is used
        # only to decide WHETHER a QSO counts as a newly-worked band-mult,
        # never to source the multiplier's identity string itself.
        has_m1 = any(q["is_mult1"] is not None for q in qsos)
        result: set = set()
        for q in qsos:
            if q["dupe"]:
                continue
            if has_m1 and q["is_mult1"] != 1:
                continue
            m = self.mult_of_qso(q)
            if m:
                result.add((m, q["band"], q["mode"]))
        return result

    def worked_secondary_band_mults(self, qsos: list) -> set:
        has_m2 = any(q["is_mult2"] is not None for q in qsos)
        if has_m2:
            return {(q["cqz"], q["band"], q["mode"]) for q in qsos
                    if not q["dupe"] and q["is_mult2"] == 1 and q["cqz"] is not None}
        return {(q["cqz"], q["band"], q["mode"]) for q in qsos
                if not q["dupe"] and q["cqz"] is not None}

    def missing_primary_mults(self, qsos: list) -> list:
        return sorted(set(self.mult_list()) - self.worked_primary_mults(qsos))

    def mults_by_region(self, qsos: list) -> dict:
        worked = self.worked_primary_mults(qsos)
        result = {}
        for m in self.mult_list():
            reg = self.region_of_mult(m) or "__none__"
            if reg not in result:
                result[reg] = {"worked": [], "missing": []}
            if m in worked:
                result[reg]["worked"].append(m)
            else:
                result[reg]["missing"].append(m)
        return result

    def region_heat(self, qsos: list) -> list:
        if not self.region_list():
            return []
        ml_set        = set(self.mult_list())
        region_total  = defaultdict(int)
        region_qsos   = defaultdict(int)
        region_worked = defaultdict(set)
        for m in self.mult_list():
            reg = self.region_of_mult(m)
            if reg:
                region_total[reg] += 1
        for q in qsos:
            if not q["dupe"] and q["mult1"] in ml_set:
                reg = self.region_of_mult(q["mult1"])
                if reg:
                    region_qsos[reg]   += 1
                    region_worked[reg].add(q["mult1"])
        result = []
        for reg in region_total:
            w = len(region_worked[reg])
            t = region_total[reg]
            result.append({"state": reg, "qsos": region_qsos[reg],
                           "worked": w, "total": t,
                           "pct": w / t * 100 if t else 0})
        return sorted(result, key=lambda x: x["qsos"], reverse=True)

    def _band_time_stats(self, qsos: list, key_fn=None) -> dict:
        """
        Best-60-minute QSO rate and most-recent QSO timestamp, grouped by
        band (default) — contest-agnostic (pure QSO-time math, no scoring
        rules involved), so every plugin's band_efficiency() override can
        pull these two fields from here instead of reimplementing the same
        band_hours/band_last bookkeeping. Returns {key: {"best_hour_rate":
        int, "last_qso_utc": str|None}}; a key with no non-dupe QSOs is
        simply absent from the dict — callers should default missing keys
        to {"best_hour_rate": 0, "last_qso_utc": None}.

        Pass key_fn to group by something other than band (e.g.
        plugins/arrl10m.py groups by mode instead, since that contest has
        no per-band axis) — key_fn(q) -> the grouping key for that QSO.

        Feeds the Bands tab's BEST RATE / LAST QSO columns (bands.js reads
        best_hour_rate / last_qso_utc directly) — every plugin override that
        omitted these left those two columns blank (see issue #19).
        """
        key_fn = key_fn or (lambda q: q.get("band") or "?")
        key_last  = {}              # key → most-recent QSO datetime
        key_hours = defaultdict(lambda: defaultdict(int))  # key → hour → count

        for q in qsos:
            if q["dupe"]:
                continue
            k = key_fn(q)
            t = q.get("time")
            if t is None:
                continue
            if k not in key_last or t > key_last[k]:
                key_last[k] = t
            h_key = t.replace(minute=0, second=0, microsecond=0)
            key_hours[k][h_key] += 1

        result = {}
        for k in key_hours:
            result[k] = {
                "best_hour_rate": max(key_hours[k].values()),
                "last_qso_utc":   key_last[k].isoformat() if key_last.get(k) else None,
            }
        return result

    def band_efficiency(self, qsos: list) -> list:
        ml_set      = set(self.mult_list())
        band_qsos   = defaultdict(int)
        band_pts    = defaultdict(int)
        band_mults  = defaultdict(set)

        for q in qsos:
            if not q["dupe"]:
                b = q["band"] or "?"
                band_qsos[b] += 1
                band_pts[b]  += q.get("pts", 0) or 0
                if q["mult1"] in ml_set:
                    band_mults[b].add(q["mult1"])

        time_stats = self._band_time_stats(qsos)
        result = []
        for b in band_qsos:
            qn = band_qsos[b]
            mn = len(band_mults[b])
            ts = time_stats.get(b, {"best_hour_rate": 0, "last_qso_utc": None})
            result.append({
                "band":           b,
                "qsos":           qn,
                "pts":            band_pts[b],
                "new_shires":     mn,
                "efficiency":     mn / qn if qn else 0,
                **ts,
            })
        return sorted(result, key=lambda x: x["efficiency"], reverse=True)

    def uses_cq_zone_scoring(self) -> bool:
        """True when recalc_pts()/scoring for this contest depends on the
        worked station's CQ/ITU zone (stored in the 'cqz' field) — used by
        the what-if replay to warn when a zone wasn't supplied."""
        return False

    def efficiency_label(self) -> str:
        """Human label for what band_efficiency()'s 'efficiency' field means.
        Most plugins rank bands by mults-per-QSO; a few (vk_rd, hasprnt) rank
        by points-per-QSO instead — this lets cross-year comparisons avoid
        conflating the two."""
        return "mults/qso"

    def sparkline_mults(self, q: dict, seen: set) -> int:
        count = 0
        key1 = (q["mult1"], q["band"], q["mode"])
        if q.get("is_mult1") == 1 and key1 not in seen:
            count += 1; seen.add(key1)
        key2 = (q.get("cqz"), q["band"], q["mode"])
        if q.get("is_mult2") == 1 and key2 not in seen:
            count += 1; seen.add(key2)
        return count

    def running_score_for_sparkline(self, qsos_up_to_hour: list) -> int:
        pts = sum(q["pts"] for q in qsos_up_to_hour if not q["dupe"])
        mr  = self.multipliers(qsos_up_to_hour)
        total_mults = len(mr.primary_mults) + len(mr.secondary_mults)
        return pts * total_mults if total_mults else pts
