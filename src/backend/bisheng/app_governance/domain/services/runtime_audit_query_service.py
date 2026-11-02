"""Administrator record lists with frozen conditions and strict signed cursors."""

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta

from bisheng.app_governance.domain.models.runtime_audit import RuntimeAuditQuerySnapshot
from bisheng.app_governance.domain.repositories.runtime_audit_repository import RuntimeAuditRepository
from bisheng.app_governance.domain.schemas.runtime_audit import digest, normalize
from bisheng.app_governance.domain.services.runtime_audit_scope import resolve_scope
from bisheng.common.errcode.app_factory import AppFactoryNotEnabledError
from bisheng.common.errcode.app_governance import RuntimeAuditCursorInvalidError, RuntimeAuditFilterInvalidError
from bisheng.common.services.config_service import settings


def enabled():
    if not settings.app_runtime.enabled:
        raise AppFactoryNotEnabledError()


def encode_cursor(payload):
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(settings.jwt_secret.encode(), b"F056-cursor-v1\0" + raw, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw + signature).decode()


def decode_cursor(cursor):
    try:
        if not isinstance(cursor, str) or len(cursor) > 4096:
            raise ValueError("invalid cursor")
        raw = base64.b64decode(cursor, altchars=b"-_", validate=True)
        body, signature = raw[:-32], raw[-32:]
        expected = hmac.new(settings.jwt_secret.encode(), b"F056-cursor-v1\0" + body, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature invalid")
        data = json.loads(body)
        if data["version"] != 1 or datetime.fromisoformat(data["expires_at"]) <= datetime.utcnow():
            raise ValueError("cursor expired")
        return data
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise RuntimeAuditCursorInvalidError() from exc


class RuntimeAuditQueryService:
    def __init__(self, repository=None, *, scope_resolver=resolve_scope):
        self.repo = repository or RuntimeAuditRepository()
        self.scope_resolver = scope_resolver

    async def list(self, user, kind, filters, *, limit=50, cursor=None, tenant_id=None):
        enabled()
        if not 1 <= limit <= 100:
            raise RuntimeAuditFilterInvalidError()
        requested, frozen = normalize(kind, filters)
        scope = (
            await self.scope_resolver(user, tenant_id, app_id=requested["app_id"])
            if requested.get("app_id")
            else await self.scope_resolver(user, tenant_id)
        )
        if scope.authorized_app_ids is not None:
            frozen["authorized_app_ids"] = list(scope.authorized_app_ids)
        fingerprint = digest([kind, scope.digest, requested])
        after = None
        if cursor:
            position = decode_cursor(cursor)
            row = await self.repo.snapshot(scope, position.get("snapshot_id"))
            if (
                row is None
                or row.expires_at <= datetime.utcnow()
                or row.kind != kind
                or row.scope_tenant_id != scope.tenant_id
                or row.filter_digest != fingerprint
                or position.get("filter_digest") != fingerprint
                or position.get("scope_digest") != scope.digest
            ):
                raise RuntimeAuditCursorInvalidError()
            last_id = position.get("last_id")
            if isinstance(last_id, bool) or not isinstance(last_id, int) or not 0 < last_id <= row.watermark:
                raise RuntimeAuditCursorInvalidError()
            last_time = position.get("last_event_time")
            try:
                if last_time is not None:
                    datetime.fromisoformat(last_time)
            except (ValueError, TypeError) as exc:
                raise RuntimeAuditCursorInvalidError() from exc
            after = (last_time, last_id)
        else:
            for key in ("app_id", "visitor_id", "credential_id"):
                if key in requested and not await self.repo.selector_exists(scope, kind, frozen, key, requested[key]):
                    raise RuntimeAuditFilterInvalidError()
            row = RuntimeAuditQuerySnapshot(
                tenant_id=scope.owner_tenant_id,
                creator_user_id=scope.creator_user_id,
                scope_tenant_id=scope.tenant_id,
                kind=kind,
                normalized_filter=frozen,
                filter_digest=fingerprint,
                watermark=await self.repo.watermark(scope, kind, frozen),
                expires_at=datetime.utcnow() + timedelta(minutes=10),
            )
            await self.repo.save_snapshot(row)
        rows = await self.repo.page(scope, kind, row.normalized_filter, row.watermark, after=after, limit=limit + 1)
        more = len(rows) > limit
        items = rows[:limit]
        next_cursor = None
        if more:
            last = items[-1]
            when = last["entry_time" if kind == "access" else "create_time"]
            next_cursor = encode_cursor(
                {
                    "version": 1,
                    "kind": kind,
                    "scope_digest": scope.digest,
                    "filter_digest": fingerprint,
                    "snapshot_id": row.id,
                    "last_event_time": when.isoformat() if when else None,
                    "last_id": last["id"],
                    "expires_at": row.expires_at.isoformat(),
                }
            )
        return {"items": items, "next_cursor": next_cursor, "snapshot_id": row.id, "matched_count": None}

    async def candidates(self, user, kind, dimension, filters, *, tenant_id=None, query="", offset=0, limit=25):
        enabled()
        if not 1 <= limit <= 100 or offset < 0 or len(query) > 128:
            raise RuntimeAuditFilterInvalidError()
        requested, frozen = normalize(kind, filters)
        scope = (
            await self.scope_resolver(user, tenant_id, app_id=requested["app_id"])
            if requested.get("app_id")
            else await self.scope_resolver(user, tenant_id)
        )
        if scope.authorized_app_ids is not None:
            frozen["authorized_app_ids"] = list(scope.authorized_app_ids)
        for key in ("app_id", "visitor_id", "credential_id"):
            if key in requested and not await self.repo.selector_exists(scope, kind, frozen, key, requested[key]):
                raise RuntimeAuditFilterInvalidError()
        return await self.repo.candidates(scope, kind, dimension, frozen, query=query, offset=offset, limit=limit)
