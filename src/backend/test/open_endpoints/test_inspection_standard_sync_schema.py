from __future__ import annotations

from bisheng.open_endpoints.domain.schemas.inspection_standard_sync import (
    InspectionStandardItemRecord,
    InspectionStandardRecord,
    InspectionStandardSyncRequest,
)


def _minimal_standard_payload(**overrides) -> dict:
    payload = {
        "CREATE_DEPT_ID": "DEPT-A",
        "CHECK_STANDARD_ID": "270101J01D01",
        "DEVICE_NAME": "调度大厅",
        "STANDARD_TYPE": "01-常规点检",
        "CHECK_ITEM_NAME": "调度操作台综合检查",
        "DEVICE_STATUS": "1-运转",
        "ENFORCE_CODE": "1-点检",
        "SAFETY_BOARD": "N-否",
        "CHECK_PERIOD": "1",
        "PERIOD_UNIT": "W-周",
        "INTERFACE_SYSTEM": "1-智能点检系统",
        "NEXT_SCHE_DATE": "2026-05-06",
        "MAINTAIN_REASON": "初始建立",
        "DEVICE_MAINTAIN_JOB_ID": "JOB001",
        "REC_CREATOR": "E001",
        "REC_CREATOR_NAME": "张三",
    }
    payload.update(overrides)
    return payload


def _minimal_item_payload(**overrides) -> dict:
    payload = {
        "CHECK_STANDARD_ID": "270101J01D01",
        "CHECK_STANDARD_SEQ_NO": "001",
        "CONTENT": "操作按钮、手柄灵活性及定位",
        "CHECK_WAY": "1-五感",
        "LUBRIC_WAY": "0-无",
        "MANAGE_CONTROL_MODE": "0-无",
        "DATA_TYPE": "20-定量",
        "CRITERI": "18-27℃",
        "UOM": "℃",
        "QLTY_TOP": "27",
        "QLTY_BOTTOM": "18",
        "STATUTORY_REQ": "0-无",
    }
    payload.update(overrides)
    return payload


def test_standard_record_fields_are_strings():
    record = InspectionStandardRecord.model_validate(_minimal_standard_payload())
    assert record.CHECK_PERIOD == "1"
    assert isinstance(record.CHECK_PERIOD, str)


def test_standard_record_coerces_numeric_check_period():
    record = InspectionStandardRecord.model_validate(
        _minimal_standard_payload(CHECK_PERIOD=1),
    )
    assert record.CHECK_PERIOD == "1"
    assert isinstance(record.CHECK_PERIOD, str)


def test_item_record_fields_are_strings():
    record = InspectionStandardItemRecord.model_validate(_minimal_item_payload())
    assert record.LUBRIC_POINT is None
    assert record.QLTY_TOP == "27"
    assert record.QLTY_BOTTOM == "18"
    assert isinstance(record.QLTY_TOP, str)
    assert isinstance(record.QLTY_BOTTOM, str)


def test_item_record_accepts_free_form_seq_no():
    record = InspectionStandardItemRecord.model_validate(
        _minimal_item_payload(CHECK_STANDARD_SEQ_NO="A01"),
    )
    assert record.CHECK_STANDARD_SEQ_NO == "A01"


def test_standard_record_accepts_free_form_next_sche_date():
    record = InspectionStandardRecord.model_validate(
        _minimal_standard_payload(NEXT_SCHE_DATE="20260506"),
    )
    assert record.NEXT_SCHE_DATE == "20260506"


def test_item_record_coerces_numeric_optional_fields():
    record = InspectionStandardItemRecord.model_validate(
        _minimal_item_payload(
            LUBRIC_POINT=3,
            QLTY_TOP=27.5,
            QLTY_BOTTOM=18,
        ),
    )
    assert record.LUBRIC_POINT == "3"
    assert record.QLTY_TOP == "27.5"
    assert record.QLTY_BOTTOM == "18"