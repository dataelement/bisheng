"""F086 T17: RedisCallback.parse_workflow_failed reads the subflow marker before other rules.

覆盖 AC: AC-20
"""

import pytest

from bisheng.common.errcode.flow import WorkFlowSubflowNotFoundError, WorkFlowSubflowRunError
from bisheng.common.errcode.linsight import AgentSkillDisabledError
from bisheng.workflow.nodes.agent.skill_support import AgentSkillRunError
from bisheng.workflow.nodes.subflow.subflow import SubflowRunError


@pytest.fixture
def callback():
    from bisheng.worker.workflow.redis_callback import RedisCallback

    instance = RedisCallback.__new__(RedisCallback)
    instance.user_id, instance.chat_id, instance.workflow_id = 7, "c1", "flow-1"
    return instance


def _run_error(reason: str) -> str:
    return str(SubflowRunError(WorkFlowSubflowRunError, subflow_name="Child", node_name="Inner", reason=reason))


def test_subflow_marker_gives_its_own_code(callback):
    response = callback.parse_workflow_failed({"reason": _run_error("kaput")})
    assert response.message["status_code"] == 10560
    assert response.message["data"] == {"subflow_name": "Child", "node_name": "Inner", "reason": "kaput"}


def test_other_subflow_codes_pass_through(callback):
    response = callback.parse_workflow_failed({"reason": str(SubflowRunError(WorkFlowSubflowNotFoundError))})
    assert response.message["status_code"] == 10561


def test_max_steps_text_inside_a_subflow_is_still_10560(callback):
    reason = _run_error("Loop -- has run more than the maximum number of times.")
    assert callback.parse_workflow_failed({"reason": reason}).message["status_code"] == 10560


def test_skill_error_inside_a_subflow_is_still_10560(callback):
    inner = str(AgentSkillRunError(AgentSkillDisabledError(skill_name="docx"), "Agent"))
    assert callback.parse_workflow_failed({"reason": _run_error(inner)}).message["status_code"] == 10560


def test_stop_by_user_still_returns_none(callback):
    assert callback.parse_workflow_failed({"reason": "stop by user"}) is None


def test_plain_max_steps_failure_is_unchanged(callback):
    reason = "Loop -- has run more than the maximum number of times."
    assert callback.parse_workflow_failed({"reason": reason}).message["status_code"] == 10528
