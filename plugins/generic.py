"""
plugins/generic.py
──────────────────
Generic fallback plugin for contests without a dedicated plugin.

Shows QSOs, score, band breakdown, and CQ zones.
No missing-mults tab, no region heat.

This plugin's identify() always returns True so it must be registered LAST
in the plugin loader — it acts as a catch-all.
"""

from __future__ import annotations

from typing import Optional

from plugins.base import (
    ACCENT,
    ACCENT3,
    GREEN,
    MUTED,
    ContestPlugin,
    GaugeDef,
    MultResult,
    SessionConfig,
)


class GenericPlugin(ContestPlugin):
    """
    Fallback for contests without a dedicated plugin.
    Shows QSOs, score, band breakdown and CQ zones only.
    No missing-mults tab, no region heat.
    """

    # Always matches — must be registered last.
    def identify(self, contest_name: str) -> bool:
        return True

    @property
    def display_name(self) -> str:
        return "Generic"

    def session_config(self) -> SessionConfig:
        # Single unbounded session — the generic fallback has no way to
        # know the actual contest duration, so use a single large block.
        # Durations of zero are handled by ContestLog.session_status()
        # as a single unbounded session.
        return SessionConfig(duration_mins=0, num_sessions=1)

    def mult_list(self) -> list:
        return []

    def mult_label(self) -> str:
        return "Mult"

    def mult_of_qso(self, q: dict) -> Optional[str]:
        return q.get("mult1") or None

    def has_missing_tab(self) -> bool:
        return False

    def has_region_heat(self) -> bool:
        return False

    def has_state_bars(self) -> bool:
        return False

    def score(self, qsos: list) -> int:
        mr = self.multipliers(qsos)
        pts = sum(q["pts"] for q in qsos if not q["dupe"])
        total_mults = len(mr.primary_mults) + len(mr.secondary_mults)
        return pts * total_mults if total_mults else pts

    def multipliers(self, qsos: list) -> MultResult:
        return MultResult(
            self.worked_primary_band_mults(qsos),
            self.worked_secondary_band_mults(qsos),
            "MULTS",
            "CQ ZONES",
        )

    def gauge_defs(self, data: dict, total_mults: int) -> list:
        return [
            GaugeDef("TOTAL QSOs", "total", "qso_max", ACCENT(), "{v}"),
            GaugeDef("VALID QSOs", "valid", "qso_max", GREEN(), "{v}"),
            GaugeDef("TOTAL SCORE", "score", "score_max", ACCENT3(), "{v:,}"),
            GaugeDef("MULTS", "band_mults", 100, ACCENT3(), "{v}"),
            GaugeDef("CQ ZONES", "zone_cnt", 40, "#64b5f6", "{v}"),
            GaugeDef("% COMPLETE", "pct", 100.0, MUTED(), "{v:.1f}%"),
        ]
