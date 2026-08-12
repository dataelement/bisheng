from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import UploadFile
from PIL import Image
from starlette.datastructures import Headers

from bisheng.core.storage.base import ObjectMetadata
from bisheng.core.storage.minio.minio_storage import MinioStorage
from bisheng.database.models.qa_expert import Answer, Expert, Question
from bisheng.qa_expert.api import endpoints
from bisheng.qa_expert.domain.asset_service import (
    AssetKind,
    PromotionResult,
    QaAssetCodec,
    QaAssetError,
    QaAssetService,
    StoredObject,
    inline_response_headers,
    redact_reference,
)
from bisheng.qa_expert.domain.schemas import AnswerCreateRequest, QuestionCreateRequest, QuestionUpdateRequest
from bisheng.qa_expert.domain.services import AnswerService, QuestionService


def _png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (2, 2), color="red").save(output, format="PNG")
    return output.getvalue()


class FakeStorage:
    bucket = "bisheng"
    tmp_bucket = "tmp-dir"
    minio_config = SimpleNamespace(endpoint="minio:9000", sharepoint="files.example.com")

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.copy_calls: list[tuple[str, str, str, str, str | None]] = []
        self.remove_calls: list[tuple[str, str]] = []
        self.sign_calls: list[tuple[str, str, dict[str, str] | None]] = []
        self.stat_calls: list[tuple[str, str]] = []
        self.fail_remove = False

    async def stat_object(self, bucket_name: str, object_name: str) -> ObjectMetadata:
        self.stat_calls.append((bucket_name, object_name))
        content, content_type = self.objects[(bucket_name, object_name)]
        return ObjectMetadata(size=len(content), content_type=content_type)

    async def get_object(self, bucket_name: str, object_name: str) -> bytes:
        return self.objects[(bucket_name, object_name)][0]

    async def object_exists(self, bucket_name: str, object_name: str) -> bool:
        return (bucket_name, object_name) in self.objects

    async def copy_object(
        self,
        source_bucket: str,
        source_object: str,
        dest_bucket: str,
        dest_object: str,
        content_type: str | None = None,
    ) -> None:
        self.copy_calls.append((source_bucket, source_object, dest_bucket, dest_object, content_type))
        content, source_content_type = self.objects[(source_bucket, source_object)]
        self.objects[(dest_bucket, dest_object)] = (
            content,
            content_type or source_content_type,
        )

    async def remove_object(self, bucket_name: str, object_name: str) -> None:
        self.remove_calls.append((bucket_name, object_name))
        if self.fail_remove:
            raise RuntimeError("cleanup failed")
        self.objects.pop((bucket_name, object_name), None)

    async def get_share_link(
        self,
        object_name: str,
        bucket: str,
        clear_host: bool,
        expire_days: int,
        response_headers: dict[str, str] | None = None,
    ) -> str:
        self.sign_calls.append((bucket, object_name, response_headers))
        return f"https://files.example.com/{bucket}/{object_name}?X-Amz-Signature=fresh"


def test_minio_stat_object_maps_size_and_content_type_without_download() -> None:
    storage = MinioStorage.__new__(MinioStorage)
    storage.minio_client_sync = MagicMock()
    storage.minio_client_sync.stat_object.return_value = SimpleNamespace(size=128, content_type="image/png")

    metadata = storage.stat_object_sync("tmp-dir", "a.png")

    assert metadata == ObjectMetadata(size=128, content_type="image/png")
    storage.minio_client_sync.stat_object.assert_called_once_with("tmp-dir", "a.png")
    storage.minio_client_sync.get_object.assert_not_called()


def test_active_or_unknown_attachment_types_are_not_served_as_executable_content() -> None:
    assert inline_response_headers("qa-expert/1/question/attachment/page.html") == {
        "response-content-disposition": "inline",
        "response-content-type": "text/plain",
    }
    assert inline_response_headers("qa-expert/1/question/attachment/vector.svg") == {
        "response-content-disposition": "inline",
        "response-content-type": "text/plain",
    }
    assert inline_response_headers("qa-expert/1/question/attachment/payload.bin") == {
        "response-content-disposition": "inline",
        "response-content-type": "application/octet-stream",
    }


