import asyncio
from typing import Any, Dict, List, Union

from bisheng.api.v1.schemas import ChatResponse
from bisheng.utils.logger import logger
from fastapi import WebSocket
from langchain.callbacks.base import AsyncCallbackHandler, BaseCallbackHandler
from langchain.schema import AgentFinish, LLMResult
from langchain.schema.agent import AgentAction
from langchain.schema.document import Document


# https://github.com/hwchase17/chat-langchain/blob/master/callback.py
class AsyncStreamingLLMCallbackHandler(AsyncCallbackHandler):
    """Callback handler for streaming LLM responses."""

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket

    async def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        resp = ChatResponse(message=token, type='stream', intermediate_steps='')
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

    async def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs: Any) -> Any:
        """Run when tool starts running."""
        resp = ChatResponse(
            message='',
            type='stream',
            intermediate_steps=f'Tool input: {input_str}',
        )
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
        resp = ChatResponse(
            message='',
            type='stream',
            intermediate_steps=intermediate_steps,
        )

        try:
            # This is to emulate the stream of tokens
            await self.websocket.send_json(resp.dict())
        except Exception as e:
            logger.error(e)

    async def on_tool_error(self, error: Union[Exception, KeyboardInterrupt], **kwargs: Any) -> Any:
        """Run when tool errors."""

    async def on_text(self, text: str, **kwargs: Any) -> Any:
        """Run on arbitrary text."""
        # This runs when first sending the prompt
        # to the LLM, adding it will send the final prompt
        # to the frontend

    async def on_agent_action(self, action: AgentAction, **kwargs: Any):
        log = f'Thought: {action.log}'
        # if there are line breaks, split them and send them
        # as separate messages
        if '\n' in log:
            logs = log.split('\n')
            for log in logs:
                resp = ChatResponse(message='', type='stream', intermediate_steps=log)
                await self.websocket.send_json(resp.dict())
        else:
            resp = ChatResponse(message='', type='stream', intermediate_steps=log)
            await self.websocket.send_json(resp.dict())

    async def on_agent_finish(self, finish: AgentFinish, **kwargs: Any) -> Any:
        """Run on agent end."""
        resp = ChatResponse(
            message='',
            type='stream',
            intermediate_steps=finish.log,
        )
        await self.websocket.send_json(resp.dict())

    async def on_retriever_start(self, serialized: Dict[str, Any], query: str,
                                 **kwargs: Any) -> Any:
        """Run when retriever start running."""

    async def on_retriever_end(self, result: List[Document], **kwargs: Any) -> Any:
        """Run when retriever end running."""
        # todo 判断技能权限
        logger.debug(f'retriver_result result={result}')


class StreamingLLMCallbackHandler(BaseCallbackHandler):
    """Callback handler for streaming LLM responses."""

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket

    def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        resp = ChatResponse(message=token, type='stream', intermediate_steps='')

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
                resp = ChatResponse(message='', type='stream', intermediate_steps=log)
                loop = asyncio.get_event_loop()
                coroutine = self.websocket.send_json(resp.dict())
                asyncio.run_coroutine_threadsafe(coroutine, loop)
        else:
            resp = ChatResponse(message='', type='stream', intermediate_steps=log)
            loop = asyncio.get_event_loop()
            coroutine = self.websocket.send_json(resp.dict())
            asyncio.run_coroutine_threadsafe(coroutine, loop)

    def on_agent_finish(self, finish: AgentFinish, **kwargs: Any) -> Any:
        """Run on agent end."""
        resp = ChatResponse(
            message='',
            type='stream',
            intermediate_steps=finish.log,
        )
        loop = asyncio.get_event_loop()
        coroutine = self.websocket.send_json(resp.dict())
        asyncio.run_coroutine_threadsafe(coroutine, loop)

    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs: Any) -> Any:
        """Run when tool starts running."""
        resp = ChatResponse(
            message='',
            type='stream',
            intermediate_steps=f'Tool input: {input_str}',
        )
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
        resp = ChatResponse(
            message='',
            type='stream',
            intermediate_steps=intermediate_steps,
        )

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
