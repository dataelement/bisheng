"""采纳并更新的解析阶段和每日 10 分封顶.

纠错单本身仍是 pending 或终态. updating / failed 由指针文件的解析状态推导.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlmodel import select

from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.models.knowledge_file_correction import KnowledgeFileCorrectionAward

UPDATE_DAILY_CAP = 10
UPDATE_POINTS = 2
AWARD_KIND_UPDATE = "update"
UPDATE_PHASE_IDLE = "idle"
UPDATE_PHASE_UPDATING = "updating"
UPDATE_PHASE_FAILED = "failed"

logger = logging.getLogger(__name__)

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


def parent_id_from_file_level_path(file_level_path: str | None) -> int | None:
    """从 file_level_path 取出直接父目录 ID.

    Args:
        file_level_path: 形如 /12/34 的路径. 空字符串或根目录没有父目录.

    Returns:
        最后一段数字. 根目录或无法解析时为 None.
    """
    parts = [part for part in str(file_level_path or "").split("/") if part.strip()]
    if not parts:
        return None
    try:
        return int(parts[-1])
    except ValueError:
        return None


def _copy_file_location(old_file: KnowledgeFile, new_file: KnowledgeFile) -> None:
    """把原文件所在目录和首次上传人抄到新文件, 避免提升后掉到知识库根目录."""
    new_file.file_level_path = old_file.file_level_path
    new_file.level = old_file.level
    if new_file.original_uploader_id is None:
        new_file.original_uploader_id = old_file.original_uploader_id
    if new_file.original_knowledge_id is None:
        new_file.original_knowledge_id = old_file.original_knowledge_id


def _clear_distribution_entry(file: KnowledgeFile) -> None:
    """去掉文件上的 F059 入口字段, 历史正文只靠版本行保留."""
    file.entry_type = None
    file.entry_status = None
    file.reference_document_id = None
    file.projection_previous_file_id = None


def _set_manager_entry(
    file: KnowledgeFile,
    *,
    document_id: int,
    previous_file_id: int | None,
) -> None:
    """把文件标成指定知识文档的当前 manager."""
    file.reference_document_id = int(document_id)
    file.entry_type = KnowledgeFileEntryType.MANAGER.value
    file.entry_status = KnowledgeFileEntryStatus.ACTIVE.value
    file.projection_previous_file_id = int(previous_file_id) if previous_file_id else None


async def adopt_update_after_promote(
    session,
    *,
    old_file_id: int,
    new_file: KnowledgeFile,
    target_document: KnowledgeDocument,
    leftover_document_id: int | None,
) -> None:
    """采纳更新把版本挂到原文档后, 对齐 F059 入口并删掉 add_file 留下的空文档.

    官方换主版本会把新文件改成目标文档 manager, 清掉旧 manager, 再删空源文档.
    预览按 primary 文件必须是同一文档的 manager 解析, 只搬家版本不够.

    Args:
        session: 当前纠错关单事务.
        old_file_id: 纠错单指向的原知识库文件 ID.
        new_file: 已解析成功、版本已挂到目标文档的更新文件.
        target_document: 原文件所在知识文档, 主版本已指向新文件.
        leftover_document_id: add_file 给更新文件建的文档 ID. 与目标文档相同或缺失时不删.
    """
    old_file = (await session.exec(select(KnowledgeFile).where(KnowledgeFile.id == int(old_file_id)))).first()
    target_id = int(target_document.id)
    leftover_id = int(leftover_document_id or 0)
    if leftover_id == target_id:
        leftover_id = 0
    if leftover_id == 0 and int(new_file.reference_document_id or 0) not in (0, target_id):
        leftover_id = int(new_file.reference_document_id)

    if old_file is not None:
        _copy_file_location(old_file, new_file)

    old_is_manager = (
        old_file is not None
        and old_file.entry_type == KnowledgeFileEntryType.MANAGER.value
        and int(old_file.reference_document_id or 0) == target_id
    )
    other_manager = (
        await session.exec(
            select(KnowledgeFile).where(
                KnowledgeFile.reference_document_id == target_id,
                KnowledgeFile.entry_type == KnowledgeFileEntryType.MANAGER.value,
                KnowledgeFile.id != int(old_file_id),
                KnowledgeFile.id != int(new_file.id),
            )
        )
    ).first()

    if old_is_manager:
        _clear_distribution_entry(old_file)
        _set_manager_entry(new_file, document_id=target_id, previous_file_id=int(old_file.id))
        target_document.content_generation = int(target_document.content_generation or 0) + 1
    elif other_manager is None and new_file.entry_type == KnowledgeFileEntryType.MANAGER.value:
        _set_manager_entry(
            new_file,
            document_id=target_id,
            previous_file_id=int(old_file.id) if old_file is not None else None,
        )
        target_document.content_generation = int(target_document.content_generation or 0) + 1
    elif leftover_id and int(new_file.reference_document_id or 0) == leftover_id:
        _clear_distribution_entry(new_file)

    session.add(new_file)
    if old_file is not None:
        session.add(old_file)
    session.add(target_document)
    await session.flush()

    if leftover_id:
        await _delete_empty_leftover_document(session, leftover_id)


async def _delete_empty_leftover_document(session, leftover_id: int) -> None:
    """版本已搬走且没有入口再指向时, 删掉 add_file 留下的空知识文档.

    Args:
        session: 当前事务.
        leftover_id: 待删除的知识文档 ID.
    """
    remaining_versions = list(
        (
            await session.exec(
                select(KnowledgeDocumentVersion.id).where(KnowledgeDocumentVersion.document_id == int(leftover_id))
            )
        ).all()
    )
    still_pointing = list(
        (
            await session.exec(select(KnowledgeFile.id).where(KnowledgeFile.reference_document_id == int(leftover_id)))
        ).all()
    )
    if remaining_versions or still_pointing:
        logger.warning(
            "skip deleting leftover document leftover_id=%s versions=%s entries=%s",
            leftover_id,
            len(remaining_versions),
            len(still_pointing),
        )
        return
    leftover = await session.get(KnowledgeDocument, int(leftover_id))
    if leftover is None:
        return
    leftover.primary_version_id = None
    session.add(leftover)
    await session.flush()
    await session.delete(leftover)
    await session.flush()
