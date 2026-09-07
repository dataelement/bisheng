"""T012/T014 — DashboardExportService (F058, AC-09, AC-10).

Since the 2026-09-07 change request the export no longer writes the chart's aggregated
numbers — it writes the records behind them (one row per file / per call / per question).
Resolving those records lives in ``dashboard_export_detail`` and is covered by
``test_dashboard_export_detail.py``; this file covers the export service around it:
permissions, empty/limit handling, sheet splitting, and the upload link.

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


def _detail(columns=None, rows=None):
    from bisheng.telemetry_search.domain.services.dashboard_export_detail import DetailColumn, DetailRows

    return DetailRows(
        columns=[DetailColumn(field=field, label=label) for field, label in (columns or [])],
        rows=rows or [],
    )


def _patch_common(monkeypatch, module, *, dashboard, component, read_flag=True, detail=None):
    monkeypatch.setattr(module.DashboardDao, "get_one", AsyncMock(return_value=dashboard))
    monkeypatch.setattr(module.DashboardDao, "get_one_component", AsyncMock(return_value=component))
    monkeypatch.setattr(module.DashboardDao, "get_components", AsyncMock(return_value=[component]))

    login_user = SimpleNamespace(
        user_id=99,
        async_access_check=AsyncMock(return_value=read_flag),
    )

    query_mock = AsyncMock(return_value=detail if detail is not None else _detail())
    monkeypatch.setattr(
        "bisheng.telemetry_search.domain.services.dashboard_export_service.query_detail_rows",
        query_mock,
    )
    return login_user, query_mock


class _FakeWriter:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


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
    login_user, query_mock = _patch_common(
        monkeypatch,
        dashboard_module,
        dashboard=_dashboard(user_id=1),
        component=_component(),
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
    export_module, dashboard_module = service_module
    login_user, _query_mock = _patch_common(
        monkeypatch,
        dashboard_module,
        dashboard=_dashboard(),
        component=_component(),
        detail=_detail(),
    )

    service = export_module.DashboardExportService(request=None, login_user=login_user)
    with pytest.raises(DashboardExportEmptyError):
        await service.export_component_detail(
            dashboard_id=1,
            component_id="comp-1",
            dimension_field="belonging_department_name",
            dimension_value="生产制造部",
        )


async def test_export_detail_writes_one_row_per_record(monkeypatch, service_module):
    """The 2026-09-07 ask: a 文件数 chart's export lists the files, not the count."""
    export_module, dashboard_module = service_module
    detail = _detail(
        columns=[("file_name", "文件名"), ("belonging_department_name", "所属部门")],
        rows=[
            {"file_name": "冷轧带钢.pdf", "belonging_department_name": "生产制造部"},
            {"file_name": "年度报告.pdf", "belonging_department_name": "生产制造部"},
        ],
    )
    login_user, query_mock = _patch_common(
        monkeypatch,
        dashboard_module,
        dashboard=_dashboard(),
        component=_component(),
        detail=detail,
    )

    captured: list = []
    monkeypatch.setattr(export_module.pd, "ExcelWriter", lambda *_a, **_k: _FakeWriter())
    monkeypatch.setattr(
        export_module.pd.DataFrame,
        "to_excel",
        lambda self_df, writer, sheet_name, index: captured.append(
            (list(self_df.columns), self_df.values.tolist())
        ),
    )
    monkeypatch.setattr(export_module, "_upload_excel", AsyncMock(return_value="https://minio/detail.xlsx"))

    service = export_module.DashboardExportService(request=None, login_user=login_user)
    url = await service.export_component_detail(
        dashboard_id=1,
        component_id="comp-1",
        dimension_field="belonging_department_name",
        dimension_value="生产制造部",
    )

    assert url == "https://minio/detail.xlsx"
    assert captured == [
        (
            ["文件名", "所属部门"],
            [["冷轧带钢.pdf", "生产制造部"], ["年度报告.pdf", "生产制造部"]],
        )
    ]
    # the clicked category must be appended as an extra filter, not replace the caller's
    assert query_mock.await_args.kwargs["dimension_filters"][-1].field_id == "belonging_department_name"


