"""Exit codes and the translation layer on top of the platform's error codes.

Three ideas hold this file together.

**One code, one next action.** The exit-code table is partitioned by what the
caller does next, not by severity. `16225` ("the platform never seeded the
approval scene — go find an administrator, editing your code will not help") and
`16226` ("the box is out of capacity — wait, or have the owner publish manually")
are the canonical example: identical severity, opposite responses, so they get
13 and 14 and must never be merged back together.

**Three parts, always.** Every failure prints the platform's raw `code`, one
sentence of Chinese explaining it, and a concrete next step. Dropping the raw
code makes support unable to place the failure; dropping the sentence leaves a
number; dropping the next step leaves the agent with nothing to act on.

**Unknown is neither crash nor success.** An unregistered code degrades in two
stages — first by HTTP status class (a 503 is "the platform is briefly down",
whatever the code says), then to exit 19 which prints the code and message
verbatim. It must never land on exit 1, which means "the CLI itself broke".
"""

from __future__ import annotations

from typing import Any

from bisheng_cli.output import mask

# ---- exit codes ---------------------------------------------------------

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_USAGE = 2
EXIT_NOT_LOGGED_IN = 3
EXIT_AUTH = 4
EXIT_FORBIDDEN = 5
EXIT_LOCAL_INVALID = 6
EXIT_UNREACHABLE = 7
EXIT_NOT_ENABLED = 8
EXIT_PLATFORM_TOO_OLD = 9
EXIT_PRECHECK_FAILED = 10
EXIT_SECRET_FOUND = 11
EXIT_PUBLISH_CONFLICT = 12
EXIT_SCENE_MISSING = 13
EXIT_CAPACITY = 14
# 18 = a defect on either side of the contract. It is separate from 1 and from
# 19 because the *action* differs, and the action is the whole point of this
# table: on 1 (the CLI crashed) retrying once is reasonable; on 19 (a code we
# have no entry for) the caller reads the message and may retry with different
# arguments; on 18 both retrying and changing arguments are guaranteed useless
# — the only correct move is to stop and file the defect. Folding it into 19
# would also mislabel it: 19 says "unregistered code", and 26004 / 26031 are
# codes we know exactly.
EXIT_DEFECT = 18
EXIT_UNKNOWN_CODE = 19
EXIT_REJECTED = 20
EXIT_WITHDRAWN = 21
EXIT_PENDING_ONLINE = 22
EXIT_WAIT_TIMEOUT = 23
EXIT_CANCELLED = 24
EXIT_APPROVAL_EXCEPTION = 25

# ---- code → (sentence, next step) --------------------------------------

