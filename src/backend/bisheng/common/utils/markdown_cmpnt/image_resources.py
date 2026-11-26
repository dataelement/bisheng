"""Read untrusted Markdown images without ambient file/network authority.

Owned workspace/object-storage images must be resolved by the authorized caller
and inlined as data URIs before conversion; URLs never imply SDK authorization.
"""

import base64
import binascii

from loguru import logger

from bisheng.core.external.safe_download import BoundedDownload, public_stream

MAX_IMAGE_BYTES = 10 * 1024 * 1024


def image_bytes(source: str) -> bytes:
    """Allow bounded inline images or public-only DNS-pinned HTTP(S) resources."""
    if not isinstance(source, str) or not source:
        raise ValueError("Markdown image has no supported source")
    if source.startswith("data:"):
        if len(source) > (MAX_IMAGE_BYTES * 4 // 3) + 1024:
            raise ValueError("Markdown image exceeds size limit")
        header, separator, payload = source.partition(",")
        if not separator or not header.lower().startswith("data:image/") or not header.lower().endswith(";base64"):
            raise ValueError("Markdown image requires an image data URI")
        try:
            result = base64.b64decode(payload, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("Markdown image data is invalid") from None
        if len(result) > MAX_IMAGE_BYTES:
            raise ValueError("Markdown image exceeds size limit")
        return result
    # The shared fetcher rejects non-HTTP schemes, local paths, private/mixed DNS,
    # redirects to private destinations, userinfo and unverifiable connected peers.
    with public_stream(source) as response:
        response.raise_for_status()
        return b"".join(BoundedDownload(response, MAX_IMAGE_BYTES).iter_content(65536))


def route_export_resource(route):
    """Fulfill Chromium resources through the same policy, never browser egress."""
    resource_type = route.request.resource_type
    # PDF's own data images are local to the document. Only the exact server
    # template's MathJax script is allowed; no user-supplied active resources.
    trusted_mathjax = (
        resource_type == "script" and route.request.url == "https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"
    )
    if resource_type != "image" and not trusted_mathjax:
        route.abort()
        return
    try:
        content = image_bytes(route.request.url)
    except Exception:
        # Optional pictures may be absent; never disclose URL/response details.
        logger.warning("[md2pdf] resource skipped: unavailable or rejected")
        route.abort()
        return
    route.fulfill(
        status=200,
        body=content,
        headers={"Content-Type": "application/javascript" if trusted_mathjax else "application/octet-stream"},
    )
