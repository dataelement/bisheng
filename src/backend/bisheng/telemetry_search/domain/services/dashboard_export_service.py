"""F058 AC-09/AC-10: dashboard chart drill-down export and full-chart export.

Access control for both entry points is delegated entirely to
``DashboardService._authorize_component_access`` — the same check the existing
``POST /component/query`` endpoint uses — so export never bypasses a component's
existing visibility rules (see spec.md §7, INV-15).
"""

import re
from io import BytesIO
from typing import Any

import pandas as pd
from fastapi import Request, UploadFile

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.telemetry import DashboardExportEmptyError, DashboardExportLimitExceededError
from bisheng.core.cache.utils import save_uploaded_file
from bisheng.utils import generate_uuid

from ..schemas.component import ComponentDataConfig, DimensionQueryFilter, TimeFilter
from .component import DataQueryService
from .dashboard import DashboardService

EXPORT_ROW_LIMIT_PER_SHEET = 50_000
_INVALID_SHEET_NAME_CHARS = re.compile(r"[:\\/?*\[\]]")


def _column_label(field) -> str:
    return field.display_name or field.field_name or field.field_id


def _sanitize_sheet_name(name: str) -> str:
    name = _INVALID_SHEET_NAME_CHARS.sub("_", str(name)).strip() or "Sheet1"
    return name[:31]


def _build_dataframe(data_config: ComponentDataConfig, dimensions: list[list], values: list[list]) -> pd.DataFrame:
    # DataQueryService.query_telemetry_data() queries data_config.dimensions followed by
    # get_stack_dimensions() (pivot table's 堆叠项/维度) as one combined dimension list —
    # see component.py::query_telemetry_data lines 80-88 — so each result.dimensions row
    # carries both, in that order. The exported columns must match, or pandas raises
    # "N columns passed, passed data had M columns" for any pivot-table component that
    # has a stack dimension configured.
    row_dimension_fields = [*data_config.dimensions, *data_config.get_stack_dimensions()]
    columns = [_column_label(field) for field in row_dimension_fields]
    columns.extend(_column_label(field) for field in data_config.metrics)
    if row_dimension_fields:
        # dimensions/values are index-aligned parallel lists (DataQueryResult contract).
        rows = [
            list(dim_row) + list(value_row) for dim_row, value_row in zip(dimensions, values, strict=True)
        ]
    else:
        # No dimensions configured: sort_metrics() leaves `dimensions` permanently empty in
        # this case (see component.py::sort_metrics), so `values` alone carries the rows.
        rows = [list(value_row) for value_row in values]
    return pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)


async def _upload_excel(bio: BytesIO, file_name: str) -> str:
    bio.seek(0)
    upload = UploadFile(filename=file_name, file=bio)
    try:
        return await save_uploaded_file(upload, "bisheng", file_name)
    finally:
        await upload.close()


class DashboardExportService:
    def __init__(self, request: Request, login_user: UserPayload):
        self.request = request
        self.login_user = login_user

    async def export_component_detail(
        self,
        dashboard_id: int,
        component_id: str,
        dimension_field: str,
        dimension_value: Any,
        time_filters: list[TimeFilter] | None = None,
        dimension_filters: list[DimensionQueryFilter] | None = None,
    ) -> str:
        """AC-09: export the detail rows for one clicked chart category."""
        dashboard_service = DashboardService(request=self.request, login_user=self.login_user)
        _dashboard, component = await dashboard_service._authorize_component_access(dashboard_id, component_id)

        data_config = ComponentDataConfig(**component.data_config)
        merged_filters = [*(dimension_filters or [])]
        merged_filters.append(DimensionQueryFilter(fieldId=dimension_field, values=[dimension_value]))

        result = await DataQueryService(
            dataset_code=component.dataset_code,
            data_config=data_config,
            time_filters=time_filters,
            dimension_filters=merged_filters,
        ).query_telemetry_data()

        if not result.dimensions and not result.value:
            raise DashboardExportEmptyError()
        if len(result.dimensions or result.value) > EXPORT_ROW_LIMIT_PER_SHEET:
            raise DashboardExportLimitExceededError()

        df = _build_dataframe(data_config, result.dimensions, result.value)
        bio = BytesIO()
        with pd.ExcelWriter(bio, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Sheet1", index=False)
        return await _upload_excel(bio, f"dashboard_export_{generate_uuid()}.xlsx")

    async def export_component_all(
        self,
        dashboard_id: int,
        component_id: str,
        time_filters: list[TimeFilter] | None = None,
        dimension_filters: list[DimensionQueryFilter] | None = None,
    ) -> str:
        """AC-10: export the whole chart, one sheet per outermost dimension value."""
        dashboard_service = DashboardService(request=self.request, login_user=self.login_user)
        _dashboard, component = await dashboard_service._authorize_component_access(dashboard_id, component_id)

        data_config = ComponentDataConfig(**component.data_config)
        result = await DataQueryService(
            dataset_code=component.dataset_code,
            data_config=data_config,
            time_filters=time_filters,
            dimension_filters=dimension_filters or [],
        ).query_telemetry_data()

        if not result.dimensions and not result.value:
            raise DashboardExportEmptyError()

        groups: dict[str, list[int]] = {}
        if data_config.dimensions:
            for row_index, dim_row in enumerate(result.dimensions):
                group_key = str(dim_row[0]) if dim_row else "Sheet1"
                groups.setdefault(group_key, []).append(row_index)
        else:
            groups["Sheet1"] = list(range(len(result.value)))

        if any(len(indices) > EXPORT_ROW_LIMIT_PER_SHEET for indices in groups.values()):
            raise DashboardExportLimitExceededError()

        bio = BytesIO()
        used_sheet_names: set[str] = set()
        with pd.ExcelWriter(bio, engine="openpyxl") as writer:
            for group_key, indices in groups.items():
                # result.dimensions stays permanently empty (not per-row) when no
                # dimensions are configured — see _build_dataframe's docstring note.
                group_dimensions = [result.dimensions[i] for i in indices] if data_config.dimensions else []
                group_values = [result.value[i] for i in indices]
                df = _build_dataframe(data_config, group_dimensions, group_values)
                sheet_name = _sanitize_sheet_name(group_key)
                suffix = 1
                base_name = sheet_name
                while sheet_name in used_sheet_names:
                    suffix += 1
                    sheet_name = _sanitize_sheet_name(f"{base_name}_{suffix}")
                used_sheet_names.add(sheet_name)
                df.to_excel(writer, sheet_name=sheet_name, index=False)
        return await _upload_excel(bio, f"dashboard_export_{generate_uuid()}.xlsx")
