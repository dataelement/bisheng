import asyncio
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Union

import aiofiles
import requests
from langchain.embeddings.base import Embeddings
from langchain.schema.document import Document
from langchain.text_splitter import CharacterTextSplitter
from langchain.vectorstores.base import VectorStore
from langchain_community.document_loaders import (
    BSHTMLLoader,
    PyPDFLoader,
    TextLoader,
    UnstructuredPowerPointLoader,
    UnstructuredWordDocumentLoader,
)
from loguru import logger
from pymilvus import Collection
from sqlalchemy import func, or_
from sqlmodel import select

from bisheng.api.services.etl4lm_loader import Etl4lmLoader
from bisheng.api.services.libreoffice_converter import (
    convert_doc_to_docx,
    convert_ppt_to_pdf, convert_ppt_to_pptx,
)
from bisheng.api.services.md_from_pdf import is_pdf_damaged
from bisheng.api.services.patch_130 import (
    convert_file_to_md,
    combine_multiple_md_files_to_raw_texts,
)
from bisheng.api.v1.schemas import ExcelRule
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum, ApplicationTypeEnum
from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.knowledge import KnowledgeSimilarError, KnowledgeFileDeleteError, KnowledgeFileEmptyError, \
    KnowledgeFileChunkMaxError, KnowledgeLLMError, KnowledgeFileDamagedError, KnowledgeFileNotSupportedError, \
    KnowledgeEtl4lmTimeoutError, KnowledgeFileFailedError, KnowledgeExcelChunkMaxError
from bisheng.common.schemas.telemetry.event_data_schema import FileParseEventData
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client_sync, get_redis_client
from bisheng.core.cache.utils import file_download
from bisheng.core.database import get_sync_db_session
from bisheng.core.logger import trace_id_var
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync, get_minio_storage
from bisheng.interface.embeddings.custom import FakeEmbedding
from bisheng.interface.importing.utils import import_vectorstore
from bisheng.interface.initialize.loading import instantiate_vectorstore
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileDao,
    KnowledgeFileStatus,
    ParseType,
    QAKnoweldgeDao,
    QAKnowledge,
    QAKnowledgeUpsert,
    QAStatus,
)
from bisheng.knowledge.domain.schemas.knowledge_rag_schema import Metadata
from bisheng.llm.domain.services import LLMService
from bisheng.user.domain.models.user import UserDao
from bisheng.utils import md5_hash, util
from bisheng.utils.exceptions import EtlException, FileParseException
from bisheng_langchain.rag.extract_info import extract_title, async_extract_title
from bisheng_langchain.text_splitter import ElemCharacterTextSplitter

filetype_load_map = {
    "txt": TextLoader,
    "pdf": PyPDFLoader,
    "html": BSHTMLLoader,
    "md": TextLoader,
    "docx": UnstructuredWordDocumentLoader,
    "pptx": UnstructuredPowerPointLoader,
}


class KnowledgeUtils:
    # Used to distinguishchunkand automated production summary content  Format e.g. Filename\nDocument Summary\n--------\n chunkContents
    chunk_split = "\n----------\n"

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
    async def async_save_preview_cache(
            cls, cache_key, mapping: dict = None, chunk_index: int = 0, value: dict = None
    ):
        redis_client = await get_redis_client()
        if mapping:
            for key, val in mapping.items():
                mapping[key] = json.dumps(val, ensure_ascii=False)
            await redis_client.ahset(cache_key, mapping=mapping)
        else:
            await redis_client.ahset(
                cache_key, key=chunk_index, value=json.dumps(value, ensure_ascii=False)
            )

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
    def get_knowledge_bbox_file_object_name(cls, file_id: int) -> str:
        """Get the corresponding knowledge base filebboxFiles inminioStorage Path for"""
        return f"partitions/{file_id}.json"

    @classmethod
    def get_knowledge_preview_file_object_name(
            cls, file_id: int, file_name: str
    ) -> Optional[str]:
        """Get the preview file corresponding to the knowledge base file atminioStorage Path for This path is stored in the officialbucketand within"""
        file_ext = file_name.split(".")[-1]
        if file_ext == "doc":
            return f"preview/{file_id}.docx"
        elif file_ext in ["ppt", "pptx"]:
            return f"preview/{file_id}.pdf"
        # No preview required for other file types
        return None

    @classmethod
    def get_tmp_preview_file_object_name(cls, file_path: str) -> Optional[str]:
        """Get a temporary preview file atminioStorage Path for This path is stored in a temporarybucket"""
        file_name = os.path.basename(file_path)
        file_name_no_ext, file_ext = file_name.rsplit(".", 1)
        if file_ext == "doc":
            return f"preview/{file_name_no_ext}.docx"
        elif file_ext in ["ppt", "pptx"]:
            return f"preview/{file_name_no_ext}.pdf"
        # No preview required for other file types
        return None


def put_images_to_minio(local_image_dir, knowledge_id, doc_id):
    if not os.path.exists(local_image_dir):
        return

    minio_client = get_minio_storage_sync()

    files = [f for f in os.listdir(local_image_dir)]
    for file_name in files:
        local_file_name = f"{local_image_dir}/{file_name}"
        object_name = f"{KnowledgeUtils.get_knowledge_file_image_dir(doc_id, knowledge_id)}/{file_name}"
        with open(local_file_name, "rb") as file_obj:
            minio_client.put_object_sync(
                object_name=object_name, file=file_obj.read(), bucket_name=minio_client.bucket
            )


async def async_images_to_minio(local_image_dir, knowledge_id, doc_id):
    if not os.path.exists(local_image_dir):
        return

    minio_client = await get_minio_storage()

    files = [f for f in os.listdir(local_image_dir)]
    for file_name in files:
        local_file_name = f"{local_image_dir}/{file_name}"
        object_name = f"{KnowledgeUtils.get_knowledge_file_image_dir(doc_id, knowledge_id)}/{file_name}"
        async with aiofiles.open(local_file_name, "rb") as file_obj:
            await minio_client.put_object(
                object_name=object_name, file=await file_obj.read(), bucket_name=minio_client.bucket
            )


