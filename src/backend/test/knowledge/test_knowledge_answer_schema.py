"""Strict, bounded request contracts for independent knowledge answers."""

import pytest
from pydantic import ValidationError

from bisheng.knowledge.domain.schemas.knowledge_answer_schema import KnowledgeAnswerReq


def request(**changes):
    return KnowledgeAnswerReq.model_validate(
        {"query": "question", "knowledge_base_ids": [2, 1, 2], "model_id": 3, **changes}
    )


def test_normalization_and_defaults():
    req = request(
        query="  question \n", filters={"knowledge_base_filters": [{"knowledge_base_id": 1, "tags": [" a ", "a", "b"]}]}
    )
    assert req.query == "question"
    assert req.knowledge_base_ids == [1, 2]
    assert (req.top_k, req.max_content) == (10, 15000)
    assert req.filters.knowledge_base_filters[0].tags == ["a", "b"]


@pytest.mark.parametrize(
    "changes",
    [
        {"query": ""},
        {"query": " \n"},
        {"query": 123},
        {"query": "a" * 4097},
        {"knowledge_base_ids": []},
        {"knowledge_base_ids": [1] * 21},
        {"knowledge_base_ids": [True]},
        {"knowledge_base_ids": ["1"]},
        {"knowledge_base_ids": [0]},
        {"knowledge_base_ids": [-1]},
        {"model_id": True},
        {"model_id": "3"},
        {"model_id": 0},
        {"model_id": 1.0},
        {"top_k": 0},
        {"top_k": 51},
        {"top_k": True},
        {"top_k": "10"},
        {"max_content": 0},
        {"max_content": 60001},
        {"max_content": True},
        {"max_content": "1"},
        {"user_id": 1},
        {"tenant_id": 1},
        {"system_prompt": "override"},
        {"stream": True},
        {"filters": {"unknown": True}},
        {"filters": {"knowledge_base_filters": [{"knowledge_base_id": 4}]}},
        {"filters": {"knowledge_base_filters": [{"knowledge_base_id": 1}, {"knowledge_base_id": 1}]}},
        {"filters": {"knowledge_base_filters": [{"knowledge_base_id": 1, "tag_match_mode": "ALL"}]}},
        {"filters": {"knowledge_base_filters": [{"knowledge_base_id": 1, "tags": [" "]}]}},
        {"filters": {"knowledge_base_filters": [{"knowledge_base_id": 1, "tags": ["a" * 129]}]}},
        {"filters": {"knowledge_base_filters": [{"knowledge_base_id": 1, "tags": [1]}]}},
        {"filters": {"knowledge_base_filters": [{"knowledge_base_id": 1, "tags": ["a"] * 21}]}},
        {"filters": {"knowledge_base_filters": [{"knowledge_base_id": True}]}},
        {"filters": {"knowledge_base_filters": [{"knowledge_base_id": 1, "unknown": True}]}},
    ],
)
def test_reject_invalid_or_untrusted_parameters(changes):
    with pytest.raises(ValidationError):
        request(**changes)


def test_inclusive_limits():
    req = request(query="a" * 4096, knowledge_base_ids=list(range(1, 21)), top_k=50, max_content=60000)
    assert len(req.query) == 4096
    assert len(req.knowledge_base_ids) == 20
