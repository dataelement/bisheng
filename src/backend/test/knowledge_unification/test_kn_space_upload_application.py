"""T897: genuine preparation, native registration and original permission records."""

import asyncio
import importlib
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.api.services import knowledge_imp
from bisheng.api.v1.schemas import FileProcessBase, KnowledgeFileOne
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    KnowledgeProcessingConflictError,
    ResourceReferenceInvalidError,
)
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.core.context import tenant as context
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState
from bisheng.knowledge.domain.models.knowledge_file import FileSource
from bisheng.knowledge.domain.services.knowledge_permission_service import F048KnowledgeFilePermissionAdapter
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.application.identity import (
    PermissionActor,
    reset_current_permission_actor,
    set_current_permission_actor,
)
from test.knowledge_unification import test_kn_upload_registration_repository as original
from test.knowledge_unification.test_file_worker import source_module

native = original.native
database = original.database


@pytest.fixture
async def case(database, monkeypatch, tmp_path):
    import bisheng.common.services.base as base

    backend = Path(__file__).resolve().parents[2]
    actual_base = source_module("_space_upload_actual_base", backend / "bisheng/common/services/base.py")
    monkeypatch.setattr(base, "BaseService", actual_base.BaseService)
    actual_utils = source_module(
        "_space_upload_actual_utils", backend / "bisheng/knowledge/domain/services/knowledge_utils.py"
    ).KnowledgeUtils
    user = UserPayload(user_id=7, user_name="original", tenant_id=101, user_role=[])
    actor = PermissionActor(user_id=7, tenant_id=101)
    token = set_current_permission_actor(actor)
    source = tmp_path / "realmd5_original.txt"
    source.write_text("actual source\n", encoding="utf-8")
    monkeypatch.setattr(knowledge_imp, "KnowledgeUtils", actual_utils)
    legacy = source_module(
        "_space_upload_actual_preparation",
        Path(__file__).resolve().parents[2] / "bisheng/knowledge/domain/services/knowledge_service.py",
    )
    monkeypatch.setattr(legacy, "file_download", lambda _path: (str(source), "download.txt"))
    monkeypatch.setattr(legacy, "get_redis_client_sync", lambda: SimpleNamespace(get=lambda _key: None))
    async with AsyncSession(database.engine, expire_on_commit=False) as session, session.begin():
        knowledge = await session.get(Knowledge, 9700)
    prepared = legacy.KnowledgeService.prepare_one_file(
        user,
        knowledge,
        KnowledgeFileOne(file_path="private-input"),
        {},
        processing_rule_request=FileProcessBase(knowledge_id=9700, chunk_size=123, force_ocr=0),
    )
    service = KnowledgeSpaceService(None, user)
    value = SimpleNamespace(
        database=database,
        user=user,
        actor=actor,
        knowledge=knowledge,
        prepared=prepared,
        legacy=legacy,
        utils=actual_utils,
        events=[],
        sessions=[],
        active=[],
        allowed={"upload_file"},
        fail=None,
        fail_commit=None,
        commit_count=0,
        blobs={},
        projection=set(),
        inverse_hook=None,
    )

    class Native(AsyncSession):
        async def commit(self):
            value.commit_count += 1
            hit = value.fail_commit and value.commit_count == value.fail_commit[0]
            if hit and value.fail_commit[1] == "before":
                raise OSError("commit ACK unknown before SQL commit")
            await super().commit()
            if hit:
                raise OSError("commit ACK unknown after SQL commit")

    @asynccontextmanager
    async def sessions():
        async with Native(database.engine) as session:
            value.sessions.append(session)
            value.active.append(session)
            try:
                yield session
            finally:
                value.active.remove(session)

    value.factory = sessions

    def io(stage):
        assert not value.active and not any(session.in_transaction() for session in value.sessions)
        value.events.append(stage)
        if value.fail == stage:
            raise OSError(stage)
        if value.fail == "cancel:" + stage:
            raise asyncio.CancelledError()

    async def check(resource_type, resource_id, action):
        value.events.append((resource_type, resource_id, action))
        assert not value.active
        return action in value.allowed

    service._check_action = check
    value.admit, value.actor_provider = service._require_action, service._permission_actor
    value.make_record = KnowledgeSpaceService._new_file_permission_record

    def put(**kwargs):
        io("put")
        value.blobs[kwargs["object_name"]] = Path(kwargs["file"]).read_bytes()

    def remove(**kwargs):
        io("remove")
        value.blobs.pop(kwargs["object_name"], None)

    value.storage = SimpleNamespace(bucket="owned", put_object_sync=put, remove_object_sync=remove)
    monkeypatch.setattr(
        legacy.KnowledgeService,
        "audit_telemetry_service",
        SimpleNamespace(telemetry_new_knowledge_file=lambda _user: io("telemetry")),
    )
    monkeypatch.setattr(legacy.KnowledgeService, "remove_unused_file", lambda _path: io("tmp"))

    async def project(**kwargs):
        io("project")
        assert kwargs["actor"] is value.actor and kwargs["owner_user_id"] == user.user_id
        value.projection.add(int(kwargs["target"].resource_id))

    async def inverse(**kwargs):
        io("inverse")
        assert kwargs["actor"] is value.actor
        if value.inverse_hook:
            await value.inverse_hook()
        value.projection.discard(int(kwargs["target"].resource_id))

    value.adapter = F048KnowledgeFilePermissionAdapter(
        loader=None,
        permission=SimpleNamespace(
            authorize_created=AsyncMock(side_effect=project), rollback_created=AsyncMock(side_effect=inverse)
        ),
    )
    value.io = io
    try:
        yield value
    finally:
        reset_current_permission_actor(token)


