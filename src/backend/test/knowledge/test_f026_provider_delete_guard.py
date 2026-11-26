"""Provider-space deletion: remote retire before cutover, safe mapping/byte cleanup."""

from datetime import datetime
from types import SimpleNamespace as NS

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.application import provider_deletion
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderBinding as Binding,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderGeneration as Generation,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderInstance as Instance,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderMapping as Mapping,
)
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderQuota as Quota
from bisheng.knowledge.domain.repositories.provider_wiki_repository import WikiControl

TABLES = (Instance.__table__, Generation.__table__, Binding.__table__, Mapping.__table__, Quota.__table__)


@pytest.fixture
async def sessions():
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with engine.begin() as conn:
            for table in TABLES:
                await conn.run_sync(table.create)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _binding(sessions, *, provider_key="weknora", generation=1, pending=None, space_id=10):
    async with sessions() as db, db.begin():
        db.add(
            Binding(
                tenant_id=1,
                space_id=space_id,
                provider_key=provider_key,
                active_generation=generation,
                pending_write_operation_id=pending,
                state="ready",
            )
        )


async def _mapping(sessions, *, resource_type, local_id, tombstoned=False):
    async with sessions() as db, db.begin():
        db.add(
            Mapping(
                tenant_id=1,
                space_id=10,
                generation=1,
                resource_type=resource_type,
                local_resource_id=local_id,
                remote_object_id=f"remote:{resource_type}:{local_id}",
                lifecycle_state="tombstoned" if tombstoned else "active",
                tombstoned_at=datetime(2026, 11, 26) if tombstoned else None,
            )
        )


def scope(*ids):
    return NS(resources=[NS(id=ident) for ident in ids])


async def test_native_space_is_never_restricted(sessions):
    await _binding(sessions, provider_key="native", generation=None)
    async with sessions() as db:
        with tenant_execution_scope(1):
            await WikiControl.require_provider_safe_deletion(db, 10, "knowledge_space_delete")
            await WikiControl.require_deletable_targets(db, 10, scope(47, 48))


async def test_whole_space_purge_of_a_provider_space_is_refused(sessions):
    await _binding(sessions)
    async with sessions() as db:
        with tenant_execution_scope(1):
            with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
                await WikiControl.require_provider_safe_deletion(db, 10, "knowledge_space_clear")
    assert caught.value.kwargs["reason"] == "external_deletion_requires_provider_operation"


async def test_provider_space_deletion_is_allowed_because_mappings_retire_locally(sessions):
    await _binding(sessions)
    async with sessions() as db:
        with tenant_execution_scope(1):
            await WikiControl.require_provider_safe_deletion(db, 10, "knowledge_space_delete")


async def test_only_externally_bound_spaces_are_reported_as_provider_spaces(sessions):
    await _binding(sessions, provider_key="native", generation=None)
    async with sessions() as db:
        with tenant_execution_scope(1):
            assert await WikiControl.is_externally_bound(db, 10) is False
    await _binding(sessions, space_id=11)
    async with sessions() as db:
        with tenant_execution_scope(1):
            assert await WikiControl.is_externally_bound(db, 11) is True


async def test_file_delete_is_allowed_once_remote_is_addressable(sessions):
    await _binding(sessions)
    await _mapping(sessions, resource_type="file", local_id=41)
    async with sessions() as db:
        with tenant_execution_scope(1):
            await WikiControl.require_deletable_targets(db, 10, scope(41))


async def test_delete_is_refused_while_a_provider_write_is_in_flight(sessions):
    await _binding(sessions, pending="op-in-flight")
    async with sessions() as db:
        with tenant_execution_scope(1):
            with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
                await WikiControl.require_deletable_targets(db, 10, scope(41))
    assert caught.value.kwargs["reason"] == "external_deletion_pending_write"


