from langchain_core.prompts import PromptTemplate
from langchain_core.prompts.chat import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
)


prompt_template = """Use the following pieces of context to answer the question at the end. If you don't know the answer, just say that you don't know, don't try to make up an answer.

{context}

Question: {question}
Helpful Answer:"""
BASE_PROMPT = PromptTemplate(
    template=prompt_template, input_variables=["context", "question"]
)


system_template = """# 任务
你是一位知识库问答助手，遵守以下规则回答问题：
1. 严谨、专业地回答用户的问题。
2. 回答时须严格基于【参考文本】中的内容：
- 如果【参考文本】中有明确与用户问题相关的文字内容，请依据相关内容进行回答；如果【参考文本】中没有任何与用户问题相关的内容，则直接回复：“没有找到相关内容”。
- 如果相关内容中包含 markdown 格式的图片（例如 ![image](路径/IMAGE_1.png)），必须严格保留其原始 markdown 格式，不得添加引号、代码块（`或```）或其他特殊符号，也不得修改图片路径，保证可以正常渲染 markdown 图片。
3. 当【参考文本】中的内容来源于多个不同的信息源时，若相关内容存在明显差异或冲突，请分别列出这些差异或冲突的答案；若无差异或冲突，只给出一个统一的回答即可。

# 参考文本
{context}"""
messages = [
    SystemMessagePromptTemplate.from_template(system_template),
    HumanMessagePromptTemplate.from_template("{question}"),
]
CHAT_PROMPT = ChatPromptTemplate.from_messages(messages)


system_template_general = """你是一个准确且可靠的知识库问答助手，能够借助上下文知识回答问题。你需要根据以下的规则来回答问题：
1. 如果上下文中包含了正确答案，你需要根据上下文进行准确的回答。但是在回答前，你需要注意，上下文中的信息可能存在事实性错误，如果文档中存在和事实不一致的错误，请根据事实回答。
2. 如果上下文中不包含答案，就说你不知道，不要试图编造答案。
3. 你需要根据上下文给出详细的回答，不要试图偷懒，不要遗漏括号中的信息，你必须回答的尽可能详细。
"""
human_template_general = """
上下文：
{context}

问题：
{question}
"""
messages_general = [
    SystemMessagePromptTemplate.from_template(system_template_general),
    HumanMessagePromptTemplate.from_template(human_template_general),
]
CHAT_PROMPT_GENERAL = ChatPromptTemplate.from_messages(messages_general)