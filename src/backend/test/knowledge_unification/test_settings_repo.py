"""T059: defaults, explicit overrides and same-transaction settings CAS.

Coverage: AC-38, AC-39, AC-40, AC-42, AC-43, AC-44.
"""

from copy import deepcopy

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeProcessingSettingsConflictError
from bisheng.common.errcode.knowledge_space import SpaceNotFoundError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.repositories.processing_settings_repository import ProcessingSettingsRepository
from bisheng.knowledge.domain.schemas.processing_settings import (
    DocumentProcessingRule,
    PartialDocumentRule,
    ProcessingDefaults,
    ProcessingSettingsWrite,
    TableProcessingRule,
)
from bisheng.knowledge.domain.services.processing_settings_service import ProcessingSettingsService


@pytest.fixture
def system_defaults():
    return ProcessingDefaults(
        document=DocumentProcessingRule(
            split_mode="auto",
            separator=["\n\n", "\n", "。", "\\."],
            separator_rule=["after"] * 4,
            chunk_size=1000,
            chunk_overlap=100,
            hierarchy_level=3,
            append_title=False,
            max_chunk_size=1000,
            retain_images=1,
            force_ocr=1,
            enable_formula=1,
            filter_page_header_footer=0,
        ),
        table=TableProcessingRule(slice_length=10, header_start_row=1, header_end_row=1, append_header=1),
    )


def changed_defaults(defaults, *, chunk_size=800, slice_length=20):
    values = defaults.model_dump()
    values["document"]["chunk_size"] = chunk_size
    values["table"]["slice_length"] = slice_length
    return ProcessingDefaults.model_validate(values)


@pytest.fixture
def processing_tenant(tenant_context):
    tenant_context(101)


@pytest.fixture
async def processing_session(processing_tenant):
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda conn: SQLModel.metadata.create_all(
                conn, tables=[Knowledge.__table__, KnowledgeProcessingJob.__table__]
            )
        )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(
            Knowledge(
                id=1,
                tenant_id=101,
                user_id=11,
                name="one",
                type=KnowledgeTypeEnum.SPACE.value,
                model_config_revision=7,
                index_generation="original-index",
            )
        )
        await session.commit()
        yield session
    await engine.dispose()


@pytest.fixture
def settings_service():
    return ProcessingSettingsService(ProcessingSettingsRepository())


async def test_missing_settings_read_system_without_backfill(processing_session, settings_service, system_defaults):
    response = await settings_service.get_settings(processing_session, 1, system_defaults=system_defaults)
    assert response.saved_defaults is None
    assert response.config_version == 0
    assert response.effective_defaults == system_defaults
    assert not processing_session.dirty
    assert not processing_session.new


async def test_save_both_types_cas_does_not_change_model_or_index(
    processing_session, settings_service, system_defaults
):
    change = ProcessingSettingsWrite(
        expected_config_version=0, defaults=changed_defaults(system_defaults, chunk_size=800, slice_length=30)
    )
    saved = await settings_service.save_settings(processing_session, 1, change, system_defaults=system_defaults)
    assert saved.config_version == 1
    assert saved.saved_defaults.document.chunk_size == 800
    assert saved.saved_defaults.table.slice_length == 30
    await processing_session.commit()
    row = await processing_session.get(Knowledge, 1)
    assert row.model_config_revision == 7
    assert row.index_generation == "original-index"
    assert not (await processing_session.exec(select(KnowledgeProcessingJob))).all()


async def test_stale_save_has_no_partial_update(processing_session, settings_service, system_defaults):
    original = ProcessingSettingsWrite(expected_config_version=0, defaults=changed_defaults(system_defaults))
    await settings_service.save_settings(processing_session, 1, original, system_defaults=system_defaults)
    await processing_session.commit()
    stale = ProcessingSettingsWrite(
        expected_config_version=0, defaults=changed_defaults(system_defaults, chunk_size=600, slice_length=40)
    )
    with pytest.raises(KnowledgeProcessingSettingsConflictError):
        await settings_service.save_settings(processing_session, 1, stale, system_defaults=system_defaults)
    current = await settings_service.get_settings(processing_session, 1, system_defaults=system_defaults)
    assert current.config_version == 1
    assert current.saved_defaults == original.defaults


async def test_owner_rollback_rolls_back_settings_and_other_changes(
    processing_session, settings_service, system_defaults
):
    row = await processing_session.get(Knowledge, 1)
    row.description = "part of owner transaction"
    change = ProcessingSettingsWrite(expected_config_version=0, defaults=changed_defaults(system_defaults))
    await settings_service.save_settings(processing_session, 1, change, system_defaults=system_defaults)
    await processing_session.rollback()
    response = await settings_service.get_settings(processing_session, 1, system_defaults=system_defaults)
    assert response.config_version == 0
    assert response.saved_defaults is None
    assert (await processing_session.get(Knowledge, 1)).description is None


async def test_invalid_settings_do_not_write(processing_session, settings_service, system_defaults):
    invalid = changed_defaults(system_defaults).model_dump()
    invalid["table"]["header_start_row"] = 3
    invalid["table"]["header_end_row"] = 1
    with pytest.raises(ValidationError):
        ProcessingSettingsWrite.model_validate({"expected_config_version": 0, "defaults": invalid})
    read = await settings_service.get_settings(processing_session, 1, system_defaults=system_defaults)
    assert read.saved_defaults is None and read.config_version == 0


