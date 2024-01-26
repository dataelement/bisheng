import os
import json
import pandas as pd
import re
from collections import defaultdict
from ragas import evaluate
from ragas.metrics import AnswerCorrectness
from datasets import Dataset


def rages_answer_correctness(dataset):
    # answer_correctness, 只考虑事实相似度
    weights = [1.0, 0.0]
    batch_size = 5
    answer_correctness = AnswerCorrectness(weights=weights, 
                                           batch_size=batch_size)
    result = evaluate(
        dataset = dataset, 
        metrics=[
            answer_correctness,
        ],
    )
    df = result.to_pandas()
    return df


def rag_benchmark_scoring(excel_file):
    df = pd.read_excel(excel_file)
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
        "ground_truths": ground_truths
    }
    # Convert dict to dataset
    dataset = Dataset.from_dict(data)

    answer_correctness_score = rages_answer_correctness(dataset)
    answer_correctness_score = answer_correctness_score.to_dict('records')

    score_map = {
        'answer_correctness': answer_correctness_score,
    }

    ragas_score = defaultdict(lambda: defaultdict(list))
    for score_type in score_map:
        for i in range(len(all_questions_info)):
            if all_questions_info[i]['问题'] != score_map[score_type][i]['question']:
                raise ValueError('question not match')
            all_questions_info[i][score_type] = score_map[score_type][i][score_type]

            if '问题类型' in all_questions_info[i]:
                ques_type = all_questions_info[i]['问题类型'].strip()
                ragas_score[ques_type][score_type].append(all_questions_info[i][score_type])  
            ragas_score['all'][score_type].append(all_questions_info[i][score_type])
        
    df = pd.DataFrame(all_questions_info)
    df.to_excel(excel_file, index=False)

    flat_score = []
    for ques_type in ragas_score:
        each_ques_type_score = dict()
        each_ques_type_score['问题类型'] = ques_type
        each_ques_type_score['问题个数'] = len(ragas_score[ques_type][list(score_map.keys())[0]])
        for score_type in ragas_score[ques_type]:
            avg_score = sum(ragas_score[ques_type][score_type]) / len(ragas_score[ques_type][score_type])
            each_ques_type_score[score_type] = avg_score

        flat_score.append(each_ques_type_score)
    
    return pd.DataFrame(flat_score)


if __name__ == '__main__':
    excel_file = '../data/questions_info_with_answer_sample_qwen14b_12chunk.xlsx'
    print(rag_benchmark_scoring(excel_file))