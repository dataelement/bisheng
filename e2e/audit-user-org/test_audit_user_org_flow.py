"""Read-only audit org columns. Runs only when BISHENG_E2E=1."""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("BISHENG_E2E") != "1", reason="只在明确跑 e2e 时连接毕昇"
)

_ORG_KEYS = ("department_name", "company_name", "office_name")


def _rows(response):
    assert response.status_code == 200
    body = response.json()
    assert body["status_code"] == 200
    return body["data"]["data"]


def test_audit_lists_expose_current_user_org_and_filters():
    import httpx

    base = os.environ["BISHENG_BASE_URL"].rstrip("/")
    headers = {"Authorization": f"Bearer {os.environ['BISHENG_TOKEN']}"}
    client = httpx.Client(base_url=base, headers=headers, timeout=30)

    options = client.get("/api/v1/audit/user-org-options")
    assert options.status_code == 200
    names = options.json()["data"]
    assert isinstance(names["departments"], list)
    assert isinstance(names["companies"], list)
    assert isinstance(names["offices"], list)

    sessions = _rows(
        client.get("/api/v1/audit/session", params={"page": 1, "page_size": 20})
    )
    logs = _rows(client.get("/api/v1/audit", params={"page": 1, "limit": 20}))
    for row in sessions + logs:
        for key in _ORG_KEYS:
            assert isinstance(row[key], str)

    department = next(
        (row["department_name"] for row in sessions if row["department_name"]), ""
    )
    if not department and names["departments"]:
        department = names["departments"][0]
    if department:
        filtered = _rows(
            client.get(
                "/api/v1/audit/session",
                params={"page": 1, "page_size": 20, "user_department": department},
            )
        )
        assert all(row["department_name"] == department for row in filtered)
        again = _rows(
            client.get("/api/v1/audit/session", params={"page": 1, "page_size": 20})
        )
        assert isinstance(again, list)

    if names["companies"]:
        company = names["companies"][0]
        filtered_logs = _rows(
            client.get(
                "/api/v1/audit",
                params={"page": 1, "limit": 20, "user_company": company},
            )
        )
        assert all(row["company_name"] == company for row in filtered_logs)
