"""Whole-result CSV artifacts published only after one source read-view reaches EOF."""

import csv
import hashlib
import io
import json
import uuid
from datetime import datetime, timedelta

from loguru import logger

from bisheng.app_governance.domain.models.runtime_audit import RuntimeAuditExport
from bisheng.app_governance.domain.repositories.runtime_audit_export_repository import RuntimeAuditExportRepository
from bisheng.app_governance.domain.repositories.runtime_audit_repository import RuntimeAuditRepository
from bisheng.app_governance.domain.schemas.runtime_audit import FIELDS
from bisheng.app_governance.domain.services.runtime_audit_query_service import enabled
from bisheng.app_governance.domain.services.runtime_audit_scope import resolve_scope
from bisheng.app_governance.domain.services.runtime_audit_storage import RuntimeAuditStorage
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.app_governance import (
    RuntimeAuditAccessDeniedError,
    RuntimeAuditCursorInvalidError,
    RuntimeAuditExportUnavailableError,
)
from bisheng.core.context.tenant import tenant_execution_scope


def safe_csv_value(value):
    if not isinstance(value, str):
        return value
    import unicodedata

    index = 0
    while index < len(value) and (value[index].isspace() or unicodedata.category(value[index]).startswith("C")):
        index += 1
    visible = value[index:]
    return "'" + value if visible.startswith(("=", "+", "-", "@")) else value


def csv_bytes(fields, rows, *, header=False):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    if header:
        output.write("\ufeff")
        writer.writerow(fields)
    for row in rows:
        writer.writerow([safe_csv_value(row.get(field)) for field in fields])
    return output.getvalue().encode("utf-8")


