import base64
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import requests
import yaml
from llmtuner.chat import ChatModel
from loguru import logger
from tqdm import tqdm


def test_chat_model():
    chat_model = ChatModel(
        dict(
            model_name_or_path='/public/youjiachen/models/Qwen2-7B-Instruct_ELLM_SFT',
            template='qwen',
            do_sample=False,
            top_p=None,
            top_k=None,
            temperature=None,
            max_new_tokens=2000,
        )
    )
    system_prompt = 'You are a student in a geography class. Your teacher asks you:'
    prompt = "What is the capital of France?"
    messages = [{"role": "user", "content": prompt}]
    response = chat_model.chat(messages, system=system_prompt)
    print(response)


def test_api():
    import requests
    from flask import Flask, Response, request

    app = Flask(__name__)

    @app.route('/test_api', methods=['POST'])
    def test_function():
        print(request.json)
        return Response('ok', status=200, mimetype='application/json')

    app.run(host='0.0.0.0', port=5000, threaded=True)


def check_folder(folder):
    if not os.path.exists(folder):
        os.makedirs(folder)
    else:
        shutil.rmtree(folder)
        os.makedirs(folder)


def load_yaml(conf_file):
    """
    :param conf_file: can be file path, or string, or bytes
    :return:
    """
    if os.path.isfile(conf_file):
        return yaml.load(open(conf_file), Loader=yaml.FullLoader)
    else:
        return yaml.load(conf_file, Loader=yaml.FullLoader)


def api_call(pdf_path, schema, examples=None):
    data = {}
    data['file_name'] = os.path.basename(pdf_path)
    data['file_b64'] = base64.b64encode(open(pdf_path, 'rb').read()).decode()
    data['schema'] = schema

    url = "http://0.0.0.0:6118/document_ie"
    headers = {"Content-Type": "application/json"}
    r = requests.post(url=url, headers=headers, json=data).json()
    print(r)
    return r


def infer_scene(scene_folder, res_folder_name):
    meta_file = os.path.join(scene_folder, 'meta.yaml')
    meta_info = load_yaml(meta_file)
    field_def = meta_info['field_def']
    schema = '|'.join(field_def)
    print(schema)
    res_folder = os.path.join(scene_folder, res_folder_name)
    check_folder(res_folder)
    val_image_folder = os.path.join(scene_folder, 'Images', 'val')
    image_files = os.listdir(val_image_folder)
    for image_file in tqdm(image_files, desc=f'{Path(scene_folder).name}'):
        print(image_file)
        res = api_call(
            os.path.join(val_image_folder, image_file),
            schema,
        )
        json_file = os.path.splitext(image_file)[0] + '.json'
        with open(os.path.join(res_folder, json_file), 'w') as f:
            json.dump({'results': res['data']}, f, ensure_ascii=False, indent=2)

def score_scene(scene_folder, res_folder_name, score_script_path='/opt/ie_benchmark/score/ie_score/ScoreEngine.py'):
    scene_folder = Path(scene_folder)
    pred_path = scene_folder / res_folder_name
    nums = len(list(pred_path.glob('*.json')))
    logger.info(f"{scene_folder.name} 样本数量 ： {nums}")
    label_path = scene_folder / 'Labels_end2end'
    output_path = scene_folder

    cmd = f"python3 {score_script_path} --datadir {label_path} --preddir {pred_path} --savedir {output_path} --exclude_keys ''"
    score_result = subprocess.run(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    logger.error(score_result.stderr.decode('utf-8'))
    decoded_score_result = score_result.stdout.decode('utf-8')
    mFieldHmean = re.search(r'mFieldHmean: (.*?) %', decoded_score_result)
    MethodHmean = re.search(r'MethodHmean: (.*?) %', decoded_score_result)

    # logger.info(decoded_score_result)
    logger.warning(f"{mFieldHmean.group(1)}, {MethodHmean.group(1)}")

    return mFieldHmean.group(1), MethodHmean.group(1), nums


def test_chat_model_v2():
    from llmtuner.chat import ChatModel

    with open(
        '/public/youjiachen/bisheng/src/bisheng-langchain/experimental/document_ie_v3/scripts/test_example.json', 'r'
    ) as f:
        res = json.load(f)

    generte_config = {
        'do_sample': False,
        'top_p': None,
        'top_k': None,
        'temperature': None,
        'max_new_tokens': 2000,
    }
    chat_model = ChatModel(
        dict(
            model_name_or_path='/public/youjiachen/models/Qwen2-7B-Instruct',
            adapter_name_or_path='/public/youjiachen/models/adaptor/ellm_qwen2_7b_instruct_0_2_shot',
            template='qwen',
            **generte_config,
        )
    )

    messages = [{'role': 'user', "content": res['meta_data']['instruction']}]
    system_msg = res['meta_data']['system']
    res = chat_model.chat(messages, system=system_msg)
    print(res)


if __name__ == '__main__':
    # dataset_folder = '/public/ELLM_v3_datasets/ellm_v3_socr'
    # result_folder_name = 'val_res_0624_llm'
    # eval_scenes = [
    #     # "收入证明",
    #     "现金缴款单-广农信",
    #     # "网智-商品房购房合同",
    # ]
    # for scene_name in tqdm(eval_scenes):
    #     infer_scene(
    #         scene_folder=Path(dataset_folder) / scene_name,
    #         res_folder_name=result_folder_name,
    #     )
    #     score_scene(
    #         scene_folder=Path(dataset_folder) / scene_name,
    #         res_folder_name=result_folder_name,
    #     )
    test_chat_model_v2()
