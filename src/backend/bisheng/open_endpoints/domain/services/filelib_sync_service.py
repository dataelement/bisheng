from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

from fastapi import UploadFile
from loguru import logger
from pydantic import ValidationError

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.filelib_sync import (
    FilelibSyncConflictError,
    FilelibSyncInvalidParamsError,
    FilelibSyncNotFoundError,
    FilelibSyncPermissionDeniedError,
)
from bisheng.common.errcode.knowledge_space import (
    DepartmentKnowledgeSpaceAmbiguousError,
    SpacePermissionDeniedError,
)
from bisheng.core.cache.utils import save_uploaded_file
from bisheng.database.models.department import Department
from bisheng.knowledge.domain.constants import normalize_business_domain_code
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.services.department_space_target_resolver import (
    DepartmentSpaceTargetResolver,
)
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.knowledge.rag.pipeline.transformer.file_encoding import FileEncodingTransformer
from bisheng.open_endpoints.domain.repositories.interfaces.filelib_sync_repository import (
    FilelibSyncRepository,
)
from bisheng.open_endpoints.domain.schemas.filelib_sync import (
    BusinessDomainStrategy,
    FilelibSyncParams,
    FilelibSyncResponseData,
    FilelibSyncRule,
    TargetSpaceStrategy,
)
from bisheng.shougang_portal_config.domain.schemas.portal_config_schema import (
    PortalDocumentTypeChildConfig,
    PortalDocumentTypeConfig,
    PortalDomainConfig,
    ShougangPortalAdminConfig,
)
from bisheng.shougang_portal_config.domain.services.portal_config_service import (
    ShougangPortalConfigService,
)


@dataclass(frozen=True)
class ResolvedIdentity:
    responsible_user_id: int
    responsible_user_name: str
    responsible_department: Department
    main_department: Department


@dataclass(frozen=True)
class ResolvedClassification:
    category_code: str
    subcategory_code: str
    business_domain_code: str
    business_domain_name: str


