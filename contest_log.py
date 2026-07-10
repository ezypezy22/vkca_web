"""
contest_log.py — self-contained data layer for VK Contest Analyzer
Zero tkinter / matplotlib dependencies. Importable by the web server.
"""
from __future__ import annotations

import sqlite3
import os
import sys
import re
import json
import math
import logging
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

# ── Plugin framework ──────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plugins.base import (
    ContestPlugin, SessionConfig, MultResult, GaugeDef,
)
from plugins.loader import plugin_for, get_all_plugins
from plugins.generic import GenericPlugin

# ── Band ordering (used by _generic_qso_value_estimate) ──────────────────────
_BAND_ORDER = ["160M", "80M", "60M", "40M", "30M", "20M", "17M", "15M",
               "12M", "10M", "6M", "2M", "70CM"]

# ── Compiled regex (used by ContestLog.load) ──────────────────────────────────
_VK_PREFIX_RE   = re.compile(r'^(VK|VJ|VL|AX)')
_PACKED_MULT_RE = re.compile(
    r'(?:^|[\s,/])(ACT|NSW|VIC|QLD|SA|WA|TAS|NT)-([A-Z]{2})([1-8])'
    r'(?:$|[\s,/]|$)', re.IGNORECASE)
_SHORT2_RE = re.compile(r'([A-Z]{2})([1-8])', re.IGNORECASE)

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
        Return a list of dicts for every contest instance in the database,
        including ones with zero QSOs logged yet, sorted by most recent first.
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
                logging.info("Contest start from DB: %s -> %s", sd, self._contest_start_dt)
        except Exception as e:
            logging.warning("Could not read ContestInstance.StartDate: %s", e)

        # ── Read the station's own callsign (for the live-ranking lookup) ──────
        # N1MM's Station table holds the logging station's identity — distinct
        # from DXLOG's per-QSO "Operator" column (multi-op operator credit).
        # Not every .s3db has this table/row populated, so this must degrade
        # to None rather than raise.
        self.my_call = None
        try:
            row = c.execute("SELECT Call FROM Station LIMIT 1").fetchone()
            if row and row[0]:
                self.my_call = str(row[0]).strip().upper() or None
        except Exception as e:
            logging.info("Could not read Station.Call (live ranking will be unavailable): %s", e)

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
        # When the plugin declares a preference list, keep EVERY candidate
        # that actually exists as a column (not just the first) — some
        # loggers (e.g. not1mm's ARRL 10M plugin) leave the higher-priority
        # column (Exchange1) present in the schema but always blank, and
        # only populate a lower-priority one (NR). A single up-front pick
        # would permanently lock onto the always-blank column since col()
        # only checks column existence, not whether it's ever populated;
        # sect_pref_cols below is consulted per-row instead, using the
        # first candidate with a non-blank value for that row.
        _pref = self.plugin.preferred_exchange_columns
        if _pref:
            _seen_pref = set()
            sect_pref_cols = []
            for name in _pref:
                if name.lower() in cols_lower and name.lower() not in _seen_pref:
                    _seen_pref.add(name.lower())
                    sect_pref_cols.append(name)
            sect_col = sect_pref_cols[0] if sect_pref_cols else None
        else:
            sect_col = col(["Sect","sect","SECT","Section","section","SECTION"])
            sect_pref_cols = [sect_col] if sect_col else []
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
        continent_col = col(["Continent","continent","CONTINENT"])

        logging.info(
            "Using columns: call=%s band=%s freq=%s mode=%s time=%s "
            "mult=%s sect=%s zone=%s m1=%s m2=%s dupe=%s pts=%s op=%s",
            call_col, band_col, freq_col, mode_col, time_col,
            mult_col, sect_col, zone_col, m1_col, m2_col, dupe_col, pts_col, op_col
        )

        sel_cols = [call_col, band_col, freq_col, mode_col, time_col,
                    mult_col, zone_col, m1_col, m2_col,
                    dupe_col, pts_col, id_col, op_col, continent_col]
        sel_cols += sect_pref_cols
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
        # Parallel to self.qsos — True where "dupe" below came from the
        # ambiguous pts==0 fallback rather than an explicit source signal
        # (IsDupe/Dupe column, or ContactType=="D"). Consumed by the
        # mode_scoped_dupes correction pass after this loop.
        _dupe_is_heuristic = []
        # Hoist mult list/set and regexes outside the per-QSO loop (fixes per-row recompute)
        _plugin_mult_list = self.plugin.mult_list()
        _plugin_mult_set  = set(_plugin_mult_list) if _plugin_mult_list else set()
        for r in rows:
            d = dict(zip(sel_cols, r))

            call = str(d.get(call_col) or "").strip().upper()
            mode = str(d.get(mode_col) or "SSB").strip().upper()
            operator = str(d.get(op_col) or "").strip().upper() if op_col else ""

            # ── Raw exchange / section ────────────────────────────────────────
            # Walk the plugin's preferred columns in priority order and use
            # the first one that's actually non-blank for THIS row — some
            # loggers leave a higher-priority column present but always
            # empty (see sect_pref_cols comment above).
            raw_sect = ""
            for _pc in sect_pref_cols:
                _v = str(d.get(_pc) or "").strip().upper()
                if _v:
                    raw_sect = _v
                    break
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
            dupe_is_heuristic = False
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
                raw_dupe_str = str(raw_dupe or "").strip().upper()
                if raw_dupe_str:
                    dupe = 1 if raw_dupe_str == "D" else 0
                elif isinstance(self.plugin, GenericPlugin):
                    # GenericPlugin has no recalc_pts() override to repair
                    # false positives (unlike e.g. CQWW's same-country 0-pt
                    # handling), and un-scored/non-contest logging (e.g.
                    # not1mm's "General-Logging" catch-all) legitimately has
                    # Points==0 on every row — so the pts==0 fallback below
                    # would flag every single QSO as a dupe. Stay conservative
                    # here and only trust an explicit "D".
                    dupe = 0
                else:
                    # not1mm's DXLOG has a ContactType column but never
                    # writes "D" into it — it zeroes Points on a dupe
                    # instead (see plugins/*.py points() implementations
                    # upstream in not1mm), so an always-blank ContactType
                    # would otherwise permanently hide every dupe from the
                    # Dupe Checker page. Fall back to the same pts==0
                    # heuristic used when no dupe column exists at all.
                    dupe = 1 if pts == 0 else 0
                    dupe_is_heuristic = True
            else:
                # Last-resort fallback: 0-pt QSOs are dupes.
                # NOTE: this is overridden by plugin.recalc_pts() for contests
                # where 0 pts is valid (e.g. CQWW same-country contacts).
                dupe = 1 if pts == 0 else 0
                dupe_is_heuristic = True

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
            zone_is_non_numeric = False
            if raw_zone:
                try:
                    cqz = int(float(raw_zone))
                except (ValueError, TypeError):
                    zone_is_non_numeric = True
            if not cqz:
                cqz = cqz_from_call(call)

            # ── Non-numeric zone fallback ────────────────────────────────────
            # not1mm's IARU HF plugin stuffs BOTH the ITU zone number and the
            # HQ/official society abbreviation into the same Zone column
            # (Exchange1/Mult1 are never written at all), unlike real N1MM
            # which keeps the abbreviation in Exchange1/Mult1. When the zone
            # column holds letters (not a plain number) and we haven't
            # resolved any other multiplier value, treat it as the mult
            # identity — this is exactly what IARU's _is_hq_or_official()
            # needs to tell an HQ/official contact apart from a zone contact.
            if zone_is_non_numeric and not mult:
                mult = raw_zone.upper()
                mult_source = mult_source or "ZONE_COL_NON_NUMERIC"

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

            # ── Continent (N1MM's own country-file lookup, when available) ─────
            continent = str(d.get(continent_col) or "").strip().upper() \
                if continent_col else ""

            if call and t:
                _dupe_is_heuristic.append(dupe_is_heuristic)
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
                    "continent":   continent,
                    "_table":      target,
                    # Populated asynchronously by web/server.py's QRZ lookup
                    # worker — never set here, ContestLog stays network-free.
                    "qrz_name":    "",
                    "qrz_grid":    "",
                    "qrz_state":   "",
                    "qrz_status":  "none",   # "none"|"pending"|"found"|"not_found"
                })

        # ── Multiplier-flag sanity check ────────────────────────────────────
        # Some loggers (e.g. not1mm's IARU HF and ARRL 10M plugins) declare
        # IsMultiplier1/IsMultiplier2 columns but never actually write a 1
        # into them — every plugin's multiplier-counting code treats "column
        # present" (is_mult1 is not None) as "trust this flag", only falling
        # back to counting every distinct worked key/band pair when the
        # column is entirely absent. A column that exists but is always 0
        # would otherwise make every band-mult / HQ-mult / secondary-mult
        # count come out permanently zero for those logs. If the flag is
        # never 1 anywhere in the whole log, treat it as unset so plugins
        # fall back to their own distinct-pair counting instead.
        if self.qsos and not any(q["is_mult1"] == 1 for q in self.qsos):
            for q in self.qsos:
                q["is_mult1"] = None
        if self.qsos and not any(q["is_mult2"] == 1 for q in self.qsos):
            for q in self.qsos:
                q["is_mult2"] = None

        # ── Mode-scoped dupe correction (issue #8) ──────────────────────────
        # For contests where a station may be worked once per band PER MODE
        # (plugin.mode_scoped_dupes — e.g. ARRL 10M rule 5.2.1), the pts==0
        # heuristic above can't distinguish "genuinely reworked on the same
        # mode" from "reworked on a different mode, but the source's own
        # dupe-checking didn't separate modes and zeroed Points anyway" (seen
        # with not1mm-sourced ARRL 10M logs). Only the ambiguous heuristic-
        # derived dupes are reconsidered here — an explicit IsDupe/Dupe/
        # ContactType="D" signal from the source is always trusted as-is.
        # First occurrence of a given (call, band, mode-bucket) is un-flagged
        # so recalc_pts() below can fill in its correct point value; a
        # genuine repeat on the *same* mode-bucket stays flagged.
        if getattr(self.plugin, "mode_scoped_dupes", False) and self.qsos:
            _seen_non_dupe = set()
            for q, is_heuristic in zip(self.qsos, _dupe_is_heuristic):
                key = (q["call"], q["band"], self.plugin.dupe_mode_key(q))
                if is_heuristic and q["dupe"] and key not in _seen_non_dupe:
                    q["dupe"] = 0
                if not q["dupe"]:
                    _seen_non_dupe.add(key)

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

    def session_status(self, now: Optional[datetime] = None):
        cfg = self._session_cfg
        cs  = self.contest_start()
        if not cs:
            return {}
        if now is None:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
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
                "duration_mins":   cfg.duration_mins,
                "label_prefix":    cfg.label_prefix,
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
                "duration_mins":   cfg.duration_mins,
                "label_prefix":    cfg.label_prefix,
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
            "duration_mins":        cfg.duration_mins,
            "label_prefix":         cfg.label_prefix,
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

    def compute_snapshot(self, now: Optional[datetime] = None) -> dict:
        """
        Single-pass computation of every value needed by _refresh_overview_cards.

        `now` lets a caller pin "the current time" for session_status() — used
        by compute_snapshot_at() so a historical replay's elapsed/remaining
        time matches the QSOs actually included, instead of real wall-clock now.

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
            "_plugin_name":    getattr(plugin, "display_name", ""),
            "my_call":         self.my_call,
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
            "session_status":  self.session_status(now),
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

    def compute_snapshot_at(self, cutoff: datetime) -> dict:
        """Recompute the snapshot as it would have looked using only QSOs at
        or before `cutoff` — powers the Overview replay scrubber. `now` is
        pinned to `cutoff` too, so elapsed/remaining contest time in the
        result matches the QSOs included rather than real wall-clock time."""
        original_qsos = self.qsos
        try:
            self.qsos = [q for q in original_qsos if q["time"] <= cutoff]
            return self.compute_snapshot(now=cutoff)
        finally:
            self.qsos = original_qsos
