"""Provider reads are scoped local-resource decisions, not bearer URLs."""

from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.knowledge.application.provider_reads import ProviderReads
from bisheng.knowledge.application.provider_resolver import ProviderResolver
from bisheng.knowledge.domain.repositories.provider_read_repository import ReadFact
from bisheng.knowledge.infrastructure.providers.registry import PortContext


class Store:
    def __init__(self):
        ctx = PortContext(1, 7, "weknora", "preview", 2, 3, "private-scope", "private-library")
        self.rows = [
            ReadFact(
                ctx,
                i,
                "folder" if i == 8 else "knowledge_file",
                f"doc{i}",
                None if i <= 2 or i == 8 else 8,
                i + 10,
                1,
                f"private-id-{i}",
            )
            for i in range(1, 9)
        ]

    async def count_files(self, *, tenant_id, space_id, root_card):
        rows = await self.load(tenant_id=tenant_id, space_id=space_id)
        return sum(
            r.kind == "knowledge_file" and (r.parent_id is None if root_card else r.resource_id != 2) for r in rows
        )

    async def load(self, *, tenant_id, space_id, resource_id=None):
        return [
            r
            for r in self.rows
            if r.context.tenant_id == tenant_id
            and r.context.space_id == space_id
            and (resource_id is None or r.resource_id == resource_id)
        ]


class Remote:
    def __init__(self):
        self.opened = []
        self.closed = 0

    def capabilities(self, ctx):
        return {ctx.operation: "supported"}

    def build(self, ctx):
        return self

    @asynccontextmanager
    async def open_stream(self, remote_id, *, range_header):
        self.opened.append((remote_id, range_header))
        try:
            yield b"content"
        finally:
            self.closed += 1


def setup_reads():
    store, remote = Store(), Remote()
    grants = {
        ("knowledge_space", 7, "visible"),
        ("folder", 8, "visible"),
        *(("knowledge_file", i, "visible") for i in (1, 5, 7)),
    }

    async def check(**kw):
        return (kw["resource_type"], int(kw["resource_id"]), kw["action"]) in grants

    async def visible(actor, space_id, rows):
        return {(r.kind, r.resource_id) for r in rows if (r.kind, r.resource_id, "visible") in grants}

    reads = ProviderReads(
        store=store,
        permissions=SimpleNamespace(check_action=check, visible=visible),
        resolver=ProviderResolver({"weknora": remote}),
    )
    return reads, grants, store, remote, SimpleNamespace(current_tenant_id=1)


async def test_sparse_pages_counts_and_public_space_is_not_file_permission():
    reads, grants, _, _, actor = setup_reads()
    page = await reads.list(actor, 7, all_folders=True, kind="knowledge_file", query="doc", offset=1, limit=1)
    assert [r.resource_id for r in page.items] == [5]
    assert page.total == 3
    assert not hasattr(page, "root_files") and not hasattr(page, "space_files")
    with pytest.raises(PermissionDeniedError):
        await reads.managed_card_count(actor, 7)
    grants.add(("knowledge_space", 7, "edit"))
    assert await reads.managed_card_count(actor, 7) == 2
    assert await reads.detail_count(actor, 7) == 6
    page = await reads.list(actor, 7, all_folders=True, query="doc7")
    assert page.total == 1
    grants.clear()
    with pytest.raises(PermissionDeniedError):
        await reads.list(actor, 7)


async def test_get_range_revocation_identity_and_close():
    reads, grants, store, remote, actor = setup_reads()
    handle = await reads.issue(actor, 7, 1, "preview")
    assert "private" not in repr(handle)
    with pytest.raises(PermissionDeniedError):
        await reads.issue(actor, 7, 1, "download")
    async with reads.open(actor, handle, range_header="bytes=0-2") as body:
        assert body == b"content"
    with pytest.raises(RuntimeError):
        async with reads.open(actor, handle):
            raise RuntimeError("disconnected")
    assert remote.closed == 2
    grants.remove(("knowledge_file", 1, "visible"))
    for header in (None, "bytes=3-"):
        with pytest.raises(PermissionDeniedError):
            async with reads.open(actor, handle, range_header=header):
                pytest.fail("revoked")
    grants.add(("knowledge_file", 1, "visible"))
    store.rows[0] = replace(store.rows[0], version_id=99)
    with pytest.raises(PermissionDeniedError):
        async with reads.open(actor, handle):
            pytest.fail("stale")
    assert remote.opened == [("private-id-1", "bytes=0-2"), ("private-id-1", None)]


async def test_batch_download_does_not_reuse_preview_or_partial_grants():
    reads, grants, _, remote, actor = setup_reads()
    grants.add(("knowledge_file", 1, "download"))
    with pytest.raises(PermissionDeniedError):
        await reads.issue_downloads(actor, 7, [1, 5])
    assert not remote.opened
    grants.add(("knowledge_file", 5, "download"))
    handles = await reads.issue_downloads(actor, 7, [1, 5, 1])
    assert [h.file_id for h in handles] == [1, 5]
    grants.remove(("knowledge_file", 5, "download"))
    with pytest.raises(PermissionDeniedError):
        async with reads.open(actor, handles[1]):
            pytest.fail("member lost download permission")


