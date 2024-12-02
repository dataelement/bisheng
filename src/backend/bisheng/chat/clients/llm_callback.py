from typing import Any

from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.callback.event import OutputMsgData, StreamMsgData, StreamMsgOverData
from langchain_core.callbacks.base import AsyncCallbackHandler, BaseCallbackHandler
from langchain_core.outputs import LLMResult
from loguru import logger


class LLMNodeAsyncCallbackHandler(AsyncCallbackHandler):
    """Callback handler for streaming LLM responses."""

    def __init__(self, callback: BaseCallback, unique_id: str, node_id: str):
        self.callback_manager = callback
        self.unique_id = unique_id
        self.node_id = node_id

    async def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        logger.debug(f'on_llm_new_token token={token} kwargs={kwargs}')
        # azure偶尔会返回一个None
        if token is None:
            return

        # 将流式输出内容放入到队列内，以方便中断流式输出后，可以将内容记录到数据库
        self.callback_manager.on_stream_msg(
            StreamMsgData(
                node_id=self.node_id,
                msg=token,
                unique_id=self.unique_id,
            ))


class LLMNodeCallbackHandler(BaseCallbackHandler):
    """Callback handler for streaming LLM responses."""

    def __init__(
            self,
            callback: BaseCallback,
            unique_id: str,
            node_id: str,
            output: bool,
            output_key: str,
            stream: bool = True,
    ):
        self.callback_manager = callback
        self.unique_id = unique_id
        self.node_id = node_id
        self.output = output
        self.output_len = 0
        self.output_key = output_key
        self.stream = stream
        logger.info('on_llm_new_token {} outkey={}', self.output, self.output_key)

    def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        # azure偶尔会返回一个None
        if token is None:
            return
        if not self.output or not self.stream:
            return

        self.output_len += len(token)  # 判断是否已经流输出完成
        self.callback_manager.on_stream_msg(
            StreamMsgData(node_id=self.node_id,
                          msg=token,
                          unique_id=self.unique_id,
                          output_key=self.output_key))

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        if not self.output:
            return
        msg = response.generations[0][0].text
        if not msg:
            logger.warning('LLM output is empty')
            return

        if self.stream and self.output_len > 0:
            # 流式输出结束需要返回一个流式结束事件
            self.callback_manager.on_stream_over(StreamMsgOverData(node_id=self.node_id,
                                                                   msg=msg,
                                                                   unique_id=self.unique_id,
                                                                   output_key=self.output_key))
            return

        # 需要输出，但是没有执行流输出，则补一条。命中缓存的情况下会出现这种情况。需要输出的情况下也这样处理
        self.callback_manager.on_output_msg(
            OutputMsgData(node_id=self.node_id,
                          msg=msg,
                          unique_id=self.unique_id,
                          output_key=self.output_key))


class LLMRagNodeCallbackHandler(LLMNodeCallbackHandler):
    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        pass
