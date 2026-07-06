"""Build E+ textcard payloads from InboxMessage action_codes."""

from bisheng.common.services.config_service import settings

FORWARDABLE_ACTION_CODES: set[str] = {
    "request_channel",
    "approved_channel",
    "rejected_channel",
    "request_knowledge_space",
    "approved_knowledge_space",
    "rejected_knowledge_space",
    "request_department_knowledge_space_upload",
    "approved_department_knowledge_space_upload",
    "rejected_department_knowledge_space_upload",
    "sensitive_rejected_department_knowledge_space_upload",
    "request_menu_access",
    "approval_task_pending",
    "approval_task_rejected",
    "approval_instance_approved",
    "approval_instance_withdrawn",
    "approval_exception_cancelled",
    "approval_exception_route_missing",
    "approval_exception_approver_empty",
    "approval_execute_failed",
    "menu_grant_revoked",
    "assigned_channel_admin",
    "assigned_knowledge_space_admin",
    "revoked_channel_admin",
    "revoked_knowledge_space_admin",
    "removed_channel_member",
    "removed_knowledge_space_member",
    "channel_made_private",
    "knowledge_space_made_private",
    "channel_dismissed",
    "knowledge_space_deleted",
    "approved_review_tag",
    "rejected_review_tag",
}


_TEMPLATES: dict[str, dict[str, str]] = {
    "request_channel": {
        "title": "[知源] 新的频道订阅申请",
        "normal": "{applicant} 申请订阅频道「{resource_name}」",
        "highlight": "需要你审批",
    },
    "approved_channel": {
        "title": "[知源] 频道订阅申请已通过",
        "normal": "你订阅频道「{resource_name}」的申请",
        "highlight": "已通过",
    },
    "rejected_channel": {
        "title": "[知源] 频道订阅申请被拒绝",
        "normal": "你订阅频道「{resource_name}」的申请",
        "highlight": "被拒绝",
    },
    "request_knowledge_space": {
        "title": "[知源] 新的知识空间加入申请",
        "normal": "{applicant} 申请加入知识空间「{resource_name}」",
        "highlight": "需要你审批",
    },
    "approved_knowledge_space": {
        "title": "[知源] 知识空间加入申请已通过",
        "normal": "你加入知识空间「{resource_name}」的申请",
        "highlight": "已通过",
    },
    "rejected_knowledge_space": {
        "title": "[知源] 知识空间加入申请被拒绝",
        "normal": "你加入知识空间「{resource_name}」的申请",
        "highlight": "被拒绝",
    },
    "request_department_knowledge_space_upload": {
        "title": "[知源] 新的部门知识空间上传申请",
        "normal": "{applicant} 申请上传文件到部门知识空间「{resource_name}」",
        "highlight": "需要你审批",
    },
    "approved_department_knowledge_space_upload": {
        "title": "[知源] 部门知识空间上传申请已通过",
        "normal": "你上传部门知识空间文件「{resource_name}」的申请",
        "highlight": "已通过",
    },
    "rejected_department_knowledge_space_upload": {
        "title": "[知源] 部门知识空间上传申请被拒绝",
        "normal": "你上传部门知识空间文件「{resource_name}」的申请",
        "highlight": "被拒绝",
    },
    "sensitive_rejected_department_knowledge_space_upload": {
        "title": "[知源] 上传未通过内容安全检测",
        "normal": "你上传的部门知识空间文件「{resource_name}」",
        "highlight": "未通过安全检测",
    },
    "request_menu_access": {
        "title": "[知源] 新的菜单访问申请",
        "normal": "{applicant} 申请访问菜单「{resource_name}」",
        "highlight": "需要你审批",
    },
    "approval_task_pending": {
        "title": "[知源] 新的审批任务",
        "normal": "{applicant} 提交了「{resource_name}」审批申请",
        "highlight": "需要你审批",
    },
    "approval_task_rejected": {
        "title": "[知源] 审批申请被拒绝",
        "normal": "你对「{resource_name}」的审批申请",
        "highlight": "被拒绝",
    },
    "approval_instance_approved": {
        "title": "[知源] 审批申请已通过",
        "normal": "你对「{resource_name}」的审批申请",
        "highlight": "已通过",
    },
    "approval_instance_withdrawn": {
        "title": "[知源] 审批申请已撤回",
        "normal": "{applicant} 撤回了「{resource_name}」的审批申请",
        "highlight": "无需处理",
    },
    "approval_exception_cancelled": {
        "title": "[知源] 审批申请已取消",
        "normal": "你对「{resource_name}」的审批申请",
        "highlight": "已被取消",
    },
    "approval_exception_route_missing": {
        "title": "[知源] 审批异常",
        "normal": "「{resource_name}」的审批申请未匹配到审批分支",
        "highlight": "请处理",
    },
    "approval_exception_approver_empty": {
        "title": "[知源] 审批异常",
        "normal": "「{resource_name}」的审批申请未解析到审批人",
        "highlight": "请处理",
    },
    "approval_execute_failed": {
        "title": "[知源] 审批执行失败",
        "normal": "「{resource_name}」审批已通过，但业务执行失败",  # noqa: RUF001
        "highlight": "请处理",
    },
    "menu_grant_revoked": {
        "title": "[知源] 菜单授权已撤回",
        "normal": "你对菜单「{resource_name}」的访问权限",
        "highlight": "已被撤回",
    },
    "assigned_channel_admin": {
        "title": "[知源] 频道管理员授权",
        "normal": "你已被设为频道「{resource_name}」的管理员",
        "highlight": "权限已变更",
    },
    "assigned_knowledge_space_admin": {
        "title": "[知源] 知识空间管理员授权",
        "normal": "你已被设为知识空间「{resource_name}」的管理员",
        "highlight": "权限已变更",
    },
    "revoked_channel_admin": {
        "title": "[知源] 频道管理员权限已取消",
        "normal": "你已不再是频道「{resource_name}」的管理员",
        "highlight": "权限已变更",
    },
    "revoked_knowledge_space_admin": {
        "title": "[知源] 知识空间管理员权限已取消",
        "normal": "你已不再是知识空间「{resource_name}」的管理员",
        "highlight": "权限已变更",
    },
    "removed_channel_member": {
        "title": "[知源] 已被移出频道",
        "normal": "你已被移出频道「{resource_name}」",
        "highlight": "访问关系已变更",
    },
    "removed_knowledge_space_member": {
        "title": "[知源] 已被移出知识空间",
        "normal": "你已被移出知识空间「{resource_name}」",
        "highlight": "访问关系已变更",
    },
    "channel_made_private": {
        "title": "[知源] 频道已转为私有",
        "normal": "频道「{resource_name}」已转为私有",
        "highlight": "你已无法访问",
    },
    "knowledge_space_made_private": {
        "title": "[知源] 知识空间已转为私有",
        "normal": "知识空间「{resource_name}」已转为私有",
        "highlight": "你已无法访问",
    },
    "channel_dismissed": {
        "title": "[知源] 频道已解散",
        "normal": "频道「{resource_name}」",
        "highlight": "已被解散",
    },
    "knowledge_space_deleted": {
        "title": "[知源] 知识空间已删除",
        "normal": "知识空间「{resource_name}」",
        "highlight": "已被删除",
    },
    "approved_review_tag": {
        "title": "[知源] 标签审核已通过",
        "normal": "你提交的标签「{resource_name}」",
        "highlight": "已通过",
    },
    "rejected_review_tag": {
        "title": "[知源] 标签审核被拒绝",
        "normal": "你提交的标签「{resource_name}」",
        "highlight": "被拒绝",
    },
}


