import time
from functools import cached_property
from typing import List, Dict

from langchain_core.documents import BaseDocumentTransformer

from bisheng.api.v1.schemas import FileProcessBase
from bisheng.knowledge.domain.schemas.knowledge_rag_schema import Metadata
from bisheng.knowledge.rag.base_file_pipeline import BaseFilePipeline
from bisheng.knowledge.rag.pipeline.transformer.abstract import AbstractTransformer
from bisheng.knowledge.rag.pipeline.transformer.extra_file import ExtraFileTransformer
from bisheng.knowledge.rag.pipeline.transformer.splitter import SplitterTransformer
from bisheng.user.domain.models.user import UserDao
from bisheng.utils import generate_uuid


class PreviewFilePipeline(BaseFilePipeline):
    """
    Pipeline for generating file preview chunks prior to knowledge base ingestion.

    This pipeline loads a locally available file, applies splitting transformers,
    and returns the resulting document chunks. It does NOT perform summarisation,
    thumbnail generation, or vector-store operations — those belong to
    ``KnowledgeFilePipeline`` which is invoked only after the user confirms the
    preview and triggers the actual ingest.

    The resulting chunks are stored in Redis by the calling service so that the
    user can review and edit them before confirming upload.
    """

    def __init__(
            self,
            invoke_user_id: int,
            local_file_path: str,
            file_name: str,
            knowledge_id: int,
            file_rule: FileProcessBase = None,
            **kwargs,
    ):
        super(PreviewFilePipeline, self).__init__(
            invoke_user_id,
            file_name,
            file_rule or FileProcessBase(knowledge_id=0),
            **kwargs,
        )
        self.local_file_path = local_file_path
        self.knowledge_id = knowledge_id

    @cached_property
    def file_metadata(self) -> Dict:
        uploader = UserDao.get_user(self.invoke_user_id)
        uploader_name = uploader.user_name if uploader else None

        now = int(time.time())
        return Metadata(
            document_id=0,
            document_name=self.file_name,
            knowledge_id=self.file_split_rule.knowledge_id,
            upload_time=now,
            update_time=now,
            uploader=uploader_name,
            updater=uploader_name,
            user_metadata={},
        ).model_dump(exclude_none=True)

    def _init_abstract_transformers(self) -> List[BaseDocumentTransformer]:
        return [AbstractTransformer(self.invoke_user_id, file_metadata=self.file_metadata)]

    def _init_common_transformers(self) -> List[BaseDocumentTransformer]:
        transformers = self._init_abstract_transformers()
        transformers.append(ExtraFileTransformer(
            loader=self.loader,
            document_id=generate_uuid(),
            knowledge_id=self.knowledge_id,
            knowledge_file=None,
            retain_images=self.file_split_rule.retain_images == 1
        ))
        transformers.append(
            SplitterTransformer(
                separator=self.file_split_rule.separator,
                separator_rule=self.file_split_rule.separator_rule,
                chunk_size=self.file_split_rule.chunk_size,
                chunk_overlap=self.file_split_rule.chunk_overlap,
            )
        )
        return transformers

    def _init_excel_transformers(self) -> List[BaseDocumentTransformer]:
        return self._init_abstract_transformers()
