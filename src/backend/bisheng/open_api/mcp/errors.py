"""Structured, machine-readable tool errors for a caller with no human in it.

An MCP client is an agent: nobody reads the log for it, and nobody retries by
hand. Every refusal therefore carries three things — **category** (what kind of
wall this is), **reason** (what the platform actually decided) and **next_step**
(what to do about it) — and arrives as parseable JSON rather than prose.

Two SDK behaviours shape the implementation and are easy to trip over:

* ``mcp.server.fastmcp.tools.base.Tool.run`` re-wraps *any* handler exception as
  ``ToolError(f"Error executing tool {name}: {e}")``. Left alone, that prefixes
  the JSON with English prose and ``json.loads`` fails at the client. The server
  unwraps it via ``__cause__`` — see ``BishengMcpServer.call_tool``.
* The low-level server turns whatever escapes into ``_make_error_result(str(e))``
  — the exception *type* is gone by the time the client sees it. So the whole
  payload lives in ``__str__``.

``next_step`` copy is deliberately **not** in ``packages/locales/api_errors``:
the backend process does not ship the frontend locale package and could not read
it at runtime, and this text is read by an agent, never rendered by the SPA. The
per-code headline copy still lives there as usual (C5).
"""

from __future__ import annotations

import json
from contextvars import ContextVar, Token
from typing import Any

from mcp.server.fastmcp.exceptions import ToolError

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.mcp_face import McpFaceError

#: Language of the ``next_step`` guidance, parsed from ``Accept-Language`` by the
#: access gate. Only these three are understood; anything else falls back.
SUPPORTED_LANGS = ("zh-Hans", "en", "ja")
DEFAULT_LANG = "zh-Hans"

current_mcp_lang: ContextVar[str] = ContextVar("current_mcp_lang", default=DEFAULT_LANG)


def set_current_mcp_lang(lang: str) -> Token:
    return current_mcp_lang.set(lang if lang in SUPPORTED_LANGS else DEFAULT_LANG)


def reset_current_mcp_lang(token: Token) -> None:
    current_mcp_lang.reset(token)


# --- categories ------------------------------------------------------------
# One value per kind of wall. An agent branches on this, not on the numeric
# code, so the set is small and stable.
CATEGORY_CREDENTIAL_INVALID = "credential_invalid"
CATEGORY_SCOPE_MISSING = "scope_missing"
CATEGORY_DELEGATE_ONLY = "delegate_only"
CATEGORY_IDENTITY_HEADER_REFUSED = "identity_header_refused"
CATEGORY_UNREACHABLE = "unreachable"
CATEGORY_CAPABILITY_REVOKED = "capability_revoked"
CATEGORY_NOT_YOUR_APP = "not_your_app"
CATEGORY_RUNTIME_DISABLED = "runtime_disabled"
CATEGORY_PERMISSION_UNAVAILABLE = "permission_unavailable"
CATEGORY_INVALID_ARGUMENT = "invalid_argument"
CATEGORY_SCOPE_TOO_LARGE = "scope_too_large"
CATEGORY_INTERNAL = "internal"

#: Fallback code for anything unmapped. Its copy is the generic "retry or ask an
#: administrator" — never the exception text, which can carry paths or SQL.
GENERIC_CODE = 26300

ERROR_CATEGORY_MAP: dict[int, str] = {
    # transport / credential (module 260, reused verbatim — one code, one meaning)
    26001: CATEGORY_CREDENTIAL_INVALID,
    26002: CATEGORY_CREDENTIAL_INVALID,
    26003: CATEGORY_SCOPE_MISSING,
    26027: CATEGORY_CREDENTIAL_INVALID,
    26030: CATEGORY_INTERNAL,
    26051: CATEGORY_DELEGATE_ONLY,
    # MCP face (module 263)
    26300: CATEGORY_INTERNAL,
    26301: CATEGORY_UNREACHABLE,
    26302: CATEGORY_SCOPE_MISSING,
    26303: CATEGORY_IDENTITY_HEADER_REFUSED,
    26304: CATEGORY_INVALID_ARGUMENT,
    26305: CATEGORY_NOT_YOUR_APP,
    26306: CATEGORY_UNREACHABLE,
    # retrieval facade (module 263)
    26320: CATEGORY_INTERNAL,
    26321: CATEGORY_UNREACHABLE,
    26322: CATEGORY_CAPABILITY_REVOKED,
    26323: CATEGORY_SCOPE_TOO_LARGE,
    # permission runtime — surfaced, never swallowed into an empty result set
    19002: CATEGORY_PERMISSION_UNAVAILABLE,
    19201: CATEGORY_PERMISSION_UNAVAILABLE,
    # hosted applications
    16101: CATEGORY_NOT_YOUR_APP,
    16161: CATEGORY_NOT_YOUR_APP,
    16162: CATEGORY_NOT_YOUR_APP,
    # 16163-16167 are real business states of an application that *is* yours.
    # Folding any of them into 26305 would tell a developer the application is
    # not theirs when it is, and send them to an administrator for nothing.
    16163: CATEGORY_UNREACHABLE,
    16164: CATEGORY_UNREACHABLE,
    16165: CATEGORY_UNREACHABLE,
    16166: CATEGORY_INVALID_ARGUMENT,
    16167: CATEGORY_INTERNAL,
    16205: CATEGORY_NOT_YOUR_APP,
    16207: CATEGORY_RUNTIME_DISABLED,
    16254: CATEGORY_NOT_YOUR_APP,
}

