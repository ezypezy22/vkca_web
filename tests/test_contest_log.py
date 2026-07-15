"""Tests for the data layer in contest_log.py."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from contest_log import (
    ContestLog,
    _freq_to_band,
    call_area_from_call,
    cqz_from_call,
    state_from_call,
)
from plugins.generic import GenericPlugin

# ═══════════════════════════════════════════════════════════════════════════════
# _freq_to_band
# ═══════════════════════════════════════════════════════════════════════════════


class TestFreqToBand:
    """_freq_to_band() — band edge cases and out-of-range."""

    @pytest.mark.parametrize(
        "freq_hz,expected",
        [
            (1_800_000, "160M"),
            (3_500_000, "80M"),
            (7_000_000, "40M"),
            (14_000_000, "20M"),
            (21_000_000, "15M"),
            (28_000_000, "10M"),
            (50_000_000, "6M"),
            (144_000_000, "2M"),
        ],
    )
    def test_known_bands(self, freq_hz: int, expected: str) -> None:
        assert _freq_to_band(freq_hz) == expected

    @pytest.mark.parametrize("freq_hz", [100_000, 1_000_000_000])
    def test_out_of_range_returns_mhz_string(self, freq_hz: int) -> None:
        result = _freq_to_band(freq_hz)
        assert result.endswith("MHz")


# ═══════════════════════════════════════════════════════════════════════════════
# cqz_from_call
# ═══════════════════════════════════════════════════════════════════════════════


class TestCqzFromCall:
    """cqz_from_call() — VK area mapping, standard prefixes, unknown."""

    @pytest.mark.parametrize(
        "call,expected",
        [
            ("VK2YI", 29),
            ("VK3ABC", 29),
            ("VK4ABC", 30),
            ("W1AW", 5),
            ("ZL3AB", 32),
            ("JA1ABC", 25),
        ],
    )
    def test_known_calls(self, call: str, expected: int) -> None:
        assert cqz_from_call(call) == expected

    def test_unknown_prefix_returns_none(self) -> None:
        assert cqz_from_call("XX1ABC") is None


# ═══════════════════════════════════════════════════════════════════════════════
# call_area_from_call
# ═══════════════════════════════════════════════════════════════════════════════


class TestCallAreaFromCall:
    """call_area_from_call() — VK prefix and portable notation."""

    @pytest.mark.parametrize(
        "call,expected",
        [
            ("VK2YI", 2),
            ("VK3ABC", 3),
            ("VK6WA", 6),
        ],
    )
    def test_vk_prefix(self, call: str, expected: int) -> None:
        assert call_area_from_call(call) == expected

    def test_vk_has_priority_over_portable(self) -> None:
        """VK area is matched first; the portable /4 is only checked when
        there is no VK prefix, so VK2YI/4 returns 2 (not 4)."""
        assert call_area_from_call("VK2YI/4") == 2

    def test_portable_notation_non_vk(self) -> None:
        """Non-VK call with portable suffix uses the suffix."""
        assert call_area_from_call("ZL3AB/4") == 4

    def test_non_vk_returns_none(self) -> None:
        assert call_area_from_call("ZL3AB") is None


# ═══════════════════════════════════════════════════════════════════════════════
# state_from_call
# ═══════════════════════════════════════════════════════════════════════════════


class TestStateFromCall:
    """state_from_call() — VK area to state mapping."""

    @pytest.mark.parametrize(
        "call,expected",
        [
            ("VK1ABC", "ACT"),
            ("VK2YI", "NSW"),
            ("VK3ABC", "VIC"),
            ("VK4ABC", "QLD"),
            ("VK5ABC", "SA"),
            ("VK6ABC", "WA"),
            ("VK7ABC", "TAS"),
            ("VK8ABC", "NT"),
        ],
    )
    def test_area_to_state(self, call: str, expected: str) -> None:
        assert state_from_call(call) == expected

    def test_non_vk_returns_none(self) -> None:
        assert state_from_call("ZL3AB") is None


# ═══════════════════════════════════════════════════════════════════════════════
# Available contests
# ═══════════════════════════════════════════════════════════════════════════════


class TestAvailableContests:
    """ContestLog.available_contests() with the fixture database."""

    def test_returns_one_contest(self, sample_contest_db: Path) -> None:
        contests = ContestLog.available_contests(str(sample_contest_db))
        assert len(contests) == 1

    def test_contest_fields(self, sample_contest_db: Path) -> None:
        contests = ContestLog.available_contests(str(sample_contest_db))
        ct = contests[0]
        assert ct["ContestName"] == "VKSHIRES2025"
        assert ct["DisplayName"] == "VK Shires 2025"
        assert ct["QSOCount"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# __init__ / load
# ═══════════════════════════════════════════════════════════════════════════════


class TestContestLogInit:
    """ContestLog.__init__() — QSO loading from the fixture DB."""

    def test_loads_qsos(self, sample_contest_db: Path) -> None:
        plugin = GenericPlugin()
        cl = ContestLog(str(sample_contest_db), contest_nr=1, plugin=plugin)
        assert len(cl.qsos) >= 1
        first = cl.qsos[0]
        assert first["call"] == "VK2YI"
        assert first["band"] == "20M"
        assert first["mode"] == "CW"

    def test_contest_start_date_set(self, sample_contest_db: Path) -> None:
        plugin = GenericPlugin()
        cl = ContestLog(str(sample_contest_db), contest_nr=1, plugin=plugin)
        assert cl._contest_start_dt is not None


# ═══════════════════════════════════════════════════════════════════════════════
# valid_qsos / total_qsos / total_points
# ═══════════════════════════════════════════════════════════════════════════════


class TestQsoCounts:
    """ContestLog.valid_qsos() / total_qsos() / total_points() with fixture."""

    def test_valid_qsos(self, sample_contest_db: Path) -> None:
        plugin = GenericPlugin()
        cl = ContestLog(str(sample_contest_db), contest_nr=1, plugin=plugin)
        # The single fixture QSO has no dupe column → dupe defaults to False
        assert cl.valid_qsos() == 1

    def test_total_qsos(self, sample_contest_db: Path) -> None:
        plugin = GenericPlugin()
        cl = ContestLog(str(sample_contest_db), contest_nr=1, plugin=plugin)
        assert cl.total_qsos() == 1

    def test_total_points(self, sample_contest_db: Path) -> None:
        plugin = GenericPlugin()
        cl = ContestLog(str(sample_contest_db), contest_nr=1, plugin=plugin)
        assert cl.total_points() == 1  # fixture QSO has Points=1


# ═══════════════════════════════════════════════════════════════════════════════
# rate_by_hour
# ═══════════════════════════════════════════════════════════════════════════════


class TestRateByHour:
    """ContestLog.rate_by_hour() — UTC hour bucketing."""

    def test_buckets_by_utc_hour(self, sample_contest_db: Path) -> None:
        plugin = GenericPlugin()
        cl = ContestLog(str(sample_contest_db), contest_nr=1, plugin=plugin)
        rate = cl.rate_by_hour()
        assert len(rate) >= 1
        # Fixture QSO is at 2025-01-01 01:00:00
        expected_hour = datetime(2025, 1, 1, 1, 0, 0)
        assert rate[0][0] == expected_hour
        assert rate[0][1] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# dupe_analysis
# ═══════════════════════════════════════════════════════════════════════════════


class TestDupeAnalysis:
    """ContestLog.dupe_analysis() — by_band and by_call breakdowns."""

    def test_no_dupes(self, sample_contest_db: Path) -> None:
        plugin = GenericPlugin()
        cl = ContestLog(str(sample_contest_db), contest_nr=1, plugin=plugin)
        by_band, by_call = cl.dupe_analysis()
        # Fixture QSO is not a dupe → both defaultdicts are empty
        assert len(by_band) == 0
        assert len(by_call) == 0
