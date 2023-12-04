import os
import copy
import requests
import json
import time
import logging
import re
from collections import defaultdict
from langchain.prompts import PromptTemplate
from bisheng_langchain.document_loaders import ElemUnstructuredLoader
from bisheng_langchain.text_splitter import ElemCharacterTextSplitter


logging.getLogger().setLevel(logging.INFO)


DEFAULT_PROMPT = PromptTemplate(
    input_variables=["context", "keywords"],
    template="""现在你需要帮我完成信息抽取的任务，你需要帮我抽取出原文中相关字段信息，如果没找到对应的值，则设为空，并按照JSON的格式输出.

原文内容：
{context}

提取上述文本中以下字段信息：{keywords}，并按照json的格式输出，如果没找到对应的值，则设为空。
"""
)


class LlmExtract(object):
    def __init__(self,
                 model_name: str = 'Qwen-14B-Chat',
                 model_api_url: str = 'https://bisheng.dataelem.com/api/v1/models/{}/infer',
                 unstructured_api_url: str = "https://bisheng.dataelem.com/api/v1/etl4llm/predict",
    ):
        self.model_name = model_name
        self.model_api_url = model_api_url.format(model_name)
        self.unstructured_api_url = unstructured_api_url

    def call_llm(self, prompt_info, max_tokens=8192):
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
        response = requests.post(url=self.model_api_url, json=payload).json()
        assert response['status_code'] == 200, response
        choices = response.get('choices', [])
        assert choices, response

        json_string = choices[0]['message']['content']
        match = re.search(r"```(json)?(.*)```", json_string, re.DOTALL)
        if match is None:
            json_str = json_string
        else:
            json_str = match.group(2)
        json_str = json_str.strip()
        extract_res = json.loads(json_str)
        return extract_res

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
        logging.info(f'pdf content len: {len(pdf_content)}')

        text_splitter = ElemCharacterTextSplitter(chunk_size=chunk_size,
                                                  chunk_overlap=chunk_overlap,
                                                  separators=separators)
        split_docs = text_splitter.split_documents(docs)
        logging.info(f'docs num: {len(docs)}, split_docs num: {len(split_docs)}')
        return split_docs, docs

    def post_extract_res(self, split_docs_extract, split_docs_content, schema):
        kv_results = defaultdict(list)
        for ext_res, content in zip(split_docs_extract, split_docs_content):
            # 每一个split_doc的提取结果
            for key, value in ext_res.items():
                # 去掉非法key和没有内容的key
                if (key not in schema) or (not value):
                    continue

                if key not in kv_results:
                    kv_results[key].append(value)
                else:
                    # 去重
                    if value in kv_results[key]:
                        continue
                    kv_results[key].append(value)

        return kv_results

    def predict(self, pdf_path, schema):
        logging.info('llm extract phase1: pdf parsing')
        schema = schema.split('|')
        keywords = '、'.join(schema)
        split_docs, docs = self.parse_pdf(pdf_path)

        logging.info('llm extract phase2: llm extract')
        split_docs_extract = []
        split_docs_content = []
        for each_doc in split_docs:
            pdf_content = each_doc.page_content
            prompt_info = DEFAULT_PROMPT.format(context=pdf_content, keywords=keywords)
            extract_res = self.call_llm(prompt_info)
            split_docs_extract.append(extract_res)
            split_docs_content.append(pdf_content)

        logging.info(f'split_docs_extract: {split_docs_extract}')

        logging.info('llm extract phase3: post extract result')
        kv_results = self.post_extract_res(split_docs_extract, split_docs_content, schema)
        logging.info(f'final kv results: {kv_results}')

        return kv_results


if __name__ == '__main__':
    llm_client = LlmExtract(model_name='Qwen-14B-Chat')
    pdf_path = '/home/gulixin/workspace/datasets/huatai/流动资金借款合同_pdf/流动资金借款合同1.pdf'
    schema = '合同标题|合同编号|借款人|贷款人|借款金额'
    llm_client.predict(pdf_path, schema)

