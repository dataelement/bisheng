import json
import os
import re
import time
from typing import Any, Dict, List, Optional, BinaryIO

import requests
from bisheng_langchain.rag.extract_info import extract_title
from bisheng_langchain.text_splitter import ElemCharacterTextSplitter
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

from bisheng.api.errcode.knowledge import KnowledgeSimilarError
from bisheng.api.services.etl4lm_loader import Etl4lmLoader
from bisheng.api.services.handler.impl.xls_split_handle import XlsSplitHandle
from bisheng.api.services.handler.impl.xlsx_split_handle import XlsxSplitHandle
from bisheng.api.services.libreoffice_converter import (
    convert_doc_to_docx,
    convert_ppt_to_pdf,
)
from bisheng.api.services.llm import LLMService
from bisheng.api.services.md_from_pdf import is_pdf_damaged
from bisheng.api.services.patch_130 import (
    convert_file_to_md,
    combine_multiple_md_files_to_raw_texts,
)
from bisheng.api.utils import md5_hash
from bisheng.api.v1.schemas import ExcelRule
from bisheng.cache.redis import redis_client
from bisheng.cache.utils import file_download
from bisheng.database.base import session_getter
from bisheng.database.models.knowledge import Knowledge, KnowledgeDao
from bisheng.database.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileDao,
    KnowledgeFileStatus,
    ParseType,
    QAKnoweldgeDao,
    QAKnowledge,
    QAKnowledgeUpsert,
    QAStatus,
)
from bisheng.interface.embeddings.custom import FakeEmbedding
from bisheng.interface.importing.utils import import_vectorstore
from bisheng.interface.initialize.loading import instantiate_vectorstore
from bisheng.settings import settings
from bisheng.utils.embedding import decide_embeddings
from bisheng.utils.minio_client import minio_client

filetype_load_map = {
    "txt": TextLoader,
    "pdf": PyPDFLoader,
    "html": BSHTMLLoader,
    "md": TextLoader,
    "docx": UnstructuredWordDocumentLoader,
    "pptx": UnstructuredPowerPointLoader,
}

split_handles = [
    XlsxSplitHandle(),
    XlsSplitHandle(),
]


