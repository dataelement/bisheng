"""The pages a visitor gets when the answer is not "come in" (D7-A′).

app-proxy renders these itself instead of redirecting to a SPA gate route. The
reason is the URL: a bookmark, a QR code and a browser refresh all have to keep
working, and a 302 loses the fragment on the way out and the original address
on the way back. Rendering in place costs a small stylesheet in Python and buys
zero client changes.

**Status codes.** Navigations get **200 + HTML** for every kind, including "not
found". That is not sloppiness: design §7 step 7 asks for
``/apps/__nonexistent__`` to show the "不存在或未上线" page and explicitly *not*
a 404, because a phone scanning a QR code that resolves to a browser error
shell is indistinguishable from "the platform is down". Programmatic callers do
get the true status — see :data:`JSON_STATUS` — because an in-app ``fetch()``
that receives HTML with a 200 will try to parse it and fail in a far more
confusing way.

**Language.** Simplified Chinese only in this wave. The trade was made
knowingly in D7: these pages sit outside ``packages/locales`` and
``pnpm check-i18n`` cannot see them, so the copy lives here and the three-locale
treatment is a follow-up rather than a half-translated table today.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from app_proxy.authz import (
    DECISION_FORBIDDEN,
    DECISION_LOGIN,
    DECISION_NOT_ENABLED,
    DECISION_NOT_FOUND,
    DECISION_STOPPED,
    DECISION_UNAVAILABLE,
)

#: Transitional, not a verdict: the app exists and you may enter, but nothing
#: is answering right now (crash window / version switch). AC-36.
PAGE_RECOVERING = "recovering"

#: Every page renders 200 for navigations. See the module docstring.
PAGE_HTTP_STATUS = 200

#: Real statuses for non-navigation callers.
JSON_STATUS = {
    DECISION_LOGIN: 401,
    DECISION_FORBIDDEN: 403,
    DECISION_STOPPED: 403,
    DECISION_NOT_FOUND: 404,
    DECISION_NOT_ENABLED: 503,
    DECISION_UNAVAILABLE: 503,
    PAGE_RECOVERING: 503,
}

#: Platform error codes (design §4.2 ⑥, section 161). ``recovering`` has no code
#: of its own — 16121 (编排器不可用) is the closest true statement and avoids
#: minting a code the backend has not registered.
ERROR_CODES = {
    DECISION_LOGIN: 16141,
    DECISION_FORBIDDEN: 16142,
    DECISION_STOPPED: 16143,
    DECISION_NOT_FOUND: 16144,
    DECISION_NOT_ENABLED: 16145,
    DECISION_UNAVAILABLE: 16146,
    PAGE_RECOVERING: 16121,
}

_STYLE = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
  padding: 24px; background: #f5f6f8; color: #1f2329;
  font: 14px/1.7 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
        "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
}
.card {
  width: 100%; max-width: 480px; background: #fff; border-radius: 12px; padding: 40px 32px;
  box-shadow: 0 2px 12px rgba(31, 35, 41, .08); text-align: center;
}
.mark { font-size: 40px; line-height: 1; margin-bottom: 16px; }
h1 { font-size: 20px; font-weight: 600; margin: 0 0 12px; }
p { margin: 0 0 8px; color: #646a73; }
.app { color: #1f2329; font-weight: 500; }
.hint { font-size: 13px; color: #8f959e; margin-top: 16px; }
.actions { margin-top: 28px; }
a.button {
  display: inline-block; padding: 8px 20px; border-radius: 6px; text-decoration: none;
  background: #1668dc; color: #fff; font-size: 14px;
}
a.button:hover { background: #1554b5; }
@media (prefers-color-scheme: dark) {
  body { background: #1a1a1a; color: #e5e6eb; }
  .card { background: #242424; box-shadow: none; }
  p { color: #9a9a9a; }
  .app { color: #e5e6eb; }
}
"""


@dataclass(frozen=True)
class _Page:
    mark: str
    title: str
    #: ``{app}`` is substituted with the app name when one is known.
    lines: tuple[str, ...]
    show_square: bool = True


