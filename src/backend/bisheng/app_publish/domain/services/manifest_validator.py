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
4. Schema → runtime → capabilities → tier.

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

#: Hint attached to a declared-but-not-created table set (design D3).
_DATABASE_TABLES_HINT = (
    "本环境暂不由平台建表: 请在应用内用 BISHENG_APP_DB_URL 连接自带数据库并自行 CREATE TABLE IF NOT EXISTS"
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
    manifest = _parse(document)
    _check_runtime(manifest)
    _check_capabilities(manifest)
    tier = await ResourceTierService.resolve_tier(manifest.tier)

    hints: list[str] = []
    if manifest.database.tables:
        hints.append(_DATABASE_TABLES_HINT)
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
    """Refused, not silently dropped (design D16) — see the errcode module for why."""
    if manifest.capabilities.is_empty():
        return
    raise AppCapabilityBusDisabledError(
        msg="本环境未启用能力总线, 暂不支持 capabilities 声明",
        details={
            "field": "capabilities",
            "reason": "capability_bus_disabled",
            "declared": {
                "models": [ref.name for ref in manifest.capabilities.models],
                "knowledge_bases": [ref.id or ref.name for ref in manifest.capabilities.knowledge_bases],
            },
        },
        hints=["请从 bisheng-app.yaml 移除 capabilities 声明后重新发布; 能力总线随后续波次开放"],
    )
