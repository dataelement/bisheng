import json
import math

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from bisheng.evaluation.domain.services.answer_correctness import compute_answer_correctness


class _StubLLM:
    """Minimal stand-in exposing .generate() like a langchain chat model."""

    def __init__(self, payload_text: str):
        self._text = payload_text

    def generate(self, messages, **kwargs):
        gens = [[ChatGeneration(message=AIMessage(content=self._text))] for _ in messages]
        return LLMResult(generations=gens)


def test_scores_match_formula():
    payload = json.dumps([{
        "statements that are present in both the answer and the ground truth": ["a", "b"],
        "statements present in the answer but not found in the ground truth": ["c"],
        "relevant statements found in the ground truth but omitted in the answer": [],
    }])
    result = compute_answer_correctness(
        _StubLLM(payload), question=["q"], answer=["x"], ground_truths=[["g"]], human_prompt="")
    # tp=2, fp=1, fn=0 -> f1 = 2/(2+0.5*1)=0.8 ; precision=2/3 ; recall=1.0
    assert result["statements_num_overlap"][0] == 2
    assert result["statements_num_answer_only"][0] == 1
    assert result["statements_num_gt_only"][0] == 0
    assert math.isclose(result["answer_f1"][0], 0.8)
    assert math.isclose(result["answer_precision"][0], 2 / 3)
    assert result["answer_recall"][0] == 1.0
    assert result["question"] == ["q"]
    assert result["ground_truths"] == [["g"]]


def test_unparseable_output_yields_nan():
    result = compute_answer_correctness(
        _StubLLM("not json at all"), question=["q"], answer=["x"], ground_truths=[["g"]], human_prompt="")
    assert math.isnan(result["answer_f1"][0])
    assert result["statements_overlap"][0] == ""
