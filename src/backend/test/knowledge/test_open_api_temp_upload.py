from types import SimpleNamespace

import pytest

from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.knowledge.domain.services.temp_upload_service import TempUploadService


async def test_attachment_reference_is_bound_to_complete_session_subject(monkeypatch):
    from minio import Minio

    storage = SimpleNamespace(
        bucket="bisheng",
        tmp_bucket="tmp-dir",
        minio_config=SimpleNamespace(access_key="fixture-access", secret_key="fixture-secret"),
        get_minio_share_host=lambda: "https://example.test",
    )
    signer = Minio(
        "example.test", access_key="fixture-access", secret_key="fixture-secret", secure=True, region="us-east-1"
    )

    async def minio():
        return storage

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.temp_upload_service.get_minio_storage",
        minio,
    )
    first = SessionSubject.service_account(
        tenant_id=1,
        service_account_id=7,
        resource_owner_user_id=9,
        external_user_id="customer-a",
    )
    second = SessionSubject.service_account(
        tenant_id=1,
        service_account_id=7,
        resource_owner_user_id=9,
        external_user_id="customer-b",
    )
    reference = {"filepath": signer.presigned_get_object("tmp-dir", f"open-api/{first.storage_partition}/file.pdf")}

    await TempUploadService.assert_owned_references([reference], first)
    with pytest.raises(Exception) as exc_info:
        await TempUploadService.assert_owned_references([reference], second)
    assert getattr(exc_info.value, "status_code", None) == 404
