"""Tests for the VK Trans-Tasman Contest plugin."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import pytest

from plugins.vk_transtasman import (
    VKTransTasmanPlugin,
    _is_vktt_workable,
    _wpx_prefix,
)

# ═══════════════════════════════════════════════════════════════════════════════
# _wpx_prefix
# ═══════════════════════════════════════════════════════════════════════════════


class TestWpxPrefix:
    """_wpx_prefix() — prefix derivation from callsign."""

    @pytest.mark.parametrize(
        "call,expected",
        [
            ("VK2YI", "VK2"),
            ("ZL3AB", "ZL3"),
            ("VJ4K", "VJ4"),
            ("VL5A", "VL5"),
            ("AX3T", "AX3"),
            ("VK2YI/P", "VK2"),  # suffix stripped
            ("VK2YI/MM", "VK2"),  # /MM stripped
            ("VK6/ON4ABC", "ON4"),  # portable, longer wins
            ("9M2ABC", "9M2"),
        ],
    )
    def test_prefix_derivation(self, call: str, expected: str) -> None:
        assert _wpx_prefix(call) == expected


# ═══════════════════════════════════════════════════════════════════════════════
# _is_vktt_workable
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsVkttWorkable:
    """_is_vktt_workable() — VK/ZL eligibility check."""

    @pytest.mark.parametrize(
        "call,expected",
        [
            ("VK2YI", True),
            ("ZL3AB", True),
            ("AX3T", True),
            ("VI2ABC", True),
            ("VJ4K", True),
            ("VL5A", True),
            ("K1ABC", False),
            ("JA1ABC", False),
            ("", False),
        ],
    )
    def test_workable_status(self, call: str, expected: bool) -> None:
        assert _is_vktt_workable(call) is expected


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def plugin() -> VKTransTasmanPlugin:
    return VKTransTasmanPlugin()


def _q(**overrides: object) -> dict:
    base: dict = {
        "call": "VK2YI",
        "band": "20M",
        "mode": "CW",
        "time": datetime(2025, 1, 1, 1, 0, 0),
        "mult1": "",
        "cqz": 29,
        "is_mult1": None,
        "is_mult2": None,
        "dupe": False,
        "pts": 0,
    }
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════════════════════
# identify
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdentify:
    """VKTransTasmanPlugin.identify() — contest name matching."""

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("VKTTRTTY", True),
            ("VKTTSSBCW", True),
            ("TRANS-TASMAN", True),
            ("TRANSTASMAN", True),
            ("CQWW", False),
        ],
    )
    def test_identify(self, plugin: VKTransTasmanPlugin, name: str, expected: bool) -> None:
        assert plugin.identify(name) is expected


# ═══════════════════════════════════════════════════════════════════════════════
# mult_of_qso
# ═══════════════════════════════════════════════════════════════════════════════


class TestMultOfQso:
    """VKTransTasmanPlugin.mult_of_qso() — stored prefix vs derived from call."""

    def test_stored_valid_prefix_used(self, plugin: VKTransTasmanPlugin) -> None:
        q = _q(mult1="VK2")
        assert plugin.mult_of_qso(q) == "VK2"

    def test_derived_from_call_when_no_stored(self, plugin: VKTransTasmanPlugin) -> None:
        q = _q(mult1="", call="ZL3AB")
        assert plugin.mult_of_qso(q) == "ZL3"

    def test_returns_none_when_no_call(self, plugin: VKTransTasmanPlugin) -> None:
        q = _q(mult1="", call="")
        assert plugin.mult_of_qso(q) is None


# ═══════════════════════════════════════════════════════════════════════════════
# recalc_pts
# ═══════════════════════════════════════════════════════════════════════════════


class TestRecalcPts:
    """VKTransTasmanPlugin.recalc_pts() — point assignment."""

    def test_vk_gets_1pt(self, plugin: VKTransTasmanPlugin) -> None:
        qsos = [_q(call="VK2YI", dupe=False)]
        plugin.recalc_pts(qsos)
        assert qsos[0]["pts"] == 1

    def test_zl_gets_1pt(self, plugin: VKTransTasmanPlugin) -> None:
        qsos = [_q(call="ZL3AB", dupe=False)]
        plugin.recalc_pts(qsos)
        assert qsos[0]["pts"] == 1

    def test_non_vkzl_gets_0pt(self, plugin: VKTransTasmanPlugin) -> None:
        qsos = [_q(call="K1ABC", dupe=False)]
        plugin.recalc_pts(qsos)
        assert qsos[0]["pts"] == 0

    def test_dupe_gets_0pt_even_if_workable(self, plugin: VKTransTasmanPlugin) -> None:
        qsos = [_q(call="VK2YI", dupe=True)]
        plugin.recalc_pts(qsos)
        assert qsos[0]["pts"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# band_efficiency
# ═══════════════════════════════════════════════════════════════════════════════


class TestBandEfficiency:
    """VKTransTasmanPlugin.band_efficiency() — custom override."""

    def test_returns_correct_shape(self, plugin: VKTransTasmanPlugin) -> None:
        qsos = [
            _q(band="20M", call="VK2YI", dupe=False, time=datetime(2025, 1, 1, 1, 0, 0)),
            _q(band="40M", call="ZL3AB", dupe=False, time=datetime(2025, 1, 1, 2, 0, 0)),
        ]
        result = plugin.band_efficiency(qsos)
        assert len(result) == 2
        for entry in result:
            assert "band" in entry
            assert "qsos" in entry
            assert "pts" in entry
            assert "new_shires" in entry
            assert "efficiency" in entry
            assert "best_hour_rate" in entry
            assert "last_qso_utc" in entry

    def test_dupes_excluded(self, plugin: VKTransTasmanPlugin) -> None:
        qsos = [
            _q(band="20M", call="VK2YI", dupe=False, time=datetime(2025, 1, 1, 1, 0, 0)),
            _q(band="20M", call="VK2YI", dupe=True, time=datetime(2025, 1, 1, 1, 30, 0)),
        ]
        result = plugin.band_efficiency(qsos)
        band20 = next(r for r in result if r["band"] == "20M")
        assert band20["qsos"] == 1

    def test_mults_use_wpx_prefixes(self, plugin: VKTransTasmanPlugin) -> None:
        qsos = [
            _q(band="20M", call="VK2YI", dupe=False, time=datetime(2025, 1, 1, 1, 0, 0)),
            _q(band="20M", call="ZL3AB", dupe=False, time=datetime(2025, 1, 1, 1, 30, 0)),
        ]
        result = plugin.band_efficiency(qsos)
        band20 = next(r for r in result if r["band"] == "20M")
        # Two different WPX prefixes on 20M
        assert band20["new_shires"] == 2
