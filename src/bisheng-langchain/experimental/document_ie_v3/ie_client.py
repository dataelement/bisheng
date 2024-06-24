import base64
import os

import requests

pdf_path = '/home/public/huatai/流动资金借款合同_pdf/JYT11.pdf'
schema = '合同标题|合同编号|借款人|贷款人|借款金额'

def predict_one_pdf(pdf_path, schema):
    data = {}
    data['file_name'] = os.path.basename(pdf_path)
    data['file_b64'] = base64.b64encode(open(pdf_path, 'rb').read()).decode()
    data['schema'] = schema

    url = "http://0.0.0.0:6118/document_ie"
    headers = {"Content-Type": "application/json"}
    r = requests.post(url=url, headers=headers, json=data).json()
    print(r)
