import argparse
import os
from typing import List

import openpyxl
from pymilvus import Collection

from bisheng.api.services.knowledge_imp import decide_vectorstores, QA_save_knowledge, delete_vector_data
from bisheng.database.models.knowledge import KnowledgeDao, Knowledge, KnowledgeTypeEnum
from bisheng.database.models.knowledge_file import QAKnoweldgeDao, KnowledgeFileDao, QAKnowledge, KnowledgeFile, \
    QAStatus, KnowledgeFileStatus
from bisheng.utils.embedding import decide_embeddings
from bisheng.worker.knowledge.file_worker import insert_milvus

_output_path = os.path.join(os.path.dirname(__file__), 'output')
os.makedirs(_output_path, exist_ok=True)


def get_all_knowledge() -> List[Knowledge]:
    all_knowledge = []
    page = 1
    limit = 1000
    while True:
        knowledge = KnowledgeDao.get_all_knowledge(page=page, limit=limit)
        if not knowledge:
            break
        page += 1
        all_knowledge.extend(knowledge)
    return all_knowledge


def get_all_qa_knowledge_files(knowledge_id: int) -> List[QAKnowledge]:
    all_files = []
    page = 1
    limit = 1000
    while True:
        files = QAKnoweldgeDao.get_qa_knowledge_by_knowledge_id(knowledge_id, page=page, page_size=limit)
        if not files:
            break
        page += 1
        for file in files:
            if file.status != QAStatus.ENABLED.value:
                continue
            all_files.append(file)
    return all_files


def get_all_knowledge_files(knowledge_id: int) -> List[KnowledgeFile]:
    all_files = []
    page = 1
    limit = 1000
    while True:
        files = KnowledgeFileDao.get_file_by_filters(knowledge_id, page=page, page_size=limit)
        if not files:
            break
        page += 1
        for file in files:
            if file.status != KnowledgeFileStatus.SUCCESS.value:
                continue
            all_files.append(file)
    return all_files


def _get_es_chunks_data(knowledge: Knowledge, es_obj=None, source: bool = False):
    if not es_obj:
        embedding = decide_embeddings(knowledge.model)
        es_obj = decide_vectorstores(knowledge.index_name or knowledge.collection_name, "ElasticKeywordsSearch",
                                     embedding)
    es_client = es_obj.client
    all_chunks = []

    def handle_hits(hits):
        for hit in hits:
            all_chunks.append({
                "file_id": hit['fields']['metadata.file_id'][0],
                "source": hit['fields']['metadata.source'][0],
                "extra": hit['fields']['metadata.extra'][0],
                "_id": hit['_id'],
                "_source": hit['_source'] if source else None,
            })

    result = es_client.search(index=knowledge.index_name or knowledge.collection_name,
                              query={"match_all": {}},
                              size=5000,
                              scroll="5m",
                              source=source,
                              fields=["_id", "metadata.source", "metadata.file_id", "metadata.extra"])
    handle_hits(result["hits"]["hits"])
    scroll_id = result['_scroll_id']
    while True:
        result = es_client.scroll(scroll_id=scroll_id, scroll='1m')
        tmp_hits = result['hits']['hits']
        if not tmp_hits:
            break
        handle_hits(tmp_hits)
        scroll_id = result['_scroll_id']
    es_client.clear_scroll(scroll_id=scroll_id)
    return all_chunks


def _get_milvus_chunks_data(knowledge: Knowledge, milvus_obj=None, all_fields_expect_pk: bool = False):
    if not milvus_obj:
        embedding = decide_embeddings(knowledge.model)
        milvus_obj = decide_vectorstores(knowledge.collection_name, "Milvus", embedding)
    all_milvus_chunks = []
    output_fields = ["file_id", "extra", "source", "pk"]
    if all_fields_expect_pk:
        output_fields = [s.name for s in milvus_obj.col.schema.fields if s.name != "pk"]
    iterator = milvus_obj.col.query_iterator(
        batch_size=1000,
        expr=f"knowledge_id=='{knowledge.id}'" if knowledge.collection_name.startswith("partition_") else None,
        output_fields=output_fields,
        timeout=30,
    )
    while True:
        result = iterator.next()
        if not result:
            iterator.close()
            break
        all_milvus_chunks.extend(result)
    return all_milvus_chunks


