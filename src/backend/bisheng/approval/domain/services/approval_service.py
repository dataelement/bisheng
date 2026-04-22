from __future__ import annotations

import asyncio
import os
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from fastapi import Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.approval.domain.models.approval_request import (
    ApprovalRequest,
    ApprovalRequestDao,
    ApprovalRequestStatusEnum,
    ApprovalRequestTypeEnum,
    ApprovalReviewModeEnum,
    ApprovalSafetyStatusEnum,
)
from bisheng.approval.domain.schemas.approval_schema import (
    ApprovalDecisionActionEnum,
    ApprovalRequestResp,
    DepartmentKnowledgeSpaceApprovalSettings,
)
from bisheng.core.database import get_async_db_session
from bisheng.common.errcode.approval import (
    ApprovalRejectReasonRequiredError,
    ApprovalRequestAlreadyProcessedError,
    ApprovalRequestNotFoundError,
    ApprovalRequestPermissionDeniedError,
    ApprovalSettingsPermissionDeniedError,
)
from bisheng.common.models.config import ConfigDao
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpaceDao
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import FileSource, FileType
from bisheng.knowledge.domain.schemas.knowledge_space_schema import KnowledgeSpaceFileResponse
from bisheng.permission.domain.services.permission_service import PermissionService
from bisheng.message.domain.models.inbox_message import MessageStatusEnum
from bisheng.message.domain.repositories.implementations.inbox_message_repository_impl import (
    InboxMessageRepositoryImpl,
)


_SETTINGS_KEY = 'department_knowledge_space_approval'
_MESSAGE_ACTION_CODE = 'request_department_knowledge_space_upload'


