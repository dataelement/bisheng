import json
from functools import cached_property
from typing import Optional, List, Dict

from langchain_core.documents import BaseDocumentTransformer

from bisheng.api.v1.schemas import FileProcessBase
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.schemas.knowledge_rag_schema import Metadata
from bisheng.knowledge.rag.base_file_pipeline import BaseFilePipeline
from bisheng.knowledge.rag.pipeline.transformer.abstract import AbstractTransformer
from bisheng.knowledge.rag.pipeline.transformer.extra_file import ExtraFileTransformer
from bisheng.knowledge.rag.pipeline.transformer.preview_cache import PreviewCacheTransformer
from bisheng.knowledge.rag.pipeline.transformer.splitter import SplitterTransformer
from bisheng.knowledge.rag.pipeline.transformer.thumbnail import ThumbnailTransformer
from bisheng.user.domain.models.user import UserDao
from bisheng.utils.file import download_minio_file


class KnowledgeFilePipeline(BaseFilePipeline):

    def __init__(self, invoke_user_id: int, db_file: KnowledgeFile, preview_cache_key: Optional[str] = None,
                 no_summary: bool = False, need_thumbnail: bool = False, **kwargs):
        split_rule = FileProcessBase(knowledge_id=db_file.knowledge_id)
        if db_file.split_rule and isinstance(db_file.split_rule, str):
            split_rule = FileProcessBase(**json.loads(db_file.split_rule))
        split_rule.knowledge_id = db_file.knowledge_id

        super(KnowledgeFilePipeline, self).__init__(invoke_user_id, db_file.file_name, split_rule, **kwargs)
        self.db_file = db_file
        self.preview_cache_key = preview_cache_key
        self.no_summary = no_summary
        self.need_thumbnail = need_thumbnail

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
        ).model_dump(exclude_none=True)

    def prepare_local_file(self):
        self.local_file_path, _ = download_minio_file(
            object_name=self.db_file.object_name,
            root_dir=self.tmp_dir,
            calc_sha256=False
        )

    def _init_abstract_transformers(self) -> List[BaseDocumentTransformer]:
        if self.no_summary:
            return []
        return [AbstractTransformer(self.invoke_user_id, file_metadata=self.file_metadata, knowledge_file=self.db_file)]

    def _init_common_transformers(self) -> List[BaseDocumentTransformer]:
        abstract_transformers = self._init_abstract_transformers()
        abstract_transformers.append(ExtraFileTransformer(
            loader=self.loader,
            document_id=str(self.db_file.id),
            knowledge_id=self.db_file.knowledge_id,
            knowledge_file=self.db_file,
            retain_images=self.file_split_rule.retain_images == 1
        ))
        if self.need_thumbnail:
            abstract_transformers.append(ThumbnailTransformer(
                loader=self.loader,
                knowledge_file=self.db_file,
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
        abstract_transformers.append(ExtraFileTransformer(
            loader=self.loader,
            document_id=str(self.db_file.id),
            knowledge_id=self.db_file.knowledge_id,
            knowledge_file=self.db_file,
            retain_images=self.file_split_rule.retain_images == 1,
        ))
        abstract_transformers.append(PreviewCacheTransformer(
            preview_cache_key=self.preview_cache_key,
            file_metadata=self.file_metadata,
        ))
        return abstract_transformers
