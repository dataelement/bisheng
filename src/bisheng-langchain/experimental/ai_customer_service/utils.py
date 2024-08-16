import json
import re
from pathlib import Path

import pandas as pd
import requests
from tqdm import tqdm


def merge_csv():
    test_df = pd.read_csv('./data/第二批test.csv')
    train_df = pd.read_csv('./data/第二批train.csv')
    result_df = pd.DataFrame(
        columns=[
            'query',
            'labels',
            'vector predict',
            'vector score',
        ]
    )
    for idx, row in tqdm(test_df.iterrows(), total=len(test_df)):
        title = row['标题']
        result_df.loc[idx, 'query'] = row['Question']
        try:
            result_df.loc[idx, 'labels'] = str([i for i in train_df[train_df['标题'] == title]['Question'].values])
        except Exception as e:
            print(e)
            result_df.loc[idx, 'labels'] = '找不到相关问题'
            continue
    result_df.to_excel('./data/第二批test_result.xlsx', index=False)


def response_parse(json_string: str) -> str:
    print(f'llm response before parse: {json_string}')
    match = re.search(r"```(json)?(.*)```", json_string, re.DOTALL)
    if match is None:
        json_str = ''
    else:
        json_str = match.group(0)

    json_str = json_str.strip()
    json_str = json_str.replace('```', '')

    match = re.search(r"\{.*\}", json_str, re.DOTALL)
    if match is None:
        json_str = json_str
    else:
        json_str = match.group(0)

    if json_str.endswith('}\n}'):
        json_str = json_str[:-2]
    if json_str.startswith('{\n{'):
        json_str = json_str.replace('{\n{', '{', 1)

    print(f'llm response after parse: {json_str}')
    return json_str


def upload_qa(file_path, knowledge_id):
    df = pd.read_excel(file_path).drop_duplicates(subset=['文章标题']).dropna(subset=['文章标题'])
    for idx, row in tqdm(df.iterrows(), total=len(df)):
        query = row['文章标题']
        answer = row['操作方法']
        json_data = {
            "knowledge_id": knowledge_id,
            "documents": [
                {
                    "page_content": query,
                    "metadata": {"source": f"{Path(file_path).name}_qa_{idx}.xlsx", "answer": answer},
                }
            ],
        }
        url = 'http://192.168.106.117:7860/api/v2/filelib/chunks_string'
        resp = requests.post(url=url, json=json_data)
        print(resp.json())


if __name__ == '__main__':
    # merge_csv()
    data_dir = '/public/youjiachen/workspace/移动九天/data/全量-QA问答对'
    for file in Path(data_dir).glob('*.xlsx'):
        upload_qa(file, '27')