def _scan_knowledge_error_data(knowledge: Knowledge, all_file_data: List[KnowledgeFile | QAKnowledge], milvus_obj,
                               es_obj):
    all_milvus_chunks = _get_milvus_chunks_data(knowledge, milvus_obj)
    judge_qa_chunk = lambda x: not x.get("source")
    if knowledge.type != KnowledgeTypeEnum.QA.value:
        judge_qa_chunk = lambda x: x.get("source")
    all_milvus_chunks_map = {
        item["file_id"]: item for item in all_milvus_chunks if judge_qa_chunk(item)  # source 不存在说明是QA对的数据，否则是文档知识库的数据
    }
    all_es_chunks = _get_es_chunks_data(knowledge, es_obj)
    all_es_chunks_map = {
        item["file_id"]: item for item in all_es_chunks if judge_qa_chunk(item)  # source 不存在说明是QA对的数据，否则是文档知识库的数据
    }
    no_data = []
    no_milvus_data = []
    no_es_data = []
    for file in all_file_data:
        milvus_flag = file.id in all_milvus_chunks_map
        if milvus_flag:
            all_milvus_chunks_map.pop(file.id)
        es_flag = file.id in all_es_chunks_map
        if es_flag:
            all_es_chunks_map.pop(file.id)
        if not milvus_flag and not es_flag:
            no_data.append(file)
        elif not milvus_flag:
            no_milvus_data.append(file)
        elif not es_flag:
            no_es_data.append(file)

    return no_data, no_milvus_data, no_es_data, all_milvus_chunks_map, all_es_chunks_map


def scan_qa_knowledge_error_data(knowledge: Knowledge, milvus_obj, es_obj):
    """ scan all qa knowledge data and find those that not exist in milvus """
    all_qa = get_all_qa_knowledge_files(knowledge.id)
    return _scan_knowledge_error_data(knowledge, all_qa, milvus_obj, es_obj)


def scan_normal_knowledge_error_data(knowledge: Knowledge, milvus_obj, es_obj):
    """ scan all normal knowledge data and find those that not exist in milvus """
    all_files = get_all_knowledge_files(knowledge.id)
    return _scan_knowledge_error_data(knowledge, all_files, milvus_obj, es_obj)


def _file_status(file: KnowledgeFile):
    if file.status == KnowledgeFileStatus.PROCESSING.value:
        return "解析中"
    elif file.status == KnowledgeFileStatus.SUCCESS.value:
        return "解析成功"
    elif file.status == KnowledgeFileStatus.FAILED.value:
        return "解析失败"
    elif file.status == KnowledgeFileStatus.REBUILDING.value:
        return "重建中"
    else:
        return "未知状态"


def _qa_status(file: QAKnowledge):
    if file.status == QAStatus.ENABLED.value:
        return "启用"
    elif file.status == QAStatus.DISABLED.value:
        return "禁用"
    elif file.status == QAStatus.PROCESSING.value:
        return "处理中"
    elif file.status == QAStatus.FAILED.value:
        return "处理失败"
    else:
        return "未知状态"


def _knowledge_common_row(knowledge: Knowledge, note: str = ""):
    one_common_row = [knowledge.id, knowledge.name, knowledge.collection_name, knowledge.index_name]
    if knowledge.type == KnowledgeTypeEnum.QA.value:
        one_common_row.append("QA知识库")
    elif knowledge.type == KnowledgeTypeEnum.NORMAL.value:
        one_common_row.append("文档知识库")
    elif knowledge.type == KnowledgeTypeEnum.PRIVATE.value:
        one_common_row.append("个人知识库")
    else:
        one_common_row.append("未知类型知识库")
    one_common_row.append(knowledge.create_time.strftime("%Y-%m-%d %H:%M:%S"))
    one_common_row.append(knowledge.update_time.strftime("%Y-%m-%d %H:%M:%S"))
    one_common_row.append(note)
    return one_common_row