class KnowledgeUtils:
    # 用来区分chunk和自动生产的总结内容  格式如：文件名\n文档总结\n--------\n chunk内容
    chunk_split = "\n----------\n"

    @classmethod
    def get_preview_cache_key(cls, knowledge_id: int, file_path: str) -> str:
        md5_value = md5_hash(file_path)
        return f"preview_file_chunk:{knowledge_id}:{md5_value}"

    @classmethod
    def aggregate_chunk_metadata(cls, chunk: str, metadata: dict) -> str:
        # 拼接chunk和metadata中的数据，获取新的chunk
        res = f"{{<file_title>{metadata.get('source', '')}</file_title>\n"
        if metadata.get("title", ""):
            res += f"<file_abstract>{metadata.get('title', '')}</file_abstract>\n"
        res += f"<paragraph_content>{chunk}</paragraph_content>}}"
        return res

    @classmethod
    def chunk2promt(cls, chunk: str, metadata: dict) -> str:
        # 拼接chunk和metadata中的数据，获取新的chunk
        res = f"[file name]:{metadata.get('source', '')}\n[file content begin]\n{chunk}[file content end]\n"
        return res

    @classmethod
    def split_chunk_metadata(cls, chunk: str) -> str:
        # 从拼接后的chunk中分离出原始chunk

        # 说明是旧的拼接规则
        if not chunk.startswith("{<file_title>"):
            return chunk.split(cls.chunk_split)[-1]

        chunk = chunk.split("<paragraph_content>")[-1]
        chunk = chunk.split("</paragraph_content>")[0]
        return chunk

    @classmethod
    def save_preview_cache(
            cls, cache_key, mapping: dict = None, chunk_index: int = 0, value: dict = None
    ):
        if mapping:
            for key, val in mapping.items():
                mapping[key] = json.dumps(val, ensure_ascii=False)
            redis_client.hset(cache_key, mapping=mapping)
        else:
            redis_client.hset(
                cache_key, key=chunk_index, value=json.dumps(value, ensure_ascii=False)
            )

    @classmethod
    def delete_preview_cache(cls, cache_key, chunk_index: int = None):
        if chunk_index is None:
            redis_client.delete(cache_key)
            redis_client.delete(f"{cache_key}_parse_type")
            redis_client.delete(f"{cache_key}_file_path")
            redis_client.delete(f"{cache_key}_partitions")
        else:
            redis_client.hdel(cache_key, chunk_index)

    @classmethod
    def get_preview_cache(cls, cache_key, chunk_index: int = None) -> dict:
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
    def get_knowledge_file_image_dir(cls, doc_id: str, knowledge_id: int = None) -> str:
        """获取文件图片在minio的存储目录"""
        if knowledge_id:
            return f"knowledge/images/{knowledge_id}/{doc_id}"
        else:
            return f"tmp/images/{doc_id}"

    @classmethod
    def get_knowledge_file_object_name(cls, file_id: int, file_name: str) -> str:
        """获取知识库源文件在minio的存储路径"""
        file_ext = file_name.split(".")[-1]
        return f"original/{file_id}.{file_ext}"

    @classmethod
    def get_knowledge_bbox_file_object_name(cls, file_id: int) -> str:
        """获取知识库文件对应的bbox文件在minio的存储路径"""
        return f"partitions/{file_id}.json"

    @classmethod
    def get_knowledge_preview_file_object_name(
            cls, file_id: int, file_name: str
    ) -> Optional[str]:
        """获取知识库文件对应的预览文件在minio的存储路径 这个路径是存储在正式bucket内"""
        file_ext = file_name.split(".")[-1]
        if file_ext == "doc":
            return f"preview/{file_id}.docx"
        elif file_ext in ["ppt", "pptx"]:
            return f"preview/{file_id}.pdf"
        # 其他类型的文件不需要预览文件
        return None

    @classmethod
    def get_tmp_preview_file_object_name(cls, file_path: str) -> Optional[str]:
        """获取临时预览文件在minio的存储路径 这个路径是存储在临时bucket"""
        file_name = os.path.basename(file_path)
        file_name_no_ext, file_ext = file_name.rsplit(".", 1)
        if file_ext == "doc":
            return f"preview/{file_name_no_ext}.docx"
        elif file_ext in ["ppt", "pptx"]:
            return f"preview/{file_name_no_ext}.pdf"
        # 其他类型的文件不需要预览文件
        return None


def put_images_to_minio(local_image_dir, knowledge_id, doc_id):
    if not os.path.exists(local_image_dir):
        return

    files = [f for f in os.listdir(local_image_dir)]
    for file_name in files:
        local_file_name = f"{local_image_dir}/{file_name}"
        object_name = f"{KnowledgeUtils.get_knowledge_file_image_dir(doc_id, knowledge_id)}/{file_name}"
        file_obj: BinaryIO = open(local_file_name, "rb")
        minio_client.upload_minio_file(
            object_name=object_name, file=file_obj, bucket_name=minio_client.bucket
        )


def process_file_task(
        knowledge: Knowledge,
        db_files: List[KnowledgeFile],
        separator: List[str],
        separator_rule: List[str],
        chunk_size: int,
        chunk_overlap: int,
        callback_url: str = None,
        extra_metadata: str = None,
        preview_cache_keys: List[str] = None,
        retain_images: int = 1,
        enable_formula: int = 1,
        force_ocr: int = 0,
        filter_page_header_footer: int = 0,
):
    """处理知识文件任务"""
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
                file.remark = str(e)[:500]
                KnowledgeFileDao.update(file)
        logger.info("update files failed status over")
        raise e


