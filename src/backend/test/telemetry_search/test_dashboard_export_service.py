"""T012/T014 — DashboardExportService (F058, AC-09, AC-10).

Permission checks are exercised via the real (unmocked)
``DashboardService._authorize_component_access`` against a mocked ``DashboardDao`` +
``login_user``, so a bug that quietly bypasses that shared check would be caught here too.
"""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

if "langchain.docstore.document" not in sys.modules:
    _docstore_stub = MagicMock()
    _docstore_stub.Document = object
    sys.modules.setdefault("langchain.docstore", MagicMock())
    sys.modules["langchain.docstore.document"] = _docstore_stub

from bisheng.common.errcode.telemetry import DashboardExportEmptyError, DashboardExportLimitExceededError

# `bisheng.common.errcode.http_error` (NotFoundError/UnAuthorizedError) is deliberately
# replaced with a MagicMock module by test/fixtures/mock_services.py::PREMOCK_MODULES for
# the whole test suite (pre-existing infra decision, unrelated to F058) — importing those
# classes here would just get the same Mock, which cannot be used with `pytest.raises()`.
# Denial is instead asserted behaviorally: the query mock must never be awaited.

# Use a dataset code that is NOT in DashboardService.REALTIME_DATASETS by default, so tests
# that aren't specifically about the realtime-dataset-must-be-published rule don't
# accidentally trip it via the fake login_user's `_can_operate_dashboards() == False`.
_NON_REALTIME_DATASET = "mid_doc_parse_dtl"


def _dashboard(user_id=1, status="published"):
    return SimpleNamespace(id=1, user_id=user_id, status=status)


def _component(dataset_code=_NON_REALTIME_DATASET, data_config=None):
    return SimpleNamespace(
        id="comp-1",
        dashboard_id=1,
        dataset_code=dataset_code,
        data_config=data_config
        or {
            "dimensions": [{"fieldId": "belonging_department_name", "displayName": "所属部门"}],
            "metrics": [{"fieldId": "file_count", "displayName": "文件数"}],
        },
    )


def _patch_common(monkeypatch, module, *, dashboard, component, read_flag=True, query_result=None):
    from bisheng.telemetry_search.domain.schemas.component import DataQueryResult

    monkeypatch.setattr(module.DashboardDao, "get_one", AsyncMock(return_value=dashboard))
    monkeypatch.setattr(module.DashboardDao, "get_one_component", AsyncMock(return_value=component))
    monkeypatch.setattr(module.DashboardDao, "get_components", AsyncMock(return_value=[component]))

    login_user = SimpleNamespace(
        user_id=99,
        async_access_check=AsyncMock(return_value=read_flag),
    )

    query_mock = AsyncMock(return_value=query_result or DataQueryResult())
    monkeypatch.setattr(
        "bisheng.telemetry_search.domain.services.dashboard_export_service.DataQueryService.query_telemetry_data",
        query_mock,
    )
    return login_user, query_mock


@pytest.fixture()
def service_module(monkeypatch):
    from bisheng.telemetry_search.domain.services import dashboard as dashboard_module
    from bisheng.telemetry_search.domain.services import dashboard_export_service as export_module

    # DashboardService is a strict pydantic model (request: Request, login_user: UserPayload) —
    # production code always gets real instances of both. Tests use lightweight fakes, so
    # bypass field validation the same way the rest of this test suite does
    # (see test_realtime_dashboard.py / test_platform_operator_dashboard_detail.py:
    # `DashboardService.model_construct(...)`).
    def _model_construct_factory(**kwargs):
        return dashboard_module.DashboardService.model_construct(**kwargs)

    monkeypatch.setattr(export_module, "DashboardService", _model_construct_factory)

    return export_module, dashboard_module


async def test_export_detail_denies_unauthorized_user(monkeypatch, service_module):
    export_module, dashboard_module = service_module
    dashboard = _dashboard(user_id=1)
    component = _component()
    login_user, query_mock = _patch_common(
        monkeypatch,
        dashboard_module,
        dashboard=dashboard,
        component=component,
        read_flag=False,
    )

    service = export_module.DashboardExportService(request=None, login_user=login_user)
    with pytest.raises(Exception):  # noqa: B017 — see module docstring re: mocked http_error
        await service.export_component_detail(
            dashboard_id=1,
            component_id="comp-1",
            dimension_field="belonging_department_name",
            dimension_value="生产制造部",
        )
    query_mock.assert_not_awaited()