def test_minio_copy_and_sign_forward_preview_metadata() -> None:
    storage = MinioStorage.__new__(MinioStorage)
    storage.minio_client_sync = MagicMock()
    storage.share_minio_client = MagicMock()
    storage.share_minio_client.presigned_get_object.return_value = "https://files.example/a.png"

    storage.copy_object_sync(
        source_bucket="tmp-dir",
        source_object="a.png",
        dest_bucket="bisheng",
        dest_object="qa-expert/a.png",
        content_type="image/png",
    )
    headers = inline_response_headers("qa-expert/a.png")
    storage.get_share_link_sync(
        "qa-expert/a.png",
        bucket="bisheng",
        clear_host=False,
        response_headers=headers,
    )

    storage.minio_client_sync.copy_object.assert_called_once()
    copy_kwargs = storage.minio_client_sync.copy_object.call_args.kwargs
    assert copy_kwargs["metadata"] == {"Content-Type": "image/png"}
    assert copy_kwargs["metadata_directive"] == "REPLACE"
    sign_kwargs = storage.share_minio_client.presigned_get_object.call_args.kwargs
    assert sign_kwargs["response_headers"] == headers


async def test_upload_response_keeps_file_path_and_adds_canonical_relative_path(monkeypatch) -> None:
    monkeypatch.setattr(
        endpoints.KnowledgeService,
        "save_upload_file_original_name",
        AsyncMock(return_value="uuid-photo.png"),
    )
    monkeypatch.setattr(
        endpoints,
        "save_uploaded_file",
        AsyncMock(return_value="https://files.example.com/tmp-dir/uuid-photo.png?old"),
    )
    monkeypatch.setattr(
        endpoints,
        "get_minio_storage",
        AsyncMock(return_value=SimpleNamespace(tmp_bucket="tmp-dir")),
    )
    upload = UploadFile(
        filename="photo.png",
        file=BytesIO(_png_bytes()),
        headers=Headers({"content-type": "image/png"}),
    )

    response = await endpoints.upload_file(file=upload)

    assert response.data.file_path.endswith("?old")
    assert response.data.relative_path == "tmp-dir/uuid-photo.png"
    assert response.data.file_name == "photo.png"
    endpoints.save_uploaded_file.assert_awaited_once_with(
        upload,
        "bisheng",
        "uuid-photo.png",
        content_type="image/png",
    )


@pytest.mark.parametrize(
    ("field_name", "value", "kind", "object_name"),
    [
        ("images_url", "https://files.example.com/tmp-dir/a.png?X-Amz-Signature=old", AssetKind.TEMP_OBJECT, "a.png"),
        ("images_url", "/tmp-dir/a.png?X-Amz-Signature=old", AssetKind.TEMP_OBJECT, "a.png"),
        ("images_url", "tmp-dir/a.png", AssetKind.TEMP_OBJECT, "a.png"),
        (
            "images_url",
            "qa-expert/1/answer/image/owner/a.png",
            AssetKind.PERMANENT_OBJECT,
            "qa-expert/1/answer/image/owner/a.png",
        ),
        ("attachments", "business-file-123", AssetKind.OPAQUE_ID, None),
    ],
)
def test_codec_classifies_supported_reference_forms(
    field_name: str,
    value: str,
    kind: AssetKind,
    object_name: str | None,
) -> None:
    codec = QaAssetCodec(
        tmp_bucket="tmp-dir",
        permanent_bucket="bisheng",
        trusted_hosts={"files.example.com"},
    )

    reference = codec.parse("answer", field_name, value)[0]

    assert reference.kind is kind
    assert reference.object_name == object_name


