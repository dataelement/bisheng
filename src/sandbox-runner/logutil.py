"""Stdlib logging for the isolation-environment runner. Must not import bisheng."""

from __future__ import annotations

import logging
import os

LOGGER_NAME = "sandbox"
_FORMAT = "%(asctime)s %(levelname)s [sandbox] %(message)s"


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def configure(level: str | None = None) -> logging.Logger:
    raw = (level or os.environ.get("SANDBOX_LOG_LEVEL") or "INFO").upper()
    numeric = getattr(logging, raw, logging.INFO)
    logger = get_logger()
    logger.setLevel(numeric)
    if not any(isinstance(handler, logging.StreamHandler) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(handler)
    logger.propagate = False
    return logger
