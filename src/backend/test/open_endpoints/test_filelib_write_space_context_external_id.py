"""Regression: external_id on write path keeps FilelibUserContextService scope during dependency build (F114)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Depends, FastAPI
from starlette.testclient import TestClient

from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.context.tenant import get_visible_tenant_ids, is_tenant_filter_bypassed
from bisheng.developer_token.api.dependencies import get_optional_developer_token_principal
from bisheng.developer_token.domain.schemas import DeveloperTokenPrincipal
from bisheng.open_endpoints.api.dependencies import (
    FilelibWriteSpaceContext,
    get_filelib_user_context_service,
    get_filelib_write_space_context,
)
from bisheng.open_endpoints.domain.services.filelib_user_context_service import FilelibUserContextService
from bisheng.open_endpoints.domain.utils import get_default_operator_async


def _binding_user() -> UserPayload:
    return UserPayload(
        user_id=7,
        user_name="bound",
        user_role=[2],
        tenant_id=1,
        token_version=0,
        is_global_super=False,
    )


def _principal() -> DeveloperTokenPrincipal:
    u = _binding_user()
    return DeveloperTokenPrincipal(
        token_id=19,
        token_name="t",
        tenant_id=1,
        user=u,
        knowledge_uploader_user_id=99,
    )


class _UserRepository:
    async def list_active_by_external_id(self, external_id: str) -> list[object]:
        return [
            SimpleNamespace(
                user_id=8,
                user_name="external",
                token_version=0,
                delete=0,
            )
        ]


@pytest.fixture
def captured_build_context(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    captured: dict[str, object] = {}

    async def fake_init_login_user(
        cls,
        user_id: int,
        user_name: str,
        tenant_id: int | None = None,
        token_version: int = 0,
    ):
        return UserPayload(
            user_id=user_id,
            user_name=user_name,
            user_role=[2],
            tenant_id=int(tenant_id or 1),
            token_version=token_version,
            is_global_super=False,
        )

    monkeypatch.setattr(
        "bisheng.open_endpoints.domain.services.filelib_user_context_service.UserPayload.init_login_user",
        classmethod(fake_init_login_user),
    )

    def build_probe(*, request, user, session, storage):
        captured["visible_ids"] = get_visible_tenant_ids()
        captured["tenant_bypass"] = is_tenant_filter_bypassed()
        return MagicMock()

    monkeypatch.setattr(
        "bisheng.open_endpoints.api.dependencies.build_filelib_space_query_service",
        build_probe,
    )
    monkeypatch.setattr(
        "bisheng.open_endpoints.api.dependencies.get_minio_storage",
        AsyncMock(return_value=MagicMock()),
    )
    return captured


def test_external_id_write_dependency_sees_global_visibility_during_query_build(
    captured_build_context: dict[str, object],
) -> None:
    """When external_id resolves, ``use_user`` must stay entered while ``FilelibSpaceCommandService`` is built."""
    app = FastAPI()
    ctx_service = FilelibUserContextService(_UserRepository())  # type: ignore[arg-type]

    app.dependency_overrides[get_optional_developer_token_principal] = _principal
    app.dependency_overrides[get_filelib_user_context_service] = lambda: ctx_service

    async def _fake_db_session():
        yield MagicMock()

    app.dependency_overrides[get_db_session] = _fake_db_session

    async def _fake_default_operator():
        return _binding_user()

    app.dependency_overrides[get_default_operator_async] = _fake_default_operator

    @app.get("/probe")
    async def _probe(
        ctx: FilelibWriteSpaceContext = Depends(get_filelib_write_space_context),
    ) -> dict[str, bool]:
        assert ctx.command is not None
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/probe", params={"external_id": "EMP001"})

    assert response.status_code == 200
    assert captured_build_context.get("tenant_bypass") is True
    assert captured_build_context.get("visible_ids") is None
