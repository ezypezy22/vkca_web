"""
plugins/loader.py
─────────────────
Dynamic plugin discovery and registration.

At import time this module scans every .py file in the plugins/ directory,
imports it, and registers any class that is a concrete subclass of
ContestPlugin.  GenericPlugin (the catch-all fallback) is always appended
last regardless of filesystem order.

Usage (in the main script):
    from plugins.loader import plugin_for, get_all_plugins

    plugin = plugin_for("VKSHIRES2025")   # → VKShiresPlugin instance
    all_p  = get_all_plugins()            # → ordered list of plugin instances
"""

from __future__ import annotations

import importlib
import inspect
import logging
import os
import re
import sys
import threading
from typing import List, Optional

from plugins.base import ContestPlugin
from plugins.generic import GenericPlugin

log = logging.getLogger(__name__)

# USA/Canadian amateur-radio callsign prefixes, per ITU allocation — used
# only as plugin_for()'s tiebreaker when more than one plugin's identify()
# claims the same contest name (see ContestPlugin.matches_station() and
# issue #40). Not a general-purpose callsign classifier; deliberately
# narrow to this one disambiguation use.
_W_VE_CALL_RE = re.compile(r'^(A[A-L]|K|N|W|V[AEOXY]|C[FGHIJKYZ]|X[JKLMNO])[0-9]')

# Alaska/Hawaii/Pacific-territory US callsigns (KL7, KH6, etc.) participate
# in ARRL DX as DX stations, not W/VE, despite the K/N/W/A prefix — called
# out explicitly in arrl_dx_dx.py's own docstring. Checked before
# _W_VE_CALL_RE so these correctly stay classified as DX-station calls.
# Known gap: arrl_dx_dx.py's docstring also calls out CY9 (St Paul Is.) and
# CYØ (Sable Is.) as DX-station entities despite the CY prefix — these
# aren't excluded here (they're rare, DXpedition-only entities), so a
# logging station using one of those calls would still be misclassified as
# W/VE. Worth revisiting if it ever comes up in practice.
_US_DX_TERRITORY_RE = re.compile(r'^[AKNW][HL][0-9]')


def looks_like_w_ve_call(call: Optional[str]) -> bool:
    """True if `call` is shaped like a mainland USA or Canadian
    amateur-radio callsign (Alaska/Hawaii/Pacific-territory US calls are
    deliberately excluded — see _US_DX_TERRITORY_RE)."""
    c = (call or "").strip().upper()
    if not c or _US_DX_TERRITORY_RE.match(c):
        return False
    return _W_VE_CALL_RE.match(c) is not None

# Ordered list of registered plugin instances (GenericPlugin always last).
_PLUGINS: List[ContestPlugin] = []
_loaded = False
_discover_lock = threading.Lock()