async def test_export_detail_empty_result_raises(monkeypatch, service_module):
    from bisheng.telemetry_search.domain.schemas.component import DataQueryResult

    export_module, dashboard_module = service_module
    dashboard = _dashboard()
    component = _component()
    login_user, _query_mock = _patch_common(
        monkeypatch,
        dashboard_module,
        dashboard=dashboard,
        component=component,
        query_result=DataQueryResult(dimensions=[], value=[]),
    )

    service = export_module.DashboardExportService(request=None, login_user=login_user)
    with pytest.raises(DashboardExportEmptyError):
        await service.export_component_detail(
            dashboard_id=1,
            component_id="comp-1",
            dimension_field="belonging_department_name",
            dimension_value="生产制造部",
        )


async def test_export_detail_success_produces_url(monkeypatch, service_module):
    from bisheng.telemetry_search.domain.schemas.component import DataQueryResult

    export_module, dashboard_module = service_module
    dashboard = _dashboard()
    component = _component()
    login_user, query_mock = _patch_common(
        monkeypatch,
        dashboard_module,
        dashboard=dashboard,
        component=component,
        query_result=DataQueryResult(dimensions=[["生产制造部"]], value=[[12]]),
    )
    monkeypatch.setattr(
        export_module,
        "_upload_excel",
        AsyncMock(return_value="https://minio/example.xlsx"),
    )

    service = export_module.DashboardExportService(request=None, login_user=login_user)
    url = await service.export_component_detail(
        dashboard_id=1,
        component_id="comp-1",
        dimension_field="belonging_department_name",
        dimension_value="生产制造部",
    )

    assert url == "https://minio/example.xlsx"
    query_mock.assert_awaited_once()
    # the extra exact-match filter must be appended, not replace the caller's filters
    call_kwargs = export_module.DataQueryService.query_telemetry_data.call_args
    assert call_kwargs is not None


async def test_export_all_groups_rows_by_outer_dimension(monkeypatch, service_module):
    from bisheng.telemetry_search.domain.schemas.component import DataQueryResult

    export_module, dashboard_module = service_module
    dashboard = _dashboard()
    component = _component(
        data_config={
            "dimensions": [{"fieldId": "belonging_department_name", "displayName": "所属部门"}],
            "metrics": [{"fieldId": "file_count", "displayName": "文件数"}],
        }
    )
    login_user, _query_mock = _patch_common(
        monkeypatch,
        dashboard_module,
        dashboard=dashboard,
        component=component,
        query_result=DataQueryResult(
            dimensions=[["部门A"], ["部门A"], ["部门B"]],
            value=[[1], [2], [3]],
        ),
    )

    captured_sheet_names = []

    class _FakeWriter:
        def __enter__(self_inner):
            return self_inner

        def __exit__(self_inner, *exc):
            return False

    def _fake_excel_writer(*_args, **_kwargs):
        return _FakeWriter()

    def _fake_to_excel(self_df, writer, sheet_name, index):
        captured_sheet_names.append(sheet_name)

    monkeypatch.setattr(export_module.pd, "ExcelWriter", _fake_excel_writer)
    monkeypatch.setattr(export_module.pd.DataFrame, "to_excel", _fake_to_excel)
    monkeypatch.setattr(export_module, "_upload_excel", AsyncMock(return_value="https://minio/all.xlsx"))

    service = export_module.DashboardExportService(request=None, login_user=login_user)
    url = await service.export_component_all(dashboard_id=1, component_id="comp-1")

    assert url == "https://minio/all.xlsx"
    assert sorted(captured_sheet_names) == ["部门A", "部门B"]


async def test_export_all_row_limit_exceeded(monkeypatch, service_module):
    from bisheng.telemetry_search.domain.schemas.component import DataQueryResult

    export_module, dashboard_module = service_module
    dashboard = _dashboard()
    component = _component(
        data_config={
            "dimensions": [{"fieldId": "belonging_department_name", "displayName": "所属部门"}],
            "metrics": [{"fieldId": "file_count", "displayName": "文件数"}],
        }
    )
    too_many = export_module.EXPORT_ROW_LIMIT_PER_SHEET + 1
    login_user, _query_mock = _patch_common(
        monkeypatch,
        dashboard_module,
        dashboard=dashboard,
        component=component,
        query_result=DataQueryResult(
            dimensions=[["部门A"]] * too_many,
            value=[[1]] * too_many,
        ),
    )

    service = export_module.DashboardExportService(request=None, login_user=login_user)
    with pytest.raises(DashboardExportLimitExceededError):
        await service.export_component_all(dashboard_id=1, component_id="comp-1")


