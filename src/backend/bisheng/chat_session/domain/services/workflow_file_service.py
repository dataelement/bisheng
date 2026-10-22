"""Bind parsed workflow images to a conversation or an expiring debug run."""

import hashlib
import json
from urllib.parse import quote
from uuid import uuid4

from bisheng.chat_session.domain.repositories.workflow_file_repository import WorkflowFileRepository, source_identity
from bisheng.core.storage.chat_attachment import promote_chat_attachments_sync, temp_object_name_from_url
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.knowledge.rag.pipeline.types import ImageStorageContext


class WorkflowFileService:
    @staticmethod
    def is_owned_image(asset: dict, tenant_id: int, user_id: int) -> bool:
        prefix = f"chat/{tenant_id}/{user_id}/workflow/"
        object_name = str(asset.get("object_name") or "")
        if not object_name.startswith(prefix):
            return False
        parts = object_name[len(prefix) :].split("/")
        if len(parts) != 3 or parts[1] != "images" or parts[2] in ("", ".", ".."):
            return False
        expected = hashlib.sha256(f"{parts[0]}/{parts[2]}".encode()).hexdigest()
        return asset.get("file_id") == expected

    @staticmethod
    def image_storage(
        *,
        chat_id: str | None,
        user_id: int,
        tenant_id: int,
        workflow_id: str,
        run_id: str,
        node_id: str,
        source_url: str,
        file_name: str,
    ) -> ImageStorageContext:
        minio = get_minio_storage_sync()
        if chat_id:
            tenant_id = WorkflowFileRepository.conversation_tenant(chat_id, user_id, workflow_id)
        host_getter = getattr(minio, "get_minio_share_host", None)
        storage_host = host_getter() if callable(host_getter) else ""
        storage_host = storage_host if isinstance(storage_host, str) else ""

        def normalize_source(value: str) -> str:
            return source_identity(value, storage_host=storage_host, buckets=(minio.bucket, minio.tmp_bucket))

        # An attempt never overwrites images already referenced by a completed run.
        identity = hashlib.sha256(
            json.dumps([chat_id, workflow_id, run_id, node_id, normalize_source(source_url), uuid4().hex]).encode()
        ).hexdigest()
        partition = f"{tenant_id}/{user_id}/workflow/{identity}"
        object_dir = f"chat/{partition}/images" if chat_id else f"workflow/{partition}/images"
        bucket = minio.bucket if chat_id else minio.tmp_bucket
        assets = []
        upload_started = False

        def asset_id(filename: str) -> str:
            return hashlib.sha256(f"{identity}/{filename}".encode()).hexdigest()

        def image_url(filename: str) -> str:
            if chat_id:
                return f"/api/v1/chat/{quote(chat_id, safe='')}/files/{asset_id(filename)}/content"
            return minio.get_share_link_sync(f"{object_dir}/{filename}", bucket=bucket)

        source = {"file_id": identity, "filename": file_name, "file_url": source_url}

        def promote_source(attachment: dict) -> None:
            promote_chat_attachments_sync([attachment], user_id)
            reference = attachment.get("filepath") or attachment.get("file_path") or attachment.get("file_url") or ""
            if temp_object_name_from_url(reference, minio.tmp_bucket) and not attachment.get("object_name"):
                raise ValueError("workflow source attachment could not be retained")

        def save(state: str) -> None:
            WorkflowFileRepository.save_assets(
                chat_id=chat_id,
                user_id=user_id,
                workflow_id=workflow_id,
                source=source,
                assets=[{**item, "state": state} for item in assets],
                promote_source=promote_source,
                normalize_source=normalize_source,
            )

        def before_upload(filenames: list[str]) -> None:
            nonlocal upload_started
            if upload_started:
                raise ValueError("workflow image storage context cannot be reused; create a new attempt")
            upload_started = True
            assets[:] = [
                {"file_id": asset_id(name), "object_name": f"{object_dir}/{name}", "bucket": bucket, "state": "pending"}
                for name in filenames
            ]
            if chat_id:
                save("pending")

        def after_upload() -> None:
            if chat_id:
                save("ready")

        return ImageStorageContext(
            object_dir=object_dir,
            bucket_name=bucket,
            url_builder=image_url,
            before_upload=before_upload,
            after_upload=after_upload,
            rollback_on_failure=True,
        )