async def test_export_all_groups_rows_by_outer_dimension(monkeypatch, service_module):
    export_module, dashboard_module = service_module
    detail = _detail(
        columns=[("file_name", "文件名"), ("belonging_department_name", "所属部门")],
        rows=[
            {"file_name": "a.pdf", "belonging_department_name": "部门A"},
            {"file_name": "b.pdf", "belonging_department_name": "部门A"},
            {"file_name": "c.pdf", "belonging_department_name": "部门B"},
        ],
    )
    login_user, _query_mock = _patch_common(
        monkeypatch,
        dashboard_module,
        dashboard=_dashboard(),
        component=_component(),
        detail=detail,
    )

    captured_sheets: list[tuple[str, int]] = []
    monkeypatch.setattr(export_module.pd, "ExcelWriter", lambda *_a, **_k: _FakeWriter())
    monkeypatch.setattr(
        export_module.pd.DataFrame,
        "to_excel",
        lambda self_df, writer, sheet_name, index: captured_sheets.append((sheet_name, len(self_df))),
    )
    monkeypatch.setattr(export_module, "_upload_excel", AsyncMock(return_value="https://minio/all.xlsx"))

    service = export_module.DashboardExportService(request=None, login_user=login_user)
    url = await service.export_component_all(dashboard_id=1, component_id="comp-1")

    assert url == "https://minio/all.xlsx"
    assert sorted(captured_sheets) == [("部门A", 2), ("部门B", 1)]


async def test_export_all_row_limit_exceeded(monkeypatch, service_module):
    export_module, dashboard_module = service_module
    too_many = export_module.EXPORT_ROW_LIMIT_PER_SHEET + 1
    detail = _detail(
        columns=[("file_name", "文件名"), ("belonging_department_name", "所属部门")],
        rows=[{"file_name": f"{index}.pdf", "belonging_department_name": "部门A"} for index in range(too_many)],
    )
    login_user, _query_mock = _patch_common(
        monkeypatch,
        dashboard_module,
        dashboard=_dashboard(),
        component=_component(),
        detail=detail,
    )

    service = export_module.DashboardExportService(request=None, login_user=login_user)
    with pytest.raises(DashboardExportLimitExceededError):
        await service.export_component_all(dashboard_id=1, component_id="comp-1")


async def test_export_all_no_dimensions_configured_uses_single_sheet(monkeypatch, service_module):
    """With no dimension to split on, every record belongs to one sheet."""
    export_module, dashboard_module = service_module
    component = _component(
        data_config={"dimensions": [], "metrics": [{"fieldId": "file_count", "displayName": "文件数"}]}
    )
    detail = _detail(
        columns=[("file_name", "文件名")],
        rows=[{"file_name": "a.pdf"}, {"file_name": "b.pdf"}, {"file_name": "c.pdf"}],
    )
    login_user, _query_mock = _patch_common(
        monkeypatch,
        dashboard_module,
        dashboard=_dashboard(),
        component=component,
        detail=detail,
    )

    captured_frames: list[tuple[str, int]] = []
    monkeypatch.setattr(export_module.pd, "ExcelWriter", lambda *_a, **_k: _FakeWriter())
    monkeypatch.setattr(
        export_module.pd.DataFrame,
        "to_excel",
        lambda self_df, writer, sheet_name, index: captured_frames.append((sheet_name, len(self_df))),
    )
    monkeypatch.setattr(export_module, "_upload_excel", AsyncMock(return_value="https://minio/all.xlsx"))

    service = export_module.DashboardExportService(request=None, login_user=login_user)
    await service.export_component_all(dashboard_id=1, component_id="comp-1")

    assert captured_frames == [("Sheet1", 3)]


async def test_upload_excel_returns_a_browser_reachable_link_not_the_internal_minio_host(monkeypatch):
    """Customer report (2026-09-01): the export link was `http://minio:9000/...` — only
    resolvable inside the docker network, unreachable from the browser. The old code
    (save_uploaded_file) hardcoded get_share_link(clear_host=False), keeping that internal
    host. Fixed to upload directly and call get_share_link with its default
    clear_host=True, matching the working pattern in api/v1/evaluation.py::get_download_url."""
    from io import BytesIO

    from bisheng.telemetry_search.domain.services import dashboard_export_service as export_module

    fake_client = SimpleNamespace(
        tmp_bucket="tmp-dir",
        put_object_tmp=AsyncMock(),
        get_share_link=AsyncMock(return_value="https://dashboard.example.com/tmp-dir/report.xlsx"),
    )
    monkeypatch.setattr(export_module, "get_minio_storage", AsyncMock(return_value=fake_client))

    url = await export_module._upload_excel(BytesIO(b"fake-excel-bytes"), "report.xlsx")

    assert url == "https://dashboard.example.com/tmp-dir/report.xlsx"
    fake_client.put_object_tmp.assert_awaited_once()
    assert fake_client.put_object_tmp.call_args.kwargs["object_name"] == "report.xlsx"
    fake_client.get_share_link.assert_awaited_once_with("report.xlsx", "tmp-dir")