def process_file_task(
        knowledge: Knowledge,
        db_files: List[KnowledgeFile],
        separator: List[str],
        separator_rule: List[str],
        chunk_size: int,
        chunk_overlap: int,
        callback_url: str = None,
        extra_metadata: Dict = None,
        preview_cache_keys: List[str] = None,
        retain_images: int = 1,
        enable_formula: int = 1,
        force_ocr: int = 0,
        filter_page_header_footer: int = 0,
):
    """Working with Knowledge Files Tasks"""
    try:
        index_name = knowledge.index_name or knowledge.collection_name
        addEmbedding(
            knowledge.collection_name,
            index_name,
            knowledge.id,
            knowledge.model,
            separator,
            separator_rule,
            chunk_size,
            chunk_overlap,
            db_files,
            callback_url,
            extra_metadata,
            preview_cache_keys=preview_cache_keys,
            retain_images=retain_images,
            enable_formula=enable_formula,
            force_ocr=force_ocr,
            filter_page_header_footer=filter_page_header_footer,
        )
    except Exception as e:
        logger.exception("process_file_task error")
        new_files = KnowledgeFileDao.select_list([file.id for file in db_files])
        new_files_map = {file.id: file for file in new_files}
        for file in db_files:
            if new_files_map[file.id].status == KnowledgeFileStatus.PROCESSING.value:
                file.status = KnowledgeFileStatus.FAILED.value
                file.remark = KnowledgeFileFailedError(exception=e).to_json_str()
                KnowledgeFileDao.update(file)
        logger.info("update files failed status over")
        raise e


def delete_vector_files(file_ids: List[int], knowledge: Knowledge) -> bool:
    """ Delete vector data andesDATA """
    if not file_ids:
        return True
    logger.info(f"delete_files file_ids={file_ids} knowledge_id={knowledge.id}")
    logger.info("start init Milvus")
    vector_client = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(0, knowledge=knowledge,
                                                                        metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA)
    logger.info("start init ES")
    es_client = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=knowledge,
                                                                metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA)
    # Automatically close purchase order aftercollectionIf it does not exist, it will not
    if vector_client.col:
        vector_client.col.delete(expr=f"document_id in {file_ids}", timeout=10)
    logger.info(f"delete_milvus file_ids={file_ids}")

    if es_client.client.indices.exists(index=knowledge.index_name):
        res = es_client.client.delete_by_query(
            index=knowledge.index_name,
            query={"terms": {"metadata.document_id": file_ids}},
        )
        logger.info(f"act=delete_es file_ids={file_ids} res={res}")

    return True


def delete_minio_files(file: KnowledgeFile):
    """Delete Knowledge Base Files inminioStorage on"""

    minio_client = get_minio_storage_sync()

    # Delete source file
    if file.object_name:
        minio_client.remove_object_sync(bucket_name=minio_client.bucket, object_name=file.object_name)

    # DeletebboxDoc.
    if file.bbox_object_name:
        minio_client.remove_object_sync(bucket_name=minio_client.bucket, object_name=file.bbox_object_name)

    # Delete ConvertedpdfDoc.
    minio_client.remove_object_sync(bucket_name=minio_client.bucket, object_name=f"{file.id}")

    # Delete preview file
    preview_object_name = KnowledgeUtils.get_knowledge_preview_file_object_name(
        file.id, file.file_name
    )
    if preview_object_name:
        minio_client.remove_object_sync(bucket_name=minio_client.bucket, object_name=preview_object_name)
    return True


def delete_knowledge_file_vectors(file_ids: List[int], clear_minio: bool = True):
    """Delete Knowledge File Information"""
    knowledge_files = KnowledgeFileDao.select_list(file_ids=file_ids)

    knowledge_ids = [file.knowledge_id for file in knowledge_files]
    knowledges = KnowledgeDao.get_list_by_ids(knowledge_ids)
    if len(knowledges) > 1:
        raise KnowledgeFileDeleteError()
    knowledge = knowledges[0]
    delete_vector_files(file_ids, knowledge)

    if clear_minio:
        for file in knowledge_files:
            delete_minio_files(file)
    return True


def decide_vectorstores(
        collection_name: str, vector_store: str, embedding: Embeddings, knowledge_id: int = None
) -> Union[VectorStore, Any]:
    """ vector db if used by query, must have knowledge_id"""
    param: dict = {"embedding": embedding}

    if vector_store == "ElasticKeywordsSearch":
        vector_config = settings.get_vectors_conf().elasticsearch.model_dump()
        if not vector_config:
            # No related configurations
            raise RuntimeError("vector_stores.elasticsearch not find in config.yaml")
        param["index_name"] = collection_name
        if isinstance(vector_config["ssl_verify"], str):
            vector_config["ssl_verify"] = eval(vector_config["ssl_verify"])

    elif vector_store == "Milvus":
        if knowledge_id and collection_name.startswith("partition"):
            param["partition_key"] = knowledge_id
        vector_config = settings.get_vectors_conf().milvus.model_dump()
        if not vector_config:
            # No related configurations
            raise RuntimeError("vector_stores.milvus not find in config.yaml")
        param["collection_name"] = collection_name
        vector_config.pop("partition_suffix", "")
        vector_config.pop("is_partition", "")
    else:
        raise RuntimeError("unknown vector store type")

    param.update(vector_config)
    class_obj = import_vectorstore(vector_store)
    return instantiate_vectorstore(vector_store, class_object=class_obj, params=param)


def decide_knowledge_llm(invoke_user_id: int) -> Any:
    """Get a summary of the knowledge basechunkright of privacy llmObjects"""
    # DapatkanllmConfigure
    knowledge_llm = LLMService.get_knowledge_llm()
    if not knowledge_llm.extract_title_model_id:
        # No related configurations
        return None

    # DapatkanllmObjects
    return LLMService.get_bisheng_llm_sync(
        model_id=knowledge_llm.extract_title_model_id,

        app_id=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
        app_name=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
        app_type=ApplicationTypeEnum.KNOWLEDGE_BASE,
        user_id=invoke_user_id)


async def async_decide_knowledge_llm(invoke_user_id: int) -> Any:
    """Get a summary of the knowledge basechunkright of privacy llmObjects"""
    # DapatkanllmConfigure
    knowledge_llm = await LLMService.aget_knowledge_llm()
    if not knowledge_llm.extract_title_model_id:
        # No related configurations
        return None

    # DapatkanllmObjects
    return await LLMService.get_bisheng_llm(
        model_id=knowledge_llm.extract_title_model_id,

        app_id=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
        app_name=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
        app_type=ApplicationTypeEnum.KNOWLEDGE_BASE,
        user_id=invoke_user_id)