def _file_row(knowledge: Knowledge, file: KnowledgeFile | QAKnowledge, milvus_flag: str, es_flag: str):
    return [
        file.id,
        file.file_name if knowledge.type != KnowledgeTypeEnum.QA.value else file.questions[0],
        _file_status(file) if knowledge.type != KnowledgeTypeEnum.QA.value else _qa_status(file),
        file.create_time.strftime("%Y-%m-%d %H:%M:%S"),
        file.update_time.strftime("%Y-%m-%d %H:%M:%S"),
        milvus_flag,
        es_flag,
    ]


def _init_knowledge_obj(knowledge: Knowledge):
    try:
        embedding = decide_embeddings(knowledge.model)
    except Exception as e:
        print(
            f"!!!! skip knowledge_id: {knowledge.id}; knowledge_name: {knowledge.name} because embedding model error: {e}")
        raise Exception(f"跳过该知识库，原因：embedding模型错误: {e}")
    try:
        milvus_obj = decide_vectorstores(knowledge.collection_name, "Milvus", embedding)
        if milvus_obj.col is None:
            raise Exception("跳过该知识库，原因：Milvus collection name not exist")
        collection_info = milvus_obj.col.schema
        fields = collection_info.fields
        fields = {field.name: 1 for field in fields}
        if "extra" not in fields or "source" not in fields or "file_id" not in fields:
            raise Exception("跳过该知识库，原因：Milvus fields not found file_id or source or extra")
    except Exception as e:
        print(
            f"!!!! skip knowledge_id: {knowledge.id}; knowledge_name: {knowledge.name} because milvus connection error: {e}")
        raise Exception(f"跳过该知识库，原因：Milvus连接错误: {e}")
    try:
        es_obj = decide_vectorstores(knowledge.index_name or knowledge.collection_name, "ElasticKeywordsSearch",
                                     embedding)
    except Exception as e:
        print(
            f"!!!! skip knowledge_id: {knowledge.id}; knowledge_name: {knowledge.name} because es connection error: {e}")
        raise Exception(f"跳过该知识库，原因：ES连接错误: {e}")
    return milvus_obj, es_obj


def _save_knowledge_error_data(rows: List[List[str]], file_name: str):
    header_rows = [
        ['知识库ID', '知识库名称', 'collection_name', 'index_name', '知识库类型', '知识库创建时间', '知识库更新时间',
         '知识库备注', '文件ID', '文件名称',
         '文件状态',
         '文件创建时间', '文件更新时间', 'Milvus是否存在', 'ES是否存在']
    ]
    if not rows:
        print("no error data found")
        return
    rows = header_rows + rows
    wb = openpyxl.workbook.Workbook()
    sh = wb.active
    for row in rows:
        sh.append(row)
    file_path = os.path.join(_output_path, file_name)
    wb.save(file_path)
    print(f"=========== knowledge error data file saved to: {file_path}")


def scan_one_knowledge(knowledge: Knowledge = None, knowledge_id: int = None) -> List[List[str]]:
    """ return error data rows for one knowledge """
    if not knowledge:
        knowledge = KnowledgeDao.query_by_id(knowledge_id)
        if not knowledge:
            print(f"knowledge_id: {knowledge_id} not exist")
            return []
    try:
        milvus_obj, es_obj = _init_knowledge_obj(knowledge)
    except Exception as e:
        print(
            f"!!!! skip knowledge_id: {knowledge.id}; knowledge_name: {knowledge.name} because error: {e}")
        return [_knowledge_common_row(knowledge, str(e))]
    if knowledge.type == KnowledgeTypeEnum.QA.value:
        no_data, no_milvus_data, no_es_data, milvus_extra, es_extra = scan_qa_knowledge_error_data(knowledge,
                                                                                                   milvus_obj,
                                                                                                   es_obj)
    else:
        no_data, no_milvus_data, no_es_data, milvus_extra, es_extra = scan_normal_knowledge_error_data(knowledge,
                                                                                                       milvus_obj,
                                                                                                       es_obj)
    if not no_data and not no_milvus_data and not no_es_data:
        return []
    print(f"!!!! find error data knowledge_id: {knowledge.id}; knowledge_name: {knowledge.name}")
    note = ""
    if milvus_extra and es_extra:
        note = "Milvus 和 ES 存在冗余数据"
    elif milvus_extra:
        note = "Milvus 存在冗余数据"
    elif es_extra:
        note = "ES 存在冗余数据"
    one_common_row = _knowledge_common_row(knowledge, note)

    def _parse_one_row(file, milvus_flag: str, es_flag: str):
        one_row = one_common_row.copy()
        one_row.extend(_file_row(knowledge, file, milvus_flag, es_flag))

        return one_row

    rows = []
    for one in no_data:
        rows.append(_parse_one_row(one, "否", "否"))
    for one in no_milvus_data:
        rows.append(_parse_one_row(one, "否", "是"))
    for one in no_es_data:
        rows.append(_parse_one_row(one, "是", "否"))
    return rows


