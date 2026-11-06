"""Preset tool seed rows must have unique ids and resolve to their own category.

Two branches each claimed category id 18 (F085 web fetch, built-in knowledge
search); the merge kept both, so fresh installs would insert a duplicate primary
key and register_work_knowledge_tool.py resolved knowledge search to the web
fetch category.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

_DATA = Path(__file__).resolve().parents[2] / "bisheng" / "database" / "data"


def _load(name: str) -> list[dict]:
    return json.loads((_DATA / name).read_text(encoding="utf-8"))


def test_seed_ids_are_unique():
    for name in ("t_gpts_tools.json", "t_gpts_tools_type.json"):
        dup = [i for i, n in Counter(row["id"] for row in _load(name)).items() if n > 1]
        assert dup == [], f"{name} has duplicate ids: {dup}"


def test_every_seed_tool_references_an_existing_category():
    category_ids = {row["id"] for row in _load("t_gpts_tools_type.json")}
    orphans = [row["tool_key"] for row in _load("t_gpts_tools.json") if row["type"] not in category_ids]
    assert orphans == []


def test_built_in_tools_resolve_to_their_own_category():
    categories = {row["id"]: row["name"] for row in _load("t_gpts_tools_type.json")}
    tools = {row["tool_key"]: row for row in _load("t_gpts_tools.json")}
    assert categories[tools["web_fetch"]["type"]] == "网页读取"
    assert categories[tools["bisheng_knowledge_search"]["type"]] == "知识库检索"
