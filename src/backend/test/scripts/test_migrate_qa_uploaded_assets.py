from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.database.models.qa_expert import Question
from bisheng.qa_expert.domain.asset_service import AssetKind, AssetReference, PromotionResult, StoredObject
from scripts import migrate_qa_uploaded_assets as migration_script
from scripts.migrate_qa_uploaded_assets import MigrationRecord, load_records, migrate_records


async def test_dry_run_classifies_both_tables_without_storage_or_database_writes() -> None:
    service = SimpleNamespace(
        codec=SimpleNamespace(parse=MagicMock()),
        promote_fields=AsyncMock(),
        compensate=AsyncMock(),
        cleanup_sources=AsyncMock(),
    )
    service.codec.parse.side_effect = [
        [AssetReference("tmp-dir/q.png", AssetKind.TEMP_OBJECT, "tmp-dir", "q.png")],
        [
            AssetReference("tmp-dir/a.pdf", AssetKind.TEMP_OBJECT, "tmp-dir", "a.pdf"),
            AssetReference("file-9", AssetKind.OPAQUE_ID),
        ],
        [AssetReference("qa-expert/1/answer/image/3/a.png", AssetKind.PERMANENT_OBJECT, "bisheng", "qa-expert/1/answer/image/3/a.png")],
    ]
    update_field = AsyncMock()
    records = [
        MigrationRecord("question", 1, {"image_url": "tmp-dir/q.png", "attachments": "tmp-dir/a.pdf;file-9"}),
        MigrationRecord("answer", 3, {"images_url": "qa-expert/1/answer/image/3/a.png"}),
    ]

    report = await migrate_records(
        records,
        asset_service=service,
        apply=False,
        tenant_id=1,
        update_field=update_field,
    )

    assert report.as_dict() == {
        "scanned_records": 2,
        "scanned_fields": 3,
        "temp_objects": 2,
        "permanent_objects": 1,
        "opaque_ids": 1,
        "updated_fields": 0,
        "unchanged_fields": 0,
        "failed_fields": 0,
        "failures": [],
    }
    service.promote_fields.assert_not_awaited()
    update_field.assert_not_awaited()


async def test_apply_updates_after_copy_and_compensates_database_failure() -> None:
    service = SimpleNamespace(
        codec=SimpleNamespace(parse=MagicMock()),
        promote_fields=AsyncMock(),
        compensate=AsyncMock(),
        cleanup_sources=AsyncMock(),
    )
    service.codec.parse.return_value = [
        AssetReference("tmp-dir/a.png", AssetKind.TEMP_OBJECT, "tmp-dir", "a.png")
    ]
    promotion = PromotionResult(
        values={"images_url": "qa-expert/1/answer/image/4/a.png"},
        source_objects=[StoredObject("tmp-dir", "a.png")],
        created_objects=[StoredObject("bisheng", "qa-expert/1/answer/image/4/a.png")],
    )
    service.promote_fields.return_value = promotion
    update_field = AsyncMock(side_effect=RuntimeError("db failed"))

    report = await migrate_records(
        [MigrationRecord("answer", 4, {"images_url": "tmp-dir/a.png"})],
        asset_service=service,
        apply=True,
        tenant_id=1,
        update_field=update_field,
    )

    assert report.failed_fields == 1
    assert report.updated_fields == 0
    assert report.failures == [
        {
            "table": "answer",
            "record_id": 4,
            "field": "images_url",
            "error_type": "RuntimeError",
        }
    ]
    service.compensate.assert_awaited_once_with(promotion)
    service.cleanup_sources.assert_not_awaited()


async def test_apply_is_idempotent_for_already_permanent_value() -> None:
    permanent = "qa-expert/1/question/attachment/2/a.pdf"
    service = SimpleNamespace(
        codec=SimpleNamespace(parse=MagicMock()),
        promote_fields=AsyncMock(),
        compensate=AsyncMock(),
        cleanup_sources=AsyncMock(),
    )
    service.codec.parse.return_value = [
        AssetReference(permanent, AssetKind.PERMANENT_OBJECT, "bisheng", permanent)
    ]
    service.promote_fields.return_value = PromotionResult(values={"attachments": permanent})
    update_field = AsyncMock()

    report = await migrate_records(
        [MigrationRecord("question", 2, {"attachments": permanent})],
        asset_service=service,
        apply=True,
        tenant_id=1,
        update_field=update_field,
    )

    assert report.unchanged_fields == 1
    assert report.updated_fields == 0
    update_field.assert_not_awaited()


async def test_apply_updates_field_before_cleaning_temporary_source() -> None:
    service = SimpleNamespace(
        codec=SimpleNamespace(
            parse=MagicMock(
                return_value=[AssetReference("tmp-dir/a.pdf", AssetKind.TEMP_OBJECT, "tmp-dir", "a.pdf")]
            )
        ),
        promote_fields=AsyncMock(
            return_value=PromotionResult(
                values={"attachments": "qa-expert/1/question/attachment/2/a.pdf"},
                source_objects=[StoredObject("tmp-dir", "a.pdf")],
            )
        ),
        compensate=AsyncMock(),
        cleanup_sources=AsyncMock(),
    )
    update_field = AsyncMock()

    report = await migrate_records(
        [MigrationRecord("question", 2, {"attachments": "tmp-dir/a.pdf"})],
        asset_service=service,
        apply=True,
        tenant_id=1,
        update_field=update_field,
    )

    assert report.updated_fields == 1
    update_field.assert_awaited_once_with(
        "question",
        2,
        "attachments",
        "qa-expert/1/question/attachment/2/a.pdf",
    )
    service.cleanup_sources.assert_awaited_once()
    service.compensate.assert_not_awaited()


async def test_load_records_honors_table_record_batch_and_limit_filters(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Question.__table__.create)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add_all(
            [
                Question(id=1, user_id=1, title="one", description="d", business_domain="domain"),
                Question(id=2, user_id=1, title="two", description="d", business_domain="domain"),
            ]
        )
        await session.commit()

    @asynccontextmanager
    async def get_session():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(migration_script, "get_async_db_session", get_session)
    records = await load_records(tables=["question"], record_id=2, batch_size=1, limit=1)

    assert [(record.entity_type, record.record_id) for record in records] == [("question", 2)]
    await engine.dispose()
