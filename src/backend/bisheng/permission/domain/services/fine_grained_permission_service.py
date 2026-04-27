from __future__ import annotations

import asyncio
import logging
from typing import Iterable, Optional

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.openfga.exceptions import FGAClientError
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.permission.api.endpoints.resource_permission import (
    _get_bindings,
    _get_relation_models,
    _normalize_model_dict,
)
from bisheng.permission.domain.application_permission_template import (
    default_permission_ids_for_relation as default_application_permissions,
)
from bisheng.permission.domain.knowledge_library_permission_template import (
    default_permission_ids_for_relation as default_knowledge_library_permissions,
)
from bisheng.permission.domain.knowledge_space_permission_template import (
    default_permission_ids_for_relation as default_knowledge_space_permissions,
)
from bisheng.permission.domain.services.permission_service import PermissionService
from bisheng.permission.domain.tool_permission_template import (
    default_permission_ids_for_relation as default_tool_permissions,
)

_PERMISSION_LEVEL_TO_RELATION = {
    'owner': 'owner',
    'can_manage': 'manager',
    'can_edit': 'editor',
    'can_read': 'viewer',
}

logger = logging.getLogger(__name__)


class FineGrainedPermissionService:
    """Permission-id evaluator for relation-model backed resource permissions.

    OpenFGA only knows coarse relations. Relation models add action-level
    permission ids on top, so every permission-id check must resolve:
    FGA tuple -> persisted relation-model binding -> model.permissions.
    """

    @staticmethod
    def default_permission_ids_for_relation(object_type: str, relation: str) -> set[str]:
        if object_type in {'workflow', 'assistant'}:
            return default_application_permissions(relation)
        if object_type == 'tool':
            return default_tool_permissions(relation)
        if object_type == 'knowledge_library':
            return default_knowledge_library_permissions(relation)
        if object_type in {'knowledge_space', 'folder', 'knowledge_file'}:
            return default_knowledge_space_permissions(relation)
        return set()

    @classmethod
    def _permission_ids_for_relation(
        cls,
        object_type: str,
        relation: str,
        model: dict | None = None,
    ) -> set[str]:
        if model is not None:
            permissions = model.get('permissions') or []
            if permissions:
                return set(permissions)
            if model.get('is_system'):
                return cls.default_permission_ids_for_relation(
                    object_type,
                    model.get('relation') or relation,
                )
            return set()
        return cls.default_permission_ids_for_relation(object_type, relation)

    @staticmethod
    def _is_legacy_subscription_viewer_tuple(
        resource_type: str,
        tuple_user: str | None,
        relation: str | None,
        binding: dict | None,
    ) -> bool:
        # Subscription/member rows are business state, not ReBAC grants. Older
        # code mirrored active subscribers into unbound user viewer tuples; keep
        # explicitly bound grants, but ignore those legacy mirrors at runtime.
        return (
            resource_type in {'knowledge_space', 'channel'}
            and relation == 'viewer'
            and bool(tuple_user and tuple_user.startswith('user:'))
            and not (binding and binding.get('model_id'))
        )

    @staticmethod
    async def get_relation_models_map() -> dict[str, dict]:
        raw_models = await _get_relation_models()
        return {m['id']: _normalize_model_dict(m) for m in raw_models}

    @staticmethod
    async def get_current_user_subject_strings(login_user: UserPayload) -> set[str]:
        subject_strings = {f'user:{login_user.user_id}'}

        user_group_ids = await login_user.get_user_group_ids(login_user.user_id)
        subject_strings.update(f'user_group:{group_id}#member' for group_id in user_group_ids)

        try:
            admin_groups = await UserGroupDao.aget_user_admin_group(login_user.user_id)
        except Exception:
            admin_groups = []
        for group in admin_groups or []:
            subject_strings.add(f'user_group:{group.group_id}#admin')
            # OpenFGA user_group#member includes admin; manual tuple matching must
            # mirror that computed userset.
            subject_strings.add(f'user_group:{group.group_id}#member')

        user_departments = await UserDepartmentDao.aget_user_departments(login_user.user_id)
        subject_strings.update(f'department:{item.department_id}#member' for item in user_departments)
        return subject_strings

    @staticmethod
    async def get_binding_department_paths(bindings: list[dict]) -> dict[int, str]:
        department_ids = {
            int(binding['subject_id'])
            for binding in bindings
            if binding.get('subject_type') == 'department' and binding.get('include_children')
        }
        departments = await DepartmentDao.aget_by_ids(list(department_ids))
        return {dept.id: dept.path or '' for dept in departments}

    @staticmethod
    async def get_current_user_department_paths(user_subject_strings: set[str]) -> dict[int, str]:
        department_ids: set[int] = set()
        for subject in user_subject_strings:
            if not subject.startswith('department:'):
                continue
            try:
                department_ids.add(int(subject.split(':', 1)[1].split('#', 1)[0]))
            except (TypeError, ValueError):
                continue
        if not department_ids:
            return {}
        departments = await DepartmentDao.aget_by_ids(list(department_ids))
        return {int(dept.id): dept.path or '' for dept in departments}

    @staticmethod
    def _subject_parts(tuple_user: str) -> tuple[str | None, int | None, str | None]:
        if tuple_user.startswith('user_group:'):
            subject_id = int(tuple_user.split(':', 1)[1].split('#', 1)[0])
            suffix = tuple_user.split('#', 1)[1] if '#' in tuple_user else None
            return 'user_group', subject_id, suffix
        if tuple_user.startswith('department:'):
            subject_id = int(tuple_user.split(':', 1)[1].split('#', 1)[0])
            suffix = tuple_user.split('#', 1)[1] if '#' in tuple_user else None
            return 'department', subject_id, suffix
        if tuple_user.startswith('user:'):
            return 'user', int(tuple_user.split(':', 1)[1]), None
        return None, None, None

    @staticmethod
    def _binding_matches_tuple_subject(binding: dict, tuple_user: str) -> bool:
        subject_type, subject_id, suffix = FineGrainedPermissionService._subject_parts(tuple_user)
        if subject_type is None or subject_id is None:
            return False
        if binding.get('subject_type') != subject_type:
            return False
        if int(binding.get('subject_id')) != subject_id:
            return False
        if subject_type == 'user':
            return suffix is None
        if subject_type == 'user_group':
            return suffix in {'member', 'admin'}
        return suffix == 'member'

    @classmethod
    def _binding_matches_current_user(
        cls,
        binding: dict,
        user_subject_strings: set[str],
        binding_department_paths: dict[int, str],
        user_department_paths: dict[int, str],
    ) -> bool:
        try:
            subject_id = int(binding.get('subject_id'))
        except (TypeError, ValueError):
            return False

        subject_type = binding.get('subject_type')
        if subject_type == 'user':
            return f'user:{subject_id}' in user_subject_strings
        if subject_type == 'user_group':
            return f'user_group:{subject_id}#member' in user_subject_strings
        if subject_type != 'department':
            return False

        if f'department:{subject_id}#member' in user_subject_strings:
            return True
        if not binding.get('include_children'):
            return False

        binding_path = binding_department_paths.get(subject_id)
        if not binding_path:
            return False
        return any(
            bool(user_path) and user_path.startswith(binding_path)
            for user_path in user_department_paths.values()
        )

    @classmethod
    async def _permission_ids_from_bindings(
        cls,
        lineage: list[tuple[str, str | int]],
        models: dict[str, dict],
        bindings: list[dict],
        binding_department_paths: dict[int, str],
        user_subject_strings: set[str],
        *,
        nearest_binding_wins: bool,
    ) -> tuple[set[str], bool, bool]:
        user_department_paths = await cls.get_current_user_department_paths(user_subject_strings)
        effective_permissions: set[str] = set()
        matched_lineage_binding = False
        saw_bound_model = False

        for resource_type, resource_id in lineage:
            level_permissions: set[str] = set()
            level_saw_binding = False
            for binding in bindings:
                if binding.get('resource_type') != resource_type:
                    continue
                if str(binding.get('resource_id')) != str(resource_id):
                    continue
                if not cls._binding_matches_current_user(
                    binding,
                    user_subject_strings,
                    binding_department_paths,
                    user_department_paths,
                ):
                    continue
                model = models.get(binding.get('model_id')) if binding.get('model_id') else None
                if binding.get('model_id'):
                    saw_bound_model = True
                level_saw_binding = True
                level_permissions.update(
                    cls._permission_ids_for_relation(
                        resource_type,
                        binding.get('relation') or '',
                        model,
                    ),
                )
            if nearest_binding_wins and level_saw_binding:
                matched_lineage_binding = True
                effective_permissions.update(level_permissions)
                break
            effective_permissions.update(level_permissions)

        return effective_permissions, matched_lineage_binding, saw_bound_model

    @classmethod
    async def _resolve_binding_for_tuple(
        cls,
        resource_type: str,
        resource_id: str | int,
        tuple_user: str,
        relation: str,
        bindings: list[dict],
        binding_department_paths: dict[int, str],
    ) -> dict | None:
        subject_type, subject_id, _suffix = cls._subject_parts(tuple_user)

        for binding in bindings:
            if binding.get('resource_type') != resource_type:
                continue
            if str(binding.get('resource_id')) != str(resource_id):
                continue
            if binding.get('relation') != relation:
                continue
            if subject_id is not None and not binding.get('include_children'):
                if cls._binding_matches_tuple_subject(binding, tuple_user):
                    return binding

        if subject_type == 'department' and subject_id is not None:
            tuple_department_rows = await DepartmentDao.aget_by_ids([subject_id])
            tuple_department_path = tuple_department_rows[0].path if tuple_department_rows else ''
            for binding in bindings:
                if binding.get('resource_type') != resource_type:
                    continue
                if str(binding.get('resource_id')) != str(resource_id):
                    continue
                if binding.get('relation') != relation:
                    continue
                if binding.get('subject_type') != 'department' or not binding.get('include_children'):
                    continue
                binding_path = binding_department_paths.get(int(binding.get('subject_id')))
                if binding_path and tuple_department_path and tuple_department_path.startswith(binding_path):
                    return binding
        return None

    @staticmethod
    async def build_resource_lineage(
        object_type: str,
        object_id: str | int,
        *,
        space_id: Optional[int] = None,
    ) -> list[tuple[str, str]]:
        if object_type == 'knowledge_space':
            return [('knowledge_space', str(object_id))]

        if object_type in {'folder', 'knowledge_file'}:
            from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileDao

            try:
                file_record = await KnowledgeFileDao.query_by_id(int(object_id))
            except Exception:
                file_record = None
            if file_record is None:
                return [(object_type, str(object_id))]

            actual_type = 'folder' if file_record.file_type == FileType.DIR.value else 'knowledge_file'
            actual_space_id = space_id or file_record.knowledge_id
            ancestor_ids = [part for part in (file_record.file_level_path or '').split('/') if part]
            return (
                [(actual_type, str(file_record.id))]
                + [('folder', str(fid)) for fid in reversed(ancestor_ids)]
                + [('knowledge_space', str(actual_space_id))]
            )

        return [(object_type, str(object_id))]

    @staticmethod
    async def _tuple_resource_types(resource_type: str, resource_id: str) -> list[str]:
        resource_types = [resource_type]
        if resource_type == 'knowledge_library':
            resource_types.extend(
                await PermissionService._legacy_alias_object_types(resource_type, resource_id),
            )
        return list(dict.fromkeys(resource_types))

    @classmethod
    async def get_effective_permission_ids_async(
        cls,
        login_user: UserPayload,
        object_type: str,
        object_id: str | int,
        *,
        models: dict[str, dict] | None = None,
        bindings: list[dict] | None = None,
        binding_department_paths: dict[int, str] | None = None,
        user_subject_strings: set[str] | None = None,
        lineage: list[tuple[str, str | int]] | None = None,
        nearest_binding_wins: bool = False,
        return_match_metadata: bool = False,
    ) -> set[str]:
        if models is None:
            models = await cls.get_relation_models_map()
        if bindings is None:
            bindings = await _get_bindings()
        if user_subject_strings is None:
            user_subject_strings = await cls.get_current_user_subject_strings(login_user)
        if binding_department_paths is None:
            binding_department_paths = await cls.get_binding_department_paths(bindings)
        if lineage is None:
            lineage = await cls.build_resource_lineage(object_type, object_id)

        effective_permissions: set[str] = set()
        matched_lineage_binding = False
        saw_bound_model_tuple = False
        saw_legacy_subscription_viewer_tuple = False
        fga = PermissionService._get_fga()
        if fga is not None:
            try:
                for resource_type, resource_id in lineage:
                    level_permissions: set[str] = set()
                    level_saw_tuple = False
                    for tuple_resource_type in await cls._tuple_resource_types(resource_type, str(resource_id)):
                        tuples = await fga.read_tuples(object=f'{tuple_resource_type}:{resource_id}')
                        binding_resource_type = (
                            resource_type
                            if tuple_resource_type != 'knowledge_space' or resource_type != 'knowledge_library'
                            else 'knowledge_library'
                        )
                        for tuple_data in tuples:
                            tuple_user = tuple_data.get('user')
                            relation = tuple_data.get('relation')
                            if tuple_user not in user_subject_strings:
                                continue
                            binding = await cls._resolve_binding_for_tuple(
                                binding_resource_type,
                                resource_id,
                                tuple_user,
                                relation,
                                bindings,
                                binding_department_paths,
                            )
                            if cls._is_legacy_subscription_viewer_tuple(
                                tuple_resource_type,
                                tuple_user,
                                relation,
                                binding,
                            ):
                                saw_legacy_subscription_viewer_tuple = True
                                continue
                            model = models.get(binding.get('model_id')) if binding and binding.get('model_id') else None
                            if binding and binding.get('model_id'):
                                saw_bound_model_tuple = True
                            level_saw_tuple = True
                            level_permissions.update(
                                cls._permission_ids_for_relation(resource_type, relation, model),
                            )
                    if nearest_binding_wins and level_saw_tuple:
                        matched_lineage_binding = True
                        effective_permissions.update(level_permissions)
                        break
                    effective_permissions.update(level_permissions)
            except FGAClientError as exc:
                logger.error(
                    'OpenFGA failed while reading permission tuples for %s:%s: %s',
                    object_type,
                    object_id,
                    exc,
                )
                binding_permissions, binding_matched, binding_saw_bound_model = await cls._permission_ids_from_bindings(
                    lineage,
                    models,
                    bindings,
                    binding_department_paths,
                    user_subject_strings,
                    nearest_binding_wins=nearest_binding_wins,
                )
                effective_permissions.update(binding_permissions)
                matched_lineage_binding = matched_lineage_binding or binding_matched
                saw_bound_model_tuple = saw_bound_model_tuple or binding_saw_bound_model

        implicit_level = await PermissionService.get_implicit_permission_level(
            user_id=login_user.user_id,
            object_type=object_type,
            object_id=str(object_id),
            login_user=login_user,
        )
        implicit_relation = _PERMISSION_LEVEL_TO_RELATION.get(implicit_level or '')
        effective_permissions.update(
            cls.default_permission_ids_for_relation(object_type, implicit_relation or ''),
        )
        if effective_permissions or saw_bound_model_tuple or saw_legacy_subscription_viewer_tuple:
            if return_match_metadata:
                return effective_permissions, matched_lineage_binding
            return effective_permissions

        level = await PermissionService.get_permission_level(
            user_id=login_user.user_id,
            object_type=object_type,
            object_id=str(object_id),
            login_user=login_user,
        )
        relation = _PERMISSION_LEVEL_TO_RELATION.get(level or '')
        effective_permissions = cls.default_permission_ids_for_relation(object_type, relation or '')
        if return_match_metadata:
            return effective_permissions, matched_lineage_binding
        return effective_permissions

    @classmethod
    async def has_any_permission_async(
        cls,
        login_user: UserPayload,
        object_type: str,
        object_id: str | int,
        permission_ids: Iterable[str],
    ) -> bool:
        required_permissions = set(permission_ids)
        if not required_permissions:
            return False
        effective_permissions = await cls.get_effective_permission_ids_async(
            login_user,
            object_type,
            object_id,
        )
        return bool(required_permissions & effective_permissions)

    @classmethod
    async def filter_object_ids_by_permission_async(
        cls,
        login_user: UserPayload,
        object_type: str,
        object_ids: list[str | int],
        permission_id: str,
    ) -> list[str]:
        normalized_ids = [str(object_id) for object_id in object_ids]
        if not normalized_ids:
            return []

        models, bindings, user_subject_strings = await asyncio.gather(
            cls.get_relation_models_map(),
            _get_bindings(),
            cls.get_current_user_subject_strings(login_user),
        )
        binding_department_paths = await cls.get_binding_department_paths(bindings)
        permissions_list = await asyncio.gather(*[
            cls.get_effective_permission_ids_async(
                login_user,
                object_type,
                object_id,
                models=models,
                bindings=bindings,
                binding_department_paths=binding_department_paths,
                user_subject_strings=user_subject_strings,
            )
            for object_id in normalized_ids
        ])
        return [
            object_id
            for object_id, permission_ids in zip(normalized_ids, permissions_list)
            if permission_id in permission_ids
        ]
