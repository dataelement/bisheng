from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from bisheng.common.errcode.filelib_sync import (
    FilelibSyncError,
    FilelibSyncNotFoundError,
    FilelibSyncPermissionDeniedError,
)
from bisheng.common.errcode.inspection_standard_sync import (
    InspectionStandardSyncCreateDeptIdError,
    InspectionStandardSyncEmptyDataError,
    InspectionStandardSyncFieldValidationError,
    InspectionStandardSyncInvalidTimeError,
    InspectionStandardSyncRelationError,
    InspectionStandardSyncTokenRuleError,
)
from bisheng.common.errcode.knowledge_space import SpaceFolderNotFoundError, SpacePermissionDeniedError
from bisheng.developer_token.domain.file_sync_folder_path import normalize_file_sync_folder_path
from bisheng.developer_token.domain.schemas import DeveloperTokenFileSyncRule
from bisheng.open_endpoints.domain.schemas.filelib_sync import FilelibSyncParams
from bisheng.open_endpoints.domain.schemas.inspection_standard_sync import (
    InspectionStandardItemRecord,
    InspectionStandardRecord,
    InspectionStandardSyncFileResult,
    InspectionStandardSyncRequest,
    InspectionStandardSyncResponseData,
)
from bisheng.open_endpoints.domain.services.filelib_sync_service import FilelibSyncService
from bisheng.open_endpoints.domain.services.inspection_standard_excel_builder import (
    build_inspection_standard_xlsx_bytes,
)

_PATH_SEPARATOR_PATTERN = re.compile(r"[\\/]")


@dataclass(frozen=True)
class InspectionStandardGroup:
    create_dept_id: str
    check_standards: list[InspectionStandardRecord]
    check_standard_items: list[InspectionStandardItemRecord]


