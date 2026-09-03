"""T006 — org-hierarchy dashboard filter enums come from the live Department tree
(F058, AC-01, AC-02, AC-03).

Layer: Service unit test, calling ``DashboardService.get_dataset_field_enums`` directly
(not via HTTP — the route itself is unchanged and already covered by
``test_dashboard_enum_labels.py``).
"""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Local dev venv note: this venv's installed `langchain` moved `Document` to
# `langchain_core.documents`; `bisheng/api/v1/schemas.py` still imports the old
# `langchain.docstore.document` path (pre-existing, unrelated to F058 — the same
# failure hits test_dashboard_enum_labels.py). Stub it out so this test file can
# actually import/exercise `dashboard.py` locally; CI's pinned deps don't need this.
if "langchain.docstore.document" not in sys.modules:
    _docstore_stub = MagicMock()
    _docstore_stub.Document = object
    sys.modules.setdefault("langchain.docstore", MagicMock())
    sys.modules["langchain.docstore.document"] = _docstore_stub


class _FakeDbSession:
    async def __aenter__(self):
        return SimpleNamespace()

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return False


def _node(id_, name, org_level, *, short_name=None, sort_order=0, status="active", children=None):
    return SimpleNamespace(
        id=id_,
        name=name,
        short_name=short_name,
        org_level=org_level,
        sort_order=sort_order,
        status=status,
        children=children or [],
    )


async def _call(monkeypatch, *, field, tree, keyword=None, size=20, page=1, resolved_labels=None):
    from bisheng.telemetry_search.domain.services import dashboard as module

    dataset = SimpleNamespace(
        es_index_name="mid_knowledge_space_content_stat",
        schema_config={
            "dimensions": [
                {"field": field, "field_type": "string"},
                # unrelated, non-org field must keep going through the ES branch
                {"field": "file_category_name", "field_type": "string"},
            ]
        },
    )
    repository = SimpleNamespace(find_one=AsyncMock(return_value=dataset))
    monkeypatch.setattr(module, "get_async_db_session", _FakeDbSession)
    monkeypatch.setattr(module, "DashboardDatasetRepositoryImpl", lambda _session: repository)
    monkeypatch.setattr(module.DepartmentService, "aget_tree", AsyncMock(return_value=tree))

    resolved_labels = resolved_labels or {}

    async def _fake_resolve(department_id, name_text):
        return resolved_labels.get(department_id, name_text)

    monkeypatch.setattr(module, "resolve_short_name", _fake_resolve)

    service = module.DashboardService.model_construct()
    return await service.get_dataset_field_enums(
        dataset_code="mid_knowledge_space_content_stat",
        field=field,
        keyword=keyword,
        size=size,
        page=page,
    )


async def test_returns_org_units_with_no_data_in_dataset(monkeypatch):
    """AC-01: a department with zero matching ES docs still appears in the enum list."""
    tree = [
        _node(1, "生产制造部", "company", short_name="生产部"),
        _node(2, "从未上传过文件的部门", "company"),
    ]

    result = await _call(monkeypatch, field="belonging_company_name", tree=tree)

    assert {opt["value"] for opt in result["options"]} == {"生产制造部", "从未上传过文件的部门"}
    assert result["total"] == 2


async def test_only_matching_org_level_returned(monkeypatch):
    """A department-tier node must not leak into the company-tier enum list."""
    tree = [
        _node(1, "生产制造部", "company", children=[_node(11, "轧钢部", "dept")]),
    ]

    result = await _call(monkeypatch, field="belonging_company_name", tree=tree)

    assert [opt["value"] for opt in result["options"]] == ["生产制造部"]


async def test_uploader_prefix_maps_to_same_org_level(monkeypatch):
    tree = [_node(1, "生产制造部", "company")]

    result = await _call(monkeypatch, field="uploader_company_name", tree=tree)

    assert [opt["value"] for opt in result["options"]] == ["生产制造部"]


async def test_options_use_resolved_short_name_label(monkeypatch):
    tree = [_node(1, "生产制造部", "company", short_name="生产部")]

    result = await _call(
        monkeypatch,
        field="belonging_company_name",
        tree=tree,
        resolved_labels={1: "生产部"},
    )

    assert result["options"] == [{"value": "生产制造部", "label": "生产部"}]


async def test_inactive_department_excluded(monkeypatch):
    tree = [
        _node(1, "在用部门", "company", status="active"),
        _node(2, "已归档部门", "company", status="archived"),
    ]

    result = await _call(monkeypatch, field="belonging_company_name", tree=tree)

    assert [opt["value"] for opt in result["options"]] == ["在用部门"]


async def test_deterministic_order_by_sort_order_then_name(monkeypatch):
    tree = [
        _node(2, "乙部门", "company", sort_order=1),
        _node(1, "甲部门", "company", sort_order=0),
    ]

    result = await _call(monkeypatch, field="belonging_company_name", tree=tree)

    assert [opt["value"] for opt in result["options"]] == ["甲部门", "乙部门"]


async def test_full_roster_returned_for_frontend_select_all(monkeypatch):
    """AC-02: "全选" is a pure frontend interaction — the backend just needs to hand back
    the complete roster (bounded by page size) for the frontend to select from."""
    tree = [_node(i, f"部门{i}", "company") for i in range(5)]

    result = await _call(monkeypatch, field="belonging_company_name", tree=tree, size=20, page=1)

    assert result["total"] == 5
    assert len(result["options"]) == 5


async def test_unrelated_field_still_uses_es_aggregation(monkeypatch):
    """Non-org fields (e.g. knowledge category) must keep going through the original ES branch."""
    from bisheng.telemetry_search.domain.services import dashboard as module

    dataset = SimpleNamespace(
        es_index_name="mid_knowledge_space_content_stat",
        schema_config={"dimensions": [{"field": "file_category_name", "field_type": "string"}]},
    )
    repository = SimpleNamespace(find_one=AsyncMock(return_value=dataset))
    es_client = SimpleNamespace(
        search=AsyncMock(
            return_value={
                "aggregations": {
                    "total_count": {"value": 1},
                    "enum_values": {"buckets": [{"key": "标准文档"}]},
                }
            }
        )
    )
    monkeypatch.setattr(module, "get_async_db_session", _FakeDbSession)
    monkeypatch.setattr(module, "DashboardDatasetRepositoryImpl", lambda _session: repository)
    monkeypatch.setattr(module, "get_es_connection", AsyncMock(return_value=es_client))
    department_mock = AsyncMock()
    monkeypatch.setattr(module.DepartmentService, "aget_tree", department_mock)

    service = module.DashboardService.model_construct()
    result = await service.get_dataset_field_enums(
        dataset_code="mid_knowledge_space_content_stat",
        field="file_category_name",
    )

    assert result["options"] == [{"value": "标准文档", "label": "标准文档"}]
    department_mock.assert_not_awaited()
