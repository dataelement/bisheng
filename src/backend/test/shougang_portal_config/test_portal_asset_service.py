import io
import json

import pytest
from fastapi import UploadFile
from PIL import Image
from starlette.datastructures import Headers

import bisheng.shougang_portal_config.domain.services.portal_asset_service as asset_module
from bisheng.core.storage.minio.minio_storage import MinioStorage
from bisheng.shougang_portal_config.domain.services.portal_asset_service import (
    PortalAssetValidationError,
    ShougangPortalAssetService,
)


def _image_bytes(image_format: str, size: tuple[int, int] = (32, 32)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=(32, 96, 160)).save(buffer, format=image_format)
    return buffer.getvalue()


def _upload_file(payload: bytes, *, filename: str, content_type: str) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(payload),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


@pytest.mark.parametrize(
    ("image_format", "content_type", "expected_extension"),
    [
        ("JPEG", "image/jpeg", ".jpg"),
        ("PNG", "image/png", ".png"),
        ("WEBP", "image/webp", ".webp"),
    ],
)
async def test_upload_valid_portal_asset_uses_tenant_category_and_decoded_format(
    monkeypatch,
    image_format,
    content_type,
    expected_extension,
):
    captured = {}

    async def fake_upload(payload, *, object_name, content_type):
        captured.update(
            payload=payload,
            object_name=object_name,
            content_type=content_type,
        )
        return f"https://assets.example.com/{object_name}"

    monkeypatch.setattr(asset_module, "_upload_public_asset", fake_upload)

    result = await ShougangPortalAssetService.upload(
        file=_upload_file(
            _image_bytes(image_format),
            filename="../../untrusted.bin",
            content_type=content_type,
        ),
        category="banner",
        tenant_id=7,
    )

    assert result["image_url"] == f"https://assets.example.com/{result['object_key']}"
    assert result["object_key"].startswith("portal-assets/7/banner/")
    assert result["object_key"].endswith(expected_extension)
    assert ".." not in result["object_key"]
    assert captured["content_type"] == content_type
    assert captured["payload"]


@pytest.mark.parametrize(
    ("category", "payload", "content_type", "expected_status"),
    [
        ("other", _image_bytes("PNG"), "image/png", 422),
        ("banner", b"", "image/png", 422),
        ("banner", b"not-an-image", "image/png", 415),
        ("banner", _image_bytes("PNG"), "image/svg+xml", 415),
        ("banner", _image_bytes("PNG"), "image/jpeg", 415),
        ("banner", b"x" * (5 * 1024 * 1024 + 1), "image/png", 413),
        ("app-icon", _image_bytes("PNG", (4097, 1)), "image/png", 413),
    ],
    ids=[
        "invalid-category",
        "empty",
        "forged-content",
        "disallowed-mime",
        "mime-format-mismatch",
        "too-large",
        "too-wide",
    ],
)
async def test_invalid_portal_asset_never_calls_storage(
    monkeypatch,
    category,
    payload,
    content_type,
    expected_status,
):
    calls = []

    async def fake_upload(*args, **kwargs):
        calls.append((args, kwargs))
        return "https://assets.example.com/unexpected"

    monkeypatch.setattr(asset_module, "_upload_public_asset", fake_upload)

    with pytest.raises(PortalAssetValidationError) as exc_info:
        await ShougangPortalAssetService.upload(
            file=_upload_file(payload, filename="asset.bin", content_type=content_type),
            category=category,
            tenant_id=7,
        )

    assert exc_info.value.status_code == expected_status
    assert calls == []


async def test_storage_failure_propagates_without_exposing_credentials(monkeypatch):
    async def fake_upload(*args, **kwargs):
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(asset_module, "_upload_public_asset", fake_upload)

    with pytest.raises(RuntimeError, match="storage unavailable"):
        await ShougangPortalAssetService.upload(
            file=_upload_file(
                _image_bytes("PNG"),
                filename="app.png",
                content_type="image/png",
            ),
            category="app-icon",
            tenant_id=9,
        )


async def test_public_upload_returns_stable_non_expiring_object_path(
    monkeypatch,
):
    calls = []

    class FakeStorage:
        async def ensure_public_read_prefix(self, **kwargs):
            calls.append(("policy", kwargs))

        async def put_object(self, **kwargs):
            calls.append(("put", kwargs))

    async def fake_get_storage():
        return FakeStorage()

    monkeypatch.setattr(asset_module, "get_minio_storage", fake_get_storage)
    monkeypatch.setattr(
        asset_module.bisheng_settings.object_storage.minio,
        "public_bucket",
        "bisheng",
    )

    image_url = await asset_module._upload_public_asset(
        b"image-bytes",
        object_name="portal-assets/7/banner/id.png",
        content_type="image/png",
    )

    assert image_url == "/bisheng/portal-assets/7/banner/id.png"
    assert calls[0] == (
        "policy",
        {
            "bucket_name": "bisheng",
            "object_prefix": "portal-assets/",
        },
    )
    assert calls[1][0] == "put"


def test_public_prefix_policy_merge_preserves_existing_resources():
    existing_resource = "arn:aws:s3:::bisheng/knowledge/images/*"

    class FakeMinioClient:
        def __init__(self):
            self.saved_policy = None

        def get_bucket_policy(self, _bucket_name):
            return json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"AWS": ["*"]},
                            "Action": ["s3:GetObject"],
                            "Resource": [existing_resource],
                        }
                    ],
                }
            )

        def set_bucket_policy(self, _bucket_name, policy):
            self.saved_policy = json.loads(policy)

    storage = object.__new__(MinioStorage)
    storage.minio_client_sync = FakeMinioClient()

    storage.ensure_public_read_prefix_sync(
        bucket_name="bisheng",
        object_prefix="portal-assets/",
    )

    resources = storage.minio_client_sync.saved_policy["Statement"][0]["Resource"]
    assert existing_resource in resources
    assert "arn:aws:s3:::bisheng/portal-assets/*" in resources
