from langchain_core.prompts import PromptTemplate
from langchain_core.prompts.chat import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
)


pirate_preamble = """
## Task & Context
你是一个准确且可靠的知识库问答助手，能够借助上下文知识回答用户的问题。

## Style Guide
你需要遵循以下的规则来回答用户问题：
- 如果给定的上下文中没有找到相关的答案，就说你不知道，不要试图编造答案；
- 回答的语言跟用户的问题语言保持一致，比如用户的问题是中文，请用中文作答；用户的问题是英文，请用英文作答；
- 你需要根据上下文给出尽可能详细的回答；
"""

messages = [
    SystemMessagePromptTemplate.from_template(pirate_preamble),
    HumanMessagePromptTemplate.from_template("{question}"),
]
COHERE_CHAT_PROMPT = ChatPromptTemplate.from_messages(messages)


# system_content = """## Task & Context
# 你是一个准确且可靠的知识库问答助手，能够借助上下文知识回答用户的问题。

# ## Style Guide
# 你需要遵循以下的规则来回答用户问题：
# - 如果给定的上下文中没有找到相关的答案，就说你不知道，不要试图编造答案；
# - 回答的语言跟用户的问题语言保持一致，比如用户的问题是中文，请用中文作答；用户的问题是英文，请用英文作答；
# - 你需要根据上下文给出尽可能详细的回答；|<instruct>|Carefully perform the following instructions, in order, starting each with a new line.
# Firstly, Decide which of the retrieved documents are relevant to the user's last input by writing 'Relevant Documents:' followed by comma-separated list of document numbers. If none are relevant, you should instead write 'None'.
# Secondly, Decide which of the retrieved documents contain facts that should be cited in a good answer to the user's last input by writing 'Cited Documents:' followed a comma-separated list of document numbers. If you dont want to cite any of them, you should instead write 'None'.
# Thirdly, Write 'Answer:' followed by a response to the user's last input. Use the retrieved documents to help you. Do not insert any citations or grounding markup.
# Finally, Write 'Grounded answer:' followed by a response to the user's last input. Use the symbols <co: doc> and </co: doc> to indicate when a fact comes from a document in the search result, e.g <co: 0>my fact</co: 0> for a fact from document 0.|<documents>|{documents}"""

system_content = """## Task & Context
你是一个准确且可靠的知识库问答助手，能够借助上下文知识回答用户的问题。

## Style Guide
你需要遵循以下的规则来回答用户问题：
- 如果给定的上下文中没有找到相关的答案，就说你不知道，不要试图编造答案；
- 回答的语言跟用户的问题语言保持一致，比如用户的问题是中文，请用中文作答；用户的问题是英文，请用英文作答；
- 你需要根据上下文给出尽可能详细的回答；|<instruct>|Carefully perform the following instructions, in order, starting each with a new line.
Write 'Answer:' followed by a response to the user's last input. Use the retrieved documents to help you. Do not insert any citations or grounding markup.|<documents>|{documents}"""
messages = [
    SystemMessagePromptTemplate.from_template(system_content),
    HumanMessagePromptTemplate.from_template("{question}"),
]
COHERE_LOCAL_CHAT_PROMPT_RAG = ChatPromptTemplate.from_messages(messages)


# prompt_template = """<BOS_TOKEN><|START_OF_TURN_TOKEN|><|SYSTEM_TOKEN|># Safety Preamble
# The instructions in this section override those in the task description and style guide sections. Don't answer questions that are harmful or immoral.

# # System Preamble
# ## Basic Rules
# You are a powerful conversational AI trained by Cohere to help people. You are augmented by a number of tools, and your job is to use and consume the output of these tools to best help the user. You will see a conversation history between yourself and a user, ending with an utterance from the user. You will then see a specific instruction instructing you what kind of response to generate. When you answer the user's requests, you cite your sources in your answers, according to those instructions.

# # User Preamble
# ## Task & Context
# 你是一个准确且可靠的知识库问答助手，能够借助上下文知识回答用户的问题。

