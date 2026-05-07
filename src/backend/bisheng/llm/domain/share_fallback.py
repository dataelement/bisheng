"""Root-share fallback helpers for LLM model/server reads.

System-level model defaults (knowledge_llm / assistant_llm / ...) live in
``tenant_system_model_config``: a Child tenant without its own row inherits
Root's value when ``Root.share_default_to_children`` is on. The resolver in
``tenant_system_model_config.aresolve`` already bypasses tenant filtering to
reach the Root row, but the **referenced** ``model_id`` then has to be loaded
from ``llm_model`` — and that second SELECT goes back through the global
``do_orm_execute`` listener that injects ``WHERE tenant_id = <child>``,
so the Root-owned row is filtered out and consumers see "model deleted".

These helpers paper over that gap: read in the requester's own scope first
(the common case + caches stay tenant-correct), and only on miss do a single
bypassed re-read guarded by a Root + share-on check. They never widen
visibility beyond the existing ``share_default_to_children`` policy.
"""
from typing import Optional

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.tenant import ROOT_TENANT_ID, TenantDao

from .models import LLMDao, LLMModel, LLMServer


def _root_share_visible_sync(owner_tenant_id: Optional[int]) -> bool:
    if owner_tenant_id != ROOT_TENANT_ID:
        return False
    root = TenantDao.get_by_id(ROOT_TENANT_ID)
    return bool(root and root.share_default_to_children)


async def _root_share_visible_async(owner_tenant_id: Optional[int]) -> bool:
    if owner_tenant_id != ROOT_TENANT_ID:
        return False
    root = await TenantDao.aget_by_id(ROOT_TENANT_ID)
    return bool(root and root.share_default_to_children)


def get_model_by_id_with_share_fallback(
    model_id: Optional[int], *, cache: bool = False,
) -> Optional[LLMModel]:
    """Sync read of an LLMModel id that may belong to Root.

    Cache is only consulted on the in-scope read; fallback reads skip the
    cache so a child never writes a Root-owned row under its own cache key.
    """
    if not model_id:
        return None
    model = LLMDao.get_model_by_id(model_id, cache=cache)
    if model is not None:
        return model
    with bypass_tenant_filter():
        model = LLMDao.get_model_by_id(model_id)
    if model is not None and _root_share_visible_sync(model.tenant_id):
        return model
    return None


async def aget_model_by_id_with_share_fallback(
    model_id: Optional[int], *, cache: bool = False,
) -> Optional[LLMModel]:
    if not model_id:
        return None
    model = await LLMDao.aget_model_by_id(model_id, cache=cache)
    if model is not None:
        return model
    with bypass_tenant_filter():
        model = await LLMDao.aget_model_by_id(model_id)
    if model is not None and await _root_share_visible_async(model.tenant_id):
        return model
    return None


def get_server_by_id_with_share_fallback(
    server_id: Optional[int], *, cache: bool = False,
) -> Optional[LLMServer]:
    if not server_id:
        return None
    server = LLMDao.get_server_by_id(server_id, cache=cache)
    if server is not None:
        return server
    with bypass_tenant_filter():
        server = LLMDao.get_server_by_id(server_id)
    if server is not None and _root_share_visible_sync(server.tenant_id):
        return server
    return None


async def aget_server_by_id_with_share_fallback(
    server_id: Optional[int], *, cache: bool = False,
) -> Optional[LLMServer]:
    if not server_id:
        return None
    server = await LLMDao.aget_server_by_id(server_id, cache=cache)
    if server is not None:
        return server
    with bypass_tenant_filter():
        server = await LLMDao.aget_server_by_id(server_id)
    if server is not None and await _root_share_visible_async(server.tenant_id):
        return server
    return None


__all__ = [
    "aget_model_by_id_with_share_fallback",
    "aget_server_by_id_with_share_fallback",
    "get_model_by_id_with_share_fallback",
    "get_server_by_id_with_share_fallback",
]
