"""专家问答已放行时, 补文档入口的查看和预览, 不改下载权."""

from __future__ import annotations

from typing import Any

from bisheng.knowledge.domain.services.department_file_view_access_service import (
    DepartmentFileAccessSource,
)

_PREVIEW_CAPABILITIES = frozenset({"can_view", "can_preview"})


def grant_expert_qa_content_preview(
    resolved: Any,
    decision: Any,
    required_capability: str,
) -> Any | None:
    """文档入口没有 can_preview 时, 若专家问答上下文已放行, 允许看正文.

    只处理 can_view 和 can_preview. 下载仍走原拒绝. 没有问答放行时返回 None.
    """
    if required_capability not in _PREVIEW_CAPABILITIES:
        return None
    if decision is None or not getattr(decision, "allowed", False):
        return None
    if getattr(decision, "source", None) != DepartmentFileAccessSource.EXPERT_QA:
        return None
    capabilities = resolved.capabilities.model_copy(
        update={"can_view": True, "can_preview": True},
    )
    return resolved.model_copy(update={"capabilities": capabilities})
