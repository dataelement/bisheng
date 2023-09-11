import base64
import json
# import time
from typing import List, Optional

import requests
from langchain.document_loaders.blob_loaders import Blob
from langchain.schema import Document


class LayoutParser(object):
    """Parse image layout structure.
    """

    def __init__(self,
                 api_key: Optional[str] = None,
                 api_base_url: Optional[str] = None):
        self.api_key = api_key
        self.api_base_url = 'http://192.168.106.20:14569/predict'
        self.class_name = ['印章', '图片', '标题', '段落', '表格', '页眉', '页码', '页脚']

    def parse(self, blob: Blob) -> List[Document]:
        b64_data = base64.b64encode(blob.as_bytes()).decode()
        data = {'img': b64_data}
        resp = requests.post('http://192.168.106.20:14569/predict', data=data)
        content = resp.json()
        doc = Document(page_content=json.dumps(content), metadata={})
        return [doc]
