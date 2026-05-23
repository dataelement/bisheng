from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException

from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.schemas.approval_center_schema import (
    ApprovalGateDecision,
    ApprovalGateRequest,
)
from bisheng.approval.domain.schemas.shougang_approval_schema import (
    ShougangFilePublishDocumentSearchResp,
    ShougangFilePublishSimilarCandidatesResp,
    ShougangFilePublishSubmitReq,
    ShougangFilePublishTargetSpace,
    ShougangFilePublishTargetSpacesResp,
    ShougangKnowledgeSpaceCreateSubmitReq,
    ShougangKnowledgeSpaceCreateValidateReq,
    ShougangKnowledgeSpaceCreateValidateResp,
)
from bisheng.approval.domain.services.approval_gate import ApprovalGate
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.approval.domain.services.shougang_approval_handler import (
    FILE_PUBLISH_SCENARIO,
    KNOWLEDGE_SPACE_CREATE_SCENARIO,
    KnowledgeSpaceCreateApprovalHandler,
    KnowledgeSpaceFilePublishApprovalHandler,
)
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFileDao,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceScopeDao,
)
from bisheng.tenant.domain.services.tenant_service import TenantService


class ShougangApprovalService:
    def __init__(
        self,
        *,
        approval_gate: ApprovalGate | Any | None = None,
        message_service: Any | None = None,
    ) -> None:
        self.approval_gate = approval_gate or self._build_gate()
        self.message_service = message_service

    @staticmethod
    def _build_gate() -> ApprovalGate:
        registry = ApprovalRegistry.with_default_presets()
        registry.register_handler(KNOWLEDGE_SPACE_CREATE_SCENARIO, KnowledgeSpaceCreateApprovalHandler())
        registry.register_handler(FILE_PUBLISH_SCENARIO, KnowledgeSpaceFilePublishApprovalHandler())
        return ApprovalGate(registry=registry)

    async def _get_primary_department_id(self, login_user) -> Optional[int]:
        primary = await UserDepartmentDao.aget_user_primary_department(login_user.user_id)
        return primary.department_id if primary else None

    async def _is_create_approval_exempt(self, login_user) -> bool:
        if login_user.is_admin():
            return True
        if await TenantService._is_tenant_admin(login_user.user_id, login_user.tenant_id):
            return True
        return bool(await DepartmentDao.aget_user_admin_departments(login_user.user_id))

    async def _task_approver_user_ids(self, task_ids: list[int]) -> list[int]:
        approver_user_ids: list[int] = []
        seen: set[int] = set()
        for task_id in task_ids:
            task = await ApprovalInstanceRepository.get_task(task_id)
            if task and task.approver_user_id not in seen:
                seen.add(task.approver_user_id)
                approver_user_ids.append(task.approver_user_id)
        return approver_user_ids

    async def _send_approval_message(
        self,
        *,
        login_user,
        result,
        business_name: str,
        action_code: str,
    ) -> None:
        if result.decision != ApprovalGateDecision.PENDING or not getattr(result, 'task_ids', None):
            return
        approver_user_ids = await self._task_approver_user_ids(result.task_ids)
        if not approver_user_ids:
            return
        message_service = self.message_service
        if message_service is None:
            from bisheng.core.database import get_async_db_session
            from bisheng.message.api.dependencies import get_message_service as _get_message_service

            async with get_async_db_session() as session:
                message_service = await _get_message_service(session)
                await message_service.send_generic_approval(
                    applicant_user_id=login_user.user_id,
                    applicant_user_name=login_user.user_name,
                    action_code=action_code,
                    business_type='approval_instance_id',
                    business_id=str(result.instance_id),
                    business_name=business_name,
                    button_action_code=action_code,
                    receiver_user_ids=approver_user_ids,
                )
            return
        await message_service.send_generic_approval(
            applicant_user_id=login_user.user_id,
            applicant_user_name=login_user.user_name,
            action_code=action_code,
            business_type='approval_instance_id',
            business_id=str(result.instance_id),
            business_name=business_name,
            button_action_code=action_code,
            receiver_user_ids=approver_user_ids,
        )

    @staticmethod
    def _space_create_params(req: ShougangKnowledgeSpaceCreateSubmitReq | ShougangKnowledgeSpaceCreateValidateReq) -> dict:
        return req.model_dump(exclude={'reason'}, mode='json')

    @staticmethod
    def _gate_result_to_dict(result) -> dict:
        if hasattr(result, 'model_dump'):
            try:
                return result.model_dump(mode='json')
            except TypeError:
                return result.model_dump()
        return dict(result)

    async def validate_knowledge_space_create(
        self,
        *,
        req: ShougangKnowledgeSpaceCreateValidateReq,
        login_user,
        space_service,
    ) -> ShougangKnowledgeSpaceCreateValidateResp:
        params = self._space_create_params(req)
        await space_service.validate_knowledge_space_create(**params)
        return ShougangKnowledgeSpaceCreateValidateResp(
            approval_required=not await self._is_create_approval_exempt(login_user)
        )

    async def submit_knowledge_space_create(
        self,
        *,
        req: ShougangKnowledgeSpaceCreateSubmitReq,
        login_user,
        space_service,
    ) -> dict:
        params = self._space_create_params(req)
        await space_service.validate_knowledge_space_create(**params)

        if await self._is_create_approval_exempt(login_user):
            created = await space_service.create_knowledge_space(**params)
            get_info = getattr(space_service, 'get_space_info', None)
            space_info = await get_info(created.id) if get_info else created
            if hasattr(space_info, 'model_dump'):
                space_info = space_info.model_dump(mode='json')
            return {
                'decision': ApprovalGateDecision.PASS.value,
                'created': True,
                'space': space_info,
                'instance_id': None,
                'task_ids': [],
            }

        applicant_department_id = await self._get_primary_department_id(login_user)
        result = await self.approval_gate.request_or_pass(
            ApprovalGateRequest(
                tenant_id=login_user.tenant_id,
                scenario_code=KNOWLEDGE_SPACE_CREATE_SCENARIO,
                business_key=f"knowledge-space-create:user:{login_user.user_id}:level:{params.get('space_level')}:name:{params.get('name')}",
                business_resource_type='knowledge_space_create_request',
                business_resource_id=f"{params.get('space_level')}:{params.get('name')}",
                business_name=f"新建知识库：{params.get('name')}",
                applicant_user_id=login_user.user_id,
                applicant_user_name=login_user.user_name,
                applicant_department_id=applicant_department_id,
                reason=req.reason,
                payload_snapshot={
                    'tenant_id': login_user.tenant_id,
                    'applicant_user_id': login_user.user_id,
                    'applicant_user_name': login_user.user_name,
                    'applicant_department_id': applicant_department_id,
                    'create_params': params,
                },
            )
        )
        await self._send_approval_message(
            login_user=login_user,
            result=result,
            business_name=f"新建知识库：{params.get('name')}",
            action_code='request_knowledge_space_create',
        )
        data = self._gate_result_to_dict(result)
        data['created'] = False
        return data

    async def _load_publish_source(self, source_space_id: int, source_file_id: int):
        source_space = await KnowledgeDao.aquery_by_id(source_space_id)
        if not source_space or source_space.type != KnowledgeTypeEnum.SPACE.value:
            raise HTTPException(status_code=404, detail='源知识空间不存在')
        source_file = await KnowledgeFileDao.query_by_id(source_file_id)
        if not source_file or source_file.knowledge_id != source_space_id:
            raise HTTPException(status_code=404, detail='源文件不存在')
        scope = await KnowledgeSpaceScopeDao.aget_by_space_id(source_space_id)
        source_level = scope.level if scope else KnowledgeSpaceLevelEnum.PERSONAL
        return source_space, source_file, source_level

    async def _ensure_can_publish_file(self, *, source_file, source_level, space_service) -> None:
        if source_level not in {KnowledgeSpaceLevelEnum.TEAM, KnowledgeSpaceLevelEnum.PERSONAL}:
            raise HTTPException(status_code=400, detail='仅团队/个人知识库文件可提交发布审批')
        if source_file.file_type == FileType.DIR.value:
            raise HTTPException(status_code=400, detail='文件夹不支持发布审批')
        if source_file.status != KnowledgeFileStatus.SUCCESS.value:
            raise HTTPException(status_code=400, detail='仅解析成功文件可发布')
        if space_service is not None:
            await space_service._require_permission_id(
                'knowledge_file',
                int(source_file.id),
                'upload_file',
                space_id=int(source_file.knowledge_id),
            )

    async def _ensure_publish_target_space(self, target_space_id: int, space_service=None):
        target_space = await KnowledgeDao.aquery_by_id(target_space_id)
        if not target_space or target_space.type != KnowledgeTypeEnum.SPACE.value:
            raise HTTPException(status_code=404, detail='目标知识空间不存在')
        scope = await KnowledgeSpaceScopeDao.aget_by_space_id(target_space_id)
        target_level = scope.level if scope else KnowledgeSpaceLevelEnum.PERSONAL
        if target_level not in {KnowledgeSpaceLevelEnum.PUBLIC, KnowledgeSpaceLevelEnum.DEPARTMENT}:
            raise HTTPException(status_code=400, detail='目标知识空间必须是公共或业务域知识库')
        if space_service is not None:
            await space_service._require_permission_id('knowledge_space', target_space_id, 'upload_file')
        return target_space

    async def list_file_publish_target_spaces(self, *, space_service) -> ShougangFilePublishTargetSpacesResp:
        grouped = await space_service.get_grouped_spaces()
        spaces = list(grouped.public_spaces or []) + list(grouped.department_spaces or [])
        items = [
            ShougangFilePublishTargetSpace(
                id=int(space.id),
                name=space.name,
                space_level=space.space_level,
                owner_name=space.owner_name,
            )
            for space in spaces
        ]
        return ShougangFilePublishTargetSpacesResp(data=items, total=len(items))

    async def _ensure_file_publish_query_allowed(
        self,
        *,
        source_file_id: int,
        target_space_id: int,
        space_service,
    ) -> None:
        source_file = await KnowledgeFileDao.query_by_id(source_file_id)
        if not source_file:
            raise HTTPException(status_code=404, detail='源文件不存在')
        _, source_file, source_level = await self._load_publish_source(
            int(source_file.knowledge_id),
            source_file_id,
        )
        await self._ensure_can_publish_file(
            source_file=source_file,
            source_level=source_level,
            space_service=space_service,
        )
        await self._ensure_publish_target_space(target_space_id, space_service=space_service)

    async def list_file_publish_similar_candidates(
        self,
        *,
        source_file_id: int,
        target_space_id: int,
        version_service,
        space_service=None,
    ) -> ShougangFilePublishSimilarCandidatesResp:
        await self._ensure_file_publish_query_allowed(
            source_file_id=source_file_id,
            target_space_id=target_space_id,
            space_service=space_service,
        )
        if hasattr(version_service, 'get_similar_candidates_for_file_in_space'):
            data = await version_service.get_similar_candidates_for_file_in_space(
                source_file_id,
                target_space_id,
            )
        else:
            data = []
        return ShougangFilePublishSimilarCandidatesResp(data=data, total=len(data))

    async def search_file_publish_documents(
        self,
        *,
        source_file_id: int,
        target_space_id: int,
        keyword: str,
        version_service,
        space_service=None,
    ) -> ShougangFilePublishDocumentSearchResp:
        await self._ensure_file_publish_query_allowed(
            source_file_id=source_file_id,
            target_space_id=target_space_id,
            space_service=space_service,
        )
        data = await version_service.search_version_sources(target_space_id, keyword, source_file_id)
        return ShougangFilePublishDocumentSearchResp(data=data, total=len(data))

    async def submit_file_publish(
        self,
        *,
        req: ShougangFilePublishSubmitReq,
        login_user,
        space_service=None,
        version_service=None,
    ) -> dict:
        source_space, source_file, source_level = await self._load_publish_source(
            req.source_space_id,
            req.source_file_id,
        )
        await self._ensure_can_publish_file(
            source_file=source_file,
            source_level=source_level,
            space_service=space_service,
        )
        target_space = await self._ensure_publish_target_space(req.target_space_id, space_service=space_service)

        target_document_title = None
        if req.target_document_id:
            if version_service is None:
                raise HTTPException(status_code=400, detail='目标文档校验服务不可用')
            documents = await version_service.search_version_sources(
                req.target_space_id,
                '',
                req.source_file_id,
            )
            matched_document = next(
                (document for document in documents if document.document_id == req.target_document_id),
                None,
            )
            if matched_document is None:
                raise HTTPException(status_code=400, detail='目标文档不可用于发布')
            target_document_title = matched_document.title

        applicant_department_id = await self._get_primary_department_id(login_user)
        file_name = getattr(source_file, 'file_name', None) or getattr(source_file, 'name', None) or str(source_file.id)
        result = await self.approval_gate.request_or_pass(
            ApprovalGateRequest(
                tenant_id=login_user.tenant_id,
                scenario_code=FILE_PUBLISH_SCENARIO,
                business_key=f"knowledge-file-publish:file:{req.source_file_id}:target:{req.target_space_id}:user:{login_user.user_id}",
                business_resource_type='knowledge_space_file_publish_request',
                business_resource_id=f"{req.source_file_id}:{req.target_space_id}",
                business_name=f"发布文件：{file_name}",
                applicant_user_id=login_user.user_id,
                applicant_user_name=login_user.user_name,
                applicant_department_id=applicant_department_id,
                reason=req.reason,
                payload_snapshot={
                    'tenant_id': login_user.tenant_id,
                    'applicant_user_id': login_user.user_id,
                    'applicant_user_name': login_user.user_name,
                    'applicant_department_id': applicant_department_id,
                    'source_space_id': int(source_space.id),
                    'source_space_name': source_space.name,
                    'source_file_id': int(source_file.id),
                    'source_file_name': file_name,
                    'target_space_id': int(target_space.id),
                    'target_space_name': target_space.name,
                    'target_document_id': req.target_document_id,
                    'target_document_title': target_document_title,
                },
            )
        )
        await self._send_approval_message(
            login_user=login_user,
            result=result,
            business_name=f"发布文件：{file_name}",
            action_code='request_knowledge_space_file_publish',
        )
        data = self._gate_result_to_dict(result)
        data['created'] = False
        return data
