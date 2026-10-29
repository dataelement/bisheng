"""平台注入的环境变量名（design §4.2 ②）。

名字是契约：托管期由 runtime-manager `lifecycle.build_env` 与能力总线注入，
本地期由 `bisheng dev` 同名注入（契约见
`features/v3.0.0/054-app-domain-runtime/contracts-runtime-manager.md` §5），
因此应用代码本地线上零差异。SDK 只读这几个名字，**不读任何别的密钥变量**。

`BISHENG_APP_TOKEN` 是应用自身的运行期凭据。它回答的是「这次调用来自哪个应用」，
与访问者身份（请求头里的 `X-BiSheng-Access-Token`）是两件事，永远一起出现、
永远不互相替代：只带应用凭据的检索会被平台以「无访问用户」拒绝，只带访问者凭据
则根本不认识这个应用。
"""

from __future__ import annotations

import os

from bisheng_sdk.errors import PlatformUnreachableError

#: 平台 API 根地址（retrieve 与版本探测都打它）。
ENV_PLATFORM_API_BASE = "BISHENG_PLATFORM_API_BASE"

#: 应用自身的运行期凭据（F055 能力总线在创建容器前注入）。
ENV_APP_TOKEN = "BISHENG_APP_TOKEN"

#: 托管期附件句柄三件（runtime-manager `storage.STORAGE_ENV_NAMES`）。
ENV_STORAGE_ENDPOINT = "BISHENG_APP_STORAGE_ENDPOINT"
ENV_STORAGE_TOKEN = "BISHENG_APP_STORAGE_TOKEN"
ENV_STORAGE_MAX_FILE_MB = "BISHENG_APP_STORAGE_MAX_FILE_MB"

#: 本地期目录句柄（`bisheng dev` 注入；值 = `<项目根>/.bisheng/attachments/`）。
ENV_STORAGE_DIR = "BISHENG_APP_STORAGE_DIR"

#: 显式打开 httpx 的代理环境变量读取（本地默认关，design D11）。
ENV_TRUST_ENV = "BISHENG_SDK_TRUST_ENV"

#: 平台出站代理的凭据（runtime-manager `egress.ENV_EGRESS_TOKEN`，开了出站白名单才注入）。
#: SDK **只看它在不在**，不取值：在 = 身处托管容器，唯一出口是注入的 `HTTP(S)_PROXY`。
ENV_EGRESS_TOKEN = "BISHENG_APP_EGRESS_TOKEN"

#: 应用标识，只用于错误文案（真正定位应用的是注入的句柄与凭据）。
ENV_APP_ID = "BISHENG_APP_ID"


def platform_api_base() -> str:
    """平台地址，空即抛错。

    `app_runtime.entry_base_url` 允许为空（"derive from request"），此时注入的
    是**空串**。不在这里挡住的话，httpx 会对相对地址报 `UnsupportedProtocol`，
    看不出是平台配置缺失（design 坑 19）。
    """
    base = (os.environ.get(ENV_PLATFORM_API_BASE) or "").strip().rstrip("/")
    if not base:
        raise PlatformUnreachableError(
            f"环境变量 {ENV_PLATFORM_API_BASE} 未注入或为空，不知道平台地址",
            "托管运行期请管理员配置 `app_runtime.entry_base_url`；本地开发请经 `bisheng dev` 启动应用",
        )
    return base


def app_token() -> str | None:
    """应用运行期凭据明文，未注入时 ``None``。"""
    return (os.environ.get(ENV_APP_TOKEN) or "").strip() or None


def storage_endpoint() -> str | None:
    return (os.environ.get(ENV_STORAGE_ENDPOINT) or "").strip().rstrip("/") or None


def storage_token() -> str | None:
    return (os.environ.get(ENV_STORAGE_TOKEN) or "").strip() or None


def storage_dir() -> str | None:
    return (os.environ.get(ENV_STORAGE_DIR) or "").strip() or None


def storage_max_file_bytes() -> int | None:
    """单文件上限（字节），未注入或不可解析时 ``None`` = 客户端不预判。

    线上恒注入（缺省 20 MB）；本地 `bisheng dev` 期可选，不注入即本地不限——
    于是本地传得进、线上 413，指南把这一条列为本地 / 线上差异之一（坑 23）。
    """
    raw = (os.environ.get(ENV_STORAGE_MAX_FILE_MB) or "").strip()
    if not raw:
        return None
    try:
        megabytes = int(float(raw))
    except ValueError:
        return None
    if megabytes <= 0:
        return None
    return megabytes * 1024 * 1024


def trust_env() -> bool:
    """httpx 是否读代理环境变量（design D11）。

    托管容器挂在 `--internal` 网上，除了网关没有任何路由：平台 API 只能经平台注入的
    出站代理到达（平台地址在代理白名单里恒放行）。所以**有出站凭据就必须读**，否则
    `retrieve` 直连平台只会得到「网络不可达」。附件句柄的地址在注入的 `NO_PROXY` 里，
    读了代理变量也照旧直连。

    本地没有这个凭据（`bisheng dev` 不注入），仍默认不读——开发机上的公网代理会劫持
    内网平台地址；确实需要时用 `BISHENG_SDK_TRUST_ENV=1` 显式打开。
    """
    if (os.environ.get(ENV_TRUST_ENV) or "").strip() == "1":
        return True
    return bool((os.environ.get(ENV_EGRESS_TOKEN) or "").strip())


def app_id() -> str:
    return (os.environ.get(ENV_APP_ID) or "").strip()