NEXT_STEP_COPY: dict[int, dict[str, str]] = {
    26001: {
        "zh-Hans": "在 MCP 客户端配置里加上 Authorization: Bearer <密钥> 请求头后重连。",
        "en": "Add an `Authorization: Bearer <key>` header to the MCP client config and reconnect.",
        "ja": "MCP クライアントの設定に Authorization: Bearer <キー> ヘッダーを追加して再接続してください。",
    },
    26002: {
        "zh-Hans": "密钥无效、已撤销或已过期，请找管理员重新签发一把。",  # noqa: RUF001
        "en": "The key is invalid, revoked or expired — ask an administrator to issue a new one.",
        "ja": "キーが無効・取り消し済み・期限切れです。管理者に再発行を依頼してください。",
    },
    26003: {
        "zh-Hans": "找管理员在这把密钥上勾选所需权限位，无需重新签发。",  # noqa: RUF001
        "en": "Ask an administrator to tick the required scope on this key; no re-issue is needed.",
        "ja": "管理者にこのキーへ必要な権限の付与を依頼してください。再発行は不要です。",
    },
    26027: {
        "zh-Hans": "密钥所属的服务账号已停用，请找管理员启用或另发一把密钥。",  # noqa: RUF001
        "en": "The service account behind this key is disabled — ask an administrator to enable it.",
        "ja": "このキーのサービスアカウントは無効です。管理者に有効化を依頼してください。",
    },
    26030: {
        "zh-Hans": "凭据校验依赖暂时不可用，请稍后重试。",  # noqa: RUF001
        "en": "The credential-validation dependency is temporarily unavailable; retry shortly.",
        "ja": "認証情報の検証基盤が一時的に利用できません。しばらくしてから再試行してください。",
    },
    26051: {
        "zh-Hans": "这把密钥配置为委托专用，本地开发请让管理员另发一把不带 delegate 的密钥。",  # noqa: RUF001
        "en": "This key is delegation-only. Ask an administrator for a separate key without `delegate`.",
        "ja": "このキーは委任専用です。ローカル開発には delegate を持たない別のキーを管理者に依頼してください。",
    },
    26300: {
        "zh-Hans": "稍后重试；持续失败请联系平台管理员。",  # noqa: RUF001
        "en": "Retry shortly; if it keeps failing, contact the platform administrator.",
        "ja": "しばらくしてから再試行し、繰り返す場合は管理者に連絡してください。",
    },
    26301: {
        "zh-Hans": "先调用 tools/list 看这把密钥当前可用的工具清单。",
        "en": "Call `tools/list` first to see what this key can actually use.",
        "ja": "まず tools/list を呼び、このキーで使えるツールを確認してください。",
    },
    26302: {
        "zh-Hans": "找管理员在这把密钥上勾选 data.required 指出的权限位，下次调用即生效。",  # noqa: RUF001
        "en": "Ask an administrator to tick the scope named in `data.required`; it applies on the next call.",
        "ja": "data.required が示す権限を管理者にこのキーへ付与してもらってください。次回の呼び出しから有効です。",
    },
    26303: {
        "zh-Hans": "移除 X-On-Behalf-Of / X-End-User 等身份传递请求头；MCP 面一律以密钥自身身份执行。",  # noqa: RUF001
        "en": "Remove the X-On-Behalf-Of / X-End-User headers — the MCP face always runs as the key itself.",
        "ja": "X-On-Behalf-Of / X-End-User などの ID 連携ヘッダーを削除してください。MCP 面は常にキー自身として実行します。",
    },
    26304: {
        "zh-Hans": "按 data.errors 修正入参后重试；入参结构见 tools/list 的 inputSchema。",  # noqa: RUF001
        "en": "Fix the arguments per `data.errors` and retry; the shape is in `tools/list`'s inputSchema.",
        "ja": "data.errors に従って引数を修正してください。形式は tools/list の inputSchema にあります。",
    },
    26305: {
        "zh-Hans": "开发者密钥只能操作自己 deploy 的应用；查他人应用请到平台的应用详情页。",  # noqa: RUF001
        "en": "A developer key only reaches applications it deployed; use the platform's app detail page for others.",
        "ja": "開発者キーは自分がデプロイしたアプリのみ操作できます。他人のアプリはプラットフォームの詳細ページで確認してください。",
    },
    26306: {
        "zh-Hans": "确认用户 / 部门标识是否正确，且属于本租户。",  # noqa: RUF001
        "en": "Check the user or department id, and that it belongs to this tenant.",
        "ja": "ユーザー / 部門 ID が正しく、同一テナントに属しているか確認してください。",
    },
    26320: {
        "zh-Hans": "无法确立执行身份，平台不会退回任何默认身份；请检查密钥后重试。",  # noqa: RUF001
        "en": "No execution identity could be established and the platform never falls back to a default one — check the key.",
        "ja": "実行 ID を確立できませんでした。既定の ID への切り替えは行いません。キーを確認してください。",
    },
    26321: {
        "zh-Hans": "先调 bisheng_knowledge_list 拿到可用的知识库清单，再用其中的标识检索。",  # noqa: RUF001
        "en": "Call `bisheng_knowledge_list` for the reachable knowledge bases and retry with an id from it.",
        "ja": "bisheng_knowledge_list で利用可能なナレッジベースを取得し、その ID で再試行してください。",
    },
    26322: {
        "zh-Hans": "声明接入的知识库已被删除或收回，请更新应用的能力声明后重新发布。",  # noqa: RUF001
        "en": "A declared knowledge base is gone — update the application's capability declaration and publish again.",
        "ja": "宣言したナレッジベースが削除/取り消されています。アプリの能力宣言を更新して再公開してください。",
    },
    26323: {
        "zh-Hans": "显式指定要检索的知识库（不超过 50 个）后重试。",  # noqa: RUF001
        "en": "Name the knowledge bases to search explicitly (at most 50) and retry.",
        "ja": "検索対象のナレッジベースを明示（最大 50 件）して再試行してください。",  # noqa: RUF001
    },
    19002: {
        "zh-Hans": "权限引擎暂时不可用，平台宁可报错也不会返回未过滤的结果；请稍后重试。",  # noqa: RUF001
        "en": "The permission engine is unavailable; the platform errors rather than return unfiltered results. Retry shortly.",
        "ja": "権限エンジンが一時的に利用できません。未フィルタの結果を返すことはありません。しばらくして再試行してください。",
    },
    19201: {
        "zh-Hans": "权限引擎暂时不可用，平台宁可报错也不会返回未过滤的结果；请稍后重试。",  # noqa: RUF001
        "en": "The permission engine is unavailable; the platform errors rather than return unfiltered results. Retry shortly.",
        "ja": "権限エンジンが一時的に利用できません。未フィルタの結果を返すことはありません。しばらくして再試行してください。",
    },
    16101: {
        "zh-Hans": "开发者密钥只能操作自己 deploy 的应用；确认 app_id 是否正确。",  # noqa: RUF001
        "en": "A developer key only reaches applications it deployed; check the app_id.",
        "ja": "開発者キーは自分がデプロイしたアプリのみ操作できます。app_id を確認してください。",
    },
    16161: {
        "zh-Hans": "开发者密钥只能读自己 deploy 的应用的日志。",
        "en": "A developer key only reads logs for applications it deployed.",
        "ja": "開発者キーは自分がデプロイしたアプリのログのみ参照できます。",
    },
    16162: {
        "zh-Hans": "开发者密钥只能读写自己 deploy 的应用的数据。",
        "en": "A developer key only reads and writes data for applications it deployed.",
        "ja": "開発者キーは自分がデプロイしたアプリのデータのみ読み書きできます。",
    },
    16163: {
        "zh-Hans": "该应用还没有创建过数据库表，先让应用写一次数据再来查。",  # noqa: RUF001
        "en": "This application has no database tables yet — let it write once, then query.",
        "ja": "このアプリはまだテーブルを作成していません。一度データを書き込んでから再試行してください。",
    },
    16164: {
        "zh-Hans": "先调 bisheng_app_db_tables 看这个应用有哪些表。",
        "en": "Call `bisheng_app_db_tables` to see which tables this application has.",
        "ja": "bisheng_app_db_tables でこのアプリのテーブル一覧を確認してください。",
    },
    16165: {
        "zh-Hans": "行不存在或已被应用改动，先读一次当前行再重试。",  # noqa: RUF001
        "en": "The row is gone or the application changed it — read it again before retrying.",
        "ja": "行が存在しないかアプリが変更しました。現在の行を読み直してから再試行してください。",
    },
    16166: {
        "zh-Hans": "表名 / 列名只能是普通标识符，值只能是标量；本工具不提供 DDL。",  # noqa: RUF001
        "en": "Table and column names must be plain identifiers and values scalar; this tool carries no DDL.",
        "ja": "テーブル名・列名は通常の識別子、値はスカラーのみです。このツールは DDL を提供しません。",
    },
    16167: {
        "zh-Hans": "应用正持有数据库写锁，请稍后重试。",  # noqa: RUF001
        "en": "The application holds its database write lock; retry shortly.",
        "ja": "アプリがデータベースの書き込みロックを保持しています。しばらくして再試行してください。",
    },
    16205: {
        "zh-Hans": "这把密钥未绑定资源归属人，请管理员在服务账号详情页指定后重试。",  # noqa: RUF001
        "en": "This key has no resource owner — ask an administrator to set one on the service account.",
        "ja": "このキーにはリソース所有者が設定されていません。管理者にサービスアカウントでの設定を依頼してください。",
    },
    16207: {
        "zh-Hans": "本环境未启用应用工场运行时层，应用类工具不可用；其余工具不受影响。",  # noqa: RUF001
        "en": "The application runtime layer is not deployed here, so the application tools are unavailable; the rest still work.",
        "ja": "この環境ではアプリランタイム層が無効なため、アプリ系ツールは利用できません。他のツールは使用できます。",
    },
    16254: {
        "zh-Hans": "开发者密钥只能查自己 deploy 的应用的发布状态。",
        "en": "A developer key only reads the publish status of applications it deployed.",
        "ja": "開発者キーは自分がデプロイしたアプリの公開状態のみ参照できます。",
    },
}