class ApprovalService:
    @classmethod
    async def _sync_message_after_decision(
        cls,
        *,
        message_id: Optional[int],
        operator_user_id: int,
        action: ApprovalDecisionActionEnum,
    ) -> None:
        if not message_id:
            return
        async with get_async_db_session() as session:
            repo = InboxMessageRepositoryImpl(session)
            message = await repo.find_by_id(message_id)
            if not message:
                return
            updated_content = []
            for item in message.content or []:
                new_item = dict(item)
                if item.get('type') == 'agree_reject_button':
                    new_item['content'] = 'agree' if action == ApprovalDecisionActionEnum.APPROVE else 'reject'
                updated_content.append(new_item)
            await repo.update_message_after_approval(
                message_id=message_id,
                status=(
                    MessageStatusEnum.APPROVED
                    if action == ApprovalDecisionActionEnum.APPROVE
                    else MessageStatusEnum.REJECTED
                ),
                content=updated_content,
                operator_user_id=operator_user_id,
            )

    @classmethod
    async def get_department_knowledge_space_settings(
        cls,
    ) -> DepartmentKnowledgeSpaceApprovalSettings:
        row = await ConfigDao.aget_config_by_key(_SETTINGS_KEY)
        if not row or not row.value:
            return DepartmentKnowledgeSpaceApprovalSettings()
        try:
            import json

            payload = json.loads(row.value)
            return DepartmentKnowledgeSpaceApprovalSettings(**payload)
        except Exception:
            return DepartmentKnowledgeSpaceApprovalSettings()

    @classmethod
    async def update_department_knowledge_space_settings(
        cls,
        *,
        login_user: UserPayload,
        settings: DepartmentKnowledgeSpaceApprovalSettings,
    ) -> DepartmentKnowledgeSpaceApprovalSettings:
        if not login_user.is_admin():
            raise ApprovalSettingsPermissionDeniedError()
        import json

        await ConfigDao.insert_or_update_config(
            _SETTINGS_KEY,
            json.dumps(settings.model_dump(), ensure_ascii=False),
        )
        return settings

    @classmethod
    async def should_require_department_space_approval(
        cls, space_id: int,
    ) -> bool:
        binding = await DepartmentKnowledgeSpaceDao.aget_by_space_id(space_id)
        if not binding:
            return False
        settings = await cls.get_department_knowledge_space_settings()
        return settings.approval_enabled

    @classmethod
    def _original_file_name_from_path(cls, file_path: str) -> str:
        from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService

        basename = os.path.basename(urlparse(file_path).path)
        return KnowledgeService.get_upload_file_original_name(basename)

    @classmethod
    async def _build_file_payload(
        cls,
        *,
        space_id: int,
        file_paths: Sequence[str],
    ) -> List[Dict]:
        out: List[Dict] = []
        for file_path in file_paths:
            out.append({
                'file_path': file_path,
                'file_name': cls._original_file_name_from_path(file_path),
                'space_id': space_id,
            })
        return out

    @classmethod
    async def _expand_department_subject(
        cls, department_id: int, include_children: bool,
    ) -> List[int]:
        dept_rows = await DepartmentDao.aget_by_ids([department_id])
        if not dept_rows:
            return []
        dept = dept_rows[0]
        dept_ids = [department_id]
        if include_children and dept.path:
            dept_ids = await DepartmentDao.aget_subtree_ids(dept.path)
        user_ids: set[int] = set()
        for one_id in dept_ids:
            ids = await UserDepartmentDao.aget_user_ids_by_department(one_id)
            user_ids.update(int(uid) for uid in ids)
        return sorted(user_ids)

    @classmethod
    async def _expand_reviewer_subject(
        cls,
        *,
        subject_type: str,
        subject_id: int,
        include_children: Optional[bool],
    ) -> List[int]:
        if subject_type == 'user':
            return [subject_id]
        if subject_type == 'department':
            return await cls._expand_department_subject(subject_id, bool(include_children))
        if subject_type == 'user_group':
            return await UserGroupDao.aget_plain_member_user_ids(subject_id)
        return []

    @classmethod
    async def _resolve_reviewer_user_ids(
        cls,
        *,
        request: Request,
        login_user: UserPayload,
        space_id: int,
        parent_folder_id: Optional[int],
    ) -> List[int]:
        from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
        from bisheng.common.models.space_channel_member import SpaceChannelMemberDao, UserRoleEnum

        svc = KnowledgeSpaceService(request=request, login_user=login_user)
        if parent_folder_id:
            lineage = await svc._build_resource_lineage('folder', parent_folder_id, space_id=space_id)
        else:
            lineage = [('knowledge_space', space_id)]

        reviewer_ids: set[int] = set()
        for resource_type, resource_id in lineage:
            permissions = await PermissionService.get_resource_permissions(resource_type, str(resource_id))
            owner_manager = [
                item for item in permissions if item.relation in ('owner', 'manager')
            ]
            if not owner_manager:
                continue
            for item in owner_manager:
                reviewer_ids.update(
                    await cls._expand_reviewer_subject(
                        subject_type=item.subject_type,
                        subject_id=item.subject_id,
                        include_children=item.include_children,
                    )
                )
            if reviewer_ids:
                break

        if reviewer_ids:
            return sorted(reviewer_ids)

        fallback_members = await SpaceChannelMemberDao.async_get_members_by_space(
            space_id,
            user_roles=[UserRoleEnum.CREATOR, UserRoleEnum.ADMIN],
        )
        reviewer_ids.update(member.user_id for member in fallback_members if member.is_active)
        return sorted(reviewer_ids)

    @classmethod
    async def get_department_space_reviewer_user_ids(
        cls,
        *,
        request: Request,
        login_user: UserPayload,
        space_id: int,
        parent_folder_id: Optional[int],
        exclude_user_ids: Optional[Iterable[int]] = None,
    ) -> List[int]:
        reviewer_ids = await cls._resolve_reviewer_user_ids(
            request=request,
            login_user=login_user,
            space_id=space_id,
            parent_folder_id=parent_folder_id,
        )
        excluded = {int(user_id) for user_id in (exclude_user_ids or [])}
        return [user_id for user_id in reviewer_ids if user_id not in excluded]

    @classmethod
    async def should_bypass_department_space_approval(
        cls,
        *,
        request: Request,
        login_user: UserPayload,
        space_id: int,
        parent_folder_id: Optional[int],
    ) -> bool:
        reviewer_user_ids = await cls.get_department_space_reviewer_user_ids(
            request=request,
            login_user=login_user,
            space_id=space_id,
            parent_folder_id=parent_folder_id,
        )
        return login_user.user_id in set(reviewer_user_ids)

    @classmethod
    def _build_system_login_user(
        cls,
        *,
        user_id: int,
        user_name: str,
        tenant_id: int,
    ) -> UserPayload:
        return UserPayload(
            user_id=user_id,
            user_name=user_name,
            tenant_id=tenant_id,
            user_role=[-999],
        )

    @classmethod
    async def _get_live_reviewer_user_ids_for_row(
        cls,
        *,
        row: ApprovalRequest,
    ) -> List[int]:
        return await cls.get_department_space_reviewer_user_ids(
            request=Request(scope={'type': 'http'}),
            login_user=cls._build_system_login_user(
                user_id=row.applicant_user_id,
                user_name=row.applicant_user_name,
                tenant_id=row.tenant_id,
            ),
            space_id=row.space_id,
            parent_folder_id=row.parent_folder_id,
            exclude_user_ids=[row.applicant_user_id],
        )

    @classmethod
    async def _can_user_access_request(
        cls,
        *,
        row: ApprovalRequest,
        login_user: UserPayload,
    ) -> bool:
        if login_user.is_admin() or row.applicant_user_id == login_user.user_id:
            return True
        live_reviewer_ids = await cls._get_live_reviewer_user_ids_for_row(row=row)
        return login_user.user_id in set(live_reviewer_ids)

    @classmethod
    async def _run_safety_check(
        cls,
        *,
        settings: DepartmentKnowledgeSpaceApprovalSettings,
        file_payloads: List[Dict],
    ) -> Tuple[str, Optional[str]]:
        if not settings.sensitive_check_enabled:
            return ApprovalSafetyStatusEnum.SKIPPED.value, None
        # Hook point for a future provider-backed content safety implementation.
        # The approval module keeps the API surface stable while the detection
        # provider can be swapped independently later.
        return ApprovalSafetyStatusEnum.PASSED.value, None

    @classmethod
    async def _send_approval_messages(
        cls,
        *,
        applicant_user_id: int,
        applicant_user_name: str,
        reviewer_user_ids: List[int],
        approval_request: ApprovalRequest,
        space_name: str,
    ) -> Optional[int]:
        if not reviewer_user_ids:
            return None
        from bisheng.core.database import get_async_db_session
        from bisheng.message.api.dependencies import get_message_service as _get_message_service

        business_name = f'{space_name}（{approval_request.file_count}个文件）'
        async with get_async_db_session() as session:
            message_service = await _get_message_service(session)
            msg = await message_service.send_generic_approval(
                applicant_user_id=applicant_user_id,
                applicant_user_name=applicant_user_name,
                action_code=_MESSAGE_ACTION_CODE,
                business_type='approval_request_id',
                business_id=str(approval_request.id),
                business_name=business_name,
                button_action_code=_MESSAGE_ACTION_CODE,
                receiver_user_ids=reviewer_user_ids,
            )
        return msg.id if msg else None

    @classmethod
    async def _send_result_notify(
        cls,
        *,
        sender: int,
        receiver_user_id: int,
        action_code: str,
        business_name: str,
        approval_request_id: int,
        reason: Optional[str] = None,
    ) -> None:
        from bisheng.core.database import get_async_db_session
        from bisheng.message.api.dependencies import get_message_service as _get_message_service

        async with get_async_db_session() as session:
            message_service = await _get_message_service(session)
            content = [
                {
                    'type': 'system_text',
                    'content': action_code,
                },
                {
                    'type': 'business_url',
                    'content': f'--{business_name}',
                    'metadata': {
                        'business_type': 'approval_request_id',
                        'data': {'approval_request_id': str(approval_request_id)},
                    },
                },
            ]
            if reason:
                content.append({
                    'type': 'tooltip_text',
                    'content': reason,
                })
            await message_service.send_generic_notify(
                sender=sender,
                receiver_user_ids=[receiver_user_id],
                content_item_list=content,
            )

    @classmethod
    async def create_department_space_upload_request(
        cls,
        *,
        request: Request,
        login_user: UserPayload,
        space_id: int,
        parent_folder_id: Optional[int],
        file_paths: Sequence[str],
    ) -> ApprovalRequest:
        binding = await DepartmentKnowledgeSpaceDao.aget_by_space_id(space_id)
        if not binding:
            raise ApprovalRequestPermissionDeniedError(msg='This space is not a department knowledge space')

        space = await KnowledgeDao.aquery_by_id(space_id)
        if not space or space.type != KnowledgeTypeEnum.SPACE.value:
            raise ApprovalRequestNotFoundError(msg='Target knowledge space does not exist')

        settings = await cls.get_department_knowledge_space_settings()
        file_payloads = await cls._build_file_payload(space_id=space_id, file_paths=file_paths)
        safety_status, safety_reason = await cls._run_safety_check(
            settings=settings,
            file_payloads=file_payloads,
        )

        request_row = ApprovalRequest(
            tenant_id=login_user.tenant_id,
            request_type=ApprovalRequestTypeEnum.DEPARTMENT_KNOWLEDGE_SPACE_FILE_UPLOAD.value,
            status=(
                ApprovalRequestStatusEnum.SENSITIVE_REJECTED.value
                if safety_status == ApprovalSafetyStatusEnum.REJECTED.value
                else ApprovalRequestStatusEnum.PENDING_REVIEW.value
            ),
            review_mode=ApprovalReviewModeEnum.FIRST_RESPONSE_WINS.value,
            space_id=space_id,
            department_id=binding.department_id,
            parent_folder_id=parent_folder_id,
            applicant_user_id=login_user.user_id,
            applicant_user_name=login_user.user_name,
            file_count=len(file_payloads),
            payload_json={
                'files': file_payloads,
                'space_id': space_id,
                'parent_folder_id': parent_folder_id,
            },
            safety_status=safety_status,
            safety_reason=safety_reason,
        )
        request_row = await ApprovalRequestDao.acreate(request_row)

        if request_row.status == ApprovalRequestStatusEnum.SENSITIVE_REJECTED.value:
            await cls._send_result_notify(
                sender=login_user.user_id,
                receiver_user_id=login_user.user_id,
                action_code='sensitive_rejected_department_knowledge_space_upload',
                business_name=space.name,
                approval_request_id=request_row.id,
                reason=safety_reason,
            )
            return request_row

        reviewer_user_ids = await cls.get_department_space_reviewer_user_ids(
            request=request,
            login_user=login_user,
            space_id=space_id,
            parent_folder_id=parent_folder_id,
            exclude_user_ids=[login_user.user_id],
        )
        if not reviewer_user_ids:
            raise ApprovalRequestPermissionDeniedError(msg='No eligible reviewers available for this approval request')
        request_row.reviewer_user_ids = reviewer_user_ids
        request_row = await ApprovalRequestDao.aupdate(request_row)
        message_id = await cls._send_approval_messages(
            applicant_user_id=login_user.user_id,
            applicant_user_name=login_user.user_name,
            reviewer_user_ids=reviewer_user_ids,
            approval_request=request_row,
            space_name=space.name,
        )
        if message_id is not None:
            await ApprovalRequestDao.aupdate_message_id(request_row.id, message_id)
            request_row.message_id = message_id
        return request_row

    @classmethod
    def build_pending_file_responses(
        cls,
        *,
        approval_request: ApprovalRequest,
    ) -> List[KnowledgeSpaceFileResponse]:
        files = list((approval_request.payload_json or {}).get('files') or [])
        out: List[KnowledgeSpaceFileResponse] = []
        for idx, item in enumerate(files):
            out.append(KnowledgeSpaceFileResponse(
                id=-(approval_request.id * 1000 + idx + 1),
                knowledge_id=approval_request.space_id,
                file_name=item.get('file_name') or '',
                file_type=FileType.FILE.value,
                file_source=FileSource.SPACE_UPLOAD.value,
                level=0,
                file_level_path='',
                status=5,
                approval_request_id=approval_request.id,
                approval_status=approval_request.status,
                is_pending_approval=approval_request.status == ApprovalRequestStatusEnum.PENDING_REVIEW.value,
                approval_reason=approval_request.safety_reason or approval_request.decision_reason,
            ))
        return out

    @classmethod
    def _to_resp(cls, row: ApprovalRequest) -> ApprovalRequestResp:
        return ApprovalRequestResp(
            id=row.id,
            request_type=row.request_type,
            status=row.status,
            review_mode=row.review_mode,
            space_id=row.space_id,
            department_id=row.department_id,
            parent_folder_id=row.parent_folder_id,
            applicant_user_id=row.applicant_user_id,
            applicant_user_name=row.applicant_user_name,
            reviewer_user_ids=list(row.reviewer_user_ids or []),
            file_count=row.file_count,
            payload_json=row.payload_json or {},
            safety_status=row.safety_status,
            safety_reason=row.safety_reason,
            decision_reason=row.decision_reason,
            decided_by=row.decided_by,
            message_id=row.message_id,
            create_time=row.create_time.isoformat() if row.create_time else None,
            update_time=row.update_time.isoformat() if row.update_time else None,
        )

    @classmethod
    async def get_request_for_user(
        cls, *, request_id: int, login_user: UserPayload,
    ) -> ApprovalRequest:
        row = await ApprovalRequestDao.aget_by_id(request_id)
        if not row:
            raise ApprovalRequestNotFoundError()
        if not await cls._can_user_access_request(row=row, login_user=login_user):
            raise ApprovalRequestPermissionDeniedError()
        return row

    @classmethod
    async def list_requests_for_user(
        cls,
        *,
        login_user: UserPayload,
        space_id: Optional[int] = None,
        statuses: Optional[List[str]] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[ApprovalRequestResp], int]:
        if login_user.is_admin():
            rows, total = await ApprovalRequestDao.alist(
                space_id=space_id,
                applicant_user_id=None,
                reviewer_user_id=None,
                statuses=statuses,
                page=page,
                page_size=page_size,
            )
            return [cls._to_resp(row) for row in rows], total

        candidate_rows = await ApprovalRequestDao.alist_all(
            space_id=space_id,
            statuses=statuses,
        )
        visible_mask = await asyncio.gather(*[
            cls._can_user_access_request(row=row, login_user=login_user)
            for row in candidate_rows
        ])
        visible_rows = [row for row, visible in zip(candidate_rows, visible_mask) if visible]
        total = len(visible_rows)
        offset = (page - 1) * page_size
        rows = visible_rows[offset:offset + page_size]
        return [cls._to_resp(row) for row in rows], total

    @classmethod
    async def _finalize_request(
        cls,
        *,
        request_row: ApprovalRequest,
    ) -> None:
        from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

        payload = dict(request_row.payload_json or {})
        service = KnowledgeSpaceService(
            request=Request(scope={'type': 'http'}),
            login_user=cls._build_system_login_user(
                user_id=request_row.applicant_user_id,
                user_name=request_row.applicant_user_name,
                tenant_id=request_row.tenant_id,
            ),
        )
        files = await service.add_file(
            knowledge_id=request_row.space_id,
            file_path=[one.get('file_path') for one in payload.get('files', [])],
            parent_id=request_row.parent_folder_id,
            skip_approval=True,
        )
        payload['finalized_file_ids'] = [file.id for file in files]
        await ApprovalRequestDao.aset_final_status(
            request_id=request_row.id,
            status=ApprovalRequestStatusEnum.FINALIZED.value,
            payload_json=payload,
        )

    @classmethod
    async def decide_request(
        cls,
        *,
        request_id: int,
        operator_user_id: int,
        action: ApprovalDecisionActionEnum,
        reason: Optional[str],
    ) -> ApprovalRequest:
        row = await ApprovalRequestDao.aget_by_id(request_id)
        if not row:
            raise ApprovalRequestNotFoundError()
        if row.status != ApprovalRequestStatusEnum.PENDING_REVIEW.value:
            raise ApprovalRequestAlreadyProcessedError()
        if operator_user_id == row.applicant_user_id:
            raise ApprovalRequestPermissionDeniedError(msg='Applicant cannot approve their own request')
        current_reviewer_ids = set(await cls._get_live_reviewer_user_ids_for_row(row=row))
        if operator_user_id not in current_reviewer_ids:
            raise ApprovalRequestPermissionDeniedError()
        if action == ApprovalDecisionActionEnum.REJECT and not (reason or '').strip():
            raise ApprovalRejectReasonRequiredError()

        new_status = (
            ApprovalRequestStatusEnum.APPROVED.value
            if action == ApprovalDecisionActionEnum.APPROVE
            else ApprovalRequestStatusEnum.REJECTED.value
        )
        changed = await ApprovalRequestDao.atry_decide(
            request_id=request_id,
            expected_status=ApprovalRequestStatusEnum.PENDING_REVIEW.value,
            new_status=new_status,
            decided_by=operator_user_id,
            decision_reason=reason,
        )
        if not changed:
            raise ApprovalRequestAlreadyProcessedError()
        row = await ApprovalRequestDao.aget_by_id(request_id)
        if not row:
            raise ApprovalRequestNotFoundError()
        await cls._sync_message_after_decision(
            message_id=row.message_id,
            operator_user_id=operator_user_id,
            action=action,
        )

        space = await KnowledgeDao.aquery_by_id(row.space_id)
        business_name = space.name if space else f'space:{row.space_id}'
        if action == ApprovalDecisionActionEnum.APPROVE:
            try:
                await cls._finalize_request(request_row=row)
            except Exception as e:
                await ApprovalRequestDao.aset_final_status(
                    request_id=row.id,
                    status=ApprovalRequestStatusEnum.FINALIZE_FAILED.value,
                    safety_reason=str(e),
                )
                row = await ApprovalRequestDao.aget_by_id(request_id)
                return row
            await cls._send_result_notify(
                sender=operator_user_id,
                receiver_user_id=row.applicant_user_id,
                action_code='approved_department_knowledge_space_upload',
                business_name=business_name,
                approval_request_id=row.id,
            )
            row = await ApprovalRequestDao.aget_by_id(request_id)
            return row

        await cls._send_result_notify(
            sender=operator_user_id,
            receiver_user_id=row.applicant_user_id,
            action_code='rejected_department_knowledge_space_upload',
            business_name=business_name,
            approval_request_id=row.id,
            reason=reason,
        )
        return row
