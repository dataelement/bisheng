"""Safely inspect or rebuild the knowledge-space dashboard statistics index."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.core.search.elasticsearch.manager import (
    get_statistics_es_connection_sync,
)
from bisheng.telemetry.domain.mid_table.knowledge_space_content import (
    KnowledgeSpaceContentStat,
)

TARGET_INDEX = KnowledgeSpaceContentStat.INDEX_NAME
KNOWN_RECORD_TYPES = (
    "file",
    "preview_daily",
    "download_daily",
    "favorite_daily",
    "portal_engagement_daily",
)


def _count_source_files() -> int:
    from bisheng.worker.telemetry.mid_table import _get_success_space_file_rows

    page = 1
    page_size = 1000
    total = 0
    while True:
        rows = _get_success_space_file_rows(page, page_size)
        if not rows:
            return total
        total += len(rows)
        page += 1


def _rebuild_projection(owner_token: str) -> dict[str, Any]:
    from bisheng.worker.telemetry.mid_table import (
        rebuild_knowledge_space_content_file_projection,
    )

    return rebuild_knowledge_space_content_file_projection(owner_token)


def _redis_key_size(redis_client: Any, key: str) -> int:
    redis_client.cluster_nodes(key)
    key_type = redis_client.connection.type(key)
    if isinstance(key_type, bytes):
        key_type = key_type.decode("utf-8")
    if key_type == "zset":
        return int(redis_client.connection.zcard(key) or 0)
    if key_type == "set":
        return int(redis_client.connection.scard(key) or 0)
    if key_type == "hash":
        return int(redis_client.connection.hlen(key) or 0)
    if key_type in {"string", "list", "stream"}:
        return int(redis_client.connection.exists(key) or 0)
    return 0


def _collect_redis_status(redis_client: Any) -> dict[str, dict[str, int]]:
    new_keys = {
        "pending": KnowledgeSpaceContentStat.PENDING_KEY,
        "processing": KnowledgeSpaceContentStat.PROCESSING_KEY,
        "processing_meta": KnowledgeSpaceContentStat.PROCESSING_META_KEY,
        "scheduled": KnowledgeSpaceContentStat.SCHEDULED_KEY,
        "owner_lock": KnowledgeSpaceContentStat.LOCK_KEY,
        "event_pending": KnowledgeSpaceContentStat.EVENT_PENDING_KEY,
        "event_processing": KnowledgeSpaceContentStat.EVENT_PROCESSING_KEY,
        "event_processing_meta": KnowledgeSpaceContentStat.EVENT_PROCESSING_META_KEY,
        "event_payload": KnowledgeSpaceContentStat.EVENT_PAYLOAD_KEY,
        "event_scheduled": KnowledgeSpaceContentStat.EVENT_SCHEDULED_KEY,
        "replay_floor": KnowledgeSpaceContentStat.REPLAY_FLOOR_KEY,
    }
    legacy_keys = {
        "file_pending": KnowledgeSpaceContentStat.LEGACY_FILE_PENDING_KEY,
        "preview_pending": KnowledgeSpaceContentStat.LEGACY_PREVIEW_PENDING_KEY,
        "space_rename_pending": (KnowledgeSpaceContentStat.LEGACY_SPACE_RENAME_PENDING_KEY),
        "space_delete_pending": (KnowledgeSpaceContentStat.LEGACY_SPACE_DELETE_PENDING_KEY),
        "scheduled": KnowledgeSpaceContentStat.LEGACY_SCHEDULED_KEY,
        "lock": KnowledgeSpaceContentStat.LEGACY_LOCK_KEY,
    }
    return {
        "new": {name: _redis_key_size(redis_client, key) for name, key in new_keys.items()},
        "legacy": {name: _redis_key_size(redis_client, key) for name, key in legacy_keys.items()},
    }


def _extract_refresh_interval(settings: dict[str, Any]) -> str | None:
    index_settings = settings.get(TARGET_INDEX, {}).get("settings", {}).get("index", {})
    return index_settings.get("refresh_interval")


def _collect_index_status(es_client: Any) -> dict[str, Any]:
    exists = bool(es_client.indices.exists(index=TARGET_INDEX))
    if not exists:
        return {
            "exists": False,
            "refresh_interval": None,
            "document_count": 0,
            "file_snapshot_count": 0,
            "preview_daily_count": 0,
            "download_daily_count": 0,
            "favorite_daily_count": 0,
            "portal_engagement_daily_count": 0,
            "other_record_count": 0,
            "other_record_type_counts": {},
            "missing_record_type_count": 0,
        }

    def count_record_type(record_type: str) -> int:
        return int(
            es_client.count(
                index=TARGET_INDEX,
                body={"query": {"term": {"record_type": record_type}}},
            )["count"]
        )

    document_count = int(es_client.count(index=TARGET_INDEX)["count"])
    record_counts = {record_type: count_record_type(record_type) for record_type in KNOWN_RECORD_TYPES}
    unknown_response = es_client.search(
        index=TARGET_INDEX,
        body={
            "size": 0,
            "query": {"bool": {"must_not": [{"terms": {"record_type": list(KNOWN_RECORD_TYPES)}}]}},
            "aggs": {
                "record_types": {
                    "terms": {
                        "field": "record_type",
                        "size": 100,
                    }
                },
                "missing_record_type": {
                    "missing": {
                        "field": "record_type",
                    }
                },
            },
        },
    )
    aggregations = unknown_response.get("aggregations", {})
    other_record_type_counts = {
        str(bucket["key"]): int(bucket.get("doc_count", 0) or 0)
        for bucket in aggregations.get("record_types", {}).get("buckets", [])
    }
    missing_record_type_count = int(aggregations.get("missing_record_type", {}).get("doc_count", 0) or 0)
    return {
        "exists": True,
        "refresh_interval": _extract_refresh_interval(es_client.indices.get_settings(index=TARGET_INDEX)),
        "document_count": document_count,
        "file_snapshot_count": record_counts["file"],
        "preview_daily_count": record_counts["preview_daily"],
        "download_daily_count": record_counts["download_daily"],
        "favorite_daily_count": record_counts["favorite_daily"],
        "portal_engagement_daily_count": record_counts["portal_engagement_daily"],
        "other_record_count": max(
            0,
            document_count - sum(record_counts.values()),
        ),
        "other_record_type_counts": other_record_type_counts,
        "missing_record_type_count": missing_record_type_count,
    }


@dataclass
class RebuildRuntime:
    get_es_client: Callable[[], Any] = get_statistics_es_connection_sync
    get_redis_client: Callable[[], Any] = get_redis_client_sync
    count_source_files: Callable[[], int] = _count_source_files
    acquire_lock: Callable[[], str | None] = KnowledgeSpaceContentStat.acquire_lock_sync
    renew_lock: Callable[[str], bool] = KnowledgeSpaceContentStat.renew_lock_sync
    release_lock: Callable[[str], bool] = KnowledgeSpaceContentStat.release_lock_sync
    reclaim_all: Callable[[], int] = lambda: KnowledgeSpaceContentStat.reclaim_expired_sync(now_ms=2**63 - 1)
    reclaim_all_events: Callable[[], int] = lambda: KnowledgeSpaceContentStat.reclaim_expired_events_sync(
        now_ms=2**63 - 1
    )
    reset_index_bootstrap: Callable[[], None] = KnowledgeSpaceContentStat.reset_index_bootstrap_state
    ensure_index: Callable[[], None] = lambda: KnowledgeSpaceContentStat()
    rebuild: Callable[[str], dict[str, Any]] = _rebuild_projection
    has_pending: Callable[[], bool] = KnowledgeSpaceContentStat.has_pending_sync
    schedule_pending: Callable[[], None] = KnowledgeSpaceContentStat.schedule_pending_sync_now
    has_event_pending: Callable[[], bool] = KnowledgeSpaceContentStat.has_event_pending_sync
    schedule_event_pending: Callable[[], None] = KnowledgeSpaceContentStat.schedule_event_pending_sync_now
    set_replay_floor: Callable[[int], None] = KnowledgeSpaceContentStat.set_replay_floor_sync


def collect_preflight(runtime: RebuildRuntime) -> tuple[Any, Any, dict[str, Any]]:
    es_client = runtime.get_es_client()
    redis_client = runtime.get_redis_client()
    return (
        es_client,
        redis_client,
        {
            "target_index": TARGET_INDEX,
            "source_file_count": runtime.count_source_files(),
            "index": _collect_index_status(es_client),
            "redis": _collect_redis_status(redis_client),
        },
    )


def _clear_legacy_keys(redis_client: Any) -> list[str]:
    keys = [
        KnowledgeSpaceContentStat.LEGACY_FILE_PENDING_KEY,
        KnowledgeSpaceContentStat.LEGACY_PREVIEW_PENDING_KEY,
        KnowledgeSpaceContentStat.LEGACY_SPACE_RENAME_PENDING_KEY,
        KnowledgeSpaceContentStat.LEGACY_SPACE_DELETE_PENDING_KEY,
        KnowledgeSpaceContentStat.LEGACY_SCHEDULED_KEY,
        KnowledgeSpaceContentStat.LEGACY_LOCK_KEY,
    ]
    for key in keys:
        redis_client.delete(key)
    return keys


def run_rebuild(
    args: argparse.Namespace,
    *,
    runtime: RebuildRuntime | None = None,
) -> tuple[int, dict[str, Any]]:
    runtime = runtime or RebuildRuntime()
    report: dict[str, Any] = {
        "mode": "apply" if args.apply else "dry-run",
        "started_at": datetime.now().astimezone().isoformat(),
        "degraded": False,
        "failure_stage": None,
    }
    owner_token: str | None = None
    try:
        es_client, redis_client, preflight = collect_preflight(runtime)
        report["preflight"] = preflight
        if not args.apply:
            report["completed_at"] = datetime.now().astimezone().isoformat()
            return 0, report

        if args.confirm_index != TARGET_INDEX:
            report.update(
                degraded=True,
                failure_stage="confirmation",
                error=(f"--confirm-index must exactly equal {TARGET_INDEX!r}; no data was changed"),
            )
            return 2, report

        owner_token = runtime.acquire_lock()
        if owner_token is None:
            report.update(
                degraded=True,
                failure_stage="owner_lock",
                error="projection owner lock is busy; no data was changed",
            )
            return 3, report

        reclaimed_count = runtime.reclaim_all()
        reclaimed_event_count = runtime.reclaim_all_events()
        replay_floor = int(datetime.now().timestamp())
        runtime.set_replay_floor(replay_floor)
        report["replay_floor"] = replay_floor
        if not runtime.renew_lock(owner_token):
            raise RuntimeError("projection owner lock was lost before index deletion")

        if es_client.indices.exists(index=TARGET_INDEX):
            es_client.indices.delete(index=TARGET_INDEX)
        if not runtime.renew_lock(owner_token):
            raise RuntimeError("projection owner lock was lost before index creation")

        runtime.reset_index_bootstrap()
        runtime.ensure_index()
        rebuild_result = runtime.rebuild(owner_token)
        cleared_legacy_keys = _clear_legacy_keys(redis_client)
        report["result"] = {
            **rebuild_result,
            "reclaimed_processing_count": reclaimed_count,
            "reclaimed_event_processing_count": reclaimed_event_count,
            "cleared_legacy_keys": cleared_legacy_keys,
            "index": _collect_index_status(es_client),
            "redis": _collect_redis_status(redis_client),
        }
        report["completed_at"] = datetime.now().astimezone().isoformat()
        released = runtime.release_lock(owner_token)
        owner_token = None
        report["owner_lock_released"] = released
        if not released:
            report.update(
                degraded=True,
                failure_stage="owner_lock_release",
                error="projection owner lock could not be released by the rebuilding owner",
            )
            return 5, report
        if runtime.has_pending():
            runtime.schedule_pending()
            report["pending_rescheduled"] = True
        else:
            report["pending_rescheduled"] = False
        if runtime.has_event_pending():
            runtime.schedule_event_pending()
            report["event_pending_rescheduled"] = True
        else:
            report["event_pending_rescheduled"] = False
        return 0, report
    except Exception as exc:
        report.update(
            degraded=True,
            failure_stage=report.get("failure_stage") or "rebuild",
            error=str(exc),
            completed_at=datetime.now().astimezone().isoformat(),
        )
        return 4, report
    finally:
        if owner_token is not None:
            released = runtime.release_lock(owner_token)
            report["owner_lock_released"] = released
            if runtime.has_pending():
                runtime.schedule_pending()
                report["pending_rescheduled"] = True
            else:
                report["pending_rescheduled"] = False
            if runtime.has_event_pending():
                runtime.schedule_event_pending()
                report["event_pending_rescheduled"] = True
            else:
                report["event_pending_rescheduled"] = False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete and rebuild the exact target index; default is read-only dry-run.",
    )
    parser.add_argument(
        "--confirm-index",
        help=f"Required with --apply and must exactly equal {TARGET_INDEX}.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    code, report = run_rebuild(args)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
