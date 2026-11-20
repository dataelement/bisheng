"""Fresh actual Root-provider sharing checks for every model/provider read.

Default inheritance never grants execution access. Cached business rows are
rechecked against the execution tenant and current permission relation.
"""

from collections.abc import Iterable
from typing import Any

from bisheng.common.errcode.llm_tenant import LLMModelNotAccessibleError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.permission.application import PermissionSubject, get_permission_relation_api
from bisheng.permission.application.relation_api import get_permission_relation_api_sync

from .models import LLMDao, LLMModel, LLMServer


def _coerce_positive_int(value: Any) -> int | None:
    """Best-effort cast of a config payload value to a positive int model_id.

    Handles ``None``, integers, numeric strings (WSModel.id is ``str``), and
    silently drops non-numeric or non-positive values — they are not real
    references to validate.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return None
    return coerced if coerced > 0 else None


def _shared_sync(server_id: int, owner_tenant_id: int) -> bool:
    tenant = _resolve_tenant_id()
    if type(tenant) is not int or tenant <= 0:
        return False
    if owner_tenant_id == tenant:
        return True
    if owner_tenant_id != ROOT_TENANT_ID:
        return False
    permissions = get_permission_relation_api_sync()
    ids = permissions.list_resource_ids_sync(
        subject=PermissionSubject("tenant", str(tenant)), relation="shared_with", resource_type="llm_server"
    )
    return str(server_id) in ids


async def _shared_async(server_id: int, owner_tenant_id: int) -> bool:
    tenant = _resolve_tenant_id()
    if type(tenant) is not int or tenant <= 0:
        return False
    if owner_tenant_id == tenant:
        return True
    if owner_tenant_id != ROOT_TENANT_ID:
        return False
    permissions = await get_permission_relation_api()
    ids = await permissions.list_resource_ids(
        subject=PermissionSubject("tenant", str(tenant)), relation="shared_with", resource_type="llm_server"
    )
    return str(server_id) in ids


def get_model_by_id_with_share_fallback(model_id: int | None, *, cache: bool = False) -> LLMModel | None:
    if not model_id:
        return None
    with bypass_tenant_filter():
        model = LLMDao.get_model_by_id(model_id, cache=False)
    return model if model is not None and _shared_sync(model.server_id, model.tenant_id) else None


async def aget_model_by_id_with_share_fallback(model_id: int | None, *, cache: bool = False) -> LLMModel | None:
    if not model_id:
        return None
    with bypass_tenant_filter():
        model = await LLMDao.aget_model_by_id(model_id, cache=False)
    return model if model is not None and await _shared_async(model.server_id, model.tenant_id) else None


def get_server_by_id_with_share_fallback(server_id: int | None, *, cache: bool = False) -> LLMServer | None:
    if not server_id:
        return None
    with bypass_tenant_filter():
        server = LLMDao.get_server_by_id(server_id, cache=False)
    return server if server is not None and _shared_sync(server.id, server.tenant_id) else None


async def aget_server_by_id_with_share_fallback(server_id: int | None, *, cache: bool = False) -> LLMServer | None:
    if not server_id:
        return None
    with bypass_tenant_filter():
        server = await LLMDao.aget_server_by_id(server_id, cache=False)
    return server if server is not None and await _shared_async(server.id, server.tenant_id) else None


async def avalidate_system_model_refs(
    model_ids: Iterable[Any],
    target_tenant_id: int,
) -> None:
    """Refuse a ``tenant_system_model_config`` write that points outside the
    target tenant's allowed catalog.

    Allowed owners for any referenced ``llm_model`` row:
      * ``target_tenant_id`` itself, or
      * Root, when its provider is actually shared to the execution Child.

    Anything else is the v2.5 stale-Root → Child-model gotcha that this
    module was written to make impossible after data repair. Raises
    ``LLMModelNotAccessibleError`` (19802) on the first offender so the
    UI surfaces the same toast as a deleted/cross-tenant pick.

    ``model_ids`` accepts mixed int / numeric-string / None — WSModel.id is
    ``str``, the rest are ``int``. None / non-numeric / non-positive entries
    are dropped silently (they are not real references).
    """
    seen: set[int] = set()
    for raw in model_ids:
        coerced = _coerce_positive_int(raw)
        if coerced is not None:
            seen.add(coerced)
    if not seen:
        return
    with bypass_tenant_filter():
        rows = await LLMDao.aget_model_by_ids(list(seen))
    by_id = {row.id: row for row in rows}
    for mid in seen:
        row = by_id.get(mid)
        if row is None:
            raise LLMModelNotAccessibleError.http_exception()
        if row.tenant_id == target_tenant_id:
            continue
        if target_tenant_id == _resolve_tenant_id() and await _shared_async(row.server_id, row.tenant_id):
            continue
        raise LLMModelNotAccessibleError.http_exception()


__all__ = [
    "aget_model_by_id_with_share_fallback",
    "aget_server_by_id_with_share_fallback",
    "avalidate_system_model_refs",
    "get_model_by_id_with_share_fallback",
    "get_server_by_id_with_share_fallback",
]