@pytest.mark.parametrize(
    "value",
    [
        "https://evil.example/tmp-dir/a.png?X-Amz-Credential=secret",
        "https://files.example.com/other/a.png",
        "https://files.example.com/bisheng/knowledge/private.pdf",
        "/tmp-dir/%2e%2e/secret",
        "tmp-dir/a/../secret",
    ],
)
def test_codec_rejects_untrusted_urls_buckets_and_traversal(value: str) -> None:
    codec = QaAssetCodec(
        tmp_bucket="tmp-dir",
        permanent_bucket="bisheng",
        trusted_hosts={"files.example.com"},
    )

    with pytest.raises(QaAssetError):
        codec.parse("answer", "images_url", value)


async def test_promote_and_resolve_mixed_answer_assets() -> None:
    storage = FakeStorage()
    # 兼容历史上未透传 MIME 的临时对象元数据
    storage.objects[("tmp-dir", "one.png")] = (_png_bytes(), "application/octet-stream")
    storage.objects[("tmp-dir", "manual.pdf")] = (b"pdf", "application/pdf")
    service = QaAssetService(storage)  # type: ignore[arg-type]

    result = await service.promote_fields(
        tenant_id=7,
        entity_type="answer",
        owner_stable_id="answer-42",
        values={
            "images_url": "tmp-dir/one.png",
            "attachments": "tmp-dir/manual.pdf;business-file-123",
        },
    )

    assert result.values["images_url"].startswith("qa-expert/7/answer/image/answer-42/")
    assert result.values["attachments"].endswith(";business-file-123")
    assert len(storage.copy_calls) == 2
    resolved = await service.resolve_fields(entity_type="answer", values=result.values)
    assert "X-Amz-Signature=fresh" in resolved["images_url"]
    assert resolved["attachments"].endswith(";business-file-123")
    assert len(storage.sign_calls) == 2


async def test_octet_stream_image_is_normalized_and_signed_for_inline_preview() -> None:
    storage = FakeStorage()
    storage.objects[("tmp-dir", "legacy.png")] = (
        _png_bytes(),
        "application/octet-stream",
    )
    service = QaAssetService(storage)  # type: ignore[arg-type]

    result = await service.promote_fields(
        tenant_id=1,
        entity_type="question",
        owner_stable_id="question-1",
        values={"image_url": "tmp-dir/legacy.png"},
    )
    permanent_key = result.values["image_url"]
    assert permanent_key
    assert storage.objects[("bisheng", permanent_key)][1] == "image/png"

    await service.resolve_fields(
        entity_type="question",
        values={"image_url": permanent_key},
    )

    assert storage.sign_calls[-1][2] == {
        "response-content-disposition": "inline",
        "response-content-type": "image/png",
    }


async def test_partial_promotion_failure_compensates_only_new_targets() -> None:
    storage = FakeStorage()
    storage.objects[("tmp-dir", "good.png")] = (_png_bytes(), "image/png")
    storage.objects[("tmp-dir", "bad.png")] = (b"not-an-image", "image/png")
    service = QaAssetService(storage)  # type: ignore[arg-type]

    with pytest.raises(QaAssetError, match="content is invalid"):
        await service.promote_fields(
            tenant_id=1,
            entity_type="answer",
            owner_stable_id="owner",
            values={"images_url": "tmp-dir/good.png;tmp-dir/bad.png"},
        )

    assert len(storage.copy_calls) == 1
    assert storage.remove_calls == [(storage.copy_calls[0][2], storage.copy_calls[0][3])]
    assert ("tmp-dir", "good.png") in storage.objects


async def test_image_count_is_rejected_before_object_io() -> None:
    storage = FakeStorage()
    service = QaAssetService(storage)  # type: ignore[arg-type]

    with pytest.raises(QaAssetError, match="too many"):
        await service.promote_fields(
            tenant_id=1,
            entity_type="answer",
            owner_stable_id="owner",
            values={"images_url": ";".join(f"tmp-dir/{index}.png" for index in range(4))},
        )

    assert storage.stat_calls == []
    assert storage.copy_calls == []


