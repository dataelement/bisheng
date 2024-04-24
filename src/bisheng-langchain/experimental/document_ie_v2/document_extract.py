# flake8: noqa
import argparse
import base64
import json
import os
import tempfile

from flask import Flask, Response, request
from llm_extract import LlmExtract, init_logger
from prompt import system_template
from tqdm import tqdm

logger = init_logger(__name__)
app = Flask(__name__)


class DocumentExtract(object):
    def __init__(self,
                 unstructured_api_url: str = 'https://bisheng.dataelem.com/api/v1/etl4llm/predict',
                 llm_model_name: str = 'Qwen-14B-Chat',
                 llm_model_api_url: str = 'http://192.168.106.20:7001/v2.1/models/{}/infer',
                 server_type: str = 'openai_api',
                 replace_llm_cache: bool = False,
    ):
        self.llm_client = LlmExtract(model_name=llm_model_name,
                                     model_api_url=llm_model_api_url,
                                     unstructured_api_url=unstructured_api_url,
                                     server_type=server_type)
        self.replace_llm_cache = replace_llm_cache

    def predict_one_pdf(self, pdf_path, schema, system_message=system_template, save_folder=''):
        pdf_name_prefix = os.path.splitext(os.path.basename(pdf_path))[0]

        if save_folder:
            save_llm_path = os.path.join(save_folder, pdf_name_prefix + '_llm.json')
            if self.replace_llm_cache or not os.path.exists(save_llm_path):
                llm_kv_results = self.llm_client.predict(pdf_path, schema, system_message)
                with open(save_llm_path, 'w') as f:
                    json.dump(llm_kv_results, f, indent=2, ensure_ascii=False)
            else:
                # get results from cache
                with open(save_llm_path, 'r') as f:
                    llm_kv_results = json.load(f)
        else:
            llm_kv_results = self.llm_client.predict(pdf_path, schema, system_message)

        return llm_kv_results

    def predict_all_pdf(self, pdf_folder, schema, system_message=system_template, save_folder=''):
        if not os.path.exists(save_folder):
            os.makedirs(save_folder)
        pdf_names = os.listdir(pdf_folder)
        for pdf_name in tqdm(pdf_names):
            logger.info(f'process pdf: {pdf_name}')
            pdf_path = os.path.join(pdf_folder, pdf_name)
            llm_kv_results = self.predict_one_pdf(pdf_path, schema, system_message, save_folder)


@app.route('/document_ie', methods=['POST'])
def extract_document_kv():
    data = request.json
    file_name = data['file_name']
    file_b64 = data['file_b64']
    schema = data['schema']
    system_message = data.get('system_message', system_template)

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = os.path.join(tmpdir, file_name)
        with open(file_path, 'wb') as fout:
            fout.write(base64.b64decode(file_b64))

        try:
            llm_kv_results = ie_client.predict_one_pdf(file_path, schema, system_message)
            result = {'code': '200', 'msg': '响应成功', 'data': llm_kv_results}
        except Exception as e:
            logger.error(f'error: {e}')
            result = {'code': '500', 'msg': str(e)}
        result = json.dumps(result, indent=4, ensure_ascii=False)

    return Response(str(result), mimetype='application/json')


if __name__ == '__main__':
    # llm_model_name = 'qwen1.5'
    # llm_model_api_url = 'http://34.87.129.78:9300/v1'
    # client = DocumentExtract(llm_model_name=llm_model_name, llm_model_api_url=llm_model_api_url)
    # schema = '合同标题|借款合同编号|担保合同编号|借款人|贷款人|借款金额'
    # pdf_folder = '/home/public/huatai/流动资金借款合同_pdf'
    # save_folder = '/home/public/huatai/流动资金借款合同_pdf_qwen72B_res'
    # client.predict_all_pdf(pdf_folder, schema, save_folder)

    config = json.load(open('./config.json'))
    model_name = config['llm_model_name']
    model_api_url = config['llm_model_api_url']
    unstructured_api_url = config['unstructured_api_url']
    api_port = config['api_port']

    parser = argparse.ArgumentParser()
    parser.add_argument('--model_name', default=model_name, type=str, help='model name')
    parser.add_argument('--model_api_url', default=model_api_url, type=str, help='model api url')
    parser.add_argument('--unstructured_api_url', default=unstructured_api_url, type=str, help='unstructur api url')
    args = parser.parse_args()
    global ie_client
    ie_client = DocumentExtract(
        llm_model_name=args.model_name,
        llm_model_api_url=args.model_api_url,
        unstructured_api_url=args.unstructured_api_url
    )

    app.run(host='0.0.0.0', port=api_port, threaded=True)
