"""Rejecting a permission target must say why — in the log, not the response.

19003 covers seven different causes with one sentence, "Invalid resource type or
ID". A knowledge space stranded at status=FAILED therefore read exactly like a
mistyped id, and finding the real cause meant querying the database by hand.

The response stays uniform on purpose: `permission_error_response` flattens every
rejection so a missing resource and one in another tenant remain
indistinguishable. The reason goes to the server log instead.
"""

from __future__ import annotations

import logging

import pytest

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.knowledge.domain.services import knowledge_permission_service as module
from bisheng.knowledge.domain.services.knowledge_permission_service import (
    KnowledgeContainerPermissionRecord,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor

ACTOR = PermissionActor(user_id=7, current_tenant_id=1)


def _record(**overrides) -> KnowledgeContainerPermissionRecord:
    fields = {
        "tenant_id": 1,
        "resource_type": "knowledge_space",
        "resource_id": "4149",
        "status": "PUBLISHED",
        "kind": "SPACE",
        "owner_user_id": 3,
        "permission_version": 0,
        "context_version": "v1",
    }
    fields.update(overrides)
    return KnowledgeContainerPermissionRecord(**fields)


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        (None, "NOT_FOUND"),
        (_record(kind="NORMAL"), "KIND_MISMATCH:NORMAL"),
        (_record(status="FAILED"), "STATUS_NOT_USABLE:FAILED"),
        (_record(status="REBUILDING"), "STATUS_NOT_USABLE:REBUILDING"),
        (_record(tenant_id=99), "TENANT_MISMATCH"),
        (_record(resource_id="9999"), "IDENTITY_MISMATCH"),
    ],
)
def test_each_cause_is_named(record, expected) -> None:
    reason = module._container_rejection(
        record,
        ACTOR,
        "knowledge_space",
        "4149",
        allowed_statuses={"PUBLISHED"},
    )
    assert reason == expected


def test_a_usable_container_is_not_rejected() -> None:
    assert (
        module._container_rejection(
            _record(),
            ACTOR,
            "knowledge_space",
            "4149",
            allowed_statuses={"PUBLISHED"},
        )
        is None
    )


def test_a_super_admin_crosses_tenants() -> None:
    assert (
        module._container_rejection(
            _record(tenant_id=99),
            PermissionActor(user_id=1, current_tenant_id=1, super_admin=True),
            "knowledge_space",
            "4149",
            allowed_statuses={"PUBLISHED"},
        )
        is None
    )


def test_the_reason_is_logged_and_kept_out_of_the_error(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        error = module._reject_container("STATUS_NOT_USABLE:FAILED", "knowledge_space", "4149")

    assert isinstance(error, PermissionInvalidResourceError)
    assert "STATUS_NOT_USABLE:FAILED" in caplog.text
    assert "knowledge_space:4149" in caplog.text
    # The caller still sees the single opaque business message.
    assert "STATUS_NOT_USABLE" not in error.Msg
