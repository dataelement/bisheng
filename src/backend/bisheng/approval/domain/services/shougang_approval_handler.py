from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from typing import Any

from bisheng.approval.domain.services.approver_resolver import (
    resolve_approvers_from_sources,
    resolve_file_publish_department_admins,
)
from bisheng.approval.domain.services.knowledge_space_subscribe_scenario_handler import _resolve_space_roles_via_fga
from bisheng.knowledge.domain.constants import normalize_business_domain_code
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileDao,
    KnowledgeFileEntryType,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum, KnowledgeSpaceScopeDao

KNOWLEDGE_SPACE_CREATE_SCENARIO = "knowledge_space_create_request"
FILE_PUBLISH_SCENARIO = "knowledge_space_file_publish_request"
FILE_SHARE_SCENARIO = "knowledge_space_file_share_request"
FILE_PUBLISH_DOMAIN_MISMATCH_MESSAGE = "您发布的文档与目标库不符"
logger = logging.getLogger(__name__)

FILE_PUBLISH_TARGET_LEVELS: dict[KnowledgeSpaceLevelEnum, set[KnowledgeSpaceLevelEnum]] = {
    KnowledgeSpaceLevelEnum.PERSONAL: {
        KnowledgeSpaceLevelEnum.TEAM,
        KnowledgeSpaceLevelEnum.TEAM_KS,
    },
    KnowledgeSpaceLevelEnum.TEAM: {
        KnowledgeSpaceLevelEnum.DEPARTMENT,
    },
    KnowledgeSpaceLevelEnum.TEAM_KS: {
        KnowledgeSpaceLevelEnum.DEPARTMENT,
    },
    KnowledgeSpaceLevelEnum.DEPARTMENT: {
        KnowledgeSpaceLevelEnum.PUBLIC,
    },
}


class _RuntimeLoginUser:
    def __init__(self, *, user_id: int, user_name: str, tenant_id: int, elevated: bool = False) -> None:
        self.user_id = int(user_id)
        self.user_name = user_name
        self.tenant_id = int(tenant_id)
        self._elevated = elevated

    def is_admin(self) -> bool:
        return self._elevated


def _runtime_request() -> Any:
    return SimpleNamespace(headers={}, client=SimpleNamespace(host="approval-runtime"))


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _file_publish_pair_allowed(source_level, target_level) -> bool:
    source_level = (
        source_level
        if isinstance(source_level, KnowledgeSpaceLevelEnum)
        else KnowledgeSpaceLevelEnum(str(source_level))
    )
    target_level = (
        target_level
        if isinstance(target_level, KnowledgeSpaceLevelEnum)
        else KnowledgeSpaceLevelEnum(str(target_level))
    )
    return target_level in FILE_PUBLISH_TARGET_LEVELS.get(source_level, set())


async def _restore_unapproved_distribution_source(
    payload_snapshot: dict,
) -> bool:
    document_id = payload_snapshot.get("canonical_document_id")
    source_file_id = payload_snapshot.get("source_entry_id")
    tenant_id = payload_snapshot.get("tenant_id")
    if document_id is None or source_file_id is None or tenant_id is None:
        return False
    original_entry_type = payload_snapshot.get("source_entry_type_before_submit")
    if original_entry_type not in {None, "normal"}:
        return False

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
        KnowledgeDocumentDistributionService,
    )
    from bisheng.knowledge.domain.services.knowledge_document_permission_activation_service import (
        KnowledgeDocumentPermissionActivationService,
    )

    async with get_async_db_session() as session:
        file_repository = KnowledgeFileRepositoryImpl(session)
        service = KnowledgeDocumentDistributionService(
            session=session,
            document_repository=KnowledgeDocumentRepositoryImpl(session),
            version_repository=KnowledgeDocumentVersionRepositoryImpl(session),
            file_repository=file_repository,
            permission_activation_service=(
                KnowledgeDocumentPermissionActivationService(
                    file_repository=file_repository,
                )
            ),
        )
        return await service.restore_unapproved_manager(
            tenant_id=int(tenant_id),
            document_id=int(document_id),
            source_file_id=int(source_file_id),
        )


def _normalize_file_publish_business_domain_codes(raw_codes: Any) -> list[str]:
    normalized_codes: list[str] = []
    seen: set[str] = set()
    for raw_code in raw_codes or []:
        code = normalize_business_domain_code(raw_code)
        if not code or code in seen:
            continue
        normalized_codes.append(code)
        seen.add(code)
    return normalized_codes


def _extract_file_publish_business_domain_code(source_file: Any) -> str:
    file_encoding = str(getattr(source_file, "file_encoding", "") or "").strip()
    parts = [part.strip() for part in file_encoding.split("-")]
    if len(parts) < 4:
        return ""
    return normalize_business_domain_code(parts[2]) or ""


