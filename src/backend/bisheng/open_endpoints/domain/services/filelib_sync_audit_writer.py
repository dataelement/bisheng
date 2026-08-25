from __future__ import annotations

from typing import Any

from fastapi import Request
from loguru import logger

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.filelib_sync import FilelibSyncError
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.open_endpoints.domain.schemas.filelib_sync import FilelibSyncParams, FilelibSyncResponseData
from bisheng.utils import get_request_ip

ACTION_UPLOAD_SUCCESS = "filelib_sync.upload.success"
ACTION_UPLOAD_FAILED = "filelib_sync.upload.failed"
ACTION_INSPECTION_BATCH_SUCCESS = "filelib_sync.inspection_standard.batch.success"
ACTION_INSPECTION_BATCH_FAILED = "filelib_sync.inspection_standard.batch.failed"


class FilelibSyncAuditWriter:
    @staticmethod
    def _append_note_line(lines: list[str], label: str, value: Any | None) -> None:
        if value is None:
            return
        text = str(value).strip()
        if not text:
            return
        lines.append(f"{label}: {text}")

    @classmethod
    def _build_upload_note(
        cls,
        *,
        token_id: int,
        token_name: str,
        params: FilelibSyncParams,
        folder_display_name: str | None,
        identity: Any | None,
        target: Any | None,
        business_domain_code: str | None,
        category_code: str | None,
        subcategory_code: str | None,
        created_file: KnowledgeFile | None,
        error_code: int | None,
        error_message: str | None,
    ) -> str:
        lines: list[str] = []
        token_label = token_name.strip() or f"Token#{token_id}"
        cls._append_note_line(lines, "Token", f"{token_label} (ID: {token_id})")
        if target is not None:
            knowledge_name = str(getattr(target.space, "name", "") or "").strip()
            knowledge_id = getattr(target.space, "id", None)
            if knowledge_name and knowledge_id is not None:
                cls._append_note_line(lines, "知识空间", f"{knowledge_name} (ID: {knowledge_id})")
            elif knowledge_id is not None:
                cls._append_note_line(lines, "知识空间ID", knowledge_id)
            if folder_display_name is not None:
                cls._append_note_line(lines, "目录", folder_display_name)
            if bool(getattr(target, "used_personal_fallback", False)):
                cls._append_note_line(lines, "目标降级", "Token用户个人库")
        cls._append_note_line(lines, "外部文件ID", params.external_file_id)
        cls._append_note_line(lines, "文件名", params.file_name)
        if identity is not None:
            responsible_label = str(
                getattr(identity, "responsible_user_external_id", "") or params.responsible_person_id or ""
            ).strip()
            responsible_id = getattr(identity, "responsible_user_id", None)
            if responsible_label and responsible_id is not None:
                cls._append_note_line(lines, "主责人", f"{responsible_label} (ID: {responsible_id})")
            elif responsible_label:
                cls._append_note_line(lines, "主责人", responsible_label)
        elif params.responsible_person_id:
            cls._append_note_line(lines, "主责人", params.responsible_person_id)
        cls._append_note_line(lines, "业务域", business_domain_code)
        if category_code or subcategory_code:
            cls._append_note_line(
                lines,
                "分类",
                " / ".join(part for part in [category_code, subcategory_code] if part),
            )
        if created_file is not None and str(created_file.file_encoding or "").strip():
            cls._append_note_line(lines, "文件编码", created_file.file_encoding)
        if error_code is not None:
            cls._append_note_line(lines, "错误码", error_code)
        cls._append_note_line(lines, "错误信息", error_message)
        return "\n".join(lines)

    @classmethod
    def _build_inspection_batch_note(
        cls,
        *,
        token_id: int,
        token_name: str,
        knowledge_id: int,
        knowledge_name: str | None,
        data_start_time: str,
        data_end_time: str,
        group_count: int,
        file_count: int | None = None,
        success_count: int | None = None,
        failed_count: int | None = None,
        error_code: int | None = None,
        error_message: str | None = None,
    ) -> str:
        lines: list[str] = []
        token_label = token_name.strip() or f"Token#{token_id}"
        cls._append_note_line(lines, "Token", f"{token_label} (ID: {token_id})")
        space_label = (knowledge_name or "").strip() or f"知识空间#{knowledge_id}"
        cls._append_note_line(lines, "知识空间", f"{space_label} (ID: {knowledge_id})")
        cls._append_note_line(lines, "数据时间范围", f"{data_start_time} ~ {data_end_time}")
        cls._append_note_line(lines, "分组数", group_count)
        if file_count is not None:
            cls._append_note_line(lines, "文件数", file_count)
        if success_count is not None:
            cls._append_note_line(lines, "成功数", success_count)
        if failed_count is not None:
            cls._append_note_line(lines, "失败数", failed_count)
        if error_code is not None:
            cls._append_note_line(lines, "错误码", error_code)
        cls._append_note_line(lines, "错误信息", error_message)
        return "\n".join(lines)

    @staticmethod
    def _request_id(request: Request | None) -> str | None:
        if request is None:
            return None
        value = str(request.headers.get("X-Request-ID") or "").strip()
        return value or None

    @classmethod
    def _build_upload_metadata(
        cls,
        *,
        request: Request | None,
        token_id: int,
        token_name: str,
        params: FilelibSyncParams,
        endpoint_tag: str,
        trigger_type: str | None,
        identity: Any | None,
        target: Any | None,
        business_domain_code: str | None,
        category_code: str | None,
        subcategory_code: str | None,
        created_file: KnowledgeFile | None,
        response: FilelibSyncResponseData | None,
        replaced_file_id: int | None,
        folder_display_name: str | None,
        extra_user_metadata: dict[str, Any] | None,
        error_code: int | None,
        error_message: str | None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "endpoint": endpoint_tag,
            "token_id": token_id,
            "token_name": token_name,
            "external_file_id": params.external_file_id,
            "file_name": params.file_name,
            "file_id": int(created_file.id) if created_file is not None else None,
            "knowledge_id": int(target.space.id) if target is not None else None,
            "knowledge_name": target.space.name if target is not None else None,
            "folder_id": target.folder_id if target is not None else None,
            "folder_name": folder_display_name,
            "responsible_user_id": int(identity.responsible_user_id) if identity is not None else None,
            "responsible_user_name": (
                str(getattr(identity, "responsible_user_name", "") or "").strip() or None
                if identity is not None
                else None
            ),
            "responsible_person_external_id": (
                identity.responsible_user_external_id if identity is not None else params.responsible_person_id
            ),
            "business_domain_code": business_domain_code,
            "category_code": category_code,
            "subcategory_code": subcategory_code,
            "file_encoding": str(created_file.file_encoding or "") if created_file is not None else None,
            "personal_fallback": bool(target.used_personal_fallback) if target is not None else None,
            "version_link_pending": bool(response.version_link_pending) if response is not None else None,
            "replaced_file_id": replaced_file_id,
            "trigger_type": trigger_type,
            "tags": list(params.tags or []),
            "error_code": error_code,
            "error_message": error_message,
            "request_id": cls._request_id(request),
        }
        if extra_user_metadata:
            metadata.update(extra_user_metadata)
        return metadata

    @classmethod
    async def write_upload_success(
        cls,
        *,
        request: Request | None,
        login_user: UserPayload,
        token_id: int,
        token_name: str,
        params: FilelibSyncParams,
        identity: Any,
        target: Any,
        created_file: KnowledgeFile,
        response: FilelibSyncResponseData,
        endpoint_tag: str,
        trigger_type: str | None,
        business_domain_code: str | None,
        category_code: str,
        subcategory_code: str,
        replaced_file_id: int | None,
        extra_user_metadata: dict[str, Any] | None = None,
        folder_display_name: str | None = None,
    ) -> None:
        metadata = cls._build_upload_metadata(
            request=request,
            token_id=token_id,
            token_name=token_name,
            params=params,
            endpoint_tag=endpoint_tag,
            trigger_type=trigger_type,
            identity=identity,
            target=target,
            business_domain_code=business_domain_code,
            category_code=category_code,
            subcategory_code=subcategory_code,
            created_file=created_file,
            response=response,
            replaced_file_id=replaced_file_id,
            extra_user_metadata=extra_user_metadata,
            folder_display_name=folder_display_name,
            error_code=None,
            error_message=None,
        )
        note = cls._build_upload_note(
            token_id=token_id,
            token_name=token_name,
            params=params,
            folder_display_name=folder_display_name,
            identity=identity,
            target=target,
            business_domain_code=business_domain_code,
            category_code=category_code,
            subcategory_code=subcategory_code,
            created_file=created_file,
            error_code=None,
            error_message=None,
        )
        try:
            await AuditLogDao.ainsert_v2(
                tenant_id=int(getattr(target.space, "tenant_id", None) or login_user.tenant_id),
                operator_id=int(login_user.user_id),
                operator_tenant_id=int(login_user.tenant_id),
                operator_name=str(login_user.user_name or ""),
                action=ACTION_UPLOAD_SUCCESS,
                target_type="knowledge_file",
                target_id=str(created_file.id),
                object_name=str(params.file_name or params.external_file_id),
                note=note,
                metadata=metadata,
                ip_address=get_request_ip(request) if request is not None else None,
            )
        except Exception:
            logger.exception(
                "filelib sync success audit write failed external_file_id={} file_id={}",
                params.external_file_id,
                created_file.id,
            )

    @classmethod
    async def write_upload_failed(
        cls,
        *,
        request: Request | None,
        login_user: UserPayload,
        token_id: int,
        token_name: str,
        params: FilelibSyncParams,
        endpoint_tag: str,
        trigger_type: str | None,
        identity: Any | None,
        target: Any | None,
        business_domain_code: str | None,
        category_code: str,
        subcategory_code: str,
        replaced_file_id: int | None,
        extra_user_metadata: dict[str, Any] | None,
        error: Exception,
        created_file: KnowledgeFile | None = None,
        folder_display_name: str | None = None,
    ) -> None:
        error_code: int | None = None
        error_message = str(error)
        if isinstance(error, FilelibSyncError):
            error_code = int(error.code)
            error_message = str(error.message)

        metadata = cls._build_upload_metadata(
            request=request,
            token_id=token_id,
            token_name=token_name,
            params=params,
            endpoint_tag=endpoint_tag,
            trigger_type=trigger_type,
            identity=identity,
            target=target,
            business_domain_code=business_domain_code,
            category_code=category_code,
            subcategory_code=subcategory_code,
            created_file=created_file,
            response=None,
            replaced_file_id=replaced_file_id,
            extra_user_metadata=extra_user_metadata,
            folder_display_name=folder_display_name,
            error_code=error_code,
            error_message=error_message,
        )
        note = cls._build_upload_note(
            token_id=token_id,
            token_name=token_name,
            params=params,
            folder_display_name=folder_display_name,
            identity=identity,
            target=target,
            business_domain_code=business_domain_code,
            category_code=category_code,
            subcategory_code=subcategory_code,
            created_file=created_file,
            error_code=error_code,
            error_message=error_message,
        )
        target_id = (
            str(created_file.id)
            if created_file is not None
            else str(params.external_file_id or "")
        )
        tenant_id = int(
            getattr(target.space, "tenant_id", None) if target is not None else login_user.tenant_id
        )
        try:
            await AuditLogDao.ainsert_v2(
                tenant_id=tenant_id,
                operator_id=int(login_user.user_id),
                operator_tenant_id=int(login_user.tenant_id),
                operator_name=str(login_user.user_name or ""),
                action=ACTION_UPLOAD_FAILED,
                target_type="knowledge_file" if created_file is not None else "external_file",
                target_id=target_id,
                object_name=str(params.file_name or params.external_file_id),
                note=note,
                metadata=metadata,
                ip_address=get_request_ip(request) if request is not None else None,
            )
        except Exception:
            logger.exception(
                "filelib sync failed audit write failed external_file_id={} error_code={}",
                params.external_file_id,
                error_code,
            )

    @classmethod
    async def write_inspection_batch_success(
        cls,
        *,
        request: Request | None,
        login_user: UserPayload,
        token_id: int,
        token_name: str,
        knowledge_id: int,
        knowledge_name: str | None,
        data_start_time: str,
        data_end_time: str,
        group_count: int,
        file_count: int,
    ) -> None:
        metadata = {
            "endpoint": "inspection_standard_sync",
            "token_id": token_id,
            "token_name": token_name,
            "knowledge_id": knowledge_id,
            "knowledge_name": knowledge_name,
            "group_count": group_count,
            "file_count": file_count,
            "success_count": file_count,
            "failed_count": 0,
            "start_time": data_start_time,
            "end_time": data_end_time,
            "request_id": cls._request_id(request),
        }
        note = cls._build_inspection_batch_note(
            token_id=token_id,
            token_name=token_name,
            knowledge_id=knowledge_id,
            knowledge_name=knowledge_name,
            data_start_time=data_start_time,
            data_end_time=data_end_time,
            group_count=group_count,
            file_count=file_count,
            success_count=file_count,
            failed_count=0,
        )
        try:
            await AuditLogDao.ainsert_v2(
                tenant_id=int(login_user.tenant_id),
                operator_id=int(login_user.user_id),
                operator_tenant_id=int(login_user.tenant_id),
                operator_name=str(login_user.user_name or ""),
                action=ACTION_INSPECTION_BATCH_SUCCESS,
                target_type="knowledge_space",
                target_id=str(knowledge_id),
                object_name=knowledge_name or f"knowledge-{knowledge_id}",
                note=note,
                metadata=metadata,
                ip_address=get_request_ip(request) if request is not None else None,
            )
        except Exception:
            logger.exception(
                "filelib inspection batch success audit write failed knowledge_id={}",
                knowledge_id,
            )

    @classmethod
    async def write_inspection_batch_failed(
        cls,
        *,
        request: Request | None,
        login_user: UserPayload,
        token_id: int,
        token_name: str,
        knowledge_id: int,
        knowledge_name: str | None,
        data_start_time: str,
        data_end_time: str,
        group_count: int,
        success_count: int,
        error: Exception,
    ) -> None:
        error_code: int | None = None
        error_message = str(error)
        if isinstance(error, FilelibSyncError):
            error_code = int(error.code)
            error_message = str(error.message)

        metadata = {
            "endpoint": "inspection_standard_sync",
            "token_id": token_id,
            "token_name": token_name,
            "knowledge_id": knowledge_id,
            "knowledge_name": knowledge_name,
            "group_count": group_count,
            "file_count": group_count,
            "success_count": success_count,
            "failed_count": max(group_count - success_count, 1),
            "start_time": data_start_time,
            "end_time": data_end_time,
            "error_code": error_code,
            "error_message": error_message,
            "request_id": cls._request_id(request),
        }
        note = cls._build_inspection_batch_note(
            token_id=token_id,
            token_name=token_name,
            knowledge_id=knowledge_id,
            knowledge_name=knowledge_name,
            data_start_time=data_start_time,
            data_end_time=data_end_time,
            group_count=group_count,
            success_count=success_count,
            failed_count=max(group_count - success_count, 1),
            error_code=error_code,
            error_message=error_message,
        )
        try:
            await AuditLogDao.ainsert_v2(
                tenant_id=int(login_user.tenant_id),
                operator_id=int(login_user.user_id),
                operator_tenant_id=int(login_user.tenant_id),
                operator_name=str(login_user.user_name or ""),
                action=ACTION_INSPECTION_BATCH_FAILED,
                target_type="knowledge_space",
                target_id=str(knowledge_id),
                object_name=knowledge_name or f"knowledge-{knowledge_id}",
                note=note,
                metadata=metadata,
                ip_address=get_request_ip(request) if request is not None else None,
            )
        except Exception:
            logger.exception(
                "filelib inspection batch failed audit write failed knowledge_id={}",
                knowledge_id,
            )
