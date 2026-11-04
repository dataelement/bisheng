"""Server-authorized record read scope and safe field projections."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from bisheng.common.errcode.app_governance import RuntimeAuditFilterInvalidError


@dataclass(frozen=True)
class AuthorizedRuntimeAuditScope:
    creator_user_id: int
    owner_tenant_id: int
    tenant_id: int | None
    authorized_app_ids: tuple[str, ...] | None = None

    @property
    def digest(self):
        return digest([self.creator_user_id, self.owner_tenant_id, self.tenant_id, self.authorized_app_ids])


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def utc_time(value):
    if not isinstance(value, str):
        raise RuntimeAuditFilterInvalidError()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
        return parsed.astimezone(UTC).replace(tzinfo=None)
    except ValueError as exc:
        raise RuntimeAuditFilterInvalidError() from exc


def normalize(kind, filters, *, now=None):
    if kind not in FIELDS or set(filters) - {
        "time_range",
        "start_time",
        "end_time",
        "app_id",
        "visitor_id",
        "credential_id",
    }:
        raise RuntimeAuditFilterInvalidError()
    result = {k: v for k, v in filters.items() if v is not None and v != ""}
    result.setdefault("time_range", "recent7d")
    mode = result["time_range"]
    if mode not in {"recent7d", "custom", "all"} or (kind != "model" and result.get("credential_id") is not None):
        raise RuntimeAuditFilterInvalidError()
    if mode == "custom":
        start, end = utc_time(result.get("start_time")), utc_time(result.get("end_time"))
        if start > end:
            raise RuntimeAuditFilterInvalidError()
        result.update(start_time=start.isoformat(), end_time=end.isoformat())
    elif result.get("start_time") or result.get("end_time"):
        raise RuntimeAuditFilterInvalidError()
    for key in ("visitor_id", "credential_id"):
        if key in result:
            try:
                if isinstance(result[key], bool) or int(result[key]) <= 0:
                    raise ValueError("positive integer required")
                result[key] = int(result[key])
            except (ValueError, TypeError) as exc:
                raise RuntimeAuditFilterInvalidError() from exc
    if "app_id" in result and (not isinstance(result["app_id"], str) or len(result["app_id"]) > 64):
        raise RuntimeAuditFilterInvalidError()
    frozen = dict(result)
    upper = now or datetime.utcnow()
    if mode == "recent7d":
        frozen.update(start_time=(upper - timedelta(days=7)).isoformat(), end_time=upper.isoformat())
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from bisheng.common.services.config_service import settings

    try:
        zone = settings.app_runtime.runtime_audit_source_timezone
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise RuntimeAuditFilterInvalidError() from exc
    frozen["source_timezone"] = zone
    frozen["upper_time"] = upper.isoformat()
    return result, frozen


FIELDS = {
    "model": (
        "id",
        "create_time",
        "app_id",
        "actor_kind",
        "actor_id",
        "actor_name",
        "subject_kind",
        "subject_id",
        "credential_id",
        "credential_mask",
        "model_id",
        "model_name",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "result",
        "error_code",
        "http_status",
        "latency_ms",
        "ttft_ms",
        "request_id",
    ),
    "capability": (
        "id",
        "create_time",
        "app_id",
        "app_name",
        "credential_id",
        "subject_kind",
        "subject_user_id",
        "capability",
        "result",
        "error_code",
        "chunk_count",
        "latency_ms",
        "version_id",
    ),
    "access": ("id", "entry_time", "app_id", "app_name_snapshot", "user_id", "user_name", "request_id"),
}
