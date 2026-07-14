"""Shared fixtures for VK Contest Analyzer tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def sample_qso() -> dict[str, Any]:
    """A minimal valid QSO dict as produced by contest_log.py load()."""
    return {
        "call": "VK2YI",
        "band": "20M",
        "mode": "CW",
        "time": datetime(2025, 1, 1, 1, 0, 0),
        "mult1": "NSW-SY2",
        "shire": "NSW-SY2",
        "cqz": 29,
        "is_mult1": None,
        "is_mult2": None,
        "dupe": False,
        "pts": 3,
        "raw_mult": "SY2",
        "mult_source": "SHORT+DIGIT",
        "qso_id": "1",
        "operator": "",
        "continent": "OC",
        "_table": "DXLOG",
        "qrz_name": "",
        "qrz_grid": "",
        "qrz_state": "",
        "qrz_status": "none",
    }


@pytest.fixture
def sample_contest_db(tmp_path: Path) -> Path:
    """Create a minimal .s3db with one contest instance and one QSO."""
    import sqlite3

    db = tmp_path / "test_contest.s3db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE ContestInstance ("
        "  ContestNR INTEGER PRIMARY KEY,"
        "  ContestName TEXT,"
        "  StartDate TEXT"
        ")"
    )
    conn.execute("CREATE TABLE Contest (Name TEXT PRIMARY KEY, DisplayName TEXT)")
    conn.execute(
        "CREATE TABLE DXLOG ("
        "  ID INTEGER PRIMARY KEY,"
        "  ContestNR INTEGER,"
        "  Call TEXT,"
        "  Band TEXT,"
        "  Mode TEXT,"
        "  QSOTime TEXT,"
        "  Points INTEGER"
        ")"
    )
    conn.execute(
        "INSERT INTO ContestInstance (ContestNR, ContestName, StartDate) "
        "VALUES (1, 'VKSHIRES2025', '2025-01-01 00:00:00')"
    )
    conn.execute(
        "INSERT INTO Contest (Name, DisplayName) VALUES ('VKSHIRES2025', 'VK Shires 2025')"
    )
    conn.execute(
        "INSERT INTO DXLOG (ID, ContestNR, Call, Band, Mode, QSOTime, Points) "
        "VALUES (1, 1, 'VK2YI', '20M', 'CW', '2025-01-01 01:00:00', 1)"
    )
    conn.commit()
    conn.close()
    return db
