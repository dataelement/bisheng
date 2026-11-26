"""T047: real router registration, fail-closed wiki generation and frozen batch plans."""

from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError
from bisheng.knowledge.domain.repositories.provider_wiki_repository import (
    WikiControl,
    WikiScope,
    WikiUnavailable,
)
from test.knowledge_unification import test_kn_batch as batch_fixtures


async def test_wiki_ready_requires_ready_generation():
    db = AsyncMock()
    db.execute.return_value = MagicMock()
    binding = NS(
        state="ready", revision=1, wiki_target_revision=2, wiki_applied_revision=2, pending_write_operation_id=None
    )
    generation = NS(state="retired", provider_instance_id=1, generation=2, remote_scope_id="tenant", remote_kb_id="kb")
    db.execute.return_value.one_or_none.return_value = binding, generation, "ready"
    sessions = MagicMock()
    sessions.return_value.__aenter__.return_value = db
    with pytest.raises(WikiUnavailable):
        await WikiControl(sessions).scope(12)


def test_space_mounts_all_govern_routes():
    from bisheng.knowledge.api.router import knowledge_space_router

    paths = {r.path for r in knowledge_space_router.routes}
    for suffix in (
        "wiki/graph",
        "wiki/search",
        "wiki/page",
        "wiki/pages/{slug:path}",
        "wiki/status",
        *(f"files/batch/{{operation}}/{v}" for v in ("inspect", "precheck", "confirm")),
    ):
        assert any(p.endswith("/{space_id}/" + suffix) for p in paths), suffix


async def test_retry_cannot_enter_native_repository_for_external_space():
    from bisheng.knowledge.application.knowledge_batch import KnowledgeBatchApplication

    repo = AsyncMock()
    db = AsyncMock()
    db.scalar.return_value = NS(provider_key="weknora", state="ready", active_generation=2)
    with pytest.raises(KnowledgeOperationPlanChangedError):
        await KnowledgeBatchApplication(repository=repo)._read_facts(db, space_id=12, command=NS(operation="retry"))
    repo.aread.assert_not_awaited()


