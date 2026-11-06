from unittest.mock import patch

import pytest

from bisheng.core.config.settings import KnowledgeConf, KnowledgeFileWorkerConf
from bisheng.worker.knowledge.scheduler import (
    KNOWLEDGE_QUEUE,
    decide_queue,
    needs_ocr_queue,
)

_OCR_QUEUE_DEFAULT = KnowledgeFileWorkerConf().ocr_queue


@pytest.fixture
def loader_configured():
    with patch(
        "bisheng.worker.knowledge.scheduler._loader_configured",
        return_value=True,
    ) as m:
        yield m


@pytest.fixture
def loader_not_configured():
    with patch(
        "bisheng.worker.knowledge.scheduler._loader_configured",
        return_value=False,
    ) as m:
        yield m


@pytest.mark.parametrize("ext", ["png", "jpg", "jpeg", "bmp", "JPG", "PNG"])
def test_images_always_need_ocr(loader_not_configured, ext):
    assert needs_ocr_queue(ext) is True


@pytest.mark.parametrize("ext", ["pdf", "ofd"])
def test_pdf_based_formats_need_ocr_only_when_loader_configured(loader_configured, ext):
    assert needs_ocr_queue(ext) is True


@pytest.mark.parametrize("ext", ["pdf", "ofd"])
def test_pdf_based_formats_skip_ocr_when_loader_missing(loader_not_configured, ext):
    assert needs_ocr_queue(ext) is False


def test_other_extensions_never_need_ocr(loader_configured):
    assert needs_ocr_queue("docx") is False
    assert needs_ocr_queue("txt") is False
    assert needs_ocr_queue("") is False


def test_decide_queue_disabled_returns_knowledge_celery(loader_configured):
    with patch(
        "bisheng.worker.knowledge.scheduler._ocr_queue_enabled",
        return_value=False,
    ):
        assert decide_queue("a.pdf") == KNOWLEDGE_QUEUE
        assert decide_queue("a.ofd") == KNOWLEDGE_QUEUE
        assert decide_queue("a.png") == KNOWLEDGE_QUEUE


def test_decide_queue_enabled_routes_by_extension(loader_configured):
    with patch(
        "bisheng.worker.knowledge.scheduler._ocr_queue_enabled",
        return_value=True,
    ):
        assert decide_queue("invoice.pdf") == _OCR_QUEUE_DEFAULT
        assert decide_queue("invoice.OFD") == _OCR_QUEUE_DEFAULT
        assert decide_queue("photo.PNG") == _OCR_QUEUE_DEFAULT
        assert decide_queue("notes.txt") == KNOWLEDGE_QUEUE
        assert decide_queue("no_extension") == KNOWLEDGE_QUEUE


def test_mineru_v4_configuration_enables_ocr_routing():
    enabled = KnowledgeConf(loader_provider="mineru_v4", mineru_v4={"api_url": "https://mineru.example"})
    disabled = KnowledgeConf(loader_provider="mineru_v4")
    assert enabled.image_parser_enabled is True
    assert disabled.image_parser_enabled is False
