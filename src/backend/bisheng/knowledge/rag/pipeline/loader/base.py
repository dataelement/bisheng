import os
from typing import List, Optional

from langchain_core.document_loaders import BaseLoader

from bisheng.knowledge.rag.pipeline.types import TextBbox


class BaseBishengLoader(BaseLoader):
    def __init__(self, file_path: str, file_metadata: dict, file_extension: str, tmp_dir: str,
                 image_object_dir: Optional[str] = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.file_path = file_path
        self.file_name = os.path.basename(file_path)
        self.file_metadata = file_metadata or {}
        self.file_extension = file_extension

        # tmp_dir is used to store images in original file.
        # Delete the temporary directory after the pipeline finishes execution.
        self.tmp_dir = tmp_dir

        # MinIO object dir (relative to bucket) where extracted images will be uploaded.
        # When set, the loader uploads images during load() and writes the final MinIO
        # URL into page_content, so chunk_bbox alignment via metadata.indexes stays
        # consistent through the splitter. When None, images stay as local file paths
        # (callers must handle upload separately).
        self.image_object_dir = image_object_dir

        # If the source file contains images, the image dir path is an absolute path to the temporary directory.
        self.local_image_dir = None
        # original file -> preview file path; will be upload to minio
        self.preview_file_path = None
        # bbox_list
        self.bbox_list: List[TextBbox] = []

    def upload_image_to_minio(self, local_path: str, file_name: Optional[str] = None) -> str:
        """Upload a locally-saved image to MinIO and return the chunk-ready URL.

        Falls back to returning the local path unchanged when image_object_dir is not
        configured (e.g., temp pipelines that never persist).
        """
        if not self.image_object_dir:
            return local_path
        from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync

        if file_name is None:
            file_name = os.path.basename(local_path)
        minio_client = get_minio_storage_sync()
        object_name = f"{self.image_object_dir}/{file_name}"
        minio_client.put_object_sync(
            object_name=object_name, file=local_path, bucket_name=minio_client.bucket
        )
        return f"/{minio_client.bucket}/{object_name}"