async def test_temporary_cleanup_failure_does_not_fail_committed_business_result() -> None:
    storage = FakeStorage()
    storage.fail_remove = True
    service = QaAssetService(storage)  # type: ignore[arg-type]
    result = PromotionResult(source_objects=[StoredObject("tmp-dir", "safe.png")], values={})

    await service.cleanup_sources(result)

    assert storage.remove_calls == [("tmp-dir", "safe.png")]


def test_redaction_removes_presigned_query_from_diagnostics() -> None:
    value = "https://files.example.com/tmp-dir/a.png?X-Amz-Credential=secret&X-Amz-Signature=value"

    assert redact_reference(value) == "/tmp-dir/a.png"


async def test_existing_permanent_target_is_idempotent_and_not_compensated() -> None:
    storage = FakeStorage()
    storage.objects[("tmp-dir", "one.png")] = (_png_bytes(), "image/png")
    service = QaAssetService(storage)  # type: ignore[arg-type]
    target_name = service._permanent_key(
        tenant_id=1,
        entity_type="answer",
        field_name="images_url",
        owner_stable_id="owner",
        source_object="one.png",
    )
    storage.objects[("bisheng", target_name)] = (_png_bytes(), "image/png")

    result = await service.promote_fields(
        tenant_id=1,
        entity_type="answer",
        owner_stable_id="owner",
        values={"images_url": "tmp-dir/one.png"},
    )
    await service.compensate(result)

    assert storage.copy_calls == []
    assert storage.remove_calls == []
    assert ("bisheng", target_name) in storage.objects


async def test_answer_create_compensates_when_database_insert_fails() -> None:
    asset_service = AsyncMock()
    promotion = PromotionResult(
        values={"images_url": "qa-expert/1/answer/image/x/a.png", "attachments": None},
        created_objects=[StoredObject("bisheng", "qa-expert/1/answer/image/x/a.png")],
    )
    asset_service.promote_fields.return_value = promotion
    service = AnswerService(asset_service=asset_service)
    service.question_repo = AsyncMock()
    service.question_repo.get_by_id.return_value = Question(
        id=9,
        user_id=1,
        title="q",
        description="d",
        business_domain="domain",
    )
    service.expert_repo = AsyncMock()
    service.expert_repo.get_by_user_id.return_value = Expert(id=3, user_id=8, expert_name="expert")
    service.repository = AsyncMock()
    service.repository.create.side_effect = RuntimeError("db failed")

    with pytest.raises(RuntimeError, match="db failed"):
        await service.create_answer(
            8,
            AnswerCreateRequest(question_id=9, content="answer", images_url="tmp-dir/a.png"),
            tenant_id=1,
        )

    asset_service.compensate.assert_awaited_once_with(promotion)
    asset_service.cleanup_sources.assert_not_awaited()


async def test_question_create_persists_keys_cleans_tmp_and_returns_fresh_urls(monkeypatch) -> None:
    asset_service = AsyncMock()
    promotion = PromotionResult(
        values={
            "image_url": "qa-expert/7/question/image/owner/a.png",
            "file_url": None,
            "attachments": "qa-expert/7/question/attachment/owner/a.pdf;file-9",
        },
        source_objects=[StoredObject("tmp-dir", "a.png")],
    )
    asset_service.promote_fields.return_value = promotion
    asset_service.resolve_fields.return_value = {
        "image_url": "https://files.example.com/bisheng/a.png?fresh",
        "file_url": None,
        "attachments": "https://files.example.com/bisheng/a.pdf?fresh;file-9",
    }
    service = QuestionService(asset_service=asset_service)
    service.repository = AsyncMock()

    async def create(question: Question) -> Question:
        question.id = 12
        return question

    service.repository.create.side_effect = create
    service._send_expert_invitation_inbox_notice = AsyncMock()  # type: ignore[method-assign]
    monkeypatch.setattr(
        "bisheng.qa_expert.domain.services.RealtimeQaQuestionFact.record_success",
        AsyncMock(),
    )

    response = await service.create_question(
        8,
        QuestionCreateRequest(
            title="question",
            description="description",
            business_domain="domain",
            image_url="tmp-dir/a.png",
            attachments="tmp-dir/a.pdf;file-9",
        ),
        "user",
        tenant_id=7,
    )

    persisted = service.repository.create.await_args.args[0]
    assert persisted.image_url.startswith("qa-expert/7/question/image/")
    assert persisted.attachments.endswith(";file-9")
    assert response.image_url.endswith("?fresh")
    asset_service.cleanup_sources.assert_awaited_once_with(promotion)