async def test_real_wiki_route_scopes_http_get(monkeypatch):
    from contextlib import asynccontextmanager

    import httpx
    from fastapi import FastAPI

    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.knowledge.api.endpoints import provider_wiki as wire
    from bisheng.knowledge.application import provider_v1_runtime
    from bisheng.knowledge.application.provider_wiki import WikiApplication, scoped_wiki_get
    from bisheng.knowledge.domain.repositories.provider_wiki_repository import WikiScope

    scope = WikiScope(7, 11, 3, 2, "tenant", "library", 1, 3, 3, None, "ready")
    calls = []

    async def handler(request):
        calls.append(request.url.path)
        assert request.headers["x-api-key"] == "server-key" and "authorization" not in request.headers
        assert request.url.params["min_revision"] == "3"
        return httpx.Response(
            200,
            json={"success": True, "data": {"ready": True, "target_revision": 3, "applied_revision": 3, "empty": False}}
            if request.url.path.endswith("source-revision")
            else {"nodes": [], "edges": []},
        )

    @asynccontextmanager
    async def instance(ctx):
        assert (ctx.tenant_id, ctx.instance_id, ctx.remote_kb_id, ctx.generation) == (7, 3, "library", 2)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://example.invalid/api/v1/",
            headers={"X-API-Key": "server-key"},
        ) as client:
            yield client

    monkeypatch.setattr(provider_v1_runtime, "instance_client", instance)
    control = AsyncMock()
    control.scope.return_value = scope
    permissions = AsyncMock(return_value=True)
    app = FastAPI()
    app.include_router(wire.router)
    app.dependency_overrides[UserPayload.get_login_user] = lambda: "member"
    app.dependency_overrides[wire.get_wiki_application] = lambda: WikiApplication(
        get=scoped_wiki_get, allowed=permissions, control=control
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/11/wiki/graph", headers={"Authorization": "browser", "X-API-Key": "browser-key"})
    assert response.json()["data"] == {"nodes": [], "edges": []}
    assert calls == ["/api/v1/knowledgebase/library/wiki/source-revision", "/api/v1/knowledgebase/library/wiki/graph"]
    assert all(
        call.kwargs == {"resource_type": "knowledge_space", "resource_id": 11, "action": "visible"}
        for call in permissions.await_args_list
    )


deletion_tenant, db, batch = batch_fixtures.deletion_tenant, batch_fixtures.db, batch_fixtures.batch


@pytest.mark.parametrize("change", ["replay", "expired", "revoked", "expanded", "revision", "unsupported"])
async def test_confirm_only_accepts_frozen_manifest(batch, change):
    from copy import deepcopy
    from datetime import datetime, timedelta

    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanExpiredError
    from bisheng.knowledge.application.provider_batch import ProviderBatchApplication

    now = [datetime(2026, 1, 1)]
    scope = {
        "binding": {"tenant_id": 101, "space_id": 1, "provider_key": "weknora"},
        "revision": [3, 4, 1, 1, 2],
        "tags": [],
        "files": [
            {"file_id": i, "document_id": i, "version_id": i, "lifecycle": "active", "status": 1 if i == 32 else 3}
            for i in (30, 31, 32)
        ],
    }

    async def facts(*_, **kwargs):
        return deepcopy(scope)

    port = AsyncMock()
    resolver = MagicMock()
    resolver.resolve.return_value = port
    app = ProviderBatchApplication(
        session_factory=batch.db.sessions,
        permission_check=batch.application().permissions,
        facts=facts,
        resolver=None if change == "unsupported" else resolver,
        clock=lambda: now[0],
    )
    batch.denied.add(31)
    command = batch_fixtures.command("retry", ("file", 30), ("file", 31), ("file", 32))
    if change == "unsupported":
        with pytest.raises(KnowledgeOperationPlanChangedError):
            await app.aprecheck(identity=batch.user, space_id=1, command=command)
        port.accept_batch.assert_not_awaited()
        return
    plan = await app.aprecheck(identity=batch.user, space_id=1, command=command)
    assert [v.id for v in plan.valid_items] == [30] and plan.requires_skip_confirmation
    port.accept_batch.assert_not_awaited()
    kwargs = {"identity": batch.user, "space_id": 1, "operation": "retry", "request": batch_fixtures.confirmation(plan)}
    if change == "replay":
        assert not (await app.aconfirm(**kwargs))["reused"]
        assert (await app.aconfirm(**kwargs))["reused"]
        port.accept_batch.assert_awaited_once()
        assert [v["file_id"] for v in port.accept_batch.await_args.kwargs["targets"]] == [30]
        return
    if change == "expired":
        now[0] += timedelta(minutes=6)
    if change == "revoked":
        batch.denied.add(30)
    if change == "expanded":
        batch.denied.clear()
    if change == "revision":
        scope["revision"][2] += 1
    with pytest.raises(
        KnowledgeOperationPlanExpiredError if change == "expired" else KnowledgeOperationPlanChangedError
    ):
        await app.aconfirm(**kwargs)
    port.accept_batch.assert_not_awaited()


async def seed_external_space(batch):
    """Ready instance/generation/binding plus primary mappings for files 30 and 31."""
    from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderBinding as B
    from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderGeneration as G
    from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderInstance as I
    from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderMapping as M
    from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderTagRef as T

    async with batch.db.engine.begin() as conn:
        for table in (I, G, M, T):
            await conn.run_sync(table.__table__.create, checkfirst=True)
    async with batch.db.sessions() as db, db.begin():
        db.add(
            I(
                id=1,
                tenant_id=101,
                provider_key="weknora",
                remote_scope_id="a",
                state="ready",
                endpoint="https://example.invalid",
                credential_ref="x",
                capability_revision=7,
            )
        )
        db.add(
            G(
                tenant_id=101,
                space_id=1,
                provider_instance_id=1,
                generation=2,
                state="ready",
                remote_scope_id="a",
                remote_kb_id="b",
            )
        )
        db.add(B(tenant_id=101, space_id=1, provider_key="weknora", active_generation=2, state="ready"))
        for file, version in [(30, 300), (31, 301)]:
            db.add(
                M(
                    tenant_id=101,
                    space_id=1,
                    generation=2,
                    resource_type="file",
                    local_resource_id=file,
                    remote_object_id=str(file),
                    version_id=version,
                    logical_document_id=100,
                    lifecycle_state="active",
                )
            )


async def test_snapshot_uses_only_current_primary_and_active_binding(batch):
    from bisheng.knowledge.domain.repositories.provider_batch_repository import snapshot

    await seed_external_space(batch)
    command = batch_fixtures.command("tag", ("file", 30), ("file", 31))
    async with batch.db.sessions() as db, db.begin():
        scope = await snapshot(db, 1, command, lock=True)
        assert [v["file_id"] for v in scope["files"]] == [30] and scope["revision"][-1] == 7
        assert scope["binding"]["remote_kb_id"] == "b"
    # Never invent a provider tag: appends must name refs the generation already published.
    for unsupported in (
        batch_fixtures.command("tag", ("file", 30), new_tag_names=["brand-new"]),
        batch_fixtures.command("tag", ("file", 30), tag_ids=[11]),
    ):
        async with batch.db.sessions() as db, db.begin():
            with pytest.raises(KnowledgeOperationPlanChangedError):
                await snapshot(db, 1, unsupported, lock=True)


# --- T048: Wiki entry and external-batch capability boundary over the real routes ---

READY_PROOF = {"success": True, "data": {"ready": True, "target_revision": 3, "applied_revision": 3, "empty": False}}
EMPTY_PROOF = {
    "success": True,
    "data": {"ready": True, "target_revision": 0, "applied_revision": 0, "empty": True},
}
GENERATING_PROOF = {"success": True, "data": {"ready": False}}

WIKI_PAGE = {
    "knowledge_base_id": "library",
    "slug": "entity/a",
    "title": "A",
    "page_type": "entity",
    "summary": "shared",
    "content": "shared body",
    "in_links": [],
    "out_links": ["concept/b"],
    "source_refs": ["doc|secret title", "unknown|hidden"],
}

WIKI_GRAPH = {
    "nodes": [{"slug": "entity/a", "title": "A", "page_type": "entity"}],
    "edges": [{"source": "entity/a", "target": "concept/b"}],
}


def wiki_scope(**changes):
    return replace(
        WikiScope(
            tenant_id=7,
            space_id=11,
            instance_id=4,
            generation=2,
            remote_scope_id="tenant",
            remote_kb_id="library",
            revision=3,
            target=3,
            applied=3,
            pending=None,
            state="ready",
        ),
        **changes,
    )


class WikiPort:
    """The KB-bound GET port: one envelope per path, plus a record of every call."""

    def __init__(self, *, proof=READY_PROOF, page=WIKI_PAGE, graph=WIKI_GRAPH):
        self.proof, self.page, self.graph, self.calls = proof, page, graph, []

    async def __call__(self, scope, path, params):
        self.calls.append((path, dict(params)))
        if path == "source-revision":
            return self.proof
        if path == "graph":
            return self.graph
        if path == "search":
            return {"pages": [self.page]}
        if path == "pages/entity/a":
            return self.page
        raise AssertionError(f"unexpected provider path {path}")


async def _wiki_allowed(user, *, resource_type, resource_id, action):
    if resource_type == "knowledge_space":
        return user != "OUT"
    return user == "LIN" and resource_id == 12


@asynccontextmanager
async def wiki_client(port, *, scope=None, user="LIN", control=None, allowed=None):
    from bisheng.knowledge.api.endpoints import provider_wiki as wire
    from bisheng.knowledge.application.provider_wiki import WikiApplication

    control = control or AsyncMock()
    control.scope.return_value = scope or wiki_scope()
    control.source.side_effect = lambda _scope, remote: 12 if remote == "doc" else None
    app = FastAPI()
    app.include_router(wire.router)
    app.dependency_overrides[UserPayload.get_login_user] = lambda: user
    app.dependency_overrides[wire.get_wiki_application] = lambda: WikiApplication(
        get=port, control=control, allowed=allowed or _wiki_allowed
    )

    @app.exception_handler(BaseErrorCode)
    async def error(request, exc):
        return JSONResponse(exc.return_resp_instance().model_dump())

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.mark.parametrize(
    "expected,changes,proof,reads",
    [
        ("preparing", {"state": "provisioning"}, READY_PROOF, False),
        ("generating", {}, GENERATING_PROOF, False),
        ("updating", {"pending": "delete-op"}, READY_PROOF, False),
        ("query_failed", {}, {}, False),
        ("empty", {"target": 0, "applied": 0}, EMPTY_PROOF, True),
        ("ready", {}, READY_PROOF, True),
    ],
)
async def test_wiki_status_names_the_barrier_state_and_blocks_content(expected, changes, proof, reads):
    port = WikiPort(proof=proof)
    async with wiki_client(port, scope=wiki_scope(**changes)) as client:
        status = (await client.get("/11/wiki/status")).json()["data"]
        assert status == {"state": expected, "generation": 2}
        assert (await client.get("/11/wiki/graph")).json()["status_code"] == (200 if reads else 18089)
        page = (await client.get("/11/wiki/pages/entity/a?generation=2")).json()
        assert page["status_code"] == (200 if reads else 18089)
    assert ("graph" in [path for path, _ in port.calls]) is reads
    assert ("pages/entity/a" in [path for path, _ in port.calls]) is reads


async def test_wiki_entry_checks_space_visible_before_any_provider_read():
    port, control = WikiPort(), AsyncMock()
    async with wiki_client(port, user="OUT", control=control) as client:
        for path in ("/11/wiki/status", "/11/wiki/graph", "/11/wiki/search?q=a", "/11/wiki/page?generation=2&slug=a"):
            assert (await client.get(path)).json()["status_code"] == 18089
    assert port.calls == []
    control.scope.assert_not_awaited()


async def test_wiki_pages_route_takes_hierarchical_slug_and_rejects_stale_or_unsafe_ones():
    port = WikiPort()
    async with wiki_client(port) as client:
        page = (await client.get("/11/wiki/pages/entity/a?generation=2")).json()["data"]
        assert page["slug"] == "entity/a" and page["page_type"] == "entity" and page["summary"] == "shared"
        for unsafe in ("/11/wiki/pages/%2e%2e%2fsecret?generation=2", "/11/wiki/pages/entity/a?generation=1"):
            assert (await client.get(unsafe)).json()["status_code"] == 18089
        assert (await client.get("/11/wiki/pages/entity/a")).status_code == 422
        assert (await client.get("/11/wiki/pages/" + "a" * 300 + "?generation=2")).status_code == 422
        # An empty slug is rejected either way: FastAPI's path converter answers
        # 422, an unmatched route answers 404. Both fail closed; the test pins
        # "rejected", not one router's incidental status.
        assert (await client.get("/11/wiki/pages/")).status_code in (404, 422)
    # Only the accepted hierarchical read reached the bound library.
    assert [path for path, _ in port.calls] == ["source-revision", "pages/entity/a"]


async def test_wiki_boundary_rejects_nonpositive_space_and_blank_search():
    port = WikiPort()
    async with wiki_client(port) as client:
        assert (await client.get("/0/wiki/status")).status_code == 422
        assert (await client.get("/11/wiki/search?q=%20%20")).status_code == 422
        assert (await client.get("/11/wiki/search?q=" + "a" * 513)).status_code == 422
    assert port.calls == []


async def test_wiki_body_is_shared_but_original_sources_follow_file_permission():
    port = WikiPort()
    async with wiki_client(port, user="LIN") as lin, wiki_client(port, user="ZHOU") as zhou:
        lin_page = (await lin.get("/11/wiki/page?generation=2&slug=entity/a")).json()["data"]
        zhou_page = (await zhou.get("/11/wiki/page?generation=2&slug=entity/a")).json()["data"]
        assert lin_page["content"] == zhou_page["content"] == "shared body"
        assert lin_page["out_links"] == zhou_page["out_links"] == ["concept/b"]
        assert lin_page["sources"] == [{"file_id": 12}, {"restricted": True}]
        assert zhou_page["sources"] == [{"restricted": True}, {"restricted": True}]
        assert "secret title" not in str(zhou_page) and "doc|" not in str(zhou_page)
        assert "http" not in str(zhou_page)


@asynccontextmanager
async def batch_client(batch, monkeypatch, *, resolver=None, application=None):
    from bisheng.knowledge.api.endpoints import batch as wire
    from bisheng.knowledge.api.endpoints import processing
    from bisheng.knowledge.application import knowledge_batch

    app = FastAPI()
    app.include_router(wire.router)
    if resolver is not None:
        app.state.provider_batch_resolver = resolver
    app.dependency_overrides[UserPayload.get_login_user] = lambda: batch.user
    if application is not None:
        app.dependency_overrides[wire.get_batch_application] = lambda: application
    # The external batch path reads frozen facts from the disposable SQLite
    # fixture, never from an ambient MySQL.
    app.state.provider_batch_session_factory = batch.db.sessions
    monkeypatch.setattr(knowledge_batch, "batch_check_business_actions", batch.application().permissions)
    monkeypatch.setattr(processing, "resolve_management_scope", AsyncMock(return_value=NS(tenant_id=101)))

    @app.exception_handler(BaseErrorCode)
    async def error(request, exc):
        return JSONResponse(exc.return_resp_instance().model_dump())

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


def external_route(monkeypatch):
    from bisheng.knowledge.api.endpoints import batch as wire

    monkeypatch.setattr(wire, "resolve_space_route", AsyncMock(return_value=NS(provider_key="weknora", generation=2)))


@pytest.mark.parametrize("operation", ["tag", "retry", "delete"])
async def test_external_batch_without_write_port_is_refused_not_native(batch, monkeypatch, operation):
    from sqlalchemy import select

    from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
    from bisheng.knowledge.domain.repositories.knowledge_batch_repository import KnowledgeBatchRepository

    await seed_external_space(batch)
    external_route(monkeypatch)
    native = {}
    for name in ("aread", "atag", "await_retry"):
        native[name] = AsyncMock()
        monkeypatch.setattr(KnowledgeBatchRepository, name, native[name])
    async with batch_client(batch, monkeypatch) as client:
        body = {"items": [{"id": 30, "type": "file"}]}
        inspect = (await client.post(f"/1/files/batch/{operation}/inspect", json=body)).json()
        precheck = await client.post(
            f"/1/files/batch/{operation}/precheck", json=body, headers={"X-Management-Tenant": "101"}
        )
    assert inspect["status_code"] == precheck.json()["status_code"] == 18089
    assert all(not call.await_count for call in native.values())
    async with batch.db.sessions() as session:
        assert (await session.execute(select(KnowledgeOperationPlan))).scalars().all() == []


async def test_external_download_inspect_does_not_require_write_port(batch, monkeypatch):
    """Download eligibility is a read probe; refusing it without a write port was a 500/toast path."""
    from bisheng.knowledge.domain.repositories.knowledge_batch_repository import KnowledgeBatchRepository

    await seed_external_space(batch)
    external_route(monkeypatch)
    native = AsyncMock()
    monkeypatch.setattr(KnowledgeBatchRepository, "aread", native)
    async with batch_client(batch, monkeypatch) as client:
        body = {"items": [{"id": 30, "type": "file"}]}
        inspect = (await client.post("/1/files/batch/download/inspect", json=body)).json()
    assert inspect["status_code"] == 200
    assert inspect["data"]["can_execute"]
    assert [row["id"] for row in inspect["data"]["valid_items"]] == [30]
    assert native.await_count == 0


async def test_external_batch_delete_freezes_plan_accepts_intent_and_replays_receipt(batch, monkeypatch):
    from bisheng.knowledge.application.provider_resolver import ProviderResolver

    await seed_external_space(batch)
    external_route(monkeypatch)
    accepted = []

    class Port:
        async def accept_batch(self, db, **kwargs):
            accepted.append(kwargs)

    class Factory:
        def capabilities(self, context):
            return {context.operation: "supported"}

        def build(self, context):
            return Port()

    async with batch_client(batch, monkeypatch, resolver=ProviderResolver({"weknora": Factory()})) as client:
        body = {"items": [{"id": 30, "type": "file"}]}
        inspect = (await client.post("/1/files/batch/delete/inspect", json=body)).json()["data"]
        assert inspect["can_execute"] and [row["id"] for row in inspect["valid_items"]] == [30]
        assert "confirmation_id" not in inspect and accepted == []
        plan = (
            await client.post("/1/files/batch/delete/precheck", json=body, headers={"X-Management-Tenant": "101"})
        ).json()["data"]
        assert accepted == []
        confirmation = {
            "confirmation_id": plan["confirmation_id"],
            "plan_digest": plan["plan_digest"],
            "idempotency_key": "external-delete-1",
        }
        first = (
            await client.post(
                "/1/files/batch/delete/confirm", json=confirmation, headers={"X-Management-Tenant": "101"}
            )
        ).json()["data"]
        assert first["state"] == "accepted" and not first["reused"]
        assert first["items"] == [{"id": 30, "state": "accepted"}]
        assert len(accepted) == 1
        frozen = accepted[0]["targets"][0]
        assert (frozen["file_id"], frozen["document_id"], frozen["version_id"]) == (30, 100, 300)
        assert (frozen["remote_id"], frozen["lifecycle"], frozen["status"]) == ("30", "active", 2)
        assert accepted[0]["operation"] == "delete" and accepted[0]["binding"]["remote_kb_id"] == "b"
        replay = (
            await client.post(
                "/1/files/batch/delete/confirm", json=confirmation, headers={"X-Management-Tenant": "101"}
            )
        ).json()["data"]
        assert replay["reused"] and replay["operation_id"] == first["operation_id"] == plan["confirmation_id"]
        assert len(accepted) == 1
