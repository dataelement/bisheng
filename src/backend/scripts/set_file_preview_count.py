"""Set a knowledge file's preview/read count by seeding ES telemetry records.

Preview volume is derived from Elasticsearch, not MySQL:
- ``base_telemetry_events``: ``portal_document_read`` events
- ``mid_knowledge_space_content_stat``: ``record_type=preview`` rows

This script resets existing records for the given ``file_id`` and inserts
``--target`` synthetic events (default 1000) into both indices.

Usage (from ``src/backend/``)::

    export config=config.yaml
    PYTHONPATH=. uv run python scripts/set_file_preview_count.py --file-id 1294
    PYTHONPATH=. uv run python scripts/set_file_preview_count.py --file-id 1294 --target 1000 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from elasticsearch.helpers import async_bulk  # noqa: E402

from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum  # noqa: E402
from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.common.services.telemetry.telemetry_service import telemetry_service  # noqa: E402
from bisheng.core.context.manager import close_app_context, initialize_app_context  # noqa: E402
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, bypass_tenant_filter, set_current_tenant_id  # noqa: E402
from bisheng.core.search.elasticsearch.manager import get_statistics_es_connection  # noqa: E402
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileDao  # noqa: E402

MID_INDEX = "mid_knowledge_space_content_stat"
EVENT_TYPE = BaseTelemetryTypeEnum.PORTAL_DOCUMENT_READ.value


def _base_query(file_id: int) -> dict:
    return {
        "bool": {
            "must": [
                {"term": {"event_type": EVENT_TYPE}},
                {"term": {"event_data.portal_document_read_file_id": file_id}},
            ]
        }
    }


def _mid_query(file_id: int) -> dict:
    return {
        "bool": {
            "must": [
                {"term": {"record_type": "preview"}},
                {"term": {"file_id": file_id}},
            ]
        }
    }


async def _count(es, index: str, query: dict) -> int:
    response = await es.search(index=index, body={"size": 0, "query": query})
    total = response.get("hits", {}).get("total", {})
    return int(total.get("value", total) if isinstance(total, dict) else total)


async def _load_file_context(file_id: int) -> tuple[KnowledgeFile, Knowledge]:
    with bypass_tenant_filter():
        file_record = await KnowledgeFileDao.query_by_id(file_id)
        if file_record is None:
            raise SystemExit(f"Knowledge file not found: file_id={file_id}")
        space = await KnowledgeDao.aquery_by_id(int(file_record.knowledge_id))
        if space is None:
            raise SystemExit(
                f"Knowledge space not found for file_id={file_id}, knowledge_id={file_record.knowledge_id}"
            )
        return file_record, space


def _bad_base_query(file_id: int) -> dict:
    """Cleanup query for malformed docs seeded via BaseTelemetryEvent.model_dump()."""
    return {
        "bool": {
            "must": [
                {"term": {"event_type": EVENT_TYPE}},
                {"term": {"event_data.BaseTelemetryTypeEnum.PORTAL_DOCUMENT_READ_file_id": file_id}},
            ]
        }
    }


def _build_base_doc(
    *,
    tenant_id: int,
    file_id: int,
    space_id: int,
    user_id: int,
    user_name: str,
    seq: int,
) -> dict:
    ts = int(datetime.now(tz=timezone.utc).timestamp()) - seq
    return {
        "event_id": uuid.uuid4().hex,
        "tenant_id": tenant_id,
        "event_type": EVENT_TYPE,
        "timestamp": ts,
        "trace_id": f"seed-preview-{file_id}-{seq}",
        "user_context": {
            "user_id": user_id,
            "user_name": user_name,
            "user_group_infos": [],
            "user_role_infos": [],
            "user_department_infos": [],
        },
        "event_data": {
            "portal_document_read_source_app": "bisheng_my_knowledge",
            "portal_document_read_scene": "document_preview",
            "portal_document_read_entry_point": "seed_script",
            "portal_document_read_resource_type": "document",
            "portal_document_read_status": "success",
            "portal_document_read_space_id": space_id,
            "portal_document_read_file_id": file_id,
        },
    }


def _build_mid_doc(
    *,
    file_id: int,
    file_name: str,
    file_type: int,
    space_id: int,
    space_name: str,
    uploader_user_id: int,
    uploader_user_name: str,
    viewer_user_id: int,
    viewer_user_name: str,
    seq: int,
) -> dict:
    event_id = uuid.uuid4().hex
    ts = int(datetime.now(tz=timezone.utc).timestamp()) - seq
    return {
        "_index": MID_INDEX,
        "_id": f"preview_seed_{file_id}_{seq}",
        "_source": {
            "user_id": viewer_user_id,
            "user_name": viewer_user_name,
            "user_group_infos": [],
            "user_role_infos": [],
            "user_department_infos": [],
            "timestamp": ts,
            "record_type": "preview",
            "sync_run_id": None,
            "space_id": space_id,
            "space_name": space_name,
            "file_id": file_id,
            "file_name": file_name,
            "file_type": file_type,
            "uploader_user_id": uploader_user_id,
            "uploader_user_name": uploader_user_name,
            "uploader_department_infos": [],
            "event_id": event_id,
            "viewer_user_id": viewer_user_id,
            "viewer_user_name": viewer_user_name,
            "action_result": "success",
        },
    }


async def run(args: argparse.Namespace) -> int:
    set_current_tenant_id(args.tenant_id)
    file_record, space = await _load_file_context(args.file_id)

    es = await get_statistics_es_connection()
    base_index = telemetry_service.index_name
    base_before = await _count(es, base_index, _base_query(args.file_id))
    mid_before = await _count(es, MID_INDEX, _mid_query(args.file_id))

    print(f"file_id={args.file_id} file_name={file_record.file_name!r} space_id={space.id} space_name={space.name!r}")
    print(f"before: base={base_before} mid={mid_before} target={args.target}")

    if not args.apply:
        print("Dry-run only. Re-run with --apply to delete existing records and seed ES.")
        return 0

    if base_before:
        deleted = await es.delete_by_query(
            index=base_index,
            body={"query": _base_query(args.file_id)},
            refresh=True,
        )
        print(f"deleted base={deleted.get('deleted', 0)}")
    bad_base_before = await _count(es, base_index, _bad_base_query(args.file_id))
    if bad_base_before:
        deleted = await es.delete_by_query(
            index=base_index,
            body={"query": _bad_base_query(args.file_id)},
            refresh=True,
        )
        print(f"deleted malformed base={deleted.get('deleted', 0)}")

    if mid_before:
        deleted = await es.delete_by_query(
            index=MID_INDEX,
            body={"query": _mid_query(args.file_id)},
            refresh=True,
        )
        print(f"deleted mid={deleted.get('deleted', 0)}")

    uploader_user_id = int(file_record.user_id or args.user_id)
    uploader_user_name = file_record.user_name or args.user_name
    viewer_user_id = args.user_id
    viewer_user_name = args.user_name

    base_actions = (
        {
            "_index": base_index,
            "_source": _build_base_doc(
                tenant_id=args.tenant_id,
                file_id=args.file_id,
                space_id=int(space.id),
                user_id=viewer_user_id,
                user_name=viewer_user_name,
                seq=seq,
            ),
        }
        for seq in range(args.target)
    )
    ok_base, err_base = await async_bulk(es, base_actions, chunk_size=500, refresh=True)
    print(f"bulk base indexed={ok_base} errors={len(err_base) if err_base else 0}")

    mid_actions = (
        _build_mid_doc(
            file_id=args.file_id,
            file_name=file_record.file_name,
            file_type=int(file_record.file_type),
            space_id=int(space.id),
            space_name=space.name,
            uploader_user_id=uploader_user_id,
            uploader_user_name=uploader_user_name,
            viewer_user_id=viewer_user_id,
            viewer_user_name=viewer_user_name,
            seq=seq,
        )
        for seq in range(args.target)
    )
    ok_mid, err_mid = await async_bulk(es, mid_actions, chunk_size=500, refresh=True)
    print(f"bulk mid indexed={ok_mid} errors={len(err_mid) if err_mid else 0}")

    base_after = await _count(es, base_index, _base_query(args.file_id))
    mid_after = await _count(es, MID_INDEX, _mid_query(args.file_id))
    print(f"after: base={base_after} mid={mid_after}")
    return 0


async def _main(args: argparse.Namespace) -> int:
    await initialize_app_context(config=settings)
    try:
        return await run(args)
    finally:
        await close_app_context()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file-id", type=int, required=True, help="Knowledge file id")
    parser.add_argument("--target", type=int, default=1000, help="Preview count to set (default: 1000)")
    parser.add_argument("--tenant-id", type=int, default=DEFAULT_TENANT_ID)
    parser.add_argument("--user-id", type=int, default=1, help="Viewer user id for seeded events")
    parser.add_argument("--user-name", default="admin", help="Viewer user name for seeded events")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete existing preview telemetry for the file and seed target count",
    )
    args = parser.parse_args()
    if args.target <= 0:
        raise SystemExit("--target must be positive")
    return asyncio.run(_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
