"""F086 T10: SubflowCallback keeps a subflow silent, records its node runs and checks for stop.

覆盖 AC: AC-15、AC-17、AC-20
"""

from unittest.mock import MagicMock

from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.callback.event import (
    GuideQuestionData,
    GuideWordData,
    NodeEndData,
    NodeStartData,
    OutputMsgChooseData,
    OutputMsgData,
    OutputMsgInputData,
    StreamMsgData,
    StreamMsgOverData,
    UserInputData,
)
from bisheng.workflow.callback.subflow_callback import SubflowCallback


def _start(uid: str, node_id: str) -> NodeStartData:
    return NodeStartData(unique_id=uid, node_id=node_id, name=f"Node {node_id}")


def _end(uid: str, node_id: str, reason: str | None = None, log_data=None, input_data=None) -> NodeEndData:
    return NodeEndData(
        unique_id=uid, node_id=node_id, name=f"Node {node_id}", reason=reason, log_data=log_data, input_data=input_data
    )


def test_is_a_base_callback():
    assert isinstance(SubflowCallback(), BaseCallback)


def test_chat_events_are_dropped_without_side_effects():
    stop_check = MagicMock(return_value=False)
    on_stop = MagicMock()
    callback = SubflowCallback(stop_check=stop_check, on_stop=on_stop)

    callback.on_user_input(UserInputData(node_id="i", name="i", input_schema={}))
    callback.on_guide_word(GuideWordData(unique_id="u", node_id="s", name="s", guide_word="hi"))
    callback.on_guide_question(GuideQuestionData(unique_id="u", node_id="s", name="s", guide_question=["q"]))
    callback.on_stream_msg(StreamMsgData(unique_id="u", node_id="l", name="l", msg="x", output_key="output"))
    callback.on_stream_over(StreamMsgOverData(unique_id="u", node_id="l", name="l", msg="x", output_key="output"))
    callback.on_output_msg(OutputMsgData(unique_id="u", node_id="o", name="o", msg="x"))
    callback.on_output_choose(OutputMsgChooseData(unique_id="u", node_id="o", name="o", msg="x"))
    callback.on_output_input(OutputMsgInputData(unique_id="u", node_id="o", name="o", msg="x"))

    stop_check.assert_not_called()
    on_stop.assert_not_called()
    assert callback.node_logs == []


def test_node_runs_are_recorded_in_execution_order():
    callback = SubflowCallback()
    callback.on_node_start(_start("u1", "start_1"))
    callback.on_node_end(_end("u1", "start_1", log_data=[[{"key": "k", "value": 1, "type": "params"}]]))
    callback.on_node_start(_start("u2", "llm_1"))
    callback.on_node_start(_start("u3", "code_1"))
    callback.on_node_end(_end("u3", "code_1", input_data={"llm_1.output": "x"}))
    callback.on_node_end(_end("u2", "llm_1", reason="boom"))

    logs = callback.node_logs
    assert [one["node_id"] for one in logs] == ["start_1", "code_1", "llm_1"]
    assert callback.executed_node_ids == ["start_1", "code_1", "llm_1"]
    assert logs[0] == {
        "node_id": "start_1",
        "name": "Node start_1",
        "duration_ms": logs[0]["duration_ms"],
        "reason": None,
        "log_data": [[{"key": "k", "value": 1, "type": "params"}]],
        "input_data": None,
    }
    assert logs[1]["input_data"] == {"llm_1.output": "x"}
    assert logs[2]["reason"] == "boom"
    assert all(isinstance(one["duration_ms"], int) and one["duration_ms"] >= 0 for one in logs)


def test_end_without_start_still_recorded():
    callback = SubflowCallback()
    callback.on_node_end(_end("u9", "end_1"))
    assert callback.node_logs[0]["duration_ms"] == 0


def test_last_failed_node_name():
    callback = SubflowCallback()
    assert callback.last_failed_node_name() == ""
    callback.on_node_end(_end("u1", "a", reason="first"))
    callback.on_node_end(_end("u2", "b"))
    callback.on_node_end(_end("u3", "c", reason="second"))
    callback.on_node_end(_end("u4", "d"))
    assert callback.last_failed_node_name() == "Node c"
    assert callback.last_failed_reason() == "second"


def test_stop_is_checked_at_every_node_start_and_end():
    stop_check = MagicMock(return_value=False)
    on_stop = MagicMock()
    callback = SubflowCallback(stop_check=stop_check, on_stop=on_stop)
    callback.on_node_start(_start("u1", "a"))
    callback.on_node_end(_end("u1", "a"))
    assert stop_check.call_count == 2
    on_stop.assert_not_called()

    stop_check.return_value = True
    callback.on_node_start(_start("u2", "b"))
    on_stop.assert_called_once()
    callback.on_node_end(_end("u2", "b"))
    assert on_stop.call_count == 2


def test_default_stop_check_never_stops():
    callback = SubflowCallback()
    callback.on_node_start(_start("u1", "a"))
    callback.on_node_end(_end("u1", "a"))
    assert len(callback.node_logs) == 1