async def test_sql_facts_use_exact_binding_version_and_lifecycle(monkeypatch):
    """Exercise the production join against a minimal, deliberately inconsistent local catalog."""
    from sqlalchemy import create_engine

    from bisheng.knowledge.domain.repositories import provider_read_repository as m

    engine = create_engine("sqlite://")
    with engine.begin() as db:
        tables = [
            (m.Binding, "tenant_id,space_id,active_generation,provider_key,state", [(1, 7, 3, "weknora", "ready")]),
            (
                m.Generation,
                "tenant_id,space_id,generation,provider_instance_id,remote_scope_id,remote_kb_id",
                [(1, 7, 3, 2, b"S", b"KB")],
            ),
            (
                m.Instance,
                "id,tenant_id,provider_key,remote_scope_id,state",
                [(2, 1, "weknora", b"S", m.READY_INSTANCE)],
            ),
            (m.Knowledge, "id,tenant_id,type", [(7, 1, m.KnowledgeTypeEnum.SPACE.value)]),
            (
                m.File,
                "id,tenant_id,knowledge_id,file_name,file_level_path,file_type,status,file_size,create_time,update_time",
                [(i, 1, 7, f"n{i}", None, 0 if i == 4 else 1, 2, 32, None, None) for i in (1, 2, 3, 4)],
            ),
            (m.Doc, "id,knowledge_id,primary_version_id", [(8, 7, 21)]),
            (m.Version, "id,document_id,knowledge_file_id,version_no,is_primary", [(21, 8, 1, 2, 1), (20, 8, 2, 1, 0)]),
            (
                m.Mapping,
                "tenant_id,space_id,generation,resource_type,local_resource_id,logical_document_id,version_id,operation_epoch,remote_object_id,lifecycle_state,tombstoned_at",
                [
                    (1, 7, 3, "file", 1, 8, 21, 1, b"A", "active", None),
                    (1, 7, 3, "file", 2, 8, 20, 1, b"B", "active", None),
                    (1, 7, 3, "file", 3, 8, 21, 1, b"C", "active", None),
                    (1, 7, 3, m.FOLDER_MAPPING, 4, None, None, 1, b"D", "active", None),
                ],
            ),
        ]
        for model, columns, values in tables:
            db.exec_driver_sql(f"CREATE TABLE {model.__tablename__} ({columns})")
            db.exec_driver_sql(f"INSERT INTO {model.__tablename__} VALUES ({','.join('?' for _ in values[0])})", values)

        @asynccontextmanager
        async def session():
            yield SimpleNamespace(execute=AsyncMock(side_effect=db.execute))

        monkeypatch.setattr(m, "get_async_db_session", session)
        monkeypatch.setattr(m, "get_current_tenant_id", lambda: 1)
        facts = m.SqlReadFacts()

        async def load(resource_id=None):
            return {r.resource_id for r in await facts.load(tenant_id=1, space_id=7, resource_id=resource_id)}

        assert await load() == {1, 4}
        db.exec_driver_sql(f"ALTER TABLE {m.Mapping.__tablename__} ADD COLUMN ready_revision INTEGER")
        assert await facts.count_files(tenant_id=1, space_id=7, root_card=True) == 1
        assert await facts.count_files(tenant_id=1, space_id=7, root_card=False) == 0
        db.exec_driver_sql(f"UPDATE {m.Mapping.__tablename__} SET lifecycle_state='received' WHERE local_resource_id=1")
        assert await facts.count_files(tenant_id=1, space_id=7, root_card=True) == 1
        # Received uploads remain visible in the directory (native WAITING UX).
        assert await facts.count_files(tenant_id=1, space_id=7, root_card=False) == 0
        assert await load() == {1, 4}
        db.exec_driver_sql(f"UPDATE {m.Mapping.__tablename__} SET ready_revision=1, lifecycle_state='active'")
        assert await facts.count_files(tenant_id=1, space_id=7, root_card=False) == 1
        assert await load(2) == {2}  # Historical physical file has its own authorization.
        assert not await load(3)  # Valid-looking mapping, but wrong F118 physical ID.
        db.exec_driver_sql(f"UPDATE {m.Mapping.__tablename__} SET tombstoned_at=1 WHERE local_resource_id=2")
        assert not await load(2)
        db.exec_driver_sql(f"UPDATE {m.Instance.__tablename__} SET state='unavailable'")
        assert not await load()


async def test_shared_runtime_authority_dispatches_exact_resource():
    from bisheng.api.services.f048_permission_runtime import build_f048_resource_composition

    adapters, _ = build_f048_resource_composition(AsyncMock())
    files, spaces = adapters["knowledge_file"], adapters["knowledge_space"]
    files.check_action = AsyncMock(return_value=True)
    spaces.check_action = AsyncMock(return_value=False)
    port = adapters["provider_reads"]
    for kind, expected in [("knowledge_space", False), ("knowledge_file", True)]:
        assert await port.check_action(actor=None, resource_type=kind, resource_id="1", action="visible") is expected
    assert files.check_action.await_count == spaces.check_action.await_count == 1
