"""上传人组织只读 knowledgefile.belonging_organization_id."""

from types import SimpleNamespace

import pytest

from test.test_knowledge_space_content_telemetry import _import_worker_mid_table


def _department(department_id: int, name: str, level: str, path: str, **overrides):
    values = {
        "id": department_id,
        "name": name,
        "org_level": level,
        "path": path,
        "status": "active",
        "tenant_id": 1,
        "is_deleted": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _file(**overrides):
    values = {
        "id": 11,
        "tenant_id": 1,
        "user_id": 7,
        "user_name": "上传人",
        "original_knowledge_id": 10,
        "belonging_organization_id": None,
        "create_time": None,
        "file_name": "制度.pdf",
        "file_type": 1,
        "split_rule": None,
        "file_subcategory_code": None,
        "file_encoding": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _build(worker, file_record, departments, registered, primary):
    return worker._build_knowledge_space_content_records(
        [(file_record, SimpleNamespace(id=20, tenant_id=1, name="当前库"))],
        {},
        space_scope_map={20: SimpleNamespace(level="department")},
        space_department_map={20: departments[2]},
        original_space_scope_map={10: SimpleNamespace(level="department"), 20: SimpleNamespace(level="department")},
        original_space_department_map={10: departments[4], 20: departments[2]},
        primary_department_map={7: primary},
        registered_organization_map=registered,
        category_label_cache={1: ({}, {})},
    )[0][0]


@pytest.fixture
def worker(monkeypatch):
    """加载投影模块并跳过用户查询.

    Returns:
        已打桩的投影模块.
    """
    module = _import_worker_mid_table()
    monkeypatch.setattr(module, "get_user_from_ids_with_cache", lambda _ids, cache: cache)
    return module


def test_uploader_organization_expands_registered_department(monkeypatch, worker):
    """有效登记组织展开四级名称, 不用当前主组织."""
    departments = {
        1: _department(1, "首钢", "company", "/1"),
        2: _department(2, "制造部", "dept", "/1/2"),
        3: _department(3, "炼铁科", "office", "/1/2/3"),
        4: _department(4, "一班", "squad", "/1/2/3/4"),
        9: _department(9, "当前部门", "dept", "/9"),
    }
    monkeypatch.setattr(worker, "_get_dimension_department_map", lambda _departments: departments)
    loaded = []
    monkeypatch.setattr(worker, "_get_departments_by_ids", lambda ids: loaded.append(list(ids)) or {})

    record = _build(worker, _file(belonging_organization_id=4), departments, {4: departments[4]}, departments[9])

    assert record.uploader_company_name == "首钢"
    assert record.uploader_department_name == "制造部"
    assert record.uploader_office_name == "炼铁科"
    assert record.uploader_squad_name == "一班"
    assert record.belonging_department_name == "制造部"
    assert "original_upload_squad_name" not in record.model_dump()
    assert loaded == []


def test_missing_registered_organization_stays_empty(monkeypatch, worker):
    """登记组织为空时上传人组织留空, 所属和原始所属仍按库计算."""
    departments = {
        2: _department(2, "制造部", "dept", "/2"),
        4: _department(4, "一班", "squad", "/4"),
        9: _department(9, "当前部门", "dept", "/9"),
    }
    monkeypatch.setattr(worker, "_get_dimension_department_map", lambda _departments: departments)

    record = _build(worker, _file(belonging_organization_id=None), departments, {}, departments[9])

    assert record.uploader_company_name is None
    assert record.uploader_department_name is None
    assert record.uploader_office_name is None
    assert record.uploader_squad_name is None
    assert record.belonging_department_name == "制造部"
    assert "original_upload_squad_name" not in record.model_dump()


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "inactive"},
        {"is_deleted": 1},
        {"tenant_id": 2},
        {"tenant_id": None},
    ],
)
def test_unusable_registered_organization_stays_empty(monkeypatch, worker, overrides):
    """停用, 已删除或跨租户的登记组织不写入上传人组织."""
    registered = _department(4, "一班", "squad", "/4", **overrides)
    departments = {
        2: _department(2, "制造部", "dept", "/2"),
        4: registered,
        9: _department(9, "当前部门", "dept", "/9"),
    }
    monkeypatch.setattr(worker, "_get_dimension_department_map", lambda _departments: departments)

    record = _build(worker, _file(belonging_organization_id=4), departments, {4: registered}, departments[9])

    assert record.uploader_department_name is None
    assert record.uploader_squad_name is None


def test_unknown_registered_organization_id_stays_empty(monkeypatch, worker):
    """登记组织 ID 找不到部门行时上传人组织留空."""
    departments = {
        2: _department(2, "制造部", "dept", "/2"),
        4: _department(4, "原始班组", "squad", "/4"),
        9: _department(9, "当前部门", "dept", "/9"),
    }
    monkeypatch.setattr(worker, "_get_dimension_department_map", lambda _departments: departments)
    monkeypatch.setattr(worker, "_get_departments_by_ids", lambda _ids: {})

    record = _build(worker, _file(belonging_organization_id=4), departments, {}, departments[9])

    assert record.uploader_department_name is None


def test_registered_organization_lookup_is_cached_on_the_caller_map(monkeypatch, worker):
    """同一次同步复用调用方传入的组织缓存, 不重复读取部门."""
    squad = _department(4, "一班", "squad", "/4")
    calls = []

    def load(ids):
        calls.append(list(ids))
        return {4: squad}

    monkeypatch.setattr(worker, "get_user_from_ids_with_cache", lambda _ids, cache: cache)
    monkeypatch.setattr(worker, "_get_dimension_department_map", lambda _departments: {4: squad})
    monkeypatch.setattr(worker, "_get_departments_by_ids", load)
    registered = {}
    kwargs = {
        "space_scope_map": {20: SimpleNamespace(level="personal", owner_id=7)},
        "space_department_map": {20: None},
        "original_space_scope_map": {20: SimpleNamespace(level="personal", owner_id=7)},
        "original_space_department_map": {20: None},
        "primary_department_map": {7: squad},
        "registered_organization_map": registered,
        "category_label_cache": {1: ({}, {})},
    }
    file_record = _file(original_knowledge_id=None, belonging_organization_id=4)
    space = SimpleNamespace(id=20, tenant_id=1, name="个人库")

    first, _ = worker._build_knowledge_space_content_records([(file_record, space)], {}, **kwargs)
    second, _ = worker._build_knowledge_space_content_records([(file_record, space)], {}, **kwargs)

    assert first[0].uploader_squad_name == "一班"
    assert second[0].uploader_squad_name == "一班"
    assert calls == [[4]]