def app(case, monkeypatch):
    module = importlib.import_module("bisheng.knowledge.application.space_upload")
    monkeypatch.setattr(module, "KnowledgeService", case.legacy.KnowledgeService)
    monkeypatch.setattr(module, "KnowledgeUtils", case.utils)
    monkeypatch.setattr(module, "get_minio_storage_sync", lambda: case.storage)
    monkeypatch.setattr(module, "get_f048_resource_adapter", AsyncMock(return_value=case.adapter))
    return module.SpaceUploadApplication(
        login_user=case.user,
        session_factory=case.factory,
        admit_upload=case.admit,
        make_permission_record=case.make_record,
        actor_provider=case.actor_provider,
    )


async def create(application, case, *, parent_id=None):
    return await application.acreate_file(
        knowledge=case.knowledge, parent_id=parent_id, prepared=case.prepared, file_source=FileSource.SPACE_UPLOAD
    )


def new_rows(snapshot, file_id):
    file = next(row for row in snapshot["knowledgefile"] if row["id"] == file_id)
    version = next(row for row in snapshot["knowledge_document_version"] if row["knowledge_file_id"] == file_id)
    document = next(row for row in snapshot["knowledge_document"] if row["id"] == version["document_id"])
    assert document["primary_version_id"] == version["id"] and version["version_no"] == 1 and version["is_primary"]
    return file, document, version


@pytest.mark.parametrize("parent", [None, 11])
async def test_genuine_prepared_snapshot_native_v1_key_and_original_container_action(case, monkeypatch, parent):
    application = app(case, monkeypatch)
    before = await original.snapshot(case.database)
    result = await create(application, case, parent_id=parent)
    after = await original.snapshot(case.database)
    file, document, version = new_rows(after, result.id)
    assert result.id > 90 and result.split_rule == case.prepared.split_rule
    assert (file["file_source"], file["file_size"], file["md5"], file["status"]) == (
        "space_upload",
        case.prepared.file_size,
        case.prepared.md5,
        5,
    )
    assert file["object_name"] == case.utils.get_knowledge_file_object_name(result.id, result.file_name)
    assert case.blobs[file["object_name"]] == Path(case.prepared.local_path).read_bytes()
    assert (document["file_level_path"], file["file_level_path"]) == (("/10/11", "/10/11") if parent else ("", ""))
    assert case.events == [
        ("folder" if parent else "knowledge_space", parent or 9700, "upload_file"),
        "telemetry",
        "put",
        "tmp",
        "project",
    ]
    target = case.adapter._permission.authorize_created.await_args.kwargs["target"]
    assert (target.resource_type, target.parent_type, target.parent_id) == (
        "knowledge_file",
        "folder" if parent else "knowledge_space",
        str(parent or 9700),
    )
    assert version["create_time"] and document["update_time"] and file["create_time"] == file["update_time"]
    for key in before:
        old_ids = {row["id"] for row in before[key]}
        assert tuple(row for row in after[key] if row["id"] in old_ids) == before[key]
    assert not case.active and all(not session.in_transaction() for session in case.sessions)


