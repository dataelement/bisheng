import json
import os
from collections.abc import Sequence
from typing import Any

from langchain_core.documents import BaseDocumentTransformer, Document

from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils
from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader


class ExtraFileTransformer(BaseDocumentTransformer):
    """
    Upload the per-file preview artefact (docx/xlsx/pdf form) and the bbox
    JSON to MinIO.

    Image uploads moved to ``ImageUploadTransformer``.
    """

    def __init__(self, loader: BaseBishengLoader, document_id: str, knowledge_id: int | str,
                 knowledge_file: KnowledgeFile = None,
                 source_file_path: str | None = None) -> None:
        self.loader = loader
        self.document_id = document_id
        self.knoledge_id = knowledge_id
        self.knowledge_file = knowledge_file
        self.source_file_path = source_file_path

    def transform_documents(
            self, documents: Sequence[Document], **kwargs: Any
    ) -> Sequence[Document]:
        minio_client = get_minio_storage_sync()
        # upload preview file
        if self.loader.preview_file_path and os.path.exists(self.loader.preview_file_path):
            if self.knowledge_file:
                preview_file_object_name = KnowledgeUtils.get_knowledge_preview_file_object_name(
                    file_id=self.document_id, file_ext=self.loader.file_extension)
                if preview_file_object_name:
                    minio_client.put_object_sync(object_name=preview_file_object_name, file=self.loader.preview_file_path)
                    self.knowledge_file.preview_file_object_name = preview_file_object_name
            elif self.source_file_path:
                preview_file_object_name = KnowledgeUtils.get_tmp_preview_file_object_name(self.source_file_path)
                if preview_file_object_name:
                    minio_client.put_object_tmp_sync(
                        object_name=preview_file_object_name,
                        file=self.loader.preview_file_path,
                    )

        # upload bbox
        if self.knowledge_file and self.loader.bbox_list:
            file_bbox = {}
            for text_bbox in self.loader.bbox_list:
                bbox_key = "-".join([str(int(one)) for one in text_bbox.bbox])
                file_bbox[f"{text_bbox.page}-{bbox_key}"] = text_bbox.model_dump()
            file_bbox_object_name = KnowledgeUtils.get_knowledge_bbox_file_object_name(self.document_id)
            minio_client.put_object_sync(object_name=file_bbox_object_name,
                                         file=json.dumps(file_bbox, ensure_ascii=False).encode("utf-8"),
                                         content_type="application/json")
            self.knowledge_file.bbox_object_name = file_bbox_object_name

        return documents
