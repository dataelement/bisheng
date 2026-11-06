"""M2 resource facts over native SQL; no conversion or freeze authority."""

import hashlib
import importlib
import json
from dataclasses import FrozenInstanceError, fields
from datetime import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
    visible_tenant_ids,
)
from bisheng.core.database import tenant_filter
from bisheng.database.models.department import Department
from bisheng.database.models.tag import Tag, TagLink
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, QAKnowledge
from bisheng.knowledge.domain.models.knowledge_space_tag_library import KnowledgeSpaceTagLibrary

MODELS = {
    "resources": Knowledge,
    "files": KnowledgeFile,
    "documents": KnowledgeDocument,
    "versions": KnowledgeDocumentVersion,
    "qa": QAKnowledge,
    "tags": Tag,
    "tag_links": TagLink,
    "tag_libraries": KnowledgeSpaceTagLibrary,
    "department_spaces": DepartmentKnowledgeSpace,
}
NOW = datetime(2026, 11, 7, 1, 2, 3, 456)
OLD_RESOURCE = (
    "user_id",
    "tenant_id",
    "name",
    "type",
    "description",
    "model",
    "collection_name",
    "index_name",
    "state",
    "is_released",
    "auth_type",
    "is_shared",
    "auto_tag_enabled",
    "auto_tag_library_id",
    "metadata_fields",
    "create_time",
    "update_time",
    "id",
    "creation_request_id",
    "creation_payload_hash",
)


@pytest.fixture
def repo():
    return importlib.import_module(
        "bisheng.knowledge.domain.repositories.unification_resource_repository"
    ).UnificationResourceRepository()


