# flake8: noqa
"""Loads PDF with semantic splilter."""
import base64
import io
import json
import logging
import os
import re
import tempfile
import time
import filetype
import cv2
from collections import defaultdict
from abc import ABC
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator, List, Mapping, Optional, Union
from urllib.parse import urlparse
from PIL import Image

import fitz
import numpy as np
import requests
from langchain.docstore.document import Document
from langchain.document_loaders.base import BaseLoader
from bisheng_langchain.document_loaders.parsers import ELLMClient, OCRClient


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

        mode = "RGBA" if pix.alpha else "RGB"
        img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
        # RGB to BGR
        img = np.array(img)[:, :, ::-1]
        img_name = "page_{:03d}".format(page.number)
        pdf_images[img_name] = img

    return pdf_images


class UniversalKVLoader(BaseLoader):
    """Extract key-value from pdf or image.
    """
    def __init__(self,
                 file_path: str,
                 ellm_model_url: str = None,
                 schema='',
                 max_pages=30,
                 verbose: bool = False) -> None:
        """Initialize with a file path."""
        self.file_path = file_path
        self.schema = schema
        self.max_pages = max_pages
        self.ellm_model = ELLMClient(ellm_model_url)
        super().__init__()

    def load(self) -> List[Document]:
        """Load given path as pages."""
        mime_type = filetype.guess(self.file_path).mime
        if mime_type.endswith('pdf'):
            file_type = 'pdf'
        elif mime_type.startswith('image'):
            file_type = 'img'
        else:
            raise ValueError(f"file type {file_type} is not support.")

        if file_type == 'img':
            bytes_data = open(self.file_path, 'rb').read()
            b64data = base64.b64encode(bytes_data).decode()
            payload = {'b64_image': b64data, 'keys': self.schema}
            resp = self.ellm_model.predict(payload)

            if 'code' in resp and resp['code'] == 200:
                key_values = resp['result']['ellm_result']
            else:
                raise ValueError(f"universal kv load failed: {resp}")

            kv_results = defaultdict(list)
            for key, value in key_values.items():
                kv_results[key] = value['text']

            content = json.dumps(kv_results, indent=2, ensure_ascii=False)
            file_name = os.path.basename(self.file_path)
            meta = {'source': file_name}
            doc = Document(page_content=content, metadata=meta)
            return [doc]

        elif file_type == 'pdf':
            pdf_images = transpdf2png(self.file_path)

            kv_results = defaultdict(list)
            for pdf_name in pdf_images:
                page = int(pdf_name.split('page_')[-1])
                if page > self.max_pages:
                    continue

                b64data = convert_base64(pdf_images[pdf_name])
                payload = {'b64_image': b64data, 'keys': self.schema}
                resp = self.ellm_model.predict(payload)

                if 'code' in resp and resp['code'] == 200:
                    key_values = resp['result']['ellm_result']
                else:
                    raise ValueError(f"universal kv load failed: {resp}")

                for key, value in key_values.items():
                    kv_results[key].extend(value['text'])

            content = json.dumps(kv_results, indent=2, ensure_ascii=False)
            file_name = os.path.basename(self.file_path)
            meta = {'source': file_name}
            doc = Document(page_content=content, metadata=meta)
            return [doc]

