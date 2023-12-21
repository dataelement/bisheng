import json
import os

from loguru import logger

os.environ['OPENAI_API_KEY'] = ''
os.environ['OPENAI_PROXY'] = ''
from langchain import OpenAI

"""

* Type1 问题处理流程 *

"""


def type1():
    '''1. preprocess'''
    from langchain.chains import SequentialChain
    from llmchain.nl2sql_llm import type1_nl2sql_llm_chain
    from llmchain.norm_llm import normlize_llm_chain
    from type1.tsfm_chain_1 import type1_tsfm_chain_1
    from type1.tsfm_chain_2 import type1_tsfm_chain_2
    from type3.search import solve_type3_chain

    '''
    RuleBasedChain
    '''
    from langchain.chains import ConversationChain, LLMChain
    from langchain.prompts import PromptTemplate
    from multi_router import MultiRuleChain
    from rule_router import RuleBasedRouter

    def rule_type1(inputs: dict) -> dict:
        sql_res = inputs['sql_res']
        if sql_res == '进入type3':
            return {'destination': 'type3', 'next_inputs': inputs}
        else:
            logger.info(f"sql_res: {sql_res}")
            logger.info(f'准备输出答案')
            return {'destination': 'norm', 'next_inputs': inputs}

    default_chain = LLMChain(
        llm=OpenAI(),
        prompt=PromptTemplate(
            input_variables=["sql_res"],
            template='{sql_res}',
        ),
        output_key='answer',
    )
    destionation_chains = {
        'type3': solve_type3_chain,  # 需要加入type3
        'norm': normlize_llm_chain,
    }

    rule_router = RuleBasedRouter(
        rule_function=rule_type1,
        input_variables=['sql_res'],
    )
    type1_multi_rule_chain = MultiRuleChain(
        default_chain=default_chain,
        router_chain=rule_router,
        destination_chains=destionation_chains,
        output_variables=['answer'],
    )

    '''
    RuleBasedChain
    '''
    # NOTE: tsfm chain 1(done) + nl2sql(done) + tsfm chain 2(done) + rule base chian+ normalize(done)
    type1_seq_chain = SequentialChain(
        chains=[
            type1_tsfm_chain_1,
            type1_nl2sql_llm_chain,
            type1_tsfm_chain_2,
            type1_multi_rule_chain,
        ],
        input_variables=["query"],
        output_variables=['answer'],
        # verbose=True,
    )
    return type1_seq_chain


def test_type1():
    type1_seq_chain = type1()

    c = 0
    with open('/home/youjiachen/workspace/FinGLM/data/C-data/C-list-question.json', 'r') as f:
        idx = 0
        for line in f:
            if idx < 3:
                idx = idx + 1
                continue
            data = json.loads(line)['question']
            # print(data)
            query_type = llm_router_with_preprocess(data)['query_type']
            if query_type.startswith('type1'):
                print(query_type)
                result = type1_seq_chain({"query": data})
                print(result)


def type2():
    from llmchain.nl2sql_llm import type2_nl2sql_llm_chain
    from type2.tsfm_chain_1 import type2_tsfm_chain_1
    from type2.tsfm_chain_2 import type2_tsfm_chain_2
    from type3.search import solve_type3_chain

    '''
    RuleBasedChain
    '''
    from langchain.chains import ConversationChain, LLMChain, SequentialChain
    from langchain.prompts import PromptTemplate
    from llmchain.norm_llm import normlize_llm_chain
    from multi_router import MultiRuleChain
    from rule_router import RuleBasedRouter

    def rule_type1(inputs: dict) -> dict:
        sql_res = inputs['sql_res']
        if sql_res == '进入type3':
            return {'destination': 'type3', 'next_inputs': inputs}
        else:
            return {'destination': 'norm', 'next_inputs': inputs}

    default_chain = LLMChain(
        llm=OpenAI(),
        prompt=PromptTemplate(
            input_variables=["sql_res"],
            template='{sql_res}',
        ),
        output_key='answer',
    )
    destionation_chains = {'type3': solve_type3_chain, 'norm': normlize_llm_chain}

    rule_router = RuleBasedRouter(
        rule_function=rule_type1,
        input_variables=['sql_res'],
    )
    type2_multi_rule_chain = MultiRuleChain(
        default_chain=default_chain,
        router_chain=rule_router,
        destination_chains=destionation_chains,
        output_variables=['answer'],
    )

    '''
    RuleBasedChain
    '''

    # NOTE: preprocess(done) + tsfm chain 1(done) + nl2sql(done) + tsfm chain 2(done) + rule base chian+ normalize(done)
    type2_seq_chain = SequentialChain(
        chains=[
            type2_tsfm_chain_1,
            type2_nl2sql_llm_chain,
            type2_tsfm_chain_2,
            type2_multi_rule_chain,
        ],
        input_variables=["query"],
        output_variables=['answer'],
        # verbose=True,
    )

    return type2_seq_chain


