import tempfile
from abc import abstractmethod
from functools import cached_property
from typing import Optional, Dict

from bisheng.api.v1.schemas import FileProcessBase
from bisheng.common.errcode.knowledge import KnowledgeFileNotSupportedError
from bisheng.common.services.config_service import settings
from bisheng.knowledge.domain.models.knowledge_file import ParseType
from bisheng.knowledge.rag.pipeline.base import BasePipeline, NormalPipeline
from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.loader.etl4lm import Etl4lmLoader
from bisheng.knowledge.rag.pipeline.loader.excel import ExcelLoader
from bisheng.knowledge.rag.pipeline.loader.html import BishengHtmlLoader
from bisheng.knowledge.rag.pipeline.loader.mineru import MineruLoader
from bisheng.knowledge.rag.pipeline.loader.paddle_ocr import PaddleOcrLoader
from bisheng.knowledge.rag.pipeline.loader.pdf import LocalPdfLoader
from bisheng.knowledge.rag.pipeline.loader.ppt import BishengPptLoader
from bisheng.knowledge.rag.pipeline.loader.txt import BishengTextLoader
from bisheng.knowledge.rag.pipeline.loader.word import BishengWordLoader
from bisheng.knowledge.rag.pipeline.types import PipelineConfig, PipelineResult

FileExtensionMap = {
    "xlsx": {"loader": "_init_excel_loader", "transformers": "_init_excel_transformers"},
    "csv": {"loader": "_init_excel_loader", "transformers": "_init_excel_transformers"},
    "xls": {"loader": "_init_excel_loader", "transformers": "_init_excel_transformers"},
    "txt": {"loader": "_init_txt_loader", "transformers": "_init_common_transformers"},
    "md": {"loader": "_init_txt_loader", "transformers": "_init_common_transformers"},
    "html": {"loader": "_init_html_loader", "transformers": "_init_common_transformers"},
    "htm": {"loader": "_init_html_loader", "transformers": "_init_common_transformers"},
    "doc": {"loader": "_init_word_loader", "transformers": "_init_common_transformers"},
    "docx": {"loader": "_init_word_loader", "transformers": "_init_common_transformers"},
    "ppt": {"loader": "_init_ppt_loader", "transformers": "_init_common_transformers"},
    "pptx": {"loader": "_init_ppt_loader", "transformers": "_init_common_transformers"},
    "pdf": {"loader": "_init_pdf_loader", "transformers": "_init_common_transformers"},
    "png": {"loader": "_init_image_loader", "transformers": "_init_common_transformers"},
    "jpg": {"loader": "_init_image_loader", "transformers": "_init_common_transformers"},
    "jpeg": {"loader": "_init_image_loader", "transformers": "_init_common_transformers"},
    "bmp": {"loader": "_init_image_loader", "transformers": "_init_common_transformers"},
}


class BaseFilePipeline(BasePipeline):

    def __init__(self, invoke_user_id: int, file_name: str, file_rule: FileProcessBase, **kwargs):
        super(BaseFilePipeline, self).__init__(**kwargs)
        self.invoke_user_id = invoke_user_id
        self.file_name = file_name
        self.file_split_rule = file_rule

        self.local_file_path: Optional[str] = getattr(self, 'local_file_path', None)
        self.tmp_dir: Optional[str] = getattr(self, 'tmp_dir', None)
        self.loader = None
        self.transformers = None

    @cached_property
    def file_extension(self):
        if self.file_name:
            return self.file_name.split(".")[-1].lower()
        else:
            return None

    @property
    @abstractmethod
    def file_metadata(self) -> Dict:
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

    def _get_loader_common_params(self) -> Dict:
        return {
            "file_path": self.local_file_path,
            "file_metadata": self.file_metadata,
            "file_extension": self.file_extension,
            "tmp_dir": self.tmp_dir,
        }

    def _init_excel_loader(self) -> BaseBishengLoader:
        return ExcelLoader(
            **self._get_loader_common_params(),
            header_rows=[self.file_split_rule.excel_rule.header_start_row,
                         self.file_split_rule.excel_rule.header_end_row],
            data_rows=self.file_split_rule.excel_rule.slice_length,
            append_header=self.file_split_rule.excel_rule.append_header
        )

    def _init_txt_loader(self) -> BaseBishengLoader:
        return BishengTextLoader(
            **self._get_loader_common_params(),
        )

    def _init_html_loader(self) -> BaseBishengLoader:
        return BishengHtmlLoader(
            **self._get_loader_common_params(),
        )

    def _init_word_loader(self) -> BaseBishengLoader:
        return BishengWordLoader(
            **self._get_loader_common_params(),
            retain_images=self.file_split_rule.retain_images == 1
        )

    def _init_ppt_loader(self) -> BaseBishengLoader:
        return BishengPptLoader(
            **self._get_loader_common_params(),
            retain_images=self.file_split_rule.retain_images == 1
        )

    def _init_pdf_loader(self) -> BaseBishengLoader:
        knowledge_conf = settings.get_knowledge()
        if knowledge_conf.loader_provider == ParseType.ETL4LM.value and knowledge_conf.etl4lm.url:
            if hasattr(self, 'db_file') and self.db_file:
                self.db_file.parse_type = ParseType.ETL4LM.value
            return Etl4lmLoader(
                **self._get_loader_common_params(),
                **knowledge_conf.etl4lm.model_dump()
            )
        elif knowledge_conf.loader_provider == ParseType.MINERU.value and knowledge_conf.mineru.url:
            if hasattr(self, 'db_file') and self.db_file:
                self.db_file.parse_type = ParseType.MINERU.value
            return MineruLoader(
                **self._get_loader_common_params(),
                **knowledge_conf.mineru.model_dump()
            )
        elif knowledge_conf.loader_provider == ParseType.PADDLE_OCR.value and knowledge_conf.paddle_ocr.url:
            if hasattr(self, 'db_file') and self.db_file:
                self.db_file.parse_type = ParseType.MINERU.value
            return PaddleOcrLoader(
                **self._get_loader_common_params(),
                **knowledge_conf.paddle_ocr.model_dump()
            )
        return LocalPdfLoader(
            **self._get_loader_common_params(),
            retain_images=self.file_split_rule.retain_images == 1
        )

    def _init_image_loader(self) -> BaseBishengLoader:
        pdf_loader = self._init_pdf_loader()
        if isinstance(pdf_loader, LocalPdfLoader):
            raise KnowledgeFileNotSupportedError()
        return pdf_loader
