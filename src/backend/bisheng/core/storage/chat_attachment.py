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

from bisheng.core.storage.minio.minio_manager import get_minio_storage

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


async def promote_chat_attachments(files: list[dict] | None, user_id: int | str) -> list[dict]:
    """Move a message's attachments out of the temp bucket, in place.

    Called when the message is sent, not when the file is uploaded: whatever is
    never sent stays in temp and is reclaimed by that bucket's 3-day rule, so
    abandoned uploads cost nothing and need no separate sweeper.

    Each promoted file gains an `object_name` pointing at the permanent copy —
    that field is what later resolves a fresh link and what conversation
    deletion removes. A file that already has one is left alone (task-mode
    uploads land in the main bucket to begin with).

    One attachment failing must not cost the others or the message itself, so
    failures are logged and that file is simply left without `object_name`.
    """
    if not files:
        return []

    minio_client = await get_minio_storage()
    for file in files:
        if not isinstance(file, dict) or file.get("object_name"):
            continue
        source_object = temp_object_name_from_url(
            file.get("filepath") or file.get("file_path") or "", minio_client.tmp_bucket
        )
        if not source_object:
            continue
        dest_object = build_chat_object_name(user_id, file.get("filename") or file.get("file_name") or "")
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
