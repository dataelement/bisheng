import os
from typing import List

from langchain_core.documents import Document

from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.loader.utils.md_from_html import HTML2MarkdownConverter
from bisheng.knowledge.rag.pipeline.loader.utils.md_post_processing import post_processing
from bisheng.utils import generate_uuid


class BishengHtmlLoader(BaseBishengLoader):

    def load(self) -> List[Document]:
        converter = HTML2MarkdownConverter(
            output_dir=self.tmp_dir,
            media_download_timeout=60,
        )
        md_file_path = converter.convert(self.file_path, output_filename_stem=generate_uuid())
        if not md_file_path or not os.path.exists(md_file_path):
            raise ValueError("convert html file to markdown, plase check server log")
        post_processing(md_file_path)

        with open(md_file_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.local_image_dir = converter.current_image_absolute_path
        return [Document(page_content=content, metadata=self.file_metadata.copy())]
