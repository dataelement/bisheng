"""审计或转正专家问答历史上传资源。

默认仅 dry-run。生产执行前应先备份五个目标字段并以小批次运行 ``--apply``。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field

from sqlmodel import select

from bisheng.core.database import get_async_db_session
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.database.models.qa_expert import Answer, Question
from bisheng.qa_expert.domain.asset_service import AssetKind, QaAssetService

TABLE_FIELDS = {
    "question": ("image_url", "file_url", "attachments"),
    "answer": ("images_url", "attachments"),
}


@dataclass(frozen=True)
class MigrationRecord:
    entity_type: str
    record_id: int
    values: dict[str, str | None]


@dataclass
class MigrationReport:
    scanned_records: int = 0
    scanned_fields: int = 0
    temp_objects: int = 0
    permanent_objects: int = 0
    opaque_ids: int = 0
    updated_fields: int = 0
    unchanged_fields: int = 0
    failed_fields: int = 0
    failures: list[dict[str, str | int]] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return vars(self).copy()


UpdateField = Callable[[str, int, str, str | None], Awaitable[None]]


async def migrate_records(
    records: Iterable[MigrationRecord],
    *,
    asset_service: QaAssetService,
    apply: bool,
    tenant_id: int,
    update_field: UpdateField,
) -> MigrationReport:
    """处理已加载记录; 字段内任一引用失败时保留该字段原值。"""
    report = MigrationReport()
    for record in records:
        report.scanned_records += 1
        for field_name, original_value in record.values.items():
            if not original_value:
                continue
            report.scanned_fields += 1
            try:
                references = asset_service.codec.parse(record.entity_type, field_name, original_value)
                report.temp_objects += sum(ref.kind is AssetKind.TEMP_OBJECT for ref in references)
                report.permanent_objects += sum(ref.kind is AssetKind.PERMANENT_OBJECT for ref in references)
                report.opaque_ids += sum(ref.kind is AssetKind.OPAQUE_ID for ref in references)
                if not apply:
                    continue
                promotion = await asset_service.promote_fields(
                    tenant_id=tenant_id,
                    entity_type=record.entity_type,
                    owner_stable_id=str(record.record_id),
                    values={field_name: original_value},
                )
                new_value = promotion.values[field_name]
                if new_value == original_value:
                    report.unchanged_fields += 1
                    continue
                try:
                    await update_field(record.entity_type, record.record_id, field_name, new_value)
                except Exception:
                    await asset_service.compensate(promotion)
                    raise
                await asset_service.cleanup_sources(promotion)
                report.updated_fields += 1
            except Exception as exc:
                report.failed_fields += 1
                report.failures.append(
                    {
                        "table": record.entity_type,
                        "record_id": record.record_id,
                        "field": field_name,
                        "error_type": type(exc).__name__,
                    }
                )
    return report


async def load_records(
    *,
    tables: list[str],
    record_id: int | None,
    batch_size: int,
    limit: int | None,
) -> list[MigrationRecord]:
    records: list[MigrationRecord] = []
    for entity_type in tables:
        model = Question if entity_type == "question" else Answer
        last_id = 0
        while limit is None or len(records) < limit:
            current_limit = min(batch_size, limit - len(records)) if limit is not None else batch_size
            async with get_async_db_session() as session:
                statement = select(model).where(model.id > last_id).order_by(model.id).limit(current_limit)
                if record_id is not None:
                    statement = select(model).where(model.id == record_id)
                result = await session.exec(statement)
                rows = result.all()
            if not rows:
                break
            for row in rows:
                records.append(
                    MigrationRecord(
                        entity_type=entity_type,
                        record_id=int(row.id),
                        values={field: getattr(row, field) for field in TABLE_FIELDS[entity_type]},
                    )
                )
            last_id = int(rows[-1].id)
            if record_id is not None or len(rows) < current_limit:
                break
    return records


async def update_database_field(
    entity_type: str,
    record_id: int,
    field_name: str,
    value: str | None,
) -> None:
    model = Question if entity_type == "question" else Answer
    async with get_async_db_session() as session:
        row = await session.get(model, record_id)
        if row is None:
            raise RuntimeError(f"QA {entity_type} record no longer exists: {record_id}")
        setattr(row, field_name, value)
        session.add(row)
        await session.commit()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate QA uploaded assets from temporary to permanent storage")
    parser.add_argument("--apply", action="store_true", help="Apply object copies and database updates")
    parser.add_argument("--table", choices=["question", "answer", "all"], default="all")
    parser.add_argument("--record-id", type=int)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--tenant-id", type=int, default=1)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if args.batch_size <= 0 or (args.limit is not None and args.limit <= 0):
        raise ValueError("batch-size and limit must be positive")
    tables = ["question", "answer"] if args.table == "all" else [args.table]
    records = await load_records(
        tables=tables,
        record_id=args.record_id,
        batch_size=args.batch_size,
        limit=args.limit,
    )
    storage = await get_minio_storage()
    report = await migrate_records(
        records,
        asset_service=QaAssetService(storage),
        apply=args.apply,
        tenant_id=args.tenant_id,
        update_field=update_database_field,
    )
    print(json.dumps({"mode": "apply" if args.apply else "dry-run", **report.as_dict()}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
