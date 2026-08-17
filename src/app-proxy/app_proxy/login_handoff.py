"""Sending an unauthenticated visitor to the login page — and getting them back.

Three separate audiences hit the same refusal and each needs a different shape
(D7, "非导航请求分流"):

* a **navigation** gets HTML — for ``login`` specifically, the handoff page
  below;
* a **programmatic request** (XHR / fetch) gets JSON and the true status code.
  Handing an in-app ``fetch()`` a chunk of HTML with a 200 makes it fail while
  parsing, three layers away from the actual cause;
* a **WebSocket upgrade** gets a close code, because that is the only channel
  its client can read.

The handoff page exists because the return address cannot survive a 302: a
fragment never reaches the server, and the platform login page reads the return
target from ``localStorage`` only (坑 11). So the browser — the one party that
can still see the whole address — writes it down before leaving.
"""

from __future__ import annotations

from starlette.requests import HTTPConnection

from app_proxy.authz import (
    DECISION_FORBIDDEN,
    DECISION_LOGIN,
    DECISION_NOT_ENABLED,
    DECISION_NOT_FOUND,
    DECISION_STOPPED,
    DECISION_UNAVAILABLE,
)
from app_proxy.pages import PAGE_RECOVERING

#: Cross-SPA contract with ``platform/src/utils/loginReturnTo.ts``. The consumer
#: is one-shot, same-origin checked and expires the value after 10 minutes; it
#: reads **these two keys and nothing else**. Rename in both places or neither.
LOGIN_PATHNAME_KEY = "LOGIN_PATHNAME"
LOGIN_PATHNAME_AT_KEY = "LOGIN_PATHNAME_AT"

#: WebSocket close codes in the private 4000–4999 range.
#: ``4501`` is deliberately distinct from the refusals: it means "you were
#: allowed, WS proxying just is not built yet" (Wave 4, T079/T080), which is
#: otherwise indistinguishable from a permission problem during 114 testing.
WS_CLOSE_NOT_IMPLEMENTED = 4501
WS_CLOSE_CODES = {
    DECISION_LOGIN: 4401,
    DECISION_FORBIDDEN: 4403,
    DECISION_STOPPED: 4403,
    DECISION_NOT_FOUND: 4404,
    DECISION_NOT_ENABLED: 4503,
    DECISION_UNAVAILABLE: 4503,
    PAGE_RECOVERING: 4503,
}


def is_navigation(connection: HTTPConnection) -> bool:
    """Is this a top-level page load?

    ``Sec-Fetch-*`` is authoritative when present — it is set by the browser and
    cannot be spoofed by page script — and it wins over ``Accept`` because
    ``fetch(url, {headers: {Accept: 'text/html'}})`` is legal and common.
    ``Accept`` is the fallback for browsers that do not send Fetch Metadata
    (which includes the Chromium 108 builds on 信创 desktops).
    """
    mode = connection.headers.get("Sec-Fetch-Mode", "").lower()
    dest = connection.headers.get("Sec-Fetch-Dest", "").lower()
    if mode or dest:
        return mode == "navigate" or dest == "document"
    return "text/html" in connection.headers.get("Accept", "").lower()


def ws_close_code(decision: str) -> int:
    return WS_CLOSE_CODES.get(decision, 4503)


def render_login_handoff(login_path: str = "/admin") -> str:
    """Write the return address down, then go to the login page.

    ``location.href`` is evaluated in the browser on purpose — it is the only
    expression that still contains the fragment. Templating the request URL in
    here would silently drop ``#b`` from a scanned link and the app would open
    blank after login, on parameterised links only.

    The whole thing is wrapped in try/catch: with storage disabled (private
    mode, some 信创 builds) losing the return address is a papercut, but an
    exception before ``location.replace`` leaves a blank page.
    """
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>正在跳转到登录页</title>
<style>
body {{
  margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
  color: #8f959e; background: #f5f6f8;
  font: 14px/1.7 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
        "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
}}
@media (prefers-color-scheme: dark) {{ body {{ background: #1a1a1a; color: #9a9a9a; }} }}
</style>
</head>
<body>
<p>正在跳转到登录页…</p>
<script>
(function () {{
  try {{
    localStorage.setItem('{LOGIN_PATHNAME_KEY}', location.href);
    localStorage.setItem('{LOGIN_PATHNAME_AT_KEY}', String(Date.now()));
  }} catch (err) {{}}
  location.replace('{login_path}');
}})();
</script>
<noscript><a href="{login_path}">请点击此处前往登录页</a></noscript>
</body>
</html>
"""
