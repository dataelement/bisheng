import os
from typing import List

from langchain_core.documents import Document

from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.loader.utils.libreoffice_converter import convert_ppt_to_pptx, convert_ppt_to_pdf
from bisheng.knowledge.rag.pipeline.loader.utils.md_from_pptx import handler as pptx_handler
from bisheng.knowledge.rag.pipeline.loader.utils.md_post_processing import post_processing


class BishengPptLoader(BaseBishengLoader):
    def __init__(self, retain_images: bool = True, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.retain_images = retain_images

    def load(self) -> List[Document]:
        input_file = self.file_path

        if self.file_extension == "ppt":
            input_file = convert_ppt_to_pptx(input_path=input_file)
            if not input_file:
                raise Exception("failed convert ppt to pptx, please check backend log")

        md_file_path, local_image_dir, doc_id = pptx_handler(
            cache_dir=self.tmp_dir,
            file_path=self.file_path,
        )
        if self.retain_images:
            self.local_image_dir = local_image_dir

        if not os.path.exists(md_file_path):
            raise Exception(f"convert {self.file_extension} to md error, please check backend log")
        post_processing(md_file_path, self.retain_images)

        pdf_file_path = convert_ppt_to_pdf(input_file)
        if os.path.exists(local_image_dir):
            self.preview_file_path = pdf_file_path

        with open(md_file_path, "r", encoding="utf-8") as f:
            content = f.read()

        return [Document(page_content=content, metadata=self.file_metadata.copy())]
