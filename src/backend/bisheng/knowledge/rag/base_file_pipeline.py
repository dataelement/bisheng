import tempfile
from abc import abstractmethod
from functools import cached_property

from bisheng.api.v1.schemas import FileProcessBase
from bisheng.common.errcode.knowledge import KnowledgeFileNotSupportedError
from bisheng.common.services.config_service import settings
from bisheng.knowledge.domain.models.knowledge_file import ParseType
from bisheng.knowledge.rag.pipeline.base import BasePipeline, NormalPipeline
from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.loader.etl4lm import Etl4lmLoader
from bisheng.knowledge.rag.pipeline.loader.excel import ExcelLoader
from bisheng.knowledge.rag.pipeline.loader.hierarchical import HierarchicalMarkdownLoader, HierarchicalWordLoader
from bisheng.knowledge.rag.pipeline.loader.html import BishengHtmlLoader
from bisheng.knowledge.rag.pipeline.loader.mineru import MineruLoader
from bisheng.knowledge.rag.pipeline.loader.ofd import OfdLoader
from bisheng.knowledge.rag.pipeline.loader.paddle_ocr import PaddleOcrLoader
from bisheng.knowledge.rag.pipeline.loader.pdf import LocalPdfLoader
from bisheng.knowledge.rag.pipeline.loader.ppt import BishengPptLoader
from bisheng.knowledge.rag.pipeline.loader.txt import BishengTextLoader
from bisheng.knowledge.rag.pipeline.loader.word import BishengWordLoader
from bisheng.knowledge.rag.pipeline.loader.x_create import XinChuangFormatterLoader
from bisheng.knowledge.rag.pipeline.types import PipelineConfig, PipelineResult

FileExtensionMap = {
    "xlsx": {"loader": "_init_excel_loader", "transformers": "_init_excel_transformers"},
    "csv": {"loader": "_init_excel_loader", "transformers": "_init_excel_transformers"},
    "xls": {"loader": "_init_excel_loader", "transformers": "_init_excel_transformers"},
    "et": {"loader": "_init_xcreate_loader", "transformers": "_init_excel_transformers"},
    "txt": {"loader": "_init_txt_loader", "transformers": "_init_common_transformers"},
    "md": {"loader": "_init_txt_loader", "transformers": "_init_common_transformers"},
    "html": {"loader": "_init_html_loader", "transformers": "_init_common_transformers"},
    "htm": {"loader": "_init_html_loader", "transformers": "_init_common_transformers"},
    "doc": {"loader": "_init_word_loader", "transformers": "_init_common_transformers"},
    "docx": {"loader": "_init_word_loader", "transformers": "_init_common_transformers"},
    "wps": {"loader": "_init_xcreate_loader", "transformers": "_init_common_transformers"},
    "ppt": {"loader": "_init_ppt_loader", "transformers": "_init_common_transformers"},
    "pptx": {"loader": "_init_ppt_loader", "transformers": "_init_common_transformers"},
    "dps": {"loader": "_init_xcreate_loader", "transformers": "_init_common_transformers"},
    "pdf": {"loader": "_init_pdf_loader", "transformers": "_init_common_transformers"},
    "ofd": {"loader": "_init_ofd_loader", "transformers": "_init_common_transformers"},
    "png": {"loader": "_init_image_loader", "transformers": "_init_common_transformers"},
    "jpg": {"loader": "_init_image_loader", "transformers": "_init_common_transformers"},
    "jpeg": {"loader": "_init_image_loader", "transformers": "_init_common_transformers"},
    "bmp": {"loader": "_init_image_loader", "transformers": "_init_common_transformers"},
}


