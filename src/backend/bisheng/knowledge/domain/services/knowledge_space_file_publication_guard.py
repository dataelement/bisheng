from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge_space import SpaceFileChangeRequestNotFoundError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeRequest,
    KnowledgeSpaceFileChangeResourceType,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
    KnowledgeSpaceFileChangeRequestRepository,
)
from bisheng.knowledge.domain.repositories.knowledge_space_mutation_repository import (
    KnowledgeSpaceMutationRepository,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_approver_resolver import (
    KnowledgeSpaceFileChangeApproverResolver,
)
from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import (
    UploadExecutionStepCode,
)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@dataclass(frozen=True, slots=True)
class _UnpublishedResource:
    resource_id: int
    resource_type: str
    request: KnowledgeSpaceFileChangeRequest


class KnowledgeSpaceFilePublicationGuard:
    """F046 publication gate layered after the caller's normal ReBAC check.

    This guard never grants resource access. It only hides formal rows created
    for approved uploads until formal registration, permission writes and the
    regular parser handoff have completed.
    """

    _MANIFEST_KEY = "formal_resource_ids"
    _MANIFEST_RESOURCE_TYPES = frozenset(
        {
            KnowledgeSpaceFileChangeResourceType.FOLDER,
            KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
        }
    )

    def __init__(
        self,
        *,
        session_factory: SessionFactory = get_async_db_session,
        approver_resolver=KnowledgeSpaceFileChangeApproverResolver,
    ) -> None:
        self.session_factory = session_factory
        self.approver_resolver = approver_resolver

    async def list_unpublished_ids(
        self,
        *,
        tenant_id: int,
        space_ids: Sequence[int],
    ) -> set[int]:
        resources = await self._list_unpublished_resources(
            tenant_id=tenant_id,
            space_ids=space_ids,
        )
        return set(resources)

    async def filter_published_ids(
        self,
        *,
        tenant_id: int,
        space_ids: Sequence[int],
        resource_ids: Sequence[int],
    ) -> list[int]:
        """Preserve caller ordering while removing every unpublished ID."""
        unpublished_ids = await self.list_unpublished_ids(
            tenant_id=tenant_id,
            space_ids=space_ids,
        )
        return [int(resource_id) for resource_id in resource_ids if int(resource_id) not in unpublished_ids]

    async def require_published_or_stakeholder(
        self,
        *,
        tenant_id: int,
        space_id: int,
        resource_id: int,
        viewer_user_id: int,
    ) -> None:
        """Allow an unpublished preview only to its applicant/current approver.

        A successful return for a published or unrelated resource is not an
        authorization result; consumers must still enforce their existing
        ReBAC permission before calling the preview/download path.
        """
        resources = await self._list_unpublished_resources(
            tenant_id=tenant_id,
            space_ids=[space_id],
        )
        matching = resources.get(int(resource_id), [])
        if not matching:
            return
        if any(int(item.request.applicant_user_id) == int(viewer_user_id) for item in matching):
            return
        if await self.approver_resolver.is_current_approver(
            tenant_id=int(tenant_id),
            space_id=int(space_id),
            user_id=int(viewer_user_id),
        ):
            return
        # Use the same response for missing and invisible resources so a
        # non-stakeholder cannot probe unpublished names or request metadata.
        raise SpaceFileChangeRequestNotFoundError()

    async def _list_unpublished_resources(
        self,
        *,
        tenant_id: int,
        space_ids: Sequence[int],
    ) -> dict[int, list[_UnpublishedResource]]:
        normalized_space_ids = self._validate_scope(tenant_id=tenant_id, space_ids=space_ids)
        if not normalized_space_ids:
            return {}
        async with self.session_factory() as session:
            request_repository = KnowledgeSpaceFileChangeRequestRepository(session)
            requests = await request_repository.list_unpublished_upload_candidates(
                tenant_id=int(tenant_id),
                space_ids=normalized_space_ids,
                required_step_codes=UploadExecutionStepCode.BUSINESS_REQUIRED,
            )
            resources = self._resources_by_id(requests)
            created_folder_ids = {
                resource_id
                for resource_id, items in resources.items()
                if any(item.resource_type == KnowledgeSpaceFileChangeResourceType.FOLDER for item in items)
            }
            if created_folder_ids:
                published_paths = await KnowledgeSpaceMutationRepository(
                    session
                ).list_successful_file_paths_using_folders(
                    tenant_id=int(tenant_id),
                    space_ids=normalized_space_ids,
                    ancestor_folder_ids=sorted(created_folder_ids),
                )
                unpublished_ids = set(resources)
                for child_file_id, file_level_path in published_paths:
                    if child_file_id in unpublished_ids:
                        continue
                    for ancestor_id in self._path_ids(file_level_path):
                        if ancestor_id in created_folder_ids:
                            resources.pop(ancestor_id, None)
            return resources

    @classmethod
    def _resources_by_id(
        cls,
        requests: Sequence[KnowledgeSpaceFileChangeRequest],
    ) -> dict[int, list[_UnpublishedResource]]:
        resources: dict[int, list[_UnpublishedResource]] = {}
        for request in requests:
            manifest = (request.execution_checkpoint or {}).get(cls._MANIFEST_KEY)
            manifest_entries = manifest if isinstance(manifest, list) else []
            seen_for_request: set[int] = set()
            for entry in manifest_entries:
                if not isinstance(entry, dict):
                    continue
                resource_type = entry.get("resource_type")
                resource_id = entry.get("resource_id")
                if resource_type not in cls._MANIFEST_RESOURCE_TYPES or not cls._positive_int(resource_id):
                    continue
                normalized_id = int(resource_id)
                seen_for_request.add(normalized_id)
                resources.setdefault(normalized_id, []).append(
                    _UnpublishedResource(
                        resource_id=normalized_id,
                        resource_type=str(resource_type),
                        request=request,
                    )
                )
            # The indexed request link is always guarded even if an old or
            # malformed checkpoint lacks the business manifest. Never inspect
            # fga_resources: that structure is an external dispatch detail.
            if request.executed_resource_id is not None:
                normalized_id = int(request.executed_resource_id)
                if normalized_id not in seen_for_request:
                    resources.setdefault(normalized_id, []).append(
                        _UnpublishedResource(
                            resource_id=normalized_id,
                            resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
                            request=request,
                        )
                    )
        return resources

    @staticmethod
    def _path_ids(file_level_path: str) -> set[int]:
        return {int(part) for part in str(file_level_path).split("/") if part.isdigit() and int(part) > 0}

    @staticmethod
    def _positive_int(value: object) -> bool:
        try:
            return int(value) > 0
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _validate_scope(*, tenant_id: int, space_ids: Sequence[int]) -> list[int]:
        if int(tenant_id) <= 0:
            raise ValueError("tenant_id must be a positive integer")
        current_tenant_id = get_current_tenant_id()
        if current_tenant_id is None or int(current_tenant_id) != int(tenant_id):
            raise RuntimeError("a matching tenant context is required for publication guards")
        normalized_space_ids = sorted({int(space_id) for space_id in space_ids})
        if any(space_id <= 0 for space_id in normalized_space_ids):
            raise ValueError("space_ids must contain only positive integers")
        return normalized_space_ids
