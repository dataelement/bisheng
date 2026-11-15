"""One-shot Desktop launch into a first-party isolated hosted-app view."""

import re
from urllib.parse import parse_qs, urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from app_proxy.authz import is_valid_slug
from app_proxy.clients import InternalRpcError, get_backend_client
from app_proxy.config import get_config
from app_proxy.routing import entry_prefix_for


async def handle_desktop_launch(request: Request):
    slug = request.path_params["slug"]
    if not is_valid_slug(slug):
        return JSONResponse({"error": "invalid_launch"}, status_code=400)
    # Bound the streaming body as well as Content-Length; do not log tickets.
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 256:
            return JSONResponse({"error": "invalid_launch"}, status_code=400)
    try:
        body = parse_qs(raw.decode("ascii"), strict_parsing=True)
        ticket, = body["ticket"]
        if set(body) != {"ticket"} or not re.fullmatch(r"[A-Za-z0-9_-]{43}", ticket):
            raise ValueError()
    except (ValueError, KeyError, UnicodeError):
        return JSONResponse({"error": "invalid_launch"}, status_code=400)
    try:
        payload = await get_backend_client().redeem_desktop(slug=slug, ticket=ticket)
    except InternalRpcError:
        return JSONResponse({"error": "launch_expired"}, status_code=401)
    target = entry_prefix_for(slug, get_config().entry_prefix) + "/"
    headers = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "Vary": "Accept"}
    # Desktop renews the scoped cookie without navigating or reloading business
    # inputs. Keep the form-post redirect for existing browser clients.
    response = (Response(status_code=204, headers=headers)
                if request.headers.get("accept") == "application/json"
                else RedirectResponse(target, status_code=303, headers=headers))
    public = str(getattr(get_config(), "entry_base_url", "") or "")
    response.set_cookie("bisheng_app_session_" + slug, payload["session"], max_age=3600,
                        httponly=True, secure=urlsplit(public).scheme == "https" or request.url.scheme == "https",
                        samesite="strict", path=target)
    return response
