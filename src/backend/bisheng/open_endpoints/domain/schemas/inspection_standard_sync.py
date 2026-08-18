from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bisheng.open_endpoints.domain.schemas.filelib_sync import FilelibSyncResponseData

CHECK_STANDARD_ID_PATTERN = r"^.{1,12}$"
CHECK_STANDARD_SEQ_NO_PATTERN = r"^\d{1,3}$"
NEXT_SCHE_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


class InspectionStandardRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    CREATE_DEPT_ID: str = Field(min_length=1, max_length=128)
    CHECK_STANDARD_ID: str = Field(min_length=1, max_length=12)
    DEVICE_NAME: str = Field(min_length=1, max_length=100)
    STANDARD_TYPE: str = Field(min_length=1, max_length=32)
    OIL_PART_NO: str | None = Field(default=None, max_length=20)
    CHECK_ITEM_NAME: str = Field(min_length=1, max_length=50)
    DEVICE_STATUS: str = Field(min_length=1, max_length=16)
    ENFORCE_CODE: str = Field(min_length=1, max_length=16)
    SAFETY_BOARD: str = Field(min_length=1, max_length=8)
    CHECK_PERIOD: int
    PERIOD_UNIT: str = Field(min_length=1, max_length=8)
    INTERFACE_SYSTEM: str = Field(min_length=1, max_length=16)
    NEXT_SCHE_DATE: str = Field(min_length=1, max_length=10)
    MAINTAIN_REASON: str = Field(min_length=1, max_length=50)
    DEVICE_MAINTAIN_JOB_ID: str = Field(min_length=1, max_length=10)
    REC_CREATOR: str = Field(min_length=1, max_length=10)
    REC_CREATOR_NAME: str = Field(min_length=1, max_length=10)

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
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("NEXT_SCHE_DATE")
    @classmethod
    def validate_next_sche_date(cls, value: str) -> str:
        import re

        if not re.fullmatch(NEXT_SCHE_DATE_PATTERN, value):
            raise ValueError("NEXT_SCHE_DATE must match YYYY-MM-DD")
        return value


class InspectionStandardItemRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    CHECK_STANDARD_ID: str = Field(min_length=1, max_length=12)
    CHECK_STANDARD_SEQ_NO: str = Field(min_length=1, max_length=3)
    CONTENT: str = Field(min_length=1, max_length=50)
    CHECK_WAY: str = Field(min_length=1, max_length=16)
    LUBRIC_WAY: str = Field(min_length=1, max_length=16)
    LUBRIC_POINT: int | None = None
    MANAGE_CONTROL_MODE: str = Field(min_length=1, max_length=16)
    MANAGE_TYPE: str | None = Field(default=None, max_length=16)
    DATA_TYPE: str = Field(min_length=1, max_length=16)
    CRITERI: str = Field(min_length=1, max_length=100)
    UOM: str | None = Field(default=None, max_length=8)
    QLTY_TOP: float | int | None = None
    QLTY_BOTTOM: float | int | None = None
    ALARM_SETTINGS: str | None = Field(default=None, max_length=100)
    STATUTORY_REQ: str = Field(min_length=1, max_length=16)
    EQUIPMENT_NAME: str | None = Field(default=None, max_length=100)
    LUBRIC_PART: str | None = Field(default=None, max_length=100)
    DISTRIBUTOR_NO: str | None = Field(default=None, max_length=32)
    ENTRY_OINT_NO: str | None = Field(default=None, max_length=32)
    LUBRIC_POINT_MARK: str | None = Field(default=None, max_length=32)
    NOZZLE_SPECIFICATION: str | None = Field(default=None, max_length=32)
    FUELING_TOOLS: str | None = Field(default=None, max_length=32)
    OIL_NO: str | None = Field(default=None, max_length=32)
    SINGLE_INJECTION_VOLUME: str | None = Field(default=None, max_length=32)
    TOTAL_INJECTION_VOLUME: str | None = Field(default=None, max_length=32)
    LUBRIC_EFFECT_JUDGE_CRITERIA: str | None = Field(default=None, max_length=100)
    TECH_MAJOR_PIC: str | None = Field(default=None, max_length=32)
    RESPONSIBILITY_TEAM: str | None = Field(default=None, max_length=32)
    LUBRIC_PIC: str | None = Field(default=None, max_length=32)
    OIL_PROPERTY: str | None = Field(default=None, max_length=16)

    @field_validator(
        "CHECK_STANDARD_ID",
        "CHECK_STANDARD_SEQ_NO",
        "CONTENT",
        "CHECK_WAY",
        "LUBRIC_WAY",
        "MANAGE_CONTROL_MODE",
        "MANAGE_TYPE",
        "DATA_TYPE",
        "CRITERI",
        "UOM",
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
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("CHECK_STANDARD_SEQ_NO")
    @classmethod
    def validate_seq_no(cls, value: str) -> str:
        import re

        if not re.fullmatch(CHECK_STANDARD_SEQ_NO_PATTERN, value):
            raise ValueError("CHECK_STANDARD_SEQ_NO must be 1-3 digits")
        return value.zfill(3)


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
