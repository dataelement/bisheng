"""Browser-facing object paths.

MinIO still receives ``/{bucket}/{key}``. Browsers use ``/object/{bucket}/{key}``
so the site entrance does not have to name the buckets. Stored text keeps the
old form; callers rewrite it when they hand it to a browser.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_OBJECT_PREFIX = "object"
_WORKSPACE_PREFIX = "workspace"


def browser_bucket_allowed(bucket: str | None, public_bucket: str | None, tmp_bucket: str | None) -> bool:
    """True only for a non-empty name that is the current public or temp bucket."""
    name = (bucket or "").strip()
    if not name:
        return False
    allowed = {(public_bucket or "").strip(), (tmp_bucket or "").strip()}
    allowed.discard("")
    return name in allowed


def browser_object_path(bucket: str, object_key: str, query: str = "") -> str:
    """Return the browser path for one object. ``query`` is without a leading ``?``."""
    key = object_key.lstrip("/")
    path = f"/{_OBJECT_PREFIX}/{bucket}/{key}"
    cleaned = query.lstrip("?")
    if cleaned:
        return f"{path}?{cleaned}"
    return path


def rewrite_current_browser_object_text(text: str | None) -> str | None:
    """Rewrite stored paths using the buckets configured for this process.

    Returns a new string. Callers must not write the result back over the stored text.
    """
    if text is None:
        return None
    from bisheng.common.services.config_service import settings

    conf = settings.get_minio_conf()
    if conf is None:
        return text
    return rewrite_browser_object_text(text, conf.public_bucket or "", conf.tmp_bucket or "")


def rewrite_browser_object_text(text: str, public_bucket: str, tmp_bucket: str) -> str:
    """Prefix stored ``/{bucket}/`` paths that belong to the two current buckets.

    A match has to be a path segment, not a later piece of ``/assets/bisheng/``
    or of an absolute ``http(s)`` URL. An already prefixed ``/object/{bucket}/``
    is left as it is. Text whose bucket is no longer current is left as it is.
    """
    if not text:
        return text
    buckets = sorted({name for name in (public_bucket, tmp_bucket) if name}, key=len, reverse=True)
    rewritten = text
    for bucket in buckets:
        pattern = re.compile(rf"(?<![\w])/(?:{_OBJECT_PREFIX}/)?({re.escape(bucket)})/")
        # The optional object/ group is only so we can see an existing prefix
        # and skip it. Replacing that form would nest the prefix.
        rewritten = pattern.sub(_keep_existing_prefix, rewritten)
        # Markdown sometimes stores "(bucket/key)" without the leading slash.
        # The parenthesis is not consumed, so the replacement only inserts the prefix.
        paren = re.compile(rf"(?<=\()({re.escape(bucket)})/")
        rewritten = paren.sub(rf"/{_OBJECT_PREFIX}/\1/", rewritten)
    return rewritten


def _keep_existing_prefix(match: re.Match[str]) -> str:
    token = match.group(0)
    if token.startswith(f"/{_OBJECT_PREFIX}/"):
        return token
    return f"/{_OBJECT_PREFIX}{token}"


def parse_browser_object_reference(value: str, public_bucket: str, tmp_bucket: str) -> tuple[str, str] | None:
    """Return ``(bucket, key)`` for a current public or temp object reference.

    Accepts ``/{bucket}/{key}``, ``/object/{bucket}/{key}``, and the same paths
    under ``/workspace``. Query strings are not part of the key. Any other
    bucket, including a static ``/assets/...`` path, returns ``None``.
    """
    raw = (value or "").strip()
    if not raw:
        return None
    if "://" in raw:
        path = urlsplit(raw).path
    else:
        path = raw.split("?", 1)[0].split("#", 1)[0]
    if not path.startswith("/"):
        return None
    segments = [segment for segment in path.split("/") if segment]
    if segments and segments[0] == _WORKSPACE_PREFIX:
        segments = segments[1:]
    if segments and segments[0] == _OBJECT_PREFIX:
        segments = segments[1:]
    if len(segments) < 2:
        return None
    bucket, *rest = segments
    allowed = {name for name in (public_bucket, tmp_bucket) if name}
    if bucket not in allowed:
        return None
    key = "/".join(rest)
    if not key:
        return None
    return bucket, key
