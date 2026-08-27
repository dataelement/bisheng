from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

from fastapi import Request, UploadFile
from loguru import logger
from pydantic import ValidationError

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.filelib_sync import (
    FilelibSyncConflictError,
    FilelibSyncError,
    FilelibSyncInvalidParamsError,
    FilelibSyncNotFoundError,
    FilelibSyncPermissionDeniedError,
)
from bisheng.common.errcode.knowledge_space import (
    DepartmentKnowledgeSpaceAmbiguousError,
    SpaceFolderNotFoundError,
    SpaceNotFoundError,
    SpacePermissionDeniedError,
)
from bisheng.common.services.config_service import settings
from bisheng.core.cache.utils import save_uploaded_file
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.database.models.department import Department
from bisheng.database.models.tag import TagResourceTypeEnum
from bisheng.developer_token.domain.file_sync_folder_path import split_file_sync_folder_path
from bisheng.developer_token.domain.schemas import DeveloperTokenFileSyncRule
from bisheng.knowledge.domain.constants import normalize_business_domain_code
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileDao, KnowledgeFileStatus
from bisheng.knowledge.domain.services.department_space_target_resolver import (
    DepartmentSpaceTargetKind,
    DepartmentSpaceTargetResolver,
)
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService
from bisheng.knowledge.domain.upload_extensions import (
    UnsupportedUploadFileExtensionError,
    validate_knowledge_upload_file_extension,
)
from bisheng.knowledge.rag.pipeline.transformer.file_encoding import FileEncodingTransformer
from bisheng.open_endpoints.domain.repositories.interfaces.filelib_sync_repository import (
    FilelibSyncRepository,
)
from bisheng.open_endpoints.domain.schemas.filelib_sync import FilelibSyncParams, FilelibSyncResponseData
from bisheng.open_endpoints.domain.services.filelib_sync_audit_writer import FilelibSyncAuditWriter
from bisheng.shougang_portal_config.domain.schemas.portal_config_schema import (
    PortalDocumentTypeChildConfig,
    PortalDocumentTypeConfig,
    PortalDomainConfig,
    ShougangPortalAdminConfig,
)
from bisheng.shougang_portal_config.domain.services.portal_config_service import (
    ShougangPortalConfigService,
)
from bisheng.user.domain.models.user import User


@dataclass(frozen=True)
class ResolvedIdentity:
    responsible_user_id: int
    responsible_user_name: str
    responsible_user_external_id: str
    responsible_department: Department
    caller_department: Department
    main_department: Department
    business_domain_department: Department | None
    target_space_department: Department | None


@dataclass(frozen=True)
class ResolvedClassification:
    category_code: str
    subcategory_code: str
    business_domain_code: str
    business_domain_name: str


@dataclass(frozen=True)
class ResolvedFileSyncTarget:
    space: Knowledge
    folder_id: int | None
    used_personal_fallback: bool = False


FILELIB_SYNC_PERSONAL_FALLBACK_METADATA_KEY = "filelib_sync_target_fallback"
FILELIB_SYNC_PERSONAL_FALLBACK_METADATA_VALUE = "token_user_personal"
FILELIB_SYNC_PERSONAL_FALLBACK_LEVEL2_FOLDER = "业务接口未分配"
FILELIB_SYNC_DEVELOPER_TOKEN_ID_METADATA_KEY = "developer_token_id"
FILELIB_SYNC_DEVELOPER_TOKEN_NAME_METADATA_KEY = "developer_token_name"
FILELIB_SYNC_TAGS_METADATA_KEY = "filelib_sync_tags"


