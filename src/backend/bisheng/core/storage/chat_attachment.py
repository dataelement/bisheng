"""Object naming for files a user uploads inside a conversation.

Attachments live in the main bucket, grouped by uploader. They are NOT grouped
by conversation: the first upload of a new chat happens before the chat exists
(the client still holds "new" and the backend assigns the id when the message
is sent), so a conversation id simply isn't available at naming time. Deleting
a conversation therefore collects object names from its messages rather than
sweeping a prefix -- the message already carries them.

The stored name is a uuid: the original filename is display metadata on the
message, never an identity -- two users uploading "1.png" must not collide.
"""

import os
from urllib.parse import unquote, urlparse
from uuid import uuid4

from loguru import logger

from bisheng.core.storage.minio.minio_manager import get_minio_storage, get_minio_storage_sync

CHAT_OBJECT_PREFIX = "chat/"

# Long enough for real-world suffixes (".jpeg", ".docx"), short enough that a
# dotted filename can't smuggle half its name into the object key.
_MAX_EXT_LEN = 10


def chat_object_prefix(user_id: int | str) -> str:
    """Prefix holding one user's conversation attachments."""
    return f"{CHAT_OBJECT_PREFIX}{user_id}/"


def _safe_extension(filename: str) -> str:
    """Extension of `filename`, or "" when it doesn't have a usable one.

    The filename comes from the client, so only the suffix is ever read from
    it -- never the stem, and never anything that could steer the object
    elsewhere in the bucket.
    """
    if not filename:
        return ""
    # Strip any directory part the client may have sent (POSIX and Windows).
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    ext = os.path.splitext(base)[1].lower()
    # splitext treats ".gitignore" as all-stem, but be explicit: a leading dot
    # is a hidden file, not an extension.
    if len(ext) > _MAX_EXT_LEN or not ext[1:].isalnum():
        return ""
    return ext


def build_chat_object_name(user_id: int | str, filename: str) -> str:
    """Storage object name for one conversation attachment."""
    return f"{chat_object_prefix(user_id)}{uuid4().hex}{_safe_extension(filename)}"


def temp_object_name_from_url(file_url: str, tmp_bucket: str) -> str | None:
    """Object name inside the temp bucket, read back off the link we issued.

    Uploads answer with a presigned link (`[host]/<bucket>/<object>?…`), and the
    client hands that same link back on the message, so the object name is
    recoverable without asking the upload endpoints to return anything new.
    Returns None when the link doesn't point into the temp bucket -- the file is
    then either already permanent or not ours to move.
    """
    if not file_url:
        return None
    path = urlparse(file_url).path
    marker = f"/{tmp_bucket}/"
    idx = path.find(marker)
    if idx == -1:
        return None
    return unquote(path[idx + len(marker) :]) or None


def _plan_promotions(files: list[dict], user_id: int | str, tmp_bucket: str) -> list[tuple[dict, str, str]]:
    """Work out which attachments still need moving: (file, source, dest)."""
    plan = []
    for file in files:
        if not isinstance(file, dict) or file.get("object_name"):
            # Already permanent — task-mode uploads land in the main bucket.
            continue
        source_object = temp_object_name_from_url(file.get("filepath") or file.get("file_path") or "", tmp_bucket)
        if not source_object:
            continue
        dest_object = build_chat_object_name(user_id, file.get("filename") or file.get("file_name") or "")
        plan.append((file, source_object, dest_object))
    return plan


async def promote_chat_attachments(files: list[dict] | None, user_id: int | str) -> list[dict]:
    """Move a message's attachments out of the temp bucket, in place.

    Called when the message is sent, not when the file is uploaded: whatever is
    never sent stays in temp and is reclaimed by that bucket's 3-day rule, so
    abandoned uploads cost nothing and need no separate sweeper.

    Each promoted file gains an `object_name` pointing at the permanent copy —
    that field is what later resolves a fresh link and what conversation
    deletion removes.

    One attachment failing must not cost the others or the message itself, so
    failures are logged and that file is simply left without `object_name`.
    """
    if not files:
        return []

    try:
        minio_client = await get_minio_storage()
    except Exception:
        # Best-effort by design: an attachment that can't be made permanent is
        # worth a broken thumbnail, not a message the user can't send.
        logger.exception("cannot reach object storage to promote chat attachments for user {}", user_id)
        return files

    for file, source_object, dest_object in _plan_promotions(files, user_id, minio_client.tmp_bucket):
        try:
            await minio_client.copy_object(
                source_bucket=minio_client.tmp_bucket,
                source_object=source_object,
                dest_bucket=minio_client.bucket,
                dest_object=dest_object,
            )
        except Exception:
            logger.exception("failed to promote chat attachment {} for user {}", source_object, user_id)
            continue
        file["object_name"] = dest_object
    return files


def promote_chat_attachments_sync(files: list[dict] | None, user_id: int | str) -> list[dict]:
    """Sync twin of `promote_chat_attachments`, for the Celery worker path."""
    if not files:
        return []

    try:
        minio_client = get_minio_storage_sync()
    except Exception:
        # Same reasoning as the async twin: never block the message.
        logger.exception("cannot reach object storage to promote chat attachments for user {}", user_id)
        return files

    for file, source_object, dest_object in _plan_promotions(files, user_id, minio_client.tmp_bucket):
        try:
            minio_client.copy_object_sync(
                source_bucket=minio_client.tmp_bucket,
                source_object=source_object,
                dest_bucket=minio_client.bucket,
                dest_object=dest_object,
            )
        except Exception:
            logger.exception("failed to promote chat attachment {} for user {}", source_object, user_id)
            continue
        file["object_name"] = dest_object
    return files
