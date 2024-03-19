import os
import copy
import requests
import json
import time
import logging
import colorlog
import re
from collections import defaultdict
from langchain.prompts import PromptTemplate
from bisheng_langchain.document_loaders import ElemUnstructuredLoader
from bisheng_langchain.text_splitter import ElemCharacterTextSplitter


def init_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.DEBUG)
        fmt_string = '%(log_color)s[%(asctime)s][%(name)s][%(levelname)s]%(message)s'
        # black red green yellow blue purple cyan and white
        log_colors = {
            'DEBUG': 'cyan',
            'INFO': 'green',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'purple'
        }
        fmt = colorlog.ColoredFormatter(fmt_string, log_colors=log_colors)
        stream_handler.setFormatter(fmt)
        logger.addHandler(stream_handler)
    return logger


logger = init_logger(__name__)


DEFAULT_PROMPT = PromptTemplate(
    input_variables=["context", "keywords"],
    template="""现在你需要帮我完成信息抽取的任务，你需要帮我抽取出原文中相关字段信息，如果没找到对应的值，则设为空，并按照JSON的格式输出。请保证输出的JSON格式正确。

原文：
{context}

问题：提取上述文本中以下字段信息：{keywords}，并按照json的格式输出，如果没找到对应的值，则设为空。
回答：
"""
)

# DEFAULT_PROMPT = PromptTemplate(
#     input_variables=["context", "keywords"],
#     template="""现在你需要帮我完成信息抽取的任务，你需要帮我抽取出原文中相关字段信息，如果没找到对应的值，则设为空，并按照JSON的格式输出。

# Examples:
# 原文：
# | 买卖合同 |  | 日期 2021.01.01-2022.12.31 |  |\n| --- | --- | --- | --- |\n| 客户编号 55652246 |  |  | 目的地国家 China |\n| 联系人 chen xu | 电话 862138623097 |  | 传真 |\n| 买方 浙江峻和科技股份有限公司 余姚市远东工业城CE-11 浙江省余姚市 315400 联系人 : 电话 : 传真 |  | 卖方 杜邦贸易 (上海) 有限公司 DuPont Trading (Shanghai) Co., Ltd. 中国《上海》自由贸易试验区港澳路239号一幢楼5层5 27室 Room 527, Floor 5, Building 1, No, 239, Gangao Road .China (Shanghai) Pilot F ree Trade Zone Shanghai 200131.PRC |\n| 付款条件 MET 30 DAYS EOM |\n|  | 运输方式 |  | 销售条款 CPT YUYAO CITY |\n| 1、买方以采购订单的形式。列明需求传送给卖方。 2、卖方负责提供合理报价、依买方采购订单内容生产交货。 3、本合同所附的"买卖条件"为本合同一个明确的组成部分。 4、若本合同任何其他规定与下列附加条件有冲突、则以附加条件为准。 |\n| 卖方银行账 汇丰银行 开户账号 SWIFT代码 |  |\n| 代表实力 浙江岭和科技股份有 (组) For and on behalf (seal) Zhejiang Junke Trehaning 签署 by: 姓名 Now Of Title: 日期 Pate: | 代表表示 杜斯汀 (图) For and configure of SELLER: (seal) Durent 监测制 乌鲁木齐市 日期 late: |

# 问题： 提取上述文本中以下字段信息：{keywords}，并按照json的格式输出，如果没找到对应的值，则设为空。
# 回答：```json\n{{\n    "买方": "浙江峻和科技股份有限公司",\n    "卖方": "杜邦贸易 (上海) 有限公司",\n    "合同期限": "2021.01.01-2022.12.31",\n    "结算条款": "MET 30 DAYS EOM",\n    "售后条款": "本合同所附的\'买卖条件\'为本合同一个明确的组成部分。",\n    "金额总金额": ""\n}}\n```

# ----------------------------------

# 原文：
# {context}

# 问题： 提取上述文本中以下字段信息：{keywords}，并按照json的格式输出，如果没找到对应的值，则设为空。
# 回答：
# """
# )


def parse_json(json_string: str) -> dict:
    match = re.search(r"```(json)?(.*)```", json_string, re.DOTALL)
    if match is None:
        json_str = json_string
    else:
        json_str = match.group(2)

    json_str = json_str.strip()
    json_str = json_str.replace('```', '')

    match = re.search(r"{.*}", json_str, re.DOTALL)
    if match is None:
        json_str = json_str
    else:
        json_str = match.group(0)

    if json_str.endswith('}\n}'):
        json_str = json_str[:-2]
    if json_str.startswith('{\n{'):
        json_str = json_str.replace('{\n{', '{', 1)

    logger.info(f'llm response after parse: {json_str}')
    extract_res = json.loads(json_str)

    return extract_res


