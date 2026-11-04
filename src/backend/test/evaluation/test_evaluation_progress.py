"""Evaluation progress reaches list readers after each completed question."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import pytest

from bisheng.evaluation.domain.models.evaluation import Evaluation, EvaluationTaskStatus, ExecType
from bisheng.evaluation.domain.services import evaluation_service as service


def _task(monkeypatch, exec_type, question_count=3, fail_at=None):
    evaluation = Evaluation(
        id=42,
        user_id=7,
        tenant_id=1,
        unique_id="app-id",
        version=4,
        exec_type=exec_type.value,
    )
    rows = [{"question": f"question-{i}", "ground_truth": f"truth-{i}"} for i in range(question_count)]
    cache = {}
    redis = SimpleNamespace(
        set=Mock(side_effect=cache.__setitem__),
        get=Mock(side_effect=cache.get),
        exists=Mock(side_effect=cache.__contains__),
        delete=Mock(side_effect=lambda key: cache.pop(key, None)),
    )
    monkeypatch.setattr(service, "get_redis_client_sync", lambda: redis)
    monkeypatch.setattr(service.EvaluationRepository, "get_one_evaluation", Mock(return_value=evaluation))
    monkeypatch.setattr(service.EvaluationRepository, "get_my_evaluations", Mock(return_value=([evaluation], 1)))
    update = Mock()
    monkeypatch.setattr(service.EvaluationRepository, "update_evaluation", update)
    monkeypatch.setattr(service.EvaluationService, "get_user_name", Mock(return_value="Test user"))
    monkeypatch.setattr(service.EvaluationService, "read_csv_file", Mock(return_value=object()))
    monkeypatch.setattr(service.EvaluationService, "parse_csv", Mock(return_value=rows))
    monkeypatch.setattr(
        service.EvaluationService, "upload_result_file", Mock(return_value="evaluation/result/test.csv")
    )
    version = SimpleNamespace(id=4, flow_id="app-id", name="Published")
    monkeypatch.setattr(service.FlowVersionDao, "get_version_by_id", Mock(return_value=version))
    monkeypatch.setattr(service.FlowVersionDao, "get_list_by_ids", Mock(return_value=[version]))
    monkeypatch.setattr(
        service.FlowDao, "get_flow_by_ids", Mock(return_value=[SimpleNamespace(id="app-id", name="App")])
    )
    monkeypatch.setattr(
        service.AssistantDao, "get_assistants_by_ids", Mock(return_value=[SimpleNamespace(id="app-id", name="App")])
    )
    monkeypatch.setattr(service.AssistantDao, "aget_one_assistant", AsyncMock(return_value=object()))
    monkeypatch.setattr(service.LLMService, "get_evaluation_llm_object", AsyncMock(return_value=object()))

    def progress():
        result = service.EvaluationService.get_evaluation(SimpleNamespace(user_id=7))
        return result.data["data"][0]["progress"]

    before_answers = []

    def answer(question):
        before_answers.append(progress())
        index = int(question.rsplit("-", 1)[1])
        if index == fail_at:
            raise RuntimeError("workflow failed")
        return f"answer-{index}"

    monkeypatch.setattr(service, "execute_workflow_get_answer", lambda workflow, evaluation, question: answer(question))
    agent = SimpleNamespace(
        init_assistant=AsyncMock(),
        run=AsyncMock(side_effect=lambda question: [SimpleNamespace(content=answer(question))]),
    )
    monkeypatch.setattr(service, "AssistantAgent", Mock(return_value=agent))
    scoring_progress = []

    def score(llm, questions, answers, ground_truths, prompt):
        scoring_progress.append(progress())
        return {
            "question": questions,
            "answer": answers,
            "ground_truths": ground_truths,
            "statements_num_gt_only": [0] * question_count,
            "statements_num_answer_only": [0] * question_count,
            "statements_num_overlap": [1] * question_count,
            "answer_recall": [1.0] * question_count,
            "answer_precision": [1.0] * question_count,
            "answer_f1": [1.0] * question_count,
        }

    scorer = Mock(side_effect=score)
    monkeypatch.setattr(service, "compute_answer_correctness", scorer)
    return SimpleNamespace(
        evaluation=evaluation,
        redis=redis,
        before_answers=before_answers,
        scoring_progress=scoring_progress,
        progress=progress,
        scorer=scorer,
        update=update,
    )


@pytest.mark.parametrize("exec_type", [ExecType.WORKFLOW, ExecType.ASSISTANT])
@pytest.mark.parametrize("question_count", [1, 3])
async def test_completed_questions_advance_list_progress_and_finish_at_100(monkeypatch, exec_type, question_count):
    task = _task(monkeypatch, exec_type, question_count)

    await service.add_evaluation_task(task.evaluation.id)

    key = service.EvaluationService.get_redis_key(task.evaluation.id)
    expected = [round((index + 1) * 80 / question_count) for index in range(question_count)]
    assert task.redis.set.call_args_list == [call(key, value) for value in expected]
    assert task.before_answers == ["0%", *(f"{value}%" for value in expected[:-1])]
    assert task.scoring_progress == ["80%"]
    assert task.evaluation.status == EvaluationTaskStatus.success.value
    assert task.evaluation.result_file_path == "evaluation/result/test.csv"
    assert task.progress() == "100%"
    task.redis.delete.assert_called_once_with(key)
    assert not task.redis.exists(key)
    task.update.assert_called_once_with(evaluation=task.evaluation)


@pytest.mark.parametrize("fail_at", [0, 1, 2])
async def test_failed_workflow_only_counts_completed_questions_and_cleans_progress(monkeypatch, fail_at):
    task = _task(monkeypatch, ExecType.WORKFLOW, fail_at=fail_at)

    await service.add_evaluation_task(task.evaluation.id)

    key = service.EvaluationService.get_redis_key(task.evaluation.id)
    assert task.redis.set.call_args_list == [call(key, round((index + 1) * 80 / 3)) for index in range(fail_at)]
    assert task.evaluation.status == EvaluationTaskStatus.failed.value
    assert task.evaluation.description == "workflow failed"
    task.scorer.assert_not_called()
    task.redis.delete.assert_called_once_with(key)
    assert not task.redis.exists(key)
