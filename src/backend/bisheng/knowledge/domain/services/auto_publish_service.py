"""Auto-publish execution service.

Orchestrates the full auto-publish flow: config matching, target resolution,
and distribution service invocation. Called by the Celery task.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

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
            KnowledgeFile,
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
            return AutoPublishResult(
                published=False,
                skipped=True,
                skip_reason="target space not resolved",
            )

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

        # -----------------------------------------------------------
        # Step 5: Execute distribution (normalize_manager + publish_approved)
        # -----------------------------------------------------------
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

        auto_publish_instance_id = _generate_auto_publish_instance_id(file_id, target_space_id)

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

            # normalize_manager ensures the source file is tagged as
            # the canonical manager and creates the KnowledgeDocument if needed.
            manager_snapshot = await service.normalize_manager(
                tenant_id=tenant_id,
                source_file_id=file_id,
            )

            command = PublishKnowledgeDocumentCommand(
                tenant_id=tenant_id,
                approval_instance_id=auto_publish_instance_id,
                document_id=manager_snapshot.document_id,
                source_entry_id=file_id,
                target_space_id=target_space_id,
                target_file_level_path=target.target_file_level_path,
                target_level=target.target_level,
                target_document_id=None,
            )

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
                        document_id=manager_snapshot.document_id,
                        manager_file_id=manager_snapshot.manager_file_id,
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

            enqueue_document_projection_entries(
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
