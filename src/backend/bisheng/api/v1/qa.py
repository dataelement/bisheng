from typing import List

import jieba.analyse
from bisheng.cache.redis import redis_client
from bisheng.chat.manager import ChatManager
from bisheng_langchain.chat_models import QwenChat
from bisheng_langchain.document_loaders import ElemUnstructuredLoader
from bisheng_langchain.text_splitter import ElemCharacterTextSplitter
from fastapi import APIRouter
from langchain import LLMChain, PromptTemplate

router = APIRouter(tags=['Chat'])
chat_manager = ChatManager()
flow_data_store = redis_client
expire = 600  # reids 60s 过期

# build router
router = APIRouter(prefix='/qa', tags=['QA'])


@router.get('/keyword', response_model=List[str], status_code=200)
def get_answer_keyword(answer: str):
    return extract_keys(answer)


model_name = 'Qwen-7B-Chat'
host_base_url = 'http://192.168.106.12:9001/v2.1/models'
llm = QwenChat(model_name=model_name,
               host_base_url=host_base_url,
               max_tokens=8192,
               temperature=0,
               verbose=False)
prompt_template = '''分析给定Question，提取Question中包含的KeyWords，输出列表形式

Examples:
Question: 达梦公司在过去三年中的流动比率如下：2021年：3.74倍；2020年：2.82倍；2019年：2.05倍。
KeyWords: ['过去三年', '流动比率', '2021', '3.74', '2020', '2.82', '2019', '2.05']

----------------
Question: {question}'''

llm_chain = LLMChain(llm=llm, prompt=PromptTemplate.from_template(prompt_template))


def extract_keys(answer, method='jiaba_kv'):
    """
    提取answer中的关键词
    """
    if method == 'jiaba_kv':
        keywords = jieba.analyse.extract_tags(answer, topK=100, withWeight=False)
    elif method == 'llm_kv':
        keywords_str = llm_chain.run(answer)
        keywords = eval(keywords_str[9:])
    return keywords


@router.get('/chunk', status_code=200)
def get_original_file(*, message_id: int):

    # all_chunk = session.exec(select(RecallChunk).where(RecallChunk.message_id == message_id)).all()
    # chunks = json.loads(all_chunk[0].chunk)
    # all_chunk_str = [chunk.]
    loader = ElemUnstructuredLoader('/app/dummy.txt')
    docs = loader.load()
    print('docs', docs)

    text_splitter = ElemCharacterTextSplitter(chunk_size=10, chunk_overlap=0)
    split_docs = text_splitter.split_documents(docs)
    print('split_docs:', split_docs)
    # sort_and_filter_all_chunks(keywords, all_chunk)
    return split_docs


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
