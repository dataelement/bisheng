"""The site entrance asks this route whether a bucket may be fetched by a browser."""

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.api.v1.storage import router as storage_router


def test_bucket_check_allows_only_the_configured_buckets(monkeypatch):
    from bisheng.api.v1 import storage as storage_endpoint

    monkeypatch.setattr(
        storage_endpoint,
        "settings",
        SimpleNamespace(get_minio_conf=lambda: SimpleNamespace(public_bucket="bisheng", tmp_bucket="tmp-dir")),
    )
    app = FastAPI()
    app.include_router(storage_router, prefix="/api/v1")
    client = TestClient(app)

    assert client.get("/api/v1/storage/browser-bucket", headers={"X-Object-Bucket": "bisheng"}).status_code == 204
    assert client.get("/api/v1/storage/browser-bucket", headers={"X-Object-Bucket": "tmp-dir"}).status_code == 204
    assert client.get("/api/v1/storage/browser-bucket", headers={"X-Object-Bucket": "bisheng-apps"}).status_code == 403
    assert client.get("/api/v1/storage/browser-bucket").status_code == 403
