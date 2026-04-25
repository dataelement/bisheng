import asyncio
import logging

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.database.models.role_access import AccessType
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao as _UserDepartmentDao
from bisheng.permission.api.endpoints.resource_permission import (
    _get_bindings,
    _get_relation_models,
    _normalize_model_dict,
)
from bisheng.permission.domain.knowledge_library_permission_template import default_permission_ids_for_relation
from bisheng.permission.domain.services.fine_grained_permission_service import FineGrainedPermissionService
from bisheng.permission.domain.services.owner_service import _run_async_safe
from bisheng.permission.domain.services.permission_service import PermissionService

UserDepartmentDao = _UserDepartmentDao

logger = logging.getLogger(__name__)


_PERMISSION_SYNC_TIMEOUT_SECONDS = 60

_KNOWLEDGE_ACCESS_RELATION = {
    AccessType.KNOWLEDGE: 'can_read',
    AccessType.KNOWLEDGE_WRITE: 'can_edit',
}

_KNOWLEDGE_ACCESS_PERMISSION_ID = {
    AccessType.KNOWLEDGE: 'view_kb',
}

_PERMISSION_LEVEL_TO_RELATION = {
    'owner': 'owner',
    'can_manage': 'manager',
    'can_edit': 'editor',
    'can_read': 'viewer',
}


