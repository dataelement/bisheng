"""SDK ↔ 平台的版本兼容校验（design D7）。

平台声明它支持的**最低兼容 SDK 版本**（`/api/v1/dev-toolkit/versions` 的
`sdk.min_compatible`）。低于它就在与该平台的**首次交互**抛错，不静默降级、不
部分工作；兼容的应用在平台升级后不需要重发。

三件容易搞反的事：

* **auth 永不探测。** 它是纯上下文读取、零 I/O，import 与探活都不该被拖下水。
  于是不兼容可能要到第一次 retrieve / storage 才暴露——指南因此建议应用启动时
  跑一次连通自检。
* **只比下界。** 平台升级后老 SDK 仍在区间内即无需重发（AC-03）。
* **成功才缓存。** 不可达不缓存，下次再试；否则一次网络抖动会让整个进程
  一直以为平台不可用。
"""

from __future__ import annotations

import threading

from bisheng_sdk import __version__, _http
from bisheng_sdk.errors import PlatformTooOldError, SdkIncompatibleError

VERSIONS_PATH = "/api/v1/dev-toolkit/versions"

_lock = threading.Lock()
_checked: set[str] = set()


def version_tuple(raw: str) -> tuple[int, ...]:
    """三段元组比较，与 CLI `bisheng_cli.http._version_tuple` 同算法。

    字符串比较会让 `"0.10.0" < "0.9.9"`，这类比较一旦错了没人看得出来。
    不引 `packaging`：依赖预算只有 httpx 一条（CON-1）。
    """
    parts: list[int] = []
    for chunk in str(raw).split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _decide(payload: object) -> None:
    sdk = payload.get("sdk") if isinstance(payload, dict) else None
    if not isinstance(sdk, dict) or not sdk.get("version"):
        raise PlatformTooOldError()
    min_compatible = sdk.get("min_compatible") or sdk.get("version")
    if not isinstance(min_compatible, str):
        raise PlatformTooOldError()
    if version_tuple(min_compatible) > version_tuple(__version__):
        platform = payload.get("platform") if isinstance(payload, dict) else None
        platform_version = platform.get("version") if isinstance(platform, dict) else None
        raise SdkIncompatibleError(
            sdk_version=__version__,
            min_compatible=min_compatible,
            platform_version=platform_version if isinstance(platform_version, str) else None,
        )


def _mark(base_url: str) -> None:
    with _lock:
        _checked.add(base_url)


def _already(base_url: str) -> bool:
    with _lock:
        return base_url in _checked


def reset() -> None:
    """清空进程内缓存（测试用；生产路径不调用）。"""
    with _lock:
        _checked.clear()


def ensure_compatible(base_url: str) -> None:
    if _already(base_url):
        return
    resp = _http.request("versions", "GET", VERSIONS_PATH, base_url=base_url)
    if resp.status_code == 404:
        raise PlatformTooOldError()
    _decide(_http.parse_envelope(resp))
    _mark(base_url)


async def aensure_compatible(base_url: str) -> None:
    if _already(base_url):
        return
    resp = await _http.arequest("versions", "GET", VERSIONS_PATH, base_url=base_url)
    if resp.status_code == 404:
        raise PlatformTooOldError()
    _decide(_http.parse_envelope(resp))
    _mark(base_url)
