import base64
import copy
import json
import logging
import os

os.environ["CUDA_VISIBLE_DEVICES"] = "5"
import re
import time
from collections import defaultdict
from pathlib import Path

import colorlog
import requests
from bisheng_langchain.document_loaders import ElemUnstructuredLoader
from bisheng_langchain.text_splitter import ElemCharacterTextSplitter
from half_json.core import JSONFixer
from langchain.output_parsers import OutputFixingParser
from langchain.prompts import PromptTemplate
from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.output_parsers import JsonOutputParser
from llmtuner.chat import ChatModel
from prompt import (
    BASE_SYSTEM_MESSAGE,
    BASE_USER_MESSAGE,
    EXAMPLE_FORMAT,
    FEW_SHOT_SYSTEM_MESSAGE,
    FEW_SHOT_USER_MESSAGE,
)


def init_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.DEBUG)
        fmt_string = '%(log_color)s[%(asctime)s][%(name)s][%(levelname)s]%(message)s'
        # black red green yellow blue purple cyan and white
        log_colors = {'DEBUG': 'cyan', 'INFO': 'green', 'WARNING': 'yellow', 'ERROR': 'red', 'CRITICAL': 'purple'}
        fmt = colorlog.ColoredFormatter(fmt_string, log_colors=log_colors)
        stream_handler.setFormatter(fmt)
        logger.addHandler(stream_handler)
    return logger


logger = init_logger(__name__)


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

    # json_str = JSONFixer().fix(json_str).line
    logger.info(f'llm response after parse: {json_str}')
    extract_res = json.loads(json_str)

    return extract_res


