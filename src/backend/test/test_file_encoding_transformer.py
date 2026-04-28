"""Unit tests for FileEncodingTransformer pure logic."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import bisheng.knowledge.rag.pipeline.transformer.file_encoding as _enc_mod
from bisheng.knowledge.rag.pipeline.transformer.file_encoding import (
    FileEncodingTransformer,
    VALID_PATTERN,
    FALLBACK,
)


def test_valid_pattern_accepts_known_combinations():
    assert VALID_PATTERN.match("ZD-SC")
    assert VALID_PATTERN.match("JSTZ-XX")
    assert VALID_PATTERN.match("HYJY-AQ")
    assert VALID_PATTERN.match("JSXY-NY")


def test_valid_pattern_rejects_invalid():
    assert not VALID_PATTERN.match("ZD-OT")
    assert not VALID_PATTERN.match("OT-SC")
    assert not VALID_PATTERN.match("zd-sc")
    assert not VALID_PATTERN.match("ZD - SC")
    assert not VALID_PATTERN.match("ZD-SC-extra")
    assert not VALID_PATTERN.match("```ZD-SC```")
    assert not VALID_PATTERN.match("")


def test_fallback_value():
    assert FALLBACK == "ZD-SC"


def test_compose_encoding_pads_seq():
    kf = SimpleNamespace(
        id=1, file_encoding=None, file_name="x.pdf",
        abstract="some abstract",
        create_time=datetime(2026, 4, 15, 10, 0, 0),
    )
    t = FileEncodingTransformer(invoke_user_id=42, knowledge_file=kf)
    assert t._compose_encoding("GF", "ZD-SC", datetime(2026, 4, 1), 7) == "GF-ZD-SC-202604-00007"
    assert t._compose_encoding("GF", "JSTZ-XX", datetime(2026, 12, 31), 99999) == "GF-JSTZ-XX-202612-99999"
    assert t._compose_encoding("GF", "ZD-SC", datetime(2026, 1, 5), 1) == "GF-ZD-SC-202601-00001"


def test_seq_capped_at_99999():
    kf = SimpleNamespace(
        id=1, file_encoding=None, file_name="x.pdf",
        abstract="x", create_time=datetime(2026, 4, 15),
    )
    t = FileEncodingTransformer(invoke_user_id=42, knowledge_file=kf)
    assert t._cap_seq(0) == 1
    assert t._cap_seq(1) == 1
    assert t._cap_seq(99999) == 99999
    assert t._cap_seq(100000) == 99999
    assert t._cap_seq(500000) == 99999


def test_month_window():
    kf = SimpleNamespace(
        id=1, file_encoding=None, file_name="x", abstract="x",
        create_time=datetime(2026, 4, 15, 10, 30, 0),
    )
    t = FileEncodingTransformer(invoke_user_id=42, knowledge_file=kf)
    start, end = t._month_window()
    assert start == datetime(2026, 4, 1, 0, 0, 0, 0)
    assert end == datetime(2026, 5, 1, 0, 0, 0, 0)


def test_month_window_december_rolls_over():
    kf = SimpleNamespace(
        id=1, file_encoding=None, file_name="x", abstract="x",
        create_time=datetime(2026, 12, 31, 23, 59, 59),
    )
    t = FileEncodingTransformer(invoke_user_id=42, knowledge_file=kf)
    start, end = t._month_window()
    assert start == datetime(2026, 12, 1)
    assert end == datetime(2027, 1, 1)


@pytest.mark.asyncio
async def test_do_work_skips_when_shougang_disabled():
    kf = SimpleNamespace(
        id=1, file_encoding=None, file_name="x", abstract="x",
        create_time=datetime(2026, 4, 15),
    )
    t = FileEncodingTransformer(invoke_user_id=42, knowledge_file=kf)
    fake_conf = SimpleNamespace(enabled=False, prefix=None)
    with patch.object(_enc_mod.bisheng_settings, 'aget_shougang_conf', AsyncMock(return_value=fake_conf)):
        await t._do_work()
    assert kf.file_encoding is None


@pytest.mark.asyncio
async def test_do_work_skips_when_encoding_already_present():
    kf = SimpleNamespace(
        id=1, file_encoding="GF-ZD-SC-202603-00001", file_name="x", abstract="x",
        create_time=datetime(2026, 4, 15),
    )
    t = FileEncodingTransformer(invoke_user_id=42, knowledge_file=kf)
    fake_conf = SimpleNamespace(enabled=True, prefix="GF")
    with patch.object(_enc_mod.bisheng_settings, 'aget_shougang_conf', AsyncMock(return_value=fake_conf)):
        await t._do_work()
    assert kf.file_encoding == "GF-ZD-SC-202603-00001"
