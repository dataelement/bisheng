from __future__ import annotations

import copy
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import (
    AbstractSet,
    Any,
    Callable,
    Collection,
    Dict,
    Iterable,
    List,
    Literal,
    Optional,
    Sequence,
    Tuple,
    Type,
    TypedDict,
    TypeVar,
    Union,
    cast,
)

from langchain.docstore.document import Document
from langchain.schema import BaseDocumentTransformer
from langchain.text_splitter import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)


class ElemCharacterTextSplitter(RecursiveCharacterTextSplitter):
    """
    todo
    """
    def split_documents(self, documents: Iterable[Document]) -> List[Document]:
        texts, metadatas = [], []
        for doc in documents:
            texts.append(doc.page_content)
            metadatas.append(doc.metadata)

        return self.create_documents(texts, metadatas=metadatas)

    def split_text(self, text):
        split_texts = []
        split_texts_range = []
        start_index = 0
        while start_index < len(text):
            split_texts.append(text[start_index:start_index+self._chunk_size])
            split_texts_range.append(
                [start_index, start_index+len(split_texts[-1])-1])
            start_index += self._chunk_size
        return split_texts, split_texts_range

    def create_documents(
        self, texts: List[str], metadatas: Optional[List[dict]] = None
    ) -> List[Document]:
        """Create documents from a list of texts."""
        _metadatas = metadatas or [{}] * len(texts)
        documents = []
        for i, text in enumerate(texts):
            metadata = copy.deepcopy(_metadatas[i])
            split_texts, split_texts_range = self.split_text(text)
            for chunk, chunk_range in zip(split_texts, split_texts_range):
                new_metadata = {}
                new_metadata['chunk_type'] = metadata.get('chunk_type', 'paragraph')
                new_metadata['bboxes'] = metadata.get('bboxes', [])
                new_metadata['source'] = metadata.get('source', '')
                new_metadata['start'] = metadata.get('start', 0) + chunk_range[0]
                new_metadata['end'] = metadata.get('start', 0) + chunk_range[1]
                if 'page' in metadata:
                    new_metadata['page'] = metadata['page'][new_metadata['start']:new_metadata['end']+1]
                if 'token_to_bbox' in metadata:
                    new_metadata['token_to_bbox'] = metadata['token_to_bbox'][new_metadata['start']:new_metadata['end']+1]

                new_doc = Document(page_content=chunk, metadata=new_metadata)
                documents.append(new_doc)
        return documents

