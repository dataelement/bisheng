import os
import pdb
import pandas as pd
import requests
import json
from config import FAST_GPT_API_KEY, FAST_GPT_APP_KEY, FAST_GPT_TOKEN
from loguru import logger
from tqdm import tqdm

datasets = set()
dataset = {}

def add_dataset(name, dataset_id):
    """    根据dataset 创建set， 映射name到id    """
    datasets.add(name)
    dataset[name] = dataset_id
    return dataset_id

def query_dataset_from_fastgpt():
    """
    知识库列表
    curl --location --request GET 'http://localhost:3000/api/core/dataset/list?parentId=' \
    --header 'Authorization: Bearer {{authorization}}' \
    """
    url = 'https://cloud.fastgpt.in/api/core/dataset/list?parentId='
    headers = {
        'Authorization': f'Bearer {FAST_GPT_API_KEY}', 
    }
    logger.debug(f'Starting to query dataset from fastgpt')
    response = requests.get(url, headers=headers).json()
    print(response)
    datasets = response['data']
        
    for dataset in datasets:
        name = dataset['name']
        id = dataset['_id']
        add_dataset(name, id)
    return datasets

def create_dataset(name):
    """curl --location --request POST 'http://localhost:3000/api/core/dataset/create' \
    --header 'Authorization: Bearer {{authorization}}' \
    --header 'Content-Type: application/json' \
    --data-raw '{
        "parentId": null,
        "type": "dataset",
        "name":"测试",
        "intro":"介绍",
        "avatar": "",
        "vectorModel": "text-embedding-ada-002",
        "agentModel": "gpt-3.5-turbo-16k"
    }'
    """
    url = 'https://cloud.fastgpt.in/api/core/dataset/create'
    headers = {
        'Authorization': f'Bearer {FAST_GPT_API_KEY}',
        'Content-Type': 'application/json',
    }
    data = {
        'name': name,
        'vectorModel': 'text-embedding-ada-002',
        'agentModel': 'gpt-4-1106-preview',
    }
    logger.debug(f'Starting to create dataset {name}')
    response = requests.post(url, headers=headers, data=json.dumps(data)).json()
    print(response)
    return response

def query_from_dataset(dataset_id):
    """curl --location --request GET 'http://localhost:3000/api/core/dataset/detail?id=6593e137231a2be9c5603ba7' \
    --header 'Authorization: Bearer {{authorization}}' \
    """
    url = f'https://cloud.fastgpt.in/api/core/dataset/detail?id={dataset_id}'
    headers = {
        'Authorization': f'Bearer {FAST_GPT_API_KEY}',
    }
    response = requests.get(url, headers=headers).json()
    print(response)

def query_file_from_dataset(dataset_id):
    """curl --location --request POST 'http://localhost:3000/api/core/dataset/collection/list' \
    --header 'Authorization: Bearer {{authorization}}' \
    --header 'Content-Type: application/json' \
    --data-raw '{
        "pageNum":1,
        "pageSize": 10,
        "datasetId":"6593e137231a2be9c5603ba7",
        "parentId": null,
        "searchText":""
    }'
    """
    url = f'https://cloud.fastgpt.in/api/core/dataset/collection/list'
    headers = {
        'Authorization': f'Bearer {FAST_GPT_API_KEY}',
         'Content-Type': 'application/json',
    }
    data = {
        'datasetId': dataset_id,
    }
    response = requests.post(url, headers=headers, data=json.dumps(data)).json()['data']
    print(response)
    
    files = response['data']
    return files
    
def create_by_file(file_path, dataset_id):
    """
    curl --location --request POST 'http://localhost:3000/api/proApi/core/dataset/collection/create/file' \
    --header 'Authorization: Bearer {{authorization}}' \
    --form 'file=@"C:\\Users\\user\\Desktop\\fastgpt测试文件\\index.html"' \
    --form 'data="{\"datasetId\":\"6593e137231a2be9c5603ba7\",\"parentId\":null,\"trainingType\":\"chunk\",\"chunkSize\":512,\"chunkSplitter\":\"\",\"qaPrompt\":\"\",\"metadata\":{}}"'
    """
    url = 'https://cloud.fastgpt.in/api/proApi/core/dataset/collection/create/file'
    headers = {
        'Authorization': f'Bearer {FAST_GPT_API_KEY}',
    }
    data = {
        'datasetId': dataset_id,
        'parentId': None,
        'trainingType': 'chunk',
        'chunkSize': 512,
        'chunkSplitter': '',
        'qaPrompt': '',
        'metadata': {},
    }
    files = {
        'file': open(file_path, 'rb'),
    }
    logger.debug(f'Starting to create file {file_path}')
    response = requests.post(url, headers=headers, data={'data': json.dumps(data)}, files=files).json()
    print(response)
    return response

def upload_file_to_fastgpt(data_dir, excel_file, save_excel_file):
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
        
  
        # 没有知识库先创建
        if collection_name not in datasets:
            res = create_dataset(collection_name)
            dataset_id = res['data']
            add_dataset(collection_name, dataset_id)
            
        else:
            dataset_id = dataset[collection_name]
        
        #  查询知识库中是否有该文件
        files = query_file_from_dataset(dataset_id)
        has_file = False

        for file in files:
            # TODO: fix pdf name 乱码
            if 'pdf' in file['name']:
                has_file = True
                file_id = file['_id']
                break
        if not has_file:
            try:
                res = create_by_file(os.path.join(data_dir, file_name), dataset_id)
                file_id = res['data']['collectionId']
            except Exception as e:
                file_id = ''
                logger.warning(f'error in create file {file_name}: {e}')
                
        questions_info['dataset_id'] = dataset_id           
        
        # save excel
        df = pd.DataFrame(all_questions_info)
        df.to_excel(save_excel_file, index=False)

