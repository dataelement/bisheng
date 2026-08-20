from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bisheng.open_endpoints.domain.schemas.filelib_sync import FilelibSyncResponseData

MAX_INSPECTION_STANDARD_FIELD_LENGTH = 100


class InspectionStandardRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    CREATE_DEPT_ID: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    CHECK_STANDARD_ID: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    DEVICE_NAME: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    STANDARD_TYPE: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    OIL_PART_NO: str | None = Field(default=None, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    CHECK_ITEM_NAME: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    DEVICE_STATUS: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    ENFORCE_CODE: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    SAFETY_BOARD: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    CHECK_PERIOD: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    PERIOD_UNIT: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    INTERFACE_SYSTEM: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    NEXT_SCHE_DATE: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    MAINTAIN_REASON: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    DEVICE_MAINTAIN_JOB_ID: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    REC_CREATOR: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    REC_CREATOR_NAME: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)

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
    def normalize_text(cls, value: Any) -> Any:
        if value is None:
            return value
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            return value.strip()
        return value


class InspectionStandardItemRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    CHECK_STANDARD_ID: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    CHECK_STANDARD_SEQ_NO: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    CONTENT: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    CHECK_WAY: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    LUBRIC_WAY: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    LUBRIC_POINT: str | None = Field(default=None, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    MANAGE_CONTROL_MODE: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    MANAGE_TYPE: str | None = Field(default=None, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    DATA_TYPE: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    CRITERI: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    UOM: str | None = Field(default=None, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    QLTY_TOP: str | None = Field(default=None, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    QLTY_BOTTOM: str | None = Field(default=None, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    ALARM_SETTINGS: str | None = Field(default=None, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    STATUTORY_REQ: str = Field(min_length=1, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    EQUIPMENT_NAME: str | None = Field(default=None, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    LUBRIC_PART: str | None = Field(default=None, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    DISTRIBUTOR_NO: str | None = Field(default=None, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    ENTRY_OINT_NO: str | None = Field(default=None, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    LUBRIC_POINT_MARK: str | None = Field(default=None, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    NOZZLE_SPECIFICATION: str | None = Field(default=None, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    FUELING_TOOLS: str | None = Field(default=None, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    OIL_NO: str | None = Field(default=None, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    SINGLE_INJECTION_VOLUME: str | None = Field(default=None, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    TOTAL_INJECTION_VOLUME: str | None = Field(default=None, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    LUBRIC_EFFECT_JUDGE_CRITERIA: str | None = Field(default=None, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    TECH_MAJOR_PIC: str | None = Field(default=None, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    RESPONSIBILITY_TEAM: str | None = Field(default=None, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    LUBRIC_PIC: str | None = Field(default=None, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)
    OIL_PROPERTY: str | None = Field(default=None, max_length=MAX_INSPECTION_STANDARD_FIELD_LENGTH)

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
    def normalize_text(cls, value: Any) -> Any:
        if value is None:
            return value
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            return value.strip()
        return value


class InspectionStandardSyncData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_standards: list[InspectionStandardRecord] = Field(min_length=1)
    check_standard_items: list[InspectionStandardItemRecord] = Field(min_length=1)


class InspectionStandardSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_time: str = Field(min_length=1)
    end_time: str = Field(min_length=1)
    data: InspectionStandardSyncData

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
