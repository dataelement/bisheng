"""HTTP access to the platform: one client, two envelope shapes, one probe.

The single most load-bearing rule in this file is the parse order in
`parse_envelope`: **body first, status line second**. `/api/v1` answers HTTP 200
and puts the verdict in `status_code`, while `/api/v2` sets a real status *and*
keeps the envelope. Read the status line first and every v1 business error looks
like a success; read only the body and a v2 503 looks like a valid response.

Nothing here judges permissions and nothing here caches `scopes`. The server
re-evaluates a key's scopes on every call (with a 3-second positive cache of its
own), so a CLI-side cache can only ever produce "the admin ticked the box but
the CLI still says no".
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from bisheng_cli import __version__
from bisheng_cli.errors import (
    EXIT_NOT_ENABLED,
    EXIT_PLATFORM_TOO_OLD,
    EXIT_UNREACHABLE,
    CliError,
    error_from_platform,
)
from bisheng_cli.output import Emitter

CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 60.0
# Deliberately below nginx's `proxy_read_timeout 300s`: the CLI has to be the one
# that gives up first, otherwise the user gets a 504 from a proxy they cannot see
# and no way to tell an upload problem from a platform problem.
UPLOAD_READ_TIMEOUT = 240.0
NGINX_PROXY_READ_TIMEOUT = 300.0

VERSIONS_PATH = "/api/v1/dev-toolkit/versions"
ENV_PATH = "/api/v1/env"

_PROXY_ENV_NAMES = ("ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "all_proxy", "https_proxy", "http_proxy")


@dataclass
class ProbeResult:
    """Outcome of the pre-flight `versions` probe."""

    versions: dict[str, Any]
    cli_min_compatible: str | None
    warning: str | None


def parse_envelope(resp: httpx.Response) -> Any:
    """Return `data`, or raise a translated CliError.

    Order matters — see the module docstring.
    """
    body: Any = None
    try:
        body = resp.json()
    except ValueError:
        body = None

    if isinstance(body, dict) and "status_code" in body:
        status_code = body.get("status_code")
        if isinstance(status_code, int) and status_code != 200:
            raise error_from_platform(
                status_code,
                str(body.get("status_message") or ""),
                http_status=resp.status_code,
                details=body.get("data"),
                hints=_hints_of(body.get("data")),
            )
        return body.get("data")

    if resp.status_code >= 400:
        raise error_from_platform(
            resp.status_code,
            _text_excerpt(resp),
            http_status=resp.status_code,
        )
    return body


def _hints_of(data: Any) -> list[str] | None:
    if isinstance(data, dict):
        hints = data.get("hints")
        if isinstance(hints, list):
            return [str(h) for h in hints]
    return None


def _text_excerpt(resp: httpx.Response) -> str:
    try:
        return resp.text[:200]
    except Exception:  # pragma: no cover - defensive
        return ""


class PlatformClient:
    """Thin httpx wrapper: base URL, bearer header, timeout tiers, envelopes."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        *,
        trust_env: bool = True,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
        emitter: Emitter | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.trust_env = trust_env
        self._read_timeout = timeout if timeout is not None else READ_TIMEOUT
        self.emitter = emitter
        self._client = httpx.Client(
            base_url=self.base_url,
            trust_env=trust_env,
            transport=transport,
            timeout=httpx.Timeout(self._read_timeout, connect=CONNECT_TIMEOUT),
            headers={"User-Agent": f"bisheng-cli/{__version__}"},
        )

    # ---- lifecycle ------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PlatformClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- requests -------------------------------------------------------

    def request(self, method: str, path: str, *, read_timeout: float | None = None, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        timeout = httpx.Timeout(
            read_timeout if read_timeout is not None else self._read_timeout, connect=CONNECT_TIMEOUT
        )
        started = time.monotonic()
        try:
            resp = self._client.request(method, path, headers=headers, timeout=timeout, **kwargs)
        except httpx.HTTPError as exc:
            raise self._connection_error(method, path, exc)
        if self.emitter is not None:
            elapsed = int((time.monotonic() - started) * 1000)
            self.emitter.debug(f"{method} {path} {resp.status_code} {elapsed}ms")
        return resp

    def get_json(self, path: str, **kwargs: Any) -> Any:
        return parse_envelope(self.request("GET", path, **kwargs))

    def post_json(self, path: str, **kwargs: Any) -> Any:
        return parse_envelope(self.request("POST", path, **kwargs))

    # ---- errors ---------------------------------------------------------

    def _connection_error(self, method: str, path: str, exc: httpx.HTTPError) -> CliError:
        """Turn a transport failure into something actionable.

        A developer machine usually has a proxy configured for the public
        internet while the platform lives on an intranet address. The symptom is
        "platform unreachable" while the platform is perfectly healthy, so the
        proxy variable is named in the message rather than left for the user to
        remember.
        """
        message = f"平台不可达（{method} {path}）：{exc.__class__.__name__}"
        proxies = [f"{name}={os.environ[name]}" for name in _PROXY_ENV_NAMES if os.environ.get(name)]
        if proxies and self.trust_env:
            next_step = (
                f"检测到代理环境变量 {', '.join(proxies)}；内网地址请加入 NO_PROXY，或改用 --no-proxy 直接绕过代理。"
            )
        else:
            next_step = "确认平台地址与网络连通性（内网地址是否需要 VPN），稍后重试。"
        return CliError(message, exit_code=EXIT_UNREACHABLE, next_step=next_step)


def probe(client: PlatformClient) -> ProbeResult:
    """Pre-flight: is this platform one this CLI can talk to at all?

    Three distinguishable outcomes, each with its own exit code, because the
    remedies have nothing in common: turn on a switch and restart (8), upgrade
    the platform or downgrade the CLI (9), fix the network (7).

    Once the probe decides the open-capability layer is absent it **returns by
    raising** — no credential is sent afterwards. That is how AC-05's "login is
    unusable in this environment" is honoured while `whoami` itself stays
    permanently registered on the server side.
    """
    resp = client.request("GET", VERSIONS_PATH)
    if resp.status_code != 404:
        versions = parse_envelope(resp)
        min_compatible = ((versions or {}).get("cli") or {}).get("min_compatible")
        warning = None
        if isinstance(min_compatible, str) and _version_tuple(min_compatible) > _version_tuple(__version__):
            download = ((versions or {}).get("cli") or {}).get("download_path") or "/api/v1/dev-toolkit/cli/download"
            warning = (
                f"平台要求的最低 CLI 版本是 {min_compatible}，本地是 {__version__}；"
                f"建议从 {client.base_url}{download} 下载新版。"
            )
            # Only a warning this round (design D11): blocking needs real
            # cross-version samples before it can be anything but noise.
            if client.emitter is not None:
                client.emitter.warn(warning)
        return ProbeResult(versions=versions or {}, cli_min_compatible=min_compatible, warning=warning)

    env = client.get_json(ENV_PATH)
    if isinstance(env, dict) and "open_platform_enabled" in env:
        if not env.get("open_platform_enabled"):
            raise CliError(
                "本环境未部署开放能力层，CLI 在这里不可用",
                exit_code=EXIT_NOT_ENABLED,
                next_step="请平台管理员打开 open_platform 开关并重启后端后再试。",
            )
        raise CliError(
            "平台版本过老，不提供 CLI 分发端点",
            exit_code=EXIT_PLATFORM_TOO_OLD,
            next_step="请升级平台，或改用与该平台同版本的 CLI。",
        )
    raise CliError(
        "平台版本过老，不支持本 CLI",
        exit_code=EXIT_PLATFORM_TOO_OLD,
        next_step="请升级平台，或改用与该平台同版本的 CLI。",
    )


def _version_tuple(raw: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in str(raw).split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)
