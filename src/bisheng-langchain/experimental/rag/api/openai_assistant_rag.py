import os
import openai
import httpx
import time
import json
import shutil
import pandas as pd
from tqdm import tqdm
from collections import defaultdict
from openai import OpenAI
thread_ids = set()


client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY', ''), 
                http_client=httpx.Client(proxies=os.environ.get('OPENAI_PROXY', '')))


def upload_files(data_folder, excel_file, save_excel_file):
    df = pd.read_excel(excel_file)
    all_questions_info = list()
    # 遍历每一行
    for index, row in df.iterrows():
        # 遍历每一列
        question_info = dict()
        for column in df.columns:
            value = row[column]
            question_info[column] = value
        all_questions_info.append(question_info)
    
    file2collection = dict()
    for questions_info in tqdm(all_questions_info):
        file_name = questions_info['文件名']
        if file_name not in file2collection:
            pdf_file = os.path.join(data_folder, file_name)
            response = client.files.create(
                file=open(pdf_file, "rb"),
                purpose="assistants"
            )
            file_id = response.id
            file2collection[file_name] = file_id
            questions_info['openai_assistant_file_id'] = file_id
        else:
            file_id = file2collection[file_name]
            questions_info['openai_assistant_file_id'] = file_id

    # save excel
    df = pd.DataFrame(all_questions_info)
    df.to_excel(save_excel_file, index=False)


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
        all_questions_info.append(question_info)
    
    file2assistant = dict()
    for questions_info in tqdm(all_questions_info):
        question = questions_info['问题']
        file_id = questions_info['openai_assistant_file_id']
        if file_id not in file2assistant:
            assistant = client.beta.assistants.create(
                name='文档问答系统',
                instructions="根据上传的文档，回答相关的问题.",
                model="gpt-4-1106-preview",
                tools=[{"type": "retrieval"}],
                file_ids=[file_id]
            )
            file2assistant[file_id] = assistant
        else:
            assistant = file2assistant[file_id]

        thread = client.beta.threads.create()
        while (thread.id in thread_ids):
            thread = client.beta.threads.create()
        thread_ids.add(thread.id)
        
        message = client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=question
        )
        run = client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=assistant.id,
        )
        run = client.beta.threads.runs.retrieve(
            thread_id=thread.id,
            run_id=run.id
        )
        while run.status != 'completed':
            run = client.beta.threads.runs.retrieve(
                thread_id=thread.id,
                run_id=run.id
            )
            print(run.status)
            time.sleep(1)
    
        # print(run)
        messages = client.beta.threads.messages.list(thread_id=thread.id)
        ans = messages.data[0].content[0].text.value
        questions_info['openai_assistant_answer'] = ans
        print('query:', question)
        print('pred:', ans)
        print('--------------------------------------')
    
    # save excel
    df = pd.DataFrame(all_questions_info)
    df.to_excel(excel_file, index=False)


if __name__ == '__main__':
    data_folder = '/home/public/rag_benchmark_v1.0/rag_benchmark_processed'
    excel_file = '../data/questions_info_with_answer_sample.xlsx'
    save_excel_file = '../data/questions_info_with_openai_assistant_file_id.xlsx'
    # upload_files(data_folder, excel_file, save_excel_file)
    question_answer(save_excel_file)