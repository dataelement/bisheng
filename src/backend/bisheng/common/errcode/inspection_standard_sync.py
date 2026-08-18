from __future__ import annotations

from bisheng.common.errcode.filelib_sync import FilelibSyncError


class InspectionStandardSyncError(FilelibSyncError):
    pass


class InspectionStandardSyncInvalidTimeError(InspectionStandardSyncError):
    Code: int = 19910
    Msg: str = "inspection_standard_sync_invalid_time"
    HttpStatus: int = 400


class InspectionStandardSyncFieldValidationError(InspectionStandardSyncError):
    Code: int = 19911
    Msg: str = "inspection_standard_sync_field_validation_failed"
    HttpStatus: int = 400


class InspectionStandardSyncRelationError(InspectionStandardSyncError):
    Code: int = 19912
    Msg: str = "inspection_standard_sync_relation_failed"
    HttpStatus: int = 400


class InspectionStandardSyncExcelBuildError(InspectionStandardSyncError):
    Code: int = 19913
    Msg: str = "inspection_standard_sync_excel_build_failed"
    HttpStatus: int = 400


class InspectionStandardSyncEmptyDataError(InspectionStandardSyncError):
    Code: int = 19914
    Msg: str = "inspection_standard_sync_empty_data"
    HttpStatus: int = 422


class InspectionStandardSyncTokenRuleError(InspectionStandardSyncError):
    Code: int = 19915
    Msg: str = "inspection_standard_sync_token_rule_invalid"
    HttpStatus: int = 403


class InspectionStandardSyncCreateDeptIdError(InspectionStandardSyncError):
    Code: int = 19916
    Msg: str = "inspection_standard_sync_create_dept_id_invalid"
    HttpStatus: int = 400