def addEmbedding(
        collection_name: str,
        index_name: str,
        knowledge_id: int,
        model: str,
        separator: List[str],
        separator_rule: List[str],
        chunk_size: int,
        chunk_overlap: int,
        knowledge_files: List[KnowledgeFile],
        callback: str = None,
        extra_meta: Dict = None,
        preview_cache_keys: List[str] = None,
        retain_images: int = 1,
        enable_formula: int = 1,
        force_ocr: int = 0,
        filter_page_header_footer: int = 0,
):
    """Adding Files to Vector SumsesCunene"""

    logger.info("start init Milvus")
    vector_client = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(knowledge_files[0].updater_id,
                                                                        knowledge_id=knowledge_id,
                                                                        metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA)
    logger.info("start init ES")
    es_client = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge_id=knowledge_id,
                                                                metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA)
    minio_client = get_minio_storage_sync()
    for index, db_file in enumerate(knowledge_files):
        # Try to get chunks of a file from the cache
        preview_cache_key = None
        if preview_cache_keys:
            preview_cache_key = (
                preview_cache_keys[index] if index < len(preview_cache_keys) else None
            )
        status = 'failed'
        try:
            logger.info(
                f"process_file_begin file_id={db_file.id} file_name={db_file.file_name}"
            )
            add_file_embedding(
                vector_client,
                es_client,
                minio_client,
                db_file,
                separator,
                separator_rule,
                chunk_size,
                chunk_overlap,
                extra_meta=extra_meta,
                preview_cache_key=preview_cache_key,
                # Added parameters
                retain_images=retain_images,
                knowledge_id=knowledge_id,
                enable_formula=enable_formula,
                force_ocr=force_ocr,
                filter_page_header_footer=filter_page_header_footer,
            )
            db_file.status = KnowledgeFileStatus.SUCCESS.value
            status = 'success'
        except FileParseException as e:
            logger.exception(
                f"process_file_fail file_id={db_file.id} file_name={db_file.file_name}"
            )
            db_file.status = KnowledgeFileStatus.FAILED.value
            if str(e).find("etl4lm server timeout") != -1:
                db_file.remark = KnowledgeEtl4lmTimeoutError(exception=e).to_json_str()
            else:
                db_file.remark = KnowledgeFileFailedError(exception=e).to_json_str()
            status = 'parse_failed'
        except BaseErrorCode as e:
            db_file.status = KnowledgeFileStatus.FAILED.value
            db_file.remark = e.to_json_str()
            status = 'failed'
        except Exception as e:
            logger.exception(
                f"process_file_fail file_id={db_file.id} file_name={db_file.file_name}"
            )
            db_file.status = KnowledgeFileStatus.FAILED.value
            db_file.remark = KnowledgeFileFailedError(exception=e).to_json_str()
            status = 'failed'
        finally:
            logger.info(
                f"process_file_end file_id={db_file.id} file_name={db_file.file_name}"
            )
            KnowledgeFileDao.update(db_file)
            telemetry_service.log_event_sync(user_id=db_file.user_id,
                                             event_type=BaseTelemetryTypeEnum.FILE_PARSE,
                                             trace_id=trace_id_var.get(),
                                             event_data=FileParseEventData(
                                                 parse_type=db_file.parse_type,
                                                 status=status,
                                                 app_type=ApplicationTypeEnum.KNOWLEDGE_BASE
                                             ))

            if callback:
                inp = {
                    "file_name": db_file.file_name,
                    "file_status": db_file.status,
                    "file_id": db_file.id,
                    "error_msg": db_file.remark,
                }
                requests.post(url=callback, json=inp, timeout=3)


def add_file_embedding(
        vector_client,
        es_client,
        minio_client,
        db_file: KnowledgeFile,
        separator: List[str],
        separator_rule: List[str],
        chunk_size: int,
        chunk_overlap: int,
        extra_meta: Dict = None,
        preview_cache_key: str = None,
        knowledge_id: int = None,
        retain_images: int = 1,
        enable_formula: int = 1,
        force_ocr: int = 0,
        filter_page_header_footer: int = 0,
):
    # download original file
    logger.info(
        f"start download original file={db_file.id} file_name={db_file.file_name}"
    )

    file_url = minio_client.get_share_link_sync(db_file.object_name, clear_host=False)
    filepath, _ = file_download(file_url)
    file_ext = db_file.file_name.split(".")[-1].lower()

    # Convert split_rule string to dict if needed
    excel_rule = ExcelRule()
    if db_file.split_rule and isinstance(db_file.split_rule, str):
        split_rule = json.loads(db_file.split_rule)
        if "excel_rule" in split_rule:
            excel_rule = ExcelRule(**split_rule["excel_rule"])
    # # extract text from file
    try:
        texts, metadatas, parse_type, partitions = read_chunk_text(
            db_file.user_id,
            filepath,
            db_file.file_name,
            separator,
            separator_rule,
            chunk_size,
            chunk_overlap,
            knowledge_id=knowledge_id,
            retain_images=retain_images,
            enable_formula=enable_formula,
            force_ocr=force_ocr,
            filter_page_header_footer=filter_page_header_footer,
            excel_rule=excel_rule,
        )
    except EtlException as e:
        db_file.parse_type = ParseType.ETL4LM.value
        raise FileParseException(str(e)) from e
    except BaseErrorCode as e:
        raise e
    except Exception as e:
        raise FileParseException(str(e)) from e

    if len(texts) == 0:
        raise KnowledgeFileEmptyError()
    # If there is data in the cache, the data in the cache is used to go to the warehouse because the user edited it in the interface.
    if preview_cache_key:
        all_chunk_info = KnowledgeUtils.get_preview_cache(preview_cache_key)
        if all_chunk_info:
            logger.info(
                f"get_preview_cache file={db_file.id} file_name={db_file.file_name}"
            )
            texts, metadatas = [], []
            for key, val in all_chunk_info.items():
                texts.append(val["text"])
                metadatas.append(Metadata(**val["metadata"]))
    for index, one in enumerate(texts):
        if len(one) > 10000:
            if file_ext in (".xlsx", ".xls", ".csv"):
                raise KnowledgeExcelChunkMaxError()
            raise KnowledgeFileChunkMaxError()
        # On Inbound Stitching file names and document summaries
        texts[index] = KnowledgeUtils.aggregate_chunk_metadata(one, metadatas[index].model_dump())

    db_file.parse_type = parse_type
    # StorageocrIdentifiedpartitions<g id="Bold">Result</g>
    if partitions:
        partition_data = json.dumps(partitions, ensure_ascii=False).encode("utf-8")
        db_file.bbox_object_name = KnowledgeUtils.get_knowledge_bbox_file_object_name(
            db_file.id
        )
        minio_client.put_object_sync(
            bucket_name=minio_client.bucket,
            object_name=db_file.bbox_object_name,
            file=partition_data, content_type="application/json",
        )

    logger.info(
        f"chunk_split file={db_file.id} file_name={db_file.file_name} size={len(texts)}"
    )
    uploader = UserDao.get_user(user_id=db_file.user_id).user_name
    if db_file.updater_id:
        updater = UserDao.get_user(user_id=db_file.updater_id).user_name
    else:
        updater = uploader
    for metadata in metadatas:
        metadata.document_id = db_file.id
        metadata.knowledge_id = db_file.knowledge_id
        if extra_meta:
            metadata.user_metadata = metadata.user_metadata.update(extra_meta)
        metadata.upload_time = int(db_file.create_time.timestamp())
        metadata.update_time = int(db_file.update_time.timestamp())
        metadata.uploader = uploader
        metadata.updater = updater

    metadatas = [metadata.model_dump() for metadata in metadatas]
    logger.info(f"add_vectordb file={db_file.id} file_name={db_file.file_name}")
    # Depositmilvus
    vector_client.add_texts(texts=texts, metadatas=metadatas)

    logger.info(f"add_es file={db_file.id} file_name={db_file.file_name}")
    # Deposites
    es_client.add_texts(texts=texts, metadatas=metadatas)

    logger.info(f"add_complete file={db_file.id} file_name={db_file.file_name}")

    if preview_cache_key:
        KnowledgeUtils.delete_preview_cache(preview_cache_key)

    if file_ext in (".doc", ".ppt", ".pptx"):
        tmp_preview_file = KnowledgeUtils.get_tmp_preview_file_object_name(filepath)

        preview_object_name = KnowledgeUtils.get_knowledge_preview_file_object_name(
            db_file.id, db_file.file_name
        )
        logger.info(
            f"upload_preview_file_to_minio file={db_file.id} tmp_object_name={tmp_preview_file}, preview_object_name={preview_object_name}"
        )
        if minio_client.object_exists_sync(minio_client.tmp_bucket, tmp_preview_file):
            minio_client.copy_object_sync(
                source_object=tmp_preview_file,
                dest_object=preview_object_name,
                source_bucket=minio_client.tmp_bucket,
                dest_bucket=minio_client.bucket,
            )
        logger.info(
            f"upload_preview_file_over file={db_file.id} tmp_object_name={tmp_preview_file}, preview_object_name={preview_object_name}"
        )


