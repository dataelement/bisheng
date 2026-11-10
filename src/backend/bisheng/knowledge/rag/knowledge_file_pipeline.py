import hashlib
import json
from dataclasses import dataclass, field
from functools import cached_property

from langchain_core.documents import BaseDocumentTransformer, Document

from bisheng.api.v1.schemas import FileProcessBase
from bisheng.knowledge.application.file_processing_adapter import legacy_rule_from_snapshot
from bisheng.knowledge.domain.models.knowledge_file import FileSource, KnowledgeFile
from bisheng.knowledge.domain.schemas.knowledge_rag_schema import Metadata
from bisheng.knowledge.domain.schemas.processing_settings import EffectiveProcessingSnapshot
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils
from bisheng.knowledge.rag.base_file_pipeline import BaseFilePipeline
from bisheng.knowledge.rag.pipeline.transformer.abstract import AbstractTransformer
from bisheng.knowledge.rag.pipeline.transformer.content_safety import ContentSafetyTransformer
from bisheng.knowledge.rag.pipeline.transformer.direct_chunk import DirectChunkTransformer
from bisheng.knowledge.rag.pipeline.transformer.extra_file import ExtraFileTransformer
from bisheng.knowledge.rag.pipeline.transformer.file_encoding import FileEncodingTransformer
from bisheng.knowledge.rag.pipeline.transformer.hierarchical_splitter import HierarchicalSplitterTransformer
from bisheng.knowledge.rag.pipeline.transformer.image_upload import ImageUploadTransformer
from bisheng.knowledge.rag.pipeline.transformer.preview_cache import PreviewCacheTransformer
from bisheng.knowledge.rag.pipeline.transformer.simhash import SimHashTransformer
from bisheng.knowledge.rag.pipeline.transformer.splitter import SplitterTransformer
from bisheng.knowledge.rag.pipeline.transformer.thumbnail import ThumbnailTransformer
from bisheng.sensitive_word.domain.schemas import SensitiveWordBusinessType
from bisheng.sensitive_word.domain.services.sensitive_word_policy_service import SensitiveWordPolicyService
from bisheng.user.domain.models.user import UserDao
from bisheng.utils.file import download_minio_file

_WEB_LINK_SEPARATORS = ["\n\n", "\n", "。", "\\.", "，", ",", "；", ";", "、", "\\s+", ""]  # noqa: RUF001
_WEB_LINK_SEPARATOR_RULES = ["after"] * len(_WEB_LINK_SEPARATORS)

FILE_PROCESSING_PATCH_FIELDS = frozenset(
    {
        "parse_type",
        "preview_file_object_name",
        "bbox_object_name",
        "abstract",
        "user_metadata",
        "simhash",
        "similar_status",
        "file_encoding",
        "thumbnails",
    }
)


