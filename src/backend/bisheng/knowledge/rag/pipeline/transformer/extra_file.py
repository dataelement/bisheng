import json
import os
from typing import Any, Sequence

from langchain_core.documents import BaseDocumentTransformer, Document

from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils
from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader


class ExtraFileTransformer(BaseDocumentTransformer):
    """
    Upload a preview file or images from the file to minio.
    """

    def __init__(self, loader: BaseBishengLoader, document_id: str, knowledge_id: int | str,
                 knowledge_file: KnowledgeFile = None, retain_images: bool = True) -> None:
        self.loader = loader
        self.document_id = document_id
        self.knoledge_id = knowledge_id
        self.knowledge_file = knowledge_file
        self.retain_images = retain_images

    def transform_documents(
            self, documents: Sequence[Document], **kwargs: Any
    ) -> Sequence[Document]:
        minio_client = get_minio_storage_sync()
        # upload preview file
        if self.knowledge_file and self.loader.preview_file_path and os.path.exists(self.loader.preview_file_path):
            preview_file_object_name = KnowledgeUtils.get_knowledge_preview_file_object_name(
                file_id=self.document_id, file_ext=self.loader.file_extension)
            if preview_file_object_name:
                minio_client.put_object_sync(object_name=preview_file_object_name, file=self.loader.preview_file_path)
                self.knowledge_file.preview_file_object_name = preview_file_object_name

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

        # upload image in file
        if self.retain_images and self.loader.local_image_dir:
            files = [f for f in os.listdir(self.loader.local_image_dir)]
            local_image_object_dir = KnowledgeUtils.get_knowledge_file_image_dir(self.document_id, self.knoledge_id)
            for file_name in files:
                local_file_name = f"{self.loader.local_image_dir}/{file_name}"
                object_name = f"{local_image_object_dir}/{file_name}"
                minio_client.put_object_sync(
                    object_name=object_name, file=local_file_name, bucket_name=minio_client.bucket
                )

            if len(files) > 0:
                # convert local image path to minio path
                for item in documents:
                    item.page_content = item.page_content.replace(self.loader.local_image_dir,
                                                                  f"/{minio_client.bucket}/{local_image_object_dir}")

        return documents
