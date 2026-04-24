"""Fine-grained app (workflow / assistant) permissions aligned with the platform
relation-model template (e.g. ``share_app`` requires inclusion in the grant model).

Used by workstation / chat list payloads and flow detail APIs for UI gating.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional, Set, Tuple

from bisheng.database.models.department import DepartmentDao, UserDepartmentDao

logger = logging.getLogger(__name__)

# Mirrors ``RolesAndPermissions.tsx`` RELATION_LEVEL / MODEL_LEVEL for the 应用/工作流 module.
_RELATION_ORDER = {'can_read': 1, 'can_edit': 2, 'can_manage': 3, 'can_delete': 4}
_MODEL_ORDER = {'viewer': 1, 'editor': 2, 'manager': 3, 'owner': 4}
_COMPUTED_TO_MODEL_RELATION = {
    'can_read': 'viewer',
    'can_edit': 'editor',
    'can_manage': 'manager',
    'can_delete': 'owner',
}

# (permission_id, minimum template relation) — same ids as platform TEMPLATE_SECTIONS.
_APP_PERMISSION_DEFINITIONS: List[Tuple[str, str]] = [
    ('view_app', 'can_read'),
    ('use_app', 'can_read'),
    ('edit_app', 'can_edit'),
    ('delete_app', 'can_delete'),
    ('publish_app', 'can_manage'),
    ('unpublish_app', 'can_manage'),
    ('share_app', 'can_manage'),
    ('manage_app_owner', 'can_manage'),
    ('manage_app_manager', 'can_manage'),
    ('manage_app_viewer', 'can_manage'),
]

# get_permission_level() returns owner | can_manage | can_edit | can_read
_PERMISSION_LEVEL_TO_FG_RELATION = {
    'owner': 'owner',
    'can_manage': 'manager',
    'can_edit': 'editor',
    'can_read': 'viewer',
}

SHARE_APP_PERMISSION_ID = 'share_app'


def default_app_permission_ids_for_relation(relation: str) -> Set[str]:
    """Default permission ids for a built-in FGA relation (viewer/editor/manager/owner)."""
    normalized = _COMPUTED_TO_MODEL_RELATION.get(relation or '', relation or '')
    ml = _MODEL_ORDER.get(normalized, 0)
    out: Set[str] = set()
    for pid, req in _APP_PERMISSION_DEFINITIONS:
        if ml >= _RELATION_ORDER.get(req, 99):
            out.add(pid)
    return out


def _permission_ids_for_relation(relation: str, model: Optional[dict]) -> Set[str]:
    if model is not None:
        perms = model.get('permissions') or []
        if perms:
            return set(perms)
        if model.get('is_system'):
            return default_app_permission_ids_for_relation(str(model.get('relation') or ''))
        return set()
    return default_app_permission_ids_for_relation(relation or '')


def _user_matches_binding(binding: dict, tuple_user: str, user_subject_strings: Set[str]) -> bool:
    if tuple_user not in user_subject_strings:
        return False
    st = binding.get('subject_type')
    sid = binding.get('subject_id')
    expected = (
        f'user:{sid}'
        if st == 'user'
        else f'{st}:{sid}#member'
    )
    return tuple_user == expected


async def _binding_department_paths(bindings: List[dict]) -> Dict[int, str]:
    department_ids = {
        int(b['subject_id'])
        for b in bindings
        if b.get('subject_type') == 'department' and b.get('include_children')
    }
    if not department_ids:
        return {}
    departments = await DepartmentDao.aget_by_ids(list(department_ids))
    return {d.id: (d.path or '') for d in departments or []}


async def _resolve_binding_for_tuple(
    resource_type: str,
    resource_id: str,
    tuple_user: str,
    relation: str,
    bindings: List[dict],
    binding_department_paths: Dict[int, str],
    user_subject_strings: Set[str],
) -> Optional[dict]:
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
        if binding.get('resource_type') != resource_type or str(binding.get('resource_id')) != str(resource_id):
            continue
        if binding.get('relation') != relation:
            continue
        if exact_subject_id is not None and not binding.get('include_children'):
            if (
                binding.get('subject_type') == exact_subject_type
                and int(binding.get('subject_id')) == exact_subject_id
                and _user_matches_binding(binding, tuple_user, user_subject_strings)
            ):
                return binding

    if tuple_user.startswith('department:'):
        tuple_department_id = int(tuple_user.split(':', 1)[1].split('#', 1)[0])
        tuple_department_rows = await DepartmentDao.aget_by_ids([tuple_department_id])
        tuple_department_path = tuple_department_rows[0].path if tuple_department_rows else ''
        for binding in bindings:
            if binding.get('resource_type') != resource_type or str(binding.get('resource_id')) != str(resource_id):
                continue
            if binding.get('relation') != relation:
                continue
            if binding.get('subject_type') != 'department' or not binding.get('include_children'):
                continue
            binding_path = binding_department_paths.get(int(binding.get('subject_id')))
            if binding_path and tuple_department_path and tuple_department_path.startswith(binding_path):
                return binding
    return None


async def _collect_user_subject_strings(login_user) -> Set[str]:
    out = {f'user:{login_user.user_id}'}
    group_ids = await login_user.get_user_group_ids(login_user.user_id)
    out.update(f'user_group:{gid}#member' for gid in (group_ids or []))
    uds = await UserDepartmentDao.aget_user_departments(login_user.user_id)
    out.update(f'department:{ud.department_id}#member' for ud in (uds or []))
    return out


async def get_effective_app_permission_ids(
    login_user,
    object_type: str,
    object_id: str,
) -> Set[str]:
    """Effective fine-grained permission ids for the current user on one app resource."""
    from bisheng.permission.domain.services.permission_service import PermissionService

    if login_user.is_admin():
        return {pid for pid, _ in _APP_PERMISSION_DEFINITIONS}

    user_subject_strings = await _collect_user_subject_strings(login_user)
    from bisheng.permission.api.endpoints.resource_permission import (
        _get_bindings,
        _get_relation_models,
        _normalize_model_dict,
    )

    raw_models = await _get_relation_models()
    model_map = {m['id']: _normalize_model_dict(m) for m in raw_models}
    bindings = await _get_bindings()
    binding_department_paths = await _binding_department_paths(bindings)
    effective: Set[str] = set()

    fga = PermissionService._get_fga()
    if fga is None:
        level = await PermissionService.get_permission_level(
            user_id=login_user.user_id,
            object_type=object_type,
            object_id=str(object_id),
            login_user=login_user,
        )
        relation = _PERMISSION_LEVEL_TO_FG_RELATION.get(level or '')
        return _permission_ids_for_relation(relation or '', None)

    try:
        tuples = await fga.read_tuples(object=f'{object_type}:{object_id}')
    except Exception as e:  # noqa: BLE001
        logger.warning('read_tuples failed for %s:%s: %s', object_type, object_id, e)
        tuples = []

    for tuple_data in tuples or []:
        tuple_user = tuple_data.get('user')
        relation = tuple_data.get('relation')
        if not tuple_user or not relation or tuple_user not in user_subject_strings:
            continue
        binding = await _resolve_binding_for_tuple(
            object_type,
            str(object_id),
            tuple_user,
            relation,
            bindings,
            binding_department_paths,
            user_subject_strings,
        )
        model = model_map.get(binding.get('model_id')) if binding and binding.get('model_id') else None
        effective.update(_permission_ids_for_relation(relation, model))

    implicit_level = await PermissionService.get_implicit_permission_level(
        user_id=login_user.user_id,
        object_type=object_type,
        object_id=str(object_id),
        login_user=login_user,
    )
    implicit_relation = _PERMISSION_LEVEL_TO_FG_RELATION.get(implicit_level or '')
    effective.update(_permission_ids_for_relation(implicit_relation or '', None))
    if effective:
        return effective

    level = await PermissionService.get_permission_level(
        user_id=login_user.user_id,
        object_type=object_type,
        object_id=str(object_id),
        login_user=login_user,
    )
    relation = _PERMISSION_LEVEL_TO_FG_RELATION.get(level or '')
    return _permission_ids_for_relation(relation or '', None)


async def user_may_share_app(login_user, object_type: str, object_id: str) -> bool:
    """True if the user's relation model includes ``share_app`` on this resource."""
    perms = await get_effective_app_permission_ids(login_user, object_type, object_id)
    return SHARE_APP_PERMISSION_ID in perms


def object_type_for_flow_type(flow_type: int) -> Optional[str]:
    from bisheng.database.models.flow import FlowType

    if flow_type == FlowType.WORKFLOW.value:
        return 'workflow'
    if flow_type == FlowType.ASSISTANT.value:
        return 'assistant'
    return None


async def batch_user_may_share_app(
    login_user,
    items: List[Tuple[str, str]],
) -> List[bool]:
    """Parallel ``user_may_share_app`` for list enrichment (same login_user)."""
    if not items:
        return []
    if login_user.is_admin():
        return [True] * len(items)
    results = await asyncio.gather(
        *[user_may_share_app(login_user, ot, oid) for ot, oid in items],
    )
    return list(results)
