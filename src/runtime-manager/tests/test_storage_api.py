"""Attachment storage over HTTP — bearer scoped to the app, HMAC for the platform (T084a).

The service-level cage is pinned in ``test_storage.py``; this file pins what
the router adds on top: *which credential* opens *which app's* space, that the
size cap bounds memory (not only what reaches the store) and that a hostile
header is a 401, never a 500.
"""

from __future__ import annotations

import pytest

from runtime_manager.config import set_config
from tests.fakes import FakeHostProbe
from tests.test_storage import APP, OTHER, _deploy


def _bearer(client, method: str, path: str, token: str, **kwargs):
    headers = {"Authorization": f"Bearer {token}", **(kwargs.pop("headers", None) or {})}
    return client.client.request(method, path, headers=headers, **kwargs)


def test_per_app_token_cannot_touch_another_apps_prefix(
    rtm_client, rtm_config, fake_docker, fake_object_store, monkeypatch
):
    """AC-45 — app A's token on app B's URL is a 401, not a scoping decision."""
    monkeypatch.setattr("runtime_manager.admission.LinuxHostProbe.snapshot", lambda self: FakeHostProbe().snapshot())
    token_a = _deploy(rtm_config, fake_docker, APP, "a")
    token_b = _deploy(rtm_config, fake_docker, OTHER, "b")
    assert token_a != token_b

    ok = _bearer(rtm_client, "PUT", f"/v1/apps/{APP}/storage/objects/x.txt", token_a, content=b"hello")
    assert ok.status_code == 200, ok.text
    assert ok.json()["key"] == "x.txt" and ok.json()["size"] == 5

    crossed = _bearer(rtm_client, "GET", f"/v1/apps/{OTHER}/storage/objects/x.txt", token_a)
    assert crossed.status_code == 401
    assert crossed.json()["detail"]["code"] == "unauthorized"
    assert fake_object_store.calls_of("get_object") == []

    # B's own token on B's URL: the object A wrote is simply not there.
    own = _bearer(rtm_client, "GET", f"/v1/apps/{OTHER}/storage/objects/x.txt", token_b)
    assert own.status_code == 404

    # No token, wrong token, and a destroyed app all fail closed.
    assert rtm_client.client.get(f"/v1/apps/{APP}/storage/objects").status_code == 401
    assert _bearer(rtm_client, "GET", f"/v1/apps/{APP}/storage/objects", "not-the-token").status_code == 401
    rtm_client.post("/v1/intents/destroy", {"app_id": APP, "purge_volume": False})
    assert _bearer(rtm_client, "GET", f"/v1/apps/{APP}/storage/objects", token_a).status_code == 401


def test_hostile_bearer_values_are_401_not_500(rtm_client, rtm_config, fake_docker, fake_object_store, monkeypatch):
    """The header is attacker supplied: non-ASCII or empty must not trip ``compare_digest`` into a 500."""
    monkeypatch.setattr("runtime_manager.admission.LinuxHostProbe.snapshot", lambda self: FakeHostProbe().snapshot())
    _deploy(rtm_config, fake_docker)
    path = f"/v1/apps/{APP}/storage/objects"

    # httpx only lets raw bytes through; Starlette decodes them as latin-1 into a non-ASCII ``str``.
    non_ascii = rtm_client.client.get(path, headers={"Authorization": "Bearer töken-é".encode("latin-1")})
    assert non_ascii.status_code == 401
    assert non_ascii.json()["detail"]["code"] == "unauthorized"
    assert rtm_client.client.get(path, headers={"Authorization": "Bearer"}).status_code == 401
    assert rtm_client.client.get(path, headers={"Authorization": "Bearer  "}).status_code == 401
    # An unknown scheme is not "the app": it falls through to HMAC and fails there.
    assert rtm_client.client.get(path, headers={"Authorization": "Basic abc"}).status_code == 401
    assert fake_object_store.calls_of("list_objects") == []


def test_http_round_trip_with_bearer(rtm_client, rtm_config, fake_docker, fake_object_store, monkeypatch):
    monkeypatch.setattr("runtime_manager.admission.LinuxHostProbe.snapshot", lambda self: FakeHostProbe().snapshot())
    token = _deploy(rtm_config, fake_docker)
    base = f"/v1/apps/{APP}/storage"

    put = _bearer(
        rtm_client, "PUT", f"{base}/objects/docs/a.txt", token, content=b"hello", headers={"content-type": "text/plain"}
    )
    assert put.status_code == 200, put.text
    assert put.json()["content_type"] == "text/plain"

    meta = _bearer(rtm_client, "GET", f"{base}/meta/docs/a.txt", token)
    assert meta.status_code == 200 and meta.json()["size"] == 5

    listing = _bearer(rtm_client, "GET", f"{base}/objects", token, params={"prefix": "docs/"})
    assert [o["key"] for o in listing.json()["objects"]] == ["docs/a.txt"]
    assert listing.json()["next_cursor"] is None

    got = _bearer(rtm_client, "GET", f"{base}/objects/docs/a.txt", token)
    assert got.status_code == 200 and got.content == b"hello"
    assert got.headers["content-type"].startswith("text/plain")

    gone = _bearer(rtm_client, "DELETE", f"{base}/objects/docs/a.txt", token)
    assert gone.status_code == 200
    assert _bearer(rtm_client, "GET", f"{base}/meta/docs/a.txt", token).status_code == 404
    assert _bearer(rtm_client, "DELETE", f"{base}/objects/docs/a.txt", token).status_code == 404

    escaped = _bearer(rtm_client, "PUT", f"{base}/objects/apps/{OTHER}/attachments/x", token, content=b"x")
    assert escaped.status_code == 400
    assert escaped.json()["detail"]["code"] == "invalid_object_key"


