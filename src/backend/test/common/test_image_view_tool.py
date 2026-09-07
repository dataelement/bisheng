"""Unit tests for view_image tool (F061 T005).

Covers AC: AC-05, AC-08, AC-09, AC-14, AC-19, AC-20
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from bisheng.common.image_view import ImageRegistry, annotate
from bisheng.common.image_view.tool import build_view_image_tool


def _registry_with_four_images() -> ImageRegistry:
    registry = ImageRegistry()
    annotate(
        "![a](/bisheng/knowledge/images/1/2/a.png)"
        "![b](/bisheng/knowledge/images/1/2/b.png)"
        "![c](/bisheng/knowledge/images/1/2/c.png)"
        "![d](/bisheng/knowledge/images/1/2/d.png)",
        registry,
    )
    return registry


def test_view_image_schema_has_ids_and_quality_but_no_url():
    tool = build_view_image_tool(ImageRegistry())
    fields = tool.args_schema.model_fields
    assert "image_ids" in fields
    assert "quality" in fields
    assert "url" not in fields
    assert 'e.g. ["img#1"]' not in tool.description
    assert "do not default to img#1" in tool.description


@pytest.mark.asyncio
async def test_unknown_image_id_does_not_fetch(monkeypatch):
    fetch = AsyncMock()
    monkeypatch.setattr("bisheng.common.image_view.tool.fetch_and_encode", fetch)
    tool = build_view_image_tool(ImageRegistry())

    observation = await tool.ainvoke({"image_ids": ["img#9"], "quality": "standard"})

    assert "not available" in observation.lower() or "unavailable" in observation.lower()
    fetch.assert_not_called()


@pytest.mark.asyncio
async def test_more_than_three_ids_fetches_only_three(monkeypatch):
    fetch = AsyncMock()
    fetch.return_value = type("R", (), {"ok": True, "data_uri": "data:image/png;base64,abc", "error": None})()
    monkeypatch.setattr("bisheng.common.image_view.tool.fetch_and_encode", fetch)
    tool = build_view_image_tool(_registry_with_four_images())

    observation = await tool.ainvoke({"image_ids": ["img#1", "img#2", "img#3", "img#4"], "quality": "standard"})

    assert fetch.await_count == 3
    assert "img#4" in observation
    assert "3" in observation
    assert "data:image" not in observation


@pytest.mark.asyncio
async def test_non_standard_quality_is_rejected(monkeypatch):
    fetch = AsyncMock()
    monkeypatch.setattr("bisheng.common.image_view.tool.fetch_and_encode", fetch)
    tool = build_view_image_tool(_registry_with_four_images())

    observation = await tool.ainvoke({"image_ids": ["img#1"], "quality": "hd"})

    assert "standard" in observation.lower()
    fetch.assert_not_called()


@pytest.mark.asyncio
async def test_success_ack_has_no_image_block(monkeypatch):
    fetch = AsyncMock()
    fetch.return_value = type("R", (), {"ok": True, "data_uri": "data:image/png;base64,abc", "error": None})()
    monkeypatch.setattr("bisheng.common.image_view.tool.fetch_and_encode", fetch)
    tool = build_view_image_tool(_registry_with_four_images())

    observation = await tool.ainvoke({"image_ids": ["img#1"], "quality": "standard"})

    fetch.assert_awaited_once()
    assert "img#1" in observation
    assert "data:image" not in observation
    assert "image_url" not in observation