class LlmExtract(object):
    def __init__(
        self,
        model_path: str,
        adaptor_path: str = None,
        unstructured_api_url: str = "https://bisheng.dataelem.com/api/v1/etl4llm/predict",
        idp_url: str = "http://192.168.106.134:8502",
    ):
        self.model_path = model_path
        self.idp_url = idp_url
        self.adaptor_path = adaptor_path
        self.unstructured_api_url = unstructured_api_url
        self.json_output_parser = JsonOutputParser()
        self.chunk_config = {
            'chunk_size': 4096,
            'chunk_overlap': 200,
        }
        self.generte_config = {
            'do_sample': False,
            'top_p': None,
            'top_k': None,
            'temperature': None,
            'max_new_tokens': 2000,
        }
        self.chat_model = ChatModel(
            dict(
                model_name_or_path=self.model_path,
                adapter_name_or_path=self.adaptor_path,
                template='qwen',
                **self.generte_config,
            )
        )

    def predict(self, filepath, schema, examples=None):
        logger.info('llm extract phase1: split texts')
        keywords = schema.split('|')
        print(keywords)
        if Path(filepath).suffix == '.pdf':
            split_docs, docs = self.parse_pdf(filepath)
        else:
            split_docs, docs = self.parse_img(filepath)

        logger.info('llm extract phase2: llm extract')
        split_docs_extract = []
        split_docs_content = []
        avg_generate_num = 0
        for each_doc in split_docs:
            pdf_content = each_doc.page_content
            start_time = time.time()
            if examples:
                pass
            else:
                messages = [
                    {
                        'role': 'user',
                        'content': BASE_USER_MESSAGE.format(
                            context=pdf_content,
                            keywords=keywords,
                        ),
                    }
                ]
                print(messages)
                response = self.chat_model.chat(messages, system=BASE_SYSTEM_MESSAGE)
                print(f'ori llm predict: {response}')
                extract_res = self.json_output_parser.parse(response[0].response_text)
                print(f'parser result: {extract_res}')
                if not extract_res:
                    extract_res = {}
            avg_generate_num += time.time() - start_time
            split_docs_extract.append(extract_res)
            split_docs_content.append(pdf_content)
        avg_generate_num = avg_generate_num / len(split_docs)
        logger.info('llm extract phase3: post extract result')
        kv_results = self.post_extract_res(split_docs_extract, split_docs_content, schema)
        logger.info(f'llm kv results: {kv_results}, avg generate char num: {avg_generate_num} char/s')

        return kv_results

    def parse_img(
        self,
        file_path,
        chunk_size=8192,
        chunk_overlap=200,
        separators=['\n\n', '\n', ' ', ''],
    ):
        ocr_result = self.call_ocr(file_path)
        final_str = self.preprocess(ocr_result)
        docs = Document(page_content=final_str)
        text_splitter = RecursiveCharacterTextSplitter(
            **self.chunk_config,
            separators=separators,
        )
        split_docs = text_splitter.split_documents([docs])

        return split_docs, docs

    def parse_pdf(self, file_path, chunk_size=8192, chunk_overlap=200, separators=['\n\n', '\n']):
        file_name = os.path.basename(file_path)
        loader = ElemUnstructuredLoader(
            file_name=file_name, file_path=file_path, unstructured_api_url=self.unstructured_api_url
        )
        docs = loader.load()
        pdf_content = ''.join([doc.page_content for doc in docs])

        text_splitter = ElemCharacterTextSplitter(
            **self.chunk_config,
            separators=separators,
        )
        split_docs = text_splitter.split_documents(docs)
        logger.info(f'pdf content len: {len(pdf_content)}, docs num: {len(docs)}, split_docs num: {len(split_docs)}')
        return split_docs, docs

    def preprocess(self, ocr_result):
        """对ocr结果根据行列信息进行对齐，同一行用 /t，不同行用 /n 分隔。"""
        ocr_texts = ocr_result['texts']
        ocr_row_col = ocr_result['row_col_info']

        if not ocr_texts:
            logger.error(f' has no text')
            return ''

        rowcol_texts = list(zip(ocr_row_col, ocr_texts))
        sorted_rowcol_texts = sorted(rowcol_texts, key=lambda x: (x[0][0], x[0][1]))

        col2pad = dict()
        for rowcol, text in sorted_rowcol_texts:
            row, col = rowcol
            len_text = len(text)
            col2pad[col] = max(col2pad.get(col, 0), len_text)

        cur_padding_template = [col2pad[col] for col in range(len(col2pad))]
        row_num = sorted_rowcol_texts[-1][0][0] + 1
        temp = [copy.deepcopy(cur_padding_template) for i in range(row_num)]

        for rowcol, text in sorted_rowcol_texts:
            row, col = rowcol
            pad_num = temp[row][col]
            if isinstance(pad_num, int):
                # temp[row][col] = text.rjust(pad_num, ' ')
                temp[row][col] = text
            elif isinstance(pad_num, str):
                temp[row][col] = pad_num + '\t' + text

        for row_str_list in temp:
            for idx, item in enumerate(row_str_list):
                # print(idx, item)
                if isinstance(item, int):
                    row_str_list[idx] = ' '

        final_string = '\n'.join('\t'.join(row) for row in temp)

        return final_string

    def call_ocr(self, input_file):
        infer_url = f'{self.idp_url}/v2/idp/idp_app/infer'

        bytes_data = open(input_file, 'rb').read()
        b64enc = base64.b64encode(bytes_data).decode()

        params = {
            # 'sort_filter_boxes': True,
            # 'enable_huarong_box_adjust': True,
            'rotateupright': True,
            # 'support_long_image_segment': True,
            # 'checkbox': ['std_checkbox'],
            'support_long_rotate_dense': True,
            'det': 'general_text_det_v2.0',
            'recog': 'general_text_reg_nb_v1.0_faster',
        }
        payload = {'param': params, 'data': [b64enc]}
        client = requests.Session()
        response = client.post(url=infer_url, json=payload)
        return response.json()['result']['ocr_result']

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
                for v in value:
                    if v not in kv_results[key]:
                        kv_results[key].append(v)

        return kv_results


if __name__ == '__main__':
    # model_name = 'qwen1.5-72b-chat'
    # model_api_url = 'https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation'
    # server_type = 'qwen_api'

    model_path = '/public/youjiachen/models/Qwen2-7B-Instruct_ELLM_SFT'
    uns_api = 'https://bisheng.dataelem.com/api/v1/etl4llm/predict'
    idp_url = 'http://192.168.106.134:8502'
    llm_client = LlmExtract(model_path=model_path, unstructured_api_url=uns_api, idp_url=idp_url)
    pdf_path = '/home/public/huatai/流动资金借款合同_pdf/JYT11.pdf'
    schema = '合同标题|合同编号|借款人|贷款人|借款金额'
    llm_client.predict(pdf_path, schema)