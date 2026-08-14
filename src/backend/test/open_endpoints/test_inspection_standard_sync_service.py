from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.inspection_standard_sync import (
    InspectionStandardSyncCreateDeptIdError,
    InspectionStandardSyncEmptyDataError,
    InspectionStandardSyncRelationError,
    InspectionStandardSyncTokenRuleError,
)
from bisheng.developer_token.domain.schemas import DeveloperTokenFileSyncRule
from bisheng.open_endpoints.domain.schemas.filelib_sync import FilelibSyncResponseData
from bisheng.open_endpoints.domain.schemas.inspection_standard_sync import (
    InspectionStandardItemRecord,
    InspectionStandardRecord,
    InspectionStandardSyncData,
    InspectionStandardSyncRequest,
)
from bisheng.open_endpoints.domain.services.inspection_standard_sync_service import (
    InspectionStandardSyncService,
)


def _fixed_rule(**target_overrides) -> DeveloperTokenFileSyncRule:
    target_space = {
        "mode": "fixed",
        "knowledge_id": 118,
        "folder_path": "点检标准",
        "dynamic_source": None,
    }
    target_space.update(target_overrides)
    return DeveloperTokenFileSyncRule.model_validate(
        {
            "category": {"code": "REPORT", "subcategory_code": "INSPECTION_STD"},
            "business_domain": {"mode": "fixed", "code": "MANUFACTURE", "dynamic_source": None},
            "target_space": target_space,
        }
    )


def _sample_standard(**overrides) -> InspectionStandardRecord:
    payload = {
        "CREATE_DEPT_ID": "DEPT-A",
        "CHECK_STANDARD_ID": "270101J01D01",
        "DEVICE_NAME": "调度大厅",
        "STANDARD_TYPE": "01-常规点检",
        "CHECK_ITEM_NAME": "调度操作台综合检查",
        "DEVICE_STATUS": "1-运转",
        "ENFORCE_CODE": "1-点检",
        "SAFETY_BOARD": "N-否",
        "CHECK_PERIOD": 1,
        "PERIOD_UNIT": "W-周",
        "INTERFACE_SYSTEM": "1-智能点检系统",
        "NEXT_SCHE_DATE": "2026-05-06",
        "MAINTAIN_REASON": "初始建立",
        "DEVICE_MAINTAIN_JOB_ID": "JOB001",
        "REC_CREATOR": "E001",
        "REC_CREATOR_NAME": "张三",
    }
    payload.update(overrides)
    return InspectionStandardRecord.model_validate(payload)


def _sample_item(**overrides) -> InspectionStandardItemRecord:
    payload = {
        "CHECK_STANDARD_ID": "270101J01D01",
        "CHECK_STANDARD_SEQ_NO": "001",
        "CONTENT": "操作按钮、手柄灵活性及定位",
        "CHECK_WAY": "1-五感",
        "LUBRIC_WAY": "0-无",
        "MANAGE_CONTROL_MODE": "0-无",
        "DATA_TYPE": "10-定性",
        "CRITERI": "灵活方便，定位可靠（GB 20905）",
        "STATUTORY_REQ": "0-无",
    }
    payload.update(overrides)
    return InspectionStandardItemRecord.model_validate(payload)


def _request(**overrides) -> InspectionStandardSyncRequest:
    payload = {
        "start_time": "2026-08-01T00:00:00",
        "end_time": "2026-08-14T23:59:59",
        "data": {
            "check_standards": [_sample_standard()],
            "check_standard_items": [_sample_item()],
        },
    }
    payload.update(overrides)
    return InspectionStandardSyncRequest.model_validate(payload)


