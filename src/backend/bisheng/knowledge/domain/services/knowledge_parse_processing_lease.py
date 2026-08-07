from __future__ import annotations

import functools
import logging
import threading
import uuid
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from typing import Any

from celery import current_task

from bisheng.common.constants.enums.knowledge_parse_priority import KnowledgeParsePriority
from bisheng.knowledge.domain.repositories.implementations.knowledge_parse_queue_redis_repository import (
    KnowledgeParseQueueRedisRepository,
)
from bisheng.knowledge.domain.schemas.knowledge_parse_queue_schema import (
    KnowledgeParseQueueTicket,
    KnowledgeParseStage,
    KnowledgeParseTicketState,
)

logger = logging.getLogger(__name__)


class KnowledgeParseProcessingLease:
    HEARTBEAT_SECONDS = 30

    def __init__(
        self,
        *,
        ticket: KnowledgeParseQueueTicket,
        repository: KnowledgeParseQueueRedisRepository | None = None,
        attempt_id: str | None = None,
    ):
        self.ticket = ticket
        self.repository = repository or KnowledgeParseQueueRedisRepository()
        self.attempt_id = attempt_id or str(uuid.uuid4())
        self._stop_event = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._started = False

    def start(self) -> None:
        try:
            self._started = self.repository.begin_attempt_sync(
                ticket=self.ticket,
                attempt_id=self.attempt_id,
            )
            if not self._started:
                return
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat,
                name=f"knowledge-parse-lease-{self.attempt_id[:8]}",
                daemon=True,
            )
            self._heartbeat_thread.start()
        except Exception:
            logger.exception(
                "knowledge parse processing lease start failed ticket_id=%s attempt_id=%s file_id=%s",
                self.ticket.queue_ticket_id,
                self.attempt_id,
                self.ticket.file_id,
            )
            self._started = False

    def close(self) -> None:
        self._stop_event.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=self.HEARTBEAT_SECONDS + 1)
        if not self._started:
            return
        try:
            self.repository.finish_attempt_sync(
                ticket=self.ticket,
                attempt_id=self.attempt_id,
            )
        except Exception:
            logger.exception(
                "knowledge parse processing lease finish failed ticket_id=%s attempt_id=%s file_id=%s",
                self.ticket.queue_ticket_id,
                self.attempt_id,
                self.ticket.file_id,
            )

    def _heartbeat(self) -> None:
        while not self._stop_event.wait(self.HEARTBEAT_SECONDS):
            try:
                if not self.repository.renew_attempt_sync(
                    ticket_id=self.ticket.queue_ticket_id,
                    attempt_id=self.attempt_id,
                ):
                    logger.warning(
                        "knowledge parse processing lease lost ticket_id=%s attempt_id=%s file_id=%s",
                        self.ticket.queue_ticket_id,
                        self.attempt_id,
                        self.ticket.file_id,
                    )
                    return
            except Exception:
                logger.exception(
                    "knowledge parse processing lease renew failed ticket_id=%s attempt_id=%s file_id=%s",
                    self.ticket.queue_ticket_id,
                    self.attempt_id,
                    self.ticket.file_id,
                )
                return


def _ticket_from_current_delivery(
    *,
    stage: KnowledgeParseStage,
    file_id: int,
) -> KnowledgeParseQueueTicket | None:
    request = getattr(current_task, "request", None)
    headers = getattr(request, "headers", None) or {}
    if not isinstance(headers, Mapping):
        return None
    ticket_header = headers.get("knowledge_parse_queue_ticket_id")
    if not isinstance(ticket_header, str) or not ticket_header:
        return None
    ticket_id = ticket_header
    try:
        return KnowledgeParseQueueTicket(
            queue_ticket_id=str(ticket_id),
            tenant_id=int(headers["tenant_id"]),
            knowledge_id=int(headers["knowledge_id"]),
            file_id=file_id,
            stage=stage,
            priority=KnowledgeParsePriority.parse(
                headers.get("knowledge_parse_priority"),
                default=KnowledgeParsePriority.MEDIUM,
            ),
            state=KnowledgeParseTicketState.PROCESSING,
        )
    except (KeyError, TypeError, ValueError):
        logger.warning(
            "knowledge parse delivery has incomplete queue metadata ticket_id=%s file_id=%s stage=%s",
            ticket_id,
            file_id,
            stage.value,
        )
        return None


@contextmanager
def processing_lease_for_current_delivery(*, stage: KnowledgeParseStage, file_id: int):
    ticket = _ticket_from_current_delivery(stage=stage, file_id=file_id)
    if ticket is None:
        yield
        return
    lease = KnowledgeParseProcessingLease(ticket=ticket)
    lease.start()
    try:
        yield
    finally:
        lease.close()


def track_knowledge_parse_delivery(stage: KnowledgeParseStage) -> Callable:
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapped(file_id: int, *args: Any, **kwargs: Any):
            with processing_lease_for_current_delivery(stage=stage, file_id=file_id):
                return func(file_id, *args, **kwargs)

        return wrapped

    return decorator
