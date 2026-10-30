from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.telemetry_search.domain.schemas.component import ComponentDataConfig
from bisheng.telemetry_search.domain.services import component, department_label_resolver
from bisheng.telemetry_search.domain.services.department_label_resolver import relabel_organization_rows


async def test_query_displays_department_short_names_without_changing_group_values(monkeypatch):
    names = ["北京首钢生产制造部", "安全环保监察部", "已撤销部门", "重名部门"]
    departments = [
        SimpleNamespace(name=names[0], short_name="  生产部  "),
        SimpleNamespace(name=names[1], short_name="  "),
        SimpleNamespace(name=names[3], short_name="一部"),
        SimpleNamespace(name=names[3], short_name="二部"),
    ]

    class SessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_args):
            return False

    dataset = SimpleNamespace(
        es_index_name="test-index",
        schema_config={
            "dimensions": [{"name": "上传人部门", "field": "uploader_department_name"}],
            "metrics": [{"name": "文档数", "field": "count"}],
        },
    )
    monkeypatch.setattr(component, "get_async_db_session", SessionContext)
    monkeypatch.setattr(
        component,
        "DashboardDatasetRepositoryImpl",
        lambda _: SimpleNamespace(
            find_one=AsyncMock(return_value=dataset),
        ),
    )
    monkeypatch.setattr(department_label_resolver, "get_async_db_session", SessionContext, raising=False)
    repository = SimpleNamespace(find_all=AsyncMock(return_value=departments))
    monkeypatch.setattr(department_label_resolver, "BaseRepositoryImpl", lambda *_: repository, raising=False)
    monkeypatch.setattr(
        component.DataQueryService,
        "query_all_metrics",
        AsyncMock(
            return_value=[[name, index + 1] for index, name in enumerate(names)],
        ),
    )
    config = ComponentDataConfig.model_validate(
        {
            "dimensions": [{"fieldId": "uploader_department_name"}],
            "metrics": [{"fieldId": "count", "aggregation": "sum"}],
        }
    )

    result = await component.DataQueryService(dataset_code="test", data_config=config).query_telemetry_data()

    assert result.dimensions == [[name] for name in names]
    assert result.value == [[1], [2], [3], [4]]
    assert result.dimension_labels["uploader_department_name"] == {
        names[0]: "生产部",
        names[1]: names[1],
        names[2]: names[2],
        names[3]: names[3],
    }
    repository.find_all.assert_awaited_once_with()


async def test_relabel_organization_rows_uses_short_names_for_every_org_level(monkeypatch):
    async def fake_labels(_fields, _rows):
        return {
            "belonging_company_name": {"北京首钢股份有限公司": "股份"},
            "belonging_department_name": {"制造部全称": "制造部"},
            "belonging_office_name": {"安全管理室": "安全室"},
            "belonging_squad_name": {"甲班全称": "甲班"},
            "file_name": {"a.pdf": "不应改文件名"},
        }

    monkeypatch.setattr(department_label_resolver, "resolve_dimension_labels", fake_labels)
    rows = await relabel_organization_rows(
        [
            {
                "belonging_company_name": "北京首钢股份有限公司",
                "belonging_department_name": "制造部全称",
                "belonging_office_name": "安全管理室",
                "belonging_squad_name": "甲班全称",
                "file_name": "a.pdf",
            },
            {"belonging_department_name": None, "file_name": "b.pdf"},
        ],
        [
            "belonging_company_name",
            "belonging_department_name",
            "belonging_office_name",
            "belonging_squad_name",
            "file_name",
        ],
    )

    assert rows[0]["belonging_company_name"] == "股份"
    assert rows[0]["belonging_department_name"] == "制造部"
    assert rows[0]["belonging_office_name"] == "安全室"
    assert rows[0]["belonging_squad_name"] == "甲班"
    assert rows[0]["file_name"] == "a.pdf"
    assert rows[1]["belonging_department_name"] is None
