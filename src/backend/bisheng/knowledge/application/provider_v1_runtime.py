"""Trusted v1/API-worker composition. Only local identities cross the browser boundary."""

import os
import re
from contextlib import asynccontextmanager
from urllib.parse import quote, urlsplit

import httpx
from sqlalchemy import select

from bisheng.common.errcode.knowledge import KnowledgeUnificationError
from bisheng.common.errcode.knowledge_space import SpaceFileNotFoundError, SpaceNotFoundError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.application.provider_external_token import (
    EXTERNAL_USER_TOKEN_HEADER,
    current_external_user_id,
    mint_external_user_token,
    unseal_external_token_secret,
)
from bisheng.knowledge.application.provider_reads import ProviderReads
from bisheng.knowledge.application.provider_resolver import ProviderResolver
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderGeneration as Generation,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderInstance as Instance,
)
from bisheng.knowledge.domain.repositories.provider_retrieval_repository import (
    ProviderRetrievalRepository,
    RetrievalFactsUnavailable,
)


class ProviderFeatureUnavailable(KnowledgeUnificationError):
    Code: int = 18089
    Msg: str = "This provider operation cannot be safely offered"


async def resolve_space_route(space_id):
    space = await KnowledgeDao.aquery_by_id(space_id)
    if space is None or space.tenant_id != get_current_tenant_id() or is_tenant_filter_bypassed():
        raise SpaceNotFoundError()
    try:
        route = await ProviderRetrievalRepository().route(space)
    except RetrievalFactsUnavailable:
        raise ProviderFeatureUnavailable() from None
    if route and route.provider_key != "weknora":
        raise ProviderFeatureUnavailable()
    return route


async def file_route(file_id):
    file = await KnowledgeFileDao.query_by_id(file_id)
    if not file or file.tenant_id != get_current_tenant_id():
        raise SpaceFileNotFoundError()
    return file.knowledge_id, await resolve_space_route(file.knowledge_id)


def _stored_parameters(endpoint, ref, *, timeout=None):
    """Use the key sealed with this instance. A stored key cannot be redirected to a public origin."""
    from bisheng.core.config.settings import decrypt_token
    from bisheng.core.config.weknora import WeKnoraSettings

    try:
        base = WeKnoraSettings.normalize_endpoint(str(endpoint).removesuffix("/"))
        secret = decrypt_token(ref.removeprefix("fernet:"))
    except Exception:
        raise ProviderFeatureUnavailable() from None
    if not secret or not secret.isascii() or not secret.isprintable() or any(c.isspace() for c in secret):
        raise ProviderFeatureUnavailable()
    return {
        "base_url": base + "/api/v1/",
        "headers": {"X-API-Key": secret},
        "trust_env": False,
        "follow_redirects": False,
        "timeout": timeout or httpx.Timeout(30, connect=5),
    }


def _client_parameters(endpoint, ref, *, tenant_id=None, instance_id=None, scope=None, timeout=None):
    """Build transport parameters for one provider instance.

    ``timeout`` overrides the configured/default budget. Blocking model probes
    exceed any short request budget, so the provisioning runtime supplies its
    own; retrieval and reads keep the fast default.
    """
    from bisheng.common.services.config_service import settings

    cfg = settings.weknora
    if (
        cfg is not None
        and tenant_id is not None
        and instance_id is not None
        and (cfg.tenant_id, cfg.instance_id) == (tenant_id, instance_id)
    ):
        # A configured key is never a global fallback, nor can a DB endpoint redirect it.
        if cfg.remote_scope_id != scope or not cfg.api_key:
            raise ProviderFeatureUnavailable()
        secret = cfg.api_key.get_secret_value()
        if not secret or not secret.isascii() or not secret.isprintable() or any(c.isspace() for c in secret):
            raise ProviderFeatureUnavailable()
        return dict(
            base_url=cfg.endpoint + "/api/v1/",
            headers={"X-API-Key": secret},
            trust_env=False,
            follow_redirects=False,
            timeout=timeout or httpx.Timeout(cfg.timeout_seconds, connect=cfg.connect_timeout_seconds),
        )

    if isinstance(ref, str) and ref.startswith("fernet:"):
        return _stored_parameters(endpoint, ref, timeout=timeout)

    url = urlsplit(endpoint)
    if url.scheme == "http":
        # Only the registered instance at this exact operator-pinned origin may use cleartext.
        if endpoint.removesuffix("/") != settings.weknora_http_endpoint:
            raise ProviderFeatureUnavailable()
    elif url.scheme != "https":
        raise ProviderFeatureUnavailable()
    if not url.hostname or url.username is not None or url.password is not None or url.query or url.fragment:
        raise ProviderFeatureUnavailable()
    if not re.fullmatch(r"env:BS_WEKNORA_[A-Z0-9_]+", ref):
        raise ProviderFeatureUnavailable()
    secret = os.environ.get(ref[4:])
    if not secret:
        raise ProviderFeatureUnavailable()
    return dict(
        base_url=endpoint.rstrip("/") + "/api/v1/",
        headers={"X-API-Key": secret},
        trust_env=False,
        follow_redirects=False,
        timeout=timeout or httpx.Timeout(30, connect=5),
    )


