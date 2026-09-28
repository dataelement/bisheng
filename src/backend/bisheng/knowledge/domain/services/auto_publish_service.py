"""Auto-publish execution service.

Orchestrates the full auto-publish flow: config matching, target resolution,
and distribution service invocation. Called by the Celery task.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from bisheng.utils.task_dispatch import run_sync_dispatch

if TYPE_CHECKING:
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.knowledge.domain.services.auto_publish_target_resolver import AutoPublishTarget

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AutoPublishResult:
    """Outcome of an auto-publish attempt."""

    published: bool
    skipped: bool = False
    skip_reason: str = ""
    document_id: int | None = None
    manager_file_id: int | None = None
    publish_entry_id: int | None = None
    target_space_id: int | None = None
    idempotent: bool = False


def _generate_auto_publish_instance_id(file_id: int, target_space_id: int) -> int:
    """Generate a deterministic negative approval_instance_id for auto-publish.

    Uses a negative integer to distinguish from real approval instances.
    Deterministic so that retries of the same (file_id, target_space_id) are idempotent.
    """
    return -(file_id * 10000 + target_space_id % 10000)


class AutoPublishService:
    """Orchestrates automatic publishing of department files to public spaces."""

    @classmethod
    async def execute(
        cls,
        *,
        file_id: int,
        tenant_id: int,
        publish_context: dict | None = None,
        save_publish_context: Callable[[dict], Awaitable[None]] | None = None,
    ) -> AutoPublishResult:
        """Execute auto-publish for a given file.

        Steps:
        1. Load file, extract file_category_code and file_subcategory_code
        2. Get enabled rules, match against file
        3. Resolve target space and folder
        4. Check idempotency (file already has publish entry to target)
        5. Call normalize_manager + publish_approved
        6. Enqueue projections

        Returns AutoPublishResult.
        Raises on transient failures (to trigger Celery retry).
        """
        from bisheng.knowledge.domain.constants import (
            get_file_category_code_from_split_rule,
        )
        from bisheng.knowledge.domain.models.knowledge_file import (
            KnowledgeFileDao,
            KnowledgeFileEntryType,
        )
        from bisheng.knowledge.domain.services.auto_publish_config_service import (
            AutoPublishConfigService,
        )
        from bisheng.knowledge.domain.services.auto_publish_target_resolver import (
            AutoPublishTargetResolver,
        )

        # -----------------------------------------------------------
        # Step 1: Load file, extract category codes
        # -----------------------------------------------------------
        db_file: KnowledgeFile | None = await KnowledgeFileDao.query_by_id(file_id)
        if db_file is None:
            return AutoPublishResult(
                published=False,
                skipped=True,
                skip_reason="file not found",
            )

        if int(db_file.tenant_id or 1) != tenant_id or db_file.deleted_at is not None:
            return AutoPublishResult(published=False, skipped=True, skip_reason="file no longer eligible")
        if db_file.status != 2:
            raise RuntimeError("auto_publish_source_not_ready")
        if publish_context is not None:
            return await cls._publish(
                db_file=db_file,
                tenant_id=tenant_id,
                publish_context=publish_context,
            )
        if getattr(db_file, "entry_status", None) == "preparing":
            # 历史记录缺少原命令时不能按当前规则猜测目标, 更不能提前激活 manager。
            raise RuntimeError("auto_publish_recovery_context_missing")
        from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScopeDao, KnowledgeSpaceLevelEnum
        scope = await KnowledgeSpaceScopeDao.aget_by_space_id(int(db_file.knowledge_id))
        if scope is None or scope.level != KnowledgeSpaceLevelEnum.DEPARTMENT:
            return AutoPublishResult(published=False, skipped=True, skip_reason="source is not department space")

        file_category_code = get_file_category_code_from_split_rule(getattr(db_file, "split_rule", None))
        file_subcategory_code = getattr(db_file, "file_subcategory_code", None) or ""

        if not file_category_code:
            return AutoPublishResult(
                published=False,
                skipped=True,
                skip_reason="missing category",
            )

        # -----------------------------------------------------------
        # Step 2: Get enabled rules, match against file
        # -----------------------------------------------------------
        rules = await AutoPublishConfigService.get_enabled_rules(tenant_id)
        matched_rule = AutoPublishConfigService.match_rule(
            rules,
            source_space_id=int(db_file.knowledge_id),
            file_category_code=file_category_code,
            file_subcategory_code=file_subcategory_code,
        )
        if matched_rule is None:
            logger.debug(
                "auto_publish: no matching rule for file_id=%s category_code=%s space_id=%s",
                file_id,
                file_category_code,
                db_file.knowledge_id,
            )
            return AutoPublishResult(
                published=False,
                skipped=True,
                skip_reason="no matching rule",
            )

        # -----------------------------------------------------------
        # Step 3: Resolve target space and folder
        # -----------------------------------------------------------
        target_space_id = await AutoPublishTargetResolver.resolve_target_space_id(
            rule_target_space_id=matched_rule.target_space_id,
            file_category_code=file_category_code,
            tenant_id=tenant_id,
        )
        if target_space_id is None:
            logger.warning(
                "auto_publish: target space not resolved for file_id=%s category_code=%s rule_id=%s",
                file_id,
                file_category_code,
                matched_rule.id,
            )
            raise RuntimeError("auto_publish_target_space_not_resolved")

        target = await AutoPublishTargetResolver.resolve_or_create_target_folder(
            target_space_id=target_space_id,
            file_subcategory_code=file_subcategory_code,
            tenant_id=tenant_id,
            system_user_id=int(db_file.user_id or 0),
        )

        # -----------------------------------------------------------
        # Step 4: Idempotency check — skip if file already distributed
        # -----------------------------------------------------------
        if db_file.entry_type == KnowledgeFileEntryType.MANAGER.value and db_file.reference_document_id is not None:
            # File already has an active manager entry — check if there's
            # already a publish entry to the target space. The publish_approved
            # idempotency logic will also catch this, but we can short-circuit.
            logger.info(
                "auto_publish: file_id=%s already has entry_type=manager "
                "reference_document_id=%s, proceeding with publish_approved "
                "idempotency check",
                file_id,
                db_file.reference_document_id,
            )

        return await cls._publish(
            db_file=db_file,
            tenant_id=tenant_id,
            target_space_id=target_space_id,
            target=target,
            save_publish_context=save_publish_context,
        )

    @classmethod
    async def _publish(
        cls,
        *,
        db_file: KnowledgeFile,
        tenant_id: int,
        target_space_id: int | None = None,
        target: AutoPublishTarget | None = None,
        publish_context: dict | None = None,
        save_publish_context: Callable[[dict], Awaitable[None]] | None = None,
    ) -> AutoPublishResult:
        """首次发布先保存原命令; 重试继续已有权限流程, 不重新匹配发布规则。"""
        from bisheng.core.database import get_async_db_session
        from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
            KnowledgeDocumentRepositoryImpl,
        )
        from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
            KnowledgeDocumentVersionRepositoryImpl,
        )
        from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
            KnowledgeFileRepositoryImpl,
        )
        from bisheng.knowledge.domain.services.knowledge_document_distribution_service import (
            KnowledgeDocumentDistributionError,
            KnowledgeDocumentDistributionService,
            PublishKnowledgeDocumentCommand,
        )
        from bisheng.knowledge.domain.services.knowledge_document_permission_activation_service import (
            KnowledgeDocumentPermissionActivationService,
        )

        file_id = int(db_file.id)

        async with get_async_db_session() as session:
            file_repository = KnowledgeFileRepositoryImpl(session)
            service = KnowledgeDocumentDistributionService(
                session=session,
                document_repository=KnowledgeDocumentRepositoryImpl(session),
                version_repository=KnowledgeDocumentVersionRepositoryImpl(session),
                file_repository=file_repository,
                permission_activation_service=KnowledgeDocumentPermissionActivationService(
                    file_repository=file_repository,
                ),
            )

            current = await file_repository.find_by_id_for_update(file_id)
            if (
                current is None
                or int(current.tenant_id or 1) != tenant_id
                or current.deleted_at is not None
                or current.status != 2
            ):
                raise RuntimeError("auto_publish_source_changed")
            if publish_context is not None:
                command = PublishKnowledgeDocumentCommand(**publish_context)
                if (
                    command.tenant_id != tenant_id
                    or command.source_entry_id != file_id
                    or command.document_id != current.reference_document_id
                    or command.approval_instance_id
                    != _generate_auto_publish_instance_id(file_id, command.target_space_id)
                    or command.target_document_id is not None
                    or command.metadata_only_migration
                    or current.entry_type != "manager"
                    or current.entry_status not in {"active", "preparing"}
                    or (
                        current.entry_status == "preparing"
                        and current.approval_instance_id != command.approval_instance_id
                    )
                ):
                    raise RuntimeError("auto_publish_recovery_context_mismatch")
            else:
                if current.entry_status == "preparing":
                    raise RuntimeError("auto_publish_recovery_context_missing")
                if current.entry_type not in {None, "manager"} or (
                    current.entry_type == "manager" and current.entry_status != "active"
                ):
                    raise RuntimeError("auto_publish_source_changed")
                assert target_space_id is not None and target is not None
                manager_snapshot = await service.normalize_manager(tenant_id=tenant_id, source_file_id=file_id)
                command = PublishKnowledgeDocumentCommand(
                    tenant_id=tenant_id,
                    approval_instance_id=_generate_auto_publish_instance_id(file_id, target_space_id),
                    document_id=manager_snapshot.document_id,
                    source_entry_id=file_id,
                    target_space_id=target_space_id,
                    target_file_level_path=target.target_file_level_path,
                    target_level=target.target_level,
                    target_document_id=None,
                )
                if save_publish_context is not None:
                    # 保存失败就停止, 确保 preparing 入口总有可恢复的原始目标。
                    await save_publish_context(asdict(command))
            target_space_id = command.target_space_id

            try:
                result = await service.publish_approved(command)
            except KnowledgeDocumentDistributionError as exc:
                error_msg = str(exc)
                # "publish duplicate content" is an idempotent case, not failure
                if "duplicate content" in error_msg.lower():
                    logger.info(
                        "auto_publish: idempotent skip (duplicate content) file_id=%s target_space_id=%s",
                        file_id,
                        target_space_id,
                    )
                    return AutoPublishResult(
                        published=False,
                        skipped=True,
                        skip_reason="duplicate content in target space",
                        document_id=command.document_id,
                        manager_file_id=file_id,
                        target_space_id=target_space_id,
                        idempotent=True,
                    )
                raise

        # -----------------------------------------------------------
        # Step 6: Post-publish — enqueue projections
        # -----------------------------------------------------------
        try:
            from bisheng.worker.knowledge.document_projection import (
                enqueue_document_projection_entries,
            )

            await run_sync_dispatch(enqueue_document_projection_entries,
                tenant_id=tenant_id,
                entry_ids=[
                    result.manager_file_id,
                    result.publish_entry_id,
                ],
            )
        except Exception:
            logger.warning(
                "auto_publish: projection enqueue failed file_id=%s document_id=%s; Beat will recover",
                file_id,
                result.document_id,
                exc_info=True,
            )

        logger.info(
            "auto_publish: success file_id=%s source_space_id=%s "
            "target_space_id=%s document_id=%s manager_entry_id=%s "
            "publish_entry_id=%s idempotent=%s",
            file_id,
            db_file.knowledge_id,
            result.target_space_id,
            result.document_id,
            result.manager_file_id,
            result.publish_entry_id,
            result.idempotent,
        )

        return AutoPublishResult(
            published=True,
            document_id=result.document_id,
            manager_file_id=result.manager_file_id,
            publish_entry_id=result.publish_entry_id,
            target_space_id=result.target_space_id,
            idempotent=result.idempotent,
        )
