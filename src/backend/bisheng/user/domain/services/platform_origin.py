"""Resolve browser origins only from explicit configuration or trusted proxies."""

from ipaddress import ip_address, ip_network
from urllib.parse import urlsplit

from bisheng.common.errcode.platform_auth import PlatformAuthError


def public_origin(request):
    conf = getattr(request.app.state, "platform_auth_settings", None)
    if conf is None:
        from bisheng.common.services.config_service import settings

        conf = settings.platform_auth
        configured = conf.public_origin or settings.bs_client.platform_public_url
    else:
        configured = conf.public_origin
    if configured:
        return configured.rstrip("/")
    peer = request.client.host if request.client else ""
    trusted = False
    for entry in conf.trusted_proxy_hosts:
        try:
            trusted = trusted or ip_address(peer) in ip_network(entry, strict=False)
        except ValueError:
            trusted = trusted or peer == entry
    scheme, host = request.url.scheme, request.headers.get("host", request.url.netloc)
    if trusted:
        scheme = request.headers.get("x-forwarded-proto", scheme).split(",")[0].strip()
        host = request.headers.get("x-forwarded-host", host).split(",")[0].strip()
    candidate = f"{scheme}://{host}"
    parsed = urlsplit(candidate)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
        or any(c in host for c in "\\\r\n ")
    ):
        raise PlatformAuthError("invalid_auth_request")
    return candidate
