"""Generate large inspection-standard sync payloads for benchmarks and tests."""

from __future__ import annotations

DEFAULT_DEPT_COUNT = 10
DEFAULT_RECORDS_PER_DEPT = 10_000


def build_standard_dict(*, create_dept_id: str, check_standard_id: str, record_idx: int) -> dict:
    suffix = str(record_idx % 10_000).zfill(4)
    return {
        "CREATE_DEPT_ID": create_dept_id,
        "CHECK_STANDARD_ID": check_standard_id,
        "DEVICE_NAME": f"设备-{create_dept_id}-{suffix}",
        "STANDARD_TYPE": "01-常规点检",
        "CHECK_ITEM_NAME": f"点检项目-{suffix}",
        "DEVICE_STATUS": "1-运转",
        "ENFORCE_CODE": "1-点检",
        "SAFETY_BOARD": "N-否",
        "CHECK_PERIOD": 1,
        "PERIOD_UNIT": "W-周",
        "INTERFACE_SYSTEM": "1-智能点检系统",
        "NEXT_SCHE_DATE": "2026-08-10",
        "MAINTAIN_REASON": "初始建立",
        "DEVICE_MAINTAIN_JOB_ID": f"J{suffix}",
        "REC_CREATOR": f"E{suffix}",
        "REC_CREATOR_NAME": f"用户{suffix}",
    }


def build_item_dict(*, check_standard_id: str) -> dict:
    return {
        "CHECK_STANDARD_ID": check_standard_id,
        "CHECK_STANDARD_SEQ_NO": "001",
        "CONTENT": "电机温度运行",
        "CHECK_WAY": "1-五感",
        "LUBRIC_WAY": "0-无",
        "MANAGE_CONTROL_MODE": "0-无",
        "DATA_TYPE": "10-定性",
        "CRITERI": "运转平稳无杂音",
        "STATUTORY_REQ": "0-无",
    }


def build_check_standard_id(dept_idx: int, record_idx: int) -> str:
    return f"{dept_idx}{record_idx:09d}"


def build_create_dept_id(dept_idx: int) -> str:
    return f"DEPT-{dept_idx:02d}"


def build_bulk_payload_dict(
    *,
    dept_count: int = DEFAULT_DEPT_COUNT,
    records_per_dept: int = DEFAULT_RECORDS_PER_DEPT,
    dept_indices: list[int] | None = None,
    start_time: str = "2026-08-01T00:00:00",
    end_time: str = "2026-08-14T23:59:59",
) -> dict:
    if dept_indices is None:
        dept_indices = list(range(dept_count))

    check_standards: list[dict] = []
    check_standard_items: list[dict] = []
    for dept_idx in dept_indices:
        create_dept_id = build_create_dept_id(dept_idx)
        for record_idx in range(records_per_dept):
            standard_id = build_check_standard_id(dept_idx, record_idx)
            check_standards.append(
                build_standard_dict(
                    create_dept_id=create_dept_id,
                    check_standard_id=standard_id,
                    record_idx=record_idx,
                )
            )
            check_standard_items.append(build_item_dict(check_standard_id=standard_id))

    return {
        "start_time": start_time,
        "end_time": end_time,
        "data": {
            "check_standards": check_standards,
            "check_standard_items": check_standard_items,
        },
    }