async def test_question_update_promotes_only_explicit_asset_fields_and_resolves_copy() -> None:
    asset_service = AsyncMock()
    asset_service.promote_fields.return_value = PromotionResult(
        values={"attachments": "qa-expert/1/question/attachment/2/a.pdf"}
    )
    asset_service.resolve_fields.return_value = {
        "image_url": None,
        "file_url": None,
        "attachments": "https://files.example.com/bisheng/a.pdf?fresh",
    }
    service = QuestionService(asset_service=asset_service)
    service.repository = AsyncMock()
    existing = Question(
        id=2,
        user_id=1,
        title="old",
        description="d",
        business_domain="domain",
    )
    updated = existing.model_copy(deep=True)
    updated.attachments = "qa-expert/1/question/attachment/2/a.pdf"
    service.repository.get_by_id.return_value = existing
    service.repository.update.return_value = updated

    response = await service.update_question(
        2,
        QuestionUpdateRequest(title="new", attachments="tmp-dir/a.pdf"),
        tenant_id=1,
    )

    assert response.attachments.startswith("https://files.example.com/")
    assert updated.attachments == "qa-expert/1/question/attachment/2/a.pdf"
    asset_service.promote_fields.assert_awaited_once()
    service.repository.update.assert_awaited_once_with(
        2,
        title="new",
        attachments="qa-expert/1/question/attachment/2/a.pdf",
    )


async def test_answer_update_persists_images_url_and_checks_expert_user() -> None:
    asset_service = AsyncMock()
    asset_service.promote_fields.return_value = PromotionResult(
        values={"images_url": "qa-expert/1/answer/image/5/a.png"}
    )
    asset_service.resolve_fields.return_value = {
        "images_url": "https://files.example.com/bisheng/a.png?fresh",
        "attachments": None,
    }
    service = AnswerService(asset_service=asset_service)
    service.repository = AsyncMock()
    existing = Answer(
        id=5,
        question_id=9,
        expert_id=3,
        expert_name="expert",
        content="old",
    )
    updated = existing.model_copy(deep=True)
    updated.images_url = "qa-expert/1/answer/image/5/a.png"
    service.repository.get_by_id.return_value = existing
    service.repository.update.return_value = updated
    service.expert_repo = AsyncMock()
    service.expert_repo.get_by_id.return_value = Expert(id=3, user_id=8, expert_name="expert")

    response = await service.update_answer(
        5,
        8,
        images_url="tmp-dir/a.png",
        tenant_id=1,
    )

    assert response.images_url.startswith("https://files.example.com/")
    service.repository.update.assert_awaited_once_with(
        5,
        images_url="qa-expert/1/answer/image/5/a.png",
    )


async def test_answer_update_can_clear_images_without_storage_io() -> None:
    asset_service = AsyncMock()
    service = AnswerService(asset_service=asset_service)
    service.repository = AsyncMock()
    existing = Answer(id=5, question_id=9, expert_id=3, expert_name="expert", content="old", images_url="old")
    updated = existing.model_copy(deep=True)
    updated.images_url = ""
    service.repository.get_by_id.return_value = existing
    service.repository.update.return_value = updated
    service.expert_repo = AsyncMock()
    service.expert_repo.get_by_id.return_value = Expert(id=3, user_id=8, expert_name="expert")

    response = await service.update_answer(5, 8, images_url="", tenant_id=1)

    assert response.images_url == ""
    service.repository.update.assert_awaited_once_with(5, images_url="")
    asset_service.promote_fields.assert_not_awaited()
    asset_service.resolve_fields.assert_not_awaited()