def add_text_into_vector(
        vector_client,
        es_client,
        db_file: KnowledgeFile,
        texts: List[str],
        metadatas: List[dict],
):
    logger.info(f"add_vectordb file={db_file.id} file_name={db_file.file_name}")
    # Depositmilvus
    vector_client.add_texts(texts=texts, metadatas=metadatas)

    logger.info(f"add_es file={db_file.id} file_name={db_file.file_name}")
    # Deposites
    es_client.add_texts(texts=texts, metadatas=metadatas)


def parse_partitions(partitions: List[Any]) -> Dict:
    """Resolve BuildbboxCorrespondence with text"""
    if not partitions:
        return {}
    res = {}
    for part_index, part in enumerate(partitions):
        bboxes = part["metadata"]["extra_data"]["bboxes"]
        indexes = part["metadata"]["extra_data"]["indexes"]
        pages = part["metadata"]["extra_data"]["pages"]
        text = part["text"]
        for index, bbox in enumerate(bboxes):
            key = f"{pages[index]}-" + "-".join([str(int(one)) for one in bbox])
            if index == len(bboxes) - 1:
                val = text[indexes[index][0]:]
            else:
                val = text[indexes[index][0]:indexes[index][1]]
            res[key] = {"text": val, "type": part["type"], "part_id": part_index}
    return res


def upload_preview_file_to_minio(original_file_path: str, preview_file_path: str):
    if (
            os.path.basename(original_file_path).split(".")[0]
            != os.path.basename(preview_file_path).split(".")[0]
    ):
        logger.error(
            f"Original and preview file paths do not match: {original_file_path} vs {preview_file_path}"
        )

    minio_client = get_minio_storage_sync()
    object_name = KnowledgeUtils.get_tmp_preview_file_object_name(original_file_path)
    with open(preview_file_path, "rb") as file_obj:
        # Upload preview file tominio
        minio_client.put_object_tmp_sync(
            object_name=object_name, file=file_obj.read()
        )
    return object_name


async def async_upload_preview_file_to_minio(
        original_file_path: str, preview_file_path: str
):
    if (
            os.path.basename(original_file_path).split(".")[0]
            != os.path.basename(preview_file_path).split(".")[0]
    ):
        logger.error(
            f"Original and preview file paths do not match: {original_file_path} vs {preview_file_path}"
        )

    minio_client = await get_minio_storage()
    object_name = KnowledgeUtils.get_tmp_preview_file_object_name(original_file_path)
    async with aiofiles.open(preview_file_path, "rb") as file_obj:
        # Upload preview file tominio
        await minio_client.put_object_tmp(
            object_name=object_name, file=await file_obj.read()
        )
    return object_name


def parse_document_title(title: str) -> str:
    """
    Parse document titles, removing special characters and extra spaces
    :param title: Original title
    :return: Post-processing title
    """
    # Removing the Thinking Model'sthinkChange Content
    title = re.sub("<think>.*</think>", "", title, flags=re.S).strip()

    # If there is amd The code fast marker removes the code block marker
    if final_title := extract_code_blocks(title):
        title = "\n".join(final_title)
    return title


