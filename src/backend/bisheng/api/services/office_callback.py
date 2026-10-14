"""Download guard for the OnlyOffice save callback.

The document server does not post the edited file. It posts a JSON notice whose
``url`` points at its own download endpoint, and the backend fetches the bytes
from there before storing them. The callback endpoints carry no user session
(the document server has none), so without a check the backend would fetch any
URL a caller names -- internal services, cloud metadata -- and store whatever
came back (issue #2190, GHSA-mh3h-jrgm-pv34).

Only URLs on the configured ``office_url`` origin (scheme + host + port) are
fetched. Redirects are not followed, so an allowed origin cannot bounce the
request elsewhere.
"""

from urllib.parse import urlsplit

import requests
from loguru import logger

from bisheng.common.services.config_service import settings as bisheng_settings
from bisheng_langchain.utils.requests import Requests

_DEFAULT_PORTS = {"http": 80, "https": 443}
# (connect, read). Both are inactivity limits, not a cap on total download time:
# a large template keeps transferring for as long as it needs, and the read
# timeout only fires when the document server goes silent mid-stream. Connect is
# short because the only reachable target is the configured document server.
OFFICE_DOWNLOAD_TIMEOUT_SECONDS = (10, 120)


def _origin(url: object) -> tuple[str, str, int] | None:
    """Return ``(scheme, host, port)`` for an http(s) URL, or None if unusable."""
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parts = urlsplit(url.strip())
        # Accessing .port raises ValueError for a non-numeric or out-of-range port.
        port = parts.port
    except ValueError:
        return None
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower()
    if scheme not in _DEFAULT_PORTS or not host:
        return None
    return scheme, host, port or _DEFAULT_PORTS[scheme]


def is_office_download_url(url: object, office_url: object) -> bool:
    """True only when ``url`` is on the same origin as the configured ``office_url``.

    Hosts are compared after parsing, so ``http://office@evil.example/`` resolves
    to ``evil.example`` and is rejected. An unset ``office_url`` rejects everything.
    """
    target = _origin(url)
    allowed = _origin(office_url)
    return target is not None and allowed is not None and target == allowed


async def aresolve_office_url() -> str:
    """Read the document server address the way the rest of the app does.

    ``office_url`` is served to the browser out of the ``env`` config block; the
    top-level key is only a legacy override.
    """
    office_url = await bisheng_settings.aget_from_db("office_url")
    if not office_url:
        office_url = (await bisheng_settings.aget_from_db("env") or {}).get("office_url")
    return office_url if isinstance(office_url, str) else ""


async def afetch_office_document(file_url: object) -> bytes | None:
    """Download a saved document from the document server, or None if refused.

    Returns None -- and logs why -- when the URL is off the office origin, the
    request fails, or the server does not answer 200. Callers report that back
    to the document server as a failed save instead of storing anything.
    """
    office_url = await aresolve_office_url()
    if not is_office_download_url(file_url, office_url):
        logger.warning(
            "office callback refused: url={!r} is not on the configured office_url origin {!r}",
            file_url,
            office_url,
        )
        return None
    try:
        response = Requests(request_timeout=OFFICE_DOWNLOAD_TIMEOUT_SECONDS).get(
            url=file_url,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        logger.warning("office callback download failed: url={!r} error={}", file_url, type(exc).__name__)
        return None
    if response.status_code != 200:
        logger.warning(
            "office callback download refused: url={!r} status={}",
            file_url,
            response.status_code,
        )
        return None
    return response.content
