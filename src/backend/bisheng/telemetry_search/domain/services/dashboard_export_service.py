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
from bisheng.common.errcode.telemetry import (
    DashboardExportEmptyError,
    DashboardExportLimitExceededError,
    DashboardExportPivotViewInvalidError,
)
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.utils import generate_uuid

from ..schemas.component import ComponentDataConfig, DimensionQueryFilter, PivotSheet, TimeFilter
from .dashboard import DashboardService
from .dashboard_export_detail import DetailRows, query_detail_rows
from .department_label_resolver import relabel_organization_rows

EXPORT_ROW_LIMIT_PER_SHEET = 50_000
# 画面最多 500 行数据加 100 列. 分组小计最多再占一倍, 再加表头, 合计和提示行.
# 超过这个网格说明请求不是当前画面, 不能当成一份完整导出.
_MAX_PIVOT_SHEET_ROWS = 1_100
_MAX_PIVOT_SHEET_COLUMNS = 120
_PIVOT_SHEET_NAME = "交叉表"
_DETAIL_SHEET_NAME = "明细"
_PIVOT_COMPONENT_TYPE = "pivot-table"
_INVALID_SHEET_NAME_CHARS = re.compile(r"[:\\/?*\[\]]")


def _sanitize_sheet_name(name: str) -> str:
    name = _INVALID_SHEET_NAME_CHARS.sub("_", str(name)).strip() or "Sheet1"
    return name[:31]


async def _display_detail(detail: DetailRows) -> DetailRows:
    rows = await relabel_organization_rows(detail.rows, [column.field for column in detail.columns])
    return DetailRows(columns=detail.columns, rows=rows)


def _build_dataframe(detail: DetailRows, row_indices: list[int] | None = None) -> pd.DataFrame:
    """One sheet of detail rows, labelled with each column's display name."""
    rows = detail.rows if row_indices is None else [detail.rows[index] for index in row_indices]
    labels = [column.label for column in detail.columns]
    data = [[row.get(column.field) for column in detail.columns] for row in rows]
    return pd.DataFrame(data, columns=labels) if data else pd.DataFrame(columns=labels)


def _validate_pivot_sheet(sheet: PivotSheet) -> None:
    """拒绝不是当前画面规模的网格, 以及无法落成合并单元格的区域."""
    width = max((len(row) for row in sheet.rows), default=0)
    if (
        (sheet.has_table and not sheet.rows)
        or len(sheet.rows) > _MAX_PIVOT_SHEET_ROWS
        or width > _MAX_PIVOT_SHEET_COLUMNS
    ):
        raise DashboardExportPivotViewInvalidError()
    occupied: set[tuple[int, int]] = set()
    for merge in sheet.merges:
        for row_index in range(merge.row, merge.row + merge.row_span):
            for column_index in range(merge.column, merge.column + merge.column_span):
                if row_index >= len(sheet.rows) or column_index >= width or (row_index, column_index) in occupied:
                    raise DashboardExportPivotViewInvalidError()
                occupied.add((row_index, column_index))


def _write_pivot_sheet(workbook, sheet: PivotSheet) -> None:
    """把画面网格写入第一页, 合并区域按画面的 rowspan / colspan."""
    worksheet = workbook.create_sheet(_PIVOT_SHEET_NAME, 0)
    width = max((len(row) for row in sheet.rows), default=0)
    for row_index, row in enumerate(sheet.rows, start=1):
        padded = list(row) + [None] * (width - len(row))
        for column_index, value in enumerate(padded, start=1):
            worksheet.cell(row_index, column_index, value)
    for merge in sheet.merges:
        if merge.row_span == 1 and merge.column_span == 1:
            continue
        worksheet.merge_cells(
            start_row=merge.row + 1,
            start_column=merge.column + 1,
            end_row=merge.row + merge.row_span,
            end_column=merge.column + merge.column_span,
        )


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

        df = _build_dataframe(await _display_detail(detail))
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
        pivot_sheet: PivotSheet | None = None,
    ) -> str:
        """导出整个组件.

        交叉表固定两个工作表: 第一页是调用方传来的当前画面, 第二页是同一筛选下的全部明细.
        其他图表仍按最外层维度把明细拆成多个工作表.

        Args:
            dashboard_id: 看板 id.
            component_id: 组件 id.
            time_filters: 看板上的时间筛选.
            dimension_filters: 看板上的维度筛选.
            pivot_sheet: 交叉表当前画面. 只有交叉表会使用.

        Returns:
            浏览器可打开的导出文件地址.

        Raises:
            DashboardExportEmptyError: 交叉表没有画面数据且明细为空, 或其他图表没有明细.
            DashboardExportLimitExceededError: 明细行数超过上限.
            DashboardExportPivotViewInvalidError: 交叉表缺少画面, 或画面网格无法写入.
        """
        dashboard_service = DashboardService(request=self.request, login_user=self.login_user)
        _dashboard, component = await dashboard_service._authorize_component_access(dashboard_id, component_id)
        is_pivot = getattr(component, "type", None) == _PIVOT_COMPONENT_TYPE
        if is_pivot and pivot_sheet is None:
            raise DashboardExportPivotViewInvalidError()
        if is_pivot and pivot_sheet is not None:
            _validate_pivot_sheet(pivot_sheet)

        data_config = ComponentDataConfig(**component.data_config)
        detail = await query_detail_rows(
            dataset_code=component.dataset_code,
            data_config=data_config,
            time_filters=time_filters,
            dimension_filters=dimension_filters or [],
            row_limit=EXPORT_ROW_LIMIT_PER_SHEET,
        )

        if len(detail.rows) > EXPORT_ROW_LIMIT_PER_SHEET:
            raise DashboardExportLimitExceededError()
        detail = await _display_detail(detail)
        if is_pivot:
            if pivot_sheet is None or (not pivot_sheet.has_table and not detail.rows):
                raise DashboardExportEmptyError()
        elif not detail.rows:
            raise DashboardExportEmptyError()

        bio = BytesIO()
        with pd.ExcelWriter(bio, engine="openpyxl") as writer:
            if is_pivot and pivot_sheet is not None:
                _write_pivot_sheet(writer.book, pivot_sheet)
                _build_dataframe(detail).to_excel(writer, sheet_name=_DETAIL_SHEET_NAME, index=False)
                default_sheet = writer.book["Sheet"] if "Sheet" in writer.book.sheetnames else None
                if default_sheet is not None and default_sheet.title not in {_PIVOT_SHEET_NAME, _DETAIL_SHEET_NAME}:
                    writer.book.remove(default_sheet)
            else:
                # 非交叉表仍按最外层维度分表, 避免一份明细被截断后拆表冒充完整结果.
                group_field = data_config.dimensions[0].field_id if data_config.dimensions else None
                groups: dict[str, list[int]] = {}
                for row_index, row in enumerate(detail.rows):
                    group_key = str(row.get(group_field) or "Sheet1") if group_field else "Sheet1"
                    groups.setdefault(group_key, []).append(row_index)
                if any(len(indices) > EXPORT_ROW_LIMIT_PER_SHEET for indices in groups.values()):
                    raise DashboardExportLimitExceededError()
                used_sheet_names: set[str] = set()
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
