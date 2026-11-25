"""Service contracts: claim-scoped recovery, not router or provider transport tests."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def api():
    from bisheng.knowledge.application import provider_provisioning

    return provider_provisioning


def catalog():
    m = api().ModelProof
    return {
        k: m(k, kind, "v1", 7, "org", True, dimension, images)
        for k, kind, dimension, images in [
            ("L", "chat", None, False),
            ("E", "embedding", 768, False),
            ("V", "vision", None, True),
        ]
    }


def proof(models=None):
    return api().PresetProof(
        catalog() if models is None else models,
        True,
        "controlled sample",
        ("label",),
        ("a", "b"),
        (("a", "related", "b"),),
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"relations": (("a", "related", "foreign"),)},
        {"nodes": ("a", "a")},
        {"graph_available": False},
        {"sample_text": ""},
    ],
)
def test_reject_invalid_extraction_preset(changes):
    with pytest.raises(ValueError):
        api().preflight(preset(), replace(proof(), **changes))


def preset(**changes):
    return replace(api().Preset(17, 7, "org", 3, "L", "E", "V", 512, 32), **changes)


@pytest.mark.parametrize(
    "model,change",
    [
        ("L", {"available": None}),
        ("E", {"dimension": 0}),
        ("E", {"kind": "chat"}),
        ("L", {"instance_id": 8}),
        ("V", {"images": False}),
        ("V", {"scope": "other"}),
    ],
)
def test_preflight_rejects_unproved_or_wrong_model(model, change):
    rows = catalog()
    rows[model] = replace(rows[model], **change)
    with pytest.raises(ValueError, match=model):
        api().preflight(preset(), proof(rows))


def test_preflight_freezes_uses_not_copies_of_summary():
    config = api().preflight(preset(), proof())
    assert config["embedding_dimension"] == 768 and config["embedding_version"] == "v1"
    assert config["summary_model_id"] == "L" and config["vision_model_id"] == "V"
    assert config["wiki_model_id"] is None and config["tag_model_id"] is None
    assert all(config[k] for k in ("wiki_enabled", "entities_enabled", "multimodal_enabled", "auto_tag_enabled"))
    assert config["chunk_size"] == 512 and config["type"] == "document"


async def test_stale_form_denied_before_any_remote_or_durable_write():
    remote, repo = AsyncMock(), AsyncMock()
    service = api().ProviderProvisioning(repo, remote, AsyncMock(return_value=True), AsyncMock())
    with pytest.raises(PermissionError):
        await service.create(
            tenant_id=18,
            expected_tenant=17,
            actor=3,
            key="q",
            space=api().SpaceSpec("personal"),
            preset=preset(),
            summary={},
        )
    assert not remote.mock_calls and not repo.mock_calls


async def test_member_read_only_revision_and_field_whitelist():
    repo, remote, auth = AsyncMock(), AsyncMock(), AsyncMock(return_value=True)
    s = api().ProviderProvisioning(repo, remote, auth, AsyncMock())
    repo.active_target.return_value = SimpleNamespace(
        remote_kb_id="k", provider_instance_id=7, remote_scope_id="org", revision=3, pending=None
    )
    remote.read_library.return_value = {
        "kb_id": "k",
        "instance_id": 7,
        "scope": "org",
        "config": {"summary_model_id": "L"},
    }
    assert (await s.read_settings(tenant_id=17, actor=3, space_id=5))["revision"] == 3
    auth.return_value = False
    args = {"tenant_id": 17, "expected_tenant": 17, "actor": 3, "space_id": 5, "key": "p", "expected_revision": 1}
    with pytest.raises(PermissionError):
        await s.settings(**args, patch={"summary_model_id": "B"})
    auth.return_value = True
    with pytest.raises(ValueError):
        await s.settings(**args, patch={"embedding_model_id": "B"})
    repo.reserve_settings.assert_not_awaited()


async def test_department_lost_ack_only_reads_original_id_before_grant():
    remote, repo, projector = AsyncMock(), AsyncMock(), AsyncMock(return_value=True)
    s = api().ProviderProvisioning(repo, remote, AsyncMock(return_value=True), projector)
    config = api().preflight(preset(), proof())
    for department, kb in [(1, "a"), (2, "b")]:
        op = SimpleNamespace(
            operation_id=kb,
            kind="create_space",
            remote_kb_id=kb,
            tenant_id=17,
            provider_instance_id=7,
            remote_scope_id="org",
            generation=1,
            space_id=department,
            actor_user_id=3,
            capability_revision=3,
            target_manifest=[{"department_id": department, "config": config, "name": kb}],
        )
        observed = {"kb_id": kb, "instance_id": 7, "scope": "org", "name": kb, "config": config}
        remote.read_library.return_value = observed
        if department == 2:
            remote.create_library.side_effect = TimeoutError()
        assert await s.send(op) == ("confirmed" if department == 1 else "unknown")
        if department == 2:
            assert projector.await_count == 1
            assert await s.reconcile(op) == "confirmed"
        assert await s.project(op) == "confirmed"
    assert remote.create_library.await_count == 2 and projector.await_count == 2
    assert [call.args[0].remote_kb_id for call in remote.read_library.await_args_list] == ["a", "b"]


async def test_durable_freeze_ready_barrier_and_single_unresolved_settings_write():
    from datetime import UTC, datetime, timedelta
    from uuid import UUID

    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from bisheng.common.models.space_channel_member import SpaceChannelMember
    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderBinding as Binding
    from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderGeneration as Gen
    from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderInstance as Instance
    from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderOperation as Op
    from bisheng.knowledge.domain.repositories.provider_provision_repository import ProvisionRepository

    engine = create_async_engine("sqlite+aiosqlite://")

    # sqlite3's legacy mode commits the first SAVEPOINT independently of the
    # outer transaction. Exercise the same real transaction boundaries as prod.
    @event.listens_for(engine.sync_engine, "begin")
    def explicit_begin(connection):
        connection.exec_driver_sql("BEGIN")

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repo = ProvisionRepository(sessions)
    remote, grant = AsyncMock(), AsyncMock(return_value=False)
    service = api().ProviderProvisioning(repo, remote, AsyncMock(return_value=True), grant)
    p = preset()
    config = api().preflight(p, proof())
    remote.probe_preset.return_value = proof()
    remote.probe_settings.return_value = (catalog(), 8)
    args = {
        "tenant_id": 17,
        "expected_tenant": 17,
        "actor": 3,
        "key": "personal",
        "space": api().SpaceSpec("private"),
        "preset": p,
        "summary": config,
    }
    try:
        async with engine.begin() as conn:
            for cls in [Knowledge, Instance, Op, Gen, Binding, SpaceChannelMember]:
                await conn.run_sync(cls.__table__.create)
        with tenant_execution_scope(17):
            async with sessions.begin() as s:
                s.add(
                    Instance(
                        id=7,
                        tenant_id=17,
                        provider_key="weknora",
                        remote_scope_id="org",
                        endpoint="fixture",
                        credential_ref="fixture",
                        capability_revision=3,
                    )
                )
            with pytest.raises(ValueError, match="provider preset changed"):
                await service.create(**args)
            async with sessions.begin() as s:
                instance = await s.get(Instance, 7)
                instance.state = "ready"
            first = await service.create(**args)
            assert UUID(first.remote_kb_id) and first.space_id
            replay = await service.create(**args)
            assert replay.operation_id == first.operation_id and replay.remote_kb_id == first.remote_kb_id
            assert remote.probe_preset.await_count == 2  # rejected admission plus fresh admission, not replay
            with pytest.raises(ValueError):
                await repo.active_target(17, first.space_id)
            async with sessions.begin() as s:
                row = await s.get(Op, first.operation_id)
                row.state = "sending"
                row.lease_token = "lease"
                row.lease_until = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5)
            await repo.require_send_target(row)
            async with sessions.begin() as s:
                row = await s.get(Op, first.operation_id)
                row.state = "applying"
            with pytest.raises(ValueError, match="stale"):
                await repo.require_send_target(row)
            assert await service.project(row) == "unknown"
            with pytest.raises(ValueError):
                await repo.active_target(17, first.space_id)
            grant.return_value = True
            assert await service.project(row) == "confirmed"
            t = await repo.active_target(17, first.space_id)
            settings = {
                "tenant_id": 17,
                "expected_tenant": 17,
                "actor": 3,
                "space_id": t.space_id,
                "key": "settings",
                "expected_revision": t.revision,
                "patch": {"wiki_model_id": "L"},
            }
            write = await service.settings(**settings)
            assert (await service.settings(**settings)).operation_id == write.operation_id
            with pytest.raises(ValueError, match="conflict"):
                await service.settings(**{**settings, "key": "other"})
            with pytest.raises(ValueError, match="conflict"):
                await repo.reserve_settings(t, 3, "race", "0" * 64, {"wiki_model_id": None}, 8)
            assert await repo.replay(17, "update_space_settings", "race", 3, "0" * 64) is None
            remote.read_library.return_value = {
                "instance_id": 7,
                "kb_id": first.remote_kb_id,
                "scope": "org",
                "config": {"wiki_model_id": "L"},
            }
            assert await service.reconcile(write) == "unknown"
            remote.read_library.return_value["applied_operation_id"] = write.operation_id
            assert await service.reconcile(write) == "unknown"
            remote.read_library.return_value.update(settings_digest=api().digest(settings["patch"]), settings_version=8)
            assert await service.reconcile(write) == "unknown"
            remote.read_library.return_value["settings_version"] = 9
            assert await service.reconcile(write) == "confirmed"
            async with sessions.begin() as s:
                write = await s.get(Op, write.operation_id)
                write.state = "applying"
                write.lease_token = "w"
                write.lease_until = row.lease_until
            assert await service.project(write) == "confirmed"
            assert (await repo.active_target(17, t.space_id)).revision == t.revision + 1
            with pytest.raises(ValueError, match="revision"):
                await service.settings(**{**settings, "key": "stale"})
    finally:
        await engine.dispose()


async def test_department_batch_isolates_archive_and_probe_timeout(monkeypatch):
    from bisheng.admin.application import tenant_scope
    from bisheng.knowledge.domain.services import department_knowledge_space_service as m

    service = m.DepartmentKnowledgeSpaceService
    monkeypatch.setattr(tenant_scope, "resolve_management_scope", AsyncMock(return_value=SimpleNamespace(tenant_id=17)))
    monkeypatch.setattr(tenant_scope, "require_expected_management_tenant", lambda expected, scope: None)
    monkeypatch.setattr(m, "get_current_tenant_id", lambda: 17)
    monkeypatch.setattr(service, "_ensure_tenant_admin", AsyncMock())

    async def departments(ids):
        if 1 in ids:
            raise m.DepartmentNotFoundError()

    monkeypatch.setattr(service, "_load_departments", departments)
    create = AsyncMock(side_effect=[TimeoutError(), SimpleNamespace(operation_id="last", state="pending")])
    result = await service.accept_external_spaces(
        login_user=SimpleNamespace(user_id=2, is_global_super=False),
        expected_tenant=17,
        items=[(api().SpaceSpec("space", i), {}) for i in (1, 2, 3)],
        preset=preset(),
        key="batch",
        provisioning=SimpleNamespace(create=create),
    )
    assert [item["department_id"] for item in result] == [1, 2, 3]
    assert all("operation_id" not in item for item in result[:2])
    assert result[2]["operation_id"] == "last"
    assert [call.kwargs["space"].department_id for call in create.await_args_list] == [2, 3]
