import os.path
import os.path
from typing import List

import openpyxl

from bisheng.api.services.knowledge_imp import decide_vectorstores
from bisheng.database.models.knowledge import KnowledgeDao, Knowledge, KnowledgeTypeEnum
from bisheng.database.models.knowledge_file import QAKnoweldgeDao, KnowledgeFileDao, QAKnowledge, KnowledgeFile, \
    QAStatus, KnowledgeFileStatus
from bisheng.utils.embedding import decide_embeddings

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


def _get_es_chunks_data(knowledge: Knowledge):
    embedding = decide_embeddings(knowledge.model)
    es_obj = decide_vectorstores(knowledge.index_name, "ElasticKeywordsSearch", embedding, knowledge.id)
    es_client = es_obj.client
    all_chunks = []

    def handle_hits(hits):
        for hit in hits:
            all_chunks.append({
                "file_id": hit['fields']['metadata.file_id'][0],
                "source": hit['fields']['metadata.source'][0],
                "extra": hit['fields']['metadata.extra'][0],
                "_id": hit['_id'],
            })

    result = es_client.search(index=knowledge.index_name,
                              query={"match_all": {}},
                              size=1000,
                              scroll="1m",
                              source=False,
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
    return all_chunks


def _get_milvus_chunks_data(knowledge: Knowledge):
    embedding = decide_embeddings(knowledge.model)
    milvus_obj = decide_vectorstores(knowledge.collection_name, "Milvus", embedding, knowledge.id)
    all_milvus_chunks = []
    iterator = milvus_obj.col.query_iterator(
        batch_size=1000,
        expr=f"knowledge_id=='{knowledge.id}'",
        output_fields=["file_id", "extra", "source", "pk"],
        timeout=10,
    )
    while True:
        result = iterator.next()
        if not result:
            iterator.close()
            break
        all_milvus_chunks.extend(result)
    return all_milvus_chunks


def _scan_knowledge_error_data(knowledge: Knowledge, all_file_data: List[KnowledgeFile | QAKnowledge]):
    all_milvus_chunks = _get_milvus_chunks_data(knowledge)
    all_milvus_chunks_map = {
        item["file_id"]: item for item in all_milvus_chunks if not item.get("source")  # source 不存在说明是QA对的数据，否则是文档知识库的数据
    }
    all_es_chunks = _get_es_chunks_data(knowledge)
    all_es_chunks_map = {
        item["file_id"]: item for item in all_es_chunks if item.get("source")  # source 不存在说明是QA对的数据，否则是文档知识库的数据
    }
    no_data = []
    no_milvus_data = []
    no_es_data = []
    for file in all_file_data:
        milvus_flag = file.id in all_milvus_chunks_map
        es_flag = file.id in all_es_chunks_map
        if not milvus_flag and not es_flag:
            no_data.append(file)
        elif not milvus_flag:
            no_milvus_data.append(file)
        elif not es_flag:
            no_es_data.append(file)

    return no_data, no_milvus_data, no_es_data


def scan_qa_knowledge_error_data(knowledge: Knowledge):
    """ scan all qa knowledge data and find those that not exist in milvus """
    all_qa = get_all_qa_knowledge_files(knowledge.id)
    return _scan_knowledge_error_data(knowledge, all_qa)


def scan_normal_knowledge_error_data(knowledge: Knowledge):
    """ scan all normal knowledge data and find those that not exist in milvus """
    all_files = get_all_knowledge_files(knowledge.id)
    return _scan_knowledge_error_data(knowledge, all_files)


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


def scan_knowledge_error_data():
    """ scan all knowledge data and find those that not exist in milvus """
    all_knowledge = get_all_knowledge()
    error_knowledge = []
    for knowledge in all_knowledge:
        if knowledge.collection_name.startswith('col_'):
            # skip collection name start with col_, because those are unique collection name for knowledge
            continue
        print(f"---- start scan knowledge_id: {knowledge.id}; knowledge_name: {knowledge.name}")
        if knowledge.type == KnowledgeTypeEnum.QA.value:
            no_data, no_milvus_data, no_es_data = scan_qa_knowledge_error_data(knowledge)
        else:
            no_data, no_milvus_data, no_es_data = scan_normal_knowledge_error_data(knowledge)
        if no_data or no_milvus_data or no_es_data:
            print(f"!!!! find error data knowledge_id: {knowledge.id}; knowledge_name: {knowledge.name}")
            error_knowledge.append([knowledge, no_data, no_milvus_data, no_es_data])
        else:
            print(f"==== no error data knowledge_id: {knowledge.id}; knowledge_name: {knowledge.name}")

    if not error_knowledge:
        return None
    # generate xlsx file
    rows = [
        ['知识库ID', '知识库名称', 'collection_name', 'index_name', '知识库类型', '文件ID', '文件名称', '文件状态',
         '文件创建时间', '更新时间', 'Milvus是否存在', 'ES是否存在']
    ]
    for knowledge, no_data, no_milvus_data, no_es_data in error_knowledge:
        one_common_row = [knowledge.id, knowledge.name, knowledge.collection_name, knowledge.index_name]
        if knowledge.type == KnowledgeTypeEnum.QA.value:
            one_common_row.append("QA知识库")
        elif knowledge.type == KnowledgeTypeEnum.NORMAL.value:
            one_common_row.append("文档知识库")
        elif knowledge.type == KnowledgeTypeEnum.PRIVATE.value:
            one_common_row.append("个人知识库")
        else:
            one_common_row.append("未知类型知识库")

        def _parse_one_row(file, milvus_flag: str, es_flag: str):
            one_row = one_common_row.copy()
            one_row.extend([
                file.id,
                file.file_name if knowledge.type != KnowledgeTypeEnum.QA.value else file.question,
                _file_status(file) if knowledge.type != KnowledgeTypeEnum.QA.value else _qa_status(file),
                file.create_time.strftime("%Y-%m-%d %H:%M:%S"),
                file.update_time.strftime("%Y-%m-%d %H:%M:%S"),
                milvus_flag,
                es_flag,
            ])
            return one_row

        for one in no_data:
            rows.append(_parse_one_row(one, "否", "否"))
        for one in no_milvus_data:
            rows.append(_parse_one_row(one, "否", "是"))
        for one in no_es_data:
            rows.append(_parse_one_row(one, "是", "否"))
    wb = openpyxl.workbook.Workbook()
    sh = wb.active
    for row in rows:
        sh.append(row)
    wb.save(os.path.join(_output_path, "knowledge_error_data.xlsx"))

    return None


if __name__ == '__main__':
    scan_knowledge_error_data()
