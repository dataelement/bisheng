"""Caller-bound object refresh for workstation attachments."""

import json
from urllib.parse import unquote

from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.storage.browser_object_path import parse_browser_object_reference
from bisheng.knowledge.domain.services.preview_source_service import PreviewSourceService
from bisheng.workstation.domain.repositories.object_download_repository import ObjectDownloadRepository


def canonical_object_key(value: str) -> str:
    decoded = unquote(value)
    while decoded != unquote(decoded):
        decoded = unquote(decoded)
    if not decoded or "\\" in decoded or "\x00" in decoded or any(p in {"", ".", ".."} for p in decoded.split("/")):
        raise UnAuthorizedError()
    return decoded


class ObjectDownloadService:
    @classmethod
    async def require_owned(cls, bucket: str, key: str, login_user, storage) -> None:
        key = canonical_object_key(key)
        if await PreviewSourceService.is_owned_object(bucket=bucket, object_name=key, login_user=login_user):
            return
        # Legacy permanent chat attachments have server-created user partitions.
        # The prefix alone is insufficient: require a durable personal-session
        # attachment reference in the exact tenant as well.
        tenant_id = get_current_tenant_id() or login_user.tenant_id
        if bucket != storage.bucket or not key.startswith(
            (f"chat/{login_user.user_id}/", f"chat/{tenant_id}/{login_user.user_id}/workflow/")
        ):
            raise UnAuthorizedError()
        subject = SessionSubject.natural_person(tenant_id=tenant_id, user_id=login_user.user_id)
        rows = await ObjectDownloadRepository.owned_attachment_rows(subject)
        for row in rows:
            if row.user_id != login_user.user_id or row.tenant_id != tenant_id:
                continue
            try:
                files = json.loads(row.files or "[]")
            except (ValueError, TypeError):
                continue
            for item in files if isinstance(files, list) else []:
                if not isinstance(item, dict):
                    continue
                assets = [item, *(item.get("derived_assets") or [])]
                for asset in assets:
                    if not isinstance(asset, dict):
                        continue
                    if asset.get("object_name") == key:
                        return
                    reference = asset.get("filepath") or asset.get("file_path") or asset.get("file_url")
                    parsed = parse_browser_object_reference(reference or "", storage.bucket, storage.tmp_bucket)
                    if parsed is not None and parsed[0] == bucket and canonical_object_key(parsed[1]) == key:
                        return
        raise UnAuthorizedError()