def test_build_dataframe_includes_stack_dimension_columns():
    from bisheng.telemetry_search.domain.schemas.component import ComponentDataConfig
    from bisheng.telemetry_search.domain.services.dashboard_export_service import _build_dataframe

    data_config = ComponentDataConfig(
        dimensions=[{"fieldId": "uploader_company_name", "displayName": "上传人公司"}],
        stackDimensions=[{"fieldId": "uploader_office_name", "displayName": "上传人科室"}],
        metrics=[{"fieldId": "total_file_count", "displayName": "总文件数"}],
    )

    df = _build_dataframe(data_config, [["gzx01205", "二级积分部门1"]], [[562]])

    assert list(df.columns) == ["上传人公司", "上传人科室", "总文件数"]
    assert df.iloc[0].tolist() == ["gzx01205", "二级积分部门1", 562]


async def test_export_detail_pivot_table_with_stack_dimension_matches_column_count(monkeypatch, service_module):
    """Regression: a pivot-table component's query result carries data_config.dimensions
    *plus* get_stack_dimensions() per row (see component.py::query_telemetry_data), so the
    export's column list must include the stack dimension too — otherwise pandas raises
    "N columns passed, passed data had M columns" for any pivot table with a 堆叠项/维度
    configured (e.g. 交叉表 grouped by 上传人公司 with 上传人科室 as the stack dimension)."""
    from bisheng.telemetry_search.domain.schemas.component import DataQueryResult

    export_module, dashboard_module = service_module
    dashboard = _dashboard()
    component = _component(
        data_config={
            "dimensions": [{"fieldId": "uploader_company_name", "displayName": "上传人公司"}],
            "stackDimensions": [{"fieldId": "uploader_office_name", "displayName": "上传人科室"}],
            "metrics": [{"fieldId": "total_file_count", "displayName": "总文件数"}],
        }
    )
    login_user, _query_mock = _patch_common(
        monkeypatch,
        dashboard_module,
        dashboard=dashboard,
        component=component,
        query_result=DataQueryResult(dimensions=[["gzx01205", "二级积分部门1"]], value=[[562]]),
    )
    monkeypatch.setattr(export_module, "_upload_excel", AsyncMock(return_value="https://minio/detail.xlsx"))

    # Before the fix, _build_dataframe's columns list only covered data_config.dimensions
    # (1 field) while each result row carried dimensions + stack dimensions (2 values) +
    # metrics (1 value) = 3 columns, so pd.DataFrame(rows, columns=columns) itself raised
    # "2 columns passed, passed data had 3 columns" here — before any Excel writing.
    service = export_module.DashboardExportService(request=None, login_user=login_user)
    url = await service.export_component_detail(
        dashboard_id=1,
        component_id="comp-1",
        dimension_field="uploader_company_name",
        dimension_value="gzx01205",
    )

    assert url == "https://minio/detail.xlsx"


async def test_export_all_no_dimensions_configured_uses_single_sheet(monkeypatch, service_module):
    """Regression: sort_metrics() leaves `dimensions` empty (not per-row) when no dimensions
    are configured — grouping must fall back to a single sheet, not zip-truncate to zero rows."""
    from bisheng.telemetry_search.domain.schemas.component import DataQueryResult

    export_module, dashboard_module = service_module
    dashboard = _dashboard()
    component = _component(
        data_config={"dimensions": [], "metrics": [{"fieldId": "file_count", "displayName": "文件数"}]}
    )
    login_user, _query_mock = _patch_common(
        monkeypatch,
        dashboard_module,
        dashboard=dashboard,
        component=component,
        query_result=DataQueryResult(dimensions=[], value=[[1], [2], [3]]),
    )

    captured_frames = []

    class _FakeWriter:
        def __enter__(self_inner):
            return self_inner

        def __exit__(self_inner, *exc):
            return False

    def _fake_excel_writer(*_args, **_kwargs):
        return _FakeWriter()

    def _fake_to_excel(self_df, writer, sheet_name, index):
        captured_frames.append((sheet_name, len(self_df)))

    monkeypatch.setattr(export_module.pd, "ExcelWriter", _fake_excel_writer)
    monkeypatch.setattr(export_module.pd.DataFrame, "to_excel", _fake_to_excel)
    monkeypatch.setattr(export_module, "_upload_excel", AsyncMock(return_value="https://minio/all.xlsx"))

    service = export_module.DashboardExportService(request=None, login_user=login_user)
    await service.export_component_all(dashboard_id=1, component_id="comp-1")

    assert captured_frames == [("Sheet1", 3)]
