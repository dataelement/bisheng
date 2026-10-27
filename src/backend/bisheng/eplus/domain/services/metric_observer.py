"""Publish ephemeral metric snapshots only after their business transaction commits."""

from contextlib import asynccontextmanager
from datetime import datetime

from loguru import logger

from bisheng.eplus.domain.schemas.metric import METRIC_SNAPSHOTS_KEY, TerminalMetricSnapshot


def notify_metric(observer, snapshot):
    if observer is None:
        return
    try:
        observer(snapshot)
    except Exception as exc:
        # Optional observation cannot change the committed business result.
        logger.debug("E+ metric observer failed error_type={}", type(exc).__name__)


@asynccontextmanager
async def terminal_metric_transaction(session, observer):
    try:
        async with session.begin():
            yield
    except BaseException:
        session.info.pop(METRIC_SNAPSHOTS_KEY, None)
        raise
    else:
        for snapshot in session.info.pop(METRIC_SNAPSHOTS_KEY, ()):
            notify_metric(observer, snapshot)


def notify_duplicate_metric(observer, message):
    if observer is None:
        return
    try:
        notify_metric(
            observer, TerminalMetricSnapshot.from_message(message, duplicate=True, finished_at=datetime.now())
        )
    except Exception as exc:
        # Invalid optional observation data must not change callback deduplication.
        logger.debug("E+ duplicate metric skipped error_type={}", type(exc).__name__)
