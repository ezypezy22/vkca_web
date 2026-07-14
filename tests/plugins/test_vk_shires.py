"""Tests for the VK Shires Contest plugin."""

from __future__ import annotations

from typing import Optional

import pytest

from plugins.vk_shires import ALL_SHIRES, VKShiresPlugin

# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def plugin() -> VKShiresPlugin:
    return VKShiresPlugin()


# ═══════════════════════════════════════════════════════════════════════════════
# identify
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdentify:
    """VKShiresPlugin.identify() — contest name matching."""

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("VKSHIRES2025", True),
            ("SHIRES", True),
            ("CQWW", False),
        ],
    )
    def test_identify(self, plugin: VKShiresPlugin, name: str, expected: bool) -> None:
        assert plugin.identify(name) is expected


# ═══════════════════════════════════════════════════════════════════════════════
# mult_list
# ═══════════════════════════════════════════════════════════════════════════════


class TestMultList:
    """VKShiresPlugin.mult_list() — returns the ALL_SHIRES list."""

    def test_returns_all_shires(self, plugin: VKShiresPlugin) -> None:
        lst = plugin.mult_list()
        assert lst == ALL_SHIRES

    def test_is_non_empty(self, plugin: VKShiresPlugin) -> None:
        assert len(plugin.mult_list()) > 0

    def test_contains_expected_shires(self, plugin: VKShiresPlugin) -> None:
        lst = plugin.mult_list()
        assert "ACT-CT1" in lst
        assert "NSW-SY2" in lst
        assert "VIC-ML3" not in lst  # VIC uses suffix 5, not 3


# ═══════════════════════════════════════════════════════════════════════════════
# mult_of_qso
# ═══════════════════════════════════════════════════════════════════════════════


class TestMultOfQso:
    """VKShiresPlugin.mult_of_qso() — packed, short-form, and fallback."""

    def test_packed_form_resolves(self, plugin: VKShiresPlugin) -> None:
        """Full shire code stored in mult1 passes through directly."""
        q = {"mult1": "ACT-CT1", "raw_mult": "CT1", "call": "VK1ABC"}
        assert plugin.mult_of_qso(q) == "ACT-CT1"

    def test_short_form_resolves_via_area_digit(self, plugin: VKShiresPlugin) -> None:
        """'SY2' with VK2 call → 'NSW-SY2'."""
        q = {"mult1": "SY2", "raw_mult": "SY2", "call": "VK2YI"}
        result = plugin.mult_of_qso(q)
        assert result == "NSW-SY2"

    def test_short_form_vk4_resolves(self, plugin: VKShiresPlugin) -> None:
        """'BN4' with VK4 call → 'QLD-BN3' (QLD → suffix 3, not 4)."""
        q = {"mult1": "BN4", "raw_mult": "BN4", "call": "VK4GSI"}
        result = plugin.mult_of_qso(q)
        assert result == "QLD-BN3"

    def test_unparseable_raw_value_returns_none(self, plugin: VKShiresPlugin) -> None:
        """Garbage raw mult with no resolvable prefix → None."""
        q = {"mult1": "ZZZZ", "raw_mult": "ZZZZ", "call": "VK2YI"}
        assert plugin.mult_of_qso(q) is None
