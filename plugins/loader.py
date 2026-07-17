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
import sys
import threading
from typing import List

from plugins.base import ContestPlugin
from plugins.generic import GenericPlugin

log = logging.getLogger(__name__)

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


def _plugin_for_locked(contest_name: str) -> ContestPlugin:
    """Shared identify() scan, used by both plugin_for() and _discover()'s
    own round-trip self-check (which runs while _discover_lock is already
    held, so it can't call plugin_for() itself without deadlocking)."""
    for p in _PLUGINS:
        try:
            if p.identify(contest_name):
                return p
        except Exception:
            log.warning("Plugin loader: %s.identify(%r) raised", type(p).__name__,
                        contest_name, exc_info=True)
    return GenericPlugin()


def plugin_for(contest_name: str) -> ContestPlugin:
    """Return the first registered plugin that claims this contest name."""
    _discover()
    return _plugin_for_locked(contest_name)
