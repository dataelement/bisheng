# flake8: noqa
import argparse
import base64
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml
from flask import Flask, Response, request
from llm_extract import LlmExtract, init_logger
from tqdm import tqdm

logger = init_logger(__name__)
app = Flask(__name__)


class DocumentExtract(object):
    def __init__(
        self,
        model_path: str,
        idp_url: str,
        generation_config: Dict[str, Any],
        spliter_config: Dict[str, Any],
        adaptor_path: str = None,
    ):
        self.llm_client = LlmExtract(
            model_path=model_path,
            adaptor_path=adaptor_path,
            idp_url=idp_url,
            generation_config=generation_config,
            spliter_config=spliter_config,
        )

    def predict_one_pdf(self, pdf_path, schema, examples: Tuple[Path, Path] = None, save_folder=''):
        pdf_name_prefix = os.path.splitext(os.path.basename(pdf_path))[0]

        if save_folder:
            save_llm_path = os.path.join(save_folder, pdf_name_prefix + '_llm.json')
            if self.replace_llm_cache or not os.path.exists(save_llm_path):
                llm_kv_results = self.llm_client.predict(
                    filepath=pdf_path,
                    schema=schema,
                    examples=examples,
                )
                with open(save_llm_path, 'w') as f:
                    json.dump(llm_kv_results, f, indent=2, ensure_ascii=False)
            else:
                # get results from cache
                with open(save_llm_path, 'r') as f:
                    llm_kv_results = json.load(f)
        else:
            llm_kv_results = self.llm_client.predict(
                filepath=pdf_path,
                schema=schema,
                examples=examples,
            )

        return llm_kv_results

    def predict_all_pdf(self, pdf_folder, schema, save_folder=''):
        if not os.path.exists(save_folder):
            os.makedirs(save_folder)
        pdf_names = os.listdir(pdf_folder)
        for pdf_name in tqdm(pdf_names):
            logger.info(f'process pdf: {pdf_name}')
            pdf_path = os.path.join(pdf_folder, pdf_name)
            llm_kv_results = self.predict_one_pdf(pdf_path, schema, save_folder)


@app.route('/document_ie', methods=['POST'])
def extract_document_kv():
    data = request.json
    file_name = data['file_name']
    file_b64 = data['file_b64']
    schema = data['schema']

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = os.path.join(tmpdir, file_name)
        with open(file_path, 'wb') as fout:
            fout.write(base64.b64decode(file_b64))

        try:
            llm_kv_results = ie_client.predict_one_pdf(file_path, schema)
            result = {'code': '200', 'msg': '响应成功', 'data': llm_kv_results}
        except Exception as e:
            logger.error(f'error: {e}')
            result = {'code': '500', 'msg': str(e)}
        result = json.dumps(result, indent=4, ensure_ascii=False)

    return Response(str(result), mimetype='application/json')


if __name__ == '__main__':
    with open('./config.yaml', 'r') as f:
        config = yaml.safe_load(f)

    model_path = config['model_path']
    adaptor_path = config['adaptor_path']

    idp_url = config['idp_url']
    spliter_config = config['spliter_config']
    generation_config = config['generation_config']

    api_port = config['api_port']

    parser = argparse.ArgumentParser()
    parser.add_argument('--model_path', default=model_path, type=str, help='model name')
    parser.add_argument('--adaptor_path', default=adaptor_path, type=str, help='adaptor path')
    parser.add_argument('--idp_url', default=idp_url, type=str, help='model api url')
    parser.add_argument('--spliter_config', default=spliter_config, type=dict, help='text spliter config')
    parser.add_argument('--generation_config', default=generation_config, type=dict, help='model generation config')
    args = parser.parse_args()
    global ie_client
    ie_client = DocumentExtract(
        model_path=args.model_path,
        idp_url=args.idp_url,
        unstructured_api_url=args.unstructured_api_url,
        adaptor_path=args.adaptor_path,
    )

    app.run(host='0.0.0.0', port=api_port, threaded=True)