class LlmExtract(object):
    def __init__(self,
                 model_name: str = 'Qwen-14B-Chat',
                 model_api_url: str = 'https://bisheng.dataelem.com/api/v1/models/{}/infer',
                 unstructured_api_url: str = "https://bisheng.dataelem.com/api/v1/etl4llm/predict",
                 server_type: str = 'qwen_api'
    ):
        self.server_type = server_type # 'qwen_api', 'bisheng_api', 'openai_api'
        self.model_name = model_name
        if self.server_type == 'bisheng_api':
            self.model_api_url = model_api_url.format(model_name)
        else:
            self.model_api_url = model_api_url
        self.unstructured_api_url = unstructured_api_url

    def call_llm(self, prompt_info, max_tokens=1500):
        if self.server_type == 'bisheng_api':
            input_template = {
                'model': 'unknown',
                'messages': [
                    {'role': 'system', 'content': '你是一个关键信息提取助手。'},
                    {
                        'role': 'user',
                        'content': prompt_info
                    }
                ],
                'max_tokens': max_tokens,
            }
            payload = copy.copy(input_template)
            payload['model'] = self.model_name
            try:
                raw_response = requests.post(url=self.model_api_url, json=payload)
                response = raw_response.json()
                assert response['status_code'] == 200, response
            except Exception as e:
                # llm request error
                logger.error(f'llm predict fail: {str(e)}')
                logger.error(f'raw_response: {raw_response.text}')
                return {}, len(raw_response.text)
        elif self.server_type == 'qwen_api':
            qwen_api_key = os.environ.get('QWEN_API_KEY', '')
            header = {'Authorization': f'Bearer {qwen_api_key}', 'Content-Type': 'application/json'}
            input = {
                'messages': [
                    {'role': 'system', 'content': '你是一个关键信息提取助手。'},
                    {
                        'role': 'user',
                        'content': prompt_info
                    }
                ]
            }
            params = {
                'temperature': 0.01,
                'top_p': 0.01,
                'seed': 1234,
                'max_tokens': max_tokens,
                'result_format': 'message', 
                'repetition_penalty': 1.1,

            }
            inp = {'input': input, 'parameters': params, 'model': self.model_name}
            try:
                raw_response = requests.post(url=self.model_api_url, json=inp, headers=header)
                response = raw_response.json()
                response = response['output']
            except Exception as e:
                # llm request error
                logger.error(f'llm predict fail: {str(e)}')
                logger.error(f'raw_response: {raw_response.text}')
                return {}, len(raw_response.text)

        choices = response.get('choices', [])
        logger.info(f'llm response: {response}')
        json_string = choices[0]['message']['content']
        try:
            extract_res = parse_json(json_string)
        except Exception as e:
            # json parse error
            logger.error(f'json parse fail: {str(e)}')
            extract_res = {}

        return extract_res, len(json_string)

    def parse_pdf(self,
                  file_path,
                  chunk_size=4096,
                  chunk_overlap=200,
                  separators=['\n\n', '\n', ' ', '']
        ):
        file_name = os.path.basename(file_path)
        loader = ElemUnstructuredLoader(file_name=file_name,
                                        file_path=file_path,
                                        unstructured_api_url=self.unstructured_api_url)
        docs = loader.load()
        pdf_content = ''.join([doc.page_content for doc in docs])

        text_splitter = ElemCharacterTextSplitter(chunk_size=chunk_size,
                                                  chunk_overlap=chunk_overlap,
                                                  separators=separators)
        split_docs = text_splitter.split_documents(docs)
        logger.info(f'pdf content len: {len(pdf_content)}, docs num: {len(docs)}, split_docs num: {len(split_docs)}')
        return split_docs, docs

    def post_extract_res(self, split_docs_extract, split_docs_content, schema):
        """
        combine and delete duplicate
        """
        kv_results = defaultdict(list)
        for ext_res, content in zip(split_docs_extract, split_docs_content):
            # 每一个split_doc的提取结果
            for key, value in ext_res.items():
                # 去掉非法key和没有内容的key
                if (key not in schema) or (not value):
                    continue
                # delete duplicate
                if value not in kv_results[key]:
                    kv_results[key].append(value)

        return kv_results

    def predict(self, pdf_path, schema):
        logger.info('llm extract phase1: pdf parsing')
        schema = schema.split('|')
        keywords = '、'.join(schema)
        try:
            split_docs, docs = self.parse_pdf(pdf_path)
        except Exception as e:
            # pdf parse error
            logger.error(f'pdf parse fail: {str(e)}')
            return {}

        logger.info('llm extract phase2: llm extract')
        split_docs_extract = []
        split_docs_content = []
        avg_generate_num = 0
        for each_doc in split_docs:
            pdf_content = each_doc.page_content
            prompt_info = DEFAULT_PROMPT.format(context=pdf_content, keywords=keywords)
            start_time = time.time()
            extract_res, generate_num = self.call_llm(prompt_info)
            llm_time = time.time() - start_time
            avg_generate_num += generate_num / llm_time
            split_docs_extract.append(extract_res)
            split_docs_content.append(pdf_content)
        avg_generate_num = avg_generate_num / len(split_docs)

        logger.info('llm extract phase3: post extract result')
        kv_results = self.post_extract_res(split_docs_extract, split_docs_content, schema)
        logger.info(f'llm kv results: {kv_results}, avg generate char num: {avg_generate_num} char/s')

        return kv_results


if __name__ == '__main__':
    model_name = 'qwen1.5-72b-chat'
    model_api_url = 'https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation'
    llm_client = LlmExtract(model_name=model_name, model_api_url=model_api_url)
    pdf_path = '/home/gulixin/workspace/datasets/huatai/流动资金借款合同_pdf/JYT11.pdf'
    schema = '合同标题|合同编号|借款人|贷款人|借款金额'
    llm_client.predict(pdf_path, schema)
