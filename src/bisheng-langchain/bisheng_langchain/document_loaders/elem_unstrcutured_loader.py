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
from abc import ABC
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator, List, Mapping, Optional, Union
from urllib.parse import urlparse

import fitz
import numpy as np
import pypdfium2
import requests
from bisheng_langchain.document_loaders.parsers import LayoutParser
from langchain.docstore.document import Document
from langchain.document_loaders.blob_loaders import Blob
from langchain.document_loaders.pdf import BasePDFLoader
from shapely import Polygon
from shapely import box as Rect


class ElemUnstructuredLoader(BasePDFLoader):
    """Loads a PDF with pypdf and chunks at character level. dummy version

    Loader also stores page numbers in metadata.
    """
    def __init__(self,
                 file_path: str,
                 unstructured_api_key: str = None,
                 unstructured_api_url: str = None,
                 start: int = 0,
                 n: int = None,
                 verbose: bool = False) -> None:
        """Initialize with a file path."""
        super().__init__(file_path)


    def load(self) -> List[Document]:
        """Load given path as pages."""
        page_content = '《毛泽东选集》第一至四卷, 在五十年代初和六十年代初先后出版,距今已有三四十年。'

        bboxes = [
            [60, 700, 540, 700, 540, 730, 60, 730],
            [60, 740, 540, 740, 540, 770, 60, 770]
        ]

        page = [1] * 40
        source = 'maozedong_xuanji.pdf'
        start = 0
        end = 39
        chunk_type = 'paragraph'
        token_to_bbox = [0] * 20 + [1] * 20
        meta = {
            'bboxes': bboxes, 'page': page, 'source': source,
            'start': start, 'end': end, 'chunk_type': chunk_type,
            'token_to_bbox': token_to_bbox
        }
        doc = Document(page_content=page_content, metadata=meta)
        return [doc]


class ElemUnstructuredLoaderV0(BasePDFLoader):
    """Loads a PDF with pypdf and chunks at character level. dummy version

    Loader also stores page numbers in metadata.
    """
    def __init__(self,
                 file_path: str,
                 unstructured_api_key: str = None,
                 unstructured_api_url: str = None,
                 start: int = 0,
                 n: int = None,
                 verbose: bool = False) -> None:
        """Initialize with a file path."""
        self.unstructured_api_url = unstructured_api_url
        self.unstructured_api_key = unstructured_api_key
        self.headers = {'Content-Type': 'application/json'}
        super().__init__(file_path)

    def load(self) -> List[Document]:
        filename = self.file_path
        b64_data = base64.b64encode(open(filename, 'rb').read()).decode()
        payload = dict(
            filename=os.path.basename(filename),
            b64_data=[b64_data],
            mode='text')

        resp = requests.post(
            self.unstructured_api_url,
            headers=self.headers,
            json=payload).json()

        page_content = resp['text']
        meta = {'source': filename}
        doc = Document(page_content=page_content, metadata=meta)
        return [doc]
