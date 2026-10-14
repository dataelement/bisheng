from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from bisheng.approval.api.dependencies import get_knowledge_space_service
from bisheng.approval.api.endpoints.shougang_approval import get_file_publish_last_target
from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateDecision
from bisheng.approval.domain.schemas.shougang_approval_schema import ShougangFilePublishSubmitReq
from bisheng.approval.domain.services.shougang_approval_service import ShougangApprovalService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.knowledge.domain.models.knowledge import KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileStatus
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.services.knowledge_publish_target_preference_service import (
    KnowledgePublishTargetPreferenceService,
)
from test.approval.test_shougang_approval_service import (
    _login_user,
    _patch_file_publish_submit_dependencies,
)
from test.knowledge.test_publish_target_preference import preference_db as _shared_preference_db

preference_db = _shared_preference_db


def patch_resources(monkeypatch, *, hidden=False, folder_state="valid"):
    login = _login_user(user_id=7)
    spaces = {
        10: SimpleNamespace(
            id=10, name="个人库", type=KnowledgeTypeEnum.SPACE.value, state=KnowledgeState.PUBLISHED.value, tenant_id=1
        ),
        20: SimpleNamespace(
            id=20, name="科室库", type=KnowledgeTypeEnum.SPACE.value, state=KnowledgeState.PUBLISHED.value, tenant_id=1
        ),
    }
    files = {
        100: SimpleNamespace(
            id=100,
            knowledge_id=10,
            file_type=FileType.FILE.value,
            status=KnowledgeFileStatus.SUCCESS.value,
            entry_type="manager",
        ),
        300: SimpleNamespace(
            id=300,
            knowledge_id=21 if folder_state == "moved" else 20,
            file_type=FileType.DIR.value,
            file_level_path="/200",
            level=1,
            deleted_at="deleted" if folder_state == "deleted" else None,
        ),
    }
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.KnowledgeDao.aquery_by_id",
        AsyncMock(side_effect=spaces.get),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.KnowledgeFileDao.query_by_id",
        AsyncMock(side_effect=files.get),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.KnowledgeSpaceScopeDao.aget_by_space_id",
        AsyncMock(
            side_effect=lambda space_id: SimpleNamespace(
                level=KnowledgeSpaceLevelEnum.PERSONAL if space_id == 10 else KnowledgeSpaceLevelEnum.TEAM_KS
            ),
        ),
    )

    async def check(resource_type, resource_id, permission, **kwargs):
        if hidden and resource_id == 20 and permission == "view_space":
            raise SpacePermissionDeniedError()

    return login, SimpleNamespace(login_user=login, _require_permission_id=AsyncMock(side_effect=check))


async def test_http_reads_current_account_and_restores_path_without_client_identity(preference_db, monkeypatch):
    login, spaces = patch_resources(monkeypatch)
    service = KnowledgePublishTargetPreferenceService()
    await service.save(user_id=7, source_level="personal", target_space_id=20, target_folder_id=300)
    await service.save(user_id=8, source_level="personal", target_space_id=999, target_folder_id=None)
    app = FastAPI()
    app.add_api_route("/last-target", get_file_publish_last_target, methods=["GET"])
    app.dependency_overrides[UserPayload.get_login_user] = lambda: login
    app.dependency_overrides[get_knowledge_space_service] = lambda: spaces
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/last-target", params={"source_space_id": 10, "source_file_id": 100, "user_id": 8})
    assert response.status_code == 200
    assert response.json()["data"] == {
        "target_space_id": 20,
        "target_folder_id": 300,
        "folder_path": [200, 300],
        "fallback_reason": None,
    }


@pytest.mark.parametrize(
    "hidden,folder_state,expected",
    [
        (True, "valid", (None, "target_unavailable")),
        (False, "deleted", (20, "folder_unavailable")),
        (False, "moved", (20, "folder_unavailable")),
    ],
)
async def test_unavailable_target_does_not_expose_path(preference_db, monkeypatch, hidden, folder_state, expected):
    login, spaces = patch_resources(monkeypatch, hidden=hidden, folder_state=folder_state)
    await KnowledgePublishTargetPreferenceService().save(
        user_id=7, source_level="personal", target_space_id=20, target_folder_id=300
    )
    response = await ShougangApprovalService().get_file_publish_last_target(
        source_space_id=10,
        source_file_id=100,
        login_user=login,
        space_service=spaces,
    )
    assert (response.target_space_id, response.fallback_reason) == expected
    assert response.target_folder_id is None and response.folder_path == []


async def test_source_permission_denial_stops_before_reading_preference(monkeypatch):
    login, spaces = patch_resources(monkeypatch)
    spaces._require_permission_id.side_effect = SpacePermissionDeniedError()
    preferences = SimpleNamespace(get=AsyncMock())
    service = ShougangApprovalService(publish_target_preference_service=preferences)
    with pytest.raises(SpacePermissionDeniedError):
        await service.get_file_publish_last_target(
            source_space_id=10, source_file_id=100, login_user=login, space_service=spaces
        )
    preferences.get.assert_not_awaited()


async def test_preference_read_failure_is_optional(monkeypatch):
    login, spaces = patch_resources(monkeypatch)
    service = ShougangApprovalService(
        publish_target_preference_service=SimpleNamespace(get=AsyncMock(side_effect=RuntimeError("offline")))
    )
    result = await service.get_file_publish_last_target(
        source_space_id=10, source_file_id=100, login_user=login, space_service=spaces
    )
    assert result.target_space_id is None and result.fallback_reason == "preference_unavailable"


@pytest.mark.parametrize(
    "decision,save_error",
    [
        (ApprovalGateDecision.PENDING, False),
        (ApprovalGateDecision.PASS, False),
        (ApprovalGateDecision.EXCEPTION, False),
        (ApprovalGateDecision.PENDING, True),
    ],
)
async def test_save_only_accepted_submission_without_changing_success(monkeypatch, decision, save_error):
    preferences = SimpleNamespace(save=AsyncMock(side_effect=RuntimeError("offline") if save_error else None))
    service = ShougangApprovalService(publish_target_preference_service=preferences)
    _patch_file_publish_submit_dependencies(monkeypatch, service)
    monkeypatch.setattr(service, "_ensure_file_publish_not_in_pending_approval", AsyncMock())
    monkeypatch.setattr(service, "_ensure_publish_target_content_not_duplicate", AsyncMock())
    monkeypatch.setattr(
        service,
        "_request_or_create_config_exception",
        AsyncMock(
            return_value=SimpleNamespace(
                decision=decision,
                instance_id=101,
                task_ids=[],
                model_dump=lambda: {"decision": decision.value, "instance_id": 101},
            )
        ),
    )
    result = await service.submit_file_publish(
        req=ShougangFilePublishSubmitReq(source_space_id=10, source_file_id=100, target_space_id=20),
        login_user=_login_user(user_id=7),
    )
    assert result["decision"] == decision.value
    if decision == ApprovalGateDecision.EXCEPTION:
        preferences.save.assert_not_awaited()
    else:
        preferences.save.assert_awaited_once_with(
            user_id=7, source_level=KnowledgeSpaceLevelEnum.TEAM, target_space_id=20, target_folder_id=None
        )
    assert result.get("target_preference_saved") is (False if save_error else None)