ERROR_HINTS: dict[int, tuple[str, str]] = {
    # --- F049, 260 segment: credential and scope ---
    26001: (
        "请求没有携带可识别的 Authorization 头",
        "检查密钥的传法：--api-key、环境变量 BISHENG_API_KEY 或 --api-key-stdin，值需是完整的 bs-sak- 开头字符串。",
    ),
    26002: (
        "平台不接受这把密钥（不存在、已撤销或已过期——平台不区分这三种成因）",
        "请平台管理员在服务账号详情页重新签发一把密钥，或改用另一把仍然有效的密钥。",
    ),
    26027: (
        "密钥所属的服务账号已被停用或删除",
        "请平台管理员启用该服务账号；换一把密钥没有用，问题在账号本身。",
    ),
    26003: (
        "这把密钥缺少本次操作需要的权限位",
        "请平台管理员在服务账号详情页编辑该密钥、补勾所缺权限位后重试（无需重新签发）。",
    ),
    26004: (
        "请求携带了身份传递头，而 CLI 从不发送这两个头——这是 CLI 缺陷",
        "请连同 --verbose 输出一起报 CLI 故障；不要改密钥或权限位，方向是错的。",
    ),
    26030: (
        "平台鉴权服务暂时不可用（fail-closed，与密钥无关），可重试",
        "稍等片刻后重跑同一条命令；持续不恢复再联系平台管理员。",
    ),
    26031: (
        "平台端点缺少权限位标记，这是平台缺陷",
        "请报平台故障并附上失败的命令与时间；CLI 侧无可修改项。",
    ),
    # --- F054, 161 segment: orchestrator ---
    16101: (
        "平台上找不到这个应用",
        "确认 --app-id 是否写错，或该应用是否已被删除；必要时删掉 .bisheng/app.json 里的过期标识重新首发。",
    ),
    16121: (
        "编排器不可用（容器守护进程或 runtime-manager 不可达），可重试",
        "稍后重试；持续不恢复请联系运维检查 runtime-manager 与 dockerd。注意这不代表应用实例不存在。",
    ),
    # --- F055, 162 segment: receive gates (synchronous leg of POST /deploy) ---
    16201: (
        "上传包超过平台配置的体量上限",
        "先看忽略统计里排除了多少，再按 Top 10 大文件清理；仍不够就请运维调整 app_runtime.max_package_mb。",
    ),
    16202: (
        "平台无法解包，或包内含非法路径条目",
        "重新执行 deploy 生成包；若持续失败，用 --dry-run 检查是否有符号链接、设备文件或越界路径。",
    ),
    16203: (
        "包根里没有 bisheng-app.yaml",
        "检查 deploy 的 PATH 参数与包根是否一致——本地校验已经过了，说明上传的包根不是项目根。",
    ),
    16205: (
        "这个应用归属于别人，当前密钥的资源归属人无权操作",
        "改用资源归属人正确的那把密钥；应用归属不因任何请求头改变。",
    ),
    16207: (
        "本环境未启用应用工场运行时层",
        "请平台管理员打开 app_runtime 开关并重启后端；开关未开时 deploy / logs 都不可用。",
    ),
    # --- F055, 162 segment: hosted precheck ---
    16221: (
        "应用声明（bisheng-app.yaml）未通过平台校验",
        "按 details 指出的字段补齐或修正 bisheng-app.yaml 后重新 deploy。",
    ),
    16222: (
        "声明的 runtime 平台不支持",
        "把 bisheng-app.yaml 的 runtime 改成 details/hints 里列出的受支持取值之一。",
    ),
    16223: (
        "声明的资源档位不存在或已停用",
        "改用平台当前提供的档位；不确定就先删掉 tier 让平台取默认值。",
    ),
    16224: (
        "能力声明无法解析",
        "修正 bisheng-app.yaml 里 capabilities 段的写法后重发。",
    ),
    16227: (
        "依赖构建失败",
        "按 details/hints 里的构建日志片段修依赖清单（requirements.txt / package.json）后重发。",
    ),
    16228: (
        "应用启动探活失败",
        "确认应用在声明的端口上监听、entrypoint 可执行；本地跑通后再重发。",
    ),
    16230: (
        "能力声明里含密钥引用",
        "从 bisheng-app.yaml 的 capabilities 段删除密钥引用后重发；密钥由平台注入，不写进声明。",
    ),
    16231: (
        "本环境未启用能力总线",
        "本版本不支持能力声明，请从 bisheng-app.yaml 删除 capabilities 段后重发。",
    ),
    16232: (
        "本版托管运行时不支持 WebSocket",
        "删掉声明里的 WebSocket 键；服务端推送改用 SSE 或轮询——托管入口会直接关闭 WS 握手（close 4501），本地连得上不代表线上连得上。",
    ),
    16241: (
        "安全扫描在包内命中了疑似密钥",
        "按输出里的 文件:行号 移除密钥、改用环境变量引用后重发；平台不会回显命中的值。",
    ),
    # --- F055, 162 segment: publish-flow conflicts ---
    16225: (
        "平台没有配置发布审批场景",
        "请平台管理员补齐发布审批场景配置；改代码或改声明都没有用。",
    ),
    16226: (
        "运行环境容量不足",
        "等资源释放后重试，或让应用归属人在应用详情页·发布手动上线。",
    ),
    16229: (
        "本次发布包含未确认的结构变更",
        "确认变更影响后带上 --confirm-schema-change 重发。",
    ),
    16251: (
        "该应用已有在途的发布审批单",
        "先在应用详情页·发布撤回在途单，再重新 deploy；CLI 不提供撤回命令。",
    ),
    16252: (
        "该应用处于待上线状态",
        "先在应用详情页·发布完成或放弃这次上线，再重新 deploy。",
    ),
    16254: (
        "该操作仅限应用归属人执行",
        "改用资源归属人是该应用 owner 的那把密钥。",
    ),
}

ERROR_EXIT_CODES: dict[int, int] = {
    26001: EXIT_AUTH,
    26002: EXIT_AUTH,
    26027: EXIT_AUTH,
    26003: EXIT_FORBIDDEN,
    # Both sides of the defect class land on 18 (see its definition above): the
    # CLI sent something it should never send, or the platform is missing a
    # scope marking. Neither is anything the caller did or can fix.
    26004: EXIT_DEFECT,
    26030: EXIT_UNREACHABLE,
    26031: EXIT_DEFECT,
    16101: EXIT_LOCAL_INVALID,
    16121: EXIT_UNREACHABLE,
    16201: EXIT_LOCAL_INVALID,
    16202: EXIT_LOCAL_INVALID,
    16203: EXIT_LOCAL_INVALID,
    16205: EXIT_PUBLISH_CONFLICT,
    16207: EXIT_NOT_ENABLED,
    16221: EXIT_PRECHECK_FAILED,
    16222: EXIT_PRECHECK_FAILED,
    16223: EXIT_PRECHECK_FAILED,
    16224: EXIT_PRECHECK_FAILED,
    16227: EXIT_PRECHECK_FAILED,
    16228: EXIT_PRECHECK_FAILED,
    16230: EXIT_PRECHECK_FAILED,
    16231: EXIT_PRECHECK_FAILED,
    16232: EXIT_PRECHECK_FAILED,
    16241: EXIT_SECRET_FOUND,
    16225: EXIT_SCENE_MISSING,
    16226: EXIT_CAPACITY,
    16229: EXIT_PUBLISH_CONFLICT,
    16251: EXIT_PUBLISH_CONFLICT,
    16252: EXIT_PUBLISH_CONFLICT,
    16254: EXIT_PUBLISH_CONFLICT,
}

