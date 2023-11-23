# flake8: noqa
"""Loads PDF with semantic splilter."""
import base64
import logging
import os
import tempfile
from pathlib import Path
from time import sleep
from typing import Iterator, List, Tuple, Union

import cv2
import fitz
import numpy as np
import requests
from langchain.docstore.document import Document
from langchain.document_loaders.base import BaseLoader
from langchain.load.serializable import Serializable
from PIL import Image

logger = logging.getLogger(__name__)

def convert_base64(image):
    image_binary = cv2.imencode('.jpg', image)[1].tobytes()
    x = base64.b64encode(image_binary)
    return x.decode('ascii').replace('\n', '')


def transpdf2png(pdf_file):
    pdf_bytes = open(pdf_file, 'rb').read()
    pdf = fitz.Document(stream=pdf_bytes, filetype='pdf')
    dpis = [72, 144, 200]

    pdf_images = dict()
    for page in pdf:
        pix = None
        for dpi in dpis:
            pix = page.get_pixmap(dpi=dpi)
            if min(pix.width, pix.height) >= 1600: break

        mode = 'RGBA' if pix.alpha else 'RGB'
        img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
        # RGB to BGR
        img = np.array(img)[:, :, ::-1]
        img_name = 'page_{:03d}'.format(page.number)
        pdf_images[img_name] = img

    return pdf_images


class CustomKVLoader(BaseLoader, Serializable):
    """Extract key-value from pdf or image.
    """
    elm_api_base_url: str
    elm_api_key: str
    elem_server_id: str
    task_type: str
    schemas: str

    def __init__(self, file_path:str,
                 elm_api_base_url: str,
                 elm_api_key: str,
                 schemas: str,
                 elem_server_id: str,
                 task_type: str,
                 request_timeout: Union[float, Tuple[float, float]]) -> None:
        """Initialize with a file path."""
        self.file_path = file_path
        self.elm_api_base_url = elm_api_base_url
        self.elm_api_key = elm_api_key
        self.elem_server_id = elem_server_id
        self.task_type = task_type
        self.schemas = schemas
        self.headers = {'Authorization': f'Bearer {elm_api_key}'}
        self.timeout = request_timeout
        if '~' in self.file_path:
            self.file_path = os.path.expanduser(self.file_path)

        # If the file is a web path, download it to a temporary file, and use that
        if not os.path.isfile(self.file_path) and self._is_valid_url(self.file_path):
            r = self.request.get(self.file_path)

            if r.status_code != 200:
                raise ValueError(
                    'Check the url of your file; returned status code %s'
                    % r.status_code
                )

            self.temp_dir = tempfile.TemporaryDirectory()
            temp_file = Path(self.temp_dir.name) / 'tmp.pdf'
            with open(temp_file, mode='wb') as f:
                f.write(r.content)
            self.file_path = str(temp_file)
        elif not os.path.isfile(self.file_path):
            raise ValueError('File path %s is not a valid file or url' % self.file_path)
        super().__init__()


    def load(self) -> List[Document]:
        """Load given path as pages."""
        return list(self.lazy_load())

    def lazy_load(
        self,
    ) -> Iterator[Document]:
        """Lazy load given path as pages."""

        blob = Blob.from_path(self.file_path)
        yield from self.parser.parse(blob)


    def load(self) -> List[Document]:
        """Load given path as pages."""
        # mime_type = filetype.guess(self.file_path).mime
        # if mime_type.endswith('pdf'):
        #     file_type = 'pdf'
        # elif mime_type.startswith('image'):
        #     file_type = 'img'

        # else:
        #     raise ValueError(f'file type {file_type} is not support.')
        file = {'file': open(self.file_path, 'rb')}
        if self.task_type == 'task':
            url = self.elm_api_base_url + '/task'
            # 创建task
            body = {'scene_id': self.elem_server_id}
            resp = requests.post(url=url, data=body, files=file, headers=self.headers)
            if resp.status_code == 200:
                task_id = resp.json.get('task_id')
                # get status
                status_url = self.elm_api_base_url + f'/task/status?task_id={task_id}'
                count = 0
                while True:
                    status = requests.get(status_url, headers=self.headers).json()
                    if 1 == status.get('data').get('status') and count <10:
                        count += 1
                        sleep(2)
                    else:
                        break
                # get result
                result_url = self.elm_api_base_url + f'/task/result?task_id={task_id}'
                result = requests.get(status_url, headers=self.headers).json()

            else:
                logger.error(f'custom_kv=create_task resp={resp.text}')
                raise Exception('custom_kv create task file')




        elif self.task_type == 'logic-job':
            url = self.ellm_api_base_url + '/logic-job'
            body = {'logic_service_id': self.elem_server_id}


        resp = requests.post(url=url, data=body, files=file, headers=self.headers)
        doc = Document(page_content=content, metadata=meta)
        return [doc]
