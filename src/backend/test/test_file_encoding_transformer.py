"""Unit tests for FileEncodingTransformer pure logic."""
import json
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
    assert VALID_PATTERN.match("POL-PP")
    assert VALID_PATTERN.match("STD-IT")
    assert VALID_PATTERN.match("RPT-QM")
    assert VALID_PATTERN.match("NEW-AD")


def test_valid_pattern_rejects_invalid():
    assert not VALID_PATTERN.match("STD-OT")
    assert not VALID_PATTERN.match("OT-PP")
    assert not VALID_PATTERN.match("std-sc")
    assert not VALID_PATTERN.match("STD - PP")
    assert not VALID_PATTERN.match("STD-PP-extra")
    assert not VALID_PATTERN.match("```STD-PP```")
    assert not VALID_PATTERN.match("")


def test_fallback_value():
    assert FALLBACK == "STD-PP"


def test_compose_encoding_pads_seq():
    kf = SimpleNamespace(
        id=1, file_encoding=None, file_name="x.pdf",
        abstract="some abstract",
        knowledge_id=10,
        create_time=datetime(2026, 4, 15, 10, 0, 0),
    )
    t = FileEncodingTransformer(invoke_user_id=42, knowledge_file=kf)
    assert t._compose_encoding("GF", "STD-PP", datetime(2026, 4, 1), 7) == "GF-STD-PP-20260400000007"
    assert t._compose_encoding("GF", "NEW-IT", datetime(2026, 12, 31), 99999999) == "GF-NEW-IT-20261299999999"
    assert t._compose_encoding("GF", "STD-PP", datetime(2026, 1, 5), 1) == "GF-STD-PP-20260100000001"


def test_seq_capped_at_99999999():
    kf = SimpleNamespace(
        id=1, file_encoding=None, file_name="x.pdf",
        abstract="x", knowledge_id=10, create_time=datetime(2026, 4, 15),
    )
    t = FileEncodingTransformer(invoke_user_id=42, knowledge_file=kf)
    assert t._cap_seq(0) == 1
    assert t._cap_seq(1) == 1
    assert t._cap_seq(99999999) == 99999999
    assert t._cap_seq(100000000) == 99999999
    assert t._cap_seq(500000000) == 99999999


def test_seq_cap_can_be_overridden_by_config():
    assert FileEncodingTransformer._cap_seq(8, seq_cap=5) == 5
    assert FileEncodingTransformer._cap_seq(0, seq_cap=5) == 1


def test_encoding_config_uses_defaults_when_missing():
    kf = SimpleNamespace(
        id=1, file_encoding=None, file_name="x.pdf",
        abstract="x", knowledge_id=10, create_time=datetime(2026, 4, 15),
    )
    t = FileEncodingTransformer(invoke_user_id=42, knowledge_file=kf)

    config = t._resolve_encoding_config(SimpleNamespace(file_encoding=None))

    assert config.classify_prompt == _enc_mod.CLASSIFY_PROMPT
    assert config.user_content_template == _enc_mod.DEFAULT_USER_CONTENT_TEMPLATE
    assert config.valid_pattern.match("STD-PP")
    assert config.fallback_code == "STD-PP"
    assert config.seq_cap == 99999999


def test_encoding_config_accepts_custom_prompt_template_pattern_fallback_and_seq_cap():
    kf = SimpleNamespace(
        id=1, file_encoding=None, file_name="视频处理.pdf",
        abstract="任务服务设计", knowledge_id=10, create_time=datetime(2026, 4, 15),
    )
    t = FileEncodingTransformer(invoke_user_id=42, knowledge_file=kf)
    raw_config = SimpleNamespace(
        file_encoding=SimpleNamespace(
            classify_prompt="只输出 X1-Y1",
            user_content_template="文件={file_name};摘要={abstract}",
            valid_pattern=r"^X1-Y1$",
            fallback_code="X1-Y1",
            seq_cap=5,
        )
    )

    config = t._resolve_encoding_config(raw_config)
    messages = t._build_classify_messages(config)

    assert config.classify_prompt == "只输出 X1-Y1"
    assert config.valid_pattern.match("X1-Y1")
    assert config.fallback_code == "X1-Y1"
    assert config.seq_cap == 5
    assert messages == [
        {"role": "system", "content": "只输出 X1-Y1"},
        {"role": "user", "content": "文件=视频处理.pdf;摘要=任务服务设计"},
    ]