async def test_foreign_tenant_settings_are_not_found(processing_session, settings_service, system_defaults):
    token = set_current_tenant_id(202)
    try:
        processing_session.add(Knowledge(id=2, tenant_id=202, user_id=21, name="two", type=3))
        await processing_session.commit()
    finally:
        current_tenant_id.reset(token)
    with pytest.raises(SpaceNotFoundError):
        await settings_service.get_settings(processing_session, 2, system_defaults=system_defaults)
    with pytest.raises(SpaceNotFoundError):
        await settings_service.save_settings(
            processing_session,
            2,
            ProcessingSettingsWrite(expected_config_version=0, defaults=system_defaults),
            system_defaults=system_defaults,
        )


def test_document_sparse_override_priority_and_null_does_not_override(system_defaults):
    raw_batch = {"document": {"chunk_size": 600, "force_ocr": None}}
    raw_file = {"document": {"chunk_size": 400, "chunk_overlap": 0}}
    before = deepcopy((raw_batch, raw_file))
    snapshot = ProcessingSettingsService.resolve_effective_snapshot(
        file_kind="document",
        system_defaults=system_defaults,
        space_defaults=changed_defaults(system_defaults),
        space_config_version=3,
        batch_overrides=raw_batch,
        file_overrides=raw_file,
    )
    assert snapshot.effective_rule.chunk_size == 400
    assert snapshot.effective_rule.chunk_overlap == 0
    assert snapshot.effective_rule.force_ocr == 1
    assert snapshot.space_config_version == 3
    assert snapshot.supplied_fields_by_layer["batch"] == ["chunk_size"]
    assert snapshot.supplied_fields_by_layer["file"] == ["chunk_overlap", "chunk_size"]
    assert before == (raw_batch, raw_file)


def test_document_and_table_defaults_do_not_leak_into_each_other(system_defaults):
    snapshot = ProcessingSettingsService.resolve_effective_snapshot(
        file_kind="table",
        system_defaults=system_defaults,
        space_defaults=changed_defaults(system_defaults, slice_length=20),
        batch_overrides={"document": {"chunk_size": 400}, "table": {"slice_length": 30}},
        file_overrides={"table": {"append_header": 0}},
    )
    assert isinstance(snapshot.effective_rule, TableProcessingRule)
    assert snapshot.effective_rule.slice_length == 30
    assert snapshot.effective_rule.append_header == 0
    assert "chunk_size" not in snapshot.effective_rule.model_dump()


def test_web_owner_rules_override_all_generic_layers(system_defaults):
    snapshot = ProcessingSettingsService.resolve_effective_snapshot(
        file_kind="web",
        system_defaults=system_defaults,
        space_defaults=changed_defaults(system_defaults),
        file_overrides={"document": {"chunk_size": 400, "chunk_overlap": 100}},
        specialized_overrides=PartialDocumentRule(
            separator=["\n", ""], separator_rule=["after", "after"], chunk_overlap=0
        ),
    )
    assert snapshot.effective_rule.separator == ["\n", ""]
    assert snapshot.effective_rule.chunk_overlap == 0
    assert snapshot.effective_rule.chunk_size == 400
    assert snapshot.supplied_fields_by_layer["specialized"] == ["chunk_overlap", "separator", "separator_rule"]


@pytest.mark.parametrize("kind", ["web", "audio", "video"])
def test_dedicated_kinds_require_owner_rule_selection(system_defaults, kind):
    with pytest.raises(ValueError, match="dedicated"):
        ProcessingSettingsService.resolve_effective_snapshot(file_kind=kind, system_defaults=system_defaults)


@pytest.mark.parametrize("kind", ["audio", "video"])
def test_media_uses_owner_selected_existing_common_split_rules(system_defaults, kind):
    snapshot = ProcessingSettingsService.resolve_effective_snapshot(
        file_kind=kind,
        system_defaults=system_defaults,
        space_defaults=changed_defaults(system_defaults),
        specialized_overrides=PartialDocumentRule(),
    )
    assert snapshot.effective_rule.chunk_size == 800
    assert snapshot.effective_rule.separator == system_defaults.document.separator


@pytest.mark.parametrize("overrides", [{"document": {"cache": True}}, {"table": {"file_name": "temp.xlsx"}}])
def test_ephemeral_or_unsupported_fields_do_not_enter_snapshot(system_defaults, overrides):
    with pytest.raises(ValidationError):
        ProcessingSettingsService.resolve_effective_snapshot(
            file_kind="document", system_defaults=system_defaults, file_overrides=overrides
        )


def test_merged_bounds_are_validated_after_sparse_overrides(system_defaults):
    with pytest.raises(ValidationError, match="chunk_overlap"):
        ProcessingSettingsService.resolve_effective_snapshot(
            file_kind="document", system_defaults=system_defaults, file_overrides={"document": {"chunk_size": 20}}
        )


def test_existing_effective_snapshot_does_not_change_with_new_defaults(system_defaults):
    first_defaults = changed_defaults(system_defaults)
    old = ProcessingSettingsService.resolve_effective_snapshot(
        file_kind="document", system_defaults=system_defaults, space_defaults=first_defaults, space_config_version=1
    )
    before = old.model_dump()
    new = ProcessingSettingsService.resolve_effective_snapshot(
        file_kind="document",
        system_defaults=system_defaults,
        space_defaults=changed_defaults(system_defaults, chunk_size=1200),
        space_config_version=2,
    )
    assert new.effective_rule.chunk_size == 1200
    assert old.model_dump() == before
    assert old.effective_rule.chunk_size == 800
    assert set(old.model_dump()) == {
        "schema_version",
        "file_kind",
        "effective_rule",
        "space_config_version",
        "supplied_fields_by_layer",
    }
