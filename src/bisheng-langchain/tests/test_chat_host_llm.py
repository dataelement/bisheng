import asyncio
import os

from bisheng_langchain.chat_models import HostQwenChat
from langchain.schema import ChatGeneration
from langchain.schema.messages import AIMessage, HumanMessage, SystemMessage

RT_EP = os.environ.get('RT_EP')


def test_host_qwen_chat_simple():
    chat = HostQwenChat(
      model_name='Qwen-1_8B-Chat',
      ver=2,
      host_base_url=f'http://{RT_EP}/v2.1/models')
    # use generate api
    resp = chat.predict('写一个下雨的悬疑小说')
    print(resp)


async def test_host_qwen_chat_stream():
    chat = HostQwenChat(
      model_name='Qwen-1_8B-Chat',
      ver=2,
      host_base_url=f'http://{RT_EP}/v2.1/models',
      streaming=True)

    msgs = [[
      SystemMessage(content='你是一个作家'),
      HumanMessage(content='你可以做什么'),
      AIMessage(content='写一个下雨的悬疑小说')
    ]]

    response = await chat.agenerate(msgs)
    for generation in response.generations[0]:
        assert isinstance(generation, ChatGeneration)
        assert isinstance(generation.text, str)
        assert generation.text == generation.message.content
        print('generation text', generation.message.content)


asyncio.run(test_host_qwen_chat_stream())
# test_host_qwen_chat_simple()
