"""Which models a tenant can call, and what a given name resolves to (F051 D5 / D6).

This module is the **single source** for three consumers that must agree: the
model protocol face, F052's model-list tool, and F055's publish precheck. If any
of them answered "which models exist" or "who is `qwen-max`" on its own, a model
would be listable and uncallable, or pass a precheck and fail at runtime.

Two facts make the naming rules non-obvious:

* ``(server_id, model_name)`` is what is unique — the same ``model_name`` under
  two providers is a legal configuration in model management. A bare name that
  matches both is therefore refused with the qualified alternatives rather than
  silently bound to one provider's credentials.
* the qualified form is ``{provider name}/{model name}``, and ``model_name``
  itself may contain a slash (OpenRouter-style ``qwen/qwen-2.5-72b``). Bare
  match is tried first for exactly that reason.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal

from cachetools import TTLCache
from loguru import logger

from bisheng.common.errcode.model_face import (
    ModelFaceCapabilityUndeclaredError,
    ModelFaceCatalogUnavailableError,
    ModelFaceModelAmbiguousError,
    ModelFaceModelNotFoundError,
    ModelFaceModelOfflineError,
)
from bisheng.common.services.config_service import settings
from bisheng.common.services.metric_log import emit_metric
from bisheng.core.context.tenant import (
    DEFAULT_TENANT_ID,
    bypass_tenant_filter,
    current_tenant_id,
    set_admin_scope_tenant_id,
    set_visible_tenant_ids,
)
from bisheng.llm.domain.const import LLMModelType
from bisheng.llm.domain.models import LLMDao

QUALIFIED_NAME_SEPARATOR = "/"


@dataclass(frozen=True, slots=True)
class CallableModel:
    model_id: int
    model_name: str
    server_id: int
    server_name: str
    server_type: str
    # False when another provider in this tenant publishes the same
    # ``model_name`` — the bare name is then refused and only the qualified one
    # is offered.
    is_unique: bool

    @property
    def qualified_name(self) -> str:
        return f"{self.server_name}{QUALIFIED_NAME_SEPARATOR}{self.model_name}"

    @property
    def callable_name(self) -> str:
        """The name a caller can put in ``model`` and have it resolve."""

        return self.model_name if self.is_unique else self.qualified_name


@dataclass(frozen=True, slots=True)
class ModelRange:
    """Whose range this is: the whole tenant, or one application's declaration."""

    kind: Literal["tenant", "declared"] = "tenant"
    declared: frozenset[str] | None = None

    def allows(self, model: CallableModel) -> bool:
        if self.kind == "tenant":
            return True
        declared = self.declared or frozenset()
        return model.model_name in declared or model.qualified_name in declared


TENANT_RANGE = ModelRange()


@dataclass(frozen=True, slots=True)
class ResolvedModel:
    model_id: int
    server_id: int
    model_name: str
    server_name: str
    server_type: str
    qualified_name: str


# Keyed by tenant, not by credential: the callable range is a tenant-level
# configuration (AC-09), never per key. Successful results only — an exception
# is never cached, or a permission blip would be pinned in for a minute.
_CATALOG_CACHE: TTLCache = TTLCache(maxsize=256, ttl=60)
_CACHED_TTL: int | None = None


def _cache() -> TTLCache:
    """Return the cache, rebuilt if the configured TTL changed."""

    global _CACHED_TTL, _CATALOG_CACHE
    ttl = int(settings.open_api.model_catalog_ttl_seconds)
    if _CACHED_TTL != ttl:
        _CATALOG_CACHE = TTLCache(maxsize=256, ttl=ttl)
        _CACHED_TTL = ttl
    return _CATALOG_CACHE


def invalidate_catalog(tenant_id: int | None = None) -> None:
    """Drop cached catalogs. Without an argument, drop every tenant's."""

    cache = _cache()
    if tenant_id is None:
        cache.clear()
    else:
        cache.pop(tenant_id, None)


@contextmanager
def _as_tenant(tenant_id: int):
    """Make ``tenant_id`` the authoritative tenant for the queries below.

    ``acollect_visible_servers`` takes the leaf id for its permission lookups,
    but the own-rows query underneath still reads the tenant ContextVar — and
    this module caches per ``tenant_id``. If the two ever disagreed, one
    tenant's rows would be cached under another's key, which is a cross-tenant
    leak with a sixty-second half-life. Binding them here is what makes the
    parameter in this module's public signature honest for all three consumers
    (the face, F052's list tool, F055's precheck), including any that call it
    from a background task with no request context at all.
    """

    tokens = [
        current_tenant_id.set(tenant_id),
        # An operator viewing another tenant through the F019 admin scope must
        # not shift what an application or a key may call.
        set_admin_scope_tenant_id(None),
        set_visible_tenant_ids(frozenset({DEFAULT_TENANT_ID, tenant_id})),
    ]
    try:
        yield
    finally:
        for token in reversed(tokens):
            token.var.reset(token)


