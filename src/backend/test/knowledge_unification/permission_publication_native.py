"""Actual M2/M3 SQL plus isolated HTTP/Redis transports for T157/T158."""

import json
from collections import defaultdict
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace
from weakref import WeakSet

import httpx
import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.config.openfga import OpenFGAConf
from bisheng.permission.application import control_state, sql_runtime
from bisheng.permission.application.catalog_api import (
    TECHNICAL_MARKER_SUBJECTS,
    OpenFGACatalogProjector,
    required_relations_checksum,
)
from bisheng.permission.application.migration_read import (
    PinnedMigrationPermissionReader,
    authorization_model_checksum,
    build_authorization_model_f048,
)
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionAction,
    PermissionActionResourceScope,
    PermissionCatalogRelease,
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionModel,
    PermissionModelAction,
    PermissionVisibleSourceProjection,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
    PermissionMigrationSnapshotRepository,
)
from bisheng.permission.domain.services.catalog_policy import derive_action_release
from bisheng.permission.domain.services.catalog_service import CatalogDraftSnapshot
from bisheng.permission.domain.services.grant_source_service import GrantSourceService
from bisheng.permission.domain.services.model_policy import CustomModelSelection, derive_permission_models
from bisheng.permission.domain.services.visibility_projection_service import VisibilityProjectionCompiler
from bisheng.permission.migration import f048_runtime_storage
from bisheng.permission.migration import f118_plan as plans
from test.knowledge_unification import test_migration_inventory_application as m2
from test.knowledge_unification.test_permission_floor_retirement_signing import legacy_catalog

raw_resource_native = m2.resource_native
native = m2.native
complete = m2.complete
transport = m2.transport
CATALOG = (
    AuthorizationModelRelease,
    PermissionCatalogRelease,
    PermissionAction,
    PermissionActionResourceScope,
    PermissionModel,
    PermissionModelAction,
)


@pytest.fixture
async def resource_native(raw_resource_native):
    metadata = sa.MetaData()
    for model in CATALOG:
        table = model.__table__.to_metadata(metadata)
        table.c.id.type = sa.Integer()
    async with raw_resource_native.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    return raw_resource_native


class Sessions:
    def __init__(self, engine):
        self.engine, self.opened, self.commits = engine, WeakSet(), 0
        self.fail_at, self.after, self.cancel = None, False, False

    @asynccontextmanager
    async def __call__(self):
        owner = self

        class Native(AsyncSession):
            async def commit(self):
                owner.commits += 1
                hit = owner.commits == owner.fail_at
                if hit and not owner.after:
                    raise OSError("commit ACK lost")
                await super().commit()
                if hit:
                    if owner.cancel:
                        import asyncio

                        raise asyncio.CancelledError()
                    raise OSError("commit ACK lost")

        async with Native(self.engine, expire_on_commit=False) as session:
            self.opened.add(session)
            yield session

    def assert_closed(self):
        assert not any(session.in_transaction() for session in self.opened), "external IO held an owned SQL transaction"


