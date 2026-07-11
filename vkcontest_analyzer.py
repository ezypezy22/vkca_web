"""
VK Contest Analyzer
Competitive intelligence tool for N1MM+ .s3db log files
Reads your log and tells you exactly where to focus to maximise your score.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import sqlite3
import os
import sys
import re
import json
from datetime import datetime, timedelta, timezone, date as date_
from collections import defaultdict, deque
import threading
import queue
import logging
import platform
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

# ── logging setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


class _LogRingBuffer(logging.Handler):
    """Keeps the most recent formatted log records in memory.

    Used to attach recent diagnostic output to bug reports / feature
    requests submitted via Help → Report Issue.
    """
    def __init__(self, capacity=300):
        super().__init__()
        self.capacity = capacity
        self.records = deque(maxlen=capacity)

    def emit(self, record):
        try:
            self.records.append(self.format(record))
        except Exception:
            pass

    def recent(self, n=25):
        return list(self.records)[-n:]


_log_ring = _LogRingBuffer(capacity=300)
_log_ring.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.getLogger().addHandler(_log_ring)

# ── matplotlib embedded in tkinter ──────────────────────────────────────────
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import numpy as np
import math
import matplotlib.patches as mpatches
from matplotlib.colors import LinearSegmentedColormap
try:
    from scipy.interpolate import make_interp_spline
    _SCIPY_AVAILABLE = True
except ImportError:
    _SCIPY_AVAILABLE = False

# ═══════════════════════════════════════════════════════════════════════════════
# ── Theme system ─────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

THEMES = {
    # ── Default: dark hacker aesthetic ───────────────────────────────────────
    "Dark (Default)": {
        "BG":      "#0d1117",
        "BG2":     "#161b22",
        "BG3":     "#21262d",
        "ACCENT":  "#00d4aa",
        "ACCENT2": "#ff6b35",
        "ACCENT3": "#f0c040",
        "RED":     "#ff4757",
        "GREEN":   "#2ed573",
        "MUTED":   "#8b949e",
        "FG":      "#e6edf3",
        "BAND_COLOURS": {
            "160m": "#e040fb",
            "80m":  "#ff6b35",
            "60m":  "#f0c040",
            "40m":  "#2ed573",
            "30m":  "#00bcd4",
            "20m":  "#00d4aa",
            "17m":  "#64b5f6",
            "15m":  "#ff5252",
            "12m":  "#ffab40",
            "10m":  "#69f0ae",
            "6m":   "#ea80fc",
            "2m":   "#80d8ff",
            "70cm": "#ccff90",
        },
        "STATE_COLOURS": {
            "NSW": "#00d4aa",
            "QLD": "#f0c040",
            "VIC": "#64b5f6",
            "SA":  "#ff6b35",
            "WA":  "#e040fb",
            "TAS": "#2ed573",
            "NT":  "#ff5252",
            "ACT": "#ffab40",
        },
        "PROP_GRAD": ["#161b22","#0d3d35","#0a5c50","#008070","#00a88a","#00c4a0","#00d4aa"],
        "SESSION_PALETTE": ["#00d4aa","#f0c040","#ff6b35","#a78bfa",
                            "#60a5fa","#34d399","#f87171","#fbbf24"],
    },

    # ── Light: clean white ────────────────────────────────────────────────────
    "Light": {
        "BG":      "#f5f6fa",
        "BG2":     "#ffffff",
        "BG3":     "#e8ecf0",
        "ACCENT":  "#0077aa",
        "ACCENT2": "#cc4400",
        "ACCENT3": "#886600",
        "RED":     "#cc0022",
        "GREEN":   "#117733",
        "MUTED":   "#6b7280",
        "FG":      "#1a1d23",
        "BAND_COLOURS": {
            "160m": "#7b2d8b",
            "80m":  "#cc4400",
            "60m":  "#886600",
            "40m":  "#117733",
            "30m":  "#007090",
            "20m":  "#0077aa",
            "17m":  "#1155aa",
            "15m":  "#cc0022",
            "12m":  "#994400",
            "10m":  "#117722",
            "6m":   "#992288",
            "2m":   "#005588",
            "70cm": "#556600",
        },
        "STATE_COLOURS": {
            "NSW": "#0077aa",
            "QLD": "#886600",
            "VIC": "#1155aa",
            "SA":  "#cc4400",
            "WA":  "#7b2d8b",
            "TAS": "#117733",
            "NT":  "#cc0022",
            "ACT": "#994400",
        },
        "PROP_GRAD": ["#e8ecf0","#cce0ee","#99c4dd","#55a0cc","#2277aa","#005588","#003366"],
        "SESSION_PALETTE": ["#0077aa","#886600","#cc4400","#7b2d8b",
                            "#1155aa","#117733","#cc0022","#994400"],
    },

    # ── High Contrast: WCAG AAA black/white/yellow ────────────────────────────
    "High Contrast": {
        "BG":      "#000000",
        "BG2":     "#0a0a0a",
        "BG3":     "#1a1a1a",
        "ACCENT":  "#ffff00",
        "ACCENT2": "#ff8800",
        "ACCENT3": "#ffffff",
        "RED":     "#ff4444",
        "GREEN":   "#00ff88",
        "MUTED":   "#bbbbbb",
        "FG":      "#ffffff",
        "BAND_COLOURS": {
            "160m": "#ff88ff",
            "80m":  "#ff8800",
            "60m":  "#ffff00",
            "40m":  "#00ff88",
            "30m":  "#00ffff",
            "20m":  "#ffff00",
            "17m":  "#88ccff",
            "15m":  "#ff4444",
            "12m":  "#ffaa44",
            "10m":  "#44ff88",
            "6m":   "#ff88ff",
            "2m":   "#88eeff",
            "70cm": "#ccff44",
        },
        "STATE_COLOURS": {
            "NSW": "#ffff00",
            "QLD": "#ffffff",
            "VIC": "#88ccff",
            "SA":  "#ff8800",
            "WA":  "#ff88ff",
            "TAS": "#00ff88",
            "NT":  "#ff4444",
            "ACT": "#ffaa44",
        },
        "PROP_GRAD": ["#000000","#1a1a00","#333300","#666600","#999900","#cccc00","#ffff00"],
        "SESSION_PALETTE": ["#ffff00","#ffffff","#ff8800","#ff88ff",
                            "#88ccff","#00ff88","#ff4444","#ffaa44"],
    },

    # ── Deuteranopia: safe for red-green colour blindness (blue/orange/teal) ──
    "Deuteranopia-Safe": {
        "BG":      "#0d1117",
        "BG2":     "#161b22",
        "BG3":     "#21262d",
        "ACCENT":  "#56b4e9",   # sky blue
        "ACCENT2": "#e69f00",   # amber/gold
        "ACCENT3": "#f0e442",   # yellow
        "RED":     "#cc79a7",   # mauve (avoids red)
        "GREEN":   "#0072b2",   # dark blue (replaces green)
        "MUTED":   "#8b949e",
        "FG":      "#e6edf3",
        "BAND_COLOURS": {
            "160m": "#cc79a7",   # mauve
            "80m":  "#e69f00",   # amber
            "60m":  "#f0e442",   # yellow
            "40m":  "#009e73",   # bluish-green (safe)
            "30m":  "#56b4e9",   # sky blue
            "20m":  "#0072b2",   # dark blue
            "17m":  "#56b4e9",   # sky blue
            "15m":  "#d55e00",   # vermillion
            "12m":  "#e69f00",   # amber
            "10m":  "#009e73",   # bluish-green
            "6m":   "#cc79a7",   # mauve
            "2m":   "#56b4e9",   # sky blue
            "70cm": "#f0e442",   # yellow
        },
        "STATE_COLOURS": {
            "NSW": "#56b4e9",   # sky blue
            "QLD": "#f0e442",   # yellow
            "VIC": "#0072b2",   # dark blue
            "SA":  "#e69f00",   # amber
            "WA":  "#cc79a7",   # mauve
            "TAS": "#009e73",   # bluish-green
            "NT":  "#d55e00",   # vermillion
            "ACT": "#e69f00",   # amber
        },
        "PROP_GRAD": ["#161b22","#0d2233","#0a3550","#005f8a","#0072b2","#3a9bcc","#56b4e9"],
        "SESSION_PALETTE": ["#56b4e9","#e69f00","#009e73","#cc79a7",
                            "#0072b2","#f0e442","#d55e00","#56b4e9"],
    },

    # ── Protanopia: safe for red-blind (blue/gold/teal, avoids red) ───────────
    "Protanopia-Safe": {
        "BG":      "#0d1117",
        "BG2":     "#161b22",
        "BG3":     "#21262d",
        "ACCENT":  "#00b4d8",   # cyan
        "ACCENT2": "#fca311",   # gold
        "ACCENT3": "#e9c46a",   # sand
        "RED":     "#a8dadc",   # teal (avoids red)
        "GREEN":   "#2196f3",   # blue (replaces green)
        "MUTED":   "#8b949e",
        "FG":      "#e6edf3",
        "BAND_COLOURS": {
            "160m": "#8ecae6",   # light blue
            "80m":  "#fca311",   # gold
            "60m":  "#e9c46a",   # sand
            "40m":  "#2196f3",   # blue
            "30m":  "#00b4d8",   # cyan
            "20m":  "#0077b6",   # dark blue
            "17m":  "#48cae4",   # sky cyan
            "15m":  "#a8dadc",   # teal (no red)
            "12m":  "#fca311",   # gold
            "10m":  "#2196f3",   # blue
            "6m":   "#8ecae6",   # light blue
            "2m":   "#48cae4",   # sky cyan
            "70cm": "#e9c46a",   # sand
        },
        "STATE_COLOURS": {
            "NSW": "#00b4d8",   # cyan
            "QLD": "#e9c46a",   # sand
            "VIC": "#2196f3",   # blue
            "SA":  "#fca311",   # gold
            "WA":  "#8ecae6",   # light blue
            "TAS": "#0077b6",   # dark blue
            "NT":  "#a8dadc",   # teal
            "ACT": "#48cae4",   # sky cyan
        },
        "PROP_GRAD": ["#161b22","#0d2d3a","#0a4458","#006989","#0090b5","#00a8d5","#00b4d8"],
        "SESSION_PALETTE": ["#00b4d8","#fca311","#2196f3","#8ecae6",
                            "#0077b6","#e9c46a","#a8dadc","#48cae4"],
    },
}

THEME_NAMES = list(THEMES.keys())

# ── Active theme (mutable globals — mutated by _apply_theme()) ────────────────
BG       = "#0d1117"
BG2      = "#161b22"
BG3      = "#21262d"
ACCENT   = "#00d4aa"
ACCENT2  = "#ff6b35"
ACCENT3  = "#f0c040"
RED      = "#ff4757"
GREEN    = "#2ed573"
MUTED    = "#8b949e"
FG       = "#e6edf3"

BAND_COLOURS = {
    "160m": "#e040fb",
    "80m":  "#ff6b35",
    "60m":  "#f0c040",
    "40m":  "#2ed573",
    "30m":  "#00bcd4",
    "20m":  "#00d4aa",
    "17m":  "#64b5f6",
    "15m":  "#ff5252",
    "12m":  "#ffab40",
    "10m":  "#69f0ae",
    "6m":   "#ea80fc",
    "2m":   "#80d8ff",
    "70cm": "#ccff90",
}
BAND_COLOURS_DEFAULT = "#8b949e"

# Canonical band ordering (low → high) used to sort per-band panels such as
# the "QSO Value" overview panel when a plugin doesn't supply its own order.
_BAND_ORDER = ["160M", "80M", "60M", "40M", "30M", "20M", "17M", "15M",
               "12M", "10M", "6M", "2M", "70CM"]

STATE_COLOURS = {
    "NSW": "#00d4aa",
    "QLD": "#f0c040",
    "VIC": "#64b5f6",
    "SA":  "#ff6b35",
    "WA":  "#e040fb",
    "TAS": "#2ed573",
    "NT":  "#ff5252",
    "ACT": "#ffab40",
}

# Active theme name (used by App for persistence)
_ACTIVE_THEME = "Dark (Default)"
_prev_theme_name = "Dark (Default)"   # set by App._on_theme_change before applying


def _apply_theme(name: str) -> None:
    """Mutate the module-level colour globals to match *name*."""
    global BG, BG2, BG3, ACCENT, ACCENT2, ACCENT3, RED, GREEN, MUTED, FG
    global BAND_COLOURS, BAND_COLOURS_DEFAULT, STATE_COLOURS, _ACTIVE_THEME, _prev_theme_name
    _prev_theme_name = _ACTIVE_THEME   # keep in sync even for startup load
    t = THEMES.get(name, THEMES["Dark (Default)"])
    BG               = t["BG"]
    BG2              = t["BG2"]
    BG3              = t["BG3"]
    ACCENT           = t["ACCENT"]
    ACCENT2          = t["ACCENT2"]
    ACCENT3          = t["ACCENT3"]
    RED              = t["RED"]
    GREEN            = t["GREEN"]
    MUTED            = t["MUTED"]
    FG               = t["FG"]
    BAND_COLOURS     = dict(t["BAND_COLOURS"])
    BAND_COLOURS_DEFAULT = MUTED
    STATE_COLOURS    = dict(t["STATE_COLOURS"])
    _ACTIVE_THEME    = name
    # Keep zebra stripe colour in sync with the active theme.
    # For light themes use a slightly darker tint; for dark themes a slightly
    # lighter tint — both derived from BG3 so they always feel at home.
    global _ZEBRA_ODD
    if BG.startswith("#f") or BG.startswith("#e"):   # light theme
        _ZEBRA_ODD = BG3
    else:
        _ZEBRA_ODD = "#1e2530"   # dark blue-grey lift used in dark/cbsafe themes


# ── Theme config persistence ─────────────────────────────────────────────────

_THEME_CFG_PATH = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")),
    "VKContestAnalyzer", "theme.txt"
)

def _load_saved_theme() -> str:
    try:
        with open(_THEME_CFG_PATH, "r", encoding="utf-8") as f:
            name = f.read().strip()
            if name in THEMES:
                return name
    except Exception:
        pass
    return "Dark (Default)"

def _save_theme(name: str) -> None:
    try:
        os.makedirs(os.path.dirname(_THEME_CFG_PATH), exist_ok=True)
        with open(_THEME_CFG_PATH, "w", encoding="utf-8") as f:
            f.write(name)
    except Exception:
        pass

# Apply saved theme at import time
_apply_theme(_load_saved_theme())

# ── Compiled regex constants ────────────────────────────────────────────────
_VK_PREFIX_RE = re.compile(r'^(VK|VJ|VL|AX)')
_PACKED_MULT_RE = re.compile(
    r'(?:^|[\s,/])(ACT|NSW|VIC|QLD|SA|WA|TAS|NT)-([A-Z]{2})([1-8])'
    r'(?:$|[\s,/]|$)', re.IGNORECASE)
_SHORT2_RE = re.compile(r'([A-Z]{2})([1-8])', re.IGNORECASE)

# ── Font constants ────────────────────────────────────────────────────────────
# Platform-adaptive UI font (modern sans-serif stack)
import platform as _platform
def _ui_font():
    s = _platform.system()
    if s == "Windows": return "Segoe UI"
    if s == "Darwin":  return "SF Pro Display"
    return "Inter"      # fallback; degrades to system sans if absent
UI_FONT  = _ui_font()

# Monospace font for callsign logs, data grids, and code-like values
MONO_FONT = "Consolas"

# Strict proportional hierarchy:
#   FONT_HERO  – 36pt bold  : large KPI numbers (gauges, big metrics)
#   FONT_H     – 15pt semi  : section headers / tab titles
#   FONT_B     – 10pt regular: body / data labels
#   FONT_S     –  9pt regular: secondary info, grid rows
FONT_HERO = (UI_FONT,   36, "bold")
FONT_H    = (UI_FONT,   15, "bold")
FONT_B    = (UI_FONT,   10)
FONT_S    = (UI_FONT,    9)
FONT_MONO = (MONO_FONT, 10)
FONT_MONO_S = (MONO_FONT, 9)

VERSION = "26.7.10"   # year.month.patch — displayed in title bar and header label

# GitHub repo used by Help → Report Issue / Request Feature
GITHUB_REPO = "ezypezy22/vkca_web"

# ═══════════════════════════════════════════════════════════════════════════════
# ── Tab Registry & Persistence ───────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

TAB_REGISTRY = [
    dict(attr="tab_overview",    label="📊 Overview",       default_on=True,  heavy=True,
         build_fn="_build_overview_tab",    refresh_fn="_refresh_overview_chart"),
    dict(attr="tab_cluster",     label="📡 DX Cluster",     default_on=True,  heavy=False,
         build_fn="_build_cluster_tab",     refresh_fn="_refresh_cluster_log"),
    dict(attr="tab_missing",     label="🎯 Missing Mults",  default_on=True,  heavy=False,
         build_fn="_build_missing_tab",     refresh_fn="_refresh_missing"),
    dict(attr="tab_worked",      label="📋 Worked",         default_on=True,  heavy=False,
         build_fn="_build_worked_tab",      refresh_fn="_refresh_worked"),
    dict(attr="tab_rate",        label="⚡ Rate Analysis",  default_on=True,  heavy=True,
         build_fn="_build_rate_tab",        refresh_fn="_refresh_rate"),
    dict(attr="tab_bands",       label="📡 Band Breakdown", default_on=True,  heavy=False,
         build_fn="_build_bands_tab",       refresh_fn="_refresh_bands"),
    dict(attr="tab_dupes",       label="⚠️ Dupe Checker",  default_on=True,  heavy=False,
         build_fn="_build_dupes_tab",       refresh_fn="_refresh_dupes"),
    dict(attr="tab_propagation", label="🌐 Propagation",    default_on=False, heavy=True,
         build_fn="_build_propagation_tab", refresh_fn="_refresh_propagation"),
    dict(attr="tab_debug",       label="🛠 Debug Mults",    default_on=True,  heavy=False,
         build_fn="_build_debug_tab",       refresh_fn="_refresh_debug"),
    dict(attr="tab_replay",      label="⏪ Score Replay",   default_on=False, heavy=True,
         build_fn="_build_replay_tab",      refresh_fn="_refresh_replay"),
    dict(attr="tab_fatigue",     label="😴 Fatigue",        default_on=False, heavy=True,
         build_fn="_build_fatigue_tab",     refresh_fn="_refresh_fatigue"),
    dict(attr="tab_yoy",         label="📈 Year on Year",   default_on=False, heavy=True,
         build_fn="_build_yoy_tab",         refresh_fn="_refresh_yoy"),
    dict(attr="tab_pace",        label="🏁 Pace Tracker",   default_on=False, heavy=True,
         build_fn="_build_pace_tab",        refresh_fn="_refresh_pace"),
]

_TAB_TOOLTIPS = {
    "tab_overview":    "Main chart with gauges, sparklines and band bars.",
    "tab_cluster":     "Live DX Cluster feed — no chart, light.",
    "tab_missing":     "Missing multipliers list — no chart, light.",
    "tab_worked":      "Full QSO log with per-row countdown — light.",
    "tab_rate":        "QSOs-per-hour bar chart — matplotlib.",
    "tab_bands":       "Band breakdown treeview — no chart, light.",
    "tab_dupes":       "Dupe checker treeview — no chart, light.",
    "tab_propagation": "24 × N region heatmap — heavy matplotlib render.",
    "tab_debug":       "Multiplier debug treeview — no chart, light.",
    "tab_replay":      "Score replay timeline — heavy matplotlib + scrubber.",
    "tab_fatigue":     "Operator fatigue chart — heavy matplotlib render.",
    "tab_yoy":         "Year-on-Year trajectory — heavy matplotlib render.",
    "tab_pace":        "Pace Tracker — compare live rate vs personal-best years. Flashes when behind.",
}

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vkcontest_config.json")

def _load_config() -> dict:
    defaults = {"active_tabs": {t["attr"]: t["default_on"] for t in TAB_REGISTRY},
                "overview_zoom": 1.0}
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for t in TAB_REGISTRY:
            data.setdefault("active_tabs", {})[t["attr"]] = \
                data["active_tabs"].get(t["attr"], t["default_on"])
        data.setdefault("overview_zoom", 1.0)
        return data
    except Exception:
        return defaults

def _save_config(cfg: dict):
    try:
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass

# splashdetails
try:
    import pyi_splash
    pyi_splash.close()
except ImportError:
    pass   # not running from a --splash build, ignore


# ═══════════════════════════════════════════════════════════════════════════════
# ── Contest Plugin Framework (loaded from plugins/ package) ──────────────────
# ═══════════════════════════════════════════════════════════════════════════════
# Plugins live in the plugins/ directory next to this script.
# To add a new contest: create plugins/my_contest.py with a ContestPlugin
# subclass.  It will be discovered and registered automatically at startup.
# The shared dataclasses and ABC are in plugins/base.py.

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from plugins.base import (
    ContestPlugin, SessionConfig, MultResult, GaugeDef,
)
from plugins.loader import plugin_for, get_all_plugins
from plugins.generic import GenericPlugin


# ═══════════════════════════════════════════════════════════════════════════════
# ── Shared utility functions ─────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

STATE_COLORS = {
    "NSW": "#4dabf7", "QLD": "#74c0fc", "SA":  "#a9e34b", "TAS": "#ffd43b",
    "VIC": "#ff8787", "WA":  "#da77f2", "NT":  "#ff922b", "ACT": "#63e6be",
}

BAND_COLORS = {
    "160M": "#e63946", "80M":  "#f4a261", "40M":  "#2a9d8f", "20M":  "#457b9d",
    "15M":  "#a8dadc", "10M":  "#e9c46a", "6M":   "#90be6d", "2M":   "#c77dff",
}


def _freq_to_band(freq_raw):
    f = float(freq_raw)
    if f > 1_000_000:    f = f / 1_000_000
    elif f > 30_000:     f = f / 1_000

    if   1.8  <= f < 2.0:   return "160M"
    elif 3.5  <= f < 4.0:   return "80M"
    elif 5.3  <= f < 5.4:   return "60M"
    elif 7.0  <= f < 7.3:   return "40M"
    elif 10.1 <= f < 10.15: return "30M"
    elif 14.0 <= f < 14.35: return "20M"
    elif 18.0 <= f < 18.17: return "17M"
    elif 21.0 <= f < 21.45: return "15M"
    elif 24.8 <= f < 25.0:  return "12M"
    elif 28.0 <= f < 29.7:  return "10M"
    elif 50.0 <= f < 54.0:  return "6M"
    elif 144  <= f < 148:   return "2M"
    else:                    return f"{f:.2f}MHz"


# ── VK call area / state helpers ─────────────────────────────────────────────

VK_AREA_TO_STATE = {
    1: "ACT", 2: "NSW", 3: "VIC", 4: "QLD",
    5: "SA",  6: "WA",  7: "TAS", 8: "NT",
}
VK_AREA_TO_CQZ = {1:29, 2:29, 3:29, 4:30, 5:29, 6:29, 7:29, 8:29}
PREFIX_TO_CQZ = {
    "VK":29, "ZL":32, "JA":25, "W":5,  "K":5,  "N":5,  "AA":5,
    "VE":3,  "G":14,  "DL":14, "F":14, "I":15, "SP":15,
    "UA9":17,"UA0":18,"BY":24, "HL":25,"BV":24,
    "9V":28, "HS":26, "VU":26, "ZS":38,"PY":11, "LU":13,
}


def cqz_from_call(call):
    call = call.upper().strip()
    if call.startswith("VK"):
        m = re.search(r"VK(\d)", call)
        if m:
            return VK_AREA_TO_CQZ.get(int(m.group(1)), 29)
        return 29
    for length in (3, 2, 1):
        pfx = call[:length]
        if pfx in PREFIX_TO_CQZ:
            return PREFIX_TO_CQZ[pfx]
    return None


def call_area_from_call(call):
    call = call.upper()
    m = re.search(r"VK(\d)", call)
    if m:
        return int(m.group(1))
    m = re.search(r"/(\d)", call)
    if m:
        return int(m.group(1))
    return None


def state_from_call(call):
    area = call_area_from_call(call)
    if area in VK_AREA_TO_STATE:
        return VK_AREA_TO_STATE[area]
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# ── ContestLog — contest-agnostic data loader ────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

class ContestLog:

    @staticmethod
    def available_contests(db_path):
        """
        Return a list of dicts for every contest instance that has QSOs,
        sorted by most recent first.
        Each dict: {contest_nr, contest_name, display_name, start_date, qso_count}

        FIX (load delay): creates a covering index on DXLOG(ContestNR) the first
        time it is needed.  The CREATE INDEX IF NOT EXISTS is a no-op on subsequent
        calls, but on the first open of a large database it reduces the GROUP BY
        COUNT scan from a full table-walk to an index-only scan — typically 10-50×
        faster for logs with thousands of QSOs.
        """
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        try:
            # Ensure index exists — fast no-op if already present
            try:
                c.execute(
                    "CREATE INDEX IF NOT EXISTS "
                    "_vkca_idx_dxlog_contestnr ON DXLOG(ContestNR)"
                )
                conn.commit()
            except Exception:
                pass   # read-only DB or DXLOG doesn't exist yet — harmless

            rows = c.execute("""
                SELECT  ci.ContestNR,
                        ci.ContestName,
                        TRIM(COALESCE(ct.DisplayName, ci.ContestName)) AS DisplayName,
                        ci.StartDate,
                        COUNT(d.ID) AS QSOCount
                FROM    ContestInstance ci
                LEFT JOIN Contest ct ON ct.Name = ci.ContestName
                LEFT JOIN DXLOG   d  ON d.ContestNR = ci.ContestNR
                WHERE   ci.ContestNR >= 0
                GROUP BY ci.ContestNR
                HAVING COUNT(d.ID) > 0
                ORDER BY ci.StartDate DESC
            """).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logging.warning("available_contests failed: %s", e)
            return []
        finally:
            conn.close()

    def __init__(self, db_path, contest_nr=None, plugin: ContestPlugin = None):
        self.db_path    = db_path
        self.contest_nr = contest_nr
        self.plugin     = plugin or GenericPlugin()
        self.qsos       = []
        self.load()

    # ── Loading ──────────────────────────────────────────────────────────────

    def load(self):
        logging.info("Opening database: %s", self.db_path)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        tables = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        logging.info("Discovered tables: %s", tables)

        # ── Read contest start date ───────────────────────────────────────────
        self._contest_start_dt = None
        try:
            if self.contest_nr is not None:
                row = c.execute(
                    "SELECT StartDate FROM ContestInstance WHERE ContestNR=?",
                    (self.contest_nr,)
                ).fetchone()
            else:
                row = c.execute(
                    "SELECT StartDate FROM ContestInstance "
                    "WHERE ContestNR >= 0 ORDER BY ContestNR DESC LIMIT 1"
                ).fetchone()
            if row and row[0]:
                sd = str(row[0]).strip()
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
                    try:
                        self._contest_start_dt = datetime.strptime(sd[:19], fmt)
                        break
                    except Exception:
                        pass
                logging.info("Contest start from DB: %s → %s", sd, self._contest_start_dt)
        except Exception as e:
            logging.warning("Could not read ContestInstance.StartDate: %s", e)

        target = None
        for t in tables:
            if "log" in t.lower() or "dxlog" in t.lower() or "qso" in t.lower():
                target = t
                break
        if target is None and tables:
            target = tables[0]
        if target is None:
            conn.close()
            raise ValueError("No database tables discovered.")

        cols = [r[1] for r in c.execute(f"PRAGMA table_info({target})").fetchall()]
        cols_lower = [cn.lower() for cn in cols]
        logging.info("Columns in %s: %s", target, cols)

        def col(candidates):
            for name in candidates:
                if name.lower() in cols_lower:
                    return name
            return None

        call_col  = col(["call","Callsign","callsign","CALL"])
        band_col  = col(["band","Band","BAND"])
        freq_col  = col(["freq","Freq","FREQ","frequency","qsxfreq"])
        mode_col  = col(["mode","Mode","MODE"])
        time_col  = col(["ts","QSOTime","qsotime","datetime","time","TIME"])
        mult_col  = col([
            "Exchange1","exchange1","EXCHANGE1",
            "Section","section","SECTION",
            "APP_N1MM_EXCHANGE1",
            "comment","COMMENT","Comment",
            "rcv","RCV",
            "Mult1","mult1",
            "srx_string","SRX_STRING",
            "exch","Exch","EXCH",
            "srx","SRX","rcvexch","RcvExch","RCVEXCH",
        ])
        # Use plugin-declared column preference when available; otherwise heuristic.
        _pref = self.plugin.preferred_exchange_columns
        if _pref:
            sect_col = col(_pref)
        else:
            sect_col = col(["Sect","sect","SECT","Section","section","SECTION"])
        dupe_col  = col(["IsDupe","isDupe","isdupe","ISDUPE",
                          "Dupe","dupe","DUPE",
                          "ContactType","contacttype","CONTACTTYPE",
                          "APP_N1MM_CONTACTTYPE",
                          "IsRunQSO","isrunqso"])
        pts_col   = col(["points","Points","POINTS","APP_N1MM_POINTS"])
        id_col    = col(["ID","id","CLAIMEDQSO","rowid"])
        zone_col  = col(["CQZone","cqzone","CQZONE","CQ_Zone","cq_zone",
                          "ZN","zn","Zone","zone","ZONE"])
        m1_col    = col(["IsMultiplier1","ismultiplier1"])
        m2_col    = col(["IsMultiplier2","ismultiplier2"])
        op_col    = col(["Operator","operator","OPERATOR"])

        logging.info(
            "Using columns: call=%s band=%s freq=%s mode=%s time=%s "
            "mult=%s sect=%s zone=%s m1=%s m2=%s dupe=%s pts=%s op=%s",
            call_col, band_col, freq_col, mode_col, time_col,
            mult_col, sect_col, zone_col, m1_col, m2_col, dupe_col, pts_col, op_col
        )

        sel_cols = [call_col, band_col, freq_col, mode_col, time_col,
                    mult_col, sect_col, zone_col, m1_col, m2_col,
                    dupe_col, pts_col, id_col, op_col]
        sel_cols = [cn for cn in sel_cols if cn]
        seen = set(); sel_cols_dedup = []
        for c_ in sel_cols:
            if c_ not in seen:
                seen.add(c_); sel_cols_dedup.append(c_)
        sel_cols = sel_cols_dedup
        sel = ", ".join(sel_cols)

        contest_nr_col = col(["ContestNR","contestnr"])
        if self.contest_nr is not None and contest_nr_col:
            rows = c.execute(
                f"SELECT {sel} FROM {target} "
                f"WHERE {contest_nr_col} = ? ORDER BY {time_col}",
                (self.contest_nr,)
            ).fetchall()
            logging.info("Filtering to ContestNR=%s — %d rows", self.contest_nr, len(rows))
        else:
            rows = c.execute(
                f"SELECT {sel} FROM {target} ORDER BY {time_col}"
            ).fetchall()
        conn.close()

        # ── Multiplier parsing regexes ────────────────────────────────────────
        # Use module-level compiled regexes (avoids recompile on every load() call)
        regex_packed = _PACKED_MULT_RE
        regex_short2 = _SHORT2_RE

        self.qsos = []
        # Hoist mult list/set and regexes outside the per-QSO loop (fixes per-row recompute)
        _plugin_mult_list = self.plugin.mult_list()
        _plugin_mult_set  = set(_plugin_mult_list) if _plugin_mult_list else set()
        for r in rows:
            d = dict(zip(sel_cols, r))

            call = str(d.get(call_col) or "").strip().upper()
            mode = str(d.get(mode_col) or "SSB").strip().upper()
            operator = str(d.get(op_col) or "").strip().upper() if op_col else ""

            # ── Raw exchange / section ────────────────────────────────────────
            raw_sect = str(d.get(sect_col) or "").strip().upper() if sect_col else ""
            raw_exch = str(d.get(mult_col) or "").strip().upper() if mult_col else ""
            if raw_sect and len(raw_sect) <= 10 and not raw_sect.isdigit():
                raw_mult = raw_sect
            else:
                raw_mult = raw_exch or raw_sect

            # ── Resolve multiplier value ──────────────────────────────────────
            mult = ""
            mult_source = ""


            if _plugin_mult_set:
                # Fixed-list contest (e.g. VK Shires): resolve raw exchange to
                # an official multiplier code.

                # 1) Full "STATE-XXN" form
                match = regex_packed.search(" " + raw_mult + " ")
                if match:
                    reconstructed = f"{match.group(1).upper()}-{match.group(2).upper()}{match.group(3)}"
                    if reconstructed in _plugin_mult_set:
                        mult = reconstructed; mult_source = "FULL"

                # 2) Short "XXN" form — derive state from the digit
                if not mult and raw_mult:
                    m_short = regex_short2.search(raw_mult)
                    if m_short:
                        letters = m_short.group(1).upper()
                        digit   = int(m_short.group(2))
                        st = VK_AREA_TO_STATE.get(digit)
                        if st:
                            candidate = f"{st}-{letters}{digit}"
                            if candidate in _plugin_mult_set:
                                mult = candidate; mult_source = "SHORT+DIGIT"

                # 3) Literal match — O(1) set lookup first, then substring scan.
                if not mult and raw_mult and len(raw_mult) >= 6:
                    if raw_mult in _plugin_mult_set:
                        mult = raw_mult; mult_source = "LITERAL"
                    else:
                        for official in _plugin_mult_list:
                            if official in raw_mult:
                                mult = official; mult_source = "LITERAL"; break

                # 4) Fallback (won't score as a valid mult)
                if not mult and raw_mult:
                    mult = raw_mult[:10]; mult_source = "FALLBACK"

            else:
                # All other contests: use the raw value directly.
                # For Trans-Tasman, raw_mult is now the WPXPrefix column value.
                if raw_mult:
                    mult = raw_mult[:20]
                    mult_source = "RAW"

            # ── Points and dupe ───────────────────────────────────────────────
            raw_pts = d.get(pts_col)
            try:
                pts = int(raw_pts or 0)
            except Exception:
                pts = 0

            raw_dupe = d.get(dupe_col) if dupe_col else None
            dupe_col_name = (dupe_col or "").lower()
            if dupe_col_name in ("isdupe", "dupe"):
                try:
                    dupe = int(raw_dupe or 0)
                except Exception:
                    dupe = 0
            elif dupe_col_name in ("app_n1mm_contacttype", "contacttype"):
                # N1MM ADIF/DB export: "D" = dupe.  Note: "N" (seen in some
                # contests, e.g. AADX, for a contact that's logged but
                # doesn't score — wrong continent, etc.) and blank/space
                # both mean "not a dupe", NOT "valid". Whether a QSO with
                # 0 points is legitimately non-scoring (vs. a real dupe)
                # is left for plugin.recalc_pts() to decide per-contest;
                # this column only tells us dupe-or-not, not score validity.
                dupe = 1 if str(raw_dupe or "").strip().upper() == "D" else 0
            else:
                # Last-resort fallback: 0-pt QSOs are dupes.
                # NOTE: this is overridden by plugin.recalc_pts() for contests
                # where 0 pts is valid (e.g. CQWW same-country contacts).
                dupe = 1 if pts == 0 else 0

            if pts == 0 and not dupe:
                pts = 1

            # ── Band ─────────────────────────────────────────────────────────
            band_raw = str(d.get(band_col) or "").strip() if band_col else ""
            band = ""
            if band_raw:
                try:
                    band_float = float(band_raw)
                    if 1.0 <= band_float <= 1500.0:
                        band = _freq_to_band(band_float)
                    else:
                        band = band_raw.upper()
                except ValueError:
                    band = band_raw.upper()
            if not band and freq_col:
                try:
                    band = _freq_to_band(float(d.get(freq_col) or 0))
                except Exception:
                    band = "?"

            # ── Timestamp ────────────────────────────────────────────────────
            tstr = d.get(time_col)
            t = None
            if tstr is not None:
                try:
                    t = datetime.fromtimestamp(
                        int(float(tstr)), tz=timezone.utc
                    ).replace(tzinfo=None)
                except Exception:
                    pass
                if t is None:
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S",
                                "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S"):
                        try:
                            t = datetime.strptime(str(tstr)[:19], fmt)
                            break
                        except Exception:
                            pass

            # ── CQ Zone ──────────────────────────────────────────────────────
            raw_zone = str(d.get(zone_col) or "").strip() if zone_col else ""
            cqz = None
            if raw_zone:
                try:
                    cqz = int(float(raw_zone))
                except (ValueError, TypeError):
                    pass
            if not cqz:
                cqz = cqz_from_call(call)

            # ── N1MM multiplier flags ─────────────────────────────────────────
            try:
                is_mult1 = int(d.get(m1_col) or 0) if m1_col else None
            except Exception:
                is_mult1 = None
            try:
                is_mult2 = int(d.get(m2_col) or 0) if m2_col else None
            except Exception:
                is_mult2 = None

            # ── Secondary-mult fallback ────────────────────────────────────
            # N1MM flagged this QSO as a secondary multiplier (IsMultiplier2)
            # but our exchange-column heuristic produced an empty `mult`
            # value (e.g. IARU HQ/official contacts, where Exchange1 is
            # blank in some .s3db exports and the HQ abbreviation lives
            # only in N1MM's own multiplier bookkeeping, not in any column
            # we read). A secondary mult can never legitimately have a
            # blank identity, so fall back to the worked callsign — any
            # non-numeric string is enough for plugins like IARU's
            # _is_hq_or_official() to correctly classify it as a secondary
            # (not primary/zone) multiplier instead of silently losing it.
            if is_mult2 == 1 and not mult:
                mult = call
                mult_source = mult_source or "IS_MULT2_FALLBACK"

            if call and t:
                self.qsos.append({
                    "call":        call,
                    "band":        band,
                    "mode":        mode,
                    "time":        t,
                    # mult1 is the normalised primary multiplier value
                    "mult1":       mult,
                    # keep legacy key for backward compat with debug view
                    "shire":       mult,
                    "cqz":         cqz,
                    "is_mult1":    is_mult1,
                    "is_mult2":    is_mult2,
                    "dupe":        dupe,
                    "pts":         pts,
                    "raw_mult":    raw_mult,
                    "mult_source": mult_source,
                    "qso_id":      str(d.get(id_col) or "") if id_col else "",
                    "operator":    operator,
                    "_table":      target,
                })

        self.plugin.recalc_pts(self.qsos)
        logging.info("Loaded %d QSOs (plugin: %s)", len(self.qsos), self.plugin.display_name)

    # ── Mutation ─────────────────────────────────────────────────────────────

    def delete_qso(self, qso_id, table):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(f"DELETE FROM {table} WHERE ID = ?", (qso_id,))
            conn.commit()
            logging.info("Deleted QSO ID=%s from %s", qso_id, table)
        finally:
            conn.close()
        self.qsos = [q for q in self.qsos if q.get("qso_id") != qso_id]

    # ── Generic read-only accessors (plugin-agnostic) ────────────────────────

    def qso_timeline(self):
        return self.qsos

    def total_qsos(self):
        return len(self.qsos)

    def valid_qsos(self):
        return sum(1 for q in self.qsos if not q["dupe"])

    def total_points(self):
        return sum(q["pts"] for q in self.qsos if not q["dupe"])

    def current_score(self):
        return self.plugin.score(self.qsos)

    def multipliers(self) -> MultResult:
        return self.plugin.multipliers(self.qsos)

    def worked_mults(self) -> set:
        return self.plugin.worked_primary_mults(self.qsos)

    def missing_mults(self) -> list:
        return self.plugin.missing_primary_mults(self.qsos)

    def worked_primary_band_mults(self) -> set:
        return self.plugin.worked_primary_band_mults(self.qsos)

    def worked_secondary_band_mults(self) -> set:
        return self.plugin.worked_secondary_band_mults(self.qsos)

    def worked_zones(self) -> set:
        return {q["cqz"] for q in self.qsos
                if not q["dupe"] and q["cqz"] is not None}

    def mults_by_region(self) -> dict:
        return self.plugin.mults_by_region(self.qsos)

    def region_heat(self) -> list:
        return self.plugin.region_heat(self.qsos)

    def band_efficiency(self) -> list:
        return self.plugin.band_efficiency(self.qsos)

    def rate_by_hour(self):
        if not self.qsos:
            return []
        buckets = defaultdict(int)
        for q in self.qsos:
            if not q["dupe"]:
                h = q["time"].replace(minute=0, second=0, microsecond=0)
                buckets[h] += 1
        return sorted(buckets.items())

    def band_breakdown(self):
        ml_set = set(self.plugin.mult_list())
        result = defaultdict(lambda: {"valid": 0, "dupe": 0, "mults": set()})
        for q in self.qsos:
            b = q["band"] or "?"
            if q["dupe"]:
                result[b]["dupe"] += 1
            else:
                result[b]["valid"] += 1
                if ml_set:
                    if q["mult1"] in ml_set:
                        result[b]["mults"].add(q["mult1"])
                elif q["mult1"]:
                    result[b]["mults"].add(q["mult1"])
        return dict(result)

    def dupe_analysis(self):
        by_band, by_call = defaultdict(int), defaultdict(int)
        for q in self.qsos:
            if q["dupe"]:
                by_band[q["band"]] += 1
                by_call[q["call"]] += 1
        return by_band, by_call

    def last_worked(self, n=5):
        valid = [q for q in self.qsos if not q["dupe"]]
        return sorted(valid, key=lambda q: q["time"], reverse=True)[:n]

    # ── Session / block helpers (delegated to plugin SessionConfig) ───────────

    @property
    def _session_cfg(self) -> SessionConfig:
        return self.plugin.session_config()

    def contest_start(self):
        """Return contest start datetime, anchored to the plugin's start hour.

        For plugins that implement contest_saturday() (e.g. Trans-Tasman),
        the calculated Saturday is used as the authoritative date so that
        the DB's stored ContestStart (which N1MM sometimes sets to the log
        creation date rather than the contest date) is overridden.
        """
        start_h = self.plugin.session_config().start_hour or 0

        # ── Plugin provides an authoritative date calculation ─────────────────
        if hasattr(self.plugin, "contest_saturday"):
            # Determine the year from the DB start date or first QSO
            if self._contest_start_dt:
                year = self._contest_start_dt.year
            elif self.qsos:
                year = min(q["time"] for q in self.qsos).year
            else:
                year = datetime.datetime.utcnow().year
            sat = self.plugin.contest_saturday(year)
            return datetime(sat.year, sat.month, sat.day, start_h, 0, 0)

        if self._contest_start_dt:
            cs = self._contest_start_dt
            if start_h:
                cs = cs.replace(hour=start_h, minute=0, second=0, microsecond=0)
            return cs
        if not self.qsos:
            return None
        # Fallback: midnight before first QSO, then adjust to plugin's start hour
        first = min(q["time"] for q in self.qsos)
        if start_h:
            base = first.replace(hour=0, minute=0, second=0, microsecond=0)
            cs = base.replace(hour=start_h)
            if first < cs:
                cs = base
            return cs
        return first.replace(hour=0, minute=0, second=0, microsecond=0)

    def session_number(self, t, contest_start):
        elapsed = (t - contest_start).total_seconds() / 60
        return max(0, int(elapsed // self._session_cfg.duration_mins))

    def session_label(self, session_nr, contest_start):
        cfg = self._session_cfg
        start_min = session_nr * cfg.duration_mins
        end_min   = start_min + cfg.duration_mins
        s_h, s_m  = divmod(start_min, 60)
        e_h, e_m  = divmod(end_min,   60)
        return f"{cfg.label_prefix}{session_nr+1}  {s_h:02d}:{s_m:02d}–{e_h:02d}:{e_m:02d}"

    def rate_by_session(self):
        cfg = self._session_cfg
        cs  = self.contest_start()
        if not cs or not self.qsos:
            return []

        sessions = defaultdict(list)
        for q in self.qsos:
            if not q["dupe"]:
                sn = self.session_number(q["time"], cs)
                sessions[sn].append(q)

        num_sessions = max(sessions.keys()) + 1 if sessions else 1
        cum_primary   = set()
        cum_secondary = set()
        running_cum_pts = 0   # accumulated to avoid O(n²) re-sum each session
        result = []

        for sn in range(num_sessions):
            qs = sessions.get(sn, [])

            sess_start = cs + timedelta(minutes=sn * cfg.duration_mins)
            sess_end   = cs + timedelta(minutes=(sn + 1) * cfg.duration_mins)
            hour_buckets = {}
            cur_h = sess_start.replace(minute=0, second=0, microsecond=0)
            while cur_h < sess_end:
                hour_buckets[cur_h] = 0
                cur_h += timedelta(hours=1)
            for q in qs:
                h = q["time"].replace(minute=0, second=0, microsecond=0)
                hour_buckets[h] = hour_buckets.get(h, 0) + 1

            new_primary = set()
            new_secondary = set()
            for q in qs:
                if q.get("is_mult1") == 1 and q["mult1"]:
                    key = (q["mult1"], q["band"], q["mode"])
                    if key not in cum_primary:
                        new_primary.add(key)
                if q.get("is_mult2") == 1 and q.get("cqz"):
                    key = (q["cqz"], q["band"], q["mode"])
                    if key not in cum_secondary:
                        new_secondary.add(key)
            cum_primary   |= new_primary
            cum_secondary |= new_secondary
            total_cum_mults = len(cum_primary) + len(cum_secondary)

            session_pts      = sum(q["pts"] for q in qs)
            running_cum_pts += session_pts   # O(1) accumulation replaces O(n²) re-sum
            cum_pts          = running_cum_pts

            result.append({
                "label":         self.session_label(sn, cs),
                "session":       sn + 1,
                "qsos":          len(qs),
                "pts":           session_pts,
                "new_mults":     len(new_primary) + len(new_secondary),
                "cum_mults":     total_cum_mults,
                "running_score": cum_pts * total_cum_mults,
                "by_hour":       sorted(hour_buckets.items()),
                "start":         sess_start,
                "end":           sess_end,
            })

        return result

    def sparkline_data(self):
        cfg = self._session_cfg
        contest_hours = int(math.ceil(cfg.duration_mins * cfg.num_sessions / 60))

        cs = self.contest_start()
        if self.qsos:
            earliest = min(q["time"] for q in self.qsos)
            if cs is None or cs > earliest:
                cs = earliest.replace(minute=0, second=0, microsecond=0)

        qso_by_hour   = [0] * contest_hours
        mults_by_hour = [0] * contest_hours
        seen_mults    = set()

        valid = sorted([q for q in self.qsos if not q["dupe"]], key=lambda q: q["time"])
        for q in valid:
            new_mults = self.plugin.sparkline_mults(q, seen_mults)
            if cs is not None:
                bucket = int((q["time"] - cs).total_seconds() // 3600)
            else:
                bucket = q["time"].hour
            if 0 <= bucket < contest_hours:
                qso_by_hour[bucket] += q["pts"]
                mults_by_hour[bucket] += new_mults

        # O(n) forward pass — avoids the O(n²) full-scan per hour of the original
        running_score = [0] * contest_hours
        acc: list = []
        vi = 0
        for h in range(contest_hours):
            if cs is not None:
                bucket_end = cs + timedelta(hours=h + 1)
                while vi < len(valid) and valid[vi]["time"] < bucket_end:
                    acc.append(valid[vi])
                    vi += 1
            else:
                while vi < len(valid) and valid[vi]["time"].hour == h:
                    acc.append(valid[vi])
                    vi += 1
            # Use plugin hook so block-formula contests (e.g. RD) show
            # their real score progression rather than pts * mults
            running_score[h] = self.plugin.running_score_for_sparkline(acc)

        if vi < len(valid):
            acc.extend(valid[vi:])
            if running_score:
                running_score[-1] = self.plugin.running_score_for_sparkline(acc)

        return {
            "qsos":          qso_by_hour,
            "running_score": running_score,
            "new_mults":     mults_by_hour,
        }

    def personal_bests(self):
        if not self.qsos:
            return {}
        hour_buckets = defaultdict(int)
        for q in self.qsos:
            if not q["dupe"]:
                h = q["time"].replace(minute=0, second=0, microsecond=0)
                hour_buckets[h] += 1

        best_hour_time = max(hour_buckets, key=hour_buckets.get) if hour_buckets else None
        best_hour_rate = hour_buckets[best_hour_time] if best_hour_time else 0

        now       = datetime.now(timezone.utc).replace(tzinfo=None, minute=0, second=0, microsecond=0)
        prev_hour = now - timedelta(hours=1)
        current_hour_rate = hour_buckets.get(now, 0)
        prev_hour_rate    = hour_buckets.get(prev_hour, 0)

        cs = self.contest_start()
        sess_qsos = defaultdict(int)
        if cs:
            for q in self.qsos:
                if not q["dupe"]:
                    sn = self.session_number(q["time"], cs)
                    sess_qsos[sn] += 1
        best_sess_nr   = max(sess_qsos, key=sess_qsos.get) + 1 if sess_qsos else 0
        best_sess_qsos = sess_qsos[best_sess_nr - 1] if sess_qsos else 0

        return {
            "best_hour_rate":    best_hour_rate,
            "best_hour_time":    best_hour_time,
            "best_session_qsos": best_sess_qsos,
            "best_session_nr":   best_sess_nr,
            "current_hour_rate": current_hour_rate,
            "prev_hour_rate":    prev_hour_rate,
        }

    def session_status(self):
        cfg = self._session_cfg
        cs  = self.contest_start()
        if not cs:
            return {}
        now           = datetime.now(timezone.utc).replace(tzinfo=None)
        total_mins    = cfg.num_sessions * cfg.duration_mins
        elapsed_total = (now - cs).total_seconds() / 60

        if elapsed_total < 0:
            mins_to_start = abs(elapsed_total)
            return {
                "state":           "pre",
                "session_nr":      0,
                "session_label":   "Pre-Contest",
                "elapsed_mins":    0,
                "remaining_mins":  mins_to_start,
                "pct_elapsed":     0,
                "contest_over":    False,
                "next_session_nr": 1,
                "start_dt":        cs,
                "mins_to_start":   mins_to_start,
            }

        if elapsed_total >= total_mins:
            return {
                "state":           "over",
                "session_nr":      cfg.num_sessions,
                "session_label":   f"{cfg.label_prefix}{cfg.num_sessions} (ended)",
                "elapsed_mins":    total_mins,
                "remaining_mins":  0,
                "pct_elapsed":     100,
                "contest_over":    True,
                "next_session_nr": None,
                "start_dt":        cs,
                "end_dt":          cs + timedelta(minutes=total_mins),
            }

        sn           = int(elapsed_total // cfg.duration_mins)
        sess_elapsed = elapsed_total - sn * cfg.duration_mins
        sess_remain  = max(0, cfg.duration_mins - sess_elapsed)
        return {
            "state":           "live",
            "session_nr":      sn + 1,
            "session_label":   self.session_label(sn, cs),
            "elapsed_mins":    sess_elapsed,
            "remaining_mins":  sess_remain,
            "pct_elapsed":     sess_elapsed / cfg.duration_mins * 100,
            "contest_over":    False,
            "next_session_nr": sn + 2 if sn + 1 < cfg.num_sessions else None,
            "start_dt":        cs,
            # ── Whole-contest progress (used by plugins without a block
            #    structure, e.g. CQWW's single 48h session) ────────────────
            "total_elapsed_mins":   elapsed_total,
            "total_remaining_mins": max(0, total_mins - elapsed_total),
            "total_pct_elapsed":    elapsed_total / total_mins * 100 if total_mins else 0,
            "end_dt":               cs + timedelta(minutes=total_mins),
        }

    def operator_time_summary(self, gap_threshold_mins=30):
        """
        Per-operator on-air ("On") vs. gap ("Off") time, derived from QSO
        timestamps and the DXLOG ``Operator`` column.

        QSOs are grouped by operator and sorted by time.  Consecutive QSOs
        whose gap is <= gap_threshold_mins are treated as continuous
        operating ("On") time; larger gaps within that operator's overall
        span (first QSO -> last QSO) are counted as "Off" time (e.g. sleep
        breaks, band changes to listen, etc.).

        Returns a list of dicts, sorted by total on-time descending:
            operator, qsos, first, last, span_minutes,
            on_minutes, off_minutes, sessions
        """
        by_op: dict = defaultdict(list)
        for q in self.qsos:
            op = (q.get("operator") or "").strip() or "—"
            by_op[op].append(q["time"])

        result = []
        for op, times in by_op.items():
            times = sorted(times)
            first, last = times[0], times[-1]
            on_minutes  = 0.0
            off_minutes = 0.0
            sessions    = 1
            for i in range(1, len(times)):
                gap = (times[i] - times[i - 1]).total_seconds() / 60.0
                if gap > gap_threshold_mins:
                    off_minutes += gap
                    sessions += 1
                else:
                    on_minutes += gap
            result.append({
                "operator":     op,
                "qsos":         len(times),
                "first":        first,
                "last":         last,
                "span_minutes": (last - first).total_seconds() / 60.0,
                "on_minutes":   on_minutes,
                "off_minutes":  off_minutes,
                "sessions":     sessions,
            })
        return sorted(result, key=lambda r: r["on_minutes"], reverse=True)

    # ── "Next QSO" value estimate (Overview "QSO Value" panel) ───────────────

    def _qso_value_estimate(self, qsos: list, plugin) -> dict:
        """
        Return the marginal-score data consumed by ``_draw_qso_value_on_ax``.

        If the active plugin implements ``qso_value_estimate(qsos)`` (e.g.
        CQWW, where it models the new-DXCC / new-zone double-mult case),
        that result is used directly. Otherwise fall back to a generic
        estimator that works for any "TotalPoints × TotalMultipliers"-style
        contest.
        """
        fn = getattr(plugin, "qso_value_estimate", None)
        if callable(fn):
            try:
                return fn(qsos)
            except Exception:
                logging.exception("qso_value_estimate failed for plugin %r", plugin)
        return self._generic_qso_value_estimate(qsos, plugin)

    @staticmethod
    def _generic_qso_value_estimate(qsos: list, plugin) -> dict:
        """
        Generic fallback "next QSO" value estimator.

        Works out whether the contest scores as TotalPoints × TotalMultipliers
        (the classic DX-contest formula CQWW/WPX/etc use) by comparing
        ``plugin.score(qsos)`` against ``pts × mults``. If so, the same
        delta formula as the CQWW plugin is used:

            delta = p * (M + dm) + P * dm

        for dm = 0 (no new mult), 1 (one new mult) and 2 (two new mults).
        If the contest scores additively (score == total points, multipliers
        are just a count rather than a multiplying factor), only the
        "no new mult" figure is meaningful — it's simply the average points
        for that band — and the multiplier scenarios are omitted.
        """
        valid     = [q for q in qsos if not q["dupe"]]
        total_pts = sum(q["pts"] for q in valid)

        try:
            mr = plugin.multipliers(qsos)
            total_mults = len(mr.primary_mults) + len(mr.secondary_mults)
        except Exception:
            total_mults = 0

        try:
            score = plugin.score(qsos)
        except Exception:
            score = total_pts

        multiplicative = total_mults > 0 and abs(score - total_pts * total_mults) < 1.0
        overall_avg = (total_pts / len(valid)) if valid else 0.0

        band_pts: dict = defaultdict(list)
        for q in valid:
            b = (q.get("band") or "?").upper()
            band_pts[b].append(q["pts"])

        def delta(p, dm):
            if multiplicative:
                return p * (total_mults + dm) + total_pts * dm
            return p

        bands: dict = {}
        for band, pts_list in band_pts.items():
            n     = len(pts_list)
            avg_p = (sum(pts_list) / n) if n else overall_avg
            bands[band] = {
                "qsos":     n,
                "avg_pts":  avg_p,
                "no_mult":  delta(avg_p, 0),
                "one_mult": delta(avg_p, 1),
                "two_mult": delta(avg_p, 2),
            }

        band_order = sorted(
            bands.keys(),
            key=lambda b: _BAND_ORDER.index(b) if b in _BAND_ORDER else 99,
        )

        scenarios = ["no_mult", "one_mult", "two_mult"] if multiplicative else ["no_mult"]
        labels = {
            "no_mult":  "+QSO",
            "one_mult": "+QSO +1 mult",
            "two_mult": "+QSO +2 mults",
        }
        return {
            "total_pts":     total_pts,
            "total_mults":   total_mults,
            "overall_avg":   overall_avg,
            "bands":         bands,
            "band_order":    band_order,
            "scenarios":     scenarios,
            "scenario_labels": labels,
            "multiplicative": multiplicative,
        }

    def compute_snapshot(self) -> dict:
        """
        Single-pass computation of every value needed by _refresh_overview_cards.

        Previously that function issued 13+ separate calls into ContestLog /
        plugin, each iterating self.qsos independently.  Key problems that are
        fixed here:

          1. multipliers() / worked_mults() / missing_mults() all called
             plugin.multipliers(qsos) separately — now called once.

          2. total_qsos() / valid_qsos() / vk_cnt / zl_cnt / last_worked() /
             personal_bests() each filtered or scanned the QSO list — now a
             single iteration populates all of them.

          3. sparkline_data() had an O(n²) running_score loop: it extended
             qsos_so_far and called plugin.running_score_for_sparkline() 24
             times on growing sublists.  Replaced with a single forward pass
             that accumulates pts and a running mult-set, computing the score
             incrementally per hour.

          4. band_efficiency() and region_heat() retain their own plugin
             calls (they are not called anywhere else and their logic is
             plugin-specific), but they now run exactly once per snapshot
             instead of potentially multiple times.

        _refresh_overview_cards() consumes the returned dict directly;
        no other callers are affected.
        """
        qsos   = self.qsos
        plugin = self.plugin
        ml_set = set(plugin.mult_list())

        # ── Sparkline bucket count: size to the contest's actual duration ────
        # The "QSOs/Hour", "Running Score" and "New Mults/Hr" sparklines used
        # to be hardcoded to 24 buckets indexed by q["time"].hour (hour-of-day,
        # UTC).  That's correct for 24h contests like VK Shires, but for a 48h
        # contest like CQWW the second day's QSOs have .hour values that
        # collide with day-1's (0-23 again), so the old "while ... .hour == h"
        # loop only ever consumed day 1 and silently dropped every QSO from
        # day 2 — the Running Score sparkline plateaued at the end of day 1
        # and never reached the real total score.
        #
        # Fix: size the buckets to the contest's full length (in whole hours,
        # minimum 24) and bucket by elapsed hours since contest start instead
        # of hour-of-day, so every QSO — on any day — lands in a bucket and
        # the final "Running Score" point always matches score().
        cfg = self._session_cfg
        contest_hours = int(math.ceil(cfg.duration_mins * cfg.num_sessions / 60))

        cs = self.contest_start()
        if self.qsos:
            earliest = min(q["time"] for q in self.qsos)
            # StartDate sometimes lands after the first QSO (N1MM quirk) —
            # anchor to the first QSO's hour in that case, same fallback used
            # by _yoy_build_trajectory().
            if cs is None or cs > earliest:
                cs = earliest.replace(minute=0, second=0, microsecond=0)

        # ── Single multiplier computation (replaces 3 separate plugin calls) ──
        mr          = plugin.multipliers(qsos)
        worked_cnt  = len(mr.primary_mults)       # unique primary mults worked
        band_mult_cnt = len(mr.primary_mults)      # same set — kept separate key
                                                   # for gauge labelling compat
        zone_cnt    = len(mr.secondary_mults)

        # missing = full list minus worked (primary values, not band-tuples)
        worked_primary_vals = {t[0] if isinstance(t, tuple) else t
                               for t in mr.primary_mults}
        missing_cnt = len([m for m in ml_set if m not in worked_primary_vals])

        total_mults = len(ml_set)
        pct = (worked_cnt / total_mults * 100) if total_mults else 0

        # ── Single QSO pass: valid filter + call-prefix counts +
        #    hour buckets (personal_bests) + sparkline raw data ────────────────
        valid        = []
        vk_cnt       = 0
        zl_cnt       = 0
        hour_buckets = defaultdict(int)   # datetime(hour) → qso count
        by_hour_cnt  = [0] * contest_hours   # index = elapsed contest hour (QSO count, not pts)
        seen_mults   = set()
        mults_by_hour = [0] * contest_hours

        for q in qsos:
            if q["dupe"]:
                continue
            valid.append(q)
            call = q.get("call", "").upper()
            if _VK_PREFIX_RE.match(call):
                vk_cnt += 1
            if call.startswith(("ZL", "ZM")):
                zl_cnt += 1
            h_key = q["time"].replace(minute=0, second=0, microsecond=0)
            hour_buckets[h_key] += 1

            # Always advance the mult-tracking set (it has side effects on
            # seen_mults), even if this QSO falls outside the bucket range.
            new_mults = plugin.sparkline_mults(q, seen_mults)
            if cs is not None:
                bucket = int((q["time"] - cs).total_seconds() // 3600)
            else:
                bucket = q["time"].hour
            if 0 <= bucket < contest_hours:
                by_hour_cnt[bucket] += 1
                mults_by_hour[bucket] += new_mults

        total_qsos_n = len(qsos)
        valid_qsos_n = len(valid)

        # ── Score (single plugin call) ────────────────────────────────────────
        score = plugin.score(qsos)

        # ── Sparkline running_score — O(n) forward accumulation ──────────────
        # Sort valid QSOs once by time, then walk hour-by-hour (elapsed
        # contest hours, not hour-of-day) accumulating a sublist.
        # plugin.running_score_for_sparkline() is called once per bucket but
        # each call receives an incrementally extended list, avoiding any
        # re-scanning of earlier QSOs.
        valid_sorted  = sorted(valid, key=lambda q: q["time"])
        running_score = [0] * contest_hours
        acc: list     = []
        vi            = 0
        for h in range(contest_hours):
            if cs is not None:
                bucket_end = cs + timedelta(hours=h + 1)
                while vi < len(valid_sorted) and valid_sorted[vi]["time"] < bucket_end:
                    acc.append(valid_sorted[vi])
                    vi += 1
            else:
                while vi < len(valid_sorted) and valid_sorted[vi]["time"].hour == h:
                    acc.append(valid_sorted[vi])
                    vi += 1
            running_score[h] = plugin.running_score_for_sparkline(acc)

        # Any QSOs landing after the nominal contest window (e.g. a late/
        # mistimed log entry) still belong in the final cumulative figure so
        # the sparkline's last point always matches score()/TOTAL SCORE.
        if vi < len(valid_sorted):
            acc.extend(valid_sorted[vi:])
            if running_score:
                running_score[-1] = plugin.running_score_for_sparkline(acc)

        sparklines = {
            "qsos":          by_hour_cnt,
            "running_score": running_score,
            "new_mults":     mults_by_hour,
        }

        # ── Personal bests (derived from already-built hour_buckets) ─────────
        if hour_buckets:
            best_hour_time = max(hour_buckets, key=hour_buckets.get)
            best_hour_rate = hour_buckets[best_hour_time]
        else:
            best_hour_time = None
            best_hour_rate = 0

        now_dt    = datetime.now(timezone.utc).replace(tzinfo=None,
                                                       minute=0, second=0,
                                                       microsecond=0)
        prev_hour = now_dt - timedelta(hours=1)
        current_hour_rate = hour_buckets.get(now_dt,    0)
        prev_hour_rate    = hour_buckets.get(prev_hour, 0)

        cs = self.contest_start()
        sess_qsos: dict = defaultdict(int)
        if cs:
            for q in valid:
                sn = self.session_number(q["time"], cs)
                sess_qsos[sn] += 1
        best_sess_nr   = max(sess_qsos, key=sess_qsos.get) + 1 if sess_qsos else 0
        best_sess_qsos = sess_qsos[best_sess_nr - 1] if sess_qsos else 0

        personal_bests = {
            "best_hour_rate":    best_hour_rate,
            "best_hour_time":    best_hour_time,
            "best_session_qsos": best_sess_qsos,
            "best_session_nr":   best_sess_nr,
            "current_hour_rate": current_hour_rate,
            "prev_hour_rate":    prev_hour_rate,
        }

        # ── Gauge nice-ceiling helper ─────────────────────────────────────────
        def nice_ceil(value, min_max=10):
            if value <= 0:
                return max(min_max, 10)
            target    = max(value * 1.2, min_max)
            magnitude = 10 ** (len(str(int(target))) - 1)
            for step in [1, 2, 2.5, 5, 10]:
                ceiling = math.ceil(target / (magnitude * step)) * magnitude * step
                if ceiling >= target:
                    return int(ceiling) if ceiling == int(ceiling) else ceiling
            return int(math.ceil(target / magnitude) * magnitude)

        return_dict = {
            # ── scalar card values ────────────────────────────────────────────
            "total":           total_qsos_n,
            "valid":           valid_qsos_n,
            "score":           score,
            "worked":          worked_cnt,
            "band_mults":      band_mult_cnt,
            "missing":         missing_cnt,
            "pct":             pct,
            "zone_cnt":        zone_cnt,
            "zone_band_cnt":   len(mr.secondary_mults),
            "vk_cnt":          vk_cnt,
            "zl_cnt":          zl_cnt,
            # ── gauge maxima ──────────────────────────────────────────────────
            "qso_max":         nice_ceil(total_qsos_n, min_max=50),
            "score_max":       nice_ceil(score,        min_max=500),
            # ── richer panel data ─────────────────────────────────────────────
            "worked_zones":    sorted({t[0] if isinstance(t, tuple) else t
                                       for t in mr.secondary_mults}),
            "band_efficiency": plugin.band_efficiency(qsos),
            "region_heat":     plugin.region_heat(qsos),
            "personal_bests":  personal_bests,
            "session_status":  self.session_status(),
            "last_worked":     sorted(valid, key=lambda q: q["time"],
                                      reverse=True)[:5],
            "sparklines":      sparklines,
            "operator_times":  self.operator_time_summary(),
            # ── "next QSO" value estimate for the QSO Value overview panel ────
            "qso_value":       self._qso_value_estimate(qsos, plugin),
            # ── plugin reference (consumed by overview draw helpers) ──────────
            "_plugin":         plugin,
            "_total_mults":    total_mults,
            # ── mult result (available if callers need deeper inspection) ─────
            "_mult_result":    mr,
        }

        # Allow the plugin to correct or augment display values (e.g. CQWW
        # needs unique-country and unique-zone counts rather than band×mult
        # pair counts for its gauges).
        plugin.post_snapshot(return_dict, qsos)
        return return_dict


# ═══════════════════════════════════════════════════════════════════════════════
# ── UI helpers ───────────────────────────────────────────────────────────────

class _Tooltip:
    """
    Lightweight hover tooltip for any tkinter widget.
    Usage:  _Tooltip(widget, "Helpful text here")
    """
    PAD   = 6
    DELAY = 500   # ms before appearing
    POLL  = 200   # ms between stuck-tooltip safety checks

    def __init__(self, widget, text: str):
        self._widget    = widget
        self._text      = text
        self._tip_win   = None
        self._job       = None
        self._poll_job  = None
        widget.bind("<Enter>",  self._on_enter, add="+")
        widget.bind("<Leave>",  self._on_leave, add="+")
        widget.bind("<Destroy>", self._on_leave, add="+")

    def _on_enter(self, event=None):
        self._job = self._widget.after(self.DELAY, self._show)

    def _on_leave(self, event=None):
        if self._job:
            self._widget.after_cancel(self._job)
            self._job = None
        self._hide()

    def _show(self):
        if self._tip_win:
            return
        x = self._widget.winfo_rootx() + self._widget.winfo_width() // 2
        y = self._widget.winfo_rooty() - 28
        self._tip_win = tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)
        tk.Label(
            tw, text=self._text,
            font=("Consolas", 9), fg=FG, bg=BG3,
            relief="flat", bd=0,
            padx=self.PAD + 4, pady=self.PAD,
            wraplength=340, justify="left",
        ).pack()
        # Thin accent border via a surrounding frame trick
        tw.configure(bg=ACCENT)
        tw.wm_attributes("-transparentcolor", "")
        self._start_poll()

    def _start_poll(self):
        # Safety net: if the tooltip box ends up overlapping the source
        # widget (e.g. widgets near the top of the window, where the tip
        # renders above and can cover the widget itself), moving the
        # cursor from the widget straight into the tooltip never fires
        # <Leave> on the widget, leaving the tooltip stuck on screen.
        # Poll the real OS cursor position independently of widget events.
        if self._poll_job:
            self._widget.after_cancel(self._poll_job)
        self._poll_job = self._widget.after(self.POLL, self._check_still_valid)

    def _check_still_valid(self):
        self._poll_job = None
        if not self._tip_win:
            return
        try:
            px, py = self._widget.winfo_pointerxy()
            wx0, wy0 = self._widget.winfo_rootx(), self._widget.winfo_rooty()
            ww, wh   = self._widget.winfo_width(), self._widget.winfo_height()
            over_widget = (wx0 <= px <= wx0 + ww) and (wy0 <= py <= wy0 + wh)
        except Exception:
            over_widget = False
        if not over_widget:
            self._hide()
            return
        self._start_poll()

    def _hide(self):
        if self._poll_job:
            try:
                self._widget.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = None
        if self._tip_win:
            try:
                self._tip_win.destroy()
            except Exception:
                pass
            self._tip_win = None
# ═══════════════════════════════════════════════════════════════════════════════

def _set_app_icon(window):
    try:
        if getattr(sys, "frozen", False):
            base = sys._MEIPASS
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        ico = os.path.join(base, "vk_icon.ico")
        if os.path.exists(ico):
            window.iconbitmap(ico)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# ── ContestPickerDialog ──────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

class ContestPickerDialog(tk.Toplevel):
    """
    Modal dialog: lists every contest in the .s3db and lets the user pick one.
    Sets self.result to (contest_nr, plugin) or (None, None) if cancelled.

    FIX (load delay): available_contests() runs in a background thread so the
    dialog window appears instantly and the DB query does not block the main
    thread / freeze the UI while scanning large log files.
    """

    def __init__(self, master, db_path):
        super().__init__(master)
        self.title("Select Contest")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.result    = None
        self._db_path  = db_path
        self._contests = []
        self._loaded   = False
        self.bind("<Escape>", lambda e: self._cancel())

        # ── Static header ────────────────────────────────────────────────────
        tk.Label(self, text="Select Contest to Analyse",
                 font=FONT_H, fg=ACCENT, bg=BG,
                 pady=12).pack(fill="x", padx=20)
        self._subtitle_var = tk.StringVar(
            value="Scanning database…  please wait")
        tk.Label(self, textvariable=self._subtitle_var,
                 font=FONT_B, fg=MUTED, bg=BG,
                 justify="left").pack(anchor="w", padx=20)

        # ── Listbox (empty until data arrives) ───────────────────────────────
        frame = tk.Frame(self, bg=BG2,
                         highlightbackground=BG3, highlightthickness=1)
        frame.pack(fill="both", expand=True, padx=20, pady=12)

        sb = ttk.Scrollbar(frame, orient="vertical")
        sb.pack(side="right", fill="y")
        self._lb = tk.Listbox(
            frame,
            bg=BG3, fg=FG, selectbackground=ACCENT, selectforeground=BG,
            font=("Consolas", 10), relief="flat", bd=0,
            yscrollcommand=sb.set, activestyle="none",
            height=10,
        )
        self._lb.pack(side="left", fill="both", expand=True)
        sb.config(command=self._lb.yview)

        # Placeholder row while loading
        self._lb.insert("end", "  ⏳  Loading contests from database…")
        self._lb.itemconfig(0, fg=MUTED)

        self._lb.bind("<Double-Button-1>", lambda e: self._confirm())
        self._lb.bind("<Return>",          lambda e: self._confirm())
        self._lb.bind("<KP_Enter>",        lambda e: self._confirm())

        tk.Label(self,
                 text="↑ ↓ to navigate  ·  Enter to select  ·  Esc to cancel",
                 font=("Consolas", 8), fg=MUTED, bg=BG).pack(pady=(0, 6))

        btn_row = tk.Frame(self, bg=BG)
        btn_row.pack(fill="x", padx=20, pady=(0, 16))
        self._confirm_btn = tk.Button(
            btn_row, text="Analyse Selected Contest",
            font=FONT_B, bg=BG3, fg=MUTED,
            activebackground=ACCENT2, activeforeground=BG,
            relief="flat", bd=0, padx=16, pady=7,
            cursor="arrow", state="disabled",
            command=self._confirm,
        )
        self._confirm_btn.pack(side="right", padx=(8, 0))
        tk.Button(
            btn_row, text="Cancel",
            font=FONT_B, bg=BG3, fg=MUTED,
            activebackground=BG2, activeforeground=FG,
            relief="flat", bd=0, padx=16, pady=7,
            cursor="hand2", command=self._cancel,
        ).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.transient(master)
        self.grab_set()

        DW, DH = 600, 360
        self.geometry(f"{DW}x{DH}")
        self.update_idletasks()
        master.update_idletasks()
        mx = master.winfo_rootx() + master.winfo_width()  // 2
        my = master.winfo_rooty() + master.winfo_height() // 2
        self.geometry(f"{DW}x{DH}+{mx - DW//2}+{my - DH//2}")

        # ── Kick off DB query in background; results polled via after() ───────
        self._load_queue: queue.Queue = queue.Queue()
        threading.Thread(target=self._bg_load, daemon=True).start()
        self._poll_load()

        # ── Fade in smoothly ─────────────────────────────────────────────────
        self.attributes("-alpha", 0.0)
        _fade_in(self, target_alpha=0.98)

    # ── Background loader ────────────────────────────────────────────────────

    def _bg_load(self):
        """Run available_contests() on a worker thread; push result to queue."""
        try:
            contests = ContestLog.available_contests(self._db_path)
            self._load_queue.put(("ok", contests))
        except Exception as exc:
            self._load_queue.put(("err", str(exc)))

    def _poll_load(self):
        """Poll for the background result every 80 ms (main-thread safe)."""
        try:
            kind, payload = self._load_queue.get_nowait()
        except queue.Empty:
            # Still waiting — reschedule
            try:
                self.after(80, self._poll_load)
            except Exception:
                pass
            return

        if kind == "err":
            self._subtitle_var.set("⚠  Could not read database.")
            return

        self._populate(payload)

    def _populate(self, contests):
        """Fill the listbox once contest data has arrived from the worker."""
        self._contests = contests

        # Clear placeholder
        self._lb.delete(0, "end")

        if not contests:
            self._lb.insert("end", "  (no contests found in this database)")
            self._lb.itemconfig(0, fg=MUTED)
            self._subtitle_var.set("No contests found in this database.")
            return

        self._subtitle_var.set(
            f"Found {len(contests)} contest(s) with QSOs in this database.\n"
            "Choose the one you want to analyse:"
        )

        for i, ct in enumerate(contests):
            date    = str(ct["StartDate"])[:10] if ct["StartDate"] else "unknown date"
            qso_cnt = ct["QSOCount"]
            p       = plugin_for(str(ct["ContestName"]))
            tag     = f"[{p.display_name}]"
            if qso_cnt == 0:
                label = f"  {ct['DisplayName']:<30}  {date}  {tag}  (no QSOs)"
            else:
                label = f"  {ct['DisplayName']:<30}  {date}  {tag}  ({qso_cnt} QSOs)"
            self._lb.insert("end", label)
            if qso_cnt == 0:
                self._lb.itemconfig(i, fg=MUTED)

        # Pre-select VKSHIRES if present, else first item
        presel = 0
        for i, ct in enumerate(contests):
            if "VKSHIRES" in str(ct["ContestName"]).upper():
                presel = i
                break
        self._lb.selection_set(presel)
        self._lb.see(presel)
        self._lb.focus_set()

        # Enable confirm button now that data is ready
        self._confirm_btn.configure(
            state="normal", bg=ACCENT, fg=BG, cursor="hand2")
        self._loaded = True

    def _confirm(self):
        sel = self._lb.curselection()
        if sel:
            ct = self._contests[sel[0]]
            p  = plugin_for(str(ct["ContestName"]))
            self.result = (ct["ContestNR"], p)
        self.grab_release()
        self.destroy()

    def _cancel(self):
        self.result = None
        self.grab_release()
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════════════
# ── App — main window ────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

class App(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title(f"VK Contest Analyzer  v{VERSION}  ·  By VK2YI  ·  N1MM+ Log Intelligence")
        _set_app_icon(self)
        self.update_idletasks()
        aw, ah = 1500, 900
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{aw}x{ah}+{(sw-aw)//2}+{(sh-ah)//2}")
        # ── Windows: enforce dark-mode title bar to match the app theme ──────
        if platform.system() == "Windows":
            import ctypes
            try:
                hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
                DWMWA_USE_IMMERSIVE_DARK_MODE = 20
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                    ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int(1))
                )
            except Exception:
                pass
        self.minsize(1280, 820)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.log = None
        self._db_path = None
        self._contest_nr = None
        self._plugin = GenericPlugin()
        self._auto_refresh_job = None
        self._auto_interval_ms = 15000
        self._countdown_remaining = 15
        self._result_queue = queue.Queue()
        self._poll_job = None
        self._cascade_jobs = []
        self._tab_dirty    = {}
        self._config      = _load_config()
        self._active_tabs = self._config.get("active_tabs",
                            {t["attr"]: t["default_on"] for t in TAB_REGISTRY})
        # Guard against a Tk/ttk-on-Windows quirk where double-clicking the
        # OS titlebar to maximize can deliver a stray click to the Notebook
        # tab strip during the resize, silently switching the active tab.
        # We track the last known-good tab and snap back to it if a
        # maximize/restore transition appears to have changed it.
        self._last_active_tab = None
        self._win_resize_job  = None
        self.bind("<Configure>", self._on_window_configure)
        self._build_ui()
        self._tick_countdown()

    def _on_close(self):
        # Cancel all pending after() jobs before destroying the window
        for job_attr in ("_auto_refresh_job", "_poll_job", "_pace_alarm_job",
                         "_pulse_job", "_cascade_jobs"):
            val = getattr(self, job_attr, None)
            if isinstance(val, list):
                for j in val:
                    try: self.after_cancel(j)
                    except Exception: pass
            elif val:
                try: self.after_cancel(val)
                except Exception: pass
        # Flush config to disk before exit
        try:
            _save_config(self._config)
        except Exception:
            pass
        try:
            self.master.destroy()
        except Exception:
            pass
        sys.exit(0)

    def _build_ui(self):
        self._theme_widgets = []   # list of (widget, role) for _reapply_styles
        self._all_trees     = []   # all ttk.Treeview instances for zebra re-tag on theme change

        style = ttk.Style(self)
        style.theme_use("clam")
        _apply_scrollbar_style(style)
        self.option_add("*TCombobox*Listbox.background", BG3)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", BG)
        self.option_add("*TCombobox*Listbox.font", "Consolas 10")
        style.configure("TNotebook",     background=BG,  borderwidth=0)
        style.configure("TNotebook.Tab", background=BG3, foreground=MUTED,
                        font=("Consolas", 9, "bold"), padding=[9, 5])
        style.map("TNotebook.Tab",
                  background=[("selected", BG2)],
                  foreground=[("selected", ACCENT)])
        style.configure("Treeview",
                        background=BG3, foreground=FG, fieldbackground=BG3,
                        rowheight=26, font=(MONO_FONT, 9))
        style.configure("Treeview.Heading",
                        background=BG2, foreground=ACCENT,
                        font=(MONO_FONT, 9, "bold"), relief="flat")
        style.map("Treeview", background=[("selected", ACCENT)],
                  foreground=[("selected", BG)])
        style.configure("TCombobox", fieldbackground=BG3, background=BG3,
                        foreground=FG, arrowcolor=ACCENT,
                        selectbackground=BG3, selectforeground=FG,
                        insertcolor=FG, bordercolor=BG3, lightcolor=BG3,
                        darkcolor=BG3)
        style.map("TCombobox",
                  fieldbackground=[("readonly", BG3), ("disabled", BG2), ("!disabled", BG3)],
                  foreground=[("readonly", FG), ("disabled", MUTED), ("!disabled", FG)],
                  background=[("readonly", BG3), ("active", BG3), ("!disabled", BG3)],
                  selectbackground=[("readonly", BG3)],
                  selectforeground=[("readonly", FG)])

        # ── Row 1: telemetry status strip ────────────────────────────────────
        top = tk.Frame(self, bg=BG, pady=0)
        top.pack(fill="x", padx=0)
        self._theme_widgets.append((top, "frame_bg"))

        # Left pill — branding card
        brand_card = tk.Frame(top, bg=BG2, padx=14, pady=6)
        brand_card.pack(side="left", fill="y")
        self._theme_widgets.append((brand_card, "frame_bg2"))
        lbl_title = tk.Label(brand_card, text=f"⬡ VK CONTEST ANALYZER  v{VERSION}",
                 font=(UI_FONT, 13, "bold"), fg=ACCENT, bg=BG2)
        lbl_title.pack(side="left")
        self._theme_widgets.append((lbl_title, "label_accent_bg2"))
        lbl_by = tk.Label(brand_card, text="  by VK2YI",
                 font=(UI_FONT, 9), fg=MUTED, bg=BG2)
        lbl_by.pack(side="left")
        self._theme_widgets.append((lbl_by, "label_muted_bg2"))

        # Thin divider
        tk.Frame(top, bg=BG3, width=1).pack(side="left", fill="y")

        # Centre pill — status text card
        status_card = tk.Frame(top, bg=BG, padx=16, pady=6)
        status_card.pack(side="left", fill="both", expand=True)
        self._theme_widgets.append((status_card, "frame_bg"))
        self.status_var = tk.StringVar(value="No log loaded  —  click  Load .s3db Log  to begin")
        lbl_status = tk.Label(status_card, textvariable=self.status_var,
                 font=(UI_FONT, 9), fg=MUTED, bg=BG, anchor="w")
        lbl_status.pack(side="left", fill="x")
        self._theme_widgets.append((lbl_status, "label_muted_bg"))

        # ── Row 2: all controls ──────────────────────────────────────────────
        ctrl = tk.Frame(self, bg=BG2, pady=4)
        ctrl.pack(fill="x", padx=0)
        self._theme_widgets.append((ctrl, "frame_bg2"))

        # Left cluster: load + switch
        left = tk.Frame(ctrl, bg=BG2)
        left.pack(side="left", padx=(10, 0))
        self._theme_widgets.append((left, "frame_bg2"))
        self._load_btn = self._btn(left, "📂  Load .s3db Log", self._load_file)
        self._load_btn.pack(side="left", padx=(0, 4))
        self._theme_widgets.append((self._load_btn, "btn_primary"))
        self._switch_btn = self._btn(left, "⇄  Switch Contest", self._switch_contest,
                                     style="secondary")
        self._switch_btn.pack(side="left", padx=(0, 0))
        self._theme_widgets.append((self._switch_btn, "btn_secondary"))
        self._switch_btn.config(state="disabled", fg=BG3, cursor="arrow")
        _Tooltip(self._switch_btn,
                 "Re-open the contest picker for the current .s3db file.\n"
                 "Switch to a different contest without reloading the file.")

        # Separator
        sep1 = tk.Frame(ctrl, bg=BG3, width=1)
        sep1.pack(side="left", fill="y", padx=10, pady=3)
        self._theme_widgets.append((sep1, "frame_bg3"))

        # Centre cluster: refresh + countdown + live
        mid = tk.Frame(ctrl, bg=BG2)
        mid.pack(side="left")
        self._theme_widgets.append((mid, "frame_bg2"))
        self._refresh_btn = self._btn(mid, "↺  Refresh Now", self._manual_refresh,
                  style="secondary")
        self._refresh_btn.pack(side="left", padx=(0, 6))
        self._theme_widgets.append((self._refresh_btn, "btn_secondary"))
        lbl_ar = tk.Label(mid, text="Auto-refresh:", font=FONT_B, fg=MUTED, bg=BG2)
        lbl_ar.pack(side="left", padx=(0, 3))
        self._theme_widgets.append((lbl_ar, "label_muted_bg2"))
        self._interval_var = tk.StringVar(value="15 sec")
        interval_cb = ttk.Combobox(mid, textvariable=self._interval_var,
                                   values=["Off", "15 sec", "30 sec", "1 min", "5 min"],
                                   width=7, state="readonly", font=FONT_B)
        interval_cb.pack(side="left", padx=(0, 6))
        interval_cb.bind("<<ComboboxSelected>>", lambda e: self._on_interval_change())
        self._countdown_var = tk.StringVar(value="")
        self._countdown_lbl = tk.Label(mid, textvariable=self._countdown_var,
                 font=FONT_B, fg=ACCENT, bg=BG2, width=8)
        self._countdown_lbl.pack(side="left", padx=(0, 6))
        self._theme_widgets.append((self._countdown_lbl, "label_accent_bg2"))
        self._live_canvas = tk.Canvas(mid, width=62, height=20,
                                      bg=BG2, highlightthickness=0)
        self._live_canvas.pack(side="left", padx=(0, 0))
        self._theme_widgets.append((self._live_canvas, "canvas_bg2"))
        self._live_dot   = self._live_canvas.create_oval(2, 4, 14, 16,
                                                         fill=GREEN, outline="")
        self._live_label = self._live_canvas.create_text(18, 10, text="LIVE",
                                                         anchor="w",
                                                         font=("Consolas", 9, "bold"),
                                                         fill=GREEN)
        self._live_pulse_state = True
        self._pulse_job = None
        self._pulse_live()
        # Spinner bound to the status label — used during heavy refreshes
        self._status_spinner = _SpinnerLabel(lbl_status)

        # Separator
        sep2 = tk.Frame(ctrl, bg=BG3, width=1)
        sep2.pack(side="left", fill="y", padx=10, pady=3)
        self._theme_widgets.append((sep2, "frame_bg3"))

        # Right cluster: theme + on top + help
        right = tk.Frame(ctrl, bg=BG2)
        right.pack(side="left")
        self._theme_widgets.append((right, "frame_bg2"))

        # Theme selector
        lbl_theme = tk.Label(right, text="Theme:", font=FONT_B, fg=MUTED, bg=BG2)
        lbl_theme.pack(side="left", padx=(0, 3))
        self._theme_widgets.append((lbl_theme, "label_muted_bg2"))
        self._theme_var = tk.StringVar(value=_ACTIVE_THEME)
        theme_cb = ttk.Combobox(right, textvariable=self._theme_var,
                                values=THEME_NAMES, width=18,
                                state="readonly", font=FONT_B)
        theme_cb.pack(side="left", padx=(0, 8))
        theme_cb.bind("<<ComboboxSelected>>",
                      lambda e: self._on_theme_change())
        _Tooltip(theme_cb,
                 "Switch colour theme.\n"
                 "Deuteranopia-Safe and Protanopia-Safe palettes use\n"
                 "blue/amber/teal combinations that remain distinguishable\n"
                 "for the most common forms of colour blindness.\n"
                 "High Contrast uses yellow-on-black for maximum legibility.")

        # Separator
        sep3 = tk.Frame(ctrl, bg=BG3, width=1)
        sep3.pack(side="left", fill="y", padx=6, pady=3)
        self._theme_widgets.append((sep3, "frame_bg3"))

        # User-adjustable text zoom — global, affects every tab (matplotlib
        # panels on Overview/Rate/Fatigue/etc. via _panel_fs(), and table
        # tabs via the scaled Treeview row height/font set in
        # _apply_text_zoom_to_trees()). On top of each panel's own
        # automatic size-based scaling. Persisted in vkcontest_config.json
        # under "overview_zoom" (key name kept for backward compatibility
        # with existing config files) so it survives restarts.
        # Range capped at 1.6 (not higher) since dense matplotlib panels
        # (_panel_fs) cap their own effective scale at 1.5 to avoid text
        # overlap.
        self._ov_zoom = max(0.8, min(1.6, float(self._config.get("overview_zoom", 1.0))))
        zoom_frame = tk.Frame(ctrl, bg=BG2)
        zoom_frame.pack(side="left", padx=(0, 0))
        self._theme_widgets.append((zoom_frame, "frame_bg2"))
        tk.Label(zoom_frame, text="🔍 TEXT ZOOM", font=("Consolas", 10, "bold"),
                 fg=ACCENT, bg=BG2).pack(side="left", padx=(0, 6))
        self._ov_zoom_var = tk.DoubleVar(value=self._ov_zoom)
        self._ov_zoom_scale = tk.Scale(
            zoom_frame, variable=self._ov_zoom_var,
            from_=0.8, to=1.6, resolution=0.1, orient="horizontal",
            showvalue=False, length=120, width=14, sliderlength=22,
            bg=BG2, fg=FG, troughcolor=BG3,
            activebackground=GREEN,
            highlightthickness=0, sliderrelief="flat", bd=0,
            font=("Consolas", 9, "bold"),
            command=self._on_overview_zoom_change,
        )
        self._ov_zoom_scale.pack(side="left", padx=(0, 6), pady=2)
        self._ov_zoom_readout = tk.Label(zoom_frame, text=f"{self._ov_zoom:.1f}x",
                                          font=("Consolas", 10, "bold"),
                                          fg=GREEN, bg=BG2, width=4)
        self._ov_zoom_readout.pack(side="left", padx=(0, 4))
        for w in (zoom_frame, self._ov_zoom_scale, self._ov_zoom_readout):
            _Tooltip(w,
                     "Scale text size across every tab — chart panels and\n"
                     "table rows alike. Independent of window size.\n"
                     "Saved automatically.")

        # Mouse wheel over the zoom control adjusts it in 0.1 steps, same
        # increment as a single slider notch — bound only while the cursor
        # is over the zoom box so it doesn't hijack scrolling elsewhere.
        def _on_zoom_wheel(event):
            step = 0.1 if event.delta > 0 else -0.1
            new_val = round(min(1.6, max(0.8, self._ov_zoom + step)), 1)
            self._ov_zoom_var.set(new_val)
            self._on_overview_zoom_change(new_val)
            return "break"
        for w in (zoom_frame, self._ov_zoom_scale, self._ov_zoom_readout):
            w.bind("<Enter>", lambda e: zoom_frame.bind_all("<MouseWheel>", _on_zoom_wheel), add="+")
            w.bind("<Leave>", lambda e: zoom_frame.unbind_all("<MouseWheel>"), add="+")

        sep3b = tk.Frame(ctrl, bg=BG3, width=1)
        sep3b.pack(side="left", fill="y", padx=6, pady=3)
        self._theme_widgets.append((sep3b, "frame_bg3"))

        self._ontop_var = tk.BooleanVar(value=False)
        self._ontop_chk = tk.Checkbutton(right, text="On Top", variable=self._ontop_var,
                       command=self._toggle_on_top,
                       font=("Consolas", 9), fg=MUTED, bg=BG2,
                       activeforeground=ACCENT, activebackground=BG2,
                       selectcolor=BG3, relief="flat", cursor="hand2")
        self._ontop_chk.pack(side="left", padx=(0, 4))
        self._theme_widgets.append((self._ontop_chk, "checkbutton_bg2"))
        self._help_btn = self._btn(right, "?  Help", self._show_help,
                  style="secondary")
        self._help_btn.pack(side="left", padx=(4, 0))
        self._theme_widgets.append((self._help_btn, "btn_secondary"))

        self._plugins_btn = self._btn(right, "🧩  Plugins", self._show_plugins_dialog,
                  style="secondary")
        self._plugins_btn.pack(side="left", padx=(4, 0))
        self._theme_widgets.append((self._plugins_btn, "btn_secondary"))
        _Tooltip(self._plugins_btn,
                 "Show every contest plugin currently recognised and\n"
                 "scored automatically — the same list shown at startup.")

        # ── 📷 Snapshot button ─────────────────────────────────────────────────
        self._snap_btn = self._btn(right, "📷  Snapshot", self._snapshot_current_tab,
                  style="secondary")
        self._snap_btn.pack(side="left", padx=(4, 0))
        self._theme_widgets.append((self._snap_btn, "btn_secondary"))
        _Tooltip(self._snap_btn,
                 "Export the active chart tab as a high-resolution PNG or PDF.\n"
                 "Only available when the current tab contains a Matplotlib figure.")

        # ── ⬇ Export CSV button ────────────────────────────────────────────────
        self._csv_btn = self._btn(right, "⬇  CSV", self._export_active_csv,
                  style="secondary")
        self._csv_btn.pack(side="left", padx=(4, 0))
        self._theme_widgets.append((self._csv_btn, "btn_secondary"))
        _Tooltip(self._csv_btn,
                 "Export the active data grid as a UTF-8 CSV file.\n"
                 "Only available when the current tab contains a data table.")

        self._report_btn = self._btn(right, "🐞  Report", self._show_report_dialog,
                  style="secondary")
        self._report_btn.pack(side="left", padx=(4, 0))
        self._theme_widgets.append((self._report_btn, "btn_secondary"))
        _Tooltip(self._report_btn,
                 "Report a bug or request a feature.\n"
                 "Optionally use AI to polish your report, then\n"
                 "submit it as a pre-filled GitHub issue.")

        # ── 🌍 World Map button ────────────────────────────────────────────────
        self._map_btn = self._btn(right, "🌍  Map", self._show_world_map,
                  style="secondary")
        self._map_btn.pack(side="left", padx=(4, 0))
        self._theme_widgets.append((self._map_btn, "btn_secondary"))
        _Tooltip(self._map_btn,
                 "Pop-out world map showing great-circle paths\n"
                 "to every worked station, colour-coded by band.\n"
                 "Hover over dots for callsign details.\n"
                 "Requires a log to be loaded first.")

        sep4 = tk.Frame(ctrl, bg=BG3, width=1)
        sep4.pack(side="left", fill="y", padx=6, pady=3)
        self._theme_widgets.append((sep4, "frame_bg3"))

        self._tabs_btn = self._btn(right, "⚙  Tabs", self._open_tab_manager,
                  style="secondary")
        self._tabs_btn.pack(side="left", padx=(6, 0))
        self._theme_widgets.append((self._tabs_btn, "btn_secondary"))
        _Tooltip(self._tabs_btn,
                 "Enable or disable individual tabs.\n"
                 "Disabling heavy tabs (Propagation, Replay, Fatigue, YoY)\n"
                 "reduces memory and improves responsiveness.\n"
                 "Disabled tabs are hidden immediately; newly enabled tabs\n"
                 "appear after a restart.")

        # Apply the restored/initial zoom level to table styling now, before
        # any Treeview-based tabs are built — otherwise tables would start
        # at the hard-coded default size and only pick up the saved zoom
        # level after the user nudges the slider.
        self._apply_text_zoom_to_trees()

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._theme_widgets.append((self, "toplevel_bg"))
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        # ── Drag-to-reorder tab support ───────────────────────────────────────
        self._drag_tab_index  = None   # index of tab being dragged
        self.nb.bind("<ButtonPress-1>",   self._tab_drag_start)
        self.nb.bind("<B1-Motion>",       self._tab_drag_motion)
        self.nb.bind("<ButtonRelease-1>", self._tab_drag_end)

        # ── Build only the tabs the user has enabled ──────────────────────────
        # Disabled tabs still get a placeholder Frame (so attr refs never break)
        # but are never added to the notebook and never built.
        # _tabs_built tracks which tabs have had their build_fn called so that
        # _ensure_plugin_tabs() can lazily promote them later if needed.
        self._tabs_built: set = set()

        for tdef in TAB_REGISTRY:
            attr    = tdef["attr"]
            enabled = self._active_tabs.get(attr, tdef["default_on"])
            if enabled:
                frame = self._make_tab(tdef["label"])
            else:
                frame = tk.Frame(self.nb, bg=BG2)   # off-screen placeholder
                self._theme_widgets.append((frame, "frame_bg2"))
            setattr(self, attr, frame)

        for tdef in TAB_REGISTRY:
            attr    = tdef["attr"]
            enabled = self._active_tabs.get(attr, tdef["default_on"])
            if enabled:
                getattr(self, tdef["build_fn"])()
                self._tabs_built.add(attr)

    def _make_tab(self, name):
        f = tk.Frame(self.nb, bg=BG2)
        self.nb.add(f, text=name)
        self._theme_widgets.append((f, "frame_bg2"))
        return f

    def _ensure_plugin_tabs(self) -> None:
        """
        Guarantee that every tab required for the app to function correctly is
        fully built, even if the user had disabled it in the Tab Manager.

        Tabs marked default_on=True in TAB_REGISTRY are considered *required*:
        they host widgets (StringVars, Comboboxes, etc.) that are referenced by
        _update_plugin_ui() and the refresh pipeline regardless of whether the
        tab is visible.  If such a tab was disabled at startup its frame is a
        plain placeholder with no children; we promote it here by:
          1. Adding it to the Notebook (so it is reachable by the refresh code).
          2. Calling its build_fn to create all the expected child widgets.
          3. Recording it in _tabs_built so we never double-build.

        Heavy optional tabs (Propagation, Replay, Fatigue, YoY) are left
        untouched — they are never referenced unconditionally.
        """
        for tdef in TAB_REGISTRY:
            attr = tdef["attr"]
            if attr in self._tabs_built:
                continue                        # already built — nothing to do
            if not tdef["default_on"]:
                continue                        # optional heavy tab — skip
            # Promote the placeholder frame into a real notebook tab
            frame = getattr(self, attr, None)
            if frame is None:
                continue
            try:
                self.nb.add(frame, text=tdef["label"])
            except Exception:
                pass                            # already in notebook somehow
            # Run the build function to populate the frame
            try:
                getattr(self, tdef["build_fn"])()
                self._tabs_built.add(attr)
                # Mark enabled so _refresh_all_views / _on_tab_changed include it
                self._active_tabs[attr] = True
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(
                    "_ensure_plugin_tabs: failed to build %s: %s", attr, exc)

    def _btn(self, parent, text, cmd, style="primary"):
        bg      = ACCENT if style == "primary" else BG3
        fg      = BG     if style == "primary" else FG
        hov_bg  = ACCENT2 if style == "primary" else ACCENT
        hov_fg  = BG
        btn = tk.Button(parent, text=text, command=cmd,
                        font=(UI_FONT, 10, "bold"),
                        bg=bg, fg=fg, relief="flat",
                        activebackground=hov_bg, activeforeground=hov_fg,
                        padx=12, pady=5, cursor="hand2")
        self._hover_bind(btn, bg, fg, hov_bg, hov_fg)
        return btn

    @staticmethod
    def _hover_bind(widget, normal_bg, normal_fg, hover_bg, hover_fg):
        """Attach enter/leave colour-morph hover states to any Tk widget."""
        widget.bind("<Enter>", lambda e: widget.config(bg=hover_bg, fg=hover_fg), add="+")
        widget.bind("<Leave>", lambda e: widget.config(bg=normal_bg, fg=normal_fg), add="+")

    @staticmethod
    def draw_rounded_card(canvas, x1, y1, x2, y2, radius=8, **kwargs):
        """Draw a smooth rounded-rectangle card on a Tkinter Canvas."""
        r = radius
        pts = [
            x1+r, y1,  x1+r, y1,  x2-r, y1,  x2-r, y1,
            x2,   y1,  x2,   y1+r, x2, y1+r,  x2, y2-r,
            x2,   y2-r, x2,  y2,  x2-r, y2,  x2-r, y2,
            x1+r, y2,   x1+r, y2,  x1, y2,   x1, y2-r,
            x1,   y2-r, x1,  y1+r, x1, y1+r, x1, y1,
        ]
        return canvas.create_polygon(pts, smooth=True, **kwargs)

    # ── Dockable panel registry ───────────────────────────────────────────────
    PANEL_KEYS = ["gauges","block","band","heat","bests","value","last","ops","sparks","bars"]
    PANEL_LABELS = {
        "gauges": "Gauges",
        "block":  "Block Status",
        "band":   "Band Efficiency",
        "heat":   "Region Heat",
        "bests":  "Personal Bests",
        "value":  "QSO Value",
        "last":   "Last Worked",
        "ops":    "Operator Times",
        "sparks": "Sparklines",
        "bars":   "Region Completion",
    }

    PANEL_TOOLTIPS = {
        "gauges": "Arc gauges showing QSOs, score, multipliers and completion at a glance.",
        "block":  "Countdown timer for the current contest block. Shows time remaining and which block is active.",
        "band":   "Per-band efficiency: how many new multipliers each band is producing per QSO. Guides where to focus.",
        "heat":   "Region heatmap: QSO density and multiplier completion by state or region.",
        "bests":  "Your best hourly rate, best session, current rate vs previous hour, and zone summary.",
        "value":  "Estimated score gain for ONE more QSO on each band, using that band's average points: "
                  "as a plain fill QSO, with one new multiplier, and (CQWW) with two new multipliers "
                  "(new DXCC AND new zone on the same band).",
        "last":   "The 5 most recent valid QSOs — call, band/mode, and multiplier.",
        "ops":    "Per-operator on-air vs. off-air time, derived from QSO timestamps in the log.",
        "sparks": "Sparkline charts: QSOs per hour, running score, and new multipliers per hour across the contest.",
        "bars":   "Stacked bar chart showing worked vs still-needed multipliers for each region.",
    }

    def _build_overview_tab(self):
        f = self.tab_overview
        f.configure(bg=BG2)
        self.sc_vars    = {}
        self._ov_data   = {}
        self._float_figs = {}
        self._dock_state = {k: {"floated": False, "collapsed": False,
                                "win": None} for k in self.PANEL_KEYS}

        dock_bar = tk.Frame(f, bg=BG3, height=34)
        dock_bar.pack(side="bottom", fill="x", padx=8, pady=(0, 4))
        dock_bar.pack_propagate(False)

        # Text Zoom control now lives in the global top toolbar (see
        # __init__ / the ctrl-row construction, built before tabs) so it's
        # visible and usable from every tab, not just Overview.
        # self._ov_zoom is already set by that point; nothing to build here.
        tk.Label(dock_bar, text=" |", font=("Consolas", 8),
                 fg=BG2, bg=BG3).pack(side="left", padx=(2, 6))

        # Panel toggle list lives in its own horizontally-scrollable strip
        # so it can never crowd out the zoom control above, and remains
        # usable (via scroll/drag) even when the window is narrower than
        # the full list of panel names.
        panel_strip_outer = tk.Frame(dock_bar, bg=BG3)
        panel_strip_outer.pack(side="left", fill="both", expand=True)
        panel_canvas = tk.Canvas(panel_strip_outer, bg=BG3, height=28,
                                  highlightthickness=0, bd=0)
        panel_canvas.pack(side="left", fill="both", expand=True)
        panel_bar = tk.Frame(panel_canvas, bg=BG3)
        panel_canvas_win = panel_canvas.create_window((0, 0), window=panel_bar, anchor="nw")

        def _on_panel_bar_configure(event):
            panel_canvas.configure(scrollregion=panel_canvas.bbox("all"))
        panel_bar.bind("<Configure>", _on_panel_bar_configure)

        def _on_panel_wheel(event):
            delta = -1 if event.delta > 0 else 1
            panel_canvas.xview_scroll(delta, "units")
        panel_canvas.bind("<Enter>", lambda e: panel_canvas.bind_all("<MouseWheel>", _on_panel_wheel))
        panel_canvas.bind("<Leave>", lambda e: panel_canvas.unbind_all("<MouseWheel>"))

        tk.Label(panel_bar, text="Panels:", font=("Consolas", 9, "bold"),
                 fg=MUTED, bg=BG3).pack(side="left", padx=(4, 4))

        for key in self.PANEL_KEYS:
            label   = self.PANEL_LABELS[key]
            tip_txt = self.PANEL_TOOLTIPS[key]
            bf = tk.Frame(panel_bar, bg=BG3)
            bf.pack(side="left", padx=1)
            lbl = tk.Label(bf, text=label, font=("Consolas", 9), fg=FG, bg=BG3)
            lbl.pack(side="left")
            _Tooltip(lbl, tip_txt)
            fb = tk.Label(bf, text="[^]", font=("Consolas", 8),
                          fg=ACCENT, bg=BG3, cursor="hand2")
            fb.pack(side="left", padx=(2,0))
            fb.bind("<Button-1>", lambda e, k=key: self._float_panel(k))
            fb.config(cursor="hand2"); fb.bind("<Enter>",    lambda e, w=fb: w.config(fg=GREEN))
            fb.bind("<Leave>",    lambda e, w=fb: w.config(fg=ACCENT))
            _Tooltip(fb, f"Pop out '{label}' into a floating window.")
            cb = tk.Label(bf, text="[-]", font=("Consolas", 8),
                          fg=MUTED, bg=BG3, cursor="hand2")
            cb.pack(side="left", padx=(1,0))
            cb.bind("<Button-1>", lambda e, k=key: self._toggle_collapse(k))
            cb.config(cursor="hand2"); cb.bind("<Enter>",    lambda e, w=cb: w.config(fg=ACCENT2))
            cb.bind("<Leave>",    lambda e, w=cb: w.config(fg=MUTED))
            _Tooltip(cb, f"Collapse/expand '{label}' in the overview layout.")
            self._dock_state[key]["collapse_btn"] = cb
            tk.Label(panel_bar, text=" |", font=("Consolas", 8),
                     fg=BG2, bg=BG3).pack(side="left")

        # Figure created lazily on first refresh to save startup memory.
        self._ov_fig_frame = tk.Frame(f, bg=BG2)
        self._ov_fig_frame.pack(fill="both", expand=True, padx=8, pady=(4, 0))
        self.fig_overview = None
        self.canvas_ov    = None
        self._ov_fs       = 1.0
        self._ov_resize_job = None
        self._ov_fig_frame.bind("<Configure>", self._on_overview_resize)

    def _on_overview_resize(self, event):
        """Debounced redraw of the overview chart on window/frame resize,
        so panel fonts can be rescaled to fit the new size."""
        if self._ov_resize_job:
            self.after_cancel(self._ov_resize_job)
        self._ov_resize_job = self.after(200, self._on_overview_resize_done)

    def _apply_text_zoom_to_trees(self):
        """
        Scale every ttk.Treeview's row height and font size by the current
        Text Zoom level. Treeview styling is global (one named style shared
        by every table tab — Missing, Worked, Bands, Dupes, Rate's session
        table, etc.), so a single style.configure() call here updates all
        of them at once; no per-tab wiring needed.

        Base values (rowheight=22, font size=9) match what was previously
        hard-coded in the two style.configure("Treeview", ...) call sites
        (initial theme setup and theme-switch re-apply) — this replaces
        the fixed numbers there with zoom-scaled ones.
        """
        try:
            style = ttk.Style(self)
            zoom = getattr(self, "_ov_zoom", 1.0)
            row_h    = max(18, round(26 * zoom))
            font_sz  = max(7,  round(9  * zoom))
            head_sz  = max(7,  round(9  * zoom))
            style.configure("Treeview", rowheight=row_h, font=(MONO_FONT, font_sz))
            style.configure("Treeview.Heading", font=(MONO_FONT, head_sz, "bold"))
        except Exception:
            logging.exception("Failed to apply text zoom to Treeview style")

    def _on_overview_zoom_change(self, value):
        """Slider callback for the user-adjustable global text zoom.
        Debounced the same way as resize, and persisted to config so the
        chosen zoom level survives an app restart."""
        self._ov_zoom = float(value)
        self._config["overview_zoom"] = self._ov_zoom
        if hasattr(self, "_ov_zoom_readout"):
            self._ov_zoom_readout.config(text=f"{self._ov_zoom:.1f}x")
        self._apply_text_zoom_to_trees()
        if self._ov_resize_job:
            self.after_cancel(self._ov_resize_job)
        self._ov_resize_job = self.after(150, self._on_overview_zoom_change_done)

    def _on_overview_zoom_change_done(self):
        self._ov_resize_job = None
        _save_config(self._config)
        # Refresh every matplotlib-backed tab that's already been built,
        # not just Overview — Text Zoom is now a global control, so a
        # currently-visible Rate/Fatigue/Pace/YoY chart should pick up the
        # new scale immediately rather than only on next tab switch.
        if self.log and self.fig_overview is not None:
            self._refresh_overview_chart()
        for fig_attr, refresh_fn in (
            ("fig_rate",     "_refresh_rate"),
            ("fig_fatigue",  "_refresh_fatigue"),
            ("fig_pace",     "_refresh_pace"),
            ("fig_yoy",      "_refresh_yoy"),
        ):
            if self.log and getattr(self, fig_attr, None) is not None \
                    and hasattr(self, refresh_fn):
                try:
                    getattr(self, refresh_fn)()
                except Exception:
                    logging.exception("Failed to refresh %s after zoom change", fig_attr)

    def _on_overview_resize_done(self):
        self._ov_resize_job = None
        if self.log and self.fig_overview is not None:
            self._refresh_overview_chart()

    def _build_missing_tab(self):
        f = self.tab_missing
        f.configure(bg=BG2)
        top = tk.Frame(f, bg=BG2)
        top.pack(fill="x", padx=12, pady=8)
        tk.Label(top, text="Missing Multipliers",
                 font=FONT_H, fg=ACCENT, bg=BG2).pack(side="left")

        self.miss_region_var = tk.StringVar(value="ALL")
        # Region filter combobox — values populated dynamically on load
        self._miss_region_cb = ttk.Combobox(
            top, textvariable=self.miss_region_var,
            values=["ALL"], width=6, state="readonly", font=FONT_B,
        )
        self._miss_region_cb.pack(side="left", padx=20)
        self._miss_region_cb.bind("<<ComboboxSelected>>", lambda e: self._refresh_missing())

        cols = ("Mult Code", "Region", "Status")
        self.miss_tree = ttk.Treeview(f, columns=cols, show="headings", height=28)
        _style_tree(self.miss_tree, self)
        for col, w in zip(cols, [250, 150, 450]):
            self.miss_tree.heading(col, text=col)
            self.miss_tree.column(col, width=w, anchor="w")
        sb = ttk.Scrollbar(f, orient="vertical", command=self.miss_tree.yview)
        self.miss_tree.configure(yscroll=sb.set)
        self.miss_tree.pack(side="left", fill="both", expand=True, padx=(20,0), pady=(0,16))
        sb.pack(side="right", fill="y", pady=(0,16), padx=(0,16))

    def _build_worked_tab(self):
        f = self.tab_worked
        f.configure(bg=BG2)
        toolbar = tk.Frame(f, bg=BG2)
        toolbar.pack(fill="x", padx=12, pady=(8, 2))
        tk.Label(toolbar, text="Worked QSOs", font=FONT_H, fg=ACCENT, bg=BG2).pack(side="left")
        tk.Label(toolbar,
                 text="  |  ⏱ Next Block = when this station can be worked again",
                 font=FONT_S, fg=MUTED, bg=BG2).pack(side="left")
        self._btn(toolbar, "🗑  Delete Selected", self._delete_selected_qso,
                  style="secondary").pack(side="right", padx=4)

        cols = ("Callsign","Band","Mode","Timestamp UTC","Mult","Points","Block","Next Block In")
        self.work_tree = ttk.Treeview(f, columns=cols, show="headings", height=27,
                                      selectmode="extended")
        _style_tree(self.work_tree, self)
        for col, w in zip(cols, [130,70,70,160,150,60,60,110]):
            self.work_tree.heading(col, text=col)
            self.work_tree.column(col, width=w, anchor="center")
        sb = ttk.Scrollbar(f, orient="vertical", command=self.work_tree.yview)
        self.work_tree.configure(yscroll=sb.set)
        self.work_tree.pack(side="left", fill="both", expand=True, padx=(20,0), pady=(0,16))
        sb.pack(side="right", fill="y", pady=(0,16), padx=(0,16))

        self._work_ctx = tk.Menu(self, tearoff=0, bg=BG3, fg=FG,
                                 activebackground=ACCENT, activeforeground=BG, font=FONT_B)
        self._work_ctx.add_command(label="🗑  Delete selected QSO(s)",
                                   command=self._delete_selected_qso)
        self.work_tree.bind("<Button-3>", self._work_tree_right_click)
        self.work_tree.bind("<Delete>",   lambda e: self._delete_selected_qso())
        self._schedule_worked_refresh()

    def _build_rate_tab(self):
        f = self.tab_rate
        f.configure(bg=BG2)
        top = tk.Frame(f, bg=BG2)
        top.pack(fill="x", padx=12, pady=(8, 4))
        # Header text is populated dynamically when a log loads
        self._rate_header_var = tk.StringVar(value="Rate Analysis")
        tk.Label(top, textvariable=self._rate_header_var,
                 font=FONT_H, fg=ACCENT, bg=BG2).pack(side="left")
        self._rate_sub_var = tk.StringVar(value="")
        tk.Label(top, textvariable=self._rate_sub_var,
                 font=FONT_S, fg=MUTED, bg=BG2).pack(side="left", padx=16)

        tbl_frame = tk.Frame(f, bg=BG2)
        tbl_frame.pack(fill="x", padx=12, pady=(0, 6))
        sess_cols = ("Block","Window (UTC)","QSOs","Pts","New Mults","Cum Mults","Running Score")
        self.sess_tree = ttk.Treeview(tbl_frame, columns=sess_cols,
                                      show="headings", height=5)
        _style_tree(self.sess_tree, self)
        for col, w in zip(sess_cols, [60,160,70,70,90,90,120]):
            self.sess_tree.heading(col, text=col)
            self.sess_tree.column(col, width=w, anchor="center")
        self.sess_tree.pack(fill="x", expand=False)

        tk.Label(f, text="QSOs per Hour  (colour = session block)",
                 font=FONT_S, fg=MUTED, bg=BG2).pack(anchor="w", padx=14)
        # Figure created lazily on first refresh to save startup memory.
        self._rate_fig_frame = tk.Frame(f, bg=BG2)
        self._rate_fig_frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        self.fig_rate    = None
        self.ax_rate     = None
        self.canvas_rate = None

    def _build_bands_tab(self):
        f = self.tab_bands
        f.configure(bg=BG2)
        top = tk.Frame(f, bg=BG2)
        top.pack(fill="x", padx=12, pady=8)
        tk.Label(top, text="Band Breakdown", font=FONT_H, fg=ACCENT, bg=BG2).pack(side="left")
        cols = ("Band","Valid Contacts","Duplicate Contacts","Unique Multipliers Secured")
        self.band_tree = ttk.Treeview(f, columns=cols, show="headings", height=25)
        _style_tree(self.band_tree, self)
        for col, w in zip(cols, [150,150,150,250]):
            self.band_tree.heading(col, text=col)
            self.band_tree.column(col, width=w, anchor="center")
        sb = ttk.Scrollbar(f, orient="vertical", command=self.band_tree.yview)
        self.band_tree.configure(yscroll=sb.set)
        self.band_tree.pack(side="left", fill="both", expand=True, padx=(20,0), pady=(0,16))
        sb.pack(side="right", fill="y", pady=(0,16), padx=(0,16))

    def _build_dupes_tab(self):
        f = self.tab_dupes
        f.configure(bg=BG2)
        top = tk.Frame(f, bg=BG2)
        top.pack(fill="x", padx=12, pady=8)
        tk.Label(top, text="Duplicate Contact Checker", font=FONT_H, fg=ACCENT, bg=BG2).pack(side="left")
        cols = ("Callsign","Duplicate Entry Count")
        self.dupe_tree = ttk.Treeview(f, columns=cols, show="headings", height=25)
        _style_tree(self.dupe_tree, self)
        for col, w in zip(cols, [250,150]):
            self.dupe_tree.heading(col, text=col)
            self.dupe_tree.column(col, width=w, anchor="center")
        sb = ttk.Scrollbar(f, orient="vertical", command=self.dupe_tree.yview)
        self.dupe_tree.configure(yscroll=sb.set)
        self.dupe_tree.pack(side="left", fill="both", expand=True, padx=(20,0), pady=(0,16))
        sb.pack(side="right", fill="y", pady=(0,16), padx=(0,16))

    def _build_propagation_tab(self):
        f = self.tab_propagation
        f.configure(bg=BG2)
        top = tk.Frame(f, bg=BG2)
        top.pack(fill="x", padx=12, pady=(8, 2))
        self._prop_title_lbl = tk.Label(
            top, text="Propagation Heatmap \u2014 Mults Worked by Hour (UTC)",
            font=FONT_H, fg=ACCENT, bg=BG2)
        self._prop_title_lbl.pack(side="left")

        leg_frame = tk.Frame(f, bg=BG2)
        leg_frame.pack(fill="x", padx=14, pady=(0, 4))
        tk.Label(leg_frame, text="Colour scale:  ",
                 font=FONT_S, fg=MUTED, bg=BG2).pack(side="left")
        leg_canvas = tk.Canvas(leg_frame, width=160, height=14,
                               bg=BG2, highlightthickness=0)
        leg_canvas.pack(side="left")
        GRAD = THEMES[_ACTIVE_THEME]["PROP_GRAD"]
        step_w = 160 // len(GRAD)
        for gi, col in enumerate(GRAD):
            leg_canvas.create_rectangle(gi*step_w, 0, (gi+1)*step_w, 14,
                                         fill=col, outline="")
        tk.Label(leg_frame, text=" 0", font=("Consolas",8), fg=MUTED, bg=BG2).pack(side="left")
        tk.Label(leg_frame, text="  \u2192 more QSOs",
                 font=("Consolas",8), fg=MUTED, bg=BG2).pack(side="left")
        self._prop_cell_lbl = tk.Label(
            leg_frame,
            text="    |    Cell = QSOs in that region during that UTC hour",
            font=("Consolas",8), fg=MUTED, bg=BG2)
        self._prop_cell_lbl.pack(side="left")

        # Figure created lazily on first refresh to save startup memory.
        self._prop_fig_frame = tk.Frame(f, bg=BG2)
        self._prop_fig_frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        self.fig_prop    = None
        self.ax_prop     = None
        self.canvas_prop = None

    def _build_debug_tab(self):
        f = self.tab_debug
        f.configure(bg=BG2)
        top = tk.Frame(f, bg=BG2)
        top.pack(fill="x", padx=12, pady=8)
        tk.Label(top, text="Multiplier Debug View (per QSO)",
                 font=FONT_H, fg=ACCENT, bg=BG2).pack(side="left")
        cols = ("Callsign","Raw Exchange","Parsed Mult","Source","Band","Time UTC")
        self.debug_tree = ttk.Treeview(f, columns=cols, show="headings", height=26)
        _style_tree(self.debug_tree, self)
        for col, w in zip(cols, [140,140,160,120,80,140]):
            self.debug_tree.heading(col, text=col)
            self.debug_tree.column(col, width=w, anchor="center")
        sb = ttk.Scrollbar(f, orient="vertical", command=self.debug_tree.yview)
        self.debug_tree.configure(yscroll=sb.set)
        self.debug_tree.pack(side="left", fill="both", expand=True, padx=(20,0), pady=(0,16))
        sb.pack(side="right", fill="y", pady=(0,16), padx=(0,16))

    # ── File loading ─────────────────────────────────────────────────────────

    def _load_file(self):
        p = filedialog.askopenfilename(
            filetypes=[("N1MM Log Files","*.s3db"), ("All DBs","*.db;*.sqlite")])
        if not p:
            return
        picker = ContestPickerDialog(self, p)
        self.wait_window(picker)
        if picker.result is None:
            return
        self._db_path    = p
        self._contest_nr, self._plugin = picker.result
        self._manual_refresh()

    def _switch_contest(self):
        """Re-open the contest picker for the already-loaded .s3db file."""
        if not self._db_path:
            return
        picker = ContestPickerDialog(self, self._db_path)
        self.wait_window(picker)
        if picker.result is None:
            return
        self._contest_nr, self._plugin = picker.result
        self._manual_refresh()

    def _manual_refresh(self):
        if not self._db_path:
            return
        self.status_var.set("Synchronizing and reading log file...")
        if hasattr(self, "_status_spinner"):
            self._status_spinner.start("Synchronizing…")
        self._start_poll_queue()
        threading.Thread(target=self._async_load, daemon=True).start()

    def _async_load(self):
        try:
            log = ContestLog(self._db_path,
                             contest_nr=getattr(self, "_contest_nr", None),
                             plugin=getattr(self, "_plugin", None) or GenericPlugin())
            self._result_queue.put(("ok", log))
        except Exception as e:
            logging.exception("Failed to load log")
            self._result_queue.put(("err", str(e)))

    def _start_poll_queue(self):
        """Start (or restart) the load-result poll loop. Called when a load begins."""
        if hasattr(self, "_poll_job") and self._poll_job:
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass
        self._poll_job = self.after(100, self._poll_queue)

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self._result_queue.get_nowait()
                if kind == "ok":
                    self._on_load_success(payload)
                else:
                    self._on_load_failed(payload)
                # Stop polling once we've drained the queue of a result —
                # _start_poll_queue will restart it for the next load.
                self._poll_job = None
                return
        except queue.Empty:
            pass
        # Queue still empty — keep polling while a load is in flight.
        self._poll_job = self.after(100, self._poll_queue)

    def _on_load_success(self, log):
        self.log = log
        qso_count = len(log.qsos)
        fname = os.path.basename(self._db_path)
        if qso_count == 0:
            if hasattr(self, "_status_spinner"):
                self._status_spinner.stop()
            self.status_var.set(
                f"{fname}  [{log.plugin.display_name}]  ⚠  No QSOs"
                f"  (Sync: {datetime.now().strftime('%H:%M:%S')})"
            )
        else:
            self.status_var.set(
                f"{fname}  [{log.plugin.display_name}]"
                f"  (Sync: {datetime.now().strftime('%H:%M:%S')})"
            )
        # Enable Switch Contest now that a db is loaded
        self._switch_btn.config(
            state="normal", fg=FG, cursor="hand2",
            activebackground=ACCENT2, activeforeground=BG,
        )
        # Restart the live-pulse loop now that a log is available
        if not self._pulse_job:
            self._pulse_live()
        # Ensure every default-on tab is built before touching plugin-specific
        # UI elements — guards against tabs the user had disabled in Tab Manager.
        self._ensure_plugin_tabs()
        # Rebuild tab map now that tabs may have changed
        self._build_tab_map()
        # Update dynamic UI elements that depend on the plugin
        self._update_plugin_ui()
        self._refresh_all_views()
        self._reset_countdown()
        # Reclassify any buffered cluster spots against the newly loaded log
        try:
            self._refresh_cluster_spots_classification()
        except Exception:
            pass

    def _update_plugin_ui(self):
        """Adapt tab labels and filter widgets to the loaded plugin."""
        p = self.log.plugin if self.log else GenericPlugin()
        cfg = p.session_config()

        # Rate tab header
        dur_h = cfg.duration_mins // 60
        self._rate_header_var.set(
            f"Rate Analysis  —  {cfg.num_sessions} × {dur_h}-Hour Blocks"
        )
        self._rate_sub_var.set(
            f"DupeType 3: workable once per block per band  |  "
            f"{cfg.num_sessions} blocks × {dur_h}hrs = "
            f"{cfg.num_sessions * dur_h}hrs"
        )

        # Missing tab region filter
        regions = p.region_list()
        if regions:
            filter_values = ["ALL"] + regions
            self._miss_region_cb.configure(values=filter_values, state="readonly")
            self.miss_region_var.set("ALL")
        else:
            self._miss_region_cb.configure(values=["ALL"], state="disabled")
            self.miss_region_var.set("ALL")

        # Show/hide Missing Mults tab
        missing_tab_idx = list(self.nb.tabs()).index(str(self.tab_missing))
        if p.has_missing_tab():
            self.nb.tab(missing_tab_idx, state="normal")
        else:
            self.nb.tab(missing_tab_idx, state="hidden")

    def _on_load_failed(self, err_msg):
        if hasattr(self, "_status_spinner"):
            self._status_spinner.stop()
        self.status_var.set("Sync Failed")
        messagebox.showerror("Error", err_msg)

    def _on_interval_change(self):
        val = self._interval_var.get()
        self._auto_interval_ms = (
            0 if val == "Off"
            else int(val.split()[0]) * (60000 if "min" in val else 1000)
        )
        if self._auto_refresh_job:
            self.after_cancel(self._auto_refresh_job)
        if self._auto_interval_ms > 0:
            self._reset_countdown()
        else:
            self._countdown_var.set("")

    # ─────────────────────────────────────────────────────────────────────────
    # ── Tab drag-to-reorder ───────────────────────────────────────────────────
    # ─────────────────────────────────────────────────────────────────────────

    def _tab_drag_start(self, event):
        """Record which tab the user pressed on (if any)."""
        try:
            idx = self.nb.index(f"@{event.x},{event.y}")
            self._drag_tab_index = idx
        except tk.TclError:
            self._drag_tab_index = None

    def _tab_drag_motion(self, event):
        """Move the dragged tab left/right as the cursor moves."""
        if self._drag_tab_index is None:
            return
        try:
            target = self.nb.index(f"@{event.x},{event.y}")
        except tk.TclError:
            return
        if target == self._drag_tab_index:
            return
        # Swap the tab at current position with the target position
        tab_id = self.nb.tabs()[self._drag_tab_index]
        self.nb.insert(target, tab_id)
        self._drag_tab_index = target

    def _tab_drag_end(self, event):
        """Persist the new tab order to config."""
        self._drag_tab_index = None
        try:
            order = [self.nb.tab(t, "text") for t in self.nb.tabs()]
            self._config["tab_order"] = order
            _save_config(self._config)
        except Exception:
            pass

    def _build_tab_map(self):
        """Build (or rebuild) the frame→refresh_fn mapping. Called after load and tab changes."""
        tab_map = {}
        for tdef in TAB_REGISTRY:
            if not (self._active_tabs.get(tdef["attr"], tdef["default_on"])
                    or tdef["attr"] in getattr(self, "_tabs_built", set())):
                continue
            frame = getattr(self, tdef["attr"], None)
            if frame is None:
                continue
            fn = getattr(self, tdef["refresh_fn"], None)
            if fn:
                tab_map[str(frame)] = fn
        try:
            tab_map.setdefault(str(self.tab_missing), self._refresh_missing)
        except Exception:
            pass
        self._tab_map = tab_map


    # ── Smart export ─────────────────────────────────────────────────────────

    # Map from tab attr name → (figure_attr, canvas_attr, suggested_stem)
    _TAB_FIG_MAP = {
        "tab_overview":  ("fig_overview",  "canvas_ov",      "overview"),
        "tab_rate":      ("fig_rate",       "canvas_rate",    "rate"),
        "tab_replay":    ("fig_replay",     "canvas_replay",  "replay"),
        "tab_fatigue":   ("fig_fatigue",    "canvas_fatigue", "fatigue"),
        "tab_yoy":       ("fig_yoy",        "canvas_yoy",     "yoy"),
        "tab_pace":      ("fig_pace",       "canvas_pace",    "pace"),
    }
    # Map from tab attr name → (tree_attr, suggested_stem)
    _TAB_TREE_MAP = {
        "tab_missing":  ("miss_tree",        "missing_mults"),
        "tab_worked":   ("work_tree",        "worked_qsos"),
        "tab_rate":     ("sess_tree",        "sessions"),
        "tab_bands":    ("band_tree",        "band_breakdown"),
        "tab_dupes":    ("dupe_tree",        "dupes"),
        "tab_debug":    ("debug_tree",       "debug_log"),
        "tab_fatigue":  ("_fatigue_roster",  "fatigue_roster"),
        "tab_yoy":      ("_yoy_roster",      "yoy_roster"),
        "tab_pace":     ("_pace_roster",     "pace_targets"),
        "tab_cluster":  ("_cluster_tree",    "cluster_spots"),
    }

    def _active_tab_attr(self):
        """Return the attribute name of the currently visible notebook tab, or None."""
        try:
            tab_frame = self.nb.nametowidget(self.nb.select())
        except Exception:
            return None
        for tdef in TAB_REGISTRY:
            attr = tdef["attr"]
            if getattr(self, attr, None) is tab_frame:
                return attr
        return None

    def _snapshot_current_tab(self):
        """
        Export the current tab's Matplotlib figure as a high-resolution PNG or PDF.
        Shows a save-as dialog; writes at 150 DPI with the active theme background.
        """
        attr = self._active_tab_attr()
        if attr is None:
            messagebox.showinfo("Snapshot", "No active tab detected.", parent=self)
            return

        fig_info = self._TAB_FIG_MAP.get(attr)
        if fig_info is None:
            messagebox.showinfo(
                "Snapshot",
                "The active tab does not contain a Matplotlib chart.\n"
                "Switch to Overview, Rate, Replay, Fatigue, YoY, or Pace to snapshot.",
                parent=self,
            )
            return

        fig_attr, _, stem = fig_info
        fig = getattr(self, fig_attr, None)
        if fig is None:
            messagebox.showinfo(
                "Snapshot",
                "Chart not yet rendered — open the tab first.",
                parent=self,
            )
            return

        path = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".png",
            filetypes=[
                ("PNG image", "*.png"),
                ("PDF vector", "*.pdf"),
                ("SVG vector", "*.svg"),
                ("All files", "*.*"),
            ],
            initialfile=f"vkcontest_{stem}.png",
            title="Save chart snapshot",
        )
        if not path:
            return

        try:
            fig.savefig(
                path,
                dpi=150,
                facecolor=fig.get_facecolor(),
                edgecolor="none",
                bbox_inches="tight",
            )
            _flash_success(self._snap_btn, "✔ Saved!", duration_ms=2500,
                           ok_fg=GREEN, orig_text="📷  Snapshot", orig_fg=MUTED)
        except Exception as exc:
            messagebox.showerror("Snapshot failed", str(exc), parent=self)

    def _export_active_csv(self):
        """
        Export the focused data-grid Treeview on the current tab to a CSV file.
        Falls back gracefully when the tab has no exportable Treeview.
        """
        attr = self._active_tab_attr()
        if attr is None:
            messagebox.showinfo("Export CSV", "No active tab detected.", parent=self)
            return

        tree_info = self._TAB_TREE_MAP.get(attr)
        if tree_info is None:
            messagebox.showinfo(
                "Export CSV",
                "The active tab does not contain an exportable data grid.",
                parent=self,
            )
            return

        tree_attr, stem = tree_info
        tree = getattr(self, tree_attr, None)
        if tree is None:
            messagebox.showinfo(
                "Export CSV",
                "Data grid not yet built — open the tab first.",
                parent=self,
            )
            return

        ok = _export_tree_to_csv(tree, self, suggested_name=f"vkcontest_{stem}.csv")
        if ok:
            _flash_success(self._csv_btn, "✔ Saved!", duration_ms=2500,
                           ok_fg=GREEN, orig_text="⬇  CSV", orig_fg=MUTED)

    @staticmethod
    def _flash_tree_rows(tree, iids, flash_fg=None, flash_bg=None,
                         duration_ms=800):
        """
        Briefly highlight a set of Treeview rows in the accent colour, then
        revert.  Used as a micro-interaction after data updates.
        """
        if flash_bg is None:
            flash_bg = ACCENT
        if flash_fg is None:
            flash_fg = BG
        # Apply flash tag
        tree.tag_configure("_flash", background=flash_bg, foreground=flash_fg)
        for iid in iids:
            existing = list(tree.item(iid, "tags"))
            tree.item(iid, tags=existing + ["_flash"])

        def _restore():
            for iid in iids:
                tags = [t for t in tree.item(iid, "tags") if t != "_flash"]
                tree.item(iid, tags=tags)
        tree.after(duration_ms, _restore)

    def _on_tab_changed(self, event=None):
        """Refresh the newly selected tab — but only if its data is stale."""
        try:
            self._last_active_tab = str(self.nb.select())
        except Exception:
            pass
        if not self.log:
            return
        try:
            active_frame = str(self.nb.select())
        except Exception:
            return
        # Use cached tab_map (rebuilt by _on_load_success and _apply_tab_visibility)
        tab_map = getattr(self, "_tab_map", None)
        if tab_map is None:
            self._build_tab_map()
            tab_map = self._tab_map
        fn = tab_map.get(active_frame)
        if fn:
            dirty = getattr(self, "_tab_dirty", {})
            if dirty.get(active_frame, True):
                def _do():
                    fn()
                    dirty[active_frame] = False
                self.after(10, _do)

    def _on_window_configure(self, event):
        """
        Detect a genuine window size/state change (e.g. double-click
        titlebar maximize/restore, or dragging to a different monitor)
        as opposed to routine internal widget layout churn, and guard
        against a Tk/ttk-on-Windows quirk where that transition can
        silently switch the active Notebook tab.
        """
        if event.widget is not self:
            return
        try:
            sig = (event.width, event.height, self.state())
        except Exception:
            return
        if sig == getattr(self, "_last_win_sig", None):
            return
        self._last_win_sig = sig
        if self._win_resize_job:
            self.after_cancel(self._win_resize_job)
        self._win_resize_job = self.after(120, self._restore_active_tab_if_drifted)

    def _restore_active_tab_if_drifted(self):
        self._win_resize_job = None
        target = self._last_active_tab
        if not target:
            return
        try:
            current = str(self.nb.select())
        except Exception:
            return
        if current != target and target in self.nb.tabs():
            self.nb.select(target)

    def _reset_countdown(self):
        if self._auto_interval_ms <= 0:
            return
        self._countdown_remaining = self._auto_interval_ms // 1000
        if self._auto_refresh_job:
            self.after_cancel(self._auto_refresh_job)
        self._tick_countdown()

    def _tick_countdown(self):
        if self._auto_interval_ms <= 0:
            return
        if self._countdown_remaining <= 0:
            self._countdown_var.set("⏱ Syncing")
            self._manual_refresh()
        else:
            self._countdown_var.set(f"⏱ {self._countdown_remaining}s")
            self._countdown_remaining -= 1
            self._auto_refresh_job = self.after(1000, self._tick_countdown)

    # ── Docking helpers ───────────────────────────────────────────────────────

    def _float_panel(self, key):
        state = self._dock_state[key]
        if state["floated"] and state["win"] and state["win"].winfo_exists():
            state["win"].lift(); return

        label = self.PANEL_LABELS[key]
        win = tk.Toplevel(self)
        win.title(f"{label}  —  VK Contest Analyzer")
        win.configure(bg=BG2)
        win.attributes("-topmost", self._ontop_var.get())

        sizes = {
            "gauges":(1100,280), "block":(340,340),
            "band":  (380,280),  "heat": (420,300),
            "bests": (340,280),  "last": (340,300),
            "ops":   (360,300),  "value": (380,300),
            "sparks":(900,180),  "bars": (900,260),
        }
        fw, fh = sizes.get(key, (500,320))
        self.update_idletasks()
        mx = self.winfo_rootx() + self.winfo_width()  // 2
        my = self.winfo_rooty() + self.winfo_height() // 2
        win.geometry(f"{fw}x{fh}+{mx-fw//2}+{my-fh//2}")

        top = tk.Frame(win, bg=BG3, height=24)
        top.pack(fill="x"); top.pack_propagate(False)
        tk.Label(top, text=label, font=("Consolas",9,"bold"),
                 fg=ACCENT, bg=BG3).pack(side="left", padx=8)
        dock_btn = tk.Label(top, text="[dock back]", font=("Consolas",8),
                            fg=MUTED, bg=BG3, cursor="hand2")
        dock_btn.pack(side="right", padx=8)
        dock_btn.bind("<Button-1>", lambda e, k=key: self._dock_panel_back(k))
        dock_btn.config(cursor="hand2")
        dock_btn.bind("<Enter>",    lambda e, w=dock_btn: w.config(fg=ACCENT))
        dock_btn.bind("<Leave>",    lambda e, w=dock_btn: w.config(fg=MUTED))

        fig = Figure(figsize=(fw/96, fh/96), facecolor=BG2)
        canvas = FigureCanvasTkAgg(fig, master=win)
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=(2,4))

        state["floated"] = True; state["win"] = win
        self._float_figs[key] = (fig, canvas)

        if hasattr(self, "_ov_data") and self._ov_data:
            self._draw_float_panel(key)

        win.protocol("WM_DELETE_WINDOW", lambda k=key: self._dock_panel_back(k))
        self._dock_state[key]["collapse_btn"].config(text=" –")
        if self.log:
            self._refresh_overview_chart()

    def _dock_panel_back(self, key):
        state = self._dock_state[key]
        if state["win"] and state["win"].winfo_exists():
            state["win"].destroy()
        state["win"] = None; state["floated"] = False
        if key in self._float_figs:
            del self._float_figs[key]
        if self.log:
            self._refresh_overview_chart()

    def _toggle_collapse(self, key):
        state = self._dock_state[key]
        if state["floated"]:
            return
        state["collapsed"] = not state["collapsed"]
        btn = state.get("collapse_btn")
        if btn:
            btn.config(text=" +" if state["collapsed"] else " –")
        if self.log:
            self._refresh_overview_chart()

    def _draw_float_panel(self, key):
        if key not in self._float_figs:
            return
        d = getattr(self, "_ov_data", {})
        if not d:
            return
        fig, canvas = self._float_figs[key]
        fig.clear()

        w_in, h_in = fig.get_size_inches()
        fs = self._combined_font_scale(w_in * fig.dpi, h_in * fig.dpi)
        self._ov_fs = fs

        def panel_style(ax, title):
            ax.set_facecolor(BG3)
            for spine in ax.spines.values(): spine.set_edgecolor(BG2)
            ax.tick_params(colors=MUTED, labelsize=7.5*fs)
            ax.set_title(title, color=ACCENT, fontfamily="monospace",
                         fontsize=8*fs, fontweight="bold", pad=4)

        total_mults = len(self.log.plugin.mult_list()) if self.log else 0

        if key == "gauges":
            self._draw_gauges_on_fig(fig, d, total_mults)
        elif key == "sparks":
            gs_s = fig.add_gridspec(1, 3, wspace=0.06,
                                    left=0.02, right=0.98, top=0.88, bottom=0.20)
            self._draw_sparklines_on_gridspec(fig, gs_s, d)
        elif key == "bars":
            ax = fig.add_subplot(111)
            ax.set_facecolor(BG2)
            self._draw_region_bars_on_ax(ax, d)
        elif key == "block":
            ax = fig.add_subplot(111)
            ax.set_aspect("equal", adjustable="box")
            ax.set_xlim(-1.6, 1.6); ax.set_ylim(-1.0, 1.5)
            ax.axis("off"); ax.set_facecolor(BG3)
            self._draw_block_status_on_ax(ax, d)
        elif key == "band":
            ax = fig.add_subplot(111)
            panel_style(ax, "[ ~ ]  BAND EFFICIENCY")
            self._draw_band_efficiency_on_ax(ax, d)
        elif key == "heat":
            ax = fig.add_subplot(111)
            panel_style(ax, "[ # ]  REGION HEAT")
            self._draw_region_heat_on_ax(ax, d)
        elif key == "bests":
            ax = fig.add_subplot(111)
            panel_style(ax, "[ * ]  PERSONAL BESTS")
            ax.axis("off"); ax.set_xlim(0,1); ax.set_ylim(0,1)
            self._draw_personal_bests_on_ax(ax, d)
        elif key == "value":
            ax = fig.add_subplot(111)
            panel_style(ax, "[ $ ]  QSO VALUE")
            ax.axis("off"); ax.set_xlim(0,1); ax.set_ylim(0,1)
            self._draw_qso_value_on_ax(ax, d)
        elif key == "last":
            ax = fig.add_subplot(111)
            panel_style(ax, "[ » ]  LAST WORKED")
            ax.axis("off"); ax.set_xlim(0,1); ax.set_ylim(0,1)
            self._draw_last_worked_on_ax(ax, d)
        elif key == "ops":
            ax = fig.add_subplot(111)
            panel_style(ax, "[ O ]  OPERATOR TIMES")
            ax.axis("off"); ax.set_xlim(0,1); ax.set_ylim(0,1)
            self._draw_operator_times_on_ax(ax, d)

        fig.patch.set_facecolor(BG2)
        fig.tight_layout(pad=0.8)
        canvas.draw_idle()
        self.attributes("-topmost", self._ontop_var.get())

    def _toggle_on_top(self):
        self.attributes("-topmost", self._ontop_var.get())

    def _on_theme_change(self):
        """Apply newly selected theme and redraw everything."""
        global _prev_theme_name
        name = self._theme_var.get()
        _prev_theme_name = _ACTIVE_THEME   # snapshot before applying
        _apply_theme(name)
        _save_theme(name)
        self._prop_cmap_theme = None  # invalidate colormap cache on theme change
        self._reapply_styles()
        if self.log:
            self._refresh_all_views()

    @staticmethod
    def _normalise_tk_colour(val: str) -> str:
        """
        Tkinter on Windows returns colours from cget() as 12-digit hex strings
        of the form '#rrrrggggbbbb' (each channel expanded to 16 bits).
        Normalise these back to the standard 6-digit '#rrggbb' form so they
        match the hex literals stored in the THEMES dict.
        """
        if isinstance(val, str) and val.startswith("#") and len(val) == 13:
            # '#rrrrggggbbbb' → take the high byte of each channel
            r = val[1:3]
            g = val[5:7]
            b = val[9:11]
            return f"#{r}{g}{b}".lower()
        return val.lower() if isinstance(val, str) else val

    def _remap_widget_colours(self, widget, colour_map: dict):
        """
        Recursively walk the widget tree.  For each tk widget, remap any
        bg/fg/foreground/background that matches an old-theme hex value.
        Uses cget() so it works on every widget regardless of where it was made.
        Skips ttk widgets (handled by style engine) and matplotlib canvases.

        Note: tkinter on Windows expands #rrggbb to #rrrrggggbbbb in cget()
        output; _normalise_tk_colour() converts it back before lookup.
        """
        cls = widget.__class__.__name__
        # Skip ttk and matplotlib widgets — they have their own styling
        if cls.startswith("T") and cls not in ("Text",):
            for child in widget.winfo_children():
                self._remap_widget_colours(child, colour_map)
            return
        if "FigureCanvasTkAgg" in str(type(widget)):
            return

        # Attributes to check per widget type
        attrs_bg  = ("bg", "background")
        attrs_fg  = ("fg", "foreground")
        attrs_sel = ("selectcolor", "activebackground", "activeforeground",
                     "selectbackground", "selectforeground", "highlightbackground",
                     "troughcolor", "insertbackground", "disabledforeground")

        for attr in attrs_bg + attrs_fg + attrs_sel:
            try:
                val = widget.cget(attr)
                if not isinstance(val, str):
                    continue
                normalised = self._normalise_tk_colour(val)
                mapped = colour_map.get(normalised)
                if mapped:
                    widget.configure(**{attr: mapped})
            except Exception:
                pass

        for child in widget.winfo_children():
            self._remap_widget_colours(child, colour_map)

    def _reapply_styles(self):
        """
        Re-push all colour settings after a theme swap.
        Uses the _theme_widgets registry for precise, role-based repainting.
        """
        # ── ttk styles ───────────────────────────────────────────────────────
        style = ttk.Style(self)
        _apply_scrollbar_style(style)
        self.option_add("*TCombobox*Listbox.background", BG3)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", BG)
        style.configure("TNotebook",     background=BG,  borderwidth=0)
        style.configure("TNotebook.Tab", background=BG3, foreground=MUTED,
                        font=("Consolas", 9, "bold"), padding=[9, 5])
        style.map("TNotebook.Tab",
                  background=[("selected", BG2)],
                  foreground=[("selected", ACCENT)])
        style.configure("Treeview",
                        background=BG3, foreground=FG, fieldbackground=BG3,
                        rowheight=26, font=(MONO_FONT, 9))
        style.configure("Treeview.Heading",
                        background=BG2, foreground=ACCENT,
                        font=(MONO_FONT, 9, "bold"), relief="flat")
        style.map("Treeview", background=[("selected", ACCENT)],
                  foreground=[("selected", BG)])
        # Refresh zebra tag colours to match new theme
        for tree in getattr(self, "_all_trees", []):
            try:
                tree.tag_configure("odd",  background=_ZEBRA_ODD)
                tree.tag_configure("even", background="")
            except Exception:
                pass
        style.configure("TCombobox", fieldbackground=BG3, background=BG3,
                        foreground=FG, arrowcolor=ACCENT,
                        selectbackground=BG3, selectforeground=FG,
                        insertcolor=FG, bordercolor=BG3, lightcolor=BG3,
                        darkcolor=BG3)
        style.map("TCombobox",
                  fieldbackground=[("readonly", BG3), ("disabled", BG2), ("!disabled", BG3)],
                  foreground=[("readonly", FG), ("disabled", MUTED), ("!disabled", FG)],
                  background=[("readonly", BG3), ("active", BG3), ("!disabled", BG3)],
                  selectbackground=[("readonly", BG3)],
                  selectforeground=[("readonly", FG)])

        # ── tk widgets via role registry ─────────────────────────────────────
        for widget, role in self._theme_widgets:
            try:
                if not widget.winfo_exists():
                    continue
                if role == "toplevel_bg":
                    widget.configure(bg=BG)
                elif role == "frame_bg":
                    widget.configure(bg=BG)
                elif role == "frame_bg2":
                    widget.configure(bg=BG2)
                elif role == "frame_bg3":
                    widget.configure(bg=BG3)
                elif role == "label_accent_bg":
                    widget.configure(fg=ACCENT, bg=BG)
                elif role == "label_accent_bg2":
                    widget.configure(fg=ACCENT, bg=BG2)
                elif role == "label_muted_bg":
                    widget.configure(fg=MUTED, bg=BG)
                elif role == "label_muted_bg2":
                    widget.configure(fg=MUTED, bg=BG2)
                elif role == "label_fg_bg2":
                    widget.configure(fg=FG, bg=BG2)
                elif role == "canvas_bg2":
                    widget.configure(bg=BG2)
                elif role == "btn_primary":
                    widget.configure(bg=ACCENT, fg=BG,
                                     activebackground=ACCENT2, activeforeground=BG)
                elif role == "btn_secondary":
                    widget.configure(bg=BG3, fg=FG,
                                     activebackground=ACCENT2, activeforeground=BG)
                elif role == "checkbutton_bg2":
                    widget.configure(bg=BG2, fg=MUTED, selectcolor=BG3,
                                     activeforeground=ACCENT, activebackground=BG2)
            except Exception:
                pass

        # ── Switch Contest button: keep disabled style correct ───────────────
        try:
            if self._switch_btn.cget("state") == "disabled":
                self._switch_btn.configure(fg=BG3)
            else:
                self._switch_btn.configure(fg=FG,
                                           activebackground=ACCENT2, activeforeground=BG)
        except Exception:
            pass

        # ── Live dot/label canvas items ──────────────────────────────────────
        try:
            self._live_canvas.configure(bg=BG2)
        except Exception:
            pass

        # ── Matplotlib figure backgrounds ─────────────────────────────────────
        for fig_attr in ("fig_overview", "fig_rate", "fig_prop", "fig_replay", "fig_fatigue", "fig_yoy", "fig_pace"):
            fig = getattr(self, fig_attr, None)
            if fig:
                try:
                    fig.patch.set_facecolor(BG2)
                except Exception:
                    pass

        # ── Full recursive colour-map walk for all remaining widgets ──────────
        # Build a lookup from the *previous* theme's colour values to new ones.
        # Because every widget was constructed with one of these exact hex strings,
        # matching on cget() values is reliable and covers all tab content.
        prev_theme = THEMES.get(_prev_theme_name, THEMES["Dark (Default)"])
        old_bg_map = {
            prev_theme["BG"].lower():      BG,
            prev_theme["BG2"].lower():     BG2,
            prev_theme["BG3"].lower():     BG3,
            prev_theme["ACCENT"].lower():  ACCENT,
            prev_theme["ACCENT2"].lower(): ACCENT2,
            prev_theme["ACCENT3"].lower(): ACCENT3,
            prev_theme["GREEN"].lower():   GREEN,
            prev_theme["RED"].lower():     RED,
            prev_theme["MUTED"].lower():   MUTED,
            prev_theme["FG"].lower():      FG,
        }
        self._remap_widget_colours(self, old_bg_map)
        # Theme switch resets Treeview rowheight/font to hard-coded
        # defaults above — re-apply the active zoom level on top so
        # switching themes doesn't silently reset table text size.
        self._apply_text_zoom_to_trees()
        # Flush all pending geometry/paint operations so every widget
        # visually updates in the same frame as the colour change.
        self.update_idletasks()

    # ─────────────────────────────────────────────────────────────────────────
    # ── Tab Manager ──────────────────────────────────────────────────────────
    # ─────────────────────────────────────────────────────────────────────────

    def _open_tab_manager(self):
        dlg = tk.Toplevel(self)
        dlg.title("Tab Manager  —  VK Contest Analyzer")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.attributes("-alpha", 0.0)
        dlg.grab_set()
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.update_idletasks()
        pw, ph = self.winfo_width(), self.winfo_height()
        px, py = self.winfo_rootx(), self.winfo_rooty()
        dw, dh = 540, 580
        dlg.geometry(f"{dw}x{dh}+{px+(pw-dw)//2}+{py+(ph-dh)//2}")
        _fade_in(dlg, target_alpha=0.98)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(dlg, bg=BG3, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⚙  Tab Manager",
                 font=("Consolas", 13, "bold"), fg=ACCENT, bg=BG3
                 ).pack(side="left", padx=18)
        tk.Label(hdr, text="Disable heavy tabs to reduce memory & improve responsiveness.",
                 font=FONT_S, fg=MUTED, bg=BG3
                 ).pack(side="left", padx=(0, 18))

        # ── Legend ────────────────────────────────────────────────────────────
        leg = tk.Frame(dlg, bg=BG, pady=4)
        leg.pack(fill="x", padx=18, pady=(6, 0))
        tk.Label(leg, text="🟡  Heavy tab — matplotlib figure, slow to render",
                 font=FONT_S, fg=MUTED, bg=BG).pack(anchor="w")
        tk.Label(leg, text="🟢  Light tab — data only, fast render",
                 font=FONT_S, fg=MUTED, bg=BG).pack(anchor="w")

        tk.Frame(dlg, bg=BG3, height=1).pack(fill="x", padx=18, pady=(6, 0))

        # ── Scrollable tab rows ───────────────────────────────────────────────
        outer = tk.Canvas(dlg, bg=BG, highlightthickness=0, bd=0)
        sb    = ttk.Scrollbar(dlg, orient="vertical", command=outer.yview)
        outer.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, 4), pady=4)
        outer.pack(fill="both", expand=True, padx=(18, 0), pady=4)
        inner = tk.Frame(outer, bg=BG)
        win_id = outer.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: (
            outer.configure(scrollregion=outer.bbox("all")),
            outer.itemconfig(win_id, width=outer.winfo_width()),
        ))
        outer.bind("<Configure>", lambda e: outer.itemconfig(win_id, width=e.width))

        # ── Mouse-wheel scroll anywhere in the dialog ─────────────────────────
        def _on_mousewheel(event):
            if event.num == 4:
                outer.yview_scroll(-1, "units")
            elif event.num == 5:
                outer.yview_scroll(1, "units")
            else:
                outer.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _bind_mousewheel(widget):
            widget.bind("<MouseWheel>", _on_mousewheel, add="+")
            widget.bind("<Button-4>",   _on_mousewheel, add="+")
            widget.bind("<Button-5>",   _on_mousewheel, add="+")
            for child in widget.winfo_children():
                _bind_mousewheel(child)

        for w in (dlg, outer, inner):
            _bind_mousewheel(w)
        # Re-bind after rows are added so all child widgets are covered
        dlg._bind_mousewheel = _bind_mousewheel
        dlg._scroll_inner    = inner

        check_vars = {}
        for tdef in TAB_REGISTRY:
            attr    = tdef["attr"]
            heavy   = tdef["heavy"]
            current = self._active_tabs.get(attr, tdef["default_on"])

            var = tk.BooleanVar(value=current)
            check_vars[attr] = var

            row_bg = BG2 if heavy else BG
            row = tk.Frame(inner, bg=row_bg, pady=6)
            row.pack(fill="x", pady=2, padx=4)

            # Colour dot
            dot_col = "#f0c040" if heavy else "#2ed573"
            tk.Label(row, text="●", font=("Consolas", 11),
                     fg=dot_col, bg=row_bg).pack(side="left", padx=(8, 2))

            # Checkbox
            tk.Checkbutton(row, variable=var,
                           font=("Consolas", 10, "bold"),
                           fg=FG, bg=row_bg,
                           activeforeground=ACCENT, activebackground=row_bg,
                           selectcolor=BG3, relief="flat",
                           cursor="hand2").pack(side="left")

            # Tab emoji + name
            tk.Label(row, text=tdef["label"],
                     font=("Consolas", 10, "bold"),
                     fg=FG, bg=row_bg).pack(side="left", padx=(0, 10))

            # Description
            tip = _TAB_TOOLTIPS.get(attr, "")
            if tip:
                tk.Label(row, text=tip, font=FONT_S, fg=MUTED,
                         bg=row_bg, wraplength=240,
                         justify="left").pack(side="left")

            # HEAVY badge
            if heavy:
                tk.Label(row, text="HEAVY",
                         font=("Consolas", 7, "bold"),
                         fg="#f0c040", bg=row_bg).pack(side="right", padx=8)

        tk.Frame(dlg, bg=BG3, height=1).pack(fill="x", padx=18, pady=(4, 0))

        # Re-bind mousewheel to all newly created row widgets
        dlg._bind_mousewheel(dlg._scroll_inner)

        # ── Restart notice ────────────────────────────────────────────────────
        note = tk.Frame(dlg, bg=BG, pady=6)
        note.pack(fill="x", padx=18)
        tk.Label(note,
                 text="ℹ  Changes take effect immediately — no restart required.",
                 font=FONT_S, fg=MUTED, bg=BG,
                 wraplength=460, justify="left").pack(anchor="w")
        tk.Label(note,
                 text="   Newly enabled tabs will be built and added to the notebook on the fly.",
                 font=FONT_S, fg=MUTED, bg=BG,
                 wraplength=460, justify="left").pack(anchor="w")

        # ── Buttons ───────────────────────────────────────────────────────────
        def _apply():
            changed = False
            for tdef in TAB_REGISTRY:
                a   = tdef["attr"]
                new = check_vars[a].get()
                if self._active_tabs.get(a, tdef["default_on"]) != new:
                    changed = True
                self._active_tabs[a] = new
            if changed:
                self._config["active_tabs"] = self._active_tabs
                _save_config(self._config)
                self._apply_tab_visibility()
            dlg.destroy()

        def _reset():
            for tdef in TAB_REGISTRY:
                check_vars[tdef["attr"]].set(tdef["default_on"])

        btn_row = tk.Frame(dlg, bg=BG, pady=8)
        btn_row.pack(fill="x", padx=18)
        self._btn(btn_row, "✔  Apply & Close", _apply).pack(side="right", padx=(4, 0))
        self._btn(btn_row, "↺  Defaults", _reset, style="secondary").pack(side="right")

    def _apply_tab_visibility(self):
        """
        Immediately show or hide tabs.
        Tabs that were never built are constructed on-the-fly — no restart needed.
        """
        nb_tabs = list(self.nb.tabs())

        for tdef in TAB_REGISTRY:
            attr    = tdef["attr"]
            enabled = self._active_tabs.get(attr, tdef["default_on"])
            frame   = getattr(self, attr, None)
            if frame is None:
                continue
            frame_id = str(frame)
            in_nb    = frame_id in nb_tabs

            if enabled:
                was_built = bool(frame.winfo_children())
                if not was_built:
                    # Build the tab on-the-fly — same path as _ensure_plugin_tabs
                    try:
                        if not in_nb:
                            self.nb.add(frame, text=tdef["label"])
                        getattr(self, tdef["build_fn"])()
                        self._tabs_built.add(attr)
                    except Exception as exc:
                        logging.warning("_apply_tab_visibility: failed to build %s: %s", attr, exc)
                        continue
                    in_nb = str(frame) in list(self.nb.tabs())
                if not in_nb:
                    # Re-add at correct registry position
                    self.nb.add(frame, text=tdef["label"])
                try:
                    idx = self._desired_tab_index(attr)
                    self.nb.insert(idx, frame)
                except Exception:
                    pass
            else:
                if in_nb:
                    self.nb.hide(frame)

        # Tab set changed — rebuild cached map
        self._build_tab_map()

    def _desired_tab_index(self, attr: str) -> int:
        """Return the notebook index this tab should occupy per registry order."""
        order = [t["attr"] for t in TAB_REGISTRY]
        try:
            reg_pos = order.index(attr)
        except ValueError:
            return len(self.nb.tabs())
        nb_tabs = list(self.nb.tabs())
        idx = 0
        for a in order[:reg_pos]:
            frame = getattr(self, a, None)
            if frame and str(frame) in nb_tabs:
                idx += 1
        return idx

    def _show_world_map(self):
        """Open the World Map pop-out showing great-circle paths to worked stations."""
        if not hasattr(self, "log") or not self.log or not self.log.qsos:
            messagebox.showinfo(
                "World Map",
                "No log loaded yet.\n\nLoad a .s3db log file first, then open the map.",
                parent=self,
            )
            return
        try:
            from world_map import WorldMapWindow
        except ImportError:
            messagebox.showerror(
                "World Map",
                "Could not import world_map.py.\n\n"
                "Make sure world_map.py is in the same folder as vkcontest_analyzer.py.",
                parent=self,
            )
            return
        WorldMapWindow(
            master=self,
            qsos=self.log.qsos,
            band_colours=BAND_COLOURS,
            theme={
                "BG":     BG,
                "BG2":    BG2,
                "BG3":    BG3,
                "ACCENT": ACCENT,
                "FG":     FG,
                "MUTED":  MUTED,
            },
        )

    def _show_plugins_dialog(self):
        """Reopen the Supported Contest Plugins list shown at startup, as a
        normal closable dialog rather than a launch gate."""
        PluginSplashScreen(self, standalone=True)

    def _show_help(self):
        dlg = tk.Toplevel(self)
        dlg.title("Help  —  VK Contest Analyzer")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.attributes("-alpha", 0.0)
        dlg.grab_set()
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.update_idletasks()
        pw, ph = self.winfo_width(), self.winfo_height()
        px, py = self.winfo_rootx(), self.winfo_rooty()
        dw, dh = 480, 360
        dlg.geometry(f"{dw}x{dh}+{px+(pw-dw)//2}+{py+(ph-dh)//2}")
        _fade_in(dlg, target_alpha=0.98)

        pad = dict(padx=28, pady=6)
        tk.Label(dlg, text="⬡ VK CONTEST ANALYZER",
                 font=("Consolas",14,"bold"), fg=ACCENT, bg=BG).pack(pady=(22,0))
        tk.Label(dlg, text=f"Version {VERSION}  ·  By VK2YI",
                 font=("Consolas",9), fg=MUTED, bg=BG).pack(pady=(2,14))
        ttk.Separator(dlg, orient="horizontal").pack(fill="x", padx=24, pady=(0,14))

        # Dynamic description based on current plugin
        plugin_name = self.log.plugin.display_name if self.log else "—"
        cfg = self.log.plugin.session_config() if self.log else None
        if cfg:
            dur_h = cfg.duration_mins // 60
            sess_desc = (f"{plugin_name}: {cfg.num_sessions} × {dur_h}-hour blocks "
                         f"= {cfg.num_sessions * dur_h} hours.")
        else:
            sess_desc = "Load a log to see contest details."

        desc = (
            "A real-time N1MM+ log analyser for contests.\n"
            "Tracks QSOs, multipliers, band efficiency,\n"
            f"propagation and block countdowns.\n{sess_desc}"
        )
        tk.Label(dlg, text=desc, font=FONT_S, fg=FG, bg=BG,
                 justify="center", wraplength=420).pack(**pad)
        ttk.Separator(dlg, orient="horizontal").pack(fill="x", padx=24, pady=(10,14))
        tk.Label(dlg, text="CONTACT  /  SUPPORT",
                 font=("Consolas",9,"bold"), fg=ACCENT3, bg=BG).pack()

        email_lbl = tk.Label(dlg, text="✉  radio@vk2yi.com",
                              font=("Consolas",10), fg=ACCENT, bg=BG, cursor="hand2")
        email_lbl.pack(pady=(8,2))
        email_lbl.bind("<Button-1>", lambda e: self._open_url("mailto:radio@vk2yi.com"))
        email_lbl.bind("<Enter>", lambda e: email_lbl.config(fg=GREEN))
        email_lbl.bind("<Leave>", lambda e: email_lbl.config(fg=ACCENT))

        qrz_lbl = tk.Label(dlg, text="🌐  qrz.com/db/vk2yi",
                            font=("Consolas",10), fg=ACCENT, bg=BG, cursor="hand2")
        qrz_lbl.pack(pady=(2,8))
        qrz_lbl.bind("<Button-1>", lambda e: self._open_url("https://www.qrz.com/db/vk2yi"))
        qrz_lbl.bind("<Enter>", lambda e: qrz_lbl.config(fg=GREEN))
        qrz_lbl.bind("<Leave>", lambda e: qrz_lbl.config(fg=ACCENT))

        ttk.Separator(dlg, orient="horizontal").pack(fill="x", padx=24, pady=(6,16))
        self._btn(dlg, "🐞  Report Issue / Request Feature",
                  lambda: (dlg.destroy(), self._show_report_dialog()),
                  style="secondary").pack(pady=(0,8))
        self._btn(dlg, "Close", dlg.destroy).pack(pady=(0,20))

    def _open_url(self, url):
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception:
            pass

    # ── Report Issue / Request Feature ────────────────────────────────────────

    def _build_diagnostic_block(self):
        """Returns a Markdown block describing app/system context for bug reports."""
        lines = []
        lines.append(f"- App version: {VERSION}")
        lines.append(f"- OS: {platform.system()} {platform.release()}")
        lines.append(f"- Python: {platform.python_version()}")
        lines.append(f"- Theme: {_ACTIVE_THEME}")
        if self.log:
            try:
                lines.append(f"- Active plugin: {self.log.plugin.display_name}")
            except Exception:
                pass
        else:
            lines.append("- No log loaded at time of report")

        recent = _log_ring.recent(15)
        if recent:
            lines.append("")
            lines.append("<details><summary>Recent log output</summary>")
            lines.append("")
            lines.append("```")
            for r in recent:
                lines.append(r if len(r) <= 200 else r[:200] + "…")
            lines.append("```")
            lines.append("</details>")
        return "\n".join(lines)

    @staticmethod
    def _extract_ai_title_and_body(raw_text):
        """If text starts with 'TITLE: ...', split it into (title, remaining body)."""
        text = raw_text.strip()
        m = re.match(r"^TITLE:\s*(.+?)\s*\n+(.*)$", text, re.S | re.I)
        if m:
            return m.group(1).strip(), m.group(2).strip()
        return None, text

    def _compose_feature_body(self, fields):
        ai = fields["ai_used"].get()
        chk = fields["checked_existing"].get()
        what = fields["what"].get("1.0", "end").strip()
        lines = [
            "### Request preparation",
            f"- [{'x' if ai else ' '}] I used an AI assistant to help structure this request",
            f"- [{'x' if chk else ' '}] I checked for existing issues covering the same feature",
            "",
            "### What would you like?",
            what or "_(describe the feature you'd like)_",
        ]
        return "\n".join(lines)

    def _compose_bug_body(self, fields):
        def gt(key, placeholder):
            v = fields[key].get("1.0", "end").strip()
            return v or placeholder

        ai = fields["ai_used"].get()
        att = fields["attached"].get()
        lines = [
            "### Report preparation",
            f"- [{'x' if ai else ' '}] I used the AI-assisted bug report tool (Help → Report Issue)",
            f"- [{'x' if att else ' '}] I have attached a support bundle or log file",
            "",
            "### What happened?",
            gt("what_happened", "_(describe what happened)_"),
            "",
            "### What did you expect?",
            gt("expected", "_(describe what you expected to happen)_"),
            "",
            "### What is the procedure for making this work?",
            gt("procedure", "_(n/a)_"),
            "",
            "### Steps to reproduce",
            gt("steps", "_(n/a)_"),
            "",
            "### VK Contest Analyzer version",
            VERSION,
            "",
            "### Operating system",
            fields["os_var"].get(),
            "",
            "### OS version and hardware",
            fields["os_detail_var"].get().strip() or platform.platform(),
        ]
        return "\n".join(lines)

    def _compose_report_body(self, kind, fields):
        override = fields["override"].get("1.0", "end").strip()
        if override:
            _, body = self._extract_ai_title_and_body(override)
            return body
        if kind == "feature":
            return self._compose_feature_body(fields)
        return self._compose_bug_body(fields)

    def _show_report_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("Report Issue / Request Feature — VK Contest Analyzer")
        dlg.configure(bg=BG)
        dlg.resizable(False, True)
        dlg.attributes("-alpha", 0.0)
        dlg.grab_set()
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.update_idletasks()
        pw, ph = self.winfo_width(), self.winfo_height()
        px, py = self.winfo_rootx(), self.winfo_rooty()
        dw = 620
        dh = min(760, max(560, ph - 60))
        dlg.geometry(f"{dw}x{dh}+{px+(pw-dw)//2}+{max(py+20, 10)}")
        dlg.minsize(dw, 480)
        _fade_in(dlg, target_alpha=0.98)

        tk.Label(dlg, text="⬡ REPORT AN ISSUE / REQUEST A FEATURE",
                 font=("Consolas", 13, "bold"), fg=ACCENT, bg=BG).pack(pady=(16, 4))
        tk.Label(dlg, text=f"VK Contest Analyzer v{VERSION}  ·  github.com/{GITHUB_REPO}",
                 font=FONT_S, fg=MUTED, bg=BG).pack(pady=(0, 10))
        ttk.Separator(dlg, orient="horizontal").pack(fill="x", padx=24, pady=(0, 8))

        # Type selector
        type_frame = tk.Frame(dlg, bg=BG)
        type_frame.pack(pady=(0, 6))
        tk.Label(type_frame, text="Type:", font=FONT_B, fg=FG, bg=BG).pack(side="left", padx=(0, 8))
        kind_var = tk.StringVar(value="bug")
        tk.Radiobutton(type_frame, text="Bug Report", variable=kind_var, value="bug",
                       font=FONT_B, fg=FG, bg=BG, selectcolor=BG3,
                       activebackground=BG, activeforeground=ACCENT,
                       command=lambda: _rebuild()).pack(side="left", padx=6)
        tk.Radiobutton(type_frame, text="Feature Request", variable=kind_var, value="feature",
                       font=FONT_B, fg=FG, bg=BG, selectcolor=BG3,
                       activebackground=BG, activeforeground=ACCENT,
                       command=lambda: _rebuild()).pack(side="left", padx=6)

        # Title (common to both)
        title_frame = tk.Frame(dlg, bg=BG)
        title_frame.pack(fill="x", padx=24, pady=(4, 0))
        tk.Label(title_frame, text="Title:", font=FONT_B, fg=FG, bg=BG, anchor="w").pack(fill="x")
        title_var = tk.StringVar()
        title_entry = tk.Entry(title_frame, textvariable=title_var, font=FONT_B,
                                bg=BG2, fg=FG, insertbackground=FG, relief="flat")
        title_entry.pack(fill="x", pady=(2, 6), ipady=4)

        # Scrollable area for type-specific fields
        outer = tk.Frame(dlg, bg=BG)
        outer.pack(fill="both", expand=True, padx=0, pady=0)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(24, 0))
        vsb.pack(side="right", fill="y")
        content = tk.Frame(canvas, bg=BG)
        content_id = canvas.create_window((0, 0), window=content, anchor="nw")

        def _on_content_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        content.bind("<Configure>", _on_content_configure)

        def _on_canvas_configure(e):
            canvas.itemconfig(content_id, width=e.width)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_wheel(e):
            if getattr(e, "num", None) == 4:
                canvas.yview_scroll(-1, "units")
            elif getattr(e, "num", None) == 5:
                canvas.yview_scroll(1, "units")
            else:
                canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        def _bind_wheel(e):
            canvas.bind_all("<MouseWheel>", _on_wheel)
            canvas.bind_all("<Button-4>", _on_wheel)
            canvas.bind_all("<Button-5>", _on_wheel)

        def _unbind_wheel(e):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        canvas.bind("<Enter>", _bind_wheel)
        canvas.bind("<Leave>", _unbind_wheel)

        fields = {}

        def _txt(parent, height):
            t = tk.Text(parent, height=height, font=FONT_S, bg=BG2, fg=FG,
                        insertbackground=FG, relief="flat", wrap="word")
            t.pack(fill="x", pady=(2, 8))
            return t

        def _chk(parent, text, default=False):
            var = tk.BooleanVar(value=default)
            tk.Checkbutton(parent, text=text, variable=var, font=FONT_S, fg=FG, bg=BG,
                           activebackground=BG, selectcolor=BG3, anchor="w",
                           justify="left", wraplength=540).pack(anchor="w", pady=(0, 2))
            return var

        def _label(parent, text, bold=False):
            f = ("Consolas", 10, "bold") if bold else FONT_B
            tk.Label(parent, text=text, font=f, fg=FG if not bold else ACCENT3,
                     bg=BG, anchor="w").pack(fill="x", pady=(6, 0))

        def _rebuild():
            for w in content.winfo_children():
                w.destroy()
            fields.clear()
            kind = kind_var.get()
            if kind == "feature":
                _label(content, "REQUEST PREPARATION", bold=True)
                fields["ai_used"] = _chk(content, "I used an AI assistant to help structure this request")
                fields["checked_existing"] = _chk(content, "I checked for existing issues covering the same feature")
                _label(content, "What would you like?")
                fields["what"] = _txt(content, 8)
            else:
                _label(content, "REPORT PREPARATION", bold=True)
                fields["ai_used"] = _chk(content, "I used the AI-assisted bug report tool (Help → Report Issue)")
                fields["attached"] = _chk(content, "I have attached a support bundle or log file")
                _label(content, "What happened?")
                fields["what_happened"] = _txt(content, 4)
                _label(content, "What did you expect?")
                fields["expected"] = _txt(content, 3)
                _label(content, "What is the procedure for making this work?")
                fields["procedure"] = _txt(content, 3)
                _label(content, "Steps to reproduce")
                fields["steps"] = _txt(content, 4)

                _label(content, "VK Contest Analyzer version")
                tk.Label(content, text=VERSION, font=FONT_S, fg=MUTED, bg=BG,
                         anchor="w").pack(fill="x", pady=(2, 8))

                _label(content, "Operating system")
                os_default = {"Windows": "Windows", "Darwin": "macOS",
                               "Linux": "Linux"}.get(platform.system(), "Other")
                fields["os_var"] = tk.StringVar(value=os_default)
                os_cb = ttk.Combobox(content, textvariable=fields["os_var"],
                                      values=["Windows", "macOS", "Linux", "Other"],
                                      state="readonly", font=FONT_S, width=20)
                os_cb.pack(anchor="w", pady=(2, 8))

                _label(content, "OS version and hardware")
                fields["os_detail_var"] = tk.StringVar(value=platform.platform())
                os_detail_entry = tk.Entry(content, textvariable=fields["os_detail_var"],
                                            font=FONT_S, bg=BG2, fg=FG,
                                            insertbackground=FG, relief="flat")
                os_detail_entry.pack(fill="x", pady=(2, 8), ipady=3)

            _label(content, "Optional — paste an AI-polished report here (overrides the fields above)")
            fields["override"] = _txt(content, 5)

            content.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.yview_moveto(0)

        _rebuild()

        # Diagnostics checkbox (fixed, below scroll area)
        diag_var = tk.BooleanVar(value=True)
        tk.Checkbutton(dlg, text="Attach diagnostic info (version, OS, plugin, recent log lines)",
                       variable=diag_var, font=FONT_S, fg=MUTED, bg=BG,
                       activebackground=BG, selectcolor=BG3).pack(anchor="w", padx=24, pady=(6, 6))

        ttk.Separator(dlg, orient="horizontal").pack(fill="x", padx=24, pady=(0, 8))

        tk.Label(dlg, text="STEP 1 (OPTIONAL) — POLISH WITH AI", font=("Consolas", 9, "bold"),
                 fg=ACCENT3, bg=BG).pack()
        tk.Label(dlg,
                 text="Copies a prompt to your clipboard and opens your preferred AI chat.\n"
                      "Paste the prompt, then paste the AI's reply into the override box above.",
                 font=FONT_S, fg=MUTED, bg=BG, justify="center").pack(pady=(2, 6))

        ai_frame = tk.Frame(dlg, bg=BG)
        ai_frame.pack(pady=(0, 8))
        self._btn(ai_frame, "Copy AI Prompt",
                  lambda: self._copy_report_prompt(kind_var, title_var, fields),
                  style="secondary").pack(side="left", padx=4)
        self._btn(ai_frame, "Open Claude",
                  lambda: self._open_url("https://claude.ai/new"), style="secondary").pack(side="left", padx=4)
        self._btn(ai_frame, "Open ChatGPT",
                  lambda: self._open_url("https://chat.openai.com/"), style="secondary").pack(side="left", padx=4)

        ttk.Separator(dlg, orient="horizontal").pack(fill="x", padx=24, pady=(0, 8))

        btn_frame = tk.Frame(dlg, bg=BG)
        btn_frame.pack(pady=(0, 14))
        self._btn(btn_frame, "Open GitHub Issue →",
                  lambda: self._submit_github_issue(kind_var, title_var, fields, diag_var)).pack(side="left", padx=6)
        self._btn(btn_frame, "Close", dlg.destroy, style="secondary").pack(side="left", padx=6)

        title_entry.focus_set()

    def _copy_report_prompt(self, kind_var, title_var, fields):
        kind = kind_var.get()
        title = title_var.get().strip()

        if kind == "feature":
            kind_label = "feature request"
            notes = fields["what"].get("1.0", "end").strip()
            template_hint = "Structure the body with a '### What would you like?' section."
        else:
            kind_label = "bug report"
            parts = []
            for key, label in [
                ("what_happened", "What happened"),
                ("expected", "What did you expect"),
                ("procedure", "What is the procedure for making this work"),
                ("steps", "Steps to reproduce"),
            ]:
                val = fields[key].get("1.0", "end").strip()
                if val:
                    parts.append(f"{label}: {val}")
            notes = "\n".join(parts)
            template_hint = (
                "Structure the body with these sections, in this order: "
                "'### What happened?', '### What did you expect?', "
                "'### What is the procedure for making this work?', "
                "'### Steps to reproduce'."
            )

        if not notes:
            notes = "(no details yet — please describe what happened or what you'd like)"

        prompt = (
            f"I'm using VK Contest Analyzer, a desktop companion app for ham radio "
            f"contest logging (works alongside N1MM Logger+). I want to file a "
            f"{kind_label} on its GitHub repo (https://github.com/{GITHUB_REPO}).\n\n"
            f"Please turn my rough notes below into a clear, well-written GitHub issue.\n"
            f"Reply with a short, specific title on the first line, prefixed exactly "
            f"'TITLE: ', then a blank line, then the issue body in Markdown. "
            f"{template_hint}\n"
            f"Do NOT add a 'Report/Request preparation' checklist or a diagnostics/"
            f"system-info section — the app adds those automatically. Do not invent "
            f"details I haven't given you.\n\n"
            f"--- MY ROUGH NOTES ---\n"
        )
        if title:
            prompt += f"Working title: {title}\n\n"
        prompt += notes + "\n--- END NOTES ---"

        try:
            self.clipboard_clear()
            self.clipboard_append(prompt)
            self.update()  # ensure clipboard is flushed before any app focus change
        except Exception:
            pass

        messagebox.showinfo(
            "Prompt copied",
            "An AI prompt has been copied to your clipboard.\n\n"
            "1. Open Claude or ChatGPT (buttons above) and paste it in.\n"
            "2. Copy the AI's reply.\n"
            "3. Paste the reply into the 'AI-polished report' box at the "
            "bottom of the form — it will override the fields above.\n\n"
            "If the reply starts with 'TITLE: ...', that title will be used "
            "automatically when you click 'Open GitHub Issue'."
        )

    def _submit_github_issue(self, kind_var, title_var, fields, diag_var):
        import webbrowser
        import urllib.parse

        kind = kind_var.get()
        override = fields["override"].get("1.0", "end").strip()
        ai_title = None
        if override:
            ai_title, _ = self._extract_ai_title_and_body(override)

        title = title_var.get().strip() or (ai_title or "")
        if not title:
            messagebox.showwarning(
                "Title needed",
                "Please enter a title (or paste an AI reply that starts with "
                "'TITLE: ...') before opening the GitHub issue."
            )
            return

        body = self._compose_report_body(kind, fields)
        if diag_var.get():
            body += "\n\n---\n\n**Diagnostics**\n\n" + self._build_diagnostic_block()

        # GitHub issue pre-fill URLs can be truncated by browsers/proxies if very
        # long (newlines URL-encode to %0A — 3 chars each — so this adds up fast).
        MAX_BODY = 3500
        if len(body) > MAX_BODY:
            body = body[:MAX_BODY] + (
                "\n\n…(truncated — please trim before submitting, "
                "or attach extra detail/log files manually after the issue is created)"
            )

        label = "bug" if kind == "bug" else "enhancement"
        params = urllib.parse.urlencode({"title": title, "body": body, "labels": label})
        url = f"https://github.com/{GITHUB_REPO}/issues/new?{params}"

        try:
            webbrowser.open(url)
        except Exception:
            messagebox.showerror("Couldn't open browser",
                                  "Please open this URL manually:\n\n" + url)


    def _pulse_live(self):
        try:
            if not self.log:
                self._live_canvas.itemconfig(self._live_dot,  fill="#3a3a3a")
                self._live_canvas.itemconfig(self._live_label, fill=MUTED)
                self._live_pulse_state = True
                # Do not reschedule while there is no log — _on_load_success
                # will call _pulse_live() again to restart the loop.
                self._pulse_job = None
                return
            elif self._live_pulse_state:
                self._live_canvas.itemconfig(self._live_dot,  fill=GREEN)
                self._live_canvas.itemconfig(self._live_label, fill=GREEN)
            else:
                self._live_canvas.itemconfig(self._live_dot,  fill="#144d35")
                self._live_canvas.itemconfig(self._live_label, fill=MUTED)
            self._live_pulse_state = not self._live_pulse_state
            self._pulse_job = self.after(700, self._pulse_live)
        except Exception:
            pass

    # ── View refresh ─────────────────────────────────────────────────────────

    def _refresh_all_views(self):
        if not self.log:
            return

        # Cancel any deferred cascade jobs from a previous refresh
        for job in getattr(self, "_cascade_jobs", []):
            try:
                self.after_cancel(job)
            except Exception:
                pass
        self._cascade_jobs = []

        self._refresh_overview_cards()

        try:
            active_frame = str(self.nb.select())
        except Exception:
            active_frame = ""

        # Use cached tab_map; classify keys into light/heavy for scheduling
        HEAVY_ATTRS = {"tab_overview", "tab_rate", "tab_propagation",
                       "tab_replay",   "tab_fatigue", "tab_yoy", "tab_pace"}
        tab_refresh_map = getattr(self, "_tab_map", {})
        if not tab_refresh_map:
            self._build_tab_map()
            tab_refresh_map = self._tab_map
        light_keys, heavy_keys = [], []
        for tdef in TAB_REGISTRY:
            attr  = tdef["attr"]
            frame = getattr(self, attr, None)
            if frame is None:
                continue
            key = str(frame)
            if key not in tab_refresh_map:
                continue
            if attr in HEAVY_ATTRS:
                heavy_keys.append(key)
            else:
                light_keys.append(key)

        self._tab_dirty = {k: True for k in tab_refresh_map}

        # Refresh active tab immediately
        active_fn = tab_refresh_map.get(active_frame)
        if active_fn:
            active_fn()
            self._tab_dirty[active_frame] = False

        # Defer the rest: light first, then heavy
        delay = 120
        for tab_frame in light_keys + heavy_keys:
            if tab_frame == active_frame:
                continue
            fn = tab_refresh_map.get(tab_frame)
            if fn:
                def _deferred(f=fn, key=tab_frame):
                    f()
                    self._tab_dirty[key] = False
                job = self.after(delay, _deferred)
                self._cascade_jobs.append(job)
                delay += 150

        # Missing tab always refreshes (drives the badge count)
        job = self.after(10, self._refresh_missing)
        self._cascade_jobs.append(job)

    def _refresh_overview_cards(self):
        # All expensive computation is consolidated in compute_snapshot(), which
        # does a single pass over the QSO list instead of the 13+ independent
        # iterations that used to happen here.  See ContestLog.compute_snapshot()
        # for a full description of what was deduplicated and why.
        snap = self.log.compute_snapshot()

        self.sc_vars["total"]      = str(snap["total"])
        self.sc_vars["valid"]      = str(snap["valid"])
        self.sc_vars["score"]      = f"{snap['score']:,}"
        self.sc_vars["worked"]     = str(snap["worked"])
        self.sc_vars["band_mults"] = str(snap["band_mults"])
        self.sc_vars["missing"]    = str(snap["missing"])
        self.sc_vars["pct"]        = f"{snap['pct']:.1f}%"

        self._ov_data = snap

    def _calc_font_scale(self, w_px, h_px, base_w=1300.0, base_h=850.0):
        """
        Scale factor for overview-panel fonts, based on the actual rendered
        size of a figure (in pixels) vs. the 13x8.5in @ 100dpi baseline the
        layout was originally designed for.

        Keeps text proportionate to the available space: panels stay
        readable (rather than tiny) on large windows, and text shrinks
        (rather than overlapping) on small/narrow windows.
        """
        if w_px <= 1 or h_px <= 1:
            return 1.0
        scale = min(w_px / base_w, h_px / base_h)
        return max(0.6, min(1.35, scale))

    def _combined_font_scale(self, w_px, h_px):
        """
        `_calc_font_scale()` combined with the user's Text Zoom slider,
        under one absolute ceiling.

        The two factors are multiplicative (auto layout-fit scale up to
        1.35x, zoom slider up to 1.6x), so without a combined ceiling the
        result can reach ~2.16x — well past what any panel's fixed label
        offsets/margins were sized for, which is what caused labels to
        overlap bars at moderate zoom levels (e.g. 1.3x) on top of an
        already large auto-fit window. Capping the *product* here keeps
        every downstream panel (including ones using the raw global scale
        rather than the per-panel _panel_fs()) within range.
        """
        base = self._calc_font_scale(w_px, h_px)
        zoom = getattr(self, "_ov_zoom", 1.0)
        return min(base * zoom, 1.6)

    def _panel_fs(self, ax, ref_w=141.0, ref_h=250.0, floor=0.45, max_scale=1.5):
        """
        Extra font-scale factor for a single panel, on top of the global
        `_ov_fs`. Compares this axes' actual pixel size (from its gridspec
        position) against a reference size — the ~7-column intel-row panel
        at the 13x8.5in baseline. Lets dense-content panels (Personal
        Bests, Operator Times, QSO Value) shrink further than the global
        scale when they end up narrower/shorter than that reference, e.g.
        because more intel panels are visible or the window got smaller.

        `max_scale` caps the panel's effective font scale independent of
        how high the user has pushed the global Text Zoom slider — these
        panels are dense, fixed-size tables, so beyond a certain point
        larger text just overlaps rather than helping readability.
        """
        fig = ax.figure
        fig_w_px = fig.get_size_inches()[0] * fig.dpi
        fig_h_px = fig.get_size_inches()[1] * fig.dpi
        pos = ax.get_position()
        w_px = pos.width  * fig_w_px
        h_px = pos.height * fig_h_px
        extra = min(w_px / ref_w, h_px / ref_h, 1.0)
        return min(self._ov_fs * max(floor, extra), max_scale)

    def _fit_text(self, ax, text, fontsize, avail_frac=0.92):
        """
        Truncate `text` (monospace) with an ellipsis so it fits within
        `avail_frac` of this axes' pixel width at the given fontsize.
        """
        fig = ax.figure
        fig_w_px  = fig.get_size_inches()[0] * fig.dpi
        panel_px  = ax.get_position().width * fig_w_px
        char_px   = fontsize * (fig.dpi / 72.0) * 0.62
        max_chars = max(3, int((panel_px * avail_frac) / char_px))
        if len(text) > max_chars:
            return text[:max(1, max_chars - 1)] + "…"
        return text

    def _ensure_fig_overview(self):
        """Create fig_overview / canvas_ov on first use (lazy init)."""
        if self.fig_overview is not None:
            return
        self.fig_overview = Figure(figsize=(13, 8.5), facecolor=BG2)
        self.canvas_ov = FigureCanvasTkAgg(self.fig_overview, master=self._ov_fig_frame)
        self.canvas_ov.get_tk_widget().pack(fill="both", expand=True)

        # Gauge hover tooltip state
        self._gauge_ax_tips: dict = {}   # {matplotlib Axes: tooltip str}
        self._gauge_tip_win = None        # current floating Tk label window
        self._gauge_tip_ax  = None        # which ax the tip is currently for
        self.canvas_ov.mpl_connect("motion_notify_event", self._on_gauge_hover)
        self.canvas_ov.mpl_connect("motion_notify_event", self._on_spark_hover)
        self.canvas_ov.mpl_connect("axes_leave_event",    self._on_gauge_leave)
        self.canvas_ov.mpl_connect("axes_leave_event",    self._on_spark_leave)
        self.canvas_ov.mpl_connect("figure_leave_event",  self._on_gauge_leave)
        self.canvas_ov.mpl_connect("figure_leave_event",  self._on_spark_leave)
        # Belt-and-suspenders: matplotlib's leave events can fail to fire on
        # Windows when the cursor moves straight from a gauge axis onto the
        # tooltip's own overlapping Toplevel window, leaving stuck tooltips
        # on screen. A plain Tk <Leave> on the canvas widget is a second,
        # independent signal that doesn't depend on matplotlib's event loop.
        self.canvas_ov.get_tk_widget().bind("<Leave>", self._on_gauge_leave, add="+")
        self._gauge_tip_poll_job = None

    def _on_gauge_hover(self, event):
        """matplotlib motion_notify_event — show tooltip when over a gauge axis."""
        if event.inaxes is None:
            self._hide_gauge_tip()
            return
        tip = self._gauge_ax_tips.get(event.inaxes)
        if not tip:
            self._hide_gauge_tip()
            return
        if event.inaxes is self._gauge_tip_ax:
            return   # already showing for this gauge — no update needed
        self._hide_gauge_tip()
        self._gauge_tip_ax = event.inaxes
        # Position near cursor in screen coords
        widget = self.canvas_ov.get_tk_widget()
        wx = widget.winfo_rootx() + int(event.x)
        wy = widget.winfo_rooty() + int(widget.winfo_height() - event.y)
        self._gauge_tip_win = tw = tk.Toplevel(self)
        tw.wm_overrideredirect(True)
        tw.attributes("-topmost", True)
        lbl = tk.Label(
            tw, text=tip,
            font=("Consolas", 9), fg=FG, bg=BG3,
            relief="flat", bd=0,
            padx=10, pady=8,
            wraplength=320, justify="left",
        )
        lbl.pack()
        tw.configure(bg=ACCENT)
        tw.update_idletasks()
        tw_w = tw.winfo_reqwidth()
        tw_h = tw.winfo_reqheight()
        # Keep tooltip on-screen
        scr_w = self.winfo_screenwidth()
        scr_h = self.winfo_screenheight()
        tx = min(wx + 16, scr_w - tw_w - 4)
        ty = min(wy - tw_h - 8, scr_h - tw_h - 4)
        ty = max(ty, 4)
        tw.wm_geometry(f"+{tx}+{ty}")
        self._start_gauge_tip_poll()

    def _start_gauge_tip_poll(self):
        """
        Safety net for stuck gauge tooltips. matplotlib's axes_leave_event /
        figure_leave_event can silently fail to fire on Windows when the
        cursor moves directly from the gauge onto the tooltip's own
        overlapping Toplevel window. This polls the real OS cursor position
        (winfo_pointerxy, independent of matplotlib's event loop) every
        150ms while a tooltip is visible, and force-hides it the moment the
        cursor isn't over the chart canvas anymore.
        """
        if self._gauge_tip_poll_job:
            self.after_cancel(self._gauge_tip_poll_job)
        self._gauge_tip_poll_job = self.after(150, self._check_gauge_tip_still_valid)

    def _check_gauge_tip_still_valid(self):
        self._gauge_tip_poll_job = None
        if not self._gauge_tip_win:
            return
        try:
            widget = self.canvas_ov.get_tk_widget()
            px, py = self.winfo_pointerxy()
            wx0, wy0 = widget.winfo_rootx(), widget.winfo_rooty()
            ww, wh   = widget.winfo_width(), widget.winfo_height()
            over_canvas = (wx0 <= px <= wx0 + ww) and (wy0 <= py <= wy0 + wh)
        except Exception:
            over_canvas = False
        if not over_canvas:
            self._hide_gauge_tip()
            return
        self._start_gauge_tip_poll()

    def _on_gauge_leave(self, event):
        """matplotlib axes_leave_event — hide tooltip."""
        self._hide_gauge_tip()

    # ── Sparkline floating tooltip ───────────────────────────────────────────

    def _on_spark_hover(self, event):
        """Show a floating Matplotlib Annotation tooltip when hovering over a sparkline."""
        meta = getattr(self, "_spark_tip_meta", {})
        ax = event.inaxes
        if ax not in meta or event.xdata is None:
            self._hide_spark_tip()
            return

        title, y_data, start_h, labels, ticks = meta[ax]
        # Snap to nearest integer bucket
        xi = int(round(event.xdata))
        xi = max(0, min(xi, len(y_data) - 1))
        val = int(y_data[xi])

        # Build human-readable time label for this bucket
        if len(y_data) <= 24:
            hr = (start_h + xi) % 24
            time_lbl = f"{hr:02d}:00"
        else:
            time_lbl = f"T+{xi}h"

        tip_text = f"{title}\n{time_lbl}  \u00b7  {val:,}"

        # Convert the data point to figure-level display coordinates so the
        # annotation is drawn on the figure (not the axes) and is never
        # clipped by adjacent sparkline panels.
        try:
            disp_xy = ax.transData.transform((xi, y_data[xi]))
            fig_xy  = self.fig_overview.transFigure.inverted().transform(disp_xy)
        except Exception:
            return

        ann = getattr(self, "_spark_ann", None)
        needs_create = (ann is None or ann.figure is not self.fig_overview)

        if needs_create:
            self._hide_spark_tip()
            ann = self.fig_overview.text(
                fig_xy[0], fig_xy[1], tip_text,
                fontsize=7.5,
                fontfamily="monospace",
                color=FG,
                va="bottom", ha="left",
                bbox=dict(
                    boxstyle="round,pad=0.45",
                    fc=BG3, ec=ACCENT, lw=1.0, alpha=0.95,
                ),
                transform=self.fig_overview.transFigure,
                clip_on=False,
                zorder=100,
            )
            self._spark_ann = ann
        else:
            ann.set_text(tip_text)
            # Nudge slightly right/up from the data point
            x_fig = min(fig_xy[0] + 0.01, 0.97)
            y_fig = min(fig_xy[1] + 0.01, 0.97)
            ann.set_position((x_fig, y_fig))

        # First creation: set position with nudge
        if needs_create:
            x_fig = min(fig_xy[0] + 0.01, 0.97)
            y_fig = min(fig_xy[1] + 0.01, 0.97)
            ann.set_position((x_fig, y_fig))

        ann.set_visible(True)

        # Crosshair vertical line (axes-local, clipped to its own panel — fine)
        vl = getattr(self, "_spark_vline", None)
        if vl is None or vl.axes is not ax:
            if vl is not None:
                try: vl.remove()
                except Exception: pass
            self._spark_vline = ax.axvline(xi, color=ACCENT, lw=0.8,
                                           ls="--", alpha=0.6, zorder=9)
        else:
            self._spark_vline.set_xdata([xi, xi])

        self.canvas_ov.draw_idle()

    def _on_spark_leave(self, event):
        self._hide_spark_tip()

    def _hide_spark_tip(self):
        ann = getattr(self, "_spark_ann", None)
        if ann is not None:
            try:
                ann.set_visible(False)
                ann.remove()   # figure.text() artists must be removed, not just hidden
            except Exception:
                pass
        vl = getattr(self, "_spark_vline", None)
        if vl is not None:
            try: vl.remove()
            except Exception: pass
            self._spark_vline = None
        self._spark_ann = None
        try:
            self.canvas_ov.draw_idle()
        except Exception:
            pass

    # ── Gauge tooltip (existing) ─────────────────────────────────────────────
    def _hide_gauge_tip(self):
        if self._gauge_tip_poll_job:
            try:
                self.after_cancel(self._gauge_tip_poll_job)
            except Exception:
                pass
            self._gauge_tip_poll_job = None
        if self._gauge_tip_win:
            try:
                self._gauge_tip_win.destroy()
            except Exception:
                pass
            self._gauge_tip_win = None
        self._gauge_tip_ax = None
        
    def _ov_layout_sig(self):
        
        """Captures everything about the *layout* of the overview chart that
        isn't part of the QSO/contest data itself: which panels are floated
        or collapsed, the embedded canvas size, and the active theme."""
        widget = self.canvas_ov.get_tk_widget()
        dock_sig = tuple(sorted(
            (k, bool(v.get("floated")), bool(v.get("collapsed")))
            for k, v in self._dock_state.items()
        ))
        return (dock_sig, widget.winfo_width(), widget.winfo_height(), _ACTIVE_THEME,
                getattr(self, "_ov_zoom", 1.0))

    def _ov_fingerprint(self, d):
        """Lightweight summary of the overview snapshot used to decide
        whether the overview chart needs a full redraw.

        The full fig.clear() + gridspec rebuild in _refresh_overview_chart()
        is the most expensive thing this app does on a routine timer — and on
        a typical auto-refresh tick nothing has actually changed (no new QSO
        has been logged yet). This fingerprint lets that tick skip the
        rebuild entirely.

        Countdown fields from session_status() are rounded to the minute to
        match the display granularity (the Contest Time / Block Status panel
        shows "Xh Ym", not seconds) — so a tick where the displayed minute
        hasn't changed is correctly treated as "nothing changed", and one
        where it has still triggers a redraw.
        """
        if not d:
            return None

        ss = d.get("session_status", {}) or {}
        ss_sig = (
            ss.get("state"),
            ss.get("session_nr"),
            ss.get("next_session_nr"),
            round(ss.get("remaining_mins", 0)),
            round(ss.get("total_remaining_mins", 0)),
            round(ss.get("total_elapsed_mins", 0)),
            round(ss.get("pct_elapsed", 0), 1),
            round(ss.get("total_pct_elapsed", 0), 1),
        )

        sp = d.get("sparklines", {}) or {}

        return (
            d.get("total"), d.get("valid"), d.get("score"), d.get("worked"),
            d.get("band_mults"), d.get("missing"), round(d.get("pct", 0), 2),
            d.get("zone_cnt"), d.get("zone_band_cnt"),
            d.get("vk_cnt"), d.get("zl_cnt"),
            d.get("qso_max"), d.get("score_max"),
            tuple(d.get("worked_zones", ())),
            repr(d.get("band_efficiency")),
            repr(d.get("region_heat")),
            repr(d.get("personal_bests")),
            tuple((q.get("call"), q.get("band"), q.get("time"))
                  for q in d.get("last_worked", [])),
            tuple(sp.get("qsos", ())),
            tuple(sp.get("running_score", ())),
            tuple(sp.get("new_mults", ())),
            repr(d.get("operator_times")),
            repr(d.get("qso_value")),
            ss_sig,
        )

    def _refresh_overview_chart(self):
        self._ensure_fig_overview()

        d = getattr(self, "_ov_data", {})

        # Skip the expensive fig.clear() + gridspec rebuild entirely if
        # nothing visible has changed since the last redraw (see
        # _ov_fingerprint / _ov_layout_sig docstrings).
        sig = (self._ov_layout_sig(), self._ov_fingerprint(d))
        if sig == getattr(self, "_ov_last_sig", None):
            return
        self._ov_last_sig = sig

        self.fig_overview.clear()

        widget = self.canvas_ov.get_tk_widget()
        self._ov_fs = self._combined_font_scale(widget.winfo_width(), widget.winfo_height())

        if not d:
            self.canvas_ov.draw_idle()
            for key in list(self._float_figs.keys()):
                self._draw_float_panel(key)
            return

        p           = d.get("_plugin", GenericPlugin())
        total_mults = d.get("_total_mults", 0)

        def visible(key):
            s = self._dock_state.get(key, {})
            # 'heat' and 'bars' panels only shown when the plugin has regions
            if key in ("heat","bars") and not p.has_region_heat():
                return False
            return not s.get("floated") and not s.get("collapsed")

        intel_visible = any(visible(k) for k in ["block","band","heat","bests","value","last","ops"])
        row_defs = [("gauges",2.0), ("intel",3.2), ("sparks",1.8), ("bars",1.8)]
        vis_rows = []
        for rkey, ratio in row_defs:
            if rkey == "intel":
                if intel_visible: vis_rows.append(("intel", ratio))
            elif rkey == "bars" and not p.has_state_bars():
                pass
            elif visible(rkey):
                vis_rows.append((rkey, ratio))

        if not vis_rows:
            self.canvas_ov.draw_idle()
            for key in list(self._float_figs.keys()):
                self._draw_float_panel(key)
            return

        # Most plugins expose exactly 7 gauges, but a plugin may add extra
        # ones (e.g. IARU's WRTC-worked side tracker) — size the grid to
        # whatever gauge_defs() actually returns so `gs[row, i]` never
        # indexes past the gridspec's column count.
        n_cols   = max(7, len(p.gauge_defs(d, total_mults)))
        n_rows   = len(vis_rows)
        ratios   = [r for _, r in vis_rows]
        row_keys = [k for k, _ in vis_rows]

        gs = self.fig_overview.add_gridspec(
            n_rows, n_cols,
            height_ratios=ratios,
            hspace=0.18, wspace=0.08,
            left=0.03, right=0.97, top=0.97, bottom=0.05,
        )

        def panel_style(ax, title, colour=None):
            fs = self._ov_fs
            c = colour or ACCENT
            ax.set_facecolor(BG3)
            for spine in ax.spines.values(): spine.set_edgecolor(BG2)
            # Accent stripe: top spine drawn in the panel's own colour
            ax.spines["top"].set_edgecolor(c)
            ax.spines["top"].set_linewidth(2.5)
            ax.tick_params(colors=MUTED, labelsize=7.5*fs)
            ax.set_title(f"● {title}", color=c, fontfamily="monospace",
                         fontsize=8*fs, fontweight="bold", pad=5)

        for row_idx, rkey in enumerate(row_keys):
            if rkey == "gauges":
                self._draw_gauges_on_fig(self.fig_overview, d, total_mults,
                                          gs=gs, row=row_idx, n_cols=n_cols)

            elif rkey == "intel":
                intel_keys = [k for k in ["block","band","heat","bests","value","last","ops"] if visible(k)]
                if not intel_keys:
                    continue
                gs_intel = gs[row_idx, :].subgridspec(1, len(intel_keys), wspace=0.28)
                for ci, k in enumerate(intel_keys):
                    if k == "block":
                        ax = self.fig_overview.add_subplot(gs_intel[0, ci])
                        uses_blocks = getattr(p, "uses_block_structure", lambda: True)()
                        title = "[ B ]  BLOCK STATUS" if uses_blocks else "[ T ]  CONTEST TIME"
                        panel_style(ax, title, colour=ACCENT)
                        ax.set_aspect("equal", adjustable="box")
                        ax.set_xlim(-1.6, 1.6); ax.set_ylim(-1.0, 1.5)
                        ax.axis("off")
                        self._draw_block_status_on_ax(ax, d)
                    elif k == "band":
                        ax = self.fig_overview.add_subplot(gs_intel[0, ci])
                        panel_style(ax, "[ ~ ]  BAND EFFICIENCY", colour=GREEN)
                        self._draw_band_efficiency_on_ax(ax, d)
                    elif k == "heat":
                        ax = self.fig_overview.add_subplot(gs_intel[0, ci])
                        panel_style(ax, "[ # ]  REGION HEAT", colour=ACCENT3)
                        self._draw_region_heat_on_ax(ax, d)
                    elif k == "bests":
                        ax = self.fig_overview.add_subplot(gs_intel[0, ci])
                        panel_style(ax, "[ * ]  PERSONAL BESTS", colour=ACCENT2)
                        ax.axis("off"); ax.set_xlim(0,1); ax.set_ylim(0,1)
                        self._draw_personal_bests_on_ax(ax, d)
                    elif k == "value":
                        ax = self.fig_overview.add_subplot(gs_intel[0, ci])
                        panel_style(ax, "[ $ ]  QSO VALUE", colour=ACCENT3)
                        ax.axis("off"); ax.set_xlim(0,1); ax.set_ylim(0,1)
                        self._draw_qso_value_on_ax(ax, d)
                    elif k == "last":
                        ax = self.fig_overview.add_subplot(gs_intel[0, ci])
                        panel_style(ax, "[ » ]  LAST WORKED", colour=ACCENT)
                        ax.axis("off"); ax.set_xlim(0,1); ax.set_ylim(0,1)
                        self._draw_last_worked_on_ax(ax, d)
                    elif k == "ops":
                        ax = self.fig_overview.add_subplot(gs_intel[0, ci])
                        panel_style(ax, "[ O ]  OPERATOR TIMES", colour=GREEN)
                        ax.axis("off"); ax.set_xlim(0,1); ax.set_ylim(0,1)
                        self._draw_operator_times_on_ax(ax, d)

            elif rkey == "sparks":
                gs_spark = gs[row_idx, :].subgridspec(1, 3, wspace=0.06)
                self._draw_sparklines_on_gridspec(self.fig_overview, gs_spark, d)

            elif rkey == "bars":
                ax_bar = self.fig_overview.add_subplot(gs[row_idx, :])
                ax_bar.set_facecolor(BG2)
                self._draw_region_bars_on_ax(ax_bar, d)

        self.canvas_ov.draw_idle()
        for key in list(self._float_figs.keys()):
            self._draw_float_panel(key)

    # ── Panel drawing helpers ─────────────────────────────────────────────────

    def _draw_gauges_on_fig(self, fig, d, total_mults, gs=None, row=0, n_cols=7):
        fs = self._ov_fs
        p = d.get("_plugin", GenericPlugin())
        gauge_defs = p.gauge_defs(d, total_mults)

        # Clear stale tooltip registrations from the previous draw so we
        # don't show tips for axes that no longer exist after fig.clear().
        # Only clear axes that belong to this figure to avoid stomping on
        # float-panel registrations when the embedded canvas is redrawn.
        self._gauge_ax_tips = {
            ax: tip for ax, tip in getattr(self, "_gauge_ax_tips", {}).items()
            if ax.get_figure() is not fig
        }

        def _resolve_max(max_spec):
            """max_spec can be a dict key string or a literal number."""
            if isinstance(max_spec, str):
                return d.get(max_spec, 100) or 100
            return max_spec or 10

        # Cancel any in-flight gauge sweep animations from a previous draw.
        for _job in getattr(self, "_gauge_anim_jobs", []):
            try: self.after_cancel(_job)
            except Exception: pass
        self._gauge_anim_jobs = []

        def draw_gauge(ax, value, max_val, colour, label, fmt, tooltip="",
                       anim_delay_ms=0):
            ax.set_aspect("equal"); ax.axis("off"); ax.set_facecolor(BG2)
            ts, te = 210, -30; sweep = ts - te
            final_frac = min(max(value / max_val, 0), 1) if max_val else 0
            tt = np.linspace(np.radians(te), np.radians(ts), 200)
            ro, ri = 1.0, 0.72

            # Background track (always visible immediately)
            ax.fill(np.concatenate([ro*np.cos(tt), ri*np.cos(tt[::-1])]),
                    np.concatenate([ro*np.sin(tt), ri*np.sin(tt[::-1])]),
                    color=BG3, zorder=1)

            # Tick marks (always visible immediately)
            for tf in [0, 0.25, 0.5, 0.75, 1.0]:
                tr = np.radians(ts - tf*sweep)
                ax.plot([0.68*np.cos(tr), 0.75*np.cos(tr)],
                         [0.68*np.sin(tr), 0.75*np.sin(tr)],
                         color=MUTED, lw=1.2, zorder=4)

            # Value label (static — shows final value from the start)
            val_str = fmt.format(v=value)
            # Long formatted values (e.g. "2,442,068") need a smaller font
            # than short ones (e.g. "1297") to stay within the gauge circle —
            # especially important now text zoom can push fs above 1.0.
            val_fs = 13 * fs if len(val_str) <= 5 else 13 * fs * (5.5 / len(val_str))
            ax.text(0,  0.10, val_str, ha="center", va="center",
                     fontsize=val_fs, fontweight="bold", color=colour,
                     fontfamily="monospace", zorder=5)
            ax.text(0, -0.28, label, ha="center", va="center",
                     fontsize=7*fs, color=MUTED, fontfamily="monospace", zorder=5)
            ax.text(-0.85, -0.55, "0", ha="center", va="center",
                     fontsize=6.5*fs, color=MUTED, fontfamily="monospace")
            max_str = (f"{max_val:,}" if isinstance(max_val, int) and max_val >= 1000
                       else str(max_val))
            ax.text(0.85, -0.55, max_str, ha="center", va="center",
                     fontsize=6.5*fs, color=MUTED, fontfamily="monospace")
            ax.set_xlim(-1.2, 1.2); ax.set_ylim(-0.75, 1.2)

            # Register for hover — only if a tooltip was supplied by the plugin
            if tooltip:
                self._gauge_ax_tips[ax] = tooltip

            # ── Animated arc sweep: grows from 0 → final_frac ────────────────
            # We keep a single mutable arc patch + tip dot, replacing their
            # path data each frame without touching any other artists.
            if final_frac <= 0:
                return   # nothing to animate

            N_STEPS  = 28
            STEP_MS  = 16   # ~60 fps feel

            # Create the arc patch and tip dot at frac=0 initially
            vt0 = np.linspace(np.radians(ts), np.radians(ts), 2)
            arc_patch = ax.fill(
                np.concatenate([ro*np.cos(vt0), ri*np.cos(vt0[::-1])]),
                np.concatenate([ro*np.sin(vt0), ri*np.sin(vt0[::-1])]),
                color=colour, zorder=2, alpha=0.92,
            )[0]

            tip_r   = (ro + ri) / 2
            (tip_dot,) = ax.plot(
                [tip_r*np.cos(np.radians(ts))],
                [tip_r*np.sin(np.radians(ts))],
                "o", color="white", ms=4, zorder=3,
            )

            canvas_ref = self.canvas_ov

            def _make_gauge_step(patch, dot, target_frac, n_steps, ts_, sweep_):
                def _step(frame):
                    # Ease-out: fast start, gentle landing
                    t = frame / n_steps
                    eased = 1.0 - (1.0 - t) ** 2
                    cur_frac = target_frac * eased
                    angle_start = ts_ - cur_frac * sweep_
                    vt = np.linspace(np.radians(angle_start), np.radians(ts_), 200)
                    xs = np.concatenate([ro*np.cos(vt), ri*np.cos(vt[::-1])])
                    ys = np.concatenate([ro*np.sin(vt), ri*np.sin(vt[::-1])])
                    patch.get_paths()[0].vertices[:, 0] = xs
                    patch.get_paths()[0].vertices[:, 1] = ys
                    dot.set_data(
                        [tip_r * np.cos(np.radians(angle_start))],
                        [tip_r * np.sin(np.radians(angle_start))],
                    )
                    try:
                        canvas_ref.draw_idle()
                    except Exception:
                        pass
                return _step

            step_fn = _make_gauge_step(
                arc_patch, tip_dot, final_frac, N_STEPS, ts, sweep
            )
            for frame in range(1, N_STEPS + 1):
                delay = anim_delay_ms + frame * STEP_MS
                job = self.after(delay, step_fn, frame)
                self._gauge_anim_jobs.append(job)

        gauges_resolved = [
            (g.label, d.get(g.value_key, 0), _resolve_max(g.max_key),
             g.colour, g.fmt, getattr(g, "tooltip", ""))
            for g in gauge_defs
        ]

        # Stagger each gauge by 80 ms so they sweep in one after another
        _GAUGE_STAGGER_MS = 80

        if gs is not None:
            for i, (label, value, mv, colour, fmt, tip) in enumerate(gauges_resolved):
                ax = fig.add_subplot(gs[row, i])
                draw_gauge(ax, value, mv, colour, label, fmt, tip,
                           anim_delay_ms=i * _GAUGE_STAGGER_MS)
        else:
            gs2 = fig.add_gridspec(1, len(gauges_resolved), wspace=0.08,
                                    left=0.02, right=0.98, top=0.95, bottom=0.05)
            for i, (label, value, mv, colour, fmt, tip) in enumerate(gauges_resolved):
                ax = fig.add_subplot(gs2[0, i])
                draw_gauge(ax, value, mv, colour, label, fmt, tip,
                           anim_delay_ms=i * _GAUGE_STAGGER_MS)

    def _draw_block_status_on_ax(self, ax, d):
        fs = self._ov_fs
        mpa = mpatches  # module-level import
        ss = d.get("session_status", {})
        if not ss:
            ax.text(0, 0, "No log loaded", ha="center", va="center",
                     color=MUTED, fontsize=8*fs, fontfamily="monospace")
            return
        state       = ss.get("state", "over")
        sn          = ss.get("session_nr", 0)
        remaining   = ss.get("remaining_mins", 0)
        pct_elapsed = ss.get("pct_elapsed", 0)
        next_sn     = ss.get("next_session_nr")
        rem_h = int(remaining // 60)
        rem_m = int(remaining % 60)

        p   = d.get("_plugin", GenericPlugin())
        cfg = p.session_config()
        lbl = cfg.label_prefix

        # Some contests (e.g. CQWW) have no meaningful "block" subdivision —
        # the plugin can opt out via uses_block_structure() and we instead
        # show whole-contest start/elapsed/remaining time.
        uses_blocks = getattr(p, "uses_block_structure", lambda: True)()

        if state == "pre":
            start_dt  = ss.get("start_dt")
            start_str = start_dt.strftime("%Y-%m-%d %H:%M UTC") if start_dt else "—"
            ax.text(0,  1.35, "PRE-CONTEST", ha="center", va="center",
                     fontsize=10*fs, fontweight="bold", color=ACCENT3, fontfamily="monospace")
            ax.text(0,  0.75, "Starts in", ha="center", va="center",
                     fontsize=8*fs, color=MUTED, fontfamily="monospace")
            ax.text(0,  0.25, f"{rem_h}h {rem_m:02d}m", ha="center", va="center",
                     fontsize=14*fs, fontweight="bold", color=ACCENT3, fontfamily="monospace")
            ax.text(0, -0.30, start_str, ha="center", va="center",
                     fontsize=7*fs, color=MUTED, fontfamily="monospace")
            dur_h      = cfg.duration_mins // 60
            total_h    = cfg.num_sessions * dur_h
            start_hhmm   = f"{cfg.start_hour:02d}:00" if cfg.start_hour else "00:00"
            end_hour_raw = (cfg.start_hour or 0) + cfg.num_sessions * dur_h
            end_hour     = end_hour_raw % 24
            end_hhmm     = f"{end_hour:02d}:00" + (" +1d" if end_hour_raw >= 24 else "")
            if uses_blocks:
                ax.text(0, -0.65,
                         f"{lbl}1 starts at {start_hhmm} UTC  "
                         f"({cfg.num_sessions} × {dur_h}hr blocks, ends {end_hhmm} UTC)",
                         ha="center", va="center", fontsize=7*fs, color=MUTED,
                         fontfamily="monospace")
            else:
                ax.text(0, -0.65,
                         f"Contest starts {start_hhmm} UTC, ends {end_hhmm} UTC  "
                         f"({total_h}hrs total)",
                         ha="center", va="center", fontsize=7*fs, color=MUTED,
                         fontfamily="monospace")
        elif state == "over":
            end_dt  = ss.get("end_dt")
            end_str = end_dt.strftime("%Y-%m-%d %H:%M UTC") if end_dt else "—"
            # ── Rich post-contest results summary ────────────────────────────
            # Pull key stats from the snapshot so the panel stays informative
            # after the contest rather than just saying "OVER".
            total_qsos   = d.get("total_qsos",   0)
            valid_qsos   = d.get("valid_qsos",    total_qsos)
            total_score  = d.get("total_score",   0)
            total_mults  = d.get("_total_mults",  0)
            best_hr      = d.get("personal_bests", {}).get("best_hour_rate", 0)
            best_hr_t    = d.get("personal_bests", {}).get("best_hour_time")
            best_hr_str  = best_hr_t.strftime("%H:%M") if best_hr_t else "—"
            dupe_cnt     = total_qsos - valid_qsos

            # Compact score formatted for readability
            def _fmt_score(n):
                if n >= 1_000_000: return f"{n/1_000_000:.2f}M"
                if n >= 1_000:     return f"{n/1_000:.1f}k"
                return str(n)

            # Centred headline
            ax.text(0,  1.25, "FINAL SCORE", ha="center", va="center",
                     fontsize=8*fs, fontweight="bold", color=MUTED,
                     fontfamily="monospace")
            ax.text(0,  0.75, _fmt_score(total_score), ha="center", va="center",
                     fontsize=20*fs, fontweight="bold", color=ACCENT,
                     fontfamily="monospace")
            ax.text(0,  0.30, f"{valid_qsos:,} Q  ×  {total_mults} mults",
                     ha="center", va="center", fontsize=8*fs, color=FG,
                     fontfamily="monospace")

            # Divider
            ax.plot([-1.3, 1.3], [0.06, 0.06], color=BG3, lw=0.8)

            # Two-column stat grid
            stats_l = [
                ("Best hr",  f"{best_hr} Q/hr @ {best_hr_str}"),
                ("Dupes",    f"{dupe_cnt}"),
            ]
            stats_r = [
                ("QSOs",  f"{total_qsos:,}"),
                ("Ended", end_str.replace(" UTC","") if end_str != "—" else "—"),
            ]
            y0 = -0.12; dy = 0.28
            for i, (lbl, val) in enumerate(stats_l):
                yy = y0 - i*dy
                ax.text(-1.3, yy, lbl, ha="left", va="center",
                         fontsize=6.5*fs, color=MUTED, fontfamily="monospace")
                ax.text(-0.15, yy, val, ha="right", va="center",
                         fontsize=6.5*fs, color=FG, fontfamily="monospace",
                         fontweight="bold")
            for i, (lbl, val) in enumerate(stats_r):
                yy = y0 - i*dy
                ax.text(0.15, yy, lbl, ha="left", va="center",
                         fontsize=6.5*fs, color=MUTED, fontfamily="monospace")
                ax.text(1.3, yy, val, ha="right", va="center",
                         fontsize=6.5*fs, color=FG, fontfamily="monospace",
                         fontweight="bold")
        elif not uses_blocks:
            # ── Whole-contest time start / time left (no block structure) ────
            start_dt = ss.get("start_dt")
            end_dt   = ss.get("end_dt")
            start_str = start_dt.strftime("%H:%M UTC %d %b") if start_dt else "—"
            end_str   = end_dt.strftime("%H:%M UTC %d %b")   if end_dt   else "—"

            total_remaining = ss.get("total_remaining_mins", remaining)
            total_elapsed   = ss.get("total_elapsed_mins", 0)
            total_pct       = ss.get("total_pct_elapsed", pct_elapsed)

            t_rem_h = int(total_remaining // 60)
            t_rem_m = int(total_remaining % 60)
            t_el_h  = int(total_elapsed // 60)
            t_el_m  = int(total_elapsed % 60)

            arc_col = GREEN if total_pct < 60 else (ACCENT3 if total_pct < 85 else ACCENT2)
            ax.add_patch(mpa.Wedge((0,0), 1.0, 0, 180, width=0.32, color=BG3, zorder=1))
            if total_pct > 0:
                deg = min(total_pct/100*180, 180)
                ax.add_patch(mpa.Wedge((0,0), 1.0, 180-deg, 180, width=0.32,
                                        color=arc_col, zorder=2, alpha=0.92))
            if 0 < total_pct < 100:
                tip_ang = np.radians(180 - total_pct/100*180)
                ax.plot(0.84*np.cos(tip_ang), 0.84*np.sin(tip_ang),
                         "o", color="white", ms=5, zorder=3)
            ax.text(0, 1.35, "CONTEST TIME", ha="center", va="center",
                     fontsize=10*fs, fontweight="bold", color=ACCENT, fontfamily="monospace")
            ax.text(0, 0.0, f"{t_rem_h}h {t_rem_m:02d}m", ha="center", va="center",
                     fontsize=11*fs, fontweight="bold", color=FG, fontfamily="monospace", zorder=4)
            ax.text(0, -0.35, "remaining", ha="center", va="center",
                     fontsize=7*fs, color=MUTED, fontfamily="monospace")
            ax.text(0, -0.65, f"Started {start_str}  |  {t_el_h}h {t_el_m:02d}m elapsed",
                     ha="center", va="center", fontsize=7*fs, color=MUTED, fontfamily="monospace")
            ax.text(0, -0.88, f"Ends {end_str}  ({total_pct:.0f}% elapsed)",
                     ha="center", va="center", fontsize=6.5*fs, color=MUTED, fontfamily="monospace")
        else:
            arc_col = GREEN if pct_elapsed < 60 else (ACCENT3 if pct_elapsed < 85 else ACCENT2)
            ax.add_patch(mpa.Wedge((0,0), 1.0, 0, 180, width=0.32, color=BG3, zorder=1))
            if pct_elapsed > 0:
                deg = min(pct_elapsed/100*180, 180)
                ax.add_patch(mpa.Wedge((0,0), 1.0, 180-deg, 180, width=0.32,
                                        color=arc_col, zorder=2, alpha=0.92))
            if 0 < pct_elapsed < 100:
                tip_ang = np.radians(180 - pct_elapsed/100*180)
                ax.plot(0.84*np.cos(tip_ang), 0.84*np.sin(tip_ang),
                         "o", color="white", ms=5, zorder=3)
            ax.text(0, 1.35, f"BLOCK  {lbl}{sn}", ha="center", va="center",
                     fontsize=10*fs, fontweight="bold", color=ACCENT, fontfamily="monospace")
            ax.text(0, 0.0, f"{rem_h}h {rem_m:02d}m", ha="center", va="center",
                     fontsize=11*fs, fontweight="bold", color=FG, fontfamily="monospace", zorder=4)
            ax.text(0, -0.35, "remaining", ha="center", va="center",
                     fontsize=7*fs, color=MUTED, fontfamily="monospace")
            if next_sn:
                ax.text(0, -0.65, f"{lbl}{next_sn} starts in {rem_h}h {rem_m:02d}m",
                         ha="center", va="center", fontsize=7*fs, color=MUTED, fontfamily="monospace")
            ax.text(0, -0.88, f"{pct_elapsed:.0f}% of block elapsed",
                     ha="center", va="center", fontsize=6.5*fs, color=MUTED, fontfamily="monospace")

    def _draw_band_efficiency_on_ax(self, ax, d):
        fs = self._ov_fs
        be = d.get("band_efficiency", [])
        if not be:
            ax.text(0.5, 0.5, "No data", ha="center", va="center",
                     color=MUTED, fontsize=8*fs, fontfamily="monospace", transform=ax.transAxes)
            return
        bands     = [r["band"]       for r in be]
        effic     = [r["efficiency"] for r in be]
        qsos      = [r["qsos"]       for r in be]
        n_sh      = [r["new_shires"] for r in be]
        bar_cols  = [BAND_COLOURS.get(b, BAND_COLOURS_DEFAULT) for b in bands]
        y = np.arange(len(bands))
        hbars = ax.barh(y, effic, color=bar_cols, height=0.55, zorder=2)
        ax.set_yticks(y); ax.set_yticklabels(bands, fontfamily="monospace", fontsize=8*fs)
        for tick, col in zip(ax.get_yticklabels(), bar_cols): tick.set_color(col)
        ax.set_xlabel("New mults / QSO", color=MUTED, fontfamily="monospace", fontsize=7*fs)
        ax.set_facecolor(BG3); ax.grid(axis="x", color=BG2, lw=0.5, zorder=0)
        for sp in ax.spines.values(): sp.set_edgecolor(BG2)
        ax.tick_params(colors=MUTED, labelsize=7.5*fs)
        from matplotlib.transforms import blended_transform_factory
        trans_mixed = blended_transform_factory(ax.transAxes, ax.transData)
        for bar, ns, nq in zip(hbars, n_sh, qsos):
            ax.text(0.99, bar.get_y() + bar.get_height() / 2,
                     f"{ns}m / {nq}q", va="center", ha="right",
                     fontsize=6.5*fs, color=MUTED, fontfamily="monospace",
                     transform=trans_mixed)
        ax.set_xlim(0, max(effic)*1.25 if effic else 1)

    def _draw_region_heat_on_ax(self, ax, d):
        """Generic region heat panel — works for any plugin with regions."""
        fs = self._panel_fs(ax)
        sh = d.get("region_heat", [])
        if not sh:
            ax.text(0.5, 0.5, "No region data", ha="center", va="center",
                     color=MUTED, fontsize=8*fs, fontfamily="monospace", transform=ax.transAxes)
            return
        states_h = [r["state"]  for r in sh]
        qsos_h   = [r["qsos"]   for r in sh]
        pcts_h   = [r["pct"]    for r in sh]
        worked_h = [r["worked"] for r in sh]
        total_h  = [r["total"]  for r in sh]
        max_q    = max(qsos_h) if any(q > 0 for q in qsos_h) else 1
        y = np.arange(len(states_h))
        for yi, (st, q) in enumerate(zip(states_h, qsos_h)):
            col   = STATE_COLOURS.get(st, MUTED)
            alpha = 0.25 + 0.75*(q/max_q) if max_q else 0.25
            ax.barh(yi, q, color=col, alpha=alpha, height=0.6, zorder=2)
        ax.set_yticks(y); ax.set_yticklabels(states_h, fontfamily="monospace", fontsize=8*fs)
        for tick, st in zip(ax.get_yticklabels(), states_h):
            tick.set_color(STATE_COLOURS.get(st, MUTED))
        ax.set_xlabel("QSOs worked", color=MUTED, fontfamily="monospace", fontsize=7*fs)
        ax.set_facecolor(BG3); ax.grid(axis="x", color=BG2, lw=0.5, zorder=0)
        for sp in ax.spines.values(): sp.set_edgecolor(BG2)
        ax.tick_params(colors=MUTED, labelsize=7.5*fs)
        # Reserve space for the "{worked}/{total} (pct%)" label proportional
        # to fs: both the gap between the bar tip and the label, and the
        # xlim headroom past the longest bar, must grow with the text size
        # or the label collides with the bar (or the next bar) once fs > ~1.
        label_gap = max_q * 0.02 * fs
        for i, (q, p, w, t) in enumerate(zip(qsos_h, pcts_h, worked_h, total_h)):
            if q > 0:
                # w/t count sits just right of the bar tip in muted text
                ax.text(q + label_gap, i, f"{w}/{t}", va="center",
                         fontsize=6.5*fs, color=MUTED, fontfamily="monospace")
                # % label centred above the bar in the state's own colour
                bar_col = STATE_COLOURS.get(states_h[i], MUTED)
                ax.text(q / 2, i + 0.38, f"{p:.0f}%",
                         ha="center", va="bottom",
                         fontsize=6*fs, color=bar_col,
                         fontfamily="monospace", fontweight="bold")
        margin = 1.45 + 0.35 * max(0.0, fs - 1.0)
        ax.set_xlim(0, max(qsos_h)*margin if qsos_h else 1)

    def _draw_personal_bests_on_ax(self, ax, d):
        fs = self._panel_fs(ax)
        pb = d.get("personal_bests", {})
        if not pb:
            ax.text(0.5, 0.5, "No data", ha="center", va="center",
                     color=MUTED, fontsize=8*fs, fontfamily="monospace")
            return
        cur  = pb.get("current_hour_rate", 0)
        prev = pb.get("prev_hour_rate", 0)
        ts2  = "+" if cur > prev else ("-" if cur < prev else "=")
        tc   = GREEN if cur > prev else (ACCENT2 if cur < prev else MUTED)
        best_h     = pb.get("best_hour_rate", 0)
        best_t     = pb.get("best_hour_time")
        best_t_str = best_t.strftime("%H:%M") if best_t else "—"
        zone_cnt      = d.get("zone_cnt", 0)
        zone_band_cnt = d.get("zone_band_cnt", 0)
        shire_mults   = d.get("band_mults", 0)
        total_mults   = shire_mults + zone_band_cnt
        worked_zones  = d.get("worked_zones", [])
        zones_str     = " ".join(str(z) for z in sorted(worked_zones)) if worked_zones else "—"
        rows = [
            ("Current hr rate", f"{cur} Q/hr",               FG),
            ("Prev hr rate",    f"{prev} Q/hr",               MUTED),
            ("Rate trend",      f"{ts2}{abs(cur-prev)} Q/hr", tc),
            ("",                "",                            MUTED),
            ("Best hour",       f"{best_h} Q/hr",             ACCENT3),
            ("  at",            best_t_str + " UTC",          MUTED),
            ("",                "",                            MUTED),
            ("Mult 1",          str(shire_mults),             GREEN),
            ("Mult 2 (zones)",  str(zone_band_cnt),           "#64b5f6"),
            ("Total mults",     str(total_mults),             ACCENT3),
        ]
        y_step = 0.083; y_pos = 0.94
        for label, val, colour in rows:
            if label:
                ax.text(0.04, y_pos, label, ha="left", va="center",
                         fontsize=7.5*fs, color=MUTED, fontfamily="monospace")
                ax.text(0.96, y_pos, val, ha="right", va="center",
                         fontsize=7.5*fs, color=colour, fontfamily="monospace", fontweight="bold")
            y_pos -= y_step

        # "Zones worked" gets its own block below — a long, space-separated
        # list doesn't fit beside its label without overlapping, especially
        # in narrow panels, so it's shown on its own line(s) instead.
        # Some contests (e.g. AADX) have no secondary multiplier type at
        # all, so worked_zones is always empty — skip the block entirely
        # rather than showing an empty dash, which just looks broken.
        if worked_zones:
            ax.text(0.04, y_pos, "Zones worked", ha="left", va="center",
                     fontsize=7.5*fs, color=MUTED, fontfamily="monospace")
            y_pos -= y_step * 0.95
            zones_fs = 7*fs
            ax.text(0.04, y_pos, self._fit_text(ax, zones_str, zones_fs),
                     ha="left", va="center", fontsize=zones_fs, color="#64b5f6",
                     fontfamily="monospace", fontweight="bold")


    def _draw_qso_value_on_ax(self, ax, d):
        """
        "What's my next QSO worth right now?" — per-band breakdown of the
        score increase for one more QSO, using that band's average QSO
        points, under three scenarios:

          +Q   : a plain "fill" QSO (no new multiplier)
          +1M  : a QSO that brings exactly one new band-multiplier
          +2M  : a QSO that brings two new band-multipliers at once
                 (CQWW: a new DXCC entity AND a new CQ zone on that band)

        Late in a big contest, with hundreds of band-mults already logged,
        the +1M/+2M figures can be in the thousands — the whole point being
        to show just how much one more multiplier QSO is worth right now.
        """
        fs = self._ov_fs
        qv = d.get("qso_value")
        sc_keys = qv.get("scenarios") if qv else None
        bands   = qv.get("bands") if qv else None
        if not qv or not sc_keys or not bands:
            ax.text(0.5, 0.5, "No data", ha="center", va="center",
                     color=MUTED, fontsize=8*fs, fontfamily="monospace")
            return

        band_order    = [b for b in qv.get("band_order", list(bands.keys())) if b in bands]
        short_labels  = {"no_mult": "+Q", "one_mult": "+1M", "two_mult": "+2M"}
        n_sc          = len(sc_keys)
        # Push the AVG column right as fs grows so wider band labels
        # ("160m" at 7.5*fs) never collide with it — at fs=1.0 this matches
        # the original 0.32, but it grows with font size instead of
        # staying fixed.
        avg_x         = min(0.32 + 0.05 * max(fs - 1.0, 0), 0.42)
        sc_start      = max(avg_x + 0.22, 0.54)
        sc_xs         = np.linspace(sc_start, 0.97, n_sc) if n_sc > 1 else [0.97]

        # ── Header row ────────────────────────────────────────────────────
        ax.text(0.04, 0.95, "BAND", ha="left", va="center", fontsize=7*fs,
                 color=MUTED, fontfamily="monospace", fontweight="bold")
        ax.text(avg_x, 0.95, "AVG", ha="right", va="center", fontsize=7*fs,
                 color=MUTED, fontfamily="monospace", fontweight="bold")
        for x, sk in zip(sc_xs, sc_keys):
            ax.text(x, 0.95, short_labels.get(sk, sk), ha="right", va="center",
                     fontsize=7*fs, color=MUTED, fontfamily="monospace", fontweight="bold")
        ax.axhline(0.905, color=BG3, lw=0.8)

        # ── Band rows ─────────────────────────────────────────────────────
        n_rows = len(band_order) or 1
        y_step = min(0.115, 0.80 / n_rows)
        y_pos  = 0.94 - y_step

        for band in band_order:
            bd       = bands[band]
            has_data = bd.get("qsos", 0) > 0
            band_col = BAND_COLOURS.get(band.lower(), BAND_COLOURS_DEFAULT)
            txt_col  = FG if has_data else MUTED
            label    = band.lower() if band != "?" else "?"
            ax.text(0.04, y_pos, label, ha="left", va="center", fontsize=7.5*fs,
                     fontweight="bold", color=band_col if has_data else MUTED,
                     fontfamily="monospace")
            ax.text(avg_x, y_pos, f"{bd.get('avg_pts', 0):.1f}", ha="right",
                     va="center", fontsize=7.5*fs, color=txt_col, fontfamily="monospace")
            for x, sk in zip(sc_xs, sc_keys):
                val = bd.get(sk, 0)
                ax.text(x, y_pos, f"{val:,.0f}", ha="right", va="center",
                         fontsize=7.5*fs, color=txt_col, fontfamily="monospace",
                         fontweight="bold" if has_data else "normal")
            y_pos -= y_step

        # ── Footer: current P × M context ────────────────────────────────
        total_pts   = qv.get("total_pts", 0)
        total_mults = qv.get("total_mults", 0)
        ax.text(0.04, max(y_pos + y_step * 0.15, 0.03),
                 f"now: {total_pts:,.0f} pts × {total_mults} mults",
                 ha="left", va="center", fontsize=6.5*fs, color=MUTED,
                 fontfamily="monospace")

    def _draw_last_worked_on_ax(self, ax, d):
        fs = self._ov_fs
        last = d.get("last_worked", [])
        if not last:
            ax.text(0.5, 0.5, "No QSOs yet", ha="center", va="center",
                     color=MUTED, fontsize=8*fs, fontfamily="monospace")
            return
        p = d.get("_plugin", GenericPlugin())
        ax.text(0.04, 0.94, "Call",      ha="left",   va="center", fontsize=7*fs, color=MUTED, fontfamily="monospace")
        ax.text(0.52, 0.94, "Band/Mode", ha="center", va="center", fontsize=7*fs, color=MUTED, fontfamily="monospace")
        ax.text(0.96, 0.94, p.mult_label(), ha="right", va="center", fontsize=7*fs, color=MUTED, fontfamily="monospace")
        ax.axhline(0.90, color=BG3, lw=0.8)
        y_step = 0.155; y_pos = 0.82
        for q in last:
            band_col = BAND_COLOURS.get(q["band"], MUTED)
            reg      = p.region_of_mult(q["mult1"]) if q["mult1"] else ""
            st_col   = STATE_COLOURS.get(reg, MUTED)
            ax.text(0.04, y_pos,      q["call"],   ha="left",  va="center",
                     fontsize=8*fs, fontweight="bold", color=FG, fontfamily="monospace")
            ax.text(0.04, y_pos-0.06, q["time"].strftime("%H:%M"), ha="left", va="center",
                     fontsize=6.5*fs, color=MUTED, fontfamily="monospace")
            ax.text(0.52, y_pos, f"{q['band']} {q['mode']}",
                     ha="center", va="center", fontsize=7.5*fs, color=band_col, fontfamily="monospace")
            ax.text(0.96, y_pos, q["mult1"] or "—",
                     ha="right",  va="center", fontsize=7.5*fs, color=st_col, fontfamily="monospace")
            y_pos -= y_step

    def _draw_operator_times_on_ax(self, ax, d):
        """
        Per-operator on-air vs off-air time, derived from the gaps between
        consecutive QSO timestamps for each Operator value in the log
        (DXLOG.Operator). "On" = sum of inter-QSO gaps <= 30 min;
        "Off" = sum of larger gaps within that operator's first..last QSO span.
        """
        fs = self._panel_fs(ax)
        ops = d.get("operator_times", [])
        if not ops:
            ax.text(0.5, 0.5, "No data", ha="center", va="center",
                     color=MUTED, fontsize=8*fs, fontfamily="monospace")
            return

        def fmt_h(mins):
            return f"{max(0, mins)/60:.1f}h"

        ax.text(0.04, 0.94, "Operator", ha="left",  va="center",
                 fontsize=7*fs, color=MUTED, fontfamily="monospace")
        ax.text(0.97, 0.94, "On / Off", ha="right", va="center",
                 fontsize=7*fs, color=MUTED, fontfamily="monospace")
        ax.axhline(0.90, color=BG3, lw=0.8)

        y_step = 0.21; y_pos = 0.78
        for op in ops[:4]:
            ax.text(0.04, y_pos, op["operator"], ha="left", va="center",
                     fontsize=8.5*fs, fontweight="bold", color=FG, fontfamily="monospace")
            ax.text(0.97, y_pos, fmt_h(op["on_minutes"]), ha="right", va="center",
                     fontsize=7.5*fs, color=GREEN, fontfamily="monospace")
            ax.text(0.97, y_pos - 0.085, fmt_h(op["off_minutes"]), ha="right", va="center",
                     fontsize=7.5*fs, color=ACCENT2, fontfamily="monospace")
            summary = (
                f"{op['qsos']} QSOs  "
                f"{op['first'].strftime('%H:%M')}\u2013{op['last'].strftime('%H:%M')} UTC  "
                f"({op['sessions']} session{'s' if op['sessions'] != 1 else ''})"
            )
            ax.text(0.04, y_pos - 0.085, self._fit_text(ax, summary, 6.5*fs, avail_frac=0.78),
                     ha="left", va="center", fontsize=6.5*fs, color=MUTED, fontfamily="monospace")
            y_pos -= y_step

    def _draw_sparklines_on_gridspec(self, fig, gs, d):
        """
        Draw the 3 hourly sparklines (QSOs/hr, running score, new mults/hr)
        into a 1x3 subgridspec `gs` on `fig`.

        The arrays in d["sparklines"] are sized to the contest's actual
        duration (e.g. 24 buckets for VK Shires, 48 for CQWW) rather than a
        hardcoded 24 — see ContestLog.compute_snapshot(). This draws
        whatever length is supplied, with vertical guide lines at each
        session/day boundary.
        """
        fs = self._ov_fs
        spark = d.get("sparklines", {})
        spark_defs = [
            ("QSOs / Hour",    spark.get("qsos",          [0]*24), ACCENT),
            ("Running Score",  spark.get("running_score", [0]*24), ACCENT3),
            ("New Mults / Hr", spark.get("new_mults",     [0]*24), ACCENT2),
        ]

        # Vertical guide lines at each session/day boundary, derived from the
        # active plugin's session length so 24h and 48h+ contests both get
        # sensible markers (e.g. every 4h for VK Shires, every 12h for CQWW).
        plugin   = d.get("_plugin")
        n        = len(spark_defs[0][1]) or 24
        sess_h   = (plugin.session_config().duration_mins / 60.0) if plugin else 4.0
        sess_h   = sess_h if sess_h > 0 else 4.0
        block_hours = []
        bh = sess_h
        while bh < n:
            block_hours.append(bh)
            bh += sess_h

        if n <= 24:
            tick_step = 4 if n > 8 else 2
        else:
            tick_step = max(4, int(round(sess_h)))
        ticks = [t for t in range(0, n, tick_step)]
        if not ticks:
            ticks = [0]
        last_idx = n - 1
        if ticks[-1] != last_idx:
            ticks.append(last_idx)
        start_h = (plugin.session_config().start_hour or 0) if plugin else 0
        labels = []
        for t in ticks:
            if n <= 24:
                # The final bucket represents [start_h+t, start_h+t+1), so
                # label it with the contest's actual end time rather than
                # the bucket's start hour.
                hr = start_h + t + 1 if t == last_idx else start_h + t
                labels.append(f"{hr % 24:02d}")
            else:
                labels.append(str(t))

        # Cancel any previous sparkline animation so a re-draw while one is
        # still running doesn't leave orphaned after() callbacks.
        for _job in getattr(self, "_spark_anim_jobs", []):
            try: self.after_cancel(_job)
            except Exception: pass
        self._spark_anim_jobs = []

        for si, (title, data, col) in enumerate(spark_defs):
            ax_sp = fig.add_subplot(gs[0, si])
            ax_sp.set_facecolor(BG2)
            # ── Top accent stripe (matches panel_style convention) ────────────
            for spine in ax_sp.spines.values():
                spine.set_visible(False)
            ax_sp.spines["top"].set_visible(True)
            ax_sp.spines["top"].set_edgecolor(col)
            ax_sp.spines["top"].set_linewidth(2.0)
            ax_sp.tick_params(colors=MUTED, labelsize=6.5*fs, length=2)

            x = np.arange(len(data)); y = np.array(data, dtype=float)
            peak = max(y.max(), 1)
            active = [i for i, v in enumerate(data) if v > 0]
            current_val = y[active[-1]] if active else 0
            peak_idx    = int(np.argmax(y))

            for bh in block_hours:
                is_day_edge = abs(bh % 24) < 1e-6
                ax_sp.axvline(bh, color=BG3, lw=1.2 if is_day_edge else 0.8,
                               zorder=0)

            # ── Compute smooth spline once ────────────────────────────────────
            if _SCIPY_AVAILABLE and len(x) > 3:
                x_smooth = np.linspace(x.min(), x.max(), 300)
                spl = make_interp_spline(x, y, k=3)
                y_smooth = spl(x_smooth)
            else:
                x_smooth = x.astype(float)
                y_smooth = y.copy()

            y_smooth_fill = np.clip(y_smooth, 0, None)

            # ── Static fill + glow (drawn immediately, always visible) ────────
            ax_sp.fill_between(x_smooth, y_smooth_fill,
                               color=col, alpha=0.12, zorder=1)
            ax_sp.plot(x_smooth, y_smooth, color=col, lw=6,
                       alpha=0.07, solid_capstyle="round", zorder=2)
            ax_sp.plot(x_smooth, y_smooth, color=col, lw=3,
                       alpha=0.13, solid_capstyle="round", zorder=3)

            # ── Animated progressive draw: line grows left→right ──────────────
            # We draw the sharp foreground line in N_STEPS segments via
            # tkinter after(), revealing the chart like a plotter pen moving
            # across the panel.  Each step extends an existing Line2D's xdata
            # and ydata rather than adding new artists, so it's lightweight.
            N_STEPS   = 30          # number of animation frames
            STEP_MS   = 18          # ms per frame  (~55 fps feel)
            DELAY_MS  = si * 60     # stagger each sparkline by 60 ms

            n_pts = len(x_smooth)
            # Pre-create the line with no data; animation will fill it in
            (anim_line,) = ax_sp.plot([], [], color=col, lw=1.8,
                                       solid_capstyle="round",
                                       antialiased=True, zorder=4)

            def _make_step_fn(line, xs, ys, n, steps, canvas_ref):
                def _step(frame):
                    end_idx = max(2, int((frame / steps) * n))
                    line.set_data(xs[:end_idx], ys[:end_idx])
                    try:
                        canvas_ref.draw_idle()
                    except Exception:
                        pass
                return _step

            step_fn = _make_step_fn(anim_line, x_smooth, y_smooth,
                                     n_pts, N_STEPS,
                                     self.canvas_ov)

            for frame in range(1, N_STEPS + 1):
                delay = DELAY_MS + frame * STEP_MS
                job = self.after(delay, step_fn, frame)
                self._spark_anim_jobs.append(job)

            # ── Peak marker (^ triangle) drawn after animation completes ──────
            def _draw_peak_marker(ax_ref, xs, ys, pidx, c, canvas_ref):
                try:
                    # Find the smoothed y value nearest the raw peak index
                    n_s = len(xs)
                    n_r = len(ys)
                    smooth_pidx = int(round(pidx / max(len(x) - 1, 1) * (n_s - 1)))
                    smooth_pidx = max(0, min(smooth_pidx, n_s - 1))
                    ax_ref.plot(xs[smooth_pidx], ys[smooth_pidx], "^",
                                color=c, ms=5, zorder=5, alpha=0.9,
                                markeredgecolor=BG2, markeredgewidth=0.8)
                    canvas_ref.draw_idle()
                except Exception:
                    pass

            peak_delay = DELAY_MS + N_STEPS * STEP_MS + 40
            peak_job = self.after(
                peak_delay, _draw_peak_marker,
                ax_sp, x_smooth, y_smooth, peak_idx, col, self.canvas_ov
            )
            self._spark_anim_jobs.append(peak_job)

            # ── End-point hollow jewel dot ────────────────────────────────────
            if active:
                lh = active[-1]
                ax_sp.plot(lh, y[lh], "o", color=BG2,
                           markeredgecolor=col, markeredgewidth=1.5,
                           ms=5.5, zorder=6)

            # ── Hero current value (large, top-left) ──────────────────────────
            ax_sp.text(0.02, 0.97, f"{current_val:.0f}",
                        transform=ax_sp.transAxes,
                        fontsize=11*fs, fontweight="bold", color=col,
                        fontfamily="monospace", va="top", zorder=6)
            ax_sp.text(0.02, 0.72, title,
                        transform=ax_sp.transAxes,
                        fontsize=6.5*fs, color=MUTED,
                        fontfamily="monospace", va="top")
            ax_sp.text(0.99, 0.97, f"peak {int(peak)}",
                        transform=ax_sp.transAxes,
                        fontsize=6.5*fs, color=col,
                        fontfamily="monospace", va="top", ha="right")

            ax_sp.set_xlim(0, max(len(data) - 1, 1))
            ax_sp.set_ylim(-peak*0.05, peak*1.35)
            ax_sp.set_xticks(ticks)
            ax_sp.set_xticklabels(labels,
                                   color=MUTED, fontsize=6*fs, fontfamily="monospace")
            ax_sp.set_yticks([])

            # ── Register for hover tooltip ────────────────────────────────────
            if not hasattr(self, "_spark_tip_meta"):
                self._spark_tip_meta = {}
            self._spark_tip_meta[ax_sp] = (title, y, start_h, labels, ticks)

    def _draw_region_bars_on_ax(self, ax, d):
        """Per-region stacked completion bar chart.  Works for any plugin with regions."""
        fs = self._panel_fs(ax, ref_w=141.0, ref_h=180.0)
        if not self.log:
            return
        p = d.get("_plugin", self.log.plugin)
        regions = p.region_list()
        if not regions:
            ax.text(0.5, 0.5, "No region data for this contest",
                     ha="center", va="center", color=MUTED, fontsize=8*fs,
                     fontfamily="monospace", transform=ax.transAxes)
            return

        mbr          = self.log.mults_by_region()
        worked_data  = [len(mbr.get(st, {}).get("worked",  [])) for st in regions]
        missing_data = [len(mbr.get(st, {}).get("missing", [])) for st in regions]
        totals       = [w + m for w, m in zip(worked_data, missing_data)]
        state_bar_cols = [STATE_COLOURS.get(st, MUTED) for st in regions]
        x = np.arange(len(regions))
        # Cancel any in-flight bar animations from a previous draw.
        for _job in getattr(self, "_bar_anim_jobs", []):
            try: self.after_cancel(_job)
            except Exception: pass
        self._bar_anim_jobs = []

        bars_w = []
        for xi, (w, col) in enumerate(zip(worked_data, state_bar_cols)):
            # Start height at 0; animation will grow to final value
            b = ax.bar(xi, 0, color=col, alpha=0.90, width=0.55)
            bars_w.append(b[0])
        bars_m = []
        for xi, (w, m, col) in enumerate(zip(worked_data, missing_data, state_bar_cols)):
            bm = ax.bar(xi, 0, color=col, alpha=0.15, width=0.55, bottom=0,
                        edgecolor=col, lw=0.4)
            bars_m.append(bm[0])

        # Grow bars from 0 → final with an ease-out curve
        N_BAR_STEPS = 24
        BAR_STEP_MS = 18
        canvas_ref  = self.canvas_ov

        def _make_bar_step(b_worked, b_missing, w_vals, m_vals, n_steps):
            def _step(frame):
                t     = frame / n_steps
                eased = 1.0 - (1.0 - t) ** 2
                for bar, w in zip(b_worked, w_vals):
                    bar.set_height(w * eased)
                for bar, w, m in zip(b_missing, w_vals, m_vals):
                    bar.set_height(m * eased)
                    bar.set_y(w * eased)
                try:
                    canvas_ref.draw_idle()
                except Exception:
                    pass
            return _step

        bar_step_fn = _make_bar_step(bars_w, bars_m,
                                      worked_data, missing_data, N_BAR_STEPS)
        for frame in range(1, N_BAR_STEPS + 1):
            job = self.after(frame * BAR_STEP_MS, bar_step_fn, frame)
            self._bar_anim_jobs.append(job)
        max_total = max(totals) if totals else 1
        # Headroom above the bars needs to grow with fs, since both the
        # above-bar totals label and (sometimes) the bumped-up % label need
        # room there. This must be set *before* the transform-based pixel
        # measurement below, or that measurement reads matplotlib's
        # transient auto-scaled range from the bar() calls above instead of
        # the actual final range, making the in-bar-vs-above-bar decision
        # wrong.
        ax.set_ylim(0, max_total * (1.12 + 0.08 * max(0.0, fs - 1.0)))
        # The in-bar "%" label only fits if the worked segment is tall
        # enough at the current font size; otherwise it spills above/below
        # the bar into the next element. Estimate the label's height in
        # data units (font points -> approx data units via the axes' y
        # pixel-per-unit ratio) and place it above the bar instead of
        # inside when it wouldn't fit, rather than letting it overlap.
        ax.figure.canvas.draw()  # ensure transforms reflect the ylim set above
        try:
            y0_px = ax.transData.transform((0, 0))[1]
            y1_px = ax.transData.transform((0, max(max_total, 1)))[1]
            px_per_unit = abs(y0_px - y1_px) / max(max_total, 1)
        except Exception:
            px_per_unit = 0
        label_fontsize = 7.5 * fs
        label_h_data = (label_fontsize * (ax.figure.dpi / 72.0) * 1.3) / px_per_unit \
                       if px_per_unit else 0
        bar_label_artists = []
        for bar, w, tot, col in zip(bars_w, worked_data, totals, state_bar_cols):
            if tot > 0 and w > 0:
                if w >= label_h_data:
                    t = ax.text(bar.get_x()+bar.get_width()/2, w/2,
                                f"{w/tot*100:.0f}%", ha="center", va="center",
                                fontsize=label_fontsize, color=BG, fontfamily="monospace",
                                fontweight="bold", alpha=0.0)
                else:
                    t = ax.text(bar.get_x()+bar.get_width()/2, w + max_total*0.03,
                                f"{w/tot*100:.0f}%", ha="center", va="bottom",
                                fontsize=label_fontsize, color=col, fontfamily="monospace",
                                fontweight="bold", alpha=0.0)
                bar_label_artists.append(t)
        above_gap = max_total * (0.01 + 0.015 * max(0.0, fs - 1.0))
        for xi, (w, m) in enumerate(zip(worked_data, missing_data)):
            t = ax.text(xi, w+m + above_gap, f"{w}/{w+m}", ha="center", va="bottom",
                         fontsize=6.5*fs, color=MUTED, fontfamily="monospace", alpha=0.0)
            bar_label_artists.append(t)

        # Fade bar labels in after bars finish growing
        BAR_LABEL_FADE_STEPS = 8
        BAR_LABEL_FADE_MS    = 20
        bar_done_delay = N_BAR_STEPS * BAR_STEP_MS + 20

        def _make_label_fade(artists, n_steps):
            def _fade(frame):
                alpha = frame / n_steps
                for artist in artists:
                    try: artist.set_alpha(alpha)
                    except Exception: pass
                try: canvas_ref.draw_idle()
                except Exception: pass
            return _fade

        label_fade_fn = _make_label_fade(bar_label_artists, BAR_LABEL_FADE_STEPS)
        for frame in range(1, BAR_LABEL_FADE_STEPS + 1):
            job = self.after(bar_done_delay + frame * BAR_LABEL_FADE_MS,
                             label_fade_fn, frame)
            self._bar_anim_jobs.append(job)
        ax.set_xticks(x); ax.set_xticklabels(regions, fontfamily="monospace", fontsize=9*fs)
        for tick, col in zip(ax.get_xticklabels(), state_bar_cols): tick.set_color(col)
        ax.tick_params(colors=MUTED, labelsize=8*fs)
        ml = p.mult_label()
        ax.set_ylabel(f"{ml}s", color=MUTED, fontfamily="monospace", fontsize=8*fs)
        for sp in ax.spines.values(): sp.set_edgecolor(BG3)

    # ── Tab refresh methods ───────────────────────────────────────────────────

    def _refresh_missing(self):
        for i in self.miss_tree.get_children():
            self.miss_tree.delete(i)
        if not self.log or not self.log.plugin.has_missing_tab():
            return
        flt    = self.miss_region_var.get()
        p      = self.log.plugin
        worked = self.log.worked_mults()
        _row = 0
        for m in p.mult_list():
            reg = p.region_of_mult(m) or ""
            if flt != "ALL" and reg != flt:
                continue
            if m not in worked:
                _zebra_insert(self.miss_tree, _row, (m, reg, "Target Multiplier is open."))
                _row += 1

    def _schedule_worked_refresh(self):
        if self.log:
            # Only do the per-row countdown work when the Worked tab is active.
            # The tab is refreshed in full by _on_tab_changed when the user
            # switches to it, so skipping updates while it is hidden is safe.
            try:
                if str(self.nb.select()) == str(self.tab_worked):
                    self._update_worked_countdowns()
            except Exception:
                pass
        self.after(1000, self._schedule_worked_refresh)

    def _update_worked_countdowns(self):
        """Update countdown column using pre-cached block_end datetimes (no string parsing)."""
        if not self.log:
            return
        cache = getattr(self, "_work_block_end_cache", {})
        if not cache:
            return
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        for iid in self.work_tree.get_children():
            block_end = cache.get(iid)
            if block_end is None:
                continue
            try:
                remaining = (block_end - now).total_seconds()
                if remaining <= 0:
                    countdown = "Workable"
                else:
                    rh = int(remaining // 3600)
                    rm = int((remaining % 3600) // 60)
                    rs = int(remaining % 60)
                    countdown = f"{rh}h {rm:02d}m {rs:02d}s"
                vals = list(self.work_tree.item(iid, "values"))
                if len(vals) >= 8 and vals[7] != countdown:
                    vals[7] = countdown
                    self.work_tree.item(iid, values=vals)
            except Exception:
                pass

    def _refresh_worked(self):
        for i in self.work_tree.get_children():
            self.work_tree.delete(i)

        cs  = self.log.contest_start()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        dur = self.log._session_cfg.duration_mins * 60
        lbl = self.log._session_cfg.label_prefix
        self._work_block_end_cache = {}  # iid → block_end datetime for countdown ticks

        for _qi, q in enumerate(reversed(self.log.qso_timeline())):
            block_nr  = "—"
            countdown = "—"
            if cs:
                try:
                    elapsed   = (q["time"] - cs).total_seconds()
                    bn        = int(elapsed // dur)
                    block_nr  = f"{lbl}{bn + 1}"
                    block_end = cs + timedelta(seconds=(bn + 1) * dur)
                    remaining = (block_end - now).total_seconds()
                    if remaining <= 0:
                        countdown = "Workable"
                    else:
                        rh = int(remaining // 3600)
                        rm = int((remaining % 3600) // 60)
                        rs = int(remaining % 60)
                        countdown = f"{rh}h {rm:02d}m {rs:02d}s"
                except Exception:
                    pass

            iid = q.get("qso_id") or ""
            _zebra_insert(self.work_tree, _qi,
                values=(
                    q["call"],
                    q["band"],
                    q["mode"],
                    q["time"].strftime("%H:%M:%S"),
                    q["mult1"],
                    q["pts"],
                    block_nr,
                    countdown,
                ),
                iid=iid,
            )
            # Cache block_end for countdown updates (avoids re-parsing the time string)
            if cs and iid:
                try:
                    elapsed = (q["time"] - cs).total_seconds()
                    bn2 = int(elapsed // dur)
                    self._work_block_end_cache[iid] = cs + timedelta(seconds=(bn2 + 1) * dur)
                except Exception:
                    pass

        # ── Micro-interaction: flash any newly appeared rows in accent colour ─
        current_iids = set(self.work_tree.get_children())
        new_iids = list(current_iids - getattr(self, "_work_tree_prev_iids", set()))
        if new_iids:
            self._flash_tree_rows(self.work_tree, new_iids)
        self._work_tree_prev_iids = current_iids

    def _work_tree_right_click(self, event):
        row = self.work_tree.identify_row(event.y)
        if row:
            if row not in self.work_tree.selection():
                self.work_tree.selection_add(row)
            self._work_ctx.post(event.x_root, event.y_root)

    def _delete_selected_qso(self):
        sel = self.work_tree.selection()
        if not sel:
            messagebox.showinfo("No selection",
                                "Please select one or more QSO rows to delete.")
            return
        qsos_to_delete = [q for q in self.log.qsos if q.get("qso_id") in sel]
        if not qsos_to_delete:
            return
        if len(qsos_to_delete) == 1:
            q = qsos_to_delete[0]
            msg = (f"Permanently delete QSO with {q['call']} at "
                   f"{q['time'].strftime('%H:%M')} UTC from the database?")
        else:
            calls = ", ".join(q["call"] for q in qsos_to_delete)
            msg = f"Permanently delete {len(qsos_to_delete)} QSOs ({calls}) from the database?"
        if not messagebox.askyesno("Confirm Delete", msg):
            return
        errors = []
        for qso in qsos_to_delete:
            try:
                self.log.delete_qso(qso["qso_id"], qso.get("_table", "DXLOG"))
            except Exception as e:
                logging.exception("Delete failed for %s", qso["qso_id"])
                errors.append(f"{qso['call']}: {e}")
        if errors:
            messagebox.showerror("Delete Failed", "\n".join(errors))
        self._refresh_all_views()

    def _ensure_fig_rate(self):
        """Create fig_rate / canvas_rate on first use (lazy init)."""
        if self.fig_rate is not None:
            return
        self.fig_rate = Figure(figsize=(12, 3.8), facecolor=BG2)
        self.ax_rate  = self.fig_rate.add_subplot(111)
        self.ax_rate.set_facecolor(BG2)
        self.canvas_rate = FigureCanvasTkAgg(self.fig_rate, master=self._rate_fig_frame)
        self.canvas_rate.get_tk_widget().configure(bg=BG2)
        self.canvas_rate.get_tk_widget().pack(fill="both", expand=True)

    def _refresh_rate(self):
        self._ensure_fig_rate()
        self.ax_rate.clear()
        for i in self.sess_tree.get_children():
            self.sess_tree.delete(i)

        sessions = self.log.rate_by_session()
        if not sessions:
            self.canvas_rate.draw_idle()
            return

        SESSION_PALETTE = THEMES[_ACTIVE_THEME]["SESSION_PALETTE"]

        for _si, s in enumerate(sessions):
            start_str = s["start"].strftime("%H:%M")
            end_str   = s["end"].strftime("%H:%M")
            if s["end"].day != s["start"].day:
                end_str += "(+1)"
            _zebra_insert(self.sess_tree, _si, (
                f"{self.log._session_cfg.label_prefix}{s['session']}",
                f"{start_str} – {end_str}",
                s["qsos"], s["pts"], s["new_mults"],
                s["cum_mults"], f"{s['running_score']:,}",
            ))

        all_hours = []; all_counts = []; all_colours = []
        for s in sessions:
            sn_idx = s["session"] - 1
            colour = SESSION_PALETTE[sn_idx % len(SESSION_PALETTE)]
            for hour_dt, count in s["by_hour"]:
                all_hours.append(hour_dt.strftime("%H:%M"))
                all_counts.append(count)
                all_colours.append(colour)

        if not all_hours:
            self.canvas_rate.draw_idle()
            return

        x    = np.arange(len(all_hours))
        bars = self.ax_rate.bar(x, all_counts, color=all_colours, width=0.72, zorder=2)

        # ── Anti-aliased, hairline-bordered bars (eliminates pixel-jagged edges) ──
        for patch in self.ax_rate.patches:
            patch.set_antialiased(True)
            patch.set_linewidth(0.5)

        for bar, count in zip(bars, all_counts):
            if count > 0:
                self.ax_rate.text(
                    bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                    str(count), ha="center", va="bottom",
                    color=FG, fontsize=8, fontname="Consolas",
                )

        pos = 0
        for s in sessions[:-1]:
            pos += len(s["by_hour"])
            self.ax_rate.axvline(pos - 0.5, color=MUTED, lw=1,
                                  linestyle="--", alpha=0.5, zorder=1)

        legend_patches = [
            mpatches.Patch(
                color=SESSION_PALETTE[s["session"]-1],
                label=s["label"]
            ) for s in sessions
        ]
        self.ax_rate.legend(handles=legend_patches,
                            facecolor=BG3, edgecolor="none",
                            labelcolor=FG, fontsize=8, loc="upper right")

        self.ax_rate.set_xticks(x)
        self.ax_rate.set_xticklabels(all_hours, rotation=45, ha="right",
                                      color=MUTED, fontsize=8)
        self.ax_rate.set_ylabel("QSOs / hour", color=MUTED,
                                 fontname="Consolas", fontsize=9)
        self.ax_rate.tick_params(colors=MUTED, labelsize=8)
        self.ax_rate.set_facecolor(BG2)
        self.ax_rate.grid(axis="y", color=BG3, linewidth=0.5, zorder=0)
        for spine in self.ax_rate.spines.values(): spine.set_edgecolor(BG3)
        self.fig_rate.patch.set_facecolor(BG2)
        self.fig_rate.tight_layout(pad=1.2)
        self.canvas_rate.draw_idle()

    def _refresh_bands(self):
        for i in self.band_tree.get_children():
            self.band_tree.delete(i)
        bb = self.log.band_breakdown()
        for _bi, b in enumerate(sorted(bb.keys())):
            _zebra_insert(self.band_tree, _bi,
                (b, bb[b]["valid"], bb[b]["dupe"], len(bb[b]["mults"])))

    def _refresh_dupes(self):
        for i in self.dupe_tree.get_children():
            self.dupe_tree.delete(i)
        _, bc = self.log.dupe_analysis()
        for _di, (call, count) in enumerate(
                sorted(bc.items(), key=lambda x: x[1], reverse=True)[:25]):
            _zebra_insert(self.dupe_tree, _di, (call, count))

    def _ensure_fig_prop(self):
        """Create fig_prop / canvas_prop on first use (lazy init)."""
        if self.fig_prop is not None:
            return
        self.fig_prop = Figure(figsize=(12, 5.0), facecolor=BG2)
        self.ax_prop  = self.fig_prop.add_subplot(111)
        self.ax_prop.set_facecolor(BG2)
        self.canvas_prop = FigureCanvasTkAgg(self.fig_prop, master=self._prop_fig_frame)
        self.canvas_prop.get_tk_widget().configure(bg=BG2)
        self.canvas_prop.get_tk_widget().pack(fill="both", expand=True)

    def _get_prop_cmap(self):
        """Return cached propagation colormap; rebuild only when theme changes."""
        theme_key = _ACTIVE_THEME
        if getattr(self, "_prop_cmap_theme", None) != theme_key:
            self._prop_cmap = LinearSegmentedColormap.from_list(
                "vk_prop", THEMES[theme_key]["PROP_GRAD"], N=256)
            self._prop_cmap_theme = theme_key
        return self._prop_cmap

    def _refresh_propagation(self):
        self._ensure_fig_prop()
        self.fig_prop.clear()
        ax = self.fig_prop.add_subplot(111)
        ax.set_facecolor(BG2)

        p        = self.log.plugin
        regions  = p.region_list()
        all_hours = list(range(24))

        # Use cached colormap; only rebuild when theme changes
        prop_cmap = self._get_prop_cmap()


        if regions:
            # ── Mode A: region × hour (VKShires and any plugin with regions) ──
            if hasattr(self, "_prop_title_lbl"):
                self._prop_title_lbl.config(
                    text="Propagation Heatmap \u2014 Mults Worked by Hour (UTC)")
            if hasattr(self, "_prop_cell_lbl"):
                self._prop_cell_lbl.config(
                    text="    |    Cell = QSOs in that region during that UTC hour")

            region_idx = {r: i for i, r in enumerate(regions)}
            matrix     = np.zeros((len(regions), 24))
            ml_set     = set(p.mult_list())
            for q in self.log.qso_timeline():
                if not q["dupe"] and q["mult1"] in ml_set and q.get("time"):
                    reg = p.region_of_mult(q["mult1"]) or regions[0]
                    if reg in region_idx:
                        matrix[region_idx[reg]][q["time"].hour] += 1

            row_labels = regions
            y_label    = "Region"

        else:
            # ── Mode B: band × hour fallback for open-ended plugins (VK RD etc.) ──
            if hasattr(self, "_prop_title_lbl"):
                self._prop_title_lbl.config(
                    text="Propagation Heatmap \u2014 Band Activity by Hour (UTC)")
            if hasattr(self, "_prop_cell_lbl"):
                self._prop_cell_lbl.config(
                    text="    |    Cell = QSOs on that band during that UTC hour")

            BAND_ORDER = ["160M", "80M", "40M", "20M", "15M", "10M", "6M", "2M"]
            bands_present = sorted(
                {q["band"] for q in self.log.qso_timeline()
                 if not q["dupe"] and q.get("band")},
                key=lambda b: BAND_ORDER.index(b) if b in BAND_ORDER else 99
            )
            if not bands_present:
                ax.text(0.5, 0.5, "No QSO data available",
                        ha="center", va="center", color=MUTED, fontsize=11,
                        fontfamily="monospace", transform=ax.transAxes)
                self.fig_prop.patch.set_facecolor(BG2)
                self.canvas_prop.draw_idle()
                return

            band_idx = {b: i for i, b in enumerate(bands_present)}
            matrix   = np.zeros((len(bands_present), 24))
            for q in self.log.qso_timeline():
                if not q["dupe"] and q.get("band") in band_idx and q.get("time"):
                    matrix[band_idx[q["band"]]][q["time"].hour] += 1

            row_labels = bands_present
            y_label    = "Band"

        # ── Common rendering ─────────────────────────────────────────────────
        im = ax.imshow(matrix, cmap=prop_cmap, aspect="auto",
                       vmin=0, vmax=max(matrix.max(), 1))

        thresh = matrix.max() * 0.85
        for row in range(len(row_labels)):
            for col in range(24):
                val = int(matrix[row][col])
                if val > 0:
                    txt_col = BG if matrix[row][col] >= thresh else FG
                    ax.text(col, row, str(val), ha="center", va="center",
                            fontsize=7, color=txt_col,
                            fontfamily="monospace", fontweight="bold")

        ax.set_yticks(range(len(row_labels)))
        ax.set_yticklabels(row_labels, color=FG, fontfamily="monospace", fontsize=9)
        ax.set_xticks(all_hours)
        ax.set_xticklabels([f"{h:02d}" for h in all_hours],
                           color=FG, fontsize=8, fontfamily="monospace")
        ax.set_xlabel("UTC Hour", color=MUTED, fontfamily="monospace", fontsize=9)
        ax.set_ylabel(y_label,    color=MUTED, fontfamily="monospace", fontsize=9)
        ax.tick_params(colors=MUTED)
        for spine in ax.spines.values():
            spine.set_edgecolor(BG3)

        cbar = self.fig_prop.colorbar(im, ax=ax, pad=0.01, fraction=0.025)
        cbar.ax.tick_params(colors=MUTED, labelsize=8)
        cbar.ax.yaxis.label.set_color(MUTED)
        cbar.set_label("QSOs", color=MUTED, fontfamily="monospace", fontsize=8)

        self.fig_prop.patch.set_facecolor(BG2)
        self.fig_prop.tight_layout(pad=1.2)
        self.canvas_prop.draw_idle()

    def _refresh_debug(self):
        for i in self.debug_tree.get_children():
            self.debug_tree.delete(i)
        if not self.log:
            return
        for _dbi, q in enumerate(reversed(self.log.qso_timeline())):
            _zebra_insert(self.debug_tree, _dbi, (
                q["call"],
                q.get("raw_mult", ""),
                q.get("mult1", ""),
                q.get("mult_source", ""),
                q["band"],
                q["time"].strftime("%H:%M"),
            ))


    # ═══════════════════════════════════════════════════════════════════════════
    # ── Score Trajectory Replay tab ─────────────────────────────────────────
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_replay_tab(self):
        f = self.tab_replay
        f.configure(bg=BG2)

        # ── State ────────────────────────────────────────────────────────────
        self._replay_data      = []   # list of per-hour snapshots
        self._replay_pos       = 0    # current scrubber position (0-based hour index)
        self._replay_playing   = False
        self._replay_play_job  = None

        # ── Header row ───────────────────────────────────────────────────────
        hdr = tk.Frame(f, bg=BG2)
        hdr.pack(fill="x", padx=12, pady=(8, 2))
        tk.Label(hdr, text="⏪  Score Trajectory Replay",
                 font=FONT_H, fg=ACCENT, bg=BG2).pack(side="left")
        self._replay_time_var = tk.StringVar(value="")
        tk.Label(hdr, textvariable=self._replay_time_var,
                 font=("Consolas", 11, "bold"), fg=ACCENT3, bg=BG2).pack(side="left", padx=18)
        self._replay_score_var = tk.StringVar(value="")
        tk.Label(hdr, textvariable=self._replay_score_var,
                 font=("Consolas", 10), fg=FG, bg=BG2).pack(side="left")

        # ── Matplotlib chart ─────────────────────────────────────────────────
        # Figure created lazily on first refresh to save startup memory.
        self._replay_fig_frame = tk.Frame(f, bg=BG2)
        self._replay_fig_frame.pack(fill="both", expand=True, padx=12, pady=(2, 0))
        self.fig_replay        = None
        self._replay_ax_score  = None
        self._replay_ax_rate   = None
        self._replay_ax_mults  = None
        self.canvas_replay     = None

        # ── Scrubber row ─────────────────────────────────────────────────────
        scrub_frame = tk.Frame(f, bg=BG2)
        scrub_frame.pack(fill="x", padx=12, pady=(4, 2))

        self._replay_lbl_start = tk.Label(scrub_frame, text="00:00",
                                           font=FONT_S, fg=MUTED, bg=BG2, width=6)
        self._replay_lbl_start.pack(side="left")

        self._replay_scale_var = tk.IntVar(value=0)
        self._replay_scale = tk.Scale(
            scrub_frame,
            variable=self._replay_scale_var,
            from_=0, to=23,
            orient="horizontal",
            showvalue=False,
            bg=BG2, fg=ACCENT,
            troughcolor=BG3,
            activebackground=ACCENT2,
            highlightthickness=0,
            sliderrelief="flat",
            bd=0,
            length=900,
            command=self._on_replay_scrub,
        )
        self._replay_scale.pack(side="left", fill="x", expand=True, padx=6)
        self._replay_lbl_end = tk.Label(scrub_frame, text="23:00",
                                         font=FONT_S, fg=MUTED, bg=BG2, width=6)
        self._replay_lbl_end.pack(side="left")

        # ── Transport controls ────────────────────────────────────────────────
        ctrl_row = tk.Frame(f, bg=BG2)
        ctrl_row.pack(fill="x", padx=12, pady=(2, 8))

        self._replay_play_btn = self._btn(ctrl_row, "▶  Play", self._replay_play_pause)
        self._replay_play_btn.pack(side="left", padx=(0, 6))

        self._btn(ctrl_row, "◀◀  Start", lambda: self._replay_jump(0),
                  style="secondary").pack(side="left", padx=(0, 4))
        self._btn(ctrl_row, "−1hr", lambda: self._replay_step(-1),
                  style="secondary").pack(side="left", padx=(0, 4))
        self._btn(ctrl_row, "+1hr", lambda: self._replay_step(+1),
                  style="secondary").pack(side="left", padx=(0, 4))
        self._btn(ctrl_row, "End ▶▶", lambda: self._replay_jump(-1),
                  style="secondary").pack(side="left", padx=(0, 4))

        # ── Speed slider (0.25× – 8×, continuous, ease-out feel) ──────────────
        tk.Label(ctrl_row, text="  Speed:", font=FONT_S, fg=MUTED, bg=BG2).pack(
            side="left", padx=(10, 2))
        self._replay_speed_multiplier = tk.DoubleVar(value=1.0)
        self._replay_speed_lbl_var    = tk.StringVar(value="1.0×")

        speed_lbl = tk.Label(ctrl_row, textvariable=self._replay_speed_lbl_var,
                             font=(UI_FONT, 9, "bold"), fg=ACCENT, bg=BG2, width=5, anchor="e")
        speed_lbl.pack(side="left")

        def _on_speed_slide(val):
            mult = round(float(val) * 4) / 4   # snap to 0.25 increments
            mult = max(0.25, min(8.0, mult))
            self._replay_speed_multiplier.set(mult)
            self._replay_speed_lbl_var.set(f"{mult:.2g}×")

        speed_scale = tk.Scale(
            ctrl_row,
            variable=self._replay_speed_multiplier,
            from_=0.25, to=8.0, resolution=0.25,
            orient="horizontal", showvalue=False,
            bg=BG2, fg=ACCENT,
            troughcolor=BG3, activebackground=ACCENT2,
            highlightthickness=0, sliderrelief="flat", bd=0,
            length=160,
            command=_on_speed_slide,
        )
        speed_scale.pack(side="left", padx=(2, 12))
        _Tooltip(speed_scale,
                 "Playback speed multiplier: 0.25x (slow) to 8x (fast).\n"
                 "Drag right for faster replay, left for slow-motion.")
        # Keep the old StringVar alive so _replay_speed_ms can still use it
        self._replay_speed_var = tk.StringVar(value="1× (1s)")

        # Event log
        tk.Label(ctrl_row, text="  Event:", font=FONT_S, fg=MUTED, bg=BG2).pack(side="left", padx=(10, 4))
        self._replay_event_var = tk.StringVar(value="—")
        tk.Label(ctrl_row, textvariable=self._replay_event_var,
                 font=("Consolas", 9), fg=ACCENT2, bg=BG2, width=60,
                 anchor="w").pack(side="left")

        _Tooltip(self._replay_scale,
                 "Drag the scrubber to replay your score building hour-by-hour.\n"
                 "The chart shows cumulative score (top), QSO rate (middle) and\n"
                 "new multipliers (bottom) up to the selected hour.\n"
                 "Events like rate spikes, band changes, and score stalls are annotated.")

    # ── Replay data builder ──────────────────────────────────────────────────

    def _replay_build_data(self):
        """
        Build per-hour snapshots from self.log for the replay scrubber.
        Returns a list of dicts, one per UTC hour that has any activity,
        sorted chronologically.  Each dict contains cumulative totals and
        per-hour deltas so the chart can animate incrementally.
        """
        if not self.log or not self.log.qsos:
            return []

        valid = sorted(
            [q for q in self.log.qsos if not q["dupe"]],
            key=lambda q: q["time"]
        )
        if not valid:
            return []

        # Build hour-keyed buckets spanning first→last QSO
        first_h = valid[0]["time"].replace(minute=0, second=0, microsecond=0)
        last_h  = valid[-1]["time"].replace(minute=0, second=0, microsecond=0)
        all_hours = []
        cur = first_h
        while cur <= last_h:
            all_hours.append(cur)
            cur += timedelta(hours=1)

        qso_by_hour   = {h: [] for h in all_hours}
        for q in valid:
            h = q["time"].replace(minute=0, second=0, microsecond=0)
            if h in qso_by_hour:
                qso_by_hour[h].append(q)

        snapshots = []
        qsos_so_far = []
        seen_mults  = set()

        for h in all_hours:
            hour_qs  = qso_by_hour[h]
            qsos_so_far.extend(hour_qs)

            # New mults this hour
            new_mults_this_hour = 0
            for q in hour_qs:
                if q.get("is_mult1") == 1 and q["mult1"]:
                    key = (q["mult1"], q["band"], q["mode"])
                    if key not in seen_mults:
                        seen_mults.add(key)
                        new_mults_this_hour += 1
                if q.get("is_mult2") == 1 and q.get("cqz"):
                    key = (q["cqz"], q["band"], q["mode"])
                    if key not in seen_mults:
                        seen_mults.add(key)
                        new_mults_this_hour += 1

            cum_score = self.log.plugin.running_score_for_sparkline(qsos_so_far)
            prev_score = snapshots[-1]["cum_score"] if snapshots else 0
            score_delta = cum_score - prev_score

            # Detect notable bands this hour
            bands_this_hour = list({q["band"] for q in hour_qs if q.get("band")})

            snapshots.append({
                "hour":            h,
                "hour_label":      h.strftime("%H:%M"),
                "qsos_this_hour":  len(hour_qs),
                "cum_qsos":        len(qsos_so_far),
                "cum_score":       cum_score,
                "score_delta":     score_delta,
                "cum_mults":       len(seen_mults),
                "new_mults":       new_mults_this_hour,
                "bands":           bands_this_hour,
            })

        return snapshots

    def _replay_event_text(self, snapshots, idx):
        """Return a short annotation string describing what happened at this hour."""
        if idx >= len(snapshots):
            return "—"
        s = snapshots[idx]

        notes = []

        # Best rate in log?
        all_rates = [ss["qsos_this_hour"] for ss in snapshots]
        max_rate  = max(all_rates) if all_rates else 0
        if max_rate > 0 and s["qsos_this_hour"] == max_rate and max_rate > 2:
            notes.append(f"🏆 Best hour — {max_rate} QSOs")

        # Zero rate (dead conditions)
        if s["qsos_this_hour"] == 0:
            notes.append("💀 Dead — no QSOs this hour")
        elif s["qsos_this_hour"] <= 2 and idx > 0:
            notes.append(f"📉 Slow — only {s['qsos_this_hour']} QSO(s)")

        # Mult bonanza
        if s["new_mults"] >= 3:
            notes.append(f"🎯 {s['new_mults']} new mults found")

        # Score stall
        if idx > 1 and s["score_delta"] == 0 and snapshots[idx - 1]["score_delta"] == 0:
            notes.append("⏸ Score stalled — check band/mult strategy")

        # Big score jump
        scores = [ss["cum_score"] for ss in snapshots]
        max_score = max(scores) if scores else 1
        if max_score > 0 and s["score_delta"] > 0:
            pct_of_total = s["score_delta"] / max_score * 100
            if pct_of_total >= 15:
                notes.append(f"🚀 Score +{s['score_delta']:,} (+{pct_of_total:.0f}% of total)")

        # Band info
        if s["bands"]:
            notes.append(f"📡 {', '.join(sorted(s['bands']))}")

        return "   |   ".join(notes) if notes else f"{s['qsos_this_hour']} QSOs this hour"

    # ── Replay rendering ──────────────────────────────────────────────────────

    def _replay_draw(self, pos):
        """Redraw the replay chart showing data up to and including hour at `pos`."""
        self._ensure_fig_replay()
        snapshots = self._replay_data
        if not snapshots:
            return

        pos = max(0, min(pos, len(snapshots) - 1))

        labels      = [s["hour_label"] for s in snapshots]
        all_scores  = [s["cum_score"]      for s in snapshots]
        all_rates   = [s["qsos_this_hour"] for s in snapshots]
        all_mults   = [s["new_mults"]      for s in snapshots]

        # Visible slice (up to pos inclusive); rest = ghost
        n   = len(snapshots)
        x   = np.arange(n)

        self.fig_replay.clear()
        gs = self.fig_replay.add_gridspec(
            3, 1, hspace=0.12,
            left=0.06, right=0.97, top=0.95, bottom=0.12
        )
        ax_s = self.fig_replay.add_subplot(gs[0])   # cumulative score
        ax_r = self.fig_replay.add_subplot(gs[1])   # QSO rate
        ax_m = self.fig_replay.add_subplot(gs[2])   # new mults

        def style_ax(ax):
            ax.set_facecolor(BG2)
            for sp in ax.spines.values():
                sp.set_edgecolor(BG3)
            ax.tick_params(colors=MUTED, labelsize=7)

        style_ax(ax_s); style_ax(ax_r); style_ax(ax_m)

        # ── Score line ───────────────────────────────────────────────────────
        # Future ghost
        if pos < n - 1:
            ax_s.plot(x, all_scores, color=BG3, lw=1.2, zorder=1)
        # Revealed portion
        rx = x[:pos + 1]
        ry = all_scores[:pos + 1]
        ax_s.fill_between(rx, ry, alpha=0.15, color=ACCENT3, zorder=2)
        ax_s.plot(rx, ry, color=ACCENT3, lw=2.2, solid_capstyle="round", zorder=3)
        if len(rx):
            ax_s.plot(rx[-1], ry[-1], "o", color=ACCENT3, ms=6, zorder=4)
            # Score value label at cursor
            ax_s.annotate(
                f"{ry[-1]:,}",
                xy=(rx[-1], ry[-1]),
                xytext=(4, 4), textcoords="offset points",
                fontsize=8, color=ACCENT3, fontfamily="monospace", fontweight="bold",
            )

        # Vertical cursor line across all axes
        for ax in (ax_s, ax_r, ax_m):
            ax.axvline(pos, color=ACCENT, lw=1.2, linestyle="--", alpha=0.7, zorder=5)

        ax_s.set_ylabel("Score", color=MUTED, fontfamily="monospace", fontsize=8)
        ax_s.set_xticks([])
        peak_s = max(all_scores) if all_scores else 1
        ax_s.set_ylim(-peak_s * 0.05, peak_s * 1.18)
        ax_s.set_xlim(-0.5, n - 0.5)
        ax_s.text(0.01, 0.92, "RUNNING SCORE", transform=ax_s.transAxes,
                   fontsize=7, color=MUTED, fontfamily="monospace", va="top")

        # ── Rate bars ────────────────────────────────────────────────────────
        SESSION_PALETTE = THEMES[_ACTIVE_THEME]["SESSION_PALETTE"]
        bar_colours = []
        if self.log:
            cs  = self.log.contest_start()
            dur = self.log._session_cfg.duration_mins
            for s in snapshots:
                if cs and dur:
                    elapsed = (s["hour"] - cs).total_seconds() / 60
                    sn = max(0, int(elapsed // dur))
                    bar_colours.append(SESSION_PALETTE[sn % len(SESSION_PALETTE)])
                else:
                    bar_colours.append(ACCENT)
        else:
            bar_colours = [ACCENT] * n

        # Ghost
        if pos < n - 1:
            ax_r.bar(x[pos + 1:], all_rates[pos + 1:],
                     color=BG3, width=0.72, zorder=1)
        # Active
        ax_r.bar(x[:pos + 1], all_rates[:pos + 1],
                 color=bar_colours[:pos + 1], width=0.72, alpha=0.90, zorder=2)
        # Highlight current bar
        if len(x) > pos:
            ax_r.bar([pos], [all_rates[pos]],
                     color=ACCENT, width=0.72, alpha=1.0, zorder=3)

        peak_r = max(all_rates) if all_rates else 1
        ax_r.set_ylim(0, peak_r * 1.35)
        ax_r.set_xlim(-0.5, n - 0.5)
        ax_r.set_ylabel("QSOs/hr", color=MUTED, fontfamily="monospace", fontsize=8)
        ax_r.set_xticks([])
        ax_r.text(0.01, 0.92, "QSO RATE", transform=ax_r.transAxes,
                   fontsize=7, color=MUTED, fontfamily="monospace", va="top")

        # ── Mults bars ───────────────────────────────────────────────────────
        if pos < n - 1:
            ax_m.bar(x[pos + 1:], all_mults[pos + 1:],
                     color=BG3, width=0.72, zorder=1)
        ax_m.bar(x[:pos + 1], all_mults[:pos + 1],
                 color=ACCENT2, width=0.72, alpha=0.85, zorder=2)
        if len(x) > pos and all_mults[pos] > 0:
            ax_m.bar([pos], [all_mults[pos]],
                     color=ACCENT2, width=0.72, alpha=1.0, zorder=3)

        peak_m = max(all_mults) if all_mults else 1
        ax_m.set_ylim(0, max(peak_m * 1.35, 1))
        ax_m.set_xlim(-0.5, n - 0.5)
        ax_m.set_ylabel("New Mults", color=MUTED, fontfamily="monospace", fontsize=8)
        ax_m.set_xticks(x)
        ax_m.set_xticklabels(labels, rotation=45, ha="right",
                              color=MUTED, fontsize=7, fontfamily="monospace")
        ax_m.text(0.01, 0.92, "NEW MULTS / HOUR", transform=ax_m.transAxes,
                   fontsize=7, color=MUTED, fontfamily="monospace", va="top")

        self.fig_replay.patch.set_facecolor(BG2)
        self.canvas_replay.draw_idle()

    # ── Replay control callbacks ──────────────────────────────────────────────

    def _on_replay_scrub(self, val):
        """Called by the Scale widget when the user drags the scrubber."""
        try:
            pos = int(float(val))
        except (ValueError, TypeError):
            return
        snapshots = self._replay_data
        if not snapshots:
            return
        pos = max(0, min(pos, len(snapshots) - 1))
        self._replay_pos = pos
        s = snapshots[pos]
        self._replay_time_var.set(f"  {s['hour_label']} UTC")
        self._replay_score_var.set(
            f"Score: {s['cum_score']:,}   |   QSOs: {s['cum_qsos']}   |   "
            f"Mults: {s['cum_mults']}   |   Rate: {s['qsos_this_hour']}/hr"
        )
        self._replay_event_var.set(self._replay_event_text(snapshots, pos))
        self._replay_draw(pos)

    def _replay_step(self, delta):
        """Step the scrubber by delta hours."""
        snapshots = self._replay_data
        if not snapshots:
            return
        new_pos = max(0, min(self._replay_pos + delta, len(snapshots) - 1))
        self._replay_scale_var.set(new_pos)
        self._on_replay_scrub(new_pos)

    def _replay_jump(self, pos):
        """Jump to start (pos=0) or end (pos=-1)."""
        snapshots = self._replay_data
        if not snapshots:
            return
        target = 0 if pos == 0 else len(snapshots) - 1
        self._replay_scale_var.set(target)
        self._on_replay_scrub(target)

    def _replay_play_pause(self):
        """Toggle animated playback."""
        if self._replay_playing:
            self._replay_playing = False
            if self._replay_play_job:
                try:
                    self.after_cancel(self._replay_play_job)
                except Exception:
                    pass
                self._replay_play_job = None
            self._replay_play_btn.configure(text="▶  Play")
        else:
            snapshots = self._replay_data
            if not snapshots:
                return
            # If at end, restart
            if self._replay_pos >= len(snapshots) - 1:
                self._replay_jump(0)
            self._replay_playing = True
            self._replay_play_btn.configure(text="⏸  Pause")
            self._replay_tick()

    def _replay_speed_ms(self):
        """Return playback interval in ms from the speed multiplier slider."""
        mult = getattr(self, "_replay_speed_multiplier", None)
        if mult is None:
            return 1000
        # base = 1 000 ms at 1×; clamped to [62, 8 000] ms
        return max(62, min(8000, int(1000 / mult.get())))

    def _replay_tick(self):
        """Advance one step during playback."""
        if not self._replay_playing:
            return
        snapshots = self._replay_data
        if not snapshots:
            self._replay_playing = False
            self._replay_play_btn.configure(text="▶  Play")
            return
        self._replay_step(+1)
        if self._replay_pos >= len(snapshots) - 1:
            self._replay_playing = False
            self._replay_play_btn.configure(text="▶  Play")
            return
        self._replay_play_job = self.after(self._replay_speed_ms(), self._replay_tick)

    # ── Replay refresh (called on log load / tab switch) ──────────────────────

    def _ensure_fig_replay(self):
        """Create fig_replay / canvas_replay on first use (lazy init)."""
        if self.fig_replay is not None:
            return
        self.fig_replay = Figure(figsize=(13, 4.6), facecolor=BG2)
        self.canvas_replay = FigureCanvasTkAgg(self.fig_replay, master=self._replay_fig_frame)
        self.canvas_replay.get_tk_widget().configure(bg=BG2)
        self.canvas_replay.get_tk_widget().pack(fill="both", expand=True)

    def _refresh_replay(self):
        self._ensure_fig_replay()
        if not self.log:
            return
        # Stop any running playback
        if self._replay_playing:
            self._replay_playing = False
            if self._replay_play_job:
                try:
                    self.after_cancel(self._replay_play_job)
                except Exception:
                    pass
                self._replay_play_job = None
            self._replay_play_btn.configure(text="▶  Play")

        self._replay_data = self._replay_build_data()
        snapshots = self._replay_data
        if not snapshots:
            self.fig_replay.clear()
            ax = self.fig_replay.add_subplot(111)
            ax.set_facecolor(BG2)
            ax.text(0.5, 0.5, "No QSO data to replay",
                    ha="center", va="center",
                    color=MUTED, fontsize=11, fontfamily="monospace",
                    transform=ax.transAxes)
            self.fig_replay.patch.set_facecolor(BG2)
            self.canvas_replay.draw_idle()
            return

        n = len(snapshots)
        self._replay_scale.configure(from_=0, to=max(0, n - 1))
        self._replay_lbl_start.configure(text=snapshots[0]["hour_label"])
        self._replay_lbl_end.configure(text=snapshots[-1]["hour_label"])

        # Jump to last active hour by default
        last_active = max(
            (i for i, s in enumerate(snapshots) if s["qsos_this_hour"] > 0),
            default=0
        )
        self._replay_pos = last_active
        self._replay_scale_var.set(last_active)
        self._on_replay_scrub(last_active)


    # ═══════════════════════════════════════════════════════════════════════════
    # ── Operator Fatigue tab ─────────────────────────────────────────────────
    # ═══════════════════════════════════════════════════════════════════════════

    # Dead-zone threshold: an hour whose mean rate falls below this fraction of
    # the operator's overall average is flagged as a potential fatigue window.
    _FATIGUE_DEAD_FRAC   = 0.35   # <35 % of personal avg  → dead zone
    _FATIGUE_WEAK_FRAC   = 0.65   # <65 % but ≥ 35 %       → weak zone
    _FATIGUE_CONSEC_MINS = 2      # ≥ N consecutive dead/weak hours → advisory

    def _build_fatigue_tab(self):
        f = self.tab_fatigue
        f.configure(bg=BG2)

        # ── State ────────────────────────────────────────────────────────────
        # All contests loaded from any .s3db files the operator adds.
        # List of dicts: {label, year, qsos}  (qsos = list of QSO dicts)
        self._fatigue_contests   = []   # accumulated across all loaded files
        self._fatigue_extra_dbs  = []   # extra .s3db paths added via "+ Add Log"
        self._fatigue_contest_var = tk.StringVar(value="— all —")

        # ── Header ───────────────────────────────────────────────────────────
        hdr = tk.Frame(f, bg=BG2)
        hdr.pack(fill="x", padx=12, pady=(8, 2))
        tk.Label(hdr, text="😴  Operator Fatigue Analysis",
                 font=FONT_H, fg=ACCENT, bg=BG2).pack(side="left")
        tk.Label(hdr,
                 text="  QSO rate vs UTC hour across all loaded contests — spot your personal dead zones",
                 font=FONT_S, fg=MUTED, bg=BG2).pack(side="left")

        # ── Toolbar ──────────────────────────────────────────────────────────
        tb = tk.Frame(f, bg=BG2)
        tb.pack(fill="x", padx=12, pady=(2, 4))

        self._btn(tb, "+ Add Log File", self._fatigue_add_log).pack(side="left", padx=(0, 6))
        self._btn(tb, "✕ Clear Extra Logs", self._fatigue_clear_extra,
                  style="secondary").pack(side="left", padx=(0, 12))

        # Contest filter
        tk.Label(tb, text="Contest:", font=FONT_S, fg=MUTED, bg=BG2).pack(side="left", padx=(0, 4))
        self._fatigue_contest_cb = ttk.Combobox(
            tb, textvariable=self._fatigue_contest_var,
            values=["— all —"], width=28, state="readonly", font=FONT_B,
        )
        self._fatigue_contest_cb.pack(side="left", padx=(0, 12))
        self._fatigue_contest_cb.bind("<<ComboboxSelected>>",
                                      lambda e: self._refresh_fatigue())
        _Tooltip(self._fatigue_contest_cb,
                 "Filter fatigue analysis to a single contest type.\n"
                 "Mixing different contests distorts the per-hour averages.\n"
                 "Select '— all —' to include everything loaded.")

        tk.Label(tb, text="Show bands:", font=FONT_S, fg=MUTED, bg=BG2).pack(side="left", padx=(0, 4))
        self._fatigue_band_var = tk.StringVar(value="All bands")
        self._fatigue_band_cb  = ttk.Combobox(
            tb, textvariable=self._fatigue_band_var,
            values=["All bands"], width=10, state="readonly", font=FONT_B,
        )
        self._fatigue_band_cb.pack(side="left", padx=(0, 12))
        self._fatigue_band_cb.bind("<<ComboboxSelected>>",
                                   lambda e: self._refresh_fatigue())

        tk.Label(tb, text="Normalise:", font=FONT_S, fg=MUTED, bg=BG2).pack(side="left", padx=(0, 4))
        self._fatigue_norm_var = tk.StringVar(value="Raw QSOs/hr")
        norm_cb = ttk.Combobox(
            tb, textvariable=self._fatigue_norm_var,
            values=["Raw QSOs/hr", "% of contest avg", "Z-score"],
            width=16, state="readonly", font=FONT_B,
        )
        norm_cb.pack(side="left", padx=(0, 12))
        norm_cb.bind("<<ComboboxSelected>>", lambda e: self._refresh_fatigue())

        # Dead-zone threshold slider
        tk.Label(tb, text="Dead-zone <", font=FONT_S, fg=MUTED, bg=BG2).pack(side="left", padx=(0, 3))
        self._fatigue_thresh_var = tk.IntVar(value=35)
        thresh_scale = tk.Scale(
            tb, variable=self._fatigue_thresh_var,
            from_=10, to=70, orient="horizontal",
            showvalue=True, length=100,
            bg=BG2, fg=MUTED, troughcolor=BG3,
            activebackground=ACCENT2,
            highlightthickness=0, sliderrelief="flat", bd=0,
            font=("Consolas", 8),
            command=lambda v: self._refresh_fatigue(),
        )
        thresh_scale.pack(side="left")
        tk.Label(tb, text="% avg", font=FONT_S, fg=MUTED, bg=BG2).pack(side="left", padx=(2, 0))

        _Tooltip(thresh_scale,
                 "Hours whose mean rate falls below this percentage of your overall\n"
                 "contest average are highlighted as dead zones.\n"
                 "Lower = only flag extreme crashes.  Higher = flag mild dips too.")

        # ── Log roster (small treeview listing loaded contests) ───────────────
        roster_frame = tk.Frame(f, bg=BG2)
        roster_frame.pack(fill="x", padx=12, pady=(0, 4))
        roster_cols = ("Year", "Contest", "QSOs", "Avg QSO/hr", "Dead Hours")
        self._fatigue_roster = ttk.Treeview(
            roster_frame, columns=roster_cols,
            show="headings", height=4, selectmode="extended",
        )
        _style_tree(self._fatigue_roster, self)
        for col, w in zip(roster_cols, [60, 260, 60, 100, 120]):
            self._fatigue_roster.heading(col, text=col)
            self._fatigue_roster.column(col, width=w, anchor="center")
        rsb = ttk.Scrollbar(roster_frame, orient="vertical",
                             command=self._fatigue_roster.yview)
        self._fatigue_roster.configure(yscroll=rsb.set)
        self._fatigue_roster.pack(side="left", fill="x", expand=True)
        rsb.pack(side="right", fill="y")

        # ── Matplotlib figure ─────────────────────────────────────────────────
        # Figure created lazily on first refresh to save startup memory.
        self._fatigue_fig_frame = tk.Frame(f, bg=BG2)
        self._fatigue_fig_frame.pack(fill="both", expand=True, padx=12, pady=(0, 2))
        self.fig_fatigue    = None
        self.canvas_fatigue = None

        # ── Advisory panel ────────────────────────────────────────────────────
        adv_frame = tk.Frame(f, bg=BG3,
                             highlightbackground=BG3, highlightthickness=1)
        adv_frame.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(adv_frame, text="  Nap schedule advisor:  ",
                 font=("Consolas", 9, "bold"), fg=ACCENT3, bg=BG3).pack(side="left")
        self._fatigue_advice_var = tk.StringVar(value="Load a log to generate advice.")
        tk.Label(adv_frame, textvariable=self._fatigue_advice_var,
                 font=("Consolas", 9), fg=FG, bg=BG3,
                 anchor="w", wraplength=1200, justify="left").pack(
                     side="left", fill="x", expand=True, pady=4)

        _Tooltip(self._fatigue_roster,
                 "Lists every contest loaded — the current log plus any extra files\n"
                 "you added with '+ Add Log File'.  Each row shows how many QSOs\n"
                 "the contest had, your average rate, and how many dead-zone hours\n"
                 "were detected at the current threshold.")

    # ── Fatigue data helpers ──────────────────────────────────────────────────

    def _fatigue_collect_contests(self):
        """
        Build self._fatigue_contests from:
          1. Every contest in the currently-loaded .s3db  (self._db_path)
          2. Every contest in each extra .s3db added via + Add Log File

        Returns a list of dicts:
          {label, year, db_path, contest_nr, qsos}
        """
        results = []

        def _load_all_from_db(db_path):
            """Yield (contest_info, qsos_list) for every contest with QSOs."""
            try:
                contests = ContestLog.available_contests(db_path)
            except Exception as e:
                logging.warning("fatigue: available_contests failed for %s: %s", db_path, e)
                return
            for ci in contests:
                if ci.get("QSOCount", 0) == 0:
                    continue
                try:
                    p   = plugin_for(str(ci.get("ContestName", "")))
                    log = ContestLog(db_path,
                                     contest_nr=ci["ContestNR"],
                                     plugin=p)
                    if not log.qsos:
                        continue
                    # Derive year from first QSO or StartDate
                    try:
                        sd  = str(ci.get("StartDate", ""))[:4]
                        year = int(sd) if sd.isdigit() else log.qsos[0]["time"].year
                    except Exception:
                        year = 0
                    name = str(ci.get("DisplayName") or ci.get("ContestName", "?"))
                    label = f"{year}  {name}"
                    yield {
                        "label":      label,
                        "year":       year,
                        "name":       name,
                        "db_path":    db_path,
                        "contest_nr": ci["ContestNR"],
                        "qsos":       log.qsos,
                    }
                except Exception as e:
                    logging.warning("fatigue: failed loading contest %s: %s",
                                    ci.get("ContestNR"), e)

        # Primary loaded DB
        if self._db_path:
            for item in _load_all_from_db(self._db_path):
                results.append(item)

        # Extra DBs
        for db_path in self._fatigue_extra_dbs:
            for item in _load_all_from_db(db_path):
                results.append(item)

        # De-duplicate by (db_path, contest_nr)
        seen   = set()
        unique = []
        for item in results:
            key = (item["db_path"], item["contest_nr"])
            if key not in seen:
                seen.add(key)
                unique.append(item)

        return unique

    def _fatigue_hour_rates(self, qsos, band_filter="All bands"):
        """
        Given a list of QSO dicts, return a 24-element array of QSO counts
        (valid only) indexed by UTC hour-of-day (0–23).
        band_filter='All bands' means no filter.
        """
        counts = np.zeros(24, dtype=float)
        for q in qsos:
            if q.get("dupe"):
                continue
            if band_filter != "All bands" and q.get("band") != band_filter:
                continue
            try:
                counts[q["time"].hour] += 1
            except Exception:
                pass
        return counts

    def _fatigue_dead_zones(self, mean_rates, avg_rate, threshold_pct):
        """
        Return list of hour indices (0–23) that are dead zones.
        mean_rates : 24-element array of mean QSO/hr across years
        avg_rate   : scalar — overall per-hour average across active hours
        threshold_pct : 0–100
        """
        if avg_rate <= 0:
            return []
        thresh = avg_rate * threshold_pct / 100.0
        return [h for h in range(24) if mean_rates[h] < thresh]

    def _fatigue_consecutive_blocks(self, dead_hours):
        """
        Group sorted dead_hours into consecutive runs.
        Returns list of (start_h, end_h_inclusive) tuples.
        """
        if not dead_hours:
            return []
        runs  = []
        start = dead_hours[0]
        prev  = dead_hours[0]
        for h in dead_hours[1:]:
            if h == prev + 1:
                prev = h
            else:
                runs.append((start, prev))
                start = prev = h
        runs.append((start, prev))
        return runs

    def _fatigue_advice(self, dead_runs, avg_rate, threshold_pct):
        """Build a human-readable nap-schedule advisory string."""
        if not dead_runs:
            return (
                "No significant dead zones detected at the current threshold.  "
                "Either your rate is consistent across the clock or you haven't "
                "loaded enough contest years for a pattern to emerge."
            )

        # Only report runs ≥ 2 consecutive hours for actionable advice
        sig = [(s, e) for s, e in dead_runs if (e - s + 1) >= 2]
        # Also report single hours that appear dead
        solo = [(s, e) for s, e in dead_runs if (e - s + 1) == 1]

        parts = []
        if sig:
            sig_strs = []
            for s, e in sig:
                sig_strs.append(f"{s:02d}:00–{e+1:02d}:00 UTC")
            parts.append(
                "⚠ Consistent crash window"
                + ("s" if len(sig) > 1 else "")
                + ":  "
                + "  and  ".join(sig_strs)
                + ".  Consider scheduling a nap to cover "
                + (sig_strs[0] if len(sig) == 1 else "these windows")
                + "."
            )
        if solo:
            solo_strs = [f"{s:02d}:00" for s, _ in solo]
            parts.append(
                "Single-hour dips at "
                + ", ".join(solo_strs)
                + " UTC — worth watching but may be contest-specific."
            )
        if not parts:
            parts.append(
                "Dead zones found but none span ≥ 2 consecutive hours — "
                "no strong nap recommendation at the current threshold."
            )
        return "   ".join(parts)

    # ── Fatigue toolbar callbacks ─────────────────────────────────────────────

    def _fatigue_add_log(self):
        """Let the operator pick an extra .s3db to fold into the fatigue chart."""
        p = filedialog.askopenfilename(
            title="Add extra contest log for fatigue analysis",
            filetypes=[("N1MM Log Files", "*.s3db"), ("All DBs", "*.db;*.sqlite")],
        )
        if not p or p in self._fatigue_extra_dbs or p == self._db_path:
            return
        self._fatigue_extra_dbs.append(p)
        self._refresh_fatigue()

    def _fatigue_clear_extra(self):
        self._fatigue_extra_dbs.clear()
        self._refresh_fatigue()

    # ── Main refresh ──────────────────────────────────────────────────────────

    def _ensure_fig_fatigue(self):
        """Create fig_fatigue / canvas_fatigue on first use (lazy init)."""
        if not hasattr(self, "fig_fatigue"):
            return          # tab was disabled — build method never ran
        if self.fig_fatigue is not None:
            return
        self.fig_fatigue = Figure(figsize=(13, 4.4), facecolor=BG2)
        self.canvas_fatigue = FigureCanvasTkAgg(self.fig_fatigue, master=self._fatigue_fig_frame)
        self.canvas_fatigue.get_tk_widget().configure(bg=BG2)
        self.canvas_fatigue.get_tk_widget().pack(fill="both", expand=True)

    def _refresh_fatigue(self):
        """Rebuild the fatigue chart and advisory from all loaded contests."""
        if not hasattr(self, "fig_fatigue"):
            return          # tab was disabled — build method never ran
        self._ensure_fig_fatigue()

        # ── Collect contests (cached; only reload when DB list changes) ──────
        cache_key = (self._db_path, tuple(self._fatigue_extra_dbs))
        if getattr(self, "_fatigue_cache_key", None) != cache_key:
            self._fatigue_contests_cache = self._fatigue_collect_contests()
            self._fatigue_cache_key = cache_key
        all_contests = self._fatigue_contests_cache

        band_filter = self._fatigue_band_var.get()
        norm_mode   = self._fatigue_norm_var.get()
        thresh_pct  = self._fatigue_thresh_var.get()

        # ── Populate contest-name filter combobox ─────────────────────────────
        all_names = sorted({ct["name"] for ct in all_contests})
        cb_vals   = ["— all —"] + all_names
        self._fatigue_contest_cb.configure(values=cb_vals)
        contest_filter = self._fatigue_contest_var.get()
        if contest_filter not in cb_vals:
            self._fatigue_contest_var.set("— all —")
            contest_filter = "— all —"
        # Auto-select when only one contest type exists
        if len(all_names) == 1 and contest_filter == "— all —":
            self._fatigue_contest_var.set(all_names[0])
            contest_filter = all_names[0]

        if contest_filter == "— all —":
            contests = all_contests
        else:
            contests = [ct for ct in all_contests if ct["name"] == contest_filter]

        band_filter = self._fatigue_band_var.get()
        norm_mode   = self._fatigue_norm_var.get()
        thresh_pct  = self._fatigue_thresh_var.get()

        # ── Update band filter combobox from discovered bands ─────────────────
        all_bands = set()
        for ct in contests:
            for q in ct["qsos"]:
                b = q.get("band")
                if b:
                    all_bands.add(b)
        BAND_ORDER = ["160M","80M","60M","40M","30M","20M","17M","15M","12M",
                      "10M","6M","2M","70CM"]
        sorted_bands = (
            sorted(all_bands, key=lambda b: BAND_ORDER.index(b)
                   if b.upper() in BAND_ORDER else 99)
        )
        cb_vals = ["All bands"] + sorted_bands
        self._fatigue_band_cb.configure(values=cb_vals)
        if band_filter not in cb_vals:
            self._fatigue_band_var.set("All bands")
            band_filter = "All bands"

        # ── Build per-contest hour-rate arrays ────────────────────────────────
        # Each entry: (label, year, rates_24)
        contest_rates = []
        for ct in contests:
            rates = self._fatigue_hour_rates(ct["qsos"], band_filter)
            contest_rates.append((ct["label"], ct["year"], rates))

        # ── Roster treeview ───────────────────────────────────────────────────
        for iid in self._fatigue_roster.get_children():
            self._fatigue_roster.delete(iid)

        if not contest_rates:
            # No data yet
            self.fig_fatigue.clear()
            ax = self.fig_fatigue.add_subplot(111)
            ax.set_facecolor(BG2)
            ax.text(0.5, 0.5,
                    "Load a log file to begin.\n"
                    "Use '+ Add Log File' to add more years for cross-year analysis.",
                    ha="center", va="center",
                    color=MUTED, fontsize=11, fontfamily="monospace",
                    transform=ax.transAxes, linespacing=2.0)
            self.fig_fatigue.patch.set_facecolor(BG2)
            self.canvas_fatigue.draw_idle()
            self._fatigue_advice_var.set("Load a log to generate advice.")
            return

        SESSION_PALETTE = THEMES[_ACTIVE_THEME]["SESSION_PALETTE"]

        for idx, (label, year, rates) in enumerate(contest_rates):
            active_hours = [h for h in range(24) if rates[h] > 0]
            if active_hours:
                avg = rates[active_hours].mean()
                dead_h = self._fatigue_dead_zones(
                    rates, avg, thresh_pct)
                # Only count active hours as dead (hours with any expected traffic)
                dead_in_active = [h for h in dead_h if h in active_hours]
            else:
                avg      = 0.0
                dead_in_active = []
            colour = SESSION_PALETTE[idx % len(SESSION_PALETTE)]
            self._fatigue_roster.insert("", "end",
                values=(year, label, sum(rates.astype(int)),
                        f"{avg:.1f}", len(dead_in_active)),
                tags=(colour,),
            )
            try:
                self._fatigue_roster.tag_configure(colour,
                                                    foreground=colour)
            except Exception:
                pass

        # ── Compute cross-year mean rates ─────────────────────────────────────
        # Stack all per-contest arrays; mean across axis-0
        stacked     = np.vstack([r for _, _, r in contest_rates])   # (N, 24)
        # For the mean, only average hours where at least one contest had activity
        # (avoid pulling down hours that simply weren't in the contest window)
        activity_mask = (stacked > 0).any(axis=0)           # (24,) bool
        mean_rates    = stacked.mean(axis=0)                 # raw mean including zeros

        # Hours with any activity across any year
        active_hours_global = [h for h in range(24) if activity_mask[h]]
        if active_hours_global:
            # avg = mean of active-hour means (scalar personal average)
            overall_avg = mean_rates[active_hours_global].mean()
        else:
            overall_avg = 0.0

        dead_zone_hours = self._fatigue_dead_zones(mean_rates, overall_avg, thresh_pct)
        dead_runs       = self._fatigue_consecutive_blocks(
            sorted(set(dead_zone_hours) & set(active_hours_global))
        )

        # ── Advisory ─────────────────────────────────────────────────────────
        self._fatigue_advice_var.set(
            self._fatigue_advice(dead_runs, overall_avg, thresh_pct)
        )

        # ── Normalise ────────────────────────────────────────────────────────
        def normalise(rates_24):
            active = [r for r in rates_24 if r > 0]
            avg    = np.mean(active) if active else 1.0
            if norm_mode == "% of contest avg":
                return rates_24 / avg * 100.0
            elif norm_mode == "Z-score":
                std = np.std(active) if len(active) > 1 else 1.0
                return (rates_24 - avg) / (std if std > 0 else 1.0)
            else:   # Raw QSOs/hr
                return rates_24.copy()

        y_label_map = {
            "Raw QSOs/hr":      "QSOs / hour",
            "% of contest avg": "% of personal avg",
            "Z-score":          "Z-score (σ)",
        }
        y_label = y_label_map.get(norm_mode, "QSOs / hour")

        norm_stacked = np.vstack([normalise(r) for _, _, r in contest_rates])
        norm_mean    = norm_stacked.mean(axis=0)

        # ── Draw ─────────────────────────────────────────────────────────────
        self.fig_fatigue.clear()
        hours = np.arange(24)

        gs  = self.fig_fatigue.add_gridspec(
            1, 1, left=0.055, right=0.97, top=0.92, bottom=0.13)
        ax  = self.fig_fatigue.add_subplot(gs[0])
        ax.set_facecolor(BG2)
        for sp in ax.spines.values():
            sp.set_edgecolor(BG3)
        ax.tick_params(colors=MUTED, labelsize=8)

        # ── Dead-zone shading (behind everything) ─────────────────────────────
        for h in dead_zone_hours:
            if activity_mask[h]:
                ax.axvspan(h - 0.5, h + 0.5,
                           color=RED, alpha=0.12, zorder=0)
        # Consecutive-run annotations
        for s, e in dead_runs:
            if (e - s + 1) >= 2:
                mid = (s + e) / 2.0
                ax.text(mid, ax.get_ylim()[1] if ax.get_ylim()[1] != 1.0 else 1.0,
                        f"ZZZ {s:02d}\u2013{e+1:02d}",
                        ha="center", va="top",
                        color=RED, fontsize=7.5,
                        fontfamily="monospace",
                        fontweight="bold", zorder=6,
                        transform=ax.get_xaxis_transform())

        # ── Per-year thin lines ───────────────────────────────────────────────
        for idx, (label, year, rates) in enumerate(contest_rates):
            y    = normalise(rates)
            col  = SESSION_PALETTE[idx % len(SESSION_PALETTE)]
            # Mask zeros outside contest window to avoid flat-zero distortion
            mask = activity_mask | (rates > 0)
            y_masked = np.where(mask, y, np.nan)
            ax.plot(hours, y_masked, color=col, lw=1.0,
                    alpha=0.45, zorder=2,
                    label=f"{year}" if len(contest_rates) <= 10 else None)

        # ── Cross-year mean — the hero line ──────────────────────────────────
        norm_mean_masked = np.where(activity_mask, norm_mean, np.nan)
        ax.plot(hours, norm_mean_masked,
                color=ACCENT, lw=2.8,
                solid_capstyle="round", zorder=4,
                label="Mean (all years)")

        # Fill under mean
        ax.fill_between(hours,
                         np.where(activity_mask, norm_mean, np.nan),
                         alpha=0.12, color=ACCENT, zorder=3)

        # ── Reference lines ───────────────────────────────────────────────────
        if norm_mode == "Raw QSOs/hr":
            thresh_val = overall_avg * thresh_pct / 100.0
            ax.axhline(thresh_val, color=RED, lw=1.0,
                       linestyle="--", alpha=0.6, zorder=5)
            ax.axhline(overall_avg, color=GREEN, lw=0.8,
                       linestyle=":", alpha=0.5, zorder=5)
            ax.text(23.4, thresh_val, f" <{thresh_pct}%",
                    va="center", fontsize=7,
                    color=RED, fontfamily="monospace")
            ax.text(23.4, overall_avg, " avg",
                    va="center", fontsize=7,
                    color=GREEN, fontfamily="monospace")
        elif norm_mode == "% of contest avg":
            ax.axhline(thresh_pct, color=RED, lw=1.0,
                       linestyle="--", alpha=0.6, zorder=5)
            ax.axhline(100.0, color=GREEN, lw=0.8,
                       linestyle=":", alpha=0.5, zorder=5)
            ax.text(23.4, thresh_pct, f" {thresh_pct}%",
                    va="center", fontsize=7,
                    color=RED, fontfamily="monospace")
            ax.text(23.4, 100.0, " 100%",
                    va="center", fontsize=7,
                    color=GREEN, fontfamily="monospace")
        elif norm_mode == "Z-score":
            ax.axhline(-1.0, color=RED, lw=1.0,
                       linestyle="--", alpha=0.6, zorder=5)
            ax.axhline(0.0, color=GREEN, lw=0.8,
                       linestyle=":", alpha=0.5, zorder=5)
            ax.text(23.4, -1.0, " −1σ",
                    va="center", fontsize=7,
                    color=RED, fontfamily="monospace")

        # ── Night-time guide band (20:00–08:00) ───────────────────────────────
        for night_h in list(range(0, 8)) + list(range(20, 24)):
            ax.axvspan(night_h - 0.5, night_h + 0.5,
                       color=BG3, alpha=0.25, zorder=0)

        # ── Axes decoration ───────────────────────────────────────────────────
        ax.set_xlim(-0.5, 23.5)
        ax.set_xticks(range(24))
        ax.set_xticklabels([f"{h:02d}" for h in range(24)],
                           color=MUTED, fontsize=8,
                           fontfamily="monospace")
        ax.set_xlabel("UTC Hour", color=MUTED,
                      fontfamily="monospace", fontsize=9)
        ax.set_ylabel(y_label, color=MUTED,
                      fontfamily="monospace", fontsize=9)

        n_years = len(contest_rates)
        title_suffix = (
            f"  ({n_years} contest{'s' if n_years != 1 else ''} loaded)"
        )
        ax.set_title(
            "Operator Fatigue Profile — Mean QSO Rate by UTC Hour" + title_suffix,
            color=FG, fontfamily="monospace", fontsize=10, pad=6,
        )

        # Legend — only if ≤ 10 years (otherwise too cluttered)
        if n_years <= 10:
            leg = ax.legend(
                facecolor=BG3, edgecolor="none",
                labelcolor=FG, fontsize=7.5,
                loc="upper right",
            )
            for line in leg.get_lines():
                line.set_linewidth(2.0)

        # Dead-zone band labels on x-axis tick marks
        for h in dead_zone_hours:
            if activity_mask[h]:
                try:
                    ax.get_xticklabels()[h].set_color(RED)
                    ax.get_xticklabels()[h].set_fontweight("bold")
                except Exception:
                    pass

        self.fig_fatigue.patch.set_facecolor(BG2)
        self.canvas_fatigue.draw_idle()


    # ═══════════════════════════════════════════════════════════════════════════
    # ── Year-over-Year Overlay tab ───────────────────────────────────────────
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_yoy_tab(self):
        f = self.tab_yoy
        f.configure(bg=BG2)

        # ── Per-tab state ─────────────────────────────────────────────────────
        # List of loaded series: each is a dict
        #   { key, label, year, contest_name, db_path, contest_nr, log, colour,
        #     visible, traj_elapsed, traj_score, traj_qsos, traj_mults,
        #     final_score, final_qsos, final_mults, total_hrs }
        self._yoy_series     = []
        self._yoy_extra_dbs  = []   # extra .s3db files the operator added

        # ── Header ───────────────────────────────────────────────────────────
        hdr = tk.Frame(f, bg=BG2)
        hdr.pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(hdr, text="📈  Year on Year Score Overlay",
                 font=FONT_H, fg=ACCENT, bg=BG2).pack(side="left")
        tk.Label(hdr,
                 text="  Overlay score trajectories from multiple contest years — aligned to contest start",
                 font=FONT_S, fg=MUTED, bg=BG2).pack(side="left")

        # ── Toolbar ──────────────────────────────────────────────────────────
        tb = tk.Frame(f, bg=BG2)
        tb.pack(fill="x", padx=12, pady=(4, 2))

        self._btn(tb, "+ Add Log File", self._yoy_add_log).pack(side="left", padx=(0, 6))
        self._btn(tb, "✕ Clear All",    self._yoy_clear_all,
                  style="secondary").pack(side="left", padx=(0, 14))

        # ── Contest filter (row 1b — same toolbar row) ────────────────────────
        tk.Label(tb, text="Contest:", font=FONT_S, fg=MUTED, bg=BG2).pack(
            side="left", padx=(0, 4))
        self._yoy_contest_var = tk.StringVar(value="— all —")
        self._yoy_contest_cb  = ttk.Combobox(
            tb, textvariable=self._yoy_contest_var,
            values=["— all —"], width=28, state="readonly", font=FONT_B,
        )
        self._yoy_contest_cb.pack(side="left", padx=(0, 14))
        self._yoy_contest_cb.bind("<<ComboboxSelected>>",
                                  lambda e: self._yoy_redraw())
        _Tooltip(self._yoy_contest_cb,
                 "Filter to a single contest name.\n"
                 "The list is built automatically from all loaded log files.\n"
                 "Select '— all —' to show every loaded contest.")

        # X-axis mode
        tk.Label(tb, text="X-axis:", font=FONT_S, fg=MUTED, bg=BG2).pack(
            side="left", padx=(0, 4))
        self._yoy_xmode_var = tk.StringVar(value="Hours elapsed")
        xmode_cb = ttk.Combobox(
            tb, textvariable=self._yoy_xmode_var,
            values=["Hours elapsed", "UTC clock time"],
            width=14, state="readonly", font=FONT_B,
        )
        xmode_cb.pack(side="left", padx=(0, 12))
        xmode_cb.bind("<<ComboboxSelected>>", lambda e: self._yoy_redraw())
        _Tooltip(xmode_cb,
                 "Hours elapsed: all years start at x=0, ignoring calendar date.\n"
                 "Ideal for comparing contest effort directly.\n\n"
                 "UTC clock time: aligned to wall-clock UTC hour.\n"
                 "Shows propagation differences between years at the same time of day.")

        # Metric selector
        tk.Label(tb, text="Show:", font=FONT_S, fg=MUTED, bg=BG2).pack(
            side="left", padx=(0, 4))
        self._yoy_metric_var = tk.StringVar(value="Score")
        metric_cb = ttk.Combobox(
            tb, textvariable=self._yoy_metric_var,
            values=["Score", "QSOs", "Multipliers", "QSOs/hr rate"],
            width=14, state="readonly", font=FONT_B,
        )
        metric_cb.pack(side="left", padx=(0, 12))
        metric_cb.bind("<<ComboboxSelected>>", lambda e: self._yoy_redraw())

        # Normalise toggle
        self._yoy_norm_var = tk.BooleanVar(value=False)
        norm_chk = tk.Checkbutton(
            tb, text="Normalise to 100%", variable=self._yoy_norm_var,
            command=self._yoy_redraw,
            font=FONT_S, fg=MUTED, bg=BG2,
            activeforeground=ACCENT, activebackground=BG2,
            selectcolor=BG3, relief="flat", cursor="hand2",
        )
        norm_chk.pack(side="left", padx=(0, 12))
        _Tooltip(norm_chk,
                 "Scale every series so its final value = 100%.\n"
                 "Removes absolute-size differences and highlights the\n"
                 "shape of progression — where each year built score fastest.")

        # Annotation toggle
        self._yoy_annot_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            tb, text="Show annotations", variable=self._yoy_annot_var,
            command=self._yoy_redraw,
            font=FONT_S, fg=MUTED, bg=BG2,
            activeforeground=ACCENT, activebackground=BG2,
            selectcolor=BG3, relief="flat", cursor="hand2",
        ).pack(side="left", padx=(0, 4))

        # ── Series roster ────────────────────────────────────────────────────
        roster_outer = tk.Frame(f, bg=BG2)
        roster_outer.pack(fill="x", padx=12, pady=(2, 4))

        roster_cols = (
            "Vis", "Year", "Contest", "Final Score", "QSOs", "Mults",
            "Duration (hrs)", "Δ Score vs prev", "Δ QSOs vs prev",
        )
        self._yoy_roster = ttk.Treeview(
            roster_outer, columns=roster_cols,
            show="headings", height=4, selectmode="browse",
        )
        _style_tree(self._yoy_roster, self)
        col_widths = [34, 54, 230, 100, 60, 60, 110, 120, 110]
        for col, w in zip(roster_cols, col_widths):
            self._yoy_roster.heading(col, text=col)
            self._yoy_roster.column(col, width=w, anchor="center")
        rsb = ttk.Scrollbar(roster_outer, orient="vertical",
                             command=self._yoy_roster.yview)
        self._yoy_roster.configure(yscroll=rsb.set)
        self._yoy_roster.pack(side="left", fill="x", expand=True)
        rsb.pack(side="right", fill="y")
        self._yoy_roster.bind("<ButtonRelease-1>", self._yoy_roster_click)
        _Tooltip(self._yoy_roster,
                 "Click the Vis column to show/hide a series.\n"
                 "Δ columns compare each year to the previous year in the list.\n"
                 "Green = improvement, red = decline.")

        # ── Matplotlib figure: 2 rows — main trajectory + per-hour rate ───────
        # Figure created lazily on first refresh to save startup memory.
        self._yoy_fig_frame = tk.Frame(f, bg=BG2)
        self._yoy_fig_frame.pack(fill="both", expand=True, padx=12, pady=(0, 2))
        self.fig_yoy    = None
        self.canvas_yoy = None

        # ── Insight bar ───────────────────────────────────────────────────────
        ins_frame = tk.Frame(f, bg=BG3,
                             highlightbackground=BG3, highlightthickness=1)
        ins_frame.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(ins_frame, text="  Insight:  ",
                 font=("Consolas", 9, "bold"), fg=ACCENT3, bg=BG3).pack(side="left")
        self._yoy_insight_var = tk.StringVar(
            value="Load two or more logs to compare year on year trajectories.")
        tk.Label(ins_frame, textvariable=self._yoy_insight_var,
                 font=("Consolas", 9), fg=FG, bg=BG3,
                 anchor="w", wraplength=1200, justify="left").pack(
                     side="left", fill="x", expand=True, pady=4)

    # ── YoY data helpers ──────────────────────────────────────────────────────

    # Palette shared across all series (cycles if > 8 years)
    _YOY_PALETTE = [
        "#00d4aa", "#f0c040", "#ff6b35", "#64b5f6",
        "#e040fb", "#2ed573", "#ff5252", "#ffab40",
    ]

    def _yoy_build_trajectory(self, log):
        """
        From a ContestLog, build elapsed-time trajectory arrays.

        Returns a dict:
          elapsed_hrs  : list[float]  — hours since contest start (0.0 …)
          cum_score    : list[int]
          cum_qsos     : list[int]
          cum_mults    : list[int]
          rate_hrs     : list[float]  — hour-bucket centres (0.5, 1.5 …)
          rate_counts  : list[int]    — QSOs in each 1-hr bucket
          utc_hrs      : list[float]  — UTC hour of each sample (for clock mode)
          utc_rate_hrs : list[float]  — UTC hour-bucket centres
        """
        valid = sorted(
            [q for q in log.qsos if not q["dupe"]],
            key=lambda q: q["time"],
        )
        cs = log.contest_start()
        if not cs or not valid:
            return None

        # If StartDate is after the first QSO, N1MM set it to instance-creation
        # date rather than actual contest start — fall back to earliest QSO time.
        earliest_qso = valid[0]["time"]
        if cs > earliest_qso:
            cs = earliest_qso.replace(minute=0, second=0, microsecond=0)

        # Build per-QSO cumulative trajectory
        elapsed_hrs = []
        utc_hrs     = []
        cum_score   = []
        cum_qsos    = []
        cum_mults   = []
        seen_mults  = set()
        qsos_so_far = []

        for q in valid:
            qsos_so_far.append(q)
            e_hrs = max(0.0, (q["time"] - cs).total_seconds() / 3600.0)
            elapsed_hrs.append(e_hrs)
            utc_hrs.append(q["time"].hour + q["time"].minute / 60.0)
            cum_qsos.append(len(qsos_so_far))
            cum_score.append(log.plugin.running_score_for_sparkline(qsos_so_far))

            # Mults
            if q.get("is_mult1") == 1 and q["mult1"]:
                seen_mults.add((q["mult1"], q["band"], q["mode"]))
            if q.get("is_mult2") == 1 and q.get("cqz"):
                seen_mults.add((q["cqz"], q["band"], q["mode"]))
            cum_mults.append(len(seen_mults))

        # Hourly rate buckets (elapsed)
        max_e = elapsed_hrs[-1] if elapsed_hrs else 0
        n_buckets = max(1, int(max(max_e, 0)) + 1)
        rate_counts = [0] * n_buckets
        for e in elapsed_hrs:
            b = max(0, min(int(e), n_buckets - 1))  # clamp: guard negative elapsed
            rate_counts[b] += 1
        rate_hrs = [b + 0.5 for b in range(n_buckets)]

        # Hourly rate buckets (UTC clock)
        utc_rate_counts = [0] * 24
        for q in valid:
            utc_rate_counts[q["time"].hour] += 1
        utc_rate_hrs = [h + 0.5 for h in range(24)]

        return {
            "elapsed_hrs":    elapsed_hrs,
            "utc_hrs":        utc_hrs,
            "cum_score":      cum_score,
            "cum_qsos":       cum_qsos,
            "cum_mults":      cum_mults,
            "rate_hrs":       rate_hrs,
            "rate_counts":    rate_counts,
            "utc_rate_hrs":   utc_rate_hrs,
            "utc_rate_counts": utc_rate_counts,
            "final_score":    cum_score[-1] if cum_score else 0,
            "final_qsos":     cum_qsos[-1]  if cum_qsos  else 0,
            "final_mults":    cum_mults[-1] if cum_mults else 0,
            "total_hrs":      max_e,
        }

    def _yoy_load_series_from_db(self, db_path):
        """
        Load every contest with QSOs from db_path, build trajectories,
        and append new ones to self._yoy_series.  Deduplicates by key.
        """
        existing_keys = {s["key"] for s in self._yoy_series}
        try:
            contests = ContestLog.available_contests(db_path)
        except Exception as e:
            messagebox.showerror("Load failed",
                                 f"Could not read contests from:\n{db_path}\n\n{e}")
            return

        added = 0
        for ci in contests:
            if ci.get("QSOCount", 0) == 0:
                continue
            # Skip generic logging entries — not real contests
            if str(ci.get("ContestName", "")).strip().upper() in ("DX", "DELETEDQS", ""):
                continue
            key = f"{db_path}::{ci['ContestNR']}"
            if key in existing_keys:
                continue
            try:
                p   = plugin_for(str(ci.get("ContestName", "")))
                log = ContestLog(db_path, contest_nr=ci["ContestNR"], plugin=p)
                if not log.qsos:
                    continue
                traj = self._yoy_build_trajectory(log)
                if traj is None:
                    continue

                try:
                    sd        = str(ci.get("StartDate", ""))[:4]
                    start_yr  = int(sd) if sd.isdigit() else 0
                    qso_yr    = log.qsos[0]["time"].year if log.qsos else 0
                    # If StartDate year differs from QSO year by >1, use QSO year
                    # (e.g. N1MM sets StartDate to instance-creation date)
                    if start_yr and qso_yr and abs(start_yr - qso_yr) > 1:
                        year = qso_yr
                    else:
                        year = start_yr or qso_yr
                except Exception:
                    year = 0

                display = str(ci.get("DisplayName") or ci.get("ContestName", "?")).strip()
                # Use ContestName (raw) as grouping key so all years of the same
                # contest are grouped together even if DisplayName varies
                contest_key_name = str(ci.get("ContestName", display)).strip()
                colour = self._YOY_PALETTE[
                    len(self._yoy_series) % len(self._YOY_PALETTE)]

                self._yoy_series.append({
                    "key":          key,
                    "label":        f"{year} — {display}",
                    "year":         year,
                    "contest_name": contest_key_name,
                    "display_name": display,
                    "db_path":      db_path,
                    "contest_nr":   ci["ContestNR"],
                    "log":          log,
                    "colour":       colour,
                    "visible":      True,
                    **traj,
                })
                existing_keys.add(key)
                added += 1
            except Exception as e:
                logging.warning("yoy: failed loading contest %s: %s",
                                ci.get("ContestNR"), e)

        if added == 0:
            # Only show the popup for external files, not the primary DB
            primary = getattr(self, "_db_path", None)
            is_primary = (primary and
                          os.path.normcase(os.path.abspath(db_path)) ==
                          os.path.normcase(os.path.abspath(primary)))
            if not is_primary:
                messagebox.showinfo(
                    "Nothing new",
                    f"All contests in:\n{os.path.basename(db_path)}\n\n"
                    f"are already loaded in the Year-on-Year view.",
                )

    def _yoy_insight(self, filtered_series):
        """
        Generate a plain-English summary comparing the loaded series.
        Compares chronologically-sorted years.
        """
        visible = [s for s in filtered_series if s["visible"]]
        if len(visible) < 2:
            return ("Load two or more contest logs from the same contest "
                    "in different years to compare trajectories.")

        sorted_v = sorted(visible, key=lambda s: s["year"])
        best  = max(sorted_v, key=lambda s: s["final_score"])
        worst = min(sorted_v, key=lambda s: s["final_score"])

        parts = []

        # Best/worst year
        contest_label = best.get('display_name', best['contest_name'])
        parts.append(
            f"Best year: {best['year']} — {contest_label} "
            f"({best['final_score']:,} pts, "
            f"{best['final_qsos']} QSOs, {best['final_mults']} mults)."
        )

        # Trend: last vs first
        first, last = sorted_v[0], sorted_v[-1]
        if last["final_score"] > first["final_score"]:
            pct = (last["final_score"] - first["final_score"]) / max(first["final_score"], 1) * 100
            parts.append(f"Score trend ↑ +{pct:.0f}% from {first['year']} to {last['year']}.")
        elif last["final_score"] < first["final_score"]:
            pct = (first["final_score"] - last["final_score"]) / max(first["final_score"], 1) * 100
            parts.append(f"Score trend ↓ −{pct:.0f}% from {first['year']} to {last['year']}.")
        else:
            parts.append(f"Score unchanged from {first['year']} to {last['year']}.")

        # Multiplier efficiency note
        best_eff  = max(sorted_v, key=lambda s: s["final_mults"])
        worst_eff = min(sorted_v, key=lambda s: s["final_mults"])
        if best_eff["year"] != worst_eff["year"]:
            parts.append(
                f"Multiplier range: {worst_eff['final_mults']} ({worst_eff['year']}) "
                f"→ {best_eff['final_mults']} ({best_eff['year']})."
            )

        # Duration note
        hrs_list = [(s["year"], s["total_hrs"]) for s in sorted_v if s["total_hrs"] > 0]
        if hrs_list:
            max_hr = max(hrs_list, key=lambda x: x[1])
            min_hr = min(hrs_list, key=lambda x: x[1])
            if max_hr[1] - min_hr[1] > 1.0:
                parts.append(
                    f"Operating time varied: {min_hr[1]:.1f} hrs ({min_hr[0]}) "
                    f"to {max_hr[1]:.1f} hrs ({max_hr[0]})."
                )

        return "   ".join(parts)

    # ── YoY toolbar callbacks ─────────────────────────────────────────────────

    def _yoy_add_log(self):
        paths = filedialog.askopenfilenames(
            title="Add contest log(s) for year-over-year comparison",
            filetypes=[("N1MM Log Files", "*.s3db"),
                       ("All DBs", "*.db;*.sqlite")],
        )
        if not paths:
            return
        primary = getattr(self, "_db_path", None)
        for p in paths:
            is_primary = (primary and os.path.normcase(os.path.abspath(p)) ==
                          os.path.normcase(os.path.abspath(primary)))
            if not is_primary and p not in self._yoy_extra_dbs:
                self._yoy_extra_dbs.append(p)
            # Suppress "Nothing new" popup for the primary DB — it was
            # already auto-loaded by _refresh_yoy; just silently skip.
            existing_keys = {s["key"] for s in self._yoy_series}
            any_new = any(
                f"{p}::{ci["ContestNR"]}" not in existing_keys
                for ci in (ContestLog.available_contests(p) or [])
            )
            if any_new or not is_primary:
                self._yoy_load_series_from_db(p)
            # If primary and nothing new, silently skip — data already loaded

        # Also fold the primary loaded DB in if not yet present
        if primary:
            primary_keys = {s["db_path"] for s in self._yoy_series}
            if primary not in primary_keys:
                self._yoy_load_series_from_db(primary)

        self._yoy_redraw()

    def _yoy_clear_all(self):
        self._yoy_series.clear()
        self._yoy_extra_dbs.clear()
        self._yoy_redraw()

    def _yoy_roster_click(self, event):
        """Toggle visibility when the Vis column is clicked."""
        region = self._yoy_roster.identify_region(event.x, event.y)
        col    = self._yoy_roster.identify_column(event.x)
        row    = self._yoy_roster.identify_row(event.y)
        if region != "cell" or col != "#1" or not row:
            return
        # Find matching series by iid (we use the series key as iid)
        key = row
        for s in self._yoy_series:
            if s["key"] == key:
                s["visible"] = not s["visible"]
                break
        self._yoy_redraw()

    # ── Main refresh / redraw ─────────────────────────────────────────────────

    def _refresh_yoy(self):
        """
        Called on log-load and tab-switch.
        Auto-adds the primary loaded .s3db to the series list if not already present.
        """
        if not hasattr(self, "_yoy_series"):
            return          # tab was disabled — build method never ran
        if getattr(self, "_db_path", None):
            primary_keys = {s["db_path"] for s in self._yoy_series}
            if self._db_path not in primary_keys:
                self._yoy_load_series_from_db(self._db_path)
        self._yoy_redraw()

    def _ensure_fig_yoy(self):
        """Create fig_yoy / canvas_yoy on first use (lazy init)."""
        if self.fig_yoy is not None:
            return
        self.fig_yoy = Figure(figsize=(13, 5.2), facecolor=BG2)
        self.canvas_yoy = FigureCanvasTkAgg(self.fig_yoy, master=self._yoy_fig_frame)
        self.canvas_yoy.get_tk_widget().configure(bg=BG2)
        self.canvas_yoy.get_tk_widget().pack(fill="both", expand=True)

    def _yoy_redraw(self):
        """Full redraw of roster + chart + insight from self._yoy_series."""
        self._ensure_fig_yoy()
        palette = THEMES[_ACTIVE_THEME]["SESSION_PALETTE"]

        # Reassign colours from current theme palette so theme-switch works
        for i, s in enumerate(self._yoy_series):
            s["colour"] = palette[i % len(palette)]

        # ── Populate contest-name filter combobox ─────────────────────────────
        # Build map: contest_name (grouping key) -> friendly display_name
        # Prefer display_name where available; fall back to contest_name
        name_to_display = {}
        for s in self._yoy_series:
            cn = s["contest_name"]
            if cn not in name_to_display:
                name_to_display[cn] = s.get("display_name", cn)
        # Combobox shows friendly display names sorted alphabetically
        sorted_keys    = sorted(name_to_display.keys(),
                                key=lambda k: name_to_display[k])
        cb_display     = [name_to_display[k] for k in sorted_keys]
        cb_vals        = ["— all —"] + cb_display
        self._yoy_contest_cb.configure(values=cb_vals)
        contest_filter = self._yoy_contest_var.get()
        if contest_filter not in cb_vals:
            self._yoy_contest_var.set("— all —")
            contest_filter = "— all —"
        # Auto-select first real contest when only one name exists
        if len(sorted_keys) == 1 and contest_filter == "— all —":
            self._yoy_contest_var.set(cb_display[0])
            contest_filter = cb_display[0]

        # Apply filter — match on display_name (what the combobox shows)
        if contest_filter == "— all —":
            filtered_series = self._yoy_series
        else:
            # Find which contest_name(s) correspond to this display label
            matched_keys = {k for k, v in name_to_display.items() if v == contest_filter}
            filtered_series = [s for s in self._yoy_series
                               if s["contest_name"] in matched_keys]

        # ── Roster ───────────────────────────────────────────────────────────
        for iid in self._yoy_roster.get_children():
            self._yoy_roster.delete(iid)

        sorted_series = sorted(filtered_series, key=lambda s: s["year"])
        prev_score = None
        prev_qsos  = None

        for s in sorted_series:
            vis_marker = "●" if s["visible"] else "○"

            d_score = ""
            d_qsos  = ""
            if prev_score is not None:
                diff_s = s["final_score"] - prev_score
                diff_q = s["final_qsos"]  - prev_qsos
                sign_s = "+" if diff_s >= 0 else "−"
                sign_q = "+" if diff_q >= 0 else "−"
                d_score = f"{sign_s}{abs(diff_s):,}"
                d_qsos  = f"{sign_q}{abs(diff_q)}"

            self._yoy_roster.insert(
                "", "end",
                iid=s["key"],
                values=(
                    vis_marker,
                    s["year"],
                    s.get("display_name", s["contest_name"]),
                    f"{s['final_score']:,}",
                    s["final_qsos"],
                    s["final_mults"],
                    f"{s['total_hrs']:.1f}",
                    d_score,
                    d_qsos,
                ),
                tags=(s["colour"],),
            )
            try:
                self._yoy_roster.tag_configure(s["colour"], foreground=s["colour"])
            except Exception:
                pass

            prev_score = s["final_score"]
            prev_qsos  = s["final_qsos"]

        # ── Chart ─────────────────────────────────────────────────────────────
        self.fig_yoy.clear()

        visible = [s for s in filtered_series if s["visible"]]

        if not visible:
            ax = self.fig_yoy.add_subplot(111)
            ax.set_facecolor(BG2)
            ax.text(
                0.5, 0.5,
                "Click  + Add Log File  to load contest logs.\n"
                "Add logs from different years of the same contest\n"
                "to overlay their score trajectories.",
                ha="center", va="center", color=MUTED,
                fontsize=11, fontfamily="monospace",
                transform=ax.transAxes, linespacing=2.0,
            )
            self.fig_yoy.patch.set_facecolor(BG2)
            self.canvas_yoy.draw_idle()
            self._yoy_insight_var.set(
                "Load two or more contest logs to compare trajectories.")
            return

        xmode   = self._yoy_xmode_var.get()
        metric  = self._yoy_metric_var.get()
        normalise = self._yoy_norm_var.get()
        annotate  = self._yoy_annot_var.get()

        use_elapsed = (xmode == "Hours elapsed")

        gs = self.fig_yoy.add_gridspec(
            2, 1, hspace=0.08,
            left=0.06, right=0.97, top=0.93, bottom=0.11,
            height_ratios=[3, 1],
        )
        ax_main = self.fig_yoy.add_subplot(gs[0])
        ax_rate = self.fig_yoy.add_subplot(gs[1], sharex=ax_main)

        for ax in (ax_main, ax_rate):
            ax.set_facecolor(BG2)
            for sp in ax.spines.values():
                sp.set_edgecolor(BG3)
            ax.tick_params(colors=MUTED, labelsize=8)

        # ── Block-boundary guide lines (elapsed mode only) ────────────────────
        if use_elapsed and self.log:
            dur_h = self.log._session_cfg.duration_mins / 60.0
            n_sess = self.log._session_cfg.num_sessions
            for bn in range(1, n_sess):
                bx = bn * dur_h
                ax_main.axvline(bx, color=BG3, lw=0.8, zorder=0)
                ax_rate.axvline(bx, color=BG3, lw=0.8, zorder=0)
                ax_main.text(bx + 0.05, 0, f"B{bn+1}",
                             transform=ax_main.get_xaxis_transform(),
                             fontsize=6.5, color=MUTED,
                             fontfamily="monospace", va="bottom")

        # ── Draw each series ──────────────────────────────────────────────────
        metric_keys = {
            "Score":        "cum_score",
            "QSOs":         "cum_qsos",
            "Multipliers":  "cum_mults",
            "QSOs/hr rate": None,          # handled separately
        }
        mk = metric_keys[metric]

        all_finals = []
        for s in visible:
            if mk:
                raw = s[mk]
            else:
                raw = s["rate_counts"] if use_elapsed else s["utc_rate_counts"]
            final = raw[-1] if raw else 1
            all_finals.append(final)

        for s in visible:
            col = s["colour"]

            if use_elapsed:
                xs = s["elapsed_hrs"]
            else:
                xs = s["utc_hrs"]

            if metric == "QSOs/hr rate":
                # Bar chart on ax_main is ugly with many series; use step line
                if use_elapsed:
                    rx = s["rate_hrs"]
                    ry = s["rate_counts"]
                else:
                    rx = s["utc_rate_hrs"]
                    ry = s["utc_rate_counts"]
                if normalise:
                    peak = max(ry) if max(ry) > 0 else 1
                    ry = [v / peak * 100 for v in ry]
                ax_main.step(rx, ry, where="mid",
                             color=col, lw=1.6, alpha=0.85,
                             label=s["label"], zorder=3)
                ax_main.fill_between(rx, ry, step="mid",
                                     color=col, alpha=0.08, zorder=2)
                # rate subplot stays blank in this mode
                ax_rate.set_visible(False)
            else:
                ys = s[mk]
                if normalise:
                    denom = ys[-1] if ys and ys[-1] > 0 else 1
                    ys = [v / denom * 100 for v in ys]

                ax_main.plot(xs, ys,
                             color=col, lw=2.2,
                             solid_capstyle="round",
                             label=s["label"], zorder=3)
                ax_main.fill_between(xs, ys, alpha=0.06, color=col, zorder=2)

                # End-point dot + label
                if xs and ys:
                    ax_main.plot(xs[-1], ys[-1], "o",
                                 color=col, ms=5, zorder=4)
                    if annotate:
                        ax_main.annotate(
                            f" {s['year']}: {ys[-1]:,.0f}"
                            + ("%" if normalise else ""),
                            xy=(xs[-1], ys[-1]),
                            xytext=(4, 0), textcoords="offset points",
                            fontsize=7.5, color=col,
                            fontfamily="monospace",
                            va="center",
                        )

                # Rate subplot — per-hour bars
                if use_elapsed:
                    rx, ry = s["rate_hrs"], s["rate_counts"]
                else:
                    rx, ry = s["utc_rate_hrs"], s["utc_rate_counts"]
                ax_rate.step(rx, ry, where="mid",
                             color=col, lw=1.2, alpha=0.7, zorder=2)

        # ── Axes decoration — main ────────────────────────────────────────────
        y_labels = {
            "Score":       "Score" + (" (% of final)" if normalise else ""),
            "QSOs":        "Cumulative QSOs" + (" (%)" if normalise else ""),
            "Multipliers": "Cumulative Mults" + (" (%)" if normalise else ""),
            "QSOs/hr rate":"QSOs/hr" + (" (% of peak)" if normalise else ""),
        }
        ax_main.set_ylabel(y_labels[metric],
                           color=MUTED, fontfamily="monospace", fontsize=9)

        x_label = "Hours elapsed since contest start" if use_elapsed else "UTC hour"
        ax_rate.set_xlabel(x_label, color=MUTED,
                           fontfamily="monospace", fontsize=9)
        ax_rate.set_ylabel("QSOs/hr",
                           color=MUTED, fontfamily="monospace", fontsize=8)

        n_vis = len(visible)
        title = (
            f"{metric} Trajectory — {n_vis} contest year"
            f"{'s' if n_vis != 1 else ''}  "
            f"({'elapsed time' if use_elapsed else 'UTC clock'})"
        )
        ax_main.set_title(title, color=FG,
                          fontfamily="monospace", fontsize=10, pad=5)

        if not use_elapsed:
            ax_main.set_xlim(-0.5, 23.5)
            ax_rate.set_xlim(-0.5, 23.5)
            ax_rate.set_xticks(range(0, 24, 2))
            ax_rate.set_xticklabels(
                [f"{h:02d}" for h in range(0, 24, 2)],
                color=MUTED, fontsize=7, fontfamily="monospace",
            )

        for lbl in ax_main.get_xticklabels():
            lbl.set_visible(False)

        leg = ax_main.legend(
            facecolor=BG3, edgecolor="none",
            labelcolor=FG, fontsize=8,
            loc="upper left",
        )
        for line in leg.get_lines():
            line.set_linewidth(2.2)

        self.fig_yoy.patch.set_facecolor(BG2)
        self.canvas_yoy.draw_idle()

        # ── Insight bar ───────────────────────────────────────────────────────
        self._yoy_insight_var.set(self._yoy_insight(filtered_series))


    # ═══════════════════════════════════════════════════════════════════════════
    # ── Pace Tracker tab ─────────────────────────────────────────────────────
    # ═══════════════════════════════════════════════════════════════════════════
    #
    # Architecture:
    #   _pace_refs       — list of reference-year series dicts (same structure
    #                      as _yoy_series but built from operator-loaded logs)
    #   _refresh_pace()  — rebuilds chart on every log reload
    #   _pace_alarm_tick() — 30-second polling loop; computes live deficit and
    #                        flashes the alarm banner when behind target pace
    #
    # Deficit formula (elapsed-time aligned):
    #   For each reference year R, find the cumulative QSO count at the same
    #   elapsed-time offset as "now".  Deficit = ref_cum - live_cum.
    #   The worst (most behind) reference drives the alarm colour/text.
    # ─────────────────────────────────────────────────────────────────────────

    # Palette for reference series (cycles)
    _PACE_PALETTE = [
        "#f0c040", "#ff6b35", "#e040fb", "#64b5f6",
        "#2ed573", "#ff5252", "#ffab40", "#00bcd4",
    ]

    def _build_pace_tab(self):
        f = self.tab_pace
        f.configure(bg=BG2)

        # ── State ────────────────────────────────────────────────────────────
        self._pace_refs       = []    # reference year series
        self._pace_extra_dbs  = []    # extra .s3db paths loaded by operator
        self._pace_alarm_job  = None  # after() handle for alarm polling
        self._pace_flash_state = True # toggle for flashing alarm

        # ── Header ───────────────────────────────────────────────────────────
        hdr = tk.Frame(f, bg=BG2)
        hdr.pack(fill="x", padx=12, pady=(8, 2))
        tk.Label(hdr, text="🏁  Pace Tracker",
                 font=FONT_H, fg=ACCENT, bg=BG2).pack(side="left")
        tk.Label(hdr, text="  Compare your live QSO rate vs personal bests from previous years",
                 font=FONT_S, fg=MUTED, bg=BG2).pack(side="left")

        # ── Toolbar ──────────────────────────────────────────────────────────
        tb = tk.Frame(f, bg=BG2)
        tb.pack(fill="x", padx=12, pady=(2, 4))
        self._btn(tb, "+ Add Reference Log", self._pace_add_log).pack(side="left", padx=(0, 6))
        self._btn(tb, "✕ Clear References", self._pace_clear_refs,
                  style="secondary").pack(side="left", padx=(0, 12))

        # Target pace selector
        tk.Label(tb, text="Target reference:", font=FONT_S, fg=MUTED, bg=BG2).pack(
            side="left", padx=(0, 4))
        self._pace_target_var = tk.StringVar(value="Best year")
        self._pace_target_cb  = ttk.Combobox(
            tb, textvariable=self._pace_target_var,
            values=["Best year"], width=22, state="readonly", font=FONT_B,
        )
        self._pace_target_cb.pack(side="left", padx=(0, 12))
        self._pace_target_cb.bind("<<ComboboxSelected>>", lambda e: self._refresh_pace())
        _Tooltip(self._pace_target_cb,
                 "Which reference year to use for the pace alarm.\n"
                 "'Best year' picks the year with the highest cumulative QSOs\n"
                 "at the current elapsed time.")

        # Alarm threshold
        tk.Label(tb, text="Alarm if behind by ≥", font=FONT_S, fg=MUTED, bg=BG2).pack(
            side="left", padx=(0, 3))
        self._pace_thresh_var = tk.IntVar(value=5)
        thresh_spin = tk.Spinbox(
            tb, textvariable=self._pace_thresh_var,
            from_=1, to=50, width=4,
            font=FONT_MONO, bg=BG3, fg=FG,
            insertbackground=FG, relief="flat", bd=0,
            buttonbackground=BG3,
            selectbackground=ACCENT, selectforeground=BG,
            command=self._refresh_pace,
        )
        thresh_spin.pack(side="left")
        tk.Label(tb, text=" QSOs", font=FONT_S, fg=MUTED, bg=BG2).pack(side="left", padx=(0, 2))
        _Tooltip(thresh_spin,
                 "Flash the alarm banner when your current QSO total falls\n"
                 "this many QSOs or more behind the target reference pace.")

        # ── Alarm banner ─────────────────────────────────────────────────────
        self._pace_alarm_frame = tk.Frame(f, bg=BG3,
                                          highlightbackground=BG3,
                                          highlightthickness=2)
        self._pace_alarm_frame.pack(fill="x", padx=12, pady=(0, 4))
        self._pace_alarm_var = tk.StringVar(
            value="  📊  Load a reference log to start tracking pace.")
        self._pace_alarm_lbl = tk.Label(
            self._pace_alarm_frame,
            textvariable=self._pace_alarm_var,
            font=("Consolas", 11, "bold"), fg=ACCENT3, bg=BG3,
            anchor="w", pady=8, padx=10,
        )
        self._pace_alarm_lbl.pack(fill="x")

        # ── Reference log roster ─────────────────────────────────────────────
        roster_outer = tk.Frame(f, bg=BG2)
        roster_outer.pack(fill="x", padx=12, pady=(0, 4))

        roster_cols = ("Vis", "Year", "Contest", "Total QSOs", "Avg QSO/hr", "Status")
        self._pace_roster = ttk.Treeview(
            roster_outer, columns=roster_cols,
            show="headings", height=3, selectmode="browse",
        )
        _style_tree(self._pace_roster, self)
        for col, w in zip(roster_cols, [34, 54, 240, 80, 90, 200]):
            self._pace_roster.heading(col, text=col)
            self._pace_roster.column(col, width=w, anchor="center")
        rsb = ttk.Scrollbar(roster_outer, orient="vertical",
                             command=self._pace_roster.yview)
        self._pace_roster.configure(yscroll=rsb.set)
        self._pace_roster.pack(side="left", fill="x", expand=True)
        rsb.pack(side="right", fill="y")
        self._pace_roster.bind("<ButtonRelease-1>", self._pace_roster_click)
        _Tooltip(self._pace_roster,
                 "Reference years loaded for pace comparison.\n"
                 "Click the Vis column to show/hide a series on the chart.\n"
                 "Add logs from previous years with '+ Add Reference Log'.\n"
                 "Accepts N1MM+ .s3db, ADIF (.adi/.adif), or Cabrillo (.log/.cbr/.txt).")

        # ── Matplotlib figure ─────────────────────────────────────────────────
        tk.Label(f, text="Cumulative QSOs vs elapsed time since contest start  (live = solid teal)",
                 font=FONT_S, fg=MUTED, bg=BG2).pack(anchor="w", padx=14, pady=(0, 2))
        self._pace_fig_frame = tk.Frame(f, bg=BG2)
        self._pace_fig_frame.pack(fill="both", expand=True, padx=12, pady=(0, 2))
        self.fig_pace    = None
        self.canvas_pace = None

        # ── Insight bar ───────────────────────────────────────────────────────
        ins_frame = tk.Frame(f, bg=BG3, highlightbackground=BG3, highlightthickness=1)
        ins_frame.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(ins_frame, text="  Pace insight:  ",
                 font=("Consolas", 9, "bold"), fg=ACCENT3, bg=BG3).pack(side="left")
        self._pace_insight_var = tk.StringVar(
            value="Load one or more reference logs to see pace comparison insights.")
        tk.Label(ins_frame, textvariable=self._pace_insight_var,
                 font=("Consolas", 9), fg=FG, bg=BG3,
                 anchor="w", wraplength=1200, justify="left").pack(
                     side="left", fill="x", expand=True, pady=4)

        # ── Start alarm polling ───────────────────────────────────────────────
        self._pace_alarm_tick()

    # ── Pace Tracker helpers ──────────────────────────────────────────────────

    def _pace_add_log(self):
        """
        Let the operator pick a reference log in any supported format:
          - N1MM+ .s3db  (SQLite - existing path)
          - ADIF  .adi / .adif
          - Cabrillo  .log / .cbr / .txt
        """
        p = filedialog.askopenfilename(
            title="Add Reference Log File",
            filetypes=[
                ("All supported logs",
                 "*.s3db *.db *.sqlite *.adi *.adif *.log *.cbr *.txt"),
                ("N1MM+ SQLite",   "*.s3db *.db *.sqlite"),
                ("ADIF",           "*.adi *.adif"),
                ("Cabrillo",       "*.log *.cbr *.txt"),
                ("All files",      "*.*"),
            ],
        )
        if not p:
            return

        ext = os.path.splitext(p)[1].lower()
        if ext in (".s3db", ".db", ".sqlite"):
            if p not in self._pace_extra_dbs and p != getattr(self, "_db_path", None):
                self._pace_extra_dbs.append(p)
            self._pace_load_series_from_db(p)
        elif ext in (".adi", ".adif"):
            self._pace_load_series_from_adif(p)
        else:
            # Cabrillo (.log, .cbr, .txt) - sniff first to confirm
            self._pace_load_series_from_cabrillo(p)

        self._refresh_pace()

    def _pace_clear_refs(self):
        """Remove all reference series (does not affect current log)."""
        self._pace_refs.clear()
        self._pace_extra_dbs.clear()
        self._refresh_pace()

    def _pace_roster_click(self, event):
        """Toggle visibility when the operator clicks the Vis column."""
        row = self._pace_roster.identify_row(event.y)
        col = self._pace_roster.identify_column(event.x)
        if not row or col != "#1":
            return
        iid = row
        for s in self._pace_refs:
            if s.get("_roster_iid") == iid:
                s["visible"] = not s["visible"]
                break
        self._pace_redraw()

    def _pace_build_trajectory(self, log):
        """
        Build an elapsed-time cumulative QSO trajectory from a ContestLog.
        Returns a dict with arrays suitable for pace comparison, or None if
        the log has no usable data.
        """
        valid = sorted(
            [q for q in log.qsos if not q["dupe"]],
            key=lambda q: q["time"],
        )
        cs = log.contest_start()
        if not cs or not valid:
            return None

        elapsed_hrs  = []
        cum_qsos     = []
        for q in valid:
            e_hrs = (q["time"] - cs).total_seconds() / 3600.0
            elapsed_hrs.append(e_hrs)
            cum_qsos.append(len(cum_qsos) + 1)

        # Hourly rate buckets for secondary sub-chart
        max_e = elapsed_hrs[-1] if elapsed_hrs else 0
        n_buckets = max(1, int(max_e) + 1)
        rate_counts = [0] * n_buckets
        for e in elapsed_hrs:
            b = min(int(e), n_buckets - 1)
            rate_counts[b] += 1
        rate_hrs = [b + 0.5 for b in range(n_buckets)]

        return {
            "elapsed_hrs":  elapsed_hrs,
            "cum_qsos":     cum_qsos,
            "rate_hrs":     rate_hrs,
            "rate_counts":  rate_counts,
            "final_qsos":   cum_qsos[-1] if cum_qsos else 0,
            "total_hrs":    max_e,
        }

    # ── ADIF / Cabrillo reference log parsers ────────────────────────────────

    def _pace_build_trajectory_from_qsos(self, qsos, contest_start, label, year,
                                          source_name, source_key):
        """
        Build a pace reference series dict from a plain list of QSO dicts.
        Each dict needs at minimum: {"time": datetime, "dupe": 0|1}.
        contest_start is a datetime marking elapsed-time t=0.
        Returns a fully-formed series dict ready for self._pace_refs, or None.
        """
        valid = sorted(
            [q for q in qsos if not q.get("dupe", 0)],
            key=lambda q: q["time"],
        )
        if not valid:
            return None

        elapsed_hrs, cum_qsos = [], []
        for q in valid:
            e = (q["time"] - contest_start).total_seconds() / 3600.0
            if e < 0:
                continue   # QSO before derived contest start — skip
            elapsed_hrs.append(e)
            cum_qsos.append(len(cum_qsos) + 1)

        if not elapsed_hrs:
            return None

        max_e = elapsed_hrs[-1]
        n_buckets = max(1, int(max_e) + 1)
        rate_counts = [0] * n_buckets
        for e in elapsed_hrs:
            b = min(int(e), n_buckets - 1)
            rate_counts[b] += 1
        rate_hrs = [b + 0.5 for b in range(n_buckets)]

        colour = self._PACE_PALETTE[len(self._pace_refs) % len(self._PACE_PALETTE)]
        return {
            "key":          source_key,
            "label":        label,
            "year":         year,
            "contest_name": source_name,
            "db_path":      None,
            "contest_nr":   None,
            "colour":       colour,
            "visible":      True,
            "_roster_iid":  None,
            "elapsed_hrs":  elapsed_hrs,
            "cum_qsos":     cum_qsos,
            "rate_hrs":     rate_hrs,
            "rate_counts":  rate_counts,
            "final_qsos":   cum_qsos[-1],
            "total_hrs":    max_e,
        }

    # ── ADIF parser ───────────────────────────────────────────────────────────

    @staticmethod
    def _parse_adif_fields(text):
        """
        Yield dicts of {field_name_upper: value} for every record in an ADIF
        string.  Handles both header (ends at <EOH>) and data records (<EOR>).
        Field syntax:  <FIELD_NAME:length>value
        """
        import re
        tag_re = re.compile(r"<([^:>]+)(?::(\d+)(?::[^>]*)?)?>", re.IGNORECASE)
        pos = 0
        text_len = len(text)
        # Skip past header block if present
        eoh = re.search(r"<EOH>", text, re.IGNORECASE)
        if eoh:
            pos = eoh.end()

        record = {}
        while pos < text_len:
            m = tag_re.search(text, pos)
            if not m:
                break
            tag  = m.group(1).upper()
            lstr = m.group(2)
            pos  = m.end()
            if tag == "EOR":
                if record:
                    yield record
                record = {}
                continue
            if lstr is None:
                continue
            length = int(lstr)
            value  = text[pos:pos + length]
            pos   += length
            record[tag] = value

        if record:   # file without final <EOR>
            yield record

    def _pace_load_series_from_adif(self, path):
        """
        Parse an ADIF file and add it as a pace reference series.
        Uses QSO_DATE + TIME_ON for timestamps; ignores dupes (ADIF files
        from loggers rarely mark them, so all records are treated as valid).
        Contest start is derived from the earliest QSO in the file.
        """
        existing_keys = {s["key"] for s in self._pace_refs}
        key = f"adif::{path}"
        if key in existing_keys:
            messagebox.showinfo("Already loaded",
                                f"This ADIF file is already loaded as a reference.")
            return

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception as e:
            messagebox.showerror("Read error",
                                 f"Could not read ADIF file:\n{path}\n\n{e}")
            return

        qsos = []
        bad  = 0
        for rec in self._parse_adif_fields(text):
            date_str = rec.get("QSO_DATE", "").strip()
            time_str = rec.get("TIME_ON",  "").strip().ljust(6, "0")[:6]
            if not date_str:
                bad += 1
                continue
            try:
                t = datetime.strptime(date_str + time_str, "%Y%m%d%H%M%S")
            except ValueError:
                try:
                    t = datetime.strptime(date_str + time_str[:4], "%Y%m%d%H%M")
                except ValueError:
                    bad += 1
                    continue
            qsos.append({
                "time":  t,
                "dupe":  0,
                "call":  rec.get("CALL", ""),
                "band":  rec.get("BAND", ""),
                "mode":  rec.get("MODE", ""),
            })

        if not qsos:
            messagebox.showwarning(
                "No QSOs found",
                f"No valid QSOs could be parsed from:\n{path}"
                + (f"\n({bad} records had unparseable timestamps.)" if bad else "")
            )
            return

        qsos.sort(key=lambda q: q["time"])
        contest_start = qsos[0]["time"].replace(minute=0, second=0, microsecond=0)
        year  = contest_start.year
        fname = os.path.splitext(os.path.basename(path))[0]
        label = f"{year} — {fname} (ADIF)"

        series = self._pace_build_trajectory_from_qsos(
            qsos, contest_start, label, year, fname, key
        )
        if series is None:
            messagebox.showwarning("No usable QSOs",
                                   f"ADIF loaded but no QSOs fell within the contest window.")
            return

        self._pace_refs.append(series)
        logging.info("ADIF pace ref loaded: %s  (%d QSOs)", label, series["final_qsos"])
        if bad:
            logging.warning("ADIF: %d records skipped (bad timestamp)", bad)

    # ── Cabrillo parser ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_cabrillo(text):
        """
        Parse a Cabrillo v2/v3 log.
        Returns (header_dict, qso_list) where each qso has:
          {time, dupe, freq, mode, call, sent_rst, sent_exch, rcvd_rst, rcvd_exch}

        Cabrillo QSO line format (v3):
          QSO: freq  mo date     time  mycall        rst snt  theircall     rst rcv  [t]
          QSO: 14000 PH 2023-11-04 1200 VK2YI        59  NSW  VK3ABC        59  VIC  0

        v2 uses the same basic structure but date format may be YYYY-MM-DD.
        """
        import re
        header = {}
        qsos   = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("START-OF-LOG") or line.startswith("END-OF-LOG"):
                continue
            if line.upper().startswith("QSO:"):
                parts = line[4:].split()
                # Minimum: freq mode date time mycall rst_s exch_s theircall rst_r exch_r
                if len(parts) < 8:
                    continue
                # Date: parts[2] format YYYY-MM-DD
                # Time: parts[3] format HHMM or HH:MM
                date_s = parts[2].replace("/", "-")
                time_s = parts[3].replace(":", "")
                try:
                    t = datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H%M")
                except ValueError:
                    continue
                qsos.append({
                    "time":       t,
                    "dupe":       0,
                    "freq":       parts[0],
                    "mode":       parts[1],
                    "call":       parts[4] if len(parts) > 4 else "",
                    "sent_rst":   parts[5] if len(parts) > 5 else "",
                    "sent_exch":  parts[6] if len(parts) > 6 else "",
                    "their_call": parts[7] if len(parts) > 7 else "",
                    "rcvd_rst":   parts[8] if len(parts) > 8 else "",
                    "rcvd_exch":  parts[9] if len(parts) > 9 else "",
                    "transmitter": parts[10] if len(parts) > 10 else "0",
                })
            elif ":" in line:
                k, _, v = line.partition(":")
                header[k.strip().upper()] = v.strip()
        return header, qsos

    def _pace_load_series_from_cabrillo(self, path):
        """
        Parse a Cabrillo file and add it as a pace reference series.
        Uses the CONTEST header field for the contest name and
        QSO-DATE-START (or first QSO) for contest start time.
        """
        existing_keys = {s["key"] for s in self._pace_refs}
        key = f"cabrillo::{path}"
        if key in existing_keys:
            messagebox.showinfo("Already loaded",
                                "This Cabrillo file is already loaded as a reference.")
            return

        try:
            # Try UTF-8 first, fall back to latin-1 (common for old contest logs)
            for enc in ("utf-8", "latin-1", "cp1252"):
                try:
                    with open(path, "r", encoding=enc, errors="strict") as f:
                        text = f.read()
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            else:
                messagebox.showerror("Read error",
                                     f"Could not decode Cabrillo file:\n{path}")
                return
        except Exception as e:
            messagebox.showerror("Read error",
                                 f"Could not read file:\n{path}\n\n{e}")
            return

        # Sniff: must start with START-OF-LOG or contain QSO: lines
        upper = text[:500].upper()
        if "START-OF-LOG" not in upper and "QSO:" not in upper:
            messagebox.showwarning(
                "Not a Cabrillo file",
                f"This file does not appear to be a Cabrillo log:\n{path}\n\n"
                "Expected 'START-OF-LOG' header or 'QSO:' lines.\n"
                "If it is an ADIF file, rename it to .adi and try again."
            )
            return

        header, qsos = self._parse_cabrillo(text)

        if not qsos:
            messagebox.showwarning(
                "No QSOs found",
                f"No valid QSO lines could be parsed from:\n{path}"
            )
            return

        qsos.sort(key=lambda q: q["time"])

        # Derive contest start from header or first QSO
        contest_start = None
        start_hdr = header.get("QSO-DATE-START") or header.get("DATE-START")
        if start_hdr:
            for fmt in ("%Y-%m-%d %H%M", "%Y-%m-%d", "%Y-%m-%d %H:%M"):
                try:
                    contest_start = datetime.strptime(start_hdr.strip()[:16], fmt)
                    break
                except ValueError:
                    continue
        if contest_start is None:
            # Fall back to midnight of first QSO day
            first = qsos[0]["time"]
            contest_start = first.replace(hour=0, minute=0, second=0, microsecond=0)

        year  = contest_start.year
        contest_name = header.get("CONTEST", "") or header.get("CONTEST-ID", "")
        fname = os.path.splitext(os.path.basename(path))[0]
        display_name = contest_name if contest_name else fname
        label = f"{year} — {display_name} (Cabrillo)"

        series = self._pace_build_trajectory_from_qsos(
            qsos, contest_start, label, year, display_name, key
        )
        if series is None:
            messagebox.showwarning("No usable QSOs",
                                   "Cabrillo loaded but no QSOs fell after the contest start time.")
            return

        self._pace_refs.append(series)
        logging.info("Cabrillo pace ref loaded: %s  (%d QSOs, start=%s)",
                     label, series["final_qsos"], contest_start)

    def _pace_load_series_from_db(self, db_path):
        """
        Load selected contests from db_path into self._pace_refs.
        Shows a picker dialog listing all contests in the DB so the operator
        can choose which one(s) to use as reference — rather than loading
        every contest indiscriminately.
        """
        existing_keys = {s["key"] for s in self._pace_refs}
        try:
            contests = ContestLog.available_contests(db_path)
        except Exception as e:
            messagebox.showerror("Load failed",
                                 f"Could not read contests from:\n{db_path}\n\n{e}")
            return

        # Build candidate list (skip empty and already-loaded contests)
        candidates = []
        for ci in contests:
            if ci.get("QSOCount", 0) == 0:
                continue
            key = f"{db_path}::{ci['ContestNR']}"
            if key in existing_keys:
                continue
            try:
                sd       = str(ci.get("StartDate", ""))[:4]
                year     = int(sd) if sd.isdigit() else 0
            except Exception:
                year = 0
            name = str(ci.get("DisplayName") or ci.get("ContestName", "?"))
            candidates.append({
                "ci":   ci,
                "key":  key,
                "year": year,
                "name": name,
                "label": f"{year} — {name}  ({ci.get('QSOCount', '?')} QSOs)",
            })

        if not candidates:
            messagebox.showinfo("Nothing to add",
                                "All contests in this database are already loaded\n"
                                "or contain no QSOs.")
            return

        # ── Contest picker dialog ─────────────────────────────────────────────
        dlg = tk.Toplevel(self)
        dlg.title("Select contests to add as reference")
        dlg.configure(bg=BG)
        dlg.resizable(True, True)
        dlg.attributes("-alpha", 0.0)
        dlg.grab_set()

        tk.Label(dlg, text="Choose contest(s) to add as pace reference:",
                 bg=BG, fg=FG, font=("Consolas", 10)).pack(anchor="w", padx=12, pady=(10, 4))
        _fade_in(dlg, target_alpha=0.98)

        lb_frame = tk.Frame(dlg, bg=BG)
        lb_frame.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        sb = tk.Scrollbar(lb_frame, orient="vertical")
        lb = tk.Listbox(lb_frame, selectmode="extended",
                        bg=BG2, fg=FG, selectbackground=ACCENT,
                        selectforeground=BG, font=("Consolas", 9),
                        yscrollcommand=sb.set, height=min(len(candidates), 18),
                        activestyle="none", relief="flat", bd=0)
        sb.configure(command=lb.yview)
        lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        for c in candidates:
            lb.insert("end", c["label"])

        # Pre-select entries whose plugin matches the current live contest
        current_plugin_type = type(self.log.plugin) if self.log else None
        for i, c in enumerate(candidates):
            ci_plugin = plugin_for(str(c["ci"].get("ContestName", "")))
            if current_plugin_type and type(ci_plugin) is current_plugin_type:
                lb.selection_set(i)

        tk.Label(dlg, text="(Ctrl-click or Shift-click to select multiple)",
                 bg=BG, fg=MUTED, font=("Consolas", 8)).pack(anchor="w", padx=12)

        selected_indices = []

        def _ok():
            selected_indices.extend(lb.curselection())
            dlg.destroy()

        def _cancel():
            dlg.destroy()

        btn_frame = tk.Frame(dlg, bg=BG)
        btn_frame.pack(fill="x", padx=12, pady=10)
        self._btn(btn_frame, "Add Selected", _ok).pack(side="left", padx=(0, 6))
        self._btn(btn_frame, "Cancel", _cancel).pack(side="left")
        dlg.bind("<Return>", lambda e: _ok())
        dlg.bind("<Escape>", lambda e: _cancel())

        # Centre over main window
        self.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width()  - 500) // 2
        y = self.winfo_rooty() + (self.winfo_height() - 400) // 2
        dlg.geometry(f"500x{min(400, 80 + len(candidates)*18)}+{x}+{y}")
        dlg.wait_window()

        if not selected_indices:
            return   # user cancelled or selected nothing

        # ── Load the chosen contests ──────────────────────────────────────────
        loaded = 0
        for i in selected_indices:
            c = candidates[i]
            ci = c["ci"]
            try:
                p   = plugin_for(str(ci.get("ContestName", "")))
                log = ContestLog(db_path, contest_nr=ci["ContestNR"], plugin=p)
                if not log.qsos:
                    continue
                traj = self._pace_build_trajectory(log)
                if traj is None:
                    continue
                # Resolve year: prefer QSO year when StartDate is far off
                try:
                    sd       = str(ci.get("StartDate", ""))[:4]
                    start_yr = int(sd) if sd.isdigit() else 0
                    qso_yr   = log.qsos[0]["time"].year if log.qsos else 0
                    year = qso_yr if (start_yr and qso_yr and abs(start_yr - qso_yr) > 1)                            else (start_yr or qso_yr)
                except Exception:
                    year = c["year"]
                colour = self._PACE_PALETTE[len(self._pace_refs) % len(self._PACE_PALETTE)]
                self._pace_refs.append({
                    "key":          c["key"],
                    "label":        f"{year} — {c['name']}",
                    "year":         year,
                    "contest_name": c["name"],
                    "db_path":      db_path,
                    "contest_nr":   ci["ContestNR"],
                    "colour":       colour,
                    "visible":      True,
                    "_roster_iid":  None,
                    **traj,
                })
                existing_keys.add(c["key"])
                loaded += 1
            except Exception as e:
                logging.warning("pace: failed loading contest %s: %s",
                                ci.get("ContestNR"), e)

        if loaded == 0:
            messagebox.showwarning("Nothing loaded",
                                   "Selected contests had no usable QSO data.")

    def _pace_live_trajectory(self):
        """
        Build elapsed-time cumulative QSO trajectory for the currently-loaded log.
        Returns (elapsed_hrs, cum_qsos) lists or ([], []).
        """
        if not self.log or not self.log.qsos:
            return [], []
        valid = sorted(
            [q for q in self.log.qsos if not q["dupe"]],
            key=lambda q: q["time"],
        )
        cs = self.log.contest_start()
        if not cs:
            return [], []
        elapsed_hrs, cum_qsos = [], []
        for q in valid:
            e = (q["time"] - cs).total_seconds() / 3600.0
            elapsed_hrs.append(e)
            cum_qsos.append(len(cum_qsos) + 1)
        return elapsed_hrs, cum_qsos

    def _pace_deficit_at_now(self):
        """
        Return a list of (label, year, deficit, ref_total_at_t) tuples — one per
        visible reference series — describing how many QSOs ahead/behind the
        operator currently is vs each reference.
        Positive deficit = behind reference.  Negative = ahead.
        Returns [] if there are no references or no live log.
        """
        live_elapsed, live_cum = self._pace_live_trajectory()
        if not live_elapsed:
            return []

        now_elapsed = live_elapsed[-1]   # hours since contest start right now
        live_total  = live_cum[-1]

        results = []
        for s in self._pace_refs:
            if not s.get("visible", True):
                continue
            # Binary search / linear interp for ref cumulative count at now_elapsed
            ref_e = s["elapsed_hrs"]
            ref_c = s["cum_qsos"]
            if not ref_e:
                continue
            if now_elapsed >= ref_e[-1]:
                ref_at_now = ref_c[-1]
            else:
                # Find first ref point past now_elapsed
                ref_at_now = 0
                for i, e in enumerate(ref_e):
                    if e >= now_elapsed:
                        ref_at_now = ref_c[i]
                        break
            deficit = ref_at_now - live_total
            results.append({
                "label":    s["label"],
                "year":     s["year"],
                "deficit":  deficit,
                "ref_at_t": ref_at_now,
                "colour":   s["colour"],
            })
        return results

    def _pace_alarm_tick(self):
        """
        30-second polling loop.  Evaluates the pace deficit and updates the
        alarm banner.  Flashes the banner background when the operator is
        behind threshold.
        """
        try:
            if not hasattr(self, "_pace_alarm_lbl"):
                return   # tab not yet built; bail silently

            thresh = getattr(self, "_pace_thresh_var", None)
            thresh_val = thresh.get() if thresh else 5

            deficits = self._pace_deficit_at_now()

            if not self.log:
                self._pace_alarm_lbl.configure(
                    text="  📊  Load a log file to start tracking.",
                    fg=MUTED, bg=BG3)
                self._pace_alarm_frame.configure(
                    highlightbackground=BG3, bg=BG3)
                self._pace_alarm_lbl.configure(bg=BG3)

            elif not deficits:
                self._pace_alarm_lbl.configure(
                    fg=MUTED, bg=BG3,
                    text="  📊  Load a reference log to compare pace.  "
                         "Use '+ Add Reference Log' above.")
                self._pace_alarm_frame.configure(
                    highlightbackground=BG3, bg=BG3)
                self._pace_alarm_lbl.configure(bg=BG3)

            else:
                worst = max(deficits, key=lambda d: d["deficit"])
                best  = min(deficits, key=lambda d: d["deficit"])

                if worst["deficit"] >= thresh_val:
                    # BEHIND — flash alarm
                    self._pace_flash_state = not self._pace_flash_state
                    flash_bg = RED if self._pace_flash_state else BG3
                    flash_fg = FG  if self._pace_flash_state else RED
                    msg = (
                        f"  ⚠  PACE ALARM  —  "
                        f"You are {worst['deficit']} QSOs behind your "
                        f"{worst['year']} pace right now!  "
                        f"({worst['ref_at_t']} QSOs at this point in {worst['year']})"
                    )
                    self._pace_alarm_lbl.configure(fg=flash_fg, bg=flash_bg, text=msg)
                    self._pace_alarm_frame.configure(
                        highlightbackground=RED, bg=flash_bg)

                elif best["deficit"] <= -thresh_val:
                    # AHEAD
                    self._pace_flash_state = True
                    msg = (
                        f"  🚀  ON PACE  —  "
                        f"You are {abs(best['deficit'])} QSOs AHEAD of your "
                        f"{best['year']} pace!  Keep it up!"
                    )
                    self._pace_alarm_lbl.configure(fg=GREEN, bg=BG3, text=msg)
                    self._pace_alarm_frame.configure(
                        highlightbackground=GREEN, bg=BG3)

                else:
                    self._pace_flash_state = True
                    msg = (
                        f"  ✅  WITHIN TARGET  —  "
                        f"Tracking within ±{thresh_val} QSOs of reference pace  "
                        f"({'ahead' if worst['deficit'] <= 0 else 'behind'} by "
                        f"{abs(worst['deficit'])} QSOs vs {worst['year']})"
                    )
                    self._pace_alarm_lbl.configure(fg=ACCENT3, bg=BG3, text=msg)
                    self._pace_alarm_frame.configure(
                        highlightbackground=ACCENT3, bg=BG3)

        except Exception as e:
            logging.debug("_pace_alarm_tick error: %s", e)

        # Re-schedule — 30 s normally, 5 s while alarming (flash faster)
        try:
            interval = 5000 if (
                deficits and max(d["deficit"] for d in deficits) >= thresh_val
            ) else 30000
        except Exception:
            interval = 30000
        self._pace_alarm_job = self.after(interval, self._pace_alarm_tick)

    def _ensure_fig_pace(self):
        """Lazy init of pace matplotlib figure."""
        if not hasattr(self, "fig_pace"):
            return          # tab was disabled — build method never ran
        if self.fig_pace is not None:
            return
        self.fig_pace = Figure(figsize=(13, 4.2), facecolor=BG2)
        self.canvas_pace = FigureCanvasTkAgg(self.fig_pace, master=self._pace_fig_frame)
        self.canvas_pace.get_tk_widget().configure(bg=BG2)
        self.canvas_pace.get_tk_widget().pack(fill="both", expand=True)

    def _refresh_pace(self):
        """Full refresh of the pace tab: roster + chart + insight + alarm."""
        if not hasattr(self, "fig_pace"):
            return          # tab was disabled — build method never ran
        self._ensure_fig_pace()

        # ── Auto-load same-contest previous years from the current DB ─────────
        # Only loads contests that the same plugin owns (i.e. same contest name),
        # so the pace chart doesn't fill up with unrelated contests.
        if self.log and self._db_path:
            current_plugin = self.log.plugin
            existing_keys  = {s["key"] for s in self._pace_refs}
            try:
                contests = ContestLog.available_contests(self._db_path)
            except Exception:
                contests = []
            for ci in contests:
                if ci.get("QSOCount", 0) == 0:
                    continue
                if ci["ContestNR"] == self._contest_nr:
                    continue   # skip the *current* contest
                # ── Only include contests owned by the same plugin ────────────
                ci_plugin = plugin_for(str(ci.get("ContestName", "")))
                if type(ci_plugin) is not type(current_plugin):
                    continue
                key = f"{self._db_path}::{ci['ContestNR']}"
                if key in existing_keys:
                    continue
                try:
                    log = ContestLog(self._db_path,
                                     contest_nr=ci["ContestNR"], plugin=ci_plugin)
                    if not log.qsos:
                        continue
                    traj = self._pace_build_trajectory(log)
                    if traj is None:
                        continue
                    try:
                        sd   = str(ci.get("StartDate", ""))[:4]
                        year = int(sd) if sd.isdigit() else log.qsos[0]["time"].year
                    except Exception:
                        year = 0
                    name   = str(ci.get("DisplayName") or ci.get("ContestName", "?"))
                    colour = self._PACE_PALETTE[len(self._pace_refs) % len(self._PACE_PALETTE)]
                    self._pace_refs.append({
                        "key":          key,
                        "label":        f"{year} — {name}",
                        "year":         year,
                        "contest_name": name,
                        "db_path":      self._db_path,
                        "contest_nr":   ci["ContestNR"],
                        "colour":       colour,
                        "visible":      True,
                        "_roster_iid":  None,
                        **traj,
                    })
                    existing_keys.add(key)
                except Exception:
                    pass

        # ── Update target-pace combobox ───────────────────────────────────────
        labels = ["Best year"] + [s["label"] for s in self._pace_refs]
        self._pace_target_cb.configure(values=labels)
        if self._pace_target_var.get() not in labels:
            self._pace_target_var.set("Best year")

        # ── Roster ───────────────────────────────────────────────────────────
        for iid in self._pace_roster.get_children():
            self._pace_roster.delete(iid)

        for s in self._pace_refs:
            avg_rate = (s["final_qsos"] / s["total_hrs"]) if s["total_hrs"] > 0 else 0
            vis_sym  = "●" if s.get("visible", True) else "○"
            iid = self._pace_roster.insert("", "end", values=(
                vis_sym,
                s["year"],
                s["contest_name"],
                s["final_qsos"],
                f"{avg_rate:.1f}",
                "Reference",
            ))
            s["_roster_iid"] = iid

        # ── Chart ─────────────────────────────────────────────────────────────
        self._pace_redraw()

    def _pace_redraw(self):
        """Redraw the pace chart from current self._pace_refs + live log."""
        if self.fig_pace is None:
            return

        self.fig_pace.clear()

        gs = self.fig_pace.add_gridspec(
            2, 1, hspace=0.10,
            left=0.05, right=0.97, top=0.93, bottom=0.13,
            height_ratios=[3, 1],
        )
        ax_main = self.fig_pace.add_subplot(gs[0])
        ax_rate = self.fig_pace.add_subplot(gs[1], sharex=ax_main)

        for ax in (ax_main, ax_rate):
            ax.set_facecolor(BG2)
            for sp in ax.spines.values():
                sp.set_edgecolor(BG3)
            ax.tick_params(colors=MUTED, labelsize=8)

        # ── Reference series ──────────────────────────────────────────────────
        visible_refs = [s for s in self._pace_refs if s.get("visible", True)]

        for s in visible_refs:
            col = s["colour"]
            ax_main.plot(
                s["elapsed_hrs"], s["cum_qsos"],
                color=col, lw=1.6, linestyle="--", alpha=0.80,
                label=s["label"], zorder=2,
            )
            if s["elapsed_hrs"] and s["cum_qsos"]:
                ax_main.plot(s["elapsed_hrs"][-1], s["cum_qsos"][-1],
                             "o", color=col, ms=5, zorder=3)
                ax_main.annotate(
                    f" {s['year']}: {s['cum_qsos'][-1]} QSOs",
                    xy=(s["elapsed_hrs"][-1], s["cum_qsos"][-1]),
                    xytext=(4, 0), textcoords="offset points",
                    fontsize=7.5, color=col, fontfamily="monospace", va="center",
                )
            # Rate subplot
            ax_rate.step(s["rate_hrs"], s["rate_counts"],
                         where="mid", color=col, lw=1.0, alpha=0.55, zorder=2)

        # ── Live (current) log ────────────────────────────────────────────────
        live_elapsed, live_cum = self._pace_live_trajectory()
        if live_elapsed:
            ax_main.plot(
                live_elapsed, live_cum,
                color=ACCENT, lw=2.8,
                solid_capstyle="round",
                label="▶  This contest (live)",
                zorder=4,
            )
            ax_main.plot(live_elapsed[-1], live_cum[-1],
                         "o", color=ACCENT, ms=7, zorder=5)
            ax_main.annotate(
                f"  NOW: {live_cum[-1]} QSOs",
                xy=(live_elapsed[-1], live_cum[-1]),
                xytext=(6, 2), textcoords="offset points",
                fontsize=9, color=ACCENT, fontfamily="monospace",
                fontweight="bold", va="center",
            )

            # Live hourly rate bars
            if self.log:
                cs  = self.log.contest_start()
                rate_buckets: dict = defaultdict(int)
                for q in self.log.qsos:
                    if not q["dupe"] and cs:
                        e = (q["time"] - cs).total_seconds() / 3600.0
                        b = max(0, int(e))
                        rate_buckets[b] += 1
                if rate_buckets:
                    max_b = max(rate_buckets)
                    rr = [rate_buckets.get(b, 0) for b in range(max_b + 1)]
                    rx = [b + 0.5 for b in range(max_b + 1)]
                    ax_rate.bar(rx, rr, width=0.72,
                                color=ACCENT, alpha=0.75, zorder=3)

            # ── Deficit annotation line ───────────────────────────────────────
            thresh_val = self._pace_thresh_var.get() if hasattr(self, "_pace_thresh_var") else 5
            target_label = self._pace_target_var.get() if hasattr(self, "_pace_target_var") else "Best year"

            # Determine the target reference series
            target_s = None
            if visible_refs:
                if target_label == "Best year":
                    # Best = most QSOs at current elapsed time
                    now_e = live_elapsed[-1]
                    def _ref_at(s):
                        for i, e in enumerate(s["elapsed_hrs"]):
                            if e >= now_e:
                                return s["cum_qsos"][i]
                        return s["cum_qsos"][-1] if s["cum_qsos"] else 0
                    target_s = max(visible_refs, key=_ref_at)
                else:
                    for s in visible_refs:
                        if s["label"] == target_label:
                            target_s = s
                            break

            if target_s and live_elapsed:
                now_e = live_elapsed[-1]
                # Find reference QSO count at now_e
                ref_at_now = 0
                for i, e in enumerate(target_s["elapsed_hrs"]):
                    if e >= now_e:
                        ref_at_now = target_s["cum_qsos"][i]
                        break
                else:
                    ref_at_now = target_s["cum_qsos"][-1] if target_s["cum_qsos"] else 0

                deficit = ref_at_now - live_cum[-1]
                if abs(deficit) >= thresh_val:
                    ax_main.annotate(
                        "",
                        xy=(now_e, ref_at_now),
                        xytext=(now_e, live_cum[-1]),
                        arrowprops=dict(
                            arrowstyle="<->",
                            color=RED if deficit > 0 else GREEN,
                            lw=1.8,
                        ),
                    )
                    mid_qso = (ref_at_now + live_cum[-1]) / 2
                    deficit_txt = f"{abs(deficit)} QSOs {'behind' if deficit > 0 else 'ahead'}"
                    ax_main.text(
                        now_e + 0.08, mid_qso, deficit_txt,
                        color=RED if deficit > 0 else GREEN,
                        fontsize=8, fontfamily="monospace", va="center",
                        fontweight="bold",
                    )

        # ── No-data placeholder ───────────────────────────────────────────────
        if not visible_refs and not live_elapsed:
            ax_main.text(
                0.5, 0.5,
                "Load a reference log with '+ Add Reference Log'\nto compare pace.",
                ha="center", va="center", color=MUTED, fontsize=11,
                fontfamily="monospace", transform=ax_main.transAxes,
            )
            ax_rate.set_visible(False)

        # ── Axis decoration ───────────────────────────────────────────────────
        ax_main.set_ylabel("Cumulative QSOs", color=MUTED,
                           fontfamily="monospace", fontsize=9)
        ax_main.set_title("QSO Pace — Live vs Reference Years",
                          color=FG, fontfamily="monospace", fontsize=10, pad=5)
        ax_rate.set_xlabel("Hours since contest start",
                           color=MUTED, fontfamily="monospace", fontsize=9)
        ax_rate.set_ylabel("QSOs/hr", color=MUTED,
                           fontfamily="monospace", fontsize=8)
        for lbl in ax_main.get_xticklabels():
            lbl.set_visible(False)

        if visible_refs or live_elapsed:
            leg = ax_main.legend(
                facecolor=BG3, edgecolor="none",
                labelcolor=FG, fontsize=8, loc="upper left",
            )
            for line in leg.get_lines():
                line.set_linewidth(2.0)

        self.fig_pace.patch.set_facecolor(BG2)
        self.canvas_pace.draw_idle()

        # ── Insight bar ───────────────────────────────────────────────────────
        self._pace_insight_var.set(self._pace_insight(visible_refs, live_elapsed, live_cum))

        # Trigger alarm re-evaluation immediately
        self._pace_alarm_tick()

    def _pace_insight(self, refs, live_elapsed, live_cum):
        """Compose a human-readable insight string for the insight bar."""
        if not refs and not live_cum:
            return "Load a reference log to see pace insights."
        if not refs:
            return f"Live: {live_cum[-1] if live_cum else 0} QSOs at {live_elapsed[-1]:.1f}h — no reference loaded yet."
        if not live_cum:
            return f"{len(refs)} reference year(s) loaded — waiting for live log data."

        now_e      = live_elapsed[-1]
        live_total = live_cum[-1]
        thresh_val = self._pace_thresh_var.get() if hasattr(self, "_pace_thresh_var") else 5

        parts = []
        for s in refs:
            # Reference QSOs at current elapsed time
            ref_at_now = 0
            for i, e in enumerate(s["elapsed_hrs"]):
                if e >= now_e:
                    ref_at_now = s["cum_qsos"][i]
                    break
            else:
                ref_at_now = s["cum_qsos"][-1] if s["cum_qsos"] else 0

            deficit = ref_at_now - live_total
            if deficit > thresh_val:
                parts.append(f"⚠ {abs(deficit)} behind {s['year']}")
            elif deficit < -thresh_val:
                parts.append(f"🚀 {abs(deficit)} ahead of {s['year']}")
            else:
                parts.append(f"✅ within ±{thresh_val} of {s['year']}")

        return "  |  ".join(parts) if parts else "—"

    # ═══════════════════════════════════════════════════════════════════════════
    # ── DX Cluster Integration tab ───────────────────────────────────────────
    # ═══════════════════════════════════════════════════════════════════════════
    #
    # Architecture:
    #   _ClusterWorker   — background thread: Telnet connect + readline loop,
    #                      pushes raw spot lines into self._cluster_q (Queue)
    #   _cluster_poll()  — Tk .after() 500 ms loop: drains queue, classifies
    #                      each spot against current log, updates treeview
    #
    # Spot classification (per spot row):
    #   NEW_MULT   — call maps to a mult not yet worked on ANY band/mode
    #   NEW_BAND   — mult worked elsewhere, but not yet on this band/mode
    #   WORKED     — already worked this mult on this band/mode (dupe territory)
    #   NOT_MULT   — spot callsign/exchange doesn't resolve to a known mult
    #   NO_LOG     — no log loaded; can still display raw spots unclassified
    #
    # ─────────────────────────────────────────────────────────────────────────

    # Known public DX clusters (host, port, label)
    _CLUSTER_PRESETS = [
        ("dx.ve7cc.net",         7300, "VE7CC (NA)"),
        ("cluster.dl9gtb.de",    7300, "DL9GTB (EU)"),
        ("vk2rcg.ampr.org",      7300, "VK2RCG (VK)"),
        ("vk4rbd.dyndns.org",    7300, "VK4RBD (VK)"),
        ("hrd.wa9pie.net",       8000, "WA9PIE / HRD (NA)"),
        ("gb7mbc.spoo.org",      7300, "GB7MBC (EU)"),
        ("dxc.k0xm.net",         7300, "K0XM (NA)"),
        ("dxspider.dj1yfk.de",   7300, "DJ1YFK (EU)"),
        ("cluster.k3lr.com",     7300, "K3LR (NA)"),
    ]

    # Spot line regex — matches the standard PacketCluster DX de format:
    #   DX de VK2YI:    14195.0  VK3IO        599 VK Shires          2134Z
    _SPOT_RE = re.compile(
        r"DX\s+de\s+(\S+?):?\s+"        # group 1: spotter
        r"(\d+(?:\.\d+)?)\s+"           # group 2: frequency kHz
        r"(\S+)\s+"                     # group 3: dx callsign
        r"(.*?)"                        # group 4: comment
        r"\s+(\d{4})Z?\s*$",            # group 5: time HHMM
        re.IGNORECASE,
    )

    # ── Band edge lookup (kHz) ────────────────────────────────────────────────
    _BAND_EDGES = [
        (1800,  2000,   "160M"),
        (3500,  4000,    "80M"),
        (5330,  5410,    "60M"),
        (7000,  7300,    "40M"),
        (10100, 10150,   "30M"),
        (14000, 14350,   "20M"),
        (18068, 18168,   "17M"),
        (21000, 21450,   "15M"),
        (24890, 24990,   "12M"),
        (28000, 29700,   "10M"),
        (50000, 54000,    "6M"),
        (144000, 148000,  "2M"),
    ]

    def _freq_to_band(self, freq_khz: float) -> str:
        for lo, hi, name in self._BAND_EDGES:
            if lo <= freq_khz <= hi:
                return name
        return f"{freq_khz:.0f}kHz"

    # ── Spot classifier ───────────────────────────────────────────────────────

    def _classify_spot(self, dx_call: str, freq_khz: float, comment: str) -> tuple:
        """
        Returns (status, mult_value, region) where:
          status : "NEW_MULT" | "NEW_BAND" | "WORKED" | "NOT_MULT" | "NO_LOG"
          mult   : the resolved mult string or ""
          region : region/state string or ""

        Mult resolution strategy:
          1. Scan comment tokens against plugin.mult_list() for direct match.
          2. Fall back to plugin.mult_of_qso() with a minimal fake QSO dict
             (catches prefix/DXCC contests that inspect the callsign).
          3. Compare resolved mult against worked_mults() and
             worked_primary_band_mults() for band-level resolution.
        """
        if not self.log:
            return "NO_LOG", "", ""

        band = self._freq_to_band(freq_khz)
        p    = self.log.plugin

        mult_val = None
        ml_set   = set(p.mult_list())

        # Pass 1: direct comment token match
        comment_upper = comment.strip().upper()
        for token in comment_upper.split():
            tok = token.strip(".,;:-")
            if tok in ml_set:
                mult_val = tok
                break

        # Pass 2: plugin hook with fake QSO dict
        if mult_val is None:
            fake_q = {
                "call":     dx_call.upper(),
                "mult1":    comment_upper,
                "band":     band,
                "mode":     "SSB",
                "pts":      1,
                "dupe":     False,
                "is_mult1": None,
                "is_mult2": None,
                "cqz":      None,
                "time":     datetime.utcnow(),
            }
            mult_val = p.mult_of_qso(fake_q)

        if mult_val is None or mult_val not in ml_set:
            return "NOT_MULT", "", ""

        region   = p.region_of_mult(mult_val) or ""
        worked   = self.log.worked_mults()
        band_wkd = self.log.worked_primary_band_mults()

        if mult_val not in worked:
            return "NEW_MULT", mult_val, region

        on_this_band = any(m == mult_val and b == band for m, b, _mode in band_wkd)
        if not on_this_band:
            return "NEW_BAND", mult_val, region

        return "WORKED", mult_val, region

    # ── Build tab UI ──────────────────────────────────────────────────────────

    def _build_cluster_tab(self):
        f = self.tab_cluster
        f.configure(bg=BG2)

        # ── Runtime state ─────────────────────────────────────────────────────
        self._cluster_q          = queue.Queue()
        self._cluster_worker     = None
        self._cluster_spots      = []
        self._cluster_max_spots  = 200
        self._cluster_poll_job   = None
        self._cluster_connected  = False
        self._cluster_tree_popout     = None   # second treeview in pop-out window
        self._cluster_raw_text_popout = None   # second raw feed in pop-out window

        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(f, bg=BG2)
        hdr.pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(hdr, text="📡  DX Cluster",
                 font=FONT_H, fg=ACCENT, bg=BG2).pack(side="left")
        self._cluster_status_var = tk.StringVar(value="  ● Disconnected")
        self._cluster_status_lbl = tk.Label(
            hdr, textvariable=self._cluster_status_var,
            font=("Consolas", 10, "bold"), fg=RED, bg=BG2,
        )
        self._cluster_status_lbl.pack(side="left", padx=(10, 0))
        self._cluster_rate_var = tk.StringVar(value="")
        tk.Label(hdr, textvariable=self._cluster_rate_var,
                 font=FONT_S, fg=MUTED, bg=BG2).pack(side="left", padx=(12, 0))
        # Pop-out button
        self._cluster_popped = False
        self._cluster_popout_win = None
        self._btn(hdr, "⬡ Pop Out", self._cluster_popout,
                  style="secondary").pack(side="right", padx=(0, 0))

        # ── Inner frame — everything below the header lives here so it can
        #    be reparented into a Toplevel for the pop-out feature ────────────
        self._cluster_inner = tk.Frame(f, bg=BG2)
        self._cluster_inner.pack(fill="both", expand=True)
        # Use f_inner as the parent for all remaining widgets
        f = self._cluster_inner

        # ── Connection toolbar ────────────────────────────────────────────────
        conn_row = tk.Frame(f, bg=BG2)
        conn_row.pack(fill="x", padx=12, pady=(4, 2))

        tk.Label(conn_row, text="Cluster:", font=FONT_S, fg=MUTED, bg=BG2).pack(
            side="left", padx=(0, 4))
        self._cluster_preset_var = tk.StringVar(value=self._CLUSTER_PRESETS[2][2])
        preset_cb = ttk.Combobox(
            conn_row, textvariable=self._cluster_preset_var,
            values=[p[2] for p in self._CLUSTER_PRESETS] + ["Custom…"],
            width=18, state="readonly", font=FONT_B,
        )
        preset_cb.pack(side="left", padx=(0, 8))
        preset_cb.bind("<<ComboboxSelected>>", self._on_cluster_preset_change)
        _Tooltip(preset_cb,
                 "Select a known DX cluster node.\n"
                 "VK2RCG and VK4RBD are best for VK contests.\n"
                 "Choose Custom… to enter your own host/port.")

        tk.Label(conn_row, text="Host:", font=FONT_S, fg=MUTED, bg=BG2).pack(
            side="left", padx=(0, 4))
        self._cluster_host_var   = tk.StringVar(value=self._CLUSTER_PRESETS[2][0])
        self._cluster_host_entry = tk.Entry(
            conn_row, textvariable=self._cluster_host_var,
            font=FONT_B, bg=BG3, fg=FG, insertbackground=FG,
            relief="flat", width=26,
        )
        self._cluster_host_entry.pack(side="left", padx=(0, 6))

        tk.Label(conn_row, text="Port:", font=FONT_S, fg=MUTED, bg=BG2).pack(
            side="left", padx=(0, 4))
        self._cluster_port_var   = tk.StringVar(value="7300")
        self._cluster_port_entry = tk.Entry(
            conn_row, textvariable=self._cluster_port_var,
            font=FONT_B, bg=BG3, fg=FG, insertbackground=FG,
            relief="flat", width=6,
        )
        self._cluster_port_entry.pack(side="left", padx=(0, 6))

        tk.Label(conn_row, text="Callsign:", font=FONT_S, fg=MUTED, bg=BG2).pack(
            side="left", padx=(0, 4))
        self._cluster_call_var   = tk.StringVar(value="")
        self._cluster_call_entry = tk.Entry(
            conn_row, textvariable=self._cluster_call_var,
            font=FONT_B, bg=BG3, fg=FG, insertbackground=FG,
            relief="flat", width=10,
        )
        self._cluster_call_entry.pack(side="left", padx=(0, 10))
        _Tooltip(self._cluster_call_entry,
                 "Your callsign — sent to the cluster on login.\n"
                 "Required by most nodes.")

        self._cluster_connect_btn = self._btn(
            conn_row, "Connect", self._cluster_connect)
        self._cluster_connect_btn.pack(side="left", padx=(0, 6))

        self._cluster_disconnect_btn = self._btn(
            conn_row, "Disconnect", self._cluster_disconnect, style="secondary")
        self._cluster_disconnect_btn.pack(side="left", padx=(0, 6))
        self._cluster_disconnect_btn.configure(state="disabled")

        self._btn(conn_row, "Clear", self._cluster_clear,
                  style="secondary").pack(side="left", padx=(0, 10))

        # SH/DX — fetch last N spots
        tk.Frame(conn_row, bg=BG3, width=1).pack(
            side="left", fill="y", pady=4, padx=(0, 10))
        self._cluster_shdx_btn = self._btn(
            conn_row, "SH/DX", self._cluster_shdx, style="secondary")
        self._cluster_shdx_btn.pack(side="left", padx=(0, 4))
        self._cluster_shdx_btn.configure(state="disabled")
        self._cluster_shdx_var = tk.StringVar(value="20")
        shdx_spin = tk.Spinbox(
            conn_row, textvariable=self._cluster_shdx_var,
            values=("10", "20", "50", "100", "200"),
            width=4, font=FONT_MONO,
            bg=BG3, fg=FG, relief="flat", bd=0,
            buttonbackground=BG3,
            selectbackground=ACCENT, selectforeground=BG,
            insertbackground=FG,
        )
        shdx_spin.pack(side="left", padx=(0, 4))
        _Tooltip(self._cluster_shdx_btn,
                 "Send SH/DX <n> to the cluster to fetch the last N spots immediately.\n"
                 "Use the spinner to choose how many (10–200).\n"
                 "Must be connected first.")

        # ── Filter toolbar ────────────────────────────────────────────────────
        flt_row = tk.Frame(f, bg=BG2)
        flt_row.pack(fill="x", padx=12, pady=(2, 4))

        tk.Label(flt_row, text="Show:", font=FONT_S, fg=MUTED, bg=BG2).pack(
            side="left", padx=(0, 6))

        self._cluster_filter_vars = {}
        filter_defs = [
            ("NEW_MULT", "🟢 New Mult",   GREEN),
            ("NEW_BAND", "🔵 New Band",   "#64b5f6"),
            ("WORKED",   "⚫ Worked",     MUTED),
            ("NOT_MULT", "— Not a Mult", MUTED),
        ]
        for key, label, colour in filter_defs:
            v = tk.BooleanVar(value=(key in ("NEW_MULT", "NEW_BAND")))
            self._cluster_filter_vars[key] = v
            ck = tk.Checkbutton(
                flt_row, text=label, variable=v,
                command=self._refresh_cluster_log,
                font=FONT_S, fg=colour, bg=BG2,
                activeforeground=ACCENT, activebackground=BG2,
                selectcolor=BG3, relief="flat", cursor="hand2",
            )
            ck.pack(side="left", padx=(0, 10))

        tk.Label(flt_row, text="  Band:", font=FONT_S, fg=MUTED, bg=BG2).pack(
            side="left", padx=(0, 4))
        self._cluster_band_var = tk.StringVar(value="All")
        self._cluster_band_cb  = ttk.Combobox(
            flt_row, textvariable=self._cluster_band_var,
            values=["All", "160M", "80M", "60M", "40M", "30M",
                    "20M", "17M", "15M", "12M", "10M", "6M", "2M"],
            width=7, state="readonly", font=FONT_B,
        )
        self._cluster_band_cb.pack(side="left", padx=(0, 8))
        self._cluster_band_cb.bind("<<ComboboxSelected>>",
                                   lambda e: self._refresh_cluster_log())

        self._cluster_autofilter_var = tk.BooleanVar(value=True)
        _cluster_autofilter_ck = tk.Checkbutton(
            flt_row, text="Contest bands only",
            variable=self._cluster_autofilter_var,
            command=self._refresh_cluster_log,
            font=FONT_S, fg=MUTED, bg=BG2,
            activeforeground=ACCENT, activebackground=BG2,
            selectcolor=BG3, relief="flat", cursor="hand2",
        )
        _cluster_autofilter_ck.pack(side="left", padx=(0, 8))
        _Tooltip(_cluster_autofilter_ck,
                 "When enabled, only shows spots on bands active in your log.\n"
                 "Clears clutter from bands you're not operating.")

        self._cluster_count_var = tk.StringVar(value="")
        tk.Label(flt_row, textvariable=self._cluster_count_var,
                 font=FONT_S, fg=MUTED, bg=BG2).pack(side="right", padx=(0, 4))

        # ── Spot treeview ─────────────────────────────────────────────────────
        tree_frame = tk.Frame(f, bg=BG2)
        tree_frame.pack(fill="both", expand=True, padx=12, pady=(0, 2))

        spot_cols = ("Time", "DX Call", "Freq", "Band", "Mult", "Region",
                     "Status", "Comment", "Spotter")
        self._cluster_tree = ttk.Treeview(
            tree_frame, columns=spot_cols,
            show="headings", selectmode="browse",
        )
        _style_tree(self._cluster_tree, self)

        col_cfgs = [
            ("Time",    54,  "center"),
            ("DX Call", 90,  "center"),
            ("Freq",    72,  "center"),
            ("Band",    52,  "center"),
            ("Mult",    80,  "center"),
            ("Region",  52,  "center"),
            ("Status",  100, "center"),
            ("Comment", 260, "w"),
            ("Spotter", 90,  "center"),
        ]
        for col, w, anchor in col_cfgs:
            self._cluster_tree.heading(col, text=col)
            self._cluster_tree.column(col, width=w, anchor=anchor,
                                       stretch=(col == "Comment"))

        vsb = ttk.Scrollbar(tree_frame, orient="vertical",
                             command=self._cluster_tree.yview)
        self._cluster_tree.configure(yscroll=vsb.set)
        self._cluster_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Row tag colours
        self._cluster_tree.tag_configure(
            "NEW_MULT", foreground=GREEN,     font=("Consolas", 10, "bold"))
        self._cluster_tree.tag_configure(
            "NEW_BAND", foreground="#64b5f6", font=("Consolas", 10, "bold"))
        self._cluster_tree.tag_configure(
            "WORKED",   foreground=MUTED)
        self._cluster_tree.tag_configure(
            "NOT_MULT", foreground=BG3)
        self._cluster_tree.tag_configure(
            "NO_LOG",   foreground=MUTED)

        # Double-click copies DX callsign to clipboard
        self._cluster_tree.bind("<Double-1>", self._cluster_copy_call)
        _Tooltip(self._cluster_tree,
                 "🟢 New Mult — station is a multiplier you haven't worked yet on any band.\n"
                 "🔵 New Band — mult already worked, but not on this band/mode.\n"
                 "⚫ Worked   — already in log on this band/mode.\n"
                 "— Not a Mult — spot doesn't match a contest multiplier.\n\n"
                 "Double-click any row to copy the DX callsign to the clipboard.")

        # ── Raw feed (collapsible) ────────────────────────────────────────────
        raw_hdr = tk.Frame(f, bg=BG3)
        raw_hdr.pack(fill="x", padx=12, pady=(0, 0))
        self._cluster_raw_visible = tk.BooleanVar(value=False)
        tk.Checkbutton(
            raw_hdr, text="▼ Raw telnet feed",
            variable=self._cluster_raw_visible,
            command=self._cluster_toggle_raw,
            font=("Consolas", 8), fg=MUTED, bg=BG3,
            activeforeground=ACCENT, activebackground=BG3,
            selectcolor=BG3, relief="flat", cursor="hand2",
        ).pack(side="left", padx=6, pady=2)
        tk.Label(raw_hdr,
                 text="all lines from cluster, including login and announcements",
                 font=("Consolas", 8), fg=MUTED, bg=BG3).pack(side="left")

        self._cluster_raw_frame = tk.Frame(f, bg=BG, height=110)
        self._cluster_raw_frame.pack_propagate(False)   # honour fixed height
        self._cluster_raw_text  = tk.Text(
            self._cluster_raw_frame,
            font=("Consolas", 8), bg=BG, fg=MUTED,
            height=5, relief="flat", wrap="none", state="disabled",
        )
        rsb2 = ttk.Scrollbar(self._cluster_raw_frame, orient="vertical",
                              command=self._cluster_raw_text.yview)
        self._cluster_raw_text.configure(yscroll=rsb2.set)
        self._cluster_raw_text.pack(side="left", fill="both", expand=True)
        rsb2.pack(side="right", fill="y")

        # ── Advice bar ────────────────────────────────────────────────────────
        adv_frame = tk.Frame(f, bg=BG3,
                             highlightbackground=BG3, highlightthickness=1)
        adv_frame.pack(fill="x", padx=12, pady=(2, 6))
        tk.Label(adv_frame, text="  Next target:  ",
                 font=("Consolas", 9, "bold"), fg=ACCENT3, bg=BG3).pack(side="left")
        self._cluster_advice_var = tk.StringVar(
            value="Connect to a cluster to see live spot recommendations.")
        tk.Label(adv_frame, textvariable=self._cluster_advice_var,
                 font=("Consolas", 9), fg=FG, bg=BG3,
                 anchor="w", wraplength=1200, justify="left").pack(
                     side="left", fill="x", expand=True, pady=4)

    # ── Cluster worker (background Telnet thread) ─────────────────────────────

    class _ClusterWorker(threading.Thread):
        """
        Background daemon thread: connects to a DX cluster via raw TCP,
        logs in with the operator callsign, then streams every received line
        into `out_q`.

        Messages placed on out_q:
          {"type": "status",      "msg":  str}  — connection state changes
          {"type": "spot",        "raw":  str}  — a line starting with "DX de"
          {"type": "raw",         "line": str}  — every received line
          {"type": "error",       "msg":  str}  — fatal connection error
          {"type": "disconnected"}              — clean disconnect / EOF
        """

        def __init__(self, host: str, port: int, callsign: str,
                     out_q: queue.Queue):
            super().__init__(daemon=True, name="ClusterWorker")
            self.host      = host
            self.port      = port
            self.callsign  = callsign.upper().strip()
            self.out_q     = out_q
            self.cmd_q     = queue.Queue()   # main thread → worker commands
            self._stop_evt = threading.Event()

        def stop(self):
            self._stop_evt.set()

        def send_cmd(self, cmd: str):
            """Thread-safe: queue a raw command string to send to the cluster."""
            self.cmd_q.put(cmd)

        def run(self):
            import socket, time
            sock = None
            try:
                self.out_q.put({
                    "type": "status",
                    "msg":  f"Connecting to {self.host}:{self.port}…"
                })
                sock = socket.create_connection((self.host, self.port), timeout=14)
                sock.settimeout(0.5)
                self.out_q.put({
                    "type": "status",
                    "msg":  f"Connected — logging in as {self.callsign}"
                })

                buf              = b""
                login_sent       = False
                set_dx_sent      = False
                post_login_lines = 0
                connect_time     = time.monotonic()
                # Keywords that mean "please tell me your callsign"
                LOGIN_KWS = (
                    "login:", "your call:", "call>", "callsign:",
                    "enter call", "please enter", "enter your call",
                )

                while not self._stop_evt.is_set():
                    # ── Receive ───────────────────────────────────────────────
                    try:
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                        buf += chunk
                    except socket.timeout:
                        pass
                    except OSError:
                        break

                    # ── Drain outbound command queue ─────────────────────────
                    if set_dx_sent:
                        try:
                            while True:
                                cmd = self.cmd_q.get_nowait()
                                sock.sendall((cmd.strip() + "\r\n").encode())
                                self.out_q.put({"type": "raw",
                                                "line": f">> sent: {cmd.strip()}"})
                        except queue.Empty:
                            pass

                    # ── Timeout login: if 2 s have passed and we still haven't
                    #    sent the callsign, send it now.  DXSpider nodes like
                    #    WA9PIE never emit a recognisable prompt — they just
                    #    wait silently after the banner.
                    if not login_sent and (time.monotonic() - connect_time) >= 2.0:
                        sock.sendall((self.callsign + "\r\n").encode())
                        login_sent = True
                        self.out_q.put({"type": "raw",
                                        "line": f">> (auto-login) sent: {self.callsign}"})

                    # ── Process complete lines ────────────────────────────────
                    while b"\n" in buf:
                        line_b, buf = buf.split(b"\n", 1)
                        try:
                            line = line_b.decode("utf-8", errors="replace").rstrip("\r")
                        except Exception:
                            continue

                        self.out_q.put({"type": "raw", "line": line})
                        line_l = line.lower().strip()

                        # Prompt-based login (catches nodes that do send a prompt)
                        if not login_sent and any(kw in line_l for kw in LOGIN_KWS):
                            sock.sendall((self.callsign + "\r\n").encode())
                            login_sent = True
                            self.out_q.put({"type": "raw",
                                            "line": f">> (prompt login) sent: {self.callsign}"})
                            continue

                        # After login wait for post-login lines then send SET/DX
                        if login_sent and not set_dx_sent:
                            post_login_lines += 1
                            # DXSpider echoes callsign then sends a Hello line;
                            # wait 4 lines or until we see the callsign echoed back
                            callsign_echoed = self.callsign.lower() in line_l
                            if post_login_lines >= 4 or callsign_echoed:
                                time.sleep(0.3)   # brief pause before SET/DX
                                sock.sendall(b"SET/DX\r\n")
                                set_dx_sent = True
                                self.out_q.put({
                                    "type": "status",
                                    "msg":  f"● Connected  {self.host}:{self.port}"
                                })
                            continue

                        # DX spot line
                        if line.upper().startswith("DX DE"):
                            self.out_q.put({"type": "spot", "raw": line})

            except OSError as exc:
                self.out_q.put({"type": "error", "msg": str(exc)})
            finally:
                if sock:
                    try:
                        sock.close()
                    except Exception:
                        pass
                self.out_q.put({"type": "disconnected"})

    # ── Cluster toolbar callbacks ─────────────────────────────────────────────

    def _on_cluster_preset_change(self, event=None):
        sel = self._cluster_preset_var.get()
        if sel == "Custom…":
            return  # user types their own values
        for host, port, label in self._CLUSTER_PRESETS:
            if label == sel:
                self._cluster_host_var.set(host)
                self._cluster_port_var.set(str(port))
                break

    def _cluster_connect(self):
        if self._cluster_worker and self._cluster_worker.is_alive():
            return
        host     = self._cluster_host_var.get().strip()
        callsign = self._cluster_call_var.get().strip()
        try:
            port = int(self._cluster_port_var.get().strip())
        except ValueError:
            port = 7300
        if not host:
            messagebox.showwarning("DX Cluster", "Enter a cluster hostname.")
            return
        if not callsign:
            messagebox.showwarning("DX Cluster",
                                   "Enter your callsign before connecting.")
            return

        self._cluster_q      = queue.Queue()
        self._cluster_worker = self._ClusterWorker(
            host, port, callsign, self._cluster_q)
        self._cluster_worker.start()
        self._cluster_connect_btn.configure(state="disabled")
        self._cluster_disconnect_btn.configure(state="normal")
        self._cluster_shdx_btn.configure(state="normal")
        self._cluster_connected = True
        self._cluster_status_var.set("  ● Connecting…")
        self._cluster_status_lbl.configure(fg=ACCENT3)

        # Cancel any stale poll job and start fresh
        if self._cluster_poll_job:
            try:
                self.after_cancel(self._cluster_poll_job)
            except Exception:
                pass
        self._cluster_poll()

    def _cluster_shdx(self):
        """Send SH/DX <n> to fetch the last N spots from the cluster."""
        if not self._cluster_worker or not self._cluster_worker.is_alive():
            messagebox.showwarning("DX Cluster", "Not connected.")
            return
        try:
            n = int(self._cluster_shdx_var.get())
        except ValueError:
            n = 20
        n = max(1, min(n, 500))
        cmd = f"SH/DX {n}"
        self._cluster_worker.send_cmd(cmd)
        self._cluster_status_var.set(f"  ● Connected — sent {cmd}")
        self._cluster_status_lbl.configure(fg=GREEN)

    def _cluster_disconnect(self):
        if self._cluster_worker:
            self._cluster_worker.stop()
            self._cluster_worker = None
        self._cluster_connected = False
        self._cluster_connect_btn.configure(state="normal")
        self._cluster_disconnect_btn.configure(state="disabled")
        self._cluster_shdx_btn.configure(state="disabled")
        self._cluster_status_var.set("  ● Disconnected")
        self._cluster_status_lbl.configure(fg=RED)

    def _cluster_clear(self):
        self._cluster_spots.clear()
        self._refresh_cluster_log()

    def _cluster_toggle_raw(self):
        if self._cluster_raw_visible.get():
            # Pack raw frame inside _cluster_inner, before the advice bar
            # (advice bar is the last child of _cluster_inner)
            try:
                children = self._cluster_inner.winfo_children()
                last     = children[-1] if children else None
            except Exception:
                last = None
            self._cluster_raw_frame.pack(
                in_=self._cluster_inner,
                fill="x", padx=12, pady=(0, 2),
                before=last,
            )
        else:
            self._cluster_raw_frame.pack_forget()

    def _cluster_copy_call(self, event=None):
        sel = self._cluster_tree.selection()
        if not sel:
            return
        vals = self._cluster_tree.item(sel[0], "values")
        if len(vals) >= 2:
            self.clipboard_clear()
            self.clipboard_append(vals[1])   # DX Call column

    def _cluster_popout(self):
        """
        Open (or close) a floating pop-out window for the DX Cluster panel.

        Tk does not allow reparenting widgets across Toplevel boundaries, so
        the pop-out is a separate window that shares all state (StringVars,
        BooleanVars, spot list, queue) with the tab.  A second treeview is
        built in the pop-out and kept in sync by _refresh_cluster_log(), which
        now writes to both self._cluster_tree and self._cluster_tree_popout.
        """
        # ── Close if already open ─────────────────────────────────────────────
        if self._cluster_popout_win is not None:
            try:
                self._cluster_popout_win.destroy()
            except Exception:
                pass
            self._cluster_popout_win  = None
            self._cluster_tree_popout = None
            self._cluster_popped      = False
            return

        # ── Build the window ──────────────────────────────────────────────────
        win = tk.Toplevel(self)
        win.title("📡 DX Cluster")
        win.configure(bg=BG2)
        win.geometry("1140x660")
        win.minsize(820, 500)
        self._cluster_popout_win = win
        self._cluster_popped     = True

        def _on_close():
            self._cluster_popout_win  = None
            self._cluster_tree_popout = None
            self._cluster_popped      = False
            try:
                win.destroy()
            except Exception:
                pass

        win.protocol("WM_DELETE_WINDOW", _on_close)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(win, bg=BG2)
        hdr.pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(hdr, text="📡  DX Cluster",
                 font=FONT_H, fg=ACCENT, bg=BG2).pack(side="left")
        # Share the same status StringVar so it updates in both windows
        tk.Label(hdr, textvariable=self._cluster_status_var,
                 font=("Consolas", 10, "bold"), fg=RED, bg=BG2).pack(
                     side="left", padx=(10, 0))

        ontop_var = tk.BooleanVar(value=False)
        def _toggle_ontop():
            win.attributes("-topmost", ontop_var.get())
        tk.Checkbutton(
            hdr, text="Always on top", variable=ontop_var,
            command=_toggle_ontop,
            font=FONT_S, fg=MUTED, bg=BG2,
            activeforeground=ACCENT, activebackground=BG2,
            selectcolor=BG3, relief="flat", cursor="hand2",
        ).pack(side="right", padx=(0, 4))
        self._btn(hdr, "✕ Close", _on_close,
                  style="secondary").pack(side="right", padx=(0, 6))
        # SH/DX in pop-out shares same var and method
        self._btn(hdr, "SH/DX", self._cluster_shdx,
                  style="secondary").pack(side="right", padx=(0, 6))
        tk.Spinbox(
            hdr, textvariable=self._cluster_shdx_var,
            values=("10", "20", "50", "100", "200"),
            width=4, font=FONT_MONO,
            bg=BG3, fg=FG, relief="flat", bd=0,
            buttonbackground=BG3,
            selectbackground=ACCENT, selectforeground=BG,
            insertbackground=FG,
        ).pack(side="right", padx=(0, 4))

        # ── Filter bar (shares same BooleanVars / StringVars) ─────────────────
        flt = tk.Frame(win, bg=BG2)
        flt.pack(fill="x", padx=12, pady=(4, 2))
        tk.Label(flt, text="Show:", font=FONT_S, fg=MUTED, bg=BG2).pack(
            side="left", padx=(0, 6))
        filter_defs = [
            ("NEW_MULT", "🟢 New Mult",   GREEN),
            ("NEW_BAND", "🔵 New Band",   "#64b5f6"),
            ("WORKED",   "⚫ Worked",     MUTED),
            ("NOT_MULT", "— Not a Mult", MUTED),
        ]
        for key, label, colour in filter_defs:
            tk.Checkbutton(
                flt, text=label,
                variable=self._cluster_filter_vars[key],
                command=self._refresh_cluster_log,
                font=FONT_S, fg=colour, bg=BG2,
                activeforeground=ACCENT, activebackground=BG2,
                selectcolor=BG3, relief="flat", cursor="hand2",
            ).pack(side="left", padx=(0, 10))

        tk.Label(flt, text="  Band:", font=FONT_S, fg=MUTED, bg=BG2).pack(
            side="left", padx=(0, 4))
        ttk.Combobox(
            flt, textvariable=self._cluster_band_var,
            values=["All","160M","80M","60M","40M","30M",
                    "20M","17M","15M","12M","10M","6M","2M"],
            width=7, state="readonly", font=FONT_B,
        ).pack(side="left", padx=(0, 8))
        tk.Checkbutton(
            flt, text="Contest bands only",
            variable=self._cluster_autofilter_var,
            command=self._refresh_cluster_log,
            font=FONT_S, fg=MUTED, bg=BG2,
            activeforeground=ACCENT, activebackground=BG2,
            selectcolor=BG3, relief="flat", cursor="hand2",
        ).pack(side="left")

        # ── Treeview ──────────────────────────────────────────────────────────
        tree_frame = tk.Frame(win, bg=BG2)
        tree_frame.pack(fill="both", expand=True, padx=12, pady=(4, 2))

        spot_cols = ("Time", "DX Call", "Freq", "Band", "Mult", "Region",
                     "Status", "Comment", "Spotter")
        pop_tree = ttk.Treeview(
            tree_frame, columns=spot_cols,
            show="headings", selectmode="browse",
        )
        _style_tree(pop_tree)
        col_cfgs = [
            ("Time",    54,  "center"),
            ("DX Call", 90,  "center"),
            ("Freq",    72,  "center"),
            ("Band",    52,  "center"),
            ("Mult",    80,  "center"),
            ("Region",  52,  "center"),
            ("Status",  100, "center"),
            ("Comment", 260, "w"),
            ("Spotter", 90,  "center"),
        ]
        for col, w, anchor in col_cfgs:
            pop_tree.heading(col, text=col)
            pop_tree.column(col, width=w, anchor=anchor,
                            stretch=(col == "Comment"))
        pop_tree.tag_configure(
            "NEW_MULT", foreground=GREEN,     font=("Consolas", 10, "bold"))
        pop_tree.tag_configure(
            "NEW_BAND", foreground="#64b5f6", font=("Consolas", 10, "bold"))
        pop_tree.tag_configure("WORKED",   foreground=MUTED)
        pop_tree.tag_configure("NOT_MULT", foreground=BG3)
        pop_tree.tag_configure("NO_LOG",   foreground=MUTED)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical",
                             command=pop_tree.yview)
        pop_tree.configure(yscroll=vsb.set)
        pop_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        def _copy_call(event=None):
            sel = pop_tree.selection()
            if sel:
                vals = pop_tree.item(sel[0], "values")
                if len(vals) >= 2:
                    self.clipboard_clear()
                    self.clipboard_append(vals[1])
        pop_tree.bind("<Double-1>", _copy_call)

        self._cluster_tree_popout = pop_tree

        # ── Raw feed ──────────────────────────────────────────────────────────
        raw_frame = tk.Frame(win, bg=BG, height=110)
        raw_frame.pack_propagate(False)
        raw_text = tk.Text(
            raw_frame, font=("Consolas", 8), bg=BG, fg=MUTED,
            height=6, relief="flat", wrap="none", state="disabled",
        )
        raw_sb = ttk.Scrollbar(raw_frame, orient="vertical",
                               command=raw_text.yview)
        raw_text.configure(yscroll=raw_sb.set)
        raw_text.pack(side="left", fill="both", expand=True)
        raw_sb.pack(side="right", fill="y")
        self._cluster_raw_text_popout = raw_text

        raw_hdr = tk.Frame(win, bg=BG3)
        raw_hdr.pack(fill="x", padx=12, pady=(0, 0))
        raw_visible = tk.BooleanVar(value=False)
        def _toggle_raw():
            if raw_visible.get():
                raw_frame.pack(fill="x", padx=12, pady=(0, 2),
                               before=adv_frame)
            else:
                raw_frame.pack_forget()
        tk.Checkbutton(
            raw_hdr, text="▼ Raw telnet feed",
            variable=raw_visible, command=_toggle_raw,
            font=("Consolas", 8), fg=MUTED, bg=BG3,
            activeforeground=ACCENT, activebackground=BG3,
            selectcolor=BG3, relief="flat", cursor="hand2",
        ).pack(side="left", padx=6, pady=2)

        # ── Advice bar ────────────────────────────────────────────────────────
        adv_frame = tk.Frame(win, bg=BG3,
                             highlightbackground=BG3, highlightthickness=1)
        adv_frame.pack(fill="x", padx=12, pady=(2, 6))
        tk.Label(adv_frame, text="  Next target:  ",
                 font=("Consolas", 9, "bold"), fg=ACCENT3, bg=BG3).pack(side="left")
        tk.Label(adv_frame, textvariable=self._cluster_advice_var,
                 font=("Consolas", 9), fg=FG, bg=BG3,
                 anchor="w", wraplength=1100, justify="left").pack(
                     side="left", fill="x", expand=True, pady=4)

        # Populate immediately with current spots
        self._refresh_cluster_log()

    # ── Poll loop — drains queue every 500 ms ────────────────────────────────

    def _cluster_poll(self):
        """Drain the worker queue, classify new spots, refresh the display."""
        changed = False

        try:
            while True:
                msg   = self._cluster_q.get_nowait()
                mtype = msg.get("type")

                if mtype == "status":
                    txt = msg["msg"]
                    self._cluster_status_var.set(f"  {txt}")
                    col = GREEN if ("● Connected" in txt) else ACCENT3
                    self._cluster_status_lbl.configure(fg=col)

                elif mtype == "error":
                    self._cluster_status_var.set(f"  ✗ {msg['msg']}")
                    self._cluster_status_lbl.configure(fg=RED)

                elif mtype == "disconnected":
                    self._cluster_status_var.set("  ● Disconnected")
                    self._cluster_status_lbl.configure(fg=RED)
                    self._cluster_connect_btn.configure(state="normal")
                    self._cluster_disconnect_btn.configure(state="disabled")
                    self._cluster_shdx_btn.configure(state="disabled")
                    self._cluster_connected = False
                    break

                elif mtype == "raw":
                    self._cluster_raw_append(msg["line"])

                elif mtype == "spot":
                    spot = self._cluster_parse_spot(msg["raw"])
                    if spot:
                        self._cluster_spots.insert(0, spot)
                        if len(self._cluster_spots) > self._cluster_max_spots:
                            self._cluster_spots = \
                                self._cluster_spots[:self._cluster_max_spots]
                        changed = True

        except queue.Empty:
            pass

        if changed:
            self._refresh_cluster_log()
            self._cluster_update_advice()

        # Reschedule while connected or worker still alive
        if self._cluster_connected or (
                self._cluster_worker and self._cluster_worker.is_alive()):
            self._cluster_poll_job = self.after(500, self._cluster_poll)

    # ── Spot parser ───────────────────────────────────────────────────────────

    def _cluster_parse_spot(self, raw: str) -> dict | None:
        """Parse a raw DX de line into a classified spot dict, or None."""
        m = self._SPOT_RE.search(raw)
        if not m:
            return None
        spotter  = m.group(1).upper()
        freq_str = m.group(2)
        dx_call  = m.group(3).upper()
        comment  = m.group(4).strip()
        time_str = m.group(5)
        try:
            freq = float(freq_str)
        except ValueError:
            return None
        band   = self._freq_to_band(freq)
        status, mult_val, region = self._classify_spot(dx_call, freq, comment)
        return {
            "time":    time_str,
            "dx_call": dx_call,
            "freq":    freq,
            "band":    band,
            "mult":    mult_val,
            "region":  region,
            "status":  status,
            "comment": comment,
            "spotter": spotter,
            "raw":     raw,
        }

    def _cluster_raw_append(self, line: str):
        def _append_to(t):
            try:
                t.configure(state="normal")
                t.insert("end", line + "\n")
                n = int(t.index("end-1c").split(".")[0])
                if n > 300:
                    t.delete("1.0", f"{n - 300}.0")
                t.see("end")
                t.configure(state="disabled")
            except Exception:
                pass
        _append_to(self._cluster_raw_text)
        if self._cluster_raw_text_popout is not None:
            try:
                self._cluster_raw_text_popout.winfo_exists()
                _append_to(self._cluster_raw_text_popout)
            except Exception:
                self._cluster_raw_text_popout = None

    # ── Treeview refresh ──────────────────────────────────────────────────────

    def _refresh_cluster_log(self):
        if not hasattr(self, "_cluster_tree"):
            return          # tab was disabled — build method never ran
        trees = [self._cluster_tree]
        if self._cluster_tree_popout is not None:
            try:
                self._cluster_tree_popout.winfo_exists()
                trees.append(self._cluster_tree_popout)
            except Exception:
                self._cluster_tree_popout = None

        show = {k for k, v in self._cluster_filter_vars.items() if v.get()}
        if not self.log:
            show = {"NEW_MULT", "NEW_BAND", "WORKED", "NOT_MULT", "NO_LOG"}

        band_filter   = self._cluster_band_var.get()
        auto_filter   = self._cluster_autofilter_var.get()
        contest_bands: set = set()
        if auto_filter and self.log:
            contest_bands = {q["band"] for q in self.log.qsos if q.get("band")}

        status_labels = {
            "NEW_MULT": "🟢 New Mult",
            "NEW_BAND": "🔵 New Band",
            "WORKED":   "⚫ Worked",
            "NOT_MULT": "— Not a Mult",
            "NO_LOG":   "? No Log",
        }

        # Build the rows to insert once, apply to all trees
        rows = []
        for spot in self._cluster_spots:
            st = spot["status"]
            if st not in show:
                continue
            b = spot["band"]
            if band_filter != "All" and b != band_filter:
                continue
            if auto_filter and contest_bands and b not in contest_bands:
                continue
            rows.append((
                (
                    spot["time"],
                    spot["dx_call"],
                    f"{spot['freq']:.1f}",
                    b,
                    spot["mult"] or "—",
                    spot["region"] or "—",
                    status_labels.get(st, st),
                    spot["comment"],
                    spot["spotter"],
                ),
                st,
            ))

        for tree in trees:
            try:
                for iid in tree.get_children():
                    tree.delete(iid)
                for values, tag in rows:
                    tree.insert("", "end", values=values, tags=(tag,))
            except Exception:
                pass

        total = len(self._cluster_spots)
        shown = len(rows)
        self._cluster_count_var.set(
            f"Showing {shown} of {total} spot{'s' if total != 1 else ''}")

    # ── Advice bar update ─────────────────────────────────────────────────────

    def _cluster_update_advice(self):
        new_mult = [s for s in self._cluster_spots if s["status"] == "NEW_MULT"]
        new_band = [s for s in self._cluster_spots if s["status"] == "NEW_BAND"]

        if not new_mult and not new_band:
            msg = ("No new mults spotted recently — all spotted stations already worked."
                   if self._cluster_spots else
                   "Connect to a cluster to see live spot recommendations.")
            self._cluster_advice_var.set(msg)
            return

        parts = []
        if new_mult:
            by_band: dict = {}
            for s in new_mult:
                b = s["band"]
                if b not in by_band:
                    by_band[b] = []
                if s["mult"] not in [x["mult"] for x in by_band[b]]:
                    by_band[b].append(s)
            for band in sorted(by_band):
                top = by_band[band][:3]
                calls = "  ".join(
                    f"{s['dx_call']} ({s['freq']:.0f}kHz, {s['mult']})"
                    for s in top
                )
                parts.append(f"🟢 {band}: {calls}")

        if new_band and len(parts) < 4:
            seen: set = set()
            uniq = []
            for s in new_band:
                k = (s["dx_call"], s["band"])
                if k not in seen:
                    seen.add(k)
                    uniq.append(s)
            nb_str = "  ".join(
                f"{s['dx_call']} ({s['freq']:.0f}kHz {s['band']})"
                for s in uniq[:3]
            )
            parts.append(f"🔵 New band: {nb_str}")

        self._cluster_advice_var.set(
            "   |   ".join(parts) if parts else "No actionable spots.")

    # ── Reclassify buffered spots when a new log is loaded ───────────────────

    def _refresh_cluster_spots_classification(self):
        """Called from _on_load_success so spots update against the new log."""
        if not hasattr(self, "_cluster_tree"):
            return          # tab was disabled — build method never ran
        for spot in self._cluster_spots:
            status, mult_val, region = self._classify_spot(
                spot["dx_call"], spot["freq"], spot["comment"])
            spot["status"] = status
            spot["mult"]   = mult_val
            spot["region"] = region
        self._refresh_cluster_log()
        self._cluster_update_advice()


# ═══════════════════════════════════════════════════════════════════════════════
# ── Utility ──────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════



def _fade_in(window, current_alpha=0.0, target_alpha=0.96, step=0.06):
    """
    Smoothly fade a Toplevel window in at ~60 FPS using .after().
    Uses ease-out by shrinking the step as we near the target.
    Safe to call from __init__: schedules itself without blocking.
    """
    if current_alpha < target_alpha:
        current_alpha = min(current_alpha + step, target_alpha)
        try:
            window.attributes("-alpha", current_alpha)
        except Exception:
            return   # window may have been destroyed
        window.after(16, lambda: _fade_in(window, current_alpha, target_alpha, step))


# ═══════════════════════════════════════════════════════════════════════════════
# ── Export helpers ────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _export_tree_to_csv(tree, parent_widget, suggested_name="export.csv"):
    """
    Write every visible row of *tree* to a CSV file chosen by the user.
    Works with any ttk.Treeview that uses show="headings".
    """
    import csv
    path = filedialog.asksaveasfilename(
        parent=parent_widget,
        defaultextension=".csv",
        filetypes=[("CSV file", "*.csv"), ("All files", "*.*")],
        initialfile=suggested_name,
        title="Export table as CSV",
    )
    if not path:
        return False
    cols = tree["columns"]
    rows = [tree.item(iid)["values"] for iid in tree.get_children()]
    try:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(rows)
        return True
    except OSError as exc:
        messagebox.showerror("Export failed", str(exc), parent=parent_widget)
        return False


def _flash_success(label, message="✔ Saved", duration_ms=2000,
                   ok_fg=None, orig_text="", orig_fg=None):
    """
    Briefly display *message* in *label* with an accent-green colour, then
    restore the original text and colour after *duration_ms* milliseconds.
    Drives a 6-frame alpha fade-out for a polished micro-interaction.
    """
    if ok_fg is None:
        ok_fg = GREEN
    if orig_fg is None:
        orig_fg = MUTED
    label.configure(text=message, fg=ok_fg)

    def _fade(step=0):
        if step >= 6:
            label.configure(text=orig_text, fg=orig_fg)
            return
        # Lerp green→muted across 6 steps
        try:
            r_s, g_s, b_s = int(ok_fg[1:3], 16), int(ok_fg[3:5], 16), int(ok_fg[5:7], 16)
            r_e, g_e, b_e = int(orig_fg[1:3], 16) if orig_fg.startswith("#") else (0x8b, 0x94, 0x9e), \
                             int(orig_fg[3:5], 16) if orig_fg.startswith("#") else 0x94, \
                             int(orig_fg[5:7], 16) if orig_fg.startswith("#") else 0x9e
            t = step / 6
            rr = int(r_s + (r_e - r_s) * t)
            gg = int(g_s + (g_e - g_s) * t)
            bb = int(b_s + (b_e - b_s) * t)
            label.configure(fg=f"#{rr:02x}{gg:02x}{bb:02x}")
        except Exception:
            pass
        label.after(80, lambda: _fade(step + 1))

    label.after(duration_ms, _fade)


# Braille-spinner frames for skeleton/loading indicator
_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class _SpinnerLabel:
    """
    Lightweight animated spinner that runs safely on a tk.Label using .after().
    Call .start(text) to begin and .stop() to restore the original label text.
    """
    def __init__(self, label):
        self._lbl   = label
        self._job   = None
        self._phase = 0
        self._msg   = ""
        self._orig  = label.cget("text")
        self._running = False

    def start(self, msg="Processing…"):
        self._msg     = msg
        self._running = True
        self._phase   = 0
        self._tick()

    def stop(self, restore_text=None):
        self._running = False
        if self._job:
            try: self._lbl.after_cancel(self._job)
            except Exception: pass
            self._job = None
        self._lbl.configure(text=restore_text if restore_text is not None else self._orig)

    def _tick(self):
        if not self._running:
            return
        frame = _SPINNER_FRAMES[self._phase % len(_SPINNER_FRAMES)]
        try:
            self._lbl.configure(text=f"{frame} {self._msg}")
        except Exception:
            self._running = False
            return
        self._phase += 1
        self._job = self._lbl.after(80, self._tick)

def _apply_scrollbar_style(style):
    """
    Override the default clam scrollbar layout with a thin, minimal design.
    Arrow buttons are removed; only a slim thumb in a flush trough remains.
    Called once at startup and again on every theme switch so colours stay
    in sync with the active theme globals.
    """
    try:
        style.element_create("Custom.Scrollbar.trough", "from", "clam")
        style.element_create("Custom.Scrollbar.thumb",  "from", "clam")
    except Exception:
        pass   # elements already exist after first call — clam raises TclError
    style.layout("Vertical.TScrollbar", [
        ("Custom.Scrollbar.trough", {
            "children": [
                ("Custom.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})
            ],
            "sticky": "ns",
        })
    ])
    style.layout("Horizontal.TScrollbar", [
        ("Custom.Scrollbar.trough", {
            "children": [
                ("Custom.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})
            ],
            "sticky": "ew",
        })
    ])
    style.configure("Vertical.TScrollbar",
                    troughcolor=BG2, background=BG3,
                    bordercolor=BG2, lightcolor=BG2, darkcolor=BG2,
                    width=8, relief="flat")
    style.map("Vertical.TScrollbar",
              background=[("active", ACCENT), ("!active", BG3)])
    style.configure("Horizontal.TScrollbar",
                    troughcolor=BG2, background=BG3,
                    bordercolor=BG2, lightcolor=BG2, darkcolor=BG2,
                    width=8, relief="flat")
    style.map("Horizontal.TScrollbar",
              background=[("active", ACCENT), ("!active", BG3)])

# ── Zebra-stripe colours (per-theme, defined at module level for
#    _style_tree to reference; updated by _apply_theme if needed) ──────
_ZEBRA_ODD  = "#1a2030"   # very subtle blue-tinted lift from BG3
_ZEBRA_EVEN = ""          # empty = let the Treeview background show through

def _style_tree(tree, app=None):
    """Apply consistent Treeview styling and register zebra-stripe tags.
    Pass `app` (the App instance) to auto-register for theme-switch re-tagging."""
    tree.configure(style="Treeview")
    # Tag names "odd" and "even" are used by _zebra_insert() below.
    tree.tag_configure("odd",  background=_ZEBRA_ODD)
    tree.tag_configure("even", background="")   # inherits Treeview fieldbackground
    if app is not None and hasattr(app, "_all_trees") and tree not in app._all_trees:
        app._all_trees.append(tree)

def _zebra_insert(tree, row_index, values, **kw):
    """Insert a row into a Treeview with automatic alternating zebra shading."""
    tag = "odd" if row_index % 2 == 1 else "even"
    return tree.insert("", "end", values=values, tags=(tag,), **kw)


# ═══════════════════════════════════════════════════════════════════════════════
# ── SplashScreen ─────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

class SplashScreen:
    """
    Animated splash screen with disclaimer and acknowledgement gate.
    """

    W, H    = 620, 540
    BG      = "#0d1117"
    BG2     = "#161b22"
    BG3     = "#21262d"
    BG4     = "#1a1f26"
    ACCENT  = "#00d4aa"
    ACCENT2 = "#ff6b35"
    FG      = "#e6edf3"
    MUTED   = "#8b949e"
    RED     = "#ff4757"
    AMBER   = "#f0c040"
    BAR_X   = 160
    BAR_Y   = 252
    BAR_W   = 300
    BAR_H   = 10

    MESSAGES = [
        "Initialising interface...",
        "Loading contest data...",
        "Preparing multiplier tables...",
        "Building band analysis...",
        "Ready — please read the notice below.",
    ]

    DISCLAIMER = (
        "⚠  DISCLAIMER\n\n"
        "This software is provided on a best-effort basis and is intended\n"
        "as a supplemental tool only. While reasonable efforts have been\n"
        "made to ensure accuracy, the software may contain errors,\n"
        "omissions, or discrepancies.\n\n"
        "Users should rely on N1MM Logger+ as the authoritative source\n"
        "for contest logging, scoring, and official results.\n\n"
        "The developers of this software make no guarantees regarding\n"
        "the accuracy or completeness of any calculations, scores, or\n"
        "data presented.\n\n"
        "Users are responsible for verifying all information against\n"
        "N1MM before making decisions or submitting contest entries."
    )

    def __init__(self, root: tk.Tk):
        self._root     = root
        self._closed   = False
        self._accepted = False
        self._bar_fill = 0
        self._bar_done = False
        self._on_accept_cb = None

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.resizable(False, False)
        self.win.configure(bg=self.BG)
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", 0.96)  # glassmorphism translucency
        self.win.protocol("WM_DELETE_WINDOW", lambda: None)

        root.update_idletasks()
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        x  = (sw - self.W) // 2
        y  = (sh - self.H) // 2
        self.win.geometry(f"{self.W}x{self.H}+{x}+{y}")
        self.win.update_idletasks()

        self.cv = tk.Canvas(self.win, width=self.W, height=self.H,
                            bg=self.BG, highlightthickness=0)
        self.cv.place(x=0, y=0)
        self._draw_static()

        self.cv.create_rectangle(self.BAR_X, self.BAR_Y,
                                  self.BAR_X + self.BAR_W, self.BAR_Y + self.BAR_H,
                                  fill=self.BG3, outline="")
        self._bar_id = self.cv.create_rectangle(self.BAR_X, self.BAR_Y,
                                                  self.BAR_X, self.BAR_Y + self.BAR_H,
                                                  fill=self.ACCENT, outline="")
        self._msg_id = self.cv.create_text(self.W // 2, self.BAR_Y + 22,
                                            text=self.MESSAGES[0],
                                            font=("Consolas", 10), fill=self.MUTED)

        disc_frame = tk.Frame(self.win, bg=self.BG4,
                              highlightbackground=self.BG3, highlightthickness=1)
        disc_frame.place(x=28, y=290, width=self.W - 56, height=170)
        disc_text = tk.Text(disc_frame, bg=self.BG4, fg=self.MUTED,
                            font=("Consolas", 9), relief="flat", bd=0,
                            wrap="word", cursor="arrow", state="normal",
                            padx=10, pady=10, height=10)
        disc_text.insert("1.0", self.DISCLAIMER)
        disc_text.tag_configure("warn", foreground=self.AMBER,
                                font=("Consolas", 9, "bold"))
        disc_text.tag_add("warn", "1.0", "1.end")
        disc_text.configure(state="disabled", takefocus=0)
        disc_text.pack(fill="both", expand=True)

        self._ack_var = tk.BooleanVar(value=False)
        chk_frame = tk.Frame(self.win, bg=self.BG)
        chk_frame.place(x=28, y=470, width=self.W - 56, height=26)
        style = ttk.Style(self.win)
        style.configure("Splash.TCheckbutton", background=self.BG,
                        foreground=self.MUTED, font=("Consolas", 9))
        self._chk = ttk.Checkbutton(
            chk_frame,
            text="I have read and understood the above. I accept all risks.",
            variable=self._ack_var,
            style="Splash.TCheckbutton",
            command=self._on_ack_toggle,
        )
        self._chk.pack(side="left")

        self._btn = tk.Button(
            self.win, text="Let's Get Started  ›",
            font=("Consolas", 11, "bold"),
            bg=self.BG3, fg=self.BG3,
            activebackground=self.ACCENT, activeforeground=self.BG,
            relief="flat", bd=0, padx=20, pady=8,
            cursor="arrow", state="disabled",
            command=self._on_start,
        )
        self._btn.place(x=self.W // 2 - 110, y=504, width=220, height=26)
        self.win.update()
        self.win.lift()
        self._grab_focus()
        self._msg_idx = 0
        self._animate()

    def _grab_focus(self):
        # On Windows, an overrideredirect Toplevel often isn't actually
        # activated by the OS yet at the moment it's mapped, so a
        # focus_force() called synchronously here can silently lose to
        # whatever window had focus before. Retry a couple of times on
        # a short delay so the splash reliably ends up with the keyboard.
        try:
            self.win.focus_force()
            self._chk.focus_set()
        except Exception:
            pass
        if not self._closed:
            self.win.after(120, self._grab_focus_once_more)

    def _grab_focus_once_more(self):
        try:
            if self.win.focus_get() is None:
                self.win.focus_force()
                self._chk.focus_set()
        except Exception:
            pass

    def _draw_static(self):
        cv, W, H = self.cv, self.W, self.H
        cv.create_rectangle(1, 1, W-2, H-2, outline=self.ACCENT, width=1)
        cv.create_rectangle(3, 3, W-4, H-4, outline=self.BG3,    width=1)
        cx, cy, r = W // 2, 72, 36
        outer, inner = [], []
        for i in range(6):
            a = math.radians(90 + 60 * i)
            outer.extend([cx + r*math.cos(a),      cy + r*math.sin(a)])
            inner.extend([cx + (r-11)*math.cos(a), cy + (r-11)*math.sin(a)])
        cv.create_polygon(outer, fill=self.BG2, outline=self.ACCENT, width=2)
        cv.create_polygon(inner, fill="",       outline=self.ACCENT, width=1,
                          stipple="gray25")
        cv.create_text(cx, cy, text="⬡",
                       font=("Consolas", 28, "bold"), fill=self.ACCENT)
        cv.create_text(W//2, 128, text="VK CONTEST ANALYZER",
                       font=("Consolas", 22, "bold"), fill=self.FG)
        cv.create_text(W//2, 150, text="N1MM+ LOG INTELLIGENCE",
                       font=("Consolas", 11), fill=self.MUTED)
        cv.create_line(210, 168, 410, 168, fill=self.BG3, width=1)
        cv.create_text(W//2, 188, text="by VK2YI",
                       font=("Consolas", 12), fill=self.MUTED)
        cv.create_text(W//2, 216, text=f"v{VERSION}  •  VK Contest",
                       font=("Consolas", 9), fill=self.BG3)

    def _animate(self):
        if self._closed:
            return
        if not self._bar_done:
            remaining      = self.BAR_W - self._bar_fill
            self._bar_fill = min(self._bar_fill + max(2, int(remaining*0.045)),
                                 self.BAR_W - 4)
            self.cv.coords(self._bar_id,
                           self.BAR_X, self.BAR_Y,
                           self.BAR_X + self._bar_fill, self.BAR_Y + self.BAR_H)
            tick = min(int(self._bar_fill / (self.BAR_W / len(self.MESSAGES))),
                       len(self.MESSAGES) - 1)
            if tick != self._msg_idx:
                self._msg_idx = tick
                self.cv.itemconfigure(self._msg_id, text=self.MESSAGES[tick])
            if self._bar_fill >= self.BAR_W - 4:
                self._bar_done = True
                self.cv.coords(self._bar_id,
                               self.BAR_X, self.BAR_Y,
                               self.BAR_X + self.BAR_W, self.BAR_Y + self.BAR_H)
                self.cv.itemconfigure(self._msg_id, text=self.MESSAGES[-1])
        # ── Pulsing "Processing…" text: ease alpha 0.4 → 1.0 → 0.4 ──────────
        if not self._bar_done:
            if not hasattr(self, "_pulse_t"):
                self._pulse_t = 0.0
            self._pulse_t += 0.12
            import math as _math
            pulse_alpha = 0.4 + 0.6 * (0.5 + 0.5 * _math.sin(self._pulse_t))
            # Blend MUTED colour with alpha against BG for canvas text
            r_m, g_m, b_m = int("8b", 16), int("94", 16), int("9e", 16)
            r_b, g_b, b_b = int("0d", 16), int("11", 16), int("17", 16)
            rr = int(r_b + (r_m - r_b) * pulse_alpha)
            gg = int(g_b + (g_m - g_b) * pulse_alpha)
            bb = int(b_b + (b_m - b_b) * pulse_alpha)
            pulse_col = f"#{rr:02x}{gg:02x}{bb:02x}"
            try:
                self.cv.itemconfigure(self._msg_id, fill=pulse_col)
            except Exception:
                pass
        self._job = self.win.after(60, self._animate)

    def _on_ack_toggle(self):
        if self._ack_var.get():
            self._btn.configure(state="normal", bg=self.ACCENT, fg=self.BG, cursor="hand2")
        else:
            self._btn.configure(state="disabled", bg=self.BG3, fg=self.BG3, cursor="arrow")

    def _on_start(self):
        if not self._ack_var.get():
            return
        self._accepted = True
        self._closed   = True
        if hasattr(self, "_job"):
            try:
                self.win.after_cancel(self._job)
            except Exception:
                pass
        try:
            self.win.destroy()
        except Exception:
            pass
        if callable(self._on_accept_cb):
            self._on_accept_cb()

    def close(self):
        if self._closed:
            return
        self._closed = True
        if hasattr(self, "_job"):
            try:
                self.win.after_cancel(self._job)
            except Exception:
                pass
        try:
            self.win.destroy()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# ── PluginSplashScreen ───────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

class PluginSplashScreen:
    """
    Second splash screen shown after the disclaimer is accepted.
    Lists every loaded contest plugin so the user can see what's supported
    before the main application window opens.

    Also reusable post-launch as a normal dialog (standalone=True) via the
    "Supported Contests" toolbar button — same content, but with a real
    title bar / Close button instead of overrideredirect + "Launch App",
    and closing it does NOT trigger on_done_cb (the app is already open).
    """

    W       = 620
    BG      = "#0d1117"
    BG2     = "#161b22"
    BG3     = "#21262d"
    BG4     = "#1a1f26"
    ACCENT  = "#00d4aa"
    ACCENT2 = "#ff6b35"
    FG      = "#e6edf3"
    MUTED   = "#8b949e"
    AMBER   = "#f0c040"

    # How many ms to show before the "Launch" button appears
    _REVEAL_DELAY_MS = 300

    def __init__(self, root: tk.Tk, on_done_cb=None, standalone: bool = False):
        self._root      = root
        self._closed    = False
        self._on_done   = on_done_cb
        self._standalone = standalone

        # ── Gather plugins ────────────────────────────────────────────────────
        try:
            plugins = get_all_plugins()
        except Exception:
            plugins = []

        # ── Dynamic height based on plugin count ─────────────────────────────
        ROW_H       = 36
        HEADER_H    = 180   # logo + title block
        LIST_PAD    = 16    # top/bottom padding inside the list area
        FOOTER_H    = 60    # button row
        num_rows    = max(len(plugins), 1)
        list_h      = LIST_PAD * 2 + num_rows * ROW_H
        H           = HEADER_H + list_h + FOOTER_H
        self.H      = H

        self.win = tk.Toplevel(root)
        if standalone:
            # Normal closable window: title bar, Close-button (X), Escape key.
            self.win.title("Supported Contest Plugins — VK Contest Analyzer")
            self.win.resizable(False, False)
            self.win.protocol("WM_DELETE_WINDOW", self._close)
            self.win.bind("<Escape>", lambda e: self._close())
            self.win.transient(root)
        else:
            self.win.overrideredirect(True)
            self.win.resizable(False, False)
            self.win.attributes("-topmost", True)
            self.win.attributes("-alpha", 0.96)  # glassmorphism translucency
            self.win.protocol("WM_DELETE_WINDOW", lambda: None)
        self.win.configure(bg=self.BG)

        root.update_idletasks()
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        x  = (sw - self.W) // 2
        y  = (sh - H)      // 2
        self.win.geometry(f"{self.W}x{H}+{x}+{y}")
        self.win.update_idletasks()
        if standalone:
            self.win.focus_set()
            self.win.grab_set()

        # ── Canvas for the header + window border ────────────────────────────
        cv = tk.Canvas(self.win, width=self.W, height=H,
                       bg=self.BG, highlightthickness=0)
        cv.place(x=0, y=0)
        self._draw_header(cv, HEADER_H, H)

        # ── Plugin list area ──────────────────────────────────────────────────
        list_frame = tk.Frame(self.win, bg=self.BG2,
                              highlightbackground=self.BG3, highlightthickness=1)
        list_frame.place(x=28, y=HEADER_H, width=self.W - 56, height=list_h)

        if not plugins:
            lbl = tk.Label(list_frame, text="No plugins found.",
                           bg=self.BG2, fg=self.MUTED,
                           font=("Consolas", 10))
            lbl.pack(pady=LIST_PAD)
        else:
            for idx, plug in enumerate(plugins):
                row_bg = self.BG2 if idx % 2 == 0 else self.BG3
                row = tk.Frame(list_frame, bg=row_bg, height=ROW_H)
                row.pack(fill="x")
                row.pack_propagate(False)

                # Coloured bullet
                bullet = tk.Label(row, text="◆", bg=row_bg, fg=self.ACCENT,
                                  font=("Consolas", 10, "bold"), width=3)
                bullet.pack(side="left", padx=(12, 4))

                # Plugin display name
                name_text = getattr(plug, "display_name", type(plug).__name__)
                name_lbl = tk.Label(row, text=name_text, bg=row_bg, fg=self.FG,
                                    font=("Consolas", 10, "bold"), anchor="w")
                name_lbl.pack(side="left", fill="x", expand=True)

                # Optional: show the class name as a subtle identifier
                class_name = type(plug).__name__
                tag_lbl = tk.Label(row, text=f"[{class_name}]",
                                   bg=row_bg, fg=self.MUTED,
                                   font=("Consolas", 8), anchor="e", padx=12)
                tag_lbl.pack(side="right")

        # ── Footer / launch button ────────────────────────────────────────────
        footer_y = HEADER_H + list_h
        footer = tk.Frame(self.win, bg=self.BG)
        footer.place(x=0, y=footer_y, width=self.W, height=FOOTER_H)

        plugin_word = "plugin" if len(plugins) == 1 else "plugins"
        count_lbl = tk.Label(footer,
                             text=f"{len(plugins)} contest {plugin_word} loaded",
                             bg=self.BG, fg=self.MUTED,
                             font=("Consolas", 9))
        count_lbl.place(x=28, y=14)

        self._btn = tk.Button(
            footer, text=("Close" if self._standalone else "Launch App  ›"),
            font=("Consolas", 11, "bold"),
            bg=self.ACCENT, fg=self.BG,
            activebackground=self.ACCENT2, activeforeground=self.BG,
            relief="flat", bd=0, padx=20, pady=6,
            cursor="hand2",
            command=self._close,
        )
        self._btn.place(x=self.W // 2 - 95, y=10, width=190, height=34)

        # Outer border
        self.win.update()

    def _draw_header(self, cv, header_h, window_h=None):
        W = self.W
        H = window_h or header_h
        # Window border (drawn on full-height canvas)
        cv.create_rectangle(1, 1, W - 2, H - 2, outline=self.ACCENT, width=1)
        cv.create_rectangle(3, 3, W - 4, H - 4, outline=self.BG3,    width=1)
        cx, cy, r = W // 2, 52, 26
        outer, inner = [], []
        for i in range(6):
            a = math.radians(90 + 60 * i)
            outer.extend([cx + r * math.cos(a),       cy + r * math.sin(a)])
            inner.extend([cx + (r - 8) * math.cos(a), cy + (r - 8) * math.sin(a)])
        cv.create_polygon(outer, fill=self.BG2, outline=self.ACCENT, width=2)
        cv.create_polygon(inner, fill="", outline=self.ACCENT, width=1,
                          stipple="gray25")
        cv.create_text(cx, cy, text="⬡",
                       font=("Consolas", 20, "bold"), fill=self.ACCENT)

        cv.create_text(W // 2, 96,
                       text="SUPPORTED CONTEST PLUGINS",
                       font=("Consolas", 16, "bold"), fill=self.FG)
        cv.create_text(W // 2, 116,
                       text="The following contests are recognised and scored automatically",
                       font=("Consolas", 9), fill=self.MUTED)
        cv.create_line(60, 138, W - 60, 138, fill=self.BG3, width=1)
        cv.create_text(28, 154,
                       text="  PLUGIN NAME", anchor="w",
                       font=("Consolas", 8, "bold"), fill=self.ACCENT)
        cv.create_text(W - 28, 154,
                       text="CLASS IDENTIFIER  ", anchor="e",
                       font=("Consolas", 8, "bold"), fill=self.ACCENT)
        cv.create_line(28, 166, W - 28, 166, fill=self.BG3, width=1)

    def _close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._standalone:
                self.win.grab_release()
            self.win.destroy()
        except Exception:
            pass
        if callable(self._on_done) and not self._standalone:
            self._on_done()


# ═══════════════════════════════════════════════════════════════════════════════
# ── Entry point ──────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # ── High-DPI awareness (Windows) — must run before any Tk window ─────────
    # Without this, Windows scales Tk bitmaps up blurrily on HiDPI displays.
    # SetProcessDpiAwareness(1) = "System Aware": crisp fonts, sharp borders.
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass   # older Windows / Wine — safe to ignore

    root = tk.Tk()
    root.withdraw()

    splash = SplashScreen(root)

    def _launch():
        def _show_plugin_splash():
            def _open_app():
                app = App(root)
                app.withdraw()

                def _show():
                    app.attributes("-alpha", 0.0)
                    app.deiconify()
                    app.lift()
                    _fade_in(app, target_alpha=1.0, step=0.08)
                    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
                        app._db_path = sys.argv[1]
                        app._manual_refresh()

                root.after(200, _show)

            PluginSplashScreen(root, on_done_cb=_open_app)

        root.after(0, _show_plugin_splash)

    splash._on_accept_cb = _launch
    root.mainloop()
