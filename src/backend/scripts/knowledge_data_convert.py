import argparse
import json
import traceback
from typing import List, Dict

from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.llm.domain import LLMService
from bisheng.script.knowledge_data_fix import get_all_knowledge_files, _get_milvus_chunks_data, _get_es_chunks_data

user_map = {}


def get_user_name_by_id(user_id: int):
    from bisheng.user.domain.models.user import UserDao

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
    print(f"converting ID:{knowledge.id} right of privacyMilvusDATA...")
    # convert_milvus_chunk
    # New.. MilvusObjects

    embedding = LLMService.get_bisheng_knowledge_embedding_sync(0, model_id=int(knowledge.model))
    new_milvus = KnowledgeRag.init_milvus_vectorstore(new_collection_name, embedding,
                                                      metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA)

    for file in all_file:
        all_file_chunk = _get_milvus_chunks_data(knowledge, all_fields_expect_pk=True, file_id=file.id)
        if not all_file_chunk:
            print(f"The knowledge base upon ID:{knowledge.id} from here{file.id}NoMilvusdata, skipping the conversion.")
            continue
        if all_file_chunk[0].get("document_id"):
            print(f"The knowledge base upon ID:{knowledge.id} right of privacyMilvusData is already in the new format, skipping conversion.")
            return None
        new_texts = []
        new_metadata = []
        new_embedding = []
        for one in all_file_chunk:
            new_texts.append(one["text"])
            new_metadata.append(convert_new_metadata(one, file, knowledge))
            new_embedding.append(one["vector"])
        new_milvus.add_embeddings(texts=new_texts, embeddings=new_embedding, metadatas=new_metadata)

    # Add conversion logic here
    print(f"The knowledge base upon ID:{knowledge.id} right of privacyMilvusData conversion complete.")
    return new_milvus


def convert_es_data(knowledge: Knowledge, all_file: List[KnowledgeFile], new_index_name: str):
    print(f"converting ID:{knowledge.id} right of privacyElasticsearchDATA...")
    # convert_es_chunk
    es_vectorstore = KnowledgeRag.init_es_vectorstore_sync(new_index_name,
                                                           metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA)
    for file in all_file:
        all_file_chunk = _get_es_chunks_data(knowledge, source=True, file_id=file.id)
        if not all_file_chunk:
            print(f"The knowledge base upon ID:{knowledge.id} from here{file.id}Noesdata, skipping the conversion.")
            continue
        if all_file_chunk[0].get("document_id"):
            print(f"The knowledge base upon ID:{knowledge.id} right of privacyESData is already in the new format, skipping conversion.")
            return None
        new_texts = []
        new_metadata = []
        for one in all_file_chunk:
            new_texts.append(one["_source"]["text"])
            new_metadata.append(convert_new_metadata(one["_source"]["metadata"], file, knowledge))
        es_vectorstore.add_texts(texts=new_texts, metadatas=new_metadata)

    print(f"The knowledge base upon ID:{knowledge.id} right of privacyElasticsearchData conversion complete.")
    return es_vectorstore


def convert_one_knowledge_data(knowledge: Knowledge):
    print(f"Start Conversion ID:{knowledge.id}  {knowledge.name} Data...")
    if knowledge.collection_name.startswith("partition_"):
        print(f"!!! Skip partition knowledge base ID:{knowledge.id} Data conversion. Please repair the data first")
        return
    if knowledge.type == KnowledgeTypeEnum.QA.value:
        print(f"SkipQAThe knowledge base upon ID:{knowledge.id} Data conversion.!!!")
        return

    all_file = get_all_knowledge_files(knowledge.id)
    old_collection_name = knowledge.collection_name
    old_index_name = knowledge.index_name
    new_collection_name = f"{old_collection_name}_new"
    new_index_name = f"{old_index_name}_new"
    try:
        old_milvus_vector = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(0, knowledge)
        old_fields = old_milvus_vector.col.schema.fields
        old_fields = {field.name: field for field in old_fields}
        if "document_id" in old_fields:
            print(f"The knowledge base upon ID:{knowledge.id} The data is already in the new format, skipping the conversion.")
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
            print(f"The knowledge base upon ID:{knowledge.id} Data does not need to be updated.")
    except Exception as e:
        print(f"The knowledge base upon ID:{knowledge.id} Data conversion failed, error reason:{e}")
        traceback.print_exc()
    # Add conversion logic here
    print(f"The knowledge base upon ID:{knowledge.id} Data conversion complete.")


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
                        help='modalities.convert_all: Convert data from all knowledge bases;convert_one: Convert data from a knowledge base')
    # Maximum number of concurrency for a single process
    parser.add_argument('--id', type=int, default=0, help='The knowledge base uponID, parameter is required if operating a single knowledge base')
    args = parser.parse_args()

    if args.mode == "convert_all":
        convert_all_knowledge_data()
    elif args.mode == "convert_one":
        tmp_knowledge = KnowledgeDao.query_by_id(args.id)
        if not tmp_knowledge:
            print(f"The knowledge base upon ID:{args.id} It does not exist and cannot be converted.")
            exit(0)
        convert_one_knowledge_data(tmp_knowledge)
    else:
        print("modeParameter salah,can only be convert_all OR convert_one")
