"""HTTP tests for concrete-action F048 permission decisions."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.permission import (
    InvalidCatalogActionError,
    PermissionFGAUnavailableError,
    PermissionInvalidResourceError,
)
from bisheng.permission.api.dependencies import get_permission_decision_api
from bisheng.permission.api.endpoints.decision import router
from bisheng.permission.application.resource_authorization import (
    PermissionDecisionApplication,
    ResourceAuthorizationRegistry,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget


class _BusinessResourcePort:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.error: Exception | None = None

    async def resolve_permission_target(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return VerifiedPermissionTarget.from_business_service(
            tenant_id=5,
            resource_type="knowledge_file",
            resource_id=kwargs["resource_id"],
            resource_version=7,
            parent_type="folder",
            parent_id="root",
            context_version="business-v7",
        )


class _PermissionCoordinator:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed
        self.error: Exception | None = None
        self.targets: list[VerifiedPermissionTarget] = []

    async def check_action(self, actor, target, action):
        self.targets.append(target)
        if self.error is not None:
            raise self.error
        return self.allowed


def _app(decision_api) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/permissions")
    app.dependency_overrides[get_permission_decision_api] = lambda: decision_api
    app.dependency_overrides[UserPayload.get_login_user] = lambda: UserPayload(
        user_id=7,
        user_name="member",
        user_role=[],
        tenant_id=5,
    )
    return app


def _decision(
    *,
    allowed: bool,
) -> tuple[
    PermissionDecisionApplication,
    _BusinessResourcePort,
    _PermissionCoordinator,
]:
    business = _BusinessResourcePort()
    coordinator = _PermissionCoordinator(allowed)
    registry = ResourceAuthorizationRegistry()
    registry.register("knowledge_file", business)
    return (
        PermissionDecisionApplication(
            resources=registry,
            permission=coordinator,
        ),
        business,
        coordinator,
    )


def test_concrete_action_check_returns_true_and_normal_false_as_200() -> None:
    for allowed in (True, False):
        decision, business, coordinator = _decision(allowed=allowed)
        with TestClient(_app(decision)) as client:
            response = client.post(
                "/api/v1/permissions/check",
                json={
                    "resource_type": "knowledge_file",
                    "resource_id": "file-1",
                    "action": "download",
                },
            )
        assert response.status_code == 200
        assert response.json()["data"] == {"allowed": allowed}
        assert business.calls[0]["action"] == "download"
        assert coordinator.targets[0].context_version == "business-v7"


def test_client_cannot_forge_verified_target_fields_or_legacy_aliases() -> None:
    decision, business, _ = _decision(allowed=True)
    forged_payloads = (
        {
            "resource_type": "knowledge_file",
            "resource_id": "file-1",
            "action": "download",
            "tenant_id": 99,
            "status": "ACTIVE",
            "parent_id": "other",
            "resource_version": 999,
        },
        {
            "object_type": "knowledge_file",
            "object_id": "file-1",
            "relation": "can_read",
            "permission_id": "download",
        },
    )
    with TestClient(_app(decision)) as client:
        responses = [client.post("/api/v1/permissions/check", json=payload).json() for payload in forged_payloads]

    assert [body["status_code"] for body in responses] == [25001, 25001]
    assert business.calls == []


def test_unknown_action_and_fga_unavailable_preserve_distinct_errors() -> None:
    decision, _, coordinator = _decision(allowed=True)
    with TestClient(_app(decision)) as client:
        coordinator.error = InvalidCatalogActionError()
        unknown = client.post(
            "/api/v1/permissions/check",
            json={
                "resource_type": "knowledge_file",
                "resource_id": "file-1",
                "action": "unknown",
            },
        ).json()
        coordinator.error = PermissionFGAUnavailableError()
        unavailable = client.post(
            "/api/v1/permissions/check",
            json={
                "resource_type": "knowledge_file",
                "resource_id": "file-1",
                "action": "download",
            },
        ).json()

    assert unknown["status_code"] == 25001
    assert unavailable["status_code"] == 19002


def test_missing_and_cross_tenant_targets_are_equally_hidden() -> None:
    decision, business, _ = _decision(allowed=True)
    with TestClient(_app(decision)) as client:
        bodies = []
        for message in ("missing", "tenant mismatch"):
            business.error = PermissionInvalidResourceError(msg=message)
            bodies.append(
                client.post(
                    "/api/v1/permissions/check",
                    json={
                        "resource_type": "knowledge_file",
                        "resource_id": "secret",
                        "action": "download",
                    },
                ).json()
            )

    assert [body["status_code"] for body in bodies] == [19003, 19003]
    assert [body["status_message"] for body in bodies] == [
        "Invalid resource type or ID",
        "Invalid resource type or ID",
    ]
