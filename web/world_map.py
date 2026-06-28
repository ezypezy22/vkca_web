"""
world_map.py  v7 — World Map for VK Contest Analyzer (Folium/Leaflet edition)
==============================================================================
Replaces the tkinter-Canvas renderer with a Folium HTML map opened in the
default browser.

Fixes vs v6:
  • Great-circle paths now always take the visually correct arc.
    Previously, paths from VK to South America / W5 dipped to -65° latitude
    through Antarctica, appearing as flat horizontal lines. Fix: compute BOTH
    the minor arc and the major arc (going the long way around the sphere)
    via proper spherical interpolation, then pick whichever arc has the higher
    minimum latitude (stays closest to the equator = the arc a human would draw).
  • Antimeridian splitting retained: paths that cross ±180° are split into
    two segments so Leaflet never draws a straight line across the whole map.
  • 12 tile layers including ESRI and Stadia options.

Public API (unchanged):
    WorldMapWindow(master, qsos, my_lat, my_lon, band_colours, theme)

Dependencies:
    folium >= 0.14   (pip install folium)
"""

import math
import os
import re
import tempfile
import threading
import webbrowser
from collections import defaultdict
from typing import List, Optional, Tuple

try:
    import folium
    _FOLIUM_OK = True
except ImportError:
    _FOLIUM_OK = False

try:
    import tkinter as tk
    _TK_OK = True
except ImportError:
    _TK_OK = False


# ── Tile layer definitions ────────────────────────────────────────────────────
TILE_LAYERS = {
    "Dark (CartoDB)":            ("CartoDB dark_matter", {}),
    "Light (CartoDB)":           ("CartoDB positron",    {}),
    "OpenStreetMap":             ("OpenStreetMap",       {}),
    "ESRI Satellite":            (None, {"tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",          "attr": "Esri, Maxar, Earthstar Geographics"}),
    "ESRI Topo":                 (None, {"tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",          "attr": "Esri, HERE, Garmin, FAO, NOAA, USGS"}),
    "ESRI Street":               (None, {"tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",        "attr": "Esri, HERE, Garmin"}),
    "ESRI Ocean":                (None, {"tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}",  "attr": "Esri, GEBCO, Garmin, NaturalVue"}),
    "ESRI Light Gray":           (None, {"tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", "attr": "Esri, HERE, Garmin"}),
    "ESRI Dark Gray":            (None, {"tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}", "attr": "Esri, HERE, Garmin"}),
    "ESRI National Geographic":  (None, {"tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/NatGeo_World_Map/MapServer/tile/{z}/{y}/{x}",        "attr": "Esri, National Geographic Society"}),
    "Stadia Smooth Dark":        (None, {"tiles": "https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png", "attr": "Stadia Maps, OpenMapTiles, OpenStreetMap"}),
    "Stadia OSM Bright":         (None, {"tiles": "https://tiles.stadiamaps.com/tiles/osm_bright/{z}/{x}/{y}{r}.png",          "attr": "Stadia Maps, OpenMapTiles, OpenStreetMap"}),
}

DEFAULT_TILE = "Dark (CartoDB)"


