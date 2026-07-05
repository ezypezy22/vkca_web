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
        has_m1 = any(q["is_mult1"] is not None for q in qsos)
        ml = self.mult_list()
        if has_m1:
            return {(q["mult1"], q["band"], q["mode"]) for q in qsos
                    if not q["dupe"] and q["is_mult1"] == 1 and q["mult1"]}
        return {(q["mult1"], q["band"], q["mode"]) for q in qsos
                if not q["dupe"] and q["mult1"] in ml}

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

    def band_efficiency(self, qsos: list) -> list:
        ml_set      = set(self.mult_list())
        band_qsos   = defaultdict(int)
        band_pts    = defaultdict(int)
        band_mults  = defaultdict(set)
        band_last   = {}              # band → most-recent QSO datetime
        band_hours  = defaultdict(lambda: defaultdict(int))  # band → hour → count

        for q in qsos:
            if not q["dupe"]:
                b = q["band"] or "?"
                band_qsos[b] += 1
                band_pts[b]  += q.get("pts", 0) or 0
                if q["mult1"] in ml_set:
                    band_mults[b].add(q["mult1"])
                t = q.get("time")
                if t is not None:
                    if b not in band_last or t > band_last[b]:
                        band_last[b] = t
                    h_key = t.replace(minute=0, second=0, microsecond=0)
                    band_hours[b][h_key] += 1

        result = []
        for b in band_qsos:
            qn   = band_qsos[b]
            mn   = len(band_mults[b])
            best = max(band_hours[b].values()) if band_hours[b] else 0
            last = band_last.get(b)
            result.append({
                "band":           b,
                "qsos":           qn,
                "pts":            band_pts[b],
                "new_shires":     mn,
                "efficiency":     mn / qn if qn else 0,
                "best_hour_rate": best,
                "last_qso_utc":   last.isoformat() if last else None,
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
