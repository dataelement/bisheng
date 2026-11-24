"""Resolve workflow KB authority before any vector clients are constructed."""

from bisheng.core.context.tenant import get_current_tenant_id, get_visible_tenant_ids
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.knowledge.domain.services.space_flow_retrieval import abuild_scoped_login_user
from bisheng.utils.async_utils import run_async_safe


async def _acandidate_knowledge_ids(*, tenant_id, knowledge_ids):
    current_tenant = get_current_tenant_id()
    tenant_id = tenant_id if tenant_id is not None else current_tenant
    if tenant_id is None or (current_tenant is not None and tenant_id != current_tenant):
        return [], tenant_id
    ids = list(dict.fromkeys(int(item) for item in knowledge_ids))
    if not ids:
        return [], tenant_id
    visible = get_visible_tenant_ids() or frozenset({tenant_id})
    rows = await KnowledgeDao.aget_list_by_ids(ids)
    candidates = {
        row.id
        for row in rows
        if row.tenant_id == tenant_id
        or (row.tenant_id == 1 and row.tenant_id in visible and bool(getattr(row, "is_shared", False)))
    }
    return [item for item in ids if item in candidates], tenant_id


async def aauthorized_knowledge_ids(*, identity_user_id, tenant_id, knowledge_ids, check_permission: bool = True):
    """Return bound knowledge ids. When ``check_permission`` is False (toggle OFF),
    skip use-permission filtering and keep every tenant-visible binding.
    """
    candidates, tenant_id = await _acandidate_knowledge_ids(tenant_id=tenant_id, knowledge_ids=knowledge_ids)
    if not candidates or not check_permission:
        return candidates
    identity = await abuild_scoped_login_user(identity_user_id, tenant_id)
    if identity is None:
        return []
    permitted = await KnowledgeRag.afilter_usable_knowledge_ids(identity, candidates)
    return [item for item in candidates if item in permitted]


def authorized_knowledge_ids(*, identity_user_id, tenant_id, knowledge_ids, check_permission: bool = True):
    if not knowledge_ids:
        return []
    return run_async_safe(
        aauthorized_knowledge_ids(
            identity_user_id=identity_user_id,
            tenant_id=tenant_id,
            knowledge_ids=knowledge_ids,
            check_permission=check_permission,
        ),
        timeout=60,
    )