async def _load_callable_chat_models(tenant_id: int) -> list[CallableModel]:
    from bisheng.llm.domain.services.llm import LLMService

    with _as_tenant(tenant_id):
        servers = await LLMService.acollect_visible_servers(tenant_id, strict=True)
    if not servers:
        return []
    server_by_id = {server.id: server for server in servers}
    # Bypass so a Child sees models under Root servers granted via
    # ``shared_with`` — the tenant filter would strip exactly those rows.
    with bypass_tenant_filter():
        models = await LLMDao.aget_model_by_server_ids(list(server_by_id))

    chat_rows = []
    for model in models:
        server = server_by_id.get(model.server_id)
        if server is None:
            # The query above asks for exactly these server ids, so this cannot
            # happen today; it stays as the cheap guard that keeps a future
            # widening of that query from producing a ``CallableModel`` with no
            # provider name, which would make ``qualified_name`` nonsense.
            continue
        if model.model_type != LLMModelType.LLM.value or not model.online:
            continue
        chat_rows.append((model, server))

    name_counts: dict[str, int] = {}
    for model, _server in chat_rows:
        name_counts[model.model_name] = name_counts.get(model.model_name, 0) + 1

    return [
        CallableModel(
            model_id=model.id,
            model_name=model.model_name,
            server_id=server.id,
            server_name=server.name,
            server_type=server.type,
            is_unique=name_counts[model.model_name] == 1,
        )
        for model, server in chat_rows
    ]


async def list_callable_chat_models(tenant_id: int) -> list[CallableModel]:
    """Online chat models this tenant may call, with their callable names.

    Fail-closed: any failure reading the catalog raises 26216 rather than
    returning a narrower set. A narrower set is indistinguishable from "that
    model does not exist" at the call site, which is the worst possible answer
    to give an agent that is about to retry.
    """

    cache = _cache()
    cached = cache.get(tenant_id)
    if cached is not None:
        emit_metric("model_catalog", status="hit", tenant_id=tenant_id)
        return cached
    try:
        rows = await _load_callable_chat_models(tenant_id)
    except Exception as exc:
        emit_metric("model_catalog", status="unavailable", tenant_id=tenant_id)
        logger.opt(exception=True).error("model_catalog.unavailable | tenant_id={}", tenant_id)
        raise ModelFaceCatalogUnavailableError(exception=exc) from exc
    emit_metric("model_catalog", status="miss", tenant_id=tenant_id)
    cache[tenant_id] = rows
    return rows


async def _explain_miss(tenant_id: int, requested: str) -> None:
    """Raise the code that says *why* the name did not resolve.

    Only ever reached on the failure path, so its two extra queries never touch
    a successful call.

    There is deliberately no "revoked" (26213) verdict here. Deleting a provider
    deletes its model rows with it (``LLMDao.adelete_server_by_id``), so by the
    time a name misses, a taken-away model is indistinguishable from one that
    never existed — and inventing a distinction would mean keeping a tombstone
    this feature has no other use for. 26213 is still reachable, and is the
    honest place for it: within the catalog's cache window the name resolves and
    ``get_bisheng_llm`` is the one that finds the row gone, which the face
    translates (``model_gateway_service._LLM_ERROR_TRANSLATION``).
    """

    from bisheng.llm.domain.services.llm import LLMService

    try:
        with _as_tenant(tenant_id):
            servers = await LLMService.acollect_visible_servers(tenant_id, strict=True)
        server_by_id = {server.id: server for server in servers}
        with bypass_tenant_filter():
            models = await LLMDao.aget_model_by_server_ids(list(server_by_id)) if server_by_id else []
    except Exception as exc:
        raise ModelFaceCatalogUnavailableError(exception=exc) from exc

    bare = requested
    for server in servers:
        prefix = f"{server.name}{QUALIFIED_NAME_SEPARATOR}"
        if requested.startswith(prefix):
            bare = requested[len(prefix) :]
            break

    offline = False
    for model in models:
        if model.model_name not in (requested, bare):
            continue
        if model.model_type != LLMModelType.LLM.value:
            # Type is not disclosed: an embedding model reads as "not found",
            # exactly like another tenant's model does.
            continue
        if not model.online:
            offline = True
    if offline:
        raise ModelFaceModelOfflineError(model=requested)
    raise ModelFaceModelNotFoundError(model=requested)


async def resolve_model_name(
    tenant_id: int,
    requested: str,
    *,
    range: ModelRange | None = None,
) -> ResolvedModel:
    """Resolve a requested model name against this tenant's callable set.

    Order matters: exact bare match, then qualified match, then a second pass
    over the unfiltered rows purely to say why it missed.
    """

    scope = range or TENANT_RANGE
    catalog = await list_callable_chat_models(tenant_id)

    exact = [model for model in catalog if model.model_name == requested]
    if len(exact) > 1:
        raise ModelFaceModelAmbiguousError(
            model=requested,
            candidates=[model.qualified_name for model in exact],
        )
    match = exact[0] if exact else None

    if match is None and QUALIFIED_NAME_SEPARATOR in requested:
        # Server names are unique within a tenant, so at most one prefix can
        # match and the qualified form is always unambiguous.
        for model in catalog:
            prefix = f"{model.server_name}{QUALIFIED_NAME_SEPARATOR}"
            if requested.startswith(prefix) and model.model_name == requested[len(prefix) :]:
                match = model
                break

    if match is None:
        await _explain_miss(tenant_id, requested)
        raise AssertionError("unreachable")  # _explain_miss always raises

    if not scope.allows(match):
        # Offline / revoked is decided before this, so "undeclared" can only
        # mean the owner never wrote the model into the declaration — which is
        # a different fix from "an administrator took it away".
        raise ModelFaceCapabilityUndeclaredError(model=requested)

    return ResolvedModel(
        model_id=match.model_id,
        server_id=match.server_id,
        model_name=match.model_name,
        server_name=match.server_name,
        server_type=match.server_type,
        qualified_name=match.qualified_name,
    )


__all__ = [
    "QUALIFIED_NAME_SEPARATOR",
    "TENANT_RANGE",
    "CallableModel",
    "ModelRange",
    "ResolvedModel",
    "invalidate_catalog",
    "list_callable_chat_models",
    "resolve_model_name",
]
