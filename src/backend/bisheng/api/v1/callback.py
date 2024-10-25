import asyncio
import copy
import json
from queue import Queue
from typing import Any, Dict, List, Union

from bisheng.api.v1.schemas import ChatResponse
from bisheng.database.models.message import ChatMessage as ChatMessageModel
from bisheng.database.models.message import ChatMessageDao
from bisheng.utils.logger import logger
from fastapi import WebSocket
from langchain.callbacks.base import AsyncCallbackHandler, BaseCallbackHandler
from langchain.schema import AgentFinish, LLMResult
from langchain.schema.agent import AgentAction
from langchain.schema.document import Document
from langchain.schema.messages import BaseMessage


# https://github.com/hwchase17/chat-langchain/blob/master/callback.py
class AsyncStreamingLLMCallbackHandler(AsyncCallbackHandler):
    """Callback handler for streaming LLM responses."""

    def __init__(self,
                 websocket: WebSocket,
                 flow_id: str,
                 chat_id: str,
                 user_id: int = None,
                 **kwargs: Any):
        self.websocket = websocket
        self.flow_id = flow_id
        self.chat_id = chat_id
        self.user_id = user_id

        # 工具调用的缓存，在tool_end时将开始和结束拼接到一起存储到数据库
        self.tool_cache = {}
        # self.tool_cache = {
        #     'run_id': {
        #         'input': {},
        #         'category': "",
        #     },  # 存储工具调用的input信息
        # }

        # 流式输出的队列
        self.stream_queue: Queue = kwargs.get('stream_queue')

    async def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        logger.debug(f'on_llm_new_token token={token} kwargs={kwargs}')
        # azure偶尔会返回一个None
        if token is None:
            return
        resp = ChatResponse(message=token,
                            type='stream',
                            flow_id=self.flow_id,
                            chat_id=self.chat_id)
        # 将流式输出内容放入到队列内，以方便中断流式输出后，可以将内容记录到数据库
        await self.websocket.send_json(resp.dict())
        if self.stream_queue:
            self.stream_queue.put(token)

    async def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str],
                           **kwargs: Any) -> Any:
        """Run when LLM starts running."""
        logger.debug(f'llm_start prompts={prompts}')

    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> Any:
        """Run when LLM ends running."""
        logger.debug(f'llm_end response={response}')

    async def on_llm_error(self, error: Union[Exception, KeyboardInterrupt], **kwargs: Any) -> Any:
        """Run when LLM errors."""
        logger.debug(f'on_llm_error error={error} kwargs={kwargs}')

    async def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any],
                             **kwargs: Any) -> Any:
        """Run when chain starts running."""
        logger.debug(f'on_chain_start inputs={inputs} kwargs={kwargs}')
        logger.info('k=s act=on_chain_start flow_id={} input_dict={}', self.flow_id, inputs)

    async def on_chain_end(self, outputs: Dict[str, Any], **kwargs: Any) -> Any:
        """Run when chain ends running."""
        logger.debug(f'on_chain_end outputs={outputs} kwargs={kwargs}')
        tmp_output = copy.deepcopy(outputs)
        if isinstance(tmp_output, dict):
            tmp_output.pop('source_documents', '')
        logger.info('k=s act=on_chain_end flow_id={} output_dict={}', self.flow_id, tmp_output)

    async def on_chain_error(self, error: Union[Exception, KeyboardInterrupt],
                             **kwargs: Any) -> Any:
        """Run when chain errors."""
        logger.debug(f'on_chain_error error={error} kwargs={kwargs}')

    async def on_tool_start(self, serialized: Dict[str, Any], input_str: str,
                            **kwargs: Any) -> Any:
        """Run when tool starts running."""
        logger.debug(
            f'on_tool_start  serialized={serialized} input_str={input_str} kwargs={kwargs}')
        logger.info('k=s act=on_tool_start flow_id={} tool_name={} input_str={}', self.flow_id,
                    serialized.get('name'), input_str)

        resp = ChatResponse(type='stream',
                            intermediate_steps=f'Tool input: {input_str}',
                            flow_id=self.flow_id,
                            chat_id=self.chat_id)
        await self.websocket.send_json(resp.dict())

    async def on_tool_end(self, output: str, **kwargs: Any) -> Any:
        """Run when tool ends running."""
        logger.debug(f'on_tool_end  output={output} kwargs={kwargs}')
        logger.info("k=s act=on_tool_end flow_id={} output='{}'", self.flow_id, output)
        observation_prefix = kwargs.get('observation_prefix', 'Tool output: ')
        # from langchain.docstore.document import Document # noqa
        # result = eval(output).get('result')
        result = output

        # Create a formatted message.
        intermediate_steps = f'{observation_prefix}{result[:100]}'

        # Create a ChatResponse instance.
        resp = ChatResponse(type='stream',
                            intermediate_steps=intermediate_steps,
                            flow_id=self.flow_id,
                            chat_id=self.chat_id)

        try:
            # This is to emulate the stream of tokens
            await self.websocket.send_json(resp.dict())
        except Exception as e:
            logger.error(e)

    async def on_tool_error(self, error: Union[Exception, KeyboardInterrupt],
                            **kwargs: Any) -> Any:
        """Run when tool errors."""
        logger.debug(f'on_tool_error error={error} kwargs={kwargs}')

    async def on_text(self, text: str, **kwargs: Any) -> Any:
        """Run on arbitrary text."""
        # This runs when first sending the prompt
        # to the LLM, adding it will send the final prompt
        # to the frontend
        logger.debug(f'on_text text={text} kwargs={kwargs}')
        if 'Prompt after formatting:' in text:
            prompt_str = text[24:]
            logger.info(
                "k=s act=on_text prompt='{}'",
                prompt_str,
            )
        sender = kwargs.get('sender')
        receiver = kwargs.get('receiver')
        if kwargs.get('sender'):
            log = ChatResponse(message=text,
                               type='end',
                               sender=sender,
                               receiver=receiver,
                               flow_id=self.flow_id,
                               chat_id=self.chat_id)
            start = ChatResponse(type='start',
                                 sender=sender,
                                 receiver=receiver,
                                 flow_id=self.flow_id,
                                 chat_id=self.chat_id)

            if receiver and receiver.get('is_self'):
                await self.websocket.send_json(log.dict())
            else:
                await self.websocket.send_json(log.dict())
                await self.websocket.send_json(start.dict())
        elif 'category' in kwargs:
            if 'autogen' == kwargs['category']:
                log = ChatResponse(message=text,
                                   type='stream',
                                   flow_id=self.flow_id,
                                   chat_id=self.chat_id)
                await self.websocket.send_json(log.dict())
                if kwargs.get('type'):
                    # 兼容下
                    start = ChatResponse(type='start',
                                         category=kwargs.get('type'),
                                         flow_id=self.flow_id,
                                         chat_id=self.chat_id)
                    end = ChatResponse(type='end',
                                       intermediate_steps=text,
                                       category=kwargs.get('type'),
                                       flow_id=self.flow_id,
                                       chat_id=self.chat_id)
                    await self.websocket.send_json(start.dict())
                    await self.websocket.send_json(end.dict())
            else:
                log = ChatResponse(message=text,
                                   intermediate_steps=kwargs['log'],
                                   type=kwargs['type'],
                                   category=kwargs['category'],
                                   flow_id=self.flow_id,
                                   chat_id=self.chat_id)
                await self.websocket.send_json(log.dict())

    async def on_agent_action(self, action: AgentAction, **kwargs: Any):
        logger.debug(f'on_agent_action action={action} kwargs={kwargs}')
        logger.info('k=s act=on_agent_action {}', action)
        log = f'\nThought: {action.log}'
        # if there are line breaks, split them and send them
        # as separate messages
        log = log.replace('\n', '\n\n')
        resp = ChatResponse(type='stream',
                            intermediate_steps=log,
                            flow_id=self.flow_id,
                            chat_id=self.chat_id)
        await self.websocket.send_json(resp.dict())

    async def on_agent_finish(self, finish: AgentFinish, **kwargs: Any) -> Any:
        """Run on agent end."""
        logger.debug(f'on_agent_finish finish={finish} kwargs={kwargs}')
        logger.info('k=s act=on_agent_finish {}', finish)
        resp = ChatResponse(flow_id=self.flow_id,
                            chat_id=self.chat_id,
                            type='stream',
                            intermediate_steps=finish.log)
        await self.websocket.send_json(resp.dict())

    async def on_retriever_start(self, serialized: Dict[str, Any], query: str,
                                 **kwargs: Any) -> Any:
        """Run when retriever start running."""
        logger.debug(f'on_retriever_start serialized={serialized} query={query} kwargs={kwargs}')
        logger.info('k=s act=on_retriever_start flow_id={} query={} meta={}', self.flow_id, query,
                    serialized.get('repr'))

    async def on_retriever_end(self, result: List[Document], **kwargs: Any) -> Any:
        """Run when retriever end running."""
        # todo 判断技能权限
        logger.debug(f'on_retriever_end result={result} kwargs={kwargs}')
        if result:
            tmp_result = copy.deepcopy(result)
            [doc.metadata.pop('bbox', '') for doc in tmp_result]
            logger.info('k=s act=on_retriever_end flow_id={} result_without_bbox={}', self.flow_id,
                        tmp_result)

    async def on_chat_model_start(self, serialized: Dict[str, Any],
                                  messages: List[List[BaseMessage]], **kwargs: Any) -> Any:
        # """Run when retriever end running."""
        # content = messages[0][0] if isinstance(messages[0][0], str) else messages[0][0].get('content')
        # stream = ChatResponse(message=f'{content}', type='stream')
        # await self.websocket.send_json(stream.dict())
        logger.debug(
            f'on_chat_model_start serialized={serialized} messages={messages} kwargs={kwargs}')
        logger.info('k=s act=on_chat_model_start messages={}', messages)


