"""Who may download a deliverable file (F078 design decision 7, spec AC-28/AC-29/AC-37).

- A formal session's files are chat attachments. ``resolve_attachment_url``
  already checks that the caller owns the conversation and reads the object
  name from the stored message, never from the request.
- A temporary session's files sit in the tmp bucket. Only the user registered
  as the session's owner may fetch them, and only while the registration lives.

The object name is always derived on the server side. The identifiers in the
URL are checked to be path-safe before they are used in any lookup.
"""

from __future__ import annotations

import asyncio
import re

from bisheng.agent_runtime.domain.services.tmp_session import TmpSessionService, tmp_deliverable_dir
from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError

_SAFE = re.compile(r"^[A-Za-z0-9_-]+$")
_TMP_PREFIX = "tmp-"


def _find_tmp_object(minio, tmp_id: str, file_id: str) -> str | None:
    prefix = f"{tmp_deliverable_dir(tmp_id)}/{file_id}"
    for obj in minio.minio_client_sync.list_objects(minio.tmp_bucket, prefix=prefix, recursive=True):
        name = obj.object_name
        # The object is "<file_id><ext>": the next character must start the extension.
        rest = name[len(prefix) :]
        if rest == "" or rest.startswith("."):
            return name
    return None


async def resolve_deliverable_url(session_key: str, file_id: str, login_user, *, minio, tmp_sessions) -> str:
    """Return a short-lived download link, or raise 403/404."""
    if not _SAFE.match(session_key or "") or not _SAFE.match(file_id or ""):
        raise NotFoundError.http_exception()

    if not session_key.startswith(_TMP_PREFIX):
        return await ChatSessionService.resolve_attachment_url(session_key, file_id, login_user)

    tmp_id = session_key[len(_TMP_PREFIX) :]
    if not tmp_id:
        raise NotFoundError.http_exception()
    owner = await tmp_sessions.aowner_of(tmp_id)
    if not owner or int(owner.get("user_id", -1)) != int(login_user.user_id):
        raise UnAuthorizedError.http_exception()
    object_name = await asyncio.to_thread(_find_tmp_object, minio, tmp_id, file_id)
    if object_name is None:
        raise NotFoundError.http_exception()
    return await minio.get_share_link(object_name, bucket=minio.tmp_bucket)


async def aresolve_deliverable_url(session_key: str, file_id: str, login_user) -> str:
    """Production entry point: wires the real MinIO and Redis clients."""
    from bisheng.core.cache.redis_manager import get_redis_client
    from bisheng.core.storage.minio.minio_manager import get_minio_storage

    minio = await get_minio_storage()
    tmp_sessions = TmpSessionService(redis=await get_redis_client(), minio=minio)
    return await resolve_deliverable_url(session_key, file_id, login_user, minio=minio, tmp_sessions=tmp_sessions)