async def test_retire_drops_folder_mappings_and_tombstones_files(sessions):
    await _binding(sessions)
    await _mapping(sessions, resource_type="folder", local_id=47)
    await _mapping(sessions, resource_type="file", local_id=41)
    async with sessions() as db, db.begin():
        with tenant_execution_scope(1):
            await WikiControl.aretire_provider_rows(db, 10, (41, 47), (37,))
    async with sessions() as db:
        rows = {row.local_resource_id: row for row in (await db.execute(select(Mapping))).scalars()}
    assert set(rows) == {41}
    assert rows[41].lifecycle_state == "tombstoned" and rows[41].tombstoned_at is not None


async def test_retire_releases_charged_bytes_once(sessions):
    await _binding(sessions)
    async with sessions() as db, db.begin():
        for kind, subject, state in (("tenant", 1, "charged"), ("user", 1, "reserved")):
            db.add(
                Quota(
                    tenant_id=1,
                    operation_id="op-1",
                    space_id=10,
                    version_id=37,
                    subject_type=kind,
                    subject_id=subject,
                    accounting_kind="original_bytes",
                    byte_count=100,
                    state=state,
                )
            )
    async with sessions() as db, db.begin():
        with tenant_execution_scope(1):
            await WikiControl.aretire_provider_rows(db, 10, (41,), (37,))
    async with sessions() as db:
        rows = (await db.execute(select(Quota))).scalars().all()
    assert {row.state for row in rows} == {"released"}


async def test_collect_targets_skips_tombstones_and_other_spaces(sessions, monkeypatch):
    monkeypatch.setattr(provider_deletion, "get_async_db_session", sessions)
    monkeypatch.setattr(provider_deletion, "_unseal_upload_secret", lambda ref: "s" * 40)
    await _mapping(sessions, resource_type="file", local_id=41)
    await _mapping(sessions, resource_type="file", local_id=44, tombstoned=True)
    async with sessions() as db, db.begin():
        db.add(
            Instance(
                tenant_id=1,
                provider_key="weknora",
                endpoint="http://wk.test",
                credential_ref="fernet:key",
                remote_scope_id="10000",
                state="ready",
            )
        )
    async with sessions() as db, db.begin():
        db.add(
            Generation(
                tenant_id=1,
                space_id=10,
                generation=1,
                provider_instance_id=1,
                remote_scope_id="10000",
                remote_kb_id="kb-1",
                state="ready",
            )
        )
    targets = await provider_deletion.collect_targets(tenant_id=1, space_id=10, file_ids=(41, 44))
    assert [target.file_id for target in targets] == [41]
    assert targets[0].remote_id == "remote:file:41"
    assert targets[0].remote_kb_id == "kb-1"


async def test_retire_remote_documents_accepts_async_delete(monkeypatch):
    seen = []

    def handle(request: httpx.Request):
        seen.append((request.method, request.url.path, request.headers.get("X-External-User-Token")))
        return httpx.Response(202, json={"success": True, "data": {"task_id": "t1"}})

    async def targets(**kwargs):
        return (
            provider_deletion.RemoteTarget(
                file_id=41,
                remote_id="remote-doc-41",
                generation=1,
                instance_id=1,
                remote_scope_id="10000",
                remote_kb_id="kb-1",
                upload_secret="0" * 48,
            ),
        )

    async def params(route):
        return {
            "base_url": "https://wk.test/api/v1/",
            "headers": {"X-API-Key": "api-key"},
            "transport": httpx.MockTransport(handle),
            "trust_env": False,
            "follow_redirects": False,
        }

    monkeypatch.setattr(provider_deletion, "collect_targets", targets)
    monkeypatch.setattr(provider_deletion, "_instance_http_params", params)
    assert await provider_deletion.retire_remote_documents(tenant_id=1, space_id=10, file_ids=(41,), user_id=7) == 1
    assert seen == [("DELETE", "/api/v1/knowledge/remote-doc-41", seen[0][2])]
    assert seen[0][2]


