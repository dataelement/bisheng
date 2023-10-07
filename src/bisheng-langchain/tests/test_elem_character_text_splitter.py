import pprint

from bisheng_langchain.document_loaders import ElemUnstructuredLoader
from bisheng_langchain.text_splitter import ElemCharacterTextSplitter


def text_splitter():
    loader = ElemUnstructuredLoader('./data/dummy.txt')
    docs = loader.load()
    print('docs', docs)

    text_splitter = ElemCharacterTextSplitter(chunk_size=10, chunk_overlap=0)
    split_docs = text_splitter.split_documents(docs)
    pprint.pprint(split_docs)


def text_splitter2():
    url = 'http://192.168.106.12:10001/v1/etl4llm/predict'
    loader = ElemUnstructuredLoader(
        file_name='达梦数据库招股说明书.pdf',
        file_path='./data/达梦数据库招股说明书.pdf',
        unstructured_api_url=url,
        start=0,
        n=100)
    docs = loader.load()
    print('docs', docs)

    text_splitter = ElemCharacterTextSplitter(chunk_size=500, chunk_overlap=0)
    split_docs = text_splitter.split_documents(docs)
    pprint.pprint(split_docs)


# text_splitter()
text_splitter2()
