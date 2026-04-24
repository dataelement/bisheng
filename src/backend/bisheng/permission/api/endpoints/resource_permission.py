"""Resource permission endpoints (T12b).

POST /api/v1/resources/{resource_type}/{resource_id}/authorize — Grant/revoke permissions.
GET  /api/v1/resources/{resource_type}/{resource_id}/permissions — List resource permissions.
"""

import json
import logging
import uuid

from fastapi import APIRouter, Depends

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.permission.domain.application_permission_template import APPLICATION_PERMISSION_TEMPLATE
from bisheng.permission.domain.knowledge_library_permission_template import KNOWLEDGE_LIBRARY_PERMISSION_TEMPLATE
from bisheng.permission.domain.knowledge_space_permission_template import KNOWLEDGE_SPACE_PERMISSION_TEMPLATE
from bisheng.permission.domain.tool_permission_template import TOOL_PERMISSION_TEMPLATE
from bisheng.permission.domain.schemas.permission_schema import (
    VALID_RESOURCE_TYPES,
    AuthorizeRequest,
    PermissionLevel,
    ResourcePermissionItem,
    RelationModelCreateRequest,
    RelationModelItem,
    RelationModelUpdateRequest,
)
from bisheng.common.errcode.permission import (
    PermissionDeniedError,
    PermissionInvalidResourceError,
    PermissionTupleWriteError,
)
from bisheng.common.models.config import ConfigDao

router = APIRouter()
logger = logging.getLogger(__name__)

# Privilege hierarchy: lower index = higher privilege
_LEVEL_ORDER = [level.value for level in PermissionLevel]  # owner, can_manage, can_edit, can_read
# Grantable role relations mapped to their required minimum level
_GRANT_RELATIONS = {'owner': 'owner', 'manager': 'can_manage', 'editor': 'can_edit', 'viewer': 'can_read'}
_GRANT_TIER_VALUES = frozenset({'owner', 'manager', 'usage'})
# 该关系模型可被「资源上最高权限档位 <= 此下标」的授权人使用（与 _LEVEL_ORDER 对齐）
_TIER_MAX_CALLER_INDEX = {'owner': 0, 'manager': 1, 'usage': 2}
_RELATION_MAX_CALLER_INDEX = {'owner': 0, 'manager': 1, 'editor': 2, 'viewer': 2}
# 无绑定信息的撤回：保持历史行为，需可管理及以上
_LEGACY_REVOKE_MAX_CALLER_INDEX = 1
_RELATION_MODELS_KEY = 'permission_relation_models_v1'
_RELATION_MODEL_BINDINGS_KEY = 'permission_relation_model_bindings_v1'


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


def _normalize_model_dict(m: dict) -> dict:
    out = dict(m)
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
    subtree department. The permission list should show the original parent
    grant, not a flat list of generated child department tuples.
    """
    if not bindings:
        return permissions

    item_map = {
        (p.subject_type, int(p.subject_id), p.relation): p
        for p in permissions
    }
    bound_keys = {
        (b.get('subject_type'), int(b.get('subject_id')), b.get('relation'))
        for b in bindings
        if b.get('subject_id') is not None
    }
    generated_department_keys: set[tuple] = set()

    for binding in bindings:
        subject_type = binding.get('subject_type')
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

        item.include_children = binding.get('include_children')
        item.model_id = binding.get('model_id')
        item.model_name = model_map.get(item.model_id, {}).get('name')

        if subject_type == 'department' and binding.get('include_children'):
            try:
                from bisheng.database.models.department import DepartmentDao

                dept = await DepartmentDao.aget_by_id(subject_id)
                subtree_ids = await DepartmentDao.aget_subtree_ids(dept.path) if dept else [subject_id]
            except Exception as e:
                logger.warning('Failed to collapse department permission subtree: %s', e)
                subtree_ids = [subject_id]

            for dept_id in subtree_ids:
                child_key = ('department', int(dept_id), relation)
                if child_key != key and child_key not in bound_keys:
                    generated_department_keys.add(child_key)

    return [
        item
        for key, item in item_map.items()
        if key not in generated_department_keys
    ]


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


def _caller_satisfies_ceiling(caller_level: str | None, max_caller_index: int) -> bool:
    """True if caller's FGA 档位下标 <= max_caller_index（下标越小权限越高）。"""
    if caller_level is None or caller_level not in _LEVEL_ORDER:
        return False
    return _LEVEL_ORDER.index(caller_level) <= max_caller_index