class McpToolError(ToolError):
    """A refusal an agent can branch on. ``str()`` is the whole JSON payload."""

    def __init__(
        self,
        *,
        code: int,
        category: str,
        reason: str,
        next_step: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.category = category
        self.reason = reason
        self.next_step = next_step
        self.data = data or {}
        super().__init__(self.to_json())

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "category": self.category,
            "reason": self.reason,
            "next_step": self.next_step,
            "data": self.data,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False)

    def __str__(self) -> str:  # what the SDK hands the client
        return self.to_json()


def _jsonable(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Keep only what survives ``json.dumps`` — the payload must never fail to serialise."""

    safe: dict[str, Any] = {}
    for key, value in kwargs.items():
        try:
            json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            continue
        safe[key] = value
    return safe


def next_step_for(code: int, *, lang: str | None = None) -> str:
    language = lang if lang in SUPPORTED_LANGS else current_mcp_lang.get()
    copy = NEXT_STEP_COPY.get(code) or NEXT_STEP_COPY[GENERIC_CODE]
    return copy.get(language) or copy[DEFAULT_LANG]


def to_tool_error(exc: BaseException, *, lang: str | None = None) -> McpToolError:
    """Any exception → the three-part form, without ever leaking its text.

    ``reason`` comes from the error class's own message, never ``str(exc)``: an
    unmapped exception's text can carry a file path, a SQL fragment or a host
    name, and this payload goes to a client outside the platform.
    """

    if isinstance(exc, McpToolError):
        return exc
    if isinstance(exc, BaseErrorCode):
        code = int(getattr(exc, "code", None) or exc.Code)
        category = ERROR_CATEGORY_MAP.get(code, CATEGORY_INTERNAL)
        if code in ERROR_CATEGORY_MAP:
            reason = getattr(exc, "message", None) or exc.Msg
            data = _jsonable(getattr(exc, "kwargs", None) or {})
        else:
            # Unmapped: the code still reaches the audit row, but the message is
            # not ours to forward to a client outside the platform.
            reason = McpFaceError.Msg
            data = {}
        return McpToolError(
            code=code,
            category=category,
            reason=reason,
            next_step=next_step_for(code if code in NEXT_STEP_COPY else GENERIC_CODE, lang=lang),
            data=data,
        )
    return McpToolError(
        code=GENERIC_CODE,
        category=CATEGORY_INTERNAL,
        reason=McpFaceError.Msg,
        next_step=next_step_for(GENERIC_CODE, lang=lang),
        data={},
    )


def from_errcode(exc: BaseErrorCode, *, lang: str | None = None) -> McpToolError:
    """Explicit conversion for an error the handler raised on purpose."""

    return to_tool_error(exc, lang=lang)


__all__ = [
    "DEFAULT_LANG",
    "ERROR_CATEGORY_MAP",
    "GENERIC_CODE",
    "NEXT_STEP_COPY",
    "SUPPORTED_LANGS",
    "McpToolError",
    "current_mcp_lang",
    "from_errcode",
    "next_step_for",
    "reset_current_mcp_lang",
    "set_current_mcp_lang",
    "to_tool_error",
]
