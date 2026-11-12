"""Approved original structural invalidity must never become new authority."""

import hashlib
from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.application.unification_conversion import UnificationSQLConversionApplication
from bisheng.knowledge.application.unification_inventory_codec import decode_inventory_page, record_from_values
from bisheng.knowledge.application.unification_structural_retention import (
    StructuralRetentionInventoryVerifier,
    absent_parent,
    creator_retention,
    stranded_retention,
)
from bisheng.permission.domain.models import PermissionGrant, ResourcePermissionMode
from test.knowledge_unification import test_migration_inventory_application as original
from test.knowledge_unification import test_migration_references_application as reference_tests
from test.knowledge_unification import test_migration_resource_repository as resources
from test.knowledge_unification.test_migration_legacy_index_retention import resource as old_resource

raw_resource_native = reference_tests.raw_resource_native
resource_native = reference_tests.resource_native
native = original.native
complete = original.complete
transport = original.transport
module = original.module


def root(user=999):
    value = old_resource().data | {"type": 3, "user_id": user}
    return record_from_values("resource", **value)


def file():
    return record_from_values(
        "file",
        id=2,
        tenant_id=101,
        knowledge_id=9000,
        file_type=1,
        level=1,
        file_level_path="/100",
        status=3,
        file_source="space_upload",
        file_size=10,
        object_name="retained.pdf",
        preview_file_object_name=None,
        bbox_object_name=None,
        thumbnails=None,
        html_snapshot_object_name=None,
        row_digest="a" * 64,
        split_rule_digest="b" * 64,
        user_metadata_digest="c" * 64,
    )


def validate(rows, proofs):
    check = StructuralRetentionInventoryVerifier()
    for section, record in rows:
        check.observe(kind="baseline", section=section, tenant_id=None if section == "fga" else 101, record=record)
    for proof in proofs:
        check.observe(kind="plan", section="control", tenant_id=101, record=proof)
    check.finish()


def test_existing_empty_space_creator_is_a_false_fact_and_never_reassigned():
    resource = root()
    creator = record_from_values("creator", user_id=999, exists=False, delete=None)
    proof = creator_retention(resource=resource.data, creator=creator.data, managed_file_count=0)
    validate((("resources", resource), ("control", creator)), (proof,))
    assert proof.data["creator_user_id"] == 999 and proof.data["managed_file_count"] == 0
    with pytest.raises(KnowledgeOperationPlanConflictError):
        validate((("resources", resource), ("control", creator)), ())


@pytest.mark.parametrize("change", ["normal", "nonempty", "owner", "present", "boolean_count"])
def test_missing_creator_exception_cannot_be_used_for_conversion_or_new_ownership(change):
    resource = root().data
    creator = {"user_id": 999, "exists": False, "delete": None}
    count = 0
    if change == "normal":
        resource = resource | {"type": 0}
    elif change == "nonempty":
        count = 1
    elif change == "owner":
        creator["user_id"] = 998
    elif change == "present":
        creator["exists"] = True
    else:
        count = False
    with pytest.raises(KnowledgeOperationPlanConflictError):
        creator_retention(resource=resource, creator=creator, managed_file_count=count)


