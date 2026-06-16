"""Retry helpers for transient database write conflicts.

Concurrent writes to a hot row/table (e.g. ``message_session`` touched on every
chat turn) make DM raise transient conflicts that a *full rollback then retry*
resolves cleanly: the loser's transaction is already rolled back, so re-running
the single statement cannot double-apply. Surfacing these as 500s instead of
retrying is what broke the chat endpoint under concurrency.

Recognised transient conflicts:
  - DM  ``-6403`` Deadlock
  - DM  ``-7067`` Too many mvcc conflict
  - DM  ``-7184`` Object definition modified, version checking failed
  - MySQL ``1213`` Deadlock / ``1205`` Lock wait timeout

Only wrap operations whose transaction is atomic and side-effect-free on
rollback (a single ``INSERT``/``UPDATE`` + commit). Do not wrap multi-statement
units where an earlier statement may have already committed.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.exc import DBAPIError

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Substrings found in the wrapped DBAPI error for retryable transient conflicts.
_TRANSIENT_DB_ERROR_MARKERS = ("-6403", "-7067", "-7184", "1213", "1205")
_DEFAULT_ATTEMPTS = 4
_BASE_BACKOFF_SECONDS = 0.05


def is_transient_db_conflict(exc: BaseException) -> bool:
    """True if ``exc`` wraps a retryable transient DB write conflict."""
    if not isinstance(exc, DBAPIError):
        return False
    orig = getattr(exc, "orig", None)
    text = str(orig) if orig is not None else str(exc)
    return any(marker in text for marker in _TRANSIENT_DB_ERROR_MARKERS)


def _backoff_seconds(attempt: int) -> float:
    # Exponential backoff with jitter so colliding writers de-synchronise.
    return _BASE_BACKOFF_SECONDS * (2**attempt) + random.uniform(0, _BASE_BACKOFF_SECONDS)


def retry_on_transient_db_conflict(attempts: int = _DEFAULT_ATTEMPTS):
    """Decorator: retry a single-transaction DB op on transient DM/MySQL conflicts.

    Works on both async and sync callables. Non-transient errors propagate
    immediately; after the final attempt the original error is re-raised.
    """

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        if asyncio.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                for attempt in range(attempts):
                    try:
                        return await fn(*args, **kwargs)
                    except DBAPIError as exc:
                        if not is_transient_db_conflict(exc) or attempt == attempts - 1:
                            raise
                        logger.warning(
                            "transient DB conflict in %s (attempt %d/%d), retrying: %s",
                            fn.__name__,
                            attempt + 1,
                            attempts,
                            getattr(exc, "orig", exc),
                        )
                        await asyncio.sleep(_backoff_seconds(attempt))

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def sync_wrapper(*args, **kwargs):
            for attempt in range(attempts):
                try:
                    return fn(*args, **kwargs)
                except DBAPIError as exc:
                    if not is_transient_db_conflict(exc) or attempt == attempts - 1:
                        raise
                    logger.warning(
                        "transient DB conflict in %s (attempt %d/%d), retrying: %s",
                        fn.__name__,
                        attempt + 1,
                        attempts,
                        getattr(exc, "orig", exc),
                    )
                    time.sleep(_backoff_seconds(attempt))

        return sync_wrapper  # type: ignore[return-value]

    return decorator


# Re-exported for callers that need to retry an inline awaitable rather than a
# decorated method.
async def aretry_on_transient_db_conflict(
    make_coro: Callable[[], Awaitable[T]], *, attempts: int = _DEFAULT_ATTEMPTS, op: str = "db-op"
) -> T:
    for attempt in range(attempts):
        try:
            return await make_coro()
        except DBAPIError as exc:
            if not is_transient_db_conflict(exc) or attempt == attempts - 1:
                raise
            logger.warning(
                "transient DB conflict in %s (attempt %d/%d), retrying: %s",
                op,
                attempt + 1,
                attempts,
                getattr(exc, "orig", exc),
            )
            await asyncio.sleep(_backoff_seconds(attempt))
    raise AssertionError("unreachable")
