import json
from collections import defaultdict

import pandas as pd


def get_short_doc_filename():
    all_docs_path = '../all_split_docs.json'
    with open(all_docs_path, 'r') as f:
        all_docs = json.load(f)
    filenames2num = defaultdict(int)
    for filename, doc in all_docs.items():
        for page in doc:
            filenames2num[filename] += len(page['page_content'])
    df = pd.DataFrame(filenames2num.items(), columns=['filename', 'num_of_char'])
    df.to_excel('./num_of_char.xlsx', index=False)

    short_df_8k = df[(df['num_of_char'] < 8000) & (df['num_of_char'] > 0)]
    short_df_16k = df[(df['num_of_char'] < 16000) & (df['num_of_char'] >= 8000)]
    print(f'8k以下短文档占比: {short_df_8k.shape[0] / df.shape[0]}')
    print(f'16k以下短文档占比: {short_df_16k.shape[0] / df.shape[0]}')

    short_doc_8k = short_df_8k['filename'].to_list()
    short_doc_16k = short_df_16k['filename'].tolist()

    return short_doc_8k, short_doc_16k


def analyze_short_docs():
    doc_8k, doc_16k = get_short_doc_filename()

    benchmark_path = '../benchmark_v1.0.xlsx'
    df = pd.read_excel(benchmark_path, sheet_name='qwen14b')

    df_8k = df[df['文件名'].isin(doc_8k)]
    print(f'8k以下的文档，问题数量: {df_8k.shape[0]}')
    print(f'8k以下文档数量：{len(doc_8k)}')
    print(f'8k以下的文档，事实相似度平均值: {df_8k["事实相似度"].mean().round(4)}')

    print('-' * 20)

    df_16k = df[df['文件名'].isin(doc_16k)]
    print(f'16k以下的文档，问题数量: {df_16k.shape[0]}')
    print(f'16k以下文档数量：{len(doc_16k)}')
    print(f'16k以下的文档，事实相似度平均值: {df_16k["事实相似度"].mean().round(4)}')


def strip_column_value():
    benchmark_data = '/opt/bisheng/src/bisheng-langchain/experimental/rag/data/benchmark_v1.0.xlsx'

    model2df = dict()
    for model in ['gpt4', 'qwen14b', 'qwen72b', 'qwen7b', 'qwen1.8b']:
        df = pd.read_excel(benchmark_data, sheet_name=model)
        df['问题类型'].fillna('无', inplace=True)
        df['问题类型'] = df['问题类型'].apply(lambda x: x.strip())
        model2df[model] = df

    # save
    with pd.ExcelWriter(benchmark_data) as writer:
        for model, df in model2df.items():
            df.to_excel(writer, sheet_name=model, index=False)


if __name__ == '__main__':
    # short_doc_questions()
    strip_column_value()
