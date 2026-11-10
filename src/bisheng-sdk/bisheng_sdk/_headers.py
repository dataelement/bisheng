"""平台注入头的名字、归一化与解析（design §4.2 ①）。

这张表是 `src/app-proxy/app_proxy/headers.py::INJECTED_HEADER_NAMES` 的第三份
副本（第二份在 `bisheng dev` 的迷你代理里）。三份必须逐字相同，
`tests/test_contract_alignment.py` 读 app-proxy 的源文件对账——SDK 不读 CLI，
上游是 app-proxy。

两个反直觉之处，写错了排查成本很高：

* **缺失的头是「不发」而不是「发空串」**（app-proxy `build_injected_headers`）。
  服务账号没有部门，于是部门三头整个不出现——用 ``== ""`` 判断"无部门"永远为假。
* **非 ASCII 值在注入侧被 ``quote(text, safe="/")``**，ASCII 值原样。因此中文
  姓名读出来是 ``%E5%BC%A0…``，必须 ``unquote`` 才是人名。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from urllib.parse import unquote

#: 平台拥有的归一化前缀。快照只收这个前缀下的头。
PLATFORM_HEADER_PREFIX = "x-bisheng-"

#: 十个注入头，顺序与拼写逐字照 app-proxy。
INJECTED_HEADER_NAMES: tuple[str, ...] = (
    "X-BiSheng-User-Id",
    "X-BiSheng-User-Name",
    "X-BiSheng-Tenant-Id",
    "X-BiSheng-Dept-Id",
    "X-BiSheng-Dept-Name",
    "X-BiSheng-Dept-Path",
    "X-BiSheng-Subject-Kind",
    "X-BiSheng-App-Id",
    "X-BiSheng-Access-Token",
    "X-BiSheng-Request-Id",
)

HEADER_USER_ID = "x-bisheng-user-id"
HEADER_USER_NAME = "x-bisheng-user-name"
HEADER_TENANT_ID = "x-bisheng-tenant-id"
HEADER_DEPT_ID = "x-bisheng-dept-id"
HEADER_DEPT_NAME = "x-bisheng-dept-name"
HEADER_DEPT_PATH = "x-bisheng-dept-path"
HEADER_SUBJECT_KIND = "x-bisheng-subject-kind"
HEADER_APP_ID = "x-bisheng-app-id"
HEADER_ACCESS_TOKEN = "x-bisheng-access-token"
HEADER_REQUEST_ID = "x-bisheng-request-id"

#: 注入侧的缺省值（`entry_authz_service` 不发该头时的含义）。线上恒 ``human``；
#: ``bisheng dev`` 期取决于 ``login`` 用的密钥种类（服务账号密钥 →
#: ``service_account``，个人访问令牌 → ``human``）。SDK 原样透传、不推导。
DEFAULT_SUBJECT_KIND = "human"


def normalize_name(name: str) -> str:
    """``X_BiSheng_User_Id``、``HTTP_X_BISHENG_USER_ID`` 与规范拼写是同一个头。

    WSGI 家族把头折成 ``HTTP_`` 前缀 + 下划线，这里先去前缀再归一化——与
    app-proxy `normalize_header_name` 同规则（那正是 CVE-2025-64484 的教训：
    只认带连字符的拼法，下划线形态会径直走过去）。
    """
    text = str(name).strip()
    if text.upper().startswith("HTTP_"):
        text = text[5:]
    return text.lower().replace("_", "-")


def snapshot(headers: Iterable[tuple[str, str]] | Mapping[str, str]) -> dict[str, str]:
    """本请求的注入头快照：只收 ``x-bisheng-`` 前缀，键为归一化名。"""
    items = headers.items() if isinstance(headers, Mapping) else headers
    collected: dict[str, str] = {}
    for raw_name, raw_value in items:
        name = normalize_name(_as_text(raw_name))
        if not name.startswith(PLATFORM_HEADER_PREFIX):
            continue
        collected[name] = _as_text(raw_value)
    return collected


def wsgi_snapshot(environ: Mapping[str, object]) -> dict[str, str]:
    """WSGI ``environ`` 里的 ``HTTP_X_BISHENG_*``，归一化成同一份快照。"""
    pairs: list[tuple[str, str]] = []
    for key, value in environ.items():
        if not isinstance(key, str) or not key.startswith("HTTP_"):
            continue
        pairs.append((key, value if isinstance(value, str) else str(value)))
    return snapshot(pairs)


def decode_value(value: str) -> str:
    """还原注入侧的 ``quote(text, safe="/")``。

    一个恰好含字面 ``%E5`` 的 ASCII 值会被误解码——病态输入，接受（注入侧对
    ASCII 值原样放行，因此无法区分"本来就有 %"与"被编码过"）。
    """
    return unquote(value)


def _as_text(value: object) -> str:
    """ASGI 的 ``scope["headers"]`` 是 ``bytes``，WSGI / 框架给 ``str``。"""
    if isinstance(value, bytes):
        return value.decode("latin-1")
    return str(value)
