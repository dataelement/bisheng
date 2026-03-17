import json
import tempfile
from functools import cached_property
from typing import Optional, List, Dict

from langchain_core.documents import BaseDocumentTransformer

from bisheng.api.v1.schemas import FileProcessBase
from bisheng.common.errcode.knowledge import KnowledgeFileNotSupportedError
from bisheng.common.services.config_service import settings
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, ParseType
from bisheng.knowledge.domain.schemas.knowledge_rag_schema import Metadata
from bisheng.knowledge.rag.pipeline.base import NormalPipeline, BasePipeline
from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.loader.etl4lm import Etl4lmLoader
from bisheng.knowledge.rag.pipeline.loader.excel import ExcelLoader
from bisheng.knowledge.rag.pipeline.loader.html import BishengHtmlLoader
from bisheng.knowledge.rag.pipeline.loader.pdf import LocalPdfLoader
from bisheng.knowledge.rag.pipeline.loader.ppt import BishengPptLoader
from bisheng.knowledge.rag.pipeline.loader.txt import BishengTextLoader
from bisheng.knowledge.rag.pipeline.loader.word import BishengWordLoader
from bisheng.knowledge.rag.pipeline.transformer.abstract import AbstractTransformer
from bisheng.knowledge.rag.pipeline.transformer.extra_file import ExtraFileTransformer
from bisheng.knowledge.rag.pipeline.transformer.preview_cache import PreviewCacheTransformer
from bisheng.knowledge.rag.pipeline.transformer.splitter import SplitterTransformer
from bisheng.knowledge.rag.pipeline.types import PipelineResult, PipelineConfig
from bisheng.user.domain.models.user import UserDao
from bisheng.utils.file import download_minio_file

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


class KnowledgeFilePipeline(BasePipeline):

    def __init__(self, invoke_user_id: int, db_file: KnowledgeFile, preview_cache_key: Optional[str] = None,
                 no_summary: bool = False, **kwargs):
        super(KnowledgeFilePipeline, self).__init__(**kwargs)
        self.invoke_user_id = invoke_user_id
        self.db_file = db_file
        self.preview_cache_key = preview_cache_key
        self.no_summary = no_summary

        self.file_name = db_file.file_name

        self.file_split_rule: FileProcessBase = self.init_file_rule()

        # when run will be set value
        self.local_file_path: Optional[str] = None
        self.tmp_dir: Optional[str] = None
        self.loader = None
        self.transformers = None

    def init_file_rule(self) -> FileProcessBase:
        split_rule = FileProcessBase(knowledge_id=self.db_file.knowledge_id)
        if self.db_file.split_rule and isinstance(self.db_file.split_rule, str):
            split_rule = FileProcessBase(**json.loads(self.db_file.split_rule))
        split_rule.knowledge_id = self.db_file.knowledge_id
        return split_rule

    @cached_property
    def file_extension(self):
        if self.file_name:
            return self.file_name.split(".")[-1].lower()
        else:
            return None

    @cached_property
    def file_metadata(self) -> Dict:
        uploader = UserDao.get_user(self.invoke_user_id)
        updater = uploader = uploader.user_name if uploader else None
        if self.db_file.updater_id:
            updater = UserDao.get_user(self.db_file.updater_id)
            updater = updater.user_name if updater else None

        return Metadata(
            document_id=self.db_file.id,
            document_name=self.file_name,
            knowledge_id=self.db_file.knowledge_id,
            upload_time=int(self.db_file.create_time.timestamp()),
            update_time=int(self.db_file.update_time.timestamp()),
            uploader=uploader,
            updater=updater,
            user_metadata=self.db_file.user_metadata,
        ).model_dump()

    def run(self, config: PipelineConfig = None) -> PipelineResult:
        with tempfile.TemporaryDirectory() as tmp_dir:
            # get file process config
            file_process_config = FileExtensionMap.get(self.file_extension)
            if not file_process_config:
                raise KnowledgeFileNotSupportedError()

            # download original file
            self.tmp_dir = tmp_dir
            self.local_file_path, _ = download_minio_file(object_name=self.db_file.object_name, root_dir=tmp_dir,
                                                          calc_sha256=False)

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

    def _init_abstract_transformers(self) -> List[BaseDocumentTransformer]:
        if self.no_summary:
            return []
        return [AbstractTransformer(self.invoke_user_id, preview_cache_key=self.preview_cache_key,
                                    file_metadata=self.file_metadata, knowledge_file=self.db_file)]

    def _init_common_transformers(self) -> List[BaseDocumentTransformer]:
        abstract_transformers = self._init_abstract_transformers()
        abstract_transformers.append(ExtraFileTransformer(
            loader=self.loader,
            document_id=str(self.db_file.id),
            knowledge_id=self.db_file.knowledge_id,
            knowledge_file=self.db_file,
            retain_images=self.file_split_rule.retain_images == 1
        ))
        abstract_transformers.append(SplitterTransformer(
            separator=self.file_split_rule.separator,
            separator_rule=self.file_split_rule.separator_rule,
            chunk_size=self.file_split_rule.chunk_size,
            chunk_overlap=self.file_split_rule.chunk_overlap
        ))
        abstract_transformers.append(PreviewCacheTransformer(
            preview_cache_key=self.preview_cache_key,
            file_metadata=self.file_metadata,
        ))
        return abstract_transformers

    def _init_excel_transformers(self) -> List[BaseDocumentTransformer]:
        abstract_transformers = self._init_abstract_transformers()
        abstract_transformers.append(PreviewCacheTransformer(
            preview_cache_key=self.preview_cache_key,
            file_metadata=self.file_metadata,
        ))
        return abstract_transformers

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
        if knowledge_conf.loader_provide == "etl4lm" and knowledge_conf.etl4lm.url:
            self.db_file.parse_type = ParseType.ETL4LM.value
            return Etl4lmLoader(
                **self._get_loader_common_params(),
                **knowledge_conf.etl4lm.model_dump()
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
