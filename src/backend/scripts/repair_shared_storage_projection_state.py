"""Audit and repair shared SPACE canonical/projection state.

Default mode is read-only. Run from ``src/backend``::

    PYTHONPATH=. .venv/bin/python scripts/repair_shared_storage_projection_state.py --tenant-id 1
    PYTHONPATH=. .venv/bin/python scripts/repair_shared_storage_projection_state.py --tenant-id 1 --apply-managers
    PYTHONPATH=. .venv/bin/python scripts/repair_shared_storage_projection_state.py --tenant-id 1 --requeue-failed

``--apply-managers`` activates manager entries only for successful current
versions in routed SPACE knowledge bases. ``--requeue-failed`` resets the
bounded projection retry state; use it only after fixing the reported root
cause. Orphan canonical rows are reported and never deleted automatically.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import exists  # noqa: E402
from sqlalchemy.orm import aliased  # noqa: E402
from sqlmodel import col, select  # noqa: E402

from bisheng.core.context.manager import close_app_context  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.knowledge.domain.models.knowledge import (  # noqa: E402
    Knowledge,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.models.knowledge_document import (  # noqa: E402
    KnowledgeDocument,
    KnowledgeDocumentLifecycleStatus,
)
from bisheng.knowledge.domain.models.knowledge_document_version import (  # noqa: E402
    KnowledgeDocumentVersion,
)
from bisheng.knowledge.domain.models.knowledge_file import (  # noqa: E402
    FileType,
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileProjectionStatus,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.models.knowledge_space_shared_storage import (  # noqa: E402
    KnowledgeSpaceSharedStorageRouting,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (  # noqa: E402
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (  # noqa: E402
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (  # noqa: E402
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_document_distribution_service import (  # noqa: E402
    KnowledgeDocumentDistributionService,
)
from bisheng.knowledge.domain.services.knowledge_document_permission_activation_service import (  # noqa: E402
    KnowledgeDocumentPermissionActivationService,
)
from bisheng.knowledge.rag.shared_space_storage import get_shared_storage_conf  # noqa: E402


async def _run(args: argparse.Namespace) -> int:
    try:
        conf = get_shared_storage_conf()
        manager_alias = aliased(KnowledgeFile)
        async with get_async_db_session() as session:
            routing = (
                await session.execute(
                    select(KnowledgeSpaceSharedStorageRouting).where(
                        KnowledgeSpaceSharedStorageRouting.tenant_id
                        == args.tenant_id,
                        KnowledgeSpaceSharedStorageRouting.shared_enabled.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if not conf.enabled or routing is None:
                print(
                    json.dumps(
                        {
                            "tenant_id": args.tenant_id,
                            "error": "shared storage routing is not enabled",
                        },
                        ensure_ascii=False,
                    )
                )
                return 2

            missing_managers = list(
                (
                    await session.execute(
                        select(
                            KnowledgeDocument.id,
                            KnowledgeDocument.primary_version_id,
                            KnowledgeFile.id,
                            KnowledgeFile.knowledge_id,
                        )
                        .join(
                            KnowledgeDocumentVersion,
                            KnowledgeDocumentVersion.id
                            == KnowledgeDocument.primary_version_id,
                        )
                        .join(
                            KnowledgeFile,
                            KnowledgeFile.id
                            == KnowledgeDocumentVersion.knowledge_file_id,
                        )
                        .join(Knowledge, Knowledge.id == KnowledgeFile.knowledge_id)
                        .where(
                            KnowledgeDocument.tenant_id == args.tenant_id,
                            KnowledgeDocument.lifecycle_status
                            == KnowledgeDocumentLifecycleStatus.ACTIVE.value,
                            Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                            KnowledgeFile.file_type == FileType.FILE.value,
                            KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
                            col(KnowledgeFile.deleted_at).is_(None),
                            ~exists(
                                select(manager_alias.id).where(
                                    manager_alias.reference_document_id
                                    == KnowledgeDocument.id,
                                    manager_alias.entry_type
                                    == KnowledgeFileEntryType.MANAGER.value,
                                    manager_alias.entry_status
                                    == KnowledgeFileEntryStatus.ACTIVE.value,
                                )
                            ),
                        )
                        .order_by(KnowledgeDocument.id)
                    )
                ).all()
            )

            exhausted = list(
                (
                    await session.execute(
                        select(
                            KnowledgeFile.id,
                            KnowledgeFile.reference_document_id,
                            KnowledgeFile.projection_retry_count,
                            KnowledgeFile.projection_last_error,
                        ).where(
                            KnowledgeFile.tenant_id == args.tenant_id,
                            KnowledgeFile.reference_document_id.is_not(None),
                            KnowledgeFile.entry_status
                            == KnowledgeFileEntryStatus.ACTIVE.value,
                            KnowledgeFile.projection_status
                            == KnowledgeFileProjectionStatus.FAILED.value,
                            KnowledgeFile.projection_retry_count
                            >= int(conf.projection_max_retries),
                        )
                    )
                ).all()
            )

            orphaned = list(
                (
                    await session.execute(
                        select(
                            KnowledgeDocument.id,
                            KnowledgeDocument.primary_version_id,
                            KnowledgeDocumentVersion.knowledge_file_id,
                        )
                        .outerjoin(
                            KnowledgeDocumentVersion,
                            KnowledgeDocumentVersion.id
                            == KnowledgeDocument.primary_version_id,
                        )
                        .outerjoin(
                            KnowledgeFile,
                            KnowledgeFile.id
                            == KnowledgeDocumentVersion.knowledge_file_id,
                        )
                        .where(
                            KnowledgeDocument.tenant_id == args.tenant_id,
                            (
                                KnowledgeDocumentVersion.id.is_(None)
                                | KnowledgeFile.id.is_(None)
                            ),
                        )
                    )
                ).all()
            )

            normalized: list[int] = []
            requeued: list[int] = []
            if args.apply_managers:
                file_repository = KnowledgeFileRepositoryImpl(session)
                service = KnowledgeDocumentDistributionService(
                    session=session,
                    document_repository=KnowledgeDocumentRepositoryImpl(session),
                    version_repository=KnowledgeDocumentVersionRepositoryImpl(session),
                    file_repository=file_repository,
                    permission_activation_service=(
                        KnowledgeDocumentPermissionActivationService(
                            file_repository=file_repository
                        )
                    ),
                )
                for document_id, _, file_id, _ in missing_managers:
                    snapshot = await service.normalize_manager(
                        tenant_id=args.tenant_id,
                        source_file_id=int(file_id),
                        expected_document_id=int(document_id),
                    )
                    await service.touch_manager_content(
                        tenant_id=args.tenant_id,
                        document_id=int(snapshot.document_id),
                        manager_file_id=int(snapshot.manager_file_id),
                    )
                    normalized.append(int(file_id))

            if args.requeue_failed:
                repository = KnowledgeFileRepositoryImpl(session)
                for entry_id, _, _, _ in exhausted:
                    if await repository.request_projection_rebuild(int(entry_id)):
                        requeued.append(int(entry_id))
                await session.commit()

        report = {
            "mode": "apply" if args.apply_managers or args.requeue_failed else "dry-run",
            "tenant_id": args.tenant_id,
            "projection_max_retries": int(conf.projection_max_retries),
            "missing_manager_count": len(missing_managers),
            "missing_managers": [
                {
                    "document_id": int(row[0]),
                    "version_id": int(row[1]),
                    "file_id": int(row[2]),
                    "knowledge_id": int(row[3]),
                }
                for row in missing_managers[: args.sample_limit]
            ],
            "exhausted_projection_count": len(exhausted),
            "exhausted_projections": [
                {
                    "entry_id": int(row[0]),
                    "document_id": int(row[1]),
                    "retry_count": int(row[2]),
                    "last_error": row[3],
                }
                for row in exhausted[: args.sample_limit]
            ],
            "orphan_canonical_count": len(orphaned),
            "orphan_canonicals": [
                {
                    "document_id": int(row[0]),
                    "primary_version_id": row[1],
                    "content_file_id": row[2],
                }
                for row in orphaned[: args.sample_limit]
            ],
            "normalized_file_ids": normalized,
            "requeued_entry_ids": requeued,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        await close_app_context()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--sample-limit", type=int, default=100)
    parser.add_argument("--apply-managers", action="store_true")
    parser.add_argument("--requeue-failed", action="store_true")
    args = parser.parse_args()
    if args.tenant_id <= 0 or args.sample_limit <= 0:
        parser.error("--tenant-id and --sample-limit must be positive")
    with bypass_tenant_filter():
        return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
