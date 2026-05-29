import os

from langchain_core.documents import Document

from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.loader.utils.md_from_pdf import handler as pdf_handler
from bisheng.knowledge.rag.pipeline.loader.utils.md_post_processing import post_processing


class LocalPdfLoader(BaseBishengLoader):

    def __init__(self, retain_images: bool = True, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.retain_images = retain_images

    def load(self) -> list[Document]:

        md_file_name, local_image_dir, doc_id = pdf_handler(self.tmp_dir, self.file_path)

        if not os.path.exists(md_file_name):
            raise Exception("failed to convert pdf to md, please check server log")

        if self.retain_images and os.path.exists(local_image_dir):
            self.local_image_dir = local_image_dir

        post_processing(md_file_name, self.retain_images)

        with open(md_file_name, encoding="utf-8") as f:
            content = f.read()
        content = self.rewrite_local_image_refs(content)
        return [Document(page_content=content, metadata=self.file_metadata.copy())]
