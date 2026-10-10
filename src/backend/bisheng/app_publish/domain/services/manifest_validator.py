"""Parse and validate ``bisheng-app.yaml`` — the synchronous precheck leg (design D4 steps ① and ②).

Everything here is answerable **without an RPC**: YAML parsing, schema
validation, a local runtime enum, a local table lookup for the tier. That is
not a simplification, it is the whole point of design D1's choice C — this code
runs inside the ``POST /api/v2/apps/deploy`` request, so a single call to an
unreachable runtime-manager would turn "you forgot ``port``" from a 200 ms
answer into a request hanging on a timeout. The runtime is re-checked against
the manager in the asynchronous leg (``precheck_build``), which is the one
place a stale local enum can cost anything.

Order matters and is not arbitrary:

1. **YAML first, with ``safe_load``.** ``full_load`` constructs arbitrary Python
   objects — ``!!python/object/apply:os.system`` in a manifest is remote code
   execution against the platform, from an unprivileged developer's package.
2. **Secret references before the schema.** The capability sub-models forbid
   unknown keys, so a ``secret_ref:`` would otherwise come out as a generic
   "unknown field" 16221 and hide the actual answer, which is "this version
   does not support secret references" (AC-56 / 16230).
3. **``manifest_version`` before the schema**, for the same reason: a newer CLI
   writing keys this platform has never heard of must be told to upgrade the
   platform, not to delete its fields.
4. **WebSocket declarations after the version gate, still before the schema.**
   Same shape as (2) and the opposite answer to (3): no platform upgrade and no
   spelling of the key buys a WebSocket this version, because the entry closes
   the upgrade with 4501. "Unknown field ws_path, did you mean slug" would send
   the developer off to rename a key and ship an app whose sockets die silently
   in production.
5. Schema → runtime → capabilities → tier.

**Tier resolution is delegated, never re-implemented.** ``resolve_tier`` owns
the ``details.reason ∈ {not_found, disabled}`` verdict that AC-46 / AC-47 are
judged on; a second copy of "look it up, check ``enabled``, build a reason"
would diverge from it on exactly that field.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any

import yaml
from pydantic import ValidationError

from bisheng.app_publish.domain.schemas.app_manifest import (
    SUPPORTED_MANIFEST_VERSION,
    SUPPORTED_RUNTIMES,
    AppManifest,
)
from bisheng.app_publish.domain.services.resource_tier_service import ResourceTierService
from bisheng.common.errcode.app_publish import (
    AppCapabilityBusDisabledError,
    AppManifestInvalidError,
    AppRuntimeUnsupportedError,
    AppSecretReferenceUnsupportedError,
    AppWebSocketDeclarationError,
)
from bisheng.database.models.resource_tier import ResourceTier

#: Manifest file name, at the package root. Missing → 16203 (raised by the
#: package layer, which is the only place that knows what "root" is).
MANIFEST_FILENAME = "bisheng-app.yaml"

#: Keys that name a secret no matter what they hold, and value prefixes that
#: reference one. Deliberately narrow: matching on *values* that merely look
#: secret would reject ``description: "set your token in the console"``.
_SECRET_KEY_RE = re.compile(r"(?i)(secret|credential|password|passwd|token|api[_-]?key|private[_-]?key)")
_SECRET_VALUE_RE = re.compile(r"(?i)^(vault|secret|secretref|ssm|kms)://")

#: Keys that can only mean "this application wants the platform to serve it a
#: WebSocket". Matched on **key names only, and only inside the two closed key
#: sets** (top level and ``capabilities``, both ``extra="forbid"``): every other
#: place in a manifest holds user data — ``database.tables[*]`` is
#: ``extra="allow"`` — and a column named ``ws_state`` must not fail a publish.
#: Values are never matched either: ``description: "WebSocket 聊天室"`` is a
#: description, not a declaration.
#:
#: Outbound ``wss://`` in ``egress.domains`` is deliberately **not** matched.
#: The limitation lives on the inbound entry; an app that dials somebody else's
#: socket as a client is unaffected by it, and refusing that would be a lie.
_WEBSOCKET_KEY_RE = re.compile(
    r"(?i)^(wss?|websockets?|socketio|socket_io)(_[a-z0-9_]+)?$|^[a-z0-9_]+_(wss?|websockets?)$"
)

#: Hint for declared tables the platform will not create: ``schema_evolution_
#: service`` builds a migration plan only from tables that list ``columns``.
_TABLES_WITHOUT_COLUMNS_HINT = (
    "这些表没有写 columns, 平台不会替你建: {names}。补上 columns 由平台在上线时建表, "
    "或在应用内用 BISHENG_APP_DB_URL 自行 CREATE TABLE IF NOT EXISTS"
)


@dataclass(slots=True)
class ManifestValidation:
    """What the synchronous leg produces: the parsed manifest, its tier, and non-blocking advice."""

    manifest: AppManifest
    tier: ResourceTier
    hints: list[str] = field(default_factory=list)


async def validate_manifest(raw: str | bytes) -> ManifestValidation:
    """Full synchronous validation of a manifest body. Raises the 162xx that fits.

    Every raise carries ``details`` (machine-readable) and ``hints``
    (human-readable) so the caller can build AC-11's five-tuple with
    ``failure_from_error`` and never has to invent copy of its own.
    """
    document = _load_yaml(raw)
    _reject_secret_references(document)
    _check_manifest_version(document)
    _reject_websocket_declaration(document)
    manifest = _parse(document)
    _check_runtime(manifest)
    _check_capabilities(manifest)
    tier = await ResourceTierService.resolve_tier(manifest.tier)

    hints: list[str] = []
    bare = [table.name for table in manifest.database.tables if not table.columns]
    if bare:
        hints.append(_TABLES_WITHOUT_COLUMNS_HINT.format(names=", ".join(bare)))
    return ManifestValidation(manifest=manifest, tier=tier, hints=hints)


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def _load_yaml(raw: str | bytes) -> dict[str, Any]:
    """``yaml.safe_load`` only. See the module docstring for what ``full_load`` costs."""
    try:
        document = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise AppManifestInvalidError(
            msg=f"{MANIFEST_FILENAME} 不是合法的 YAML",
            details={"reason": "yaml_error", "errors": [{"field": MANIFEST_FILENAME, "reason": "yaml_error"}]},
            hints=[f"用 YAML 校验器检查 {MANIFEST_FILENAME}; 平台只接受纯数据标签, 不解析 !!python/ 标签"],
        ) from exc
    if not isinstance(document, dict):
        raise AppManifestInvalidError(
            msg=f"{MANIFEST_FILENAME} 必须是键值对",
            details={"reason": "not_a_mapping", "errors": [{"field": MANIFEST_FILENAME, "reason": "not_a_mapping"}]},
            hints=[f"{MANIFEST_FILENAME} 顶层需要 name / runtime / port 三个必填键"],
        )
    return document


def _reject_secret_references(document: dict[str, Any]) -> None:
    """AC-56 — any secret reference is refused in this version, with its own code."""
    hit = _find_secret_reference(document, path="")
    if hit is None:
        return
    raise AppSecretReferenceUnsupportedError(
        msg="本版不支持在应用声明中引用密钥",
        details={"field": hit, "reason": "secret_reference"},
        hints=["请移除密钥引用; 运行期凭据随能力总线波次提供, 当前版本不注入任何密钥"],
    )


def _find_secret_reference(node: Any, *, path: str) -> str | None:
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            if _SECRET_KEY_RE.search(str(key)):
                return child
            found = _find_secret_reference(value, path=child)
            if found is not None:
                return found
        return None
    if isinstance(node, list):
        for index, value in enumerate(node):
            found = _find_secret_reference(value, path=f"{path}[{index}]")
            if found is not None:
                return found
        return None
    if isinstance(node, str) and _SECRET_VALUE_RE.match(node):
        return path
    return None


def _reject_websocket_declaration(document: dict[str, Any]) -> None:
    """Refuse a manifest key that tries to declare a WebSocket (16232).

    The entry carries WebSocket upgrades for every app without any
    declaration. Caught here rather than left to the schema because the
    generic answer misleads: ``extra="forbid"`` turns ``ws_path:`` into
    "unknown field ws_path, did you mean slug", and the developer goes looking
    for the right spelling of a key that does not exist.
    """
    hit = _find_websocket_key(document)
    if hit is None:
        return
    raise AppWebSocketDeclarationError(
        msg="WebSocket 无需在 bisheng-app.yaml 里声明",
        details={"field": hit, "reason": "websocket_needs_no_declaration"},
        hints=[
            f"托管入口直接转发 WebSocket, 应用照常监听即可; 从 {MANIFEST_FILENAME} 删除该键后重新发布",
            "入口会在授权到期(close 4001)、权限收回或应用下线(4403)、发布或恢复中(4503)时关闭连接, "
            "前端要对任何 close 自动重连",
        ],
    )


def _find_websocket_key(document: dict[str, Any]) -> str | None:
    """The offending key path, or ``None``. Top level plus ``capabilities`` only."""
    for key in document:
        if _WEBSOCKET_KEY_RE.match(str(key)):
            return str(key)
    capabilities = document.get("capabilities")
    if isinstance(capabilities, dict):
        for key in capabilities:
            if _WEBSOCKET_KEY_RE.match(str(key)):
                return f"capabilities.{key}"
    return None


def _check_manifest_version(document: dict[str, Any]) -> None:
    """The forward-compatibility gate — "upgrade the platform", not "unknown field" (D3)."""
    declared = document.get("manifest_version", SUPPORTED_MANIFEST_VERSION)
    try:
        declared_int = int(declared)
    except (TypeError, ValueError):
        raise AppManifestInvalidError(
            msg="manifest_version 必须是整数",
            details={"field": "manifest_version", "value": declared, "reason": "not_an_integer"},
            hints=[f"本平台支持的 manifest_version 为 {SUPPORTED_MANIFEST_VERSION}"],
        ) from None
    if declared_int > SUPPORTED_MANIFEST_VERSION:
        raise AppManifestInvalidError(
            msg=f"manifest_version {declared_int} 高于本平台支持的 {SUPPORTED_MANIFEST_VERSION}",
            details={"field": "manifest_version", "value": declared_int, "reason": "ahead_of_platform"},
            hints=[
                f"请升级平台到支持 manifest_version {declared_int} 的版本, "
                f"或用 manifest_version {SUPPORTED_MANIFEST_VERSION} 的写法重写清单"
            ],
        )


def _parse(document: dict[str, Any]) -> AppManifest:
    """pydantic validation; ``ValidationError`` becomes ``details.errors`` verbatim (AC-11)."""
    try:
        return AppManifest.model_validate(document)
    except ValidationError as exc:
        errors = [_describe(item) for item in exc.errors()]
        raise AppManifestInvalidError(
            msg=f"{MANIFEST_FILENAME} 校验失败: " + "; ".join(item["message"] for item in errors),
            details={"errors": errors},
            hints=[f"必填项为 name / runtime / port; 未知字段一律拒绝, 请对照 {MANIFEST_FILENAME} 字段表"],
        ) from exc


def _describe(item: dict[str, Any]) -> dict[str, Any]:
    """One pydantic error → ``{field, reason, message[, suggestion]}``.

    ``extra_forbidden`` gets a "did you mean" from ``difflib`` — no new
    dependency, and a typo'd key is the single most common manifest mistake.
    """
    location = ".".join(str(part) for part in item.get("loc", ()) if part != "__root__")
    kind = str(item.get("type", "invalid"))
    reason = {"missing": "missing", "extra_forbidden": "unknown_field"}.get(kind, kind)
    described: dict[str, Any] = {
        "field": location or MANIFEST_FILENAME,
        "reason": reason,
        "message": str(item.get("msg", "")),
    }
    if reason == "unknown_field":
        candidates = difflib.get_close_matches(location, list(AppManifest.model_fields), n=1, cutoff=0.6)
        if candidates:
            described["suggestion"] = candidates[0]
            described["message"] = f"未知字段 {location}, 是不是想写 {candidates[0]}"
    return described


def _check_runtime(manifest: AppManifest) -> None:
    """Local enum only — the manager's own list is re-checked in ``precheck_build`` (D4)."""
    if manifest.runtime in SUPPORTED_RUNTIMES:
        return
    raise AppRuntimeUnsupportedError(
        msg=f"运行时 {manifest.runtime} 不受支持",
        details={"field": "runtime", "value": manifest.runtime, "reason": "not_supported"},
        hints=[f"本部署支持的运行时: {', '.join(SUPPORTED_RUNTIMES)}"],
    )


