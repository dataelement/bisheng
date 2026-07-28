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
from uuid import uuid4

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
