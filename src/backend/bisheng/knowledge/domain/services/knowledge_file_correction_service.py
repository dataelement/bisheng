"""知识库文档纠错: 提交, 审批, 撤回和删除时取消待处理."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import Integer, String, column, table
from sqlalchemy import select as sa_select
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalTask,
    ApprovalTaskStatus,
)
from bisheng.common.errcode.approval import (
    ApprovalRejectReasonRequiredError,
    ApprovalRequestAlreadyProcessedError,
    ApprovalRequestNotFoundError,
    ApprovalRequestPermissionDeniedError,
)
from bisheng.common.errcode.file_correction import (
    FileCorrectionContentForbiddenError,
    FileCorrectionContentRequiredError,
    FileCorrectionContentTooLongError,
    FileCorrectionPendingExistsError,
    FileCorrectionSelfSubmitError,
    FileCorrectionSpaceNotAllowedError,
    FileCorrectionUpdateFileInvalidError,
    FileCorrectionUpdateFileNotReadyError,
    FileCorrectionUpdateInProgressError,
    FileCorrectionUpdateRetryNotAllowedError,
    FileCorrectionUploaderOnlyError,
    FileCorrectionUploaderUnavailableError,
    FileCorrectionViewDeniedError,
)
from bisheng.common.errcode.knowledge_space import SpaceFileNotFoundError
from bisheng.core.database import get_async_db_session
from bisheng.database.models.review_tags import ReviewTag, ReviewTagLink
from bisheng.database.models.tag import Tag, TagLink, TagResourceTypeEnum
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.models.knowledge_file_correction import (
    AWARD_RESERVED,
    CORRECTION_APPROVED,
    CORRECTION_CANCELLED,
    CORRECTION_PENDING,
    CORRECTION_REJECTED,
    CORRECTION_WITHDRAWN,
    FILE_CORRECTION_CONTENT_LIMIT,
    FILE_CORRECTION_SCENARIO,
    FILE_CORRECTION_SCENARIO_NAME,
    KnowledgeFileCorrection,
    KnowledgeFileCorrectionAward,
    KnowledgeFileCorrectionOpen,
)
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceScope,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_correction_repository_impl import (
    KnowledgeFileCorrectionRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_file_correction_update import (
    UPDATE_PHASE_IDLE,
    UPDATE_PHASE_UPDATING,
    UPDATE_POINTS,
    classify_update_phase,
    is_update_failed,
    is_update_in_progress,
    should_pay_update,
)
from bisheng.permission.domain.services.permission_service import PermissionService

# 只读上传人是否停用. 不引用 user 领域模型, 避免测试桩把 User 换成 MagicMock.
_USER_TABLE = table(
    "user",
    column("user_id", Integer),
    column("user_name", String),
    column("delete", Integer),
)

logger = logging.getLogger(__name__)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_UPDATE_SOURCE_KEY = "correction_update_source"
_register_guard = asyncio.Lock()
# 按纠错单缓存, 用完不删. 删掉正在等待的锁会让两个请求各拿一把, 同时登记.
_register_locks: dict[int, asyncio.Lock] = {}
ADOPT_POINTS = 1
AWARD_KIND_ADOPT = "adopt"
AWARD_KIND_UPDATE = "update"

_ELIGIBLE_LEVELS = {
    KnowledgeSpaceLevelEnum.PUBLIC.value,
    KnowledgeSpaceLevelEnum.DEPARTMENT.value,
    KnowledgeSpaceLevelEnum.TEAM.value,
    KnowledgeSpaceLevelEnum.TEAM_KS.value,
}


async def _lock_for_correction(correction_id: int) -> asyncio.Lock:
    """取出这一条纠错的进程内互斥锁.

    Args:
        correction_id: 纠错单 ID.

    Returns:
        该纠错单专用的锁. 其他纠错单不会被挡住.
    """
    async with _register_guard:
        lock = _register_locks.get(correction_id)
        if lock is None:
            lock = asyncio.Lock()
            _register_locks[correction_id] = lock
        return lock


async def _add_correction_file(request, login_user, **kwargs):
    """登记新文件且不记入库分. 单独放出来, 便于测试替换这一步.

    Args:
        request: 当前 HTTP 请求.
        login_user: 当前登录用户.
        **kwargs: 传给知识库 add_file 的参数, 必须包含 award_points=False.

    Returns:
        add_file 的文件列表.
    """
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    return await KnowledgeSpaceService(request, login_user).add_file(**kwargs)


def _split_rule_value(split_rule, key: str) -> str | None:
    """从文件解析规则里取出分类或业务域.

    Args:
        split_rule: knowledgefile.split_rule, 可能是 JSON 字符串或字典.
        key: file_category_code 或 business_domain_code.

    Returns:
        去空白后的编码. 没有时返回 None.
    """
    data = split_rule
    if isinstance(split_rule, str) and split_rule.strip():
        try:
            data = json.loads(split_rule)
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    value = str(data.get(key) or "").strip()
    return value or None


async def _copy_tag_links(session, tag_model, link_model, *, old_id: int, new_id: int, user_id: int, review: bool) -> None:
    """复制一类标签关联. 自动标签不复制.

    Args:
        session: 当前事务.
        tag_model: 标签表.
        link_model: 标签关联表.
        old_id: 旧文件 ID.
        new_id: 新文件 ID.
        user_id: 关联记录上的用户 ID.
        review: 为 True 时只复制未删除的审核标签.
    """
    statement = (
        select(link_model.tag_id, link_model.resource_type, link_model.tenant_id)
        .join(tag_model, tag_model.id == link_model.tag_id)
        .where(
            link_model.resource_id == str(old_id),
            tag_model.resource_type != TagResourceTypeEnum.AI_AUTO_TAG.value,
        )
    )
    if review:
        statement = statement.where(link_model.is_deleted == False, tag_model.is_deleted == False)  # noqa: E712
    rows = (await session.execute(statement)).all()
    for tag_id, resource_type, tenant_id in rows:
        session.add(
            link_model(
                tag_id=int(tag_id),
                resource_id=str(new_id),
                resource_type=int(resource_type),
                user_id=int(user_id),
                tenant_id=int(tenant_id or 1),
            )
        )


def _public_library_grants_view(knowledge, scope) -> bool:
    """公共库是否按阅读页规则直接给查看权.

    Args:
        knowledge: 文件所在知识库.
        scope: 知识库层级.

    Returns:
        非收藏、未在删除中的公共库返回 True.
    """
    if knowledge is None or bool(getattr(knowledge, "is_favorite", False)):
        return False
    if int(getattr(knowledge, "state", 0) or 0) == int(KnowledgeState.DELETING.value):
        return False
    level = getattr(scope, "level", None) if scope is not None else None
    value = getattr(level, "value", level)
    return value == KnowledgeSpaceLevelEnum.PUBLIC.value


def normalize_correction_content(raw: str | None) -> str:
    """去掉首尾空白并按字符数校验纠错说明.

    Args:
        raw: 用户提交的原文.

    Returns:
        去掉首尾空白后的说明.

    Raises:
        FileCorrectionContentRequiredError: 说明为空.
        FileCorrectionContentTooLongError: 超过 500 个字符.
    """
    text = str(raw or "").strip()
    if not text:
        raise FileCorrectionContentRequiredError()
    if len(text) > FILE_CORRECTION_CONTENT_LIMIT:
        raise FileCorrectionContentTooLongError()
    return text


class KnowledgeFileCorrectionService:
    """纠错单写在本服务的事务里. 积分在通过提交之后另投."""

    @classmethod
    async def submit(
        cls,
        *,
        login_user,
        file_id: int,
        content: str = "",
        original_error: str | None = None,
        corrected_content: str | None = None,
    ) -> dict:
        """提交一条纠错并给上传人创建待办.

        Args:
            login_user: 当前登录用户.
            file_id: 知识库文件 ID.
            content: 旧的一段说明. 两段都没传时才用.
            original_error: 用户认为原文中错误的地方.
            corrected_content: 用户纠正后的内容.

        Returns:
            纠错单编号, 审批实例编号和待处理状态.

        Raises:
            SpaceFileNotFoundError: 当前租户看不到该文档.
            FileCorrectionViewDeniedError: 无权查看该文档.
            FileCorrectionSpaceNotAllowedError: 库层级不允许纠错.
            FileCorrectionContentRequiredError: 说明为空.
            FileCorrectionContentTooLongError: 说明超过 500 字.
            FileCorrectionSelfSubmitError: 当前用户就是上传人.
            FileCorrectionUploaderUnavailableError: 没有可处理的上传人.
            FileCorrectionPendingExistsError: 已有待处理纠错.
        """
        async with get_async_db_session() as session:
            repo = KnowledgeFileCorrectionRepositoryImpl(session)
            file = await repo.lock_file(int(file_id))
            if file is None:
                raise SpaceFileNotFoundError()
            knowledge = (
                await session.exec(select(Knowledge).where(Knowledge.id == int(file.knowledge_id)))
            ).first()
            scope = (
                await session.exec(
                    select(KnowledgeSpaceScope).where(KnowledgeSpaceScope.space_id == int(file.knowledge_id))
                )
            ).first()
            await cls._require_view(login_user, int(file_id), knowledge, scope)
            cls._require_space(knowledge, scope)
            two_part = original_error is not None or corrected_content is not None
            if two_part:
                # 两段都必填, 各最多 500 字. content 仍写入原文错误处, 给只读旧字段的调用方.
                original_text = normalize_correction_content(original_error)
                corrected_text = normalize_correction_content(corrected_content)
                text = original_text
            else:
                original_text = None
                corrected_text = None
                text = normalize_correction_content(content)
            applicant_id = int(login_user.user_id)
            uploader_id = int(file.user_id) if file.user_id is not None else None
            if uploader_id is not None and uploader_id == applicant_id:
                raise FileCorrectionSelfSubmitError()
            uploader = await cls._require_uploader(session, uploader_id)
            tenant_id = int(getattr(file, "tenant_id", None) or getattr(login_user, "tenant_id", None) or 1)
            existing = await repo.lock_open_slot(
                tenant_id=tenant_id,
                file_id=int(file.id),
                applicant_user_id=applicant_id,
            )
            if existing is not None:
                raise FileCorrectionPendingExistsError()
            now = datetime.now()
            correction = KnowledgeFileCorrection(
                tenant_id=tenant_id,
                file_id=int(file.id),
                knowledge_id=int(file.knowledge_id),
                applicant_user_id=applicant_id,
                applicant_user_name=str(getattr(login_user, "user_name", "") or ""),
                uploader_user_id=int(uploader.user_id),
                uploader_user_name=str(uploader.user_name or file.user_name or ""),
                file_name=str(file.file_name or ""),
                content=text,
                original_error=original_text,
                corrected_content=corrected_text,
                status=CORRECTION_PENDING,
                create_time=now,
                update_time=now,
            )
            session.add(correction)
            await session.flush()
            snapshot = {
                "correction_id": int(correction.id),
                "file_id": int(file.id),
                "file_name": str(file.file_name or ""),
                "space_id": int(file.knowledge_id),
            }
            instance = ApprovalInstance(
                tenant_id=tenant_id,
                scenario_code=FILE_CORRECTION_SCENARIO,
                scenario_name=FILE_CORRECTION_SCENARIO_NAME,
                handler_key=FILE_CORRECTION_SCENARIO,
                business_key=f"file-correction:{int(correction.id)}",
                business_resource_type="knowledge_file",
                business_resource_id=str(int(file.id)),
                business_name=str(file.file_name or ""),
                applicant_user_id=applicant_id,
                applicant_user_name=str(getattr(login_user, "user_name", "") or ""),
                status=ApprovalInstanceStatus.PENDING,
                reason=None,
                payload_snapshot=snapshot,
                detail_snapshot=snapshot,
                current_node_name="上传人审批",
                create_time=now,
                update_time=now,
            )
            session.add(instance)
            await session.flush()
            task = ApprovalTask(
                tenant_id=tenant_id,
                instance_id=int(instance.id),
                flow_version_id=0,
                node_code="file_uploader",
                node_name="上传人审批",
                node_order=1,
                approver_user_id=int(uploader.user_id),
                approver_source_type="file_uploader",
                node_mode="or",
                status=ApprovalTaskStatus.PENDING,
                create_time=now,
                update_time=now,
            )
            session.add(task)
            correction.approval_instance_id = int(instance.id)
            session.add(correction)
            session.add(
                KnowledgeFileCorrectionOpen(
                    tenant_id=tenant_id,
                    file_id=int(file.id),
                    applicant_user_id=applicant_id,
                    correction_id=int(correction.id),
                )
            )
            try:
                await session.flush()
            except IntegrityError as exc:
                raise FileCorrectionPendingExistsError() from exc
            session.add(
                ApprovalActionLog(
                    tenant_id=tenant_id,
                    instance_id=int(instance.id),
                    action="submitted",
                    operator_user_id=applicant_id,
                    operator_user_name=str(getattr(login_user, "user_name", "") or ""),
                    detail={"correction_id": int(correction.id), "file_id": int(file.id)},
                    create_time=now,
                    update_time=now,
                )
            )
            await session.commit()
            return {
                "correction_id": int(correction.id),
                "instance_id": int(instance.id),
                "task_id": int(task.id),
                "status": CORRECTION_PENDING,
            }

    @classmethod
    async def list_for_file(cls, *, login_user, file_id: int) -> list[dict]:
        """列出这篇文档的纠错. 能看文档的人都能看到说明和状态.

        Args:
            login_user: 当前登录用户.
            file_id: 知识库文件 ID.

        Returns:
            按创建时间倒序的纠错摘要, 含反馈人, 当时文件名, 说明和状态.
            范围是当前文件所属文档的全部版本.

        Raises:
            SpaceFileNotFoundError: 文档不存在.
            FileCorrectionViewDeniedError: 无权查看该文档.
            FileCorrectionSpaceNotAllowedError: 库层级不允许纠错.
        """
        async with get_async_db_session() as session:
            file = (
                await session.exec(select(KnowledgeFile).where(KnowledgeFile.id == int(file_id)))
            ).first()
            if file is None:
                raise SpaceFileNotFoundError()
            knowledge = (
                await session.exec(select(Knowledge).where(Knowledge.id == int(file.knowledge_id)))
            ).first()
            scope = (
                await session.exec(
                    select(KnowledgeSpaceScope).where(KnowledgeSpaceScope.space_id == int(file.knowledge_id))
                )
            ).first()
            await cls._require_view(login_user, int(file_id), knowledge, scope)
            cls._require_space(knowledge, scope)
            file_ids = await cls._document_version_file_ids(session, file)
            rows = await KnowledgeFileCorrectionRepositoryImpl(session).list_for_files(file_ids)
            award_kind_by_correction: dict[int, str] = {}
            correction_ids = [int(row.id) for row in rows if row.id is not None]
            if correction_ids:
                awards = (
                    await session.exec(
                        select(KnowledgeFileCorrectionAward).where(
                            KnowledgeFileCorrectionAward.correction_id.in_(correction_ids)
                        )
                    )
                ).all()
                award_kind_by_correction = {
                    int(item.correction_id): str(item.award_kind) for item in awards
                }
            items = []
            for row in rows:
                created = row.create_time.isoformat(sep=" ", timespec="seconds") if row.create_time else None
                items.append({
                    "correction_id": int(row.id),
                    "status": row.status,
                    "award_kind": award_kind_by_correction.get(int(row.id)),
                    "applicant_user_name": row.applicant_user_name,
                    "file_name": row.file_name,
                    "create_time": created,
                    "content": row.content,
                    "original_error": row.original_error,
                    "corrected_content": row.corrected_content,
                })
            return items

    @staticmethod
    async def _document_version_file_ids(session, file: KnowledgeFile) -> list[int]:
        """取出当前文件所属文档的全部版本文件编号.

        没有版本行时只返回当前文件. 只保留同一知识库里的文件.
        一次返回全部版本, 不翻页. 单篇文档版本数到几百时再改成分页.

        Args:
            session: 当前事务.
            file: 用户正在打开的知识库文件.

        Returns:
            去重后的文件 ID, 至少包含当前文件.
        """
        current_id = int(file.id)
        version = (
            await session.exec(
                select(KnowledgeDocumentVersion).where(
                    KnowledgeDocumentVersion.knowledge_file_id == current_id
                )
            )
        ).first()
        if version is None:
            return [current_id]
        siblings = (
            await session.exec(
                select(KnowledgeDocumentVersion.knowledge_file_id).where(
                    KnowledgeDocumentVersion.document_id == int(version.document_id)
                )
            )
        ).all()
        sibling_ids = {int(item) for item in siblings if item}
        sibling_ids.add(current_id)
        same_space = (
            await session.exec(
                select(KnowledgeFile.id).where(
                    col(KnowledgeFile.id).in_(list(sibling_ids)),
                    KnowledgeFile.knowledge_id == int(file.knowledge_id),
                )
            )
        ).all()
        ids = {int(item) for item in same_space if item}
        ids.add(current_id)
        return sorted(ids)

    @classmethod
    async def get_content(cls, *, login_user, correction_id: int) -> dict:
        """读取纠错说明. 只有反馈人和冻结上传人可以看.

        Args:
            login_user: 当前登录用户.
            correction_id: 纠错单 ID.

        Returns:
            纠错单编号, 文档信息, 说明, 两段正文和状态.

        Raises:
            FileCorrectionContentForbiddenError: 当前用户不能看, 或记录不存在.
        """
        async with get_async_db_session() as session:
            repo = KnowledgeFileCorrectionRepositoryImpl(session)
            row = await repo.get_by_id(int(correction_id))
            user_id = int(login_user.user_id)
            if row is None or user_id not in {int(row.applicant_user_id), int(row.uploader_user_id)}:
                raise FileCorrectionContentForbiddenError()
            update_file_status, update_phase = await cls._update_phase(session, row)
            return {
                "correction_id": int(row.id),
                "file_id": int(row.file_id),
                "file_name": row.file_name,
                "space_id": int(row.knowledge_id),
                "content": row.content,
                "original_error": row.original_error,
                "corrected_content": row.corrected_content,
                "status": row.status,
                "applicant_user_id": int(row.applicant_user_id),
                "uploader_user_id": int(row.uploader_user_id),
                "pending_update_file_id": int(row.pending_update_file_id) if row.pending_update_file_id else None,
                "update_file_status": update_file_status,
                "update_phase": update_phase,
            }

    @classmethod
    async def register_update_file(cls, *, login_user, request, correction_id: int, file_path: str) -> dict:
        """把采纳并更新的新文件登记进原知识库, 不记入库分.

        分类、业务域、二级分类以及非自动标签从旧文件复制. 文件写入知识库后不关待办、不发分.
        指针文件仍在解析时拒绝再次登记. 失败后再次登记视为重新上传, 会删掉上一份失败文件.
        当前版本要等这份新文件解析成功后再换.

        Args:
            login_user: 当前登录用户, 必须是冻结上传人.
            request: 当前 HTTP 请求, 供知识库上传服务读取.
            correction_id: 待处理纠错单 ID.
            file_path: 已经上传到临时目录的文件路径.

        Returns:
            新文件的 id、解析状态和文件名.

        Raises:
            FileCorrectionUpdateFileInvalidError: 没有临时路径, 或登记没有产生文件.
            ApprovalRequestNotFoundError: 纠错单不存在.
            FileCorrectionUploaderOnlyError: 当前用户不是冻结上传人.
            ApprovalRequestAlreadyProcessedError: 纠错已不在待处理.
            SpaceFileNotFoundError: 旧文件不存在.
        """
        path = str(file_path or "").strip()
        if not path:
            raise FileCorrectionUpdateFileInvalidError()
        # 同一进程里先按纠错单排队, 再靠行锁挡住其他进程. 登记期间不锁整库.
        register_lock = await _lock_for_correction(int(correction_id))
        async with register_lock:
            return await cls._register_update_file_locked(
                login_user=login_user,
                request=request,
                correction_id=int(correction_id),
                file_path=path,
            )

    @classmethod
    async def _register_update_file_locked(cls, *, login_user, request, correction_id: int, file_path: str) -> dict:
        """在纠错单锁内登记新文件.

        Args:
            login_user: 当前登录用户.
            request: 当前 HTTP 请求.
            correction_id: 纠错单 ID.
            file_path: 临时文件路径.

        Returns:
            新文件的 id、解析状态和文件名.
        """
        created_new = False
        async with get_async_db_session() as session:
            # 行锁只包住检查. 上传放在锁外, 避免一次解析占住连接.
            repo = KnowledgeFileCorrectionRepositoryImpl(session)
            correction = await repo.lock_by_id(int(correction_id))
            if correction is None:
                raise ApprovalRequestNotFoundError()
            if int(correction.uploader_user_id) != int(login_user.user_id):
                raise FileCorrectionUploaderOnlyError()
            if correction.status != CORRECTION_PENDING:
                raise ApprovalRequestAlreadyProcessedError()
            existing_id = await cls._existing_pending_update_file_id(session, correction)
            if existing_id is not None:
                phase = (await cls._update_phase(session, correction))[1]
                if is_update_in_progress(phase):
                    raise FileCorrectionUpdateInProgressError()
                if is_update_failed(phase):
                    existing_id = None
            new_id = existing_id
            old_file = (
                await session.exec(select(KnowledgeFile).where(KnowledgeFile.id == int(correction.file_id)))
            ).first()
            if old_file is None:
                raise SpaceFileNotFoundError()
            category = _split_rule_value(old_file.split_rule, "file_category_code")
            domain = _split_rule_value(old_file.split_rule, "business_domain_code")
            subcategory = str(old_file.file_subcategory_code or "").strip().upper() or None
            subcategory_source = old_file.file_subcategory_source
            old_id = int(old_file.id)
            knowledge_id = int(correction.knowledge_id)
        if new_id is None:
            created = await _add_correction_file(
                request,
                login_user,
                knowledge_id=knowledge_id,
                file_path=[file_path],
                file_category_code=category,
                file_subcategory_code=subcategory,
                business_domain_code=domain,
                award_points=False,
            )
            new_file = next((item for item in created or [] if getattr(item, "id", None)), None)
            if new_file is None:
                raise FileCorrectionUpdateFileInvalidError()
            new_id = int(new_file.id)
            created_new = True
        award_payload = None
        notify_payload = None
        async with get_async_db_session() as session:
            # 新会话才能看见刚才提交的文件. 再锁一次, 避免两笔请求各写一个指针.
            correction = await KnowledgeFileCorrectionRepositoryImpl(session).lock_by_id(int(correction_id))
            if correction is None:
                raise FileCorrectionUpdateFileInvalidError()
            if correction.status != CORRECTION_PENDING:
                raise ApprovalRequestAlreadyProcessedError()
            already_id = await cls._existing_pending_update_file_id(session, correction)
            phase = (await cls._update_phase(session, correction))[1]
            if already_id is not None and is_update_in_progress(phase) and int(already_id) != int(new_id):
                raise FileCorrectionUpdateInProgressError()
            if already_id is not None and is_update_failed(phase) and created_new:
                await cls._discard_pending_update_file(session, correction)
            elif already_id is not None and not created_new:
                new_id = already_id
            row = (await session.exec(select(KnowledgeFile).where(KnowledgeFile.id == new_id))).first()
            if row is None:
                raise FileCorrectionUpdateFileInvalidError()
            if created_new:
                metadata = dict(row.user_metadata or {})
                metadata[_UPDATE_SOURCE_KEY] = file_path
                row.user_metadata = metadata
                if subcategory_source:
                    row.file_subcategory_source = subcategory_source
                session.add(row)
                await cls._copy_non_ai_tags(
                    session,
                    old_id=old_id,
                    new_id=new_id,
                    user_id=int(login_user.user_id),
                )
            correction.pending_update_file_id = new_id
            session.add(correction)
            if int(row.status or 0) == int(KnowledgeFileStatus.SUCCESS.value):
                await cls._promote_new_version(session, correction, int(new_id))
                award_payload, notify_payload = await cls._finalize_update(session, correction)
            await session.commit()
            result = {
                "id": new_id,
                "status": int(row.status or 0),
                "file_name": row.file_name,
                "update_phase": classify_update_phase(new_id, int(row.status or 0)),
            }
        if notify_payload is not None:
            await cls._notify(**notify_payload)
        if award_payload is not None:
            await cls._dispatch_award(award_payload)
        return result

    @staticmethod
    async def _existing_pending_update_file_id(session, correction: KnowledgeFileCorrection) -> int | None:
        """这条纠错如果已经登记过新文件, 返回那个文件 ID.

        Args:
            session: 持有纠错行锁的会话.
            correction: 待处理纠错.

        Returns:
            仍在同一知识库中的新文件 ID. 没有可复用文件时返回 None.
        """
        pending_id = int(correction.pending_update_file_id or 0)
        if pending_id <= 0:
            return None
        row = (await session.exec(select(KnowledgeFile).where(KnowledgeFile.id == pending_id))).first()
        if row is None or int(row.knowledge_id) != int(correction.knowledge_id):
            return None
        return int(row.id)

    @classmethod
    async def _finalize_update(cls, session, correction: KnowledgeFileCorrection):
        """解析成功并收成当前版本后结束待办. 按当天 10 分封顶决定是否发分.

        Args:
            session: 持有纠错行锁的会话.
            correction: 仍待处理的纠错. 新文件此时已是主版本.

        Returns:
            发分载荷和审批通知参数. 超限时第一项为 None.

        Raises:
            ApprovalRequestNotFoundError: 审批实例不存在.
        """
        instance = (
            await session.exec(
                select(ApprovalInstance)
                .where(ApprovalInstance.id == int(correction.approval_instance_id or 0))
                .with_for_update()
            )
        ).first()
        if instance is None:
            raise ApprovalRequestNotFoundError()
        task = (
            await session.exec(
                select(ApprovalTask)
                .where(
                    ApprovalTask.instance_id == int(instance.id),
                    ApprovalTask.status == ApprovalTaskStatus.PENDING,
                )
                .with_for_update()
            )
        ).first()
        now = datetime.now()
        if task is not None:
            task.status = ApprovalTaskStatus.APPROVED
            task.acted_at = now
            task.update_time = now
            session.add(task)
        new_file_id = int(correction.pending_update_file_id or 0)
        correction.status = CORRECTION_APPROVED
        correction.pending_update_file_id = None
        correction.update_time = now
        instance.status = ApprovalInstanceStatus.APPROVED
        instance.latest_approver_user_id = int(correction.uploader_user_id)
        instance.current_node_name = None
        instance.update_time = now
        session.add(correction)
        session.add(instance)
        pay = await should_pay_update(session, applicant_user_id=int(correction.applicant_user_id))
        award_payload = await cls._create_award(
            session,
            correction,
            award_kind=AWARD_KIND_UPDATE,
            delta=UPDATE_POINTS,
            pay=pay,
        )
        await cls._delete_open_slot(session, correction)
        session.add(
            ApprovalActionLog(
                tenant_id=int(correction.tenant_id),
                instance_id=int(instance.id),
                action="approved",
                operator_user_id=int(correction.uploader_user_id),
                operator_user_name=str(correction.uploader_user_name or ""),
                detail={"comment": "", "correction_id": int(correction.id), "new_file_id": new_file_id},
                create_time=now,
                update_time=now,
            )
        )
        notify_payload = {
            "sender": int(correction.uploader_user_id),
            "receivers": [int(correction.applicant_user_id)],
            "action_code": "approval_instance_approved",
            "business_name": instance.business_name,
            "instance_id": int(instance.id),
            "reason": None,
        }
        return award_payload, notify_payload

    @classmethod
    async def promote_parsed_update_file(cls, file_id: int) -> None:
        """解析成功后, 把采纳并更新登记的新文件收成当前版本.

        仍待处理的单在这里关待办并发分. 旧路径若登记时已经关单, 这里只换版本.

        Args:
            file_id: 刚解析成功的知识库文件 ID.
        """
        award_payload = None
        notify_payload = None
        async with get_async_db_session() as session:
            correction = (
                await session.exec(
                    select(KnowledgeFileCorrection).where(
                        KnowledgeFileCorrection.pending_update_file_id == int(file_id),
                    )
                )
            ).first()
            if correction is None:
                return
            new_file = (
                await session.exec(select(KnowledgeFile).where(KnowledgeFile.id == int(file_id)))
            ).first()
            if new_file is None or int(new_file.status or 0) != int(KnowledgeFileStatus.SUCCESS.value):
                return
            await cls._promote_new_version(session, correction, int(file_id))
            if correction.status == CORRECTION_PENDING:
                award_payload, notify_payload = await cls._finalize_update(session, correction)
            else:
                correction.pending_update_file_id = None
                correction.update_time = datetime.now()
                session.add(correction)
            await session.commit()
        if notify_payload is not None:
            await cls._notify(**notify_payload)
        if award_payload is not None:
            await cls._dispatch_award(award_payload)

    @staticmethod
    async def _copy_non_ai_tags(session, *, old_id: int, new_id: int, user_id: int) -> None:
        """把旧文件上除自动标签以外的标签挂到新文件.

        Args:
            session: 当前事务.
            old_id: 旧文件 ID.
            new_id: 新文件 ID.
            user_id: 执行复制的用户 ID.
        """
        await _copy_tag_links(session, Tag, TagLink, old_id=old_id, new_id=new_id, user_id=user_id, review=False)
        await _copy_tag_links(
            session,
            ReviewTag,
            ReviewTagLink,
            old_id=old_id,
            new_id=new_id,
            user_id=user_id,
            review=True,
        )

    @classmethod
    async def decide_from_approval(
        cls,
        *,
        task_id: int,
        action: str,
        operator_user_id: int,
        operator_user_name: str,
        comment: str | None,
        new_file_id: int | None = None,
    ) -> None:
        """处理纠错待办. 平台管理员不能代批.

        Args:
            task_id: 审批任务 ID.
            action: adopt, adopt_update 或 reject. approve 与 adopt 相同.
            operator_user_id: 操作人用户 ID.
            operator_user_name: 操作人姓名.
            comment: 拒绝原因. 采纳和采纳并更新不用填.
            new_file_id: 采纳并更新时的新文件 ID.

        Raises:
            ApprovalRequestNotFoundError: 任务不存在.
            FileCorrectionUploaderOnlyError: 操作人不是冻结上传人.
            ApprovalRejectReasonRequiredError: 拒绝未填原因.
            ApprovalRequestAlreadyProcessedError: 任务已处理.
            FileCorrectionUpdateFileNotReadyError: 新文件尚未解析完成.
            FileCorrectionUpdateFileInvalidError: 新文件不能成为这篇文档的新版本.
        """
        normalized = str(action or "").strip().lower()
        if normalized == "approve":
            normalized = "adopt"
        if normalized == "reject" and not str(comment or "").strip():
            raise ApprovalRejectReasonRequiredError()
        if normalized not in {"adopt", "adopt_update", "reject"}:
            raise ApprovalRequestAlreadyProcessedError()
        if normalized == "adopt_update" and not new_file_id:
            raise FileCorrectionUpdateFileInvalidError()
        award_payload: dict | None = None
        async with get_async_db_session() as session:
            task = (
                await session.exec(select(ApprovalTask).where(ApprovalTask.id == int(task_id)).with_for_update())
            ).first()
            if task is None:
                raise ApprovalRequestNotFoundError()
            instance = (
                await session.exec(
                    select(ApprovalInstance).where(ApprovalInstance.id == int(task.instance_id)).with_for_update()
                )
            ).first()
            if instance is None or instance.scenario_code != FILE_CORRECTION_SCENARIO:
                raise ApprovalRequestNotFoundError()
            correction_id = int((instance.payload_snapshot or {}).get("correction_id") or 0)
            repo = KnowledgeFileCorrectionRepositoryImpl(session)
            correction = await repo.lock_by_id(correction_id)
            if correction is None:
                raise ApprovalRequestNotFoundError()
            if int(task.approver_user_id) != int(operator_user_id) or int(correction.uploader_user_id) != int(
                operator_user_id
            ):
                raise FileCorrectionUploaderOnlyError()
            if task.status != ApprovalTaskStatus.PENDING or correction.status != CORRECTION_PENDING:
                raise ApprovalRequestAlreadyProcessedError()
            phase = (await cls._update_phase(session, correction))[1]
            if is_update_in_progress(phase):
                raise FileCorrectionUpdateInProgressError()
            if is_update_failed(phase):
                await cls._discard_pending_update_file(session, correction)
            now = datetime.now()
            if normalized == "reject":
                task.status = ApprovalTaskStatus.REJECTED
                task.comment = str(comment or "").strip()
                correction.status = CORRECTION_REJECTED
                instance.status = ApprovalInstanceStatus.REJECTED
                action_name = "rejected"
            else:
                if normalized == "adopt_update":
                    await cls._promote_new_version(session, correction, int(new_file_id))
                    award_kind = AWARD_KIND_UPDATE
                    delta = UPDATE_POINTS
                    pay = await should_pay_update(
                        session, applicant_user_id=int(correction.applicant_user_id)
                    )
                else:
                    award_kind = AWARD_KIND_ADOPT
                    delta = ADOPT_POINTS
                    pay = not await cls._adopt_point_used_today(session, correction)
                task.status = ApprovalTaskStatus.APPROVED
                correction.status = CORRECTION_APPROVED
                instance.status = ApprovalInstanceStatus.APPROVED
                action_name = "approved"
                award_payload = await cls._create_award(
                    session,
                    correction,
                    award_kind=award_kind,
                    delta=delta,
                    pay=pay,
                )
            task.acted_at = now
            task.update_time = now
            correction.update_time = now
            correction.pending_update_file_id = None
            instance.latest_approver_user_id = int(operator_user_id)
            instance.current_node_name = None
            instance.update_time = now
            session.add(task)
            session.add(correction)
            session.add(instance)
            await cls._delete_open_slot(session, correction)
            session.add(
                ApprovalActionLog(
                    tenant_id=int(correction.tenant_id),
                    instance_id=int(instance.id),
                    action=action_name,
                    operator_user_id=int(operator_user_id),
                    operator_user_name=operator_user_name,
                    detail={"comment": str(comment or "").strip(), "correction_id": int(correction.id)},
                    create_time=now,
                    update_time=now,
                )
            )
            await session.commit()
            instance_id = int(instance.id)
            business_name = instance.business_name
            applicant_id = int(correction.applicant_user_id)
        await cls._notify(
            sender=int(operator_user_id),
            receivers=[applicant_id],
            action_code="approval_task_rejected" if normalized == "reject" else "approval_instance_approved",
            business_name=business_name,
            instance_id=instance_id,
            reason=str(comment or "").strip() or None,
        )
        if award_payload is not None:
            await cls._dispatch_award(award_payload)

    @classmethod
    async def withdraw(cls, *, instance_id: int, operator_user_id: int, operator_user_name: str) -> None:
        """反馈人撤回仍在审批中的纠错.

        Args:
            instance_id: 审批实例 ID.
            operator_user_id: 操作人用户 ID.
            operator_user_name: 操作人姓名.

        Raises:
            ApprovalRequestNotFoundError: 实例不存在.
            ApprovalRequestPermissionDeniedError: 不是反馈人.
            ApprovalRequestAlreadyProcessedError: 已不在待处理.
        """
        async with get_async_db_session() as session:
            instance = (
                await session.exec(
                    select(ApprovalInstance).where(ApprovalInstance.id == int(instance_id)).with_for_update()
                )
            ).first()
            if instance is None or instance.scenario_code != FILE_CORRECTION_SCENARIO:
                raise ApprovalRequestNotFoundError()
            if int(instance.applicant_user_id) != int(operator_user_id):
                raise ApprovalRequestPermissionDeniedError()
            correction_id = int((instance.payload_snapshot or {}).get("correction_id") or 0)
            repo = KnowledgeFileCorrectionRepositoryImpl(session)
            correction = await repo.lock_by_id(correction_id)
            if correction is None or correction.status != CORRECTION_PENDING:
                raise ApprovalRequestAlreadyProcessedError()
            if is_update_in_progress((await cls._update_phase(session, correction))[1]):
                raise FileCorrectionUpdateInProgressError()
            if is_update_failed((await cls._update_phase(session, correction))[1]):
                await cls._discard_pending_update_file(session, correction)
            now = datetime.now()
            tasks = (
                await session.exec(select(ApprovalTask).where(ApprovalTask.instance_id == int(instance.id)))
            ).all()
            approver_ids = []
            for task in tasks:
                if task.status == ApprovalTaskStatus.PENDING:
                    task.status = ApprovalTaskStatus.CANCELLED
                    task.acted_at = now
                    task.update_time = now
                    session.add(task)
                    if int(task.approver_user_id) != int(operator_user_id):
                        approver_ids.append(int(task.approver_user_id))
            correction.status = CORRECTION_WITHDRAWN
            correction.pending_update_file_id = None
            correction.update_time = now
            instance.status = ApprovalInstanceStatus.WITHDRAWN
            instance.update_time = now
            session.add(correction)
            session.add(instance)
            await cls._delete_open_slot(session, correction)
            session.add(
                ApprovalActionLog(
                    tenant_id=int(correction.tenant_id),
                    instance_id=int(instance.id),
                    action="withdrawn",
                    operator_user_id=int(operator_user_id),
                    operator_user_name=operator_user_name,
                    detail={"correction_id": int(correction.id)},
                    create_time=now,
                    update_time=now,
                )
            )
            await session.commit()
            business_name = instance.business_name
        if approver_ids:
            await cls._notify(
                sender=int(operator_user_id),
                receivers=approver_ids,
                action_code="approval_instance_withdrawn",
                business_name=business_name,
                instance_id=int(instance_id),
                reason=None,
            )

    @classmethod
    async def cancel_pending_for_files(cls, file_ids: list[int]) -> None:
        """文档删除后取消这些文件上的待处理纠错, 不追回已入账积分.

        Args:
            file_ids: 被删除的知识库文件 ID.
        """
        async with get_async_db_session() as session:
            deleted_ids = {int(item) for item in file_ids if int(item) > 0}
            if deleted_ids:
                pointer_rows = (
                    await session.exec(
                        select(KnowledgeFileCorrection).where(
                            col(KnowledgeFileCorrection.pending_update_file_id).in_(list(deleted_ids)),
                            KnowledgeFileCorrection.status == CORRECTION_PENDING,
                        )
                    )
                ).all()
                for correction in pointer_rows:
                    # 删的是更新文件时只清指针, 原文档上的待办还在.
                    if int(correction.file_id) not in deleted_ids:
                        correction.pending_update_file_id = None
                        session.add(correction)
            repo = KnowledgeFileCorrectionRepositoryImpl(session)
            rows = await repo.list_pending_for_files(file_ids)
            if not rows:
                await session.commit()
                return
            now = datetime.now()
            for correction in rows:
                await cls._discard_pending_update_file(session, correction)
                correction.status = CORRECTION_CANCELLED
                correction.pending_update_file_id = None
                correction.update_time = now
                session.add(correction)
                if correction.approval_instance_id:
                    instance = (
                        await session.exec(
                            select(ApprovalInstance).where(ApprovalInstance.id == int(correction.approval_instance_id))
                        )
                    ).first()
                    if instance is not None and instance.status == ApprovalInstanceStatus.PENDING:
                        instance.status = ApprovalInstanceStatus.CANCELLED
                        instance.update_time = now
                        session.add(instance)
                    tasks = (
                        await session.exec(
                            select(ApprovalTask).where(
                                ApprovalTask.instance_id == int(correction.approval_instance_id)
                            )
                        )
                    ).all()
                    for task in tasks:
                        if task.status == ApprovalTaskStatus.PENDING:
                            task.status = ApprovalTaskStatus.CANCELLED
                            task.acted_at = now
                            task.update_time = now
                            session.add(task)
                await cls._delete_open_slot(session, correction)
            await session.commit()

    @staticmethod
    async def _require_view(login_user, file_id: int, knowledge, scope) -> None:
        """判断当前用户能否查看这份文件.

        公共库读者的查看权来自库层级, 阅读页用有效权限加上 viewer, 不要求文件上有
        OpenFGA view_file. PermissionService.check 看不到这层, 会把已经打开公共库
        文档的人拒成 18405.

        Args:
            login_user: 当前登录用户.
            file_id: 知识库文件 ID.
            knowledge: 文件所在知识库.
            scope: 知识库层级. 没有层级时不能按公共库放行.

        Raises:
            FileCorrectionViewDeniedError: 当前用户不能查看该文件.
        """
        if _public_library_grants_view(knowledge, scope):
            return
        allowed = await PermissionService.check(
            int(login_user.user_id),
            "view_file",
            "knowledge_file",
            str(int(file_id)),
            login_user,
        )
        if not allowed:
            raise FileCorrectionViewDeniedError()

    @staticmethod
    def _require_space(knowledge, scope) -> None:
        if knowledge is None or bool(getattr(knowledge, "is_favorite", False)):
            raise FileCorrectionSpaceNotAllowedError()
        level = getattr(scope, "level", None) if scope is not None else None
        value = getattr(level, "value", level)
        if value not in _ELIGIBLE_LEVELS:
            raise FileCorrectionSpaceNotAllowedError()

    @staticmethod
    async def _require_uploader(session, uploader_id: int | None):
        if uploader_id is None:
            raise FileCorrectionUploaderUnavailableError()
        uploader = (
            await session.execute(sa_select(_USER_TABLE).where(_USER_TABLE.c.user_id == int(uploader_id)))
        ).first()
        if uploader is None or int(uploader.delete or 0) == 1:
            raise FileCorrectionUploaderUnavailableError()
        return uploader

    @classmethod
    async def retry_update_file(cls, *, login_user, correction_id: int) -> dict:
        """对解析失败的更新文件重新入队, 不换文件号.

        Args:
            login_user: 当前登录用户, 必须是冻结上传人.
            correction_id: 仍待处理的纠错单 ID.

        Returns:
            原更新文件的 id、解析状态和更新阶段.

        Raises:
            ApprovalRequestNotFoundError: 纠错单不存在.
            FileCorrectionUploaderOnlyError: 当前用户不是冻结上传人.
            ApprovalRequestAlreadyProcessedError: 纠错已不在待处理.
            FileCorrectionUpdateRetryNotAllowedError: 没有失败的更新文件.
        """
        register_lock = await _lock_for_correction(int(correction_id))
        async with register_lock:
            async with get_async_db_session() as session:
                correction = await KnowledgeFileCorrectionRepositoryImpl(session).lock_by_id(int(correction_id))
                if correction is None:
                    raise ApprovalRequestNotFoundError()
                if int(correction.uploader_user_id) != int(login_user.user_id):
                    raise FileCorrectionUploaderOnlyError()
                if correction.status != CORRECTION_PENDING:
                    raise ApprovalRequestAlreadyProcessedError()
                _file_status, phase = await cls._update_phase(session, correction)
                if not is_update_failed(phase):
                    raise FileCorrectionUpdateRetryNotAllowedError()
                pending_id = int(correction.pending_update_file_id or 0)
                row = (
                    await session.exec(select(KnowledgeFile).where(KnowledgeFile.id == pending_id))
                ).first()
                if row is None:
                    raise FileCorrectionUpdateRetryNotAllowedError()
                row.status = int(KnowledgeFileStatus.WAITING.value)
                session.add(row)
                await session.commit()
                file_name = row.file_name
            from bisheng.knowledge.domain.services.knowledge_parse_dispatch_service import (
                KnowledgeParseAttemptKind,
                dispatch_knowledge_parse_task,
            )
            from bisheng.knowledge.domain.services.knowledge_pdf_artifact_service import (
                request_pdf_artifact_generation,
            )

            await request_pdf_artifact_generation(row)
            await dispatch_knowledge_parse_task(
                attempt_kind=KnowledgeParseAttemptKind.RETRY,
                file_id=pending_id,
                operator_user_id=int(login_user.user_id),
                operator_is_global_super=bool(getattr(login_user, "is_global_super", False)),
            )
            return {
                "id": pending_id,
                "status": int(KnowledgeFileStatus.WAITING.value),
                "file_name": file_name,
                "update_phase": UPDATE_PHASE_UPDATING,
            }

    @staticmethod
    async def _update_phase(session, correction: KnowledgeFileCorrection) -> tuple[int | None, str]:
        """读取指针文件状态并推导更新阶段.

        Args:
            session: 当前会话.
            correction: 纠错单.

        Returns:
            文件解析状态和 idle/updating/failed. 指针文件不存在时当作 idle.
        """
        pending_id = int(correction.pending_update_file_id or 0)
        if pending_id <= 0:
            return None, UPDATE_PHASE_IDLE
        row = (await session.exec(select(KnowledgeFile).where(KnowledgeFile.id == pending_id))).first()
        if row is None:
            return None, UPDATE_PHASE_IDLE
        status = int(row.status or 0)
        return status, classify_update_phase(pending_id, status)

    @staticmethod
    async def _discard_pending_update_file(session, correction: KnowledgeFileCorrection) -> None:
        """删掉尚未成为当前版本的更新文件, 并清空指针.

        已经是主版本的文件不删. 对象存储里的孤儿文件这版不清理.

        Args:
            session: 当前事务.
            correction: 仍指向更新文件的纠错单.
        """
        pending_id = int(correction.pending_update_file_id or 0)
        correction.pending_update_file_id = None
        session.add(correction)
        if pending_id <= 0:
            return
        primary = (
            await session.exec(
                select(KnowledgeDocumentVersion).where(
                    KnowledgeDocumentVersion.knowledge_file_id == pending_id,
                    KnowledgeDocumentVersion.is_primary == True,  # noqa: E712
                )
            )
        ).first()
        if primary is not None:
            return
        row = (await session.exec(select(KnowledgeFile).where(KnowledgeFile.id == pending_id))).first()
        if row is not None:
            await session.delete(row)

    @staticmethod
    async def _delete_open_slot(session, correction: KnowledgeFileCorrection) -> None:
        slot = (
            await session.exec(
                select(KnowledgeFileCorrectionOpen).where(
                    KnowledgeFileCorrectionOpen.tenant_id == int(correction.tenant_id),
                    KnowledgeFileCorrectionOpen.file_id == int(correction.file_id),
                    KnowledgeFileCorrectionOpen.applicant_user_id == int(correction.applicant_user_id),
                    KnowledgeFileCorrectionOpen.correction_id == int(correction.id),
                )
            )
        ).first()
        if slot is not None:
            await session.delete(slot)

    @staticmethod
    async def _adopt_point_used_today(session, correction: KnowledgeFileCorrection) -> bool:
        now = datetime.now(_SHANGHAI)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
        rows = (
            await session.exec(
                select(KnowledgeFileCorrectionAward).where(
                    KnowledgeFileCorrectionAward.tenant_id == int(correction.tenant_id),
                    KnowledgeFileCorrectionAward.file_id == int(correction.file_id),
                    KnowledgeFileCorrectionAward.applicant_user_id == int(correction.applicant_user_id),
                    KnowledgeFileCorrectionAward.award_kind == AWARD_KIND_ADOPT,
                    KnowledgeFileCorrectionAward.award_state == "awarded",
                    KnowledgeFileCorrectionAward.create_time >= day_start,
                )
            )
        ).all()
        return len(list(rows)) > 0

    @staticmethod
    async def _create_award(
        session,
        correction: KnowledgeFileCorrection,
        *,
        award_kind: str,
        delta: int,
        pay: bool,
    ) -> dict | None:
        session.add(
            KnowledgeFileCorrectionAward(
                tenant_id=int(correction.tenant_id),
                file_id=int(correction.file_id),
                applicant_user_id=int(correction.applicant_user_id),
                correction_id=int(correction.id),
                award_kind=award_kind,
                award_state=AWARD_RESERVED if pay else "skipped",
                create_time=datetime.now(),
            )
        )
        await session.flush()
        if not pay:
            return None
        return {
            "tenant_id": int(correction.tenant_id),
            "file_id": int(correction.file_id),
            "applicant_user_id": int(correction.applicant_user_id),
            "correction_id": int(correction.id),
            "award_kind": award_kind,
            "delta": int(delta),
            "space_id": int(correction.knowledge_id),
        }

    @staticmethod
    async def _promote_new_version(session, correction: KnowledgeFileCorrection, new_file_id: int) -> None:
        """把新文件收成当前主版本, 原文件留在历史版本.

        Args:
            session: 当前事务.
            correction: 待处理纠错.
            new_file_id: 已解析完成的新文件 ID.

        Raises:
            SpaceFileNotFoundError: 新文件不存在.
            FileCorrectionUpdateFileInvalidError: 新文件不在同一知识库, 或已属于别的多版本链.
            FileCorrectionUpdateFileNotReadyError: 新文件尚未解析成功.
        """
        new_file = (
            await session.exec(select(KnowledgeFile).where(KnowledgeFile.id == int(new_file_id)).with_for_update())
        ).first()
        if new_file is None:
            raise SpaceFileNotFoundError()
        if int(new_file.id) == int(correction.file_id) or int(new_file.knowledge_id) != int(correction.knowledge_id):
            raise FileCorrectionUpdateFileInvalidError()
        if int(new_file.status or 0) != int(KnowledgeFileStatus.SUCCESS.value):
            raise FileCorrectionUpdateFileNotReadyError()
        now = datetime.now()
        old_version = (
            await session.exec(
                select(KnowledgeDocumentVersion).where(
                    KnowledgeDocumentVersion.knowledge_file_id == int(correction.file_id)
                )
            )
        ).first()
        if old_version is None:
            document = KnowledgeDocument(
                tenant_id=int(correction.tenant_id),
                knowledge_id=int(correction.knowledge_id),
                lifecycle_status="active",
                create_time=now,
                update_time=now,
            )
            session.add(document)
            await session.flush()
            old_version = KnowledgeDocumentVersion(
                document_id=int(document.id),
                knowledge_file_id=int(correction.file_id),
                version_no=1,
                is_primary=True,
                create_time=now,
                update_time=now,
            )
            session.add(old_version)
            await session.flush()
            document.primary_version_id = int(old_version.id)
            session.add(document)
        else:
            document = (
                await session.exec(
                    select(KnowledgeDocument).where(KnowledgeDocument.id == int(old_version.document_id))
                )
            ).first()
            if document is None:
                raise FileCorrectionUpdateFileInvalidError()
        versions = list(
            (
                await session.exec(
                    select(KnowledgeDocumentVersion).where(
                        KnowledgeDocumentVersion.document_id == int(document.id)
                    )
                )
            ).all()
        )
        next_no = max(int(item.version_no) for item in versions) + 1
        incoming = (
            await session.exec(
                select(KnowledgeDocumentVersion).where(
                    KnowledgeDocumentVersion.knowledge_file_id == int(new_file.id)
                )
            )
        ).first()
        if incoming is not None and int(incoming.document_id) != int(document.id):
            siblings = (
                await session.exec(
                    select(KnowledgeDocumentVersion).where(
                        KnowledgeDocumentVersion.document_id == int(incoming.document_id)
                    )
                )
            ).all()
            if len(list(siblings)) > 1:
                raise FileCorrectionUpdateFileInvalidError()
            incoming.document_id = int(document.id)
            incoming.version_no = next_no
            incoming.is_primary = True
            incoming.update_time = now
            session.add(incoming)
            saved_id = int(incoming.id)
        elif incoming is None:
            incoming = KnowledgeDocumentVersion(
                document_id=int(document.id),
                knowledge_file_id=int(new_file.id),
                version_no=next_no,
                is_primary=True,
                create_time=now,
                update_time=now,
            )
            session.add(incoming)
            await session.flush()
            saved_id = int(incoming.id)
        else:
            incoming.is_primary = True
            incoming.update_time = now
            session.add(incoming)
            saved_id = int(incoming.id)
        for version in versions:
            if int(version.id) != saved_id and version.is_primary:
                version.is_primary = False
                version.update_time = now
                session.add(version)
        if old_version.is_primary and int(old_version.id) != saved_id:
            old_version.is_primary = False
            old_version.update_time = now
            session.add(old_version)
        document.primary_version_id = saved_id
        document.update_time = now
        session.add(document)

    @staticmethod
    async def _dispatch_award(payload: dict) -> None:
        try:
            from bisheng.points.domain.services.points_award_hooks import notify_file_correction_adopted

            await notify_file_correction_adopted(
                tenant_id=int(payload["tenant_id"]),
                file_id=int(payload["file_id"]),
                applicant_user_id=int(payload["applicant_user_id"]),
                correction_id=int(payload["correction_id"]),
                award_kind=str(payload["award_kind"]),
                delta=int(payload["delta"]),
                space_id=int(payload.get("space_id") or 0),
            )
        except Exception:
            logger.exception(
                "file correction points dispatch failed correction_id=%s",
                payload.get("correction_id"),
            )

    @staticmethod
    async def _notify(
        *,
        sender: int,
        receivers: list[int],
        action_code: str,
        business_name: str,
        instance_id: int,
        reason: str | None,
    ) -> None:
        try:
            from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService

            await ApprovalCenterService._send_approval_notify(
                sender=sender,
                receiver_user_ids=receivers,
                action_code=action_code,
                business_name=business_name,
                instance_id=instance_id,
                reason=reason,
            )
        except Exception:
            logger.exception("file correction notify failed instance_id=%s", instance_id)


def promote_parsed_update_file_sync(file_id: int) -> None:
    """在解析进程里把已登记的新文件收成当前版本.

    Args:
        file_id: 刚解析成功的知识库文件 ID.
    """
    from bisheng.worker._asyncio_utils import run_async_task

    run_async_task(lambda: KnowledgeFileCorrectionService.promote_parsed_update_file(int(file_id)))


async def cancel_pending_file_corrections(file_ids: list[int]) -> None:
    """删除文档后取消待处理纠错.

    Args:
        file_ids: 被删除的知识库文件 ID.
    """
    await KnowledgeFileCorrectionService.cancel_pending_for_files(file_ids)
