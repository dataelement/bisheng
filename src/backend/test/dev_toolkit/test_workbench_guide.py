"""Agents read the enterprise's hosted protocol without local attachments or secrets."""

import pytest

from bisheng.dev_toolkit.domain.services import artifact_service


@pytest.mark.parametrize(
    "path,heading",
    [
        ("/api/v1/dev-toolkit/workbench-guide.md", "毕昇云端工作台协议"),
        ("/api/v1/dev-toolkit/workbench-guide-en.md", "Requirements before implementation"),
    ],
)
def test_guide_is_anonymous_markdown_with_real_protocol(path, heading, client_factory):
    client = client_factory()
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.headers["cache-control"] == "no-cache"
    assert heading in response.text
    assert "cloud_workbench" in response.text
    assert "next_cursor" in response.text
    assert "RealtimeStore" in response.text
    route = next(route for route in client.app.routes if getattr(route, "path", None) == path)
    assert route.dependant.dependencies == []


def test_missing_guide_fails_as_404_not_a_fake_success(client_factory, monkeypatch):
    monkeypatch.setattr(artifact_service, "read_workbench_guide", lambda language: None)
    assert client_factory().get("/api/v1/dev-toolkit/workbench-guide.md").status_code == 404


def test_guide_language_is_not_a_filesystem_path():
    with pytest.raises(ValueError):
        artifact_service.read_workbench_guide("../../secrets")
