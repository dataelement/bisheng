import json
import tempfile
from functools import cached_property
from typing import Optional, List, Dict

from langchain_core.documents import BaseDocumentTransformer

from bisheng.api.v1.schemas import FileProcessBase
from bisheng.common.errcode.knowledge import KnowledgeFileNotSupportedError
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.schemas.knowledge_rag_schema import Metadata
from bisheng.knowledge.rag.pipeline.base import NormalPipeline, BasePipeline
from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.loader.excel import ExcelLoader
from bisheng.knowledge.rag.pipeline.loader.txt import BishengTextLoader
from bisheng.knowledge.rag.pipeline.transformer.abstract import AbstractTransformer
from bisheng.knowledge.rag.pipeline.types import PipelineResult, PipelineConfig
from bisheng.user.domain.models.user import UserDao
from bisheng.utils.file import download_minio_file

FileExtensionMap = {
    "xlsx": {
        "loader": "_init_excel_loader",
        "transformers": "_init_abstract_transformers"
    },
    "csv": {
        "loader": "_init_excel_loader",
        "transformers": "_init_abstract_transformers"
    },
    "xls": {
        "loader": "_init_excel_loader",
        "transformers": "_init_abstract_transformers"
    },
    "txt": {
        "loader": "_init_txt_loader",
        "transformers": "_init_abstract_transformers"
    },
    "md": {
        "loader": "_init_txt_loader",
        "transformers": "_init_abstract_transformers"
    },
    "html": {
        "loader": "_init_html_loader",
        "transformers": "_init_html_transformers"
    },
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

        self.milvus_vector, self.es_vector = self.init_vectore()

        # when run will be set value
        self.local_file_path: Optional[str] = None
        self.tmp_dir: Optional[str] = None

    def init_file_rule(self) -> FileProcessBase:
        split_rule = FileProcessBase(knowledge_id=self.db_file.knowledge_id)
        if self.db_file.split_rule and isinstance(self.db_file.split_rule, str):
            split_rule = FileProcessBase(**json.loads(self.db_file.split_rule))
        split_rule.knowledge_id = self.db_file.knowledge_id
        return split_rule

    def init_vectore(self):
        milvus_vector = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(self.invoke_user_id,
                                                                            knowledge_id=self.db_file.knowledge_id)
        es_vector = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge_id=self.db_file.knowledge_id)
        return milvus_vector, es_vector

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

    def run(self, config: PipelineConfig) -> PipelineResult:
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
            transformers = getattr(self, transformers_func)() if transformers_func else []
            pipeline = NormalPipeline(loader=loader, transformers=transformers, vector_store=[self.milvus_vector,
                                                                                              self.es_vector])
            return pipeline.run()

    def _get_loader_common_params(self) -> Dict:
        return {
            "file_path": self.local_file_path,
            "file_metadata": self.file_metadata,
            "tmp_dir": self.tmp_dir,
        }

    def _init_abstract_transformers(self) -> List[BaseDocumentTransformer]:
        if self.no_summary:
            return []
        return [AbstractTransformer(self.invoke_user_id)]

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