async def test_visible_only_cannot_register_and_no_business_session_is_opened(case, monkeypatch):
    application = app(case, monkeypatch)
    case.allowed = {"visible"}
    case.database.queries.clear()
    with pytest.raises(SpacePermissionDeniedError):
        await create(application, case)
    assert not case.sessions and not case.database.queries
    assert case.events == [("knowledge_space", 9700, "upload_file")]


@pytest.mark.parametrize(
    "change", [{"state": KnowledgeState.REBUILDING.value}, {"model_transition": {"state": "rebuilding"}}]
)
async def test_root_idle_uses_current_locked_sql_instead_of_the_stale_passed_root(case, monkeypatch, change):
    application = app(case, monkeypatch)
    async with case.database.engine.begin() as conn:
        await conn.execute(sa.update(Knowledge.__table__).where(Knowledge.id == 9700).values(**change))
    before = await original.snapshot(case.database)
    with pytest.raises(KnowledgeProcessingConflictError):
        await create(application, case)
    assert await original.snapshot(case.database) == before and not case.blobs


@pytest.mark.parametrize("parent", [0, True, 20, 21, 30, 90, 999])
async def test_invalid_foreign_or_wrong_parent_never_leaves_a_chain_or_external_io(case, monkeypatch, parent):
    application = app(case, monkeypatch)
    before = await original.snapshot(case.database)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await create(application, case, parent_id=parent)
    assert await original.snapshot(case.database) == before and not case.blobs and "put" not in case.events


@pytest.mark.parametrize("mode", ["foreign", "home_mismatch", "narrowed_super", "service_account_cross_home"])
async def test_scope_mismatch_is_rejected_before_business_sql_without_rewriting_actor_or_user(case, monkeypatch, mode):
    application = app(case, monkeypatch)
    user_before = case.user.model_dump()
    if mode == "foreign":
        token = context.set_current_tenant_id(202)
    else:
        token = context.set_current_tenant_id(101)
        case.user.tenant_id = 1
        case.user.is_global_super = mode == "narrowed_super"
        case.actor = PermissionActor(
            subject_type="service_account" if mode == "service_account_cross_home" else "user",
            subject_id=7,
            tenant_id=1,
            super_admin=mode == "narrowed_super",
            data_scope="personal_only",
        )
    actor_token = set_current_permission_actor(case.actor)
    try:
        case.database.queries.clear()
        with pytest.raises(ResourceReferenceInvalidError):
            await create(application, case)
        assert not case.sessions and not case.database.queries and not case.blobs
        assert case.user.tenant_id == (user_before["tenant_id"] if mode == "foreign" else 1)
    finally:
        reset_current_permission_actor(actor_token)
        context.current_tenant_id.reset(token)


async def test_full_scope_super_preserves_home_with_the_original_trusted_selected_pin(case, monkeypatch):
    case.user.tenant_id, case.user.is_global_super = 1, True
    case.actor = PermissionActor(user_id=7, tenant_id=1, super_admin=True)
    token = set_current_permission_actor(case.actor)
    flag = context.set_is_management_api(True)
    pin = context.set_admin_scope_tenant_id(101)
    try:
        application = app(case, monkeypatch)
        result = await create(application, case)
        assert result.tenant_id == 101 and case.user.tenant_id == case.actor.current_tenant_id == 1
        assert case.adapter._permission.authorize_created.await_args.kwargs["actor"] is case.actor
    finally:
        context._admin_scope_tenant_id.reset(pin)
        context._is_management_api.reset(flag)
        reset_current_permission_actor(token)