# Unregistered codes degrade by HTTP status class before falling to exit 19.
_HTTP_STATUS_FALLBACK: dict[int, int] = {
    401: EXIT_AUTH,
    403: EXIT_FORBIDDEN,
    502: EXIT_UNREACHABLE,
    503: EXIT_UNREACHABLE,
    504: EXIT_UNREACHABLE,
}


class CliError(Exception):
    """A failure with a decided exit code and something to say about it."""

    def __init__(
        self,
        message: str,
        *,
        exit_code: int = EXIT_INTERNAL,
        code: int | None = None,
        next_step: str = "",
        platform_message: str = "",
        details: Any = None,
        hints: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code
        self.code = code
        self.next_step = next_step
        self.platform_message = platform_message
        self.details = details
        self.hints = hints or []

    def as_failure(self, stage: str | None = None) -> dict[str, Any]:
        """The machine-readable five-tuple.

        `details` and `hints` go through untouched: they are the entire input a
        local agent has for repairing the failure automatically.
        """
        return {
            "stage": stage,
            "code": self.code,
            "message": self.platform_message or self.message,
            "details": self.details,
            "hints": self.hints,
        }


def error_from_platform(
    code: int,
    message: str = "",
    *,
    http_status: int | None = None,
    details: Any = None,
    hints: list[str] | None = None,
) -> CliError:
    """Translate a platform error code into a CliError."""
    hint = ERROR_HINTS.get(code)
    if hint is not None:
        human, next_step = hint
        next_step = _augment_next_step(code, next_step, details)
        return CliError(
            human,
            exit_code=ERROR_EXIT_CODES[code],
            code=code,
            next_step=next_step,
            platform_message=message,
            details=details,
            hints=hints,
        )

    exit_code = _HTTP_STATUS_FALLBACK.get(http_status or 0, EXIT_UNKNOWN_CODE)
    if exit_code == EXIT_UNREACHABLE:
        human = f"平台暂时不可用（HTTP {http_status}），可重试"
        next_step = "稍后重跑同一条命令；持续不恢复请联系平台管理员。"
    elif exit_code == EXIT_AUTH:
        human = f"平台拒绝了这次鉴权（HTTP {http_status}）"
        next_step = "检查密钥是否有效、是否已过期或被撤销。"
    elif exit_code == EXIT_FORBIDDEN:
        human = f"平台以权限不足拒绝了这次请求（HTTP {http_status}）"
        next_step = "请平台管理员核对该密钥的权限位。"
    else:
        human = f"平台返回未登记的错误码 {code}"
        next_step = "按平台给出的信息处置；若无法判断，请把该错误码报给平台支持。"
    return CliError(
        human,
        exit_code=exit_code,
        code=code,
        next_step=next_step,
        platform_message=message,
        details=details,
        hints=hints,
    )


def _augment_next_step(code: int, next_step: str, details: Any) -> str:
    """Fold code-specific payload fields into the next step.

    Only `26003` needs this today: naming the missing scope verbatim is the
    difference between "ask your admin for permissions" and an admin who knows
    which checkbox to tick.
    """
    if code == 26003 and isinstance(details, dict):
        required = details.get("required")
        # A single string, not a list (OpenApiScopeMissingError(required: str)).
        if isinstance(required, str) and required:
            return f"该密钥缺少权限位 {required}。" + next_step
    return next_step


def delegate_refusal() -> CliError:
    """CLI-side refusal of a delegate-only key.

    Shaped to match the server-side refusal on purpose (same exit code, same
    "delegate-only, get a separate key" direction): the two rejections are the
    same product rule enforced at two gates, and a caller that special-cases one
    of them is a caller that will mishandle the other.
    """
    return CliError(
        "这把密钥被配置为委托专用（delegate），不能用于本地开发",
        exit_code=EXIT_FORBIDDEN,
        next_step="请平台管理员另外签发一把不含 delegate 位的服务账号密钥用于 CLI。",
    )


def render_human(err: CliError) -> str:
    """Format a failure for a person: raw code, sentence, next step, hints."""
    head = f"错误 {err.code}: {err.message}" if err.code is not None else f"错误: {err.message}"
    lines = [head]
    if err.platform_message and err.platform_message != err.message:
        lines.append(f"  平台信息: {err.platform_message}")
    if err.next_step:
        lines.append(f"  下一步: {err.next_step}")
    for hint in err.hints:
        lines.append(f"  提示: {hint}")
    return mask("\n".join(lines))
