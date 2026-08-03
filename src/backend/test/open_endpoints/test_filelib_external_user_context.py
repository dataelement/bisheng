from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.context.tenant import (
    get_visible_tenant_ids,
    is_tenant_filter_bypassed,
    set_visible_tenant_ids,
    visible_tenant_ids,
)
from bisheng.developer_token.api.dependencies import get_developer_token_principal
from bisheng.developer_token.domain.schemas import DeveloperTokenPrincipal
from bisheng.open_endpoints.api.dependencies import (
    get_filelib_knowledge_document_repository,
    get_filelib_knowledge_document_version_repository,
    get_filelib_user_context_service,
)
from bisheng.open_endpoints.api.endpoints import filelib as filelib_endpoint
from bisheng.open_endpoints.domain.schemas.filelib import RetrieveReq
from bisheng.open_endpoints.domain.services import filelib_user_context_service
from bisheng.open_endpoints.domain.services.filelib_user_context_service import (
    FilelibUserContextService,
)


class _UserRepository:
    def __init__(self, candidates: list[object]) -> None:
        self.candidates = candidates
        self.external_ids: list[str] = []
        self.lookup_contexts: list[tuple[object, bool]] = []

    async def list_active_by_external_id(self, external_id: str) -> list[object]:
        self.external_ids.append(external_id)
        self.lookup_contexts.append((get_visible_tenant_ids(), is_tenant_filter_bypassed()))
        return self.candidates


class _UnauthorizedErrorStub:
    @classmethod
    def http_exception(cls) -> HTTPException:
        return HTTPException(status_code=403, detail="No permission to operate")


def _user_payload(
    user_id: int,
    *,
    is_global_super: bool = False,
) -> UserPayload:
    return UserPayload(
        user_id=user_id,
        user_name=f"user-{user_id}",
        user_role=[2],
        tenant_id=1,
        token_version=0,
        is_global_super=is_global_super,
    )


def _principal(user: UserPayload) -> DeveloperTokenPrincipal:
    return DeveloperTokenPrincipal(token_id=19, tenant_id=1, user=user)


async def test_missing_external_id_reuses_token_user_without_context_change() -> None:
    token_user = _user_payload(7)
    repository = _UserRepository([])
    service = FilelibUserContextService(repository)
    visible_token = set_visible_tenant_ids(frozenset({1}))
    try:
        async with service.use_user(_principal(token_user), None) as resolved:
            assert resolved is token_user
            assert get_visible_tenant_ids() == frozenset({1})
            assert not is_tenant_filter_bypassed()
    finally:
        visible_tenant_ids.reset(visible_token)

    assert repository.external_ids == []


@pytest.mark.parametrize("is_global_super", [False, True], ids=["ordinary", "global-super"])
async def test_unique_external_user_gets_full_identity_and_global_context(
    monkeypatch,
    is_global_super: bool,
) -> None:
    candidate = SimpleNamespace(
        user_id=8,
        user_name="target-user",
        token_version=3,
        delete=0,
    )
    target_user = _user_payload(8, is_global_super=is_global_super)
    init_login_user = AsyncMock(return_value=target_user)
    monkeypatch.setattr(UserPayload, "init_login_user", init_login_user)
    repository = _UserRepository([candidate])
    service = FilelibUserContextService(repository)
    visible_token = set_visible_tenant_ids(frozenset({1}))
    try:
        async with service.use_user(_principal(_user_payload(7)), " EMP001 ") as resolved:
            assert resolved is target_user
            assert resolved.is_global_super is is_global_super
            assert get_visible_tenant_ids() is None
            assert is_tenant_filter_bypassed()
    finally:
        visible_tenant_ids.reset(visible_token)

    assert repository.external_ids == ["EMP001"]
    assert repository.lookup_contexts == [(None, True)]
    assert get_visible_tenant_ids() is None
    assert not is_tenant_filter_bypassed()
    init_login_user.assert_awaited_once_with(
        user_id=8,
        user_name="target-user",
        tenant_id=1,
        token_version=3,
    )


