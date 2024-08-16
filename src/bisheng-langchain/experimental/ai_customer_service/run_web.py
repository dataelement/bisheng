import json
import os
import tempfile
from pathlib import Path
from typing import Optional, Tuple

import gradio as gr
import httpx
import pandas as pd
import yaml
from bisheng_langchain.chat_models import CustomLLMChat
from dotenv import load_dotenv
from langchain.chains import LLMChain
from langchain.chat_models import ChatOpenAI
from langchain.memory import ConversationBufferMemory
from langchain.prompts import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    MessagesPlaceholder,
    SystemMessagePromptTemplate,
)
from prompt import intent_clarify_prompt
from retrieval_v2 import LlmBasedLayerwiseReranker, VectorSearch
from sentence_transformers import SentenceTransformer, util
from utils import response_parse

load_dotenv('.env', override=True)


def prepare():
    config_file = './config.yaml'
    with open(config_file) as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    embedding = SentenceTransformer(
        model_name_or_path=config['vector_store']['embedding']['model_path'],
    )
    embedding.to(config['vector_store']['embedding']['device'])

    global RERANK_MODEL
    RERANK_MODEL = LlmBasedLayerwiseReranker(
        model_path=config['reranker']['model_path'],
        device=config['reranker']['device'],
    )

    doc_dir = config['data']['doc_dir']
    docs = []
    detail_docs = []
    for doc in Path(doc_dir).glob("*"):
        df = pd.read_excel(doc).dropna(subset=['文章标题']).drop_duplicates(subset=['文章标题'])
        titles = df['文章标题'].to_list()
        docs.extend(titles)
        detail_docs.extend(df.to_dict(orient='records'))

    global VECTOR_STORE
    VECTOR_STORE = VectorSearch(
        embedding_model=embedding,
        store_name=config['vector_store']['store_name'],
        docs=list(set(docs)),
        drop_old_cache=True,
        detail_docs=detail_docs,
    )


def initial_chain(assistant_message):
    travel_prompt = ChatPromptTemplate(
        messages=[
            SystemMessagePromptTemplate.from_template(assistant_message),
            MessagesPlaceholder(variable_name="chat_history"),
            HumanMessagePromptTemplate.from_template("{question}"),
        ]
    )

    # llm = ChatOpenAI(
    #     model="gpt-4-0125-preview",
    #     temperature=0.3,
    #     openai_api_key=os.environ.get('OPENAI_API_KEY', ''),
    #     http_client=httpx.Client(proxies=os.environ.get('OPENAI_PROXY', '')),
    # )
    # llm = ChatOpenAI(
    #     model='CM-57B',
    #     base_url='http://192.168.106.117:10005/generate',
    #     temperature=0.3,
    # )
    llm = CustomLLMChat(
        model='CM-57B',
        host_base_url='http://192.168.106.117:10005/generate',
        temperature=0.3,
        max_tokens=2048
    )
    memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
    global conversation
    conversation = LLMChain(llm=llm, prompt=travel_prompt, verbose=True, memory=memory)
    print(conversation.input_keys)
    return [
        (
            '正在初始化助手',
            '请详细描述您的问题，例如您想进行的操作是什么，遇到了什么问题，报错信息是什么？告诉我，我会为您解决: ',
        )
    ]


def clear_session(assistant_message):
    return initial_chain(assistant_message), []


def predict(command, history: Optional[Tuple[str, str]]):
    history = history or []
    if not history:
        print('Initial assistant')
        question_list = VECTOR_STORE.search(command, add_instruction=False, topk=5, threshold=0.6)
        print(f"用户意图的初次检索结果：{question_list}")
        conversation.prompt.messages[0].prompt.template = conversation.prompt.messages[0].prompt.template.replace(
            '<question_list>', ";\n".join([f"意图{i+1}: {q}" for i, q in enumerate(question_list)])
        )
    response = conversation({"question": command})['text']
    parse_result = response_parse(response)
    if parse_result:
        query = json.loads(parse_result)['消除歧义后的问题']
        embed_result = VECTOR_STORE.search(query, add_instruction=False, topk=10, threshold=0.7)
        if len(embed_result):
            print(f"最终embedding检索结果：{embed_result}")
            score, idx = RERANK_MODEL.rerank([[query, r] for r in embed_result])
            answer = list(filter(lambda x: x['文章标题'] == embed_result[idx], VECTOR_STORE.detail_docs))[0]['操作方法']
            print(f"最终答案：{embed_result[idx]}")
            print(f"最终答案：{answer}")
            parse_result = f'文章标题: {embed_result[idx]}\n\n 文章内容: {answer}'
        else:
            parse_result = f"没有找到相关信息"
        history.append((command, parse_result))

        return history, history, '', parse_result
    else:
        history.append((command, response))

    return history, history, '', ''


if __name__ == "__main__":
    title = """九天客服机器人"""
    prepare()

    with gr.Blocks() as demo:
        gr.Markdown(title)

        assistant_message = gr.Textbox(label='九天客服', value=intent_clarify_prompt, interactive=True, lines=2)

        with gr.Row():
            with gr.Column(scale=2):
                chatbot = gr.Chatbot()
                user_input = gr.Textbox(show_label=False, placeholder="Input...", container=False)
                with gr.Row():
                    initialBtn = gr.Button("🙂initial assistant")
                    submitBtn = gr.Button("🚀Submit", variant="primary")
                    emptyBtn = gr.Button("🧹Clear History")
            slot_show = gr.Textbox(label="检索结果", lines=20, interactive=False, scale=1)

        state = gr.State([])

        initialBtn.click(fn=initial_chain, inputs=[assistant_message], outputs=[chatbot])
        submitBtn.click(fn=predict, inputs=[user_input, state], outputs=[chatbot, state, user_input, slot_show])
        emptyBtn.click(fn=clear_session, inputs=[assistant_message], outputs=[chatbot, state])

    demo.queue().launch(share=False, inbrowser=True, server_name="0.0.0.0", server_port=8331)