def _attach_external_identity(params, upload_ref, scope):
    """Add the signed external-user token when the instance seals an HMAC.

    Instances without a sealed secret keep API-key-only auth. Once a secret is
    configured the workspace is expected to run in signed_token mode, so a
    missing acting user is a capability failure rather than a quiet 401.
    """
    if not upload_ref:
        return params
    secret = unseal_external_token_secret(upload_ref)
    user_id = current_external_user_id()
    if secret is None or type(user_id) is not int or user_id <= 0:
        raise ProviderFeatureUnavailable()
    if not isinstance(scope, str) or not scope.isdigit() or int(scope) <= 0:
        raise ProviderFeatureUnavailable()
    headers = dict(params["headers"])
    headers[EXTERNAL_USER_TOKEN_HEADER] = mint_external_user_token(
        secret=secret, weknora_tenant_id=int(scope), external_user_id=str(user_id)
    )
    return {**params, "headers": headers}


@asynccontextmanager
async def provision_instance_client(*, tenant_id, instance_id, scope, capability_revision=None):
    if tenant_id != get_current_tenant_id() or is_tenant_filter_bypassed():
        raise ProviderFeatureUnavailable()
    q = select(Instance.endpoint, Instance.credential_ref, Instance.upload_credential_ref).where(
        Instance.tenant_id == tenant_id,
        Instance.id == instance_id,
        Instance.remote_scope_id == scope,
        Instance.provider_key == "weknora",
        Instance.capability_revision > 0,
        Instance.state == "ready",
    )
    if capability_revision is not None:
        q = q.where(Instance.capability_revision == capability_revision)
    async with get_async_db_session() as session:
        row = (await session.execute(q)).one_or_none()
    if not row:
        raise ProviderFeatureUnavailable()
    endpoint, credential_ref, upload_ref = row
    params = _client_parameters(endpoint, credential_ref, tenant_id=tenant_id, instance_id=instance_id, scope=scope)
    async with httpx.AsyncClient(**_attach_external_identity(params, upload_ref, scope)) as client:
        yield client


@asynccontextmanager
async def instance_client(context):
    route = await resolve_space_route(context.space_id)
    if (
        not route
        or not route.capability_revision
        or getattr(context, "capability_revision", route.capability_revision) != route.capability_revision
        or any(
            getattr(route, k) != getattr(context, k)
            for k in (
                "tenant_id",
                "space_id",
                "instance_id",
                "generation",
                "provider_key",
                "remote_scope_id",
                "remote_kb_id",
            )
        )
    ):
        raise ProviderFeatureUnavailable()
    async with get_async_db_session() as session:
        row = (
            await session.execute(
                select(Instance.endpoint, Instance.credential_ref, Instance.upload_credential_ref)
                .join(Generation, Generation.provider_instance_id == Instance.id)
                .where(
                    Generation.tenant_id == route.tenant_id,
                    Generation.space_id == route.space_id,
                    Generation.generation == route.generation,
                    Generation.remote_kb_id == route.remote_kb_id,
                    Generation.remote_scope_id == route.remote_scope_id,
                    Generation.state == "ready",
                    Instance.id == route.instance_id,
                    Instance.provider_key == route.provider_key,
                    Instance.remote_scope_id == route.remote_scope_id,
                    Instance.tenant_id == route.tenant_id,
                    Instance.state == "ready",
                )
            )
        ).one_or_none()
    if not row:
        raise ProviderFeatureUnavailable()
    endpoint, credential_ref, upload_ref = row
    params = _client_parameters(
        endpoint, credential_ref, tenant_id=route.tenant_id, instance_id=route.instance_id, scope=route.remote_scope_id
    )
    async with httpx.AsyncClient(**_attach_external_identity(params, upload_ref, route.remote_scope_id)) as client:
        yield client