class FilelibSyncService:
    def __init__(
        self,
        *,
        request: Request | None,
        login_user: UserPayload,
        token_id: int,
        token_name: str = "",
        file_sync_rule: DeveloperTokenFileSyncRule,
        repository: FilelibSyncRepository,
        knowledge_space_service: KnowledgeSpaceService,
    ) -> None:
        self.request = request
        self.login_user = login_user
        self.token_id = token_id
        self.token_name = str(token_name or "").strip()
        self.file_sync_rule = file_sync_rule
        self.repository = repository
        self.knowledge_space_service = knowledge_space_service

    async def sync(
        self,
        *,
        raw_params: str,
        upload_file: UploadFile,
    ) -> FilelibSyncResponseData:
        params = self.parse_params(raw_params)
        self._validate_upload(params, upload_file)
        self._require_dynamic_source_id(params)
        temporary_file_path = await self._save_temporary_file(params, upload_file)
        return await self.sync_from_staged_file(
            params=params,
            local_file_path=temporary_file_path,
            endpoint_tag="sync",
            allow_personal_fallback=True,
        )

    async def sync_from_staged_file(
        self,
        *,
        params: FilelibSyncParams,
        local_file_path: str,
        endpoint_tag: str = "sync",
        trigger_type: str | None = None,
        allow_personal_fallback: bool = True,
        target_folder_path_override: str | None = None,
        target_folder_id_override: int | None = None,
        extra_user_metadata: dict[str, Any] | None = None,
    ) -> FilelibSyncResponseData:
        self._validate_file_name(params.file_name)
        self._require_dynamic_source_id(params)
        created_file: KnowledgeFile | None = None
        file_persisted = False
        staged_upload_path = local_file_path
        extra_cleanup_paths: list[str] = []
        identity: ResolvedIdentity | None = None
        target: ResolvedFileSyncTarget | None = None
        business_domain_code: str | None = None
        replaced_file_id: int | None = None
        try:
            identity = await self._resolve_identity(params)
            portal_config = await self._get_portal_config()
            self._resolve_document_type(portal_config)
            domain = self._resolve_business_domain(
                portal_config,
                identity.business_domain_department,
            )
            target = await self._resolve_target_space(
                identity,
                allow_personal_fallback=allow_personal_fallback,
            )
            if not target.used_personal_fallback:
                if target_folder_id_override is not None:
                    folder_id = int(target_folder_id_override)
                elif target_folder_path_override is not None:
                    folder_id = await self._resolve_folder_path_override(
                        int(target.space.id),
                        target_folder_path_override,
                    )
                else:
                    folder_id = await self._resolve_target_folder(int(target.space.id), identity)
                target = ResolvedFileSyncTarget(
                    space=target.space,
                    folder_id=folder_id,
                    used_personal_fallback=False,
                )
            if (
                domain is not None
                and self.file_sync_rule.business_domain.mode == "dynamic"
                and not target.used_personal_fallback
            ):
                self._ensure_domain_bound(target.space, domain)
            try:
                await self._require_upload_permission(target)
            except FilelibSyncNotFoundError:
                if target.used_personal_fallback or not allow_personal_fallback:
                    raise
                logger.warning(
                    "filelib sync target unavailable, fallback to token user personal space token_id={} knowledge_id={}",
                    self.token_id,
                    target.space.id,
                )
                target = await self._resolve_personal_fallback_target(identity)
                await self._require_upload_permission(target)

            replaced_file_id = await self._cleanup_duplicate_files_before_sync(
                knowledge_id=int(target.space.id),
                folder_id=target.folder_id,
                file_name=params.file_name,
                external_file_id=params.external_file_id,
            )

            staged_upload_path = await self._ensure_upload_path_preserves_display_name(
                local_file_path=local_file_path,
                file_name=params.file_name,
            )
            if staged_upload_path != local_file_path:
                extra_cleanup_paths.append(staged_upload_path)

            preview_cache_key = self.knowledge_space_service.get_preview_cache_key(
                int(target.space.id),
                staged_upload_path,
            )
            business_domain_code = domain.code if domain is not None else None
            upload_results = await self.knowledge_space_service.add_file(
                knowledge_id=int(target.space.id),
                file_path=[staged_upload_path],
                parent_id=target.folder_id,
                file_category_code=self.file_sync_rule.category.code,
                file_subcategory_code=self.file_sync_rule.category.subcategory_code,
                business_domain_code=business_domain_code,
                skip_approval=True,
                enqueue_processing=False,
                allow_duplicate_name=True,
                allow_duplicate_content=True,
                skip_space_business_domain_check=(
                    self.file_sync_rule.business_domain.mode == "fixed" or domain is None
                ),
            )
            if len(upload_results) != 1 or upload_results[0].status == KnowledgeFileStatus.FAILED.value:
                raise FilelibSyncConflictError(msg="duplicate file content or name")

            upload_result = upload_results[0]
            file_id = int(upload_result.id)
            created_file = upload_result if isinstance(upload_result, KnowledgeFile) else None
            if created_file is None:
                created_file = await self.repository.find_by_id(file_id)
            if created_file is None:
                raise FilelibSyncNotFoundError(msg="created knowledge file does not exist")
            owner_user_id = int(identity.responsible_user_id)
            owner_user_name = str(identity.responsible_user_name or "")
            # File owner follows params.responsible_person_id/responsible_person when provided;
            # otherwise defaults to the token-bound user via _resolve_responsible_user().
            created_file.user_id = owner_user_id
            created_file.user_name = owner_user_name
            created_file.updater_id = owner_user_id
            created_file.updater_name = owner_user_name
            created_file.original_uploader_id = owner_user_id
            user_metadata = {
                **(created_file.user_metadata or {}),
                "external_file_id": params.external_file_id,
                "department": identity.main_department.name,
                "department_id": int(identity.main_department.id),
                "responsible_person": identity.responsible_user_external_id,
                "responsible_person_id": identity.responsible_user_id,
                "filelib_sync_endpoint": endpoint_tag,
                FILELIB_SYNC_DEVELOPER_TOKEN_ID_METADATA_KEY: self.token_id,
                FILELIB_SYNC_DEVELOPER_TOKEN_NAME_METADATA_KEY: self._developer_token_display_name(),
            }
            if trigger_type is not None:
                user_metadata["filelib_sync_trigger"] = trigger_type
            if extra_user_metadata:
                user_metadata.update(extra_user_metadata)
            if target.used_personal_fallback:
                user_metadata[FILELIB_SYNC_PERSONAL_FALLBACK_METADATA_KEY] = (
                    FILELIB_SYNC_PERSONAL_FALLBACK_METADATA_VALUE
                )
            created_file.user_metadata = user_metadata
            if domain is not None:
                await FileEncodingTransformer.generate_fixed_encoding(
                    invoke_user_id=identity.responsible_user_id,
                    knowledge_file=created_file,
                    document_type_code=self.file_sync_rule.category.code,
                    business_domain_code=domain.code,
                )
            created_file = await asyncio.to_thread(KnowledgeFileDao.update, created_file)
            file_persisted = True

            applied_tags = await self._apply_sync_tags(
                space_id=int(target.space.id),
                file_id=int(created_file.id),
                tag_names=params.tags,
            )
            if applied_tags:
                created_file.user_metadata = {
                    **(created_file.user_metadata or {}),
                    FILELIB_SYNC_TAGS_METADATA_KEY: applied_tags,
                }
                created_file = await asyncio.to_thread(KnowledgeFileDao.update, created_file)

            await self.knowledge_space_service.enqueue_file_title_extraction(
                [created_file],
                [preview_cache_key],
                operator_user_id=self.login_user.user_id,
                operator_is_global_super=bool(getattr(self.login_user, "is_global_super", False)),
            )
            logger.info(
                "filelib sync queued token_id={} external_file_id={} file_id={} knowledge_id={} folder_id={} token_user_id={} responsible_user_id={} personal_fallback={} endpoint={} trigger={}",
                self.token_id,
                params.external_file_id,
                created_file.id,
                target.space.id,
                target.folder_id,
                self.login_user.user_id,
                identity.responsible_user_id,
                target.used_personal_fallback,
                endpoint_tag,
                trigger_type,
            )
            response = FilelibSyncResponseData(
                external_file_id=params.external_file_id,
                file_id=int(created_file.id),
                file_encoding=str(created_file.file_encoding),
                knowledge_id=int(target.space.id),
                knowledge_name=target.space.name,
                status=int(created_file.status),
                version_link_pending=False,
                replaced_file_id=replaced_file_id,
                tags=applied_tags,
            )
            folder_display_name = await self._resolve_folder_display_label(
                identity=identity,
                target=target,
            )
            await FilelibSyncAuditWriter.write_upload_success(
                request=self.request,
                login_user=self.login_user,
                token_id=self.token_id,
                token_name=self.token_name,
                params=params,
                identity=identity,
                target=target,
                created_file=created_file,
                response=response,
                endpoint_tag=endpoint_tag,
                trigger_type=trigger_type,
                business_domain_code=business_domain_code,
                category_code=self.file_sync_rule.category.code,
                subcategory_code=self.file_sync_rule.category.subcategory_code,
                replaced_file_id=replaced_file_id,
                extra_user_metadata=extra_user_metadata,
                folder_display_name=folder_display_name,
            )
            return response
        except FilelibSyncError as exc:
            folder_display_name = await self._resolve_folder_display_label(
                identity=identity,
                target=target,
            )
            await FilelibSyncAuditWriter.write_upload_failed(
                request=self.request,
                login_user=self.login_user,
                token_id=self.token_id,
                token_name=self.token_name,
                params=params,
                endpoint_tag=endpoint_tag,
                trigger_type=trigger_type,
                identity=identity,
                target=target,
                business_domain_code=business_domain_code,
                category_code=self.file_sync_rule.category.code,
                subcategory_code=self.file_sync_rule.category.subcategory_code,
                replaced_file_id=replaced_file_id,
                extra_user_metadata=extra_user_metadata,
                error=exc,
                created_file=created_file if file_persisted else None,
                folder_display_name=folder_display_name,
            )
            if not file_persisted:
                await self._cleanup_failed_sync(created_file, local_file_path)
                for extra_path in extra_cleanup_paths:
                    await self._cleanup_failed_sync(None, extra_path)
            raise
        except Exception as exc:
            folder_display_name = await self._resolve_folder_display_label(
                identity=identity,
                target=target,
            )
            await FilelibSyncAuditWriter.write_upload_failed(
                request=self.request,
                login_user=self.login_user,
                token_id=self.token_id,
                token_name=self.token_name,
                params=params,
                endpoint_tag=endpoint_tag,
                trigger_type=trigger_type,
                identity=identity,
                target=target,
                business_domain_code=business_domain_code,
                category_code=self.file_sync_rule.category.code,
                subcategory_code=self.file_sync_rule.category.subcategory_code,
                replaced_file_id=replaced_file_id,
                extra_user_metadata=extra_user_metadata,
                error=exc,
                created_file=created_file if file_persisted else None,
                folder_display_name=folder_display_name,
            )
            if not file_persisted:
                await self._cleanup_failed_sync(created_file, local_file_path)
                for extra_path in extra_cleanup_paths:
                    await self._cleanup_failed_sync(None, extra_path)
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
    def _validate_file_name(file_name: str) -> None:
        if "/" in file_name or "\\" in file_name:
            raise FilelibSyncInvalidParamsError(msg="file_name must be a base name")
        try:
            validate_knowledge_upload_file_extension(
                file_name,
                image_parser_enabled=settings.get_knowledge().image_parser_enabled,
            )
        except UnsupportedUploadFileExtensionError as exc:
            extension = str(exc) or "unknown"
            raise FilelibSyncInvalidParamsError(
                msg=f"file format is not supported: .{extension}",
            ) from exc

    @staticmethod
    def _validate_upload(params: FilelibSyncParams, upload_file: UploadFile) -> None:
        FilelibSyncService._validate_file_name(params.file_name)
        if upload_file.size == 0:
            raise FilelibSyncInvalidParamsError(msg="file must not be empty")

    async def _apply_sync_tags(
        self,
        *,
        space_id: int,
        file_id: int,
        tag_names: list[str],
    ) -> list[str]:
        if not tag_names:
            return []
        applied = await TagLibraryTagService.ensure_and_append_file_tags(
            space_id=space_id,
            file_id=file_id,
            tag_names=tag_names,
            user_id=int(self.login_user.user_id),
            tenant_id=int(self.login_user.tenant_id) if self.login_user.tenant_id is not None else None,
            resource_type=TagResourceTypeEnum.MANUAL_TAG,
        )
        logger.info(
            "filelib sync tags applied token_id={} file_id={} knowledge_id={} requested={} applied={}",
            self.token_id,
            file_id,
            space_id,
            len(tag_names),
            len(applied),
        )
        return applied

    def _require_dynamic_source_id(self, params: FilelibSyncParams) -> None:
        required_fields: set[str] = set()
        if self.file_sync_rule.business_domain.mode == "dynamic":
            required_fields.add(self.file_sync_rule.business_domain.dynamic_source or "")
        if self.file_sync_rule.target_space.mode == "dynamic":
            required_fields.add(self.file_sync_rule.target_space.dynamic_source or "")
        required_fields.discard("")

        if "department_id" in required_fields and params.department_id is None:
            raise FilelibSyncInvalidParamsError(msg="department_id is required by the token rule")
        if "responsible_person_id" in required_fields and not self._resolve_responsible_external_id(params):
            raise FilelibSyncInvalidParamsError(msg="responsible_person_id is required by the token rule")

    @staticmethod
    def _department_for_dynamic_source(
        *,
        source: str,
        main_department: Department,
        responsible_department: Department,
    ) -> Department:
        if source == "department_id":
            return main_department
        if source == "responsible_person_id":
            return responsible_department
        raise FilelibSyncInvalidParamsError(msg="invalid dynamic source in token rule")

    @staticmethod
    def _normalize_user_external_id(user: User | None) -> str:
        if user is None:
            return ""
        return str(getattr(user, "external_id", None) or "").strip()

    @staticmethod
    def _resolve_responsible_external_id(params: FilelibSyncParams) -> str | None:
        external_id = params.responsible_person_id or params.responsible_person
        if (
            params.responsible_person_id
            and params.responsible_person
            and params.responsible_person_id != params.responsible_person
        ):
            raise FilelibSyncInvalidParamsError(msg="responsible_person does not match responsible_person_id")
        return external_id

    async def _resolve_responsible_user(self, params: FilelibSyncParams) -> tuple[int, str, str]:
        tenant_id = int(self.login_user.tenant_id)
        external_id = self._resolve_responsible_external_id(params)

        if external_id:
            matches = await self.repository.find_users_by_external_id(
                external_id,
                tenant_id=tenant_id,
            )
            if not matches:
                raise FilelibSyncNotFoundError(msg="responsible person does not exist")
            if len(matches) != 1:
                raise FilelibSyncInvalidParamsError(msg="responsible person is ambiguous")
            responsible_user = matches[0]
            return (
                int(responsible_user.user_id),
                str(responsible_user.user_name or ""),
                external_id,
            )

        if int(self.login_user.user_id) > 0:
            token_user = await self.repository.find_user_by_id(int(self.login_user.user_id))
            return (
                int(self.login_user.user_id),
                self.login_user.user_name,
                self._normalize_user_external_id(token_user),
            )
        return int(self.login_user.user_id), self.login_user.user_name, ""

    async def _resolve_identity(self, params: FilelibSyncParams) -> ResolvedIdentity:
        (
            responsible_user_id,
            responsible_user_name,
            responsible_user_external_id,
        ) = await self._resolve_responsible_user(params)

        caller_department = await self._resolve_unique_primary_department(
            int(self.login_user.user_id),
            subject="caller",
        )

        responsible_department = await self._resolve_unique_primary_department(
            responsible_user_id,
            subject="responsible person",
        )

        main_department = await self._resolve_main_department(params, responsible_department)
        if params.department and params.department != main_department.name:
            raise FilelibSyncInvalidParamsError(msg="department does not match department_id")

        business_domain_department = None
        if self.file_sync_rule.business_domain.mode == "dynamic":
            business_domain_department = self._department_for_dynamic_source(
                source=str(self.file_sync_rule.business_domain.dynamic_source),
                main_department=main_department,
                responsible_department=responsible_department,
            )
        target_space_department = None
        if self.file_sync_rule.target_space.mode == "dynamic":
            target_space_department = self._department_for_dynamic_source(
                source=str(self.file_sync_rule.target_space.dynamic_source),
                main_department=main_department,
                responsible_department=responsible_department,
            )

        return ResolvedIdentity(
            responsible_user_id=responsible_user_id,
            responsible_user_name=responsible_user_name,
            responsible_user_external_id=responsible_user_external_id,
            responsible_department=responsible_department,
            caller_department=caller_department,
            main_department=main_department,
            business_domain_department=business_domain_department,
            target_space_department=target_space_department,
        )

    async def _resolve_main_department(
        self,
        params: FilelibSyncParams,
        default_department: Department,
    ) -> Department:
        if params.department_id is None:
            return default_department

        mapping = await self.repository.find_department_mapping_by_external_department_id(
            params.department_id,
        )
        if mapping is None:
            logger.warning(
                "filelib sync department_id={} mapping missing; fallback to uploader primary department_id={}",
                params.department_id,
                default_department.id,
            )
            return default_department

        department = await self.repository.find_department_by_external_id(
            mapping.org_code,
            tenant_id=int(self.login_user.tenant_id),
        )
        if department is None:
            logger.warning(
                "filelib sync department_id={} org_code={} department missing; "
                "fallback to uploader primary department_id={}",
                params.department_id,
                mapping.org_code,
                default_department.id,
            )
            return default_department
        return department

    async def _resolve_unique_primary_department(
        self,
        user_id: int,
        *,
        subject: str,
    ) -> Department:
        primary_links = await self.repository.find_primary_departments(user_id)
        if not primary_links:
            raise FilelibSyncNotFoundError(msg=f"{subject} primary department does not exist")
        if len(primary_links) > 1:
            raise FilelibSyncConflictError(msg=f"{subject} has multiple primary departments")
        department = await self.repository.find_department_by_id(int(primary_links[0].department_id))
        if department is None:
            raise FilelibSyncNotFoundError(msg=f"{subject} primary department does not exist")
        return department

    @staticmethod
    async def _get_portal_config() -> ShougangPortalAdminConfig:
        config = await ShougangPortalConfigService.get_config()
        if config is None:
            raise FilelibSyncNotFoundError(msg="首钢股份知识管理平台未配置文件分类和业务域")
        return config

    def _resolve_document_type(
        self,
        config: ShougangPortalAdminConfig,
    ) -> tuple[PortalDocumentTypeConfig, PortalDocumentTypeChildConfig]:
        parent_matches = [
            item
            for item in config.portal.document_types
            if str(item.code or "").strip().upper() == self.file_sync_rule.category.code
        ]
        if not parent_matches:
            raise FilelibSyncNotFoundError(msg="configured file category does not exist")
        if len(parent_matches) > 1:
            raise FilelibSyncConflictError(msg="multiple configured file categories match")

        document_type = parent_matches[0]
        child_matches = [
            item
            for item in document_type.children
            if str(item.code or "").strip().upper() == self.file_sync_rule.category.subcategory_code
        ]
        if not child_matches:
            raise FilelibSyncNotFoundError(msg="configured file subcategory does not exist")
        if len(child_matches) > 1:
            raise FilelibSyncConflictError(msg="multiple configured file subcategories match")
        return document_type, child_matches[0]

    def _resolve_business_domain(
        self,
        config: ShougangPortalAdminConfig,
        selected_department: Department | None,
    ) -> PortalDomainConfig | None:
        if self.file_sync_rule.business_domain.mode == "fixed":
            candidates = [
                item
                for item in config.portal.domains
                if item.enabled
                and normalize_business_domain_code(item.code) == self.file_sync_rule.business_domain.code
            ]
        else:
            if selected_department is None:
                raise FilelibSyncNotFoundError(msg="dynamic business department does not exist")
            candidates = [
                item
                for item in config.portal.domains
                if item.enabled
                and normalize_business_domain_code(item.code)
                and int(selected_department.id) in (item.department_ids or [])
            ]
        if not candidates:
            if self.file_sync_rule.business_domain.mode == "dynamic":
                logger.warning(
                    "filelib sync business domain unresolved department_id={} department_name={}; uploading without business domain",
                    getattr(selected_department, "id", None),
                    getattr(selected_department, "name", None),
                )
                return None
            raise FilelibSyncNotFoundError(msg="configured business domain does not exist")
        if len(candidates) > 1:
            if self.file_sync_rule.business_domain.mode == "dynamic":
                logger.warning(
                    "filelib sync multiple business domains match department_id={} department_name={}; using first domain code={}",
                    getattr(selected_department, "id", None),
                    getattr(selected_department, "name", None),
                    candidates[0].code,
                )
                return candidates[0]
            raise FilelibSyncConflictError(msg="multiple business domains match the department")
        return candidates[0]

    async def _resolve_target_space(
        self,
        identity: ResolvedIdentity,
        *,
        allow_personal_fallback: bool = True,
    ) -> ResolvedFileSyncTarget:
        try:
            space = await self._resolve_configured_target_space(identity)
            return ResolvedFileSyncTarget(space=space, folder_id=None, used_personal_fallback=False)
        except (FilelibSyncNotFoundError, FilelibSyncConflictError) as exc:
            if not allow_personal_fallback:
                raise
            logger.warning(
                "filelib sync configured target space unavailable, fallback to token user personal space: {}",
                exc,
            )
            return await self._resolve_personal_fallback_target(identity)

    async def _resolve_configured_target_space(self, identity: ResolvedIdentity) -> Knowledge:
        if self.file_sync_rule.target_space.mode == "fixed":
            space = await self.repository.find_knowledge_by_id(int(self.file_sync_rule.target_space.knowledge_id))
            if space is None:
                raise FilelibSyncNotFoundError(msg="configured target knowledge space does not exist")
            return space
        if identity.target_space_department is None:
            raise FilelibSyncNotFoundError(msg="dynamic target department does not exist")
        dynamic_source = str(self.file_sync_rule.target_space.dynamic_source or "")
        return await self._find_department_space(
            identity.target_space_department,
            dynamic_source=dynamic_source,
        )

    async def _resolve_personal_fallback_target(self, identity: ResolvedIdentity) -> ResolvedFileSyncTarget:
        space = await self.knowledge_space_service.ensure_personal_default_space()
        folder_id = await self._resolve_personal_fallback_folder(int(space.id), identity)
        return ResolvedFileSyncTarget(
            space=space,
            folder_id=folder_id,
            used_personal_fallback=True,
        )

    def _personal_fallback_token_folder_name(self) -> str:
        return self._developer_token_display_name()

    def _developer_token_display_name(self) -> str:
        if self.token_name:
            return self.token_name
        return f"token-{self.token_id}"

    def _resolve_configured_target_folder_path(self, identity: ResolvedIdentity) -> str | None:
        rule = self.file_sync_rule.target_space
        if rule.folder_mode == "none":
            return None
        if rule.folder_mode == "fixed":
            return rule.folder_path
        segments = list(split_file_sync_folder_path(rule.parent_folder_path))
        try:
            child_name = self._resolve_dynamic_folder_name(identity, rule.folder_dynamic_source).strip()
        except FilelibSyncInvalidParamsError:
            child_name = ""
        if child_name:
            segments.append(child_name)
        if not segments:
            return None
        return "/".join(segments)

    def build_personal_fallback_folder_path(self, identity: ResolvedIdentity) -> str:
        segments = [
            FILELIB_SYNC_PERSONAL_FALLBACK_LEVEL2_FOLDER,
            self._personal_fallback_token_folder_name(),
        ]
        segments.extend(split_file_sync_folder_path(self._resolve_configured_target_folder_path(identity)))
        return "/".join(segments)

    async def _resolve_personal_fallback_folder(
        self,
        knowledge_id: int,
        identity: ResolvedIdentity,
    ) -> int | None:
        folder_path = self.build_personal_fallback_folder_path(identity)
        try:
            folder = await self.knowledge_space_service.find_or_create_folder_path_for_file_sync(
                knowledge_id,
                folder_path,
            )
        except SpaceFolderNotFoundError as exc:
            raise FilelibSyncNotFoundError(msg="personal fallback folder cannot be created") from exc
        except SpacePermissionDeniedError as exc:
            raise FilelibSyncPermissionDeniedError(msg="no permission to create personal fallback folder") from exc
        if folder is None:
            return None
        return int(folder.id)

    async def _resolve_folder_display_label(
        self,
        *,
        identity: ResolvedIdentity | None,
        target: ResolvedFileSyncTarget | None,
    ) -> str | None:
        if target is None:
            return None
        if target.used_personal_fallback and identity is not None:
            return self.build_personal_fallback_folder_path(identity)
        if target.folder_id is None:
            return "根目录"
        folder = await self.repository.find_by_id(int(target.folder_id))
        if folder is None:
            return f"目录#{target.folder_id}"
        return str(folder.file_name or f"#{target.folder_id}")

    async def _resolve_folder_path_override(
        self,
        knowledge_id: int,
        folder_path: str,
    ) -> int | None:
        try:
            folder = await self.knowledge_space_service.find_or_create_folder_path_for_file_sync(
                knowledge_id,
                folder_path,
            )
        except SpaceFolderNotFoundError as exc:
            raise FilelibSyncNotFoundError(msg="configured folder path does not exist") from exc
        except SpacePermissionDeniedError as exc:
            raise FilelibSyncPermissionDeniedError(msg="no permission to create target folder") from exc
        if folder is None:
            return None
        return int(folder.id)

    async def _resolve_target_folder(
        self,
        knowledge_id: int,
        identity: ResolvedIdentity,
    ) -> int | None:
        rule = self.file_sync_rule.target_space
        folder_mode = rule.folder_mode
        if folder_mode == "none":
            return None
        if folder_mode == "fixed":
            if rule.folder_path:
                try:
                    folder = await self.knowledge_space_service.find_or_create_folder_path_for_file_sync(
                        knowledge_id,
                        rule.folder_path,
                    )
                except SpaceFolderNotFoundError as exc:
                    raise FilelibSyncNotFoundError(msg="configured folder path does not exist") from exc
                except SpacePermissionDeniedError as exc:
                    raise FilelibSyncPermissionDeniedError(msg="no permission to create target folder") from exc
                if folder is None:
                    return None
                return int(folder.id)
            return rule.folder_id

        child_name = self._resolve_dynamic_folder_name(identity, rule.folder_dynamic_source)
        if not str(child_name or "").strip():
            raise FilelibSyncInvalidParamsError(msg="dynamic folder name is empty")

        try:
            parent_folder = await self.knowledge_space_service.find_or_create_folder_path_for_file_sync(
                knowledge_id,
                rule.parent_folder_path,
            )
            parent_id = int(parent_folder.id) if parent_folder is not None else None
            folder = await self.knowledge_space_service.find_or_create_folder_for_file_sync(
                knowledge_id,
                child_name.strip(),
                parent_id,
            )
        except SpaceFolderNotFoundError as exc:
            raise FilelibSyncNotFoundError(msg="configured parent folder path does not exist") from exc
        except SpacePermissionDeniedError as exc:
            raise FilelibSyncPermissionDeniedError(msg="no permission to create dynamic folder") from exc
        return int(folder.id)

    @staticmethod
    def _resolve_dynamic_folder_name(
        identity: ResolvedIdentity,
        source: str | None,
    ) -> str:
        if source == "department_name":
            return str(identity.main_department.name or "")
        if source == "caller_main_department_name":
            return str(identity.caller_department.name or "")
        raise FilelibSyncInvalidParamsError(msg="invalid folder dynamic source in token rule")

    async def _find_department_space(
        self,
        department: Department,
        *,
        dynamic_source: str = "department_id",
    ) -> Knowledge:
        if dynamic_source == "responsible_person_id":
            return await self._find_responsible_person_target_space(department)
        return await self._resolve_bound_space(
            department,
            department_ids=self._department_chain(department),
            kind=DepartmentSpaceTargetKind.DEPARTMENT,
        )

    async def _find_responsible_person_target_space(self, department: Department) -> Knowledge:
        """Clinic library on the responsible person's department, then nearest department library."""
        clinic_space = await self._resolve_bound_space(
            department,
            department_ids=[int(department.id)],
            kind=DepartmentSpaceTargetKind.CLINIC,
            missing_is_error=False,
            ambiguous_picks_first=True,
        )
        if clinic_space is not None:
            return clinic_space
        return await self._resolve_bound_space(
            department,
            department_ids=self._department_chain(department),
            kind=DepartmentSpaceTargetKind.DEPARTMENT,
        )

    async def _resolve_bound_space(
        self,
        department: Department,
        *,
        department_ids: list[int],
        kind: DepartmentSpaceTargetKind,
        missing_is_error: bool = True,
        ambiguous_picks_first: bool = False,
    ) -> Knowledge | None:
        space_id: int | None
        try:
            space_id = await DepartmentSpaceTargetResolver.resolve(
                department_ids,
                kind=kind,
                allow_legacy=False,
            )
        except DepartmentKnowledgeSpaceAmbiguousError as exc:
            if ambiguous_picks_first:
                candidate_space_ids = sorted(
                    int(one) for one in (exc.kwargs.get("candidate_space_ids") or [])
                )
                if not candidate_space_ids:
                    if missing_is_error:
                        raise FilelibSyncConflictError(
                            msg="multiple target clinic knowledge spaces are bound to the department",
                        ) from exc
                    return None
                space_id = candidate_space_ids[0]
                logger.warning(
                    "filelib sync picked first clinic knowledge space department_id={} space_id={} candidates={}",
                    int(department.id),
                    space_id,
                    candidate_space_ids,
                )
            else:
                space_label = "clinic" if kind == DepartmentSpaceTargetKind.CLINIC else "department"
                raise FilelibSyncConflictError(
                    msg=f"multiple target {space_label} knowledge spaces are bound to the department",
                ) from exc
        if space_id is None:
            if missing_is_error:
                raise FilelibSyncNotFoundError(msg=f"首钢股份知识管理平台不存在知识库{department.name}")
            return None
        space = await self.repository.find_knowledge_by_id(space_id)
        if space is None:
            if missing_is_error:
                raise FilelibSyncNotFoundError(msg=f"首钢股份知识管理平台不存在知识库{department.name}")
            return None
        return space

    async def _find_nearest_department_space(self, department: Department) -> Knowledge:
        return await self._find_department_space(department, dynamic_source="department_id")

    @staticmethod
    def _department_chain(department: Department) -> list[int]:
        path_ids = [int(part) for part in str(department.path or "").split("/") if part.strip().isdigit()]
        if int(department.id) not in path_ids:
            path_ids.append(int(department.id))
        return list(dict.fromkeys(reversed(path_ids)))

    @staticmethod
    def _ensure_domain_bound(space: Knowledge, domain: PortalDomainConfig) -> None:
        configured_space_ids = {int(space_id) for space_id in (domain.space_ids or []) if int(space_id) > 0}
        allowed_codes = {
            normalized
            for code in (space.business_domain_codes or [])
            if (normalized := normalize_business_domain_code(code)) is not None
        }
        domain_code = normalize_business_domain_code(domain.code)
        if int(space.id) not in configured_space_ids or domain_code not in allowed_codes:
            logger.warning(f"首钢股份知识管理平台的{space.name}不存在{domain.name}")
            # raise FilelibSyncNotFoundError(msg=f"首钢股份知识管理平台的{space.name}不存在{domain.name}")
            return

    async def _require_upload_permission(self, target: ResolvedFileSyncTarget) -> None:
        strict_catalog = (
            self.file_sync_rule.target_space.mode == "fixed"
            and not target.used_personal_fallback
        )
        try:
            await KnowledgeSpaceService.validate_file_sync_target(
                login_user=self.login_user,
                knowledge_id=int(target.space.id),
                folder_id=target.folder_id,
                strict_catalog=strict_catalog,
            )
        except (SpaceNotFoundError, SpaceFolderNotFoundError) as exc:
            raise FilelibSyncNotFoundError(msg="configured file sync target does not exist") from exc
        except SpacePermissionDeniedError as exc:
            raise FilelibSyncPermissionDeniedError(msg="no upload permission for file sync target") from exc

    async def _cleanup_duplicate_files_before_sync(
        self,
        *,
        knowledge_id: int,
        folder_id: int | None,
        file_name: str,
        external_file_id: str,
    ) -> int | None:
        """Soft-delete historical duplicates in the target folder; newest upload wins."""
        file_level_path = await self._resolve_upload_file_level_path(
            knowledge_id=knowledge_id,
            folder_id=folder_id,
        )
        candidates: dict[int, KnowledgeFile] = {}

        for existing_file in await asyncio.to_thread(
            KnowledgeFileDao.get_file_by_condition,
            knowledge_id=knowledge_id,
            file_name=file_name,
            file_level_path=file_level_path,
        ) or []:
            candidates[int(existing_file.id)] = existing_file

        for existing_file in await self.repository.find_files_by_external_file_id(
            knowledge_id,
            external_file_id,
            file_level_path=file_level_path,
        ):
            candidates[int(existing_file.id)] = existing_file

        if not candidates:
            return None

        ordered = sorted(
            candidates.values(),
            key=lambda item: (
                getattr(item, "create_time", None),
                int(item.id),
            ),
            reverse=True,
        )
        replaced_file_id = int(ordered[0].id)
        removed_ids: list[int] = []
        for existing_file in ordered:
            await self._remove_duplicate_file_for_sync_replace(int(existing_file.id))
            removed_ids.append(int(existing_file.id))

        logger.info(
            "filelib sync duplicate cleanup knowledge_id={} folder_id={} file_name={} external_file_id={} removed_ids={} replaced_file_id={}",
            knowledge_id,
            folder_id,
            file_name,
            external_file_id,
            removed_ids,
            replaced_file_id,
        )
        return replaced_file_id

    @staticmethod
    async def _resolve_upload_file_level_path(
        *,
        knowledge_id: int,
        folder_id: int | None,
    ) -> str:
        if folder_id is None:
            return ""
        folder = await asyncio.to_thread(KnowledgeFileDao.query_by_id_sync, int(folder_id))
        if folder is None or int(folder.knowledge_id) != int(knowledge_id):
            raise FilelibSyncNotFoundError(msg="target folder does not exist")
        parent_path = folder.file_level_path or ""
        return f"{parent_path}/{int(folder_id)}" if parent_path else str(int(folder_id))

    async def _remove_duplicate_file_for_sync_replace(self, file_id: int) -> None:
        try:
            await self.knowledge_space_service.delete_file(file_id)
        except SpaceNotFoundError:
            logger.warning("filelib sync replace skipped missing file_id={}", file_id)
        except SpacePermissionDeniedError as exc:
            raise FilelibSyncPermissionDeniedError(
                msg="no permission to replace existing file for file sync",
            ) from exc

    @staticmethod
    async def _save_temporary_file(
        params: FilelibSyncParams,
        upload_file: UploadFile,
    ) -> str:
        object_name = await KnowledgeService.save_upload_file_original_name(params.file_name)
        file_path = await save_uploaded_file(upload_file, "bisheng", object_name)
        return str(file_path)

    @staticmethod
    async def _ensure_upload_path_preserves_display_name(
        *,
        local_file_path: str,
        file_name: str,
    ) -> str:
        """Re-stage local disk files with the uuid+Redis naming used by HTTP uploads."""
        local_candidate = local_file_path.split("?", 1)[0]
        if not os.path.isfile(local_candidate):
            return local_file_path

        object_name = await KnowledgeService.save_upload_file_original_name(file_name)
        minio_client = await get_minio_storage()
        content_type = (
            "application/pdf"
            if object_name.lower().endswith(".pdf")
            else "application/octet-stream"
        )
        await minio_client.put_object_tmp(
            object_name=object_name,
            file=local_candidate,
            content_type=content_type,
        )
        return str(
            await minio_client.get_share_link(
                object_name,
                minio_client.tmp_bucket,
                clear_host=False,
            )
        )

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