def rule_router_chain_1():
    """
    主线路的rule chain
    """
    from langchain.chains import LLMChain
    from langchain.prompts import PromptTemplate
    from multi_router import MultiRuleChain
    from rule_router import RuleBasedRouter
    from type3.search import solve_type3_chain

    def rule_preprocess(inputs: dict) -> dict:
        query_type = inputs['query_type']
        query = inputs['query']
        if query_type.startswith('type1'):
            return {'destination': 'type1', 'next_inputs': inputs}
        elif query_type.startswith('type2'):
            if '增长率' in query:
                return {'destination': 'type1', 'next_inputs': inputs}
            return {'destination': 'type2', 'next_inputs': inputs}
        elif query_type.startswith('type3'):
            return {'destination': 'type3', 'next_inputs': inputs}
        else:
            return {'destination': None, 'next_inputs': inputs}

    default_chain = LLMChain(
        llm=OpenAI(),
        prompt=PromptTemplate(input_variables=['query'], template='{query}'),
        output_key='answer',
    )

    destionation_chains = {
        'type1': type1(),
        'type2': type2(),
        'type3': solve_type3_chain,
    }
    rule_router_0 = RuleBasedRouter(rule_function=rule_preprocess, input_variables=['query_type'])

    chains = MultiRuleChain(
        router_chain=rule_router_0,
        default_chain=default_chain,
        destination_chains=destionation_chains,
        output_variables=['answer'],
    )

    return chains


def llm_router_with_preprocess():
    '''
    主线路
    '''
    from langchain.chains import SequentialChain
    from llmchain.router_llm import router_llm_chain
    from preprocess import (
        preprocess_tsfm_chain_0,
        preprocess_tsfm_chain_1,
        preprocess_tsfm_chain_2,
    )

    llm_router_with_preprocess_chain = SequentialChain(
        chains=[
            router_llm_chain,  # llm router
            preprocess_tsfm_chain_0,  # 存储所有全局变量
            preprocess_tsfm_chain_1,  # comps_and_years
            preprocess_tsfm_chain_2,  # trans_extract_keywords
            rule_router_chain_1(),  # 根据query type 走不同的分支
        ],
        input_variables=["query"],
        output_variables=["answer"],
        # verbose=True,
    )

    return llm_router_with_preprocess_chain


def test_main():
    import random
    import time

    random.seed(42)
    from collections import defaultdict

    from loguru import logger

    router_with_preprocess_chain = llm_router_with_preprocess()
    oup_path = '/home/youjiachen/workspace/FinGLM/code/finglm5/serving/bisheng/combine_train_result.txt'
    logger.add('./combine_train_result.log')

    # ave_cost_time = defaultdict(float)
    file_out = open(oup_path, 'w')
    time_cost = defaultdict(float)
    type_count = defaultdict(int)

    with open('/home/youjiachen/workspace/FinGLM/code/finglm5/serving/test_data/router_v1.json', 'r') as f:
        for line in f:
            data = json.loads(line)
            question = data['question']
            start_time = time.time()
            res = router_with_preprocess_chain(question)
            end_time = time.time()
            # logger.info(f"cost time: {end_time - start_time}")
            time_cost[data['type']] += end_time - start_time
            type_count[data['type']] += 1
            file_out.write(
                json.dumps(
                    {'id': data['id'], 'question': data['question'], 'answer': res['answer']},
                    ensure_ascii=False,
                )
                + '\n',
            )
            logger.info(res['answer'])

    logger.info(f"total_cost_time: {time_cost}")
    logger.info(f"total_type_count: {type_count}")
    file_out.close()


if __name__ == '__main__':
    # test_type1()
    # test_llm_router_with_preprocess()
    test_main()
    pass