def scan_knowledge_error_data():
    """ scan all knowledge data and find those that not exist in milvus """
    all_knowledge = get_all_knowledge()

    total = len(all_knowledge)
    rows = []
    for index, knowledge in enumerate(all_knowledge):
        print(
            f"{round(index / total * 100, 2)}% ---- start scan knowledge_id: {knowledge.id}; knowledge_name: {knowledge.name}")

        error_rows = scan_one_knowledge(knowledge)
        if error_rows:
            rows.extend(error_rows)
        else:
            print(f"==== no error data knowledge_id: {knowledge.id}; knowledge_name: {knowledge.name}")

    _save_knowledge_error_data(rows, "all_knowledge_error_data.xlsx")

    return None


def _sync_milvus_new_collection_name(knowledge: Knowledge, milvus_obj) -> bool:
    """ copy knowledge data to new milvus collection name """
    embedding = decide_embeddings(knowledge.model)
    new_collection_name = knowledge.index_name or knowledge.collection_name
    if new_collection_name == knowledge.collection_name:
        return milvus_obj
    # create new collection name
    new_col = Collection(name=new_collection_name, schema=milvus_obj.col.schema, using=milvus_obj.alias,
                         consistency_level=milvus_obj.consistency_level)
    new_milvus_obj = decide_vectorstores(new_collection_name, "Milvus", embedding)

    output_fields = [s.name for s in milvus_obj.col.schema.fields if s.name != "pk"]

    try:
        # get old chunks
        all_chunks = _get_milvus_chunks_data(knowledge, milvus_obj, all_fields_expect_pk=True)
        insert_milvus(all_chunks, output_fields, new_milvus_obj)
        knowledge.collection_name = new_collection_name
        knowledge = KnowledgeDao.update_one(knowledge)
        return new_milvus_obj
    except Exception as e:
        print(
            f"!!!! copy vector data knowledge_id: {knowledge.id}; knowledge_name: {knowledge.name} error: {e}")
        new_milvus_obj.col.delete()
        return False


