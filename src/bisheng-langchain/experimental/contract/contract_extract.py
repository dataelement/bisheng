import os
import json
import logging
from tqdm import tqdm
from ellm_extract import EllmExtract
from llm_extract import LlmExtract

logging.getLogger().setLevel(logging.INFO)


class ContractExtract(object):
    def __init__(self,
                ellm_api_base_url: str = 'http://192.168.106.20:3502/v2/idp/idp_app/infer',
                llm_model_name: str = 'Qwen-14B-Chat',
                llm_model_api_url: str = 'https://bisheng.dataelem.com/api/v1/models/{}/infer',
                unstructured_api_url: str = "https://bisheng.dataelem.com/api/v1/etl4llm/predict",
                replace_ellm_cache: bool = False,
                replace_llm_cache: bool = True,
    ):
        self.ellm_client = EllmExtract(api_base_url=ellm_api_base_url)
        self.llm_client = LlmExtract(model_name=llm_model_name,
                                model_api_url=llm_model_api_url,
                                unstructured_api_url=unstructured_api_url)
        self.replace_ellm_cache = replace_ellm_cache
        self.replace_llm_cache = replace_llm_cache

    def predict_one_pdf(self, pdf_path, schema, save_folder):
        pdf_name_prefix = os.path.splitext(os.path.basename(pdf_path))[0]
        save_ellm_path = os.path.join(save_folder, pdf_name_prefix + '_ellm.json')
        save_llm_path = os.path.join(save_folder, pdf_name_prefix + '_llm.json')

        if self.replace_ellm_cache or not os.path.exists(save_ellm_path):
            ellm_kv_results = self.ellm_client.predict(pdf_path, schema)
            with open(save_ellm_path, 'w') as f:
                json.dump(ellm_kv_results, f, indent=2, ensure_ascii=False)
        else:
            with open(save_ellm_path, 'r') as f:
                ellm_kv_results = json.load(f)

        if self.replace_llm_cache or not os.path.exists(save_llm_path):
            llm_kv_results = self.llm_client.predict(pdf_path, schema)
            with open(save_llm_path, 'w') as f:
                json.dump(llm_kv_results, f, indent=2, ensure_ascii=False)
        else:
            with open(save_llm_path, 'r') as f:
                llm_kv_results = json.load(f)

        return ellm_kv_results, llm_kv_results

    def predict_all_pdf(self, pdf_folder, schema, save_folder):
        if not os.path.exists(save_folder):
            os.makedirs(save_folder)
        pdf_names = os.listdir(pdf_folder)
        for pdf_name in tqdm(pdf_names):
            pdf_path = os.path.join(pdf_folder, pdf_name)
            ellm_kv_results, llm_kv_results = self.predict_one_pdf(pdf_path, schema, save_folder)


if __name__ == '__main__':
    client = ContractExtract()
    pdf_folder = '/home/gulixin/workspace/datasets/huatai/重大商务合同(汇总)_pdf'
    # schema = '合同标题|合同编号|借款人|贷款人|借款金额'
    schema = '买方|卖方|合同期限|结算条款|售后条款|金额总金额'
    save_folder = '/home/gulixin/workspace/datasets/huatai/重大商务合同(汇总)_pdf_res'
    client.predict_all_pdf(pdf_folder, schema, save_folder)
