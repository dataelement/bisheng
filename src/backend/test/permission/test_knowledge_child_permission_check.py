from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.core.openfga.exceptions import FGAConnectionError
from bisheng.permission.api.endpoints.permission_check import router
from bisheng.permission.domain.services.fine_grained_permission_service import (
    FineGrainedPermissionService as Fine,
)
from bisheng.permission.domain.services.permission_service import PermissionService


@pytest.fixture
def permission_state():
    user = SimpleNamespace(user_id=7, tenant_id=1, is_admin=lambda: False)
    models = {name: {"id": name, "relation": name, "is_system": True} for name in ("editor", "viewer")}
    models["empty"] = {
        "id": "empty",
        "relation": "viewer",
        "permissions": [],
        "permissions_explicit": True,
        "is_system": False,
    }
    state = {
        "user": user,
        "models": models,
        "bindings": [],
        "lineage": [],
        "subjects": {"user:7", "user_group:8#member", "department:9#member"},
        "offline": False,
    }

    async def read_tuples(*, object):
        if state["offline"]:
            raise FGAConnectionError("offline")
        return [
            {
                "user": (
                    f"user:{b['subject_id']}"
                    if b["subject_type"] == "user"
                    else f"{b['subject_type']}:{b['subject_id']}#member"
                ),
                "relation": b["relation"],
                "object": object,
            }
            for b in state["bindings"]
            if object == f"{b['resource_type']}:{b['resource_id']}"
        ]

    with ExitStack() as stack:
        stack.enter_context(
            patch.object(
                PermissionService,
                "_get_fga",
                return_value=SimpleNamespace(read_tuples=AsyncMock(side_effect=read_tuples)),
            )
        )
        stack.enter_context(
            patch.object(PermissionService, "get_implicit_permission_level", AsyncMock(return_value=None))
        )
        stack.enter_context(patch.object(PermissionService, "get_permission_level", AsyncMock(return_value="can_edit")))
        for name, value in [
            ("get_relation_models_map", models),
            ("get_current_user_subject_strings", state["subjects"]),
            ("get_binding_department_paths", {}),
            ("get_current_user_department_paths", {}),
            ("_public_knowledge_space_viewer_permission_ids", set()),
        ]:
            stack.enter_context(patch.object(Fine, name, AsyncMock(return_value=value)))
        stack.enter_context(
            patch.object(
                Fine,
                "build_resource_lineage",
                AsyncMock(
                    side_effect=lambda *args, **kwargs: state["lineage"],
                ),
            )
        )
        stack.enter_context(
            patch(
                "bisheng.permission.domain.services.fine_grained_permission_service._get_bindings",
                AsyncMock(return_value=state["bindings"]),
            )
        )
        yield state


def grant(state, resource_type, resource_id, model, subject_type="user", subject_id=7):
    state["bindings"].append(
        {
            "resource_type": resource_type,
            "resource_id": str(resource_id),
            "subject_type": subject_type,
            "subject_id": subject_id,
            "relation": "editor" if model == "editor" else "viewer",
            "model_id": model,
        }
    )


@pytest.mark.parametrize("offline", [False, True], ids=["fga", "binding-fallback"])
@pytest.mark.parametrize(
    "object_type,permission_id",
    [
        ("folder", "upload_file_to_folder"),
        ("folder", "create_folder"),
        ("knowledge_file", "rename_file"),
    ],
)
async def test_child_viewer_overrides_space_editor(permission_state, offline, object_type, permission_id):
    state = permission_state
    state["offline"] = offline
    state["lineage"] = [(object_type, "200"), ("folder", "150"), ("knowledge_space", "100")]
    grant(state, "folder", 150, "viewer", "user_group", 8)
    grant(state, "knowledge_space", 100, "editor")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/permissions")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: state["user"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/permissions/check",
            json={
                "object_type": object_type,
                "object_id": "200",
                "relation": "can_edit",
                "permission_id": permission_id,
            },
        )
    assert response.json()["data"]["allowed"] is False


@pytest.mark.parametrize("child_model,expected", [(None, True), ("viewer", False), ("empty", False), ("editor", True)])
async def test_closest_grant_and_empty_model(permission_state, child_model, expected):
    state = permission_state
    state["lineage"] = [("folder", "200"), ("folder", "150"), ("knowledge_space", "100")]
    grant(state, "knowledge_space", 100, "editor")
    if child_model:
        grant(state, "folder", 150, "viewer", "department", 9)
        grant(state, "folder", 200, child_model)
    assert (
        await Fine.has_any_permission_async(
            state["user"],
            "folder",
            "200",
            ["upload_file_to_folder"],
        )
        is expected
    )


async def test_implicit_owner_and_other_resource_semantics_unchanged(permission_state):
    state = permission_state
    state["lineage"] = [("folder", "200"), ("knowledge_space", "100")]
    grant(state, "folder", 200, "viewer")
    with patch.object(PermissionService, "get_implicit_permission_level", AsyncMock(return_value="owner")):
        assert await Fine.has_any_permission_async(state["user"], "folder", "200", ["upload_file_to_folder"])
    with patch.object(Fine, "get_effective_permission_ids_async", AsyncMock(return_value={"view_app"})) as resolve:
        assert await Fine.has_any_permission_async(state["user"], "workflow", "200", ["view_app"])
        assert not resolve.await_args.kwargs


async def test_upload_still_denied_before_processing(permission_state):
    from test.test_knowledge_space_service import _load_service_class

    state = permission_state
    state["lineage"] = [("folder", "200"), ("knowledge_space", "100")]
    grant(state, "folder", 200, "viewer")
    grant(state, "knowledge_space", 100, "editor")
    service = _load_service_class()(None, state["user"])
    with ExitStack() as stack:
        for name, value in [
            ("_build_resource_lineage", state["lineage"]),
            ("_get_current_user_subject_strings", state["subjects"]),
            ("_get_relation_bindings", state["bindings"]),
            ("_get_binding_department_paths", {}),
            ("_get_relation_models_map", state["models"]),
            ("_membership_permission_ids", set()),
            ("_public_space_viewer_permission_ids", set()),
        ]:
            stack.enter_context(patch.object(service, name, AsyncMock(return_value=value)))
        with pytest.raises(SpacePermissionDeniedError):
            await service.add_file(100, ["/tmp/not-opened.txt"], parent_id=200)