async def test_retire_remote_documents_treats_404_as_final(monkeypatch):
    async def targets(**kwargs):
        return (
            provider_deletion.RemoteTarget(
                file_id=41,
                remote_id="gone",
                generation=1,
                instance_id=1,
                remote_scope_id="10000",
                remote_kb_id="kb-1",
                upload_secret="0" * 48,
            ),
        )

    async def params(route):
        return {
            "base_url": "https://wk.test/api/v1/",
            "headers": {},
            "transport": httpx.MockTransport(lambda request: httpx.Response(404)),
            "trust_env": False,
            "follow_redirects": False,
        }

    monkeypatch.setattr(provider_deletion, "collect_targets", targets)
    monkeypatch.setattr(provider_deletion, "_instance_http_params", params)
    assert await provider_deletion.retire_remote_documents(tenant_id=1, space_id=10, file_ids=(41,), user_id=7) == 1


async def test_retire_remote_documents_propagates_a_refused_delete(monkeypatch):
    async def targets(**kwargs):
        return (
            provider_deletion.RemoteTarget(
                file_id=41,
                remote_id="doc",
                generation=1,
                instance_id=1,
                remote_scope_id="10000",
                remote_kb_id="kb-1",
                upload_secret="0" * 48,
            ),
        )

    async def params(route):
        return {
            "base_url": "https://wk.test/api/v1/",
            "headers": {},
            "transport": httpx.MockTransport(lambda request: httpx.Response(403)),
            "trust_env": False,
            "follow_redirects": False,
        }

    monkeypatch.setattr(provider_deletion, "collect_targets", targets)
    monkeypatch.setattr(provider_deletion, "_instance_http_params", params)
    with pytest.raises(provider_deletion.ProviderFeatureUnavailable):
        await provider_deletion.retire_remote_documents(tenant_id=1, space_id=10, file_ids=(41,), user_id=7)


async def test_purge_skips_local_index_steps_for_a_provider_space(sessions):
    """A WeKnora space owns no local ES index / Milvus collection to clean."""
    from bisheng.knowledge.domain.services.knowledge_space_direct_delete_service import (
        KnowledgeSpaceDirectDeleteService,
    )

    await _binding(sessions)
    service = KnowledgeSpaceDirectDeleteService(session_factory=sessions)
    job = NS(
        tenant_id=1,
        space_id=10,
        operation_type="knowledge_file_delete",
        state="RUNNING",
        manifest={"file_ids": [41], "object_names": [], "knowledge": {}, "documents": []},
    )

    assert await service._provider_owned(job) is True
    # The step returns before touching Milvus (which would raise for an empty collection).
    await service._purge_step("milvus", job)


async def test_purge_keeps_local_index_steps_for_a_native_space(sessions):
    from bisheng.knowledge.domain.services.knowledge_space_direct_delete_service import (
        KnowledgeSpaceDirectDeleteService,
    )

    await _binding(sessions, provider_key="native", generation=None)
    service = KnowledgeSpaceDirectDeleteService(session_factory=sessions)
    job = NS(tenant_id=1, space_id=10, operation_type="knowledge_file_delete", state="RUNNING")
    assert await service._provider_owned(job) is False


async def test_purge_treats_a_missing_binding_as_native(sessions):
    from bisheng.knowledge.domain.services.knowledge_space_direct_delete_service import (
        KnowledgeSpaceDirectDeleteService,
    )

    service = KnowledgeSpaceDirectDeleteService(session_factory=sessions)
    job = NS(tenant_id=1, space_id=99, operation_type="knowledge_file_delete", state="RUNNING")
    assert await service._provider_owned(job) is False


async def _library_facts(sessions, *, space_id=10, generation=1, kb="kb-1", state="ready"):
    async with sessions() as db, db.begin():
        db.add(
            Instance(
                tenant_id=1,
                provider_key="weknora",
                endpoint="https://wk.test",
                credential_ref="fernet:key",
                upload_credential_ref=None,
                remote_scope_id="10000",
                state="ready",
            )
        )
        db.add(
            Generation(
                tenant_id=1,
                space_id=space_id,
                generation=generation,
                provider_instance_id=1,
                remote_scope_id="10000",
                remote_kb_id=kb,
                state=state,
            )
        )


