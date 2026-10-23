from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langchain_core.documents import Document

from bisheng.core.config.settings import KnowledgeConf
from bisheng.knowledge.domain.models.knowledge_file import ParseType
from bisheng.knowledge.rag.base_file_pipeline import BaseFilePipeline
from bisheng.knowledge.rag.pipeline.loader.mineru import MineruLoader
from bisheng.knowledge.rag.pipeline.loader.mineru_v4 import MineruV4Loader
from bisheng.knowledge.rag.pipeline.loader.mineru_v4_client import MineruV4Error
from bisheng.knowledge.rag.pipeline.transformer.preview_cache import PreviewCacheTransformer


class DummyPipeline(BaseFilePipeline):
    @property
    def file_metadata(self) -> dict:
        return {}


def _pipeline(tmp_path, force_ocr=0, retain_images=1):
    pipeline = DummyPipeline(
        invoke_user_id=1,
        file_name="sample.pdf",
        file_rule=SimpleNamespace(filter_page_header_footer=0, force_ocr=force_ocr, retain_images=retain_images),
    )
    pipeline.local_file_path = str(tmp_path / "sample.pdf")
    pipeline.tmp_dir = str(tmp_path)
    pipeline.db_file = SimpleNamespace(parse_type=None)
    return pipeline


def test_new_provider_is_explicit_and_shared_by_pdf_image_ofd(tmp_path):
    pipeline = _pipeline(tmp_path, force_ocr=1)
    config = KnowledgeConf(loader_provider="mineru_v4", mineru_v4={"api_url": "https://mineru.example"})
    with patch("bisheng.knowledge.rag.base_file_pipeline.settings", SimpleNamespace(get_knowledge=lambda: config)):
        pdf = pipeline._init_pdf_loader()
        image = pipeline._init_image_loader()
        ofd = pipeline._init_ofd_loader()._pdf_loader_factory(str(tmp_path / "converted.pdf"))
    assert all(isinstance(loader, MineruV4Loader) for loader in [pdf, image, ofd])
    assert pdf.force_ocr is True
    assert pdf.retain_images is True
    assert pipeline.db_file.parse_type == ParseType.MINERU_V4.value


def test_new_provider_passes_image_retention_rule_to_loader(tmp_path):
    pipeline = _pipeline(tmp_path, retain_images=0)
    config = KnowledgeConf(loader_provider="mineru_v4", mineru_v4={"api_url": "https://mineru.example"})
    with patch("bisheng.knowledge.rag.base_file_pipeline.settings", SimpleNamespace(get_knowledge=lambda: config)):
        loader = pipeline._init_pdf_loader()
    assert isinstance(loader, MineruV4Loader)
    assert loader.retain_images is False


def test_existing_mineru_remains_selected_by_old_provider(tmp_path):
    pipeline = _pipeline(tmp_path)
    config = KnowledgeConf(loader_provider="mineru", mineru={"url": "https://old.example/file_parse"})
    with patch("bisheng.knowledge.rag.base_file_pipeline.settings", SimpleNamespace(get_knowledge=lambda: config)):
        loader = pipeline._init_pdf_loader()
    assert isinstance(loader, MineruLoader)
    assert pipeline.db_file.parse_type == ParseType.MINERU.value


def test_provider_is_selected_when_loader_is_built(tmp_path):
    pipeline = _pipeline(tmp_path)
    selected = {"config": KnowledgeConf(loader_provider="mineru_v4", mineru_v4={"api_url": "https://new.example"})}
    with patch(
        "bisheng.knowledge.rag.base_file_pipeline.settings",
        SimpleNamespace(get_knowledge=lambda: selected["config"]),
    ):
        first = pipeline._init_pdf_loader()
        selected["config"] = KnowledgeConf(loader_provider="mineru", mineru={"url": "https://old.example/file_parse"})
        second = pipeline._init_pdf_loader()
    assert isinstance(first, MineruV4Loader)
    assert isinstance(second, MineruLoader)
    assert pipeline.db_file.parse_type == ParseType.MINERU.value


def test_explicit_new_provider_with_missing_address_fails(tmp_path):
    pipeline = _pipeline(tmp_path)
    config = KnowledgeConf(loader_provider="mineru_v4")
    with patch("bisheng.knowledge.rag.base_file_pipeline.settings", SimpleNamespace(get_knowledge=lambda: config)):
        with pytest.raises(MineruV4Error, match=r"^MinerU V4 API root URL is missing$"):
            pipeline._init_pdf_loader()


def test_preview_cache_uses_existing_user_visible_text():
    visible = {"0": {"text": "Approved preview body", "metadata": {}}}
    utils = SimpleNamespace(get_preview_cache=lambda _: visible, aggregate_chunk_metadata=lambda text, metadata: text)
    with patch("bisheng.knowledge.rag.pipeline.transformer.preview_cache.KnowledgeUtils", utils):
        result = PreviewCacheTransformer("same-key", {}).transform_documents(
            [Document(page_content="New provider body", metadata={})]
        )
    assert len(result) == 1
    assert "Approved preview body" in result[0].page_content
    assert "New provider body" not in result[0].page_content