def read_chunk_text(
        invoke_user_id: int,
        input_file: str,
        file_name: str,
        separator: Optional[List[str]],
        separator_rule: Optional[List[str]],
        chunk_size: int,
        chunk_overlap: int,
        knowledge_id: Optional[int] = None,
        retain_images: int = 1,
        enable_formula: int = 1,
        force_ocr: int = 1,
        filter_page_header_footer: int = 0,
        excel_rule: ExcelRule = None,
        no_summary: bool = False,
) -> (List[str], List[dict], str, Any):  # type: ignore
    """
    0：chunks text
    1：chunks metadata
    2：parse_type: etl4lm or un_etl4lm
    3: ocr bbox data: maybe None
    """
    # Gets the title of the document summaryllm
    llm = None
    if not no_summary:
        try:
            llm = decide_knowledge_llm(invoke_user_id)
            knowledge_llm = LLMService.get_knowledge_llm()
        except Exception as e:
            logger.exception("knowledge_llm_error:")
            raise KnowledgeLLMError()

    text_splitter = ElemCharacterTextSplitter(
        separators=separator,
        separator_rule=separator_rule,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        is_separator_regex=True,
    )
    # Load document content
    logger.info(f"start_file_loader file_name={file_name}")
    parse_type = ParseType.UN_ETL4LM.value
    # excel File processing comes out separately
    partitions = []
    texts = []
    etl_for_lm_url = settings.get_knowledge().etl4lm.url
    file_extension_name = file_name.split(".")[-1].lower()

    if file_extension_name in ["xls", "xlsx", "csv"]:
        # set default values.
        if not excel_rule:
            excel_rule = ExcelRule()

        # convert excel contents to markdown
        md_files_path, local_image_dir, doc_id = convert_file_to_md(
            file_name=file_name,
            input_file_name=input_file,
            header_rows=[
                excel_rule.header_start_row - 1,  # convert to 0-based index
                excel_rule.header_end_row - 1,
            ],
            data_rows=excel_rule.slice_length,
            append_header=excel_rule.append_header,
            retain_images=bool(retain_images),
        )

        # skip following processes and return splited values.
        texts, documents = combine_multiple_md_files_to_raw_texts(path=md_files_path)

    elif file_extension_name in ["doc", "docx", "html", "mhtml", "ppt", "pptx"]:

        if file_extension_name == "doc":
            # convert doc to docx
            input_file = convert_doc_to_docx(input_doc_path=input_file)
            if not input_file:
                raise Exception(
                    f"failed to convert {file_name} to docx, please check backend log"
                )
        elif file_extension_name == "ppt":
            input_file = convert_ppt_to_pptx(input_path=input_file)
            if not input_file:
                raise Exception("failed convert ppt to pptx, please check backend log")

        md_file_name, local_image_dir, doc_id = convert_file_to_md(
            file_name=file_name,
            input_file_name=input_file,
            knowledge_id=knowledge_id,
            retain_images=bool(retain_images),
        )

        if not md_file_name:
            raise Exception(f"failed to parse {file_name}, please check backend log")

        # save images to minio
        if local_image_dir and retain_images == 1:
            put_images_to_minio(
                local_image_dir=local_image_dir,
                knowledge_id=knowledge_id,
                doc_id=doc_id,
            )
        # will bepptxSave as preview file to
        if file_extension_name in ["ppt", "pptx"]:
            ppt_pdf_path = convert_ppt_to_pdf(input_path=input_file)
            if ppt_pdf_path:
                upload_preview_file_to_minio(input_file, ppt_pdf_path)
        elif file_extension_name == "doc":
            upload_preview_file_to_minio(
                input_file.replace(".docx", ".doc"), input_file
            )

        # Handle it the same way you didmdDoc.
        loader = filetype_load_map["md"](file_path=md_file_name, autodetect_encoding=True)
        documents = loader.load()

    elif file_extension_name in ["txt", "md"]:
        loader = filetype_load_map[file_extension_name](file_path=input_file, autodetect_encoding=True)
        documents = loader.load()
    else:
        if etl_for_lm_url:
            if file_extension_name in ["pdf"]:
                # Determine if the document is damaged
                if is_pdf_damaged(input_file):
                    raise KnowledgeFileDamagedError()
            etl4lm_settings = settings.get_knowledge().etl4lm
            parse_type = ParseType.ETL4LM.value
            try:
                loader = Etl4lmLoader(
                    file_name,
                    input_file,
                    unstructured_api_url=etl4lm_settings.url,
                    ocr_sdk_url=etl4lm_settings.ocr_sdk_url,
                    force_ocr=bool(force_ocr),
                    enable_formular=bool(enable_formula),
                    timeout=etl4lm_settings.timeout,
                    filter_page_header_footer=bool(filter_page_header_footer),
                    knowledge_id=knowledge_id,
                )
                documents = loader.load()
            except Exception as e:
                raise EtlException(str(e)) from e
            partitions = loader.partitions
            partitions = parse_partitions(partitions)
        else:
            if file_extension_name in ['pdf']:
                md_file_name, local_image_dir, doc_id = convert_file_to_md(
                    file_name=file_name,
                    input_file_name=input_file,
                    knowledge_id=knowledge_id,
                    retain_images=bool(retain_images),
                )
                if not md_file_name: raise Exception(f"failed to parse {file_name}, please check backend log")

                # save images to minio
                if local_image_dir and retain_images == 1:
                    put_images_to_minio(
                        local_image_dir=local_image_dir,
                        knowledge_id=knowledge_id,
                        doc_id=doc_id,
                    )
                    # Handle it the same way you didmdDoc.
                loader = filetype_load_map["md"](file_path=md_file_name)
                documents = loader.load()
            else:
                if file_extension_name not in filetype_load_map:
                    raise KnowledgeFileNotSupportedError()
                loader = filetype_load_map[file_extension_name](file_path=input_file)
                documents = loader.load()

    logger.info(f"start_extract_title file_name={file_name}")
    if llm:
        t = time.time()
        for one in documents:
            # Configured correlationllmIf so, summarize the document
            title = extract_title(
                llm=llm,
                text=one.page_content,
                abstract_prompt=knowledge_llm.abstract_prompt,
            )
            # remove <think>.*</think> tag content
            one.metadata["title"] = parse_document_title(title)
        logger.info("file_extract_title=success timecost={}", time.time() - t)

    if file_extension_name in ["xls", "xlsx", "csv"]:
        for one in texts:
            one.metadata["title"] = documents[0].metadata.get("title", "")
    else:
        logger.info(f"start_split_text file_name={file_name}")
        texts = text_splitter.split_documents(documents)

    raw_texts = [t.page_content for t in texts]
    logger.info(f"start_process_metadata file_name={file_name}")
    metadatas = [

        Metadata(
            bbox=json.dumps({"chunk_bboxes": t.metadata.get("chunk_bboxes", "")}),
            page=(
                t.metadata["chunk_bboxes"][0].get("page")
                if t.metadata.get("chunk_bboxes", None)
                else t.metadata.get("page", 0)
            ),
            document_name=file_name,
            abstract=t.metadata.get("title", ""),
            chunk_index=t_index,
            user_metadata={}
        )
        for t_index, t in enumerate(texts)
    ]
    logger.info(f"file_chunk_over file_name=={file_name}")
    return raw_texts, metadatas, parse_type, partitions


