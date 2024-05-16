import httpx
from langchain.chat_models import ChatOpenAI
from bisheng_langchain.chat_models import ChatQWen
from langchain.chains import LLMChain
from langchain.prompts.chat import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)

system_template = """你是一个可靠标题生成或者提取助手。你会收到一篇文档的主要内容，请根据这些内容生成或者提取这篇文档的标题。"""
human_template = """
文档内容如下：
{context}

生成或提取的标题：
"""

messages = [
        SystemMessagePromptTemplate.from_template(system_template),
        HumanMessagePromptTemplate.from_template(human_template),
    ]
title_extract_prompt = ChatPromptTemplate.from_messages(messages)


def extract_title(llm, text, max_length=7000) -> str:
    chain = LLMChain(llm=llm, prompt=title_extract_prompt)
    ans = chain.run(context=text[:max_length])
    return ans 


if __name__ == '__main__':
    llm = ChatQWen(model_name='qwen1.5-72b-chat', 
                   api_key='', 
                   temperature=0.01)
    text = "江苏蔚蓝锂芯股份有限公司\n2021 年年度报告 \n2022 年 03 月\n\n 第一节 重要提示、目录和释义\n公司董事会、监事会及董事、监事、高级管理人员保证年度报告内容的真实、准确、完整，不存在虚假记载、误导性陈述或重大遗漏，并承担个别和连带的法律责任。\n公司负责人 CHEN KAI、主管会计工作负责人林文华及会计机构负责人(会计主管人员)张宗红声明：保证本年度报告中财务报告的真实、准确、完整。\n所有董事均已出席了审议本报告的董事会会议。"
    ans = extract_title(llm, text)
    print(ans)