@pytest.mark.parametrize(
    "candidates",
    [
        [],
        [SimpleNamespace(user_id=8), SimpleNamespace(user_id=9)],
    ],
    ids=["missing-or-disabled", "duplicate"],
)
async def test_external_user_resolution_fails_closed_with_same_403(
    candidates: list[object],
    caplog,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        filelib_user_context_service,
        "UnAuthorizedError",
        _UnauthorizedErrorStub,
    )
    service = FilelibUserContextService(_UserRepository(candidates))

    with pytest.raises(HTTPException) as exc_info:
        async with service.use_user(_principal(_user_payload(7)), "SECRET-EMP-ID"):
            pytest.fail("invalid external user must not enter business scope")

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "No permission to operate"
    assert "SECRET-EMP-ID" not in caplog.text
    assert not is_tenant_filter_bypassed()


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_external_user_context_is_restored_after_business_failure(
    monkeypatch,
    error_type: type[BaseException],
) -> None:
    candidate = SimpleNamespace(
        user_id=8,
        user_name="target-user",
        token_version=0,
        delete=0,
    )
    monkeypatch.setattr(
        UserPayload,
        "init_login_user",
        AsyncMock(return_value=_user_payload(8)),
    )
    service = FilelibUserContextService(_UserRepository([candidate]))
    visible_token = set_visible_tenant_ids(frozenset({5}))
    try:
        with pytest.raises(error_type):
            async with service.use_user(_principal(_user_payload(7)), "EMP001"):
                assert get_visible_tenant_ids() is None
                assert is_tenant_filter_bypassed()
                raise error_type()

        assert get_visible_tenant_ids() == frozenset({5})
        assert not is_tenant_filter_bypassed()
    finally:
        visible_tenant_ids.reset(visible_token)


def test_retrieve_request_accepts_missing_and_trimmed_external_id() -> None:
    without_external_id = RetrieveReq(query="q", knowledge_base_ids=[1])
    with_external_id = RetrieveReq(
        query="q",
        knowledge_base_ids=[1],
        external_id=" EMP001 ",
    )

    assert without_external_id.external_id is None
    assert with_external_id.external_id == "EMP001"


@pytest.mark.parametrize(
    "external_id",
    ["", "   ", "x" * 256],
    ids=["empty", "whitespace", "oversized"],
)
def test_retrieve_request_rejects_invalid_external_id(external_id: str) -> None:
    with pytest.raises(ValidationError):
        RetrieveReq(
            query="q",
            knowledge_base_ids=[1],
            external_id=external_id,
        )