@pytest.mark.parametrize("position", ["before", "after"])
async def test_commit_unknown_stops_before_external_io_and_never_acks_or_guesses_compensation(
    case, monkeypatch, position
):
    application = app(case, monkeypatch)
    case.fail_commit = (1, position)
    with pytest.raises(OSError) as caught:
        await create(application, case)
    assert "telemetry" not in case.events and not case.blobs
    progress = caught.value.space_upload_progress
    assert progress and "private-input" not in repr(progress) and case.prepared.split_rule not in repr(progress)
    assert not case.active and all(not session.in_transaction() for session in case.sessions)
    persisted = await original.snapshot(case.database)
    assert len(persisted["knowledge_document"]) == (2 if position == "after" else 1)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await application.arollback_created()
    assert "inverse" not in case.events and "remove" not in case.events


@pytest.mark.parametrize("failure", ["telemetry", "put", "tmp", "project", "cancel:project"])
async def test_known_ack_failed_upload_is_reclaimed_sql_first_then_only_owned_blob(case, monkeypatch, failure):
    application = app(case, monkeypatch)
    before = await original.snapshot(case.database)
    case.fail = failure
    expected = asyncio.CancelledError if failure.startswith("cancel:") else OSError
    with pytest.raises(expected) as caught:
        await create(application, case)
    assert caught.value.space_upload_progress
    case.fail = None
    await application.arollback_created()
    assert await original.snapshot(case.database) == before and not case.blobs and not case.projection
    assert "inverse" in case.events
    if "remove" in case.events:
        assert case.events.index("inverse") < case.events.index("remove")


async def test_same_application_rolls_back_the_actual_acknowledged_prefix_in_reverse_order(case, monkeypatch):
    application = app(case, monkeypatch)
    before = await original.snapshot(case.database)
    first = await create(application, case)
    case.fail = "project"
    with pytest.raises(OSError):
        await create(application, case)
    case.fail = None
    await application.arollback_created()
    assert await original.snapshot(case.database) == before and not case.blobs
    calls = case.adapter._permission.rollback_created.await_args_list
    assert [int(call.kwargs["target"].resource_id) for call in calls] == [first.id + 1, first.id]


@pytest.mark.parametrize("failure", ["inverse", "delete_before", "delete_after", "rename", "history", "identity"])
async def test_uncertain_or_changed_cleanup_preserves_owned_blob_and_never_deletes_a_foreign_chain(
    case, monkeypatch, failure
):
    application = app(case, monkeypatch)
    row = await create(application, case)
    if failure == "inverse":
        case.fail = "inverse"
    elif failure.startswith("delete_"):
        case.fail_commit = (case.commit_count + 1, failure.split("_")[1])
    elif failure == "identity":
        case.user.token_version += 1
    else:
        existing = await original.snapshot(case.database)
        async with case.database.engine.begin() as conn:
            if failure == "rename":
                await conn.execute(
                    sa.update(original.File.__table__).where(original.File.id == row.id).values(file_name="changed")
                )
            else:
                await conn.execute(
                    original.Version.__table__.insert(),
                    {
                        "document_id": next(
                            r["document_id"]
                            for r in existing["knowledge_document_version"]
                            if r["knowledge_file_id"] == row.id
                        ),
                        "knowledge_file_id": 90,
                        "version_no": 2,
                        "is_primary": False,
                    },
                )
    with pytest.raises((OSError, KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError)):
        await application.arollback_created()
    assert row.object_name in case.blobs and "remove" not in case.events


async def test_native_change_during_external_inverse_is_rejected_by_the_second_fresh_rebind(case, monkeypatch):
    application = app(case, monkeypatch)
    row = await create(application, case)

    async def changed():
        async with case.database.engine.begin() as conn:
            await conn.execute(
                sa.update(original.File.__table__).where(original.File.id == row.id).values(file_name="during inverse")
            )

    case.inverse_hook = changed
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await application.arollback_created()
    assert row.object_name in case.blobs and "remove" not in case.events


async def test_management_pin_or_credential_drift_before_io_blocks_reclaim(case, monkeypatch):
    application = app(case, monkeypatch)
    row = await create(application, case)
    flag = context.set_is_management_api(True)
    pin = context.set_admin_scope_tenant_id(101)
    try:
        before = list(case.events)
        with pytest.raises(ResourceReferenceInvalidError):
            await application.arollback_created()
        assert case.events == before and row.object_name in case.blobs
    finally:
        context._admin_scope_tenant_id.reset(pin)
        context._is_management_api.reset(flag)