def _fix_knowledge_data(knowledge: Knowledge, milvus_obj, es_obj, all_files: List[QAKnowledge | KnowledgeFile]):
    """ fix all qa knowledge data """
    if knowledge.collection_name.startswith("partition_"):
        print("start copy milvus data to new collection_name")
        milvus_obj = _sync_milvus_new_collection_name(knowledge, milvus_obj)
        if not milvus_obj:
            raise Exception(f"copy milvus data to new collection_name failed")
        print("finish copy milvus data to new collection_name")

    all_milvus_chunk = _get_milvus_chunks_data(knowledge, milvus_obj, all_fields_expect_pk=True)
    all_milvus_chunk_map = {}
    all_es_chunk = _get_es_chunks_data(knowledge, es_obj, source=True)
    all_es_chunk_map = {}

    judge_qa_chunk = lambda x: not x.get("source")
    if knowledge.type != KnowledgeTypeEnum.QA.value:
        judge_qa_chunk = lambda x: x.get("source")

    remove_pk = []
    remove_id = []
    for item in all_milvus_chunk:
        # have source, is doc chunk
        if not judge_qa_chunk(item):
            remove_pk.append(item.get("pk"))
            continue
        if item["file_id"] not in all_milvus_chunk_map:
            all_milvus_chunk_map[item["file_id"]] = []
        all_milvus_chunk_map[item["file_id"]].append(item)
    for item in all_es_chunk:
        # no source, is qa chunk
        if not judge_qa_chunk(item):
            remove_id.append(item.get("_id"))
            continue
        if item["file_id"] not in all_es_chunk_map:
            all_es_chunk_map[item["file_id"]] = []
        all_es_chunk_map[item["file_id"]].append(item)
    old_all_milvus_chunk_map = all_milvus_chunk_map.copy()
    old_all_es_chunk_map = all_es_chunk_map.copy()
    no_data = []
    no_milvus_data = []
    no_es_data = []
    for file in all_files:
        milvus_flag = file.id in all_milvus_chunk_map
        if milvus_flag:
            all_milvus_chunk_map.pop(file.id)
        es_flag = file.id in all_es_chunk_map
        if es_flag:
            all_es_chunk_map.pop(file.id)
        if not milvus_flag and not es_flag:
            no_data.append(file)
        elif not milvus_flag:
            no_milvus_data.append(file)
        elif not es_flag:
            no_es_data.append(file)
    if remove_pk:
        print(
            f"----remove extra milvus data knowledge_id: {knowledge.id}; knowledge_name: {knowledge.name} pk: {remove_pk}")
        milvus_obj.col.delete(expr=f"pk in {remove_pk}")
    if remove_id:
        print(
            f"----remove extra es data knowledge_id: {knowledge.id}; knowledge_name: {knowledge.name} _id: {remove_id}")
        es_obj.client.delete_by_query(index=knowledge.index_name or knowledge.collection_name,
                                      query={"terms": {"_id": remove_id}})

    if all_milvus_chunk_map:
        print(f"---- fix knowledge_id: {knowledge.id}; knowledge_name: {knowledge.name} milvus extra data found")
        for file_id, chunks in all_milvus_chunk_map.items():
            milvus_obj.col.delete(expr=f"file_id=={file_id}")
    if all_es_chunk_map:
        print(f"---- fix knowledge_id: {knowledge.id}; knowledge_name: {knowledge.name} es extra data found")
        es_obj.client.delete_by_query(index=knowledge.index_name or knowledge.collection_name,
                                      query={"terms": {"metadata.file_id": list(all_es_chunk_map.keys())}})

    return no_data, no_milvus_data, no_es_data, old_all_milvus_chunk_map, old_all_es_chunk_map, milvus_obj


def fix_qa_knowledge_data(knowledge: Knowledge, milvus_obj, es_obj):
    all_qa = get_all_qa_knowledge_files(knowledge.id)
    no_data, no_milvus_data, no_es_data, _, _, _ = _fix_knowledge_data(knowledge, milvus_obj, es_obj, all_qa)
    for qa in no_data:
        print(f"try insert qa {qa.id} into vector store")
        QA_save_knowledge(knowledge, qa)
    for qa in no_milvus_data:
        print(f"try insert qa {qa.id} into vector store")
        delete_vector_data(knowledge, [qa.id])
        QA_save_knowledge(knowledge, qa)
    for qa in no_es_data:
        print(f"try insert qa {qa.id} into vector store")
        delete_vector_data(knowledge, [qa.id])
        QA_save_knowledge(knowledge, qa)


