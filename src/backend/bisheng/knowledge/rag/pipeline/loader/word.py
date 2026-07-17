import os

from langchain_core.documents import Document
from loguru import logger

from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.loader.utils.libreoffice_converter import (
    convert_doc_to_docx,
    convert_docx_to_pdf,
)
from bisheng.knowledge.rag.pipeline.loader.utils.md_from_docx import handler as docx_handler
from bisheng.knowledge.rag.pipeline.loader.utils.md_post_processing import post_processing


class BishengWordLoader(BaseBishengLoader):
    def __init__(self, retain_images: bool = True, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.retain_images = retain_images

    def load(self) -> list[Document]:

        input_file = self.file_path
        file_name = os.path.basename(self.file_path)

        if self.file_extension == "doc":
            input_file = convert_doc_to_docx(input_doc_path=input_file)
            if not input_file:
                raise Exception(
                    f"failed to convert {file_name} to docx, please check backend log"
                )
            # record preview file path
            self.preview_file_path = input_file

        md_file_name, local_image_dir, doc_id = docx_handler(self.tmp_dir, self.file_path)

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

        with open(md_file_name, encoding="utf-8") as f:
            content = f.read()
        content = self.rewrite_local_image_refs(content)

        self._build_pdf_preview()

        return [Document(page_content=content, metadata=self.file_metadata.copy())]

    def _build_pdf_preview(self) -> None:
        """Render the preview .docx to PDF for the frontend to display.

        The browser converts .docx to HTML, which loses e-seals and shape positioning;
        LibreOffice lays the page out the way Word does. Best-effort: the .docx preview
        remains as the fallback, so a conversion failure must not fail the parse of a
        file whose text extracted fine.
        """
        if not self.preview_file_path or not os.path.exists(self.preview_file_path):
            return
        try:
            pdf_path = convert_docx_to_pdf(
                input_path=self.preview_file_path,
                # Well under the parse pipeline's own budget: a preview is not worth
                # holding a worker thread for minutes.
                timeout=60,
            )
        except Exception:
            logger.exception(
                "failed to render pdf preview for %s; falling back to the docx preview",
                self.preview_file_path,
            )
            return
        if pdf_path and os.path.exists(pdf_path):
            self.pdf_preview_file_path = pdf_path
        else:
            logger.warning(
                "pdf preview conversion produced no file for %s; falling back to the docx preview",
                self.preview_file_path,
            )
