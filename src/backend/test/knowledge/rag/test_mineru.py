import unittest

from bisheng.knowledge.rag.pipeline.loader.mineru import MineruLoader
from bisheng.knowledge.rag.pipeline.transformer.splitter import SplitterTransformer


class MineruTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp_dir = "/Users/zhangguoqing/works/bisheng/src/backend/test/knowledge/rag"
        self.file_path = "/Users/zhangguoqing/works/bisheng/src/backend/test/knowledge/rag/test1.pdf"
        self.url = "http://192.168.106.20:8033/file_parse"

    def test_load(self):
        loader = MineruLoader(
            file_path=self.file_path,
            file_metadata={},
            file_extension="pdf",
            tmp_dir=self.tmp_dir,

            url=self.url,
        )
        documents = loader.load()
        assert len(documents) == 1, "documents not equal 1"

        splitter = SplitterTransformer(separator=["\\n\\n", "\\n"], separator_rule=["after", "after"], chunk_size=100,
                                       chunk_overlap=10)
        new_document = splitter.transform_documents(documents)

        assert isinstance(new_document, list), "new_document is not a list"
