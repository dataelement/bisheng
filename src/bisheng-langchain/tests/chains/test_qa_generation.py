import os
import httpx
# from langchain.document_loaders import PyPDFLoader
from langchain_openai import ChatOpenAI
from bisheng_langchain.document_loaders import ElemUnstructuredLoader
from bisheng_langchain.chat_models import ChatQWen
from bisheng_langchain.chains import QAGenerationChain, QAGenerationChainV2


openai_proxy = os.getenv('OPENAI_PROXY')
async_http_client = httpx.AsyncClient(proxies=openai_proxy)
httpx_client = httpx.Client(proxies=openai_proxy)
llm = ChatOpenAI(
    model='gpt-4-0125-preview',
    temperature=0.3,
    http_async_client=async_http_client,
    http_client=httpx_client,
)

# llm = ChatQWen(
#     model_name='qwen1.5-72b-chat',
#     temperature=0.3,
# )


def generator():
    file_path = "../data/个人经营性贷款材料.pdf"
    # loader = PyPDFLoader(file_path)
    loader = ElemUnstructuredLoader(
        file_name='个人经营性贷款材料.pdf',
        file_path=file_path,
        unstructured_api_url='https://bisheng.dataelem.com/api/v1/etl4llm/predict',
    )
    documents = loader.load()
    k = 5
    chunk_size = 512
    filter_lowquality_context = False
    filter_lowquality_question = False
    # qa_generator = QAGenerationChain.from_llm(documents, llm, k=k, chunk_size=chunk_size, filter_lowquality_context=filter_lowquality_context, filter_lowquality_question=filter_lowquality_question)
    qa_generator = QAGenerationChainV2.from_llm(documents, 
                                                llm, 
                                                k=k, 
                                                chunk_size=chunk_size, 
                                                filter_lowquality_context=filter_lowquality_context, 
                                                filter_lowquality_question=filter_lowquality_question
    )
    inputs = {'begin': '开始'}
    response = qa_generator(inputs)
    question_answers = response['questions']
    print(question_answers)


generator()