class Store:
    def __init__(self, schema, sessions):
        self.models = {"original-model": schema}
        self.tuples, self.requests, self.sessions = set(), [], sessions
        self.writes, self.scans = 0, 0
        self.enforce_closed = False
        self.fail_write, self.after, self.cancel = None, False, False
        self.extra, self.drop, self.unknown = False, False, False
        self.on_request = None

    async def request(self, request):
        if self.enforce_closed:
            self.sessions.assert_closed()
        self.requests.append(request)
        if self.on_request is not None:
            await self.on_request(request)
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else {}
        if path == "/stores":
            return httpx.Response(200, json={"stores": [{"id": "original-store", "name": OpenFGAConf().store_name}]})
        if path.endswith("/authorization-models"):
            if method == "POST":
                self.models["published-target"] = body
                return httpx.Response(200, json={"authorization_model_id": "published-target"})
            return httpx.Response(
                200, json={"authorization_models": [{"id": key, **value} for key, value in self.models.items()]}
            )
        if "/authorization-models/" in path:
            value = self.models.get(path.rsplit("/", 1)[1])
            return httpx.Response(200 if value else 404, json={"authorization_model": value})
        if path.endswith("/read"):
            key = body.get("tuple_key", {})
            if not key and not body.get("continuation_token"):
                self.scans += 1
            if not key:
                if not body.get("continuation_token"):
                    self._scan_values = sorted(self.tuples, reverse=self.scans % 2 == 0)
                values = self._scan_values
            else:
                values = sorted(self.tuples)

            def matches(row):
                for index, field in enumerate(("user", "relation", "object")):
                    value = key.get(field)
                    if value is not None and (
                        not row[index].startswith(value)
                        if field == "object" and value.endswith(":")
                        else row[index] != value
                    ):
                        return False
                return True

            values = [row for row in values if matches(row)]
            start = int(body.get("continuation_token") or 0)
            limit = body.get("page_size", 100)
            selected = values[start : start + limit]
            response = {
                "tuples": [{"key": dict(zip(("user", "relation", "object"), row, strict=True))} for row in selected]
            }
            if start + limit < len(values):
                response["continuation_token"] = str(start + limit)
            return httpx.Response(200, json=response)
        if path.endswith("/write"):
            self.writes += 1
            hit = self.writes == self.fail_write
            if hit and not self.after:
                raise httpx.ReadTimeout("write acknowledgement lost", request=request)
            schema = self.models[body["authorization_model_id"]]
            types = {row["type"]: row for row in schema["type_definitions"]}
            for row in body.get("writes", {}).get("tuple_keys", ()):
                object_type = row["object"].partition(":")[0]
                assert row["relation"] in types[object_type]["relations"], "write used the wrong real model schema"
                self.tuples.add((row["user"], row["relation"], row["object"]))
            for row in body.get("deletes", {}).get("tuple_keys", ()):
                self.tuples.discard((row["user"], row["relation"], row["object"]))
            if hit:
                if self.cancel:
                    import asyncio

                    raise asyncio.CancelledError()
                raise httpx.ReadTimeout("write acknowledgement lost", request=request)
            return httpx.Response(200, json={})
        if path.endswith("/streamed-list-objects"):
            return httpx.Response(200, text="")
        return httpx.Response(200, json={"objects": []})


def model_release(before):
    actions = derive_action_release(before.actions, registered_action_codes=tuple(row.code for row in before.actions))
    models = derive_permission_models(
        actions,
        custom_models=tuple(
            CustomModelSelection(
                row.model_key,
                row.name,
                row.selected_action_codes,
                row.active,
                row.allow_same_level,
                row.config_scope,
                row.visibility_only_resource_types,
                row.visibility_level,
                retired_use_level_floor=row.retired_use_level_floor,
            )
            for row in before.models
            if row.kind == "CUSTOM"
        ),
        standard_allow_same_level={
            row.model_key: row.allow_same_level for row in before.models if row.kind == "STANDARD"
        },
    )
    return models


def initial_tuples(before, resource, schema):
    draft = CatalogDraftSnapshot(
        before.release.id,
        before.release.release_key,
        before.release.id,
        before.release.release_key,
        before.release.checksum,
        "b" * 64,
        (),
        (),
        model_release=model_release(before),
    )
    rows = OpenFGACatalogProjector._expected_tuples(draft)
    for subject in TECHNICAL_MARKER_SUBJECTS:
        rows.append(
            {
                "user": subject,
                "relation": "active",
                "object": "permission_catalog_release:" + before.release.release_key,
            }
        )
        for relation in ("permission_enabled", "custom_mode"):
            rows.append({"user": subject, "relation": relation, "object": "knowledge_library:9000"})
    buckets = {}
    for row in resource.assignees:
        buckets.setdefault(row.grant_id, []).append(row.to_source_record())
    grants = plans._grants(
        resource,
        {row.model_key: row for row in before.models},
        {row.code: row.resource_types for row in before.actions},
        {key: tuple(value) for key, value in buckets.items()},
    )
    service = GrantSourceService()
    for grant in grants:
        if not grant.active:
            continue
        grant = replace(
            grant,
            grant_id=sql_runtime.stable_grant_key(
                tenant_id=grant.tenant_id,
                resource_type=grant.resource_type,
                resource_id=grant.resource_id,
                model_key=grant.model.model_key,
            ),
        )
        sources = [source for source in grant.sources if source.active]
        if not sources:
            continue
        rows.extend(
            asdict(delta)
            for delta in (
                service._model_delta(grant, action="WRITE", sequence=0),
                service._grant_delta(grant, action="WRITE", sequence=1),
            )
        )
        rows.extend(asdict(service._assignee_delta(grant, source, action="WRITE", sequence=0)) for source in sources)
    rows.extend(
        {"user": row.source.projected_subject, "relation": "visible", "object": "knowledge_library:9000"}
        for row in resource.visible_sources
        if row.source.state == "ACTIVE"
    )
    allowed = {row["type"]: set(row.get("relations", {})) for row in schema["type_definitions"]}
    rows = [row for row in rows if row["relation"] in allowed[row["object"].partition(":")[0]]]
    return {(row["user"], row["relation"], row["object"]) for row in rows} | {("user:42", "member", "tenant:202")}