async def async_read_chunk_text(
        invoke_user_id: int,
        input_file: str,
        file_name: str,
        separator: Optional[List[str]],
        separator_rule: Optional[List[str]],
        chunk_size: int,
        chunk_overlap: int,
        knowledge_id: Optional[int] = None,
        retain_images: int = 1,
        enable_formula: int = 1,
        force_ocr: int = 1,
        filter_page_header_footer: int = 0,
        excel_rule: ExcelRule = None,
        no_summary: bool = False,
) -> (List[str], List[Metadata], str, Any):  # type: ignore
    """Asynchronous version of read_chunk_text"""
    llm = None
    if not no_summary:
        try:
            llm = await async_decide_knowledge_llm(invoke_user_id)
            knowledge_llm = await LLMService.aget_knowledge_llm()
        except Exception as e:
            logger.exception("knowledge_llm_error:")
            raise Exception(
                f"Documentation Knowledge Base Summary Model is no longer valid, please go to Model Management-Configure in System Model Settings.{str(e)}"
            )

    text_splitter = ElemCharacterTextSplitter(
        separators=separator,
        separator_rule=separator_rule,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        is_separator_regex=True,
    )
    # Load document content
    logger.info(f"start_file_loader file_name={file_name}")
    parse_type = ParseType.UN_ETL4LM.value
    # excel File processing comes out separately
    partitions = []
    texts = []
    etl_for_lm_url = (await settings.async_get_knowledge()).etl4lm.url
    file_extension_name = file_name.split(".")[-1].lower()

    if file_extension_name in ["xls", "xlsx", "csv"]:
        # set default values.
        if not excel_rule:
            excel_rule = ExcelRule()

        # convert excel contents to markdown
        md_files_path, local_image_dir, doc_id = await util.sync_func_to_async(convert_file_to_md)(
            file_name=file_name,
            input_file_name=input_file,
            header_rows=[
                excel_rule.header_start_row - 1,  # convert to 0-based index
                excel_rule.header_end_row - 1,
            ],
            data_rows=excel_rule.slice_length,
            append_header=excel_rule.append_header,
            retain_images=bool(retain_images),
        )

        # skip following processes and return splited values.
        texts, documents = await util.sync_func_to_async(combine_multiple_md_files_to_raw_texts)(path=md_files_path)

    elif file_extension_name in ["doc", "docx", "html", "mhtml", "ppt", "pptx"]:

        if file_extension_name == "doc":
            # convert doc to docx
            input_file = await util.sync_func_to_async(convert_doc_to_docx)(input_doc_path=input_file)
            if not input_file:
                raise Exception(
                    f"failed to convert {file_name} to docx, please check backend log"
                )
        elif file_extension_name == "ppt":
            input_file = await asyncio.to_thread(convert_ppt_to_pptx, input_path=input_file)
            if not input_file:
                raise Exception("failed convert ppt to pptx, please check backend log")
        md_file_name, local_image_dir, doc_id = await util.sync_func_to_async(convert_file_to_md)(
            file_name=file_name,
            input_file_name=input_file,
            knowledge_id=knowledge_id,
            retain_images=bool(retain_images),
        )

        if not md_file_name:
            raise Exception(f"failed to parse {file_name}, please check backend log")

        # save images to minio
        if local_image_dir and retain_images == 1:
            await async_images_to_minio(
                local_image_dir=local_image_dir,
                knowledge_id=knowledge_id,
                doc_id=doc_id,
            )
        # will bepptxSave as preview file to
        if file_extension_name in ["ppt", "pptx"]:
            ppt_pdf_path = await util.sync_func_to_async(convert_ppt_to_pdf)(input_path=input_file)
            if ppt_pdf_path:
                await async_upload_preview_file_to_minio(input_file, ppt_pdf_path)
        elif file_extension_name == "doc":
            await async_upload_preview_file_to_minio(
                input_file.replace(".docx", ".doc"), input_file
            )

        # Handle it the same way you didmdDoc.
        loader = filetype_load_map["md"](file_path=md_file_name, autodetect_encoding=True)
        documents = await loader.aload()

    elif file_extension_name in ["txt", "md"]:
        loader = filetype_load_map[file_extension_name](file_path=input_file, autodetect_encoding=True)
        documents = await loader.aload()
    else:
        if etl_for_lm_url:
            if file_extension_name in ["pdf"]:
                # Determine if the document is damaged
                if is_pdf_damaged(input_file):
                    raise Exception('The file is damaged.')
            etl4lm_settings = (await settings.async_get_knowledge()).etl4lm
            loader = Etl4lmLoader(
                file_name,
                input_file,
                unstructured_api_url=etl4lm_settings.url,
                ocr_sdk_url=etl4lm_settings.ocr_sdk_url,
                force_ocr=bool(force_ocr),
                enable_formular=bool(enable_formula),
                timeout=etl4lm_settings.timeout,
                filter_page_header_footer=bool(filter_page_header_footer),
                knowledge_id=knowledge_id,
            )
            documents = await loader.aload()
            parse_type = ParseType.ETL4LM.value
            partitions = loader.partitions
            partitions = parse_partitions(partitions)
        else:
            if file_extension_name in ['pdf']:
                md_file_name, local_image_dir, doc_id = await util.sync_func_to_async(convert_file_to_md)(
                    file_name=file_name,
                    input_file_name=input_file,
                    knowledge_id=knowledge_id,
                    retain_images=bool(retain_images),
                )
                if not md_file_name: raise Exception(f"failed to parse {file_name}, please check backend log")

                # save images to minio
                if local_image_dir and retain_images == 1:
                    await async_images_to_minio(
                        local_image_dir=local_image_dir,
                        knowledge_id=knowledge_id,
                        doc_id=doc_id,
                    )
                    # Handle it the same way you didmdDoc.
                loader = filetype_load_map["md"](file_path=md_file_name)
                documents = await loader.aload()
            else:
                if file_extension_name not in filetype_load_map:
                    raise Exception("Type not supported")
                loader = filetype_load_map[file_extension_name](file_path=input_file)
                documents = await loader.aload()

    logger.info(f"start_extract_title file_name={file_name}")
    if llm:
        t = time.time()
        for one in documents:
            # Configured correlationllmIf so, summarize the document
            title = await async_extract_title(
                llm=llm,
                text=one.page_content,
                abstract_prompt=knowledge_llm.abstract_prompt,
            )
            # remove <think>.*</think> tag content
            one.metadata["title"] = parse_document_title(title)
        logger.info("file_extract_title=success timecost={}", time.time() - t)

    if file_extension_name in ["xls", "xlsx", "csv"]:
        for one in texts:
            one.metadata["title"] = documents[0].metadata.get("title", "")
    else:
        logger.info(f"start_split_text file_name={file_name}")
        texts = text_splitter.split_documents(documents)

    raw_texts = [t.page_content for t in texts]
    logger.info(f"start_process_metadata file_name={file_name}")
    metadatas = [

        Metadata(
            bbox=json.dumps({"chunk_bboxes": t.metadata.get("chunk_bboxes", "")}),
            page=(
                t.metadata["chunk_bboxes"][0].get("page")
                if t.metadata.get("chunk_bboxes", None)
                else t.metadata.get("page", 0)
            ),
            document_name=file_name,
            abstract=t.metadata.get("title", ""),
            chunk_index=t_index,
            user_metadata={}
        )
        for t_index, t in enumerate(texts)
    ]
    logger.info(f"file_chunk_over file_name=={file_name}")
    return raw_texts, metadatas, parse_type, partitions


