"""F086 T06: inspect_flow_data decides whether a workflow can be used as a subflow.

覆盖 AC: AC-03、AC-04、AC-05
"""

from bisheng.workflow.domain.services.subflow_inspect import inspect_flow_data


def _node(node_id: str, node_type: str, name: str = "", params: list[dict] | None = None) -> dict:
    return {
        "id": node_id,
        "data": {
            "id": node_id,
            "type": node_type,
            "name": name or node_id,
            "group_params": [{"name": "", "params": params or []}],
        },
    }


def _start(custom_variables: list[dict]) -> dict:
    return _node("start_1", "start", "Start", [{"key": "custom_variables", "value": custom_variables}])


def _output(node_id: str, output_type: str) -> dict:
    return _node(node_id, "output", f"Output {node_id}", [{"key": "output_result", "value": {"type": output_type}}])


def _end(node_id: str, enabled: bool | None, names: list[str]) -> dict:
    params = []
    if enabled is not None:
        params.append({"key": "return_enabled", "value": enabled})
        params.append(
            {
                "key": "return_results",
                "value": [{"key": n, "type": "ref", "value": "llm_1.output"} for n in names],
            }
        )
    return _node(node_id, "end", f"End {node_id}", params)


def _flow(*nodes: dict) -> dict:
    return {"nodes": list(nodes), "edges": []}


def test_plain_workflow_is_eligible_and_lists_interface():
    data = _flow(
        _start([{"key": "u1", "label": "city", "value": "Shanghai"}, {"key": "u2", "label": "days", "value": "3"}]),
        _node("llm_1", "llm"),
        _output("output_1", ""),
        _end("end_1", True, ["answer", "score"]),
    )
    result = inspect_flow_data(data)
    assert result.eligible
    assert result.forbidden_nodes == []
    assert result.inputs == [{"name": "city", "value": "Shanghai"}, {"name": "days", "value": "3"}]
    assert result.outputs == ["answer", "score"]
    assert result.ineligible_reasons == []


def test_input_node_is_forbidden():
    result = inspect_flow_data(_flow(_start([]), _node("input_1", "input", "Ask user"), _end("end_1", None, [])))
    assert not result.eligible
    assert result.forbidden_nodes == [{"id": "input_1", "name": "Ask user", "type": "input"}]
    assert result.ineligible_reasons == ["input_node"]


def test_interactive_output_nodes_are_forbidden_plain_output_is_not():
    data = _flow(_start([]), _output("o_input", "input"), _output("o_choose", "choose"), _output("o_plain", ""))
    result = inspect_flow_data(data)
    assert [n["id"] for n in result.forbidden_nodes] == ["o_input", "o_choose"]
    assert result.ineligible_reasons == ["interactive_output_node"]


def test_subflow_node_is_forbidden():
    result = inspect_flow_data(_flow(_start([]), _node("subflow_1", "subflow", "Inner")))
    assert result.forbidden_nodes == [{"id": "subflow_1", "name": "Inner", "type": "subflow"}]
    assert result.ineligible_reasons == ["subflow_node"]
    assert result.subflow_ids == []


def test_subflow_ids_are_collected_in_order_without_duplicates():
    def subflow(node_id: str, flow_id: str) -> dict:
        return _node(node_id, "subflow", params=[{"key": "subflow_id", "value": {"id": flow_id, "name": "x"}}])

    data = _flow(_start([]), subflow("s1", "flow_b"), subflow("s2", "flow_a"), subflow("s3", "flow_b"))
    assert inspect_flow_data(data).subflow_ids == ["flow_b", "flow_a"]


def test_reasons_follow_a_fixed_order():
    data = _flow(_start([]), _node("subflow_1", "subflow"), _output("o1", "choose"), _node("input_1", "input"))
    assert inspect_flow_data(data).ineligible_reasons == ["input_node", "interactive_output_node", "subflow_node"]


def test_outputs_merge_enabled_end_nodes_only():
    data = _flow(
        _start([]),
        _end("end_1", True, ["a", "b"]),
        _end("end_2", False, ["hidden"]),
        _end("end_3", None, []),
        _end("end_4", True, ["b", "c"]),
    )
    assert inspect_flow_data(data).outputs == ["a", "b", "c"]


def test_chat_history_output_name_makes_workflow_ineligible():
    result = inspect_flow_data(_flow(_start([]), _end("end_1", True, ["chat_history", "ok"])))
    assert not result.eligible
    assert result.invalid_output_names == ["chat_history"]
    assert result.ineligible_reasons == ["invalid_output_name"]
    assert result.forbidden_nodes == []


def test_note_nodes_are_ignored():
    result = inspect_flow_data(_flow(_start([]), _node("note_1", "note")))
    assert result.eligible


def test_empty_or_malformed_data_does_not_raise():
    for data in (None, {}, {"nodes": None}, {"nodes": [{}]}, {"nodes": [{"data": {"type": "start"}}]}):
        result = inspect_flow_data(data)
        assert result.eligible
        assert result.inputs == []
        assert result.outputs == []

    broken = _flow(
        _node("start_1", "start", params=[{"key": "custom_variables", "value": None}]),
        _node("o1", "output", params=[{"key": "output_result", "value": None}]),
        _node("end_1", "end", params=[{"key": "return_enabled", "value": True}]),
    )
    result = inspect_flow_data(broken)
    assert result.eligible
    assert result.outputs == []
