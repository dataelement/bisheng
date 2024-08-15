import json

import pandas as pd
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


if __name__ == '__main__':
    merge_csv()