def text_knowledge(
        db_knowledge: Knowledge, db_file: KnowledgeFile, documents: List[Document]
):
    """Usetext Importknowledge"""
    embeddings = LLMService.get_bisheng_knowledge_embedding_sync(model_id=int(db_knowledge.model),
                                                                 invoke_user_id=db_file.user_id)
    vectore_client = decide_vectorstores(
        db_knowledge.collection_name, "Milvus", embeddings
    )
    logger.info("vector_init_conn_done milvus={}", db_knowledge.collection_name)
    index_name = db_knowledge.index_name or db_knowledge.collection_name
    es_client = decide_vectorstores(index_name, "ElasticKeywordsSearch", embeddings)

    separator = "\n\n"
    chunk_size = 1000
    chunk_overlap = 100

    text_splitter = CharacterTextSplitter(
        separator=separator,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        add_start_index=True,
    )

    texts = text_splitter.split_documents(documents)

    logger.info(f"chunk_split knowledge_id={db_knowledge.id} size={len(texts)}")

    # Storage mysql
    file_name = documents[0].metadata.get("source")
    db_file.file_name = file_name
    with get_sync_db_session() as session:
        session.add(db_file)
        session.commit()
        session.refresh(db_file)
    result = db_file.model_dump()
    try:
        metadata = [
            {
                "file_id": db_file.id,
                "knowledge_id": f"{db_knowledge.id}",
                "page": doc.metadata.pop("page", 1),
                "source": doc.metadata.pop("source", ""),
                "bbox": doc.metadata.pop("bbox", ""),
                "extra": json.dumps(doc.metadata, ensure_ascii=False),
                "title": "",
                "chunk_index": index,
            }
            for index, doc in enumerate(documents)
        ]
        vectore_client.add_texts(
            texts=[t.page_content for t in texts], metadatas=metadata
        )

        # Storagees
        if es_client:
            es_client.add_texts(
                texts=[t.page_content for t in texts], metadatas=metadata
            )
        db_file.status = 2
        result["status"] = 2
        with get_sync_db_session() as session:
            session.add(db_file)
            session.commit()
    except Exception as e:
        logger.error(e)
        setattr(db_file, "status", 3)
        setattr(db_file, "remark", str(e)[:500])
        with get_sync_db_session() as session:
            session.add(db_file)
            session.commit()
        result["status"] = 3
        result["remark"] = str(e)[:500]
    return result


def delete_vector(collection_name: str, partition_key: str):
    try:
        embeddings = FakeEmbedding()
        vectore_client = decide_vectorstores(collection_name, 'Milvus', embeddings)
        if isinstance(vectore_client.col, Collection):
            if partition_key:
                pass
            else:
                res = vectore_client.col.drop(timeout=1)
                logger.info('act=delete_milvus col={} res={}', collection_name, res)
    except Exception as e:
        # Handle situations where a collection does not exist or where there are other errors
        logger.warning(f'act=delete_milvus_failed col={collection_name} error={str(e)}')
        # Even an error is considered a successful deletion as the goal is to ensure that there is no dirty data


def delete_es(index_name: str):
    try:
        embeddings = FakeEmbedding()
        esvectore_client = decide_vectorstores(index_name, 'ElasticKeywordsSearch', embeddings)

        if esvectore_client:
            res = esvectore_client.client.indices.delete(index=index_name, ignore=[400, 404])
            logger.info(f'act=delete_es index={index_name} res={res}')
    except Exception as e:
        # Dealing with non-existent indexes or other errors
        logger.warning(f'act=delete_es_failed index={index_name} error={str(e)}')
        # Even an error is considered a successful deletion as the goal is to ensure that there is no dirty data


def QA_save_knowledge(db_knowledge: Knowledge, QA: QAKnowledge):
    """Usetext Importknowledge"""

    questions = QA.questions
    answer = json.loads(QA.answers)[0]
    extra = {}
    if QA.extra_meta:
        extra = json.loads(QA.extra_meta) or {}
    extra.update({"answer": answer, "main_question": questions[0]})
    docs = [Document(page_content=question, metadata=extra) for question in questions]
    try:
        embeddings = LLMService.get_bisheng_knowledge_embedding_sync(invoke_user_id=QA.user_id,
                                                                     model_id=int(db_knowledge.model))
        vector_client = decide_vectorstores(
            db_knowledge.collection_name, "Milvus", embeddings
        )
        es_client = decide_vectorstores(
            db_knowledge.index_name, "ElasticKeywordsSearch", embeddings
        )
        logger.info(
            f"vector_init_conn_done col={db_knowledge.collection_name} index={db_knowledge.index_name}"
        )
        # Unificationdocument
        metadata = [
            {
                "file_id": QA.id,
                "knowledge_id": f"{db_knowledge.id}",
                "page": doc.metadata.pop("page", 1),
                "source": doc.metadata.pop("source", ""),
                "bbox": doc.metadata.pop("bbox", ""),
                "title": doc.metadata.pop("title", ""),
                "chunk_index": index,
                "extra": json.dumps(doc.metadata, ensure_ascii=False),
            }
            for index, doc in enumerate(docs)
        ]
        vector_client.add_texts(
            texts=[t.page_content for t in docs], metadatas=metadata
        )
        logger.info(f"qa_save_knowledge add vector over")
        es_client.add_texts(texts=[t.page_content for t in docs], metadatas=metadata)
        logger.info(f"qa_save_knowledge add es over")

        QA.status = QAStatus.ENABLED.value
        KnowledgeFileDao.update(QA)
    except Exception as e:
        logger.error(e)
        setattr(QA, "status", QAStatus.FAILED.value)
        setattr(QA, "remark", KnowledgeFileFailedError(exception=e).to_json_str())
        KnowledgeFileDao.update(QA)

    return QA


def add_qa(db_knowledge: Knowledge, data: QAKnowledgeUpsert) -> QAKnowledge:
    """Usetext ImportQAknowledge"""
    if db_knowledge.type != 1:
        raise Exception("knowledge type error")
    try:
        # Similar question unified insertion
        questions = data.questions
        if questions:
            if data.id:
                qa_db = QAKnoweldgeDao.get_qa_knowledge_by_primary_id(data.id)
                qa_db.questions = questions
                qa_db.answers = data.answers
                qa = QAKnoweldgeDao.update(qa_db)
                # Needs to be deleted before insertion
                delete_vector_data(db_knowledge, [data.id])
            else:
                qa = QAKnoweldgeDao.insert_qa(data)
                telemetry_service.log_event_sync(
                    user_id=qa.user_id,
                    event_type=BaseTelemetryTypeEnum.NEW_KNOWLEDGE_FILE,
                    trace_id=trace_id_var.get()
                )

            # Right.questionTo be performedembedding, and then enter the Knowledge Base
            qa = QA_save_knowledge(db_knowledge, qa)
            return qa
    except Exception as e:
        logger.exception(e)
        raise e


def qa_status_change(qa_db: QAKnowledge, target_status: int, db_knowledge: Knowledge):
    """QA State toggle"""

    if qa_db.status == target_status:
        logger.info("qa status is same, skip")
        return
    if target_status == QAStatus.DISABLED.value:
        delete_vector_data(db_knowledge, [qa_db.id])
        qa_db.status = target_status
        QAKnoweldgeDao.update(qa_db)
    else:
        qa_db.status = QAStatus.PROCESSING.value
        QAKnoweldgeDao.update(qa_db)
        QA_save_knowledge(db_knowledge, qa_db)
    return qa_db


