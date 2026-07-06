from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException

from bisheng.approval.domain.models.approval_instance import (
    ApprovalException,
    ApprovalExceptionType,
    ApprovalInstance,
    ApprovalInstanceStatus,
)
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.schemas.approval_center_schema import (
    ApprovalGateDecision,
    ApprovalGateRequest,
    ApprovalGateResult,
)
from bisheng.approval.domain.schemas.shougang_approval_schema import (
    ShougangFilePublishDocumentEntry,
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
    FILE_PUBLISH_DOMAIN_MISMATCH_MESSAGE,
    FILE_PUBLISH_SCENARIO,
    KNOWLEDGE_SPACE_CREATE_SCENARIO,
    KnowledgeSpaceCreateApprovalHandler,
    KnowledgeSpaceFilePublishApprovalHandler,
    ensure_file_publish_business_domain_matches,
)
from bisheng.common.errcode.approval import ApprovalScenarioDisabledError
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.database.models.department import UserDepartmentDao
from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum, KnowledgeDao, KnowledgeTypeEnum
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
    _FILE_PUBLISH_TARGET_LEVELS: dict[KnowledgeSpaceLevelEnum, set[KnowledgeSpaceLevelEnum]] = {
        KnowledgeSpaceLevelEnum.PERSONAL: {
            KnowledgeSpaceLevelEnum.PUBLIC,
            KnowledgeSpaceLevelEnum.DEPARTMENT,
            KnowledgeSpaceLevelEnum.TEAM,
        },
        KnowledgeSpaceLevelEnum.TEAM: {
            KnowledgeSpaceLevelEnum.PUBLIC,
            KnowledgeSpaceLevelEnum.DEPARTMENT,
        },
        KnowledgeSpaceLevelEnum.DEPARTMENT: {
            KnowledgeSpaceLevelEnum.PUBLIC,
        },
    }

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

    @staticmethod
    def _normalize_space_level(level) -> KnowledgeSpaceLevelEnum:
        if isinstance(level, KnowledgeSpaceLevelEnum):
            return level
        return KnowledgeSpaceLevelEnum(str(level))

    @classmethod
    def _allowed_file_publish_target_levels(cls, source_level) -> set[KnowledgeSpaceLevelEnum]:
        return cls._FILE_PUBLISH_TARGET_LEVELS.get(cls._normalize_space_level(source_level), set())

    @classmethod
    def _is_file_publish_pair_allowed(cls, source_level, target_level) -> bool:
        return cls._normalize_space_level(target_level) in cls._allowed_file_publish_target_levels(source_level)

    async def _get_primary_department_id(self, login_user) -> Optional[int]:
        primary = await UserDepartmentDao.aget_user_primary_department(login_user.user_id)
        return primary.department_id if primary else None

    async def _is_create_approval_exempt(self, login_user) -> bool:
        if login_user.is_admin():
            return True
        if await TenantService._is_tenant_admin(login_user.user_id, login_user.tenant_id):
            return True
        return False

    @staticmethod
    def _enum_value(value) -> Any:
        return value.value if hasattr(value, 'value') else value

    @classmethod
    def _is_private_personal_space_create(cls, params: dict) -> bool:
        return (
            cls._enum_value(params.get('space_level')) == KnowledgeSpaceLevelEnum.PERSONAL.value
            and cls._enum_value(params.get('auth_type')) == AuthTypeEnum.PRIVATE.value
            and not bool(params.get('is_released'))
        )

    @classmethod
    def _is_personal_space_create(cls, params: dict) -> bool:
        return cls._enum_value(params.get('space_level')) == KnowledgeSpaceLevelEnum.PERSONAL.value

    @classmethod
    def _is_public_level_space_create(cls, params: dict) -> bool:
        return cls._enum_value(params.get('space_level')) == KnowledgeSpaceLevelEnum.PUBLIC.value

    @classmethod
    def _is_department_level_space_create(cls, params: dict) -> bool:
        return cls._enum_value(params.get('space_level')) == KnowledgeSpaceLevelEnum.DEPARTMENT.value

    @classmethod
    def _is_admin_only_level_space_create(cls, params: dict) -> bool:
        return cls._is_public_level_space_create(params) or cls._is_department_level_space_create(params)

    @classmethod
    def _space_visibility_for_payload(cls, params: dict) -> str:
        if bool(params.get('is_released')):
            return 'released'
        return str(cls._enum_value(params.get('auth_type')) or AuthTypeEnum.PRIVATE.value)

    async def _requires_create_approval(self, *, login_user, params: dict) -> bool:
        if self._is_admin_only_level_space_create(params):
            return False
        if self._is_private_personal_space_create(params):
            return False
        if self._is_personal_space_create(params):
            return not await self._is_create_approval_exempt(login_user)
        return True

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
    def _space_create_params(
        req: ShougangKnowledgeSpaceCreateSubmitReq | ShougangKnowledgeSpaceCreateValidateReq,
    ) -> dict:
        return req.model_dump(exclude={'reason'}, mode='json')

    @staticmethod
    def _gate_result_to_dict(result) -> dict:
        if hasattr(result, 'model_dump'):
            try:
                return result.model_dump(mode='json')
            except TypeError:
                return result.model_dump()
        return dict(result)

    async def _request_or_create_config_exception(
        self,
        *,
        req: ApprovalGateRequest,
        scenario_name: str,
        handler: Any,
    ) -> ApprovalGateResult:
        try:
            return await self.approval_gate.request_or_pass(req)
        except ApprovalScenarioDisabledError:
            detail_snapshot = await handler.build_detail(req)
            business_name = await handler.build_title(req)
            instance = await ApprovalInstanceRepository.create_instance(
                ApprovalInstance(
                    tenant_id=req.tenant_id,
                    scenario_code=req.scenario_code,
                    scenario_name=scenario_name,
                    handler_key=req.scenario_code,
                    business_key=req.business_key,
                    business_resource_type=req.business_resource_type,
                    business_resource_id=req.business_resource_id,
                    business_name=business_name,
                    applicant_user_id=req.applicant_user_id,
                    applicant_user_name=req.applicant_user_name,
                    applicant_department_id=req.applicant_department_id,
                    status=ApprovalInstanceStatus.EXCEPTION,
                    reason=req.reason,
                    payload_snapshot=req.payload_snapshot,
                    detail_snapshot=detail_snapshot,
                )
            )
            await ApprovalInstanceRepository.create_exception(
                ApprovalException(
                    tenant_id=req.tenant_id,
                    instance_id=int(instance.id),
                    exception_type=ApprovalExceptionType.ROUTE_MISSING,
                    detail={
                        'scenario_code': req.scenario_code,
                        'business_key': req.business_key,
                        'current_node_name': None,
                    },
                )
            )
            await ApprovalGate._notify_admins_of_exception(
                tenant_id=req.tenant_id,
                applicant_user_id=req.applicant_user_id,
                exception_type=ApprovalExceptionType.ROUTE_MISSING,
                business_name=business_name,
                instance_id=int(instance.id),
            )
            return ApprovalGateResult(
                decision=ApprovalGateDecision.EXCEPTION,
                instance_id=int(instance.id),
                exception_type=ApprovalExceptionType.ROUTE_MISSING,
            )

    async def validate_knowledge_space_create(
        self,
        *,
        req: ShougangKnowledgeSpaceCreateValidateReq,
        login_user,
        space_service,
    ) -> ShougangKnowledgeSpaceCreateValidateResp:
        params = self._space_create_params(req)
        approval_required = await self._requires_create_approval(login_user=login_user, params=params)
        await space_service.validate_knowledge_space_create(
            **params,
            approval_request=approval_required,
        )
        return ShougangKnowledgeSpaceCreateValidateResp(
            approval_required=approval_required
        )

    async def submit_knowledge_space_create(
        self,
        *,
        req: ShougangKnowledgeSpaceCreateSubmitReq,
        login_user,
        space_service,
    ) -> dict:
        params = self._space_create_params(req)
        approval_required = await self._requires_create_approval(login_user=login_user, params=params)
        await space_service.validate_knowledge_space_create(
            **params,
            approval_request=approval_required,
        )

        if not approval_required:
            created = await space_service.create_knowledge_space(**params)
            build_info = getattr(space_service, 'build_created_space_info', None)
            if build_info:
                space_info = build_info(created)
            else:
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
        approval_req = ApprovalGateRequest(
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
                'space_level': params.get('space_level'),
                'space_visibility': self._space_visibility_for_payload(params),
                'auth_type': params.get('auth_type'),
                'is_released': params.get('is_released'),
                'department_id': params.get('department_id'),
                'user_group_id': params.get('user_group_id'),
                'create_params': params,
            },
        )
        result = await self._request_or_create_config_exception(
            req=approval_req,
            scenario_name='知识空间创建审批',
            handler=KnowledgeSpaceCreateApprovalHandler(),
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
        if not self._allowed_file_publish_target_levels(source_level):
            raise HTTPException(status_code=400, detail='当前知识空间类型不支持发布文件')
        if source_file.file_type == FileType.DIR.value:
            raise HTTPException(status_code=400, detail='文件夹不支持发布审批')
        if source_file.status != KnowledgeFileStatus.SUCCESS.value:
            raise HTTPException(status_code=400, detail='仅解析成功文件可发布')
        if space_service is not None:
            await space_service._require_permission_id(
                'knowledge_space',
                int(source_file.knowledge_id),
                'publish_file',
            )

    async def _ensure_publish_target_space(self, target_space_id: int, *, source_level, space_service=None):
        target_space = await KnowledgeDao.aquery_by_id(target_space_id)
        if not target_space or target_space.type != KnowledgeTypeEnum.SPACE.value:
            raise HTTPException(status_code=404, detail='目标知识空间不存在')
        scope = await KnowledgeSpaceScopeDao.aget_by_space_id(target_space_id)
        target_level = scope.level if scope else KnowledgeSpaceLevelEnum.PERSONAL
        if not self._is_file_publish_pair_allowed(source_level, target_level):
            raise HTTPException(status_code=400, detail='目标知识空间类型不允许发布')
        if space_service is not None:
            await space_service._require_permission_id('knowledge_space', target_space_id, 'view_space')
        return target_space

    async def _ensure_publish_target_folder(
        self,
        target_space_id: int,
        target_folder_id: int | None,
        *,
        space_service=None,
    ):
        if target_folder_id is None:
            return None
        target_folder = await KnowledgeFileDao.query_by_id(target_folder_id)
        if (
            not target_folder
            or int(target_folder.knowledge_id) != int(target_space_id)
            or int(target_folder.file_type) != FileType.DIR.value
        ):
            raise HTTPException(status_code=404, detail='目标目录不存在')
        if space_service is not None:
            await space_service._require_permission_id(
                'folder',
                int(target_folder_id),
                'view_folder',
                space_id=int(target_space_id),
            )
        return target_folder

    @staticmethod
    def _target_folder_payload(target_folder) -> dict[str, Any]:
        if not target_folder:
            return {
                'target_folder_id': None,
                'target_folder_name': '根目录',
                'target_folder_level': 0,
                'target_folder_level_path': '',
            }
        folder_id = int(target_folder.id)
        folder_level_path = (target_folder.file_level_path or '').rstrip('/')
        return {
            'target_folder_id': folder_id,
            'target_folder_name': target_folder.file_name,
            'target_folder_level': int(target_folder.level or 0) + 1,
            'target_folder_level_path': f"{folder_level_path}/{folder_id}" if folder_level_path else f"/{folder_id}",
        }

    async def _space_level_for_payload(self, space) -> str:
        level = getattr(space, 'space_level', None)
        if level is None:
            scope = await KnowledgeSpaceScopeDao.aget_by_space_id(int(space.id))
            level = scope.level if scope else KnowledgeSpaceLevelEnum.PERSONAL
        return self._enum_value(level)

    async def list_file_publish_target_spaces(
        self,
        *,
        source_space_id: int,
        space_service,
    ) -> ShougangFilePublishTargetSpacesResp:
        source_space = await KnowledgeDao.aquery_by_id(source_space_id)
        if not source_space or source_space.type != KnowledgeTypeEnum.SPACE.value:
            raise HTTPException(status_code=404, detail='源知识空间不存在')
        scope = await KnowledgeSpaceScopeDao.aget_by_space_id(source_space_id)
        source_level = scope.level if scope else KnowledgeSpaceLevelEnum.PERSONAL
        allowed_levels = self._allowed_file_publish_target_levels(source_level)
        if not allowed_levels:
            raise HTTPException(status_code=400, detail='当前知识空间类型不支持发布文件')
        grouped = await space_service.get_grouped_spaces()
        space_groups = [
            (KnowledgeSpaceLevelEnum.PUBLIC, list(grouped.public_spaces or [])),
            (KnowledgeSpaceLevelEnum.DEPARTMENT, list(grouped.department_spaces or [])),
            (KnowledgeSpaceLevelEnum.TEAM, list(grouped.team_spaces or [])),
        ]
        spaces = [
            space
            for level, group_spaces in space_groups
            if level in allowed_levels
            for space in group_spaces
        ]
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
        await self._ensure_publish_target_space(
            target_space_id,
            source_level=source_level,
            space_service=space_service,
        )

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
        can_view_file = self._build_file_publish_candidate_permission_checker(
            space_service=space_service,
            target_space_id=target_space_id,
        )
        if hasattr(version_service, 'get_shougang_publish_similar_candidates_for_file_in_space'):
            data = await version_service.get_shougang_publish_similar_candidates_for_file_in_space(
                source_file_id,
                target_space_id,
                can_view_file=can_view_file,
            )
        elif hasattr(version_service, 'get_similar_candidates_for_file_in_space'):
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
        can_view_file = self._build_file_publish_candidate_permission_checker(
            space_service=space_service,
            target_space_id=target_space_id,
        )
        if hasattr(version_service, 'search_shougang_publish_version_sources'):
            data = await version_service.search_shougang_publish_version_sources(
                target_space_id,
                keyword,
                source_file_id,
                can_view_file=can_view_file,
            )
        else:
            data = await version_service.search_version_sources(target_space_id, keyword, source_file_id)
        normalized = [
            item if isinstance(item, ShougangFilePublishDocumentEntry)
            else ShougangFilePublishDocumentEntry.model_validate(
                item.model_dump() if hasattr(item, 'model_dump') else item
            )
            for item in data
        ]
        return ShougangFilePublishDocumentSearchResp(data=normalized, total=len(normalized))

    def _build_file_publish_candidate_permission_checker(self, *, space_service, target_space_id: int):
        async def can_view_file(file_id: int) -> bool:
            if space_service is None:
                return True
            try:
                await space_service._require_permission_id(
                    'knowledge_file',
                    int(file_id),
                    'view_file',
                    space_id=int(target_space_id),
                )
                return True
            except SpacePermissionDeniedError:
                return False

        return can_view_file

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
        target_space = await self._ensure_publish_target_space(
            req.target_space_id,
            source_level=source_level,
            space_service=space_service,
        )
        try:
            ensure_file_publish_business_domain_matches(source_file, target_space)
        except ValueError as exc:
            if str(exc) == FILE_PUBLISH_DOMAIN_MISMATCH_MESSAGE:
                raise HTTPException(status_code=400, detail=FILE_PUBLISH_DOMAIN_MISMATCH_MESSAGE) from exc
            raise
        target_level = await self._space_level_for_payload(target_space)
        target_folder = await self._ensure_publish_target_folder(
            req.target_space_id,
            req.target_folder_id,
            space_service=space_service,
        )
        target_folder_payload = self._target_folder_payload(target_folder)

        target_document_title = None
        if req.target_document_id and req.target_file_id:
            raise HTTPException(status_code=400, detail='目标文档和目标文件不能同时选择')
        if req.target_document_id or req.target_file_id:
            if version_service is None:
                raise HTTPException(status_code=400, detail='目标文档校验服务不可用')
            if hasattr(version_service, '_require_version_management_enabled'):
                await version_service._require_version_management_enabled()
            can_view_file = self._build_file_publish_candidate_permission_checker(
                space_service=space_service,
                target_space_id=req.target_space_id,
            )
            if hasattr(version_service, 'search_shougang_publish_version_sources'):
                documents = await version_service.search_shougang_publish_version_sources(
                    req.target_space_id,
                    '',
                    req.source_file_id,
                    can_view_file=can_view_file,
                )
            else:
                documents = await version_service.search_version_sources(
                    req.target_space_id,
                    '',
                    req.source_file_id,
                )
            if req.target_document_id:
                matched_document = next(
                    (
                        document
                        for document in documents
                        if getattr(document, 'document_id', None) == req.target_document_id
                    ),
                    None,
                )
            else:
                matched_document = next(
                    (
                        document
                        for document in documents
                        if getattr(document, 'target_file_id', None) == req.target_file_id
                    ),
                    None,
                )
            if matched_document is None:
                raise HTTPException(status_code=400, detail='目标文档不可用于发布')
            target_document_title = matched_document.title

        applicant_department_id = await self._get_primary_department_id(login_user)
        file_name = getattr(source_file, 'file_name', None) or getattr(source_file, 'name', None) or str(source_file.id)
        approval_req = ApprovalGateRequest(
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
                'source_space_level': self._enum_value(source_level),
                'source_file_id': int(source_file.id),
                'source_file_name': file_name,
                'target_space_id': int(target_space.id),
                'target_space_name': target_space.name,
                'target_space_level': target_level,
                **target_folder_payload,
                'target_document_id': req.target_document_id,
                'target_file_id': req.target_file_id,
                'target_document_title': target_document_title,
            },
            duplicate_active_statuses=[
                ApprovalInstanceStatus.PENDING,
                ApprovalInstanceStatus.EXECUTE_FAILED,
            ],
        )
        result = await self._request_or_create_config_exception(
            req=approval_req,
            scenario_name='知识空间文件发布审批',
            handler=KnowledgeSpaceFilePublishApprovalHandler(),
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
