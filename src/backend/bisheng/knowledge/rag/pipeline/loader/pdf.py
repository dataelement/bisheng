import os
from typing import List

from langchain_core.documents import Document

from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.loader.utils.md_from_pdf import handler as pdf_handler
from bisheng.knowledge.rag.pipeline.loader.utils.md_post_processing import post_processing


class LocalPdfLoader(BaseBishengLoader):

    def __init__(self, retain_images: bool = True, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.retain_images = retain_images

    def load(self) -> List[Document]:

        md_file_name, local_image_dir, doc_id = pdf_handler(self.tmp_dir, self.file_path)

        if not os.path.exists(md_file_name):
            raise Exception(f"failed to convert pdf to md, please check server log")

        if self.retain_images and os.path.exists(local_image_dir):
            self.local_image_dir = local_image_dir

        post_processing(md_file_name, self.retain_images)

        with open(md_file_name, "r", encoding="utf-8") as f:
            content = f.read()
        return [Document(page_content=content, metadata=self.file_metadata.copy())]
