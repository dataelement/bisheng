from bisheng_langchain.document_loaders import UniversalKVLoader
from bisheng_langchain.chains import LoaderOutputChain


def test_universal_kv_loader1():
    url = 'http://192.168.106.20:4502/v2/idp/idp_app/infer'
    loader = UniversalKVLoader(
        file_path='./data/whzm.jpeg',
        ellm_model_url=url,
        schema='税务机关|纳税人识别号|纳税人名称|原凭证号',
        max_pages=30
        )
    doc = loader.load()
    print(doc)
    return doc


def test_universal_kv_loader2():
    url = 'http://192.168.106.20:4502/v2/idp/idp_app/infer'
    loader = UniversalKVLoader(
        file_path='./data/个人经营性贷款材料.pdf',
        ellm_model_url=url,
        schema='借款申请人姓名|借款申请人最高学历|借款申请人家庭净资产额|授信金额',
        max_pages=30
        )
    doc = loader.load()
    print(doc)
    return doc


def test_loader_output_chain():
    doc1 = test_universal_kv_loader1()
    doc2 = test_universal_kv_loader2()
    doc = doc1 + doc2
    chain = LoaderOutputChain(documents=doc)
    print(chain('开始', return_only_outputs=True)['text'])


# test_universal_kv_loader1()
# test_universal_kv_loader2()
test_loader_output_chain()