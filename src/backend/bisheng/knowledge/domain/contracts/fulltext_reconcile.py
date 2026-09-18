"""全文对账的批量读写契约; 未知读取结果不得当成不存在。"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


class ReconcileReadError(RuntimeError):
    pass


class ReconcileWriteError(RuntimeError):
    pass


class ReconcileChunkDataError(ReconcileReadError):
    pass


class ReconcileLeaseLost(RuntimeError):
    pass


class ReconcileDependencyUnavailable(RuntimeError):
    pass


@dataclass
class Observation:
    source: dict[str, Any] | None
    seq_no: int | None = None
    primary_term: int | None = None


@dataclass
class Mutation:
    file_id: int
    document: dict[str, Any] | None
    observed: Observation


VOLATILE_FIELDS = frozenset({"indexed_at", "sync_revision", "preview_count", "download_count", "engagement_updated_at"})


def comparable(document: dict[str, Any]) -> dict[str, Any]:
    result = {k: v for k, v in document.items() if k not in VOLATILE_FIELDS}
    for key in ("tags", "knowledge_business_domain_codes"):
        if key in result:
            result[key] = sorted(set(result[key] or []))
    for key in ("created_at", "updated_at"):
        value = result.get(key)
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if isinstance(value, datetime):
            # 全文 schema 将无时区时间解释为 UTC, 沿用既有序列化契约。
            result[key] = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return result


def matches(expected: dict[str, Any] | None, actual: Observation) -> bool:
    if expected is None:
        return actual.source is None
    try:
        return actual.source is not None and comparable(expected) == comparable(actual.source)
    except (ValueError, TypeError):
        # 已读取的损坏字段属于差异, 不应中断同批其他条目。
        return False
