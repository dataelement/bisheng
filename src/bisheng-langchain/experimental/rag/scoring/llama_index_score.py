import os
import httpx
import pandas as pd
import nest_asyncio
nest_asyncio.apply()
from collections import defaultdict
from tqdm import tqdm
from llama_index.evaluation import CorrectnessEvaluator
from llama_index.llms import OpenAI
from llama_index import ServiceContext
from llama_index.embeddings.openai import OpenAIEmbedding

openai_api_key = os.environ.get('OPENAI_API_KEY', '')
openai_proxy = os.environ.get('OPENAI_PROXY', '')


def llama_index_answer_correctness(querys, responses, references):
    embed = OpenAIEmbedding(api_key=openai_api_key, 
                            http_client=httpx.AsyncClient(proxies=openai_proxy))

    model_name = "gpt-3.5-turbo-16k"
    service_context = ServiceContext.from_defaults(llm=OpenAI(model=model_name, 
                                                              api_key=openai_api_key, 
                                                              http_client=httpx.AsyncClient(proxies=openai_proxy)), 
                                                   embed_model=embed)
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
    df = pd.read_excel(excel_file)
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
    
    correctness_scores, correctness_feedbacks = llama_index_answer_correctness(
        questions, answers, ground_truths)

    score_map = {
        'llama_index_correctness': correctness_scores,
    }

    llama_index_score = defaultdict(lambda: defaultdict(list))
    for score_type in score_map:
        for i in range(len(all_questions_info)):
            all_questions_info[i][score_type] = score_map[score_type][i]

            if '问题类型' in all_questions_info[i]:
                ques_type = all_questions_info[i]['问题类型'].strip()
                llama_index_score[ques_type][score_type].append(all_questions_info[i][score_type])  
            llama_index_score['all'][score_type].append(all_questions_info[i][score_type])
        
    df = pd.DataFrame(all_questions_info)
    df.to_excel(excel_file, index=False)

    flat_score = []
    for ques_type in llama_index_score:
        each_ques_type_score = dict()
        each_ques_type_score['问题类型'] = ques_type
        each_ques_type_score['问题个数'] = len(llama_index_score[ques_type][list(score_map.keys())[0]])
        for score_type in llama_index_score[ques_type]:
            avg_score = sum(llama_index_score[ques_type][score_type]) / len(llama_index_score[ques_type][score_type])
            each_ques_type_score[score_type] = avg_score

        flat_score.append(each_ques_type_score)
    
    return pd.DataFrame(flat_score)


if __name__ == '__main__':
    excel_file = '../data/questions_info_with_answer_sample_qwen14b_12chunk.xlsx'
    print(rag_benchmark_scoring(excel_file))