"""Tests for utility functions in web/server.py.

NOTE: web/server.py has heavy external dependencies (uvicorn, fastapi, etc.)
and local modules (cosb, qrz) that aren't always available in isolation.
We inject stubs so the import succeeds.
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

# ═══════════════════════════════════════════════════════════════════════════════
# Flexible stub infrastructure for modules we want to mock
# ═══════════════════════════════════════════════════════════════════════════════


class _StubModule(ModuleType):
    """A module that auto-creates any attribute you ask for, so any
    ``from stub import Whatever`` or ``stub.Whatever()`` just works."""

    def __getattr__(self, name: str) -> Any:
        # Return a class that accepts any constructor arguments
        class _Auto:
            def __init__(self, *a: Any, **kw: Any) -> None:
                pass

            def __call__(self, *a: Any, **kw: Any) -> Any:
                return self

            def __getattr__(self, n: str) -> Any:
                return _Auto()

        val = _Auto()
        setattr(self, name, val)
        return val


def _install_stub(name: str) -> None:
    """Ensure *name* is inserted into sys.modules as a _StubModule."""
    if name not in sys.modules:
        sys.modules[name] = _StubModule(name, "")


# Install stubs for every module web/server.py might touch
for _name in ("uvicorn", "cosb", "qrz"):
    _install_stub(_name)

for _name in ("fastapi", "fastapi.responses", "fastapi.staticfiles"):
    _install_stub(_name)


# Now safe to import from web.server
from web.server import AppState, _json_safe  # noqa: E402

# ═══════════════════════════════════════════════════════════════════════════════
# _json_safe
# ═══════════════════════════════════════════════════════════════════════════════


class TestJsonSafe:
    """_json_safe() — JSON-safe serialisation of special types."""

    def test_datetime_to_isoformat(self) -> None:
        dt = datetime(2025, 1, 1, 12, 30, 0)
        assert _json_safe(dt) == "2025-01-01T12:30:00"

    def test_date_to_isoformat(self) -> None:
        d = date(2025, 6, 15)
        assert _json_safe(d) == "2025-06-15"

    def test_nan_to_none(self) -> None:
        assert _json_safe(float("nan")) is None

    def test_dict_filters_private_keys(self) -> None:
        d: dict[str, Any] = {"public": 1, "_private": 2, "__magic": 3}
        result = _json_safe(d)
        assert result == {"public": 1}

    def test_list_of_mixed_types(self) -> None:
        lst: list[Any] = [1, "hello", 3.14]
        assert _json_safe(lst) == [1, "hello", 3.14]

    def test_float_inf_passes_through(self) -> None:
        """json.dumps accepts float('inf') with allow_nan=True by default,
        so _json_safe returns it as-is without conversion."""
        result = _json_safe(float("inf"))
        assert isinstance(result, float)
        import math

        assert math.isinf(result)


# ═══════════════════════════════════════════════════════════════════════════════
# AppState.validate_path
# ═══════════════════════════════════════════════════════════════════════════════


class TestValidatePath:
    """AppState.validate_path() — path validation."""

    def test_existing_file_passes(self, tmp_path: Path) -> None:
        f = tmp_path / "test.s3db"
        f.write_text("dummy content")
        assert AppState.validate_path(str(f)) is None

    def test_missing_file_returns_error(self, tmp_path: Path) -> None:
        f = tmp_path / "nonexistent.s3db"
        err = AppState.validate_path(str(f))
        assert err is not None
        assert "not found" in err.lower()

    def test_directory_returns_error(self, tmp_path: Path) -> None:
        err = AppState.validate_path(str(tmp_path))
        assert err is not None
        assert "folder" in err.lower() or "directory" in err.lower()

    def test_wrong_extension_returns_error(self, tmp_path: Path) -> None:
        f = tmp_path / "data.txt"
        f.write_text("dummy")
        err = AppState.validate_path(str(f))
        assert err is not None
        assert ".s3db" in err or ".db" in err or ".sqlite" in err