def handle_url(handle):
    return f"/api/v1/knowledge/space/{handle.space_id}/files/{handle.file_id}/content/{handle.operation}?version_id={handle.version_id}&generation={handle.generation}&epoch={handle.epoch}"


class _Download:
    def __init__(self, context):
        self.context = context

    @asynccontextmanager
    async def open_stream(self, remote_id, *, range_header=None):
        if not remote_id or remote_id in (".", "..") or "/" in remote_id or "\\" in remote_id:
            raise ProviderFeatureUnavailable()
        path = "knowledge/" + quote(remote_id, safe="")
        async with instance_client(self.context) as client:
            # Verify the scoped remote object, not just service-key access to the tenant.
            resp = await client.get(path)
            if resp.status_code != 200:
                raise ProviderFeatureUnavailable()
            obj = resp.json().get("data") or {}
            if (obj.get("id"), obj.get("knowledge_base_id"), str(obj.get("tenant_id"))) != (
                remote_id,
                self.context.remote_kb_id,
                self.context.remote_scope_id,
            ):
                raise ProviderFeatureUnavailable()
            headers = {"Accept-Encoding": "identity"}
            if range_header:
                if not re.fullmatch(r"bytes=(?:\d+-\d*|-\d+)", range_header):
                    raise ProviderFeatureUnavailable()
                headers["Range"] = range_header
            async with client.stream("GET", path + "/download", headers=headers) as upstream:
                if upstream.status_code not in (200, 206) or (range_header and upstream.status_code != 206):
                    raise ProviderFeatureUnavailable()
                yield upstream


class _PreviewExcerpt:
    """A bounded plain-text derivative, never a link or stream of source bytes."""

    def __init__(self, context):
        self.context = context

    @asynccontextmanager
    async def open_stream(self, remote_id, *, range_header=None):
        import json

        if range_header or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", remote_id):
            raise ProviderFeatureUnavailable()
        async with instance_client(self.context) as client:
            async with client.stream(
                "GET", "chunks/" + remote_id, params={"page": 1, "page_size": 3, "chunk_type": "text"}
            ) as source:
                if source.status_code != 200:
                    raise ProviderFeatureUnavailable()
                raw = bytearray()
                async for block in source.aiter_bytes(chunk_size=16384):
                    if len(raw) + len(block) > 256 * 1024:
                        raise ProviderFeatureUnavailable()
                    raw.extend(block)
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ProviderFeatureUnavailable() from None
        if (
            not isinstance(body, dict)
            or body.get("success") is not True
            or not isinstance(body.get("data"), list)
            or not 1 <= len(body["data"]) <= 3
        ):
            raise ProviderFeatureUnavailable()
        pieces = []
        for chunk in body["data"]:
            if (
                not isinstance(chunk, dict)
                or chunk.get("knowledge_id") != remote_id
                or chunk.get("knowledge_base_id") != self.context.remote_kb_id
                or str(chunk.get("tenant_id")) != self.context.remote_scope_id
                or chunk.get("chunk_type") != "text"
                or not isinstance(chunk.get("content"), str)
            ):
                raise ProviderFeatureUnavailable()
            pieces.append(chunk["content"][:4096])
        text = ("解析文本节选（非原文件）\n\n" + "\n\n".join(pieces)).encode("utf-8")
        yield httpx.Response(200, content=text, headers={"content-type": "text/plain; charset=utf-8"})


class _Factory:
    def capabilities(self, context):
        # WeKnora /preview serves the ORIGINAL. Never substitute it for a derivative.
        return {"download": "supported", "preview": "supported"}

    def build(self, context):
        return _PreviewExcerpt(context) if context.operation == "preview" else _Download(context)


async def build_provider_reads():
    return await ProviderReads.from_runtime(ProviderResolver({"weknora": _Factory()}))