def _build_service(*, rule: DeveloperTokenFileSyncRule | None = None) -> InspectionStandardSyncService:
    filelib_sync_service = SimpleNamespace(
        file_sync_rule=rule or _fixed_rule(),
        knowledge_space_service=SimpleNamespace(
            find_or_create_folder_path_for_file_sync=AsyncMock(
                return_value=SimpleNamespace(id=9001),
            ),
            find_or_create_folder_for_file_sync=AsyncMock(
                return_value=SimpleNamespace(id=9002),
            ),
        ),
        sync_from_staged_file=AsyncMock(
            return_value=FilelibSyncResponseData(
                external_file_id="INSPECTION-STD-DEPT-A-abc",
                file_id=456,
                file_encoding="ENC-001",
                knowledge_id=118,
                knowledge_name="智能制造室(制造)",
                status=5,
            )
        ),
    )
    return InspectionStandardSyncService(filelib_sync_service=filelib_sync_service)


@pytest.mark.asyncio
async def test_sync_builds_single_group_file():
    service = _build_service()
    result = await service.sync(_request())

    assert result.group_count == 1
    assert len(result.files) == 1
    assert result.files[0].create_dept_id == "DEPT-A"
    assert result.files[0].folder_path == "点检标准/DEPT-A"
    assert result.files[0].generated_file_name == "2026-08-01T00-00-00-2026-08-14T23-59-59.xlsx"
    service.filelib_sync_service.sync_from_staged_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_sync_builds_multiple_groups():
    service = _build_service()
    request = _request(
        data=InspectionStandardSyncData(
            check_standards=[
                _sample_standard(CREATE_DEPT_ID="DEPT-A", CHECK_STANDARD_ID="STD-A"),
                _sample_standard(
                    CREATE_DEPT_ID="DEPT-B",
                    CHECK_STANDARD_ID="STD-B",
                    DEVICE_NAME="核心机房",
                ),
            ],
            check_standard_items=[
                _sample_item(CHECK_STANDARD_ID="STD-A"),
                _sample_item(CHECK_STANDARD_ID="STD-B", CONTENT="机房温度"),
            ],
        )
    )

    result = await service.sync(request)

    assert result.group_count == 2
    assert {item.create_dept_id for item in result.files} == {"DEPT-A", "DEPT-B"}
    assert service.filelib_sync_service.sync_from_staged_file.await_count == 2


def test_build_groups_rejects_orphan_item():
    service = _build_service()
    request = _request(
        data=InspectionStandardSyncData(
            check_standards=[_sample_standard()],
            check_standard_items=[_sample_item(CHECK_STANDARD_ID="UNKNOWN")],
        )
    )

    with pytest.raises(InspectionStandardSyncRelationError):
        service._build_groups(request)


def test_build_groups_rejects_empty_group_items():
    service = _build_service()
    request = _request(
        data=InspectionStandardSyncData(
            check_standards=[
                _sample_standard(CREATE_DEPT_ID="DEPT-A", CHECK_STANDARD_ID="STD-A"),
                _sample_standard(CREATE_DEPT_ID="DEPT-B", CHECK_STANDARD_ID="STD-B"),
            ],
            check_standard_items=[_sample_item(CHECK_STANDARD_ID="STD-A")],
        )
    )

    with pytest.raises(InspectionStandardSyncEmptyDataError):
        service._build_groups(request)


def test_validate_token_rule_rejects_dynamic_target_space():
    service = _build_service(
        rule=DeveloperTokenFileSyncRule.model_validate(
            {
                "category": {"code": "REPORT", "subcategory_code": "INSPECTION_STD"},
                "business_domain": {"mode": "fixed", "code": "MANUFACTURE", "dynamic_source": None},
                "target_space": {
                    "mode": "dynamic",
                    "knowledge_id": None,
                    "dynamic_source": "department_id",
                },
            }
        )
    )

    with pytest.raises(InspectionStandardSyncTokenRuleError):
        service._validate_token_rule(service.filelib_sync_service.file_sync_rule)


def test_validate_create_dept_id_rejects_path_separator():
    with pytest.raises(InspectionStandardSyncCreateDeptIdError):
        InspectionStandardSyncService._validate_create_dept_id("DEPT/A")