async def list_qa_by_knowledge_id(
        knowledge_id: int,
        page_size: int = 10,
        page_num: int = 1,
        question: Optional[str] = None,
        answer: Optional[str] = None,
        keyword: Optional[str] = None,
        status: Optional[int] = None,
) -> list[Any] | tuple[Any, Any]:
    """Get all under knowledge baseqa"""
    if not knowledge_id:
        return []

    count_sql = select(func.count(QAKnowledge.id)).where(
        QAKnowledge.knowledge_id == knowledge_id
    )
    list_sql = select(QAKnowledge).where(QAKnowledge.knowledge_id == knowledge_id)

    if status:
        count_sql = count_sql.where(QAKnowledge.status == status)
        list_sql = list_sql.where(QAKnowledge.status == status)

    if question:
        count_sql = count_sql.where(QAKnowledge.questions.like(f"%{question}%"))
        list_sql = list_sql.where(QAKnowledge.questions.like(f"%{question}%"))

    if answer:
        count_sql = count_sql.where(QAKnowledge.answers.like(f"%{answer}%"))
        list_sql = list_sql.where(QAKnowledge.answers.like(f"%{answer}%"))

    if keyword:
        count_sql = count_sql.where(
            or_(
                QAKnowledge.questions.like(f"%{keyword}%"),
                QAKnowledge.answers.like(f"%{keyword}%"),
            )
        )
        list_sql = list_sql.where(
            or_(
                QAKnowledge.answers.like(f"%{keyword}%"),
                QAKnowledge.questions.like(f"%{keyword}%"),
            )
        )

    list_sql = (
        list_sql.order_by(QAKnowledge.update_time.desc())
        .limit(page_size)
        .offset((page_num - 1) * page_size)
    )
    count = await QAKnoweldgeDao.total_count(count_sql)
    list_qa = await QAKnoweldgeDao.query_by_condition(list_sql)

    return list_qa, count


def delete_vector_data(knowledge: Knowledge, file_ids: List[int]):
    """Delete vector data, Want to make a general purpose that can be dockedlangchainright of privacyvectorDB"""
    # embeddings = FakeEmbedding()
    # vectore_config_dict: dict = settings.get_knowledge().get('vectorstores')
    # if not vectore_config_dict:
    #     raise Exception('Vector database must be configured')
    # elastic_index = knowledge.index_name or knowledge.collection_name
    # vectore_client_list = [
    #     decide_vectorstores(elastic_index, db, embeddings) if db == 'ElasticKeywordsSearch' else
    #     decide_vectorstores(knowledge.collection_name, db, embeddings)
    #     for db in vectore_config_dict.keys()
    # ]
    # logger.info('vector_init_conn_done col={} dbs={}', knowledge.collection_name,
    #             vectore_config_dict.keys())

    # for vectore_client in vectore_client_list:
    # Inquiryvector primary key
    embeddings = FakeEmbedding()
    collection_name = knowledge.collection_name
    # <g id="Bold">Medical Treatment:</g>vectordb
    vectore_client = decide_vectorstores(collection_name, "Milvus", embeddings)
    try:
        if isinstance(vectore_client.col, Collection):
            pk = vectore_client.col.query(
                expr=f"file_id in {file_ids}", output_fields=["pk"], timeout=10
            )
        else:
            pk = []
    except Exception:
        # Want to try that again?
        logger.error("timeout_except")
        vectore_client.close_connection(vectore_client.alias)
        vectore_client = decide_vectorstores(collection_name, "Milvus", embeddings)
        pk = vectore_client.col.query(
            expr=f"file_id in {file_ids}", output_fields=["pk"], timeout=10
        )
    logger.info("query_milvus pk={}", pk)
    if pk:
        res = vectore_client.col.delete(f"pk in {[p['pk'] for p in pk]}", timeout=10)
        logger.info(f"act=delete_vector file_id={file_ids} res={res}")
    vectore_client.close_connection(vectore_client.alias)

    # elastic
    index_name = knowledge.index_name or collection_name
    esvectore_client = decide_vectorstores(
        index_name, "ElasticKeywordsSearch", embeddings
    )

    if esvectore_client:
        res = esvectore_client.client.delete_by_query(
            index=index_name, body={"query": {"terms": {"metadata.file_id": file_ids}}}
        )
    logger.info(f"act=delete_es  res={res}")
    return True


def recommend_question(invoke_user_id: int, question: str, answer: str, number: int = 3) -> List[str]:
    from langchain.chains.llm import LLMChain
    from langchain_core.prompts.prompt import PromptTemplate

    prompt = """- Role: Problem Generation Specialist
        - Background: Users want to generate similar questions based on given questions and answers through artificial intelligence models in order to expand the knowledge base or for educational and testing purposes.
        - Profile: You are a professional data analyst and language modeler who specializes in extracting patterns from existing data and generating new relevant questions.
        - Constrains: Ensure that the generated questions are semantically similar to the original questions, while maintaining diversity and avoiding duplication.
        - Workflow:
        1. Analyze questions and answers entered by users and extract keywords and topics.
        2. Create similar questions based on extracted keywords and topics.
        3. Verify that the generated questions are semantically similar to the original questions and ensure diversity.
        - Examples:
        Question:"What is the capital of France?"
        Answers:"Paris"
        Buat3similar questions:
        - "What is the name of the capital of France?"
        - "Which city is the capital of France?"
        - "What country's capital is Paris?"

        Please usejson Return
        {{"questions": Generated Question List}}

        Here are the questions and answers provided by the user:
        Question:{question}
        Answers:{answer}

        You generated{number}similar questions:
    """
    llm = LLMService.get_knowledge_similar_llm(invoke_user_id)
    if not llm:
        raise KnowledgeSimilarError.http_exception()

    llm_chain = LLMChain(llm=llm, prompt=PromptTemplate.from_template(prompt))
    gen_question = llm_chain.predict(question=question, answer=answer, number=number)
    try:
        code_ret = extract_code_blocks(gen_question)
        if code_ret:
            question_dict = json.loads(code_ret[0])
            return question_dict["questions"]
        elif gen_question:
            question_dict = json.loads(gen_question)
            return question_dict.get("questions", [])
        else:
            logger.info("md_code_extract_error {}", gen_question)
        return []
    except Exception as exc:
        logger.error("recommend_question json.loads error:{}", gen_question)
        raise ValueError(gen_question) from exc


def extract_code_blocks(markdown_code_block: str):
    # Define regular expression patterns
    pattern = r"```\w*\s*(.*?)```"

    # Use re.DOTALL letting . Ability to match line breaks
    matches = re.findall(pattern, markdown_code_block, re.DOTALL)

    # Remove whitespace at both ends of each code block
    return [match.strip() for match in matches]
