"""Real answer route, credential validation, execution identity and permission gate."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.services.knowledge_space_answer_service import KnowledgeSpaceAnswerService
from bisheng.open_api.api.dependencies import verify_open_api_access
from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers
from bisheng.open_api.domain.context import get_current_open_api_principal
from bisheng.open_api.domain.models.api_credential import ApiCredential
from bisheng.open_api.domain.services.credential_service import hash_token
from bisheng.open_endpoints.api import knowledge_answer_dependencies as di
from bisheng.open_endpoints.api.endpoints.knowledge_answer import router
from bisheng.permission.application.identity import get_current_permission_actor
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from test.permission.test_data_scope_enforcement import FakeResolver, StubFGA
from test.permission.test_data_scope_enforcement import service as permission_service

BODY = {"query": "question", "knowledge_base_ids": [1], "model_id": 3}


def test_answer_is_registered_in_production_router_and_scope():
    from bisheng.api.router import router_rpc
    from bisheng.open_api.domain.scopes import OPEN_API_SCOPES

    assert any(
        route.path == "/api/v2/filelib/answer" and "POST" in getattr(route, "methods", set())
        for route in router_rpc.routes
    )
    scope = next(item for item in OPEN_API_SCOPES if item.code == "knowledge:read")
    assert ("POST", "/api/v2/filelib/answer") in scope.endpoints
    assert any(item.dependency is verify_open_api_access for item in router_rpc.dependencies)


@pytest.fixture()
def wired(monkeypatch, fake_redis):
    import bisheng.open_api.domain.services.credential_validator as validator
    import bisheng.permission.domain.services.data_scope as data_scope
    from bisheng.open_api.domain.repositories.owner_repository import OwnerRepository
    from bisheng.open_api.domain.repositories.tenant_setting_repository import TenantSettingRepository

    key = "bs-sak-" + "a" * 43
    credential = ApiCredential(
        id=7,
        tenant_id=1,
        subject_kind="service_account",
        subject_id=31,
        name="test",
        key_prefix="bs-sak-",
        last4="aaaa",
        token_hash=hash_token(key),
        scopes=["knowledge:read"],
    )
    lookup = AsyncMock(return_value=credential)
    monkeypatch.setattr(validator.CredentialRepository, "get_by_hash", lookup)
    monkeypatch.setattr(
        validator.ServiceAccountRepository,
        "get",
        AsyncMock(
            return_value=SimpleNamespace(id=31, name="indexer", tenant_id=1, resource_owner_user_id=12, is_enabled=True)
        ),
    )
    monkeypatch.setattr(validator.CredentialService, "touch_last_used", AsyncMock())
    monkeypatch.setattr(
        OwnerRepository,
        "get_active_natural_person",
        AsyncMock(return_value=SimpleNamespace(user_id=5, tenant_id=1, user_name="holder")),
    )
    monkeypatch.setattr(
        TenantSettingRepository,
        "get",
        AsyncMock(return_value=SimpleNamespace(pat_enabled=True, pat_ttl_days=30, pat_data_scope="personal_only")),
    )
    monkeypatch.setattr("bisheng.open_api.api.dependencies.settings.open_api.pat_enabled", True)
    monkeypatch.setattr("bisheng.utils.http_middleware._check_is_global_super", AsyncMock(return_value=False))
    monkeypatch.setattr("bisheng.permission.application.relation_api.is_tenant_admin", AsyncMock(return_value=False))
    monkeypatch.setattr(data_scope, "_resolver", FakeResolver({"knowledge_space": {"1"}}))
    fga = StubFGA()
    observed = []
    retrieval = SimpleNamespace(aretrieve_chunks=AsyncMock(return_value=[]))
    model = SimpleNamespace(prepare=AsyncMock(return_value=SimpleNamespace(ainvoke=AsyncMock())))

    async def check_permission(space_id):
        actor = get_current_permission_actor()
        observed.append(actor)
        target = VerifiedPermissionTarget.from_business_service(
            tenant_id=1,
            resource_type="knowledge_space",
            resource_id=str(space_id),
            resource_version=0,
            context_version="ctx",
        )
        assert await permission_service(fga).check_action(actor, target, "use")

    retrieval._require_space_view_permission = check_permission
    repository = SimpleNamespace(find_by_id=AsyncMock(return_value=SimpleNamespace(type=KnowledgeTypeEnum.SPACE.value)))
    factory = Mock()

    async def answer_service():
        principal = get_current_open_api_principal()
        factory(principal)
        return KnowledgeSpaceAnswerService(
            login_user=SimpleNamespace(user_id=principal.resource_owner_user_id),
            knowledge_repository=repository,
            retrieval_service=retrieval,
            model_service=model,
        )

    app = FastAPI()
    register_open_api_exception_handlers(app)
    app.include_router(router, prefix="/api/v2", dependencies=[Depends(verify_open_api_access)])
    app.dependency_overrides[di.get_knowledge_answer_service] = answer_service
    return SimpleNamespace(
        app=app,
        key=key,
        credential=credential,
        lookup=lookup,
        factory=factory,
        observed=observed,
        retrieval=retrieval,
        model=model,
        fga=fga,
    )


async def post(wired, *, authenticated=True, body=None):
    headers = {"Authorization": f"Bearer {wired.key}"} if authenticated else {}
    async with AsyncClient(transport=ASGITransport(app=wired.app), base_url="http://test") as client:
        return await client.post("/api/v2/filelib/answer", json=BODY if body is None else body, headers=headers)


async def test_new_answer_missing_key_fails_before_any_work(wired):
    response = await post(wired, authenticated=False)
    assert (response.status_code, response.json()["status_code"]) == (401, 26001)
    wired.lookup.assert_not_awaited()
    wired.factory.assert_not_called()
    wired.model.prepare.assert_not_awaited()


async def test_new_answer_insufficient_scope_fails_before_any_work(wired):
    wired.credential.scopes = []
    response = await post(wired)
    assert (response.status_code, response.json()["status_code"]) == (403, 26003)
    wired.lookup.assert_awaited_once_with(hash_token(wired.key))
    wired.factory.assert_not_called()
    wired.retrieval.aretrieve_chunks.assert_not_awaited()


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"query": " "}, 400),
        ({"user_id": 7}, 26019),
        ({"stream": True}, 400),
        ({"filters": {"knowledge_base_filters": [{"knowledge_base_id": 2}]}}, 400),
    ],
)
async def test_valid_key_invalid_answer_request_uses_shared_v2_error(wired, changes, code):
    response = await post(wired, body={**BODY, **changes})
    assert response.status_code == 400
    assert response.json()["status_code"] == code
    assert not wired.observed
    wired.retrieval.aretrieve_chunks.assert_not_awaited()
    wired.model.prepare.assert_not_awaited()


async def test_service_account_actor_reaches_real_answer_and_fga(wired):
    response = await post(wired)
    assert response.status_code == 200
    assert response.json()["data"]["has_context"] is False
    actor = wired.observed[0]
    assert actor.fga_subject == "service_account:31"
    assert not actor.super_admin
    assert actor.data_scope == "all_visible"
    assert wired.fga.calls[0][1]["user"] == "service_account:31"
    wired.model.prepare.assert_awaited_once_with(model_id=3, user_id=12)
    assert get_current_permission_actor() is None


async def test_delegated_key_without_header_cannot_reach_answer(wired):
    wired.credential.scopes = ["knowledge:read", "delegate"]
    response = await post(wired)
    assert (response.status_code, response.json()["status_code"]) == (400, 26016)
    wired.factory.assert_not_called()
    wired.model.prepare.assert_not_awaited()


@pytest.mark.parametrize("space,expected_status", [(1, 200), (2, 403)])
async def test_pat_narrowed_actor_enforced_inside_real_answer(wired, space, expected_status):
    wired.key = "bs-pat-" + "a" * 43
    wired.credential.subject_kind = "natural_person"
    wired.credential.subject_id = 5
    wired.credential.token_hash = hash_token(wired.key)
    wired.credential.key_prefix = "bs-pat-"
    response = await post(wired, body={**BODY, "knowledge_base_ids": [space]})
    assert response.status_code == expected_status
    actor = wired.observed[0]
    assert actor.fga_subject == "user:5"
    assert actor.data_scope == "personal_only"
    if space == 2:
        assert response.json()["status_code"] == 26044
        wired.model.prepare.assert_not_awaited()
        wired.retrieval.aretrieve_chunks.assert_not_awaited()
        assert not wired.fga.calls
    else:
        wired.model.prepare.assert_awaited_once_with(model_id=3, user_id=5)
        assert wired.fga.calls


async def test_actual_dependency_factory_preserves_operator_and_session(monkeypatch):
    request = Request({"type": "http"})
    session = object()
    operator = SimpleNamespace(user_id=12, is_global_super=False, user_role=[])
    monkeypatch.setattr(di, "get_open_api_operator_async", AsyncMock(return_value=operator))
    retrieval = SimpleNamespace()
    retrieval_factory = Mock(return_value=retrieval)
    version_repository = object()
    version_factory = Mock(return_value=version_repository)
    knowledge_repository = object()
    repository_factory = Mock(return_value=knowledge_repository)
    monkeypatch.setattr(di, "KnowledgeSpaceChatService", retrieval_factory)
    monkeypatch.setattr(di, "KnowledgeDocumentVersionRepositoryImpl", version_factory)
    monkeypatch.setattr(di, "KnowledgeRepositoryImpl", repository_factory)
    result = await di.get_knowledge_answer_service(request, session)
    assert isinstance(result, KnowledgeSpaceAnswerService)
    assert result.login_user is operator and not result.login_user.is_global_super
    assert result.knowledge_repository is knowledge_repository
    assert result.retrieval_service is retrieval
    assert retrieval.version_repo is version_repository
    retrieval_factory.assert_called_once_with(request=request, login_user=operator)
    version_factory.assert_called_once_with(session)
    repository_factory.assert_called_once_with(session)
