from bisheng.api.v1.schemas import ChatMessage
from bisheng.interface.utils import try_setting_streaming_options
from bisheng.processing.base import get_result_and_steps
from bisheng.utils.logger import logger
from fastapi import WebSocket


async def process_graph(
    langchain_object,
    chat_inputs: ChatMessage,
    websocket: WebSocket,
):
    langchain_object = try_setting_streaming_options(langchain_object, websocket)
    logger.debug('Loaded langchain object')

    if langchain_object is None:
        # Raise user facing error
        raise ValueError(
            'There was an error loading the langchain_object. Please, check all the nodes and try again.'
        )

    # Generate result and thought
    try:
        if not chat_inputs.message:
            logger.debug('No message provided')
            raise ValueError('No message provided')

        logger.debug('Generating result and thought')
        result, intermediate_steps = await get_result_and_steps(
            langchain_object, chat_inputs.message, websocket=websocket
        )
        logger.debug('Generated result and intermediate_steps')
        return result, intermediate_steps
    except Exception as e:
        # Log stack trace
        logger.exception(e)
        raise e