@pytest.fixture
async def native(monkeypatch):
    models = (Tenant, Department, *MODELS.values())
    names = {model.__tablename__ for model in models if "tenant_id" in model.__table__.c}
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | names)
    tenant_filter.register_tenant_filter_events()
    token = set_current_tenant_id(101)
    engine = create_async_engine("sqlite+aiosqlite://")
    metadata = sa.MetaData()
    for model in models:
        table = model.__table__.to_metadata(metadata)
        if "tenant_id" in table.c:
            table.c.tenant_id.nullable = True  # corrupt legacy rows without mutating production ORM metadata
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.execute(
            Tenant.__table__.insert(),
            [{"id": ident, "tenant_code": f"t{ident}", "tenant_name": f"t{ident}"} for ident in (1, 101, 202)],
        )
    queries = []

    @sa.event.listens_for(engine.sync_engine, "before_cursor_execute")
    def statement_seen(_conn, _cursor, statement, parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append((statement, parameters))

    async def insert(model, rows):
        async with engine.begin() as connection:
            await connection.execute(model.__table__.insert(), rows)

    try:
        yield type("Native", (), {"engine": engine, "insert": staticmethod(insert), "queries": queries})()
    finally:
        current_tenant_id.reset(token)
        await engine.dispose()


def resource(ident, tenant=101, **changes):
    return {
        "id": ident,
        "tenant_id": tenant,
        "user_id": 7,
        "name": f"space-{ident}",
        "type": 0,
        "description": "original description",
        "model": "11",
        "collection_name": "original-vector",
        "index_name": "original-text",
        "state": 0,
        "is_released": False,
        "auth_type": "private",
        "is_shared": False,
        "auto_tag_enabled": False,
        "auto_tag_library_id": None,
        "metadata_fields": [{"name": "private-field", "type": "string"}],
        "create_time": NOW,
        "update_time": NOW,
        "creation_request_id": f"old-request-{ident}",
        "creation_payload_hash": "a" * 64,
        **changes,
    }


def file(ident, tenant=101, **changes):
    return {
        "id": ident,
        "tenant_id": tenant,
        "knowledge_id": 9000,
        "user_id": 7,
        "file_name": "private-name",
        "file_type": 1,
        "file_source": "upload",
        "status": 2,
        "level": 0,
        "file_level_path": None,
        "file_size": 5,
        "object_name": "original/object",
        "split_rule": "  exact original text  ",
        "user_metadata": {"private-value": "keep"},
        "abstract": "private-abstract",
        "remark": "private-remark",
        "create_time": NOW,
        "update_time": NOW,
        **changes,
    }


def data(kind, ident, tenant=101):
    common = {"id": ident, "tenant_id": tenant, "create_time": NOW, "update_time": NOW}
    return {
        "resources": lambda: resource(ident, tenant, type=ident % 5, creation_request_id=f"old-{ident}"),
        "files": lambda: file(ident, tenant),
        "documents": lambda: {
            "id": ident,
            "knowledge_id": 9000 if tenant == 101 else 8000,
            "file_level_path": None,
            "level": 0,
            "primary_version_id": None,
            "create_time": NOW,
            "update_time": NOW,
        },
        "versions": lambda: {
            "id": ident,
            "document_id": ident,
            "knowledge_file_id": ident,
            "version_no": 1,
            "is_primary": True,
            "create_time": NOW,
            "update_time": NOW,
        },
        "qa": lambda: {
            **common,
            "knowledge_id": 9000,
            "user_id": 7,
            "questions": ["private-question"],
            "answers": "private-answer",
            "status": 1,
        },
        "tags": lambda: {
            **common,
            "name": "private-tag",
            "business_type": "knowledge",
            "business_id": "9000",
            "user_id": 7,
        },
        "tag_links": lambda: {**common, "tag_id": ident, "resource_id": str(ident), "resource_type": 9, "user_id": 7},
        "tag_libraries": lambda: {
            **common,
            "name": "private-library",
            "description": "private-library-description",
            "tags": ["private-tag"],
            "tag_count": 1,
            "is_builtin": False,
            "user_id": 7,
        },
        "department_spaces": lambda: {
            **common,
            "department_id": ident,
            "space_id": ident,
            "created_by": 7,
            "approval_enabled": True,
            "sensitive_check_enabled": False,
            "is_hidden": False,
        },
    }[kind]()


async def collect(repo, kind, session):
    result, after = [], None
    while True:
        page = await getattr(repo, f"alist_{kind}")(session, after_id=after)
        assert type(page.items) is tuple and len(page.items) <= 200
        result.extend(page.items)
        if page.next_after is None:
            return result
        assert page.next_after == page.items[-1].id and page.next_after != after
        after = page.next_after


def test_nine_pagers_have_single_integer_pk_and_20_original_resource_columns():
    assert len(OLD_RESOURCE) == 20 and len(set(OLD_RESOURCE)) == 20
    for model in MODELS.values():
        assert tuple(model.__table__.primary_key.columns.keys()) == ("id",)
        assert isinstance(model.__table__.c.id.type, sa.Integer)


@pytest.mark.parametrize("kind", MODELS)
async def test_401_independent_pk_pages_preserve_all_rows_without_tenant_or_join_multiplication(repo, native, kind):
    if kind != "resources":
        await native.insert(Knowledge, [resource(9000), resource(8000, 202)])
    if kind == "versions":
        await native.insert(
            KnowledgeDocument, [data("documents", ident) for ident in range(1, 402)] + [data("documents", 402, 202)]
        )
        await native.insert(
            KnowledgeFile, [file(ident) for ident in range(1, 402)] + [file(402, 202, knowledge_id=8000)]
        )
    await native.insert(MODELS[kind], [data(kind, ident) for ident in range(1, 402)] + [data(kind, 402, 202)])
    async with AsyncSession(native.engine) as session, session.begin():
        rows = await collect(repo, kind, session)
    assert [row.id for row in rows] == list(range(1, 402))
    assert len(native.queries) == 3
    assert all("LIMIT" in sql.upper() and "OFFSET ?" in sql.upper() for sql, _ in native.queries)
    assert all(201 in parameters for _, parameters in native.queries)
    with pytest.raises(FrozenInstanceError):
        rows[0].id = 99
    assert not hasattr(rows[0], "__dict__")


async def test_original_20_digest_is_complete_and_neutral_seven_are_separate(repo, native):
    original = resource(1)
    await native.insert(Knowledge, [original])
    async with AsyncSession(native.engine) as session, session.begin():
        before = (await repo.alist_resources(session)).items[0]
        assert set(OLD_RESOURCE) <= {field.name for field in fields(before)}
        expected = {key: value.isoformat() if isinstance(value, datetime) else value for key, value in original.items()}
        digest = hashlib.sha256(
            json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        assert before.old_business_digest == digest
        assert before.metadata_fields == original["metadata_fields"]
        await session.execute(
            sa.update(Knowledge)
            .where(Knowledge.id == 1)
            .values(
                processing_defaults={"private-processing": "value"},
                processing_config_version=4,
                metadata_schema_revision=5,
                model_config_revision=6,
                model_transition={"private-transition": "value"},
                index_generation="generation",
                migration_origin="origin",
            )
        )
        after = (await repo.alist_resources(session)).items[0]
        assert after.old_business_digest == before.old_business_digest
        assert {field.name for field in fields(after.neutral)} == {
            "processing_defaults",
            "processing_config_version",
            "metadata_schema_revision",
            "model_config_revision",
            "model_transition",
            "index_generation",
            "migration_origin",
        }
        assert after.neutral.model_config_revision == 6
        assert "private-" not in repr(after)
        assert "private-" not in repr(after.neutral)
        await session.execute(
            sa.update(Knowledge).where(Knowledge.id == 1).values(creation_request_id="changed-old-field")
        )
        assert (await repo.alist_resources(session)).items[0].old_business_digest != digest


@pytest.mark.parametrize(
    "kind,field_name",
    [("resources", "metadata_fields"), ("files", "user_metadata"), ("qa", "questions"), ("tag_libraries", "tags")],
)
async def test_raw_original_content_is_private_and_json_nonfinite_values_fail_closed(repo, native, kind, field_name):
    if kind != "resources":
        await native.insert(Knowledge, [resource(9000)])
    values = data(kind, 1)
    await native.insert(MODELS[kind], [values])
    async with AsyncSession(native.engine) as session, session.begin():
        row = (await getattr(repo, f"alist_{kind}")(session)).items[0]
        assert "private-" not in repr(row)
        assert getattr(row, field_name) == values[field_name]
        if kind == "files":
            assert row.split_rule == "  exact original text  "
        await session.execute(sa.update(MODELS[kind]).where(MODELS[kind].id == 1).values({field_name: [float("nan")]}))
        with pytest.raises(KnowledgeOperationPlanConflictError) as error:
            await getattr(repo, f"alist_{kind}")(session)
        assert "private-" not in str(error.value)


@pytest.mark.parametrize("kind", [key for key, model in MODELS.items() if "tenant_id" in model.__table__.c])
@pytest.mark.parametrize("tenant", [None, 0, -1, 999])
async def test_global_integrity_finds_tenant_null_invalid_and_unknown_once(repo, native, kind, tenant):
    if kind != "resources":
        await native.insert(Knowledge, [resource(9000)])
    await native.insert(MODELS[kind], [data(kind, 1, tenant)])
    async with AsyncSession(native.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.avalidate_global_integrity(session)
    assert native.queries and all("LIMIT" in sql.upper() for sql, _ in native.queries)
    assert all("private-" not in sql for sql, _ in native.queries)


@pytest.mark.parametrize(
    "broken",
    [
        "file_root",
        "file_tenant",
        "document_root",
        "version_document",
        "version_file",
        "version_space",
        "version_tenant",
        "version_directory",
        "primary_pointer",
    ],
)
async def test_global_raw_left_parent_probes_do_not_hide_existing_bad_chains(repo, native, broken):
    await native.insert(Knowledge, [resource(9000), resource(8000, 202), resource(7000)])
    item = file(1)
    doc = data("documents", 1)
    version = data("versions", 1)
    if broken == "file_root":
        item["knowledge_id"] = 9999
    if broken == "file_tenant":
        item["knowledge_id"] = 8000
    if broken == "document_root":
        doc["knowledge_id"] = 9999
    if broken == "version_document":
        version["document_id"] = 9999
    if broken == "version_file":
        version["knowledge_file_id"] = 9999
    if broken == "version_space":
        item["knowledge_id"] = 7000
    if broken == "version_tenant":
        item.update(tenant_id=202, knowledge_id=8000)
    if broken == "version_directory":
        item["file_type"] = 0
    if broken == "primary_pointer":
        doc["primary_version_id"] = 9999
    await native.insert(KnowledgeFile, [item])
    await native.insert(KnowledgeDocument, [doc])
    await native.insert(KnowledgeDocumentVersion, [version])
    async with AsyncSession(native.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.avalidate_global_integrity(session)
    assert all("LIMIT" in sql.upper() for sql, _ in native.queries)


async def test_unregistered_file_and_legacy_overdeep_raw_tree_remain_inventory_facts(repo, native):
    await native.insert(Knowledge, [resource(9000)])
    folders = [
        file(
            ident,
            file_type=0,
            level=ident - 1,
            file_level_path="" if ident == 1 else "/" + "/".join(map(str, range(1, ident))),
        )
        for ident in range(1, 14)
    ]
    await native.insert(
        KnowledgeFile, [*folders, file(99, level=13, file_level_path="/" + "/".join(map(str, range(1, 14))))]
    )
    async with AsyncSession(native.engine) as session, session.begin():
        await repo.avalidate_global_integrity(session)
        rows = (await repo.alist_files(session)).items
        assert rows[-1].level == 13 and rows[-1].file_level_path.endswith("/13")
        assert rows[0].file_level_path == "" and rows[12].level == 12
        assert (await repo.alist_documents(session)).items == ()
        assert (await repo.alist_versions(session)).items == ()


async def test_existing_partial_and_multiple_version_links_stay_visible_as_raw_facts(repo, native):
    await native.insert(Knowledge, [resource(9000)])
    await native.insert(KnowledgeFile, [file(1)])
    await native.insert(KnowledgeDocument, [data("documents", 1)])
    await native.insert(
        KnowledgeDocumentVersion,
        [data("versions", 1), {**data("versions", 2), "document_id": 1, "knowledge_file_id": 1, "version_no": 2}],
    )
    async with AsyncSession(native.engine) as session, session.begin():
        docs = (await repo.alist_documents(session)).items
        versions = (await repo.alist_versions(session)).items
    assert docs[0].primary_version_id is None
    assert [(row.id, row.document_id, row.knowledge_file_id) for row in versions] == [(1, 1, 1), (2, 1, 1)]


async def test_ancestor_500_unique_keys_use_three_queries_and_keep_foreign_and_missing_distinct(repo, native):
    await native.insert(Knowledge, [resource(9000), resource(8000, 202)])
    await native.insert(
        KnowledgeFile,
        [file(ident, file_type=0) for ident in range(1, 499)]
        + [file(500, 202, knowledge_id=8000, file_type=0, level=17, file_level_path="/888")],
    )
    async with AsyncSession(native.engine) as session, session.begin():
        assert await repo.ainspect_file_ancestors(session, file_ids=()) == ()
        assert not native.queries
        facts = await repo.ainspect_file_ancestors(session, file_ids=(*range(1, 501), 1, 2, 500))
    assert [fact.id for fact in facts] == list(range(1, 501))
    assert len(native.queries) == 3
    assert not facts[498].exists and facts[498].tenant_id is None
    assert (
        facts[499].exists
        and facts[499].tenant_id == 202
        and facts[499].file_level_path == "/888"
        and facts[499].level == 17
    )
    assert all(
        "file_name" not in sql and "abstract" not in sql and "user_metadata" not in sql for sql, _ in native.queries
    )
    assert {field.name for field in fields(facts[0])} == {
        "id",
        "exists",
        "tenant_id",
        "knowledge_id",
        "file_type",
        "level",
        "file_level_path",
        "update_time",
    }


async def test_many_files_share_one_unique_ancestor_batch_not_one_query_per_file_or_level(repo, native):
    await native.insert(Knowledge, [resource(9000)])
    await native.insert(
        KnowledgeFile,
        [file(1, file_type=0), file(2, file_type=0, file_level_path="/1", level=1)]
        + [file(ident, file_level_path="/1/2", level=2) for ident in range(1000, 1401)],
    )
    async with AsyncSession(native.engine) as session, session.begin():
        rows = await collect(repo, "files", session)
        ids = tuple(sorted({int(part) for row in rows for part in (row.file_level_path or "").split("/") if part}))
        facts = await repo.ainspect_file_ancestors(session, file_ids=ids)
    assert len(rows) == 403 and [fact.id for fact in facts] == [1, 2]
    assert len(native.queries) == 4


@pytest.mark.parametrize("values", [[1], (True,), (0,), (-1,), ("1",), tuple(range(1, 502))])
async def test_invalid_ancestor_inputs_fail_before_sql(repo, native, values):
    async with AsyncSession(native.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.ainspect_file_ancestors(session, file_ids=values)
    assert not native.queries


@pytest.mark.parametrize("kind", MODELS)
@pytest.mark.parametrize("options", [{"limit": 201}, {"limit": True}, {"after_id": 0}, {"after_id": "1"}])
async def test_invalid_page_inputs_never_query_or_flush(repo, native, kind, options):
    async with AsyncSession(native.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await getattr(repo, f"alist_{kind}")(session, **options)
    assert not native.queries


@pytest.mark.parametrize("scope", [None, 0, True, "bypass", "no_transaction", "not_native"])
async def test_every_entry_requires_original_native_transaction_and_concrete_scope(repo, native, scope):
    async with AsyncSession(native.engine) as session:
        if scope != "no_transaction":
            await session.begin()
        token = set_current_tenant_id(scope if scope in (None, 0, True) else 101)
        try:
            manager = bypass_tenant_filter() if scope == "bypass" else __import__("contextlib").nullcontext()
            with manager:
                target = object() if scope == "not_native" else session
                for kind in MODELS:
                    with pytest.raises(KnowledgeOperationPlanConflictError):
                        await getattr(repo, f"alist_{kind}")(target)
                with pytest.raises(KnowledgeOperationPlanConflictError):
                    await repo.avalidate_global_integrity(target)
                with pytest.raises(KnowledgeOperationPlanConflictError):
                    await repo.ainspect_file_ancestors(target, file_ids=())
        finally:
            current_tenant_id.reset(token)
    assert not native.queries


async def test_reads_never_flush_or_commit_unrelated_pending_state_and_widened_scope_stays_strict(repo, native):
    await native.insert(Knowledge, [resource(9000), resource(8000, 202)])
    async with AsyncSession(native.engine) as session, session.begin():
        original = await session.get(Knowledge, 9000)
        original.description = "caller-pending"
        pending = Knowledge(**resource(1))
        pending.tenant_id = None
        session.add(pending)
        flushes = []
        sa.event.listen(session.sync_session, "before_flush", lambda *_args: flushes.append(True))
        token = visible_tenant_ids.set(frozenset({101, 202}))
        try:
            for kind in MODELS:
                await getattr(repo, f"alist_{kind}")(session)
            await repo.avalidate_global_integrity(session)
            await repo.ainspect_file_ancestors(session, file_ids=(1,))
            resources = (await repo.alist_resources(session)).items
            assert [row.id for row in resources] == [9000] and resources[0].description == "original description"
            assert pending in session.new and pending.tenant_id is None
            assert original.description == "caller-pending" and not flushes
            assert session.in_transaction()
        finally:
            visible_tenant_ids.reset(token)
        await session.rollback()
