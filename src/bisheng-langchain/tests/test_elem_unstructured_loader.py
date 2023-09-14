from bisheng_langchain.document_loaders import ElemUnstructuredLoader


def test_loader():
    loader = ElemUnstructuredLoader('./data/dummy.txt')
    docs = loader.load()
    print('docs', docs)


test_loader()