def test_openapi_contract_exposes_external_id_on_four_routes() -> None:
    app = FastAPI()
    app.include_router(filelib_endpoint.router, prefix="/api/v2")
    openapi = app.openapi()

    for path in (
        "/api/v2/filelib/",
        "/api/v2/filelib/file/list",
        "/api/v2/filelib/file/detail",
    ):
        parameter_names = {parameter["name"] for parameter in openapi["paths"][path]["get"]["parameters"]}
        assert "external_id" in parameter_names

    retrieve_schema_ref = openapi["paths"]["/api/v2/filelib/retrieve"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    retrieve_schema_name = retrieve_schema_ref.rsplit("/", 1)[-1]
    retrieve_properties = openapi["components"]["schemas"][retrieve_schema_name]["properties"]
    assert "external_id" in retrieve_properties


async def test_retrieve_uses_external_user_for_complete_business_call(monkeypatch) -> None:
    principal = _principal(_user_payload(7))
    target_user = _user_payload(8, is_global_super=True)
    context_events: list[tuple[str, object]] = []

    @asynccontextmanager
    async def use_user(received_principal, external_id):
        context_events.append(("enter", (received_principal, external_id)))
        yield target_user
        context_events.append(("exit", target_user))

    user_context_service = SimpleNamespace(use_user=use_user)
    chat_service = SimpleNamespace(aretrieve_chunks=AsyncMock(return_value=[]))
    build_service = MagicMock(return_value=chat_service)
    monkeypatch.setattr(
        filelib_endpoint,
        "build_knowledge_space_chat_service_for_openapi",
        build_service,
    )
    monkeypatch.setattr(
        filelib_endpoint.settings,
        "aget_shougang_conf",
        AsyncMock(return_value=SimpleNamespace(portal_base_url="https://portal.example.com")),
    )
    request = MagicMock()
    version_repo = MagicMock()
    doc_repo = MagicMock()

    response = await filelib_endpoint.retrieve_chunks(
        request=request,
        req=RetrieveReq(
            query="permission-scoped query",
            knowledge_base_ids=[118],
            external_id="EMP001",
        ),
        principal=principal,
        user_context_service=user_context_service,
        version_repo=version_repo,
        doc_repo=doc_repo,
    )

    assert context_events == [
        ("enter", (principal, "EMP001")),
        ("exit", target_user),
    ]
    build_service.assert_called_once_with(
        request=request,
        request_user=target_user,
        version_repo=version_repo,
        doc_repo=doc_repo,
    )
    chat_service.aretrieve_chunks.assert_awaited_once()
    assert response.status_code == 200
    assert response.data.total == 0


@pytest.mark.parametrize(
    ("method", "path", "request_kwargs"),
    [
        ("get", "/api/v2/filelib/", {"params": {"external_id": ""}}),
        (
            "post",
            "/api/v2/filelib/retrieve",
            {
                "json": {
                    "query": "q",
                    "knowledge_base_ids": [1],
                    "external_id": "",
                }
            },
        ),
    ],
    ids=["get", "retrieve"],
)
def test_invalid_token_precedes_invalid_external_id(method, path, request_kwargs) -> None:
    async def reject_token():
        raise HTTPException(status_code=401, detail="token-invalid")
        yield

    user_repository = _UserRepository([])
    context_service = FilelibUserContextService(user_repository)
    app = FastAPI()
    app.include_router(filelib_endpoint.router, prefix="/api/v2")
    app.dependency_overrides[get_developer_token_principal] = reject_token
    app.dependency_overrides[get_filelib_user_context_service] = lambda: context_service
    app.dependency_overrides[get_filelib_knowledge_document_version_repository] = MagicMock
    app.dependency_overrides[get_filelib_knowledge_document_repository] = MagicMock

    with TestClient(app) as client:
        response = getattr(client, method)(path, **request_kwargs)

    assert response.status_code == 401
    assert response.json() == {"detail": "token-invalid"}
    assert user_repository.external_ids == []


@pytest.mark.parametrize(
    ("method", "path", "request_kwargs"),
    [
        ("get", "/api/v2/filelib/", {"params": {"external_id": "   "}}),
        (
            "post",
            "/api/v2/filelib/retrieve",
            {
                "json": {
                    "query": "q",
                    "knowledge_base_ids": [1],
                    "external_id": "   ",
                }
            },
        ),
    ],
    ids=["get", "retrieve"],
)
def test_invalid_external_id_returns_422_without_user_lookup(
    method,
    path,
    request_kwargs,
) -> None:
    principal = _principal(_user_payload(7))

    async def accept_token():
        yield principal

    user_repository = _UserRepository([])
    context_service = FilelibUserContextService(user_repository)
    app = FastAPI()
    app.include_router(filelib_endpoint.router, prefix="/api/v2")
    app.dependency_overrides[get_developer_token_principal] = accept_token
    app.dependency_overrides[get_filelib_user_context_service] = lambda: context_service
    app.dependency_overrides[get_filelib_knowledge_document_version_repository] = MagicMock
    app.dependency_overrides[get_filelib_knowledge_document_repository] = MagicMock

    with TestClient(app) as client:
        response = getattr(client, method)(path, **request_kwargs)

    assert response.status_code == 422
    assert user_repository.external_ids == []
