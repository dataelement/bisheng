"""异常层次：一个基类 + 按「应用的下一步动作」分格的子类（design D6）。

三条规则撑起本文件：

**一个异常，一个下一步。** 分格依据不是严重程度，而是应用（或读日志的人）接下来
该做什么。`VisitorCredentialMissingError`（这条路径根本不该调）与
`VisitorCredentialRejectedError`（让用户重新进入应用）严重程度相同、处置相反，
因此永远是两个类。

**未登记的错误绝不吞掉。** 平台答了一个本 SDK 不认识的业务码时，
`PlatformRefusedError` 原样带上 `code` / `message` / `details`——降级成一句
"平台拒绝了请求"会让排查从"查这个码"变成"猜"。

**凭据永不出现在任何字符串里。** `__str__` / `__repr__` 一律过 :func:`redact`，
`details` 里的令牌也一并掩掉（AC-04）。
"""

from __future__ import annotations

import re
from typing import Any

__all__ = (
    "AppCredentialMissingError",
    "AttachmentNotFoundError",
    "AttachmentTooLargeError",
    "BishengSdkError",
    "CapabilityNotDeclaredError",
    "CapabilityRevokedError",
    "InvalidAttachmentPathError",
    "PermissionEvaluationError",
    "PlatformIdentityMissingError",
    "PlatformRefusedError",
    "PlatformTooOldError",
    "PlatformUnreachableError",
    "ScopeMissingError",
    "SdkIncompatibleError",
    "StorageHandleMissingError",
    "StorageHandleRejectedError",
    "StorageUnavailableError",
    "TargetUnreachableError",
    "VisitorCredentialMissingError",
    "VisitorCredentialRejectedError",
    "redact",
)

# 掩码规则与 CLI `bisheng_cli.output._MASK_PATTERNS` 同源：两个平台凭据前缀
# （`bs-sak-` 服务账号密钥 / `bs-pat-` 个人访问令牌）、`Bearer <值>`、以及裸的
# JWT（app-proxy 注入的 OBO 令牌就是 `eyJ...` 开头的 JWT）。尾部贪婪是刻意的：
# 半截密钥仍是泄漏的密钥。
_MASK_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(bs-(?:sak|pat)-)[A-Za-z0-9_\-]+"), r"\1****"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-.]{8,}"), "Bearer ****"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{6,}(?:\.[A-Za-z0-9_-]+){0,2}"), "****"),
    # `bisheng dev` 的本地访问凭据句柄（`bsdev.<b64>.<hmac>`，F053 devproxy）。
    (re.compile(r"\bbsdev\.[A-Za-z0-9_\-.=]+"), "bsdev.****"),
)


def redact(text: str) -> str:
    """把任何凭据形态的子串换成掩码；用于一切离开本进程的字符串。"""
    result = str(text)
    for pattern, replacement in _MASK_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def _redact_value(value: Any) -> Any:
    """递归掩码：`details` 常常是服务端原样回传的字典，里面可能带令牌回显。"""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: _redact_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_redact_value(item) for item in value)
    return value


class BishengSdkError(Exception):
    """所有 SDK 异常的基类。

    `next_step` 不是可选的修辞——DEV-04 验收 7 的判据是「缺什么、怎么改」，
    一个只有 message 的异常把这件事留给了读堆栈的人。
    """

    def __init__(
        self,
        message: str,
        next_step: str,
        *,
        code: int | None = None,
        details: Any = None,
    ) -> None:
        self.message = redact(str(message))
        self.next_step = redact(str(next_step))
        self.code = code
        self.details = _redact_value(details)
        super().__init__(self.message)

    def __str__(self) -> str:
        return redact(f"{self.message}（下一步：{self.next_step}）")

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.__str__()!r})"


# ---------------------------------------------------------------------------
# auth / retrieve —— 身份与访问者凭据
# ---------------------------------------------------------------------------


class PlatformIdentityMissingError(BishengSdkError):
    """上下文里没有平台注入的身份（AC-07）。

    刻意不返回 None / 匿名身份：那会让应用写出 `if user is None: 匿名处理`，
    把静默失败点从「自建登录页」挪到「匿名兜底」，性质不变。
    """

    def __init__(self, message: str | None = None, next_step: str | None = None) -> None:
        super().__init__(
            message or "未取得平台注入的访问者身份",
            next_step
            or (
                "这条路径不应调用 auth（健康探活、后台任务、单元测试），"
                "或请求未经平台入口转发；本地开发请经 `bisheng dev` 启动应用"
            ),
        )


class VisitorCredentialMissingError(BishengSdkError):
    """retrieve 时上下文里没有访问者凭据（含根本没有请求上下文，AC-15）。"""

    def __init__(self, message: str | None = None, next_step: str | None = None) -> None:
        super().__init__(
            message or "当前请求上下文中没有平台注入的访问者凭据，检索不会以任何其它身份发起",
            next_step
            or (
                "经平台入口访问应用；后台任务没有访问者、按设计不能检索；"
                "线上另请管理员确认 `app_runtime.obo_secret` 已配置"
            ),
        )


