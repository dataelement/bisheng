import os
import shutil

import httpx
import nest_asyncio
import pandas as pd

nest_asyncio.apply()
from collections import defaultdict

from llama_index import ServiceContext
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.evaluation import CorrectnessEvaluator
from llama_index.llms import OpenAI
from tqdm import tqdm

openai_api_key = os.environ.get('OPENAI_API_KEY', '')
openai_proxy = os.environ.get('OPENAI_PROXY', '')


def llama_index_answer_correctness(querys, responses, references):
    embed = OpenAIEmbedding(api_key=openai_api_key, http_client=httpx.AsyncClient(proxies=openai_proxy))

    model_name = "gpt-3.5-turbo-16k"
    service_context = ServiceContext.from_defaults(
        llm=OpenAI(model=model_name, api_key=openai_api_key, http_client=httpx.AsyncClient(proxies=openai_proxy)),
        embed_model=embed,
    )
    evaluator = CorrectnessEvaluator(service_context=service_context)

    correctness_scores = []
    correctness_feedbacks = []
    for i in tqdm(range(len(querys))):
        result = evaluator.evaluate(
            query=querys[i],
            response=responses[i],
            reference=references[i],
        )
        correctness = result.score
        feedback = result.feedback
        correctness_scores.append(correctness)
        correctness_feedbacks.append(feedback)
    return correctness_scores, correctness_feedbacks


def rag_benchmark_scoring(excel_file):
    if not os.path.exists(excel_file + '.bak'):
        shutil.copy(excel_file, excel_file + '.bak')

    df = pd.read_excel(excel_file)
    df.dropna(subset=['问题', 'GT', 'rag_answer'], inplace=True)
    all_questions_info = df.to_dict('records')

    questions = []
    ground_truths = []
    answers = []
    for question_info in all_questions_info:
        question = question_info['问题']
        gt = question_info['GT']
        pred = question_info['rag_answer']

        questions.append(question)
        answers.append(pred)
        ground_truths.append(gt)

    correctness_scores, correctness_feedbacks = llama_index_answer_correctness(questions, answers, ground_truths)

    score_map = {
        'llama_index_correctness': correctness_scores,
    }

    for metric, scores in score_map.items():
        df[metric] = df.index.map({i: score for i, score in enumerate(scores)})
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
    excel_file = './data/benchmark_v1.0.xlsx'
    print(rag_benchmark_scoring(excel_file))
