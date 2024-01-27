import json
import os
import re
import shutil
from collections import defaultdict
from pathlib import Path

import pandas as pd
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import AnswerCorrectness


def rages_answer_correctness(dataset):
    # answer_correctness, 只考虑事实相似度
    weights = [1.0, 0.0]
    batch_size = 5
    answer_correctness = AnswerCorrectness(weights=weights, batch_size=batch_size)
    result = evaluate(
        dataset=dataset,
        metrics=[
            answer_correctness,
        ],
    )
    df = result.to_pandas()
    return df


def rag_benchmark_scoring(excel_file):
    if not os.path.exists(excel_file + '.bak'):
        shutil.copy(excel_file, excel_file + '.bak')

    df = pd.read_excel(excel_file)
    df.dropna(subset=['问题', 'GT', 'rag_answer'], inplace=True)
    all_questions_info = df.to_dict('records')

    questions = []
    ground_truths = []
    answers = []
    contexts = []
    for question_info in all_questions_info:
        question = question_info['问题']
        gt = question_info['GT']
        pred = question_info['rag_answer']

        # 去除【1†source】, only for openai assitant
        # pattern = re.compile("【(\d+)†source】")
        # match = re.findall(pattern, pred)
        # for i in match:
        #     str_temp = f"【{i}†source】"
        #     pred = pred.replace(str_temp, '')

        questions.append(question)
        answers.append(pred)
        ground_truths.append([gt])
        contexts.append([''])

    # To dict
    data = {
        "question": questions,
        "answer": answers,
        "contexts": contexts,
        "ground_truths": ground_truths,
    }
    # Convert dict to dataset
    dataset = Dataset.from_dict(data)

    answer_correctness_score = rages_answer_correctness(dataset)
    score_map = {
        'answer_correctness': answer_correctness_score,
    }
    for metric, scores in score_map.items():
        df[metric] = df.index.map({idx: rows[metric] for idx, rows in scores.iterrows()})
    df.to_excel(excel_file, index=False)

    if '问题类型' in df.columns:
        grouped_df = (
            df.groupby('问题类型')
            .agg({'问题': 'count', **{metric: 'mean' for metric in score_map}})
            .rename(columns={'问题': '问题数量'})
        )
        total_question = grouped_df['问题数量'].sum()
        grouped_df.loc['all', '问题数量'] = total_question
        for metric in score_map:
            grouped_df.loc['all', metric] = df[metric].sum() / total_question
        return grouped_df


if __name__ == '__main__':
    excel_file = '/opt/bisheng/src/bisheng-langchain/experimental/rag/scoring/data/benchmark_v1.0.xlsx'
    print(rag_benchmark_scoring(excel_file))