class AppCredentialMissingError(BishengSdkError):
    """应用自身的运行期凭据（`BISHENG_APP_TOKEN`）未注入。

    托管期由平台在创建容器前注入（F055 能力总线）；`bisheng dev` 本地期今天
    不注入它，因此本地 retrieve 得到的是这条明确错误，而不是一次注定被拒的请求。
    """

    def __init__(self, message: str | None = None, next_step: str | None = None) -> None:
        super().__init__(
            message or "应用运行期凭据未注入，无法向平台证明「这次调用来自哪个应用」",
            next_step
            or (
                "托管运行期由平台注入，请确认实例是经平台发布上线的；"
                "本地 `bisheng dev` 期平台尚未注入该凭据，检索请在发布后用真实账号验证"
            ),
        )


class VisitorCredentialRejectedError(BishengSdkError):
    """平台拒绝了访问者凭据：过期、失效、或无法确立访问用户。"""

    def __init__(self, message: str | None = None, next_step: str | None = None, **kwargs: Any) -> None:
        super().__init__(
            message or "平台拒绝了本次调用的访问者凭据",
            next_step
            or (
                "让用户刷新页面重新进入应用；若应用刚下线或凭据已过期，重新上线后再试；仍被拒请确认平台已受理访问者凭据"
            ),
            **kwargs,
        )


class ScopeMissingError(BishengSdkError):
    """凭据缺某个权限位（服务端 26003，`data.required` 是**单个字符串**）。"""

    def __init__(self, required: str = "", **kwargs: Any) -> None:
        self.required = required
        super().__init__(
            f"调用所用的凭据缺少权限位「{required}」" if required else "调用所用的凭据缺少必需的权限位",
            f"请管理员给该密钥勾上「{required}」后重试" if required else "请管理员给该密钥补上所缺的权限位后重试",
            **kwargs,
        )


class TargetUnreachableError(BishengSdkError):
    """显式指定的知识库中有不可及的（缺失 / 未授予 / 类型不支持 / 白名单外）。

    整个请求被拒，而不是静默剔除后返回缩水结果——存在性不泄露，缩水结果也不该
    被当成"查过了"。
    """

    def __init__(self, ids: Any = None, **kwargs: Any) -> None:
        self.ids = list(ids or [])
        shown = "、".join(str(one) for one in self.ids)
        super().__init__(
            f"目标知识库不可及：{shown}" if shown else "指定的目标知识库不可及",
            "去掉不可及的知识库 id 后重试；托管运行期请确认它在应用的能力声明白名单内",
            **kwargs,
        )


class CapabilityRevokedError(BishengSdkError):
    """应用声明过的能力已被平台收回（服务端 16273 / 26322）。"""

    def __init__(self, capability: str | None = None, reason: str = "revoked", **kwargs: Any) -> None:
        self.capability = capability
        self.reason = reason
        super().__init__(
            f"能力「{capability}」已被收回（原因：{reason}）"
            if capability
            else f"应用声明的能力已被收回（原因：{reason}）",
            "请应用负责人重新声明该能力并发布，或联系管理员确认它为何消失",
            **kwargs,
        )


class CapabilityNotDeclaredError(BishengSdkError):
    """应用请求了它从未声明的能力（服务端 16274）。"""

    def __init__(self, capability: str | None = None, **kwargs: Any) -> None:
        self.capability = capability
        super().__init__(
            f"能力「{capability}」不在应用的能力声明中" if capability else "该能力不在应用的能力声明中",
            "在 `bisheng-app.yaml` 中声明后重新发布；应用已下线时同样会得到这条错误",
            **kwargs,
        )


class PermissionEvaluationError(BishengSdkError):
    """权限引擎不可用 / 评估失败（服务端 26030 等）。

    **不得**改小范围重试：那会把"判不了"变成"判成更少"，正是 GOV-05 fail-closed
    要挡住的事。
    """

    def __init__(self, message: str | None = None, next_step: str | None = None, **kwargs: Any) -> None:
        super().__init__(
            message or "平台的权限评估暂时不可用，本次检索未执行",
            next_step or "稍后重试；不要改小检索范围重试——那会得到一个不完整但看起来成功的结果",
            **kwargs,
        )


class PlatformRefusedError(BishengSdkError):
    """平台以一个本 SDK 未登记的业务码拒绝了请求——原样呈现，永不吞掉。"""

    def __init__(self, message: str | None = None, *, code: int | None = None, details: Any = None) -> None:
        super().__init__(
            message or "平台拒绝了本次请求",
            "按平台返回的说明处置；若这是一个应当被 SDK 识别的错误，请反馈该错误码",
            code=code,
            details=details,
        )


