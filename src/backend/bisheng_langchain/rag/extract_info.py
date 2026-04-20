from bisheng_langchain.chat_models import ChatQWen
from langchain.chains.llm import LLMChain
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

abstract_system_template = """# role
你是一名经验丰富的“文档摘要专家”，擅长针对不同类型的文档（例如：书籍、论文、标书、研究报告、规章制度、合同协议、会议纪要、产品手册、运维手册、需求说明书等）进行精准识别，并根据文档类型灵活调整摘要风格，例如：
- 报告类文档需强调研究发现或核心观点；
- 制度类文档需突出制度目的及适用范围；
- 合同类文档需明确合同主体及关键条款；
- 会议纪要需聚焦会议议题与决策结果；
- 产品说明需提炼产品功能与使用场景。

# task
接下来你将收到一篇文档的主要内容，请你：
1. 判断并简要说明该文档属于上述哪种类型；
2. 使用2～3句话概括文档的核心内容和关键结论，强调信息的准确性、完整性与清晰度。

# result example
【文档类型】：会议纪要
【摘要】：本文档为公司季度业务会议纪要，会议围绕本季度销售目标的达成情况展开，最终决定下一季度加强市场推广投入，并设立专门团队负责新产品上市工作，以改善销售表现。"""
abstract_human_template = """
文档内容如下：
{context}

文档摘要：
"""

messages = [
    SystemMessagePromptTemplate.from_template(system_template),
    HumanMessagePromptTemplate.from_template(human_template),
]
title_extract_prompt = ChatPromptTemplate.from_messages(messages)

abstract_messages = [
    SystemMessagePromptTemplate.from_template(abstract_system_template),
    HumanMessagePromptTemplate.from_template(abstract_human_template),
]
abstract_extract_prompt = ChatPromptTemplate.from_messages(abstract_messages)


def _build_prompt_chain(
        llm,
        *,
        default_prompt: ChatPromptTemplate,
        system_prompt: str | None = None,
        human_prompt: str | None = None,
):
    if system_prompt or human_prompt:
        prompt_messages = [
            SystemMessagePromptTemplate.from_template(
                system_prompt or default_prompt.messages[0].prompt.template
            ),
            HumanMessagePromptTemplate.from_template(
                human_prompt or default_prompt.messages[1].prompt.template
            ),
        ]
        prompt = ChatPromptTemplate.from_messages(prompt_messages)
    else:
        prompt = default_prompt
    return LLMChain(llm=llm, prompt=prompt)


def extract_title(llm, text, max_length=7000, abstract_prompt: str = None) -> str:
    """
    此方法在bisheng_langchain模型的还有两处调用用，在不能提供abstract_propmpt的情况下
    使用原来现有提示词.
    """
    chain = _build_prompt_chain(
        llm,
        default_prompt=title_extract_prompt,
        system_prompt=abstract_prompt,
        human_prompt=human_template,
    )
    ans = chain.run(context=text[:max_length])
    return ans


def extract_abstract(llm, text, max_length=7000, abstract_prompt: str = None) -> str:
    """Extract a document abstract with an abstract-specific fallback prompt."""
    chain = _build_prompt_chain(
        llm,
        default_prompt=abstract_extract_prompt,
        system_prompt=abstract_prompt or abstract_system_template,
        human_prompt=abstract_human_template,
    )
    ans = chain.run(context=text[:max_length])
    return ans


async def async_extract_title(llm, text, max_length=7000, abstract_prompt: str = None) -> str:
    """
    此方法在bisheng_langchain模型的还有两处调用用，在不能提供abstract_propmpt的情况下
    使用原来现有提示词.
    """
    chain = _build_prompt_chain(
        llm,
        default_prompt=title_extract_prompt,
        system_prompt=abstract_prompt,
        human_prompt=human_template,
    )
    ans = await chain.arun(context=text[:max_length])
    return ans


async def async_extract_abstract(llm, text, max_length=7000, abstract_prompt: str = None) -> str:
    """Async variant of `extract_abstract`."""
    chain = _build_prompt_chain(
        llm,
        default_prompt=abstract_extract_prompt,
        system_prompt=abstract_prompt or abstract_system_template,
        human_prompt=abstract_human_template,
    )
    ans = await chain.arun(context=text[:max_length])
    return ans


if __name__ == "__main__":
    llm = ChatQWen(model_name="qwen1.5-72b-chat", api_key="", temperature=0.01)
    text = "江苏蔚蓝锂芯股份有限公司\n2021 年年度报告 \n2022 年 03 月\n\n 第一节 重要提示、目录和释义\n公司董事会、监事会及董事、监事、高级管理人员保证年度报告内容的真实、准确、完整，不存在虚假记载、误导性陈述或重大遗漏，并承担个别和连带的法律责任。\n公司负责人 CHEN KAI、主管会计工作负责人林文华及会计机构负责人(会计主管人员)张宗红声明：保证本年度报告中财务报告的真实、准确、完整。\n所有董事均已出席了审议本报告的董事会会议。"
    ans = extract_title(llm, text)
    print(ans)
