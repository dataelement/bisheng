from __future__ import annotations

import asyncio

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao as _UserDepartmentDao
from bisheng.permission.api.endpoints.resource_permission import (
    _get_bindings,
    _get_relation_models,
    _normalize_model_dict,
)
from bisheng.permission.domain.services.owner_service import _run_async_safe
from bisheng.permission.domain.services.fine_grained_permission_service import FineGrainedPermissionService
from bisheng.permission.domain.services.permission_service import PermissionService as _PermissionService
from bisheng.permission.domain.tool_permission_template import default_permission_ids_for_relation

PermissionService = _PermissionService
UserDepartmentDao = _UserDepartmentDao

_PERMISSION_LEVEL_TO_RELATION = {
    'owner': 'owner',
    'can_manage': 'manager',
    'can_edit': 'editor',
    'can_read': 'viewer',
}


class ToolPermissionService:
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
            if binding.get('resource_type') != 'tool' or str(binding.get('resource_id')) != str(resource_id):
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
                if binding.get('resource_type') != 'tool' or str(binding.get('resource_id')) != str(resource_id):
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
        tool_type_id: str,
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
            'tool',
            tool_type_id,
            models=models,
            bindings=bindings,
            binding_department_paths=binding_department_paths,
            user_subject_strings=user_subject_strings,
        )

    @classmethod
    async def has_any_permission_async(
        cls,
        login_user: UserPayload,
        tool_type_id: str,
        permission_ids: list[str],
    ) -> bool:
        effective_permissions = await cls.get_effective_permission_ids_async(login_user, tool_type_id)
        return bool(set(permission_ids) & effective_permissions)

    @classmethod
    def has_any_permission_sync(
        cls,
        login_user: UserPayload,
        tool_type_id: str,
        permission_ids: list[str],
    ) -> bool:
        return _run_async_safe(cls.has_any_permission_async(login_user, tool_type_id, permission_ids))

    @classmethod
    def filter_tool_ids_by_permission_sync(
        cls,
        login_user: UserPayload,
        tool_type_ids: list[str | int],
        permission_id: str,
    ) -> list[str]:
        normalized_ids = [str(tool_type_id) for tool_type_id in tool_type_ids]
        if not normalized_ids:
            return []

        async def _all() -> list[str]:
            models, bindings, user_subject_strings = await asyncio.gather(
                cls._get_relation_models_map(),
                _get_bindings(),
                cls._get_current_user_subject_strings(login_user),
            )
            binding_department_paths = await cls._get_binding_department_paths(bindings)
            permissions_list = await asyncio.gather(*[
                cls.get_effective_permission_ids_async(
                    login_user,
                    tool_type_id,
                    models=models,
                    bindings=bindings,
                    binding_department_paths=binding_department_paths,
                    user_subject_strings=user_subject_strings,
                )
                for tool_type_id in normalized_ids
            ])
            return [
                tool_type_id
                for tool_type_id, permission_ids in zip(normalized_ids, permissions_list)
                if permission_id in permission_ids
            ]

        return _run_async_safe(_all())

    @classmethod
    async def filter_tool_ids_by_permission_async(
        cls,
        login_user: UserPayload,
        tool_type_ids: list[str | int],
        permission_id: str,
    ) -> list[str]:
        normalized_ids = [str(tool_type_id) for tool_type_id in tool_type_ids]
        if not normalized_ids:
            return []

        models, bindings, user_subject_strings = await asyncio.gather(
            cls._get_relation_models_map(),
            _get_bindings(),
            cls._get_current_user_subject_strings(login_user),
        )
        binding_department_paths = await cls._get_binding_department_paths(bindings)
        permissions_list = await asyncio.gather(*[
            cls.get_effective_permission_ids_async(
                login_user,
                tool_type_id,
                models=models,
                bindings=bindings,
                binding_department_paths=binding_department_paths,
                user_subject_strings=user_subject_strings,
            )
            for tool_type_id in normalized_ids
        ])
        return [
            tool_type_id
            for tool_type_id, permission_ids in zip(normalized_ids, permissions_list)
            if permission_id in permission_ids
        ]
