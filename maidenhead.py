"""
maidenhead.py
─────────────
Maidenhead grid-locator helpers for the VHF/UHF contests: validation, the
4-character "square" and the 6-character "sub-square", and great-circle
distance between two sub-square centres (the WIA VHF/UHF Field Day scores
every contact from the sub-square centres: "Distances between stations is
calculated from the sub-square centre").
"""

from __future__ import annotations

import math
import re
from typing import Optional

_EARTH_RADIUS_KM = 6371.0

_FULL_RE   = re.compile(r"^[A-R]{2}[0-9]{2}[A-X]{2}$")
_SQUARE_RE = re.compile(r"^[A-R]{2}[0-9]{2}$")


def norm(loc) -> str:
    """Upper-cased, trimmed locator ('' if None)."""
    return (loc or "").strip().upper()


def is_full_locator(loc) -> bool:
    """A complete 6-character sub-square locator, e.g. QF56LB."""
    return bool(_FULL_RE.match(norm(loc)))


def is_square(loc) -> bool:
    return bool(_SQUARE_RE.match(norm(loc)))


def square4(loc) -> str:
    """The 4-character square ('QF56') of a 4- or 6-character locator, or ''."""
    loc = norm(loc)
    return loc[:4] if (is_full_locator(loc) or is_square(loc)) else ""


def centre(loc) -> Optional[tuple]:
    """(lat, lon) in degrees of the centre of a 6-character sub-square (or, for
    a bare 4-character square, of that square). None if not a valid locator."""
    loc = norm(loc)
    if is_full_locator(loc):
        lon = (ord(loc[0]) - 65) * 20 + int(loc[2]) * 2 + (ord(loc[4]) - 65) * (5 / 60) + (2.5 / 60) - 180
        lat = (ord(loc[1]) - 65) * 10 + int(loc[3]) + (ord(loc[5]) - 65) * (2.5 / 60) + (1.25 / 60) - 90
        return lat, lon
    if is_square(loc):
        lon = (ord(loc[0]) - 65) * 20 + int(loc[2]) * 2 + 1 - 180
        lat = (ord(loc[1]) - 65) * 10 + int(loc[3]) + 0.5 - 90
        return lat, lon
    return None


def distance_km(a, b) -> Optional[float]:
    """Great-circle distance in km between two locators' centres (None if either
    is invalid)."""
    ca, cb = centre(a), centre(b)
    if ca is None or cb is None:
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, (ca[0], ca[1], cb[0], cb[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(h))
