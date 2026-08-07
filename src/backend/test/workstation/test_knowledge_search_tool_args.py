from __future__ import annotations

import json

from bisheng.citation.domain.services.citation_prompt_helper import CitationRegistryCollector
from bisheng.workstation.domain.services.chat_service import _build_knowledge_search_tool


async def _args_schema():
    tool = await _build_knowledge_search_tool(
        knowledge_bases_info=[
            {"id": 101, "name": "one", "source": "organization"},
            {"id": 102, "name": "two", "source": "organization"},
        ],
        login_user=None,  # type: ignore[arg-type] -- validation does not execute the tool closure
        max_token=1000,
        citation_collector=CitationRegistryCollector(),
    )
    assert tool is not None
    return tool.args_schema


async def test_filters_accept_model_stringified_json_object():
    schema = await _args_schema()
    args = schema.model_validate(
        {
            "query": "market report",
            "filters": json.dumps(
                {
                    "knowledge_base_filters": [
                        {
                            "knowledge_base_id": "101",
                            "tags": ["market"],
                            "tag_match_mode": "ANY",
                        }
                    ]
                }
            ),
        }
    )

    [kb_filter] = args.filters.knowledge_base_filters
    assert kb_filter.knowledge_base_id == "101"
    assert kb_filter.tags == ["market"]
    assert kb_filter.tag_match_mode == "ANY"


async def test_nested_filter_and_sequence_fields_accept_common_model_coercions():
    schema = await _args_schema()
    args = schema.model_validate(
        {
            "knowledge_base_ids": '[101, "102"]',
            "query": 2026,
            "filters": {
                "knowledge_base_filters": json.dumps(
                    {
                        "knowledge_base_id": 101,
                        "tags": "strategy",
                        "tag_match_mode": "all",
                    }
                )
            },
        }
    )

    assert args.knowledge_base_ids == ["101", "102"]
    assert args.query == "2026"
    [kb_filter] = args.filters.knowledge_base_filters
    assert kb_filter.knowledge_base_id == "101"
    assert kb_filter.tags == ["strategy"]
    assert kb_filter.tag_match_mode == "ALL"


async def test_filters_accept_list_shorthand_with_stringified_items():
    schema = await _args_schema()
    args = schema.model_validate(
        {
            "knowledge_base_ids": 101,
            "query": "policy",
            "filters": [
                json.dumps(
                    {
                        "knowledge_base_id": "101",
                        "tags": '["policy", "2026"]',
                    }
                )
            ],
        }
    )

    assert args.knowledge_base_ids == ["101"]
    [kb_filter] = args.filters.knowledge_base_filters
    assert kb_filter.tags == ["policy", "2026"]
