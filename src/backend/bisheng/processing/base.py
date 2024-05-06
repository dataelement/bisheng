import asyncio
from typing import Tuple, Union

from bisheng.api.v1.callback import AsyncStreamingLLMCallbackHandler, StreamingLLMCallbackHandler
from bisheng.processing.process import fix_memory_inputs, format_actions
from bisheng.utils.logger import logger


async def get_result_and_steps(langchain_object, inputs: Union[dict, str], **kwargs):
    """Get result and thought from extracted json"""

    try:
        if hasattr(langchain_object, 'verbose'):
            langchain_object.verbose = True

        if hasattr(langchain_object, 'return_intermediate_steps'):
            # https://github.com/hwchase17/langchain/issues/2068
            # Deactivating until we have a frontend solution
            # to display intermediate steps
            langchain_object.return_intermediate_steps = True
        try:
            fix_memory_inputs(langchain_object)
        except Exception as exc:
            logger.error(exc)

        asyc = True
        try:
            async_callbacks = [AsyncStreamingLLMCallbackHandler(**kwargs)]
            output = await langchain_object.acall(inputs, callbacks=async_callbacks)
        except Exception as exc:
            # make the error message more informative
            logger.exception(exc)
            asyc = False
            # step = ChatResponse(intermediate_steps='分析中', type='stream',)
            # await kwargs['websocket'].send_json(step.dict())
            sync_callbacks = [StreamingLLMCallbackHandler(**kwargs)]
            output = langchain_object(inputs, callbacks=sync_callbacks)
        finally:
            if not asyc:
                # 协程切换一下，将同步的过程打印
                await asyncio.sleep(1)

        intermediate_steps = (output.get('intermediate_steps', [])
                              if isinstance(output, dict) else [])
        source_document = (output.get('source_documents', '') if isinstance(output, dict) else '')
        # 针对返回为空的情况，进行默认文案说明
        if isinstance(output, dict):
            result = output.get(langchain_object.output_keys[0])
        else:
            result = output

        try:
            if intermediate_steps and isinstance(intermediate_steps[0], Tuple):
                thought = format_actions(intermediate_steps)
            else:
                thought = intermediate_steps
        except Exception as exc:
            logger.exception(exc)
            thought = ''
    except Exception as exc:
        logger.exception(exc)
        raise ValueError(f'Error: {str(exc)}') from exc
    return result, thought, source_document
