"""Centralized logging helpers for the project.

This module provides thin wrappers around the standard `logging` module
and reads `SILENT_MODE` from `backend.config` at call time so that
logging calls are suppressed when the user requests silent mode.

Avoids heavy configuration at import time; it's safe to import from
other backend modules without creating import cycles.
"""
from __future__ import annotations

import logging
from typing import Any

_CONFIGURED = False


def _ensure_configured() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(format="%(message)s")
    # default level INFO; modules may adjust their own levels if needed
    logging.getLogger().setLevel(logging.INFO)
    _CONFIGURED = True


def _should_log(always: bool = False) -> bool:
    # Import config lazily to avoid import-time cycles
    try:
        from backend.config import SILENT_MODE

        return (not SILENT_MODE) or always
    except Exception:
        # If config cannot be imported (rare), default to logging
        return True


def info(msg: Any, *, always: bool = False) -> None:
    _ensure_configured()
    if _should_log(always):
        logging.getLogger("analiza_plex").info(str(msg))


def warning(msg: Any, *, always: bool = False) -> None:
    _ensure_configured()
    if _should_log(always):
        logging.getLogger("analiza_plex").warning(str(msg))


def error(msg: Any, *, always: bool = False) -> None:
    _ensure_configured()
    if _should_log(always):
        logging.getLogger("analiza_plex").error(str(msg))


def debug(msg: Any, *, always: bool = False) -> None:
    _ensure_configured()
    if _should_log(always):
        logging.getLogger("analiza_plex").debug(str(msg))


__all__ = ["info", "warning", "error", "debug"]
