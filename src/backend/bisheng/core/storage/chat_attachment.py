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

import asyncio
import hashlib
import os
import re
from typing import Any
from urllib.parse import unquote
from uuid import uuid4

from loguru import logger

from bisheng.core.storage.browser_object_path import parse_browser_object_reference
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


# F004 (design §7 item 11): the copies an answer keeps of the files its run wrote.
ANSWER_FILE_DIR = "answers"
# Set on an answer-row file item that points at a copy: the ``file_id`` its
# ``file`` events carried while the run was live (the workspace object's id).
WORKSPACE_FILE_ID_KEY = "workspace_file_id"
_SAFE_KEY_PART = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _key_part(value: str) -> str:
    """``value`` when it is safe inside an object key, else a digest of it."""
    value = str(value or "")
    return value if _SAFE_KEY_PART.fullmatch(value) else hashlib.md5(value.encode("utf-8")).hexdigest()


def build_answer_file_object_name(partition: int | str, run_id: str, file_key: str, filename: str) -> str:
    """Object name of the copy one answer keeps of one generated file.

    ``chat/{partition}/answers/{run_id}/{file_key}{ext}``. One answer row per run,
    so the run id is the answer's directory. The name is a function of its
    inputs: writing the row of the same run again overwrites the same copy.
    """
    return (
        f"{chat_object_prefix(partition)}{ANSWER_FILE_DIR}/{_key_part(run_id)}/"
        f"{_key_part(file_key)}{_safe_extension(filename)}"
    )


def answer_file_id(object_name: str) -> str:
    """Stable ``file_id`` of an answer's copy (differs from the workspace file's id)."""
    return hashlib.md5(object_name.encode("utf-8")).hexdigest()[:16]


async def copy_answer_files(
    files: list[dict] | None, partition: int | str, run_id: str, *, minio_client: Any = None
) -> list[dict]:
    """Give an answer its own copy of each generated file, in place.

    Each item carries ``object_name`` (an object of the main bucket that a later
    run may overwrite, e.g. ``workspace/{conversation}/output/x``). The object is
    copied inside the bucket (a server-side copy) and the item is repointed:
    ``object_name`` = the copy, ``file_id`` = the copy's id, and the id it had
    goes to ``workspace_file_id``.

    A copy that fails is logged and that item is left as it was (it keeps
    pointing at the source object); the other files and the answer row are not
    affected. Returns ``files``.
    """
    if not files:
        return files or []
    if minio_client is None:
        try:
            minio_client = await get_minio_storage()
        except Exception:
            logger.exception(
                "cannot reach object storage to copy the files of run {}; the answer keeps the workspace objects",
                run_id,
            )
            return files

    async def copy_one(item: dict) -> None:
        source = item.get("object_name")
        if not source:
            return
        name = item.get("file_name") or item.get("filename") or ""
        dest = build_answer_file_object_name(partition, run_id, str(item.get("file_id") or source), name)
        try:
            await minio_client.copy_object(
                source_bucket=minio_client.bucket,
                source_object=source,
                dest_bucket=minio_client.bucket,
                dest_object=dest,
            )
        except Exception:
            logger.exception(
                "failed to copy generated file {} of run {} to {}; the answer keeps the workspace object",
                source,
                run_id,
                dest,
            )
            return
        item[WORKSPACE_FILE_ID_KEY] = item.get("file_id")
        item["object_name"] = dest
        item["file_id"] = answer_file_id(dest)

    await asyncio.gather(*(copy_one(item) for item in files if isinstance(item, dict)))
    return files


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
    parsed = parse_browser_object_reference(file_url, "", tmp_bucket)
    if parsed is None:
        return None
    _bucket, key = parsed
    name = unquote(key)
    while name != unquote(name):
        name = unquote(name)
    return name or None


def _plan_promotions(files: list[dict], user_id: int | str, tmp_bucket: str) -> list[tuple[dict, str, str]]:
    """Work out which attachments still need moving: (file, source, dest)."""
    plan = []
    for file in files:
        if not isinstance(file, dict) or file.get("object_name"):
            # Already permanent — task-mode uploads land in the main bucket.
            continue
        # The upload endpoints disagree on the field name for the link they
        # issued -- daily/task say filepath, workflow chat says file_url.
        source_url = file.get("filepath") or file.get("file_path") or file.get("file_url") or ""
        source_object = temp_object_name_from_url(source_url, tmp_bucket)
        if not source_object:
            continue
        dest_object = build_chat_object_name(user_id, file.get("filename") or file.get("file_name") or "")
        plan.append((file, source_object, dest_object))
    return plan


async def promote_chat_attachments(
    files: list[dict] | None,
    user_id: int | str,
    *,
    storage_partition: str | None = None,
) -> list[dict]:
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

    partition = storage_partition or str(user_id)
    for file, source_object, dest_object in _plan_promotions(files, partition, minio_client.tmp_bucket):
        try:
            from bisheng.core.storage.minio.signed_reference import verify_signed_reference

            reference = verify_signed_reference(
                file.get("filepath") or file.get("file_path") or file.get("file_url") or "", minio_client
            )
            if reference.bucket != minio_client.tmp_bucket or reference.version_id:
                raise ValueError("Attachment source does not match its signed reference")
            source_object = reference.object_name
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
            from bisheng.core.storage.minio.signed_reference import verify_signed_reference

            reference = verify_signed_reference(
                file.get("filepath") or file.get("file_path") or file.get("file_url") or "", minio_client
            )
            if reference.bucket != minio_client.tmp_bucket or reference.version_id:
                raise ValueError("Attachment source does not match its signed reference")
            source_object = reference.object_name
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
