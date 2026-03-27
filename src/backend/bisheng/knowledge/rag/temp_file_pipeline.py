import time
from functools import cached_property
from typing import List, Dict

from langchain_core.documents import BaseDocumentTransformer

from bisheng.api.v1.schemas import FileProcessBase
from bisheng.knowledge.domain.schemas.knowledge_rag_schema import Metadata
from bisheng.knowledge.rag.base_file_pipeline import BaseFilePipeline
from bisheng.knowledge.rag.pipeline.transformer.splitter import SplitterTransformer
from bisheng.user.domain.models.user import UserDao


class TempFilePipeline(BaseFilePipeline):

    def __init__(self, invoke_user_id: int, local_file_path: str, file_name: str,
                 file_rule: FileProcessBase = None, **kwargs):
        super(TempFilePipeline, self).__init__(invoke_user_id, file_name, file_rule or FileProcessBase(knowledge_id=0),
                                               **kwargs)
        self.local_file_path = local_file_path

    @cached_property
    def file_metadata(self) -> Dict:
        uploader = UserDao.get_user(self.invoke_user_id)
        uploader_name = uploader.user_name if uploader else None

        now = int(time.time())
        return Metadata(
            document_id=0,
            document_name=self.file_name,
            knowledge_id=0,
            upload_time=now,
            update_time=now,
            uploader=uploader_name,
            updater=uploader_name,
            user_metadata={},
        ).model_dump(exclude_none=True)

    def _init_abstract_transformers(self) -> List[BaseDocumentTransformer]:
        return []

    def _init_common_transformers(self) -> List[BaseDocumentTransformer]:
        transformers = self._init_abstract_transformers()
        transformers.append(SplitterTransformer(
            separator=self.file_split_rule.separator,
            separator_rule=self.file_split_rule.separator_rule,
            chunk_size=self.file_split_rule.chunk_size,
            chunk_overlap=self.file_split_rule.chunk_overlap
        ))
        return transformers

    def _init_excel_transformers(self) -> List[BaseDocumentTransformer]:
        transformers = self._init_abstract_transformers()
        return transformers
