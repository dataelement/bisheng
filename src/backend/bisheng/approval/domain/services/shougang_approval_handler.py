from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from bisheng.approval.domain.services.approver_resolver import resolve_approvers_from_sources
from bisheng.approval.domain.services.knowledge_space_subscribe_scenario_handler import _resolve_space_roles_via_fga
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileDao,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum, KnowledgeSpaceScopeDao

KNOWLEDGE_SPACE_CREATE_SCENARIO = 'knowledge_space_create_request'
FILE_PUBLISH_SCENARIO = 'knowledge_space_file_publish_request'

_FILE_PUBLISH_TARGET_LEVELS: dict[KnowledgeSpaceLevelEnum, set[KnowledgeSpaceLevelEnum]] = {
    KnowledgeSpaceLevelEnum.PERSONAL: {
        KnowledgeSpaceLevelEnum.PUBLIC,
        KnowledgeSpaceLevelEnum.DEPARTMENT,
        KnowledgeSpaceLevelEnum.TEAM,
    },
    KnowledgeSpaceLevelEnum.TEAM: {
        KnowledgeSpaceLevelEnum.PUBLIC,
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
    return SimpleNamespace(headers={}, client=SimpleNamespace(host='approval-runtime'))


def _enum_value(value):
    return value.value if hasattr(value, 'value') else value


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
    return target_level in _FILE_PUBLISH_TARGET_LEVELS.get(source_level, set())


async def _resolve_approvers(node_config: dict, req) -> list[int]:
    sources = node_config.get('sources') or []
    if sources:
        return await resolve_approvers_from_sources(sources, req)
    approver_ids = node_config.get('approver_user_ids') or node_config.get('user_ids') or []
    return [int(one) for one in approver_ids]


async def _resolve_file_publish_approvers(node_config: dict, req) -> list[int]:
    sources = node_config.get('sources') or []
    if not sources:
        approver_ids = node_config.get('approver_user_ids') or node_config.get('user_ids') or []
        return [int(one) for one in approver_ids]

    seen: set[int] = set()
    result: list[int] = []

    def _add(uid: int) -> None:
        if uid not in seen:
            seen.add(uid)
            result.append(uid)

    space_source_types = {'knowledge_space_owner', 'knowledge_space_manager', 'space_admin'}
    has_space_source = any(source.get('type') in space_source_types for source in sources)
    owner_ids: list[int] = []
    manager_ids: list[int] = []
    if has_space_source:
        target_space_id = (getattr(req, 'payload_snapshot', {}) or {}).get('target_space_id')
        if target_space_id:
            owner_ids, manager_ids = await _resolve_space_roles_via_fga(int(target_space_id))

    for source in sources:
        source_type = source.get('type', '')
        if source_type == 'knowledge_space_owner':
            for uid in owner_ids:
                _add(int(uid))
        elif source_type in ('knowledge_space_manager', 'space_admin'):
            for uid in manager_ids:
                _add(int(uid))
        else:
            for uid in await resolve_approvers_from_sources([source], req):
                _add(int(uid))
    return result


def _approval_instance_id_from_metadata(metadata: Any) -> int | None:
    if isinstance(metadata, dict):
        approval_meta = metadata.get('shougang_approval') or metadata.get('shougang_portal_publish')
        if isinstance(approval_meta, dict) and approval_meta.get('approval_instance_id') is not None:
            return int(approval_meta['approval_instance_id'])
        if metadata.get('approval_instance_id') is not None:
            return int(metadata['approval_instance_id'])
    if isinstance(metadata, list):
        for item in metadata:
            instance_id = _approval_instance_id_from_metadata(item)
            if instance_id is not None:
                return instance_id
    return None


def _metadata_with_approval_instance(metadata: Any, instance_id: int) -> list[dict]:
    items = list(metadata or []) if isinstance(metadata, list) else []
    return [
        *items,
        {'shougang_approval': {'approval_instance_id': int(instance_id)}},
    ]


class KnowledgeSpaceCreateApprovalHandler:
    scenario_code = KNOWLEDGE_SPACE_CREATE_SCENARIO

    async def validate(self, req, login_user) -> None:
        return None

    async def build_title(self, req) -> str:
        return f"新建知识库：{req.payload_snapshot.get('create_params', {}).get('name') or req.business_name}"

    async def build_detail(self, req) -> dict:
        params = req.payload_snapshot.get('create_params') or {}
        return {
            'type': 'knowledge_space_create',
            'name': params.get('name'),
            'space_level': params.get('space_level'),
            'department_id': params.get('department_id'),
            'user_group_id': params.get('user_group_id'),
            'auth_type': params.get('auth_type'),
            'is_released': params.get('is_released'),
            'reason': req.reason,
            'applicant_user_id': req.applicant_user_id,
            'applicant_user_name': req.applicant_user_name,
        }

    async def build_business_link(self, req) -> dict:
        return {'scenario_code': self.scenario_code}

    async def resolve_approvers(self, node_config: dict, req) -> list[int]:
        return await _resolve_approvers(node_config, req)

    async def _find_created_space(self, instance_id: int, applicant_user_id: int):
        spaces = await KnowledgeDao.async_get_spaces_by_user(applicant_user_id)
        for space in spaces:
            if _approval_instance_id_from_metadata(space.metadata_fields) == int(instance_id):
                return space
        return None

    async def _ensure_admin_only_level_applicant_is_admin(self, applicant_user_id: int, params: dict) -> None:
        level = _enum_value(params.get('space_level'))
        if level not in {KnowledgeSpaceLevelEnum.PUBLIC.value, KnowledgeSpaceLevelEnum.DEPARTMENT.value}:
            return
        from bisheng.common.errcode.knowledge_space import (
            SpaceCreateDepartmentDeniedError,
            SpaceCreatePublicDeniedError,
        )
        from bisheng.database.constants import AdminRole
        from bisheng.user.domain.models.user_role import UserRoleDao

        roles = await UserRoleDao.aget_user_roles(int(applicant_user_id))
        if not any(int(getattr(role, 'role_id', 0)) == AdminRole for role in roles):
            if level == KnowledgeSpaceLevelEnum.DEPARTMENT.value:
                raise SpaceCreateDepartmentDeniedError()
            raise SpaceCreatePublicDeniedError()

    async def on_approved(self, instance_id: int, payload_snapshot: dict) -> dict:
        from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

        applicant_user_id = int(payload_snapshot['applicant_user_id'])
        existing_space = await self._find_created_space(instance_id, applicant_user_id)
        if existing_space:
            return {'space_id': int(existing_space.id), 'space_name': existing_space.name, 'idempotent': True}

        params = payload_snapshot.get('create_params') or {}
        await self._ensure_admin_only_level_applicant_is_admin(applicant_user_id, params)
        login_user = _RuntimeLoginUser(
            user_id=applicant_user_id,
            user_name=str(payload_snapshot.get('applicant_user_name') or ''),
            tenant_id=int(payload_snapshot['tenant_id']),
            elevated=True,
        )
        service = KnowledgeSpaceService(request=_runtime_request(), login_user=login_user)
        await service.validate_knowledge_space_create(**params)
        space = await service.create_knowledge_space(**params)
        space.metadata_fields = _metadata_with_approval_instance(space.metadata_fields, instance_id)
        space = await KnowledgeDao.async_update_space(space)
        return {'space_id': int(space.id), 'space_name': space.name}

    async def on_rejected(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        return None

    async def on_withdrawn(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        return None


class KnowledgeSpaceFilePublishApprovalHandler:
    scenario_code = FILE_PUBLISH_SCENARIO

    async def validate(self, req, login_user) -> None:
        return None

    async def build_title(self, req) -> str:
        source_name = req.payload_snapshot.get('source_file_name') or req.business_name
        target_name = req.payload_snapshot.get('target_space_name') or ''
        return f"发布文件：{source_name} → {target_name}".rstrip()

    async def build_detail(self, req) -> dict:
        return {
            'type': 'knowledge_space_file_publish',
            'source_space_id': req.payload_snapshot.get('source_space_id'),
            'source_space_name': req.payload_snapshot.get('source_space_name'),
            'source_file_id': req.payload_snapshot.get('source_file_id'),
            'source_file_name': req.payload_snapshot.get('source_file_name'),
            'target_space_id': req.payload_snapshot.get('target_space_id'),
            'target_space_name': req.payload_snapshot.get('target_space_name'),
            'target_folder_id': req.payload_snapshot.get('target_folder_id'),
            'target_folder_name': req.payload_snapshot.get('target_folder_name'),
            'target_document_id': req.payload_snapshot.get('target_document_id'),
            'target_document_title': req.payload_snapshot.get('target_document_title'),
            'reason': req.reason,
            'applicant_user_id': req.applicant_user_id,
            'applicant_user_name': req.applicant_user_name,
        }

    async def build_business_link(self, req) -> dict:
        return {
            'source_file_id': req.payload_snapshot.get('source_file_id'),
            'target_space_id': req.payload_snapshot.get('target_space_id'),
            'target_folder_id': req.payload_snapshot.get('target_folder_id'),
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
        target_file_level_path: str = '',
    ) -> KnowledgeFile | None:
        from bisheng.worker.knowledge import file_worker

        extra_user_metadata = {
            'shougang_portal_publish': {
                'approval_instance_id': int(instance_id),
                'source_space_id': source_space.id,
                'source_file_id': source_file.id,
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
            if _approval_instance_id_from_metadata(file.user_metadata) == int(instance_id):
                return file
        return None

    async def _space_level(self, space_id: int) -> KnowledgeSpaceLevelEnum:
        scope = await KnowledgeSpaceScopeDao.aget_by_space_id(space_id)
        return scope.level if scope else KnowledgeSpaceLevelEnum.PERSONAL

    async def on_approved(self, instance_id: int, payload_snapshot: dict) -> dict:
        from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

        source_space_id = int(payload_snapshot['source_space_id'])
        source_file_id = int(payload_snapshot['source_file_id'])
        target_space_id = int(payload_snapshot['target_space_id'])
        target_folder_id = payload_snapshot.get('target_folder_id')
        target_folder_id = int(target_folder_id) if target_folder_id else None
        target_document_id = payload_snapshot.get('target_document_id')
        target_file_id = payload_snapshot.get('target_file_id')

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
            version_result = None
            login_user = _RuntimeLoginUser(
                user_id=int(payload_snapshot['applicant_user_id']),
                user_name=str(payload_snapshot.get('applicant_user_name') or ''),
                tenant_id=int(payload_snapshot['tenant_id']),
                elevated=True,
            )
            resolved_target_document_id = await resolve_target_document_id(login_user)
            if resolved_target_document_id:
                version_result = await _link_file_as_version(
                    login_user=login_user,
                    knowledge_file_id=int(existing_file.id),
                    target_document_id=resolved_target_document_id,
                    file_level_path=getattr(existing_file, 'file_level_path', '') or '',
                    level=int(getattr(existing_file, 'level', 0) or 0),
                )
            return {
                'file_id': int(existing_file.id),
                'target_space_id': target_space_id,
                'version': version_result,
                'idempotent': True,
            }

        source_space = await KnowledgeDao.aquery_by_id(source_space_id)
        target_space = await KnowledgeDao.aquery_by_id(target_space_id)
        source_file = await KnowledgeFileDao.query_by_id(source_file_id)
        if not source_space or source_space.type != KnowledgeTypeEnum.SPACE.value:
            raise ValueError('source space not found')
        if not target_space or target_space.type != KnowledgeTypeEnum.SPACE.value:
            raise ValueError('target space not found')
        if not source_file or source_file.knowledge_id != source_space_id:
            raise ValueError('source file not found')
        source_level = await self._space_level(source_space_id)
        target_level = await self._space_level(target_space_id)
        if not _file_publish_pair_allowed(source_level, target_level):
            raise ValueError('source and target space levels are not allowed for publish')
        if source_file.status != KnowledgeFileStatus.SUCCESS.value:
            raise ValueError('source file is not parsed successfully')

        target_parent_type = 'knowledge_space'
        target_parent_id = target_space_id
        copy_target_level = 0
        copy_target_file_level_path = ''
        if target_folder_id is not None:
            target_folder = await KnowledgeFileDao.query_by_id(target_folder_id)
            if (
                not target_folder
                or int(target_folder.knowledge_id) != target_space_id
                or int(target_folder.file_type) != FileType.DIR.value
            ):
                raise ValueError('target folder not found')
            copy_target_level = int(target_folder.level or 0) + 1
            folder_level_path = (target_folder.file_level_path or '').rstrip('/')
            copy_target_file_level_path = (
                f"{folder_level_path}/{target_folder_id}" if folder_level_path else f"/{target_folder_id}"
            )
            target_parent_type = 'folder'
            target_parent_id = target_folder_id

        copied_file = await asyncio.to_thread(
            self._copy_file,
            source_file,
            source_space,
            target_space,
            int(payload_snapshot['applicant_user_id']),
            instance_id,
            copy_target_level,
            copy_target_file_level_path,
        )
        if not copied_file or not copied_file.id:
            raise ValueError('copy file failed')

        login_user = _RuntimeLoginUser(
            user_id=int(payload_snapshot['applicant_user_id']),
            user_name=str(payload_snapshot.get('applicant_user_name') or ''),
            tenant_id=int(payload_snapshot['tenant_id']),
            elevated=True,
        )
        space_service = KnowledgeSpaceService(request=_runtime_request(), login_user=login_user)
        await space_service._initialize_child_resource_permissions(
            'knowledge_file',
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
        return {
            'file_id': int(copied_file.id),
            'target_space_id': target_space_id,
            'version': version_result,
        }

    async def on_rejected(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        return None

    async def on_withdrawn(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        return None


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

    async with get_async_db_session() as session:
        service = KnowledgeVersionService(
            request=_runtime_request(),
            login_user=login_user,
            doc_repo=KnowledgeDocumentRepositoryImpl(session),
            version_repo=KnowledgeDocumentVersionRepositoryImpl(session),
            knowledge_file_repo=KnowledgeFileRepositoryImpl(session),
        )
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
