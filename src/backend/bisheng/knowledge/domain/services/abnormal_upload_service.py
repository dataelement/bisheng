"""平台管理员查看并处理当前租户的异常上传."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.knowledge_space import (
    AbnormalFileStateConflictError,
    AbnormalUploadRetryFailedError,
    SpaceFileNotFoundError,
)
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import KnowledgeFileRepository
from bisheng.knowledge.domain.services.knowledge_parse_dispatch_service import (
    KnowledgeParseAttemptKind,
    dispatch_knowledge_parse_task,
)
from bisheng.user.domain.services.platform_operator import can_platform_operate

logger = logging.getLogger(__name__)

ABNORMAL_UPLOAD_STATUSES = frozenset(
    {
        KnowledgeFileStatus.FAILED.value,
        KnowledgeFileStatus.TIMEOUT.value,
        KnowledgeFileStatus.VIOLATION.value,
    }
)
MAX_PAGE_SIZE = 100
MAX_BATCH_SIZE = 100
MAX_KEYWORD_LENGTH = 100
MAX_ORG_NAME_LENGTH = 128
_SOURCE_SPACE_LEVELS = frozenset(item.value for item in KnowledgeSpaceLevelEnum)

ParseDispatcher = Callable[..., Awaitable[Any]]


class AbnormalUploadService:
    """列表、重新解析和普通删除. 删除不走违规扣分."""

    def __init__(
        self,
        *,
        login_user: Any,
        file_repository: KnowledgeFileRepository,
        space_service: Any,
        dispatcher: ParseDispatcher | None = None,
    ) -> None:
        self.login_user = login_user
        self.file_repository = file_repository
        self.space_service = space_service
        self._dispatcher = dispatcher

    async def list_uploads(
        self,
        *,
        page: int,
        page_size: int,
        status: int | None = None,
        space_level: str | None = None,
        keyword: str | None = None,
        knowledge_name: str | None = None,
        uploader_name: str | None = None,
        uploader_company: str | None = None,
        uploader_department: str | None = None,
        uploader_office: str | None = None,
        update_time_from: str | None = None,
        update_time_to: str | None = None,
    ) -> dict:
        self._require_operator()
        self._require_page(page, page_size)
        filters = self._require_filters(
            status=status,
            space_level=space_level,
            keyword=keyword,
            knowledge_name=knowledge_name,
            uploader_name=uploader_name,
            uploader_company=uploader_company,
            uploader_department=uploader_department,
            uploader_office=uploader_office,
            update_time_from=update_time_from,
            update_time_to=update_time_to,
        )
        items, total = await self.file_repository.list_abnormal_source_uploads(
            offset=(page - 1) * page_size,
            limit=page_size,
            **filters,
        )
        return {"data": items, "total": total}

    async def list_org_options(self) -> dict[str, list[str]]:
        self._require_operator()
        return await self.file_repository.list_abnormal_uploader_org_options()

    async def retry(self, file_id: int) -> None:
        self._require_operator()
        file_record = await self.file_repository.lock_abnormal_source_file(file_id)
        if file_record is None:
            raise SpaceFileNotFoundError()
        previous_status = int(file_record.status or -1)
        if previous_status not in ABNORMAL_UPLOAD_STATUSES:
            raise AbnormalFileStateConflictError()
        previous_remark = file_record.remark
        file_record.status = KnowledgeFileStatus.WAITING.value
        file_record.remark = ""
        file_record.updater_id = int(self.login_user.user_id)
        file_record.updater_name = str(getattr(self.login_user, "user_name", "") or "")
        await self.file_repository.session.commit()
        try:
            await self._dispatch(file_record)
        except Exception:
            logger.exception("abnormal upload retry dispatch failed file_id=%s", file_id)
            file_record.status = previous_status
            file_record.remark = previous_remark
            await self.file_repository.session.commit()
            raise AbnormalUploadRetryFailedError() from None
        await self._audit(file_id, "abnormal_upload.retry")

    async def retry_batch(self, file_ids: list[int]) -> dict[str, int]:
        """逐条重新解析. 已派发的不回滚."""
        self._require_operator()
        unique_ids = self._require_batch_ids(file_ids)
        retried = 0
        failed = 0
        for file_id in unique_ids:
            try:
                await self.retry(file_id)
                retried += 1
            except BaseErrorCode as exc:
                if int(getattr(exc, "code", 0) or 0) == 403:
                    raise
                failed += 1
            except Exception:
                logger.exception("abnormal upload batch retry failed file_id=%s", file_id)
                failed += 1
        return {"retried": retried, "failed": failed}

    async def delete(self, file_id: int) -> None:
        """普通回收删除. 不调用违规删除, 不扣分."""
        self._require_operator()
        file_record = await self.file_repository.lock_abnormal_source_file(file_id)
        if file_record is None:
            raise SpaceFileNotFoundError()
        if int(file_record.status or -1) not in ABNORMAL_UPLOAD_STATUSES:
            raise AbnormalFileStateConflictError()
        # 锁留在当前事务里会挡住 delete_file 的另一个会话. 先提交锁检查, 再按状态回收.
        await self.file_repository.session.commit()
        await self.space_service.delete_file(
            file_id,
            skip_space_permission=True,
            require_statuses=set(ABNORMAL_UPLOAD_STATUSES),
        )
        await self._audit(file_id, "abnormal_upload.delete")

    async def delete_batch(self, file_ids: list[int]) -> dict[str, int]:
        """逐条普通回收. 已成功的不回滚."""
        self._require_operator()
        unique_ids = self._require_batch_ids(file_ids)
        deleted = 0
        failed = 0
        for file_id in unique_ids:
            try:
                await self.delete(file_id)
                deleted += 1
            except UnAuthorizedError:
                raise
            except BaseErrorCode:
                failed += 1
            except Exception:
                logger.exception("abnormal upload batch delete failed file_id=%s", file_id)
                failed += 1
        return {"deleted": deleted, "failed": failed}

    def _require_operator(self) -> None:
        if not can_platform_operate(self.login_user):
            raise UnAuthorizedError()

    @staticmethod
    def _require_page(page: int, page_size: int) -> None:
        if page < 1 or page_size < 1 or page_size > MAX_PAGE_SIZE:
            raise ValueError("invalid abnormal upload page")

    @staticmethod
    def _parse_day(value: str | None) -> date | None:
        text = (value or "").strip()
        if not text:
            return None
        try:
            return datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError("invalid abnormal upload filter") from exc

    @staticmethod
    def _require_text(value: str | None) -> str | None:
        text = (value or "").strip() or None
        if text is not None and len(text) > MAX_KEYWORD_LENGTH:
            raise ValueError("invalid abnormal upload filter")
        return text

    @classmethod
    def _require_filters(
        cls,
        *,
        status: int | None,
        space_level: str | None,
        keyword: str | None,
        knowledge_name: str | None,
        uploader_name: str | None,
        uploader_company: str | None,
        uploader_department: str | None,
        uploader_office: str | None,
        update_time_from: str | None,
        update_time_to: str | None,
    ) -> dict:
        status_value = status
        if status_value is not None and status_value not in ABNORMAL_UPLOAD_STATUSES:
            raise ValueError("invalid abnormal upload filter")
        level_value = (space_level or "").strip() or None
        if level_value is not None and level_value not in _SOURCE_SPACE_LEVELS:
            raise ValueError("invalid abnormal upload filter")
        from_day = cls._parse_day(update_time_from)
        to_day = cls._parse_day(update_time_to)
        if from_day and to_day and from_day > to_day:
            raise ValueError("invalid abnormal upload filter")
        return {
            "status": status_value,
            "space_level": level_value,
            "keyword": cls._require_text(keyword),
            "knowledge_name": cls._require_text(knowledge_name),
            "uploader_name": cls._require_text(uploader_name),
            "uploader_company": cls._require_org_name(uploader_company),
            "uploader_department": cls._require_org_name(uploader_department),
            "uploader_office": cls._require_org_name(uploader_office),
            "update_time_from": from_day,
            "update_time_to": to_day,
        }

    @staticmethod
    def _require_org_name(value: str | None) -> str | None:
        text = (value or "").strip() or None
        if text is not None and len(text) > MAX_ORG_NAME_LENGTH:
            raise ValueError("invalid abnormal upload filter")
        return text

    @staticmethod
    def _require_batch_ids(file_ids: list[int]) -> list[int]:
        unique_ids: list[int] = []
        seen: set[int] = set()
        for file_id in file_ids:
            if file_id in seen:
                continue
            seen.add(file_id)
            unique_ids.append(file_id)
        if not unique_ids or len(unique_ids) > MAX_BATCH_SIZE:
            raise ValueError("invalid abnormal upload batch")
        return unique_ids

    async def _dispatch(self, file_record: Any) -> None:
        dispatcher = self._dispatcher or dispatch_knowledge_parse_task
        await dispatcher(
            attempt_kind=KnowledgeParseAttemptKind.RETRY,
            file_id=int(file_record.id),
            operator_user_id=int(self.login_user.user_id),
            operator_is_global_super=bool(getattr(self.login_user, "is_global_super", False)),
            tenant_id=int(file_record.tenant_id) if file_record.tenant_id is not None else None,
            knowledge_id=int(file_record.knowledge_id),
        )

    async def _audit(self, file_id: int, action: str) -> None:
        tenant_id = int(getattr(self.login_user, "tenant_id", None) or 1)
        try:
            await AuditLogDao.ainsert_v2(
                tenant_id=tenant_id,
                operator_id=int(self.login_user.user_id),
                operator_tenant_id=tenant_id,
                action=action,
                target_type="knowledge_file",
                target_id=str(file_id),
                operator_name=str(getattr(self.login_user, "user_name", "") or ""),
                metadata={"result": "success"},
            )
        except Exception:
            logger.exception("abnormal upload audit failed action=%s file_id=%s", action, file_id)
