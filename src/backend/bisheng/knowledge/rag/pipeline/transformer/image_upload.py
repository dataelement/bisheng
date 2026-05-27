import os
from collections.abc import Sequence
from typing import Any

from langchain_core.documents import BaseDocumentTransformer, Document
from loguru import logger

from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils
from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader


class ImageUploadTransformer(BaseDocumentTransformer):
    """Upload every file under loader.local_image_dir to MinIO under target_dir.

    The mapping is by-name 1:1: ``{local_image_dir}/{fname}`` is uploaded to
    ``{target_dir}/{fname}``. Whether page_content gets rewritten depends on
    whether the loader pre-computed final URLs at load() time:

      - ``loader.image_object_dir`` is set (KnowledgeFilePipeline /
        PreviewFilePipeline): the loader already embedded final MinIO URLs in
        page_content; we only upload the bytes. metadata.indexes alignment is
        preserved by design.

      - ``loader.image_object_dir`` is unset (only legitimate for transient
        pipelines that should NOT inject this transformer; logged as a warning
        if it happens): the loader embedded absolute local paths; rewrite them
        to MinIO URLs after upload. metadata.indexes is not used by any
        consumer in this branch, so the length delta is harmless.
    """

    def __init__(
        self,
        loader: BaseBishengLoader,
        document_id: str,
        knowledge_id: int | str,
        retain_images: bool = True,
    ) -> None:
        self.loader = loader
        self.document_id = document_id
        self.knowledge_id = knowledge_id
        self.retain_images = retain_images

    def transform_documents(
        self, documents: Sequence[Document], **kwargs: Any
    ) -> Sequence[Document]:
        if not self.retain_images:
            return documents
        local_dir = self.loader.local_image_dir
        if not local_dir or not os.path.exists(local_dir):
            return documents

        files = [
            f for f in os.listdir(local_dir)
            if os.path.isfile(os.path.join(local_dir, f))
        ]
        if not files:
            return documents

        if not self.loader.image_object_dir:
            # Sanity guard: only KnowledgeFilePipeline / PreviewFilePipeline
            # should wire this transformer in, and both override
            # _get_image_object_dir to a non-None value. Hitting this branch
            # means a misconfigured pipeline is about to write images to a
            # synthetic dir derived from document_id/knowledge_id, polluting
            # the persistent bucket without proper isolation.
            logger.warning(
                "ImageUploadTransformer invoked with loader.image_object_dir=None "
                "(document_id=%s, knowledge_id=%s) -- falling back to "
                "KnowledgeUtils.get_knowledge_file_image_dir",
                self.document_id,
                self.knowledge_id,
            )

        target_dir = self.loader.image_object_dir or (
            KnowledgeUtils.get_knowledge_file_image_dir(
                self.document_id, self.knowledge_id
            )
        )

        minio = get_minio_storage_sync()
        for fname in files:
            local_path = os.path.join(local_dir, fname)
            minio.put_object_sync(
                object_name=f"{target_dir}/{fname}",
                file=local_path,
                bucket_name=minio.bucket,
            )

        if not self.loader.image_object_dir:
            # Fallback branch: loader embedded local absolute paths; rewrite.
            url_prefix = f"/{minio.bucket}/{target_dir}"
            for doc in documents:
                doc.page_content = doc.page_content.replace(local_dir, url_prefix)

        return documents
