import os
import pdb
import pandas as pd
import requests
import json
from config import API_KEY, DATASET_API, DIFY_TOKEN
from loguru import logger
import tqdm

datasets = set()
dataset = {}

def add_dataset(name, dataset_id):
    """    根据dataset 创建set， 映射name到id    """
    datasets.add(name)
    dataset[name] = dataset_id
    return dataset_id

def query_dataset_from_dify():
    """
    知识库列表
    curl --location --request GET 'https://api.dify.ai/v1/datasets?page=1&limit=20' \
    --header 'Authorization: Bearer {api_key}'"""
    url = 'https://api.dify.ai/v1/datasets?page=1&limit=100'
    headers = {
        'Authorization': f'Bearer {DATASET_API}', 
    }
    response = requests.get(url, headers=headers).json()
    datasets = response['data']
    print(datasets)
    
    for dataset in datasets:
        name = dataset['name']
        id = dataset['id']
        add_dataset(name, id)
    return datasets

def create_dataset(name):
    url = 'https://api.dify.ai/v1/datasets'
    headers = {
        'Authorization': f'Bearer {DATASET_API}',
        'Content-Type': 'application/json',
    }
    data = {
        'name': name,
    }
    response = requests.post(url, headers=headers, data=json.dumps(data)).json()
    print(response)
    return response

def query_file_from_dataset(dataset_id):
    """curl --location --request GET 'https://api.dify.ai/v1/datasets/{dataset_id}/documents' \
--header 'Authorization: Bearer {api_key}'"""
    url = f'https://api.dify.ai/v1/datasets/{dataset_id}/documents'
    headers = {
        'Authorization': f'Bearer {DATASET_API}',
    }
    response = requests.get(url, headers=headers).json()
    print(response)
    
    files = response['data']
    return files
    
def create_by_file(file_path, dataset_id):
    url = f'https://api.dify.ai/v1/datasets/{dataset_id}/document/create_by_file'
    headers = {
        'Authorization': f'Bearer {DATASET_API}',
    }
    data = {
        "name": "Dify",
        "indexing_technique": "high_quality",
        "process_rule": {
            "rules": {
                "pre_processing_rules": [
                    {"id": "remove_extra_spaces", "enabled": True},
                    {"id": "remove_urls_emails", "enabled": True}
                ],
                "segmentation": {
                    "separator": "###",
                    "max_tokens": 500
                }
            },
            "mode": "automatic"
        }
    }
    files = {
        'data': (None, json.dumps(data), 'application/json'),
        'file': open(file_path, 'rb')
    }
    response = requests.post(url, headers=headers, files=files).json()
    print(response)
    return response

def get_answer_from_dify(query, conversation_id="", user="abc123"):
    url = 'https://api.dify.ai/v1/chat-messages'
    headers = {
        'Authorization': f'Bearer {API_KEY}',
        'Content-Type': 'application/json',
    }
    data = {
        'inputs': {},
        'query': query,
        'response_mode': 'blocking',
        'conversation_id': conversation_id,
        'user': user,
        # 'files': [
        #     {
        #         "type": "image",
        #         "transfer_method": "local_file",
        #         "upload_file_id": f'{file_id}'}    
        # ],
    }
    response = requests.post(url, headers=headers, data=json.dumps(data)).json()
    print(response)
    return response

def upload_file_to_dify(data_dir, excel_file, save_excel_file):
    df = pd.read_excel(excel_file)
    all_questions_info = list()
    # 遍历每一行
    for index, row in df.iterrows():
        # 遍历每一列
        question_info = dict()
        for column in df.columns:
            value = row[column]
            question_info[column] = value
            # print(f"Row {index}, Column {column} has value {value}")
        all_questions_info.append(question_info)
    
    for questions_info in tqdm(all_questions_info):
        collection_name = questions_info['知识库名']
        file_name = questions_info['文件名']
        file_type = questions_info['文件类型']
        
        # pdb.set_trace()
        if file_type == 'pdf':
            # 没有知识库先创建
            if collection_name not in datasets:
                res = create_dataset(collection_name)
                dataset_id = res['id']
                add_dataset(collection_name, dataset_id) 
            else:
                dataset_id = dataset[collection_name]
           
            #  查询知识库中是否有该文件
            files = query_file_from_dataset(dataset_id)
            has_file = False
            for file in files:
                if file_name == file['name']:
                    has_file = True
                    file_id = file['id']
                    break
            if not has_file:
                try:
                    res = create_by_file(os.path.join(data_dir, file_name), dataset_id)
                    file_id = res['document']['id']
                except Exception as e:
                    file_id = ''
                    logger.warning(f'error in create file {file_name}: {e}')
                    
            questions_info['dataset_id'] = dataset_id           
        
    # save excel
    df = pd.DataFrame(all_questions_info)
    df.to_excel(save_excel_file, index=False)