class StreamingLLMCallbackHandler(BaseCallbackHandler):
    """Callback handler for streaming LLM responses."""

    def __init__(self,
                 websocket: WebSocket,
                 flow_id: str,
                 chat_id: str,
                 user_id: int = None,
                 **kwargs: Any):
        self.websocket = websocket
        self.flow_id = flow_id
        self.chat_id = chat_id
        self.user_id = user_id

        self.stream_queue: Queue = kwargs.get('stream_queue')

    def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        # azure偶尔会返回一个None
        if token is None:
            return
        resp = ChatResponse(message=token,
                            type='stream',
                            flow_id=self.flow_id,
                            chat_id=self.chat_id)
        if self.websocket:
            loop = asyncio.get_event_loop()
            coroutine = self.websocket.send_json(resp.dict())
            asyncio.run_coroutine_threadsafe(coroutine, loop)

        if self.stream_queue:
            self.stream_queue.put(token)

    def on_agent_action(self, action: AgentAction, **kwargs: Any) -> Any:
        log = f'\nThought: {action.log}'
        # if there are line breaks, split them and send them
        # as separate messages
        log = log.replace('\n', '\n\n')
        resp = ChatResponse(type='stream',
                            intermediate_steps=log,
                            flow_id=self.flow_id,
                            chat_id=self.chat_id)
        if self.websocket:
            loop = asyncio.get_event_loop()
            coroutine = self.websocket.send_json(resp.dict())
            asyncio.run_coroutine_threadsafe(coroutine, loop)
        logger.info('k=s act=on_agent_action {}', action)

    def on_agent_finish(self, finish: AgentFinish, **kwargs: Any) -> Any:
        """Run on agent end."""
        resp = ChatResponse(type='stream',
                            intermediate_steps=finish.log,
                            flow_id=self.flow_id,
                            chat_id=self.chat_id)
        if self.websocket:
            loop = asyncio.get_event_loop()
            coroutine = self.websocket.send_json(resp.dict())
            asyncio.run_coroutine_threadsafe(coroutine, loop)
        logger.info('k=s act=on_agent_finish {}', finish)

    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs: Any) -> Any:
        """Run when tool starts running."""
        resp = ChatResponse(type='stream',
                            intermediate_steps=f'Tool input: {input_str}',
                            flow_id=self.flow_id,
                            chat_id=self.chat_id)
        if self.websocket:
            loop = asyncio.get_event_loop()
            coroutine = self.websocket.send_json(resp.dict())
            asyncio.run_coroutine_threadsafe(coroutine, loop)
        logger.info('k=s act=on_tool_start flow_id={} tool_name={} input_str={}', self.flow_id,
                    serialized.get('name'), input_str)

    def on_tool_end(self, output: str, **kwargs: Any) -> Any:
        """Run when tool ends running."""
        observation_prefix = kwargs.get('observation_prefix', 'Tool output: ')

        # from langchain.docstore.document import Document # noqa
        # result = eval(output).get('result')
        result = output
        # Create a formatted message.
        intermediate_steps = f'{observation_prefix}{result}'

        # Create a ChatResponse instance.
        resp = ChatResponse(type='stream',
                            intermediate_steps=intermediate_steps,
                            flow_id=self.flow_id,
                            chat_id=self.chat_id)

        # Try to send the response, handle potential errors.
        try:
            if self.websocket:
                loop = asyncio.get_event_loop()
                coroutine = self.websocket.send_json(resp.dict())
                asyncio.run_coroutine_threadsafe(coroutine, loop)
        except Exception as e:
            logger.error(e)
        logger.info("k=s act=on_tool_end flow_id={} output='{}'", self.flow_id, output)

    def on_retriever_start(self, serialized: Dict[str, Any], query: str, **kwargs: Any) -> Any:
        """Run when retriever start running."""
        logger.info('k=s act=on_retriever_start flow_id={} query={} meta={}', self.flow_id, query,
                    serialized.get('repr'))

    def on_retriever_end(self, result: List[Document], **kwargs: Any) -> Any:
        """Run when retriever end running."""
        # todo 判断技能权限
        logger.debug(f'retriver_result result={result}')
        if result:
            tmp_result = copy.deepcopy(result)
            [doc.metadata.pop('bbox', '') for doc in tmp_result]
            logger.info('k=s act=on_retriever_end flow_id={} result_without_bbox={}', self.flow_id,
                        tmp_result)

    def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any],
                       **kwargs: Any) -> Any:
        """Run when chain starts running."""
        logger.debug(f'on_chain_start inputs={inputs}')
        logger.info('k=s act=on_chain_start flow_id={} input_dict={}', self.flow_id, inputs)

    def on_chain_end(self, outputs: Dict[str, Any], **kwargs: Any) -> Any:
        """Run when chain ends running."""
        logger.debug(f'on_chain_end outputs={outputs}')
        tmp_output = copy.deepcopy(outputs)
        if isinstance(tmp_output, dict):
            tmp_output.pop('source_documents', '')
        logger.info('k=s act=on_chain_end flow_id={} output_dict={}', self.flow_id, tmp_output)

    def on_chat_model_start(self, serialized: Dict[str, Any], messages: List[List[BaseMessage]],
                            **kwargs: Any) -> Any:
        """Run when retriever end running."""
        # sender = kwargs['sender']
        # receiver = kwargs['receiver']
        # content = messages[0][0] if isinstance(messages[0][0], str) else messages[0][0].get('content')
        # end = ChatResponse(message=f'{content}', type='end', sender=sender, recevier=receiver)
        # start = ChatResponse(type='start', sender=sender, recevier=receiver)
        # loop = asyncio.get_event_loop()
        # coroutine2 = self.websocket.send_json(end.dict())
        # coroutine3 = self.websocket.send_json(start.dict())
        # asyncio.run_coroutine_threadsafe(coroutine2, loop)
        # asyncio.run_coroutine_threadsafe(coroutine3, loop)
        logger.debug(f'on_chat result={messages}')
        logger.info('k=s act=on_chat_model_start messages={}', messages)

    def on_text(self, text: str, **kwargs) -> Any:
        logger.info(text)
        if 'Prompt after formatting:' in text:
            prompt_str = text[24:]
            logger.info(
                "k=s act=on_text prompt='{}'",
                prompt_str,
            )


