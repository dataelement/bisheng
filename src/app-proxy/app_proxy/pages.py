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

**Language.** Three locales — zh-Hans / en / ja — chosen from the request's
``Accept-Language`` and falling back to zh-Hans. The copy lives in this module
rather than in ``packages/locales``: app-proxy is a separate process that must
still render when the platform is half-broken, so it carries no runtime
dependency on the SPA bundles, and ``pnpm check-i18n`` therefore cannot see
these strings. :data:`_COPY` is the substitute for that check — every locale
declares every kind, and ``test_pages_i18n`` fails the build if one drifts.

**Roles named in the copy.** Never "租户管理员": ``multi_tenant.enabled``
defaults to *false*, so a standard install is single-tenant, ``tenant_admin``
resolves to the platform super admin, and Root may not even be granted a tenant
administrator (19204) — the person that page told the visitor to find does not
exist. This process cannot read the switch either (it never talks to the config
service), so the copy uses the tenant-neutral "平台管理员" that is true in both
deployment shapes.
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

#: The three bundles the platform ships everywhere else (``packages/locales``).
LOCALE_ZH = "zh-Hans"
LOCALE_EN = "en"
LOCALE_JA = "ja"
DEFAULT_LOCALE = LOCALE_ZH

#: ``<html lang>`` per bundle — not the bundle name: "zh-Hans" is a valid BCP 47
#: tag but "zh-CN" is what the rest of the platform emits.
_HTML_LANG = {LOCALE_ZH: "zh-CN", LOCALE_EN: "en", LOCALE_JA: "ja"}

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
class _Layout:
    """What a page looks like — the same in every language."""

    mark: str
    show_square: bool = True


@dataclass(frozen=True)
class _Copy:
    """What a page says in one language.

    ``lines`` may reference ``{app}`` and ``{owner}``; both are always
    substituted, with a generic stand-in when the name is unknown.
    """

    title: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class _Chrome:
    """Everything on the page that is not a :class:`_Copy` line."""

    square: str
    request_id: str
    #: ``{name}`` — how the app's own name is set off from the sentence around
    #: it. CJK takes 「」 instead of the spaces a Latin script would use.
    app_named: str
    #: Stand-in when the app name is unknown (the not-found page never has one).
    #: Every line has to read correctly with *either* value in the slot, which
    #: is why no line starts with ``{app}`` or puts an article in front of it.
    app_fallback: str
    #: ``{name}`` — the owner, with their role spelled out around the name so
    #: the sentence survives the fallback below without saying it twice.
    owner_named: str
    owner_fallback: str


_LAYOUT: dict[str, _Layout] = {
    DECISION_FORBIDDEN: _Layout(mark="🔒"),
    DECISION_STOPPED: _Layout(mark="⏸"),
    # Carries neither name nor owner — draft / pending / deleted / never
    # existed must be one indistinguishable page (AC-29).
    DECISION_NOT_FOUND: _Layout(mark="🔍"),
    DECISION_NOT_ENABLED: _Layout(mark="🧩", show_square=False),
    DECISION_UNAVAILABLE: _Layout(mark="⚠️", show_square=False),
    PAGE_RECOVERING: _Layout(mark="🔄", show_square=False),
}

_CHROME: dict[str, _Chrome] = {
    LOCALE_ZH: _Chrome(
        square="返回广场",
        request_id="请求编号：{id}",
        app_named="「{name}」",
        app_fallback="该应用",
        owner_named="应用负责人「{name}」",
        owner_fallback="应用负责人",
    ),
    LOCALE_EN: _Chrome(
        square="Back to Square",
        request_id="Request ID: {id}",
        app_named="{name}",
        app_fallback="this application",
        owner_named="the app owner ({name})",
        owner_fallback="the app owner",
    ),
    LOCALE_JA: _Chrome(
        square="広場に戻る",
        request_id="リクエスト ID：{id}",
        app_named="「{name}」",
        app_fallback="このアプリ",
        owner_named="アプリ担当者（{name}）",
        owner_fallback="アプリ担当者",
    ),
}

