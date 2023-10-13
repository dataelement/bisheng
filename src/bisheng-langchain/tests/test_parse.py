import base64
from bisheng_langchain.document_loaders.parsers.ocr_client import OCRClient
from bisheng_langchain.document_loaders.parsers.ellm_client import ELLMClient


def test_ocr():
    api_base_url = 'http://192.168.106.20:4502/v2/idp/idp_app/infer'
    model = OCRClient(api_base_url)

    test_image = 'data/maoxuan_mulu.jpg'
    bytes_data = open(test_image, 'rb').read()
    b64data = base64.b64encode(bytes_data).decode()
    inp = {'b64_image': b64data}
    outp = model.predict(inp)
    print(outp)


def test_ellm():
    api_base_url = 'http://192.168.106.20:4502/v2/idp/idp_app/infer'
    model = ELLMClient(api_base_url)

    test_image = 'data/maoxuan_mulu.jpg'
    bytes_data = open(test_image, 'rb').read()
    b64data = base64.b64encode(bytes_data).decode()
    inp = {'b64_image': b64data, 'keys': '标题'}
    outp = model.predict(inp)
    print(outp)


# test_ocr()
test_ellm()
