import requests

url_host = 'http://{ip}:{port}/api/v1'.format(ip='127.0.0.1', port=7860)


def test_env():
    requests.get(url_host / 'env')


def test_upload():
    file = {'file': open('/Users/huangly/Downloads/co2.pdf', 'rb')}
    resp = requests.post('http://127.0.0.1:7860/api/v2/filelib/file/1',
                         json={'callback_url': '123'},
                         files=file)
    resp


def test_file():
    url = 'http://192.168.106.116:7860/api/v2/filelib/chunks'
    data = {'knowledge_id': 349, 'metadata': "{\"url\":\"https://baidu.com\"}"}
    file = {'file': open('/Users/huangly/Downloads/co2.pdf', 'rb')}

    resp = requests.post(url=url, data=data, files=file)
    resp


def test_upload2():
    url = 'http://192.168.106.116:7862/api/v2/filelib/file/252'
    data = {'callback_url': 'https://baidu.com'}
    file = {'file': open('/Users/huangly/Downloads/co2.pdf', 'rb')}

    resp = requests.post(url=url, data=data, files=file)
    resp


# test_file()
test_upload()