#: Locale → kind → copy. Every locale declares every kind; the parity is a
#: test, because nothing else checks these strings.
_COPY: dict[str, dict[str, _Copy]] = {
    LOCALE_ZH: {
        DECISION_FORBIDDEN: _Copy(
            title="无访问权限",
            lines=(
                "你没有访问{app}的权限。",
                "如需使用，请联系{owner}或平台管理员开通权限。",
            ),
        ),
        DECISION_STOPPED: _Copy(
            title="应用已停用",
            lines=(
                "{app}已停用，恢复后即可正常访问。",
                "如需恢复，请联系{owner}或平台管理员。",
            ),
        ),
        DECISION_NOT_FOUND: _Copy(
            title="应用不存在或未上线",
            lines=("该链接对应的应用不存在，或尚未上线。", "请确认链接是否正确，或返回广场查看可用的应用。"),
        ),
        DECISION_NOT_ENABLED: _Copy(
            title="本环境未启用应用工场",
            lines=("当前环境未部署应用工场运行时层，无法访问托管应用。", "如需启用，请联系平台管理员。"),
        ),
        DECISION_UNAVAILABLE: _Copy(
            title="暂时无法访问",
            lines=("平台暂时无法确认你的访问权限，请稍后重试。", "若持续出现，请联系平台管理员。"),
        ),
        PAGE_RECOVERING: _Copy(
            title="应用恢复中",
            lines=("{app}正在恢复，请稍后刷新页面重试。",),
        ),
    },
    LOCALE_EN: {
        DECISION_FORBIDDEN: _Copy(
            title="No access",
            lines=(
                "You do not have access to {app}.",
                "To get access, contact {owner} or a platform administrator.",
            ),
        ),
        DECISION_STOPPED: _Copy(
            title="Application stopped",
            lines=(
                "For now, {app} is stopped. It will be reachable again once it is restarted.",
                "To have it restarted, contact {owner} or a platform administrator.",
            ),
        ),
        DECISION_NOT_FOUND: _Copy(
            title="Application not found",
            lines=(
                "The application this link points to does not exist, or is not online yet.",
                "Check the link, or go back to the square to see the applications available to you.",
            ),
        ),
        DECISION_NOT_ENABLED: _Copy(
            title="App factory is not enabled",
            lines=(
                "The app factory runtime layer is not deployed in this environment, "
                "so hosted applications cannot be opened.",
                "To have it enabled, contact a platform administrator.",
            ),
        ),
        DECISION_UNAVAILABLE: _Copy(
            title="Temporarily unavailable",
            lines=(
                "The platform cannot confirm your access right now. Please try again in a moment.",
                "If this keeps happening, contact a platform administrator.",
            ),
        ),
        PAGE_RECOVERING: _Copy(
            title="Application is restarting",
            lines=("Please wait, {app} is restarting. Refresh the page in a moment.",),
        ),
    },
    LOCALE_JA: {
        DECISION_FORBIDDEN: _Copy(
            title="アクセス権限がありません",
            lines=(
                "{app}へのアクセス権限がありません。",
                "利用するには、{owner}またはプラットフォーム管理者に権限の付与を依頼してください。",
            ),
        ),
        DECISION_STOPPED: _Copy(
            title="アプリは停止中です",
            lines=(
                "{app}は停止中です。再開後にアクセスできます。",
                "再開するには、{owner}またはプラットフォーム管理者にご連絡ください。",
            ),
        ),
        DECISION_NOT_FOUND: _Copy(
            title="アプリが存在しないか、公開されていません",
            lines=(
                "このリンクのアプリは存在しないか、まだ公開されていません。",
                "リンクをご確認いただくか、広場に戻って利用できるアプリをご覧ください。",
            ),
        ),
        DECISION_NOT_ENABLED: _Copy(
            title="この環境ではアプリ工場が有効化されていません",
            lines=(
                "この環境にはアプリ工場のランタイム層が導入されていないため、ホスト型アプリを開けません。",
                "有効化するには、プラットフォーム管理者にご連絡ください。",
            ),
        ),
        DECISION_UNAVAILABLE: _Copy(
            title="一時的にアクセスできません",
            lines=(
                "アクセス権限を確認できませんでした。しばらくしてからもう一度お試しください。",
                "繰り返し発生する場合は、プラットフォーム管理者にご連絡ください。",
            ),
        ),
        PAGE_RECOVERING: _Copy(
            title="アプリを復旧しています",
            lines=("{app}を復旧しています。しばらくしてからページを再読み込みしてください。",),
        ),
    },
}

#: Language subtag → bundle. Any Chinese (including zh-Hant / zh-TW) maps to the
#: single Chinese bundle the platform ships; "*" and everything else fall back.
_LANGUAGE_BUNDLE = {"zh": LOCALE_ZH, "en": LOCALE_EN, "ja": LOCALE_JA}


