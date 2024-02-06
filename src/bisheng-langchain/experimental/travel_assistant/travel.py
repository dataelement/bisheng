import os
import httpx
import gradio as gr
import re
import json
from typing import Optional, Tuple
from langchain.chat_models import ChatOpenAI
from bisheng_langchain.chat_models import HostQwenChat
from bisheng_langchain.chat_models import ChatZhipuAI
from langchain.chains import LLMChain
from langchain.memory import ConversationBufferMemory
from prompt import system_template
from langchain.prompts import (
    ChatPromptTemplate,
    MessagesPlaceholder,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)

openai_api_key = os.environ.get('OPENAI_API_KEY', '')
openai_proxy = os.environ.get('OPENAI_PROXY', '')


def initial_chain(assistant_message, host_url):
    travel_prompt = ChatPromptTemplate(
        messages=[
            SystemMessagePromptTemplate.from_template(assistant_message),
            MessagesPlaceholder(variable_name="chat_history"),
            HumanMessagePromptTemplate.from_template("{question}")
        ]
    )

    llm = ChatOpenAI(model="gpt-4-0125-preview", 
                    temperature=0.0,
                    openai_api_key=openai_api_key,
                    http_client=httpx.Client(proxies=openai_proxy))
    # llm = HostQwenChat(
    #     model_name='Qwen-14B-Chat',
    #     host_base_url=host_url,
    #     request_timeout=1000,
    # )
    # llm = ChatZhipuAI(
    #     model_name='glm-4',
    #     zhipuai_api_key='a57f9268b15a331b857ec5a73765f948.57xj0ahR3cBv5DLe',
    #     request_timeout=1000,
    # )
    # Notice that we `return_messages=True` to fit into the MessagesPlaceholder
    # Notice that `"chat_history"` aligns with the MessagesPlaceholder name.
    memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
    global conversation
    conversation = LLMChain(llm=llm, prompt=travel_prompt, verbose=True, memory=memory)
    return [('正在初始化助手', '初始化助手成功请开始对话')]


def clear_session(assistant_message, host_url):
    initial_chain(assistant_message, host_url)
    return [], []


def response_parse(json_string: str) -> str:
    print(f'llm response before parse: {json_string}')
    match = re.search(r"```(json)?(.*)```", json_string, re.DOTALL)
    if match is None:
        json_str = ''
    else:
        json_str = match.group(2)

    json_str = json_str.strip()
    json_str = json_str.replace('```', '')

    match = re.search(r"{.*}", json_str, re.DOTALL)
    if match is None:
        json_str = json_str
    else:
        json_str = match.group(0)

    if json_str.endswith('}\n}'):
        json_str = json_str[:-2]
    if json_str.startswith('{\n{'):
        json_str = json_str.replace('{\n{', '{', 1)

    print(f'llm response after parse: {json_str}')
    # 清掉历史memory
    if json_str:
        try:    
            res = json.loads(json_str)
        except:
            res = {}
        if res:
            print('finnal information:', res)
            conversation.memory.clear()
    return json_str


def predict(command, history: Optional[Tuple[str, str]]):
    history = history or []
    response = conversation({"question": command})['text']
    history.append((command, response))
    return history, history, '', response_parse(response)


if __name__ == "__main__":
    title = """差旅智能体输入解析多轮引导"""
    with gr.Blocks() as demo:
        gr.Markdown(title)

        assistant_message = gr.Textbox(label='自定义你的专属差旅助手', value=system_template, interactive=True, lines=2)
        model_url = gr.Textbox(label='模型服务地址', value='http://34.142.140.180:7001/v2.1/models', interactive=True, lines=2)

        with gr.Row():
            with gr.Column(scale=2):
                chatbot = gr.Chatbot()
                user_input = gr.Textbox(show_label=False, placeholder="Input...", container=False)
                with gr.Row():
                    initialBtn = gr.Button("🙂initial assistant")
                    submitBtn = gr.Button("🚀Submit", variant="primary")
                    emptyBtn = gr.Button("🧹Clear History")
            slot_show = gr.Textbox(label="最终用户提交信息", lines=20, interactive=False, scale=1)

        state = gr.State([])

        initialBtn.click(fn=initial_chain, inputs=[assistant_message, model_url], outputs=[chatbot])
        submitBtn.click(fn=predict, inputs=[user_input, state], outputs=[chatbot, state, user_input, slot_show])
        emptyBtn.click(fn=clear_session, inputs=[assistant_message, model_url], outputs=[chatbot, state])

    demo.queue().launch(share=False, inbrowser=True, server_name="0.0.0.0", server_port=8000)