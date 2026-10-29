"""Uploader name lookup in temp/preview pipelines must not fail the file parse.

Regression: on 2026-10-27 MySQL hit ``1040 Too many connections`` and
``TempFilePipeline.file_metadata`` raised from ``UserDao.get_user``, which failed
the whole task-mode attachment parse even though uploader is display-only.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy.exc import OperationalError

from bisheng.knowledge.rag.preview_file_pipeline import PreviewFilePipeline
from bisheng.knowledge.rag.temp_file_pipeline import TempFilePipeline

GET_USER = "bisheng.knowledge.rag.base_file_pipeline.UserDao.get_user"


def _too_many_connections(*_args, **_kwargs):
    raise OperationalError("SELECT user", {}, Exception("(1040, 'Too many connections')"))


def _build(kind: str):
    if kind == "temp":
        return TempFilePipeline(1, "/tmp/a.pdf", "a.pdf")
    return PreviewFilePipeline(1, "/tmp/a.pdf", "a.pdf", knowledge_id=3)


@pytest.mark.parametrize("kind", ["temp", "preview"])
def test_file_metadata_degrades_when_user_lookup_fails(kind):
    pipeline = _build(kind)
    with patch(GET_USER, side_effect=_too_many_connections) as mocked:
        metadata = pipeline.file_metadata

    mocked.assert_called_once_with(1)
    assert metadata["document_name"] == "a.pdf"
    assert "uploader" not in metadata
    assert "updater" not in metadata


@pytest.mark.parametrize("kind", ["temp", "preview"])
def test_file_metadata_keeps_uploader_name_on_success(kind):
    pipeline = _build(kind)
    with patch(GET_USER, return_value=SimpleNamespace(user_name="alice")):
        metadata = pipeline.file_metadata

    assert metadata["uploader"] == "alice"
    assert metadata["updater"] == "alice"


def test_file_metadata_missing_user_yields_no_uploader():
    pipeline = _build("temp")
    with patch(GET_USER, return_value=None):
        metadata = pipeline.file_metadata

    assert "uploader" not in metadata


def test_non_db_errors_still_propagate():
    pipeline = _build("temp")
    with patch(GET_USER, side_effect=RuntimeError("bug")), pytest.raises(RuntimeError):
        _ = pipeline.file_metadata