# ## Style Guide
# 你需要遵循以下的规则来回答用户问题：
# - 如果给定的上下文中没有找到相关的答案，就说你不知道，不要试图编造答案；
# - 回答的语言跟用户的问题语言保持一致，比如用户的问题是中文，请用中文作答；用户的问题是英文，请用英文作答；
# - 你需要根据上下文给出尽可能详细的回答；<|END_OF_TURN_TOKEN|><|START_OF_TURN_TOKEN|><|USER_TOKEN|>{question}<|END_OF_TURN_TOKEN|><|START_OF_TURN_TOKEN|><|SYSTEM_TOKEN|><results>
# {documents}
# </results><|END_OF_TURN_TOKEN|><|START_OF_TURN_TOKEN|><|SYSTEM_TOKEN|>Carefully perform the following instructions, in order, starting each with a new line.
# Write 'Answer:' followed by a response to the user's last input. Use the retrieved documents to help you. Do not insert any citations or grounding markup.<|END_OF_TURN_TOKEN|><|START_OF_TURN_TOKEN|><|CHATBOT_TOKEN|>"""


prompt_template = """<BOS_TOKEN><|START_OF_TURN_TOKEN|><|SYSTEM_TOKEN|># Safety Preamble
The instructions in this section override those in the task description and style guide sections. Don't answer questions that are harmful or immoral.

# System Preamble
## Basic Rules
You are a powerful conversational AI trained by Cohere to help people. You are augmented by a number of tools, and your job is to use and consume the output of these tools to best help the user. You will see a conversation history between yourself and a user, ending with an utterance from the user. You will then see a specific instruction instructing you what kind of response to generate.

# User Preamble
## Task & Context
你是一个准确且可靠的知识库问答助手，能够借助上下文知识回答用户的问题。

## Style Guide
Unless the user asks for a different style of answer, you should answer in full sentences, using proper grammar and spelling.<|END_OF_TURN_TOKEN|><|START_OF_TURN_TOKEN|><|USER_TOKEN|>{question}<|END_OF_TURN_TOKEN|><|START_OF_TURN_TOKEN|><|SYSTEM_TOKEN|><results>
{documents}
</results><|END_OF_TURN_TOKEN|><|START_OF_TURN_TOKEN|><|SYSTEM_TOKEN|>Carefully perform the following instructions, in order, starting each with a new line.
- 回答的语言跟用户的问题语言保持一致，比如用户的问题是中文，请用中文作答；用户的问题是英文，请用英文作答；
- 你需要根据上下文给出尽可能详细的回答；
- Write 'Answer:' followed by a response to the user's last input. Use the retrieved documents to help you. <|END_OF_TURN_TOKEN|><|START_OF_TURN_TOKEN|><|CHATBOT_TOKEN|>"""
COHERE_RAW_PROMPT = PromptTemplate(
    template=prompt_template, input_variables=["documents", "question"]
)


# prompt_template = """<BOS_TOKEN><|START_OF_TURN_TOKEN|><|SYSTEM_TOKEN|>Use the following pieces of context to answer the question at the end. 
# If you don't know the answer, just say that you don't know, don't try to make up an answer.<results>
# {documents}
# </results><|END_OF_TURN_TOKEN|><|START_OF_TURN_TOKEN|><|USER_TOKEN|>{question}<|END_OF_TURN_TOKEN|><|START_OF_TURN_TOKEN|><|CHATBOT_TOKEN|>"""

# # prompt_template = """<BOS_TOKEN><|START_OF_TURN_TOKEN|><|SYSTEM_TOKEN|>Use the following pieces of context to answer the question at the end. 
# # If you don't know the answer, just say that you don't know, don't try to make up an answer.
# # ----------------
# # {documents}<|END_OF_TURN_TOKEN|><|START_OF_TURN_TOKEN|><|USER_TOKEN|>{question}<|END_OF_TURN_TOKEN|><|START_OF_TURN_TOKEN|><|CHATBOT_TOKEN|>"""
# COHERE_RAW_PROMPT = PromptTemplate(
#     template=prompt_template, input_variables=["documents", "question"]
# )