@pytest.mark.parametrize(
    "change", ["valid", "permission", "fga", "parent", "success", "normal", "digest", "missing_proof"]
)
def test_failed_file_retention_is_closed_over_original_parent_and_absent_rights(change):
    resource, item = root(user=7), file()
    proof = stranded_retention(
        resource=resource.data, file=item.data, ancestor=absent_parent(100), sql_permission_count=0, fga_tuple_count=0
    )
    rows = [("resources", resource), ("resources", item)]
    if change == "permission":
        rows.append(
            (
                "permission",
                record_from_values(
                    "resource_mode",
                    id=2,
                    tenant_id=101,
                    resource_type="knowledge_file",
                    resource_id="2",
                    mode="INHERIT",
                    parent_type="knowledge_space",
                    parent_id="9000",
                    version=1,
                    projection_state="CURRENT",
                    operation_id=None,
                ),
            )
        )
    elif change == "fga":
        rows.append(
            ("fga", record_from_values("fga_tuple", user="user:7", relation="visible", object="knowledge_file:2"))
        )
    elif change == "parent":
        rows.append(
            (
                "resources",
                record_from_values(
                    "file", **(item.data | {"id": 100, "file_type": 0, "file_level_path": "", "level": 0})
                ),
            )
        )
    elif change == "success":
        rows[1] = ("resources", record_from_values("file", **(item.data | {"status": 2})))
    elif change == "normal":
        rows[0] = ("resources", record_from_values("resource", **(resource.data | {"type": 0})))
    elif change == "digest":
        proof = record_from_values("stranded_file_retention", **(proof.data | {"file_digest": "f" * 64}))
    proofs = () if change == "missing_proof" else (proof,)
    if change == "valid":
        validate(rows, proofs)
    else:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            validate(rows, proofs)


async def seed_existing(complete, *, stranded=False):
    await complete.insert(
        resources.Knowledge, [resources.resource(9001, type=3, user_id=7 if stranded else 999, model=None)]
    )
    await complete.insert(
        ResourcePermissionMode,
        [
            {
                "id": 9001,
                "tenant_id": 101,
                "resource_type": "knowledge_space",
                "resource_id": "9001",
                "mode": "CUSTOM",
                "version": 1,
                "projection_state": "CURRENT",
            }
        ],
    )
    if stranded:
        await complete.insert(
            resources.KnowledgeFile,
            [
                resources.file(
                    2, knowledge_id=9001, file_level_path="/99999", level=1, status=3, file_source="space_upload"
                )
            ],
        )


@pytest.fixture
async def actual(module, complete, transport, monkeypatch, request):
    stranded = getattr(request, "param", False)
    await seed_existing(complete, stranded=stranded)
    original_factory = transport.reader_factory
    transport.stranded_tuples = []

    @asynccontextmanager
    async def factory(catalog):
        async with original_factory(catalog) as reader:
            original_read = reader._client.read_tuples

            async def read(**kwargs):
                if kwargs.get("object") == "knowledge_file:2":
                    return list(transport.stranded_tuples)
                return await original_read(**kwargs)

            reader._client.read_tuples = read
            yield reader

    transport.reader_factory = factory
    inventory = original.application(module, transport)
    async with AsyncSession(complete.engine) as session, session.begin():
        frozen = await inventory.arun(session, **transport.inputs)

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(complete.engine, expire_on_commit=False) as session:
            yield session

    app = UnificationSQLConversionApplication(
        artifact_store=transport.store, session_factory=sessions, structural_reader_factory=transport.reader_factory
    )
    return complete, transport, inventory, frozen, app, stranded


