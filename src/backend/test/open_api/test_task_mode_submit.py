"""F073 submit-time checks (spec AC-02, AC-08, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-18).

All I/O is patched at the seams ``OpenTaskModeService`` calls; what is under
test is the order of the checks, the error each one raises, and that a
rejected submission writes nothing.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode import open_api as errors
from bisheng.common.errcode.knowledge import KnowledgeNotExistError, KnowledgeTypeNotSupportedError
from bisheng.common.errcode.knowledge_space import SpaceNotFoundError, SpacePermissionDeniedError
from bisheng.common.errcode.permission import PermissionDeniedError, PermissionServiceUnavailableError
from bisheng.open_api.domain.services import task_mode_service
from bisheng.open_api.domain.services.task_mode_service import OpenTaskModeService
from test.open_api.task_mode_support import LOGIN_USER, _knowledge, _req, delegated_principal, sa_principal


async def test_accepted_submission_is_queued_with_api_meta(task_mode_seams):
    result = await OpenTaskModeService.submit(sa_principal(), _req(skills=["contract-review"]), LOGIN_USER)

    assert result.task_id == "svid-1"
    assert result.status.value == "queued"
    assert result.queue_position == 3
    data, kwargs = task_mode_seams.submitted
    assert data.task_mode is True
    assert kwargs["strict_enqueue"] is True
    assert kwargs["telemetry_source"] == "api"
    assert kwargs["session_name"] == "Review the attached contracts"
    assert kwargs["api_meta"]["channel"] == "open_api_v2"
    assert kwargs["api_meta"]["identity_mode"] == "S"
    assert kwargs["session_subject"].subject_type == "service_account"


async def test_delegated_user_without_task_mode_is_forbidden(task_mode_seams):
    task_mode_seams.menu_ok = False
    with pytest.raises(errors.OpenApiTaskModeForbiddenError):
        await OpenTaskModeService.submit(delegated_principal(), _req(), LOGIN_USER)
    assert task_mode_seams.submitted is None


async def test_self_identity_skips_the_menu_check(task_mode_seams):
    task_mode_seams.menu_ok = False
    await OpenTaskModeService.submit(sa_principal(), _req(), LOGIN_USER)
    assert task_mode_seams.submitted is not None


@pytest.mark.parametrize(
    "model_state,model_id",
    [
        (SimpleNamespace(model_type="llm", online=False), "7"),
        (SimpleNamespace(model_type="embedding", online=True), "7"),
        (None, "7"),
        (SimpleNamespace(model_type="llm", online=True), "8"),  # not in the workbench list
    ],
)
async def test_unavailable_model_is_rejected(task_mode_seams, model_state, model_id):
    task_mode_seams.model = model_state
    with pytest.raises(errors.OpenApiModelUnavailableError):
        await OpenTaskModeService.submit(sa_principal(), _req(model=model_id), LOGIN_USER)
    assert task_mode_seams.submitted is None


async def test_every_unavailable_skill_is_listed(task_mode_seams):
    with pytest.raises(errors.OpenApiTaskSkillUnavailableError) as exc_info:
        await OpenTaskModeService.submit(sa_principal(), _req(skills=["contract-review", "gone", "off"]), LOGIN_USER)
    assert exc_info.value.to_dict()["data"]["unavailable"] == ["gone", "off"]
    assert task_mode_seams.submitted is None


async def test_unavailable_tool_is_rejected(task_mode_seams):
    with pytest.raises(errors.OpenApiToolUnavailableError):
        await OpenTaskModeService.submit(sa_principal(), _req(tools=[{"id": 99, "tool_key": "shell"}]), LOGIN_USER)


async def test_available_tool_passes(task_mode_seams):
    await OpenTaskModeService.submit(sa_principal(), _req(tools=[{"id": 30, "tool_key": "web_search"}]), LOGIN_USER)
    assert task_mode_seams.submitted is not None


@pytest.mark.parametrize(
    "knowledge,allowed,error",
    [
        ({}, set(), KnowledgeNotExistError),
        ({5: _knowledge(5, 1)}, {5}, KnowledgeTypeNotSupportedError),  # QA library
        ({5: _knowledge(5, 2)}, {5}, KnowledgeTypeNotSupportedError),  # retired personal KB
        ({5: _knowledge(5, 3)}, {5}, KnowledgeTypeNotSupportedError),  # a space passed as a library
        ({5: _knowledge(5, 0)}, set(), PermissionDeniedError),
    ],
)
async def test_knowledge_library_checks(task_mode_seams, knowledge, allowed, error):
    task_mode_seams.knowledge = knowledge
    task_mode_seams.use_allowed = allowed
    with pytest.raises(error):
        await OpenTaskModeService.submit(sa_principal(), _req(knowledge_ids=[5]), LOGIN_USER)
    assert task_mode_seams.submitted is None


async def test_owner_permission_does_not_leak_to_the_service_account(task_mode_seams):
    """The resource owner may use library 5; the service account may not.

    The check goes through the permission actor (the service account), so the
    owner's grant must not let the submission through.
    """
    task_mode_seams.knowledge = {5: _knowledge(5, 0)}
    task_mode_seams.use_allowed = set()  # what the SA actor resolves to
    with pytest.raises(PermissionDeniedError):
        await OpenTaskModeService.submit(sa_principal(), _req(knowledge_ids=[5]), LOGIN_USER)


@pytest.mark.parametrize(
    "knowledge,visible,error",
    [
        ({}, set(), SpaceNotFoundError),
        ({6: _knowledge(6, 0)}, {6}, SpaceNotFoundError),
        ({6: _knowledge(6, 3)}, set(), SpacePermissionDeniedError),
    ],
)
async def test_knowledge_space_checks(task_mode_seams, knowledge, visible, error):
    task_mode_seams.knowledge = knowledge
    task_mode_seams.visible = visible
    with pytest.raises(error):
        await OpenTaskModeService.submit(sa_principal(), _req(knowledge_space_ids=[6]), LOGIN_USER)


async def test_readable_knowledge_passes(task_mode_seams):
    task_mode_seams.knowledge = {5: _knowledge(5, 0), 6: _knowledge(6, 3)}
    task_mode_seams.use_allowed = {5}
    task_mode_seams.visible = {6}
    await OpenTaskModeService.submit(sa_principal(), _req(knowledge_ids=[5], knowledge_space_ids=[6]), LOGIN_USER)
    data, _ = task_mode_seams.submitted
    assert data.use_knowledge_base.organization_knowledge_ids == [5]
    assert data.use_knowledge_base.knowledge_space_ids == [6]


async def test_permission_engine_failure_is_not_swallowed(task_mode_seams):
    task_mode_seams.knowledge = {5: _knowledge(5, 0)}
    task_mode_seams.permission_error = PermissionServiceUnavailableError()
    with pytest.raises(PermissionServiceUnavailableError):
        await OpenTaskModeService.submit(sa_principal(), _req(knowledge_ids=[5]), LOGIN_USER)


@pytest.mark.parametrize("field", ["text", "instructions"])
async def test_content_safety_blocks_before_anything_is_written(task_mode_seams, field):
    task_mode_seams.blocked = SimpleNamespace(word="forbidden", auto_reply="Please rephrase")
    overrides = {"text": "do the forbidden thing"} if field == "text" else {"instructions": "forbidden context"}
    with pytest.raises(errors.OpenApiContentBlockedError) as exc_info:
        await OpenTaskModeService.submit(sa_principal(), _req(**overrides), LOGIN_USER)
    assert exc_info.value.to_dict()["data"]["auto_reply"] == "Please rephrase"
    assert task_mode_seams.submitted is None


async def test_foreign_attachment_is_rejected_before_any_other_check(task_mode_seams, monkeypatch):
    from bisheng.common.errcode.http_error import NotFoundError

    monkeypatch.setattr(
        task_mode_service.TempUploadService,
        "assert_owned_references",
        AsyncMock(side_effect=NotFoundError()),
    )
    task_mode_seams.model = None  # would fail later; the attachment must fail first
    with pytest.raises(NotFoundError):
        await OpenTaskModeService.submit(
            sa_principal(),
            _req(files=[{"file_path": "http://x/tmp/open-api/other/a.pdf", "file_name": "a.pdf"}]),
            LOGIN_USER,
        )
