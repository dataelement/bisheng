import os

from bisheng_langchain.chat_models import ChatXunfeiAI


def test_chat_spark_v1():
    xunfeiai_appid = os.environ['xunfeiai_appid']
    xunfeiai_api_key = os.environ['xunfeiai_api_key']
    xunfeiai_api_secret = os.environ['xunfeiai_api_secret']
    chat = ChatXunfeiAI(
      model='spark-v1.5',
      xunfeiai_appid=xunfeiai_appid,
      xunfeiai_api_key=xunfeiai_api_key,
      xunfeiai_api_secret=xunfeiai_api_secret)

    resp = chat.predict('你好')
    print(resp)


def test_chat_spark_v2():
    xunfeiai_appid = os.environ['xunfeiai_appid']
    xunfeiai_api_key = os.environ['xunfeiai_api_key']
    xunfeiai_api_secret = os.environ['xunfeiai_api_secret']
    chat = ChatXunfeiAI(
      model='spark-v2.0',
      xunfeiai_appid=xunfeiai_appid,
      xunfeiai_api_key=xunfeiai_api_key,
      xunfeiai_api_secret=xunfeiai_api_secret)

    resp = chat.predict('你好')
    print(resp)


test_chat_spark_v1()
test_chat_spark_v2()
