from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bisheng.open_endpoints.domain.schemas.filelib_sync import FilelibSyncResponseData

MAX_INSPECTION_STANDARD_FIELD_LENGTH = 1000


def _opt_text(**kwargs: Any) -> Any:
    return Field(default="", min_length=0, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH, **kwargs)


class InspectionStandardRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    CREATE_DEPT_ID: str = _opt_text()
    CHECK_STANDARD_ID: str = _opt_text()
    DEVICE_NAME: str = _opt_text()
    STANDARD_TYPE: str = _opt_text()
    OIL_PART_NO: str = _opt_text()
    CHECK_ITEM_NAME: str = _opt_text()
    DEVICE_STATUS: str = _opt_text()
    ENFORCE_CODE: str = _opt_text()
    SAFETY_BOARD: str = _opt_text()
    CHECK_PERIOD: str = _opt_text()
    PERIOD_UNIT: str = _opt_text()
    INTERFACE_SYSTEM: str = _opt_text()
    NEXT_SCHE_DATE: str = _opt_text()
    MAINTAIN_REASON: str = _opt_text()
    DEVICE_MAINTAIN_JOB_ID: str = _opt_text()
    REC_CREATOR: str = _opt_text()
    REC_CREATOR_NAME: str = _opt_text()

    @field_validator(
        "CREATE_DEPT_ID",
        "CHECK_STANDARD_ID",
        "DEVICE_NAME",
        "STANDARD_TYPE",
        "OIL_PART_NO",
        "CHECK_ITEM_NAME",
        "DEVICE_STATUS",
        "ENFORCE_CODE",
        "SAFETY_BOARD",
        "CHECK_PERIOD",
        "PERIOD_UNIT",
        "INTERFACE_SYSTEM",
        "NEXT_SCHE_DATE",
        "MAINTAIN_REASON",
        "DEVICE_MAINTAIN_JOB_ID",
        "REC_CREATOR",
        "REC_CREATOR_NAME",
        mode="before",
    )
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            return value.strip()
        return str(value)


class InspectionStandardItemRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    CHECK_STANDARD_ID: str = _opt_text()
    CHECK_STANDARD_SEQ_NO: str = _opt_text()
    CONTENT: str = _opt_text()
    CHECK_WAY: str = _opt_text()
    LUBRIC_WAY: str = _opt_text()
    LUBRIC_POINT: str = _opt_text()
    MANAGE_CONTROL_MODE: str = _opt_text()
    MANAGE_TYPE: str = _opt_text()
    DATA_TYPE: str = _opt_text()
    CRITERI: str = _opt_text()
    UOM: str = _opt_text()
    QLTY_TOP: str = _opt_text()
    QLTY_BOTTOM: str = _opt_text()
    ALARM_SETTINGS: str = _opt_text()
    STATUTORY_REQ: str = _opt_text()
    EQUIPMENT_NAME: str = _opt_text()
    LUBRIC_PART: str = _opt_text()
    DISTRIBUTOR_NO: str = _opt_text()
    ENTRY_OINT_NO: str = _opt_text()
    LUBRIC_POINT_MARK: str = _opt_text()
    NOZZLE_SPECIFICATION: str = _opt_text()
    FUELING_TOOLS: str = _opt_text()
    OIL_NO: str = _opt_text()
    SINGLE_INJECTION_VOLUME: str = _opt_text()
    TOTAL_INJECTION_VOLUME: str = _opt_text()
    LUBRIC_EFFECT_JUDGE_CRITERIA: str = _opt_text()
    TECH_MAJOR_PIC: str = _opt_text()
    RESPONSIBILITY_TEAM: str = _opt_text()
    LUBRIC_PIC: str = _opt_text()
    OIL_PROPERTY: str = _opt_text()

    @field_validator(
        "CHECK_STANDARD_ID",
        "CHECK_STANDARD_SEQ_NO",
        "CONTENT",
        "CHECK_WAY",
        "LUBRIC_WAY",
        "LUBRIC_POINT",
        "MANAGE_CONTROL_MODE",
        "MANAGE_TYPE",
        "DATA_TYPE",
        "CRITERI",
        "UOM",
        "QLTY_TOP",
        "QLTY_BOTTOM",
        "ALARM_SETTINGS",
        "STATUTORY_REQ",
        "EQUIPMENT_NAME",
        "LUBRIC_PART",
        "DISTRIBUTOR_NO",
        "ENTRY_OINT_NO",
        "LUBRIC_POINT_MARK",
        "NOZZLE_SPECIFICATION",
        "FUELING_TOOLS",
        "OIL_NO",
        "SINGLE_INJECTION_VOLUME",
        "TOTAL_INJECTION_VOLUME",
        "LUBRIC_EFFECT_JUDGE_CRITERIA",
        "TECH_MAJOR_PIC",
        "RESPONSIBILITY_TEAM",
        "LUBRIC_PIC",
        "OIL_PROPERTY",
        mode="before",
    )
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            return value.strip()
        return str(value)


class InspectionStandardSyncData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_standards: list[InspectionStandardRecord] = Field(default_factory=list, min_length=0)
    check_standard_items: list[InspectionStandardItemRecord] = Field(default_factory=list, min_length=0)


class InspectionStandardSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_time: str = Field(default="", min_length=0)
    end_time: str = Field(default="", min_length=0)
    data: InspectionStandardSyncData = Field(default_factory=InspectionStandardSyncData)

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def normalize_time(cls, value: Any) -> str:
        return str(value or "").strip()


class InspectionStandardSyncFileResult(BaseModel):
    create_dept_id: str
    external_file_id: str
    file_id: int
    file_encoding: str
    knowledge_id: int
    knowledge_name: str
    folder_path: str
    generated_file_name: str
    status: int
    check_standard_count: int
    check_standard_item_count: int
    version_link_pending: bool = False
    replaced_file_id: int | None = None

    @classmethod
    def from_filelib_sync(
        cls,
        *,
        create_dept_id: str,
        folder_path: str,
        generated_file_name: str,
        check_standard_count: int,
        check_standard_item_count: int,
        sync_result: FilelibSyncResponseData,
    ) -> InspectionStandardSyncFileResult:
        return cls(
            create_dept_id=create_dept_id,
            external_file_id=sync_result.external_file_id,
            file_id=sync_result.file_id,
            file_encoding=sync_result.file_encoding,
            knowledge_id=sync_result.knowledge_id,
            knowledge_name=sync_result.knowledge_name,
            folder_path=folder_path,
            generated_file_name=generated_file_name,
            status=sync_result.status,
            check_standard_count=check_standard_count,
            check_standard_item_count=check_standard_item_count,
            version_link_pending=sync_result.version_link_pending,
            replaced_file_id=sync_result.replaced_file_id,
        )


class InspectionStandardSyncResponseData(BaseModel):
    data_start_time: str
    data_end_time: str
    group_count: int
    files: list[InspectionStandardSyncFileResult]

    @model_validator(mode="after")
    def validate_group_count(self):
        if self.group_count != len(self.files):
            raise ValueError("group_count must match files length")
        return self