@pytest.mark.parametrize("actual", [False, True], indirect=True)
async def test_native_m2_m3_and_resume_preserve_rows_and_never_create_permissions(actual):
    complete, transport, inventory, frozen, app, stranded = actual
    proofs = []
    async for page in inventory.aiter_frozen_pages(
        frozen,
        environment=transport.inputs["environment"],
        backup_ref=transport.inputs["backup_ref"],
        schema_ref=transport.inputs["schema_ref"],
    ):
        if page.kind == "plan" and page.section == "control":
            proofs.extend(
                decode_inventory_page(
                    page.content,
                    run_id=frozen.run_id,
                    section=page.section,
                    scope=page.scope,
                    tenant_id=page.tenant_id,
                    page_index=page.page_index,
                    kind=page.kind,
                ).records
            )
    assert len(proofs) == 1 and proofs[0].record_type == (
        "stranded_file_retention" if stranded else "existing_space_creator_retention"
    )
    with tenant_execution_scope(1):
        assert (await app.arun(**transport.inputs)).sql_complete
        assert (await app.arun(**transport.inputs)).sql_complete
    async with complete.engine.connect() as c:
        owner = (
            await c.execute(sa.select(resources.Knowledge.user_id).where(resources.Knowledge.id == 9001))
        ).scalar_one()
        assert owner == (7 if stranded else 999)
        if stranded:
            row = (
                (await c.execute(sa.select(resources.KnowledgeFile.__table__).where(resources.KnowledgeFile.id == 2)))
                .mappings()
                .one()
            )
            assert (row["file_level_path"], row["level"], row["status"]) == ("/99999", 1, 3)
            assert not (
                await c.execute(
                    sa.select(ResourcePermissionMode.id).where(
                        ResourcePermissionMode.resource_type == "knowledge_file",
                        ResourcePermissionMode.resource_id == "2",
                    )
                )
            ).all()
            assert not (
                await c.execute(
                    sa.select(PermissionGrant.id).where(
                        PermissionGrant.resource_type == "knowledge_file", PermissionGrant.resource_id == "2"
                    )
                )
            ).all()
        else:
            assert not (
                await c.execute(
                    sa.select(original.SpaceChannelMember.id).where(original.SpaceChannelMember.business_id == "9001")
                )
            ).all()


@pytest.mark.parametrize("actual", [True], indirect=True)
@pytest.mark.parametrize("change", ["status", "path", "parent", "permission", "fga"])
async def test_native_drift_rejects_before_any_tenant_conversion(actual, change, monkeypatch):
    complete, transport, _inventory, _frozen, app, _ = actual
    async with complete.engine.begin() as c:
        if change in {"status", "path"}:
            values = {"status": 2} if change == "status" else {"file_level_path": "", "level": 0}
            await c.execute(sa.update(resources.KnowledgeFile).where(resources.KnowledgeFile.id == 2).values(**values))
        elif change == "parent":
            await c.execute(
                sa.insert(resources.KnowledgeFile).values(**resources.file(99999, knowledge_id=9001, file_type=0))
            )
        elif change == "permission":
            await c.execute(
                sa.insert(ResourcePermissionMode).values(
                    id=2,
                    tenant_id=101,
                    resource_type="knowledge_file",
                    resource_id="2",
                    mode="INHERIT",
                    parent_type="knowledge_space",
                    parent_id="9001",
                    version=1,
                    projection_state="CURRENT",
                )
            )
    if change == "fga":
        transport.stranded_tuples = [{"user": "user:7", "relation": "visible", "object": "knowledge_file:2"}]
    from bisheng.common.errcode.base import BaseErrorCode

    with tenant_execution_scope(1), pytest.raises(BaseErrorCode):
        await app.arun(**transport.inputs)
    async with complete.engine.connect() as c:
        assert (
            await c.execute(sa.select(resources.Knowledge.type).where(resources.Knowledge.id == 9000))
        ).scalar_one() == 0
        assert set((await c.execute(sa.select(original.KnowledgeUnificationRun.phase))).scalars()) == {
            "baseline_frozen"
        }


@pytest.mark.parametrize("actual", [False], indirect=True)
@pytest.mark.parametrize("change", ["new_file", "creator_changed", "normal_conversion", "account_appeared"])
async def test_native_empty_space_creator_drift_rejects_before_conversion(actual, change):
    complete, transport, _inventory, _frozen, app, _stranded = actual
    async with complete.engine.begin() as c:
        if change == "new_file":
            await c.execute(sa.insert(resources.KnowledgeFile).values(**resources.file(2, knowledge_id=9001)))
        elif change == "creator_changed":
            await c.execute(sa.update(resources.Knowledge).where(resources.Knowledge.id == 9001).values(user_id=7))
        elif change == "normal_conversion":
            await c.execute(sa.update(resources.Knowledge).where(resources.Knowledge.id == 9001).values(type=0))
        else:
            from bisheng.user.domain.models.user import User

            await c.execute(
                sa.insert(User).values(
                    user_id=999, user_name="appeared", password=hashlib.sha256(b"fixture-only").hexdigest()
                )
            )
    from bisheng.common.errcode.base import BaseErrorCode

    with tenant_execution_scope(1), pytest.raises(BaseErrorCode):
        await app.arun(**transport.inputs)
    async with complete.engine.connect() as c:
        assert (
            await c.execute(sa.select(resources.Knowledge.type).where(resources.Knowledge.id == 9000))
        ).scalar_one() == 0


