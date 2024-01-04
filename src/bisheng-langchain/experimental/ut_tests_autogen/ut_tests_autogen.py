import os
from langchain.prompts.chat import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
)
from langchain.chat_models.openai import ChatOpenAI
from langchain.chains import SequentialChain, LLMChain


def ut_tests_gen():
    system_template = """你是一名资深的测试工程师，对生成单元测试(UT Test)有着丰富的经验。为以下Python代码生成单元测试：
    """

    messages = [
        SystemMessagePromptTemplate.from_template(system_template),
        HumanMessagePromptTemplate.from_template("{question}"),
    ]

    CHAT_PROMPT = ChatPromptTemplate(messages=messages)
    llm = ChatOpenAI(temperature=0, model="gpt-4-1106-preview")


#     question = """
# ```Python
# def add(lst):
#     return sum([lst[i] for i in range(1, len(lst), 2) if lst[i]%2 == 0])
# ```
# """

    question = """
import functools
import logging
import json
from typing import Any, Awaitable, Callable, Dict, List, Optional

from langchain.callbacks.manager import (
    AsyncCallbackManagerForChainRun,
    CallbackManagerForChainRun,
)
from langchain.chains.base import Chain
from langchain.docstore.document import Document

logger = logging.getLogger(__name__)


class LoaderOutputChain(Chain):
    documents: List[Document]
    input_key: str = "begin"  #: :meta private:
    output_key: str = "text"  #: :meta private:

    @staticmethod
    @functools.lru_cache
    def _log_once(msg: str) -> None:
        logger.warning(msg)

    @property
    def input_keys(self) -> List[str]:
        return [self.input_key]

    @property
    def output_keys(self) -> List[str]:
        return [self.output_key]

    def _call(
        self,
        inputs: Dict[str, str],
        run_manager: Optional[CallbackManagerForChainRun] = None,
    ) -> Dict[str, str]:
        contents = [doc.page_content for doc in self.documents]
        contents = '\n\n'.join(contents)
        # contents = json.dumps(contents, indent=2, ensure_ascii=False)
        output = {self.output_key: contents}
        return output

    async def _acall(
        self,
        inputs: Dict[str, Any],
        run_manager: Optional[AsyncCallbackManagerForChainRun] = None,
    ) -> Dict[str, Any]:
        contents = [doc.page_content for doc in self.documents]
        contents = '\n\n'.join(contents)
        # contents = json.dumps(contents, indent=2, ensure_ascii=False)
        output = {self.output_key: contents}
        return output
"""

    prompt = CHAT_PROMPT.format_prompt(question=question)
    response = llm.predict_messages(prompt.to_messages())
    print(response.content)


def ui_test_gen():
    import httpx
    from openai import OpenAI
    client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY', ''),
                    http_client=httpx.Client(proxies=os.environ.get('OPENAI_PROXY', '')))
    response = client.chat.completions.create(
        model="gpt-4-vision-preview",
        messages=[
            {
                "role": "system",
                "content": """你是一名资深的测试工程师，对网页的UI测试有着丰富的经验。请根据提供的网页截图，给出相关的测试用例，输出格式参考如下：
<test_cases>
    <test_case
        explanation="Test the search input functionality"
        expectation="Should be able to type into the search input field">
        <action="input_text" target_type="text_field" target_text="" position="center"/>
    </test_case>

    <test_case
        explanation="Test the 'Google Search' button"
        expectation="Should initiate a search when clicked">
        <action="mouse_click" target_type="button" target_text="Google Search" position="below_search_field"/>
    </test_case>

    <test_case
        explanation="Test the language links"
        expectation="Should display more languages when clicked">
        <action="mouse_click" target_type="link" target_text="Google offered in:" position="bottom"/>
    </test_case>
</test_cases>
"""
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        # "text": "这张图片为毕昇软件的登录界面，为了完成测试登录功能，我需要你给出这个页面重要的网页元素。"
                        "text": "这张图片为毕昇软件的登录界面，为了完成测试登录功能，我需要你给出相关的ui test case。"
                    },
                    {
                        "type": "image_url",
                        "image_url": "https://s2.loli.net/2023/12/27/LDBOSEwv75PpHxT.png",
                    },
                ],
            }
        ],
        max_tokens=2048,
    )

    print(response.choices[0].message.content)


# ut_tests_gen()
ui_test_gen()