import asyncio
import os

from bisheng_langchain.chat_models import CustomLLMChat, HostBaichuanChat, HostQwenChat
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


async def test_host_baichuan2_chat_stream():
    chat = HostBaichuanChat(
      model_name='Baichuan2-13B-Chat',
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


def test_host_baichuan_chat_simple():
    # chat = HostBaichuanChat(
    #   model_name='Baichuan-13B-Chat',
    #   ver=1,
    #   host_base_url=f'http://{RT_EP}/v2.1/models')
    # # use generate api
    # resp = chat.predict('写一个下雨的悬疑小说')
    # print(resp)

    chat = HostBaichuanChat(
      model_name='Baichuan2-13B-Chat',
      host_base_url=f'http://{RT_EP}/v2.1/models',
      verbose=True)
    # use generate api
    resp = chat.predict('写一个下雨的悬疑小说')
    print(resp)


def test_custom_host_chat():
    chat = CustomLLMChat(
      model_name='custom-llm-chat',
      host_base_url=f'http://{RT_EP}/v2.1/models/Baichuan2-13B-Chat/generate',
      verbose=True)
    # use generate api
    resp = chat.predict('写一个下雨的悬疑小说')
    print(resp)


def test_custom_host_chat_timeout():
    try:
        chat = CustomLLMChat(
          model_name='custom-llm-chat',
          host_base_url=f'http://{RT_EP}/v2.1/models/Baichuan2-13B-Chat/generate',
          request_timeout=10,
          verbose=True)
        # use generate api
        resp = chat.predict('写一个下雨的悬疑小说')
        print(resp)
    except Exception as e:
        assert 'timeout' in str(e)


async def test_host_baichuan2_chat_stream_timeout():
    try:
        chat = HostBaichuanChat(
          model_name='Baichuan2-13B-Chat',
          host_base_url=f'http://{RT_EP}/v2.1/models',
          streaming=True,
          request_timeout=10)

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

    except Exception as e:
        assert 'timeout' in str(e)


def test_host_baichuan_chat_timeout():
    try:
        chat = HostBaichuanChat(
          model_name='Baichuan2-13B-Chat',
          host_base_url=f'http://{RT_EP}/v2.1/models',
          verbose=True,
          request_timeout=5)
        resp = chat.predict('写一个下雨的悬疑小说')
        print(resp)
    except Exception as e:
        assert 'timeout' in str(e)


asyncio.run(test_host_baichuan2_chat_stream_timeout())
# asyncio.run(test_host_baichuan2_chat_stream())
# asyncio.run(test_host_qwen_chat_stream())
# test_host_qwen_chat_simple()
test_host_baichuan_chat_simple()
# test_custom_host_chat()
# test_custom_host_chat_timeout()
# test_host_baichuan_chat_timeout()
