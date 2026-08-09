from __future__ import annotations

from unittest.mock import Mock

from bisheng.common.constants.enums.knowledge_parse_priority import KnowledgeParsePriority
from bisheng.knowledge.domain.schemas.knowledge_parse_queue_schema import (
    KnowledgeParseAttemptKind,
    KnowledgeParseQueueTicket,
)
from bisheng.knowledge.domain.services.knowledge_parse_processing_lease import (
    KnowledgeParseProcessingLease,
)


def _ticket() -> KnowledgeParseQueueTicket:
    return KnowledgeParseQueueTicket(
        queue_ticket_id="logical-ticket",
        tenant_id=1,
        knowledge_id=10,
        file_id=1,
        attempt_kind=KnowledgeParseAttemptKind.INITIAL,
        priority=KnowledgeParsePriority.MEDIUM,
    )


def test_each_delivery_uses_an_independent_attempt_and_cleans_only_itself() -> None:
    repository = Mock()
    repository.begin_attempt_sync.return_value = True
    first = KnowledgeParseProcessingLease(
        ticket=_ticket(),
        repository=repository,
        attempt_id="attempt-first",
    )
    second = KnowledgeParseProcessingLease(
        ticket=_ticket(),
        repository=repository,
        attempt_id="attempt-second",
    )

    first.start()
    second.start()
    first.close()

    assert repository.begin_attempt_sync.call_count == 2
    repository.finish_attempt_sync.assert_called_once_with(
        ticket=first.ticket,
        attempt_id="attempt-first",
    )
    second.close()
    assert repository.finish_attempt_sync.call_count == 2
    assert repository.finish_attempt_sync.call_args.kwargs["attempt_id"] == "attempt-second"


def test_index_start_failure_does_not_change_task_business_flow() -> None:
    repository = Mock()
    repository.begin_attempt_sync.side_effect = RuntimeError("redis unavailable")
    lease = KnowledgeParseProcessingLease(
        ticket=_ticket(),
        repository=repository,
        attempt_id="attempt-failed-index",
    )

    lease.start()
    lease.close()

    repository.finish_attempt_sync.assert_not_called()