def ensure_file_publish_business_domain_matches(source_file: Any, target_space: Any) -> None:
    allowed_codes = _normalize_file_publish_business_domain_codes(getattr(target_space, "business_domain_codes", None))
    if not allowed_codes:
        return
    source_code = _extract_file_publish_business_domain_code(source_file)
    if source_code not in allowed_codes:
        raise ValueError(FILE_PUBLISH_DOMAIN_MISMATCH_MESSAGE)


async def _copy_file_tags(
    *,
    source_file_id: int,
    target_file_id: int,
    user_id: int,
    tenant_id: int,
) -> None:
    """Copy approved and pending review tag links from source file to the published copy."""
    from bisheng.database.models.group_resource import ResourceTypeEnum
    from bisheng.database.models.review_tags import ReviewTagDao
    from bisheng.database.models.tag import TagDao

    source_rid = str(source_file_id)
    target_rid = str(target_file_id)
    resource_types = [ResourceTypeEnum.SPACE_FILE]

    tag_dict = await asyncio.to_thread(
        TagDao.get_tags_by_resource_batch,
        resource_types,
        [source_rid],
    )
    review_tag_dict = await asyncio.to_thread(
        ReviewTagDao.get_tags_by_resource_batch,
        resource_types,
        [source_rid],
        tenant_id=tenant_id,
    )

    approved_tag_ids = list(dict.fromkeys(tag.id for tag in tag_dict.get(source_rid, []) if getattr(tag, "id", None)))
    if approved_tag_ids:
        await TagDao.add_tags(approved_tag_ids, target_rid, ResourceTypeEnum.SPACE_FILE, user_id)

    pending_review_tag_ids = list(
        dict.fromkeys(
            tag.id
            for tag in review_tag_dict.get(source_rid, [])
            if getattr(tag, "id", None) and getattr(tag, "review_status", 0) == 0
        )
    )
    if pending_review_tag_ids:
        await ReviewTagDao.add_tags(
            pending_review_tag_ids,
            target_rid,
            ResourceTypeEnum.SPACE_FILE,
            user_id,
            tenant_id=tenant_id,
        )


async def _resolve_approvers(node_config: dict, req) -> list[int]:
    sources = node_config.get("sources") or []
    if sources:
        return await resolve_approvers_from_sources(sources, req)
    approver_ids = node_config.get("approver_user_ids") or node_config.get("user_ids") or []
    return [int(one) for one in approver_ids]


async def _resolve_file_publish_approvers(node_config: dict, req) -> list[int]:
    sources = node_config.get("sources") or []
    if not sources:
        approver_ids = node_config.get("approver_user_ids") or node_config.get("user_ids") or []
        return [int(one) for one in approver_ids]

    seen: set[int] = set()
    result: list[int] = []

    def _add(uid: int) -> None:
        if uid not in seen:
            seen.add(uid)
            result.append(uid)

    source_space_role_types = {"knowledge_space_owner", "knowledge_space_manager"}
    target_space_role_types = {"target_knowledge_space_owner", "target_knowledge_space_manager", "space_admin"}
    target_department_admin_types = {
        "target_knowledge_space_owner_department_admin",
        "target_knowledge_space_manager_department_admin",
    }
    publish_department_admin_types = {"department_admin"} | target_department_admin_types
    payload_snapshot = getattr(req, "payload_snapshot", {}) or {}
    source_owner_ids: list[int] = []
    source_manager_ids: list[int] = []
    target_owner_ids: list[int] = []
    target_manager_ids: list[int] = []
    if any(source.get("type") in source_space_role_types for source in sources):
        source_space_id = payload_snapshot.get("source_space_id")
        if source_space_id:
            source_owner_ids, source_manager_ids = await _resolve_space_roles_via_fga(int(source_space_id))
    if any(source.get("type") in target_space_role_types | target_department_admin_types for source in sources):
        target_space_id = payload_snapshot.get("target_space_id")
        if target_space_id:
            target_owner_ids, target_manager_ids = await _resolve_space_roles_via_fga(int(target_space_id))

    publish_department_admin_ids: list[int] = []
    if any(source.get("type") in publish_department_admin_types for source in sources):
        start_department_ids: list[int] = []
        start_user_ids: list[int] = []
        if any(source.get("type") == "department_admin" for source in sources):
            applicant_department_id = payload_snapshot.get("applicant_department_id")
            if applicant_department_id is None:
                applicant_department_id = getattr(req, "applicant_department_id", None)
            if applicant_department_id:
                start_department_ids.append(int(applicant_department_id))
        if any(source.get("type") == "target_knowledge_space_owner_department_admin" for source in sources):
            start_user_ids.extend(int(uid) for uid in target_owner_ids)
        if any(source.get("type") == "target_knowledge_space_manager_department_admin" for source in sources):
            start_user_ids.extend(int(uid) for uid in target_manager_ids)
        publish_department_admin_ids = await resolve_file_publish_department_admins(
            start_department_ids=start_department_ids,
            start_user_ids=start_user_ids,
            applicant_user_id=None,
        )

    department_admins_added = False
    for source in sources:
        source_type = source.get("type", "")
        if source_type == "knowledge_space_owner":
            for uid in source_owner_ids:
                _add(int(uid))
        elif source_type == "knowledge_space_manager":
            for uid in source_manager_ids:
                _add(int(uid))
        elif source_type == "target_knowledge_space_owner":
            for uid in target_owner_ids:
                _add(int(uid))
        elif source_type in ("target_knowledge_space_manager", "space_admin"):
            for uid in target_manager_ids:
                _add(int(uid))
        elif source_type in publish_department_admin_types:
            if not department_admins_added:
                for uid in publish_department_admin_ids:
                    _add(int(uid))
                department_admins_added = True
        else:
            for uid in await resolve_approvers_from_sources([source], req):
                _add(int(uid))
    return result


