"""Issue #2190: the OnlyOffice save callback must only download from the office origin.

The callback endpoints are unauthenticated by necessity (the document server has
no user session). Before this guard, the backend fetched whatever ``url`` the
caller named and stored the response -- a server-side request forgery into the
internal network and cloud metadata.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
import requests

from bisheng.api.services import office_callback
from bisheng.api.services.office_callback import is_office_download_url

OFFICE = "http://192.168.106.120:8702"


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.106.120:8702/cache/files/abc_123/output.docx/output.docx?md5=x&expires=1",
        "HTTP://192.168.106.120:8702/cache/files/x.docx",
    ],
)
def test_document_server_download_url_is_allowed(url):
    assert is_office_download_url(url, OFFICE)


@pytest.mark.parametrize(
    "url",
    [
        # The PoC targets from the report.
        "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
        "http://bisheng-mysql:3306/",
        "http://bisheng-minio:9000/",
        # Right host, wrong port: another service on the same machine.
        "http://192.168.106.120:3306/",
        "http://192.168.106.120/",
        # Right host and port, wrong scheme.
        "https://192.168.106.120:8702/cache/files/x.docx",
        # Userinfo makes a naive prefix/contains check pass while the request goes elsewhere.
        "http://192.168.106.120:8702@169.254.169.254/latest/meta-data/",
        # A lookalike host that merely starts with the office host.
        "http://192.168.106.120.evil.example:8702/",
        # Non-HTTP schemes.
        "file:///etc/passwd",
        "gopher://192.168.106.120:8702/_x",
        # Garbage.
        "http://192.168.106.120:notaport/",
        "",
        None,
        123,
    ],
)
def test_anything_off_the_office_origin_is_refused(url):
    assert not is_office_download_url(url, OFFICE)


def test_default_ports_are_equivalent_to_explicit_ones():
    office = "https://office.example.com"
    assert is_office_download_url("https://office.example.com:443/cache/x.docx", office)
    assert is_office_download_url("https://OFFICE.example.com/cache/x.docx", office)
    assert not is_office_download_url("https://office.example.com:8443/cache/x.docx", office)


@pytest.mark.parametrize("office_url", ["", None, {}, "not a url", "ftp://192.168.106.120:8702"])
def test_unset_or_unusable_office_url_refuses_everything(office_url):
    assert not is_office_download_url(f"{OFFICE}/cache/files/x.docx", office_url)


@pytest.fixture
def office_configured(monkeypatch):
    monkeypatch.setattr(office_callback, "aresolve_office_url", AsyncMock(return_value=OFFICE))


@pytest.fixture
def fake_get(monkeypatch):
    get = MagicMock()
    monkeypatch.setattr(office_callback.Requests, "get", get)
    return get


def _response(status_code: int, content: bytes = b"docx-bytes") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.content = content
    return response


async def test_refused_url_is_never_requested(office_configured, fake_get):
    assert await office_callback.afetch_office_document("http://169.254.169.254/latest/meta-data/") is None
    fake_get.assert_not_called()


async def test_allowed_url_is_fetched_without_following_redirects(office_configured, fake_get):
    fake_get.return_value = _response(200, b"saved-docx")

    assert await office_callback.afetch_office_document(f"{OFFICE}/cache/files/x.docx") == b"saved-docx"
    assert fake_get.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("status_code", [301, 302, 404, 500])
async def test_non_200_answer_is_not_stored(office_configured, fake_get, status_code):
    # With redirects off, a 30x from the office origin comes back as-is and is refused here.
    fake_get.return_value = _response(status_code)

    assert await office_callback.afetch_office_document(f"{OFFICE}/cache/files/x.docx") is None


async def test_transport_error_is_reported_as_a_failed_save(office_configured, fake_get):
    fake_get.side_effect = requests.ConnectionError("connection refused")

    assert await office_callback.afetch_office_document(f"{OFFICE}/cache/files/x.docx") is None


async def test_missing_office_config_refuses_without_requesting(monkeypatch, fake_get):
    monkeypatch.setattr(office_callback, "aresolve_office_url", AsyncMock(return_value=""))

    assert await office_callback.afetch_office_document(f"{OFFICE}/cache/files/x.docx") is None
    fake_get.assert_not_called()


@pytest.fixture
def storage(monkeypatch):
    minio = MagicMock()
    minio.bucket = "bisheng"
    minio.put_object = AsyncMock()
    return minio


async def test_workflow_callback_refuses_and_stores_nothing(monkeypatch, storage):
    from bisheng.api.v1 import workflow

    monkeypatch.setattr(workflow, "afetch_office_document", AsyncMock(return_value=None))
    monkeypatch.setattr(workflow, "get_minio_storage", AsyncMock(return_value=storage))

    result = await workflow.upload_report_file(
        MagicMock(),
        {"status": 2, "url": "http://169.254.169.254/", "key": "probe123"},
    )

    assert result == {"error": 1}
    storage.put_object.assert_not_called()


async def test_workflow_callback_stores_the_downloaded_document(monkeypatch, storage):
    from bisheng.api.v1 import workflow

    monkeypatch.setattr(workflow, "afetch_office_document", AsyncMock(return_value=b"saved-docx"))
    monkeypatch.setattr(workflow, "get_minio_storage", AsyncMock(return_value=storage))

    result = await workflow.upload_report_file(
        MagicMock(),
        {"status": 2, "url": f"{OFFICE}/cache/files/x.docx", "key": "abc_1700000000000"},
    )

    assert result == {"error": 0}
    kwargs = storage.put_object.call_args.kwargs
    assert kwargs["object_name"] == "workflow/report/abc.docx"
    assert kwargs["file"] == b"saved-docx"


async def test_report_callback_refuses_and_stores_nothing(monkeypatch, storage):
    from bisheng.api.v1 import report

    monkeypatch.setattr(report, "afetch_office_document", AsyncMock(return_value=None))
    monkeypatch.setattr(report, "get_minio_storage", AsyncMock(return_value=storage))

    result = await report.callback({"status": 2, "url": "http://bisheng-mysql:3306/", "key": "probe123"})

    assert result == {"error": 1}
    storage.put_object.assert_not_called()
