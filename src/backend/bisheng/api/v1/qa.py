import json
from typing import List

import jieba.analyse
from bisheng.database.base import get_session
from bisheng.database.models.model_deploy import ModelDeploy
from bisheng.database.models.recall_chunk import RecallChunk
from bisheng.settings import settings
from bisheng.utils import minio_client
from bisheng.utils.logger import logger
from bisheng_langchain.chat_models import HostQwenChat
from fastapi import APIRouter, Depends
from langchain import LLMChain, PromptTemplate
from sqlmodel import Session, select

# build router
router = APIRouter(prefix='/qa', tags=['QA'])


@router.get('/keyword', response_model=List[str], status_code=200)
def get_answer_keyword(answer: str):
    return extract_keys(answer)


prompt_template = '''分析给定Question，提取Question中包含的KeyWords，输出列表形式

Examples:
Question: 达梦公司在过去三年中的流动比率如下：2021年：3.74倍；2020年：2.82倍；2019年：2.05倍。
KeyWords: ['过去三年', '流动比率', '2021', '3.74', '2020', '2.82', '2019', '2.05']

----------------
Question: {question}'''


def extract_keys(answer):
    """
    提取answer中的关键词
    """
    model = settings.knowledges.get('keyword_llm')
    db_session = next(get_session())
    model_deploy = db_session.exec(select(ModelDeploy).where(ModelDeploy.model == model)).first()
    if model_deploy and model_deploy.status == '已上线':
        llm = HostQwenChat(model_name=model_deploy.model,
                           host_base_url=model_deploy.endpoint,
                           max_tokens=8192,
                           temperature=0,
                           verbose=True)
        llm_chain = LLMChain(llm=llm, prompt=PromptTemplate.from_template(prompt_template))
    try:
        keywords_str = llm_chain.run(answer)
        keywords = eval(keywords_str[9:])
    except Exception:
        logger.warning(f'llm {model} extract_not_support, change to jieba')
        keywords = jieba.analyse.extract_tags(answer, topK=100, withWeight=False)

    return keywords


@router.get('/chunk', status_code=200)
def get_original_file(*, message_id: int, keys: str, session: Session = Depends(get_session)):
    # 获取命中的key
    chunks = session.exec(select(RecallChunk).where(RecallChunk.message_id == message_id)).all()
    # keywords
    keywords = keys.split(';') if keys else []
    result = []
    for index, chunk in enumerate(chunks):
        chunk_res = json.loads(json.loads(chunk.meta_data).get('bbox'))
        chunk_res['source_url'] = minio_client.get_share_link(str(chunk.file_id))
        chunk_res['score'] = round(match_score(chunk.chunk, keywords), 2)
        chunk_res['file_id'] = chunk.file_id
        result.append(chunk_res)

    # sort_and_filter_all_chunks(keywords, all_chunk)
    return {'data': result, 'msg': 'success'}


def find_lcsubstr(s1, s2):
    m = [[0 for i in range(len(s2) + 1)] for j in range(len(s1) + 1)]
    mmax = 0
    p = 0
    for i in range(len(s1)):
        for j in range(len(s2)):
            if s1[i] == s2[j]:
                m[i + 1][j + 1] = m[i][j] + 1
                if m[i + 1][j + 1] > mmax:
                    mmax = m[i + 1][j + 1]
                    p = i + 1
    return s1[p - mmax:p], mmax


def match_score(chunk, keywords):
    """
    去重后的keywords，被chunk覆盖的比例多少
    """
    hit_num = 0
    # # 精确匹配
    # for keyword in keywords:
    #     if keyword in chunk:
    #         hit_num += 1

    # 模糊匹配，关键词2/3以上被包含
    for keyword in keywords:
        res = find_lcsubstr(keyword, chunk)
        if res[1] >= 2 / 3 * len(keyword):
            hit_num += 1
    return hit_num / len(keywords)


def sort_and_filter_all_chunks(keywords, all_chunks, thr=0.0):
    """
    1. answer提取关键词，并进行去重处理
    2. 计算关键词被chunk的覆盖比例（=matched_key_num / all_key_num），依次计算每一个chunk
    3. 按照覆盖比例从高到低，对chunk进行排序
    4. 过滤掉覆盖比例小于阈值Thr的chunk，同时至少保留一个chunk（防止阈值过高，把所有的chunk都过滤掉了）
    """
    keywords = set(keywords)

    chunk_match_score = []
    for index, chunk in enumerate(all_chunks):
        chunk_match_score.append(match_score(chunk, keywords))

    sorted_res = sorted(enumerate(chunk_match_score), key=lambda x: -x[1])
    print(sorted_res)
    remain_chunks = [all_chunks[elem[0]] for elem in sorted_res if elem[1] >= thr]
    if not remain_chunks:
        remain_chunks = [all_chunks[sorted_res[0][0]]]

    return remain_chunks
