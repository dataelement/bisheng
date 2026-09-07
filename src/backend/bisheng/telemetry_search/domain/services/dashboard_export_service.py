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
from fastapi import Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.telemetry import DashboardExportEmptyError, DashboardExportLimitExceededError
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.utils import generate_uuid

from ..schemas.component import ComponentDataConfig, DimensionQueryFilter, TimeFilter
from .dashboard import DashboardService
from .dashboard_export_detail import DetailRows, query_detail_rows

EXPORT_ROW_LIMIT_PER_SHEET = 50_000
_INVALID_SHEET_NAME_CHARS = re.compile(r"[:\\/?*\[\]]")


def _sanitize_sheet_name(name: str) -> str:
    name = _INVALID_SHEET_NAME_CHARS.sub("_", str(name)).strip() or "Sheet1"
    return name[:31]


def _build_dataframe(detail: DetailRows, row_indices: list[int] | None = None) -> pd.DataFrame:
    """One sheet of detail rows, labelled with each column's display name."""
    rows = detail.rows if row_indices is None else [detail.rows[index] for index in row_indices]
    labels = [column.label for column in detail.columns]
    data = [[row.get(column.field) for column in detail.columns] for row in rows]
    return pd.DataFrame(data, columns=labels) if data else pd.DataFrame(columns=labels)


async def _upload_excel(bio: BytesIO, file_name: str) -> str:
    # `save_uploaded_file` (used elsewhere for cache-scoped uploads) hardcodes
    # get_share_link(clear_host=False), which keeps the internal-only "minio:9000" host in
    # the returned URL — unreachable from the browser. Upload directly and ask for the
    # nginx-proxied, browser-reachable link instead (clear_host=True is the client's
    # default — see minio_storage.py::get_share_link's docstring — matching the working
    # pattern in api/v1/evaluation.py::get_download_url).
    bio.seek(0)
    minio_client = await get_minio_storage()
    try:
        await minio_client.put_object_tmp(
            object_name=file_name,
            file=bio,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        return await minio_client.get_share_link(file_name, minio_client.tmp_bucket)
    finally:
        bio.close()


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
        """AC-09: export the records behind one clicked chart category."""
        dashboard_service = DashboardService(request=self.request, login_user=self.login_user)
        _dashboard, component = await dashboard_service._authorize_component_access(dashboard_id, component_id)

        data_config = ComponentDataConfig(**component.data_config)
        merged_filters = [*(dimension_filters or [])]
        merged_filters.append(DimensionQueryFilter(fieldId=dimension_field, values=[dimension_value]))

        detail = await query_detail_rows(
            dataset_code=component.dataset_code,
            data_config=data_config,
            time_filters=time_filters,
            dimension_filters=merged_filters,
            row_limit=EXPORT_ROW_LIMIT_PER_SHEET,
        )

        if not detail.rows:
            raise DashboardExportEmptyError()
        if len(detail.rows) > EXPORT_ROW_LIMIT_PER_SHEET:
            raise DashboardExportLimitExceededError()

        df = _build_dataframe(detail)
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
        """AC-10: export every record behind the chart, one sheet per outermost dimension value."""
        dashboard_service = DashboardService(request=self.request, login_user=self.login_user)
        _dashboard, component = await dashboard_service._authorize_component_access(dashboard_id, component_id)

        data_config = ComponentDataConfig(**component.data_config)
        detail = await query_detail_rows(
            dataset_code=component.dataset_code,
            data_config=data_config,
            time_filters=time_filters,
            dimension_filters=dimension_filters or [],
            row_limit=EXPORT_ROW_LIMIT_PER_SHEET,
        )

        if not detail.rows:
            raise DashboardExportEmptyError()

        # Sheets still split on the chart's outermost dimension, so the workbook keeps the
        # same shape as before — only each sheet's contents changed from one aggregated row
        # per category to the records that make up that category.
        group_field = data_config.dimensions[0].field_id if data_config.dimensions else None
        groups: dict[str, list[int]] = {}
        for row_index, row in enumerate(detail.rows):
            group_key = str(row.get(group_field) or "Sheet1") if group_field else "Sheet1"
            groups.setdefault(group_key, []).append(row_index)

        if any(len(indices) > EXPORT_ROW_LIMIT_PER_SHEET for indices in groups.values()):
            raise DashboardExportLimitExceededError()

        bio = BytesIO()
        used_sheet_names: set[str] = set()
        with pd.ExcelWriter(bio, engine="openpyxl") as writer:
            for group_key, indices in groups.items():
                df = _build_dataframe(detail, indices)
                sheet_name = _sanitize_sheet_name(group_key)
                suffix = 1
                base_name = sheet_name
                while sheet_name in used_sheet_names:
                    suffix += 1
                    sheet_name = _sanitize_sheet_name(f"{base_name}_{suffix}")
                used_sheet_names.add(sheet_name)
                df.to_excel(writer, sheet_name=sheet_name, index=False)
        return await _upload_excel(bio, f"dashboard_export_{generate_uuid()}.xlsx")
