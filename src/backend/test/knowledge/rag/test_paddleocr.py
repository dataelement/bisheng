import unittest

from bisheng.knowledge.rag.pipeline.loader.paddle_ocr import PaddleOcrLoader
from bisheng.knowledge.rag.pipeline.transformer.splitter import SplitterTransformer


class PaddleOcrTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp_dir = "/Users/zhangguoqing/works/bisheng/src/backend/test/knowledge/rag"
        self.file_path = "/Users/zhangguoqing/works/bisheng/src/backend/test/knowledge/rag/test1.pdf"
        self.url = ""

    def test_load(self):
        loader = PaddleOcrLoader(
            file_path=self.file_path,
            file_metadata={},
            file_extension="pdf",
            tmp_dir=self.tmp_dir,

            url=self.url,
            timeout=60,
            auth_token=""
        )

        documents = loader.load()
        assert len(documents) == 1, "documents not equal 1"

        splitter = SplitterTransformer(separator=["\\n\\n", "\\n"], separator_rule=["after", "after"], chunk_size=100,
                                       chunk_overlap=10)
        new_document = splitter.transform_documents(documents)

        assert isinstance(new_document, list), "new_document is not a list"
