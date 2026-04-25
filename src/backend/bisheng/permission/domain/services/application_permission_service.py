from __future__ import annotations

import asyncio
import logging
from typing import Iterable

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao as _UserDepartmentDao
from bisheng.database.models.flow import FlowType
from bisheng.permission.domain.services.owner_service import _run_async_safe
from bisheng.permission.api.endpoints.resource_permission import (
    _get_bindings,
    _get_relation_models,
    _normalize_model_dict,
)
from bisheng.permission.domain.application_permission_template import default_permission_ids_for_relation
from bisheng.permission.domain.services.fine_grained_permission_service import FineGrainedPermissionService
from bisheng.permission.domain.services.permission_service import PermissionService as _PermissionService

logger = logging.getLogger(__name__)
PermissionService = _PermissionService
UserDepartmentDao = _UserDepartmentDao

_PERMISSION_LEVEL_TO_RELATION = {
    'owner': 'owner',
    'can_manage': 'manager',
    'can_edit': 'editor',
    'can_read': 'viewer',
}

_FLOW_TYPE_TO_OBJECT_TYPE = {
    FlowType.WORKFLOW.value: 'workflow',
    FlowType.ASSISTANT.value: 'assistant',
}


class ApplicationPermissionService:
    @staticmethod
    def get_effective_permission_ids_sync(
        login_user: UserPayload,
        object_type: str,
        object_id: str,
    ) -> set[str]:
        return _run_async_safe(
            ApplicationPermissionService.get_effective_permission_ids_async(
                login_user,
                object_type,
                object_id,
            )
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
        return {dept.id: dept.path or '' for dept in departments}

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
        object_type: str,
        resource_id: str,
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
            if binding.get('resource_type') != object_type or str(binding.get('resource_id')) != str(resource_id):
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
                if binding.get('resource_type') != object_type or str(binding.get('resource_id')) != str(resource_id):
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
        object_type: str,
        object_id: str,
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
            object_type,
            object_id,
            models=models,
            bindings=bindings,
            binding_department_paths=binding_department_paths,
            user_subject_strings=user_subject_strings,
        )

    @classmethod
    async def get_app_permission_map_async(
        cls,
        login_user: UserPayload,
        rows: list[dict],
        permission_ids: Iterable[str],
    ) -> dict[str, set[str]]:
        permission_id_set = set(permission_ids)
        if not rows or not permission_id_set:
            return {}

        models, bindings, user_subject_strings = await asyncio.gather(
            cls._get_relation_models_map(),
            _get_bindings(),
            cls._get_current_user_subject_strings(login_user),
        )
        binding_department_paths = await cls._get_binding_department_paths(bindings)

        async def _one(row: dict) -> tuple[str, set[str]]:
            object_type = _FLOW_TYPE_TO_OBJECT_TYPE.get(row.get('flow_type'))
            object_id = str(row.get('id'))
            if object_type is None or not object_id:
                return object_id, set()
            perms = await cls.get_effective_permission_ids_async(
                login_user,
                object_type,
                object_id,
                models=models,
                bindings=bindings,
                binding_department_paths=binding_department_paths,
                user_subject_strings=user_subject_strings,
            )
            return object_id, perms & permission_id_set

        pairs = await asyncio.gather(*[_one(row) for row in rows])
        return {row_id: perms for row_id, perms in pairs}

    @classmethod
    def get_app_permission_map_sync(
        cls,
        login_user: UserPayload,
        rows: list[dict],
        permission_ids: Iterable[str],
    ) -> dict[str, set[str]]:
        return _run_async_safe(cls.get_app_permission_map_async(login_user, rows, permission_ids))

    @classmethod
    def filter_object_ids_by_permission_sync(
        cls,
        login_user: UserPayload,
        object_type: str,
        object_ids: list[str | int],
        permission_id: str,
    ) -> list[str]:
        normalized_ids = [str(object_id) for object_id in object_ids]
        if not normalized_ids:
            return []
        permission_map = cls.get_app_permission_map_sync(
            login_user,
            [{'id': object_id, 'flow_type': FlowType.WORKFLOW.value if object_type == 'workflow' else FlowType.ASSISTANT.value} for object_id in normalized_ids],
            [permission_id],
        )
        return [
            object_id
            for object_id in normalized_ids
            if permission_id in permission_map.get(object_id, set())
        ]

    @classmethod
    async def has_any_permission_async(
        cls,
        login_user: UserPayload,
        object_type: str,
        object_id: str,
        permission_ids: Iterable[str],
    ) -> bool:
        effective_permissions = await cls.get_effective_permission_ids_async(
            login_user,
            object_type,
            object_id,
        )
        required_permissions = set(permission_ids)
        allowed = bool(required_permissions & effective_permissions)
        if not allowed:
            logger.warning(
                'application permission denied user=%s object=%s:%s required=%s effective=%s',
                getattr(login_user, 'user_id', None),
                object_type,
                object_id,
                sorted(required_permissions),
                sorted(effective_permissions),
            )
        return allowed

    @classmethod
    def has_any_permission_sync(
        cls,
        login_user: UserPayload,
        object_type: str,
        object_id: str,
        permission_ids: Iterable[str],
    ) -> bool:
        effective_permissions = cls.get_effective_permission_ids_sync(
            login_user,
            object_type,
            object_id,
        )
        required_permissions = set(permission_ids)
        allowed = bool(required_permissions & effective_permissions)
        if not allowed:
            logger.warning(
                'application permission denied(sync) user=%s object=%s:%s required=%s effective=%s',
                getattr(login_user, 'user_id', None),
                object_type,
                object_id,
                sorted(required_permissions),
                sorted(effective_permissions),
            )
        return allowed
