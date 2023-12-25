def _test_python_code():
    from bisheng import load_flow_from_json

    TWEAKS = {
        'PyPDFLoader-RJlDA': {},
        'InputFileNode-hikjJ': {
            'file_path':
            'https://bisheng.dataelem.com/bisheng/1673?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=minioadmin%2F20231025%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20231025T093224Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=b124b651adcfb0aa3c86d821072fa81d3f8e7b42a39ec517f1d146353ef6867b'  # noqa
        },
        'InputNode-keWk3': {},
        'Milvus-VzZtx': {},
        'RetrievalQA-Y4e1R': {},
        'CombineDocsChain-qrRE4': {},
        'RecursiveCharacterTextSplitter-C6YSc': {},
        'ProxyChatLLM-oWqpn': {
            'elemai_api_key':
            'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiaXNoZW5nX29wZW42IiwiZXhwIjoxNzEzNzU0MjUyfQ.ww1l-GTBYJiHV3-U1JcacvWOqYPd-QMpuJIeuO9_OM8'  # noqa
        },
        'HostEmbeddings-EJq6w': {}
    }
    flow = load_flow_from_json('/Users/huangly/Downloads/⭐️ PDF文档摘要-zxf.json', tweaks=TWEAKS)
    # Now you can use it like any chain
    inputs = {'query': '合同甲方是谁', 'id': 'RetrievalQA-Y4e1R'}
    print(flow(inputs))


def _test_uns():

    import base64
    import requests

    # 使用场景1： 文件到tokens
    url = 'http://192.168.106.12:10001/v1/etl4llm/predict'

    filename = '/Users/huangly/Downloads/合同(1).pdf'
    b64_data = base64.b64encode(open(filename, 'rb').read()).decode()
    filename_type = '合同(1).pdf'

    inp = dict(filename=filename_type,
               b64_data=[b64_data],
               mode='partition',
               parameters={
                   'start': 0,
                   'n': None
               })

    resp = requests.post(url, json=inp).json()
    print(resp)


def test_input():
    from bisheng_langchain.input_output import InputNode
    param = {'input': [1]}
    a = InputNode(**param)
    print(a)


# _test_python_code()
# _test_uns()
test_input()
