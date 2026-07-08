"""
web/qrz.py — QRZ.com XML Data API lookup (https://xmldata.qrz.com/xml/current/).

Session-key auth: log in once with username/password to get a Session Key,
reuse it for lookups, transparently re-login on expiry. Requires a QRZ.com
XML subscription — a free/base account gets an explicit "not authorized"
error back from the API, surfaced here as QRZAuthError.

All network I/O here is synchronous (requests), matching web/cosb.py's
convention — callers must run this off the asyncio event loop (executor or
a dedicated worker thread; see the QRZ worker thread in web/server.py).
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Optional

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://xmldata.qrz.com/xml/current/"
AGENT = "vkca"
TIMEOUT_SECS = 8
USER_AGENT = "VKContestAnalyzer/26.7 (+https://github.com/ezypezy22/vkca_web)"


class QRZError(Exception):
    """Generic QRZ API error — the XML response's <Session><Error> text."""


class QRZAuthError(QRZError):
    """Username/password rejected, or the account lacks XML API access."""


class QRZSessionExpired(QRZError):
    """Session key timed out or was otherwise invalidated — re-login and retry."""


class QRZNotFound(QRZError):
    """The callsign isn't in QRZ's database. A definitive, cacheable result."""


def _strip_ns(el: ET.Element) -> ET.Element:
    """QRZ's XML uses the http://xmldata.qrz.com namespace on every element,
    which makes plain tag lookups like el.find('Session') fail silently
    (they'd need the {http://xmldata.qrz.com} prefix). Rewriting every tag
    in place once, right after parsing, lets the rest of this module use
    plain, unprefixed tag names."""
    for node in el.iter():
        if "}" in node.tag:
            node.tag = node.tag.split("}", 1)[1]
    return el


def _get(params: dict) -> ET.Element:
    try:
        resp = requests.get(
            BASE_URL,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT_SECS,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise QRZError(f"QRZ request failed: {e}") from e

    try:
        root = _strip_ns(ET.fromstring(resp.text))
    except ET.ParseError as e:
        raise QRZError(f"QRZ returned unparseable XML: {e}") from e

    session = root.find("Session")
    error_el = session.find("Error") if session is not None else None
    if error_el is not None and error_el.text:
        text = error_el.text.strip()
        lower = text.lower()
        if "session timeout" in lower or "invalid session key" in lower:
            raise QRZSessionExpired(text)
        if "not found" in lower:
            raise QRZNotFound(text)
        if "username" in lower or "password" in lower or "incorrect" in lower or "not authorized" in lower:
            raise QRZAuthError(text)
        raise QRZError(text)

    return root


def login(username: str, password: str) -> str:
    """Log in and return a fresh Session Key. Raises QRZAuthError on bad
    credentials or an account without XML API access."""
    root = _get({"username": username, "password": password, "agent": AGENT})
    session = root.find("Session")
    key_el = session.find("Key") if session is not None else None
    if key_el is None or not key_el.text:
        raise QRZAuthError("QRZ login did not return a session key")
    return key_el.text.strip()


def lookup(session_key: str, callsign: str) -> dict:
    """Look up a callsign using an existing session key.

    Returns {"name": str, "grid": str, "state": str} (any of which may be
    empty — QRZ's own record for that call may simply be missing a field,
    e.g. non-US calls rarely have `state` populated). Raises QRZSessionExpired
    if the key needs refreshing, or QRZNotFound if the call isn't in QRZ's
    database (a definitive, cacheable result — not an error to retry)."""
    root = _get({"s": session_key, "callsign": callsign})
    cs = root.find("Callsign")
    if cs is None:
        raise QRZNotFound(f"No Callsign record for {callsign}")

    def _text(tag: str) -> str:
        el = cs.find(tag)
        return (el.text or "").strip() if el is not None and el.text else ""

    fname = _text("fname")
    lname = _text("name")
    name = " ".join(p for p in (fname, lname) if p)
    grid = _text("grid")
    state = _text("state") or _text("county")

    return {"name": name, "grid": grid, "state": state}


class QRZClient:
    """Stateful wrapper the background worker owns exclusively — see
    web/server.py's QRZ worker thread. Not thread-safe by design: it's only
    ever touched from that single thread, so no internal locking."""

    def __init__(self):
        self._username: Optional[str] = None
        self._password: Optional[str] = None
        self._session_key: Optional[str] = None

    def set_credentials(self, username: Optional[str], password: Optional[str]):
        self._username = username
        self._password = password
        self._session_key = None  # force re-login on next lookup

    def has_credentials(self) -> bool:
        return bool(self._username and self._password)

    def lookup_one(self, callsign: str) -> Optional[dict]:
        """Returns {"found": True, "name":..., "grid":..., "state":...} on a
        match, {"found": False} if QRZ has no record (cacheable), or None on
        a transient failure (network error, expired-and-re-login-also-failed,
        etc.) that the caller should NOT cache and should retry later."""
        if not self.has_credentials():
            return None

        if not self._session_key:
            try:
                self._session_key = login(self._username, self._password)
            except QRZAuthError:
                log.warning("QRZ login failed for %s — check credentials", self._username)
                return None
            except QRZError as e:
                log.info("QRZ login failed (transient?): %s", e)
                return None

        try:
            result = lookup(self._session_key, callsign)
            return {"found": True, **result}
        except QRZNotFound:
            return {"found": False}
        except QRZSessionExpired:
            try:
                self._session_key = login(self._username, self._password)
                result = lookup(self._session_key, callsign)
                return {"found": True, **result}
            except QRZNotFound:
                return {"found": False}
            except QRZError as e:
                log.info("QRZ lookup failed for %s after re-login: %s", callsign, e)
                return None
        except QRZError as e:
            log.info("QRZ lookup failed for %s: %s", callsign, e)
            return None