class AsyncGptsLLMCallbackHandler(AsyncStreamingLLMCallbackHandler):

    async def on_tool_start(self, serialized: Dict[str, Any], input_str: str,
                            **kwargs: Any) -> Any:
        """Run when tool starts running."""
        logger.debug(
            f'on_tool_start serialized={serialized} input_str={input_str} kwargs={kwargs}')
        pass

    async def on_tool_end(self, output: str, **kwargs: Any) -> Any:
        """Run when tool ends running."""
        logger.debug(f'on_tool_end output={output} kwargs={kwargs}')
        pass


class AsyncGptsDebugCallbackHandler(AsyncGptsLLMCallbackHandler):

    @staticmethod
    def parse_tool_category(tool_name) -> (str, str):
        """
        将tool_name解析为tool_category和真正的tool_name
        """
        tool_category = 'tool'
        if tool_name.startswith('flow_'):
            # 说明是技能调用
            tool_category = 'flow'
            tool_name = tool_name.replace('flow_', '')
        elif tool_name.startswith('knowledge_'):
            # 说明是知识库调用
            tool_category = 'knowledge'
            tool_name = tool_name.replace('knowledge_', '')
        return tool_name, tool_category

    async def on_chat_model_start(self, serialized: Dict[str, Any],
                                  messages: List[List[BaseMessage]], **kwargs: Any) -> Any:
        # """Run when retriever end running."""
        # content = messages[0][0] if isinstance(messages[0][0], str) else messages[0][0].get('content')
        # stream = ChatResponse(message=f'{content}', type='stream')
        # await self.websocket.send_json(stream.dict())
        logger.debug(
            f'on_chat_model_start serialized={serialized} messages={messages} kwargs={kwargs}')
        resp = ChatResponse(type='start',
                            category='processing',
                            flow_id=self.flow_id,
                            chat_id=self.chat_id)
        await self.websocket.send_json(resp.dict())

    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> Any:
        """Run when LLM ends running."""
        logger.debug(f'llm_end response={response}')
        resp = ChatResponse(type='end',
                            category='processing',
                            flow_id=self.flow_id,
                            chat_id=self.chat_id)
        await self.websocket.send_json(resp.dict())

    async def on_llm_error(self, error: Union[Exception, KeyboardInterrupt], **kwargs: Any) -> Any:
        """Run when LLM errors."""
        logger.debug(f'on_llm_error error={error} kwargs={kwargs}')
        resp = ChatResponse(type='end',
                            category='processing',
                            flow_id=self.flow_id,
                            chat_id=self.chat_id)
        await self.websocket.send_json(resp.dict())

    async def on_tool_start(self, serialized: Dict[str, Any], input_str: str,
                            **kwargs: Any) -> Any:
        """Run when tool starts running."""
        logger.debug(
            f'on_tool_start serialized={serialized} input_str={input_str} kwargs={kwargs}')

        input_str = input_str
        tool_name, tool_category = self.parse_tool_category(serialized['name'])
        input_info = {'tool_key': tool_name, 'serialized': serialized, 'input_str': input_str}
        self.tool_cache[kwargs.get('run_id').hex] = {
            'input': input_info,
            'category': tool_category,
            'steps': f'Tool input: \n\n{input_str}\n\n',
        }
        resp = ChatResponse(type='start',
                            category=tool_category,
                            intermediate_steps=self.tool_cache[kwargs.get('run_id').hex]['steps'],
                            message=json.dumps(input_info, ensure_ascii=False),
                            flow_id=self.flow_id,
                            chat_id=self.chat_id,
                            extra=json.dumps({'run_id': kwargs.get('run_id').hex}))
        await self.websocket.send_json(resp.dict())

    async def on_tool_end(self, output: str, **kwargs: Any) -> Any:
        """Run when tool ends running."""
        logger.debug(f'on_tool_end output={output} kwargs={kwargs}')
        observation_prefix = kwargs.get('observation_prefix', 'Tool output: ')

        result = output
        # Create a formatted message.
        intermediate_steps = f'{observation_prefix}\n\n{result}'
        tool_name, tool_category = self.parse_tool_category(kwargs.get('name'))

        # Create a ChatResponse instance.
        output_info = {'tool_key': tool_name, 'output': output}
        resp = ChatResponse(type='end',
                            category=tool_category,
                            intermediate_steps=intermediate_steps,
                            message=json.dumps(output_info, ensure_ascii=False),
                            flow_id=self.flow_id,
                            chat_id=self.chat_id,
                            extra=json.dumps({'run_id': kwargs.get('run_id').hex}))

        await self.websocket.send_json(resp.dict())
        # 从tool cache中获取input信息
        input_info = self.tool_cache.get(kwargs.get('run_id').hex)
        if input_info:
            if not self.chat_id:
                # 说明是调试界面，不用持久化数据
                self.tool_cache.pop(kwargs.get('run_id').hex)
                return
            output_info.update(input_info['input'])
            intermediate_steps = f'{input_info["steps"]}\n\n{intermediate_steps}'
            ChatMessageDao.insert_one(
                ChatMessageModel(is_bot=1,
                                 message=json.dumps(output_info),
                                 intermediate_steps=intermediate_steps,
                                 category=tool_category,
                                 type='end',
                                 flow_id=self.flow_id,
                                 chat_id=self.chat_id,
                                 user_id=self.user_id,
                                 extra=json.dumps({'run_id': kwargs.get('run_id').hex})))
            self.tool_cache.pop(kwargs.get('run_id').hex)

    async def on_tool_error(self, error: Union[Exception, KeyboardInterrupt],
                            **kwargs: Any) -> Any:
        """Run when tool errors."""
        logger.debug(f'on_tool_error error={error} kwargs={kwargs}')
        input_info = self.tool_cache.get(kwargs.get('run_id').hex)
        if input_info:
            output_info = {'output': 'Error: ' + str(error)}
            output_info.update(input_info['input'])
            resp = ChatResponse(type='end',
                                category=input_info['category'],
                                intermediate_steps='\n\nTool output:\n\n  Error: ' + str(error),
                                message=json.dumps(output_info, ensure_ascii=False),
                                flow_id=self.flow_id,
                                chat_id=self.chat_id,
                                extra=json.dumps({'run_id': kwargs.get('run_id').hex}))
            await self.websocket.send_json(resp.dict())

            # 保存工具调用记录
            if not self.chat_id:
                # 说明是调试界面，不用持久化数据
                self.tool_cache.pop(kwargs.get('run_id').hex)
                return
            tool_name, tool_category = self.parse_tool_category(kwargs.get('name'))
            self.tool_cache.pop(kwargs.get('run_id').hex)
            ChatMessageDao.insert_one(
                ChatMessageModel(
                    is_bot=1,
                    message=json.dumps(output_info),
                    intermediate_steps=f'{input_info["steps"]}\n\nTool output:\n\n  Error: ' +
                    str(error),
                    category=tool_category,
                    type='end',
                    flow_id=self.flow_id,
                    chat_id=self.chat_id,
                    user_id=self.user_id,
                    extra=json.dumps({'run_id': kwargs.get('run_id').hex})))