def test_http_upload_over_cap_is_413_before_reading(
    rtm_client, rtm_config, fake_docker, fake_object_store, monkeypatch
):
    monkeypatch.setattr("runtime_manager.admission.LinuxHostProbe.snapshot", lambda self: FakeHostProbe().snapshot())
    token = _deploy(rtm_config, fake_docker)
    set_config(rtm_config.with_overrides(storage_max_file_mb=1))
    try:
        # Header says too big → refused on the header alone.
        lying = _bearer(
            rtm_client,
            "PUT",
            f"/v1/apps/{APP}/storage/objects/big.bin",
            token,
            content=b"x",
            headers={"content-length": str(2 * 1024 * 1024)},
        )
        assert lying.status_code == 413
        real = _bearer(
            rtm_client, "PUT", f"/v1/apps/{APP}/storage/objects/big.bin", token, content=b"x" * (1024 * 1024 + 1)
        )
        assert real.status_code == 413
        assert real.json()["detail"]["code"] == "payload_too_large"
    finally:
        set_config(rtm_config)
    assert fake_object_store.calls_of("put_object") == []


def test_chunked_upload_without_content_length_is_still_capped(
    rtm_client, rtm_config, fake_docker, fake_object_store, monkeypatch
):
    """No ``Content-Length`` (chunked): over the cap is a 413 with nothing stored; under it works."""
    monkeypatch.setattr("runtime_manager.admission.LinuxHostProbe.snapshot", lambda self: FakeHostProbe().snapshot())
    token = _deploy(rtm_config, fake_docker)
    set_config(rtm_config.with_overrides(storage_max_file_mb=1))
    try:
        big = _bearer(
            rtm_client,
            "PUT",
            f"/v1/apps/{APP}/storage/objects/big.bin",
            token,
            content=iter([b"x" * (256 * 1024)] * 8),  # 2 MiB, chunked
        )
        assert big.status_code == 413
        assert big.json()["detail"]["code"] == "payload_too_large"
        small = _bearer(
            rtm_client, "PUT", f"/v1/apps/{APP}/storage/objects/ok.bin", token, content=iter([b"ab", b"cd"])
        )
        assert small.status_code == 200 and small.json()["size"] == 4
    finally:
        set_config(rtm_config)
    assert [c["key"].rsplit("/", 1)[-1] for c in fake_object_store.calls_of("put_object")] == ["ok.bin"]


async def test_read_capped_stops_pulling_chunks_at_the_cap(rtm_config):
    """The cap bounds *memory*: the read gives up at the first chunk over it and never pulls the rest.

    The test client buffers a request body before the app sees it, so this is
    pinned at the ASGI level with a ``receive`` that counts what was pulled.
    """
    from starlette.requests import Request

    from runtime_manager.api.storage import _read_capped
    from runtime_manager.storage import AppStorageService, PayloadTooLargeError

    service = AppStorageService(rtm_config.with_overrides(storage_max_file_mb=1))
    pulled: list[int] = []

    async def receive():
        pulled.append(len(pulled))
        # 256 KiB per chunk, endless: only a capped reader ever returns.
        return {"type": "http.request", "body": b"x" * (256 * 1024), "more_body": True}

    request = Request({"type": "http", "method": "PUT", "path": "/", "headers": [], "query_string": b""}, receive)
    with pytest.raises(PayloadTooLargeError):
        await _read_capped(request, service)
    assert len(pulled) == 5  # 4 × 256 KiB fit; the 5th crosses 1 MiB and stops the read


def test_platform_reaches_storage_with_hmac(rtm_client, rtm_config, fake_object_store):
    """F052 / a later data tab: the platform signs like every other ``/v1`` route — no record needed."""
    from runtime_manager.auth import compute_signature
    from tests.conftest import TEST_SECRET

    path = f"/v1/apps/{APP}/storage/objects/from-platform.txt"
    body = b"platform wrote this"
    signed = rtm_client.client.put(
        path, content=body, headers={"X-Signature": compute_signature("PUT", path, body, TEST_SECRET)}
    )
    assert signed.status_code == 200, signed.text

    listing = rtm_client.get(f"/v1/apps/{APP}/storage/objects")
    assert [o["key"] for o in listing.json()["objects"]] == ["from-platform.txt"]

    forged = rtm_client.get(f"/v1/apps/{APP}/storage/objects", secret="wrong")
    assert forged.status_code == 401