class FilelibSyncService:
    def __init__(
        self,
        *,
        login_user: UserPayload,
        repository: FilelibSyncRepository,
        knowledge_space_service: KnowledgeSpaceService,
    ) -> None:
        self.login_user = login_user
        self.repository = repository
        self.knowledge_space_service = knowledge_space_service

    async def sync(
        self,
        *,
        rule: FilelibSyncRule,
        raw_params: str,
        upload_file: UploadFile,
    ) -> FilelibSyncResponseData:
        params = self.parse_params(raw_params)
        self._validate_upload(params, upload_file)
        identity = await self._resolve_identity(params)
        portal_config = await self._get_portal_config()
        category, subcategory = self._resolve_document_type(portal_config, rule)
        domain = self._resolve_business_domain(
            portal_config,
            rule,
            identity.responsible_department.id,
        )
        target_space = await self._resolve_target_space(rule, identity)
        self._ensure_domain_bound(target_space, domain)
        await self._require_upload_permission(target_space)

        created_file: KnowledgeFile | None = None
        temporary_file_path: str | None = None
        file_persisted = False
        try:
            temporary_file_path = await self._save_temporary_file(params, upload_file)
            preview_cache_key = self.knowledge_space_service.get_preview_cache_key(
                int(target_space.id),
                temporary_file_path,
            )
            upload_results = await self.knowledge_space_service.add_file(
                knowledge_id=int(target_space.id),
                file_path=[temporary_file_path],
                parent_id=None,
                file_category_code=category.code,
                file_subcategory_code=subcategory.code,
                business_domain_code=domain.code,
                skip_approval=True,
                enqueue_processing=False,
            )
            if len(upload_results) != 1 or upload_results[0].status == KnowledgeFileStatus.FAILED.value:
                raise FilelibSyncConflictError(msg="duplicate file content or name")

            file_id = int(upload_results[0].id)
            created_file = await self.repository.find_by_id(file_id)
            if created_file is None:
                raise FilelibSyncNotFoundError(msg="created knowledge file does not exist")
            created_file.user_metadata = {
                **(created_file.user_metadata or {}),
                "external_file_id": params.external_file_id,
                "department": identity.main_department.name,
                "department_id": int(identity.main_department.id),
                "responsible_person": identity.responsible_user_name,
                "responsible_person_id": identity.responsible_user_id,
                "filelib_sync_endpoint": rule.endpoint_code,
            }
            await FileEncodingTransformer.generate_fixed_encoding(
                invoke_user_id=int(self.login_user.user_id),
                knowledge_file=created_file,
                document_type_code=category.code,
                business_domain_code=domain.code,
            )
            created_file = await self.repository.update(created_file)
            file_persisted = True

            self.knowledge_space_service.enqueue_file_processing(
                [created_file],
                [preview_cache_key],
            )
            logger.info(
                "filelib sync queued endpoint={} external_file_id={} file_id={} knowledge_id={} user_id={}",
                rule.endpoint_code,
                params.external_file_id,
                created_file.id,
                target_space.id,
                self.login_user.user_id,
            )
            return FilelibSyncResponseData(
                external_file_id=params.external_file_id,
                file_id=int(created_file.id),
                file_encoding=str(created_file.file_encoding),
                knowledge_id=int(target_space.id),
                knowledge_name=target_space.name,
                status=int(created_file.status),
            )
        except Exception:
            if not file_persisted:
                await self._cleanup_failed_sync(created_file, temporary_file_path)
            raise

    @staticmethod
    def parse_params(raw_params: str) -> FilelibSyncParams:
        try:
            data = json.loads(raw_params)
        except (TypeError, json.JSONDecodeError) as exc:
            raise FilelibSyncInvalidParamsError(msg="params must be valid JSON") from exc
        if not isinstance(data, dict):
            raise FilelibSyncInvalidParamsError(msg="params must be a JSON object")
        if not str(data.get("external_file_id") or "").strip():
            raise FilelibSyncInvalidParamsError(msg="external_file_id must not be empty")
        if not str(data.get("file_name") or "").strip():
            raise FilelibSyncInvalidParamsError(msg="file_name must not be empty")
        try:
            return FilelibSyncParams.model_validate(data)
        except (TypeError, ValueError, ValidationError) as exc:
            raise FilelibSyncInvalidParamsError(msg="params fields are invalid") from exc

    @staticmethod
    def _validate_upload(params: FilelibSyncParams, upload_file: UploadFile) -> None:
        if "/" in params.file_name or "\\" in params.file_name:
            raise FilelibSyncInvalidParamsError(msg="file_name must be a base name")
        if upload_file.size == 0:
            raise FilelibSyncInvalidParamsError(msg="file must not be empty")

    async def _resolve_identity(self, params: FilelibSyncParams) -> ResolvedIdentity:
        caller_primary_link = await self.repository.find_primary_department(int(self.login_user.user_id))
        if caller_primary_link is None:
            raise FilelibSyncNotFoundError(msg="caller primary department does not exist")
        caller_department = await self.repository.find_department_by_id(int(caller_primary_link.department_id))
        if caller_department is None:
            raise FilelibSyncNotFoundError(msg="caller primary department does not exist")

        responsible_user_id = params.responsible_person_id or int(self.login_user.user_id)
        if responsible_user_id == int(self.login_user.user_id):
            responsible_user_name = self.login_user.user_name
        else:
            responsible_user = await self.repository.find_user_by_id(responsible_user_id)
            if responsible_user is None:
                raise FilelibSyncNotFoundError(msg="responsible person does not exist")
            responsible_user_name = responsible_user.user_name
        if params.responsible_person and params.responsible_person != responsible_user_name:
            raise FilelibSyncInvalidParamsError(msg="responsible_person does not match responsible_person_id")

        responsible_primary_link = await self.repository.find_primary_department(responsible_user_id)
        if responsible_primary_link is None:
            raise FilelibSyncNotFoundError(msg="responsible person primary department does not exist")
        responsible_department = await self.repository.find_department_by_id(
            int(responsible_primary_link.department_id)
        )
        if responsible_department is None:
            raise FilelibSyncNotFoundError(msg="responsible person primary department does not exist")

        if params.department_id is None:
            main_department = caller_department
        else:
            main_department = await self.repository.find_department_by_id(params.department_id)
            if main_department is None:
                raise FilelibSyncNotFoundError(msg="department does not exist")
        if params.department and params.department != main_department.name:
            raise FilelibSyncInvalidParamsError(msg="department does not match department_id")

        return ResolvedIdentity(
            responsible_user_id=responsible_user_id,
            responsible_user_name=responsible_user_name,
            responsible_department=responsible_department,
            main_department=main_department,
        )

    @staticmethod
    async def _get_portal_config() -> ShougangPortalAdminConfig:
        config = await ShougangPortalConfigService.get_config()
        if config is None:
            raise FilelibSyncNotFoundError(msg="首钢股份知识管理平台未配置文件分类和业务域")
        return config

    @classmethod
    def _resolve_document_type(
        cls,
        config: ShougangPortalAdminConfig,
        rule: FilelibSyncRule,
    ) -> tuple[PortalDocumentTypeConfig, PortalDocumentTypeChildConfig]:
        document_type = next(
            (
                item
                for item in config.portal.document_types
                if item.label.strip() == rule.category_name
                and cls._normalize_category_code(item.code, allow_hyphen=False)
            ),
            None,
        )
        if document_type is None:
            raise FilelibSyncNotFoundError(msg=f"首钢股份知识管理平台不存在分类{rule.category_name}")
        subcategory = next(
            (
                item
                for item in document_type.children
                if item.label.strip() == rule.subcategory_name
                and cls._normalize_category_code(item.code, allow_hyphen=True)
            ),
            None,
        )
        if subcategory is None:
            raise FilelibSyncNotFoundError(
                msg=f"首钢股份知识管理平台不存在分类{rule.category_name}/{rule.subcategory_name}"
            )
        return document_type, subcategory

    @staticmethod
    def _resolve_business_domain(
        config: ShougangPortalAdminConfig,
        rule: FilelibSyncRule,
        responsible_department_id: int,
    ) -> PortalDomainConfig:
        if rule.business_domain_strategy == BusinessDomainStrategy.RESPONSIBLE_DEPARTMENT:
            domain = next(
                (
                    item
                    for item in config.portal.domains
                    if item.enabled
                    and normalize_business_domain_code(item.code)
                    and responsible_department_id in item.department_ids
                ),
                None,
            )
            display_name = "责任人科室对应的业务域"
        else:
            domain = next(
                (
                    item
                    for item in config.portal.domains
                    if item.enabled
                    and normalize_business_domain_code(item.code)
                    and item.name.strip() == rule.fixed_business_domain_name
                ),
                None,
            )
            display_name = str(rule.fixed_business_domain_name)
        if domain is None:
            raise FilelibSyncNotFoundError(msg=f"首钢股份知识管理平台不存在业务域{display_name}")
        return domain

    @staticmethod
    def _normalize_category_code(value: Any, *, allow_hyphen: bool) -> str | None:
        if not isinstance(value, str):
            return None
        pattern = r"[A-Z0-9_-]{1,16}" if allow_hyphen else r"[A-Z0-9_]{1,16}"
        code = value.strip().upper()
        return code if re.fullmatch(pattern, code) else None

    async def _resolve_target_space(
        self,
        rule: FilelibSyncRule,
        identity: ResolvedIdentity,
    ) -> Knowledge:
        if rule.target_space_strategy == TargetSpaceStrategy.MAIN_DEPARTMENT:
            return await self._find_nearest_department_space(identity.main_department)
        if rule.target_space_strategy == TargetSpaceStrategy.RESPONSIBLE_DEPARTMENT:
            return await self._find_nearest_department_space(identity.responsible_department)
        if rule.target_space_strategy == TargetSpaceStrategy.FIXED_PUBLIC:
            space = await self.repository.find_public_space_by_name(str(rule.fixed_space_name))
            if space is None:
                raise FilelibSyncNotFoundError(msg=f"首钢股份知识管理平台不存在知识库{rule.fixed_space_name}")
            return space

        department = await self.repository.find_department_by_name(str(rule.fixed_department_name))
        if department is None:
            raise FilelibSyncNotFoundError(msg=f"首钢股份知识管理平台不存在部门{rule.fixed_department_name}")
        return await self._find_nearest_department_space(department)

    async def _find_nearest_department_space(self, department: Department) -> Knowledge:
        chain = self._department_chain(department)
        try:
            space_id = await DepartmentSpaceTargetResolver.resolve(chain)
        except DepartmentKnowledgeSpaceAmbiguousError as exc:
            raise FilelibSyncConflictError(
                msg="multiple target knowledge spaces are bound to the department",
            ) from exc
        if space_id is not None:
            space = await self.repository.find_knowledge_by_id(space_id)
            if space is not None:
                return space
        raise FilelibSyncNotFoundError(msg=f"首钢股份知识管理平台不存在知识库{department.name}")

    @staticmethod
    def _department_chain(department: Department) -> list[int]:
        path_ids = [int(part) for part in str(department.path or "").split("/") if part.strip().isdigit()]
        if int(department.id) not in path_ids:
            path_ids.append(int(department.id))
        return list(dict.fromkeys(reversed(path_ids)))

    @staticmethod
    def _ensure_domain_bound(space: Knowledge, domain: PortalDomainConfig) -> None:
        configured_space_ids = {int(space_id) for space_id in (domain.space_ids or []) if int(space_id) > 0}
        allowed_codes = {str(code).strip().upper() for code in (space.business_domain_codes or []) if str(code).strip()}
        if int(space.id) not in configured_space_ids or domain.code.strip().upper() not in allowed_codes:
            raise FilelibSyncNotFoundError(msg=f"首钢股份知识管理平台的{space.name}不存在{domain.name}")

    async def _require_upload_permission(self, space: Knowledge) -> None:
        try:
            await self.knowledge_space_service.require_root_upload_permission(int(space.id))
        except SpacePermissionDeniedError as exc:
            raise FilelibSyncPermissionDeniedError(msg="no upload permission for target knowledge space") from exc

    @staticmethod
    async def _save_temporary_file(
        params: FilelibSyncParams,
        upload_file: UploadFile,
    ) -> str:
        object_name = await KnowledgeService.save_upload_file_original_name(params.file_name)
        file_path = await save_uploaded_file(upload_file, "bisheng", object_name)
        return str(file_path)

    async def _cleanup_failed_sync(
        self,
        created_file: KnowledgeFile | None,
        temporary_file_path: str | None,
    ) -> None:
        if created_file is not None:
            try:
                await self.knowledge_space_service.cleanup_unqueued_files([created_file])
            except Exception:
                logger.exception(
                    "filelib sync failed-file cleanup failed file_id={}",
                    created_file.id,
                )
        if temporary_file_path:
            try:
                await asyncio.to_thread(
                    KnowledgeService.remove_unused_file,
                    temporary_file_path,
                )
            except Exception:
                # 临时对象会由对象存储生命周期策略清理; 不影响主错误返回。
                logger.warning(
                    "filelib sync temporary object cleanup failed path={}",
                    temporary_file_path,
                )
