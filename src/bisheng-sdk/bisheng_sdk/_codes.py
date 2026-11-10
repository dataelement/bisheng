"""服务端错误码 → SDK 异常（design D6）。

**两张表，因为线上有两种错误信封**：

* backend（`/api/v1`、`/api/v2`）用 `{status_code: <int>, status_message, data}`，
  码是整数；
* runtime-manager 的附件 API 用 `{"detail": {"code": "<机器码>", "message", …}}`，
  码是字符串。

用一套解析会让 storage 的 401 / 413 / 404 全部落成"平台拒绝"、机器码丢失
（坑 26）。

**未登记的码永不吞掉**：两级降级——先按码查表，查不到按 HTTP 状态类兜底，
再兜不住就是 `PlatformRefusedError`，原样带上 code / message / details。
"""

from __future__ import annotations

from typing import Any

from bisheng_sdk import errors

# --- backend 业务码（int） -------------------------------------------------

#: 260 段：开放 API 鉴权。26001 缺凭据 / 26002 凭据无效 / 26027 服务账号被停用。
CREDENTIAL_REJECTED_CODES = frozenset({26001, 26002, 26027})

#: 263 段（F052 统一检索门面）：26320「无执行身份」。托管期它意味着平台没能从
#: `X-BiSheng-Access-Token` 确立访问用户——检索无访问用户一律拒绝，没有兜底身份。
RETRIEVAL_IDENTITY_MISSING_CODE = 26320

#: 26321「知识库不可及」——缺失 / 未授予 / 类型不支持 / 白名单外合并成一个码
#: （存在性不泄露），`data.unreachable_ids` 是不可及的标识。
TARGET_UNREACHABLE_CODES = frozenset({26321})

#: 26322：声明过的知识库没了（可与普通不可及区分，`data.knowledge_id`）。
KNOWLEDGE_CAPABILITY_REVOKED_CODE = 26322

#: 162 段（F055 能力总线）：16273 能力已收回 / 16274 能力未声明。
CAPABILITY_REVOKED_CODE = 16273
CAPABILITY_NOT_DECLARED_CODE = 16274

#: 26003 缺权限位（`data.required` 是**单个字符串**，不是列表）。
SCOPE_MISSING_CODE = 26003

#: 26030 凭据校验 / 权限评估依赖不可用。
PERMISSION_EVALUATION_CODES = frozenset({26030})


def map_error(
    code: int | None,
    message: str,
    *,
    http_status: int,
    data: Any = None,
) -> errors.BishengSdkError:
    """backend 信封 → 异常。"""
    details = data if isinstance(data, dict) else ({"data": data} if data is not None else None)
    payload = details or {}

    if code in CREDENTIAL_REJECTED_CODES or code == RETRIEVAL_IDENTITY_MISSING_CODE:
        return errors.VisitorCredentialRejectedError(message or None, code=code, details=details)
    if code == SCOPE_MISSING_CODE:
        required = payload.get("required")
        return errors.ScopeMissingError(
            required=required if isinstance(required, str) else "",
            code=code,
            details=details,
        )
    if code in TARGET_UNREACHABLE_CODES:
        ids = payload.get("unreachable_ids")
        return errors.TargetUnreachableError(ids if isinstance(ids, list) else [], code=code, details=details)
    if code == KNOWLEDGE_CAPABILITY_REVOKED_CODE:
        knowledge_id = payload.get("knowledge_id")
        return errors.CapabilityRevokedError(
            capability=str(knowledge_id) if knowledge_id is not None else None,
            reason="revoked",
            code=code,
            details=details,
        )
    if code == CAPABILITY_REVOKED_CODE:
        return errors.CapabilityRevokedError(
            capability=_text(payload.get("capability")),
            reason=_text(payload.get("reason")) or "revoked",
            code=code,
            details=details,
        )
    if code == CAPABILITY_NOT_DECLARED_CODE:
        return errors.CapabilityNotDeclaredError(
            capability=_text(payload.get("capability")), code=code, details=details
        )
    if code in PERMISSION_EVALUATION_CODES:
        return errors.PermissionEvaluationError(message or None, code=code, details=details)

    return _by_http_status(code, message, http_status=http_status, details=details)


def _by_http_status(
    code: int | None,
    message: str,
    *,
    http_status: int,
    details: Any,
) -> errors.BishengSdkError:
    if http_status == 401:
        return errors.VisitorCredentialRejectedError(message or None, code=code, details=details)
    if http_status >= 500:
        return errors.PlatformUnreachableError(
            message or f"平台返回 {http_status}",
            "稍后重试；持续如此请管理员查看平台日志",
            code=code,
            details=details,
        )
    return errors.PlatformRefusedError(message or None, code=code, details=details)


# --- runtime-manager 机器码（str） ----------------------------------------

STORAGE_UNAUTHORIZED = "unauthorized"
STORAGE_NOT_FOUND = "not_found"
STORAGE_INVALID_KEY = "invalid_object_key"
STORAGE_TOO_LARGE = "payload_too_large"
STORAGE_UNAVAILABLE = "storage_unavailable"


def map_storage_error(
    code: str | None,
    message: str,
    *,
    http_status: int,
    detail: Any = None,
    path: str = "",
) -> errors.BishengSdkError:
    """manager 信封 → 异常。

    **没有 403、也没有「应用已下线」专用码**：令牌不属本应用、应用已被销毁、
    根本没带 Bearer，全都是 401 `unauthorized`（坑 28）。AC-25 只要求这几类
    彼此可区分，因此归一到 `StorageHandleRejectedError`，原因放 `reason`。
    """
    payload = detail if isinstance(detail, dict) else {}

    if code == STORAGE_UNAUTHORIZED:
        return errors.StorageHandleRejectedError(reason=message, details=payload or None)
    if code == STORAGE_NOT_FOUND:
        return errors.AttachmentNotFoundError(path=path, details=payload or None)
    if code == STORAGE_INVALID_KEY:
        return errors.InvalidAttachmentPathError(path=path, reason=message, details=payload or None)
    if code == STORAGE_TOO_LARGE:
        max_file_mb = payload.get("max_file_mb")
        limit = (
            int(max_file_mb) * 1024 * 1024
            if isinstance(max_file_mb, (int, float, str)) and _numeric(max_file_mb)
            else None
        )
        return errors.AttachmentTooLargeError(path=path, limit_bytes=limit, details=payload or None)
    if code == STORAGE_UNAVAILABLE:
        return errors.StorageUnavailableError(message or None, details=payload or None)

    if http_status == 401:
        return errors.StorageHandleRejectedError(reason=message, details=payload or None)
    if http_status == 404:
        return errors.AttachmentNotFoundError(path=path, details=payload or None)
    if http_status >= 500:
        return errors.StorageUnavailableError(message or None, details=payload or None)
    return errors.PlatformRefusedError(message or None, code=None, details=payload or None)


def _numeric(value: Any) -> bool:
    try:
        int(value)
    except (TypeError, ValueError):
        return False
    return True


def _text(value: Any) -> str:
    return str(value) if value is not None else ""
