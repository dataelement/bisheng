"""Platform storage is mandatory; neither redirects nor bad bytes may be accepted."""

import hashlib

import httpx
import pytest

from runtime_manager.config import Config


def config():
    return Config(
        platform_base_url="http://platform",
        node_id="node-a",
        platform_key_id="node",
        platform_secret="fixture-signing-key",
    )


def test_download_validates_content_and_never_follows_storage_redirect(tmp_path):
    """AC-05, AC-06, AC-07: manager only gets bytes through backend and verifies hash."""
    from runtime_manager.platform_client import PlatformClient, PlatformError

    calls = []

    def reply(request):
        calls.append(request.url.host)
        assert request.headers.get("x-runtime-signature")
        if request.url.path.endswith("/downloads"):
            return httpx.Response(
                200,
                json={
                    "transfer_id": "transfer-a",
                    "ticket": "fixture-ticket",
                    "size_bytes": 3,
                    "sha256": hashlib.sha256(b"abc").hexdigest(),
                },
            )
        return httpx.Response(200, content=b"bad")

    client = PlatformClient(config(), transport=httpx.MockTransport(reply))
    with pytest.raises(PlatformError, match="digest"):
        client.download("op", "artifact", tmp_path / "output")
    assert not (tmp_path / "output").exists() and set(calls) == {"platform"}
    client.close()


def test_lost_upload_response_queries_offset_before_retry(tmp_path):
    """AC-36, AC-43: a lost PUT response never blindly duplicates snapshot data."""
    from runtime_manager.platform_client import PlatformClient

    path = tmp_path / "snapshot"
    path.write_bytes(b"abc")
    puts = []

    def reply(request):
        if request.url.path.endswith("/transfers"):
            return httpx.Response(200, json={"transfer_id": "t", "ticket": "fixture-ticket", "offset": 0})
        if request.method == "PUT":
            puts.append(request.content)
            raise httpx.ReadTimeout("fixture lost response", request=request)
        if request.method == "GET":
            return httpx.Response(200, json={"offset": 3})
        return httpx.Response(200, json={"state": "verified", "artifact_id": "snapshot-a"})

    client = PlatformClient(config(), transport=httpx.MockTransport(reply))
    assert client.upload("op", path, kind="snapshot")["state"] == "verified"
    assert puts == [b"abc"]
    client.close()


def test_scope_and_redirect_fail_closed():
    """AC-06, AC-53: trusted platform identity cannot redirect to another origin."""
    from runtime_manager.platform_client import PlatformClient, PlatformError

    client = PlatformClient(
        config(),
        transport=httpx.MockTransport(lambda req: httpx.Response(307, headers={"Location": "http://minio/private"})),
    )
    with pytest.raises(PlatformError):
        client.operation("op")
    client.close()