def _grant_ceiling_index(grant, model_map: dict):
    """Return max caller index allowed for this grant; None if invalid."""
    mid = getattr(grant, 'model_id', None)
    if mid:
        if mid not in model_map:
            return None
        m = model_map[mid]
        if m.get('relation') != grant.relation:
            return None
        return _TIER_MAX_CALLER_INDEX.get(m.get('grant_tier'))
    return _RELATION_MAX_CALLER_INDEX.get(grant.relation)


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

    from bisheng.permission.domain.services.permission_service import PermissionService

    if not login_user.is_admin():
        raw_models = await _get_relation_models()
        model_map = {m['id']: _normalize_model_dict(m) for m in raw_models}
        binding_map = {
            b.get('key'): b for b in await _get_bindings()
            if b.get('resource_type') == resource_type and str(b.get('resource_id')) == str(resource_id)
        }
        caller_level = await PermissionService.get_permission_level(
            user_id=login_user.user_id,
            object_type=resource_type,
            object_id=resource_id,
            login_user=login_user,
        )

        for grant in (request.grants or []):
            ceiling = _grant_ceiling_index(grant, model_map)
            if ceiling is None or not _caller_satisfies_ceiling(caller_level, ceiling):
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
            if binding and binding.get('model_id'):
                m = model_map.get(binding['model_id'])
                ceiling = _TIER_MAX_CALLER_INDEX.get(m.get('grant_tier'), _LEGACY_REVOKE_MAX_CALLER_INDEX) if m else _LEGACY_REVOKE_MAX_CALLER_INDEX
            else:
                ceiling = _LEGACY_REVOKE_MAX_CALLER_INDEX
            if not _caller_satisfies_ceiling(caller_level, ceiling):
                return PermissionDeniedError.return_resp()

    grant_signatures = {_tuple_signature(g) for g in (request.grants or [])}
    revoke_signatures = {_tuple_signature(r) for r in (request.revokes or [])}
    rebind_only_signatures = grant_signatures & revoke_signatures

    tuple_grants = [
        grant for grant in (request.grants or [])
        if _tuple_signature(grant) not in rebind_only_signatures
    ]
    tuple_revokes = [
        revoke for revoke in (request.revokes or [])
        if _tuple_signature(revoke) not in rebind_only_signatures
    ]

    if tuple_grants or tuple_revokes:
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
        for key in _binding_lookup_keys(
            resource_type,
            str(resource_id),
            revoke.subject_type,
            revoke.subject_id,
            revoke.relation,
            getattr(revoke, 'include_children', None),
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
    logger.info(
        'resource_authorize success actor=%s resource=%s:%s grants=%d revokes=%d bindings=%d',
        login_user.user_id, resource_type, resource_id, len(request.grants or []), len(request.revokes or []),
        len(bindings_map),
    )
    return resp_200(None)


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
    allowed = await PermissionService.check(
        user_id=login_user.user_id,
        relation='can_edit',
        object_type=resource_type,
        object_id=resource_id,
        login_user=login_user,
    )
    if not allowed:
        return PermissionDeniedError.return_resp()

    permissions = await PermissionService.get_resource_permissions(
        object_type=resource_type,
        object_id=resource_id,
    )
    models = await _get_relation_models()
    model_map = {m['id']: m for m in models}
    binding_map = {
        b.get('key'): b for b in await _get_bindings()
        if b.get('resource_type') == resource_type and str(b.get('resource_id')) == str(resource_id)
    }
    bindings = list(binding_map.values())
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
    permissions = await _apply_binding_metadata_to_permissions(permissions, bindings, model_map)
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

    from bisheng.permission.domain.services.permission_service import PermissionService

    raw = [_normalize_model_dict(m) for m in await _get_relation_models()]
    if login_user.is_admin():
        return resp_200([RelationModelItem(**m) for m in raw])

    caller_level = await PermissionService.get_permission_level(
        user_id=login_user.user_id,
        object_type=object_type,
        object_id=object_id,
        login_user=login_user,
    )
    out = []
    for m in raw:
        ceiling = _TIER_MAX_CALLER_INDEX.get(m.get('grant_tier'))
        if ceiling is None:
            continue
        if _caller_satisfies_ceiling(caller_level, ceiling):
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
    model_id = f'custom_{uuid.uuid4().hex[:8]}'
    models.append({
        'id': model_id,
        'name': request.name.strip(),
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
    updated = False
    for m in models:
        if m.get('id') != model_id:
            continue
        if request.name is not None:
            m['name'] = request.name.strip()
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
    from bisheng.permission.domain.services.permission_service import PermissionService
    for b in to_remove:
        await PermissionService.authorize(
            object_type=b.get('resource_type'),
            object_id=str(b.get('resource_id')),
            grants=[],
            revokes=[AuthorizeRevokeItem(
                subject_type=b.get('subject_type'),
                subject_id=int(b.get('subject_id')),
                relation=b.get('relation'),
                include_children=bool(b.get('include_children')),
            )],
        )

    remain_bindings = [b for b in bindings if b.get('model_id') != model_id]
    await _save_relation_models(remain_models)
    await _save_bindings(remain_bindings)
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