class InspectionStandardSyncService:
    def __init__(self, *, filelib_sync_service: FilelibSyncService) -> None:
        self.filelib_sync_service = filelib_sync_service

    async def sync(self, request: InspectionStandardSyncRequest) -> InspectionStandardSyncResponseData:
        self._validate_token_rule(self.filelib_sync_service.file_sync_rule)
        start_dt, end_dt = self._parse_time_window(request.start_time, request.end_time)
        year_dir = str(start_dt.year)
        groups = self._build_groups(request)
        generated_file_name = self._build_generated_file_name(start_dt, end_dt)
        base_folder_path = self._resolve_base_folder_path(self.filelib_sync_service.file_sync_rule)
        knowledge_id = int(self.filelib_sync_service.file_sync_rule.target_space.knowledge_id)

        staged_paths: list[str] = []
        try:
            file_results: list[InspectionStandardSyncFileResult] = []
            for group in groups:
                target_folder_id, folder_path = await self._resolve_group_target_folder(
                    knowledge_id=knowledge_id,
                    create_dept_id=group.create_dept_id,
                    base_folder_path=base_folder_path,
                    year=year_dir,
                )
                xlsx_bytes = build_inspection_standard_xlsx_bytes(
                    check_standards=group.check_standards,
                    check_standard_items=group.check_standard_items,
                )
                staged_path = self._write_temp_xlsx(xlsx_bytes)
                staged_paths.append(staged_path)
                params = FilelibSyncParams(
                    external_file_id=self._build_external_file_id(
                        create_dept_id=group.create_dept_id,
                        start_time=request.start_time,
                        end_time=request.end_time,
                        check_standard_count=len(group.check_standards),
                        check_standard_item_count=len(group.check_standard_items),
                    ),
                    file_name=generated_file_name,
                )
                sync_result = await self.filelib_sync_service.sync_from_staged_file(
                    params=params,
                    local_file_path=staged_path,
                    endpoint_tag="inspection_standard_sync",
                    allow_personal_fallback=False,
                    target_folder_id_override=target_folder_id,
                    extra_user_metadata={
                        "inspection_standard_data_start": request.start_time,
                        "inspection_standard_data_end": request.end_time,
                        "inspection_standard_create_dept_id": group.create_dept_id,
                        "inspection_standard_check_standard_count": len(group.check_standards),
                        "inspection_standard_check_standard_item_count": len(group.check_standard_items),
                    },
                )
                file_results.append(
                    InspectionStandardSyncFileResult.from_filelib_sync(
                        create_dept_id=group.create_dept_id,
                        folder_path=folder_path,
                        generated_file_name=generated_file_name,
                        check_standard_count=len(group.check_standards),
                        check_standard_item_count=len(group.check_standard_items),
                        sync_result=sync_result,
                    )
                )
            return InspectionStandardSyncResponseData(
                data_start_time=request.start_time,
                data_end_time=request.end_time,
                group_count=len(file_results),
                files=file_results,
            )
        except FilelibSyncError:
            raise
        finally:
            for path in staged_paths:
                self._safe_unlink(path)

    @staticmethod
    def _validate_token_rule(rule: DeveloperTokenFileSyncRule) -> None:
        if rule.business_domain.mode != "fixed" or not rule.business_domain.code:
            raise InspectionStandardSyncTokenRuleError(
                msg="token file_sync_rule requires fixed business domain",
            )
        if rule.business_domain.dynamic_source is not None:
            raise InspectionStandardSyncTokenRuleError(
                msg="token file_sync_rule does not support dynamic business domain",
            )
        target_space = rule.target_space
        if target_space.mode != "fixed" or target_space.knowledge_id is None:
            raise InspectionStandardSyncTokenRuleError(
                msg="token file_sync_rule requires fixed target knowledge space",
            )
        if target_space.dynamic_source is not None:
            raise InspectionStandardSyncTokenRuleError(
                msg="token file_sync_rule does not support dynamic target space",
            )
        if target_space.folder_mode == "dynamic":
            raise InspectionStandardSyncTokenRuleError(
                msg="token file_sync_rule does not support dynamic folder mode",
            )
        if not target_space.folder_path and target_space.folder_id is None:
            raise InspectionStandardSyncTokenRuleError(
                msg="token file_sync_rule requires fixed folder_path or folder_id",
            )

    @staticmethod
    def _parse_time_window(start_time: str, end_time: str) -> tuple[datetime, datetime]:
        start_dt = InspectionStandardSyncService._parse_time_value(start_time)
        end_dt = InspectionStandardSyncService._parse_time_value(end_time)
        if end_dt < start_dt:
            raise InspectionStandardSyncInvalidTimeError(msg="end_time must be greater than or equal to start_time")
        return start_dt, end_dt

    @staticmethod
    def _parse_time_value(value: str) -> datetime:
        text = str(value or "").strip()
        if not text:
            raise InspectionStandardSyncInvalidTimeError(msg="time value must not be empty")
        normalized = text.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        raise InspectionStandardSyncInvalidTimeError(msg="time value is invalid")

    @staticmethod
    def _build_groups(request: InspectionStandardSyncRequest) -> list[InspectionStandardGroup]:
        try:
            standards = list(request.data.check_standards)
            items = list(request.data.check_standard_items)
        except ValidationError as exc:
            raise InspectionStandardSyncFieldValidationError(msg="request data fields are invalid") from exc

        standard_id_to_dept: dict[str, str] = {}
        grouped_standards: dict[str, list[InspectionStandardRecord]] = defaultdict(list)
        grouped_items: dict[str, list[InspectionStandardItemRecord]] = defaultdict(list)
        seq_seen: set[tuple[str, str]] = set()

        for record in standards:
            create_dept_id = record.CREATE_DEPT_ID.strip()
            InspectionStandardSyncService._validate_create_dept_id(create_dept_id)
            if record.CHECK_STANDARD_ID in standard_id_to_dept:
                raise InspectionStandardSyncRelationError(msg="CHECK_STANDARD_ID must be unique")
            standard_id_to_dept[record.CHECK_STANDARD_ID] = create_dept_id
            grouped_standards[create_dept_id].append(record)

        for item in items:
            standard_id = item.CHECK_STANDARD_ID
            create_dept_id = standard_id_to_dept.get(standard_id)
            if create_dept_id is None:
                raise InspectionStandardSyncRelationError(
                    msg="check_standard_items references unknown CHECK_STANDARD_ID",
                )
            seq_key = (standard_id, item.CHECK_STANDARD_SEQ_NO)
            if seq_key in seq_seen:
                raise InspectionStandardSyncRelationError(
                    msg="CHECK_STANDARD_SEQ_NO must be unique within CHECK_STANDARD_ID",
                )
            seq_seen.add(seq_key)
            grouped_items[create_dept_id].append(item)

        groups: list[InspectionStandardGroup] = []
        for create_dept_id in sorted(grouped_standards.keys()):
            standards_in_group = grouped_standards[create_dept_id]
            items_in_group = grouped_items.get(create_dept_id, [])
            if not standards_in_group or not items_in_group:
                raise InspectionStandardSyncEmptyDataError(
                    msg="each CREATE_DEPT_ID group must contain standards and items",
                )
            groups.append(
                InspectionStandardGroup(
                    create_dept_id=create_dept_id,
                    check_standards=standards_in_group,
                    check_standard_items=items_in_group,
                )
            )
        if not groups:
            raise InspectionStandardSyncEmptyDataError(msg="request data must not be empty")
        return groups

    @staticmethod
    def _validate_create_dept_id(value: str) -> None:
        if not str(value or "").strip():
            raise InspectionStandardSyncCreateDeptIdError(msg="CREATE_DEPT_ID must not be empty")
        if _PATH_SEPARATOR_PATTERN.search(value):
            raise InspectionStandardSyncCreateDeptIdError(msg="CREATE_DEPT_ID must not contain path separators")

    @staticmethod
    def _resolve_base_folder_path(rule: DeveloperTokenFileSyncRule) -> str | None:
        if rule.target_space.folder_path:
            return rule.target_space.folder_path
        return None

    async def _resolve_group_target_folder(
        self,
        *,
        knowledge_id: int,
        create_dept_id: str,
        base_folder_path: str | None,
        year: str,
    ) -> tuple[int, str]:
        rule = self.filelib_sync_service.file_sync_rule.target_space
        knowledge_space_service = self.filelib_sync_service.knowledge_space_service
        child = normalize_file_sync_folder_path(create_dept_id)
        if child is None:
            raise InspectionStandardSyncCreateDeptIdError(msg="CREATE_DEPT_ID is invalid")
        year_segment = normalize_file_sync_folder_path(year)
        if year_segment is None:
            raise InspectionStandardSyncInvalidTimeError(msg="start_time year is invalid")
        relative_path = f"{child}/{year_segment}"

        try:
            if base_folder_path:
                folder_path = f"{base_folder_path}/{relative_path}"
                folder = await knowledge_space_service.find_or_create_folder_path_for_file_sync(
                    knowledge_id,
                    folder_path,
                )
            elif rule.folder_id is not None:
                dept_folder = await knowledge_space_service.find_or_create_folder_for_file_sync(
                    knowledge_id,
                    child,
                    int(rule.folder_id),
                )
                folder = await knowledge_space_service.find_or_create_folder_for_file_sync(
                    knowledge_id,
                    year_segment,
                    int(dept_folder.id),
                )
                folder_path = relative_path
            else:
                raise InspectionStandardSyncTokenRuleError(
                    msg="token file_sync_rule requires fixed folder_path or folder_id",
                )
        except SpaceFolderNotFoundError as exc:
            raise FilelibSyncNotFoundError(msg="configured folder path does not exist") from exc
        except SpacePermissionDeniedError as exc:
            raise FilelibSyncPermissionDeniedError(msg="no permission to create target folder") from exc

        if folder is None:
            raise FilelibSyncNotFoundError(msg="target folder does not exist")
        return int(folder.id), folder_path

    @staticmethod
    def _build_generated_file_name(start_dt: datetime, end_dt: datetime) -> str:
        start_date = start_dt.date().isoformat()
        end_date = end_dt.date().isoformat()
        return f"{start_date}至{end_date}.xlsx"

    @staticmethod
    def _build_external_file_id(
        *,
        create_dept_id: str,
        start_time: str,
        end_time: str,
        check_standard_count: int,
        check_standard_item_count: int,
    ) -> str:
        digest_source = "|".join(
            [
                create_dept_id,
                start_time,
                end_time,
                str(check_standard_count),
                str(check_standard_item_count),
            ]
        )
        digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:16]
        safe_dept = re.sub(r"[^A-Za-z0-9._-]+", "-", create_dept_id).strip("-") or "DEPT"
        return f"INSPECTION-STD-{safe_dept}-{digest}"[:255]

    @staticmethod
    def _write_temp_xlsx(content: bytes) -> str:
        fd, path = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        with open(path, "wb") as handle:
            handle.write(content)
        return path

    @staticmethod
    def _safe_unlink(path: str) -> None:
        try:
            os.unlink(path)
        except OSError:
            pass
