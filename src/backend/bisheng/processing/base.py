from typing import Tuple, Union

from langchain_core.runnables import RunnableConfig
from loguru import logger

from bisheng.api.v1.callback import AsyncStreamingLLMCallbackHandler
from bisheng.processing.process import fix_memory_inputs, format_actions


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

        async_callbacks = [AsyncStreamingLLMCallbackHandler(**kwargs)]
        output = await langchain_object.ainvoke(inputs, config=RunnableConfig(callbacks=async_callbacks))

        intermediate_steps = (output.get('intermediate_steps', [])
                              if isinstance(output, dict) else [])
        source_document = (output.get('source_documents', '') if isinstance(output, dict) else '')
        # Default copywriting for cases where the return is empty
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
