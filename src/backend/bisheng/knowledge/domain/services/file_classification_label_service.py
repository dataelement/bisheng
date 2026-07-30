"""Lightweight resolver for configured file classification labels.

This module deliberately avoids the auto-tag/LLM dependency graph so telemetry
workers can enrich file projections without importing model runtimes.
"""

from typing import Any

from loguru import logger
from sqlmodel import select

from bisheng.common.models.config import Config
from bisheng.common.services.config_service import settings
from bisheng.core.config.settings import DEFAULT_SHOUGANG_FILE_DOCUMENT_TYPES
from bisheng.core.database import get_sync_db_session
from bisheng.knowledge.domain.constants import normalize_file_category_code
from bisheng.shougang_portal_config.domain.repositories.interfaces.portal_admin_config_repository import (
    portal_admin_config_physical_key,
)
from bisheng.shougang_portal_config.domain.schemas.portal_config_schema import (
    ShougangPortalAdminConfig,
)


class FileClassificationLabelService:
    @staticmethod
    def _item_value(item: Any, key: str):
        return item.get(key) if isinstance(item, dict) else getattr(item, key, None)

    @classmethod
    def _item_label(cls, item: Any, fallback: str) -> str:
        label = cls._item_value(item, "label")
        return label.strip() if isinstance(label, str) and label.strip() else fallback

    @classmethod
    def build_label_lookup(
        cls,
        raw_document_types: list[Any],
    ) -> tuple[dict[str, str], dict[str, str]]:
        parent_labels: dict[str, str] = {}
        subcategory_labels: dict[str, str] = {}
        for item in raw_document_types or DEFAULT_SHOUGANG_FILE_DOCUMENT_TYPES:
            parent_code = normalize_file_category_code(cls._item_value(item, "code"))
            if not parent_code:
                continue
            parent_labels[parent_code] = cls._item_label(item, parent_code)

            raw_children = cls._item_value(item, "children")
            children = raw_children if isinstance(raw_children, list) and raw_children else [item]
            for child in children:
                child_code = normalize_file_category_code(cls._item_value(child, "code"))
                if child_code:
                    subcategory_labels[child_code] = cls._item_label(child, child_code)
        return parent_labels, subcategory_labels

    @classmethod
    def load_document_types_for_tenant(cls, tenant_id: int | None) -> list[Any]:
        resolved_tenant_id = int(tenant_id or 1)
        try:
            with get_sync_db_session() as session:
                config_row = session.exec(
                    select(Config).where(
                        Config.key == portal_admin_config_physical_key(resolved_tenant_id)
                    )
                ).first()
            if config_row and config_row.value:
                portal_config = ShougangPortalAdminConfig.model_validate_json(config_row.value)
                document_types = (
                    getattr(getattr(portal_config, "portal", None), "document_types", None)
                    or []
                )
                if document_types:
                    return list(document_types)
        except Exception:
            logger.warning(
                "file_classification_labels_portal_config_failed tenant_id={}",
                resolved_tenant_id,
            )

        try:
            shougang_conf = settings.get_all_config().get("shougang", {}) or {}
            file_encoding_conf = shougang_conf.get("file_encoding", {}) or {}
            document_types = file_encoding_conf.get("document_types")
            if isinstance(document_types, list) and document_types:
                return document_types
        except Exception:
            logger.warning(
                "file_classification_labels_shougang_config_failed tenant_id={}",
                resolved_tenant_id,
            )
        return list(DEFAULT_SHOUGANG_FILE_DOCUMENT_TYPES)

    @classmethod
    def get_label_lookup_for_tenant(
        cls,
        tenant_id: int | None,
    ) -> tuple[dict[str, str], dict[str, str]]:
        return cls.build_label_lookup(cls.load_document_types_for_tenant(tenant_id))
