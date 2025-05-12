from typing import Any, Dict, Optional, List, Union
from uuid import UUID

from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.callback.event import OutputMsgData, StreamMsgData, StreamMsgOverData
from langchain_core.callbacks.base import AsyncCallbackHandler, BaseCallbackHandler
from langchain_core.outputs import LLMResult
from loguru import logger


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
            tool_list: Optional[List[Any]] = None,
            cancel_llm_end: bool = False,
    ):
        self.callback_manager = callback
        self.unique_id = unique_id
        self.node_id = node_id
        self.output = output
        self.output_len = 0
        self.output_key = output_key
        self.stream = stream
        self.tool_list = tool_list
        self.cancel_llm_end = cancel_llm_end
        self.reasoning_content = ''
        logger.info('on_llm_new_token {} outkey={}', self.output, self.output_key)

    async def on_tool_start(self, serialized: Dict[str, Any], input_str: str,
                            **kwargs: Any) -> Any:
        """Run when tool starts running."""
        logger.debug(
            f'on_tool_start  serialized={serialized} input_str={input_str} kwargs={kwargs}')
        if self.tool_list is not None:
            self.tool_list.append({
                'type': 'start',
                'run_id': kwargs.get('run_id').hex,
                'name': serialized['name'],
                'input': input_str,
            })
        if serialized['name'] == 'sql_agent':
            self.output = False

    async def on_tool_end(self, output: str, **kwargs: Any) -> Any:
        """Run when tool ends running."""
        logger.debug(f'on_tool_end  output={output} kwargs={kwargs}')
        result = output if isinstance(output, str) else getattr(output, 'content', output)
        if self.tool_list is not None:
            self.tool_list.append({
                'type': 'end',
                'run_id': kwargs.get('run_id').hex,
                'name': kwargs['name'],
                'output': result,
            })
        if kwargs['name'] == 'sql_agent':
            self.output = True

    async def on_tool_error(self, error: Union[Exception, KeyboardInterrupt],
                            **kwargs: Any) -> Any:
        """Run when tool errors."""
        logger.debug(f'on_tool_error error={error} kwargs={kwargs}')
        if self.tool_list is not None:
            self.tool_list.append({
                'type': 'error',
                'run_id': kwargs.get('run_id').hex,
                'error': str(error),
            })
        if kwargs['name'] == 'sql_agent':
            self.output = True

    def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        chunk = kwargs.get('chunk', None)
        # azure偶尔会返回一个None
        if token is None and chunk is None:
            return
        if not self.output or not self.stream:
            return

        self.output_len += len(token)  # 判断是否已经流输出完成
        self.callback_manager.on_stream_msg(
            StreamMsgData(node_id=self.node_id,
                          msg=token,
                          reasoning_content=getattr(chunk.message, 'additional_kwargs', {}).get('reasoning_content'),
                          unique_id=self.unique_id,
                          output_key=self.output_key))

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        self.reasoning_content = getattr(response.generations[0][0].message, 'additional_kwargs', {}).get('reasoning_content')
        if self.cancel_llm_end:
            return
        if not self.output:
            return
        msg = response.generations[0][0].message
        # ChatTongYi vl model special text
        if isinstance(msg.content, list):
            msg = ''.join([one.get('text', '') for one in msg.content])
        else:
            msg = msg.content
        if not msg:
            logger.warning('LLM output is empty')
            return

        if self.stream and self.output_len > 0:
            # 流式输出结束需要返回一个流式结束事件
            self.callback_manager.on_stream_over(StreamMsgOverData(node_id=self.node_id,
                                                                   msg=msg,
                                                                   reasoning_content=self.reasoning_content,
                                                                   unique_id=self.unique_id,
                                                                   output_key=self.output_key))
            return

        # 需要输出，但是没有执行流输出，则补一条。命中缓存的情况下会出现这种情况。需要输出的情况下也这样处理
        self.callback_manager.on_output_msg(
            OutputMsgData(node_id=self.node_id,
                          msg=msg,
                          unique_id=self.unique_id,
                          output_key=self.output_key))
