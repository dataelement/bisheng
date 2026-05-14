from typing import List

from langchain_community.document_loaders import TextLoader
from langchain_core.documents import Document

from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader


class BishengTextLoader(BaseBishengLoader):

    def load(self) -> List[Document]:
        text_loader = TextLoader(file_path=self.file_path, autodetect_encoding=True)
        documents = text_loader.load()
        for item in documents:
            item.metadata = self.file_metadata.copy()
        return documents
