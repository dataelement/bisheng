"""Retire provider-backed documents before the local deletion cutover.

Local DIR rows and their synthetic mappings are local-only facts; a file that
already carries a remote mapping cannot vanish locally without orphaning its
remote document (AC-14). This module deletes those remote documents first, with
HTTP outside any business transaction, and accepts the provider's asynchronous
``task_id`` acknowledgement as an accepted delete while the local mapping is
tombstoned for reconciliation.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from urllib.parse import quote

import httpx
from sqlalchemy import select

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.application.provider_v1_runtime import ProviderFeatureUnavailable
from bisheng.knowledge.application.provider_weknora_upload import (
    _instance_http_params,
    _unseal_upload_secret,
    mint_external_user_token,
)
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderBinding as Binding
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderGeneration as Generation,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderInstance as Instance,
)
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderMapping as Mapping

_ACCEPTED = frozenset({200, 202, 404})


@dataclass(frozen=True, slots=True)
class RemoteTarget:
    """One remote document plus the frozen route facts that address it."""

    file_id: int
    remote_id: str
    generation: int
    instance_id: int
    remote_scope_id: str
    remote_kb_id: str
    upload_secret: str = ""


async def collect_targets(*, tenant_id: int, space_id: int, file_ids: tuple[int, ...]) -> tuple[RemoteTarget, ...]:
    """Remote documents owned by these local file ids, with their frozen route facts."""
    if not file_ids:
        return ()
    async with get_async_db_session() as session:
        rows = (
            await session.execute(
                select(
                    Mapping.local_resource_id,
                    Mapping.remote_object_id,
                    Mapping.generation,
                    Generation.provider_instance_id,
                    Generation.remote_scope_id,
                    Generation.remote_kb_id,
                    Instance.upload_credential_ref,
                )
                .join(
                    Generation,
                    (Generation.tenant_id == Mapping.tenant_id)
                    & (Generation.space_id == Mapping.space_id)
                    & (Generation.generation == Mapping.generation),
                )
                .join(
                    Instance,
                    (Instance.tenant_id == Generation.tenant_id) & (Instance.id == Generation.provider_instance_id),
                )
                .where(
                    Mapping.tenant_id == tenant_id,
                    Mapping.space_id == space_id,
                    Mapping.resource_type == "file",
                    Mapping.lifecycle_state.in_(("received", "active")),
                    Mapping.tombstoned_at.is_(None),
                    Mapping.local_resource_id.in_(file_ids),
                )
            )
        ).all()
    targets = []
    for row in rows:
        secret = _unseal_upload_secret(row.upload_credential_ref)
        if secret is None:
            # Without the signed-token secret this deployment cannot prove a delete.
            raise ProviderFeatureUnavailable()
        targets.append(
            RemoteTarget(
                file_id=row.local_resource_id,
                remote_id=row.remote_object_id,
                generation=row.generation,
                instance_id=row.provider_instance_id,
                remote_scope_id=row.remote_scope_id,
                remote_kb_id=row.remote_kb_id,
                upload_secret=secret,
            )
        )
    return tuple(targets)


async def _delete_one(target: RemoteTarget, *, tenant_id: int, space_id: int, user_id: int) -> None:
    route = SimpleNamespace(
        tenant_id=tenant_id,
        space_id=space_id,
        provider_key="weknora",
        generation=target.generation,
        instance_id=target.instance_id,
        remote_scope_id=target.remote_scope_id,
        remote_kb_id=target.remote_kb_id,
    )
    scope = target.remote_scope_id
    if not scope.isdigit():
        raise ProviderFeatureUnavailable()
    params = await _instance_http_params(route)
    headers = dict(params.pop("headers"))
    headers["X-External-User-Token"] = mint_external_user_token(
        secret=target.upload_secret,
        weknora_tenant_id=int(scope),
        external_user_id=str(user_id),
    )
    async with httpx.AsyncClient(headers=headers, **params) as client:
        response = await client.delete(f"knowledge/{target.remote_id}")
    # 200/202: delete accepted as an async task. 404: already gone, equally final.
    if response.status_code not in _ACCEPTED:
        raise ProviderFeatureUnavailable()


async def retire_remote_documents(*, tenant_id: int, space_id: int, file_ids: tuple[int, ...], user_id: int) -> int:
    """Delete every remote document owned by these files; returns the target count."""
    if get_current_tenant_id() is not None and get_current_tenant_id() != tenant_id:
        raise ProviderFeatureUnavailable()
    targets = await collect_targets(tenant_id=tenant_id, space_id=space_id, file_ids=file_ids)
    for target in targets:
        await _delete_one(target, tenant_id=tenant_id, space_id=space_id, user_id=user_id)
    return len(targets)


@dataclass(frozen=True, slots=True)
class RemoteLibrary:
    """The remote library a space owns, plus the facts that address it."""

    remote_id: str
    generation: int
    instance_id: int
    remote_scope_id: str
    endpoint: str
    credential_ref: str
    upload_credential_ref: str | None


async def collect_library(*, tenant_id: int, space_id: int) -> RemoteLibrary | None:
    """The library this space's binding owns; None for a native space.

    The *latest* generation is used when the binding has no active pointer: a
    space whose creation never finished still owns whatever library it managed
    to create upstream, and leaving that behind is exactly the orphan this
    retirement exists to prevent.
    """
    async with get_async_db_session() as session:
        binding = (
            await session.execute(
                select(Binding.provider_key, Binding.active_generation).where(
                    Binding.tenant_id == tenant_id, Binding.space_id == space_id
                )
            )
        ).one_or_none()
        if binding is None or binding[0] == "native":
            return None
        if binding[0] != "weknora":
            # An unregistered provider cannot be proven retired, so refuse rather
            # than delete locally and orphan it.
            raise ProviderFeatureUnavailable()
        query = (
            select(
                Generation.remote_kb_id,
                Generation.generation,
                Generation.provider_instance_id,
                Generation.remote_scope_id,
                Instance.endpoint,
                Instance.credential_ref,
                Instance.upload_credential_ref,
            )
            .select_from(Generation)
            .join(
                Instance,
                (Instance.tenant_id == Generation.tenant_id) & (Instance.id == Generation.provider_instance_id),
            )
            .where(Generation.tenant_id == tenant_id, Generation.space_id == space_id)
            .order_by(Generation.generation.desc())
        )
        if binding[1] is not None:
            query = query.where(Generation.generation == binding[1])
        row = (await session.execute(query.limit(1))).one_or_none()
    if row is None:
        return None
    return RemoteLibrary(
        remote_id=row.remote_kb_id,
        generation=row.generation,
        instance_id=row.provider_instance_id,
        remote_scope_id=row.remote_scope_id,
        endpoint=row.endpoint,
        credential_ref=row.credential_ref,
        upload_credential_ref=row.upload_credential_ref,
    )


async def _delete_library(target: RemoteLibrary, *, tenant_id: int, space_id: int, user_id: int) -> None:
    from bisheng.knowledge.application.provider_external_token import provider_external_identity
    from bisheng.knowledge.application.provider_v1_runtime import _attach_external_identity, _client_parameters

    if not target.remote_id or target.remote_id in (".", ".."):
        raise ProviderFeatureUnavailable()
    params = _client_parameters(
        target.endpoint,
        target.credential_ref,
        tenant_id=tenant_id,
        instance_id=target.instance_id,
        scope=target.remote_scope_id,
        timeout=httpx.Timeout(60, connect=10),
    )
    with provider_external_identity(user_id):
        attached = _attach_external_identity(params, target.upload_credential_ref, target.remote_scope_id)
        async with httpx.AsyncClient(**attached) as client:
            response = await client.delete("knowledge-bases/" + quote(target.remote_id, safe=""))
    # 200/202: accepted as an async task. 404: already gone, equally final.
    if response.status_code not in _ACCEPTED:
        raise ProviderFeatureUnavailable()


async def retire_remote_library(*, tenant_id: int, space_id: int, user_id: int) -> int:
    """Delete the remote library a whole-space delete owns; returns the target count.

    Documents are retired per file above; this removes the container itself. It
    runs before the local cutover because afterwards the route facts that address
    the library are gone from the local ledger.
    """
    if get_current_tenant_id() is not None and get_current_tenant_id() != tenant_id:
        raise ProviderFeatureUnavailable()
    target = await collect_library(tenant_id=tenant_id, space_id=space_id)
    if target is None:
        return 0
    await _delete_library(target, tenant_id=tenant_id, space_id=space_id, user_id=user_id)
    return 1
