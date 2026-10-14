"""采纳并更新的解析阶段和每日 10 分封顶.

纠错单本身仍是 pending 或终态. updating / failed 由指针文件的解析状态推导.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlmodel import select

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus
from bisheng.knowledge.domain.models.knowledge_file_correction import KnowledgeFileCorrectionAward

UPDATE_DAILY_CAP = 10
UPDATE_POINTS = 2
AWARD_KIND_UPDATE = "update"
UPDATE_PHASE_IDLE = "idle"
UPDATE_PHASE_UPDATING = "updating"
UPDATE_PHASE_FAILED = "failed"

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_FAILED_STATUSES = {
    int(KnowledgeFileStatus.FAILED.value),
    int(KnowledgeFileStatus.TIMEOUT.value),
    int(KnowledgeFileStatus.VIOLATION.value),
}


def classify_update_phase(pending_update_file_id: int | None, file_status: int | None) -> str:
    """按指针文件的解析状态推导待办展示阶段.

    Args:
        pending_update_file_id: 纠错单上登记的新文件 ID. 没有指针时为空.
        file_status: 该文件当前解析状态. 指针文件不存在时为空.

    Returns:
        idle, updating 或 failed.
    """
    if not int(pending_update_file_id or 0):
        return UPDATE_PHASE_IDLE
    if file_status is None:
        return UPDATE_PHASE_IDLE
    if int(file_status) in _FAILED_STATUSES:
        return UPDATE_PHASE_FAILED
    return UPDATE_PHASE_UPDATING


def is_update_in_progress(phase: str) -> bool:
    """更新文件仍在解析或尚未收成当前版本.

    Args:
        phase: classify_update_phase 的返回值.

    Returns:
        为 True 时服务端必须拒绝采纳, 拒绝, 再登记和撤回.
    """
    return phase == UPDATE_PHASE_UPDATING


def is_update_failed(phase: str) -> bool:
    """指针文件已解析失败, 可以重解析或重上传.

    Args:
        phase: classify_update_phase 的返回值.

    Returns:
        失败阶段为 True.
    """
    return phase == UPDATE_PHASE_FAILED


async def update_points_used_today(session, *, applicant_user_id: int) -> int:
    """统计该反馈人当天已占用的采纳并更新分数.

    按 reserved 和 awarded 行数乘每条 2 分, 避免两笔同时关单都看到未满额.
    不按文件号, 也不读账本 daily_cap. 租户由现有注入过滤.

    Args:
        session: 当前事务.
        applicant_user_id: 反馈人用户 ID.

    Returns:
        当天已占用的更新分.
    """
    now = datetime.now(_SHANGHAI)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
    rows = (
        await session.exec(
            select(KnowledgeFileCorrectionAward).where(
                KnowledgeFileCorrectionAward.applicant_user_id == int(applicant_user_id),
                KnowledgeFileCorrectionAward.award_kind == AWARD_KIND_UPDATE,
                KnowledgeFileCorrectionAward.award_state.in_(("awarded", "reserved")),
                KnowledgeFileCorrectionAward.create_time >= day_start,
            )
        )
    ).all()
    return len(list(rows)) * UPDATE_POINTS


async def should_pay_update(session, *, applicant_user_id: int) -> bool:
    """这次采纳并更新是否还能再发 2 分.

    Args:
        session: 当前事务.
        applicant_user_id: 反馈人用户 ID.

    Returns:
        当天已用分加 2 不超过 10 时为 True.
    """
    used = await update_points_used_today(session, applicant_user_id=int(applicant_user_id))
    return used + UPDATE_POINTS <= UPDATE_DAILY_CAP