def build_textcard_url(message_id: int) -> str:
    """Return the BiSheng callback URL for a textcard button."""
    base = settings.get_cofco_forwarding_conf().bisheng_inbox_url.rstrip("/")
    return f"{base}/?open-notifications=1&message-id={message_id}"


def _truncate_bytes(text: str, max_bytes: int) -> str:
    """Truncate text to at most max_bytes UTF-8 bytes without splitting a multi-byte char."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    # Binary search for the largest prefix that fits within max_bytes
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(text[:mid].encode("utf-8")) <= max_bytes:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo]


def build_textcard(
    *,
    message_id: int,
    action_code: str,
    applicant_name: str,
    resource_name: str,
    triggered_at: str,
) -> dict:
    """Build the ``textcard`` dict for the E+ /v2/message/send body.

    Returns a dict with keys: title, description, url, btntxt.
    Raises KeyError when action_code is not in _TEMPLATES.
    """
    tpl = _TEMPLATES[action_code]  # KeyError for unknown codes — intentional
    title = _truncate_bytes(tpl["title"], 128)
    normal = tpl["normal"].format(applicant=applicant_name, resource_name=resource_name)
    description = (
        f'<div class="gray">{triggered_at}</div>'
        f'<div class="normal">{normal}</div>'
        f'<div class="highlight">{tpl["highlight"]}</div>'
    )
    description = _truncate_bytes(description, 512)
    return {
        "title": title,
        "description": description,
        "url": build_textcard_url(message_id),
        "btntxt": "去查看",
    }