def test_encoding_config_falls_back_per_invalid_field():
    kf = SimpleNamespace(
        id=1, file_encoding=None, file_name="x.pdf",
        abstract="x", knowledge_id=10, create_time=datetime(2026, 4, 15),
    )
    t = FileEncodingTransformer(invoke_user_id=42, knowledge_file=kf)
    raw_config = SimpleNamespace(
        file_encoding={
            "classify_prompt": "",
            "user_content_template": "标题: {missing}",
            "valid_pattern": "[",
            "fallback_code": "BAD",
            "seq_cap": 0,
        }
    )

    config = t._resolve_encoding_config(raw_config)
    messages = t._build_classify_messages(config)

    assert config.classify_prompt == _enc_mod.CLASSIFY_PROMPT
    assert config.valid_pattern.match("STD-PP")
    assert config.fallback_code == "STD-PP"
    assert config.seq_cap == 99999999
    assert messages[1]["content"] == "标题: x.pdf\n摘要: x"


def test_month_window():
    kf = SimpleNamespace(
        id=1, file_encoding=None, file_name="x", abstract="x",
        knowledge_id=10,
        create_time=datetime(2026, 4, 15, 10, 30, 0),
    )
    t = FileEncodingTransformer(invoke_user_id=42, knowledge_file=kf)
    start, end = t._month_window()
    assert start == datetime(2026, 4, 1, 0, 0, 0, 0)
    assert end == datetime(2026, 5, 1, 0, 0, 0, 0)


def test_month_window_december_rolls_over():
    kf = SimpleNamespace(
        id=1, file_encoding=None, file_name="x", abstract="x",
        knowledge_id=10,
        create_time=datetime(2026, 12, 31, 23, 59, 59),
    )
    t = FileEncodingTransformer(invoke_user_id=42, knowledge_file=kf)
    start, end = t._month_window()
    assert start == datetime(2026, 12, 1)
    assert end == datetime(2027, 1, 1)


@pytest.mark.asyncio
async def test_do_work_uses_default_company_code_when_prefix_missing():
    kf = SimpleNamespace(
        id=1, file_encoding=None, file_name="x", abstract="x",
        knowledge_id=10,
        create_time=datetime(2026, 4, 15),
    )
    t = FileEncodingTransformer(invoke_user_id=42, knowledge_file=kf)
    fake_conf = SimpleNamespace(enabled=False, prefix=None)
    fake_settings = SimpleNamespace(aget_shougang_conf=AsyncMock(return_value=fake_conf))
    with patch.object(_enc_mod, 'bisheng_settings', fake_settings), \
            patch.object(t, '_classify_with_llm', AsyncMock(return_value="STD-PP")), \
            patch.object(t, '_compute_seq', AsyncMock(return_value=7)):
        await t._do_work()
    assert kf.file_encoding == "SGGF-STD-PP-20260400000007"


@pytest.mark.asyncio
async def test_do_work_uses_selected_document_type_from_split_rule():
    kf = SimpleNamespace(
        id=1, file_encoding=None, file_name="x", abstract="x",
        knowledge_id=10,
        create_time=datetime(2026, 4, 15),
        split_rule=json.dumps({"file_category_code": "RPT"}),
    )
    t = FileEncodingTransformer(invoke_user_id=42, knowledge_file=kf)
    fake_conf = SimpleNamespace(enabled=True, prefix="SGGF", file_encoding=None)
    fake_settings = SimpleNamespace(aget_shougang_conf=AsyncMock(return_value=fake_conf))
    with patch.object(_enc_mod, 'bisheng_settings', fake_settings), \
            patch.object(t, '_classify_with_llm', AsyncMock(return_value="STD-PP")), \
            patch.object(t, '_compute_seq', AsyncMock(return_value=7)):
        await t._do_work()
    assert kf.file_encoding == "SGGF-RPT-PP-20260400000007"


@pytest.mark.asyncio
async def test_do_work_skips_when_encoding_already_present():
    kf = SimpleNamespace(
        id=1, file_encoding="GF-STD-SC-20260300000001", file_name="x", abstract="x",
        knowledge_id=10,
        create_time=datetime(2026, 4, 15),
    )
    t = FileEncodingTransformer(invoke_user_id=42, knowledge_file=kf)
    fake_conf = SimpleNamespace(enabled=True, prefix="GF")
    fake_settings = SimpleNamespace(aget_shougang_conf=AsyncMock(return_value=fake_conf))
    with patch.object(_enc_mod, 'bisheng_settings', fake_settings):
        await t._do_work()
    assert kf.file_encoding == "GF-STD-SC-20260300000001"
