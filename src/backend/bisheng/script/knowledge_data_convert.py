import argparse
import json
import traceback
from typing import List, Dict

from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.script.knowledge_data_fix import get_all_knowledge_files, _get_milvus_chunks_data, _get_es_chunks_data
from bisheng.utils.embedding import decide_embeddings

user_map = {}


def get_user_name_by_id(user_id: int):
    from bisheng.database.models.user import UserDao

    if user_id in user_map:
        return user_map[user_id]
    tmp_user = UserDao.get_user(user_id)
    if tmp_user:
        user_map[user_id] = tmp_user.user_name
        return tmp_user.user_name

    return f"unknown user: {user_id}"


def convert_new_metadata(old_metadata: Dict, file: KnowledgeFile, knowledge: Knowledge):
    user_metadata = {}
    if old_metadata.get("extra"):
        try:
            user_metadata = json.loads(old_metadata["extra"])
        except Exception:
            pass
    return {
        "document_id": file.id,
        "document_name": file.file_name,
        "abstract": old_metadata.get("title", ""),
        "chunk_index": old_metadata.get("chunk_index", 0),
        "bbox": old_metadata.get("bbox", ""),
        "page": old_metadata.get("page", 0),
        "knowledge_id": knowledge.id,
        "upload_time": int(file.create_time.timestamp()),
        "update_time": int(file.update_time.timestamp()),
        "uploader": get_user_name_by_id(file.user_id),
        "updater": get_user_name_by_id(file.user_id),
        "user_metadata": user_metadata,
    }


def convert_milvus_data(knowledge: Knowledge, all_file: List[KnowledgeFile], new_collection_name: str):
    print(f"正在转换 ID:{knowledge.id} 的Milvus数据...")
    # convert_milvus_chunk
    # 新的Milvus对象

    embedding = decide_embeddings(knowledge.model)
    new_milvus = KnowledgeRag.init_milvus_vectorstore(new_collection_name, embedding,
                                                      metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA)

    for file in all_file:
        all_file_chunk = _get_milvus_chunks_data(knowledge, all_fields_expect_pk=True, file_id=file.id)
        if not all_file_chunk:
            print(f"知识库 ID:{knowledge.id} 的文件：{file.id}没有Milvus数据，跳过转换。")
            continue
        if all_file_chunk[0].get("document_id"):
            print(f"知识库 ID:{knowledge.id} 的Milvus数据已经是新格式，跳过转换。")
            return None
        new_texts = []
        new_metadata = []
        new_embedding = []
        for one in all_file_chunk:
            new_texts.append(one["text"])
            new_metadata.append(convert_new_metadata(one, file, knowledge))
            new_embedding.append(one["vector"])
        new_milvus.add_embeddings(texts=new_texts, embeddings=new_embedding, metadatas=new_metadata)

    # 在这里添加转换逻辑
    print(f"知识库 ID:{knowledge.id} 的Milvus数据转换完成。")
    return new_milvus


def convert_es_data(knowledge: Knowledge, all_file: List[KnowledgeFile], new_index_name: str):
    print(f"正在转换 ID:{knowledge.id} 的Elasticsearch数据...")
    # convert_es_chunk
    es_vectorstore = KnowledgeRag.init_es_vectorstore_sync(new_index_name,
                                                           metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA)
    for file in all_file:
        all_file_chunk = _get_es_chunks_data(knowledge, source=True, file_id=file.id)
        if not all_file_chunk:
            print(f"知识库 ID:{knowledge.id} 的文件：{file.id}没有es数据，跳过转换。")
            continue
        if all_file_chunk[0].get("document_id"):
            print(f"知识库 ID:{knowledge.id} 的ES数据已经是新格式，跳过转换。")
            return None
        new_texts = []
        new_metadata = []
        for one in all_file_chunk:
            new_texts.append(one["_source"]["text"])
            new_metadata.append(convert_new_metadata(one["_source"]["metadata"], file, knowledge))
        es_vectorstore.add_texts(texts=new_texts, metadatas=new_metadata)

    print(f"知识库 ID:{knowledge.id} 的Elasticsearch数据转换完成。")
    return es_vectorstore


def convert_one_knowledge_data(knowledge: Knowledge):
    print(f"开始转换 ID:{knowledge.id}  {knowledge.name} 的数据...")
    if knowledge.collection_name.startswith("partition_"):
        print(f"！！！跳过分区知识库 ID:{knowledge.id} 的数据转换。请先进行数据修复")
        return
    if knowledge.type == KnowledgeTypeEnum.QA.value:
        print(f"跳过QA知识库 ID:{knowledge.id} 的数据转换。!!!")
        return

    all_file = get_all_knowledge_files(knowledge.id)
    old_collection_name = knowledge.collection_name
    old_index_name = knowledge.index_name
    new_collection_name = f"{old_collection_name}_new"
    new_index_name = f"{old_index_name}_new"
    try:
        old_milvus_vector = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(knowledge)
        old_fields = old_milvus_vector.col.schema.fields
        old_fields = {field.name: field for field in old_fields}
        if "document_id" in old_fields:
            print(f"知识库 ID:{knowledge.id} 的数据已经是新格式，跳过转换。")
            return
        milvus_vector = convert_milvus_data(knowledge, all_file, new_collection_name)
        es_vector = convert_es_data(knowledge, all_file, new_index_name)
        if milvus_vector and es_vector:
            knowledge.collection_name = new_collection_name
            knowledge.index_name = new_index_name
            KnowledgeDao.update_one(knowledge)
            # clear old data
            milvus_vector.client.drop_collection(old_collection_name)
            if es_vector.client.indices.exists(index=old_index_name):
                es_vector.client.indices.delete(index=old_index_name)
        else:
            print(f"知识库 ID:{knowledge.id} 的数据无需更新。")
    except Exception as e:
        print(f"知识库 ID:{knowledge.id} 数据转换失败，错误原因：{e}")
        traceback.print_exc()
    # 在这里添加转换逻辑
    print(f"知识库 ID:{knowledge.id} 的数据转换完成。")


def convert_all_knowledge_data():
    all_knowledge = KnowledgeDao.get_all_knowledge()
    total = len(all_knowledge)
    for index, knowledge in enumerate(all_knowledge):
        print(
            f"convert progress: {round((index + 1) / total * 100, 2)}% knowledge id: {knowledge.id} name: {knowledge.name}")
        convert_one_knowledge_data(knowledge)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', type=str, default="convert_all",
                        help='模式。convert_all: 转换所有知识库的数据；convert_one: 转换某一个知识库的数据')
    # 单个进程的最大并发数
    parser.add_argument('--id', type=int, default=0, help='知识库ID，如果是操作单个知识库时，参数必填')
    args = parser.parse_args()

    if args.mode == "convert_all":
        convert_all_knowledge_data()
    elif args.mode == "convert_one":
        tmp_knowledge = KnowledgeDao.query_by_id(args.id)
        convert_one_knowledge_data(tmp_knowledge)
    else:
        print("mode参数错误,只能是 convert_all 或 convert_one")
