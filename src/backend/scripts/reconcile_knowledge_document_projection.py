"""检查或重新调度单个 F059 文档入口投影。

默认只读; 显式传入 ``--apply`` 才会向默认 Celery 队列调度任务:

    PYTHONPATH=./ .venv/bin/python \
      scripts/reconcile_knowledge_document_projection.py \
      --tenant-id 1 --entry-id 123

    PYTHONPATH=./ .venv/bin/python \
      scripts/reconcile_knowledge_document_projection.py \
      --tenant-id 1 --entry-id 123 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.core.context.tenant import (  # noqa: E402
    current_tenant_id,
    set_current_tenant_id,
)
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (  # noqa: E402
    KnowledgeFileRepositoryImpl,
)


class RecoveryCommittedError(RuntimeError):
    def __init__(self, message: str, snapshot: dict):
        super().__init__(message)
        self.snapshot = snapshot


def _snapshot(entry, tenant_id: int) -> dict:
    if (
        entry is None
        or int(entry.tenant_id or 0) != tenant_id
        or entry.reference_document_id is None
        or entry.entry_type is None
    ):
        raise ValueError("entry does not exist in the requested tenant")
    return {
        "tenant_id": tenant_id,
        "entry_id": int(entry.id),
        "document_id": int(entry.reference_document_id),
        "entry_type": str(entry.entry_type),
        "entry_status": str(entry.entry_status or ""),
        "projection_status": str(entry.projection_status),
        "desired_content_generation": int(entry.desired_content_generation),
        "applied_content_generation": int(entry.applied_content_generation),
        "desired_entry_generation": int(entry.desired_entry_generation),
        "applied_entry_generation": int(entry.applied_entry_generation),
        "retry_count": int(entry.projection_retry_count),
        "last_error": entry.projection_last_error,
        "lease_owner": entry.projection_lease_owner,
        "lease_until": entry.projection_lease_until,
        "next_retry_at": entry.projection_next_retry_at,
    }


def _service(session):
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
        KnowledgeDocumentRepositoryImpl,
    )
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
        KnowledgeDocumentVersionRepositoryImpl,
    )
    from bisheng.knowledge.domain.services.knowledge_document_projection_service import (
        KnowledgeDocumentProjectionService,
    )

    return KnowledgeDocumentProjectionService(
        session=session,
        file_repository=KnowledgeFileRepositoryImpl(session),
        document_repository=KnowledgeDocumentRepositoryImpl(session),
        version_repository=KnowledgeDocumentVersionRepositoryImpl(session),
    )


async def inspect_entry(*, tenant_id: int, entry_id: int) -> dict:
    async with get_async_db_session() as session:
        entry = await KnowledgeFileRepositoryImpl(session).find_by_id(entry_id)
        snapshot = _snapshot(entry, tenant_id)
        try:
            await _service(session).validate_failed_entry_recovery(entry, tenant_id=tenant_id, now=datetime.now())
            snapshot["recovery_blocked_reason"] = None
        except ValueError as exc:
            snapshot["recovery_blocked_reason"] = str(exc)
        return snapshot


def _append_audit(path: str, record: dict) -> None:
    # 审计必须先可靠落盘, 才能提交重试状态; 禁止默认丢失原错误。
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


async def recover_entry(*, tenant_id: int, entry_id: int, operator: str, reason: str, audit_file: str) -> dict:
    if not operator.strip() or not reason.strip() or not audit_file:
        raise ValueError("recovery requires operator, reason and audit-file")
    recovery_id = uuid.uuid4().hex
    now = datetime.now()
    async with get_async_db_session() as session:
        repository = KnowledgeFileRepositoryImpl(session)
        entry = await repository.find_by_id_for_update(entry_id)
        before = _snapshot(entry, tenant_id)
        await _service(session).validate_failed_entry_recovery(entry, tenant_id=tenant_id, now=now)
        audit = {
            "recovery_id": recovery_id,
            "operator": operator,
            "reason": reason,
            "time": now.isoformat(),
            "before": before,
        }
        _append_audit(audit_file, {**audit, "phase": "prepared"})
        if not await repository.recover_failed_projection(
            entry_id=entry_id,
            now=now,
            audit_summary=f"manual_recovery:{recovery_id}",
        ):
            raise ValueError("projection state changed; recovery was not applied")
        after = _snapshot(await repository.find_by_id(entry_id), tenant_id)
        after["recovery_id"] = recovery_id
        await session.commit()
        after["recovery_status"] = "committed"
        try:
            _append_audit(audit_file, {**audit, "phase": "committed", "after": after})
        except OSError as exc:
            # 数据库已提交, prepared 审计和数据库 recovery_id 可用于确认结果。
            raise RecoveryCommittedError(
                "recovery committed; audit completion failed; use prepared audit and inspect the entry",
                after,
            ) from exc
        return after


async def execute(args) -> dict:
    snapshot = await inspect_entry(tenant_id=args.tenant_id, entry_id=args.entry_id)
    if args.apply:
        if args.recover_failed:
            snapshot = await recover_entry(
                tenant_id=args.tenant_id,
                entry_id=args.entry_id,
                operator=args.operator,
                reason=args.reason,
                audit_file=args.audit_file,
            )
        elif snapshot["projection_status"] == "failed":
            from bisheng.knowledge.rag.shared_space_storage import get_shared_storage_conf

            if snapshot["retry_count"] >= int(get_shared_storage_conf().projection_max_retries):
                raise ValueError("retry exhausted; inspect dependencies and use --recover-failed explicitly")
        from bisheng.worker.knowledge.document_projection import (
            process_document_projection,
        )

        try:
            task = process_document_projection.apply_async(
                kwargs={
                    "tenant_id": int(args.tenant_id),
                    "entry_id": int(args.entry_id),
                },
                headers={"tenant_id": int(args.tenant_id)},
                queue="celery",
            )
            snapshot["dispatch_status"] = "submitted"
            snapshot["task_id"] = str(task.id)
        except Exception as exc:
            if snapshot.get("recovery_status") == "committed":
                raise RecoveryCommittedError(
                    "recovery committed; dispatch failed; periodic projection scan will compensate",
                    snapshot,
                ) from exc
            raise
    else:
        snapshot["dispatch_status"] = "dry_run"
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--entry-id", type=int, required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际调度投影任务; 默认只读",
    )
    parser.add_argument(
        "--recover-failed", action="store_true", help="显式重置单个失败投影的重试次数; 仍需 --apply 才执行"
    )
    parser.add_argument("--operator", help="执行人, 仅用于审计")
    parser.add_argument("--reason", help="上游故障已经修复的说明")
    parser.add_argument("--audit-file", help="追加写入的 JSONL 审计文件, 父目录须已存在")
    args = parser.parse_args()
    if args.apply and args.recover_failed and not all([args.operator, args.reason, args.audit_file]):
        parser.error("--recover-failed --apply requires --operator, --reason and --audit-file")
    if args.tenant_id <= 0 or args.entry_id <= 0:
        parser.error("tenant-id and entry-id must be positive")

    token = set_current_tenant_id(args.tenant_id)
    try:
        snapshot = asyncio.run(execute(args))
        print(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str))
        return 0
    except ValueError as exc:
        print(
            json.dumps(
                {
                    "status": "invalid_target",
                    "error": str(exc),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "entry_id": args.entry_id,
                    "recovery_status": getattr(exc, "snapshot", {}).get("recovery_status"),
                    "recovery_id": getattr(exc, "snapshot", {}).get("recovery_id"),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 3
    finally:
        current_tenant_id.reset(token)


if __name__ == "__main__":
    raise SystemExit(main())