def _approval_instance_id_from_metadata(metadata: Any) -> int | None:
    if isinstance(metadata, dict):
        approval_meta = metadata.get("shougang_approval") or metadata.get("shougang_portal_publish")
        if isinstance(approval_meta, dict) and approval_meta.get("approval_instance_id") is not None:
            return int(approval_meta["approval_instance_id"])
        if metadata.get("approval_instance_id") is not None:
            return int(metadata["approval_instance_id"])
    if isinstance(metadata, list):
        for item in metadata:
            instance_id = _approval_instance_id_from_metadata(item)
            if instance_id is not None:
                return instance_id
    return None


def _copied_file_error_summary(copied_file: KnowledgeFile) -> str:
    remark = str(getattr(copied_file, "remark", "") or "").strip()
    if not remark:
        return "copy file failed"
    try:
        payload = json.loads(remark)
    except (TypeError, ValueError):
        return remark
    error_data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(error_data, dict) and error_data.get("exception"):
        return str(error_data["exception"])
    if isinstance(payload, dict) and payload.get("status_message"):
        return str(payload["status_message"])
    return remark


def _metadata_with_approval_instance(metadata: Any, instance_id: int) -> list[dict]:
    items = list(metadata or []) if isinstance(metadata, list) else []
    return [
        *items,
        {"shougang_approval": {"approval_instance_id": int(instance_id)}},
    ]


