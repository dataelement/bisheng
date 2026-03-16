import os
import shutil
from typing import List

from langchain_core.documents import Document

from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.loader.md_from_excel import convert_file_to_markdown


class ExcelLoader(BaseBishengLoader):
    def __init__(self, header_rows: List[int] = None, data_rows: int = 12, append_header=True,
                 *args, **kwargs):
        super(ExcelLoader, self).__init__(*args, **kwargs)
        self.header_rows = header_rows or [0, 1]
        self.data_rows = data_rows
        self.append_header = append_header

    def load(self) -> List[Document]:
        md_file_path = os.path.join(self.tmp_dir, "chunks_md")
        os.makedirs(md_file_path, exist_ok=True)

        md_file_path = convert_file_to_markdown(input_file_path=self.file_path,
                                                num_header_rows=self.header_rows,
                                                rows_per_markdown=self.data_rows,
                                                base_output_dir=md_file_path,
                                                append_header=self.append_header)

        files = sorted([f for f in os.listdir(md_file_path)])

        # A file corresponds to only one complete Document Objects, texts It is only after cuttingchunkContents
        documents = []

        for chunk_index, file_name in enumerate(files):
            full_file_name = f"{md_file_path}/{file_name}"
            with open(full_file_name, "r", encoding="utf-8") as f:
                content = f.read()
                one_metadata = self.file_metadata.copy()
                one_metadata["chunk_index"] = chunk_index
                documents.append(Document(page_content=content, metadata=self.file_metadata.copy()))

        shutil.rmtree(md_file_path)
        return documents