def delete_vector_files(file_ids: List[int], knowledge: Knowledge) -> bool:
    """ 删除知识文件的向量数据和es数据 """
    if not file_ids:
        return True
    logger.info(f"delete_files file_ids={file_ids} knowledge_id={knowledge.id}")
    embeddings = FakeEmbedding()
    vector_client = decide_vectorstores(knowledge.collection_name, "Milvus", embeddings)
    vector_client.col.delete(expr=f"file_id in {file_ids}", timeout=10)
    vector_client.close_connection(vector_client.alias)
    logger.info(f"delete_milvus file_ids={file_ids}")

    es_client = decide_vectorstores(
        knowledge.index_name, "ElasticKeywordsSearch", embeddings
    )
    for one in file_ids:
        res = es_client.client.delete_by_query(
            index=knowledge.index_name, query={"match": {"metadata.file_id": one}}
        )
        logger.info(f"act=delete_es file_id={one} res={res}")
    return True


def delete_minio_files(file: KnowledgeFile):
    """删除知识库文件在minio上的存储"""

    # 删除源文件
    if file.object_name:
        minio_client.delete_minio(file.object_name)

    # 删除bbox文件
    if file.bbox_object_name:
        minio_client.delete_minio(file.bbox_object_name)

    # 删除转换后的pdf文件
    minio_client.delete_minio(f"{file.id}")

    # 删除预览文件
    preview_object_name = KnowledgeUtils.get_knowledge_preview_file_object_name(
        file.id, file.file_name
    )
    if preview_object_name:
        minio_client.delete_minio(preview_object_name)
    return True


def delete_knowledge_file_vectors(file_ids: List[int], clear_minio: bool = True):
    """删除知识文件信息"""
    knowledge_files = KnowledgeFileDao.select_list(file_ids=file_ids)

    knowledge_ids = [file.knowledge_id for file in knowledge_files]
    knowledges = KnowledgeDao.get_list_by_ids(knowledge_ids)
    if len(knowledges) > 1:
        raise ValueError("不支持多个知识库的文件同时删除")
    knowledge = knowledges[0]
    delete_vector_files(file_ids, knowledge)

    if clear_minio:
        for file in knowledge_files:
            delete_minio_files(file)
    return True


def decide_vectorstores(
        collection_name: str, vector_store: str, embedding: Embeddings
) -> VectorStore:
    """vector db"""
    param: dict = {"embedding": embedding}

    if vector_store == "ElasticKeywordsSearch":
        vector_config = settings.get_vectors_conf().elasticsearch.model_dump()
        if not vector_config:
            # 无相关配置
            raise RuntimeError("vector_stores.elasticsearch not find in config.yaml")
        param["index_name"] = collection_name
        if isinstance(vector_config["ssl_verify"], str):
            vector_config["ssl_verify"] = eval(vector_config["ssl_verify"])

    elif vector_store == "Milvus":
        vector_config = settings.get_vectors_conf().milvus.model_dump()
        if not vector_config:
            # 无相关配置
            raise RuntimeError("vector_stores.milvus not find in config.yaml")
        param["collection_name"] = collection_name
        vector_config.pop("partition_suffix", "")
        vector_config.pop("is_partition", "")
    else:
        raise RuntimeError("unknown vector store type")

    param.update(vector_config)
    class_obj = import_vectorstore(vector_store)
    return instantiate_vectorstore(vector_store, class_object=class_obj, params=param)


