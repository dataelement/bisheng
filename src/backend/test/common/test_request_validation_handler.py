"""The platform validation handler must answer 422, never 500."""

import json

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


def test_credential_type_errors_do_not_echo_the_submitted_value():
    request = type("Request", (), {"method": "POST", "url": "/api/v1/llm/models/discover"})()
    errors = [
        {
            "type": "string_type",
            "loc": ("body", "config", "api_key"),
            "msg": "Input should be a valid string",
            "input": {"nested": "MARKER-KEY"},
        },
        {
            "type": "string_type",
            "loc": ("body", "options", "management_token"),
            "msg": "Input should be a valid string",
            "input": ["MARKER-TOKEN"],
        },
        {
            "type": "string_type",
            "loc": ("body", "options", "secret_key"),
            "msg": "Input should be a valid string",
            "input": {"sk": "MARKER-SK"},
        },
        {
            "type": "string_type",
            "loc": ("body", "name"),
            "msg": "Input should be a valid string",
            "input": "visible-name",
        },
    ]
    response = handle_request_validation_error(request, RequestValidationError(errors))
    body = response.body.decode()
    assert "MARKER-KEY" not in body
    assert "MARKER-TOKEN" not in body
    assert "MARKER-SK" not in body
    payload = json.loads(response.body)
    echoed = payload["status_message"]
    assert echoed[0]["input"] == "********"
    assert echoed[1]["input"] == "********"
    assert echoed[2]["input"] == "********"
    assert echoed[3]["input"] == "visible-name"


class _Discover(BaseModel):
    config: dict[str, str | None] = {}
    options: dict[str, str] = {}


def test_discover_schema_rejects_object_credentials_without_echoing_them():
    app = FastAPI(exception_handlers={RequestValidationError: handle_request_validation_error})

    @app.post("/discover")
    def discover(body: _Discover):
        return {"ok": True}

    with TestClient(app) as client:
        resp = client.post(
            "/discover",
            json={
                "config": {"api_key": {"nested": "MARKER-KEY"}},
                "options": {
                    "management_token": ["MARKER-TOKEN"],
                    "secret_key": {"sk": "MARKER-SK"},
                },
            },
        )

    assert resp.status_code == 200
    body = resp.text
    assert "MARKER-KEY" not in body
    assert "MARKER-TOKEN" not in body
    assert "MARKER-SK" not in body
    echoed = resp.json()["status_message"]
    assert {item["input"] for item in echoed} == {"********"}
    assert {item["type"] for item in echoed} == {"string_type"}


def test_a_custom_validator_value_error_is_reported_as_422():
    with TestClient(_app()) as client:
        resp = client.put("/configs", json={"allow_dept_ids": [1, "bad"]})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status_code"] == 422
    assert "allow_dept_ids must be a list of integers" in body["status_message"][0]["msg"]
