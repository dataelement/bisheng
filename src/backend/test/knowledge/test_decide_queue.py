from unittest.mock import patch

import pytest

from bisheng.worker.knowledge.scheduler import (
    decide_queue,
    needs_ocr_queue,
)


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


def test_pdf_needs_ocr_only_when_loader_configured(loader_configured):
    assert needs_ocr_queue("pdf") is True


def test_pdf_skips_ocr_when_loader_missing(loader_not_configured):
    assert needs_ocr_queue("pdf") is False


def test_other_extensions_never_need_ocr(loader_configured):
    assert needs_ocr_queue("docx") is False
    assert needs_ocr_queue("txt") is False
    assert needs_ocr_queue("") is False


def test_decide_queue_disabled_returns_knowledge_celery(loader_configured):
    with patch(
        "bisheng.worker.knowledge.scheduler._ocr_queue_enabled",
        return_value=False,
    ):
        assert decide_queue("a.pdf") == "knowledge_celery"
        assert decide_queue("a.png") == "knowledge_celery"


def test_decide_queue_enabled_routes_by_extension(loader_configured):
    with patch(
        "bisheng.worker.knowledge.scheduler._ocr_queue_enabled",
        return_value=True,
    ):
        assert decide_queue("invoice.pdf") == "ocr_celery"
        assert decide_queue("photo.PNG") == "ocr_celery"
        assert decide_queue("notes.txt") == "knowledge_celery"
        assert decide_queue("no_extension") == "knowledge_celery"