def decide_knowledge_llm() -> Any:
    """获取用来总结知识库chunk的 llm对象"""
    # 获取llm配置
    knowledge_llm = LLMService.get_knowledge_llm()
    if not knowledge_llm.extract_title_model_id:
        # 无相关配置
        return None

    # 获取llm对象
    return LLMService.get_bisheng_llm(
        model_id=knowledge_llm.extract_title_model_id, cache=False
    )


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
        extra_meta: str = None,
        preview_cache_keys: List[str] = None,
        retain_images: int = 1,
        enable_formula: int = 1,
        force_ocr: int = 0,
        filter_page_header_footer: int = 0,
):
    """将文件加入到向量和es库内"""

    logger.info("start process files")
    embeddings = decide_embeddings(model)

    logger.info("start init Milvus")
    vector_client = decide_vectorstores(collection_name, "Milvus", embeddings)

    logger.info("start init ElasticKeywordsSearch")
    es_client = decide_vectorstores(index_name, "ElasticKeywordsSearch", embeddings)

    for index, db_file in enumerate(knowledge_files):
        # 尝试从缓存中获取文件的分块
        preview_cache_key = None
        if preview_cache_keys:
            preview_cache_key = (
                preview_cache_keys[index] if index < len(preview_cache_keys) else None
            )
        try:
            logger.info(
                f"process_file_begin file_id={db_file.id} file_name={db_file.file_name}"
            )
            # TODO:TJU: 多list里面取值
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
                # 增加的参数
                retain_images=retain_images,
                knowledge_id=knowledge_id,
                enable_formula=enable_formula,
                force_ocr=force_ocr,
                filter_page_header_footer=filter_page_header_footer,
            )
            db_file.status = KnowledgeFileStatus.SUCCESS.value
        except Exception as e:
            logger.exception(
                f"process_file_fail file_id={db_file.id} file_name={db_file.file_name}"
            )
            db_file.status = KnowledgeFileStatus.FAILED.value
            db_file.remark = str(e)[:500]
        finally:
            logger.info(
                f"process_file_end file_id={db_file.id} file_name={db_file.file_name}"
            )
            KnowledgeFileDao.update(db_file)
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
        extra_meta: str = None,
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

    file_url = minio_client.get_share_link(db_file.object_name)
    filepath, _ = file_download(file_url)

    if not vector_client:
        raise ValueError("vector db not found, please check your milvus config")
    if not es_client:
        raise ValueError("es not found, please check your es config")

    # Convert split_rule string to dict if needed
    excel_rule = ExcelRule()
    if db_file.split_rule and isinstance(db_file.split_rule, str):
        split_rule = json.loads(db_file.split_rule)
        if "excel_rule" in split_rule:
            excel_rule = ExcelRule(**split_rule["excel_rule"])
    # # extract text from file
    texts, metadatas, parse_type, partitions = read_chunk_text(
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
    if len(texts) == 0:
        raise ValueError("文件解析为空")
    # 缓存中有数据则用缓存中的数据去入库，因为是用户在界面编辑过的
    if preview_cache_key:
        all_chunk_info = KnowledgeUtils.get_preview_cache(preview_cache_key)
        if all_chunk_info:
            logger.info(
                f"get_preview_cache file={db_file.id} file_name={db_file.file_name}"
            )
            texts, metadatas = [], []
            for key, val in all_chunk_info.items():
                texts.append(val["text"])
                metadatas.append(val["metadata"])
    for index, one in enumerate(texts):
        if len(one) > 10000:
            raise ValueError(
                "分段结果超长，请尝试在自定义策略中使用更多切分符（例如 \\n、。、\\.）进行切分"
            )
        # 入库时 拼接文件名和文档摘要
        texts[index] = KnowledgeUtils.aggregate_chunk_metadata(one, metadatas[index])

    db_file.parse_type = parse_type
    # 存储ocr识别后的partitions结果
    if partitions:
        partition_data = json.dumps(partitions, ensure_ascii=False).encode("utf-8")
        db_file.bbox_object_name = KnowledgeUtils.get_knowledge_bbox_file_object_name(
            db_file.id
        )
        minio_client.upload_minio_data(
            db_file.bbox_object_name,
            partition_data,
            len(partition_data),
            "application/json",
        )

    logger.info(
        f"chunk_split file={db_file.id} file_name={db_file.file_name} size={len(texts)}"
    )
    for metadata in metadatas:
        metadata.update(
            {
                "file_id": db_file.id,
                "knowledge_id": f"{db_file.knowledge_id}",
                "extra": extra_meta or "",
            }
        )

    logger.info(f"add_vectordb file={db_file.id} file_name={db_file.file_name}")
    # 存入milvus
    vector_client.add_texts(texts=texts, metadatas=metadatas)

    logger.info(f"add_es file={db_file.id} file_name={db_file.file_name}")
    # 存入es
    es_client.add_texts(texts=texts, metadatas=metadatas)

    logger.info(f"add_complete file={db_file.id} file_name={db_file.file_name}")

    if preview_cache_key:
        KnowledgeUtils.delete_preview_cache(preview_cache_key)

    if db_file.file_name.endswith((".doc", ".ppt", ".pptx")):
        tmp_preview_file = KnowledgeUtils.get_tmp_preview_file_object_name(filepath)

        preview_object_name = KnowledgeUtils.get_knowledge_preview_file_object_name(
            db_file.id, db_file.file_name
        )
        logger.info(
            f"upload_preview_file_to_minio file={db_file.id} tmp_object_name={tmp_preview_file}, preview_object_name={preview_object_name}"
        )
        if minio_client.object_exists(minio_client.tmp_bucket, tmp_preview_file):
            minio_client.copy_object(
                tmp_preview_file,
                preview_object_name,
                minio_client.tmp_bucket,
                minio_client.bucket,
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
    # 存入milvus
    vector_client.add_texts(texts=texts, metadatas=metadatas)

    logger.info(f"add_es file={db_file.id} file_name={db_file.file_name}")
    # 存入es
    es_client.add_texts(texts=texts, metadatas=metadatas)


def parse_partitions(partitions: List[Any]) -> Dict:
    """解析生成bbox和文本的对应关系"""
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
                val = text[indexes[index][0]:indexes[index][1] + 1]
            res[key] = {"text": val, "type": part["type"], "part_id": part_index}
    return res


def upload_preview_file_to_minio(original_file_path: str, preview_file_path: str):
    if (
            os.path.basename(original_file_path).split(".")[0]
            != os.path.basename(preview_file_path).split(".")[0]
    ):
        logger.error(
            f"原始文件和预览文件路径不匹配: {original_file_path} vs {preview_file_path}"
        )
    object_name = KnowledgeUtils.get_tmp_preview_file_object_name(original_file_path)
    with open(preview_file_path, "rb") as file_obj:
        # 上传预览文件到minio
        minio_client.upload_minio_file(
            object_name=object_name, file=file_obj, bucket_name=minio_client.tmp_bucket
        )
    return object_name


def parse_document_title(title: str) -> str:
    """
    解析文档标题，去除特殊字符和多余空格
    :param title: 文档标题
    :return: 处理后的标题
    """
    # 去除思考模型的think标签内容
    title = re.sub("<think>.*</think>", "", title, flags=re.S).strip()

    # 如果有符合md 代码快的标记则去除代码块标记
    if final_title := extract_code_blocks(title):
        title = "\n".join(final_title)
    return title


def read_chunk_text(
        input_file,
        file_name,
        separator: List[str],
        separator_rule: List[str],
        chunk_size: int,
        chunk_overlap: int,
        knowledge_id: Optional[int] = None,
        retain_images: int = 1,
        enable_formula: int = 1,
        force_ocr: int = 1,
        filter_page_header_footer: int = 0,
        excel_rule: ExcelRule = None,
) -> (List[str], List[dict], str, Any):  # type: ignore
    """
    0：chunks text
    1：chunks metadata
    2：parse_type: etl4lm or un_etl4lm
    3: ocr bbox data: maybe None
    """
    # 获取文档总结标题的llm
    try:
        llm = decide_knowledge_llm()
        knowledge_llm = LLMService.get_knowledge_llm()
    except Exception as e:
        logger.exception("knowledge_llm_error:")
        raise Exception(
            f"文档知识库总结模型已失效，请前往模型管理-系统模型设置中进行配置。{str(e)}"
        )
    text_splitter = ElemCharacterTextSplitter(
        separators=separator,
        separator_rule=separator_rule,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        is_separator_regex=True,
    )
    # 加载文档内容
    logger.info(f"start_file_loader file_name={file_name}")
    parse_type = ParseType.UN_ETL4LM.value
    # excel 文件的处理单独出来
    partitions = []
    texts = []
    etl_for_lm_url = settings.get_knowledge().get("etl4lm", {}).get("url", None)
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
        # 将pptx转为预览文件存到
        if file_extension_name in ["ppt", "pptx"]:
            ppt_pdf_path = convert_ppt_to_pdf(input_path=input_file)
            if ppt_pdf_path:
                upload_preview_file_to_minio(input_file, ppt_pdf_path)
        elif file_extension_name == "doc":
            upload_preview_file_to_minio(
                input_file.replace(".docx", ".doc"), input_file
            )

        # 沿用原来的方法处理md文件
        loader = filetype_load_map["md"](file_path=md_file_name)
        documents = loader.load()

    elif file_extension_name in ["txt", "md"]:
        loader = filetype_load_map[file_extension_name](file_path=input_file)
        documents = loader.load()
    else:
        if etl_for_lm_url:
            if file_extension_name in ["pdf"]:
                # 判断文件是否损坏
                if is_pdf_damaged(input_file):
                    raise Exception('The file is damaged.')
            etl4lm_settings = settings.get_knowledge().get("etl4lm", {})
            loader = Etl4lmLoader(
                file_name,
                input_file,
                unstructured_api_url=etl4lm_settings.get("url", ""),
                ocr_sdk_url=etl4lm_settings.get("ocr_sdk_url", ""),
                force_ocr=bool(force_ocr),
                enable_formular=bool(enable_formula),
                timeout=etl4lm_settings.get("timeout", 60),
                filter_page_header_footer=bool(filter_page_header_footer),
                knowledge_id=knowledge_id,
            )
            documents = loader.load()
            parse_type = ParseType.ETL4LM.value
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
                    # 沿用原来的方法处理md文件
                loader = filetype_load_map["md"](file_path=md_file_name)
                documents = loader.load()
            else:
                if file_extension_name not in filetype_load_map:
                    raise Exception("类型不支持")
                loader = filetype_load_map[file_extension_name](file_path=input_file)
                documents = loader.load()

    logger.info(f"start_extract_title file_name={file_name}")
    if llm:
        t = time.time()
        for one in documents:
            # 配置了相关llm的话，就对文档做总结
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
        {
            "bbox": json.dumps({"chunk_bboxes": t.metadata.get("chunk_bboxes", "")}),
            "page": (
                t.metadata["chunk_bboxes"][0].get("page")
                if t.metadata.get("chunk_bboxes", None)
                else t.metadata.get("page", 0)
            ),
            "source": file_name,
            "title": t.metadata.get("title", ""),
            "chunk_index": t_index,
            "extra": "",
        }
        for t_index, t in enumerate(texts)
    ]
    logger.info(f"file_chunk_over file_name=={file_name}")
    return raw_texts, metadatas, parse_type, partitions


def text_knowledge(
        db_knowledge: Knowledge, db_file: KnowledgeFile, documents: List[Document]
):
    """使用text 导入knowledge"""
    embeddings = decide_embeddings(db_knowledge.model)
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

    # 存储 mysql
    file_name = documents[0].metadata.get("source")
    db_file.file_name = file_name
    with session_getter() as session:
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

        # 存储es
        if es_client:
            es_client.add_texts(
                texts=[t.page_content for t in texts], metadatas=metadata
            )
        db_file.status = 2
        result["status"] = 2
        with session_getter() as session:
            session.add(db_file)
            session.commit()
    except Exception as e:
        logger.error(e)
        setattr(db_file, "status", 3)
        setattr(db_file, "remark", str(e)[:500])
        with session_getter() as session:
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
        # 处理集合不存在或其他错误的情况
        logger.warning(f'act=delete_milvus_failed col={collection_name} error={str(e)}')
        # 即使出错也视为成功删除，因为目标是确保没有脏数据


def delete_es(index_name: str):
    try:
        embeddings = FakeEmbedding()
        esvectore_client = decide_vectorstores(index_name, 'ElasticKeywordsSearch', embeddings)

        if esvectore_client:
            res = esvectore_client.client.indices.delete(index=index_name, ignore=[400, 404])
            logger.info(f'act=delete_es index={index_name} res={res}')
    except Exception as e:
        # 处理索引不存在或其他错误的情况
        logger.warning(f'act=delete_es_failed index={index_name} error={str(e)}')
        # 即使出错也视为成功删除，因为目标是确保没有脏数据


def QA_save_knowledge(db_knowledge: Knowledge, QA: QAKnowledge):
    """使用text 导入knowledge"""

    questions = QA.questions
    answer = json.loads(QA.answers)[0]
    extra = {}
    if QA.extra_meta:
        extra = json.loads(QA.extra_meta) or {}
    extra.update({"answer": answer, "main_question": questions[0]})
    docs = [Document(page_content=question, metadata=extra) for question in questions]
    try:
        embeddings = decide_embeddings(db_knowledge.model)
        vector_client = decide_vectorstores(
            db_knowledge.collection_name, "Milvus", embeddings
        )
        es_client = decide_vectorstores(
            db_knowledge.index_name, "ElasticKeywordsSearch", embeddings
        )
        logger.info(
            f"vector_init_conn_done col={db_knowledge.collection_name} index={db_knowledge.index_name}"
        )
        # 统一document
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

        # vector_client.add_texts(
        #     texts=[t.page_content for t in docs], metadatas=metadata
        # )

        texts = [t.page_content for t in docs]

        max_attempts = 5
        success = False
        for attempt in range(max_attempts):
            try:
                vector_client.add_texts(texts=texts, metadatas=metadata)
                validation_query = texts[0]
                search_results = vector_client.search(query=validation_query, search_type="similarity", k=100)
                matched = any(
                    result.metadata.get('file_id') == QA.id and
                    result.metadata.get('knowledge_id') == f'{db_knowledge.id}'
                    for result in search_results
                )
                if matched:
                    success = True
                    logger.debug(f'jjxx validation_query:{validation_query} success')
                    break  # 验证成功，跳出重试循环
            except Exception as e:
                raise e
        if not success:
            raise ValueError("插入向量库失败")

        logger.info(f"qa_save_knowledge add vector over")
        es_client.add_texts(texts=[t.page_content for t in docs], metadatas=metadata)
        logger.info(f"qa_save_knowledge add es over")
        QA.status = QAStatus.ENABLED.value
        KnowledgeFileDao.update(QA)
    except Exception as e:
        logger.debug(f'jjxx validation_query:{e} error')
        logger.error(e)
        setattr(QA, "status", QAStatus.FAILED.value)
        setattr(QA, "remark", str(e)[:500])
        KnowledgeFileDao.update(QA)

    return QA


def add_qa(db_knowledge: Knowledge, data: QAKnowledgeUpsert) -> QAKnowledge:
    """使用text 导入QAknowledge"""
    if db_knowledge.type != 1:
        raise Exception("knowledge type error")
    try:
        # 相似问统一插入
        questions = data.questions
        if questions:
            if data.id:
                qa_db = QAKnoweldgeDao.get_qa_knowledge_by_primary_id(data.id)
                qa_db.questions = questions
                qa_db.answers = data.answers
                qa = QAKnoweldgeDao.update(qa_db)
                # 需要先删除再插入
                delete_vector_data(db_knowledge, [data.id])
            else:
                qa = QAKnoweldgeDao.insert_qa(data)

            # 对question进行embedding，然后录入知识库
            qa = QA_save_knowledge(db_knowledge, qa)
            return qa
    except Exception as e:
        logger.exception(e)
        raise e

def add_qa_batch(db_knowledge: Knowledge, data_list: List[QAKnowledgeUpsert]) -> List[QAKnowledge]:
    result = []
    for data in data_list:
        QA = add_qa(db_knowledge, data)
        result.append(QA)
    return result


def qa_status_change(qa_id: int, target_status: int):
    """QA 状态切换"""
    qa_db = QAKnoweldgeDao.get_qa_knowledge_by_primary_id(qa_id)

    if qa_db.status == target_status:
        logger.info("qa status is same, skip")
        return

    db_knowledge = KnowledgeDao.query_by_id(qa_db.knowledge_id)
    if target_status == QAStatus.DISABLED.value:
        delete_vector_data(db_knowledge, [qa_id])
        qa_db.status = target_status
        QAKnoweldgeDao.update(qa_db)
    else:
        qa_db.status = QAStatus.PROCESSING.value
        QAKnoweldgeDao.update(qa_db)
        QA_save_knowledge(db_knowledge, qa_db)
    return qa_db


def list_qa_by_knowledge_id(
        knowledge_id: int,
        page_size: int = 10,
        page_num: int = 1,
        question: Optional[str] = None,
        answer: Optional[str] = None,
        keyword: Optional[str] = None,
        status: Optional[int] = None,
) -> List[QAKnowledge]:
    """获取知识库下的所有qa"""
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
    count = QAKnoweldgeDao.total_count(count_sql)
    list_qa = QAKnoweldgeDao.query_by_condition(list_sql)

    return list_qa, count


def delete_vector_data(knowledge: Knowledge, file_ids: List[int]):
    """删除向量数据, 想做一个通用的，可以对接langchain的vectorDB"""
    # embeddings = FakeEmbedding()
    # vectore_config_dict: dict = settings.get_knowledge().get('vectorstores')
    # if not vectore_config_dict:
    #     raise Exception('向量数据库必须配置')
    # elastic_index = knowledge.index_name or knowledge.collection_name
    # vectore_client_list = [
    #     decide_vectorstores(elastic_index, db, embeddings) if db == 'ElasticKeywordsSearch' else
    #     decide_vectorstores(knowledge.collection_name, db, embeddings)
    #     for db in vectore_config_dict.keys()
    # ]
    # logger.info('vector_init_conn_done col={} dbs={}', knowledge.collection_name,
    #             vectore_config_dict.keys())

    # for vectore_client in vectore_client_list:
    # 查询vector primary key
    embeddings = FakeEmbedding()
    collection_name = knowledge.collection_name
    # 处理vectordb
    vectore_client = decide_vectorstores(collection_name, "Milvus", embeddings)
    try:
        if isinstance(vectore_client.col, Collection):
            pk = vectore_client.col.query(
                expr=f"file_id in {file_ids}", output_fields=["pk"], timeout=10
            )
        else:
            pk = []
    except Exception:
        # 重试一次
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


def recommend_question(question: str, answer: str, number: int = 3) -> List[str]:
    from langchain.chains.llm import LLMChain
    from langchain_core.prompts.prompt import PromptTemplate

    prompt = """- Role: 问题生成专家
        - Background: 用户希望通过人工智能模型根据给定的问题和答案生成相似的问题，以便于扩展知识库或用于教育和测试目的。
        - Profile: 你是一位专业的数据分析师和语言模型专家，擅长从现有数据中提取模式，并生成新的相关问题。
        - Constrains: 确保生成的问题在语义上与原始问题相似，同时保持多样性，避免重复。
        - Workflow:
        1. 分析用户输入的问题和答案，提取关键词和主题。
        2. 根据提取的关键词和主题创建相似问题。
        3. 验证生成的问题与原始问题在语义上的相似性，并确保多样性。
        - Examples:
        问题："法国的首都是哪里？"
        答案："巴黎"
        生成3个相似问题：
        - "法国的首都叫什么名字？"
        - "哪个城市是法国的首都？"
        - "巴黎是哪个国家的首都？"

        请使用json 返回
        {{"questions": 生成的问题列表}}

        以下是用户提供的问题和答案：
        问题：{question}
        答案：{answer}

        你生成的{number}个相似问题：
    """
    llm = LLMService.get_knowledge_similar_llm()
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
    # 定义正则表达式模式
    pattern = r"```\w*\s*(.*?)```"

    # 使用 re.DOTALL 使 . 能够匹配换行符
    matches = re.findall(pattern, markdown_code_block, re.DOTALL)

    # 去除每段代码块两端的空白字符
    return [match.strip() for match in matches]
