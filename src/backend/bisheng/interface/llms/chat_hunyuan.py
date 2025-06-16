import warnings
from typing import Any, Optional, Iterator, AsyncIterator, Type, List

from langchain_core.callbacks import CallbackManagerForLLMRun, AsyncCallbackManagerForLLMRun
from langchain_core.messages import BaseMessageChunk, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.utils.pydantic import is_basemodel_subclass
from langchain_openai.chat_models import ChatOpenAI
# from langchain_openai.chat_models.base import _convert_chunk_to_generation_chunk


class ChatHunyuanOpenai(ChatOpenAI):
    """ when function call result is output, remove the assistant content """

    def _super_stream(self,
                      messages: List[BaseMessage],
                      stop: Optional[List[str]] = None,
                      run_manager: Optional[CallbackManagerForLLMRun] = None,
                      **kwargs: Any) -> Iterator[ChatGenerationChunk]:
        print("------------------- super stream -------------")
        kwargs["stream"] = True
        payload = self._get_request_payload(messages, stop=stop, **kwargs)
        default_chunk_class: Type[BaseMessageChunk] = AIMessageChunk
        base_generation_info = {}

        if "response_format" in payload and is_basemodel_subclass(
                payload["response_format"]
        ):
            # TODO: Add support for streaming with Pydantic response_format.
            warnings.warn("Streaming with Pydantic response_format not yet supported.")
            chat_result = self._generate(
                messages, stop, run_manager=run_manager, **kwargs
            )
            msg = chat_result.generations[0].message
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    **msg.dict(exclude={"type", "additional_kwargs"}),
                    # preserve the "parsed" Pydantic object without converting to dict
                    additional_kwargs=msg.additional_kwargs,
                ),
                generation_info=chat_result.generations[0].generation_info,
            )
            return
        if self.include_response_headers:
            raw_response = self.client.with_raw_response.create(**payload)
            response = raw_response.parse()
            base_generation_info = {"headers": dict(raw_response.headers)}
        else:
            response = self.client.create(**payload)
        with response:
            is_func_call = False
            is_first_chunk = True
            for chunk in response:
                if not isinstance(chunk, dict):
                    chunk = chunk.model_dump()

                # DONE merge_check 1
                # generation_chunk = _convert_chunk_to_generation_chunk(
                #     chunk,
                #     default_chunk_class,
                #     base_generation_info if is_first_chunk else {},
                # )

                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                message_chunk = AIMessageChunk(content=content)
                generation_chunk = ChatGenerationChunk(
                    message=message_chunk,
                    # generation_info 仍然可以像以前一样处理，通常只在第一个块中非空
                    generation_info=base_generation_info if is_first_chunk else None
                )

                if generation_chunk is None:
                    continue

                # 如果是func call 去除assistant的内容
                if generation_chunk.message.additional_kwargs.get('tool_calls'):
                    is_func_call = True
                if is_func_call:
                    generation_chunk.message.content = ''
                    generation_chunk.text = ''

                default_chunk_class = generation_chunk.message.__class__
                logprobs = (generation_chunk.generation_info or {}).get("logprobs")
                if run_manager:
                    run_manager.on_llm_new_token(
                        generation_chunk.text, chunk=generation_chunk, logprobs=logprobs
                    )
                is_first_chunk = False
                yield generation_chunk

    async def _super_astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        kwargs["stream"] = True
        payload = self._get_request_payload(messages, stop=stop, **kwargs)
        default_chunk_class: Type[BaseMessageChunk] = AIMessageChunk
        base_generation_info = {}
        if "response_format" in payload and is_basemodel_subclass(
            payload["response_format"]
        ):
            # TODO: Add support for streaming with Pydantic response_format.
            warnings.warn("Streaming with Pydantic response_format not yet supported.")
            chat_result = await self._agenerate(
                messages, stop, run_manager=run_manager, **kwargs
            )
            msg = chat_result.generations[0].message
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    **msg.dict(exclude={"type", "additional_kwargs"}),
                    # preserve the "parsed" Pydantic object without converting to dict
                    additional_kwargs=msg.additional_kwargs,
                ),
                generation_info=chat_result.generations[0].generation_info,
            )
            return
        if self.include_response_headers:
            raw_response = await self.async_client.with_raw_response.create(**payload)
            response = raw_response.parse()
            base_generation_info = {"headers": dict(raw_response.headers)}
        else:
            response = await self.async_client.create(**payload)
        async with response:
            is_first_chunk = True
            is_func_call = False
            async for chunk in response:
                if not isinstance(chunk, dict):
                    chunk = chunk.model_dump()
                # generation_chunk = _convert_chunk_to_generation_chunk(
                #     chunk,
                #     default_chunk_class,
                #     base_generation_info if is_first_chunk else {},
                # )

                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                message_chunk = AIMessageChunk(content=content)
                generation_chunk = ChatGenerationChunk(
                    message=message_chunk,
                    # generation_info 仍然可以像以前一样处理，通常只在第一个块中非空
                    generation_info=base_generation_info if is_first_chunk else None
                )

                if generation_chunk is None:
                    continue

                # 如果是func call 去除assistant的内容
                if generation_chunk.message.additional_kwargs.get('tool_calls'):
                    is_func_call = True
                if is_func_call:
                    generation_chunk.message.content = ''
                    generation_chunk.text = ''

                default_chunk_class = generation_chunk.message.__class__
                logprobs = (generation_chunk.generation_info or {}).get("logprobs")
                if run_manager:
                    await run_manager.on_llm_new_token(
                        generation_chunk.text, chunk=generation_chunk, logprobs=logprobs
                    )
                is_first_chunk = False
                yield generation_chunk


    def _stream(
            self, *args: Any, stream_usage: Optional[bool] = None, **kwargs: Any
    ) -> Iterator[ChatGenerationChunk]:
        """Set default stream_options."""
        stream_usage = self._should_stream_usage(stream_usage, **kwargs)
        # Note: stream_options is not a valid parameter for Azure OpenAI.
        # To support users proxying Azure through ChatOpenAI, here we only specify
        # stream_options if include_usage is set to True.
        # See https://learn.microsoft.com/en-us/azure/ai-services/openai/whats-new
        # for release notes.
        if stream_usage:
            kwargs["stream_options"] = {"include_usage": stream_usage}
        for chunk in self._super_stream(*args, **kwargs):
            yield chunk

    async def _astream(
            self, *args: Any, stream_usage: Optional[bool] = None, **kwargs: Any
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Set default stream_options."""
        stream_usage = self._should_stream_usage(stream_usage, **kwargs)
        if stream_usage:
            kwargs["stream_options"] = {"include_usage": stream_usage}

        async for chunk in self._super_astream(*args, **kwargs):
            yield chunk
