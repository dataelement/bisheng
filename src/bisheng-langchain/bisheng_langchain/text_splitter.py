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


def _split_text_with_regex(
    text: str, separator: str, keep_separator: bool
) -> List[str]:
    # Now that we have the separator, split the text
    if separator:
        if keep_separator:
            # The parentheses in the pattern keep the delimiters in the result.
            _splits = re.split(f"({separator})", text)
            splits = [_splits[i] + _splits[i + 1] for i in range(1, len(_splits), 2)]
            if len(_splits) % 2 == 0:
                splits += _splits[-1:]
            splits = [_splits[0]] + splits
        else:
            splits = re.split(separator, text)
    else:
        splits = list(text)
    return [s for s in splits if s != ""]


class ElemCharacterTextSplitter(RecursiveCharacterTextSplitter):
    """
    todo
    """
    def __init__(
        self,
        separators: Optional[List[str]] = None,
        keep_separator: bool = True,
        is_separator_regex: bool = False,
        **kwargs: Any,
    ) -> None:
        """Create a new TextSplitter."""
        super().__init__(
            separators=separators,
            keep_separator=keep_separator,
            is_separator_regex=is_separator_regex,
            **kwargs
        )
        self._separators = separators or ["\n\n", "\n", " ", ""]
        self._is_separator_regex = is_separator_regex

    def split_documents(self, documents: Iterable[Document]) -> List[Document]:
        texts, metadatas = [], []
        for doc in documents:
            texts.append(doc.page_content)
            metadatas.append(doc.metadata)

        return self.create_documents(texts, metadatas=metadatas)

    def _split_text(self, text: str, separators: List[str]) -> List[str]:
        """Split incoming text and return chunks."""
        final_chunks = []
        # Get appropriate separator to use
        separator = separators[-1]
        new_separators = []
        for i, _s in enumerate(separators):
            _separator = _s if self._is_separator_regex else re.escape(_s)
            if _s == "":
                separator = _s
                break
            if re.search(_separator, text):
                separator = _s
                new_separators = separators[i + 1 :]
                break

        _separator = separator if self._is_separator_regex else re.escape(separator)
        splits = _split_text_with_regex(text, _separator, self._keep_separator)

        # Now go merging things, recursively splitting longer texts.
        _good_splits = []
        _separator = "" if self._keep_separator else separator
        for s in splits:
            if self._length_function(s) < self._chunk_size:
                _good_splits.append(s)
            else:
                if _good_splits:
                    merged_text = self._merge_splits(_good_splits, _separator)
                    final_chunks.extend(merged_text)
                    _good_splits = []
                if not new_separators:
                    final_chunks.append(s)
                else:
                    other_info = self._split_text(s, new_separators)
                    final_chunks.extend(other_info)
        if _good_splits:
            merged_text = self._merge_splits(_good_splits, _separator)
            final_chunks.extend(merged_text)
        return final_chunks

    def split_text(self, text: str) -> List[str]:
        return self._split_text(text, self._separators)

    def create_documents(
        self, texts: List[str], metadatas: Optional[List[dict]] = None
    ) -> List[Document]:
        """Create documents from a list of texts."""
        _metadatas = metadatas or [{}] * len(texts)
        documents = []
        for i, text in enumerate(texts):
            index = -1
            metadata = copy.deepcopy(_metadatas[i])
            split_texts = self.split_text(text)
            for chunk in split_texts:
                new_metadata = {}
                new_metadata['chunk_type'] = metadata.get('chunk_type', 'paragraph')
                new_metadata['bboxes'] = metadata.get('bboxes', [])
                new_metadata['source'] = metadata.get('source', '')
                # chunk's start index in text
                index = text.find(chunk, index + 1)
                new_metadata['start'] = metadata.get('start', 0) + index
                new_metadata['end'] = metadata.get('start', 0) + index + len(chunk) - 1

                if 'page' in metadata:
                    new_metadata['page'] = metadata['page'][new_metadata['start']:new_metadata['end']+1]
                if 'token_to_bbox' in metadata:
                    new_metadata['token_to_bbox'] = metadata['token_to_bbox'][new_metadata['start']:new_metadata['end']+1]

                new_doc = Document(page_content=chunk, metadata=new_metadata)
                documents.append(new_doc)
        return documents



