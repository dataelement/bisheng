import asyncio
from typing import Any, Dict, List, Union

from bisheng.api.v1.schemas import ChatResponse
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

    def __init__(self, websocket: WebSocket, flow_id: str, chat_id: str):
        self.websocket = websocket
        self.flow_id = flow_id
        self.chat_id = chat_id

    async def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        resp = ChatResponse(message=token,
                            type='stream',
                            flow_id=self.flow_id,
                            chat_id=self.chat_id)
        await self.websocket.send_json(resp.dict())

    async def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str],
                           **kwargs: Any) -> Any:
        """Run when LLM starts running."""
        logger.debug(f'llm_start prompts={prompts}')

    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> Any:
        """Run when LLM ends running."""
        logger.debug(f'llm_end response={response}')

    async def on_llm_error(self, error: Union[Exception, KeyboardInterrupt], **kwargs: Any) -> Any:
        """Run when LLM errors."""

    async def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any],
                             **kwargs: Any) -> Any:
        """Run when chain starts running."""
        logger.debug(f'on_chain_start inputs={inputs}')

    async def on_chain_end(self, outputs: Dict[str, Any], **kwargs: Any) -> Any:
        """Run when chain ends running."""
        logger.debug(f'on_chain_end outputs={outputs}')

    async def on_chain_error(self, error: Union[Exception, KeyboardInterrupt],
                             **kwargs: Any) -> Any:
        """Run when chain errors."""

    async def on_tool_start(self, serialized: Dict[str, Any], input_str: str,
                            **kwargs: Any) -> Any:
        """Run when tool starts running."""
        resp = ChatResponse(type='stream',
                            intermediate_steps=f'Tool input: {input_str}',
                            flow_id=self.flow_id,
                            chat_id=self.chat_id)
        await self.websocket.send_json(resp.dict())

    async def on_tool_end(self, output: str, **kwargs: Any) -> Any:
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

        try:
            # This is to emulate the stream of tokens
            await self.websocket.send_json(resp.dict())
        except Exception as e:
            logger.error(e)

    async def on_tool_error(self, error: Union[Exception, KeyboardInterrupt],
                            **kwargs: Any) -> Any:
        """Run when tool errors."""

    async def on_text(self, text: str, **kwargs: Any) -> Any:
        """Run on arbitrary text."""
        # This runs when first sending the prompt
        # to the LLM, adding it will send the final prompt
        # to the frontend
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
        logger.debug(f'on_text text={text} kwargs={kwargs}')

    async def on_agent_action(self, action: AgentAction, **kwargs: Any):
        log = f'Thought: {action.log}'
        # if there are line breaks, split them and send them
        # as separate messages
        if '\n' in log:
            logs = log.split('\n')
            for log in logs:
                resp = ChatResponse(type='stream',
                                    intermediate_steps=log,
                                    flow_id=self.flow_id,
                                    chat_id=self.chat_id)
                await self.websocket.send_json(resp.dict())
        else:
            resp = ChatResponse(type='stream',
                                intermediate_steps=log,
                                flow_id=self.flow_id,
                                chat_id=self.chat_id)
            await self.websocket.send_json(resp.dict())

    async def on_agent_finish(self, finish: AgentFinish, **kwargs: Any) -> Any:
        """Run on agent end."""
        resp = ChatResponse(flow_id=self.flow_id,
                            chat_id=self.chat_id,
                            type='stream',
                            intermediate_steps=finish.log)
        await self.websocket.send_json(resp.dict())

    async def on_retriever_start(self, serialized: Dict[str, Any], query: str,
                                 **kwargs: Any) -> Any:
        """Run when retriever start running."""

    async def on_retriever_end(self, result: List[Document], **kwargs: Any) -> Any:
        """Run when retriever end running."""
        # todo 判断技能权限
        logger.debug(f'retriver_result result={result}')

    async def on_chat_model_start(self, serialized: Dict[str, Any],
                                  messages: List[List[BaseMessage]], **kwargs: Any) -> Any:
        # """Run when retriever end running."""
        # content = messages[0][0] if isinstance(messages[0][0], str) else messages[0][0].get('content')
        # stream = ChatResponse(message=f'{content}', type='stream')
        # await self.websocket.send_json(stream.dict())
        logger.debug(f'chat_message result={messages}')


class StreamingLLMCallbackHandler(BaseCallbackHandler):
    """Callback handler for streaming LLM responses."""

    def __init__(self, websocket: WebSocket, flow_id: str, chat_id: str):
        self.websocket = websocket
        self.flow_id = flow_id
        self.chat_id = chat_id

    def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        resp = ChatResponse(message=token,
                            type='stream',
                            flow_id=self.flow_id,
                            chat_id=self.chat_id)

        loop = asyncio.get_event_loop()
        coroutine = self.websocket.send_json(resp.dict())
        asyncio.run_coroutine_threadsafe(coroutine, loop)

    def on_agent_action(self, action: AgentAction, **kwargs: Any) -> Any:
        log = f'Thought: {action.log}'
        # if there are line breaks, split them and send them
        # as separate messages
        if '\n' in log:
            logs = log.split('\n')
            for log in logs:
                resp = ChatResponse(type='stream',
                                    intermediate_steps=log,
                                    flow_id=self.flow_id,
                                    chat_id=self.chat_id)
                loop = asyncio.get_event_loop()
                coroutine = self.websocket.send_json(resp.dict())
                asyncio.run_coroutine_threadsafe(coroutine, loop)
        else:
            resp = ChatResponse(type='stream',
                                intermediate_steps=log,
                                flow_id=self.flow_id,
                                chat_id=self.chat_id)
            loop = asyncio.get_event_loop()
            coroutine = self.websocket.send_json(resp.dict())
            asyncio.run_coroutine_threadsafe(coroutine, loop)

    def on_agent_finish(self, finish: AgentFinish, **kwargs: Any) -> Any:
        """Run on agent end."""
        resp = ChatResponse(type='stream',
                            intermediate_steps=finish.log,
                            flow_id=self.flow_id,
                            chat_id=self.chat_id)
        loop = asyncio.get_event_loop()
        coroutine = self.websocket.send_json(resp.dict())
        asyncio.run_coroutine_threadsafe(coroutine, loop)

    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs: Any) -> Any:
        """Run when tool starts running."""
        resp = ChatResponse(type='stream',
                            intermediate_steps=f'Tool input: {input_str}',
                            flow_id=self.flow_id,
                            chat_id=self.chat_id)
        loop = asyncio.get_event_loop()
        coroutine = self.websocket.send_json(resp.dict())
        asyncio.run_coroutine_threadsafe(coroutine, loop)

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
            loop = asyncio.get_event_loop()
            coroutine = self.websocket.send_json(resp.dict())
            asyncio.run_coroutine_threadsafe(coroutine, loop)
        except Exception as e:
            logger.error(e)

    def on_retriever_start(self, serialized: Dict[str, Any], query: str, **kwargs: Any) -> Any:
        """Run when retriever start running."""

    def on_retriever_end(self, result: List[Document], **kwargs: Any) -> Any:
        """Run when retriever end running."""
        # todo 判断技能权限
        logger.debug(f'retriver_result result={result}')

    def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any],
                       **kwargs: Any) -> Any:
        """Run when chain starts running."""
        logger.debug(f'on_chain_start inputs={inputs}')

    def on_chain_end(self, outputs: Dict[str, Any], **kwargs: Any) -> Any:
        """Run when chain ends running."""
        logger.debug(f'on_chain_end outputs={outputs}')

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

    def on_text(self, text: str, **kwargs) -> Any:
        logger.info(text)