# ── Callsign prefix → (lat, lon) ─────────────────────────────────────────────
_PREFIX_LATLON: dict = {
    "VK":  (-25.0, 133.0), "VK9": (-14.0, 130.0), "ZL":  (-41.0, 174.0),
    "YB":  (-5.0,  120.0), "DU":  (13.0,  122.0), "HS":  (15.0,  101.0),
    "9V":  (1.4,   103.8), "VR":  (22.3,  114.2), "BV":  (23.7,  121.0),
    "BY":  (35.0,  105.0), "HL":  (37.0,  127.5), "JA":  (37.0,  138.0),
    "VU":  (22.0,   79.0), "4S":  (7.9,    80.7), "AP":  (30.0,   69.0),
    "A4":  (23.0,   58.0), "A6":  (24.5,   54.4), "HZ":  (24.0,   45.0),
    "OD":  (33.9,   35.5), "4X":  (31.5,   35.0), "TA":  (39.0,   35.0),
    "UA9": (60.0,   80.0), "UA0": (60.0,  120.0), "JT":  (46.5,  102.9),
    "XV":  (16.0,  108.0), "XU":  (12.5,  105.0), "XW":  (18.0,  103.0),
    "XZ":  (19.0,   96.0), "S2":  (24.0,   90.0), "9N":  (28.0,   84.0),
    "A5":  (27.5,   90.5), "T2":  (-8.5,  179.2), "T3":  (1.9,  -157.4),
    "5W":  (-13.8,-172.1), "3D2": (-17.7, 178.8), "KH6": (21.3, -157.8),
    "KH8": (-14.3,-170.7), "VK9X":(-10.5, 105.7), "VK9C":(-12.2,  96.8),
    "VK0": (-53.1,  73.5),
    "W":   (38.0,  -97.0), "K":   (38.0,  -97.0), "N":   (38.0,  -97.0),
    "AA":  (38.0,  -97.0), "VE":  (60.0,  -96.0), "XE":  (23.0, -102.0),
    "TG":  (15.5,  -90.2), "HR":  (15.0,  -86.5), "YN":  (12.9,  -85.2),
    "TI":  (10.0,  -84.0), "HP":  (8.4,   -80.1), "HH":  (19.0,  -72.3),
    "HI":  (19.0,  -70.2), "CM":  (22.0,  -79.5), "PY":  (-10.0, -55.0),
    "LU":  (-35.0, -65.0), "CE":  (-30.0, -71.0), "OA":  (-10.0, -76.0),
    "HC":  (-2.0,  -77.5), "CP":  (-17.0, -65.0), "ZP":  (-23.0, -58.0),
    "CX":  (-33.0, -56.0),
    "G":   (52.5,   -1.5), "GM":  (57.0,   -4.0), "GW":  (52.5,   -3.5),
    "GI":  (54.7,   -6.8), "EI":  (53.0,   -8.0), "F":   (46.0,    2.0),
    "DL":  (51.0,   10.0), "PA":  (52.5,    5.3), "ON":  (50.5,    4.5),
    "LX":  (49.8,    6.1), "HB":  (47.0,    8.0), "OE":  (47.5,   14.5),
    "I":   (43.0,   12.0), "EA":  (40.0,   -4.0), "CT":  (39.5,   -8.0),
    "OH":  (64.0,   26.0), "SM":  (62.0,   15.0), "LA":  (65.0,   15.0),
    "OZ":  (56.0,   10.0), "SP":  (52.0,   20.0), "OK":  (50.0,   15.5),
    "OM":  (48.7,   19.5), "HA":  (47.0,   19.5), "YO":  (45.5,   25.0),
    "LZ":  (42.7,   25.5), "SV":  (39.0,   22.0), "YU":  (44.0,   21.0),
    "S5":  (46.1,   14.8), "9A":  (45.2,   16.5), "UA":  (61.0,   60.0),
    "UR":  (49.0,   32.0), "EU":  (53.9,   28.0), "LY":  (56.0,   24.0),
    "YL":  (57.0,   25.0), "ES":  (59.0,   25.0),
    "ZS":  (-29.0,  25.0), "ZE":  (-20.0,  30.0), "9J":  (-14.0,  28.0),
    "5H":  (-6.0,   35.0), "5Z":  (1.0,    38.0), "ET":  (9.0,    40.0),
    "SU":  (27.0,   30.0), "CN":  (32.0,   -6.0), "7X":  (28.0,    3.0),
    "5A":  (26.0,   17.0), "ST":  (15.0,   32.0), "EA8": (28.0,  -15.0),
    "EP":  (33.0,   53.0), "YK":  (34.8,   38.9), "UN":  (48.0,   68.0),
    "EX":  (41.5,   74.5), "EY":  (39.0,   71.0), "EZ":  (40.0,   59.0),
    "UK":  (41.5,   64.5), "4J":  (40.5,   47.5), "4L":  (42.0,   44.0),
    "EK":  (40.0,   45.0),
}
_VK_AREA: dict = {
    1: (-35.3, 149.1), 2: (-33.9, 151.2), 3: (-37.8, 145.0),
    4: (-27.5, 153.0), 5: (-34.9, 138.6), 6: (-31.9, 115.9),
    7: (-42.9, 147.3), 8: (-12.5, 130.8),
}

