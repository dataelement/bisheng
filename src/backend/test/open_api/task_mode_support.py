"""Shared helpers for the F073 task-mode service tests.

The ``task_mode_seams`` fixture (in this directory's conftest) patches every
seam ``OpenTaskModeService`` calls; tests flip fields on the returned state.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException

from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.schemas.task_mode import OpenTaskSubmitReq
from bisheng.open_api.domain.services import task_mode_service
from bisheng.open_api.domain.services.task_mode_service import OpenTaskModeService
from bisheng.permission.application.identity import get_current_permission_actor
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.permission_action_service import PermissionActor

CONFIG = {
    "models": [{"id": "7", "name": "qwen"}],
    "tools": [{"id": 3, "children": [{"id": 30, "tool_key": "web_search"}]}],
}


def sa_principal() -> OpenApiPrincipal:
    return OpenApiPrincipal(
        credential_id=7,
        actor_kind="service_account",
        actor_id=31,
        actor_name="form-app",
        tenant_id=9,
        resource_owner_user_id=12,
        scopes=frozenset({"chat:invoke"}),
        authorization_subject_type="service_account",
        authorization_subject_id=31,
        effective_user_id=None,
        end_user_id="emp-1",
    )


def delegated_principal() -> OpenApiPrincipal:
    return sa_principal().model_copy(
        update={
            "mode": "D",
            "authorization_subject_type": "user",
            "authorization_subject_id": 55,
            "effective_user_id": 55,
            "resource_owner_user_id": 55,
            "on_behalf_of_user_id": 55,
            "end_user_id": None,
        }
    )


def _req(**overrides) -> OpenTaskSubmitReq:
    body = {
        "run_mode": "task",
        "execution": "async",
        "clientTimestamp": "2026-09-30T10:00:00",
        "text": "Review the attached contracts\nand list the risks",
        "model": "7",
    }
    body.update(overrides)
    return OpenTaskSubmitReq.model_validate(body)


def _knowledge(knowledge_id: int, knowledge_type: int):
    return SimpleNamespace(id=knowledge_id, type=knowledge_type, tenant_id=9)


def install_task_mode_seams(monkeypatch):
    state = SimpleNamespace(
        submitted=None,
        menu_ok=True,
        model=SimpleNamespace(model_type="llm", online=True),
        skills={"contract-review"},
        knowledge={},
        use_allowed=set(),
        visible=set(),
        blocked=None,
        permission_error=None,
        permission_calls=[],
        loaded_actor=None,
    )

    async def _menu(_user_id, _key):
        if not state.menu_ok:
            raise HTTPException(status_code=403)

    async def _model_info(_model_id):
        return state.model, (SimpleNamespace() if state.model else None)

    async def _enabled(_login_user):
        return [SimpleNamespace(name=n, display_name=n, description=None) for n in state.skills]

    async def _by_ids(ids):
        return [state.knowledge[i] for i in ids if i in state.knowledge]

    async def _batch_actions(_login_user, *, resource_type, resource_ids, actions):
        assert actions == ("visible",)
        state.permission_calls.append((resource_type, tuple(resource_ids), actions))
        if state.permission_error:
            raise state.permission_error
        # The historical fixture name denotes the original library's admission;
        # migrated IDs use the space namespace rather than borrowing that set.
        allowed = state.use_allowed if resource_type == "knowledge_library" else state.visible
        assert resource_type in {"knowledge_library", "knowledge_space"}
        return {str(i): frozenset({"visible"}) for i in resource_ids if int(i) in allowed}

    async def _batch_visible(_login_user, *, resource_type, resource_ids):
        assert resource_type == "knowledge_space"
        if state.permission_error:
            raise state.permission_error
        return {str(i): int(i) in state.visible for i in resource_ids}

    async def _actor(_login_user):
        return get_current_permission_actor() or PermissionActor(
            subject_type="service_account", subject_id=31, tenant_id=9
        )

    async def _loaded(*, rows, resource_type, actor):
        assert actor.tenant_id == 9
        assert all(row.tenant_id == 9 for row in rows)
        state.loaded_actor = actor
        state.permission_calls.append((resource_type, tuple(row.id for row in rows), ("visible",)))
        return tuple(
            VerifiedPermissionTarget.from_business_service(
                tenant_id=9,
                resource_type=resource_type,
                resource_id=str(row.id),
                resource_version=1,
                context_version="task-fixture",
            )
            for row in rows
        )

    async def _batch_loaded_visible(*, actor, targets):
        if state.permission_error:
            raise state.permission_error
        assert actor is state.loaded_actor
        return {
            (target.resource_type, target.resource_id): int(target.resource_id)
            in (state.use_allowed if target.resource_type == "knowledge_library" else state.visible)
            for target in targets
        }

    async def _submit(data, login_user, **kwargs):
        state.submitted = (data, kwargs)
        return SimpleNamespace(), SimpleNamespace(id="svid-1")

    monkeypatch.setattr("bisheng.common.dependencies.user_deps.UserPayload.assert_effective_web_menu_contains", _menu)
    monkeypatch.setattr("bisheng.llm.domain.llm.base.BishengBase.get_model_server_info", _model_info)
    monkeypatch.setattr(OpenTaskModeService, "enabled_skill_rows", staticmethod(_enabled))
    monkeypatch.setattr(task_mode_service.KnowledgeDao, "aget_list_by_ids", _by_ids)
    monkeypatch.setattr(task_mode_service, "get_current_tenant_id", lambda: 9, raising=False)
    monkeypatch.setattr(
        "bisheng.permission.application.business_authorization.batch_check_business_actions", _batch_actions
    )
    monkeypatch.setattr(
        "bisheng.permission.application.business_authorization.batch_check_business_visible", _batch_visible
    )
    monkeypatch.setattr("bisheng.permission.application.identity.resolve_permission_actor", _actor)
    monkeypatch.setattr(
        "bisheng.permission.application.access.get_f048_resource_adapter",
        AsyncMock(return_value=SimpleNamespace(resolve_permission_targets_from_rows=_loaded)),
    )
    monkeypatch.setattr(
        "bisheng.permission.application.business_authorization.batch_check_verified_business_visible",
        _batch_loaded_visible,
    )
    monkeypatch.setattr(task_mode_service.TempUploadService, "assert_owned_references", AsyncMock())
    monkeypatch.setattr(
        "bisheng.workstation.domain.services.workstation_service.WorkStationService.get_open_api_daily_config",
        AsyncMock(return_value=CONFIG),
    )
    monkeypatch.setattr(
        "bisheng.sensitive_word.domain.services.sensitive_word_policy_service."
        "SensitiveWordPolicyService.evaluate_workbench_user_text",
        lambda _tenant, text: state.blocked if state.blocked and state.blocked.word in text else None,
    )
    monkeypatch.setattr("bisheng.workstation.domain.services.content_safety.workbench_tenant_id", lambda _u: 9)
    monkeypatch.setattr("bisheng.workstation.domain.services.task_submit_service.submit_task_turn", _submit)
    monkeypatch.setattr(OpenTaskModeService, "_queue_position", staticmethod(AsyncMock(return_value=3)))
    return state


LOGIN_USER = SimpleNamespace(user_id=12, tenant_id=9)
