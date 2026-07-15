"""Tests for shared base classes in plugins/base.py."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import pytest

from plugins.base import (
    ContestPlugin,
    GaugeDef,
    MultResult,
    SessionConfig,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Minimal concrete plugin for testing abstract-class behaviour
# ═══════════════════════════════════════════════════════════════════════════════


class _TestPlugin(ContestPlugin):
    """Minimal concrete plugin used by tests in this file."""

    def identify(self, contest_name: str) -> bool:
        return contest_name == "TEST"

    def session_config(self) -> SessionConfig:
        return SessionConfig(duration_mins=60, num_sessions=2)

    def mult_list(self) -> list:
        return ["NSW-SY2", "NSW-AR2", "VIC-ML3"]

    def mult_label(self) -> str:
        return "Shire"

    def mult_of_qso(self, q: dict) -> Optional[str]:
        return q.get("mult1") or None

    def score(self, qsos: list) -> int:
        mr = self.multipliers(qsos)
        pts = sum(q["pts"] for q in qsos if not q["dupe"])
        return pts * (len(mr.primary_mults) + len(mr.secondary_mults))

    def multipliers(self, qsos: list) -> MultResult:
        return MultResult(
            self.worked_primary_band_mults(qsos),
            self.worked_secondary_band_mults(qsos),
            "MULTS",
            "ZONES",
        )

    def region_of_mult(self, m: str) -> Optional[str]:
        return m.split("-")[0] if "-" in m else None

    def region_list(self) -> list:
        return ["NSW", "VIC"]


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def plugin() -> _TestPlugin:
    return _TestPlugin()


def _q(**overrides: object) -> dict:
    """Build a minimal QSO dict with useful defaults."""
    base: dict = {
        "call": "VK2YI",
        "band": "20M",
        "mode": "CW",
        "time": datetime(2025, 1, 1, 1, 0, 0),
        "mult1": "NSW-SY2",
        "cqz": 29,
        "is_mult1": None,
        "is_mult2": None,
        "dupe": False,
        "pts": 1,
    }
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════════════════════
# SessionConfig
# ═══════════════════════════════════════════════════════════════════════════════


class TestSessionConfig:
    """SessionConfig dataclass — construction, default values."""

    def test_construction(self) -> None:
        sc = SessionConfig(duration_mins=120, num_sessions=3)
        assert sc.duration_mins == 120
        assert sc.num_sessions == 3

    def test_default_label_prefix(self) -> None:
        sc = SessionConfig(duration_mins=60, num_sessions=1)
        assert sc.label_prefix == "B"

    def test_default_start_hour(self) -> None:
        sc = SessionConfig(duration_mins=60, num_sessions=1)
        assert sc.start_hour is None


# ═══════════════════════════════════════════════════════════════════════════════
# MultResult
# ═══════════════════════════════════════════════════════════════════════════════


class TestMultResult:
    """MultResult dataclass — construction with sets."""

    def test_construction_with_sets(self) -> None:
        mr = MultResult(
            {"NSW-SY2", "NSW-AR2"},
            {"Z1", "Z2"},
            "SHIRES",
            "ZONES",
        )
        assert mr.primary_mults == {"NSW-SY2", "NSW-AR2"}
        assert mr.secondary_mults == {"Z1", "Z2"}
        assert mr.primary_label == "SHIRES"
        assert mr.secondary_label == "ZONES"

    def test_empty_sets(self) -> None:
        mr = MultResult(set(), set(), "MULTS", "ZONES")
        assert mr.primary_mults == set()
        assert mr.secondary_mults == set()


# ═══════════════════════════════════════════════════════════════════════════════
# GaugeDef
# ═══════════════════════════════════════════════════════════════════════════════


class TestGaugeDef:
    """GaugeDef dataclass — construction, default fmt."""

    def test_construction(self) -> None:
        g = GaugeDef("TOTAL QSOs", "total", "qso_max", "#00d4aa")
        assert g.label == "TOTAL QSOs"
        assert g.value_key == "total"
        assert g.max_key == "qso_max"
        assert g.colour == "#00d4aa"

    def test_default_fmt(self) -> None:
        g = GaugeDef("Test", "k", "m", "#fff")
        assert g.fmt == "{v}"

    def test_default_tooltip(self) -> None:
        g = GaugeDef("Test", "k", "m", "#fff")
        assert g.tooltip == ""


# ═══════════════════════════════════════════════════════════════════════════════
# ContestPlugin abstract class — defaults
# ═══════════════════════════════════════════════════════════════════════════════


class TestContestPluginDefaults:
    """ContestPlugin abstract class default property values."""

    def test_display_name_fallback(self, plugin: _TestPlugin) -> None:
        """display_name strips 'Plugin' from the class name."""
        assert plugin.display_name == "_Test"

    def test_dupe_rule_text_default(self, plugin: _TestPlugin) -> None:
        text = plugin.dupe_rule_text
        assert "once per band" in text.lower()

    def test_has_missing_tab_default(self, plugin: _TestPlugin) -> None:
        assert plugin.has_missing_tab() is True

    def test_band_list_default(self, plugin: _TestPlugin) -> None:
        bands = plugin.band_list()
        assert "160M" in bands
        assert "20M" in bands
        assert "10M" in bands
        assert isinstance(bands, list)


# ═══════════════════════════════════════════════════════════════════════════════
# worked_primary_mults
# ═══════════════════════════════════════════════════════════════════════════════


class TestWorkedPrimaryMults:
    """ContestPlugin.worked_primary_mults() — dupe filtering, None handling."""

    def test_filters_dupes(self, plugin: _TestPlugin) -> None:
        qsos = [
            _q(mult1="NSW-SY2", dupe=False),
            _q(mult1="NSW-AR2", dupe=True),
        ]
        result = plugin.worked_primary_mults(qsos)
        assert "NSW-AR2" not in result, "dupe mult should be excluded"
        assert result == {"NSW-SY2"}

    def test_no_dupes(self, plugin: _TestPlugin) -> None:
        qsos = [
            _q(mult1="NSW-SY2", dupe=False),
            _q(mult1="NSW-AR2", dupe=False),
        ]
        result = plugin.worked_primary_mults(qsos)
        assert result == {"NSW-SY2", "NSW-AR2"}

    def test_mult_of_qso_returns_none(self, plugin: _TestPlugin) -> None:
        qsos = [_q(mult1="", dupe=False)]
        result = plugin.worked_primary_mults(qsos)
        assert result == set()


# ═══════════════════════════════════════════════════════════════════════════════
# missing_primary_mults
# ═══════════════════════════════════════════════════════════════════════════════


class TestMissingPrimaryMults:
    """ContestPlugin.missing_primary_mults() — sorted complement."""

    def test_returns_sorted_complement(self, plugin: _TestPlugin) -> None:
        qsos = [_q(mult1="NSW-SY2", dupe=False)]
        result = plugin.missing_primary_mults(qsos)
        assert result == ["NSW-AR2", "VIC-ML3"]

    def test_all_worked_returns_empty(self, plugin: _TestPlugin) -> None:
        qsos = [_q(mult1=m, dupe=False) for m in plugin.mult_list()]
        result = plugin.missing_primary_mults(qsos)
        assert result == []


# ═══════════════════════════════════════════════════════════════════════════════
# worked_primary_band_mults
# ═══════════════════════════════════════════════════════════════════════════════


class TestWorkedPrimaryBandMults:
    """ContestPlugin.worked_primary_band_mults() — is_mult1 flag presence."""

    def test_with_is_mult1_flag(self, plugin: _TestPlugin) -> None:
        """When any QSO has a non-None is_mult1, only is_mult1==1 entries count."""
        qsos = [
            _q(mult1="NSW-SY2", band="20M", mode="CW", is_mult1=1),
            _q(mult1="NSW-AR2", band="40M", mode="SSB", is_mult1=0),
            _q(mult1="NSW-SY2", band="20M", mode="SSB", is_mult1=None),
        ]
        result = plugin.worked_primary_band_mults(qsos)
        assert ("NSW-SY2", "20M", "CW") in result
        assert ("NSW-AR2", "40M", "SSB") not in result
        assert ("NSW-SY2", "20M", "SSB") not in result

    def test_without_is_mult1_flag(self, plugin: _TestPlugin) -> None:
        """When is_mult1 is universally None, uses mult_list membership."""
        qsos = [
            _q(mult1="NSW-SY2", band="20M", mode="CW", is_mult1=None),
            _q(mult1="XXX-YYY", band="40M", mode="SSB", is_mult1=None),
        ]
        result = plugin.worked_primary_band_mults(qsos)
        assert ("NSW-SY2", "20M", "CW") in result
        assert ("XXX-YYY", "40M", "SSB") not in result


# ═══════════════════════════════════════════════════════════════════════════════
# band_efficiency
# ═══════════════════════════════════════════════════════════════════════════════


class TestBandEfficiency:
    """ContestPlugin.band_efficiency() — grouping, best_hour_rate, calc."""

    def test_correct_band_grouping(self, plugin: _TestPlugin) -> None:
        qsos = [
            _q(band="20M", mult1="NSW-SY2", dupe=False, time=datetime(2025, 1, 1, 1, 0, 0)),
            _q(band="20M", mult1="NSW-AR2", dupe=False, time=datetime(2025, 1, 1, 1, 30, 0)),
            _q(band="40M", mult1="VIC-ML3", dupe=False, time=datetime(2025, 1, 1, 2, 0, 0)),
        ]
        result = plugin.band_efficiency(qsos)
        bands = {r["band"] for r in result}
        assert bands == {"20M", "40M"}

    def test_best_hour_rate(self, plugin: _TestPlugin) -> None:
        t = datetime(2025, 1, 1, 1, 0, 0)
        qsos = [
            _q(band="20M", dupe=False, time=t),
            _q(band="20M", dupe=False, time=t.replace(minute=10)),
            _q(band="20M", dupe=False, time=datetime(2025, 1, 1, 2, 0, 0)),
        ]
        result = plugin.band_efficiency(qsos)
        band20 = next(r for r in result if r["band"] == "20M")
        assert band20["best_hour_rate"] == 2

    def test_efficiency_calculation(self, plugin: _TestPlugin) -> None:
        """efficiency = mults / qsos per band."""
        qsos = [
            _q(band="20M", mult1="NSW-SY2", dupe=False, time=datetime(2025, 1, 1, 1, 0, 0)),
            _q(band="20M", mult1="NSW-SY2", dupe=False, time=datetime(2025, 1, 1, 1, 30, 0)),
            _q(band="20M", mult1="NSW-AR2", dupe=False, time=datetime(2025, 1, 1, 2, 0, 0)),
        ]
        result = plugin.band_efficiency(qsos)
        band20 = next(r for r in result if r["band"] == "20M")
        # 2 unique mults / 3 QSOs = 0.666...
        assert band20["efficiency"] == pytest.approx(2 / 3)

    def test_dupes_excluded_from_counts(self, plugin: _TestPlugin) -> None:
        qsos = [
            _q(band="20M", mult1="NSW-SY2", dupe=False, time=datetime(2025, 1, 1, 1, 0, 0)),
            _q(band="20M", mult1="NSW-SY2", dupe=True, time=datetime(2025, 1, 1, 1, 30, 0)),
        ]
        result = plugin.band_efficiency(qsos)
        band20 = next(r for r in result if r["band"] == "20M")
        assert band20["qsos"] == 1
        assert band20["efficiency"] == 1.0

    def test_results_sorted_by_efficiency_desc(self, plugin: _TestPlugin) -> None:
        qsos = [
            _q(band="40M", mult1="VIC-ML3", dupe=False, time=datetime(2025, 1, 1, 0, 0, 0)),
            _q(band="20M", mult1="NSW-SY2", dupe=False, time=datetime(2025, 1, 1, 1, 0, 0)),
            _q(
                band="20M", mult1="NSW-SY2", dupe=False, time=datetime(2025, 1, 1, 2, 0, 0)
            ),  # lowers 20M efficiency
        ]
        result = plugin.band_efficiency(qsos)
        efficiencies = [r["efficiency"] for r in result]
        assert efficiencies == sorted(efficiencies, reverse=True)


# ═══════════════════════════════════════════════════════════════════════════════
# mults_by_region
# ═══════════════════════════════════════════════════════════════════════════════


class TestMultsByRegion:
    """ContestPlugin.mults_by_region() — region grouping."""

    def test_with_region_of_mult(self, plugin: _TestPlugin) -> None:
        qsos = [_q(mult1="NSW-SY2", dupe=False)]
        result = plugin.mults_by_region(qsos)
        assert "NSW" in result
        assert "VIC" in result
        assert result["NSW"]["worked"] == ["NSW-SY2"]
        assert result["NSW"]["missing"] == ["NSW-AR2"]
        assert result["VIC"]["worked"] == []
        assert result["VIC"]["missing"] == ["VIC-ML3"]

    def test_without_region_of_mult(self, plugin: _TestPlugin) -> None:
        class _NoRegionPlugin(_TestPlugin):
            def region_of_mult(self, m: str) -> Optional[str]:
                return None

        p = _NoRegionPlugin()
        qsos = [_q(mult1="NSW-SY2", dupe=False)]
        result = p.mults_by_region(qsos)
        assert "__none__" in result
        assert result["__none__"]["worked"] == ["NSW-SY2"]
        assert "NSW-SY2" in result["__none__"]["worked"]


# ═══════════════════════════════════════════════════════════════════════════════
# sparkline_mults
# ═══════════════════════════════════════════════════════════════════════════════


class TestSparklineMults:
    """ContestPlugin.sparkline_mults() — is_mult1 and is_mult2 tracking."""

    def test_is_mult1_seen_counts(self, plugin: _TestPlugin) -> None:
        q = _q(mult1="NSW-SY2", band="20M", mode="CW", is_mult1=1, cqz=29)
        seen: set = set()
        assert plugin.sparkline_mults(q, seen) == 1
        assert plugin.sparkline_mults(q, seen) == 0  # already seen

    def test_is_mult1_unseen(self, plugin: _TestPlugin) -> None:
        q = _q(mult1="NSW-SY2", band="20M", mode="CW", is_mult1=None, cqz=29)
        seen: set = set()
        assert plugin.sparkline_mults(q, seen) == 0

    def test_is_mult2_counts(self, plugin: _TestPlugin) -> None:
        q = _q(mult1="NSW-SY2", band="20M", mode="CW", is_mult1=0, is_mult2=1, cqz=29)
        seen: set = set()
        count = plugin.sparkline_mults(q, seen)
        # is_mult1 != 1 so only is_mult2 branch can fire
        assert count == 1
