import os
import json
from tqdm import tqdm
from ellm_extract import EllmExtract
from llm_extract import LlmExtract
from collections import defaultdict
from llm_extract import init_logger

logger = init_logger(__name__)


class DocumentExtract(object):
    def __init__(self,
                ellm_api_base_url: str = 'http://192.168.106.20:3502/v2/idp/idp_app/infer',
                llm_model_name: str = 'Qwen-14B-Chat',
                llm_model_api_url: str = 'http://192.168.106.20:7001/v2.1/models/{}/infer',
                unstructured_api_url: str = "https://bisheng.dataelem.com/api/v1/etl4llm/predict",
                do_ellm: bool = True,
                do_llm: bool = True,
                replace_ellm_cache: bool = False,
                replace_llm_cache: bool = False,
                ensemble_method: str = 'llm_first'
    ):
        self.ellm_client = EllmExtract(api_base_url=ellm_api_base_url)
        self.llm_client = LlmExtract(model_name=llm_model_name,
                                model_api_url=llm_model_api_url,
                                unstructured_api_url=unstructured_api_url)
        self.do_ellm = do_ellm
        self.do_llm = do_llm
        self.ensemble_method = ensemble_method
        self.replace_ellm_cache = replace_ellm_cache
        self.replace_llm_cache = replace_llm_cache

    def ensemble(self, ellm_kv_results, llm_kv_results):
        """
        1. 如果当前字段llm有结果，以llm为准，丢掉ellm的提取结果
        2. 如果ellm还有剩余字段，归到最终结果中
        """
        final_kv_results = defaultdict(list)
        if self.ensemble_method == 'llm_first':
            for key in llm_kv_results:
                final_kv_results[key] = llm_kv_results[key]
                if key in ellm_kv_results:
                    ellm_kv_results.pop(key)
            for key in ellm_kv_results:
                final_kv_results[key] = ellm_kv_results[key]
        elif self.ensemble_method == 'ellm_first':
            for key in ellm_kv_results:
                final_kv_results[key] = ellm_kv_results[key]
                if key in llm_kv_results:
                    llm_kv_results.pop(key)
            for key in llm_kv_results:
                final_kv_results[key] = llm_kv_results[key]

        logger.info(f'ensemble final kv results: {final_kv_results}')
        return final_kv_results

    def predict_one_pdf(self, pdf_path, schema, save_folder=''):
        pdf_name_prefix = os.path.splitext(os.path.basename(pdf_path))[0]

        if self.do_ellm:
            if save_folder:
                save_ellm_path = os.path.join(save_folder, pdf_name_prefix + '_ellm.json')
                if self.replace_ellm_cache or not os.path.exists(save_ellm_path):
                    ellm_kv_results = self.ellm_client.predict(pdf_path, schema)
                    with open(save_ellm_path, 'w') as f:
                        json.dump(ellm_kv_results, f, indent=2, ensure_ascii=False)
                else:
                    # get results from cache
                    with open(save_ellm_path, 'r') as f:
                        ellm_kv_results = json.load(f)
            else:
                ellm_kv_results = self.ellm_client.predict(pdf_path, schema)
        else:
            ellm_kv_results = {}

        if self.do_llm:
            if save_folder:
                save_llm_path = os.path.join(save_folder, pdf_name_prefix + '_llm.json')
                if self.replace_llm_cache or not os.path.exists(save_llm_path):
                    llm_kv_results = self.llm_client.predict(pdf_path, schema)
                    with open(save_llm_path, 'w') as f:
                        json.dump(llm_kv_results, f, indent=2, ensure_ascii=False)
                else:
                    # get results from cache
                    with open(save_llm_path, 'r') as f:
                        llm_kv_results = json.load(f)
            else:
                llm_kv_results = self.llm_client.predict(pdf_path, schema)
        else:
            llm_kv_results = {}

        final_kv_results = self.ensemble(ellm_kv_results, llm_kv_results)
        if save_folder:
            save_final_path = os.path.join(save_folder, pdf_name_prefix + '_ensemble.json')
            with open(save_final_path, 'w') as f:
                json.dump(final_kv_results, f, indent=2, ensure_ascii=False)

        return ellm_kv_results, llm_kv_results, final_kv_results

    def predict_all_pdf(self, pdf_folder, schema, save_folder):
        if not os.path.exists(save_folder):
            os.makedirs(save_folder)
        pdf_names = os.listdir(pdf_folder)
        for pdf_name in tqdm(pdf_names):
            logger.info(f'process pdf: {pdf_name}')
            pdf_path = os.path.join(pdf_folder, pdf_name)
            ellm_kv_results, llm_kv_results, final_kv_results = self.predict_one_pdf(
                pdf_path, schema, save_folder)


if __name__ == '__main__':
    # llm_model_name = 'Qwen-14B-Chat'
    llm_model_name = 'Qwen-72B-Chat-Int4'
    client = DocumentExtract(llm_model_name=llm_model_name)
    schema = '合同标题|借款合同编号|担保合同编号|借款人|贷款人|借款金额'
    pdf_folder = '/home/gulixin/workspace/datasets/huatai/流动资金借款合同_pdf'
    save_folder = '/home/gulixin/workspace/datasets/huatai/流动资金借款合同_pdf_qwen72B_res'
    # schema = '买方|卖方|合同期限|结算条款|售后条款|合同总金额'
    # pdf_folder = '/home/gulixin/workspace/datasets/huatai/重大商务合同(汇总)_pdf'
    # save_folder = '/home/gulixin/workspace/datasets/huatai/重大商务合同(汇总)_pdf_qwen72B_res'
    client.predict_all_pdf(pdf_folder, schema, save_folder)
