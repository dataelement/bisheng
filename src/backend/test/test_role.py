import requests

url_host = 'http://{ip}:{port}/api/v1'.format(ip='127.0.0.1', port=7860)


def test_env():
    requests.get(url_host / 'env')
