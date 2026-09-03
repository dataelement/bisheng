import json
from pathlib import Path

import orjson


def test_validation_error_handler_serializes_ctx_value_error():
    main_source = Path(__file__).resolve().parents[2] / "bisheng" / "main.py"
    assert "json.loads(json.dumps(exc.errors(), default=str))" in main_source.read_text()

    errors = [
        {
            "type": "bool_parsing",
            "loc": ("body", "force"),
            "msg": "Input should be a valid boolean",
            "input": "true",
            "ctx": {"error": ValueError("bad bool")},
        }
    ]
    payload = {
        "status_code": 422,
        "status_message": json.loads(json.dumps(errors, default=str)),
    }
    body = orjson.dumps(payload)
    assert b'"status_code":422' in body
    assert b"force" in body
    assert b"bad bool" in body
