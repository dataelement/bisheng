"""WeKnora upload port: signed external-user JWT + ingest receipt principal.

The tenant API key alone is not a receipt actor (WeKnora rejects it). Admission
requires the instance's sealed HMAC secret matching the remote tenant's
APIPrincipalConfig in signed_token mode, plus finite server byte budgets.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from types import SimpleNamespace

import httpx
from sqlalchemy import select

from bisheng.core.database import get_async_db_session
from bisheng.knowledge.application.provider_external_token import (
    mint_external_user_token,
    unseal_external_token_secret,
)
from bisheng.knowledge.application.provider_upload_quota import UploadReceipt
from bisheng.knowledge.application.provider_v1_runtime import (
    ProviderFeatureUnavailable,
    _client_parameters,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderGeneration as Generation,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderInstance as Instance,
)
from bisheng.knowledge.infrastructure.providers.registry import PortContext

_UPLOAD_TIMEOUT = 120.0
_UNLIMITED = 2**62 - 1
_RECEIPT_TOKEN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _unseal_upload_secret(ref: str | None) -> str | None:
    return unseal_external_token_secret(ref)


async def _byte_budgets(tenant_id: int, user_id: int) -> tuple[int, int] | None:
    from bisheng.role.domain.services.quota_service import QuotaService

    login = SimpleNamespace(user_id=user_id, tenant_id=tenant_id, is_admin=lambda: False)
    try:
        user_limit = await QuotaService.get_knowledge_space_upload_limit_bytes(login)
    except Exception:
        return None
    if user_limit is None:
        user_limit = _UNLIMITED
    if type(user_limit) is not int or user_limit <= 0:
        return None
    try:
        used = await QuotaService.get_tenant_storage_used_bytes(tenant_id)
        remaining = await QuotaService.get_tenant_storage_remaining_bytes(tenant_id)
    except Exception:
        return None
    if remaining is None:
        tenant_limit = _UNLIMITED
    else:
        if type(used) is not int or type(remaining) is not int or used < 0 or remaining < 0:
            return None
        tenant_limit = used + remaining
    if tenant_limit <= 0:
        return None
    return user_limit, tenant_limit


async def _instance_upload_binding(route):
    try:
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
                        Instance.provider_key == "weknora",
                        Instance.remote_scope_id == route.remote_scope_id,
                        Instance.tenant_id == route.tenant_id,
                        Instance.state == "ready",
                    )
                )
            ).one_or_none()
    except Exception:
        # Missing tenant context / DB / column: admission stays unverified.
        return None
    if not row:
        return None
    secret = _unseal_upload_secret(row.upload_credential_ref)
    if secret is None:
        return None
    return row.endpoint, row.credential_ref, secret


async def _instance_http_params(route):
    binding = await _instance_upload_binding(route)
    if binding is None:
        raise ProviderFeatureUnavailable()
    endpoint, credential_ref, _ = binding
    return _client_parameters(
        endpoint,
        credential_ref,
        tenant_id=route.tenant_id,
        instance_id=route.instance_id,
        scope=route.remote_scope_id,
    )


@dataclass(frozen=True, slots=True)
class WeKnoraUploadPort:
    context: PortContext
    capability_revision: int
    user_id: int
    hmac_secret: str
    timeout_seconds: float

    def validate_upload(self, options):
        # Chunking already validated by the ledger path; WeKnora applies its own presets.
        return None

    def _token(self, identity) -> str:
        scope = identity.remote_scope_id
        if not scope.isdigit():
            raise ProviderFeatureUnavailable()
        return mint_external_user_token(
            secret=self.hmac_secret,
            weknora_tenant_id=int(scope),
            external_user_id=str(self.user_id),
        )

    def _document_key(self, identity) -> str:
        key = str(identity.document_id)
        if not _RECEIPT_TOKEN.fullmatch(key) or not _RECEIPT_TOKEN.fullmatch(identity.request_key):
            raise ProviderFeatureUnavailable()
        if type(identity.version_id) is not int or identity.version_id < 1:
            raise ProviderFeatureUnavailable()
        return key

    async def _client(self, identity):
        params = await _instance_http_params(self.context)
        headers = dict(params["headers"])
        headers["X-External-User-Token"] = self._token(identity)
        return httpx.AsyncClient(
            base_url=params["base_url"],
            headers=headers,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(self.timeout_seconds, connect=min(10.0, self.timeout_seconds)),
        )

    async def _filename(self, identity) -> str:
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

        async with get_async_db_session() as session:
            name = await session.scalar(
                select(KnowledgeFile.file_name).where(
                    KnowledgeFile.id == identity.file_id,
                    KnowledgeFile.tenant_id == identity.tenant_id,
                    KnowledgeFile.knowledge_id == identity.space_id,
                )
            )
        if isinstance(name, str) and name.strip() and "/" not in name and "\\" not in name:
            return name.strip()[:200]
        return f"upload-{identity.document_id}"

    async def _folder_path(self, identity) -> str:
        """Ancestor DIR names as a WeKnora path-type folder path.

        WeKnora has no document-folder entity: each knowledge row carries a
        ``folder_path`` derived from a path-qualified upload ``fileName``
        (``types.SplitKnowledgeRelativePath``). Local DIR rows stay
        authoritative; mirroring their names keeps both trees in step.
        """
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

        async with get_async_db_session() as session:
            path = (
                await session.execute(
                    select(KnowledgeFile.file_level_path).where(
                        KnowledgeFile.id == identity.file_id,
                        KnowledgeFile.tenant_id == identity.tenant_id,
                        KnowledgeFile.knowledge_id == identity.space_id,
                    )
                )
            ).scalar()
            ids = [int(part) for part in (path or "").split("/") if part.isdigit()]
            if not ids:
                return ""
            ancestors = (
                await session.execute(
                    select(KnowledgeFile.id, KnowledgeFile.file_name).where(
                        KnowledgeFile.id.in_(ids),
                        KnowledgeFile.tenant_id == identity.tenant_id,
                        KnowledgeFile.knowledge_id == identity.space_id,
                        KnowledgeFile.file_type == 0,
                    )
                )
            ).all()
        names = {row.id: row.file_name for row in ancestors}
        segments = [names.get(ident) for ident in ids]
        if not all(
            isinstance(name, str) and name.strip() and "/" not in name and "\\" not in name for name in segments
        ):
            # A broken ancestor chain must not invent a remote directory.
            return ""
        return "/".join(name.strip() for name in segments)

    async def send(self, *, identity, chunks, chunking):
        document_key = self._document_key(identity)
        body = bytearray()
        async for part in chunks:
            if not isinstance(part, bytes):
                raise TypeError("upload chunk must be bytes")
            body.extend(part)
        if len(body) != identity.byte_count:
            raise ProviderFeatureUnavailable()
        filename = await self._filename(identity)
        folder_path = await self._folder_path(identity)
        data = {
            "request_key": identity.request_key,
            "document_key": document_key,
            "version": str(identity.version_id),
        }
        if folder_path:
            # WeKnora splits `fileName` into folder_path + display name.
            data["fileName"] = f"{folder_path}/{filename}"
        if chunking and "chunk_size" in chunking:
            data["process_config"] = json.dumps(
                {"chunk_size": chunking["chunk_size"], "chunk_overlap": chunking.get("chunk_overlap", 0)}
            )
        files = {"file": (filename, bytes(body), "application/octet-stream")}
        async with await self._client(identity) as client:
            response = await client.post(
                f"knowledge-bases/{identity.remote_kb_id}/knowledge/file", data=data, files=files
            )
        return self._parse_receipt(identity, response, require_body=True)

    async def lookup(self, *, identity):
        document_key = self._document_key(identity)
        async with await self._client(identity) as client:
            response = await client.get(
                f"knowledge-bases/{identity.remote_kb_id}/receipt",
                params={
                    "request_key": identity.request_key,
                    "document_key": document_key,
                    "version": identity.version_id,
                },
            )
        if response.status_code == 404:
            # A plain miss is not fenced not_received proof for this attempt.
            return None
        return self._parse_receipt(identity, response, require_body=False)

    @staticmethod
    def _parse_receipt(identity, response, *, require_body: bool):
        # 200/201 create; 409 duplicate still returns the existing Knowledge body.
        if response.status_code not in (200, 201, 409):
            if require_body:
                raise TimeoutError("weknora upload incomplete")
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or payload.get("success") is not True:
            return None
        # Managed receipt protocol (request_key echo). Prefer it when present.
        remote_id = data.get("knowledge_id")
        state = data.get("state")
        if (
            state == "accepted"
            and isinstance(remote_id, str)
            and 0 < len(remote_id.encode()) <= 255
            and data.get("request_key") == identity.request_key
            and data.get("document_key") == str(identity.document_id)
            and data.get("version") == identity.version_id
        ):
            return UploadReceipt(identity, "accepted", remote_id)
        # Stock WeKnora create/duplicate envelope: {"success":true,"data":{Knowledge}}.
        # Deployed WeKnora ignores request_key fields and has no /receipt route.
        remote_id = remote_id if isinstance(remote_id, str) else data.get("id")
        kb = data.get("knowledge_base_id")
        size = data.get("file_size")
        if (
            isinstance(remote_id, str)
            and 0 < len(remote_id.encode()) <= 255
            and (kb is None or kb == identity.remote_kb_id)
            and (size is None or size == identity.byte_count)
        ):
            return UploadReceipt(identity, "accepted", remote_id)
        return None


async def resolve_weknora_upload(route, user_id):
    from bisheng.knowledge.application.provider_upload_v1 import UploadAdmission

    if type(user_id) is not int or user_id <= 0:
        return None
    binding = await _instance_upload_binding(route)
    if binding is None:
        return None
    _, _, secret = binding
    budgets = await _byte_budgets(route.tenant_id, user_id)
    if budgets is None:
        return None
    user_limit, tenant_limit = budgets
    context = PortContext(
        tenant_id=route.tenant_id,
        space_id=route.space_id,
        provider_key="weknora",
        operation="upload",
        instance_id=route.instance_id,
        generation=route.generation,
        remote_scope_id=route.remote_scope_id,
        remote_kb_id=route.remote_kb_id,
    )
    port = WeKnoraUploadPort(
        context=context,
        capability_revision=route.capability_revision,
        user_id=user_id,
        hmac_secret=secret,
        timeout_seconds=_UPLOAD_TIMEOUT,
    )
    return UploadAdmission(port, user_limit, tenant_limit)