@pytest.fixture
async def published_input(complete, transport, monkeypatch, request):
    options = getattr(request, "param", False)
    options = options if type(options) is dict else {"same": options}
    same = options.get("same", False)
    target = build_authorization_model_f048()
    source_schema = deepcopy(target)
    release_type = next(row for row in source_schema["type_definitions"] if row["type"] == "permission_model_release")
    if not same:
        release_type["relations"]["use_marker"] = {"this": {}}
        release_type["metadata"]["relations"]["use_marker"] = deepcopy(
            release_type["metadata"]["relations"]["download_marker"]
        )
    if "models" in options:
        standard_count = sum(row.kind != "CUSTOM" for row in legacy_catalog().models)
        customs = (
            CustomModelSelection("inactive-model", "Inactive model", ("download", "use"), active=False),
            *(
                CustomModelSelection(f"custom-{i}", f"Custom {i}", ("download", "use"))
                for i in range(options["models"] - standard_count - 1)
            ),
        )
        before = legacy_catalog(customs=customs)
    else:
        before = legacy_catalog()
    before = replace(
        before,
        authorization=replace(
            before.authorization,
            model_checksum=authorization_model_checksum(source_schema),
            required_relations_checksum=required_relations_checksum(source_schema),
        ),
        models=tuple(replace(row, legacy_source_key="legacy:" + row.model_key) for row in before.models),
    )
    if options.get("history"):
        before = replace(
            before,
            authorization=replace(before.authorization, id=3),
            release=replace(before.release, required_authorization_model_release_id=3),
        )
    # Same-schema installations may still carry a Catalog use selection; the
    # Store model itself is the actual current target model, not a fake hash.
    async with AsyncSession(complete.engine) as session, session.begin():
        for table in (
            PermissionModelAction,
            PermissionActionResourceScope,
            PermissionModel,
            PermissionAction,
            PermissionCatalogRelease,
            AuthorizationModelRelease,
        ):
            await session.execute(sa.delete(table.__table__))
        monkeypatch.setattr(m2.permission, "baseline", lambda _: before)
        await m2.permission.seed_catalog(session)
        if options.get("history"):
            session.add(
                AuthorizationModelRelease(
                    **(asdict(before.authorization) | {"id": 1, "model_id": "earlier-same", "status": "RETIRED"})
                )
            )
            await session.flush()
        mode = (await PermissionMigrationSnapshotRepository().alist_resource_modes(session))[0]
        source_service = GrantSourceService()
        sources = []
        grants = []
        for index, key in enumerate(("owner", "inactive-model"), 101):
            grant = plans.PermissionGrantBaseline(index, 101, "knowledge_library", "9000", key, "ACTIVE")
            grants.append(grant)
            canonical = source_service.canonicalize_source(
                source_id=index,
                subject_type="user",
                subject_id="7",
                source_type="CREATOR" if index == 101 else "DIRECT",
                source_ref="original-library-source:" + key,
                protected=index == 101,
            )
            values = asdict(canonical)
            values.pop("active")
            values["id"] = values.pop("source_id")
            sources.append(plans.PermissionAssigneeBaseline(grant_id=index, tenant_id=101, state="ACTIVE", **values))
        resource = plans.PermissionResourceBaseline(
            101, "knowledge_library", "9000", mode, tuple(grants), tuple(sources), ()
        )
        for index in range(options.get("sources", 2) - 2):
            canonical = source_service.canonicalize_source(
                source_id=1000 + index,
                subject_type="user",
                subject_id="7",
                source_type="OTHER",
                source_ref=f"original-scale:{index}",
            )
            values = asdict(canonical)
            values.pop("active")
            sources.append(
                plans.PermissionAssigneeBaseline(
                    id=values.pop("source_id"), grant_id=101, tenant_id=101, state="ACTIVE", **values
                )
            )
        resource = replace(resource, assignees=tuple(sources))
        buckets = defaultdict(list)
        for row in sources:
            buckets[row.grant_id].append(row.to_source_record())
        snapshots = plans._grants(
            resource,
            {row.model_key: row for row in before.models},
            {row.code: row.resource_types for row in before.actions},
            {key: tuple(rows) for key, rows in buckets.items()},
        )
        visible = (
            VisibilityProjectionCompiler().compile(tenant_id=101, grants=snapshots, existing_sources=()).active_sources
        )
        resource = replace(
            resource,
            visible_sources=tuple(
                plans.PermissionVisibleSourceBaseline(index, row) for index, row in enumerate(visible, 101)
            ),
        )
        session.add_all(PermissionGrant(**asdict(row)) for row in grants)
        session.add_all(PermissionGrantAssignee(**asdict(row)) for row in sources)
        session.add_all(
            PermissionVisibleSourceProjection(id=row.id, **row.source.model_dump()) for row in resource.visible_sources
        )
    from test.knowledge_unification import test_migration_resource_repository as resources

    extra_modes = []
    if options.get("roots", 1) > 1:
        roots = [resources.resource(10000 + i) for i in range(options["roots"] - 1)]
        await complete.insert(resources.Knowledge, roots)
        extra_modes.extend(
            plans.ResourceModeBaseline(10000 + i, 101, "knowledge_library", str(10000 + i), "CUSTOM")
            for i in range(options["roots"] - 1)
        )
    if options.get("parent"):
        extra_modes.append(
            plans.ResourceModeBaseline(1, 101, "knowledge_file", "1", "INHERIT", "knowledge_library", "9000")
        )
    if options.get("contexts"):
        extra_modes.append(plans.ResourceModeBaseline(2, 101, "workflow", "context-flow", "CUSTOM"))
    if extra_modes:
        await complete.insert(ResourcePermissionMode, [asdict(row) for row in extra_modes])
    sessions = Sessions(complete.engine)
    store = Store(source_schema, sessions)
    if options.get("history"):
        store.models["earlier-same"] = source_schema
    store.tuples = initial_tuples(before, resource, source_schema)
    from bisheng.permission.domain.services.resource_lifecycle_policy import compile_existing_mode_tuples

    for row in extra_modes:
        store.tuples.update(delta.key for delta in compile_existing_mode_tuples(row))
    store.tuples.update((f"user:{100000 + i}", "member", "tenant:202") for i in range(options.get("tuples", 0)))
    if options.get("contexts"):
        store.tuples.update(
            {
                ("tenant:202", "shared_with", "workflow:context-flow"),
                ("user:*", "visible", "knowledge_library:9000"),
                ("user:*", "system_download_marker", "knowledge_library:9000"),
                ("user:*", "system_use_marker", "knowledge_library:9000"),
            }
        )
    if options.get("raw_edge"):
        store.tuples.add(tuple(options["raw_edge"]))
    if getattr(request.node, "callspec", None) and request.node.callspec.params.get("corrupt") == "unknown_namespace":
        store.tuples.add(("user:7", "unknown_relation", "knowledge_library:9000"))
    original_client = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(store.request)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setattr(f048_runtime_storage, "get_async_db_session", sessions)
    monkeypatch.setattr(control_state, "get_async_db_session", sessions)
    redis = SimpleNamespace(aget=lambda *args: None)

    async def get(*args):
        sessions.assert_closed()
        return "ready"

    async def set_value(*args, **kwargs):
        sessions.assert_closed()

    redis.aget, redis.aset = get, set_value

    async def redis_factory():
        return redis

    monkeypatch.setattr(sql_runtime, "get_redis_client", redis_factory)

    @asynccontextmanager
    async def sharing(catalog):
        async with PinnedMigrationPermissionReader(OpenFGAConf(), catalog) as reader:
            yield reader

    transport.reader_factory = sharing

    @sa.event.listens_for(complete.engine.sync_engine, "begin")
    def begin(connection):
        connection.exec_driver_sql("BEGIN")

    if options.get("reference_seed") is not None:
        await options["reference_seed"](complete)
    if options.get("existing_mode_graph_from_seed"):
        async with sessions() as session, session.begin():
            modes = await PermissionMigrationSnapshotRepository().alist_resource_modes(session)
        for mode in modes:
            store.tuples.update(delta.key for delta in compile_existing_mode_tuples(mode))

    app = m2.application(
        __import__("bisheng.knowledge.application.unification_inventory", fromlist=["UnificationInventoryApplication"]),
        transport,
    )
    async with sessions() as session, session.begin():
        frozen = await app.arun(session, **transport.inputs)
    store.enforce_closed = True
    store.requests.clear()
    store.scans = 0
    return SimpleNamespace(
        database=complete,
        artifacts=transport,
        sessions=sessions,
        store=store,
        before=before,
        resource=resource,
        frozen=frozen,
        input=dict(transport.inputs),
        same=same,
        options=options,
    )