class RuntimeAuditExportService:
    def __init__(self, repository=None, source=None, storage=None, *, scope_resolver=resolve_scope, worker_scope=None):
        self.repo = repository or RuntimeAuditExportRepository()
        self.source = source or RuntimeAuditRepository()
        self.storage = storage or RuntimeAuditStorage()
        self.scope_resolver = scope_resolver
        self.worker_scope = worker_scope or self.current_worker_scope

    async def current_worker_scope(self, job):
        enabled()
        account = await self.repo.worker_user(job.creator_user_id)
        if account is None:
            raise RuntimeAuditAccessDeniedError()
        user = UserPayload(
            user_id=account.user_id,
            user_name=account.user_name,
            tenant_id=job.tenant_id,
            user_role=[],
            token_version=account.token_version,
        )
        with tenant_execution_scope(job.tenant_id):
            scope = await self.job_scope(user, job)
        if scope.tenant_id != job.scope_tenant_id or scope.owner_tenant_id != job.tenant_id:
            raise RuntimeAuditAccessDeniedError()
        return scope

    async def submit(self, user, snapshot_id, request_id, *, tenant_id=None):
        enabled()
        if not request_id or len(request_id) > 128:
            raise RuntimeAuditExportUnavailableError()
        from bisheng.app_governance.domain.schemas.runtime_audit import AuthorizedRuntimeAuditScope
        from bisheng.core.context.tenant import get_current_tenant_id

        effective = get_current_tenant_id() or user.tenant_id
        if tenant_id is not None and tenant_id != effective:
            raise RuntimeAuditAccessDeniedError()
        lookup = AuthorizedRuntimeAuditScope(user.user_id, effective, effective)
        snapshot = await self.source.snapshot(lookup, snapshot_id)
        if snapshot is None:
            raise RuntimeAuditCursorInvalidError()
        filters = snapshot.normalized_filter
        scope = (
            await self.scope_resolver(user, effective, app_id=filters["app_id"])
            if filters.get("app_id")
            else await self.scope_resolver(user, effective)
        )
        if not snapshot or snapshot.expires_at <= datetime.utcnow() or snapshot.scope_tenant_id != scope.tenant_id:
            raise RuntimeAuditCursorInvalidError()
        await self.check_snapshot_scope(user, scope, snapshot.normalized_filter)
        return await self.repo.create(
            RuntimeAuditExport(
                tenant_id=scope.owner_tenant_id,
                creator_user_id=scope.creator_user_id,
                scope_tenant_id=scope.tenant_id,
                kind=snapshot.kind,
                snapshot_id=snapshot.id,
                request_id=request_id,
                normalized_filter=snapshot.normalized_filter,
                watermark=snapshot.watermark,
            )
        )

    async def check_snapshot_scope(self, user, scope, filters):
        current = (
            await self.scope_resolver(user, scope.tenant_id, app_id=filters["app_id"])
            if filters.get("app_id")
            else scope
        )
        frozen = filters.get("authorized_app_ids")
        if frozen is not None and (
            current.authorized_app_ids is None or not set(frozen).issubset(current.authorized_app_ids)
        ):
            raise RuntimeAuditAccessDeniedError()
        return current

    async def job_scope(self, user, job):
        filters = job.normalized_filter
        scope = (
            await self.scope_resolver(user, job.scope_tenant_id, app_id=filters["app_id"])
            if filters.get("app_id")
            else await self.scope_resolver(user, job.scope_tenant_id)
        )
        await self.check_snapshot_scope(user, scope, filters)
        return scope

    async def authorized_job(self, user, job_id, tenant_id=None):
        enabled()
        from bisheng.core.context.tenant import get_current_tenant_id

        effective = get_current_tenant_id() or user.tenant_id
        if tenant_id is not None and tenant_id != effective:
            raise RuntimeAuditAccessDeniedError()
        job = await self.repo.get(effective, job_id)
        if not job or job.creator_user_id != user.user_id:
            raise RuntimeAuditAccessDeniedError()
        scope = await self.job_scope(user, job)
        if job.scope_tenant_id != scope.tenant_id or job.tenant_id != scope.owner_tenant_id:
            raise RuntimeAuditAccessDeniedError()
        return job

    async def status(self, user, job_id, *, tenant_id=None):
        job = await self.authorized_job(user, job_id, tenant_id)
        status = job.status
        if status == "ready" and job.download_expires_at <= datetime.utcnow():
            status = "expired"
        return {
            "export_id": job.id,
            "status": status,
            "safe_reason": job.safe_failure,
            "attempt": job.attempt,
            "selection_started_at": job.selection_started_at,
            "processed_rows": job.processed_rows,
            "final_count": job.final_count,
            "ready_at": job.ready_at,
            "expires_at": job.download_expires_at,
        }

    async def cancel(self, user, job_id, *, tenant_id=None):
        job = await self.authorized_job(user, job_id, tenant_id)
        await self.repo.terminate(job.tenant_id, job.id, "expired")
        return {"export_id": job.id, "status": "expired"}

    async def run(self, job_id, tenant_id, *, batch_size=500):
        job = await self.repo.claim(tenant_id, job_id, uuid.uuid4().hex)
        if not job:
            return
        prefix = f"runtime-audit/{job.tenant_id}/{job.id}/{job.attempt}-{job.epoch}/"
        parts = []
        count = 0

        async def upload(raw, rows):
            key = prefix + f"part-{len(parts):08d}.csv"
            await self.storage.put(key, raw)
            parts.append({"key": key, "rows": rows, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})

        try:
            scope = await self.worker_scope(job)
            async for rows in self.source.stream_export(
                scope, job.kind, job.normalized_filter, job.watermark, batch_size=min(max(batch_size, 1), 500)
            ):
                current = await self.worker_scope(job)
                if current != scope:
                    raise RuntimeAuditAccessDeniedError()
                raw = csv_bytes(FIELDS[job.kind], rows, header=not parts)
                await upload(raw, len(rows))
                count += len(rows)
                await self.repo.checkpoint(job, processed_rows=count)
            if not parts:
                await upload(csv_bytes(FIELDS[job.kind], [], header=True), 0)
            # EOF and all uploads are confirmed before a fenced atomic publication.
            await self.worker_scope(job)
            manifest = json.dumps(
                {
                    "version": 1,
                    "job_id": job.id,
                    "attempt": job.attempt,
                    "epoch": job.epoch,
                    "count": count,
                    "parts": parts,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            key = prefix + "manifest.json"
            await self.storage.put(key, manifest)
            now = datetime.utcnow()
            await self.repo.checkpoint(
                job,
                status="ready",
                processed_rows=count,
                final_count=count,
                manifest_object_key=key,
                manifest_digest=hashlib.sha256(manifest).hexdigest(),
                ready_at=now,
                download_expires_at=now + timedelta(minutes=10),
            )
        except Exception:
            logger.exception("runtime_audit export failed job={} attempt={}", job.id, job.attempt)
            # A stale attempt cannot overwrite another owner's state. Never
            # expose provider exceptions, source values or partial artifacts.
            try:
                await self.repo.checkpoint(job, status="failed", safe_failure="export_failed")
            except RuntimeAuditExportUnavailableError:
                logger.warning("runtime_audit export ownership changed job={}", job.id)
            raise

    async def selected_manifest(self, user, job_id, *, tenant_id=None):
        job = await self.authorized_job(user, job_id, tenant_id)
        if job.status != "ready" or not job.download_expires_at or job.download_expires_at <= datetime.utcnow():
            raise RuntimeAuditExportUnavailableError()
        raw = await self.storage.get(job.manifest_object_key)
        if raw is None or hashlib.sha256(raw).hexdigest() != job.manifest_digest:
            raise RuntimeAuditExportUnavailableError()
        manifest = json.loads(raw)
        prefix = f"runtime-audit/{job.tenant_id}/{job.id}/{job.attempt}-{job.epoch}/"
        if (
            manifest.get("job_id") != job.id
            or manifest.get("epoch") != job.epoch
            or manifest.get("count") != job.final_count
        ):
            raise RuntimeAuditExportUnavailableError()
        parts = manifest.get("parts")
        if not isinstance(parts, list) or not parts:
            raise RuntimeAuditExportUnavailableError()
        for index, part in enumerate(parts):
            if (
                part.get("key") != prefix + f"part-{index:08d}.csv"
                or type(part.get("bytes")) is not int
                or part["bytes"] <= 0
                or type(part.get("rows")) is not int
                or part["rows"] < 0
            ):
                raise RuntimeAuditExportUnavailableError()
        if sum(part["rows"] for part in parts) != job.final_count:
            raise RuntimeAuditExportUnavailableError()
        return job, manifest

    async def download_size(self, user, job_id, *, tenant_id=None):
        _, manifest = await self.selected_manifest(user, job_id, tenant_id=tenant_id)
        return sum(part["bytes"] for part in manifest["parts"])

    async def download(self, user, job_id, *, tenant_id=None):
        job, manifest = await self.selected_manifest(user, job_id, tenant_id=tenant_id)
        for part in manifest["parts"]:
            current = await self.authorized_job(user, job_id, tenant_id)
            if (
                current.status != "ready"
                or current.epoch != job.epoch
                or current.download_expires_at <= datetime.utcnow()
            ):
                raise RuntimeAuditExportUnavailableError()
            data = await self.storage.get(part["key"])
            if data is None or len(data) != part["bytes"] or hashlib.sha256(data).hexdigest() != part["sha256"]:
                raise RuntimeAuditExportUnavailableError()
            yield data
