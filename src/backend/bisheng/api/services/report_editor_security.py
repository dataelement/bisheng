"""Authorize editor configurations and bind document-server saves to edit grants."""

import copy
import hashlib
import json
import re
from io import BytesIO
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import jwt
from fastapi import HTTPException
from loguru import logger

from bisheng.api.services import report_template
from bisheng.api.services.report_repository import ReportRepository
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.core.external.safe_download import same_origin
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.core.storage.minio.signed_reference import verify_signed_reference
from bisheng.knowledge.domain.services.preview_source_service import PreviewSourceService
from bisheng.permission.application.business_authorization import check_business_action
from bisheng.permission.application.identity import reset_current_permission_actor, set_current_permission_actor

EDIT_GRANT_TTL = 24 * 3600
_KEY = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
_EDITOR_FIELDS = {
    "width",
    "height",
    "type",
    "documentType",
    "document",
    "editorConfig",
    "events",
    "source_kind",
    "preview_upload_ref",
}


def _public_base() -> str:
    base = settings.open_api.public_base_url
    if not isinstance(base, str) or not base:
        raise HTTPException(503, "Configure open_api.public_base_url for the document server")
    parsed = urlsplit(base)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or "\\" in base
        or any(c.isspace() or ord(c) < 32 for c in base)
        or any(p in {".", ".."} for p in parsed.path.split("/"))
    ):
        raise HTTPException(503, "Invalid configured document callback base")
    return base.rstrip("/")


def _grant_key(key: str) -> str:
    return "report:editor:grant:" + hashlib.sha256(key.encode()).hexdigest()


def verify_callback(data: dict, secret: str, authorization: str | None = None) -> dict | None:
    """OnlyOffice outbox token must sign this exact body, not an editor config.

    Support the documented body token and Authorization Bearer token with a
    nested payload. JWT timestamps are metadata; every callback field is bound.
    """
    if not isinstance(secret, str) or not secret or not isinstance(data, dict):
        return None
    token = data.get("token")
    if authorization:
        scheme, _, header_token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not header_token or (token and token != header_token):
            return None
        token = header_token
    if not isinstance(token, str) or len(token) > 65536:
        return None
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"], options={"verify_aud": False})
        payload = claims.get("payload", claims)
        if not isinstance(payload, dict) or "document" in payload or "editorConfig" in payload:
            return None
        body = {key: value for key, value in data.items() if key != "token"}
        signed_body = {key: value for key, value in payload.items() if key not in {"iat", "exp", "nbf"}}
        if json.dumps(body, sort_keys=True) != json.dumps(signed_body, sort_keys=True):
            return None
        if (
            type(body.get("status")) is not int  # noqa: E721  # exact type, bool must not pass as int
            or not isinstance(body.get("key"), str)
            or not _KEY.fullmatch(body["key"])
        ):
            return None
        if body["status"] in {2, 6} and not isinstance(body.get("url"), str):
            return None
        return body
    except (jwt.PyJWTError, ValueError, TypeError):
        return None


def _validate_editor_shape(payload: dict) -> tuple[str, str, str]:
    if not isinstance(payload, dict) or set(payload) - _EDITOR_FIELDS:
        raise HTTPException(400, "Only an authorized editor configuration can be signed")
    document, editor = payload.get("document"), payload.get("editorConfig")
    if not isinstance(document, dict) or not isinstance(editor, dict) or payload.get("documentType") != "word":
        raise HTTPException(400, "Invalid document editor configuration")
    key, url = document.get("key"), document.get("url")
    if (
        not isinstance(key, str)
        or not _KEY.fullmatch(key)
        or not isinstance(url, str)
        or document.get("fileType") != "docx"
    ):
        raise HTTPException(400, "Invalid document editor configuration")
    callback_url = editor.get("callbackUrl")
    try:
        callback = urlsplit(callback_url)
        if (
            callback.scheme not in {"http", "https"}
            or not callback.hostname
            or callback.username
            or callback.password
            or callback.query
            or callback.fragment
        ):
            raise ValueError()
        _ = callback.port
    except (TypeError, ValueError):
        raise HTTPException(400, "Invalid document callback URL") from None
    base = _public_base()
    prefix = urlsplit(base).path.rstrip("/")
    routes = {"/api/v1/report/callback", "/api/v1/workflow/report/callback"}
    route = callback.path[len(prefix) :] if prefix and callback.path.startswith(prefix + "/") else callback.path
    if route not in routes or callback.path not in {route, prefix + route}:
        raise HTTPException(400, "Invalid document callback URL")
    return key, url, route


async def _check_document_url(url: str, object_name: str | None) -> None:
    if not url:
        if object_name:
            raise HTTPException(400, "Document URL does not match report")
        return
    minio = await get_minio_storage()
    expected = f"/{minio.bucket}/{object_name}" if object_name else None
    if (
        expected is None
        or not same_origin(url, minio.get_minio_share_host())
        or unquote(urlsplit(url).path) != expected
    ):
        raise HTTPException(400, "Document URL does not match report")