published_input = reference_tests.published_input


async def seed_missing_space_creator(database):
    await seed_existing(database, stranded=False)


async def seed_stranded_failed_file(database):
    await seed_existing(database, stranded=True)


@pytest.mark.parametrize(
    "published_input",
    [
        {"reference_seed": seed_missing_space_creator, "existing_mode_graph_from_seed": True},
        {"reference_seed": seed_stranded_failed_file, "existing_mode_graph_from_seed": True},
    ],
    indirect=True,
)
async def test_original_m4_closes_without_restoring_creator_or_file_access(published_input):
    from bisheng.knowledge.application.unification_coverage import production_coverage_factory

    value = published_input
    app = UnificationSQLConversionApplication(
        artifact_store=value.artifacts.store,
        session_factory=value.sessions,
        structural_reader_factory=value.artifacts.reader_factory,
    )
    first = await app.arun_references(**value.input, operator_id=7)
    assert first.complete
    value.sessions.assert_closed()
    assert await app.arun_references(**value.input, operator_id=7) == first
    assert not any(obj == "knowledge_file:2" for _user, _relation, obj in value.store.tuples)
    async with value.sessions() as session, session.begin():
        assert (
            await production_coverage_factory(session).arequire_global_ready()
        ).verified_tenant_ids == value.frozen.tenant_ids


def test_retained_missing_creator_cannot_authorize_another_source_kind():
    from bisheng.knowledge.application.unification_sources import RootInventoryRecord
    from bisheng.resource_reference.application.contracts import SourceRootKey

    resource = root()
    creator = record_from_values("creator", user_id=999, exists=False, delete=None)
    proof = creator_retention(resource=resource.data, creator=creator.data, managed_file_count=0)
    check = StructuralRetentionInventoryVerifier()
    check.observe(kind="baseline", section="resources", tenant_id=101, record=resource)
    check.observe(kind="baseline", section="control", tenant_id=101, record=creator)
    check.observe(kind="plan", section="control", tenant_id=101, record=proof)
    check.observe_source(RootInventoryRecord(SourceRootKey(101, "assistant", "other"), 999, (), "a" * 64, 1, "b" * 64))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        check.finish()


def test_stranded_file_with_saved_direct_reference_is_not_reactivated_by_compatibility():
    from bisheng.knowledge.application.unification_sources import ReferenceInventoryRecord
    from bisheng.knowledge.domain.repositories.unification_target_repository import KnowledgeMigrationTargetFact
    from bisheng.resource_reference.application.contracts import SourceKey, TargetKey

    resource, item = root(user=7), file()
    proof = stranded_retention(
        resource=resource.data, file=item.data, ancestor=absent_parent(100), sql_permission_count=0, fga_tuple_count=0
    )
    check = StructuralRetentionInventoryVerifier()
    check.observe(kind="baseline", section="resources", tenant_id=101, record=resource)
    check.observe(kind="baseline", section="resources", tenant_id=101, record=item)
    check.observe(kind="plan", section="control", tenant_id=101, record=proof)
    target = TargetKey("knowledge_file", "2")
    check.observe_source(
        ReferenceInventoryRecord(
            SourceKey(101, "workflow_version", "wf", "1"),
            "file",
            target,
            "explicit_id",
            KnowledgeMigrationTargetFact(target, True, 101, 9000, 3, 1, True, 101, "a" * 64),
        )
    )
    with pytest.raises(KnowledgeOperationPlanConflictError):
        check.finish()