def re_config_dataset(dataset_id, app_id='65b0b043c8685c9a14443f29'):
    """抓包的应用config url"""
    url = 'https://cloud.fastgpt.in/api/core/app/form2Modules/fastgpt-universal'
    headers = {
        'authority': 'cloud.fastgpt.in',
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'zh-CN,zh;q=0.9',
        'content-type': 'application/json',
        'cookie': FAST_GPT_TOKEN,
        'origin': 'https://cloud.fastgpt.in',
        'referer': f'https://cloud.fastgpt.in/app/detail?appId={app_id}',
        'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'token': FAST_GPT_TOKEN,
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    data = json.dumps({
        "formData": {
            "templateId": "fastgpt-universal",
            "aiSettings": {
                "model": "gpt-4-1106-preview",
                "temperature": 0,
                "isResponseAnswerText": True,
                "maxToken": 8000
            },
            "cfr": {
                "background": ""
            },
            "dataset": {
                "datasets": [
                    {
                        "datasetId": dataset_id,
                        "vectorModel": {
                            "model": "text-embedding-ada-002",
                            "name": "Embedding-2",
                            "defaultToken": 512,
                            "maxToken": 3000,
                            "weight": 100,
                            "inputPrice": 0.002,
                            "outputPrice": 0
                        }
                    }
                ],
                "similarity": 0.5,
                "limit": 1500,
                "searchEmptyText": "",
                "searchMode": "embedding",
                "usingReRank": True
            },
            "userGuide": {
                "welcomeText": "",
                "variables": [],
                "questionGuide": False,
                "tts": {
                    "type": "web"
                }
            }
        },
        "chatModelMaxToken": 16000,
    })

    logger.debug(f'Starting to re_config_dataset {dataset_id}')
    response = requests.post(url, headers=headers, data=data)
    logger.debug(response.json())

def get_answer_from_fastgpt(query, app_id='65b0b043c8685c9a14443f29'):
    """curl --location --request POST 'https://api.fastgpt.in/api/v1/chat/completions' \
    --header 'Authorization: Bearer fastgpt-xxxxxx' \
    --header 'Content-Type: application/json' \
    --data-raw '{
        "chatId": "abcd",
        "stream": false,
        "detail": false,
        "variables": {
            "uid": "asdfadsfasfd2323",
            "name": "张三"
        },
        "messages": [
            {
                "content": "导演是谁",
                "role": "user"
            }
        ]
    }'
    """
    url = 'https://api.fastgpt.in/api/v1/chat/completions'
    headers = {
        'Authorization': f'Bearer {FAST_GPT_APP_KEY}',
        'Content-Type': 'application/json',
    }
    data = {
        "chatId": app_id,
        "stream": False,
        "detail": False,
        "variables": {
            "uid": "asdfadsfasfd2323",
            "name": "张三"
        },
        "messages": [
            {
                "content": query,
                "role": "user"
            }
        ]
    }
    response = requests.post(url, headers=headers, data=json.dumps(data)).json()
    print(response)
    return response

def search_dataset_from_fastgpt(query, dataset_id):
    """curl --location --request POST 'https://api.fastgpt.in/api/core/dataset/searchTest' \
    --header 'Authorization: Bearer fastgpt-xxxxx' \
    --header 'Content-Type: application/json' \
    --data-raw '{
        "datasetId": "知识库的ID",
        "text": "导演是谁",
        "limit": 5000,
        "similarity": 0,
        "searchMode": "embedding",
        "usingReRank": false
    }'
    """
    url = 'https://api.fastgpt.in/api/core/dataset/searchTest'
    headers = {
        'Authorization': f'Bearer {FAST_GPT_API_KEY}',
        'Content-Type': 'application/json',
    }
    data = {
        "datasetId": dataset_id,
        "text": query,
        "limit": 5000,
        "similarity": 0,
        "searchMode": "embedding",
        "usingReRank": True
    }
    response = requests.post(url, headers=headers, data=json.dumps(data)).json()
    print(response)
    return response             
    
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

    for questions_info in tqdm(all_questions_info):
        question = questions_info['问题']
        file_type = questions_info['文件类型']
        collection_name = questions_info['知识库名']
        dataset_id = questions_info['dataset_id']
        if collection_name not in datasets or dataset_id == '':
            res = create_dataset(collection_name)
            dataset_id = add_dataset(collection_name, res['id']) 
        
        try:
            re_config_dataset(dataset_id)
            # response = search_dataset_from_fastgpt(question, dataset_id)
            response = get_answer_from_fastgpt(question)
            ans = response['choices'][0]['message']['content']
        except Exception as e:
            print(f'error in query {question}')
            ans = ''    
        print('ans:', ans, 'question:', question)
        questions_info['fastgpt_answer'] = ans
    
        df = pd.DataFrame(all_questions_info)
        df.to_excel(os.path.join('questions_info_with_answer_fastgpt.xlsx'), index=False)

if __name__ == '__main__':
    data_dir = './rag_benchmark_v1.0/rag_benchmark'
    save_dir = './rag_benchmark_v1.0/rag_benchmark_processed'
    excel_file = './data/questions_info_with_answer_sample.xlsx'
    save_excel_file = './data/questions_info_with_fastgpt_file_id.xlsx'
    
    query_dataset_from_fastgpt()
    # upload_file_to_fastgpt(save_dir, excel_file, save_excel_file)
    question_answer(save_excel_file)
    