def negotiate_locale(accept_language: str | None) -> str:
    """Pick a bundle from an ``Accept-Language`` header.

    A hand-rolled parser rather than a dependency: the header is three tokens
    and a q-value, and this process deliberately ships nothing it does not need
    to render a page while the platform is down.
    """
    if not accept_language:
        return DEFAULT_LOCALE

    ranked: list[tuple[float, int, str]] = []
    for index, part in enumerate(accept_language.split(",")):
        token, _, params = part.strip().partition(";")
        tag = token.strip().lower()
        if not tag:
            continue
        quality = 1.0
        for param in params.split(";"):
            key, _, value = param.partition("=")
            if key.strip().lower() == "q":
                try:
                    quality = float(value.strip())
                except ValueError:
                    quality = 0.0
        if quality <= 0:
            # ``q=0`` is an explicit refusal, not a weak preference.
            continue
        # Negated quality first, then the original position: sorting the tuple
        # then reproduces "highest q wins, ties keep the order the client sent".
        ranked.append((-quality, index, tag))

    for _, _, tag in sorted(ranked):
        bundle = _LANGUAGE_BUNDLE.get(tag.split("-")[0])
        if bundle:
            return bundle
    return DEFAULT_LOCALE


def _copy(kind: str, locale: str) -> _Copy:
    bundle = _COPY.get(locale) or _COPY[DEFAULT_LOCALE]
    return bundle.get(kind) or bundle[DECISION_UNAVAILABLE]


def _fill(line: str, chrome: _Chrome, app_name: str | None, owner_name: str | None) -> str:
    """Substitute, and degrade gracefully when a name is unknown.

    The owner's *role* travels with the substituted value rather than sitting in
    the sentence, so the fallback reads "请联系应用负责人或平台管理员" instead of
    naming the role twice. An owner may genuinely be missing after an account is
    removed, and the not-found page has no name by design.
    """
    return line.format(
        app=chrome.app_named.format(name=html.escape(app_name)) if app_name else chrome.app_fallback,
        owner=chrome.owner_named.format(name=html.escape(owner_name)) if owner_name else chrome.owner_fallback,
    )


def render_page(
    kind: str,
    *,
    app_name: str | None = None,
    owner_name: str | None = None,
    square_url: str = "/workspace",
    request_id: str = "",
    accept_language: str | None = None,
) -> str:
    """Full self-contained HTML document. No script, no external request.

    These render when the platform may already be half-broken, so a CDN font or
    a logo fetched over the network is exactly the dependency that turns a
    tidy explanation into a blank page.
    """
    locale = negotiate_locale(accept_language)
    layout = _LAYOUT.get(kind) or _LAYOUT[DECISION_UNAVAILABLE]
    chrome = _CHROME[locale]
    copy = _copy(kind, locale)
    body = "\n".join(f"    <p>{_fill(line, chrome, app_name, owner_name)}</p>" for line in copy.lines)

    actions = ""
    if layout.show_square:
        actions = (
            f'    <div class="actions">'
            f'<a class="button" href="{html.escape(square_url)}">{html.escape(chrome.square)}</a></div>'
        )

    hint = ""
    # Only on the two "something broke" pages: a request id printed on the
    # not-found page would make four supposedly identical renders differ, which
    # is exactly the enumeration oracle AC-29 closes.
    if request_id and kind in (DECISION_UNAVAILABLE, PAGE_RECOVERING):
        hint = f'    <p class="hint">{html.escape(chrome.request_id.format(id=request_id))}</p>'

    return f"""<!doctype html>
<html lang="{_HTML_LANG[locale]}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{html.escape(copy.title)}</title>
<style>{_STYLE}</style>
</head>
<body>
  <div class="card">
    <div class="mark">{layout.mark}</div>
    <h1>{html.escape(copy.title)}</h1>
{body}
{actions}
{hint}
  </div>
</body>
</html>
"""


def error_payload(kind: str, request_id: str = "", accept_language: str | None = None) -> dict:
    """JSON body for non-navigation callers, shaped like the platform envelope."""
    copy = _copy(kind, negotiate_locale(accept_language))
    return {
        "status_code": ERROR_CODES.get(kind, ERROR_CODES[DECISION_UNAVAILABLE]),
        "status_message": copy.title,
        "decision": kind,
        "request_id": request_id,
    }


def json_status(kind: str) -> int:
    return JSON_STATUS.get(kind, 503)
