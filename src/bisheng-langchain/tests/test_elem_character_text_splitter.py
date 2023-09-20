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


text_splitter()
