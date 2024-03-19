import requests


def test_build():
    flow_id = '27abf101-050d-4cbc-9b3b-4e912fe14c87'
    headers = {}
    # headers = {
    #     'Cookie':
    #     'access_token_cookie=eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ7XCJ1c2VyX25hbWVcIjogXCJhZG1pblwiLCBcInVzZXJfaWRcIjogMywgXCJyb2xlXCI6IFwiYWRtaW5cIn0iLCJpYXQiOjE3MDQ2OTU3NDQsIm5iZiI6MTcwNDY5NTc0NCwianRpIjoiMDBjNTFhMjUtNWIyNi00MGY4LWFiMTEtNzJhNTYxM2MzOTUyIiwiZXhwIjoxNzA0NzgyMTQ0LCJ0eXBlIjoiYWNjZXNzIiwiZnJlc2giOmZhbHNlfQ.zJxytrpW3J5zxLb9gzo7oImPaQlIqtZ9AE0g2Tx0RZY;'
    # }  # noqa
    # init
    init_url = 'http://127.0.0.1:7860/api/v1/build/init/' + flow_id
    inp = {'chat_id': '1232'}
    requests.post(init_url, json=inp, headers=headers)
    build_url = 'http://127.0.0.1:7860/api/v1/build/stream/' + flow_id

    resp = requests.get(url=build_url, headers=headers)
    resp


test_build()
