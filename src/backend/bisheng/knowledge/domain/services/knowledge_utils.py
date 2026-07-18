import json
import os
import time

from langchain_core.language_models import BaseChatModel
from loguru import logger

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.services.base import BaseService
from bisheng.core.cache.redis_manager import get_redis_client, get_redis_client_sync
from bisheng.knowledge.domain.models.knowledge_space_file import SpaceFileDao
from bisheng.knowledge.domain.upload_file_size import MEDIA_FILE_EXTENSIONS
from bisheng.llm.domain import LLMService
from bisheng.llm.domain.schemas import KnowledgeLLMConfig
from bisheng.utils import md5_hash


class KnowledgeUtils(BaseService):
    # Used to distinguishchunkand automated production summary content  Format e.g. Filename\nDocument Summary\n--------\n chunkContents
    chunk_split = "\n----------\n"
    schema_ready_lock_ttl = 60
    schema_ready_wait_seconds = 20
    schema_ready_poll_interval = 0.5

    @classmethod
    def get_preview_cache_key(cls, knowledge_id: int, file_path: str, md5_value=None) -> str:
        if not md5_value:
            md5_value = md5_hash(file_path)
        return f"preview_file_chunk:{knowledge_id}:{md5_value}"

    @classmethod
    def aggregate_chunk_metadata(cls, chunk: str, metadata: dict) -> str:
        # Video Wall ProcessingchunkAndmetadatadata in to get a newchunk
        res = f"{{<file_title>{metadata.get('document_name', '')}</file_title>\n"
        if metadata.get("abstract", ""):
            res += f"<file_abstract>{metadata.get('abstract', '')}</file_abstract>\n"
        res += f"<paragraph_content>{chunk}</paragraph_content>}}"
        return res

    @classmethod
    def chunk2promt(cls, chunk: str, metadata: dict) -> str:
        # Video Wall ProcessingchunkAndmetadatadata in to get a newchunk
        res = f"[file name]:{metadata.get('source', '')}\n[file content begin]\n{chunk}[file content end]\n"
        return res

    @classmethod
    def split_chunk_metadata(cls, chunk: str) -> str:
        # After stitching fromchunkis isolated from the originalchunk

        # Instructions are old stitching rules
        if not chunk.startswith("{<file_title>"):
            return chunk.split(cls.chunk_split)[-1]

        chunk = chunk.split("<paragraph_content>")[-1]
        chunk = chunk.split("</paragraph_content>")[0]
        return chunk

    @classmethod
    def format_retrieved_chunk(cls, doc, kb_name: str = "") -> str:
        """Format a retrieved Document into the tool-output chunk string shared by
        the workstation daily-mode search, the workflow agent knowledge tool, and
        the RAG/assistant document-stuffing paths.

        <chunk_id> carries the citation_key (the source id the model cites with);
        the legacy document-segment id was unused downstream and is dropped.

        page_content is stored pre-wrapped with <file_title>/<file_abstract>/
        <paragraph_content> by aggregate_chunk_metadata at ingest time; strip that
        wrapper so we don't nest it again. annotate_rag_documents_with_citations may
        have appended a "\n\ncitation_key: ..." tail; peel it off so paragraph_content
        holds only the bare body (the id now lives in <chunk_id>, not the tail).
        """
        meta = getattr(doc, "metadata", {}) or {}
        file_title = meta.get("document_name") or meta.get("source") or meta.get("file_name") or ""
        file_abstract = meta.get("file_abstract") or meta.get("abstract") or ""
        citation_key = meta.get("citation_key") or ""
        raw_content = (getattr(doc, "page_content", "") or "").strip()
        if citation_key:
            citation_suffix = f"\n\ncitation_key: {citation_key}"
            if raw_content.endswith(citation_suffix):
                raw_content = raw_content[: -len(citation_suffix)].rstrip()
        content = cls.split_chunk_metadata(raw_content).strip()
        kb_id_raw = meta.get("knowledge_id") or meta.get("kb_id") or ""
        kb_id = str(kb_id_raw) if kb_id_raw not in (None, "") else ""
        return (
            "{"
            f"<chunk_id>{citation_key}</chunk_id>\n"
            f"<knowledge_base_id>{kb_id}</knowledge_base_id>\n"
            f"<knowledge_base_name>{kb_name}</knowledge_base_name>\n"
            f"<file_title>{file_title}</file_title>\n"
            f"<file_abstract>{file_abstract}</file_abstract>\n"
            f"<paragraph_content>{content}</paragraph_content>"
            "}"
        )

    @classmethod
    async def async_save_preview_cache(cls, cache_key, mapping: dict = None, chunk_index: int = 0, value: dict = None):
        redis_client = await get_redis_client()
        if mapping:
            for key, val in mapping.items():
                mapping[key] = json.dumps(val, ensure_ascii=False)
            await redis_client.ahset(cache_key, mapping=mapping)
        else:
            await redis_client.ahset(cache_key, key=str(chunk_index), value=json.dumps(value, ensure_ascii=False))

    @classmethod
    def delete_preview_cache(cls, cache_key, chunk_index: int = None):
        redis_client = get_redis_client_sync()
        if chunk_index is None:
            redis_client.delete(cache_key)
            redis_client.delete(f"{cache_key}_parse_type")
            redis_client.delete(f"{cache_key}_file_path")
            redis_client.delete(f"{cache_key}_partitions")
        else:
            redis_client.hdel(cache_key, chunk_index)

    @classmethod
    def get_preview_cache(cls, cache_key, chunk_index: int = None) -> dict:
        redis_client = get_redis_client_sync()
        if chunk_index is None:
            all_chunk_info = redis_client.hgetall(cache_key)
            for key, value in all_chunk_info.items():
                all_chunk_info[key] = json.loads(value)
            return all_chunk_info
        else:
            chunk_info = redis_client.hget(cache_key, chunk_index)
            if chunk_info:
                chunk_info = json.loads(chunk_info)
            return chunk_info

    @classmethod
    async def async_get_preview_cache(cls, cache_key, chunk_index: int = None) -> dict:
        redis_client = await get_redis_client()
        if chunk_index is None:
            all_chunk_info = await redis_client.ahgetall(cache_key)
            for key, value in all_chunk_info.items():
                all_chunk_info[key] = json.loads(value)
            return all_chunk_info
        else:
            chunk_info = await redis_client.ahget(cache_key, chunk_index)
            if chunk_info:
                chunk_info = json.loads(chunk_info)
            return chunk_info

    @classmethod
    def get_knowledge_file_image_dir(cls, doc_id: str, knowledge_id: int = None) -> str:
        """Get file image atminioStorage directory for"""
        if knowledge_id:
            return f"knowledge/images/{knowledge_id}/{doc_id}"
        else:
            return f"tmp/images/{doc_id}"

    @classmethod
    def get_knowledge_file_object_name(cls, file_id: int, file_name: str) -> str:
        """Get Knowledge Base Source Files atminioStorage Path for"""
        file_ext = file_name.split(".")[-1]
        return f"original/{file_id}.{file_ext}"

    @classmethod
    def resolve_source_object_name(
        cls, file_id: int | str, file_name: str, object_name: str | None = None
    ) -> str | None:
        """Prefer the persisted object path and fall back to the canonical storage path."""
        if object_name:
            return object_name
        if not file_name:
            return object_name
        return cls.get_knowledge_file_object_name(file_id, file_name)

    @classmethod
    def get_knowledge_bbox_file_object_name(cls, file_id: int | str) -> str:
        """Get the corresponding knowledge base filebboxFiles inminioStorage Path for"""
        return f"partitions/{file_id}.json"

    @classmethod
    def get_knowledge_preview_file_object_name(
        cls, file_id: int | str, file_name: str = None, file_ext: str = None
    ) -> str | None:
        """Get the preview file corresponding to the knowledge base file atminioStorage Path for This path is stored in the officialbucketand within"""
        if file_name:
            file_ext = file_name.split(".")[-1]
        file_ext = file_ext.lower() if file_ext else file_ext
        if file_ext in ["doc", "docx", "wps"]:
            return f"preview/{file_id}.docx"
        elif file_ext in ["xls", "xlsx", "et"]:
            return f"preview/{file_id}.xlsx"
        elif file_ext in ["ppt", "pptx", "dps", "ofd"]:
            return f"preview/{file_id}.pdf"
        elif file_ext in ["mp3", "wav", "m4a", "aac", "flac", "ogg", "mp4", "mov", "avi", "mkv", "webm"]:
            return f"preview/{file_id}.md"
        # No preview required for other file types
        return None

    @classmethod
    def resolve_preview_object_name(
        cls, file_id: int | str, file_name: str = None, preview_file_object_name: str | None = None
    ) -> str | None:
        """Prefer the persisted preview path and fall back to the canonical preview path."""
        if preview_file_object_name:
            return preview_file_object_name
        if not file_name:
            return preview_file_object_name
        return cls.get_knowledge_preview_file_object_name(file_id=file_id, file_name=file_name)

    @classmethod
    def get_tmp_preview_file_object_name(cls, file_path: str) -> str | None:
        """Get a temporary preview file atminioStorage Path for This path is stored in a temporarybucket"""
        file_name = os.path.basename(file_path)
        file_name_no_ext, file_ext = file_name.rsplit(".", 1)
        file_ext = file_ext.lower()
        if file_ext in ["doc", "docx", "wps"]:
            return f"preview/{file_name_no_ext}.docx"
        elif file_ext in ["xls", "xlsx", "et"]:
            return f"preview/{file_name_no_ext}.xlsx"
        elif file_ext in ["ppt", "pptx", "dps", "ofd"]:
            return f"preview/{file_name_no_ext}.pdf"
        if file_ext in MEDIA_FILE_EXTENSIONS:
            return f"preview/{file_name_no_ext}_transcript.md"
        return None

    @classmethod
    def get_knowledge_abstract_llm(
        cls,
        invoke_user_id: int,
        tenant_id: int | None = None,
    ) -> tuple[BaseChatModel | None, KnowledgeLLMConfig | None]:
        """Get a summary of the knowledge basechunkright of privacy llmObjects"""
        knowledge_llm = LLMService.get_knowledge_llm(tenant_id=tenant_id)
        if not knowledge_llm.abstract_enabled or not knowledge_llm.extract_title_model_id:
            # No related configurations
            return None, None

        return LLMService.get_bisheng_llm_sync(
            model_id=knowledge_llm.extract_title_model_id,
            app_id=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
            app_name=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
            app_type=ApplicationTypeEnum.KNOWLEDGE_BASE,
            user_id=invoke_user_id,
        ), knowledge_llm

    @classmethod
    def _get_milvus_schema_ready_signature(cls) -> str:
        from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA

        field_names = ",".join([item.field_name for item in KNOWLEDGE_RAG_METADATA_SCHEMA])
        return f"v1:{field_names}"

    @classmethod
    def _build_schema_ready_cache_key(cls, collection_name: str) -> str:
        signature = cls._get_milvus_schema_ready_signature()
        return f"milvus_schema_ready:{collection_name}:{signature}"

    @classmethod
    def _build_schema_ready_lock_key(cls, collection_name: str) -> str:
        signature = cls._get_milvus_schema_ready_signature()
        return f"milvus_schema_ready_lock:{collection_name}:{signature}"

    @classmethod
    def _build_schema_init_metadata(cls, knowledge_id: int) -> dict:
        from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
        from bisheng.knowledge.domain.schemas.knowledge_rag_schema import Metadata

        metadata = Metadata(
            document_id=0,
            knowledge_id=knowledge_id,
            document_name="",
            abstract="",
            chunk_index=1,
            bbox="{}",
            page=1,
            upload_time=int(time.time()),
            update_time=int(time.time()),
            uploader="",
            updater="",
            user_metadata={},
        ).model_dump(exclude_none=True)
        allowed_fields = {item.field_name for item in KNOWLEDGE_RAG_METADATA_SCHEMA}
        return {key: value for key, value in metadata.items() if key in allowed_fields}

    @classmethod
    def ensure_milvus_schema_ready(cls, invoke_user_id: int, knowledge, vector_client=None):
        from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
        from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag

        if not knowledge or not getattr(knowledge, "collection_name", None):
            return vector_client

        collection_name = knowledge.collection_name
        ready_key = cls._build_schema_ready_cache_key(knowledge.collection_name)
        lock_key = cls._build_schema_ready_lock_key(knowledge.collection_name)

        redis_client = None
        try:
            redis_client = get_redis_client_sync()
            if redis_client.get(ready_key):
                logger.debug(
                    "milvus_schema_ready cache_hit collection={} knowledge_id={}",
                    collection_name,
                    knowledge.id,
                )
                if vector_client is None or getattr(vector_client, "col", None) is None:
                    vector_client = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
                        invoke_user_id,
                        knowledge=knowledge,
                        metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA,
                    )
                return vector_client
        except Exception:
            redis_client = None

        acquired_lock = False
        if redis_client:
            try:
                acquired_lock = redis_client.setNx(lock_key, "1", expiration=cls.schema_ready_lock_ttl)
                if acquired_lock:
                    logger.info(
                        "milvus_schema_ready lock_acquired collection={} knowledge_id={} ttl={}",
                        collection_name,
                        knowledge.id,
                        cls.schema_ready_lock_ttl,
                    )
            except Exception:
                acquired_lock = False

        if not acquired_lock and redis_client:
            logger.info(
                "milvus_schema_ready waiting collection={} knowledge_id={} wait_seconds={}",
                collection_name,
                knowledge.id,
                cls.schema_ready_wait_seconds,
            )
            deadline = time.time() + cls.schema_ready_wait_seconds
            while time.time() < deadline:
                if redis_client.get(ready_key):
                    logger.info(
                        "milvus_schema_ready wait_finished collection={} knowledge_id={} source=peer_init",
                        collection_name,
                        knowledge.id,
                    )
                    if vector_client is None or getattr(vector_client, "col", None) is None:
                        vector_client = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
                            invoke_user_id,
                            knowledge=knowledge,
                            metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA,
                        )
                    return vector_client
                time.sleep(cls.schema_ready_poll_interval)

        try:
            logger.info(
                "milvus_schema_ready init_start collection={} knowledge_id={}",
                collection_name,
                knowledge.id,
            )
            vector_client = vector_client or KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
                invoke_user_id,
                knowledge=knowledge,
                metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA,
            )
            init_ids = vector_client.add_texts(
                texts=["init_schema"],
                metadatas=[cls._build_schema_init_metadata(knowledge.id)],
            )
            if init_ids:
                vector_client.delete(ids=init_ids)
            if redis_client:
                redis_client.set(ready_key, True, expiration=24 * 3600)
            logger.info(
                "milvus_schema_ready init_done collection={} knowledge_id={} cached={}",
                collection_name,
                knowledge.id,
                bool(redis_client),
            )
            return vector_client
        finally:
            if acquired_lock and redis_client:
                try:
                    redis_client.delete(lock_key)
                    logger.debug(
                        "milvus_schema_ready lock_released collection={} knowledge_id={}",
                        collection_name,
                        knowledge.id,
                    )
                except Exception:
                    pass

    @staticmethod
    async def update_folder_update_time(file_level_path: str) -> None:
        if not file_level_path:
            return
        folder_ids = file_level_path.split("/")
        folder_ids = [int(one) for one in folder_ids if one]
        await SpaceFileDao.update_records_update_time(folder_ids)

    @staticmethod
    def update_folder_update_time_sync(file_level_path: str) -> None:
        if not file_level_path:
            return
        folder_ids = file_level_path.split("/")
        folder_ids = [int(one) for one in folder_ids if one]
        SpaceFileDao.update_records_update_time_sync(folder_ids)

    @classmethod
    async def process_rebuild_file(cls, db_file, req_data, login_user_id: int, login_user_name: str):
        """Shared logic to rebuild a knowledge file with new rules."""
        from bisheng.api.v1.schemas import FileProcessBase
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao, KnowledgeFileStatus
        from bisheng.worker.knowledge import file_worker

        split_rule_dict = req_data.model_dump(include=set(list(FileProcessBase.model_fields.keys())))
        if req_data.excel_rule is not None:
            split_rule_dict["excel_rule"] = req_data.excel_rule.model_dump()
        db_file.split_rule = json.dumps(split_rule_dict)
        db_file.status = KnowledgeFileStatus.WAITING.value
        db_file.updater_id = login_user_id
        db_file.updater_name = login_user_name
        db_file = await KnowledgeFileDao.async_update(db_file)

        preview_cache_key = cls.get_preview_cache_key(req_data.knowledge_id, file_path=req_data.file_path)
        file_worker.retry_knowledge_file_celery.delay(db_file.id, preview_cache_key, req_data.callback_url)

        return db_file

    @classmethod
    async def process_retry_files(cls, db_files, id2input: dict, login_user) -> tuple[list, set]:
        """Shared logic for retrying multiple files with updated configuration"""
        from bisheng.core.storage.minio.minio_manager import get_minio_storage
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao, KnowledgeFileStatus
        from bisheng.worker.knowledge import file_worker

        minio_client = await get_minio_storage()
        file_level_path = set()
        res = []

        for file in db_files:
            input_file = id2input.get(file.id)
            new_file_name = file.file_name
            try:
                content = input_file.get("remark")
                content = json.loads(content)
                if content.get("new_name"):
                    new_file_name = content.get("new_name")
            except Exception:
                pass

            # file exist
            file.object_name = input_file.get("object_name", file.object_name)
            file_preview_cache_key = cls.get_preview_cache_key(file.knowledge_id, input_file.get("file_path", ""))

            if file.object_name.startswith("tmp"):
                # Moving Temporary Files to the Official Directory
                new_object_name = cls.get_knowledge_file_object_name(file.id, file.object_name)
                await minio_client.copy_object(
                    source_object=file.object_name,
                    dest_object=new_object_name,
                    source_bucket=minio_client.tmp_bucket,
                    dest_bucket=minio_client.bucket,
                )
                file.object_name = new_object_name
            file.file_name = new_file_name
            file.remark = ""
            file.split_rule = input_file["split_rule"]
            file.status = KnowledgeFileStatus.WAITING.value  # Parsing
            # Content has been replaced (overwrite path) — the previous
            # similar-document marker and simhash were computed against the
            # old content and must be cleared so the new parse re-scans from
            # scratch. Otherwise users see a "similar" tag on a file that has
            # already been overwritten with different content.
            file.similar_status = 0
            file.simhash = None
            file.updater_id = login_user.user_id
            file.updater_name = login_user.user_name
            file.file_level_path = input_file["file_level_path"]
            if file.file_level_path:
                file_level_path.add(file.file_level_path)

            file = await KnowledgeFileDao.async_update(file)
            res.append([file, file_preview_cache_key])

        tmp = []
        for one_file in res:
            file_worker.retry_knowledge_file_celery.delay(one_file[0].id, one_file[1], None)
            tmp.append(one_file[0])

        return tmp, file_level_path
