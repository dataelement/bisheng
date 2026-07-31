import json
from types import SimpleNamespace

from bisheng import main


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
