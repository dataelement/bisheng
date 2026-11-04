"""Safe metadata and retained output; never expose an internal operation document."""

import re
from copy import deepcopy

from bisheng.common.errcode.app_factory import AppProbeFailedError
from bisheng.common.errcode.app_publish import AppDependencyBuildFailedError, AppStartupProbeFailedError


def stored_failure(value):
    """Logs belong to expiring RuntimeOperation, never a persistent release/audit copy."""
    if isinstance(value, dict):
        return {
            key: stored_failure(item)
            for key, item in value.items()
            if key not in {"tail", "diagnostic_tail", "diagnostics_available"}
        }
    if isinstance(value, (list, tuple)):
        return [stored_failure(item) for item in value]
    return deepcopy(value)


def bounded_tail(text):
    if not isinstance(text, str):
        return []
    return "\n".join(text.splitlines()[-40:]).encode()[-16384:].decode("utf-8", errors="ignore").splitlines()


def runtime_failure_error(operation):
    failure = operation.failure or {}
    reason = failure.get("reason", "execution_failed")
    if not isinstance(reason, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", reason):
        reason = "execution_failed"
    stage = failure.get("failed_stage") or operation.stage
    if not isinstance(stage, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", stage):
        stage = "unknown"
    details = {
        "operation_id": operation.id,
        "reason": reason,
        "runtime_stage": stage,
        "maintenance": bool(failure.get("maintenance")),
        "data_may_have_changed": bool(failure.get("data_may_have_changed")),
    }
    error = AppProbeFailedError
    hints = ["依据操作标识检查当前阶段;数据维护或清理未完成时先确认状态再重试"]
    if operation.status == "failed" and operation.kind == "prepare":
        error = AppDependencyBuildFailedError
        hints = ["检查固定镜像、入口和精确版本依赖材料;离线模式请导入对应平台材料后重试"]
    elif (
        operation.status == "failed"
        and operation.kind in {"probe", "preview", "deploy", "restore"}
        and stage in {"starting", "ready"}
        and reason
        in {"startup_exited", "readiness_timeout", "workload_readiness_timeout", "workload_failed", "startup_failed"}
    ):
        error = AppStartupProbeFailedError
        hints = ["检查启动命令、监听地址和平台端口后重新提交"]
    role, reference = failure.get("image_role"), failure.get("image_ref")
    if (
        isinstance(role, str)
        and role in {"runtime", "preparer", "base", "image", "helper", "assembler"}
        and isinstance(reference, str)
        and len(reference) <= 512
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./:_-]*(?:@sha256:[a-f0-9]{64})?", reference)
    ):
        details.update(image_role=role, image_ref=reference)
        hints = [f"请维护者核对并补齐 {role} 镜像 {reference}, 保持原镜像拉取策略后重试", *hints]
    return error(details=details, hints=hints, **details)
