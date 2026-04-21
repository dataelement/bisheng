import os
from typing import List

from langchain_core.documents import Document

from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.loader.utils.libreoffice_converter import convert_doc_to_docx
from bisheng.knowledge.rag.pipeline.loader.utils.markdown_structure import parse_markdown_to_hierarchical_documents
from bisheng.knowledge.rag.pipeline.loader.utils.md_from_docx import handler as docx_handler
from bisheng.knowledge.rag.pipeline.loader.utils.md_post_processing import post_processing


class HierarchicalMarkdownLoader(BaseBishengLoader):

    def load(self) -> List[Document]:
        with open(self.file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return list(
            parse_markdown_to_hierarchical_documents(
                content=content,
                metadata=self.file_metadata.copy(),
                fallback_to_auto=False,
            )
        )


class HierarchicalWordLoader(BaseBishengLoader):
    def __init__(self, retain_images: bool = True, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.retain_images = retain_images

    def load(self) -> List[Document]:
        input_file = self.file_path
        file_name = os.path.basename(self.file_path)

        if self.file_extension == "doc":
            input_file = convert_doc_to_docx(input_doc_path=input_file)
            if not input_file:
                raise Exception(
                    f"failed to convert {file_name} to docx, please check backend log"
                )
            self.preview_file_path = input_file

        md_file_name, local_image_dir, _ = docx_handler(self.tmp_dir, input_file)

        if self.file_extension == "docx":
            docx_fixed_path = os.path.join(os.path.join(self.tmp_dir, "tmp"), os.path.basename(self.file_path))
            if os.path.exists(docx_fixed_path):
                self.preview_file_path = docx_fixed_path

        if self.retain_images:
            self.local_image_dir = local_image_dir

        if not md_file_name:
            raise Exception(f"failed to parse {file_name}, please check backend log")

        post_processing(
            file_path=md_file_name,
            retain_images=self.retain_images,
        )

        with open(md_file_name, "r", encoding="utf-8") as f:
            content = f.read()

        return list(
            parse_markdown_to_hierarchical_documents(
                content=content,
                metadata=self.file_metadata.copy(),
                fallback_to_auto=True,
            )
        )
