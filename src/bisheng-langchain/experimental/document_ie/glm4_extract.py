import copy
import json
import logging
import os
import random
import subprocess
from itertools import groupby
from pathlib import Path
from typing import List

import pandas as pd
import yaml
import zhipu
from langchain.text_splitter import RecursiveCharacterTextSplitter
from tqdm import tqdm

random.seed(2024)
import re
import time
from collections import defaultdict

from zhipuai import ZhipuAI

client = ZhipuAI(api_key="")

from langchain.prompts import PromptTemplate
from loguru import logger

logger.add(
    'glm4_llm_extract.log',
)
DEFAULT_PROMPT = PromptTemplate(
    input_variables=["context", "keywords"],
    template="""现在你需要帮我完成信息抽取的任务，你需要帮我抽取出原文中相关字段信息，如果没找到对应的值，则设为空，并按照JSON的格式输出。请保证输出的JSON格式正确。

原文：
{context}

问题：提取上述文本中以下字段信息：{keywords}，并按照json的格式输出，如果没找到对应的值，则设为空。
回答：
""",
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
    def __init__(
        self,
        model_name: str = 'Qwen-7B-Chat',
        model_api_url: str = 'http://34.124.253.159:7001/v2.1/models',
        unstructured_api_url: str = "http://192.168.106.20:10001/v1/etl4llm/predict",
    ):
        self.model_name = model_name
        self.model_api_url = model_api_url.format(model_name)
        self.unstructured_api_url = unstructured_api_url

    def call_llm(self, prompt_info, max_tokens=8192):
        input_template = {
            'model': 'unknown',
            'messages': [{'role': 'system', 'content': '你是一个关键信息提取助手。'}, {'role': 'user', 'content': prompt_info}],
            # 'max_tokens': max_tokens,
        }
        payload = copy.copy(input_template)
        payload['model'] = self.model_name
        try:
            raw_response = client.chat.completions.create(**payload)
            # breakpoint()
        except Exception as e:
            # llm request error
            logger.error(f'llm predict fail: {str(e)}')
            # logger.error(f'raw_response: {raw_response}')
            # return {}, len(raw_response.message.content)
            return {}, 0

        choices = raw_response.choices
        logger.info(f'llm response: {raw_response}')
        json_string = choices[0].message.content
        try:
            extract_res = parse_json(json_string)
        except Exception as e:
            # json parse error
            logger.error(f'json parse fail: {str(e)}')
            extract_res = {}

        return extract_res, len(json_string)

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

    def predict(self, texts, schema):
        logger.info('llm extract phase1: split texts')
        keywords = '、'.join(schema)

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=4096,
            chunk_overlap=200,
            separators=['\n\n', '\n', ' ', ''],
        )
        split_docs = text_splitter.create_documents([texts])

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


def run_predict(ellm_data_dir, predict_scenes, sample_size=50):
    """
    Args:
        ellm_data_dir: Directory path of ellm data in socr format
        predict_scenes: List of scenes to predict
        sample_size: Number of sample images to process
    """
    llm_client = LlmExtract(model_name='glm-4')

    for scene in predict_scenes:
        logger.info(f'{"=" * 20} {scene} {"=" * 20}')
        scene_dir = Path(ellm_data_dir) / scene
        val_ocr_results_dir = scene_dir / 'Images/ocr_results_v2/val'
        val_images = sorted(list(scene_dir.glob('Images/val/*')))
        logger.info(f'{scene} val images num: {len(val_images)}')

        meta_data_path = scene_dir / 'meta.yaml'
        with open(meta_data_path, 'r') as f:
            meta_data = yaml.load(f, Loader=yaml.FullLoader)
        fields = meta_data['field_def']
        logger.warning(f"预估字段：{fields}")

        sample_images = random.sample(val_images, k=min(len(val_images), sample_size))
        logger.info(f'{scene} sample images: {len(sample_images)}')

        save_dir = scene_dir / 'glm4_results'
        save_dir.mkdir(parents=True, exist_ok=True)

        for image_path in tqdm(sample_images, desc=f'{scene} sample images'):
            image_name = image_path.stem

            # Skip if already predicted
            if (save_dir / f'{image_name}.json').exists():
                continue

            ocr_file = val_ocr_results_dir / f'{image_name}.json'
            with open(ocr_file, 'r') as f:
                ocr_res = json.load(f)
            ocr_texts = ocr_res['texts']
            ocr_row_col = ocr_res['row_col_info']

            processed_texts = []
            rowcol_texts = list(zip(ocr_row_col, ocr_texts))
            sorted_rowcol_texts = sorted(rowcol_texts, key=lambda x: (x[0][0], x[0][1]))
            for row, grouped in groupby(sorted_rowcol_texts, key=lambda x: x[0][0]):
                row_texts = [text for _, text in grouped]
                processed_texts.append(' '.join(row_texts))
            input_texts = '\n'.join(processed_texts)

            kv_result = llm_client.predict(texts=input_texts, schema=fields)
            with open(save_dir / f'{image_name}.json', 'w') as f:
                json.dump(kv_result, f, ensure_ascii=False, indent=4)


def score(data_dir, score_script_path, scenes):
    scenes = [Path(data_dir) / scene for scene in scenes]
    for scene in tqdm(scenes):
        pred_path = scene / 'glm4_results'
        logger.info(f"{scene.name} 样本数量 ： {len(list(pred_path.glob('*.json')))}")
        label_path = scene / 'Labels_end2end'
        output_path = scene

        cmd = f"python {score_script_path} --datadir {label_path} --preddir {pred_path} --savedir {output_path} --exclude_keys ''"
        score_result = subprocess.run(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        decoded_score_result = score_result.stdout.decode('utf-8')
        mFieldHmean = re.search(r'mFieldHmean: (.*?) %', decoded_score_result)
        MethodHmean = re.search(r'MethodHmean: (.*?) %', decoded_score_result)

        logger.info(decoded_score_result)
        logger.warning(f"{mFieldHmean.group(1)}, {MethodHmean.group(1)}")


if __name__ == '__main__':
    scenes = [
        '完税证明',
        '电子商务承兑汇票',
        '结算任务申请书-盛京银行-手造',
        '银行承兑汇票_无锡农商',
        '不动产登记查询表-final',
        '余额对账单-无锡农商-final',
        '保险单ps数据-final',
        '报关单-final',
        '抵押合同-final',
        '现金支票反附件-CA-final',
        '网智-存量房购房合同',
        '网智-借款合同',
    ]
    ellm_data_dir = '/home/youjiachen/bisheng/src/bisheng-langchain/experimental/document_ie/data'
    script_path = '/home/youjiachen/ie_benchmark/score/ie_score/ScoreEngine.py'

    run_predict(ellm_data_dir, scenes)
    score(ellm_data_dir, script_path, scenes)
