"""Resource permission endpoints (T12b).

POST /api/v1/resources/{resource_type}/{resource_id}/authorize — Grant/revoke permissions.
GET  /api/v1/resources/{resource_type}/{resource_id}/permissions — List resource permissions.
"""

import json
import logging
import uuid

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.permission import (
    PermissionDeniedError,
    PermissionInvalidResourceError,
    PermissionRelationModelNameExistsError,
    PermissionTupleWriteError,
)
from bisheng.common.models.config import ConfigDao
from bisheng.common.schemas.api import resp_200
from bisheng.permission.domain.application_permission_template import (
    APPLICATION_PERMISSION_TEMPLATE,
    default_permission_ids_for_relation as default_application_permissions,
)
from bisheng.permission.domain.channel_permission_template import (
    CHANNEL_PERMISSION_TEMPLATE,
    default_permission_ids_for_relation as default_channel_permissions,
)
from bisheng.permission.domain.knowledge_library_permission_template import (
    KNOWLEDGE_LIBRARY_PERMISSION_TEMPLATE,
    default_permission_ids_for_relation as default_knowledge_library_permissions,
)
from bisheng.permission.domain.knowledge_space_permission_template import (
    KNOWLEDGE_SPACE_PERMISSION_TEMPLATE,
    default_permission_ids_for_relation as default_knowledge_space_permissions,
)
from bisheng.permission.domain.schemas.permission_schema import (
    VALID_RESOURCE_TYPES,
    AuthorizeRequest,
    PermissionLevel,
    ResourcePermissionItem,
    RelationModelCreateRequest,
    RelationModelItem,
    RelationModelUpdateRequest,
)
from bisheng.permission.domain.tool_permission_template import (
    TOOL_PERMISSION_TEMPLATE,
    default_permission_ids_for_relation as default_tool_permissions,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Grantable role relations mapped to their required minimum level
_GRANT_RELATIONS = {'owner': 'owner', 'manager': 'can_manage', 'editor': 'can_edit', 'viewer': 'can_read'}
_GRANT_TIER_VALUES = frozenset({'owner', 'manager', 'usage'})
_MANAGE_PERMISSION_BY_RESOURCE_TIER = {
    'workflow': {
        'owner': 'manage_app_owner',
        'manager': 'manage_app_manager',
        'usage': 'manage_app_viewer',
    },
    'assistant': {
        'owner': 'manage_app_owner',
        'manager': 'manage_app_manager',
        'usage': 'manage_app_viewer',
    },
    'tool': {
        'owner': 'manage_tool_owner',
        'manager': 'manage_tool_manager',
        'usage': 'manage_tool_viewer',
    },
    'knowledge_library': {
        'owner': 'manage_kb_owner',
        'manager': 'manage_kb_manager',
        'usage': 'manage_kb_viewer',
    },
    'channel': {
        'owner': 'manage_channel_owner',
        'manager': 'manage_channel_manager',
        'usage': 'manage_channel_user',
    },
}
_MANAGE_PERMISSION_BY_RESOURCE = {
    'knowledge_space': 'manage_space_relation',
    'folder': 'manage_folder_relation',
    'knowledge_file': 'manage_file_relation',
}
_KNOWLEDGE_PERMISSION_RESOURCE_TYPES = {'knowledge_space', 'folder', 'knowledge_file'}
_PERMISSION_LEVEL_TO_RELATION = {
    PermissionLevel.owner.value: 'owner',
    PermissionLevel.can_manage.value: 'manager',
    PermissionLevel.can_edit.value: 'editor',
    PermissionLevel.can_read.value: 'viewer',
}
_RELATION_MODELS_KEY = 'permission_relation_models_v1'
_RELATION_MODEL_BINDINGS_KEY = 'permission_relation_model_bindings_v1'
_PERMISSION_TEMPLATES = (
    KNOWLEDGE_SPACE_PERMISSION_TEMPLATE,
    APPLICATION_PERMISSION_TEMPLATE,
    KNOWLEDGE_LIBRARY_PERMISSION_TEMPLATE,
    TOOL_PERMISSION_TEMPLATE,
    CHANNEL_PERMISSION_TEMPLATE,
)
_RELATION_MODEL_NAME_PREFIX_PAIRS = tuple(
    (template.get('title') or '', item.get('label') or '')
    for template in _PERMISSION_TEMPLATES
    for column in template.get('columns', [])
    for item in column.get('items', [])
)


def _infer_grant_tier_from_relation(relation: str) -> str:
    if relation == 'owner':
        return 'owner'
    if relation == 'manager':
        return 'manager'
    return 'usage'


def _validate_tier_relation(grant_tier: str, relation: str) -> bool:
    if grant_tier == 'owner':
        return relation == 'owner'
    if grant_tier == 'manager':
        return relation == 'manager'
    if grant_tier == 'usage':
        return relation in ('editor', 'viewer')
    return False


def _is_invalid_owner_subject(subject_type: str | None, relation: str | None) -> bool:
    return relation == 'owner' and subject_type != 'user'


def _normalize_relation_model_name(name: str | None) -> str:
    text = (name or '').strip()
    for title, label in _RELATION_MODEL_NAME_PREFIX_PAIRS:
        if title and label and text == f'{title}{label}':
            return label
    return text


def _relation_model_name_exists(models: list[dict], name: str | None, exclude_model_id: str | None = None) -> bool:
    normalized_name = _normalize_relation_model_name(name)
    if not normalized_name:
        return False
    return any(
        m.get('id') != exclude_model_id
        and _normalize_relation_model_name(m.get('name')) == normalized_name
        for m in models
    )


def _normalize_model_dict(m: dict) -> dict:
    out = dict(m)
    out['name'] = _normalize_relation_model_name(out.get('name'))
    gt = out.get('grant_tier')
    if gt not in _GRANT_TIER_VALUES:
        out['grant_tier'] = _infer_grant_tier_from_relation(out.get('relation') or '')
    if not _validate_tier_relation(out['grant_tier'], out.get('relation') or ''):
        out['grant_tier'] = _infer_grant_tier_from_relation(out.get('relation') or '')
    if 'permissions_explicit' not in out:
        permissions = out.get('permissions') or []
        if out.get('is_system'):
            out['permissions_explicit'] = False
        else:
            out['permissions_explicit'] = bool(permissions)
    return out


def _default_relation_models() -> list[dict]:
    return [
        {
            'id': 'owner', 'name': '所有者', 'relation': 'owner',
            'grant_tier': 'owner', 'permissions': [], 'permissions_explicit': False, 'is_system': True,
        },
        {
            'id': 'manager', 'name': '可管理', 'relation': 'manager',
            'grant_tier': 'manager', 'permissions': [], 'permissions_explicit': False, 'is_system': True,
        },
        {
            'id': 'editor', 'name': '可编辑', 'relation': 'editor',
            'grant_tier': 'usage', 'permissions': [], 'permissions_explicit': False, 'is_system': True,
        },
        {
            'id': 'viewer', 'name': '可查看', 'relation': 'viewer',
            'grant_tier': 'usage', 'permissions': [], 'permissions_explicit': False, 'is_system': True,
        },
    ]


async def _get_relation_models() -> list[dict]:
    """只读；若库中无记录则初始化默认四条，禁止每次读取都覆盖已保存的自定义模型。"""
    row = await ConfigDao.aget_config_by_key(_RELATION_MODELS_KEY)
    if not row or not (row.value or '').strip():
        models = _default_relation_models()
        await _save_relation_models(models)
        return models
    try:
        models = json.loads(row.value or '[]')
    except Exception:
        models = _default_relation_models()
        await _save_relation_models(models)
        return models
    if not models:
        models = _default_relation_models()
        await _save_relation_models(models)
        return models
    return models


async def _save_relation_models(models: list[dict]) -> None:
    await ConfigDao.insert_or_update_config(
        _RELATION_MODELS_KEY,
        json.dumps(models, ensure_ascii=False),
    )


async def _get_bindings() -> list[dict]:
    """只读；禁止每次读取都把绑定表写回空数组。"""
    row = await ConfigDao.aget_config_by_key(_RELATION_MODEL_BINDINGS_KEY)
    if not row or not (row.value or '').strip():
        return []
    try:
        bindings = json.loads(row.value or '[]')
    except Exception:
        return []
    normalized = await _migrate_legacy_knowledge_library_bindings(bindings)
    if normalized != bindings:
        await _save_bindings(normalized)
    return normalized


async def _save_bindings(bindings: list[dict]) -> None:
    await ConfigDao.insert_or_update_config(
        _RELATION_MODEL_BINDINGS_KEY,
        json.dumps(bindings, ensure_ascii=False),
    )


async def _migrate_legacy_knowledge_library_bindings(bindings: list[dict]) -> list[dict]:
    legacy_ids = {
        int(binding.get('resource_id'))
        for binding in bindings
        if binding.get('resource_type') == 'knowledge_space'
           and str(binding.get('resource_id', '')).isdigit()
    }
    if not legacy_ids:
        return bindings

    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum

    knowledge_rows = await KnowledgeDao.aget_list_by_ids(sorted(legacy_ids))
    knowledge_type_map = {row.id: row.type for row in knowledge_rows}

    normalized: list[dict] = []
    for binding in bindings:
        migrated = dict(binding)
        resource_type = migrated.get('resource_type')
        resource_id = migrated.get('resource_id')
        if resource_type == 'knowledge_space' and str(resource_id).isdigit():
            knowledge_type = knowledge_type_map.get(int(resource_id))
            if knowledge_type is not None and knowledge_type != KnowledgeTypeEnum.SPACE.value:
                migrated['resource_type'] = 'knowledge_library'
                migrated['key'] = _binding_key_with_scope(
                    'knowledge_library',
                    str(resource_id),
                    migrated.get('subject_type'),
                    int(migrated.get('subject_id')),
                    migrated.get('relation'),
                    migrated.get('include_children'),
                )
        normalized.append(migrated)
    return normalized


def _normalize_binding_include_children(subject_type: str, include_children) -> bool | None:
    if subject_type != 'department':
        return None
    return bool(include_children)


def _space_member_role_for_direct_relations(relations: set[str]):
    if not relations:
        return None

    from bisheng.common.models.space_channel_member import UserRoleEnum

    if relations & {'owner', 'manager'}:
        return UserRoleEnum.ADMIN
    if relations & {'editor', 'viewer'}:
        return UserRoleEnum.MEMBER
    return None


async def _sync_knowledge_space_direct_user_memberships(
    *,
    resource_type: str,
    resource_id: str,
    request: AuthorizeRequest,
    bindings_map: dict,
) -> None:
    """同步直接用户 ReBAC 授权与知识广场加入关系。

    知识广场加入会同时写 `space_channel_member` 和直接 ReBAC 授权。
    因此 ReBAC 授权页对“用户”主体做授权/撤权时，也需要反向维护
    `space_channel_member`，避免权限页已移除但广场仍显示“已加入”。
    部门/用户组授权不展开写成员表，保持 ReBAC 群体授权语义。
    """
    if resource_type != 'knowledge_space' or not str(resource_id).isdigit():
        return

    direct_user_ids = {
        int(item.subject_id)
        for item in [*(request.grants or []), *(request.revokes or [])]
        if item.subject_type == 'user'
    }
    if not direct_user_ids:
        return

    from bisheng.common.models.space_channel_member import (
        BusinessTypeEnum,
        MembershipStatusEnum,
        SpaceChannelMember,
        SpaceChannelMemberDao,
        UserRoleEnum,
    )
    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum

    space_id = int(resource_id)
    space = await KnowledgeDao.aquery_by_id(space_id)
    if not space or space.type != KnowledgeTypeEnum.SPACE.value:
        return

    creator_user_id = int(getattr(space, 'user_id', 0) or 0)
    direct_grant_relations: dict[int, set[str]] = {}
    for grant in request.grants or []:
        if grant.subject_type != 'user':
            continue
        direct_grant_relations.setdefault(int(grant.subject_id), set()).add(grant.relation)

    for user_id in direct_user_ids:
        if user_id == creator_user_id:
            continue

        relations = {
            binding.get('relation')
            for binding in bindings_map.values()
            if binding.get('resource_type') == 'knowledge_space'
            and str(binding.get('resource_id')) == str(space_id)
            and binding.get('subject_type') == 'user'
            and int(binding.get('subject_id') or 0) == user_id
            and binding.get('relation')
        }
        relations.update(direct_grant_relations.get(user_id, set()))
        role = _space_member_role_for_direct_relations(relations)

        if role is None:
            await SpaceChannelMemberDao.delete_space_member(space_id=space_id, user_id=user_id)
            continue

        member = await SpaceChannelMemberDao.async_find_member(space_id, user_id)
        if member is None:
            await SpaceChannelMemberDao.async_insert_member(
                SpaceChannelMember(
                    business_id=str(space_id),
                    business_type=BusinessTypeEnum.SPACE,
                    user_id=user_id,
                    user_role=role,
                    status=MembershipStatusEnum.ACTIVE,
                    membership_source='rebac',
                )
            )
            continue

        if member.user_role == UserRoleEnum.CREATOR:
            continue

        changed = member.user_role != role or member.status != MembershipStatusEnum.ACTIVE
        member.user_role = role
        member.status = MembershipStatusEnum.ACTIVE
        if changed:
            await SpaceChannelMemberDao.update(member)


def _binding_key_with_scope(
    resource_type: str,
    resource_id: str,
    subject_type: str,
    subject_id: int,
    relation: str,
    include_children,
) -> str:
    normalized = _normalize_binding_include_children(subject_type, include_children)
    scope = '-' if normalized is None else ('1' if normalized else '0')
    return f'{resource_type}:{resource_id}:{subject_type}:{subject_id}:{relation}:{scope}'


def _binding_key(resource_type: str, resource_id: str, subject_type: str, subject_id: int, relation: str) -> str:
    return _binding_key_with_scope(
        resource_type, resource_id, subject_type, subject_id, relation, None,
    )


def _legacy_binding_key(
    resource_type: str, resource_id: str, subject_type: str, subject_id: int, relation: str,
) -> str:
    return f'{resource_type}:{resource_id}:{subject_type}:{subject_id}:{relation}'


def _binding_lookup_keys(
    resource_type: str,
    resource_id: str,
    subject_type: str,
    subject_id: int,
    relation: str,
    include_children,
) -> list[str]:
    return [
        _binding_key_with_scope(
            resource_type, resource_id, subject_type, subject_id, relation, include_children,
        ),
        _legacy_binding_key(
            resource_type, resource_id, subject_type, subject_id, relation,
        ),
    ]


def _binding_from_map(
    bindings_map: dict,
    resource_type: str,
    resource_id: str,
    subject_type: str,
    subject_id: int,
    relation: str,
    include_children,
):
    for key in _binding_lookup_keys(
        resource_type, resource_id, subject_type, subject_id, relation, include_children,
    ):
        binding = bindings_map.get(key)
        if binding:
            return binding
    return None


async def _apply_binding_metadata_to_permissions(
    permissions: list[ResourcePermissionItem],
    bindings: list[dict],
    model_map: dict,
) -> list[ResourcePermissionItem]:
    """Overlay persisted UI binding metadata onto raw FGA tuple rows.

    Department grants with include_children=True are written as one tuple per
    subtree department. Knowledge-space resources list only explicit
    department bindings; other resources keep the legacy expanded list while
    copying the original parent binding's relation-model metadata to child
    department rows.
    """
    if not bindings:
        return permissions

    collapse_inherited_department_rows = any(
        binding.get('resource_type') in _KNOWLEDGE_PERMISSION_RESOURCE_TYPES
        for binding in bindings
    )

    item_map = {
        (p.subject_type, int(p.subject_id), p.relation): p
        for p in permissions
    }
    bound_keys = {
        (b.get('subject_type'), int(b.get('subject_id')), b.get('relation'))
        for b in bindings
        if b.get('subject_id') is not None
    }

    for binding in bindings:
        subject_type = binding.get('subject_type')
        if binding.get('subject_id') is None:
            continue
        subject_id = int(binding.get('subject_id'))
        relation = binding.get('relation')
        key = (subject_type, subject_id, relation)
        item = item_map.get(key)
        if item is None:
            item = ResourcePermissionItem(
                subject_type=subject_type,
                subject_id=subject_id,
                subject_name=None,
                relation=relation,
            )
            item_map[key] = item

        binding_include_children = binding.get('include_children')
        binding_model_id = binding.get('model_id')
        binding_model_name = model_map.get(binding_model_id, {}).get('name')
        item.include_children = binding_include_children
        item.model_id = binding_model_id
        item.model_name = binding_model_name

        if subject_type == 'department' and binding_include_children:
            try:
                from bisheng.database.models.department import DepartmentDao

                dept = await DepartmentDao.aget_by_id(subject_id)
                subtree_ids = await DepartmentDao.aget_subtree_ids(dept.path) if dept else [subject_id]
            except Exception as e:
                logger.warning('Failed to expand department permission subtree metadata: %s', e)
                subtree_ids = [subject_id]

            for dept_id in subtree_ids:
                child_key = ('department', int(dept_id), relation)
                if child_key == key or child_key in bound_keys:
                    continue
                if collapse_inherited_department_rows:
                    item_map.pop(child_key, None)
                    continue
                child_item = item_map.get(child_key)
                if child_item is None:
                    continue
                child_item.include_children = False
                child_item.model_id = binding_model_id
                child_item.model_name = binding_model_name

    return list(item_map.values())


def _tuple_signature(item) -> tuple:
    return (
        getattr(item, 'subject_type', None),
        getattr(item, 'subject_id', None),
        getattr(item, 'relation', None),
        _normalize_binding_include_children(
            getattr(item, 'subject_type', None),
            getattr(item, 'include_children', None),
        ),
    )


def _default_permission_ids_for_relation(resource_type: str, relation: str) -> set[str]:
    if resource_type in {'workflow', 'assistant'}:
        return default_application_permissions(relation)
    if resource_type == 'tool':
        return default_tool_permissions(relation)
    if resource_type == 'channel':
        return default_channel_permissions(relation)
    if resource_type == 'knowledge_library':
        return default_knowledge_library_permissions(relation)
    if resource_type in {'knowledge_space', 'folder', 'knowledge_file'}:
        return default_knowledge_space_permissions(relation)
    return set()


def _resource_permission_universe(resource_type: str) -> set[str]:
    # The owner defaults cover the full canonical permission set for each
    # resource type, so they can be used as the scope filter for explicit
    # relation-model permissions persisted in DB.
    return _default_permission_ids_for_relation(resource_type, 'owner')


def _permission_ids_for_model(resource_type: str, relation: str, model: dict | None) -> set[str]:
    if model is None:
        return _default_permission_ids_for_relation(resource_type, relation)
    scope = _resource_permission_universe(resource_type)
    permissions = model.get('permissions') or []
    if model.get('permissions_explicit') is True:
        return set(permissions) & scope
    if model.get('is_system'):
        return _default_permission_ids_for_relation(resource_type, model.get('relation') or relation)
    return set(permissions)


def _model_matches_relation(relation: str, model: dict | None) -> bool:
    return model is None or model.get('relation') == relation


def _can_grant_relation_model(
    *,
    resource_type: str,
    relation: str,
    model: dict | None,
    caller_permission_ids: set[str],
) -> bool:
    if not _model_matches_relation(relation, model):
        return False

    tier_map = _MANAGE_PERMISSION_BY_RESOURCE_TIER.get(resource_type)
    if tier_map:
        grant_tier = (
            model.get('grant_tier')
            if model and model.get('grant_tier') in _GRANT_TIER_VALUES
            else _infer_grant_tier_from_relation(relation)
        )
        required_manage_permissions = {
            permission_id
            for tier, permission_id in tier_map.items()
            if tier == grant_tier
        }

        # Custom or explicitly edited models may themselves carry management
        # permissions. Require the caller to already hold those management
        # capabilities so a "usage" grant cannot smuggle owner-management power.
        if model and (not model.get('is_system') or model.get('permissions_explicit') is True):
            model_permission_ids = _permission_ids_for_model(resource_type, relation, model)
            required_manage_permissions.update(model_permission_ids & set(tier_map.values()))

        return bool(required_manage_permissions) and required_manage_permissions.issubset(caller_permission_ids)

    model_permission_ids = _permission_ids_for_model(resource_type, relation, model)
    return model_permission_ids.issubset(caller_permission_ids)


def _management_permission_ids(resource_type: str) -> set[str]:
    direct = _MANAGE_PERMISSION_BY_RESOURCE.get(resource_type)
    if direct:
        return {direct}
    tier_map = _MANAGE_PERMISSION_BY_RESOURCE_TIER.get(resource_type)
    if not tier_map:
        return set()
    return set(tier_map.values())


async def _knowledge_space_membership_permission_ids(
    *,
    login_user: UserPayload,
    resource_type: str,
    resource_id: str,
) -> set[str]:
    """Fallback for legacy space-member roles when ReBAC metadata drifts."""
    if resource_type != 'knowledge_space' or not str(resource_id).isdigit():
        return set()

    from bisheng.common.models.space_channel_member import SpaceChannelMemberDao, UserRoleEnum

    try:
        role = await SpaceChannelMemberDao.async_get_active_member_role(
            int(resource_id),
            login_user.user_id,
        )
    except Exception as exc:
        logger.debug(
            'Could not resolve space membership fallback for user=%s space=%s: %s',
            login_user.user_id,
            resource_id,
            exc,
        )
        return set()
    if role == UserRoleEnum.CREATOR:
        return default_knowledge_space_permissions('owner')
    if role == UserRoleEnum.ADMIN:
        return default_knowledge_space_permissions('manager')
    return set()


async def _get_caller_grant_permission_ids(
    *,
    login_user: UserPayload,
    resource_type: str,
    resource_id: str,
    management_permission_ids: set[str],
) -> set[str]:
    if not management_permission_ids:
        return set()

    from bisheng.permission.domain.services.fine_grained_permission_service import FineGrainedPermissionService

    caller_permission_ids = await FineGrainedPermissionService.get_effective_permission_ids_async(
        login_user,
        resource_type,
        resource_id,
        nearest_binding_wins=_lineage_binding_can_override(resource_type),
    )

    try:
        from bisheng.permission.domain.services.permission_service import PermissionService

        implicit_level = await PermissionService.get_implicit_permission_level(
            user_id=login_user.user_id,
            object_type=resource_type,
            object_id=str(resource_id),
            login_user=login_user,
        )
    except Exception:
        implicit_level = None

    implicit_relation = _PERMISSION_LEVEL_TO_RELATION.get(implicit_level or '')
    if implicit_relation:
        caller_permission_ids.update(
            _default_permission_ids_for_relation(resource_type, implicit_relation),
        )
    caller_permission_ids.update(
        await _knowledge_space_membership_permission_ids(
            login_user=login_user,
            resource_type=resource_type,
            resource_id=resource_id,
        ),
    )

    return caller_permission_ids


def _lineage_binding_can_override(resource_type: str) -> bool:
    return resource_type in {'folder', 'knowledge_file'}


async def _has_resource_permission_management_access(
    *,
    resource_type: str,
    resource_id: str,
    login_user: UserPayload,
) -> bool:
    from bisheng.permission.domain.services.permission_service import PermissionService

    management_permission_ids = _management_permission_ids(resource_type)
    if management_permission_ids:
        from bisheng.permission.domain.services.fine_grained_permission_service import FineGrainedPermissionService

        effective_permission_ids = await FineGrainedPermissionService.get_effective_permission_ids_async(
            login_user,
            resource_type,
            resource_id,
            nearest_binding_wins=_lineage_binding_can_override(resource_type),
        )
        effective_permission_ids.update(
            await _knowledge_space_membership_permission_ids(
                login_user=login_user,
                resource_type=resource_type,
                resource_id=resource_id,
            ),
        )
        return bool(management_permission_ids & effective_permission_ids)

    return await PermissionService.check(
        user_id=login_user.user_id,
        relation='can_edit',
        object_type=resource_type,
        object_id=resource_id,
        login_user=login_user,
    )


def _attach_default_model_metadata(item: ResourcePermissionItem, model_map: dict) -> None:
    model = model_map.get(item.relation)
    if not model:
        return
    item.model_id = model.get('id') or item.relation
    item.model_name = model.get('name')


def _permission_subject_key(item: ResourcePermissionItem) -> tuple[str, int, str]:
    return item.subject_type, int(item.subject_id), item.relation


async def _list_knowledge_space_grant_users(
    *,
    tenant_id: int,
    keyword: str,
    page: int,
    page_size: int,
) -> list[dict]:
    from sqlmodel import select

    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_async_db_session
    from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
    from bisheng.database.models.tenant import Tenant, UserTenant
    from bisheng.user.domain.models.user import User

    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            stmt = (
                select(User)
                .join(UserTenant, UserTenant.user_id == User.user_id)
                .join(Tenant, Tenant.id == UserTenant.tenant_id)
                .where(
                    UserTenant.tenant_id == tenant_id,
                    UserTenant.status == 'active',
                    Tenant.status == 'active',
                    User.delete == 0,
                )
                .order_by(User.user_id.desc())
            )
            if keyword:
                stmt = stmt.where(User.user_name.like(f'%{keyword}%'))
            if page and page_size:
                stmt = stmt.offset((page - 1) * page_size).limit(page_size)
            result = await session.exec(stmt)
            active_users = list(result.all())

    if not active_users:
        return []

    user_ids = [
        int(user.user_id) for user in active_users
        if getattr(user, 'user_id', None) is not None
    ]
    dept_rows = await UserDepartmentDao.aget_by_user_ids(user_ids)
    primary_rows = [
        row for row in dept_rows
        if int(getattr(row, 'is_primary', 0) or 0) == 1
    ]
    departments = await DepartmentDao.aget_active_by_tenant(tenant_id)
    dept_map = {
        int(dept.id): dept for dept in departments
        if getattr(dept, 'id', None) is not None
    }
    primary_by_user = {
        int(row.user_id): dept_map.get(int(row.department_id))
        for row in primary_rows
        if getattr(row, 'user_id', None) is not None and getattr(row, 'department_id', None) is not None
    }

    def _department_display_path(dept) -> str | None:
        if dept is None:
            return None
        path_ids: list[int] = []
        for part in str(getattr(dept, 'path', '') or '').split('/'):
            part = part.strip()
            if part.isdigit():
                path_ids.append(int(part))
        labels = [
            getattr(dept_map.get(dept_id), 'name', f'#{dept_id}')
            for dept_id in path_ids
        ]
        current_name = getattr(dept, 'name', None)
        if current_name and current_name not in labels:
            labels.append(current_name)
        return '/'.join(labels) if labels else current_name

    return [
        {
            'user_id': int(user.user_id),
            'user_name': user.user_name,
            'external_id': getattr(user, 'external_id', None),
            'primary_department_path': _department_display_path(
                primary_by_user.get(int(user.user_id)),
            ),
        }
        for user in active_users
    ]


async def _list_knowledge_space_grant_departments(*, tenant_id: int) -> list[dict]:
    from sqlalchemy import func
    from sqlmodel import select

    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_async_db_session
    from bisheng.database.models.department import Department, UserDepartment
    from bisheng.database.models.tenant import ROOT_TENANT_ID, Tenant

    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            tenant = (
                await session.exec(
                    select(Tenant).where(
                        Tenant.id == tenant_id,
                        Tenant.status == 'active',
                    )
                )
            ).first()
            if tenant is None:
                return []

            root_dept = None
            if getattr(tenant, 'root_dept_id', None):
                root_dept = (
                    await session.exec(
                        select(Department).where(
                            Department.id == int(tenant.root_dept_id),
                            Department.status == 'active',
                        )
                    )
                ).first()

            if root_dept is not None:
                stmt = select(Department).where(
                    Department.path.like(f'{root_dept.path}%'),
                    Department.status == 'active',
                )
                if tenant_id == ROOT_TENANT_ID:
                    child_roots = (
                        await session.exec(
                            select(Department.path).where(
                                Department.is_tenant_root == 1,
                                Department.mounted_tenant_id.is_not(None),
                                Department.mounted_tenant_id != ROOT_TENANT_ID,
                                Department.status == 'active',
                            )
                        )
                    ).all()
                    for child_path in child_roots:
                        stmt = stmt.where(~Department.path.like(f'{child_path}%'))
            else:
                stmt = select(Department).where(
                    Department.tenant_id == tenant_id,
                    Department.status == 'active',
                )

            result = await session.exec(
                stmt.order_by(Department.sort_order, Department.id)
            )
            departments = list(result.all())
    if not departments:
        return []

    dept_ids = [
        int(dept.id)
        for dept in departments
        if getattr(dept, 'id', None) is not None
    ]
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            count_result = await session.exec(
                select(
                    UserDepartment.department_id,
                    func.count(UserDepartment.id),
                )
                .where(UserDepartment.department_id.in_(dept_ids))
                .group_by(UserDepartment.department_id)
            )
            count_map = {
                int(dept_id): int(count)
                for dept_id, count in count_result.all()
            }

    nodes = {
        int(dept.id): {
            'id': int(dept.id),
            'dept_id': dept.dept_id,
            'name': dept.name,
            'parent_id': int(dept.parent_id) if getattr(dept, 'parent_id', None) is not None else None,
            'path': dept.path,
            'sort_order': int(getattr(dept, 'sort_order', 0) or 0),
            'source': dept.source,
            'status': dept.status,
            'member_count': count_map.get(int(dept.id), 0),
            'children': [],
        }
        for dept in departments
        if getattr(dept, 'id', None) is not None
    }

    roots: list[dict] = []
    for node in nodes.values():
        parent_id = node['parent_id']
        if parent_id and parent_id in nodes:
            nodes[parent_id]['children'].append(node)
        else:
            roots.append(node)

    def _sort_tree(items: list[dict]) -> list[dict]:
        items.sort(key=lambda item: (item['sort_order'], item['name']))
        for item in items:
            item['children'] = _sort_tree(item['children'])
        return items

    return _sort_tree(roots)


async def _list_knowledge_space_grant_user_groups(
    *,
    tenant_id: int,
    keyword: str,
    login_user,
) -> list[dict]:
    from sqlmodel import col, select

    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_async_db_session
    from bisheng.database.models.group import LEGACY_HIDDEN_USER_GROUP_NAMES, Group
    from bisheng.database.models.tenant import Tenant
    from bisheng.database.models.user_group import UserGroupDao
    from bisheng.user_group.domain.services.user_group_service import (
        _can_view_all_groups,
    )

    viewer_group_ids: set[int] = set()
    can_view_all = await _can_view_all_groups(login_user)
    if not can_view_all:
        raw_visible_group_ids = await UserGroupDao.aget_user_visible_group_ids(
            login_user.user_id,
        )
        viewer_group_ids = {
            int(x[0]) if isinstance(x, tuple) else int(x)
            for x in raw_visible_group_ids or []
            if x is not None
        }

    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            stmt = (
                select(Group)
                .join(Tenant, Tenant.id == Group.tenant_id)
                .where(
                    Group.tenant_id == tenant_id,
                    Tenant.status == 'active',
                    col(Group.group_name).notin_(LEGACY_HIDDEN_USER_GROUP_NAMES),
                )
                .order_by(Group.update_time.desc())
                .limit(2000)
            )
            if not can_view_all:
                if viewer_group_ids:
                    stmt = stmt.where(
                        (
                            (Group.visibility == 'public')
                            | (Group.create_user == login_user.user_id)
                            | (Group.id.in_(viewer_group_ids))
                        )
                    )
                else:
                    stmt = stmt.where(
                        (
                            (Group.visibility == 'public')
                            | (Group.create_user == login_user.user_id)
                        )
                    )
            if keyword:
                stmt = stmt.where(Group.group_name.like(f'%{keyword}%'))
            result = await session.exec(stmt)
            groups = list(result.all())
    return [
        {
            'id': int(group.id),
            'group_name': group.group_name,
        }
        for group in groups
        if getattr(group, 'id', None) is not None
    ]


def _filter_department_tree_by_ids(nodes: list[dict], allowed_ids: set[int]) -> list[dict]:
    if not allowed_ids:
        return []
    filtered: list[dict] = []
    for node in nodes:
        children = _filter_department_tree_by_ids(node.get('children') or [], allowed_ids)
        node_id = int(node['id'])
        if node_id in allowed_ids:
            cloned = dict(node)
            cloned['children'] = children
            filtered.append(cloned)
        else:
            filtered.extend(children)
    return filtered


def _collect_department_tree_ids(nodes: list[dict]) -> set[int]:
    ids: set[int] = set()
    stack = list(nodes)
    while stack:
        node = stack.pop()
        if node.get('id') is not None:
            ids.add(int(node['id']))
        stack.extend(node.get('children') or [])
    return ids


def _is_team_knowledge_space_level(space_level) -> bool:
    return getattr(space_level, 'value', space_level) == 'team'


async def _resolve_child_resource_space_id_for_grant_scope(resource_type: str, resource_id: str) -> str | None:
    if resource_type not in {'folder', 'knowledge_file'} or not str(resource_id).isdigit():
        return None
    try:
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao

        file_record = await KnowledgeFileDao.query_by_id(int(resource_id))
    except Exception as e:
        logger.debug('Could not resolve knowledge space for %s:%s grant subjects: %s', resource_type, resource_id, e)
        return None
    if file_record is None or getattr(file_record, 'knowledge_id', None) is None:
        return None
    return str(file_record.knowledge_id)


async def _department_subtree_ids(department_id: int) -> set[int]:
    from bisheng.database.models.department import DepartmentDao

    dept = await DepartmentDao.aget_by_id(int(department_id))
    if dept is None or getattr(dept, 'id', None) is None:
        return set()
    ids = {int(dept.id)}
    if getattr(dept, 'path', None):
        ids.update(int(i) for i in await DepartmentDao.aget_subtree_ids(dept.path))
    return ids


async def _knowledge_space_grant_department_ids(
    *,
    resource_id: str,
    login_user: UserPayload,
) -> set[int]:
    from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpaceDao
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceOwnerTypeEnum
    from bisheng.database.models.department import DepartmentDao, UserDepartmentDao

    ids: set[int] = set()

    user_departments = await UserDepartmentDao.aget_user_departments(login_user.user_id)
    for row in user_departments or []:
        if getattr(row, 'department_id', None) is None:
            continue
        ids.update(await _department_subtree_ids(int(row.department_id)))

    admin_departments = await DepartmentDao.aget_user_admin_departments(login_user.user_id)
    for dept in admin_departments:
        if getattr(dept, 'id', None) is None:
            continue
        ids.update(await _department_subtree_ids(int(dept.id)))

    scope = await _get_knowledge_space_scope(resource_id)
    if scope is not None and scope.owner_type in {
        KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
        KnowledgeSpaceOwnerTypeEnum.TENANT_ROOT_DEPARTMENT,
    }:
        ids.update(await _department_subtree_ids(int(scope.owner_id)))
    elif scope is None and str(resource_id).isdigit():
        binding = await DepartmentKnowledgeSpaceDao.aget_by_space_id(int(resource_id))
        if binding is not None:
            ids.update(await _department_subtree_ids(int(binding.department_id)))
    return ids


async def _knowledge_space_grant_user_group_ids(
    *,
    resource_id: str,
    login_user: UserPayload,
) -> set[int]:
    from bisheng.database.models.group import GroupDao
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceOwnerTypeEnum

    visible_groups, _ = await GroupDao.aget_visible_groups(login_user.user_id, 1, 2000, '')
    ids = {
        int(group.id)
        for group in visible_groups or []
        if getattr(group, 'id', None) is not None
    }

    scope = await _get_knowledge_space_scope(resource_id)
    if (
        scope is not None
        and scope.owner_type == KnowledgeSpaceOwnerTypeEnum.USER_GROUP
        and getattr(scope, 'owner_id', None) is not None
    ):
        ids.add(int(scope.owner_id))

    return ids


async def _can_view_all_grant_subject_departments(login_user: UserPayload) -> bool:
    if login_user.is_admin():
        return True
    from bisheng.department.domain.services.department_service import _is_tenant_admin

    return await _is_tenant_admin(login_user)


async def _can_view_all_grant_subject_user_groups(login_user: UserPayload) -> bool:
    from bisheng.user_group.domain.services.user_group_service import _can_view_all_groups

    return await _can_view_all_groups(login_user)


async def _resolve_grant_subject_tenant_id(
    *,
    resource_type: str,
    resource_id: str,
    login_user: UserPayload,
) -> int | None:
    from bisheng.core.context.tenant import get_current_tenant_id
    from bisheng.database.models.tenant import TenantDao
    from bisheng.permission.domain.services.permission_service import PermissionService

    tenant_id = await PermissionService._resolve_resource_tenant(resource_type, resource_id)
    if tenant_id is None:
        tenant_id = get_current_tenant_id() or getattr(login_user, 'tenant_id', None)
    if tenant_id is None:
        return None

    tenant = await TenantDao.aget_by_id(int(tenant_id))
    if tenant is None or getattr(tenant, 'status', None) != 'active':
        return None
    return int(tenant_id)


async def _get_knowledge_space_level(resource_id: str):
    if not str(resource_id).isdigit():
        return None
    from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpaceDao
    from bisheng.knowledge.domain.models.knowledge_space_scope import (
        KnowledgeSpaceLevelEnum,
        KnowledgeSpaceScopeDao,
    )

    try:
        scope = await KnowledgeSpaceScopeDao.aget_by_space_id(int(resource_id))
        if scope is not None:
            return scope.level
        binding = await DepartmentKnowledgeSpaceDao.aget_by_space_id(int(resource_id))
        if binding is not None:
            return KnowledgeSpaceLevelEnum.DEPARTMENT
    except Exception as e:
        logger.debug('Could not load knowledge space level for %s: %s', resource_id, e)
        return None
    return KnowledgeSpaceLevelEnum.PERSONAL


async def _get_knowledge_space_scope(resource_id: str):
    if not str(resource_id).isdigit():
        return None
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScopeDao

    try:
        return await KnowledgeSpaceScopeDao.aget_by_space_id(int(resource_id))
    except Exception as e:
        logger.debug('Could not load knowledge space scope for %s: %s', resource_id, e)
        return None


def _allowed_subject_types_for_space_level(space_level) -> set[str]:
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    if space_level == KnowledgeSpaceLevelEnum.DEPARTMENT:
        return {'user', 'department'}
    if space_level == KnowledgeSpaceLevelEnum.TEAM:
        return {'user', 'department'}
    return {'user', 'department', 'user_group'}


async def _validate_knowledge_space_authorize_scope(
    *,
    resource_type: str,
    resource_id: str,
    request: AuthorizeRequest,
    login_user: UserPayload,
):
    if resource_type != 'knowledge_space':
        return None

    from bisheng.common.errcode.knowledge_space import (
        SpaceAuthorizeScopeDeniedError,
        SpaceAuthorizeSubjectDeniedError,
    )

    level = await _get_knowledge_space_level(resource_id)
    if level is None:
        return None
    allowed_subject_types = _allowed_subject_types_for_space_level(level)
    items = [*(request.grants or []), *(request.revokes or [])]
    if any(item.subject_type not in allowed_subject_types for item in items):
        return SpaceAuthorizeSubjectDeniedError

    if login_user.is_admin():
        return None

    department_items = [item for item in items if item.subject_type == 'department']
    if department_items and not await _can_view_all_grant_subject_departments(login_user):
        if _is_team_knowledge_space_level(level):
            tenant_id = await _resolve_grant_subject_tenant_id(
                resource_type=resource_type,
                resource_id=resource_id,
                login_user=login_user,
            )
            if tenant_id is None:
                return SpaceAuthorizeScopeDeniedError
            tree = await _list_knowledge_space_grant_departments(tenant_id=tenant_id)
            tenant_department_ids = _collect_department_tree_ids(tree)
            if any(int(item.subject_id) not in tenant_department_ids for item in department_items):
                return SpaceAuthorizeScopeDeniedError
            return None

        allowed_department_ids = await _knowledge_space_grant_department_ids(
            resource_id=resource_id,
            login_user=login_user,
        )
        if any(int(item.subject_id) not in allowed_department_ids for item in department_items):
            return SpaceAuthorizeScopeDeniedError

    group_items = [item for item in items if item.subject_type == 'user_group']
    if group_items and not await _can_view_all_grant_subject_user_groups(login_user):
        allowed_group_ids = await _knowledge_space_grant_user_group_ids(
            resource_id=resource_id,
            login_user=login_user,
        )
        if any(int(item.subject_id) not in allowed_group_ids for item in group_items):
            return SpaceAuthorizeScopeDeniedError

    return None


def _is_self_owner_revoke(revoke, login_user: UserPayload) -> bool:
    return (
        getattr(revoke, 'subject_type', None) == 'user'
        and int(getattr(revoke, 'subject_id', 0) or 0) == int(login_user.user_id)
        and getattr(revoke, 'relation', None) == 'owner'
    )


async def _can_remove_self_owner_relation(
    *,
    resource_type: str,
    resource_id: str,
    revokes: list,
) -> bool:
    """Only allow self owner removal when another owner already exists."""
    from bisheng.permission.domain.services.permission_service import PermissionService

    permissions = await PermissionService.get_resource_permissions(
        object_type=resource_type,
        object_id=resource_id,
    )
    owner_signatures = {
        _tuple_signature(item)
        for item in permissions
        if getattr(item, 'relation', None) == 'owner'
    }
    revoke_signatures = {
        _tuple_signature(item)
        for item in revokes
        if getattr(item, 'relation', None) == 'owner'
    }
    remaining_owner_count = len(owner_signatures - revoke_signatures)
    return remaining_owner_count > 0


async def _add_implicit_permission_entries(
    *,
    resource_type: str,
    resource_id: str,
    permissions: list[ResourcePermissionItem],
    model_map: dict,
    login_user: UserPayload,
) -> list[ResourcePermissionItem]:
    """Show implicit caller access sources in the permission dialog.

    Some department knowledge spaces remain accessible to the current caller
    through implicit permission shortcuts even when no explicit OpenFGA tuple
    exists to list. The authorization checks already honor those paths; this
    keeps the management dialog aligned with the effective permission model
    without synthesizing department viewer rows that look like stored grants.
    """
    out = list(permissions)
    if resource_type != 'knowledge_space' or not str(resource_id).isdigit():
        return out

    try:
        from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpaceDao

        binding = await DepartmentKnowledgeSpaceDao.aget_by_space_id(int(resource_id))
    except Exception as e:
        logger.debug('Could not load department-space binding for %s: %s', resource_id, e)
        return out
    if binding is None:
        return out

    user_has_list_entry = any(
        item.subject_type == 'user' and int(item.subject_id) == int(login_user.user_id)
        for item in out
    )
    if not login_user.is_admin() and not user_has_list_entry:
        from bisheng.permission.domain.services.permission_service import PermissionService

        implicit_level = await PermissionService.get_implicit_permission_level(
            user_id=login_user.user_id,
            object_type=resource_type,
            object_id=resource_id,
            login_user=login_user,
        )
        relation = _PERMISSION_LEVEL_TO_RELATION.get(implicit_level or '')
        if relation:
            user_name = getattr(login_user, 'user_name', None)
            if not user_name:
                try:
                    from bisheng.user.domain.models.user import UserDao

                    user = await UserDao.aget_user(login_user.user_id)
                    user_name = getattr(user, 'user_name', None) if user else None
                except Exception as e:
                    logger.debug('Could not resolve user %s for permission list: %s', login_user.user_id, e)
            item = ResourcePermissionItem(
                subject_type='user',
                subject_id=login_user.user_id,
                subject_name=user_name,
                relation=relation,
            )
            _attach_default_model_metadata(item, model_map)
            out.append(item)

    return out


async def _add_creator_owner_entry(
    *,
    resource_type: str,
    resource_id: str,
    permissions: list[ResourcePermissionItem],
    model_map: dict,
) -> list[ResourcePermissionItem]:
    """Expose the DB creator as owner when the owner tuple is missing.

    Resource creation writes an OpenFGA owner tuple, but older data or a delayed
    tuple write can leave the permission dialog without the resource creator.
    Permission checks already use the creator fallback; the list view should
    show the same effective owner.
    """
    from bisheng.permission.domain.services.permission_service import PermissionService

    creator_id = await PermissionService._get_resource_creator(resource_type, resource_id)
    if creator_id is None:
        return permissions

    creator_id = int(creator_id)
    has_creator_owner = any(
        item.subject_type == 'user'
        and int(item.subject_id) == creator_id
        and item.relation == 'owner'
        for item in permissions
    )
    if has_creator_owner:
        return permissions

    user_name = None
    try:
        from bisheng.user.domain.models.user import UserDao

        user = await UserDao.aget_user(creator_id)
        user_name = getattr(user, 'user_name', None) if user else None
    except Exception as e:
        logger.debug('Could not resolve creator %s for permission list: %s', creator_id, e)

    item = ResourcePermissionItem(
        subject_type='user',
        subject_id=creator_id,
        subject_name=user_name,
        relation='owner',
    )
    _attach_default_model_metadata(item, model_map)
    return [*permissions, item]


@router.post('/resources/{resource_type}/{resource_id}/authorize')
async def authorize_resource(
    resource_type: str,
    resource_id: str,
    request: AuthorizeRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Grant or revoke permissions on a resource.

    调用方在资源上的档位需覆盖本次操作涉及的「关系模型授权级别」
    （所有者级 / 管理级 / 使用级），与 PRD 管理应用所有者/管理者/使用者对齐。
    """
    if resource_type not in VALID_RESOURCE_TYPES:
        return PermissionInvalidResourceError.return_resp()
    if resource_type == 'channel':
        return PermissionDeniedError.return_resp()
    if any(_is_invalid_owner_subject(grant.subject_type, grant.relation) for grant in (request.grants or [])):
        return PermissionDeniedError.return_resp()
    scope_error = await _validate_knowledge_space_authorize_scope(
        resource_type=resource_type,
        resource_id=resource_id,
        request=request,
        login_user=login_user,
    )
    if scope_error is not None:
        return scope_error.return_resp()

    from bisheng.permission.domain.services.permission_service import PermissionService

    if not login_user.is_admin():
        raw_models = await _get_relation_models()
        model_map = {m['id']: _normalize_model_dict(m) for m in raw_models}
        binding_map = {
            b.get('key'): b for b in await _get_bindings()
            if b.get('resource_type') == resource_type and str(b.get('resource_id')) == str(resource_id)
        }
        management_permission_ids = _management_permission_ids(resource_type)
        caller_permission_ids = set()
        if management_permission_ids:
            caller_permission_ids = await _get_caller_grant_permission_ids(
                login_user=login_user,
                resource_type=resource_type,
                resource_id=resource_id,
                management_permission_ids=management_permission_ids,
            )

        if management_permission_ids and not (management_permission_ids & caller_permission_ids):
            return PermissionDeniedError.return_resp()

        for grant in (request.grants or []):
            model = model_map.get(getattr(grant, 'model_id', None)) if getattr(grant, 'model_id', None) else None
            if getattr(grant, 'model_id', None) and model is None:
                return PermissionDeniedError.return_resp()
            if not _can_grant_relation_model(
                resource_type=resource_type,
                relation=grant.relation,
                model=model,
                caller_permission_ids=caller_permission_ids,
            ):
                return PermissionDeniedError.return_resp()

        for revoke in (request.revokes or []):
            binding = _binding_from_map(
                binding_map,
                resource_type,
                str(resource_id),
                revoke.subject_type,
                revoke.subject_id,
                revoke.relation,
                getattr(revoke, 'include_children', None),
            )
            model = model_map.get(binding.get('model_id')) if binding and binding.get('model_id') else None
            if binding and binding.get('model_id') and model is None:
                return PermissionDeniedError.return_resp()
            if not _can_grant_relation_model(
                resource_type=resource_type,
                relation=revoke.relation,
                model=model,
                caller_permission_ids=caller_permission_ids,
            ):
                return PermissionDeniedError.return_resp()

    grant_signatures = {_tuple_signature(g) for g in (request.grants or [])}
    revoke_signatures = {_tuple_signature(r) for r in (request.revokes or [])}
    rebind_only_signatures = grant_signatures & revoke_signatures

    # Same subject/relation changes are model rebinds. Do not delete the tuple,
    # but still issue an idempotent write so stale DB-only bindings are repaired.
    rebind_only_grants = [
        grant for grant in (request.grants or [])
        if _tuple_signature(grant) in rebind_only_signatures
    ]
    tuple_grants = [
                       grant for grant in (request.grants or [])
                       if _tuple_signature(grant) not in rebind_only_signatures
                   ] + rebind_only_grants
    tuple_revokes = [
        revoke for revoke in (request.revokes or [])
        if _tuple_signature(revoke) not in rebind_only_signatures
           and not _is_invalid_owner_subject(revoke.subject_type, revoke.relation)
    ]

    self_owner_revokes = [
        revoke for revoke in tuple_revokes
        if _is_self_owner_revoke(revoke, login_user)
    ]
    if self_owner_revokes:
        if not await _can_remove_self_owner_relation(
            resource_type=resource_type,
            resource_id=resource_id,
            revokes=self_owner_revokes,
        ):
            return PermissionDeniedError.return_resp()

    permission_notify_context = None
    if tuple_grants or tuple_revokes:
        from bisheng.permission.domain.services.resource_permission_notification_service import (
            ResourcePermissionNotificationService,
        )

        permission_notify_context = await ResourcePermissionNotificationService.build_context(
            resource_type=resource_type,
            resource_id=resource_id,
            grants=tuple_grants,
            revokes=tuple_revokes,
        )
        logger.info(
            'resource_authorize start actor=%s resource=%s:%s grants=%d revokes=%d',
            login_user.user_id, resource_type, resource_id, len(tuple_grants), len(tuple_revokes),
        )
        try:
            await PermissionService.authorize(
                object_type=resource_type,
                object_id=resource_id,
                grants=tuple_grants,
                revokes=tuple_revokes,
                enforce_fga_success=True,
            )
        except Exception as e:
            logger.error(
                'resource_authorize failed actor=%s resource=%s:%s grants=%d revokes=%d error=%s',
                login_user.user_id, resource_type, resource_id, len(tuple_grants), len(tuple_revokes), e,
            )
            return PermissionTupleWriteError.return_resp(data={'exception': str(e)})

    # Persist relation-model bindings for UI display and model deletion cascade.
    bindings = await _get_bindings()
    bindings_map = {b.get('key'): b for b in bindings if b.get('key')}
    for revoke in (request.revokes or []):
        include_children = getattr(revoke, 'include_children', None)
        include_children_values = [include_children]
        if (
            revoke.subject_type == 'department'
            and (
            include_children is True
            or _is_invalid_owner_subject(revoke.subject_type, revoke.relation)
        )
        ):
            include_children_values = [True, False]
        for include_children in include_children_values:
            for key in _binding_lookup_keys(
                resource_type,
                str(resource_id),
                revoke.subject_type,
                revoke.subject_id,
                revoke.relation,
                include_children,
            ):
                bindings_map.pop(key, None)
    for grant in (request.grants or []):
        if not getattr(grant, 'model_id', None):
            continue
        normalized_include_children = _normalize_binding_include_children(
            grant.subject_type, getattr(grant, 'include_children', None),
        )
        key = _binding_key_with_scope(
            resource_type,
            str(resource_id),
            grant.subject_type,
            grant.subject_id,
            grant.relation,
            normalized_include_children,
        )
        bindings_map[key] = {
            'key': key,
            'resource_type': resource_type,
            'resource_id': str(resource_id),
            'subject_type': grant.subject_type,
            'subject_id': grant.subject_id,
            'relation': grant.relation,
            'include_children': normalized_include_children,
            'model_id': grant.model_id,
        }
    await _save_bindings(list(bindings_map.values()))
    try:
        await _sync_knowledge_space_direct_user_memberships(
            resource_type=resource_type,
            resource_id=str(resource_id),
            request=request,
            bindings_map=bindings_map,
        )
    except Exception as e:
        logger.error(
            'resource_authorize membership sync failed actor=%s resource=%s:%s error=%s',
            login_user.user_id, resource_type, resource_id, e,
        )
        return PermissionTupleWriteError.return_resp(data={'exception': str(e)})

    if permission_notify_context is not None:
        from bisheng.permission.domain.services.resource_permission_notification_service import (
            ResourcePermissionNotificationService,
        )

        await ResourcePermissionNotificationService.dispatch_after_authorize(
            context=permission_notify_context,
            operator_user_id=login_user.user_id,
            operator_user_name=getattr(login_user, 'user_name', None),
        )
    logger.info(
        'resource_authorize success actor=%s resource=%s:%s grants=%d revokes=%d bindings=%d',
        login_user.user_id, resource_type, resource_id, len(request.grants or []), len(request.revokes or []),
        len(bindings_map),
    )
    return resp_200(None)


@router.get('/resources/{resource_type}/{resource_id}/grant-subjects/users')
async def get_grant_subject_users(
    resource_type: str,
    resource_id: str,
    keyword: str = '',
    page: int = Query(1, ge=1),
    page_size: int = Query(1000, ge=1, le=2000),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    if resource_type not in VALID_RESOURCE_TYPES:
        return PermissionInvalidResourceError.return_resp()
    if not await _has_resource_permission_management_access(
        resource_type=resource_type,
        resource_id=resource_id,
        login_user=login_user,
    ):
        return PermissionDeniedError.return_resp()
    tenant_id = await _resolve_grant_subject_tenant_id(
        resource_type=resource_type,
        resource_id=resource_id,
        login_user=login_user,
    )
    if tenant_id is None:
        return resp_200([])
    return resp_200(await _list_knowledge_space_grant_users(
        tenant_id=tenant_id,
        keyword=keyword,
        page=page,
        page_size=page_size,
    ))


@router.get('/resources/{resource_type}/{resource_id}/grant-subjects/departments')
async def get_grant_subject_departments(
    resource_type: str,
    resource_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    if resource_type not in VALID_RESOURCE_TYPES:
        return PermissionInvalidResourceError.return_resp()
    if not await _has_resource_permission_management_access(
        resource_type=resource_type,
        resource_id=resource_id,
        login_user=login_user,
    ):
        return PermissionDeniedError.return_resp()
    tenant_id = await _resolve_grant_subject_tenant_id(
        resource_type=resource_type,
        resource_id=resource_id,
        login_user=login_user,
    )
    if tenant_id is None:
        return resp_200([])
    scope_space_id = await _resolve_child_resource_space_id_for_grant_scope(resource_type, resource_id)
    if resource_type in {'folder', 'knowledge_file'} and scope_space_id is None:
        return resp_200([])
    grant_scope_space_id = scope_space_id or (resource_id if resource_type == 'knowledge_space' else None)
    scope_space_level = None
    if scope_space_id is not None:
        scope_space_level = await _get_knowledge_space_level(scope_space_id)
        if (
            scope_space_level is not None
            and 'department' not in _allowed_subject_types_for_space_level(scope_space_level)
        ):
            return resp_200([])
    resource_space_level = None
    if resource_type == 'knowledge_space':
        resource_space_level = await _get_knowledge_space_level(resource_id)
        if (
            resource_space_level is not None
            and 'department' not in _allowed_subject_types_for_space_level(resource_space_level)
        ):
            return resp_200([])
    tree = await _list_knowledge_space_grant_departments(tenant_id=tenant_id)
    if (
        _is_team_knowledge_space_level(scope_space_level)
        or _is_team_knowledge_space_level(resource_space_level)
    ):
        return resp_200(tree)
    if grant_scope_space_id is not None and not await _can_view_all_grant_subject_departments(login_user):
        allowed_ids = await _knowledge_space_grant_department_ids(
            resource_id=grant_scope_space_id,
            login_user=login_user,
        )
        return resp_200(_filter_department_tree_by_ids(tree, allowed_ids))
    return resp_200(tree)


@router.get('/resources/{resource_type}/{resource_id}/grant-subjects/user-groups')
async def get_grant_subject_user_groups(
    resource_type: str,
    resource_id: str,
    keyword: str = '',
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    if resource_type not in VALID_RESOURCE_TYPES:
        return PermissionInvalidResourceError.return_resp()
    if not await _has_resource_permission_management_access(
        resource_type=resource_type,
        resource_id=resource_id,
        login_user=login_user,
    ):
        return PermissionDeniedError.return_resp()
    tenant_id = await _resolve_grant_subject_tenant_id(
        resource_type=resource_type,
        resource_id=resource_id,
        login_user=login_user,
    )
    if tenant_id is None:
        return resp_200([])
    scope_space_id = await _resolve_child_resource_space_id_for_grant_scope(resource_type, resource_id)
    if resource_type in {'folder', 'knowledge_file'} and scope_space_id is None:
        return resp_200([])
    grant_scope_space_id = scope_space_id or (resource_id if resource_type == 'knowledge_space' else None)
    scope_space_level = None
    if scope_space_id is not None:
        scope_space_level = await _get_knowledge_space_level(scope_space_id)
        if (
            scope_space_level is not None
            and 'user_group' not in _allowed_subject_types_for_space_level(scope_space_level)
        ):
            return resp_200([])
    if resource_type == 'knowledge_space':
        level = await _get_knowledge_space_level(resource_id)
        if level is not None and 'user_group' not in _allowed_subject_types_for_space_level(level):
            return resp_200([])
    groups = await _list_knowledge_space_grant_user_groups(
        tenant_id=tenant_id,
        keyword=keyword,
        login_user=login_user,
    )
    if grant_scope_space_id is not None and not await _can_view_all_grant_subject_user_groups(login_user):
        allowed_ids = await _knowledge_space_grant_user_group_ids(
            resource_id=grant_scope_space_id,
            login_user=login_user,
        )
        return resp_200([
            group for group in groups
            if int(group['id']) in allowed_ids
        ])
    return resp_200(groups)


@router.get('/knowledge-spaces/{space_id}/grant-subjects/departments')
async def get_knowledge_space_grant_subject_departments(
    space_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    if not await _has_resource_permission_management_access(
        resource_type='knowledge_space',
        resource_id=space_id,
        login_user=login_user,
    ):
        return PermissionDeniedError.return_resp()
    tenant_id = await _resolve_grant_subject_tenant_id(
        resource_type='knowledge_space',
        resource_id=space_id,
        login_user=login_user,
    )
    if tenant_id is None:
        return resp_200([])

    level = await _get_knowledge_space_level(space_id)
    if level is not None and 'department' not in _allowed_subject_types_for_space_level(level):
        return resp_200([])

    tree = await _list_knowledge_space_grant_departments(tenant_id=tenant_id)
    if _is_team_knowledge_space_level(level):
        return resp_200(tree)
    if await _can_view_all_grant_subject_departments(login_user):
        return resp_200(tree)

    allowed_ids = await _knowledge_space_grant_department_ids(
        resource_id=space_id,
        login_user=login_user,
    )
    return resp_200(_filter_department_tree_by_ids(tree, allowed_ids))


@router.get('/knowledge-spaces/{space_id}/grant-subjects/user-groups')
async def get_knowledge_space_grant_subject_user_groups(
    space_id: str,
    keyword: str = '',
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    if not await _has_resource_permission_management_access(
        resource_type='knowledge_space',
        resource_id=space_id,
        login_user=login_user,
    ):
        return PermissionDeniedError.return_resp()
    tenant_id = await _resolve_grant_subject_tenant_id(
        resource_type='knowledge_space',
        resource_id=space_id,
        login_user=login_user,
    )
    if tenant_id is None:
        return resp_200([])

    level = await _get_knowledge_space_level(space_id)
    if level is not None and 'user_group' not in _allowed_subject_types_for_space_level(level):
        return resp_200([])

    groups = await _list_knowledge_space_grant_user_groups(
        tenant_id=tenant_id,
        keyword=keyword,
        login_user=login_user,
    )
    if await _can_view_all_grant_subject_user_groups(login_user):
        return resp_200(groups)

    allowed_ids = await _knowledge_space_grant_user_group_ids(
        resource_id=space_id,
        login_user=login_user,
    )
    return resp_200([
        group for group in groups
        if int(group['id']) in allowed_ids
    ])


@router.get('/resources/{resource_type}/{resource_id}/permissions')
async def get_resource_permissions(
    resource_type: str,
    resource_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """List all permission entries for a resource.

    Caller must have at least can_edit on the resource (与使用级授权一致)。
    """
    if resource_type not in VALID_RESOURCE_TYPES:
        return PermissionInvalidResourceError.return_resp()

    from bisheng.permission.domain.services.permission_service import PermissionService

    allowed = await _has_resource_permission_management_access(
        resource_type=resource_type,
        resource_id=resource_id,
        login_user=login_user,
    )
    if not allowed:
        return PermissionDeniedError.return_resp()

    permissions = await PermissionService.get_resource_permissions(
        object_type=resource_type,
        object_id=resource_id,
    )
    models = await _get_relation_models()
    model_map = {m['id']: _normalize_model_dict(m) for m in models}
    binding_map = {
        b.get('key'): b for b in await _get_bindings()
        if b.get('resource_type') == resource_type and str(b.get('resource_id')) == str(resource_id)
    }
    bindings = list(binding_map.values())
    visible_permissions = []
    for p in permissions:
        matched = _binding_from_map(
            binding_map,
            resource_type,
            str(resource_id),
            p.subject_type,
            p.subject_id,
            p.relation,
            getattr(p, 'include_children', None),
        )
        if matched:
            p.model_id = matched.get('model_id')
            p.model_name = model_map.get(p.model_id, {}).get('name')
            p.include_children = matched.get('include_children')

        visible_permissions.append(p)
    permissions = visible_permissions
    permissions = await _apply_binding_metadata_to_permissions(permissions, bindings, model_map)
    permissions = await _add_creator_owner_entry(
        resource_type=resource_type,
        resource_id=resource_id,
        permissions=permissions,
        model_map=model_map,
    )
    permissions = await _add_implicit_permission_entries(
        resource_type=resource_type,
        resource_id=resource_id,
        permissions=permissions,
        model_map=model_map,
        login_user=login_user,
    )
    return resp_200(permissions)


@router.get('/relation-models')
async def get_relation_models(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    models = [RelationModelItem(**_normalize_model_dict(m)) for m in await _get_relation_models()]
    return resp_200(models)


@router.get('/relation-models/grantable')
async def get_grantable_relation_models(
    object_type: str,
    object_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """返回当前用户在指定资源上「有权用于授权」的关系模型子集。"""
    if object_type not in VALID_RESOURCE_TYPES:
        return PermissionInvalidResourceError.return_resp()

    raw = [_normalize_model_dict(m) for m in await _get_relation_models()]
    if login_user.is_admin():
        return resp_200([RelationModelItem(**m) for m in raw])

    management_permission_ids = _management_permission_ids(object_type)
    caller_permission_ids = set()
    if management_permission_ids:
        caller_permission_ids = await _get_caller_grant_permission_ids(
            login_user=login_user,
            resource_type=object_type,
            resource_id=object_id,
            management_permission_ids=management_permission_ids,
        )
    if management_permission_ids and not (management_permission_ids & caller_permission_ids):
        return resp_200([])

    out = []
    for m in raw:
        if _can_grant_relation_model(
            resource_type=object_type,
            relation=m.get('relation') or '',
            model=m,
            caller_permission_ids=caller_permission_ids,
        ):
            out.append(RelationModelItem(**m))
    return resp_200(out)


@router.post('/relation-models')
async def create_relation_model(
    request: RelationModelCreateRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    if not login_user.is_admin():
        return PermissionDeniedError.return_resp()
    if request.relation not in _GRANT_RELATIONS:
        return PermissionDeniedError.return_resp()
    models = await _get_relation_models()
    if _relation_model_name_exists(models, request.name):
        return PermissionRelationModelNameExistsError.return_resp()
    model_id = f'custom_{uuid.uuid4().hex[:8]}'
    models.append({
        'id': model_id,
        'name': _normalize_relation_model_name(request.name),
        'relation': request.relation,
        'grant_tier': _infer_grant_tier_from_relation(request.relation),
        'permissions': request.permissions or [],
        'permissions_explicit': True,
        'is_system': False,
    })
    await _save_relation_models(models)
    return resp_200({'id': model_id})


@router.put('/relation-models/{model_id}')
async def update_relation_model(
    model_id: str,
    request: RelationModelUpdateRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    if not login_user.is_admin():
        return PermissionDeniedError.return_resp()
    models = await _get_relation_models()
    if request.name is not None and _relation_model_name_exists(models, request.name, exclude_model_id=model_id):
        return PermissionRelationModelNameExistsError.return_resp()
    updated = False
    for m in models:
        if m.get('id') != model_id:
            continue
        if request.name is not None:
            m['name'] = _normalize_relation_model_name(request.name)
        if request.permissions is not None:
            m['permissions'] = request.permissions
            m['permissions_explicit'] = True
        updated = True
        break
    if not updated:
        return PermissionInvalidResourceError.return_resp()
    await _save_relation_models(models)
    return resp_200(None)


@router.delete('/relation-models/{model_id}')
async def delete_relation_model(
    model_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    if not login_user.is_admin():
        return PermissionDeniedError.return_resp()
    models = await _get_relation_models()
    target = next((m for m in models if m.get('id') == model_id), None)
    if target is None:
        return PermissionInvalidResourceError.return_resp()
    if target.get('is_system'):
        return PermissionDeniedError.return_resp()

    # Remove model and revoke all tuples bound to this model.
    remain_models = [m for m in models if m.get('id') != model_id]
    bindings = await _get_bindings()
    to_remove = [b for b in bindings if b.get('model_id') == model_id]

    from bisheng.permission.domain.schemas.permission_schema import AuthorizeRevokeItem
    from bisheng.permission.domain.services.resource_permission_notification_service import (
        ResourcePermissionNotificationService,
    )
    from bisheng.permission.domain.services.permission_service import PermissionService
    notify_contexts = []
    try:
        for b in to_remove:
            if _is_invalid_owner_subject(b.get('subject_type'), b.get('relation')):
                logger.warning(
                    'delete_relation_model skip impossible owner revoke model=%s subject=%s:%s resource=%s:%s',
                    model_id, b.get('subject_type'), b.get('subject_id'),
                    b.get('resource_type'), b.get('resource_id'),
                )
                continue
            revoke_item = AuthorizeRevokeItem(
                subject_type=b.get('subject_type'),
                subject_id=int(b.get('subject_id')),
                relation=b.get('relation'),
                include_children=bool(b.get('include_children')),
            )
            notify_context = await ResourcePermissionNotificationService.build_context(
                resource_type=b.get('resource_type'),
                resource_id=str(b.get('resource_id')),
                grants=[],
                revokes=[revoke_item],
            )
            if notify_context is not None:
                notify_contexts.append(notify_context)
            await PermissionService.authorize(
                object_type=b.get('resource_type'),
                object_id=str(b.get('resource_id')),
                grants=[],
                revokes=[revoke_item],
                enforce_fga_success=True,
            )
    except Exception as e:
        logger.error('delete_relation_model failed to revoke model=%s bindings=%d error=%s', model_id, len(to_remove),
                     e)
        return PermissionTupleWriteError.return_resp(data={'exception': str(e)})

    remain_bindings = [b for b in bindings if b.get('model_id') != model_id]
    await _save_relation_models(remain_models)
    await _save_bindings(remain_bindings)
    for notify_context in notify_contexts:
        await ResourcePermissionNotificationService.dispatch_after_authorize(
            context=notify_context,
            operator_user_id=login_user.user_id,
            operator_user_name=getattr(login_user, 'user_name', None),
        )
    return resp_200(None)


@router.get('/rebac-schema')
async def rebac_schema_summary(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """PRD §3.2.3 资源权限模板：返回当前内置 OpenFGA 模型类型与关系名（仅超管）。"""
    if not login_user.is_admin():
        return PermissionDeniedError.return_resp()

    from bisheng.core.openfga.authorization_model import MODEL_VERSION, get_authorization_model

    model = get_authorization_model()
    types_out = []
    for td in model.get('type_definitions', []):
        tname = td.get('type')
        rels = sorted(list((td.get('relations') or {}).keys()))
        types_out.append({'type': tname, 'relations': rels})
    return resp_200(
        {'schema_version': model.get('schema_version'), 'model_version': MODEL_VERSION, 'types': types_out},
    )


@router.get('/permission-templates/knowledge-space')
async def get_knowledge_space_permission_template(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Return the canonical backend template for knowledge-space permissions.

    Frontend relation-model editors should consume this endpoint instead of
    hardcoding their own copy so runtime and UI stay aligned.
    """
    if not login_user.is_admin():
        return PermissionDeniedError.return_resp()
    return resp_200(KNOWLEDGE_SPACE_PERMISSION_TEMPLATE)


@router.get('/permission-templates/application')
async def get_application_permission_template(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Return the canonical backend template for application permissions."""
    if not login_user.is_admin():
        return PermissionDeniedError.return_resp()
    return resp_200(APPLICATION_PERMISSION_TEMPLATE)


@router.get('/permission-templates/knowledge-library')
async def get_knowledge_library_permission_template(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Return the canonical backend template for knowledge-library permissions."""
    if not login_user.is_admin():
        return PermissionDeniedError.return_resp()
    return resp_200(KNOWLEDGE_LIBRARY_PERMISSION_TEMPLATE)


@router.get('/permission-templates/tool')
async def get_tool_permission_template(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Return the canonical backend template for tool permissions."""
    if not login_user.is_admin():
        return PermissionDeniedError.return_resp()
    return resp_200(TOOL_PERMISSION_TEMPLATE)


@router.get('/permission-templates/channel')
async def get_channel_permission_template(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Return the canonical backend template for channel permissions."""
    if not login_user.is_admin():
        return PermissionDeniedError.return_resp()
    return resp_200(CHANNEL_PERMISSION_TEMPLATE)