_FALLBACK_COLOURS = {
    "160M": "#e040fb", "80M": "#ff6b35",  "60M": "#f0c040",
    "40M":  "#2ed573", "30M": "#00bcd4",  "20M": "#00d4aa",
    "17M":  "#64b5f6", "15M": "#ff5252",  "12M": "#ffab40",
    "10M":  "#69f0ae", "6M":  "#ea80fc",  "2M":  "#80d8ff",
    "70CM": "#ccff90",
}
_BAND_ORDER = [
    "160M","80M","60M","40M","30M","20M",
    "17M","15M","12M","10M","6M","2M","70CM",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def latlon_from_call(call: str):
    call = call.upper().strip()
    m = re.match(r"VK(\d)", call)
    if m:
        return _VK_AREA.get(int(m.group(1)), _PREFIX_LATLON.get("VK"))
    for n in (4, 3, 2, 1):
        p = _PREFIX_LATLON.get(call[:n])
        if p:
            return p
    return None


def _bcolour(band_colours: dict, band: str) -> str:
    bu = band.upper()
    return (band_colours.get(bu)
            or band_colours.get(band.lower())
            or _FALLBACK_COLOURS.get(bu, "#00d4aa"))


def _slerp_arc(la1: float, lo1: float, la2: float, lo2: float,
               n: int, major: bool = False) -> List[Tuple[float, float]]:
    """
    Spherical linear interpolation between two points.

    major=False → minor arc (shorter great-circle path, default)
    major=True  → major arc (longer path, going the other way around)

    Uses the perpendicular-component form so the direction of traversal is
    explicitly controlled, unlike the atan2 form which always returns the
    same arc regardless of how you nudge the destination longitude.
    """
    la1r, lo1r, la2r, lo2r = map(math.radians, [la1, lo1, la2, lo2])

    # 3-D unit vectors
    P1 = (math.cos(la1r)*math.cos(lo1r),
          math.cos(la1r)*math.sin(lo1r),
          math.sin(la1r))
    P2 = (math.cos(la2r)*math.cos(lo2r),
          math.cos(la2r)*math.sin(lo2r),
          math.sin(la2r))

    dot  = max(-1.0, min(1.0, sum(a*b for a, b in zip(P1, P2))))
    d    = math.acos(dot)          # minor-arc angular distance
    norm = math.sqrt(1 - dot**2)

    if d < 1e-9 or norm < 1e-9:
        return [(la1, lo1)] * (n + 1)

    # Pp: unit vector in the plane of P1,P2, perpendicular to P1, pointing toward P2
    Pp = tuple((P2[i] - dot * P1[i]) / norm for i in range(3))

    pts = []
    for k in range(n + 1):
        t     = k / n
        # Minor arc: θ goes 0 → d
        # Major arc: θ goes 0 → -(2π - d)  (backward around the sphere)
        theta = t * d if not major else -t * (2 * math.pi - d)
        cx = math.cos(theta) * P1[0] + math.sin(theta) * Pp[0]
        cy = math.cos(theta) * P1[1] + math.sin(theta) * Pp[1]
        cz = math.cos(theta) * P1[2] + math.sin(theta) * Pp[2]
        pts.append((
            math.degrees(math.atan2(cz, math.sqrt(cx**2 + cy**2))),
            math.degrees(math.atan2(cy, cx)),
        ))
    return pts


def gc_segments_for_leaflet(la1: float, lo1: float,
                             la2: float, lo2: float,
                             n: int = 80) -> List[List[List[float]]]:
    """
    Return a list of [[lat, lon], …] segments ready for Leaflet PolyLine.

    Algorithm:
      1. Compute both the minor arc and the major arc between the two points.
      2. Pick the arc whose minimum latitude is higher (stays closer to the
         equator) — this is always the visually expected path from a radio
         operator's perspective.
      3. Unwrap the chosen arc's longitudes into a continuous sequence.
      4. Split at every antimeridian crossing (odd multiples of 180° in the
         unwrapped sequence), interpolating the exact crossing latitude.
      5. Re-wrap each segment's longitudes to [-180, 180] for Leaflet.
    """
    minor = _slerp_arc(la1, lo1, la2, lo2, n, major=False)
    major = _slerp_arc(la1, lo1, la2, lo2, n, major=True)

    min_minor = min(p[0] for p in minor)
    min_major = min(p[0] for p in major)
    pts = minor if min_minor >= min_major else major

    if len(pts) <= 1:
        return [[[pts[0][0], pts[0][1]]]] if pts else []

    # ── Unwrap longitudes ─────────────────────────────────────────────────────
    unwrapped: List[Tuple[float, float]] = [(pts[0][0], pts[0][1])]
    for i in range(1, len(pts)):
        prev_lon = unwrapped[-1][1]
        curr_lon = pts[i][1]
        diff = curr_lon - prev_lon
        while diff > 180:   diff -= 360
        while diff <= -180: diff += 360
        unwrapped.append((pts[i][0], prev_lon + diff))

    # ── Split at antimeridian crossings ───────────────────────────────────────
    def _wrap(lon: float) -> float:
        lon = lon % 360
        if lon > 180:
            lon -= 360
        return lon

    segments: List[List[List[float]]] = []
    current: List[List[float]] = [[unwrapped[0][0], _wrap(unwrapped[0][1])]]

    for i in range(1, len(unwrapped)):
        lat0, lon0 = unwrapped[i - 1]
        lat1, lon1 = unwrapped[i]

        lo_min, lo_max = min(lon0, lon1), max(lon0, lon1)
        k_start = math.ceil(lo_min / 180)
        k_end   = math.floor(lo_max / 180)
        crossings = [
            k * 180
            for k in range(int(k_start), int(k_end) + 1)
            if k % 2 != 0 and lo_min < k * 180 < lo_max
        ]

        if not crossings:
            current.append([lat1, _wrap(lon1)])
        else:
            for cross_lon in sorted(crossings, key=lambda c: abs(c - lon0)):
                frac    = (cross_lon - lon0) / (lon1 - lon0)
                mid_lat = lat0 + frac * (lat1 - lat0)
                current.append([mid_lat, _wrap(cross_lon)])
                segments.append(current)
                other_side = cross_lon - math.copysign(360, lon1 - lon0)
                current = [[mid_lat, _wrap(other_side)]]
            current.append([lat1, _wrap(lon1)])

    if current:
        segments.append(current)

    return segments


# ═══════════════════════════════════════════════════════════════════════════════
class WorldMapWindow:
    """
    Drop-in replacement for the tkinter-Canvas WorldMapWindow.
    Generates a Folium/Leaflet HTML file and opens it in the default browser.
    """

    DEFAULT_LAT = -33.87
    DEFAULT_LON =  151.21

    def __init__(
        self,
        master,
        qsos:         list,
        my_lat:       float = DEFAULT_LAT,
        my_lon:       float = DEFAULT_LON,
        band_colours: Optional[dict] = None,
        theme:        Optional[dict] = None,
    ):
        self._master       = master
        self._my_lat       = my_lat
        self._my_lon       = my_lon
        self._band_colours = band_colours or {}
        self._theme        = theme or {}

        if not _FOLIUM_OK:
            self._show_error(
                "folium is not installed.\n\n"
                "Run:  pip install folium\n\nthen restart the analyzer."
            )
            return

        band_calls: dict = defaultdict(set)
        call_info:  dict = {}

        for q in qsos:
            if q.get("dupe"):
                continue
            call = q.get("call", "")
            band = (q.get("band") or "?").upper()
            if not call:
                continue
            ll = latlon_from_call(call)
            if ll is None:
                continue
            band_calls[band].add(call)
            if call not in call_info:
                call_info[call] = {
                    "bands": set(), "count": 0,
                    "latlon": ll,   "modes": set(),
                }
            call_info[call]["bands"].add(band)
            call_info[call]["count"] += 1
            call_info[call]["modes"].add(q.get("mode", ""))

        all_bands = sorted(
            band_calls.keys(),
            key=lambda b: _BAND_ORDER.index(b) if b in _BAND_ORDER else 99,
        )

        self._show_toast("🌍  Generating world map…")
        threading.Thread(
            target=self._build_and_open,
            args=(band_calls, call_info, all_bands),
            daemon=True,
        ).start()

    # ── Map construction ──────────────────────────────────────────────────────

    def _build_and_open(self, band_calls, call_info, all_bands):
        try:
            html_path = self._build_map(band_calls, call_info, all_bands)
            webbrowser.open(f"file://{html_path}")
        except Exception as exc:
            self._show_error(f"Failed to generate map:\n\n{exc}")

    def _build_map(self, band_calls, call_info, all_bands) -> str:

        accent = self._theme.get("ACCENT", "#00d4aa")
        bg     = self._theme.get("BG2",    "#161b22")
        fg_col = self._theme.get("FG",     "#e6edf3")
        muted  = self._theme.get("MUTED",  "#8b949e")

        m = folium.Map(
            location=[20, 0],
            zoom_start=2,
            tiles=None,
            world_copy_jump=True,
        )

        # ── Tile layers ───────────────────────────────────────────────────────
        first = True
        for label, (builtin, kwargs) in TILE_LAYERS.items():
            if builtin is not None:
                tl = folium.TileLayer(builtin, name=label, show=first)
            else:
                tl = folium.TileLayer(
                    tiles=kwargs["tiles"],
                    attr=kwargs.get("attr", ""),
                    name=label,
                    show=first,
                    max_zoom=19,
                )
            tl.add_to(m)
            first = False

        # ── Band feature groups ───────────────────────────────────────────────
        band_groups = {
            band: folium.FeatureGroup(name=band, show=True)
            for band in all_bands
        }

        # ── Great-circle lines ────────────────────────────────────────────────
        for band in all_bands:
            colour = _bcolour(self._band_colours, band)
            fg     = band_groups[band]
            for call in band_calls.get(band, set()):
                info = call_info.get(call)
                if not info:
                    continue
                lat2, lon2 = info["latlon"]
                segments = gc_segments_for_leaflet(
                    self._my_lat, self._my_lon, lat2, lon2, n=80
                )
                for seg in segments:
                    if len(seg) < 2:
                        continue
                    folium.PolyLine(
                        locations=seg,
                        color=colour,
                        weight=1.5,
                        opacity=0.75,
                        tooltip=f"{call} · {band}",
                    ).add_to(fg)

        # ── Station dots ──────────────────────────────────────────────────────
        for call, info in call_info.items():
            active_bands = sorted(
                info["bands"],
                key=lambda b: _BAND_ORDER.index(b) if b in _BAND_ORDER else 99,
            )
            if not active_bands:
                continue
            lat2, lon2 = info["latlon"]
            bands_str  = " · ".join(active_bands)
            modes_str  = " · ".join(sorted(x for x in info["modes"] if x) or ["?"])

            for band in active_bands:
                fg = band_groups.get(band)
                if fg is None:
                    continue
                c = _bcolour(self._band_colours, band)
                tooltip_html = (
                    f"<b style='color:{c};font-family:Consolas,monospace'>{call}</b><br>"
                    f"<span style='color:#aaa;font-family:Consolas,monospace;font-size:11px'>"
                    f"QSOs&nbsp;: {info['count']}<br>"
                    f"Bands: {bands_str}<br>"
                    f"Mode&nbsp;: {modes_str}</span>"
                )
                folium.CircleMarker(
                    location=[lat2, lon2],
                    radius=4,
                    color="#000",
                    weight=1,
                    fill=True,
                    fill_color=c,
                    fill_opacity=0.9,
                    tooltip=folium.Tooltip(tooltip_html, sticky=False),
                ).add_to(fg)

        for fg in band_groups.values():
            fg.add_to(m)

        # ── My station marker ─────────────────────────────────────────────────
        folium.Marker(
            location=[self._my_lat, self._my_lon],
            icon=folium.DivIcon(
                html=(
                    f"<div style='width:14px;height:14px;border-radius:50%;"
                    f"background:{accent};border:2px solid #fff;"
                    f"box-shadow:0 0 8px {accent},0 0 2px #fff;'></div>"
                ),
                icon_size=(14, 14),
                icon_anchor=(7, 7),
            ),
            tooltip=folium.Tooltip(
                f"<b style='color:{accent};font-family:Consolas,monospace'>▶ MY STATION</b><br>"
                f"<span style='color:#aaa;font-family:Consolas,monospace;font-size:11px'>"
                f"{self._my_lat:.3f}°, {self._my_lon:.3f}°</span>",
                sticky=False,
            ),
            z_index_offset=1000,
        ).add_to(m)

        # ── Layer control ─────────────────────────────────────────────────────
        folium.LayerControl(position="topright", collapsed=False).add_to(m)

        # ── Stats overlay ─────────────────────────────────────────────────────
        total_stations = len(call_info)
        total_qsos     = sum(i["count"] for i in call_info.values())

        m.get_root().html.add_child(folium.Element(f"""
        <div style="position:fixed;top:10px;left:10px;z-index:9999;
            background:{bg}ee;color:{fg_col};
            font-family:Consolas,monospace;font-size:12px;
            padding:10px 14px;border-radius:6px;
            border:1px solid {muted}55;box-shadow:0 2px 10px #0009;
            pointer-events:none;line-height:1.6;">
            <b style="color:{accent}">⬡ VK CONTEST ANALYZER</b><br>
            <span style="color:{muted}">Stations : </span><b>{total_stations}</b><br>
            <span style="color:{muted}">Total QSOs: </span><b>{total_qsos}</b><br>
            <span style="color:{muted}">Bands     : </span><b>{len(all_bands)}</b>
        </div>"""))

        # ── Band legend ───────────────────────────────────────────────────────
        legend_rows = "".join(
            f"<div style='display:flex;align-items:center;gap:7px;margin:3px 0'>"
            f"<div style='width:24px;height:3px;"
            f"background:{_bcolour(self._band_colours, b)};border-radius:2px'></div>"
            f"<span style='color:{_bcolour(self._band_colours, b)};"
            f"font-weight:bold;font-size:11px'>{b}</span></div>"
            for b in all_bands
        )
        m.get_root().html.add_child(folium.Element(f"""
        <div style="position:fixed;bottom:30px;left:10px;z-index:9999;
            background:{bg}ee;color:{fg_col};
            font-family:Consolas,monospace;
            padding:8px 13px;border-radius:6px;
            border:1px solid {muted}55;box-shadow:0 2px 10px #0009;">
            <b style="color:{accent};font-size:11px;letter-spacing:1px">BANDS</b><br>
            {legend_rows}
        </div>"""))

        # ── Save ──────────────────────────────────────────────────────────────
        tmp = tempfile.NamedTemporaryFile(
            suffix=".html", prefix="vkcontest_map_",
            delete=False, mode="w", encoding="utf-8",
        )
        m.save(tmp.name)
        tmp.close()
        return tmp.name

    # ── UI helpers ────────────────────────────────────────────────────────────

    def _show_toast(self, message: str):
        if not _TK_OK or self._master is None:
            return
        try:
            toast = tk.Toplevel(self._master)
            toast.overrideredirect(True)
            toast.attributes("-topmost", True)
            toast.configure(bg="#161b22")
            accent = self._theme.get("ACCENT", "#00d4aa")
            tk.Label(
                toast, text=message,
                font=("Consolas", 11), fg=accent, bg="#161b22",
                padx=20, pady=12,
            ).pack()
            toast.update_idletasks()
            sw, sh = toast.winfo_screenwidth(), toast.winfo_screenheight()
            w,  h  = toast.winfo_reqwidth(),    toast.winfo_reqheight()
            toast.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
            toast.after(3000, toast.destroy)
        except Exception:
            pass

    def _show_error(self, message: str):
        if _TK_OK:
            try:
                from tkinter import messagebox
                messagebox.showerror("World Map — Error", message)
                return
            except Exception:
                pass
        print(f"[WorldMapWindow] ERROR: {message}")
