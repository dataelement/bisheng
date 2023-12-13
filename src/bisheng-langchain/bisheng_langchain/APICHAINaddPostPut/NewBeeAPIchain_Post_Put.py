"""
2023/12/8,说明：
此代码继承langchain的APIchain实现更高级的APIchain，能够实现get和post等http方法。
工作原理：见代码注释。
注意：必须搭配新的提示词模板template。
<此代码包含隐私内容，包括apikey等信息，供测试>
"""

import json
import os

from template import API_REQUEST_PROMPT, API_RESPONSE_PROMPT  # change this to the path you placed the templates
from langchain.chains import APIChain
from typing import Any, Dict, Optional
from langchain.prompts import BasePromptTemplate
from langchain.requests import TextRequestsWrapper
from langchain.chains.llm import LLMChain
from langchain.chat_models import ChatOpenAI
from langchain.callbacks.manager import CallbackManagerForChainRun
os.environ["OPENAI_API_KEY"] = "sk-XXX" #其中key和value均为string类型
# 测试用llm
llm = ChatOpenAI(model="gpt-4", temperature=0, openai_api_key=os.getenv("OPENAI_API_KEY"))


class NewBeeAPIChain(APIChain):
    def _call(self, inputs: Dict[str, any],
              run_manager: Optional[CallbackManagerForChainRun] = None,
              ) -> Dict[str, str]:
        Callback_Manager = run_manager or CallbackManagerForChainRun.get_noop_manager()
        question = inputs[self.question_key]

        # get api_url, request_method and body to call
        request_info = self.api_request_chain.predict(
            question=question,
            api_docs=self.api_docs
        )
        api_url, request_method, body = request_info.split('|')
        print(f'request info: {request_info}')

        # get the http method with same name, and call api for api response
        Callback_Manager.on_text(api_url, color="green", end="\n", verbose=self.verbose)
        request_func = getattr(self.requests_wrapper, request_method.lower())
        if request_method == "GET":
            api_response = request_func(api_url)
        else:
            api_response = request_func(api_url, json.loads(body))
        Callback_Manager.on_text(api_response, color="yellow", end="\n", verbose=self.verbose)

        print("api_response:", str(api_response))
        # get the answer to the original question using the API response
        answer = self.api_answer_chain.predict(
            question=question,
            api_docs=self.api_docs,
            api_url=api_url,
            api_response=api_response,
        )
        return {self.output_key: answer}

    @classmethod
    def from_llm_and_api_docs(
            cls,
            llm: llm,
            api_docs: str,
            headers: Optional[dict] = None,
            api_url_prompt: BasePromptTemplate = API_REQUEST_PROMPT,
            api_response_prompt: BasePromptTemplate = API_RESPONSE_PROMPT,
            **kwargs: Any,
    ) -> APIChain:
        """Load chain from just an LLM and the api docs."""
        get_request_chain = LLMChain(llm=llm, prompt=api_url_prompt)
        requests_wrapper = TextRequestsWrapper(headers=headers)
        get_answer_chain = LLMChain(llm=llm, prompt=api_response_prompt)
        return cls(
            api_request_chain=get_request_chain,
            api_answer_chain=get_answer_chain,
            requests_wrapper=requests_wrapper,
            limit_to_domains=None,
            api_docs=api_docs,
            **kwargs,
        )



if __name__ == "__main__":
    from JSon_Post_Put import *
    api_docs = str(tool1)+str(tool2)+str(tool3)
    headers = {"appKey":"XXX",
               "appSecret":"XXX"}
    # headers = {}
    chain = NewBeeAPIChain.from_llm_and_api_docs(llm=llm, headers=headers, api_docs=api_docs)
    # result = chain.run("创建任务DDY测试1，ID是8ef0da86ccd84ed99b78526006ec9bb3，立即执行一次。") #Post
    # result = chain.run("任务ID是24826366e3881eec2f74f3755cc1fc77的任务立即执行一次!") #put
    result = chain.run("任务ID是24826366e3881eec2f74f3755cc1fc77的任务立即删掉!") #Delete 也是通过Put实现的,实在智能RPA的PUT接口说明包括执行、停止、删除等操作
    # result = chain.run("查询蓝猫信息") #Get
    print(result)
