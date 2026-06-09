"""OfdLoader: convert OFD to PDF, then delegate parsing to a PDF loader.

Mirrors XinChuangFormatterLoader: the converted PDF doubles as the preview file
(uploaded to ``preview/{id}.pdf`` by ExtraFileTransformer), and parsing is
delegated to whichever PDF loader the pipeline selects (ETL4LM / MinerU /
PaddleOCR / LocalPDF) — kept single-sourced via an injected factory.
"""

from collections.abc import Callable

from langchain_core.documents import Document

from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.loader.utils.ofd_converter import convert_ofd_to_pdf


class OfdLoader(BaseBishengLoader):
    def __init__(
        self,
        pdf_loader_factory: Callable[[str], BaseBishengLoader],
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        # callable(pdf_path) -> BaseBishengLoader; built by the pipeline so the
        # PDF loader selection logic stays in one place.
        self._pdf_loader_factory = pdf_loader_factory

    def load(self) -> list[Document]:
        pdf_path = convert_ofd_to_pdf(self.file_path, self.tmp_dir)

        delegate = self._pdf_loader_factory(pdf_path)
        documents = delegate.load()

        self.local_image_dir = delegate.local_image_dir
        self.bbox_list = delegate.bbox_list
        # Preview is the converted PDF (the original is .ofd, which the browser
        # PDF viewer cannot render).
        self.preview_file_path = pdf_path
        return documents
