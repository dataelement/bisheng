from types import SimpleNamespace

from bisheng.knowledge.domain.services.uploader_org_names import resolve_uploader_org_names


def _dept(department_id: int, name: str, path: str, org_level: str, status: str = "active"):
    return SimpleNamespace(id=department_id, name=name, path=path, org_level=org_level, status=status)


def test_resolve_uploader_org_names_uses_first_active_level_on_the_path():
    company = _dept(1, "首钢", "/1/", "company")
    department = _dept(2, "设备部", "/1/2/", "dept")
    office = _dept(3, "点检科", "/1/2/3/", "office")
    archived = _dept(4, "旧班组", "/1/2/3/4/", "squad", status="archived")
    by_id = {1: company, 2: department, 3: office, 4: archived}

    assert resolve_uploader_org_names(office, by_id) == {
        "company_name": "首钢",
        "department_name": "设备部",
        "office_name": "点检科",
    }
    assert resolve_uploader_org_names(None, by_id)["company_name"] == ""
    assert resolve_uploader_org_names(archived, by_id)["office_name"] == "点检科"


def test_resolve_uploader_org_names_uses_company_path_when_level_is_missing():
    company = _dept(1, "首钢", "/1/", "")
    department = _dept(2, "设备部", "/1/2/", "")
    office = _dept(3, "点检科", "/1/2/3/", "")
    by_id = {1: company, 2: department, 3: office}

    assert resolve_uploader_org_names(office, by_id, "/1/") == {
        "company_name": "首钢",
        "department_name": "设备部",
        "office_name": "点检科",
    }
