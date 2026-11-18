"""F004 T055: preview / download link of a file of the conversation's current run (AC-24, AC-28).

A ``file`` event tells the client that ``output/<name>`` of the conversation
workspace is stored. Until the run ends, no message row carries that file, so
the attachment endpoint of F016 (``/chat/{chat_id}/files/{file_id}/url``) cannot
sign it yet. This module signs it from the run's accumulated state in Redis.

Rules:

* the caller has already proven that the login user owns the conversation;
* the object key is never taken from the caller: ``file_id`` is looked up in the
  ``files`` of the Redis snapshot, and only a path under ``output/`` of
  ``workspace/{conversation_id}`` is signed;
* nothing is stored: the link is signed on each request (AC-27);
* a file that is no longer in the snapshot (the run ended and the snapshot
  expired, or a newer run replaced it) is answered from the message rows by the
  F016 resolver. An auditor uses the F016 audit endpoint, which reads the rows.

Two ids exist for a generated file (design §7 item 11):

* the id of its ``file`` events = the id of the workspace object. It is signed
  from the snapshot and gives the file as the workspace has it NOW;
* the ``file_id`` on the answer row = the id of that answer's own copy
  (``chat/{partition}/answers/{run_id}/...``). It is signed from the rows and
  gives the file as it was when that answer was written.

A client that still holds the event id after the snapshot is gone gets the copy
of the newest answer that produced the file (the row item keeps the event id in
``workspace_file_id``).
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from bisheng.common.errcode.http_error import NotFoundError
from bisheng.core.storage.chat_attachment import WORKSPACE_FILE_ID_KEY
from bisheng.linsight.domain.services import file_events
from bisheng.linsight.domain.services.run_event_stream import RunEventStream
from bisheng.linsight.domain.services.workspace_backend import workspace_prefix_for


async def _default_minio() -> Any:
    from bisheng.core.storage.minio.minio_manager import get_minio_storage

    return await get_minio_storage()


def live_file_object_key(conversation_id: str, snapshot: dict | None, file_id: str) -> str | None:
    """Object key of ``file_id`` among the current run's files, or None."""
    for item in reversed((snapshot or {}).get("files") or []):
        if not isinstance(item, dict) or str(item.get("file_id")) != str(file_id):
            continue
        path = str(item.get("path") or "")
        if not file_events.is_deliverable_path(path):
            # A deep-research result (``linsight/final_result/...``) is served by
            # the deep-research download endpoint, not from here.
            return None
        return file_events.workspace_object_key(workspace_prefix_for(conversation_id), path)
    return None


async def resolve_run_file_url(
    conversation_id: str,
    file_id: str,
    login_user: Any,
    *,
    stream: RunEventStream | None = None,
    minio: Any = None,
) -> str:
    """A fresh link to one file of the conversation. The caller checked ownership."""
    snapshot = await (stream or RunEventStream()).snapshot(conversation_id)
    key = live_file_object_key(conversation_id, snapshot, file_id)
    if key is None:
        from bisheng.chat_session.domain.chat import ChatSessionService

        # Not a file of the current run: the stored rows decide (and re-check the owner).
        return await ChatSessionService.resolve_attachment_url(
            conversation_id, file_id, login_user, alias_key=WORKSPACE_FILE_ID_KEY
        )
    client = minio if minio is not None else await _default_minio()
    if not await client.object_exists(object_name=key):
        logger.warning("run file {} of conversation {} is announced but not stored: {}", file_id, conversation_id, key)
        raise NotFoundError.http_exception()
    return await client.get_share_link(key)