class KnowledgeSpaceCreateApprovalHandler:
    scenario_code = KNOWLEDGE_SPACE_CREATE_SCENARIO

    async def validate(self, req, login_user) -> None:
        return None

    async def build_title(self, req) -> str:
        return f"新建知识库：{req.payload_snapshot.get('create_params', {}).get('name') or req.business_name}"

    async def build_detail(self, req) -> dict:
        params = req.payload_snapshot.get("create_params") or {}
        return {
            "type": "knowledge_space_create",
            "name": params.get("name"),
            "space_level": params.get("space_level"),
            "department_id": params.get("department_id"),
            "user_group_id": params.get("user_group_id"),
            "auth_type": params.get("auth_type"),
            "is_released": params.get("is_released"),
            "reason": req.reason,
            "applicant_user_id": req.applicant_user_id,
            "applicant_user_name": req.applicant_user_name,
        }

    async def build_business_link(self, req) -> dict:
        return {"scenario_code": self.scenario_code}

    async def resolve_approvers(self, node_config: dict, req) -> list[int]:
        return await _resolve_approvers(node_config, req)

    async def _find_created_space(self, instance_id: int, applicant_user_id: int):
        spaces = await KnowledgeDao.async_get_spaces_by_user(applicant_user_id)
        for space in spaces:
            if _approval_instance_id_from_metadata(space.metadata_fields) == int(instance_id):
                return space
        return None

    async def _ensure_admin_only_level_applicant_is_admin(self, applicant_user_id: int, params: dict) -> None:
        level = _enum_value(params.get("space_level"))
        if level not in {KnowledgeSpaceLevelEnum.PUBLIC.value, KnowledgeSpaceLevelEnum.DEPARTMENT.value}:
            return
        from bisheng.common.errcode.knowledge_space import (
            SpaceCreateDepartmentDeniedError,
            SpaceCreatePublicDeniedError,
        )
        from bisheng.database.constants import AdminRole
        from bisheng.user.domain.models.user_role import UserRoleDao

        roles = await UserRoleDao.aget_user_roles(int(applicant_user_id))
        if not any(int(getattr(role, "role_id", 0)) == AdminRole for role in roles):
            if level == KnowledgeSpaceLevelEnum.DEPARTMENT.value:
                raise SpaceCreateDepartmentDeniedError()
            raise SpaceCreatePublicDeniedError()

    async def on_approved(self, instance_id: int, payload_snapshot: dict) -> dict:
        from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

        applicant_user_id = int(payload_snapshot["applicant_user_id"])
        existing_space = await self._find_created_space(instance_id, applicant_user_id)
        if existing_space:
            return {"space_id": int(existing_space.id), "space_name": existing_space.name, "idempotent": True}

        params = payload_snapshot.get("create_params") or {}
        await self._ensure_admin_only_level_applicant_is_admin(applicant_user_id, params)
        login_user = _RuntimeLoginUser(
            user_id=applicant_user_id,
            user_name=str(payload_snapshot.get("applicant_user_name") or ""),
            tenant_id=int(payload_snapshot["tenant_id"]),
            elevated=True,
        )
        service = KnowledgeSpaceService(request=_runtime_request(), login_user=login_user)
        await service.validate_knowledge_space_create(**params)
        space = await service.create_knowledge_space(**params)
        space.metadata_fields = _metadata_with_approval_instance(space.metadata_fields, instance_id)
        space = await KnowledgeDao.async_update_space(space)
        return {"space_id": int(space.id), "space_name": space.name}

    async def on_rejected(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        return None

    async def on_withdrawn(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        return None


class KnowledgeSpaceFilePublishApprovalHandler:
    scenario_code = FILE_PUBLISH_SCENARIO

    async def validate(self, req, login_user) -> None:
        return None

    async def build_title(self, req) -> str:
        source_name = req.payload_snapshot.get("source_file_name") or req.business_name
        target_name = req.payload_snapshot.get("target_space_name") or ""
        return f"发布文件：{source_name} → {target_name}".rstrip()

    async def build_detail(self, req) -> dict:
        return {
            "type": "knowledge_space_file_publish",
            "source_space_id": req.payload_snapshot.get("source_space_id"),
            "source_space_name": req.payload_snapshot.get("source_space_name"),
            "source_file_id": req.payload_snapshot.get("source_file_id"),
            "source_file_name": req.payload_snapshot.get("source_file_name"),
            "target_space_id": req.payload_snapshot.get("target_space_id"),
            "target_space_name": req.payload_snapshot.get("target_space_name"),
            "target_folder_id": req.payload_snapshot.get("target_folder_id"),
            "target_folder_name": req.payload_snapshot.get("target_folder_name"),
            "target_document_id": req.payload_snapshot.get("target_document_id"),
            "target_document_title": req.payload_snapshot.get("target_document_title"),
            "reason": req.reason,
            "applicant_user_id": req.applicant_user_id,
            "applicant_user_name": req.applicant_user_name,
        }

    async def build_business_link(self, req) -> dict:
        return {
            "source_file_id": req.payload_snapshot.get("source_file_id"),
            "target_space_id": req.payload_snapshot.get("target_space_id"),
            "target_folder_id": req.payload_snapshot.get("target_folder_id"),
        }

    async def resolve_approvers(self, node_config: dict, req) -> list[int]:
        return await _resolve_file_publish_approvers(node_config, req)

    def _copy_file(
        self,
        source_file: KnowledgeFile,
        source_space,
        target_space,
        user_id: int,
        instance_id: int,
        target_level: int = 0,
        target_file_level_path: str = "",
    ) -> KnowledgeFile | None:
        from bisheng.worker.knowledge import file_worker

        extra_user_metadata = {
            "shougang_portal_publish": {
                "approval_instance_id": int(instance_id),
                "source_space_id": source_space.id,
                "source_file_id": source_file.id,
            }
        }
        return file_worker.copy_normal(
            source_file,
            source_space,
            target_space,
            user_id,
            extra_user_metadata=extra_user_metadata,
            target_level=target_level,
            target_file_level_path=target_file_level_path,
        )

    async def _find_copied_file(self, instance_id: int, target_space_id: int) -> KnowledgeFile | None:
        files = await KnowledgeFileDao.aget_file_by_filters(target_space_id)
        for file in files:
            if (
                _approval_instance_id_from_metadata(file.user_metadata) == int(instance_id)
                and file.status == KnowledgeFileStatus.SUCCESS.value
            ):
                return file
        return None

    async def _space_level(self, space_id: int) -> KnowledgeSpaceLevelEnum:
        scope = await KnowledgeSpaceScopeDao.aget_by_space_id(space_id)
        return scope.level if scope else KnowledgeSpaceLevelEnum.PERSONAL

    @staticmethod
    async def _enqueue_content_statistics(file_ids: list[int]) -> None:
        try:
            from bisheng.telemetry.domain.mid_table.knowledge_space_content import (
                KnowledgeSpaceContentStat,
            )

            await KnowledgeSpaceContentStat.enqueue_file_stat_async(file_ids)
        except Exception:
            logger.warning(
                "Knowledge space content statistics enqueue failed file_ids=%s",
                file_ids,
                exc_info=True,
            )

    async def _publish_distribution(
        self,
        instance_id: int,
        payload_snapshot: dict,
    ) -> dict:
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
            KnowledgeDocumentDistributionService,
            PublishKnowledgeDocumentCommand,
        )
        from bisheng.knowledge.domain.services.knowledge_document_permission_activation_service import (
            KnowledgeDocumentPermissionActivationService,
        )

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
            await service.normalize_manager(
                tenant_id=int(payload_snapshot["tenant_id"]),
                source_file_id=int(payload_snapshot["source_entry_id"]),
                expected_document_id=int(payload_snapshot["canonical_document_id"]),
            )
            result = await service.publish_approved(
                PublishKnowledgeDocumentCommand(
                    tenant_id=int(payload_snapshot["tenant_id"]),
                    approval_instance_id=int(instance_id),
                    document_id=int(payload_snapshot["canonical_document_id"]),
                    source_entry_id=int(payload_snapshot["source_entry_id"]),
                    target_space_id=int(payload_snapshot["target_space_id"]),
                    target_file_level_path=str(
                        payload_snapshot.get("target_folder_level_path") or ""
                    ),
                    target_level=int(
                        payload_snapshot.get("target_folder_level") or 0
                    ),
                    target_document_id=(
                        int(payload_snapshot["target_document_id"])
                        if payload_snapshot.get("target_document_id")
                        else None
                    ),
                )
            )
        try:
            from bisheng.worker.knowledge.document_projection import (
                enqueue_document_projection_entries,
            )

            enqueue_document_projection_entries(
                tenant_id=int(payload_snapshot["tenant_id"]),
                entry_ids=[
                    result.manager_file_id,
                    result.publish_entry_id,
                ],
            )
        except Exception:
            logger.warning(
                "F059 publish projection enqueue failed; Beat will recover "
                "document_id=%s",
                result.document_id,
                exc_info=True,
            )
        await self._enqueue_content_statistics(
            [
                result.manager_file_id,
                result.publish_entry_id,
            ]
        )
        logger.info(
            "F059 publish applied tenant_id=%s document_id=%s "
            "manager_entry_id=%s publish_entry_id=%s target_space_id=%s "
            "idempotent=%s",
            payload_snapshot["tenant_id"],
            result.document_id,
            result.manager_file_id,
            result.publish_entry_id,
            result.target_space_id,
            result.idempotent,
        )
        return {
            "document_id": result.document_id,
            "file_id": result.manager_file_id,
            "publish_entry_id": result.publish_entry_id,
            "target_space_id": result.target_space_id,
            "idempotent": result.idempotent,
        }

    async def on_approved(self, instance_id: int, payload_snapshot: dict) -> dict:
        if payload_snapshot.get("canonical_document_id") is not None:
            source_space = await KnowledgeDao.aquery_by_id(
                int(payload_snapshot["source_space_id"])
            )
            target_space = await KnowledgeDao.aquery_by_id(
                int(payload_snapshot["target_space_id"])
            )
            if (
                source_space is None
                or target_space is None
                or source_space.state != KnowledgeState.PUBLISHED.value
                or target_space.state != KnowledgeState.PUBLISHED.value
            ):
                raise ValueError("source or target space is no longer published")
            source_level = await self._space_level(int(payload_snapshot["source_space_id"]))
            target_level = await self._space_level(int(payload_snapshot["target_space_id"]))
            if not _file_publish_pair_allowed(source_level, target_level):
                raise ValueError("source and target space levels are not allowed for publish")
            return await self._publish_distribution(
                instance_id,
                payload_snapshot,
            )

        from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

        source_space_id = int(payload_snapshot["source_space_id"])
        source_file_id = int(payload_snapshot["source_file_id"])
        target_space_id = int(payload_snapshot["target_space_id"])
        target_folder_id = payload_snapshot.get("target_folder_id")
        target_folder_id = int(target_folder_id) if target_folder_id else None
        target_document_id = payload_snapshot.get("target_document_id")
        target_file_id = payload_snapshot.get("target_file_id")

        async def resolve_target_document_id(login_user: _RuntimeLoginUser) -> int | None:
            if target_document_id:
                return int(target_document_id)
            if target_file_id:
                return await _ensure_file_publish_target_document(
                    login_user=login_user,
                    target_file_id=int(target_file_id),
                )
            return None

        existing_file = await self._find_copied_file(instance_id, target_space_id)
        if existing_file:
            await _copy_file_tags(
                source_file_id=source_file_id,
                target_file_id=int(existing_file.id),
                user_id=int(payload_snapshot["applicant_user_id"]),
                tenant_id=int(payload_snapshot["tenant_id"]),
            )
            version_result = None
            login_user = _RuntimeLoginUser(
                user_id=int(payload_snapshot["applicant_user_id"]),
                user_name=str(payload_snapshot.get("applicant_user_name") or ""),
                tenant_id=int(payload_snapshot["tenant_id"]),
                elevated=True,
            )
            resolved_target_document_id = await resolve_target_document_id(login_user)
            if resolved_target_document_id:
                version_result = await _link_file_as_version(
                    login_user=login_user,
                    knowledge_file_id=int(existing_file.id),
                    target_document_id=resolved_target_document_id,
                    file_level_path=getattr(existing_file, "file_level_path", "") or "",
                    level=int(getattr(existing_file, "level", 0) or 0),
                )
            from bisheng.worker.knowledge.portal_recommendation import (
                enqueue_portal_recommendation_projection_refresh,
            )

            enqueue_portal_recommendation_projection_refresh(
                file_id=int(existing_file.id),
                tenant_id=int(payload_snapshot["tenant_id"]),
            )
            await self._enqueue_content_statistics([int(existing_file.id)])
            return {
                "file_id": int(existing_file.id),
                "target_space_id": target_space_id,
                "version": version_result,
                "idempotent": True,
            }

        source_space = await KnowledgeDao.aquery_by_id(source_space_id)
        target_space = await KnowledgeDao.aquery_by_id(target_space_id)
        source_file = await KnowledgeFileDao.query_by_id(source_file_id)
        if not source_space or source_space.type != KnowledgeTypeEnum.SPACE.value:
            raise ValueError("source space not found")
        if not target_space or target_space.type != KnowledgeTypeEnum.SPACE.value:
            raise ValueError("target space not found")
        if not source_file or source_file.knowledge_id != source_space_id:
            raise ValueError("source file not found")
        source_level = await self._space_level(source_space_id)
        target_level = await self._space_level(target_space_id)
        if not _file_publish_pair_allowed(source_level, target_level):
            raise ValueError("source and target space levels are not allowed for publish")
        if source_file.status != KnowledgeFileStatus.SUCCESS.value:
            raise ValueError("source file is not parsed successfully")
        ensure_file_publish_business_domain_matches(source_file, target_space)

        target_parent_type = "knowledge_space"
        target_parent_id = target_space_id
        copy_target_level = 0
        copy_target_file_level_path = ""
        if target_folder_id is not None:
            target_folder = await KnowledgeFileDao.query_by_id(target_folder_id)
            if (
                not target_folder
                or int(target_folder.knowledge_id) != target_space_id
                or int(target_folder.file_type) != FileType.DIR.value
            ):
                raise ValueError("target folder not found")
            copy_target_level = int(target_folder.level or 0) + 1
            folder_level_path = (target_folder.file_level_path or "").rstrip("/")
            copy_target_file_level_path = (
                f"{folder_level_path}/{target_folder_id}" if folder_level_path else f"/{target_folder_id}"
            )
            target_parent_type = "folder"
            target_parent_id = target_folder_id

        copied_file = await asyncio.to_thread(
            self._copy_file,
            source_file,
            source_space,
            target_space,
            int(payload_snapshot["applicant_user_id"]),
            instance_id,
            copy_target_level,
            copy_target_file_level_path,
        )
        if not copied_file or not copied_file.id:
            raise ValueError("copy file failed")
        if copied_file.status != KnowledgeFileStatus.SUCCESS.value:
            raise RuntimeError(_copied_file_error_summary(copied_file))

        await _copy_file_tags(
            source_file_id=source_file_id,
            target_file_id=int(copied_file.id),
            user_id=int(payload_snapshot["applicant_user_id"]),
            tenant_id=int(payload_snapshot["tenant_id"]),
        )

        login_user = _RuntimeLoginUser(
            user_id=int(payload_snapshot["applicant_user_id"]),
            user_name=str(payload_snapshot.get("applicant_user_name") or ""),
            tenant_id=int(payload_snapshot["tenant_id"]),
            elevated=True,
        )
        space_service = KnowledgeSpaceService(request=_runtime_request(), login_user=login_user)
        await space_service._initialize_child_resource_permissions(
            "knowledge_file",
            int(copied_file.id),
            target_parent_type,
            target_parent_id,
        )
        await KnowledgeDao.async_update_knowledge_update_time_by_id(target_space_id)

        version_result = None
        resolved_target_document_id = await resolve_target_document_id(login_user)
        if resolved_target_document_id:
            version_result = await _link_file_as_version(
                login_user=login_user,
                knowledge_file_id=int(copied_file.id),
                target_document_id=resolved_target_document_id,
                file_level_path=copy_target_file_level_path,
                level=copy_target_level,
            )
        from bisheng.worker.knowledge.portal_recommendation import (
            enqueue_portal_recommendation_projection_refresh,
        )

        enqueue_portal_recommendation_projection_refresh(
            file_id=int(copied_file.id),
            tenant_id=int(payload_snapshot["tenant_id"]),
        )
        await self._enqueue_content_statistics([int(copied_file.id)])
        return {
            "file_id": int(copied_file.id),
            "target_space_id": target_space_id,
            "version": version_result,
        }

    async def on_rejected(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        await _restore_unapproved_distribution_source(payload_snapshot)

    async def on_withdrawn(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        await _restore_unapproved_distribution_source(payload_snapshot)

    async def on_cancelled(
        self,
        instance_id: int,
        payload_snapshot: dict,
        reason: str | None,
    ) -> None:
        await _restore_unapproved_distribution_source(payload_snapshot)


class KnowledgeSpaceFileShareApprovalHandler:
    scenario_code = FILE_SHARE_SCENARIO

    async def validate(self, req, login_user) -> None:
        return None

    async def build_title(self, req) -> str:
        source_name = (
            req.payload_snapshot.get("source_file_name")
            or req.business_name
        )
        target_name = req.payload_snapshot.get("target_space_name") or ""
        return f"分享文件：{source_name} → {target_name}".rstrip()

    async def build_detail(self, req) -> dict:
        return {
            "type": "knowledge_space_file_share",
            "source_space_id": req.payload_snapshot.get("source_space_id"),
            "source_space_name": req.payload_snapshot.get("source_space_name"),
            "source_file_id": req.payload_snapshot.get("source_file_id"),
            "source_file_name": req.payload_snapshot.get("source_file_name"),
            "target_space_id": req.payload_snapshot.get("target_space_id"),
            "target_space_name": req.payload_snapshot.get("target_space_name"),
            "target_folder_id": req.payload_snapshot.get("target_folder_id"),
            "target_folder_name": req.payload_snapshot.get("target_folder_name"),
            "allow_download": bool(
                req.payload_snapshot.get("allow_download")
            ),
            "reason": req.reason,
            "applicant_user_id": req.applicant_user_id,
            "applicant_user_name": req.applicant_user_name,
        }

    async def build_business_link(self, req) -> dict:
        return {
            "source_file_id": req.payload_snapshot.get("source_file_id"),
            "target_space_id": req.payload_snapshot.get("target_space_id"),
            "target_folder_id": req.payload_snapshot.get("target_folder_id"),
        }

    async def resolve_approvers(self, node_config: dict, req) -> list[int]:
        return await _resolve_file_publish_approvers(node_config, req)

    @staticmethod
    async def _resolve_target_location(
        payload_snapshot: dict,
    ) -> tuple[str, int]:
        from bisheng.knowledge.domain.services.knowledge_space_service import (
            KnowledgeSpaceService,
        )

        target_space_id = int(payload_snapshot["target_space_id"])
        if not await KnowledgeSpaceService.is_valid_department_space_id(target_space_id):
            raise ValueError("share target department space is no longer valid")
        target_space = await KnowledgeDao.aquery_by_id(target_space_id)
        if (
            target_space is None
            or int(target_space.tenant_id) != int(payload_snapshot["tenant_id"])
            or target_space.state != KnowledgeState.PUBLISHED.value
        ):
            raise ValueError("share target department space is no longer valid")

        target_folder_id = payload_snapshot.get("target_folder_id")
        if target_folder_id is None:
            return "", 0
        folder_id = int(target_folder_id)
        target_folder = await KnowledgeFileDao.query_by_id(folder_id)
        if (
            target_folder is None
            or int(target_folder.knowledge_id) != target_space_id
            or int(target_folder.file_type) != FileType.DIR.value
        ):
            raise ValueError("share target folder is no longer valid")
        parent_path = str(target_folder.file_level_path or "").rstrip("/")
        return (
            f"{parent_path}/{folder_id}" if parent_path else f"/{folder_id}",
            int(target_folder.level or 0) + 1,
        )

    async def on_approved(
        self,
        instance_id: int,
        payload_snapshot: dict,
    ) -> dict:
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
            KnowledgeDocumentDistributionService,
            ShareKnowledgeDocumentCommand,
        )
        from bisheng.knowledge.domain.services.knowledge_document_permission_activation_service import (
            KnowledgeDocumentPermissionActivationService,
        )

        target_file_level_path, target_level = (
            await self._resolve_target_location(payload_snapshot)
        )
        source_space = await KnowledgeDao.aquery_by_id(
            int(payload_snapshot["source_space_id"])
        )
        if (
            source_space is None
            or source_space.state != KnowledgeState.PUBLISHED.value
        ):
            raise ValueError("share source space is no longer published")
        async with get_async_db_session() as session:
            file_repository = KnowledgeFileRepositoryImpl(session)
            service = KnowledgeDocumentDistributionService(
                session=session,
                document_repository=KnowledgeDocumentRepositoryImpl(session),
                version_repository=KnowledgeDocumentVersionRepositoryImpl(
                    session
                ),
                file_repository=file_repository,
                permission_activation_service=(
                    KnowledgeDocumentPermissionActivationService(
                        file_repository=file_repository,
                    )
                ),
            )
            source_entry = await file_repository.find_by_id(
                int(payload_snapshot["source_entry_id"])
            )
            if (
                source_entry is not None
                and source_entry.entry_type != KnowledgeFileEntryType.PUBLISH.value
            ):
                await service.normalize_manager(
                    tenant_id=int(payload_snapshot["tenant_id"]),
                    source_file_id=int(payload_snapshot["source_entry_id"]),
                    expected_document_id=int(payload_snapshot["canonical_document_id"]),
                )
            result = await service.share_approved(
                ShareKnowledgeDocumentCommand(
                    tenant_id=int(payload_snapshot["tenant_id"]),
                    approval_instance_id=int(instance_id),
                    document_id=int(
                        payload_snapshot["canonical_document_id"]
                    ),
                    source_entry_id=int(
                        payload_snapshot["source_entry_id"]
                    ),
                    target_space_id=int(
                        payload_snapshot["target_space_id"]
                    ),
                    allow_download=bool(
                        payload_snapshot.get("allow_download")
                    ),
                    target_file_level_path=target_file_level_path,
                    target_level=target_level,
                )
            )
        try:
            from bisheng.worker.knowledge.document_projection import (
                enqueue_document_projection_entries,
            )

            enqueue_document_projection_entries(
                tenant_id=int(payload_snapshot["tenant_id"]),
                entry_ids=[result.share_entry_id],
            )
        except Exception:
            logger.warning(
                "F059 share projection enqueue failed; Beat will recover "
                "document_id=%s",
                result.document_id,
                exc_info=True,
            )
        logger.info(
            "F059 share applied tenant_id=%s document_id=%s "
            "share_entry_id=%s target_space_id=%s idempotent=%s",
            payload_snapshot["tenant_id"],
            result.document_id,
            result.share_entry_id,
            result.target_space_id,
            result.idempotent,
        )
        return {
            "document_id": result.document_id,
            "file_id": result.share_entry_id,
            "manager_file_id": result.manager_file_id,
            "target_space_id": result.target_space_id,
            "idempotent": result.idempotent,
        }

    async def on_rejected(
        self,
        instance_id: int,
        payload_snapshot: dict,
        reason: str | None,
    ) -> None:
        await _restore_unapproved_distribution_source(payload_snapshot)

    async def on_withdrawn(
        self,
        instance_id: int,
        payload_snapshot: dict,
        reason: str | None,
    ) -> None:
        await _restore_unapproved_distribution_source(payload_snapshot)

    async def on_cancelled(
        self,
        instance_id: int,
        payload_snapshot: dict,
        reason: str | None,
    ) -> None:
        await _restore_unapproved_distribution_source(payload_snapshot)


async def _link_file_as_version(
    *,
    login_user: _RuntimeLoginUser,
    knowledge_file_id: int,
    target_document_id: int,
    file_level_path: str | None = None,
    level: int | None = None,
) -> dict:
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
    from bisheng.knowledge.domain.services.knowledge_version_service import KnowledgeVersionService
    from bisheng.message.api.dependencies import get_message_service

    async with get_async_db_session() as session:
        service = KnowledgeVersionService(
            request=_runtime_request(),
            login_user=login_user,
            doc_repo=KnowledgeDocumentRepositoryImpl(session),
            version_repo=KnowledgeDocumentVersionRepositoryImpl(session),
            knowledge_file_repo=KnowledgeFileRepositoryImpl(session),
        )
        # 审批通过后执行版本关联时，收藏了受影响文件的用户也应收到站内信。
        service.message_service = await get_message_service(session)
        result = await service.link_file_to_document(knowledge_file_id, target_document_id)
        if file_level_path is not None and level is not None:
            target_doc = await service.doc_repo.find_by_id(target_document_id)
            if target_doc is not None:
                target_doc.file_level_path = file_level_path
                target_doc.level = level
                await service.doc_repo.update(target_doc)
        return result.model_dump()


async def _ensure_file_publish_target_document(*, login_user: _RuntimeLoginUser, target_file_id: int) -> int:
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
    from bisheng.knowledge.domain.services.knowledge_version_service import KnowledgeVersionService

    async with get_async_db_session() as session:
        service = KnowledgeVersionService(
            request=_runtime_request(),
            login_user=login_user,
            doc_repo=KnowledgeDocumentRepositoryImpl(session),
            version_repo=KnowledgeDocumentVersionRepositoryImpl(session),
            knowledge_file_repo=KnowledgeFileRepositoryImpl(session),
        )
        return await service.ensure_shougang_publish_document_for_file(target_file_id)
