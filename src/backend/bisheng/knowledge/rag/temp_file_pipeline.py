import time
from functools import cached_property

from langchain_core.documents import BaseDocumentTransformer

from bisheng.api.v1.schemas import FileProcessBase
from bisheng.knowledge.domain.schemas.knowledge_rag_schema import Metadata
from bisheng.knowledge.rag.base_file_pipeline import BaseFilePipeline
from bisheng.knowledge.rag.pipeline.transformer.direct_chunk import DirectChunkTransformer
from bisheng.knowledge.rag.pipeline.transformer.hierarchical_splitter import HierarchicalSplitterTransformer
from bisheng.knowledge.rag.pipeline.transformer.image_upload import ImageUploadTransformer
from bisheng.knowledge.rag.pipeline.transformer.splitter import SplitterTransformer


class TempFilePipeline(BaseFilePipeline):
    def __init__(
        self, invoke_user_id: int, local_file_path: str, file_name: str, file_rule: FileProcessBase = None, **kwargs
    ):
        super().__init__(invoke_user_id, file_name, file_rule or FileProcessBase(knowledge_id=0), **kwargs)
        self.local_file_path = local_file_path

    @cached_property
    def file_metadata(self) -> dict:
        uploader_name = self._get_display_user_name(self.invoke_user_id)

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

    def _init_abstract_transformers(self) -> list[BaseDocumentTransformer]:
        if not self.image_storage:
            return []
        return [
            ImageUploadTransformer(
                loader=self.loader,
                document_id=self.image_storage.object_dir,
                knowledge_id=0,
                retain_images=self.file_split_rule.retain_images == 1,
                storage=self.image_storage,
            )
        ]

    def _init_common_transformers(self) -> list[BaseDocumentTransformer]:
        transformers = self._init_abstract_transformers()
        if not self.split_for_retrieval:
            return transformers
        if self.should_use_ppt_page_split():
            transformers.append(DirectChunkTransformer())
        elif self.should_use_hierarchical_split():
            transformers.append(
                HierarchicalSplitterTransformer(
                    hierarchy_level=self.file_split_rule.hierarchy_level,
                    append_title=self.file_split_rule.append_title,
                    max_chunk_size=self.file_split_rule.max_chunk_size,
                    fallback_separator=self.file_split_rule.separator,
                    fallback_separator_rule=self.file_split_rule.separator_rule,
                    fallback_chunk_size=self.file_split_rule.chunk_size,
                    fallback_chunk_overlap=self.get_splitter_kwargs()["chunk_overlap"],
                )
            )
        else:
            transformers.append(SplitterTransformer(**self.get_splitter_kwargs()))
        return transformers

    def _init_excel_transformers(self) -> list[BaseDocumentTransformer]:
        transformers = self._init_abstract_transformers()
        return transformers
