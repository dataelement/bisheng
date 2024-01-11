import os
import openai
import httpx
import time
import json
import shutil
from collections import defaultdict
from openai import OpenAI
thread_ids = set()

client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY', ''), 
                http_client=httpx.Client(proxies=os.environ.get('OPENAI_PROXY', '')))
assistant = client.beta.assistants.create(
    name='文档问答系统',
    instructions="根据上传的文档，回答相关的问题.",
    model="gpt-4-1106-preview",
    tools=[{"type": "retrieval"}],
    file_ids=['file-iBBdA0u0oSCjlzsxPmka0qMe']
)

res = defaultdict(list)
with open('/Users/gulixin/Downloads/question_v2.json', 'r') as f:
    ds = json.load(f)
    for d in ds:
        query = d['question'].strip()
        q_type = d['type']
        answer = d['answer'].strip()
        keyword = d['keyword'].strip()
        if q_type != "基于文档直接获取答案":
            continue

        thread = client.beta.threads.create()
        while (thread.id in thread_ids):
            thread = client.beta.threads.create()
        thread_ids.add(thread.id)
        
        message = client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=query
        )
        # print(message.id, question)
    
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
            # print(run.status)
            time.sleep(1)
    
        # print(run)
        messages = client.beta.threads.messages.list(thread_id=thread.id)
        ans = messages.data[0].content[0].text.value
        print(messages.data, len(messages.data))
       
        res[q_type].append({'question': str(query), 'answer': str(answer), 'pred': str(ans), 'keyword': str(keyword)})

        print('query:', query)
        print('pred:', ans)
        print('--------------------------------------')


def check_folder(folder):
    if not os.path.exists(folder):
        os.makedirs(folder)
    else:
        shutil.rmtree(folder)
        os.makedirs(folder)

folder = './openai_retrieval_assistant'
check_folder(folder)
for type in res:
    with open(os.path.join(folder, type + '.json'), 'w') as f:
        f.write(json.dumps(res[type], ensure_ascii=False, indent=2))