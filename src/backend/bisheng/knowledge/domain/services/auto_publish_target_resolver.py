"""Auto-publish target resolution.

Resolves the target public space and folder for an auto-publish rule
based on file category code -> PUBLIC space name matching and subcategory code -> folder name matching.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileDao,
    KnowledgeFileStatus,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AutoPublishTarget:
    """Resolved target for auto-publishing a file."""

    space_id: int
    folder_id: int | None
    target_level: int
    target_file_level_path: str


class AutoPublishTargetResolver:
    """Resolves target public space and folder for auto-publish."""

    @classmethod
    async def resolve_target_space_id(
        cls,
        *,
        rule_target_space_id: int | None,
        file_category_code: str,
        tenant_id: int,
    ) -> int | None:
        """Resolve the target public space ID.

        - If rule specifies target_space_id directly, use it.
        - Otherwise find the category label from portal config, then match it
          against PUBLIC knowledge space names in the database.
        Returns None if no match found.
        """
        if rule_target_space_id is not None:
            return rule_target_space_id

        # Auto-match: find document_type label by code, then match to public space name
        portal_config = await cls._load_portal_config(tenant_id)
        if portal_config is None:
            logger.warning(
                "auto_publish_target: portal config not found for tenant_id=%s",
                tenant_id,
            )
            return None

        # 1. Find document_type entry where code matches file_category_code
        document_types = portal_config.get("document_types", [])
        category_label = cls._find_document_type_label(document_types, file_category_code)
        if not category_label:
            logger.warning(
                "auto_publish_target: no document_type found for code=%s, tenant_id=%s",
                file_category_code,
                tenant_id,
            )
            return None

        # 2. Find a PUBLIC knowledge space whose name matches the category label
        from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
        from bisheng.knowledge.domain.models.knowledge_space_scope import (
            KnowledgeSpaceLevelEnum,
            KnowledgeSpaceScopeDao,
        )

        public_space_ids = await KnowledgeSpaceScopeDao.aget_space_ids_by_level(KnowledgeSpaceLevelEnum.PUBLIC)
        if not public_space_ids:
            logger.warning(
                "auto_publish_target: no PUBLIC spaces found for tenant_id=%s",
                tenant_id,
            )
            return None

        # Query the actual space records to match by name
        public_spaces = await KnowledgeDao.aget_list_by_ids(public_space_ids)
        for space in public_spaces:
            if str(getattr(space, "name", "") or "").strip() == category_label:
                return int(space.id)

        logger.warning(
            "auto_publish_target: no PUBLIC space matched name=%s for code=%s, tenant_id=%s",
            category_label,
            file_category_code,
            tenant_id,
        )
        return None

    @classmethod
    async def resolve_or_create_target_folder(
        cls,
        *,
        target_space_id: int,
        file_subcategory_code: str,
        tenant_id: int,
        system_user_id: int,
    ) -> AutoPublishTarget:
        """Resolve target folder by matching subcategory label to folder name.

        If folder doesn't exist, create it in the root of target space.
        Returns AutoPublishTarget with level/path info for the publish command.
        """
        # 1. Find subcategory label from portal config
        portal_config = await cls._load_portal_config(tenant_id)
        subcategory_label: str | None = None
        if portal_config is not None:
            document_types = portal_config.get("document_types", [])
            subcategory_label = cls._find_subcategory_label(document_types, file_subcategory_code)

        if not subcategory_label:
            # Cannot determine subcategory label, publish to root
            logger.debug(
                "auto_publish_target: subcategory label not found for code=%s, publishing to root of space_id=%s",
                file_subcategory_code,
                target_space_id,
            )
            return AutoPublishTarget(
                space_id=target_space_id,
                folder_id=None,
                target_level=0,
                target_file_level_path="",
            )

        # 2. Query root-level folders in target space
        folders = await KnowledgeFileDao.aget_folders_by_space(target_space_id)
        root_folders = [f for f in folders if f.level == 0]

        # 3. Match folder by name
        matched_folder: KnowledgeFile | None = None
        for folder in root_folders:
            if folder.file_name == subcategory_label:
                matched_folder = folder
                break

        # 4. If found, return target with existing folder
        if matched_folder is not None:
            return AutoPublishTarget(
                space_id=target_space_id,
                folder_id=int(matched_folder.id),
                target_level=matched_folder.level + 1,
                target_file_level_path=f"/{matched_folder.id}",
            )

        # 5. If not found, create a new folder in root
        new_folder = await KnowledgeFileDao.aadd_file(
            KnowledgeFile(
                knowledge_id=target_space_id,
                file_name=subcategory_label,
                file_type=FileType.DIR.value,
                level=0,
                file_level_path="",
                user_id=system_user_id,
                tenant_id=tenant_id,
                status=KnowledgeFileStatus.SUCCESS.value,
            )
        )
        logger.info(
            "auto_publish_target: created folder '%s' (id=%s) in space_id=%s for subcategory_code=%s",
            subcategory_label,
            new_folder.id,
            target_space_id,
            file_subcategory_code,
        )
        return AutoPublishTarget(
            space_id=target_space_id,
            folder_id=int(new_folder.id),
            target_level=1,
            target_file_level_path=f"/{new_folder.id}",
        )

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    @classmethod
    async def _load_portal_config(cls, tenant_id: int) -> dict | None:
        """Load the portal section of the admin config JSON.

        Uses the same repository pattern as AutoPublishConfigService._load_rules_from_config.
        """
        from bisheng.core.database import get_async_db_session
        from bisheng.shougang_portal_config.domain.repositories.implementations.portal_admin_config_repository_impl import (
            PortalAdminConfigRepositoryImpl,
        )

        async with get_async_db_session() as session:
            repository = PortalAdminConfigRepositoryImpl(session)
            config_record = await repository.get(tenant_id)
            if config_record is None or not config_record.value:
                return None

        try:
            raw_config = json.loads(config_record.value)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "auto_publish_target: failed to parse portal config JSON for tenant_id=%s",
                tenant_id,
            )
            return None

        portal = raw_config.get("portal")
        if not isinstance(portal, dict):
            return None

        return portal

    @classmethod
    def _find_document_type_label(cls, document_types: list, file_category_code: str) -> str | None:
        """Find the label of a document_type by its code (case-insensitive)."""
        normalized_code = file_category_code.strip().upper()
        for dt in document_types:
            if not isinstance(dt, dict):
                continue
            code = str(dt.get("code", "")).strip().upper()
            if code == normalized_code:
                label = str(dt.get("label", "")).strip()
                return label if label else None
        return None

    @classmethod
    def _find_subcategory_label(cls, document_types: list, file_subcategory_code: str) -> str | None:
        """Find the label of a subcategory (child) by its code across all document types."""
        normalized_code = file_subcategory_code.strip().upper()
        for dt in document_types:
            if not isinstance(dt, dict):
                continue
            children = dt.get("children", [])
            if not isinstance(children, list):
                continue
            for child in children:
                if not isinstance(child, dict):
                    continue
                child_code = str(child.get("code", "")).strip().upper()
                if child_code == normalized_code:
                    label = str(child.get("label", "")).strip()
                    return label if label else None
        return None
