"""Build the recommendation projection from current file and ACL facts."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from bisheng.knowledge.domain.constants import get_business_domain_code_from_file
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileStatus
from bisheng.knowledge.domain.repositories.interfaces.portal_recommendation_repository import (
    PortalRecommendationProjectionUpsert,
)


@dataclass(frozen=True, slots=True)
class PortalRecommendationSourceFile:
    file_id: int
    space_id: int
    file_type: int
    status: int | None
    split_rule: str | dict | None
    file_encoding: str | None
    file_level_path: str | None
    source_update_time: datetime
    is_primary: bool | None


class _SourceRepository(Protocol):
    async def find_by_id(self, file_id: int) -> PortalRecommendationSourceFile | None: ...


class _ProjectionRepository(Protocol):
    async def upsert(self, value: PortalRecommendationProjectionUpsert) -> bool: ...

    async def delete(self, file_id: int, projection_version: int) -> bool: ...


BindingLoader = Callable[[], Sequence[dict] | Awaitable[Sequence[dict]]]


class PortalRecommendationProjectionService:
    def __init__(
        self,
        *,
        source_repository: _SourceRepository,
        projection_repository: _ProjectionRepository,
        binding_loader: BindingLoader | None = None,
    ):
        self.source_repository = source_repository
        self.projection_repository = projection_repository
        self.binding_loader = binding_loader or self._load_bindings

    @staticmethod
    async def _load_bindings() -> list[dict]:
        return await PortalRecommendationProjectionService.load_bindings_strict()

    @staticmethod
    async def load_bindings_strict() -> list[dict]:
        """Read bindings without converting malformed permission config to an empty ACL."""
        from bisheng.common.models.config import ConfigDao

        row = await ConfigDao.aget_config_by_key("permission_relation_model_bindings_v1")
        if row is None or not str(row.value or "").strip():
            return []
        try:
            bindings = json.loads(row.value)
        except Exception as exc:
            raise ValueError("invalid permission binding config JSON") from exc
        if not isinstance(bindings, list) or any(not isinstance(binding, dict) for binding in bindings):
            raise ValueError("invalid permission binding config shape")
        return bindings

    @staticmethod
    def _lineage_keys(file: Any) -> set[tuple[str, str]]:
        file_id = getattr(file, "file_id", None)
        if file_id is None:
            file_id = getattr(file, "id", None)
        space_id = getattr(file, "space_id", None)
        if space_id is None:
            space_id = getattr(file, "knowledge_id", None)
        file_level_path = getattr(file, "file_level_path", None) or ""
        result = {("knowledge_file", str(file_id))}
        if space_id is not None:
            result.update(
                {
                    ("knowledge_space", str(space_id)),
                    ("knowledge_library", str(space_id)),
                }
            )
        result.update(
            ("folder", part)
            for part in str(file_level_path).split("/")
            if part
        )
        return result

    @classmethod
    def has_custom_acl(cls, file: Any, bindings: Sequence[dict]) -> bool:
        lineage = cls._lineage_keys(file)
        return any(
            (str(binding.get("resource_type") or ""), str(binding.get("resource_id") or "")) in lineage
            for binding in bindings
        )

    @staticmethod
    def projection_version_for(source: PortalRecommendationSourceFile) -> int:
        update_time = source.source_update_time
        if update_time.tzinfo is None:
            update_time = update_time.replace(tzinfo=timezone.utc)
        return max(int(update_time.timestamp() * 1_000_000), 0)

    async def refresh_file(
        self,
        file_id: int,
        *,
        projection_version: int | None = None,
        deleted: bool = False,
    ) -> bool:
        source = None if deleted else await self.source_repository.find_by_id(int(file_id))
        if source is None:
            if projection_version is None:
                raise ValueError("projection_version is required for a delete event")
            return await self.projection_repository.delete(
                int(file_id),
                max(int(projection_version), 0),
            )

        permission_scope = "unknown"
        try:
            maybe_bindings = self.binding_loader()
            bindings = await maybe_bindings if inspect.isawaitable(maybe_bindings) else maybe_bindings
            permission_scope = "custom" if self.has_custom_acl(source, bindings) else "inherited"
        except Exception:
            permission_scope = "unknown"

        recommendable, reason_code = self._eligibility(source, permission_scope)
        version = (
            self.projection_version_for(source)
            if projection_version is None
            else max(int(projection_version), 0)
        )
        value = PortalRecommendationProjectionUpsert(
            file_id=int(source.file_id),
            space_id=int(source.space_id),
            business_domain_code=get_business_domain_code_from_file(source),
            permission_scope=permission_scope,
            recommendable=recommendable,
            reason_code=reason_code,
            source_update_time=source.source_update_time,
            projection_version=version,
        )
        return await self.projection_repository.upsert(value)

    @staticmethod
    def _eligibility(
        source: PortalRecommendationSourceFile,
        permission_scope: str,
    ) -> tuple[bool, str]:
        if int(source.file_type) != FileType.FILE.value:
            return False, "not_file"
        if source.status != KnowledgeFileStatus.SUCCESS.value:
            return False, "not_success"
        # Legacy files have no version row and are their own primary version.
        if source.is_primary is False:
            return False, "not_primary"
        if permission_scope == "custom":
            return False, "custom_acl"
        if permission_scope != "inherited":
            return False, "acl_unknown"
        return True, "eligible"