def re_config_dataset(dataset_id, app_id='8ab350f2-d4f9-40c9-a9f3-ff5575332dea'):
    """抓包的应用config url"""
    url = f'https://cloud.dify.ai/console/api/apps/{app_id}/model-config'
    headers = {
        'authority': 'cloud.dify.ai',
        'accept': '*/*',
        'accept-language': 'zh-CN,zh;q=0.9',
        'authorization': f'Bearer {DIFY_TOKEN}',
        'content-type': 'application/json',
        'origin': 'https://cloud.dify.ai',
        'referer': 'https://cloud.dify.ai/app/97b613df-c950-4c53-a9ae-125bd1c54386/configuration',
        'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    data = {
        "pre_prompt": None,
        "prompt_type": "simple",
        "chat_prompt_config": {},
        "completion_prompt_config": {},
        "user_input_form": [],
        "dataset_query_variable": "",
        "opening_statement": "",
        "more_like_this": {"enabled": False},
        "suggested_questions_after_answer": {"enabled": False},
        "speech_to_text": {"enabled": False},
        "retriever_resource": {"enabled": False},
        "sensitive_word_avoidance": {"enabled": False, "type": "", "configs": []},
        "external_data_tools": [],
        "agent_mode": {
            "enabled": True,
            "tools": [
                {"dataset": {"enabled": True, "id": f'{dataset_id}'}},
            ]
        },
        "model": {
            "provider": "openai",
            "name": "gpt-4-1106-preview",
            "mode": "chat",
            "completion_params": {"max_tokens": 512, "temperature": 1, "top_p": 1, "presence_penalty": 0, "frequency_penalty": 0}
        },
        "dataset_configs": {"retrieval_model": "single", "top_k": 20, "score_threshold": 0.5},
        "file_upload": {"image": {"enabled": False, "number_limits": 3, "detail": "high", "transfer_methods": ["remote_url", "local_file"]}}
    }

    response = requests.post(url, headers=headers, data=json.dumps(data))
    print(response.json())
               
    
def question_answer(excel_file):
    df = pd.read_excel(excel_file)
    all_questions_info = list()
    # 遍历每一行
    for index, row in df.iterrows():
        # 遍历每一列
        question_info = dict()
        for column in df.columns:
            value = row[column]
            question_info[column] = value
            # print(f"Row {index}, Column {column} has value {value}")
        all_questions_info.append(question_info)  

    for questions_info in all_questions_info:
        question = questions_info['问题']
        file_type = questions_info['文件类型']
        collection_name = questions_info['知识库名']
        dataset_id = questions_info['dataset_id']
        if collection_name not in datasets or dataset_id == '':
            res = create_dataset(collection_name)
            dataset_id = add_dataset(collection_name, res['id']) 
        
        try:
            re_config_dataset(dataset_id)
            response = get_answer_from_dify(question)
            ans = response['answer']
        except Exception as e:
            print(f'error in query {question}')
            ans = ''    
        print('ans:', ans, 'question:', question)
        questions_info['dify_answer'] = ans
    
    df = pd.DataFrame(all_questions_info)
    df.to_excel(os.path.join('questions_info_with_answer_dify.xlsx'), index=False)

if __name__ == '__main__':
    data_dir = './rag_benchmark_v1.0/rag_benchmark'
    save_dir = './rag_benchmark_v1.0/rag_benchmark_processed'
    excel_file = './data/questions_info_with_answer_sample.xlsx'
    save_excel_file = './data/questions_info_with_dify_file_id.xlsx'
    
    query_dataset_from_dify()
    # upload_file_to_dify(save_dir, excel_file, save_excel_file)
    question_answer(save_excel_file)
    
