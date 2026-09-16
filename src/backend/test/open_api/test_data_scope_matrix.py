"""F066 end-to-end wiring and the knowledge:read coverage registry.

覆盖 AC: AC-P23, AC-P24, AC-P26, AC-P27, AC-R2, AC-R3

The full behaviour matrix against real endpoints and real stores runs in the
feature's ``/e2e-test`` pass; here the registry keeps the endpoint set honest
(a new knowledge:read endpoint fails until classified) and a miniature app
proves the wire: gate policy → narrowed actor → permission-layer denial →
HTTP 403 with business code 26044 and an enumeration-safe payload.
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient

import bisheng.permission.domain.services.data_scope as data_scope_module
from bisheng.open_api.api.dependencies import verify_open_api_access
from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.schemas.personal_token import PersonalTokenSettingUpdate
from bisheng.open_api.domain.scopes import OPEN_API_SCOPES, open_api_scope
from bisheng.open_api.domain.services.tenant_setting_service import TenantSettingService
from bisheng.permission.application.identity import get_current_permission_actor
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from test.permission.test_data_scope_enforcement import (
    FakeResolver,
    StubFGA,
    service,
)

# ── AC-R3: every knowledge:read endpoint is classified for the narrowing ──
# raise      → single-resource gate raises 26044 on a non-owned target
# narrow     → list surface silently intersects with the holder-created set
# per-item   → mixed-parent items resolve False in batch checks (then 404 path)
# sa-only    → modes=("S",): personal tokens cannot reach it at all
# unreachable→ F052: the unified retrieval facade decides in **batch**, and a
#              batch check resolves a narrowed-out target to False instead of
#              raising (permission_action_service "design decision 2"). The
#              endpoint therefore answers 404 / 26321 — the same answer it gives
#              for a knowledge base that does not exist, which is what AC-11 /
#              AC-27 require: "exists but was not created by me" must not be
#              distinguishable from "does not exist".
KNOWLEDGE_READ_CLASSIFICATION = {
    ("GET", "/api/v2/filelib/"): "narrow",
    ("GET", "/api/v2/filelib/file/list"): "raise",
    ("POST", "/api/v2/filelib/retrieve"): "unreachable",
    ("GET", "/api/v2/filelib/download_statistic"): "sa-only",
    ("GET", "/api/v2/filelib/detail_qa"): "raise",
    ("POST", "/api/v2/filelib/query_qa"): "raise",
    ("GET", "/api/v2/citation/{citation_id}"): "per-item",
}


def test_every_knowledge_read_endpoint_is_classified_for_data_scope():
    registered = {
        endpoint for scope in OPEN_API_SCOPES if scope.code == "knowledge:read" for endpoint in scope.endpoints
    }
    assert registered, "knowledge:read scope disappeared from the registry"
    unclassified = registered - set(KNOWLEDGE_READ_CLASSIFICATION)
    stale = set(KNOWLEDGE_READ_CLASSIFICATION) - registered
    assert not unclassified, (
        f"new knowledge:read endpoints lack a data-scope classification: {sorted(unclassified)}. "
        "Decide raise/narrow/per-item behaviour, cover it, then extend this map."
    )
    assert not stale, f"classification map lists retired endpoints: {sorted(stale)}"


# ── the wire: policy → gate → actor → denial → 403/26044 ──


def _pat_principal() -> OpenApiPrincipal:
    return OpenApiPrincipal(
        credential_id=8,
        actor_kind="natural_person",
        actor_id=5,
        actor_name="holder",
        tenant_id=1,
        resource_owner_user_id=5,
        scopes=frozenset({"knowledge:read"}),
        authorization_subject_type="user",
        authorization_subject_id=5,
        effective_user_id=5,
    )


def build_app() -> FastAPI:
    app = FastAPI()
    register_open_api_exception_handlers(app)
    router = APIRouter(prefix="/api/v2", dependencies=[Depends(verify_open_api_access)])

    @router.get("/probe")
    @open_api_scope("knowledge:read")
    async def probe():
        actor = get_current_permission_actor()
        fga = StubFGA()
        target = VerifiedPermissionTarget.from_business_service(
            tenant_id=1,
            resource_type="knowledge_library",
            resource_id="999",
            resource_version=0,
            context_version="ctx",
        )
        allowed = await service(fga).check_action(actor, target, "use")
        return {"allowed": allowed, "data_scope": actor.data_scope, "super_admin": actor.super_admin}

    app.include_router(router)
    return app


@pytest.fixture
def gate(monkeypatch, open_api_db, fake_redis):
    async def validate(_authorization):
        return _pat_principal()

    async def not_super(_user_id):
        return False

    async def not_tenant_admin(_user_id, _tenant_id):
        return False

    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate)
    monkeypatch.setattr("bisheng.open_api.api.dependencies.settings.open_api.pat_enabled", True)
    monkeypatch.setattr("bisheng.utils.http_middleware._check_is_global_super", not_super)
    monkeypatch.setattr("bisheng.permission.application.relation_api.is_tenant_admin", not_tenant_admin)
    monkeypatch.setattr(
        data_scope_module,
        "_resolver",
        FakeResolver({"knowledge_library": {"7"}}),
    )
    return monkeypatch


async def _get(app: FastAPI, path: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path, headers={"Authorization": "Bearer opaque"})


async def test_default_scope_leaves_the_call_untouched(gate):
    await TenantSettingService.update(1, PersonalTokenSettingUpdate(pat_enabled=True, pat_ttl_days=30))

    response = await _get(build_app(), "/api/v2/probe")

    assert response.status_code == 200
    assert response.json() == {"allowed": True, "data_scope": "all_visible", "super_admin": False}


async def test_narrowing_takes_effect_on_the_next_call_and_is_reversible(gate):
    app = build_app()
    await TenantSettingService.update(1, PersonalTokenSettingUpdate(pat_enabled=True, pat_ttl_days=30))
    assert (await _get(app, "/api/v2/probe")).status_code == 200

    await TenantSettingService.update(
        1,
        PersonalTokenSettingUpdate(pat_enabled=True, pat_ttl_days=30, data_scope="personal_only"),
    )
    denied = await _get(app, "/api/v2/probe")
    assert denied.status_code == 403
    payload = denied.json()
    assert payload["status_code"] == 26044
    # Enumeration-safe: the payload names the policy, never the resource.
    assert payload["data"] == {"exception": payload["data"]["exception"], "scope": "personal_only"}
    assert "999" not in denied.text

    await TenantSettingService.update(
        1,
        PersonalTokenSettingUpdate(pat_enabled=True, pat_ttl_days=30, data_scope="all_visible"),
    )
    assert (await _get(app, "/api/v2/probe")).status_code == 200  # no re-issue needed


async def test_admin_holder_is_narrowed_exactly_the_same(gate, monkeypatch):
    async def is_super(_user_id):
        return True

    monkeypatch.setattr("bisheng.utils.http_middleware._check_is_global_super", is_super)
    await TenantSettingService.update(
        1,
        PersonalTokenSettingUpdate(pat_enabled=True, pat_ttl_days=30, data_scope="personal_only"),
    )

    denied = await _get(build_app(), "/api/v2/probe")

    assert denied.status_code == 403
    assert denied.json()["status_code"] == 26044  # super-admin shortcut never fired


async def test_narrowed_token_retrieve_is_unreachable_not_26044(gate, monkeypatch):
    """F052 D6 ①: narrowing a retrieve target must not be distinguishable.

    A batch check resolves a data-scope-narrowed target to ``False`` rather than
    raising (``permission_action_service.batch_check_actions``: "Batch checks
    carry filtering semantics: narrowed-out targets resolve to False instead of
    raising"), so the facade classes it as unreachable. That is the required
    outcome, not an accident of the implementation: a narrowed token that still
    got 26044 here could tell "this knowledge base exists but I did not create
    it" apart from "this knowledge base does not exist", which is exactly the
    enumeration channel AC-11 / AC-27 close.
    """

    from unittest.mock import MagicMock

    from bisheng.common.errcode.mcp_face import KnowledgeUnreachableError
    from bisheng.knowledge.domain.schemas.retrieval_facade import RetrievalIdentity, RetrievalRequest
    from bisheng.knowledge.domain.services.retrieval_facade_service import RetrievalFacadeService
    from bisheng.open_api.api.exception_handlers import open_api_http_status

    identity = RetrievalIdentity.from_open_api_principal(_pat_principal())

    async def batch_check(_login_user, *, resource_type, resource_ids, actions):
        # What the real batch path returns for a narrowed-out target.
        return {str(one): frozenset() for one in resource_ids}

    async def rows(ids):
        row = MagicMock()
        row.id = 999
        row.type = 3
        row.name = "someone else's space"
        row.description = ""
        return [row] if 999 in ids else []

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.retrieval_facade_service.batch_check_business_actions",
        batch_check,
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.retrieval_facade_service.KnowledgeDao.aget_list_by_ids", rows
    )

    with pytest.raises(KnowledgeUnreachableError) as narrowed:
        await RetrievalFacadeService.retrieve(identity, RetrievalRequest(query="q", knowledge_ids=[999]))
    with pytest.raises(KnowledgeUnreachableError) as absent:
        await RetrievalFacadeService.retrieve(identity, RetrievalRequest(query="q", knowledge_ids=[12345]))

    assert narrowed.value.code == absent.value.code == 26321
    assert open_api_http_status(narrowed.value) == 404
    # Byte-identical apart from the id each one names.
    narrowed_body = narrowed.value.to_dict()
    absent_body = absent.value.to_dict()
    narrowed_body["data"]["unreachable_ids"] = absent_body["data"]["unreachable_ids"] = []
    assert narrowed_body == absent_body
