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

    stats = defaultdict(dict)
    start = 1
    interval2filenames = defaultdict(list)
    for end in range(8000, 200000, 8000):
        interval = f'[{start}, {end})'
        count = df[(df['num_of_char'] >= start) & (df['num_of_char'] < end)]
        interval2filenames[interval] = count['filename'].to_list()
        row_nums = count.shape[0]

        stats[interval] = {'count': row_nums, 'percent': row_nums / df.shape[0]}

        print(f'{interval} : {row_nums}')
        print(f'{interval} 占比 : {row_nums / df.shape[0]}')
        print('-' * 20)

        start = end

    match_row_nums = df[df['num_of_char'] >= start].shape[0]
    final_interval = f'[{start}, +inf)'
    stats[final_interval] = {
        'count': match_row_nums,
        'percent': match_row_nums / df.shape[0],
    }
    interval2filenames[final_interval] = df[df['num_of_char'] >= start]['filename'].to_list()

    return interval2filenames


def analyze_docs():
    interval2filenames = get_short_doc_filename()

    benchmark_path = '../benchmark_v1.0.xlsx'
    df = pd.read_excel(benchmark_path, sheet_name='qwen14b')
    df.dropna(subset=['问题', 'GT', 'rag_answer'], inplace=True)

    total_question = 0
    interval2question_num = defaultdict(dict)
    for interval, filenames in interval2filenames.items():
        match_rows = df[df['文件名'].isin(filenames)]
        match_question_num = match_rows.shape[0]
        total_question += match_question_num
        interval2question_num[interval]['问题数'] = match_question_num
        interval2question_num[interval]['文档数'] = len(filenames)
        print(f"{interval}的文档，问题数量: {match_question_num}")
        print(f"{interval}的文档数量：{len(filenames)}")
        if len(filenames) == 0:
            print('-' * 20)
            continue
        print(f"{interval}的文档，事实相似度平均值: {match_rows['事实相似度'].mean():.4f}")
        print('-' * 20)

    c_df = pd.DataFrame.from_dict(interval2question_num, orient='index')
    c_df['问题数占比'] = c_df['问题数'] / c_df['问题数'].sum()
    c_df['文档数占比'] = c_df['文档数'] / c_df['文档数'].sum()
    c_df.to_excel('./interval2question_num.xlsx')
    print(total_question)


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
    get_short_doc_filename()
    analyze_docs()
    # strip_column_value()
