from typing import List

from langchain_core.document_loaders import BaseLoader

from bisheng.knowledge.rag.pipeline.types import TextBbox


class BaseBishengLoader(BaseLoader):
    def __init__(self, file_path: str, file_metadata: dict, tmp_dir: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.file_path = file_path
        self.file_metadata = file_metadata or {}

        # tmp_dir is used to store images in original file.
        # Delete the temporary directory after the pipeline finishes execution.
        # If the source file contains images, the image path is an absolute path to the temporary directory.
        self.tmp_dir = tmp_dir
        # original file -> preview file path; will be upload to minio
        self.preview_file_path = None
        # bbox_list
        self.bbox_list: List[TextBbox] = []