_PAGES: dict[str, _Page] = {
    DECISION_FORBIDDEN: _Page(
        mark="🔒",
        title="无访问权限",
        lines=(
            "你没有访问 {app} 的权限。",
            "如需使用，请联系应用负责人 {owner} 或所在租户的租户管理员开通权限。",
        ),
    ),
    DECISION_STOPPED: _Page(
        mark="⏸",
        title="应用已停用",
        lines=(
            "{app} 已停用，恢复后即可正常访问。",
            "如需恢复，请联系应用负责人 {owner} 或所在租户的租户管理员。",
        ),
    ),
    # Carries neither name nor owner — draft / pending / deleted / never
    # existed must be one indistinguishable page (AC-29).
    DECISION_NOT_FOUND: _Page(
        mark="🔍",
        title="应用不存在或未上线",
        lines=("该链接对应的应用不存在，或尚未上线。", "请确认链接是否正确，或返回广场查看可用的应用。"),
    ),
    DECISION_NOT_ENABLED: _Page(
        mark="🧩",
        title="本环境未启用应用工场",
        lines=("当前环境未部署应用工场运行时层，无法访问托管应用。", "如需启用，请联系平台超管。"),
        show_square=False,
    ),
    DECISION_UNAVAILABLE: _Page(
        mark="⚠️",
        title="暂时无法访问",
        lines=("平台暂时无法确认你的访问权限，请稍后重试。", "若持续出现，请联系平台管理员。"),
        show_square=False,
    ),
    PAGE_RECOVERING: _Page(
        mark="🔄",
        title="应用恢复中",
        lines=("{app} 正在恢复，请稍后刷新页面重试。",),
        show_square=False,
    ),
}


def _fill(line: str, app_name: str | None, owner_name: str | None) -> str:
    """Substitute, and degrade gracefully when a name is unknown.

    "该应用" rather than an empty gap: the not-found page has no name by
    design, and an owner may genuinely be missing after an account is removed.
    """
    return line.format(
        app=html.escape(app_name) if app_name else "该应用",
        owner=html.escape(owner_name) if owner_name else "应用负责人",
    )


def render_page(
    kind: str,
    *,
    app_name: str | None = None,
    owner_name: str | None = None,
    square_url: str = "/workspace",
    request_id: str = "",
) -> str:
    """Full self-contained HTML document. No script, no external request.

    These render when the platform may already be half-broken, so a CDN font or
    a logo fetched over the network is exactly the dependency that turns a
    tidy explanation into a blank page.
    """
    page = _PAGES.get(kind) or _PAGES[DECISION_UNAVAILABLE]
    body = "\n".join(f"    <p>{_fill(line, app_name, owner_name)}</p>" for line in page.lines)

    actions = ""
    if page.show_square:
        actions = f'    <div class="actions"><a class="button" href="{html.escape(square_url)}">返回广场</a></div>'

    hint = ""
    # Only on the two "something broke" pages: a request id printed on the
    # not-found page would make four supposedly identical renders differ, which
    # is exactly the enumeration oracle AC-29 closes.
    if request_id and kind in (DECISION_UNAVAILABLE, PAGE_RECOVERING):
        hint = f'    <p class="hint">请求编号：{html.escape(request_id)}</p>'

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{html.escape(page.title)}</title>
<style>{_STYLE}</style>
</head>
<body>
  <div class="card">
    <div class="mark">{page.mark}</div>
    <h1>{html.escape(page.title)}</h1>
{body}
{actions}
{hint}
  </div>
</body>
</html>
"""


def error_payload(kind: str, request_id: str = "") -> dict:
    """JSON body for non-navigation callers, shaped like the platform envelope."""
    page = _PAGES.get(kind) or _PAGES[DECISION_UNAVAILABLE]
    return {
        "status_code": ERROR_CODES.get(kind, ERROR_CODES[DECISION_UNAVAILABLE]),
        "status_message": page.title,
        "decision": kind,
        "request_id": request_id,
    }


def json_status(kind: str) -> int:
    return JSON_STATUS.get(kind, 503)
