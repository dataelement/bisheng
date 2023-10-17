from bisheng.api.v1.schemas import ChatMessage
from bisheng.interface.utils import try_setting_streaming_options
from bisheng.processing.base import get_result_and_steps
from bisheng.utils.logger import logger
from bisheng_langchain.chat_models import HostQwenChat
from fastapi import WebSocket
from langchain import LLMChain, PromptTemplate


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
        result, intermediate_steps, source_document = await get_result_and_steps(
            langchain_object, chat_inputs.message, websocket=websocket)
        logger.debug('Generated result and intermediate_steps')
        return result, intermediate_steps, source_document
    except Exception as e:
        # Log stack trace
        logger.exception(e)
        raise e


prompt_template = '''分析给定Question，提取Question中包含的KeyWords，输出列表形式

Examples:
Question: 达梦公司在过去三年中的流动比率如下：2021年：3.74倍；2020年：2.82倍；2019年：2.05倍。
KeyWords: ['过去三年', '流动比率', '2021', '3.74', '2020', '2.82', '2019', '2.05']

----------------
Question: {question}'''


def extract_answer_keys(answer, extract_model, host_base_url):
    """
    提取answer中的关键词
    """
    if extract_model:
        llm = HostQwenChat(model_name=extract_model,
                           host_base_url=host_base_url,
                           max_tokens=8192,
                           temperature=0,
                           verbose=True)
        llm_chain = LLMChain(llm=llm, prompt=PromptTemplate.from_template(prompt_template))
    try:
        keywords_str = llm_chain.run(answer)
        keywords = eval(keywords_str[9:])
    except Exception:
        import jieba.analyse
        logger.warning(f'llm {extract_model} extract_not_support, change to jieba')
        keywords = jieba.analyse.extract_tags(answer, topK=100, withWeight=False)

    return keywords
