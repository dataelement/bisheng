"""Hosted precheck — the asynchronous leg: dependency build and startup probe (design D4).

The precheck is a **linear fail-fast** chain, split across two legs:

* **Synchronous leg** (``manifest_validator``, runs inside the deploy request):
  YAML, schema, local reference checks. No RPC at all — a single call to an
  unreachable runtime-manager there would turn every "you forgot ``port``" into
  a request hanging on a socket timeout, which is the failure mode design D1
  picked its shape to avoid.
* **Asynchronous leg** (this module, runs on the Celery worker):
  ``precheck_build`` then ``precheck_probe``. Minutes, not milliseconds.

Consequences worth stating out loud:

* **The runtime re-check lives here, not in the manifest stage.** The schema's
  ``SUPPORTED_RUNTIMES`` is a local *copy* of the manager's list; this is where
  the two are intersected, at the start of the build, before anything is
  spent.
* **Upstream 161xx becomes 162xx, and says where it came from.** F054's
  ``orchestrator_client`` raises the runtime layer's codes; the CLI branches on
  the *publish* codes. The mapping is by stage, with ``details.upstream_code``
  carrying the original — so "the build failed" and "the manager was down" are
  the same code with different, visible causes.
* **Capacity shortage is 16226. Never 16225.** ``16225`` means "this deployment
  never seeded the approval scenario". The remedies are "wait for memory" and
  "ask an administrator to seed a scenario"; merging them guarantees one of the
  two copy strings is wrong wherever it is shown.
* **AC-08 is judged by a failed start, not by static analysis.** Reading
  ``requirements.txt`` to guess whether an app talks to its own MySQL is
  guesswork; an app that cannot reach its self-hosted database does not become
  ready, and the probe failure carries the hosting-contract guidance in
  ``hints``.

Everything reaches runtime-manager through F054's ``orchestrator_client``
facade — backend has no docker dependency of its own (arch-guard RULE-10).
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from bisheng.app_publish.domain.models.app_deployment import AppDeployment
from bisheng.app_publish.domain.schemas.app_manifest import AppManifest
from bisheng.app_publish.domain.services.package_service import APPS_BUCKET
from bisheng.common.errcode.app_publish import (
    AppCapacityInsufficientError,
    AppDependencyBuildFailedError,
    AppRuntimeUnsupportedError,
    AppStartupProbeFailedError,
)
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.core.database import get_async_db_session
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.database.models.app import AppDao
from bisheng.database.models.app_version import AppVersionDao
from bisheng.database.models.resource_tier import ResourceTier

#: Polling cadence for ``GET /v1/builds/{id}``. The manager's build is minutes
#: long; the interval only decides how quickly the *end* is noticed.
BUILD_POLL_INTERVAL_SECONDS = 2.0
BUILD_POLL_TIMEOUT_SECONDS = 1800.0

#: Lifetime of the presigned ``code_url`` handed to the manager. Long enough for
#: a slow build to start, short enough that a leaked intent payload is stale.
CODE_URL_EXPIRE_DAYS = 1

#: F054 runtime-layer codes this module translates (contract §3).
UPSTREAM_CAPACITY = 16125
UPSTREAM_UNSUPPORTED_RUNTIME = 16123

#: Guidance attached to every probe failure — AC-08's remedy, in the words the
#: hosting contract uses.
PROBE_HINTS: tuple[str, ...] = (
    "平台不提供自带数据库 / 消息队列 / 缓存: 应用要连的中间件不会在托管环境里存在",
    "数据请改接平台应用数据库: 读环境变量 BISHENG_APP_DB_URL 连接, 应用内自行建表",
    "确认应用监听 bisheng-app.yaml 里声明的 port, 且监听地址是 0.0.0.0 而不是 127.0.0.1",
    "本地用 bisheng dev 复现: 它注入与线上同名的环境变量",
)


def _client():
    """F054's orchestrator facade, imported at call time.

    Late import on purpose: it keeps this module importable (and the whole
    publish pipeline unit-testable) while F054's service layer is still in
    flight, and it is the seam the tests replace.
    """
    from bisheng.app_runtime.domain.services.orchestrator_client import orchestrator_client

    return orchestrator_client


def tier_payload(tier: ResourceTier) -> dict[str, Any]:
    """The ``tier`` shape runtime-manager speaks: vCPU float + MiB int (contract §2).

    The table stores integer millicores (design D11); this is the only place the
    conversion back happens, so a float can never round-trip through the DB.
    """
    return {"cpu": tier.cpu_millicores / 1000, "mem": tier.memory_mb}


# ---------------------------------------------------------------------------
# Stage ③ — dependency build
# ---------------------------------------------------------------------------


async def precheck_build(
    deployment: AppDeployment,
    *,
    manifest: AppManifest,
    tier: ResourceTier,
    poll_interval: float = BUILD_POLL_INTERVAL_SECONDS,
    timeout: float = BUILD_POLL_TIMEOUT_SECONDS,
) -> str:
    """Re-check the runtime, build the image, wait for the result. Returns ``image_ref``."""
    client = _client()

    try:
        runtime_status = await client.runtime_status()
    except BaseErrorCode as exc:
        raise _as_build_failure(exc, "无法连接运行环境管理器") from exc

    supported = list(runtime_status.get("supported_runtimes") or [])
    if manifest.runtime not in supported:
        raise AppRuntimeUnsupportedError(
            msg=f"运行时 {manifest.runtime} 在本环境不可用",
            details={
                "field": "runtime",
                "value": manifest.runtime,
                "reason": "not_supported_by_manager",
                "supported_runtimes": supported,
            },
            hints=[f"本环境当前支持的运行时: {', '.join(supported) or '(无)'}"],
        )

    code_url = await _presign(deployment.code_object_key)
    slug, version_no = await _build_identity(deployment, manifest)
    payload = {
        "app_id": deployment.app_id,
        "version_id": deployment.version_id,
        "slug": slug,
        "version_no": version_no,
        "runtime": manifest.runtime,
        "port": manifest.port,
        "code_url": code_url,
        "code_object_key": deployment.code_object_key,
        "tier": tier_payload(tier),
    }
    try:
        started = await client.build(**payload)
    except BaseErrorCode as exc:
        raise _as_build_failure(exc, "构建请求被拒绝") from exc

    build_id = started.get("build_id")
    return await _await_build(client, build_id, poll_interval=poll_interval, timeout=timeout)


async def _await_build(client, build_id: str, *, poll_interval: float, timeout: float) -> str:
    """Poll ``GET /v1/builds/{id}`` until it settles. The first look happens immediately."""
    waited = 0.0
    while True:
        try:
            status = await client.build_status(build_id=build_id)
        except BaseErrorCode as exc:
            raise _as_build_failure(exc, "无法获取构建状态") from exc

        state = str(status.get("status") or "")
        if state == "succeeded":
            image_ref = status.get("image_ref")
            if not image_ref:
                raise AppDependencyBuildFailedError(
                    msg="构建成功但未返回镜像标识",
                    details={"reason": "missing_image_ref", "build_id": build_id},
                    hints=["请联系管理员查看 runtime-manager 日志"],
                )
            return str(image_ref)
        if state == "failed":
            tail = status.get("tail") or []
            raise AppDependencyBuildFailedError(
                msg=f"依赖构建失败: {status.get('message') or ''}".strip(),
                details={
                    "reason": "build_failed",
                    "build_id": build_id,
                    "build_stage": status.get("stage"),
                    "tail": list(tail) if isinstance(tail, (list, tuple)) else [str(tail)],
                },
                hints=[
                    "按下面的构建日志尾部定位失败的依赖, 修好 requirements.txt 后重新 bisheng deploy",
                    "私有源 / 离线环境请与管理员确认构建镜像源配置",
                ],
            )

        if waited >= timeout:
            raise AppDependencyBuildFailedError(
                msg=f"依赖构建超时({int(timeout)}s)",
                details={"reason": "build_timeout", "build_id": build_id, "last_stage": status.get("stage")},
                hints=["依赖过多或网络缓慢会导致构建超时, 可精简 requirements.txt 后重试"],
            )
        await asyncio.sleep(poll_interval)
        waited += poll_interval


# ---------------------------------------------------------------------------
# Stage ④ — startup probe
# ---------------------------------------------------------------------------


async def precheck_probe(deployment: AppDeployment, *, manifest: AppManifest, image_ref: str) -> None:
    """Start the built image in a throw-away form and require it to become ready.

    ``probe`` is called with ``image_ref`` rather than ``app_id`` (contract §2):
    naming the app would consume the real instance slot and, for an iteration,
    disturb the version that is currently serving traffic.
    """
    client = _client()
    payload = {
        "image_ref": image_ref,
        "port": manifest.port,
        "env": {"PORT": str(manifest.port), "BISHENG_APP_PORT": str(manifest.port)},
        "health": {"path": "/", "interval": 10, "timeout": 5, "retries": 3, "start_period": 20},
    }
    try:
        result = await client.probe(**payload)
    except BaseErrorCode as exc:
        raise _as_probe_failure(exc, "启动探活失败") from exc

    if result.get("ready"):
        return
    raise AppStartupProbeFailedError(
        msg=f"应用启动探活失败: {result.get('reason') or ''}".strip(),
        details={"reason": "probe_not_ready", "probe_reason": result.get("reason"), "port": manifest.port},
        hints=list(PROBE_HINTS),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _presign(object_key: str | None) -> str:
    """A presigned download URL for the snapshot — the manager holds no MinIO credentials.

    ``clear_host=False`` is essential: ``get_share_link`` defaults to stripping
    the scheme+host so a browser fetches through the frontend nginx proxy, but
    this URL is consumed by runtime-manager **server-to-server**. A host-less,
    scheme-less path makes its HTTP client reject the fetch ("Request URL is
    missing an 'http://' or 'https://' protocol") and the build fails at
    ``fetch_source`` with 16227.
    """
    storage = await get_minio_storage()
    return await storage.get_share_link(
        object_key, bucket=APPS_BUCKET, clear_host=False, expire_days=CODE_URL_EXPIRE_DAYS
    )


async def _build_identity(deployment: AppDeployment, manifest: AppManifest) -> tuple[str, int]:
    """``slug`` and the version number this build will belong to.

    The version row does not exist yet (it is written after the approval gate,
    design D6), so the number is the next one — the same value
    ``VersionService`` will compute, derived from the same query.
    """
    async with get_async_db_session() as session:
        app_row = await AppDao.aget(session, deployment.app_id)
        previous = await AppVersionDao.amax_version_no(session, deployment.app_id)
    slug = (app_row.slug if app_row is not None else None) or manifest.slug or manifest.name
    return slug, previous + 1


def _as_build_failure(exc: BaseErrorCode, message: str) -> BaseErrorCode:
    """Translate a runtime-layer error raised during the build stage."""
    upstream = int(getattr(exc, "code", 0) or 0)
    if upstream == UPSTREAM_CAPACITY:
        return AppCapacityInsufficientError(
            msg="运行环境容量不足, 暂时无法构建",
            details={"reason": "capacity_exhausted", "upstream_code": upstream, "upstream_message": str(exc)},
            hints=["稍后重试, 或请管理员下线暂时不用的应用释放资源", "也可以先选更低的资源档位再发布"],
        )
    if upstream == UPSTREAM_UNSUPPORTED_RUNTIME:
        return AppRuntimeUnsupportedError(
            msg="运行时不受支持",
            details={"field": "runtime", "reason": "not_supported_by_manager", "upstream_code": upstream},
            hints=["请改用本环境支持的运行时后重新发布"],
        )
    logger.warning(f"app_publish.precheck_build upstream_code={upstream} message={exc}")
    return AppDependencyBuildFailedError(
        msg=f"{message}: {exc}",
        details={"reason": "upstream_error", "upstream_code": upstream, "upstream_message": str(exc)},
        hints=["请联系管理员确认运行环境管理器状态(超管「运行环境状态」页)"],
    )


def _as_probe_failure(exc: BaseErrorCode, message: str) -> BaseErrorCode:
    """Translate a runtime-layer error raised during the probe stage."""
    upstream = int(getattr(exc, "code", 0) or 0)
    if upstream == UPSTREAM_CAPACITY:
        return AppCapacityInsufficientError(
            msg="运行环境容量不足, 暂时无法启动探活",
            details={"reason": "capacity_exhausted", "upstream_code": upstream},
            hints=["稍后重试, 或请管理员释放资源后重新发布"],
        )
    return AppStartupProbeFailedError(
        msg=f"{message}: {exc}",
        details={"reason": "upstream_error", "upstream_code": upstream, "upstream_message": str(exc)},
        hints=list(PROBE_HINTS),
    )