class BaseFilePipeline(BasePipeline):
    hierarchical_file_exts = {"md", "doc", "docx"}
    ppt_page_split_exts = {"ppt", "pptx"}

    def __init__(self, invoke_user_id: int, file_name: str, file_rule: FileProcessBase, **kwargs):
        super().__init__(**kwargs)
        self.invoke_user_id = invoke_user_id
        self.file_name = file_name
        self.file_split_rule = file_rule

        self.local_file_path: str | None = getattr(self, "local_file_path", None)
        self.tmp_dir: str | None = getattr(self, "tmp_dir", None)
        self.loader = None
        self.transformers = None

    @cached_property
    def file_extension(self):
        if self.file_name:
            return self.file_name.split(".")[-1].lower()
        else:
            return None

    @cached_property
    def split_mode(self) -> str:
        split_mode = self.file_split_rule.split_mode or "auto"
        if split_mode == "hierarchical" and self.file_extension not in self.hierarchical_file_exts:
            return "auto"
        return split_mode

    def should_use_hierarchical_split(self) -> bool:
        return self.split_mode == "hierarchical" and self.file_extension in self.hierarchical_file_exts

    def should_use_ppt_page_split(self) -> bool:
        return self.split_mode == "auto" and self.file_extension in self.ppt_page_split_exts

    def get_splitter_kwargs(self) -> dict:
        chunk_overlap = self.file_split_rule.chunk_overlap
        if self.split_mode == "auto" and "chunk_overlap" not in self.file_split_rule.model_fields_set:
            chunk_overlap = 0

        return {
            "separator": self.file_split_rule.separator,
            "separator_rule": self.file_split_rule.separator_rule,
            "chunk_size": self.file_split_rule.chunk_size,
            "chunk_overlap": chunk_overlap,
        }

    @property
    @abstractmethod
    def file_metadata(self) -> dict:
        pass

    def prepare_local_file(self):
        """Override to download file if not already present."""
        pass

    def run(self, config: PipelineConfig = None) -> PipelineResult:
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_process_config = FileExtensionMap.get(self.file_extension)
            if not file_process_config:
                raise KnowledgeFileNotSupportedError()

            self.tmp_dir = tmp_dir
            self.prepare_local_file()

            # init loader and transformers
            loader_func = file_process_config.get("loader")
            transformers_func = file_process_config.get("transformers")
            loader = getattr(self, loader_func)()
            self.loader = loader
            transformers = getattr(self, transformers_func)() if transformers_func else []
            self.transformers = transformers
            pipeline = NormalPipeline(loader=loader, transformers=transformers, vector_store=self.vector_store)
            return pipeline.run(config)

    def _get_loader_common_params(self, file_path: str | None = None, file_extension: str | None = None) -> dict:
        return {
            "file_path": file_path or self.local_file_path,
            "file_metadata": self.file_metadata,
            "file_extension": file_extension or self.file_extension,
            "tmp_dir": self.tmp_dir,
            "image_object_dir": self._get_image_object_dir(),
        }

    def _get_image_object_dir(self) -> str | None:
        """MinIO object dir (relative to bucket) where loader uploads extracted images.

        Returning None keeps the loader writing local file paths and disables the
        bbox-aligned upload path — appropriate for transient pipelines that have no
        durable document_id (e.g., temp parsing).
        """
        return None

    def _init_excel_loader(self) -> BaseBishengLoader:
        return ExcelLoader(
            **self._get_loader_common_params(),
            header_rows=[
                self.file_split_rule.excel_rule.header_start_row,
                self.file_split_rule.excel_rule.header_end_row,
            ],
            data_rows=self.file_split_rule.excel_rule.slice_length,
            append_header=self.file_split_rule.excel_rule.append_header,
        )

    def _init_txt_loader(self) -> BaseBishengLoader:
        if self.should_use_hierarchical_split():
            return HierarchicalMarkdownLoader(
                **self._get_loader_common_params(),
            )
        return BishengTextLoader(
            **self._get_loader_common_params(),
        )

    def _init_html_loader(self) -> BaseBishengLoader:
        return BishengHtmlLoader(
            **self._get_loader_common_params(),
        )

    def _init_word_loader(self) -> BaseBishengLoader:
        if self.should_use_hierarchical_split():
            return HierarchicalWordLoader(
                **self._get_loader_common_params(), retain_images=self.file_split_rule.retain_images == 1
            )
        return BishengWordLoader(
            **self._get_loader_common_params(), retain_images=self.file_split_rule.retain_images == 1
        )

    def _init_ppt_loader(self) -> BaseBishengLoader:
        return BishengPptLoader(
            **self._get_loader_common_params(),
            retain_images=self.file_split_rule.retain_images == 1,
            page_chunk_mode=self.should_use_ppt_page_split(),
        )

    def _init_xcreate_loader(self) -> BaseBishengLoader:
        return XinChuangFormatterLoader(
            **self._get_loader_common_params(),
            retain_images=self.file_split_rule.retain_images == 1,
            header_rows=[
                self.file_split_rule.excel_rule.header_start_row,
                self.file_split_rule.excel_rule.header_end_row,
            ],
            data_rows=self.file_split_rule.excel_rule.slice_length,
            append_header=self.file_split_rule.excel_rule.append_header,
        )

    def _build_pdf_loader(self, file_path: str, file_extension: str) -> BaseBishengLoader:
        """Select and build the PDF loader for ``file_path`` (single source of truth).

        Used both for genuine PDF input (``_init_pdf_loader``) and for the PDF that
        OfdLoader produces from an OFD. ``file_extension`` is passed through so the
        image-loader path (``_init_image_loader`` → png/jpg/...) keeps its real
        extension, while OFD delegation passes ``"pdf"``.
        """
        knowledge_conf = settings.get_knowledge()
        common_params = self._get_loader_common_params(file_path=file_path, file_extension=file_extension)
        if knowledge_conf.loader_provider == ParseType.ETL4LM.value and knowledge_conf.etl4lm.url:
            if hasattr(self, "db_file") and self.db_file:
                self.db_file.parse_type = ParseType.ETL4LM.value
            return Etl4lmLoader(
                **common_params,
                filter_page_header_footer=self.file_split_rule.filter_page_header_footer == 1,
                **knowledge_conf.etl4lm.model_dump(),
            )
        elif knowledge_conf.loader_provider == ParseType.MINERU.value and knowledge_conf.mineru.url:
            if hasattr(self, "db_file") and self.db_file:
                self.db_file.parse_type = ParseType.MINERU.value
            return MineruLoader(
                **common_params,
                filter_page_header_footer=self.file_split_rule.filter_page_header_footer == 1,
                **knowledge_conf.mineru.model_dump(),
            )
        elif knowledge_conf.loader_provider == ParseType.PADDLE_OCR.value and knowledge_conf.paddle_ocr.url:
            if hasattr(self, "db_file") and self.db_file:
                self.db_file.parse_type = ParseType.PADDLE_OCR.value
            return PaddleOcrLoader(
                **common_params,
                filter_page_header_footer=self.file_split_rule.filter_page_header_footer == 1,
                **knowledge_conf.paddle_ocr.model_dump(),
            )
        return LocalPdfLoader(
            **common_params,
            retain_images=self.file_split_rule.retain_images == 1,
        )

    def _init_pdf_loader(self) -> BaseBishengLoader:
        return self._build_pdf_loader(self.local_file_path, self.file_extension)

    def _init_ofd_loader(self) -> BaseBishengLoader:
        # Convert OFD -> PDF in OfdLoader.load(), then delegate to the PDF loader
        # the pipeline would build for a real PDF (selection stays single-sourced).
        return OfdLoader(
            **self._get_loader_common_params(),
            pdf_loader_factory=lambda pdf_path: self._build_pdf_loader(pdf_path, "pdf"),
        )

    def _init_image_loader(self) -> BaseBishengLoader:
        pdf_loader = self._init_pdf_loader()
        if isinstance(pdf_loader, LocalPdfLoader):
            raise KnowledgeFileNotSupportedError()
        return pdf_loader