def fix_normal_knowledge_data(knowledge: Knowledge, milvus_obj, es_obj):
    all_file = get_all_knowledge_files(knowledge.id)
    no_data, no_milvus_data, no_es_data, all_milvus, all_es, milvus_obj = _fix_knowledge_data(knowledge, milvus_obj,
                                                                                              es_obj,
                                                                                              all_file)
    for file in no_data:
        print(f"update file to failed status file_id: {file.id}; file_name: {file.file_name}")
        KnowledgeFileDao.update_file_status([file.id], KnowledgeFileStatus.FAILED,
                                            "知识库数据修复时发现该文件数据缺失，已将文件状态更新为解析失败，请重新进行解析。")
    for file in no_milvus_data:
        es_chunks = all_es.get(file.id, [])
        if not es_chunks:
            file.status = KnowledgeFileStatus.FAILED.value
            file.remark = "知识库数据修复时发现该文件数据缺失，已将文件状态更新为解析失败，请重新进行解析。"
            KnowledgeFileDao.update(file)
            print(f"!!!!skip file_id: {file.id}; file_name: {file.file_name} because es data not found")
            continue
        texts = []
        metadatas = []
        for chunk in es_chunks:
            texts.append(chunk["_source"]["text"])
            metadatas.append(chunk["_source"]["metadata"])
        milvus_obj.add_texts(texts=texts, metadatas=metadatas)
    for file in no_es_data:
        milvus_chunks = all_milvus.get(file.id, [])
        if not milvus_chunks:
            print(f"!!!!skip file_id: {file.id}; file_name: {file.file_name} because milvus data not found")
            file.status = KnowledgeFileStatus.FAILED.value
            KnowledgeFileDao.update(file)
            continue
        texts = []
        metadatas = []
        for chunk in milvus_chunks:
            texts.append(chunk.pop("text"))
            chunk.pop("pk")
            chunk.pop("vector")
            metadatas.append(chunk)
        es_obj.add_texts(texts=texts, metadatas=metadatas)


def fix_one_knowledge(knowledge: Knowledge = None, knowledge_id: int = None):
    if not knowledge:
        knowledge = KnowledgeDao.query_by_id(knowledge_id)
        if not knowledge:
            print(f"knowledge_id: {knowledge_id} not exist")
            return
    try:
        milvus_obj, es_obj = _init_knowledge_obj(knowledge)
    except Exception as e:
        print(
            f"!!!! skip knowledge_id: {knowledge.id}; knowledge_name: {knowledge.name} because error: {e}")
        return
    if not knowledge.index_name:
        knowledge.index_name = knowledge.collection_name
        KnowledgeDao.update_one(knowledge)
    print(f"---- start fix knowledge_id: {knowledge.id}; knowledge_name: {knowledge.name}")
    if knowledge.type == KnowledgeTypeEnum.QA.value:
        fix_qa_knowledge_data(knowledge, milvus_obj, es_obj)
    else:
        fix_normal_knowledge_data(knowledge, milvus_obj, es_obj)
    print(f"---- finish fix knowledge_id: {knowledge.id}; knowledge_name: {knowledge.name}")


def fix_knowledge_error_data():
    all_knowledge = get_all_knowledge()
    total = len(all_knowledge)
    for index, knowledge in enumerate(all_knowledge):
        print(
            f"{round(index / total * 100, 2)}% ---- start fix knowledge_id: {knowledge.id}; knowledge_name: {knowledge.name}")
        fix_one_knowledge(knowledge)
        print(f"---- finish fix knowledge_id: {knowledge.id}; knowledge_name: {knowledge.name}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', type=str, default="scan_all",
                        help='模式。scan_all: 扫描所有知识库错误数据；fix_all: 修复所有知识库错误数据；fix_one: 修复单个知识库错误数据；scan_one: 扫描单个知识库错误数据')
    # 单个进程的最大并发数
    parser.add_argument('--id', type=int, default=0, help='知识库ID，如果是操作单个知识库时，参数必填')
    args = parser.parse_args()

    if args.mode == "scan_all":
        scan_knowledge_error_data()
    elif args.mode == "fix_all":
        fix_knowledge_error_data()
    elif args.mode == "fix_one":
        fix_one_knowledge(None, args.id)
    elif args.mode == "scan_one":
        tmp_rows = scan_one_knowledge(None, args.id)
        _save_knowledge_error_data(tmp_rows, f"{args.id}_knowledge_error_data.xlsx")
    else:
        print("mode参数错误，只能是scan_all、fix_all、fix_one、scan_one其中之一")
