import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from bisheng import main
from bisheng.dsh.domain.schemas.unified_policy import CreditRuleInput


def test_unhandled_exception_uses_http_500() -> None:
    request = SimpleNamespace(method="GET", url="/api/v1/knowledge")

    response = main.handle_http_exception(
        request,
        AttributeError("missing permission runtime method"),
    )

    assert response.status_code == 500
    assert json.loads(response.body) == {
        "status_code": 500,
        "status_message": "missing permission runtime method",
    }


@pytest.mark.parametrize("credits", ["9999999999999", "9223372036854.775808"])
def test_credit_range_validation_remains_a_serializable_client_error(credits):
    app = FastAPI(exception_handlers={RequestValidationError: main.handle_request_validation_error})
    saved = []

    @app.put("/credit-rule")
    def save_rule(body: CreditRuleInput):
        saved.append(body)
        return {"saved": True}

    with TestClient(app) as client:
        response = client.put("/credit-rule", json={"version": 0, "monthly_credits": credits})

    assert response.status_code == 200
    data = response.json()
    assert data["status_code"] == 422
    error = data["status_message"][0]
    assert error["type"] == "value_error"
    assert error["ctx"]["error"] == "Credit limit exceeds the accounting range"
    assert saved == []


def test_missing_field_validation_keeps_the_existing_error_envelope():
    request = SimpleNamespace(method="PUT", url="/api/v1/dsh/admin/credit-rules/USER/1")
    error = {"type": "missing", "loc": ("body", "monthly_credits"), "msg": "Field required", "input": {}}
    response = main.handle_request_validation_error(request, RequestValidationError([error]))
    assert response.status_code == 200
    assert json.loads(response.body) == {
        "status_code": 422,
        "status_message": [{**error, "loc": ["body", "monthly_credits"]}],
    }