async def _canonical_source(payload: dict, login_user, object_name: str | None) -> tuple[str, str]:
    source_kind = payload.get("source_kind")
    upload_ref = payload.get("preview_upload_ref")
    url = payload["document"]["url"]
    if source_kind not in {None, "empty"} or (source_kind and upload_ref):
        raise HTTPException(400, "Invalid document source")
    minio = await get_minio_storage()
    if source_kind == "empty" or (not url and object_name is None and not upload_ref):
        if url:
            raise HTTPException(400, "Empty document cannot carry a source URL")
        from docx import Document

        output = BytesIO()
        document = Document()
        document.add_paragraph("")
        document.save(output)
        key = f"office/empty/{login_user.tenant_id}/{login_user.user_id}/{uuid4().hex}.docx"
        await minio.put_object(
            bucket_name=minio.tmp_bucket,
            object_name=key,
            file=output.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        return await minio.get_share_link(key, minio.tmp_bucket, clear_host=False), "docx"
    if upload_ref:
        if not isinstance(upload_ref, str) or not url:
            raise HTTPException(400, "Invalid document upload reference")
        item = SimpleNamespace(preview_upload_ref=upload_ref, preview_file_id=None, file_path=url)
        source = await PreviewSourceService.resolve(item=item, login_user=login_user, knowledge_id=0)
        try:
            signed = verify_signed_reference(url, minio)
        except (ValueError, TypeError):
            raise HTTPException(400, "Invalid signed document source") from None
        if (
            (signed.bucket, signed.object_name) != (source.bucket, source.object_name)
            or source.bucket != minio.tmp_bucket
            or not await PreviewSourceService.is_owned_object(
                bucket=source.bucket, object_name=source.object_name, login_user=login_user
            )
        ):
            raise HTTPException(403, "Document upload ownership is not valid")
        suffix = source.file_name.rsplit(".", 1)[-1].lower()
        if suffix not in {"doc", "docx"}:
            raise HTTPException(400, "Only Word documents can be imported")
        return await minio.get_share_link(source.object_name, source.bucket, clear_host=False), suffix
    await _check_document_url(url, object_name)
    return await minio.get_share_link(object_name, minio.bucket, clear_host=False), "docx"


async def authorize_editor(payload: dict, login_user) -> dict:
    key, url, callback_path = _validate_editor_shape(payload)
    tenant_id = login_user.tenant_id
    if type(tenant_id) is not int or tenant_id <= 0:  # noqa: E721  # exact type, bool must not pass as int
        raise HTTPException(403, "Report editor access denied")
    with tenant_execution_scope(tenant_id):
        if callback_path == "/api/v1/report/callback":
            row = ReportRepository.find_by_key(key)
            if row is None or row.tenant_id != tenant_id:
                raise HTTPException(403, "Report editor access denied")
            flow_id = row.flow_id
            object_name = row.object_name
        else:
            session = await report_template.aget_edit_session(key)
            flow_id = session.get("workflow_id") if isinstance(session, dict) else None
            if not flow_id or not session.get("can_edit") or report_template.owner_workflow_id(key) != flow_id:
                raise HTTPException(403, "Report editor access denied")
            object_name = f"workflow/report/{report_template.storage_key(key)}.docx" if url else None
        if not await check_business_action(login_user, resource_type="workflow", resource_id=flow_id, action="edit"):
            raise HTTPException(403, "Report editor access denied")
        canonical_url, file_type = await _canonical_source(payload, login_user, object_name)
        config = copy.deepcopy(payload)
        config.pop("source_kind", None)
        config.pop("preview_upload_ref", None)
        config["document"]["url"] = canonical_url
        config["document"]["fileType"] = file_type
        config["editorConfig"]["callbackUrl"] = _public_base() + callback_path
        if callback_path == "/api/v1/report/callback":
            redis = await get_redis_client()
            await redis.aset(
                _grant_key(key),
                {
                    "report_id": row.id,
                    "tenant_id": tenant_id,
                    "flow_id": flow_id,
                    "user_id": login_user.user_id,
                    "key": key,
                },
                expiration=EDIT_GRANT_TTL,
            )
        return config


async def resolve_callback_report(key: str):
    """Read an issued key grant, then re-authorize its exact tenant/parent/user."""
    redis = await get_redis_client()
    grant = await redis.aget(_grant_key(key))
    if not isinstance(grant, dict) or grant.get("key") != key:
        return None
    if any(type(grant.get(field)) is not int or grant[field] <= 0 for field in ("tenant_id", "report_id", "user_id")):  # noqa: E721  # exact type, bool must not pass as int
        return None
    with tenant_execution_scope(grant["tenant_id"]):
        row = ReportRepository.find_by_key(key)
        if row is None or (row.id, row.tenant_id, row.flow_id) != (
            grant["report_id"],
            grant["tenant_id"],
            grant.get("flow_id"),
        ):
            return None
        if not ReportRepository.editor_is_active(grant["user_id"], grant["tenant_id"]):
            return None
        actor = SimpleNamespace(user_id=grant["user_id"], tenant_id=grant["tenant_id"], is_global_super=False)
        # A callback may carry an unrelated browser cookie; never inherit its
        # contextual permission actor instead of the server-issued grant actor.
        token = set_current_permission_actor(None)
        try:
            allowed = await check_business_action(
                actor, resource_type="workflow", resource_id=row.flow_id, action="edit"
            )
        finally:
            reset_current_permission_actor(token)
        if not allowed:
            logger.warning("Report callback denied after editor permission changed")
            return None
        return row
