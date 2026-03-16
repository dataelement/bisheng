from typing import Any, List

from langchain_community.document_loaders import TextLoader
from langchain_core.documents import Document

from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader


class BishengTextLoader(BaseBishengLoader):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.text_loader = TextLoader(file_path=self.file_path, autodetect_encoding=True)

    def load(self) -> List[Document]:
        documents = self.text_loader.load()
        for item in documents:
            item.metadata = item.metadata.update(self.file_metadata.copy())
        return documents