def _check_capabilities(manifest: AppManifest) -> None:
    """Refuse a declaration this deployment cannot actually honour (design D16).

    The bus itself is no longer a wave gate — it ships. What is still a
    deployment fact is whether the open-API scopes a declaration derives can be
    **issued** here: ``model:invoke`` sits behind ``open_platform.enabled``, so
    on a deployment without it a declared model would be published into an
    application whose every model call answers 403, with nothing anywhere saying
    why. Refused up front instead, which is the same reasoning that made a
    declaration refused rather than silently dropped in the first place.

    Reference resolution (does this model exist, is this knowledge base of a
    retrievable type) is a database question and lives in
    ``capability_bus_service.validate_capability_refs``, called by the receive
    leg once the application's tenant and owner are known.
    """
    if manifest.capabilities.is_empty():
        return
    from bisheng.app_publish.domain.services.capability_bus_service import undeployable_scopes

    refused = undeployable_scopes(manifest.capabilities)
    if not refused:
        return
    raise AppCapabilityBusDisabledError(
        msg="本环境未开放能力声明所需的开放能力位, 暂不支持该 capabilities 声明",
        details={
            "field": "capabilities",
            "reason": "capability_scope_not_deployed",
            "scopes": refused,
            "declared": {
                "models": [ref.name for ref in manifest.capabilities.models],
                "knowledge_bases": [ref.id or ref.name for ref in manifest.capabilities.knowledge_bases],
            },
        },
        hints=[
            "请管理员在部署配置中开启 open_platform 后重新发布",
            "或先从 bisheng-app.yaml 移除对应的能力声明",
        ],
    )