class PlatformUnreachableError(BishengSdkError):
    """连不上平台：网络、超时、无信封的 5xx，或平台地址根本没注入。"""

    def __init__(self, message: str | None = None, next_step: str | None = None, **kwargs: Any) -> None:
        super().__init__(
            message or "无法连接到平台",
            next_step or "检查平台地址与网络连通性后重试",
            **kwargs,
        )


class SdkIncompatibleError(BishengSdkError):
    """本 SDK 版本低于该平台声明的最低兼容版本（AC-03）。"""

    def __init__(self, sdk_version: str, min_compatible: str, platform_version: str | None = None) -> None:
        self.sdk_version = sdk_version
        self.min_compatible = min_compatible
        self.platform_version = platform_version
        platform = f"（平台版本 {platform_version}）" if platform_version else ""
        super().__init__(
            f"本地 bisheng-sdk 版本 {sdk_version} 低于该平台要求的最低兼容版本 {min_compatible}{platform}",
            "从当前平台重新获取 SDK（`/api/v1/dev-toolkit/simple/` 索引）并重新发布应用",
        )


class PlatformTooOldError(BishengSdkError):
    """平台没有 SDK 版本信息：版本过老，或开放能力层未部署。"""

    def __init__(self, message: str | None = None, next_step: str | None = None) -> None:
        super().__init__(
            message or "该平台未提供 SDK 版本信息",
            next_step or "升级平台，或确认平台已部署开放能力层（`open_platform` 开关）",
        )


# ---------------------------------------------------------------------------
# storage —— 附件空间
# ---------------------------------------------------------------------------


class StorageHandleMissingError(BishengSdkError):
    """取不到应用的附件存储句柄：未注入、不完整、或两种形态同时存在。"""

    def __init__(self, message: str | None = None, next_step: str | None = None) -> None:
        super().__init__(
            message or "未取得应用的附件存储句柄",
            next_step or ("托管运行期由平台注入，请确认实例是经平台发布上线的；本地开发请经 `bisheng dev` 启动应用"),
        )


class StorageHandleRejectedError(BishengSdkError):
    """附件服务拒绝了句柄（令牌不属本应用 / 应用已删除 / 未带凭据，恒 401）。"""

    def __init__(self, reason: str = "", **kwargs: Any) -> None:
        self.reason = redact(str(reason))
        super().__init__(
            f"附件存储拒绝了本应用的句柄：{self.reason}" if reason else "附件存储拒绝了本应用的句柄",
            "重新上线应用以取得新的句柄；仍被拒请联系平台管理员",
            **kwargs,
        )


class StorageUnavailableError(BishengSdkError):
    """附件服务不可用（对象存储未配置 / 不可达 / 连接失败）。"""

    def __init__(self, message: str | None = None, next_step: str | None = None, **kwargs: Any) -> None:
        super().__init__(
            message or "附件存储暂时不可用",
            next_step
            or (
                "稍后重试；请管理员查看运行环境状态中的 `attachment_storage` 自检项"
                "（`GET /v1/runtime/status` 的 preflight）"
            ),
            **kwargs,
        )


class AttachmentNotFoundError(BishengSdkError):
    """附件不存在。删除一个不存在的附件同样是这条错误，不是静默成功。"""

    def __init__(self, path: str = "", **kwargs: Any) -> None:
        self.path = path
        super().__init__(
            f"附件「{path}」不存在" if path else "附件不存在",
            "确认路径与大小写；用 `storage.list()` 查看当前应用附件空间内的文件",
            **kwargs,
        )


class AttachmentTooLargeError(BishengSdkError):
    """超过部署配置的单文件上限——拒绝，绝不截断写入。"""

    def __init__(self, path: str = "", limit_bytes: int | None = None, **kwargs: Any) -> None:
        self.path = path
        self.limit_bytes = limit_bytes
        limit = f"（单文件上限 {limit_bytes // (1024 * 1024)} MB）" if limit_bytes else ""
        super().__init__(
            f"附件「{path}」超过单文件上限{limit}" if path else f"附件超过单文件上限{limit}",
            "缩小文件或分成多个附件上传；上限由平台部署配置决定",
            **kwargs,
        )


class InvalidAttachmentPathError(BishengSdkError):
    """路径不是合法的应用内相对路径——拒绝，而不是规范化后放行。"""

    def __init__(self, path: str = "", reason: str = "", **kwargs: Any) -> None:
        self.path = path
        self.reason = reason
        detail = f"（{reason}）" if reason else ""
        super().__init__(
            f"附件路径「{path}」不合法{detail}",
            "用应用内相对路径，如 `报告/2026.pdf`；不要用绝对路径、`..`、反斜杠或 `apps/` 前缀",
            **kwargs,
        )
