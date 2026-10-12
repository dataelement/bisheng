"""The platform validation handler must answer 422, never 500."""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, field_validator

from bisheng.main import handle_request_validation_error


class _Body(BaseModel):
    allow_dept_ids: list

    @field_validator("allow_dept_ids")
    @classmethod
    def _ints_only(cls, value: list) -> list:
        if not all(isinstance(item, int) for item in value):
            raise ValueError("allow_dept_ids must be a list of integers")
        return value


def _app() -> FastAPI:
    app = FastAPI(exception_handlers={RequestValidationError: handle_request_validation_error})

    @app.put("/configs")
    def update(body: _Body):
        return {"ok": True}

    return app


def test_a_custom_validator_value_error_is_reported_as_422():
    with TestClient(_app()) as client:
        resp = client.put("/configs", json={"allow_dept_ids": [1, "bad"]})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status_code"] == 422
    assert "allow_dept_ids must be a list of integers" in body["status_message"][0]["msg"]
