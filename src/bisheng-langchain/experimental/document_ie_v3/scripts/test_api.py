import requests

data = {'file_name': 'test.pdf', 'file_b64': 'base64', 'schema': 'schema'}
url = 'http://localhost:5000/test_api'
headers = {'Content-Type': 'application/json'}
response = requests.post(url, json=data, headers=headers)
print(response.content)
