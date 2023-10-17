from bisheng_langchain.document_loaders import ElemUnstructuredLoader
from bisheng_langchain.document_loaders.elem_unstrcutured_loader import ElemUnstructuredLoaderV0


def test_loader():
    loader = ElemUnstructuredLoader('./data/dummy.txt')
    docs = loader.load()
    print('docs', docs)


def test_elem_loader2():
    url = 'http://192.168.106.12:10001/v1/etl4llm/predict'
    loader = ElemUnstructuredLoaderV0(
        file_name='毛泽东课件.pptx',
        file_path='./data/毛泽东课件.pptx',
        unstructured_api_url=url)

    docs = loader.load()
    print('docs', docs)


def test_elem_loader():
    url = 'http://192.168.106.12:10001/v1/etl4llm/predict'
    loader = ElemUnstructuredLoader(
        file_name='达梦数据库招股说明书.pdf',
        file_path='./data/达梦数据库招股说明书.pdf',
        unstructured_api_url=url,
        start=0,
        n=10)
    docs = loader.load()
    print('docs', docs)


# test_loader()
# test_elem_loader2()
test_elem_loader()