def _discover() -> None:
    """
    Scan the plugins/ package directory and import every module.
    Any concrete ContestPlugin subclass found is instantiated and added to
    _PLUGINS.  Modules that fail to import are logged and skipped gracefully.
    GenericPlugin is excluded from auto-discovery and appended manually at
    the end so it always acts as the last-resort fallback.
    """
    global _loaded
    if _loaded:
        return
    # web/server.py runs most /api/* handlers on the default thread pool, so
    # a page load firing several of those concurrently could have multiple
    # threads reach this function before any of them has set _loaded — the
    # plain check-then-set above isn't atomic. The lock makes only the first
    # caller actually populate _PLUGINS; every other concurrent caller just
    # waits and then sees _loaded already True (see issue #39).
    with _discover_lock:
        if _loaded:
            return

        pkg_dir = os.path.dirname(__file__)
        skip = {"__init__", "base", "loader", "generic"}

        seen_classes: set = set()

        for fname in sorted(os.listdir(pkg_dir)):
            if not fname.endswith(".py"):
                continue
            mod_name = fname[:-3]
            if mod_name in skip:
                continue

            full_name = f"plugins.{mod_name}"
            try:
                mod = importlib.import_module(full_name)
            except Exception as exc:
                log.warning("Plugin loader: could not import %s — %s", full_name, exc)
                continue

            for _name, obj in inspect.getmembers(mod, inspect.isclass):
                if (
                    obj is not ContestPlugin
                    and obj is not GenericPlugin
                    and issubclass(obj, ContestPlugin)
                    and not inspect.isabstract(obj)
                    and obj not in seen_classes
                ):
                    seen_classes.add(obj)
                    try:
                        _PLUGINS.append(obj())
                        log.debug("Plugin loader: registered %s from %s", obj.__name__, full_name)
                    except Exception as exc:
                        log.warning("Plugin loader: could not instantiate %s — %s", obj.__name__, exc)

        # GenericPlugin is always last — it matches every contest name.
        _PLUGINS.append(GenericPlugin())

        # Self-check: every plugin's own display_name should round-trip back
        # to itself through plugin_for(). This is the exact property that
        # broke ~5 times this project's history (a plugin's identify() not
        # broad enough to match its own display_name, or another plugin's
        # identify() greedily stealing it first by sorting earlier) — each
        # one only ever discovered by a user hitting a wrong-contest bug
        # live. Checking it here turns that into a loud, immediate warning
        # at startup instead (see issue #37).
        for p in _PLUGINS:
            if isinstance(p, GenericPlugin):
                continue
            got = _plugin_for_locked(p.display_name)
            if type(got) is not type(p):
                log.warning(
                    "Plugin loader: %s's own display_name %r round-trips to %s "
                    "instead — check identify() for an overlap/gap",
                    type(p).__name__, p.display_name, type(got).__name__,
                )

        _loaded = True


def get_all_plugins() -> List[ContestPlugin]:
    """Return the ordered list of registered plugin instances."""
    _discover()
    return list(_PLUGINS)


def _plugin_for_locked(contest_name: str, my_call: Optional[str] = None) -> ContestPlugin:
    """Shared identify() scan, used by both plugin_for() and _discover()'s
    own round-trip self-check (which runs while _discover_lock is already
    held, so it can't call plugin_for() itself without deadlocking).

    Collects every non-GenericPlugin plugin whose identify() claims
    contest_name — usually just one, but occasionally more than one (ARRL
    DX's near-identical DX-station/W/VE-station plugins both recognise the
    same raw N1MM ContestName values — see issue #40). GenericPlugin is
    excluded from this collection specifically because its own identify()
    matches every contest name unconditionally (it's the catch-all
    fallback) — including it here would make it "win" the tiebreak against
    any specific plugin whenever matches_station(my_call) can't confirm the
    specific plugin (e.g. my_call is unknown), which defeats the whole
    point of falling back to a specific plugin. When there's more than one
    specific-plugin match, matches_station(my_call) breaks the tie; if that
    still leaves zero or more than one candidate, the first identify()-match
    wins, same as before this disambiguation existed. GenericPlugin is only
    ever returned when no specific plugin matches at all."""
    matches = []
    for p in _PLUGINS:
        if isinstance(p, GenericPlugin):
            continue
        try:
            if p.identify(contest_name):
                matches.append(p)
        except Exception:
            log.warning("Plugin loader: %s.identify(%r) raised", type(p).__name__,
                        contest_name, exc_info=True)
    if not matches:
        return GenericPlugin()
    if len(matches) > 1:
        preferred = [p for p in matches if p.matches_station(my_call)]
        if len(preferred) == 1:
            return preferred[0]
    return matches[0]


def plugin_for(contest_name: str, my_call: Optional[str] = None) -> ContestPlugin:
    """Return the registered plugin that claims this contest name. `my_call`
    (the logging station's own callsign) is optional and only used to break
    a tie when more than one plugin claims the same contest_name — pass it
    whenever it's available (see issue #40)."""
    _discover()
    return _plugin_for_locked(contest_name, my_call)
