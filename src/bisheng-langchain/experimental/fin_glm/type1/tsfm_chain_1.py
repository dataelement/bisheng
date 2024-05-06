import hashlib
import os
import time

from langchain.chains import TransformChain
from langchain.embeddings.openai import OpenAIEmbeddings
from loguru import logger

os.environ['OPENAI_API_KEY'] = ''
os.environ['OPENAI_PROXY'] = ''
TABLE = 'big'


def prepare_question_columns_for_sql_for_type1(inputs: dict) -> dict:
    """
    [start]
    """

    def prepare_query_for_sql(inputs, query, query_analyze_result):
        comps = keywords = query_analyze_result.get('comps', [])
        for comp in comps:
            if comp in query:
                query = query.replace(comp, f'公司名称为{comp}的公司')
            elif inputs['comp_short_dict'][comp] in query:
                comp_short = inputs['comp_short_dict'][comp]
                query = query.replace(comp_short, f'股票简称为{comp_short}的公司')
        return query

    def prepare_columns_for_sql_v2(inputs, query, query_analyze_result):
        '''
        向量化召回，准备好所需要的列
        '''
        """
        query_words_filter
        """
        import re

        stopwords = set(
            [i.strip() for i in open(inputs['stopwords_path'], encoding='utf-8').readlines() if i])
        stopwords_v2 = set([
            i.strip() for i in open(inputs['stopwordsv2_path'], encoding='utf-8').readlines() if i
        ])
        stopwords_v2 |= stopwords

        def query_words_filter(w):
            fil = not (len(w) > 1 and w not in stopwords_v2 and is_zh(w)
                       and w not in inputs['comps'] and w not in inputs['comps_short'])
            # print(w, fil)
            return fil

        def is_zh(string):
            return re.fullmatch('[\u4e00-\u9fa5]+', string) != None

        """
        recall_from_edit_distance
        """
        from langchain.schema import Document
        from langchain_community.vectorstores import FAISS

        # encode_kwargs = {'normalize_embeddings': inputs['ENCODER_NORMALIZE_EMBEDDINGS'], 'device': 'cuda'}
        # encoder = HuggingFaceEmbeddings(model_name=inputs['ENCODER_MODEL_PATH'], encode_kwargs=encode_kwargs)
        encoder = OpenAIEmbeddings()

        def md5(string):
            md5 = hashlib.md5()
            md5.update(string.encode('utf-8'))
            return md5.hexdigest()

        def recall_from_edit_distance(word, recall_n=3):
            '对于召回结果进行编辑距离过滤'
            recalls = vector_search(
                inputs['schema_emp'] + inputs['schema_base'] + inputs['schema_fin_filtered'],
                word,
                'all',
                k=recall_n,
                rel_thres=0,
            )
            # print(word, recalls)
            candidates = [i[0] for i in recalls][:3]
            edit_lens = [edit_distance(i, word) for i in candidates]
            return [
                cand for i, cand in enumerate(candidates)
                if edit_lens[i] != max(len(candidates[i]), len(word)) and edit_lens[i] <= 3
            ]

        def vector_search(docs,
                          query,
                          store_name,
                          k=3,
                          rel_thres=inputs['VECTOR_SEARCH_THRESHOLD_2']):
            start1 = time.time()
            store = build_vector_store([str(i) for i in docs], store_name)
            end1 = time.time()
            logger.info(f'build_vector_store time: {end1 - start1}')
            start2 = time.time()
            searched = store.similarity_search_with_relevance_scores(query, k=k)
            end2 = time.time()
            logger.info(f'vector_search time: {end2 - start2}')
            return [(docs[i[0].metadata['id']], i[1]) for i in searched]

        def build_vector_store(lines, idx_name, read_cache=True, engine=FAISS, encoder=encoder):
            cache_path = os.path.join(VECTOR_CACHE_PATH, md5(idx_name))
            if read_cache and os.path.exists(cache_path):
                store = engine.load_local(cache_path, encoder)
                if store.index.ntotal == len(lines):
                    # print("Load vectors from cache: ", idx_name)
                    return store
            store = engine.from_documents([
                Document(page_content=line, metadata={'id': id}) for id, line in enumerate(lines)
            ],
                                          embedding=encoder)
            store.save_local(cache_path)
            return store

        def edit_distance(s1, s2):
            if len(s1) > len(s2):
                s1, s2 = s2, s1

            distances = range(len(s1) + 1)
            for i2, c2 in enumerate(s2):
                distances_ = [i2 + 1]
                for i1, c1 in enumerate(s1):
                    if c1 == c2:
                        distances_.append(distances[i1])
                    else:
                        distances_.append(1 +
                                          min((distances[i1], distances[i1 + 1], distances_[-1])))
                distances = distances_
            return distances[-1]

        """
        main
        """
        # META
        import random

        schema_meta = inputs['schema_meta']
        schema_edu = inputs['schema_edu']
        schema_set = inputs['schema_set']
        jieba = inputs['_jieba']
        VECTOR_CACHE_PATH = inputs['VECTOR_CACHE_PATH']

        all_cols = []
        all_cols += [i for i in schema_meta if i != '小数位数']
        query_words = jieba.lcut(query)
        query_words = [w for w in query_words if not query_words_filter(w)]

        # 来自KEYWORDS本身
        keywords = query_analyze_result.get('keywords', [])
        ques_type = ''
        for keyword in keywords:
            if keyword.type in (1, 3) and keyword.word in schema_set:
                all_cols.append(keyword.word)
            elif keyword.type == 2:
                all_cols += [i.word for i in keyword.sub if i.word in schema_set]

        # 向量召回近义词
        all_candidates = []
        for word in query_words:
            all_candidates += recall_from_edit_distance(word)
        all_cols += all_candidates

        if any([col in schema_edu for col in all_candidates]):
            all_cols += schema_edu

        all_cols_set = []
        for col in all_cols:
            if col not in all_cols_set:
                all_cols_set.append(col)
        random.shuffle(all_cols_set)
        logger.info(f'all_cols_set: {all_cols_set}')
        return ','.join(all_cols_set)

    """
    [end]
    """
    query = inputs['query']
    query_analyze_result = inputs['query_analyze_result']
    # query_analyze_result = get_query_analyze_result(query)
    cols = prepare_columns_for_sql_v2(inputs, query, query_analyze_result)
    question = prepare_query_for_sql(inputs, query, query_analyze_result)

    return {'cols': cols, 'question': question}


type1_tsfm_chain_1 = TransformChain(
    input_variables=['query'],
    output_variables=['cols', 'question'],
    transform=prepare_question_columns_for_sql_for_type1,
)
