import os
import sys

import requests
# from bisheng.database.models.knowledge import KnowledgeCreate

parent_dir = os.path.dirname(os.path.abspath(__file__)).replace('test', '')
sys.path.append(parent_dir)
os.environ['config'] = os.path.join(parent_dir, 'bisheng/config.dev.yaml')

url_host = 'http://{ip}:{port}/api'.format(ip='127.0.0.1', port=7860)


def test_env():
    requests.get(url_host / 'v1/env')


def test_upload():
    file = {'file': open('../../Downloads/合同.pdf', 'rb')}
    resp = requests.post('http://127.0.0.1:7860/api/v2/filelib/file/1',
                         json={'callback_url': '123'},
                         files=file)
    resp


def test_file(knowledge_id: int):
    url = url_host + '/v2/filelib/chunks'
    data = {'knowledge_id': knowledge_id, 'metadata': "{\"url\":\"https://baidu.com\"}"}
    file = {'file': open('/Users/huangly/Downloads/co2.pdf', 'rb')}

    resp = requests.post(url=url, data=data, files=file)
    print(resp.text)
    resp


def string_knowledge(knowledge_id: int):
    url = url_host + '/v2/filelib/chunks_string'
    json_data = {
        'knowledge_id':
        knowledge_id,
        'documents': [{
            'page_content': '达梦有多少专利和知识产权？',
            'metadata': {
                'source': '达梦有多少专利和知识产权？.txt',
                'url': 'http://baidu.com',
                'answer': '达梦共有177个已获授权专利情况，293个软件著作权情况',
                'page': 1
            }
        }]
    }
    resp = requests.post(url=url, json=json_data)
    print(resp.text)
    resp


def test_upload2():
    url = 'http://192.168.106.116:7862/api/v2/filelib/file/252'
    data = {'callback_url': 'https://baidu.com'}
    file = {'file': open('/Users/huangly/Downloads/co2.pdf', 'rb')}

    resp = requests.post(url=url, data=data, files=file)
    resp


def test_create():
    url = url_host + '/v2/filelib/'
    inp = KnowledgeCreate(name='es_index',
                          description='test',
                          model='multilingual-e5-large',
                          user_id=1,
                          is_partition=False)
    resp = requests.post(url=url, json=inp.model_dump())
    print(resp.text)
    return resp


# # test_create()
# test_file(479)
# # string_knowledge(471)
test_upload()