class KnowledgePermissionService:
    """Centralized permission checks for knowledge domain services."""

    @classmethod
    async def check_permission_id_async(
        cls,
        login_user: UserPayload,
        knowledge_id: int,
        permission_id: str,
    ) -> bool:
        effective_permission_ids = await cls.get_effective_permission_ids_async(
            login_user=login_user,
            knowledge_id=knowledge_id,
        )
        allowed = permission_id in effective_permission_ids
        if not allowed:
            logger.warning(
                'knowledge permission denied user=%s knowledge_id=%s permission_id=%s effective_permissions=%s',
                getattr(login_user, 'user_id', None),
                knowledge_id,
                permission_id,
                sorted(effective_permission_ids),
            )
        return allowed

    @classmethod
    def check_permission_id_sync(
        cls,
        login_user: UserPayload,
        knowledge_id: int,
        permission_id: str,
    ) -> bool:
        return _run_async_safe(
            cls.check_permission_id_async(
                login_user=login_user,
                knowledge_id=knowledge_id,
                permission_id=permission_id,
            ),
            timeout=_PERMISSION_SYNC_TIMEOUT_SECONDS,
        )

    @staticmethod
    def _permission_ids_for_relation(relation: str, model: dict | None = None) -> set[str]:
        if model is not None:
            permissions = model.get('permissions') or []
            if permissions:
                return set(permissions)
            if model.get('is_system'):
                return default_permission_ids_for_relation(model.get('relation'))
            return set()
        return default_permission_ids_for_relation(relation)

    @staticmethod
    async def _get_relation_models_map() -> dict[str, dict]:
        raw_models = await _get_relation_models()
        return {m['id']: _normalize_model_dict(m) for m in raw_models}

    @staticmethod
    async def _get_current_user_subject_strings(login_user: UserPayload) -> set[str]:
        return await FineGrainedPermissionService.get_current_user_subject_strings(login_user)

    @staticmethod
    async def _get_binding_department_paths(bindings: list[dict]) -> dict[int, str]:
        department_ids = {
            int(binding['subject_id'])
            for binding in bindings
            if binding.get('subject_type') == 'department' and binding.get('include_children')
        }
        departments = await DepartmentDao.aget_by_ids(list(department_ids))
        return {
            dept.id: dept.path or ''
            for dept in departments
        }

    @staticmethod
    def _user_matches_binding(binding: dict, tuple_user: str, user_subject_strings: set[str]) -> bool:
        if tuple_user not in user_subject_strings:
            return False

        expected = (
            f"user:{binding['subject_id']}"
            if binding.get('subject_type') == 'user'
            else f"{binding.get('subject_type')}:{binding['subject_id']}#member"
        )
        return tuple_user == expected

    @classmethod
    async def _resolve_binding_for_tuple(
        cls,
        resource_id: int,
        tuple_user: str,
        relation: str,
        bindings: list[dict],
        binding_department_paths: dict[int, str],
        user_subject_strings: set[str],
    ) -> dict | None:
        exact_subject_type = 'user'
        exact_subject_id = None
        if tuple_user.startswith('user_group:'):
            exact_subject_type = 'user_group'
            exact_subject_id = int(tuple_user.split(':', 1)[1].split('#', 1)[0])
        elif tuple_user.startswith('department:'):
            exact_subject_type = 'department'
            exact_subject_id = int(tuple_user.split(':', 1)[1].split('#', 1)[0])
        elif tuple_user.startswith('user:'):
            exact_subject_id = int(tuple_user.split(':', 1)[1])

        for binding in bindings:
            if binding.get('resource_type') != 'knowledge_library' or str(binding.get('resource_id')) != str(resource_id):
                continue
            if binding.get('relation') != relation:
                continue
            if exact_subject_id is not None and not binding.get('include_children'):
                if (
                    binding.get('subject_type') == exact_subject_type
                    and int(binding.get('subject_id')) == exact_subject_id
                    and cls._user_matches_binding(binding, tuple_user, user_subject_strings)
                ):
                    return binding

        if tuple_user.startswith('department:'):
            tuple_department_id = int(tuple_user.split(':', 1)[1].split('#', 1)[0])
            tuple_department_rows = await DepartmentDao.aget_by_ids([tuple_department_id])
            tuple_department_path = tuple_department_rows[0].path if tuple_department_rows else ''
            for binding in bindings:
                if binding.get('resource_type') != 'knowledge_library' or str(binding.get('resource_id')) != str(resource_id):
                    continue
                if binding.get('relation') != relation:
                    continue
                if binding.get('subject_type') != 'department' or not binding.get('include_children'):
                    continue
                binding_path = binding_department_paths.get(int(binding.get('subject_id')))
                if binding_path and tuple_department_path and tuple_department_path.startswith(binding_path):
                    return binding
        return None

    @classmethod
    async def get_effective_permission_ids_async(
        cls,
        login_user: UserPayload,
        knowledge_id: int,
        *,
        models: dict[str, dict] | None = None,
        bindings: list[dict] | None = None,
        binding_department_paths: dict[int, str] | None = None,
        user_subject_strings: set[str] | None = None,
    ) -> set[str]:
        if models is None:
            models = await cls._get_relation_models_map()
        if bindings is None:
            bindings = await _get_bindings()
        if user_subject_strings is None:
            user_subject_strings = await cls._get_current_user_subject_strings(login_user)
        if binding_department_paths is None:
            binding_department_paths = await cls._get_binding_department_paths(bindings)

        return await FineGrainedPermissionService.get_effective_permission_ids_async(
            login_user,
            'knowledge_library',
            knowledge_id,
            models=models,
            bindings=bindings,
            binding_department_paths=binding_department_paths,
            user_subject_strings=user_subject_strings,
        )

    async def filter_knowledge_ids_by_permission_async(
        self,
        login_user: UserPayload,
        knowledge_ids: list[int],
        permission_id: str,
    ) -> list[int]:
        normalized_ids = [int(knowledge_id) for knowledge_id in knowledge_ids]
        if not normalized_ids:
            return []

        models, bindings, user_subject_strings = await asyncio.gather(
            self._get_relation_models_map(),
            _get_bindings(),
            self._get_current_user_subject_strings(login_user),
        )
        binding_department_paths = await self._get_binding_department_paths(bindings)
        permissions_list = await asyncio.gather(*[
            self.get_effective_permission_ids_async(
                login_user,
                knowledge_id,
                models=models,
                bindings=bindings,
                binding_department_paths=binding_department_paths,
                user_subject_strings=user_subject_strings,
            )
            for knowledge_id in normalized_ids
        ])
        return [
            knowledge_id
            for knowledge_id, permission_ids in zip(normalized_ids, permissions_list)
            if permission_id in permission_ids
        ]

    async def check_access_async(
            self,
            login_user: UserPayload,
            owner_user_id: int,
            knowledge_id: int,
            access_type: AccessType,
    ) -> bool:
        permission_id = _KNOWLEDGE_ACCESS_PERMISSION_ID.get(access_type)
        if permission_id is not None:
            return await self.check_permission_id_async(login_user, knowledge_id, permission_id)

        relation = self._get_relation(access_type)
        if relation is None:
            return await login_user.async_access_check(owner_user_id, str(knowledge_id), access_type)
        return await PermissionService.check(
            user_id=login_user.user_id,
            relation=relation,
            object_type='knowledge_library',
            object_id=str(knowledge_id),
            login_user=login_user,
        )

    @staticmethod
    def _get_relation(access_type: AccessType) -> str | None:
        return _KNOWLEDGE_ACCESS_RELATION.get(access_type)

    def check_access_sync(
            self,
            login_user: UserPayload,
            owner_user_id: int,
            knowledge_id: int,
            access_type: AccessType,
    ) -> bool:
        permission_id = _KNOWLEDGE_ACCESS_PERMISSION_ID.get(access_type)
        if permission_id is not None:
            return self.check_permission_id_sync(login_user, knowledge_id, permission_id)

        relation = self._get_relation(access_type)
        if relation is None:
            return login_user.access_check(owner_user_id, str(knowledge_id), access_type)
        return _run_async_safe(PermissionService.check(
            user_id=login_user.user_id,
            relation=relation,
            object_type='knowledge_library',
            object_id=str(knowledge_id),
            login_user=login_user,
        ), timeout=_PERMISSION_SYNC_TIMEOUT_SECONDS)

    async def ensure_access_async(
            self,
            login_user: UserPayload,
            owner_user_id: int,
            knowledge_id: int,
            access_type: AccessType,
    ) -> None:
        allowed = await self.check_access_async(
            login_user=login_user,
            owner_user_id=owner_user_id,
            knowledge_id=knowledge_id,
            access_type=access_type,
        )
        if not allowed:
            raise UnAuthorizedError()

    def ensure_access_sync(
            self,
            login_user: UserPayload,
            owner_user_id: int,
            knowledge_id: int,
            access_type: AccessType,
    ) -> None:
        if not self.check_access_sync(login_user, owner_user_id, knowledge_id, access_type):
            raise UnAuthorizedError()

    async def ensure_knowledge_write_async(
            self,
            login_user: UserPayload,
            owner_user_id: int,
            knowledge_id: int,
    ) -> None:
        await self.ensure_access_async(login_user, owner_user_id, knowledge_id, AccessType.KNOWLEDGE_WRITE)

    async def ensure_knowledge_read_async(
            self,
            login_user: UserPayload,
            owner_user_id: int,
            knowledge_id: int,
    ) -> None:
        await self.ensure_access_async(login_user, owner_user_id, knowledge_id, AccessType.KNOWLEDGE)

    def ensure_knowledge_write_sync(
            self,
            login_user: UserPayload,
            owner_user_id: int,
            knowledge_id: int,
    ) -> None:
        self.ensure_access_sync(login_user, owner_user_id, knowledge_id, AccessType.KNOWLEDGE_WRITE)

    def ensure_knowledge_read_sync(
            self,
            login_user: UserPayload,
            owner_user_id: int,
            knowledge_id: int,
    ) -> None:
        self.ensure_access_sync(login_user, owner_user_id, knowledge_id, AccessType.KNOWLEDGE)
