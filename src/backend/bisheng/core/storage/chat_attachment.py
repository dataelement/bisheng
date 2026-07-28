"""Object naming for files a user uploads inside a conversation.

Conversation attachments live in the main bucket under a per-conversation
prefix, which is what lets deleting a conversation wipe its files in one
prefixed sweep. The stored name is a uuid: the original filename is display
metadata carried on the message, never an identity -- two users uploading
"1.png" must not land on the same object.
"""

import os
from uuid import uuid4

CHAT_OBJECT_PREFIX = "chat/"

# Long enough for real-world suffixes (".jpeg", ".docx"), short enough that a
# dotted filename can't smuggle half its name into the object key.
_MAX_EXT_LEN = 10


def chat_object_prefix(chat_id: str) -> str:
    """Prefix holding every attachment of one conversation."""
    return f"{CHAT_OBJECT_PREFIX}{chat_id}/"


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


def build_chat_object_name(chat_id: str, filename: str) -> str:
    """Storage object name for one attachment of one conversation."""
    return f"{chat_object_prefix(chat_id)}{uuid4().hex}{_safe_extension(filename)}"