async def test_whole_space_delete_retires_the_remote_library(sessions, monkeypatch):
    await _binding(sessions)
    await _library_facts(sessions)
    seen = []

    def handle(request: httpx.Request):
        seen.append((request.method, request.url.path))
        return httpx.Response(202, json={"success": True, "data": {"task_id": "t1"}})

    monkeypatch.setattr(provider_deletion, "get_async_db_session", sessions)
    # ``_client_parameters`` is imported inside the call, so patch its own module.
    import bisheng.knowledge.application.provider_v1_runtime as runtime

    monkeypatch.setattr(
        runtime,
        "_client_parameters",
        lambda *a, **k: {
            "base_url": "https://wk.test/api/v1/",
            "headers": {"X-API-Key": "api-key"},
            "transport": httpx.MockTransport(handle),
            "trust_env": False,
            "follow_redirects": False,
        },
    )
    assert await provider_deletion.retire_remote_library(tenant_id=1, space_id=10, user_id=7) == 1
    assert seen == [("DELETE", "/api/v1/knowledge-bases/kb-1")]


async def test_native_space_has_no_remote_library_to_retire(sessions, monkeypatch):
    await _binding(sessions, provider_key="native", generation=None)
    monkeypatch.setattr(provider_deletion, "get_async_db_session", sessions)
    assert await provider_deletion.collect_library(tenant_id=1, space_id=10) is None
    assert await provider_deletion.retire_remote_library(tenant_id=1, space_id=10, user_id=7) == 0


async def test_unfinished_creation_still_owns_its_library(sessions, monkeypatch):
    """A space whose create never confirmed still has a remote library to clean up."""
    await _binding(sessions, generation=None)
    await _library_facts(sessions, state="provisioning")
    monkeypatch.setattr(provider_deletion, "get_async_db_session", sessions)
    target = await provider_deletion.collect_library(tenant_id=1, space_id=10)
    assert target is not None and target.remote_id == "kb-1"


async def test_retiring_a_library_treats_404_as_final(sessions, monkeypatch):
    await _binding(sessions)
    await _library_facts(sessions, kb="already-gone")
    monkeypatch.setattr(provider_deletion, "get_async_db_session", sessions)
    import bisheng.knowledge.application.provider_v1_runtime as runtime

    monkeypatch.setattr(
        runtime,
        "_client_parameters",
        lambda *a, **k: {
            "base_url": "https://wk.test/api/v1/",
            "headers": {},
            "transport": httpx.MockTransport(lambda request: httpx.Response(404)),
            "trust_env": False,
            "follow_redirects": False,
        },
    )
    assert await provider_deletion.retire_remote_library(tenant_id=1, space_id=10, user_id=7) == 1


async def test_a_refused_library_delete_stops_the_local_cutover(sessions, monkeypatch):
    await _binding(sessions)
    await _library_facts(sessions)
    monkeypatch.setattr(provider_deletion, "get_async_db_session", sessions)
    import bisheng.knowledge.application.provider_v1_runtime as runtime

    monkeypatch.setattr(
        runtime,
        "_client_parameters",
        lambda *a, **k: {
            "base_url": "https://wk.test/api/v1/",
            "headers": {},
            "transport": httpx.MockTransport(lambda request: httpx.Response(500)),
            "trust_env": False,
            "follow_redirects": False,
        },
    )
    with pytest.raises(provider_deletion.ProviderFeatureUnavailable):
        await provider_deletion.retire_remote_library(tenant_id=1, space_id=10, user_id=7)


@pytest.mark.parametrize(
    "operation, expected",
    [
        ("knowledge_space_delete", True),
        ("knowledge_space_clear", False),
        ("knowledge_file_delete", False),
    ],
)
def test_only_a_whole_space_delete_retires_the_remote_library(operation, expected):
    from bisheng.knowledge.application.knowledge_deletion import KnowledgeDeletionApplication

    job = NS(operation_type=operation)
    assert KnowledgeDeletionApplication._retires_remote_library(job) is expected