def physical_processing_source_digest(row):
    fields = (
        "id",
        "tenant_id",
        "knowledge_id",
        "file_type",
        "file_source",
        "object_name",
        "md5",
        "file_size",
        "file_name",
        "file_level_path",
        "user_metadata",
    )
    return hashlib.sha256(
        json.dumps(
            {key: getattr(row, key) for key in fields},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class PreparedFileProcessing:
    file_id: int
    tenant_id: int
    space_id: int
    model_config_revision: int
    index_generation: str
    physical_source_digest: str
    source_revision: str
    documents: tuple[Document, ...] = field(repr=False)
    file_patch: dict = field(repr=False)
    status: int = 2
    error_code: int | None = None


@dataclass(frozen=True, slots=True)
class FileProcessingResult:
    file_id: int
    source_revision: str
    status: int
    chunk_count: int
    file_patch: dict = field(default_factory=dict, repr=False)
    error_code: int | None = None

    @property
    def succeeded(self):
        return self.status == 2


class KnowledgeFilePipeline(BaseFilePipeline):
    def __init__(
        self,
        invoke_user_id: int,
        db_file: KnowledgeFile,
        preview_cache_key: str | None = None,
        no_summary: bool = False,
        need_thumbnail: bool = False,
        effective_processing: EffectiveProcessingSnapshot | None = None,
        **kwargs,
    ):
        split_rule = FileProcessBase(knowledge_id=db_file.knowledge_id)
        if effective_processing is not None:
            split_rule = legacy_rule_from_snapshot(effective_processing, space_id=db_file.knowledge_id)
        elif db_file.split_rule and isinstance(db_file.split_rule, str):
            split_rule = FileProcessBase(**json.loads(db_file.split_rule))
        split_rule.knowledge_id = db_file.knowledge_id
        if db_file.file_source == FileSource.WEB_LINK.value:
            split_rule.separator = _WEB_LINK_SEPARATORS
            split_rule.separator_rule = _WEB_LINK_SEPARATOR_RULES
            split_rule.chunk_overlap = 0

        super().__init__(invoke_user_id, db_file.file_name, split_rule, **kwargs)
        self.db_file = db_file
        self.preview_cache_key = preview_cache_key
        self.no_summary = no_summary
        self.need_thumbnail = need_thumbnail

    @cached_property
    def file_extension(self):
        if self.db_file.file_source == FileSource.WEB_LINK.value:
            return "md"
        if self.file_name:
            return self.file_name.split(".")[-1].lower()
        return None

    @cached_property
    def file_metadata(self) -> dict:
        uploader = UserDao.get_user(self.invoke_user_id)
        updater = uploader = uploader.user_name if uploader else None
        if self.db_file.updater_id:
            updater = UserDao.get_user(self.db_file.updater_id)
            updater = updater.user_name if updater else None

        metadata = Metadata(
            document_id=self.db_file.id,
            document_name=self.file_name,
            knowledge_id=self.db_file.knowledge_id,
            upload_time=int(self.db_file.create_time.timestamp()),
            update_time=int(self.db_file.update_time.timestamp()),
            uploader=uploader,
            updater=updater,
            user_metadata=self.db_file.user_metadata,
        ).model_dump(exclude_none=True)

        # Always emit `abstract`, even when summary extraction is off. The
        # AbstractTransformer only adds this key when an abstract LLM is
        # configured, so `exclude_none` would otherwise drop it entirely.
        # Legacy collections (created before `abstract` became nullable in
        # KNOWLEDGE_RAG_METADATA_SCHEMA) declare `abstract` as a required field;
        # omitting it makes Milvus reject the insert with "Insert missed an
        # field `abstract`". Keeping the key always present (default "") keeps
        # those legacy collections writable and matches the rebuild path.
        metadata.setdefault("abstract", self.db_file.abstract or "")
        # Rebuilds created by older code could infer `user_metadata` as a
        # required Milvus field. SQL NULL is removed by `exclude_none=True`,
        # so normalize it to an empty JSON object for those collections.
        metadata.setdefault("user_metadata", self.db_file.user_metadata or {})
        return metadata

    def prepare_local_file(self):
        self.local_file_path, _ = download_minio_file(
            object_name=self.db_file.object_name, root_dir=self.tmp_dir, calc_sha256=False
        )

    def _get_image_object_dir(self) -> str | None:
        return KnowledgeUtils.get_knowledge_file_image_dir(str(self.db_file.id), self.db_file.knowledge_id)

    def _init_abstract_transformers(self) -> list[BaseDocumentTransformer]:
        if self.no_summary:
            return []
        return [AbstractTransformer(self.invoke_user_id, file_metadata=self.file_metadata, knowledge_file=self.db_file)]

    def _init_content_safety_transformers(self) -> list[BaseDocumentTransformer]:
        tenant_id = self.db_file.tenant_id or 1
        if not SensitiveWordPolicyService.is_effective(
            tenant_id=tenant_id,
            business_type=SensitiveWordBusinessType.KNOWLEDGE_SPACE_FILE_PARSE,
        ):
            return []
        return [ContentSafetyTransformer(tenant_id=tenant_id)]

    def _init_common_transformers(self) -> list[BaseDocumentTransformer]:
        abstract_transformers = self._init_content_safety_transformers()
        abstract_transformers.extend(self._init_abstract_transformers())
        # FileEncodingTransformer runs right after AbstractTransformer (in _init_abstract_transformers),
        # using the abstract field for LLM classification. When shougang is disabled it skips internally.
        abstract_transformers.append(
            FileEncodingTransformer(
                invoke_user_id=self.invoke_user_id,
                knowledge_file=self.db_file,
            )
        )
        abstract_transformers.append(SimHashTransformer(knowledge_file=self.db_file))
        abstract_transformers.append(
            ExtraFileTransformer(
                loader=self.loader,
                document_id=str(self.db_file.id),
                knowledge_id=self.db_file.knowledge_id,
                knowledge_file=self.db_file,
            )
        )
        abstract_transformers.append(
            ImageUploadTransformer(
                loader=self.loader,
                document_id=str(self.db_file.id),
                knowledge_id=self.db_file.knowledge_id,
                retain_images=self.file_split_rule.retain_images == 1,
            )
        )
        if self.need_thumbnail:
            abstract_transformers.append(
                ThumbnailTransformer(
                    loader=self.loader,
                    knowledge_file=self.db_file,
                )
            )
        if self.should_use_ppt_page_split():
            abstract_transformers.append(DirectChunkTransformer())
        elif self.should_use_hierarchical_split():
            abstract_transformers.append(
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
            abstract_transformers.append(SplitterTransformer(**self.get_splitter_kwargs()))
        abstract_transformers.append(
            PreviewCacheTransformer(
                preview_cache_key=self.preview_cache_key,
                file_metadata=self.file_metadata,
            )
        )
        return abstract_transformers

    def _init_excel_transformers(self) -> list[BaseDocumentTransformer]:
        abstract_transformers = self._init_content_safety_transformers()
        abstract_transformers.extend(self._init_abstract_transformers())
        abstract_transformers.append(SimHashTransformer(knowledge_file=self.db_file))
        abstract_transformers.append(
            ExtraFileTransformer(
                loader=self.loader,
                document_id=str(self.db_file.id),
                knowledge_id=self.db_file.knowledge_id,
                knowledge_file=self.db_file,
            )
        )
        abstract_transformers.append(
            ImageUploadTransformer(
                loader=self.loader,
                document_id=str(self.db_file.id),
                knowledge_id=self.db_file.knowledge_id,
                retain_images=self.file_split_rule.retain_images == 1,
            )
        )
        abstract_transformers.append(
            PreviewCacheTransformer(
                preview_cache_key=self.preview_cache_key,
                file_metadata=self.file_metadata,
            )
        )
        return abstract_transformers
