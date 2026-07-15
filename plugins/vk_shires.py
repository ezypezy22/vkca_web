"""
plugins/vk_shires.py
────────────────────
WIA VK Shires Contest plugin.

Contest rules:
  6 × 4-hour blocks = 24 hours total (0000–0000 UTC).
  Score = total valid points × (shire band/mode mults + CQ zone band/mode mults).
  Multiplier: unique VK Shire/Council identifier per band per mode.
  DupeType 3: same call workable once per block per band.

To add/remove shires, edit data/shires.json (or update ALL_SHIRES below as a fallback).
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
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

_SHIRES_CACHE: list[str] | None = None


def _load_shires() -> list[str]:
    global _SHIRES_CACHE
    if _SHIRES_CACHE is not None:
        return _SHIRES_CACHE
    data_path = Path(__file__).resolve().parent.parent / "data" / "shires.json"
    if data_path.exists():
        try:
            with data_path.open() as f:
                _SHIRES_CACHE = json.load(f)
            return _SHIRES_CACHE
        except Exception as exc:
            logging.warning("Failed to load shires.json: %s", exc)
    logging.warning("shires.json not found, using built-in fallback list")
    _SHIRES_CACHE = list(ALL_SHIRES)
    return _SHIRES_CACHE


# ── Built-in fallback shire list (used only when data/shires.json is absent) ──

ALL_SHIRES = [
    # ACT
    "ACT-CT1",
    # NSW
    "NSW-AC2",
    "NSW-AR2",
    "NSW-BA2",
    "NSW-BD2",
    "NSW-BE2",
    "NSW-BH2",
    "NSW-BK2",
    "NSW-BL2",
    "NSW-BM2",
    "NSW-BN2",
    "NSW-BO2",
    "NSW-BQ2",
    "NSW-BR2",
    "NSW-BS2",
    "NSW-BU2",
    "NSW-BV2",
    "NSW-BW2",
    "NSW-BX2",
    "NSW-BY2",
    "NSW-CB2",
    "NSW-CC2",
    "NSW-CD2",
    "NSW-CE2",
    "NSW-CF2",
    "NSW-CG2",
    "NSW-CH2",
    "NSW-CI2",
    "NSW-CJ2",
    "NSW-CK2",
    "NSW-CL2",
    "NSW-CM2",
    "NSW-CN2",
    "NSW-CO2",
    "NSW-CP2",
    "NSW-CQ2",
    "NSW-CR2",
    "NSW-CS2",
    "NSW-CU2",
    "NSW-CV2",
    "NSW-CW2",
    "NSW-CX2",
    "NSW-CY2",
    "NSW-DA2",
    "NSW-DC2",
    "NSW-DE2",
    "NSW-DU2",
    "NSW-EC2",
    "NSW-EL2",
    "NSW-FA2",
    "NSW-FB2",
    "NSW-FO2",
    "NSW-GA2",
    "NSW-GB2",
    "NSW-GE2",
    "NSW-GF2",
    "NSW-GG2",
    "NSW-GH2",
    "NSW-GI2",
    "NSW-GJ2",
    "NSW-GL2",
    "NSW-GM2",
    "NSW-GN2",
    "NSW-GP2",
    "NSW-GS2",
    "NSW-GT2",
    "NSW-GU2",
    "NSW-GV2",
    "NSW-GW2",
    "NSW-GX2",
    "NSW-HA2",
    "NSW-HB2",
    "NSW-HC2",
    "NSW-HD2",
    "NSW-HE2",
    "NSW-HF2",
    "NSW-HG2",
    "NSW-HH2",
    "NSW-HI2",
    "NSW-HJ2",
    "NSW-HK2",
    "NSW-HL2",
    "NSW-HM2",
    "NSW-HN2",
    "NSW-HP2",
    "NSW-HR2",
    "NSW-HS2",
    "NSW-HT2",
    "NSW-HU2",
    "NSW-HV2",
    "NSW-HW2",
    "NSW-HX2",
    "NSW-HY2",
    "NSW-HZ2",
    "NSW-IA2",
    "NSW-IB2",
    "NSW-IC2",
    "NSW-ID2",
    "NSW-IE2",
    "NSW-IG2",
    "NSW-IH2",
    "NSW-II2",
    "NSW-IJ2",
    "NSW-IK2",
    "NSW-IL2",
    "NSW-IM2",
    "NSW-IN2",
    "NSW-IP2",
    "NSW-IQ2",
    "NSW-IR2",
    "NSW-IS2",
    "NSW-IT2",
    "NSW-IU2",
    "NSW-IV2",
    "NSW-IW2",
    "NSW-IX2",
    "NSW-IY2",
    "NSW-IZ2",
    "NSW-JA2",
    "NSW-JB2",
    "NSW-JC2",
    "NSW-JD2",
    "NSW-JE2",
    "NSW-JF2",
    "NSW-JG2",
    "NSW-JH2",
    "NSW-JI2",
    "NSW-JJ2",
    "NSW-JK2",
    "NSW-JL2",
    "NSW-JM2",
    "NSW-JN2",
    "NSW-JP2",
    "NSW-JQ2",
    "NSW-JR2",
    "NSW-JS2",
    "NSW-JT2",
    "NSW-JU2",
    "NSW-JV2",
    "NSW-JW2",
    "NSW-JX2",
    "NSW-JY2",
    "NSW-JZ2",
    "NSW-KA2",
    "NSW-KB2",
    "NSW-KC2",
    "NSW-KD2",
    "NSW-KE2",
    "NSW-KF2",
    "NSW-KG2",
    "NSW-KH2",
    "NSW-KI2",
    "NSW-KJ2",
    "NSW-KK2",
    "NSW-KL2",
    "NSW-KM2",
    "NSW-KN2",
    "NSW-KO2",
    "NSW-KP2",
    "NSW-KQ2",
    "NSW-KR2",
    "NSW-KS2",
    "NSW-KT2",
    "NSW-KU2",
    "NSW-KV2",
    "NSW-KW2",
    "NSW-KX2",
    "NSW-KY2",
    "NSW-KZ2",
    "NSW-LA2",
    "NSW-LB2",
    "NSW-LC2",
    "NSW-LD2",
    "NSW-LE2",
    "NSW-LF2",
    "NSW-LG2",
    "NSW-LH2",
    "NSW-LI2",
    "NSW-LJ2",
    "NSW-LK2",
    "NSW-LL2",
    "NSW-LM2",
    "NSW-LN2",
    "NSW-LO2",
    "NSW-LP2",
    "NSW-LQ2",
    "NSW-LR2",
    "NSW-LS2",
    "NSW-LT2",
    "NSW-LU2",
    "NSW-LV2",
    "NSW-LW2",
    "NSW-LX2",
    "NSW-MA2",
    "NSW-MC2",
    "NSW-MD2",
    "NSW-ME2",
    "NSW-MF2",
    "NSW-MG2",
    "NSW-MH2",
    "NSW-MI2",
    "NSW-MJ2",
    "NSW-MK2",
    "NSW-ML2",
    "NSW-MM2",
    "NSW-MN2",
    "NSW-MO2",
    "NSW-MP2",
    "NSW-MQ2",
    "NSW-MR2",
    "NSW-MS2",
    "NSW-MT2",
    "NSW-MU2",
    "NSW-MV2",
    "NSW-MW2",
    "NSW-MX2",
    "NSW-MY2",
    "NSW-MZ2",
    "NSW-NA2",
    "NSW-NB2",
    "NSW-NC2",
    "NSW-ND2",
    "NSW-NE2",
    "NSW-NF2",
    "NSW-NG2",
    "NSW-NH2",
    "NSW-NI2",
    "NSW-NJ2",
    "NSW-NK2",
    "NSW-NL2",
    "NSW-NM2",
    "NSW-NN2",
    "NSW-NO2",
    "NSW-NP2",
    "NSW-NQ2",
    "NSW-NR2",
    "NSW-NS2",
    "NSW-NT2",
    "NSW-NU2",
    "NSW-NV2",
    "NSW-NW2",
    "NSW-NX2",
    "NSW-NY2",
    "NSW-NZ2",
    "NSW-OA2",
    "NSW-OB2",
    "NSW-OC2",
    "NSW-OD2",
    "NSW-OE2",
    "NSW-OF2",
    "NSW-OG2",
    "NSW-OH2",
    "NSW-OI2",
    "NSW-OJ2",
    "NSW-OK2",
    "NSW-OL2",
    "NSW-OM2",
    "NSW-ON2",
    "NSW-OO2",
    "NSW-OP2",
    "NSW-OQ2",
    "NSW-OR2",
    "NSW-OS2",
    "NSW-OT2",
    "NSW-OU2",
    "NSW-OV2",
    "NSW-OW2",
    "NSW-OX2",
    "NSW-OY2",
    "NSW-OZ2",
    "NSW-PA2",
    "NSW-PB2",
    "NSW-PC2",
    "NSW-PD2",
    "NSW-PE2",
    "NSW-PF2",
    "NSW-PG2",
    "NSW-PH2",
    "NSW-PI2",
    "NSW-PJ2",
    "NSW-PK2",
    "NSW-PL2",
    "NSW-PM2",
    "NSW-PN2",
    "NSW-PO2",
    "NSW-PP2",
    "NSW-PQ2",
    "NSW-PR2",
    "NSW-PS2",
    "NSW-PT2",
    "NSW-PU2",
    "NSW-PV2",
    "NSW-PW2",
    "NSW-PX2",
    "NSW-PY2",
    "NSW-PZ2",
    "NSW-QA2",
    "NSW-QB2",
    "NSW-QC2",
    "NSW-QD2",
    "NSW-QE2",
    "NSW-QF2",
    "NSW-QG2",
    "NSW-QH2",
    "NSW-QI2",
    "NSW-QJ2",
    "NSW-QK2",
    "NSW-QL2",
    "NSW-QM2",
    "NSW-QN2",
    "NSW-QO2",
    "NSW-QP2",
    "NSW-QQ2",
    "NSW-QR2",
    "NSW-QS2",
    "NSW-QT2",
    "NSW-QU2",
    "NSW-QV2",
    "NSW-QW2",
    "NSW-QX2",
    "NSW-QY2",
    "NSW-QZ2",
    "NSW-RA2",
    "NSW-RB2",
    "NSW-RC2",
    "NSW-RD2",
    "NSW-RE2",
    "NSW-RF2",
    "NSW-RG2",
    "NSW-RH2",
    "NSW-RI2",
    "NSW-RJ2",
    "NSW-RK2",
    "NSW-RL2",
    "NSW-RM2",
    "NSW-RN2",
    "NSW-RO2",
    "NSW-RP2",
    "NSW-RQ2",
    "NSW-RR2",
    "NSW-RS2",
    "NSW-RT2",
    "NSW-RU2",
    "NSW-RV2",
    "NSW-RW2",
    "NSW-RX2",
    "NSW-RY2",
    "NSW-RZ2",
    "NSW-SA2",
    "NSW-SB2",
    "NSW-SC2",
    "NSW-SD2",
    "NSW-SE2",
    "NSW-SF2",
    "NSW-SG2",
    "NSW-SH2",
    "NSW-SI2",
    "NSW-SJ2",
    "NSW-SK2",
    "NSW-SL2",
    "NSW-SM2",
    "NSW-SN2",
    "NSW-SO2",
    "NSW-SP2",
    "NSW-SQ2",
    "NSW-SR2",
    "NSW-SS2",
    "NSW-ST2",
    "NSW-SU2",
    "NSW-SV2",
    "NSW-SW2",
    "NSW-SX2",
    "NSW-SY2",
    "NSW-SZ2",
    "NSW-TA2",
    "NSW-TB2",
    "NSW-TC2",
    "NSW-TD2",
    "NSW-TE2",
    "NSW-TF2",
    "NSW-TG2",
    "NSW-TH2",
    "NSW-TI2",
    "NSW-TJ2",
    "NSW-TK2",
    "NSW-TL2",
    "NSW-TM2",
    "NSW-TN2",
    "NSW-TO2",
    "NSW-TP2",
    "NSW-TQ2",
    "NSW-TR2",
    "NSW-TS2",
    "NSW-TT2",
    "NSW-TU2",
    "NSW-TV2",
    "NSW-TW2",
    "NSW-TX2",
    "NSW-TY2",
    "NSW-TZ2",
    "NSW-UA2",
    "NSW-UB2",
    "NSW-UC2",
    "NSW-UD2",
    "NSW-UE2",
    "NSW-UF2",
    "NSW-UG2",
    "NSW-UH2",
    "NSW-UI2",
    "NSW-UJ2",
    "NSW-UK2",
    "NSW-UL2",
    "NSW-UM2",
    "NSW-UN2",
    "NSW-UO2",
    "NSW-UP2",
    "NSW-UQ2",
    "NSW-UR2",
    "NSW-US2",
    "NSW-UT2",
    "NSW-UU2",
    "NSW-UV2",
    "NSW-UW2",
    "NSW-UX2",
    "NSW-UY2",
    "NSW-UZ2",
    # QLD
    "QLD-AA3",
    "QLD-AB3",
    "QLD-AC3",
    "QLD-AD3",
    "QLD-AE3",
    "QLD-AF3",
    "QLD-AG3",
    "QLD-AH3",
    "QLD-AI3",
    "QLD-AJ3",
    "QLD-AK3",
    "QLD-AL3",
    "QLD-AM3",
    "QLD-AN3",
    "QLD-AO3",
    "QLD-AP3",
    "QLD-AQ3",
    "QLD-AR3",
    "QLD-AS3",
    "QLD-AT3",
    "QLD-AU3",
    "QLD-AV3",
    "QLD-AW3",
    "QLD-AX3",
    "QLD-AY3",
    "QLD-AZ3",
    "QLD-BA3",
    "QLD-BB3",
    "QLD-BC3",
    "QLD-BD3",
    "QLD-BE3",
    "QLD-BF3",
    "QLD-BG3",
    "QLD-BH3",
    "QLD-BI3",
    "QLD-BJ3",
    "QLD-BK3",
    "QLD-BL3",
    "QLD-BM3",
    "QLD-BN3",
    "QLD-BO3",
    "QLD-BP3",
    "QLD-BQ3",
    "QLD-BR3",
    "QLD-BS3",
    "QLD-BT3",
    "QLD-BU3",
    "QLD-BV3",
    "QLD-BW3",
    "QLD-BX3",
    "QLD-BY3",
    "QLD-BZ3",
    "QLD-CA3",
    "QLD-CB3",
    "QLD-CC3",
    "QLD-CD3",
    "QLD-CE3",
    "QLD-CF3",
    "QLD-CG3",
    "QLD-CH3",
    "QLD-CI3",
    "QLD-CJ3",
    "QLD-CK3",
    "QLD-CL3",
    "QLD-CM3",
    "QLD-CN3",
    "QLD-CO3",
    "QLD-CP3",
    "QLD-CQ3",
    "QLD-CR3",
    "QLD-CS3",
    "QLD-CT3",
    "QLD-CU3",
    "QLD-CV3",
    "QLD-CW3",
    "QLD-CX3",
    "QLD-CY3",
    "QLD-CZ3",
    # VIC
    "VIC-AA5",
    "VIC-AB5",
    "VIC-AC5",
    "VIC-AD5",
    "VIC-AE5",
    "VIC-AF5",
    "VIC-AG5",
    "VIC-AH5",
    "VIC-AI5",
    "VIC-AJ5",
    "VIC-AK5",
    "VIC-AL5",
    "VIC-AM5",
    "VIC-AN5",
    "VIC-AO5",
    "VIC-AP5",
    "VIC-AQ5",
    "VIC-AR5",
    "VIC-AS5",
    "VIC-AT5",
    "VIC-AU5",
    "VIC-AV5",
    "VIC-AW5",
    "VIC-AX5",
    "VIC-AY5",
    "VIC-AZ5",
    "VIC-BA5",
    "VIC-BB5",
    "VIC-BC5",
    "VIC-BD5",
    "VIC-BE5",
    "VIC-BF5",
    "VIC-BG5",
    "VIC-BH5",
    "VIC-BI5",
    "VIC-BJ5",
    "VIC-BK5",
    "VIC-BL5",
    "VIC-BM5",
    "VIC-BN5",
    "VIC-BO5",
    "VIC-BP5",
    "VIC-BQ5",
    "VIC-BR5",
    "VIC-BS5",
    "VIC-BT5",
    "VIC-BU5",
    "VIC-BV5",
    "VIC-BW5",
    "VIC-BX5",
    "VIC-BY5",
    "VIC-BZ5",
    # SA
    "SA-AA5",
    "SA-AB5",
    "SA-AC5",
    "SA-AD5",
    "SA-AE5",
    "SA-AF5",
    "SA-AG5",
    "SA-AH5",
    "SA-AI5",
    "SA-AJ5",
    "SA-AK5",
    "SA-AL5",
    "SA-AM5",
    "SA-AN5",
    "SA-AO5",
    "SA-AP5",
    "SA-AQ5",
    "SA-AR5",
    "SA-AS5",
    "SA-AT5",
    "SA-AU5",
    "SA-AV5",
    "SA-AW5",
    "SA-AX5",
    # WA
    "WA-AA6",
    "WA-AB6",
    "WA-AC6",
    "WA-AD6",
    "WA-AE6",
    "WA-AF6",
    "WA-AG6",
    "WA-AH6",
    "WA-AI6",
    "WA-AJ6",
    "WA-AK6",
    "WA-AL6",
    "WA-AM6",
    "WA-AN6",
    "WA-AO6",
    "WA-AP6",
    "WA-AQ6",
    "WA-AR6",
    "WA-AS6",
    "WA-AT6",
    "WA-AU6",
    "WA-AV6",
    "WA-AW6",
    "WA-AX6",
    "WA-AY6",
    "WA-AZ6",
    "WA-BA6",
    "WA-BB6",
    "WA-BC6",
    "WA-BD6",
    "WA-BE6",
    "WA-BF6",
    "WA-BG6",
    "WA-BH6",
    "WA-BI6",
    "WA-BJ6",
    "WA-BK6",
    "WA-BL6",
    "WA-BM6",
    "WA-BN6",
    "WA-BO6",
    # TAS
    "TAS-AA7",
    "TAS-AB7",
    "TAS-AC7",
    "TAS-AD7",
    "TAS-AE7",
    "TAS-AF7",
    "TAS-AG7",
    "TAS-AH7",
    "TAS-AI7",
    "TAS-AJ7",
    "TAS-AK7",
    "TAS-AL7",
    "TAS-AM7",
    "TAS-AN7",
    "TAS-AO7",
    "TAS-AP7",
    "TAS-AQ7",
    "TAS-AR7",
    # NT
    "NT-AA8",
    "NT-AB8",
    "NT-AC8",
    "NT-AD8",
    "NT-AE8",
    "NT-AF8",
    "NT-AG8",
    "NT-AH8",
    "NT-AI8",
    "NT-AJ8",
    "NT-AK8",
    "NT-AL8",
    "NT-AM8",
    "NT-AN8",
    "NT-AO8",
]

_ALL_SHIRES_SET = set(_load_shires())
_SHIRE_STATES_ORDERED = ["NSW", "QLD", "VIC", "SA", "WA", "TAS", "NT", "ACT"]

# ── Short-form shire resolution helpers ──────────────────────────────────────
# N1MM sends the exchange as XX{callsign-area-digit}, e.g. VK4GSI sends "BN4"
# (4 = QLD callsign area).  But ALL_SHIRES uses a different trailing digit per
# state: NSW=2, QLD=3, VIC=5, SA=5, WA=6, TAS=7, NT=8, ACT=1.
# So "BN4" should resolve to "QLD-BN3", not "QLD-BN4".
#
# _VK_AREA_TO_STATE_SUFFIX maps VK callsign area -> (state_code, shire_suffix)
_VK_AREA_TO_STATE_SUFFIX: dict = {
    1: ("ACT", "1"),
    2: ("NSW", "2"),
    3: ("VIC", "5"),
    4: ("QLD", "3"),
    5: ("SA", "5"),
    6: ("WA", "6"),
    7: ("TAS", "7"),
    8: ("NT", "8"),
}

# Reverse lookup: 2-letter prefix -> list of full shire codes (for unambiguous cases)
_PREFIX_TO_SHIRES: dict = {}
for _s in _load_shires():
    _letters = _s.split("-")[1][:-1]
    _PREFIX_TO_SHIRES.setdefault(_letters, []).append(_s)


def _state_from_vk_call(call: str) -> Optional[str]:
    """Derive state string from a VK callsign area digit, e.g. 'VK3ABC' -> 'VIC'."""
    import re as _re

    cm = _re.search(r"V[A-Z]?(\d)", call, _re.I)
    if cm:
        return _VK_AREA_TO_STATE_SUFFIX.get(int(cm.group(1)), (None, None))[0]
    return None


def _resolve_shire_from_call(raw: str, call: str) -> Optional[str]:
    """
    Resolve a short-form N1MM section (e.g. 'BN4') to a full shire code
    (e.g. 'QLD-BN3') using the operator's callsign area digit.
    Falls back to an unambiguous prefix lookup when the call isn't a VK.
    Returns None if unresolvable.
    """
    import re as _re

    raw = raw.strip().upper()
    # Already a valid full-form shire?
    if raw in _ALL_SHIRES_SET:
        return raw
    # Full form but wrong suffix? e.g. "NSW-BN4" should still try
    m = _re.match(r"^([A-Z]+)-([A-Z]{2})([1-9])$", raw)
    if m:
        candidate = f"{m.group(1)}-{m.group(2)}{m.group(3)}"
        if candidate in _ALL_SHIRES_SET:
            return candidate
    # Short form: XX{digit}
    m = _re.match(r"^([A-Z]{2})([1-9])$", raw)
    if not m:
        return None
    letters = m.group(1)
    # Derive VK area from callsign (handles VK3, VL4, VJ2 etc.)
    cm = _re.search(r"V[A-Z]?(\d)", call, _re.I)
    if cm:
        area = int(cm.group(1))
        if area in _VK_AREA_TO_STATE_SUFFIX:
            state, suffix = _VK_AREA_TO_STATE_SUFFIX[area]
            candidate = f"{state}-{letters}{suffix}"
            if candidate in _ALL_SHIRES_SET:
                return candidate
    # Last resort: unambiguous prefix match
    matches = _PREFIX_TO_SHIRES.get(letters, [])
    return matches[0] if len(matches) == 1 else None


def _shire_region(s: str) -> Optional[str]:
    """'NSW-AC2' → 'NSW',  'XX0' → None."""
    if "-" in s:
        return s.split("-")[0]
    return None


class VKShiresPlugin(ContestPlugin):
    """
    WIA VK Shires Contest.
    6 × 4-hour blocks = 24 hours.
    Score = total valid points × (shire band/mode mults + CQ zone band/mode mults).
    """

    def identify(self, contest_name: str) -> bool:
        cn = contest_name.upper()
        return "SHIRES" in cn or "VKSHIRES" in cn

    @property
    def display_name(self) -> str:
        return "VK Shires"

    def session_config(self) -> SessionConfig:
        return SessionConfig(duration_mins=240, num_sessions=6)

    def mult_list(self) -> list:
        return _load_shires()

    def mult_label(self) -> str:
        return "Shire"

    def mult_of_qso(self, q: dict) -> Optional[str]:
        m = q.get("mult1", "")
        if m in _ALL_SHIRES_SET:
            return m
        # The loader's short-form expansion (e.g. "LV4" -> "QLD-LV4") can fail
        # because N1MM sends XX{callsign-area-digit} but ALL_SHIRES uses a
        # different suffix per state (VIC=5, QLD=3, SA=5 etc.).
        # Re-attempt using the callsign's VK area to derive the correct state.
        raw = q.get("raw_mult", "") or q.get("mult1", "")
        call = q.get("call", "")
        return _resolve_shire_from_call(raw, call)

    def region_of_mult(self, m: str) -> Optional[str]:
        return _shire_region(m)

    def region_list(self) -> list:
        return _SHIRE_STATES_ORDERED

    def band_list(self) -> list:
        # Rules III.A: "Bands: 160 Metres, 80 Metres, 40 Metres, 20 Metres
        # 15 Metres, 10 Metres." — no WARC bands, no 60m, no VHF/UHF.
        return ["160M", "80M", "40M", "20M", "15M", "10M"]

    def has_region_heat(self) -> bool:
        return True

    def has_state_bars(self) -> bool:
        return True

    def region_heat(self, qsos: list) -> list:
        # Override base implementation: use is_mult1 as the authoritative worked
        # count and callsign-area derivation for QSO assignment.  The base class
        # uses mult_of_qso() which can't resolve all short-form N1MM section codes
        # when ALL_SHIRES is incomplete.
        from collections import defaultdict

        region_qsos = defaultdict(int)
        region_worked = defaultdict(set)
        region_total = defaultdict(int)
        for m in _load_shires():
            reg = _shire_region(m)
            if reg:
                region_total[reg] += 1
        for q in qsos:
            if q.get("dupe"):
                continue
            shire = _resolve_shire_from_call(q.get("raw_mult", ""), q.get("call", ""))
            state = shire.split("-")[0] if shire else _state_from_vk_call(q.get("call", ""))
            if not state:
                continue
            region_qsos[state] += 1
            # Dedupe on the resolved canonical shire code, not the raw
            # exchange string — two QSOs whose raw text differs (e.g. a
            # short-form "BN4" vs the full "QLD-BN3") but resolve to the
            # same shire must count as one worked mult, matching
            # worked_primary_mults()/mult_of_qso() elsewhere.
            if q.get("is_mult1") == 1 and shire:
                region_worked[state].add(shire)
        result = []
        for reg in _SHIRE_STATES_ORDERED:
            w = len(region_worked[reg])
            t = region_total.get(reg, 0)
            q_count = region_qsos[reg]
            result.append(
                {
                    "state": reg,
                    "qsos": q_count,
                    "worked": w,
                    "total": t,
                    "pct": w / t * 100 if t else 0,
                }
            )
        return [r for r in result if r["qsos"] > 0 or r["total"] > 0]

    def band_efficiency(self, qsos: list) -> list:
        # Override base implementation: count all non-dupe QSOs per band and
        # use is_mult1 for new-shire counts so 160m (and any band) always appears.
        from collections import defaultdict

        band_qsos = defaultdict(int)
        band_mults = defaultdict(set)
        for q in qsos:
            if q.get("dupe"):
                continue
            b = q.get("band") or "?"
            band_qsos[b] += 1
            if q.get("is_mult1") == 1 and q.get("raw_mult"):
                band_mults[b].add(q["raw_mult"].strip().upper())
        result = []
        for b, qn in band_qsos.items():
            mn = len(band_mults[b])
            result.append(
                {"band": b, "qsos": qn, "new_shires": mn, "efficiency": mn / qn if qn else 0}
            )
        return sorted(result, key=lambda x: x["efficiency"], reverse=True)

    def score(self, qsos: list) -> int:
        mr = self.multipliers(qsos)
        pts = sum(q["pts"] for q in qsos if not q["dupe"])
        return pts * len(mr.primary_mults)

    def running_score_for_sparkline(self, qsos_up_to_hour: list) -> int:
        """
        Running score for the Overview "Running Score" sparkline.

        VK Shires scores as ``pts x shire-band/mode mults`` ONLY — CQ zones
        are tracked for the gauge display but are explicitly NOT part of the
        score (see multipliers()/score() above). Without this override, the
        base ContestPlugin default multiplies by (primary + secondary) mults,
        which would fold the CQ-zone count into the multiplier and inflate
        the sparkline well above the real TOTAL SCORE gauge.

        Delegating to score() guarantees the sparkline's final value always
        matches the TOTAL SCORE gauge for the same slice of QSOs.
        """
        return self.score(qsos_up_to_hour)

    def multipliers(self, qsos: list) -> MultResult:
        # Secondary mults hold unique CQ zones for the gauge display only —
        # they are NOT added to the score (see score() below).
        zones = {q["cqz"] for q in qsos if not q.get("dupe") and q.get("cqz")}
        return MultResult(
            self.worked_primary_band_mults(qsos),
            zones,
            "SHIRE MULTS",
            "CQ ZONES",
        )

    def gauge_defs(self, data: dict, total_mults: int) -> list:
        return [
            GaugeDef("TOTAL QSOs", "total", "qso_max", ACCENT(), "{v}"),
            GaugeDef("VALID QSOs", "valid", "qso_max", GREEN(), "{v}"),
            GaugeDef("TOTAL SCORE", "score", "score_max", ACCENT3(), "{v:,}"),
            GaugeDef("SHIRES WORKED", "worked", total_mults, ACCENT3(), "{v}"),
            GaugeDef("SHIRE MULTS", "band_mults", total_mults, GREEN(), "{v}"),
            GaugeDef("CQ ZONES", "zone_cnt", 40, "#64b5f6", "{v}"),
            GaugeDef("% COMPLETE", "pct", 100.0, MUTED(), "{v:.1f}%"),
        ]
