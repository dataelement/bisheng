from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bisheng.approval.domain.models.approval_decision_outbox import ApprovalDecisionOutbox
from bisheng.approval.domain.models.approval_instance import ApprovalInstance
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KNOWLEDGE_SPACE_FILE_CHANGE_REQUEST_TYPE,
    KNOWLEDGE_SPACE_FILE_CHANGE_SCENARIO_CODE,
    KnowledgeSpaceFileChangeCleanupState,
    KnowledgeSpaceFileChangeExecutionState,
    KnowledgeSpaceFileChangeRequest,
)
from scripts.recover_approval_decision_events import Candidate, CandidateResult, _dispatch, _validate_candidate


@pytest.fixture(autouse=True)
def tenant_context():
    token = set_current_tenant_id(3)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


def _outbox() -> ApprovalDecisionOutbox:
    return ApprovalDecisionOutbox(
        id=71,
        tenant_id=3,
        instance_id=41,
        scenario_code=KNOWLEDGE_SPACE_FILE_CHANGE_SCENARIO_CODE,
        subscriber_key=KNOWLEDGE_SPACE_FILE_CHANGE_SCENARIO_CODE,
        business_request_type=KNOWLEDGE_SPACE_FILE_CHANGE_REQUEST_TYPE,
        business_request_id="51",
        business_key="knowledge-change:51",
        request_fingerprint="fingerprint",
        decision="rejected",
        decided_at=datetime(2026, 9, 11, 12, 0, 0),
        status="pending",
    )


def _instance() -> ApprovalInstance:
    return ApprovalInstance(
        id=41,
        tenant_id=3,
        scenario_code=KNOWLEDGE_SPACE_FILE_CHANGE_SCENARIO_CODE,
        scenario_name="Knowledge file change",
        handler_key=KNOWLEDGE_SPACE_FILE_CHANGE_SCENARIO_CODE,
        business_key="knowledge-change:51",
        business_resource_type=KNOWLEDGE_SPACE_FILE_CHANGE_REQUEST_TYPE,
        business_resource_id="51",
        business_name="file.pdf",
        applicant_user_id=9,
        applicant_user_name="user",
        status="rejected",
    )


def _request() -> KnowledgeSpaceFileChangeRequest:
    return KnowledgeSpaceFileChangeRequest(
        id=51,
        tenant_id=3,
        space_id=140,
        action="delete",
        resource_type="knowledge_file",
        resource_id=1176,
        applicant_user_id=9,
        business_key="knowledge-change:51",
        request_fingerprint="fingerprint",
        approval_instance_id=41,
        execution_state=KnowledgeSpaceFileChangeExecutionState.NOT_STARTED,
        cleanup_state=KnowledgeSpaceFileChangeCleanupState.NONE,
    )


def test_validate_candidate_accepts_unconsumed_terminal_decision_without_mutating_request():
    request = _request()

    assert _validate_candidate(_outbox(), _instance(), request) is None
    assert request.decision_event_id is None
    assert request.execution_state == KnowledgeSpaceFileChangeExecutionState.NOT_STARTED


def test_validate_candidate_rejects_non_terminal_instance_state():
    instance = _instance()
    instance.status = "pending"

    assert _validate_candidate(_outbox(), instance, _request()) == "approval_instance_not_terminal_decision:pending"


def test_validate_candidate_rejects_conflicting_recorded_event():
    request = _request()
    request.decision_event_id = 70
    request.execution_state = KnowledgeSpaceFileChangeExecutionState.CLOSED

    reason = _validate_candidate(_outbox(), _instance(), request)

    assert reason == "subscriber_validation_failed:file change event is old or out of order"


def test_dispatch_publishes_exact_event_on_default_queue():
    task = Mock()
    task.apply_async.return_value = SimpleNamespace(id="celery-task-1")
    result = CandidateResult(
        candidate=Candidate(
            tenant_id=3,
            event_id=71,
            instance_id=41,
            scenario_code=KNOWLEDGE_SPACE_FILE_CHANGE_SCENARIO_CODE,
            business_request_id="51",
            decision="rejected",
            outbox_status="pending",
            retry_count=0,
        ),
        result="eligible",
    )

    dispatched = _dispatch(result, task)

    task.apply_async.assert_called_once_with(args=[71], headers={"tenant_id": 3})
    assert dispatched.result == "dispatched"
    assert dispatched.task_id == "celery-task-1"
