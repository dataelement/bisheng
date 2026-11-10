"""昆联单次文本输入的有界等待快照。"""

import json
from importlib.metadata import version
from math import isfinite

from langchain_classic.memory import ConversationBufferWindowMemory

from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunError
from bisheng.workflow.domain.schemas.platform_agent import canonical_digest

# TODO [F123][EXT-03] 确认快照上限及跨版本升级兼容窗口。
_MAX_BYTES = 256 * 1024
_ENGINE = ("1.2.10", "4.1.1")
_CHECKPOINT_KEYS = {"v", "ts", "id", "channel_versions", "versions_seen", "updated_channels", "channel_values"}


def _require(condition):
    if not condition:
        raise RunError("RESUME_STATE_INVALID")


def _plain_json(value, depth=0):
    _require(depth <= 32)
    kind = type(value)
    if kind is dict:
        for key, item in value.items():
            _require(type(key) is str)
            _plain_json(item, depth + 1)
    elif kind is list:
        for item in value:
            _plain_json(item, depth + 1)
    else:
        _require(value is None or kind in (str, bool, int) or (kind is float and isfinite(value)))


def _validate_size(snapshot):
    _plain_json(snapshot)
    try:
        encoded = json.dumps(snapshot, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    except (ValueError, OverflowError) as exc:
        raise RunError("RESUME_STATE_INVALID") from exc
    _require(len(encoded) <= _MAX_BYTES)


def prepare_thread(workflow, session_id):
    workflow.graph_engine.graph_config["configurable"] = {"thread_id": session_id, "checkpoint_ns": ""}


def wait_engine_version():
    _require((version("langgraph"), version("langgraph-checkpoint")) == _ENGINE)
    return list(_ENGINE)


def _binding(row):
    return {
        "format": 1,
        "engine": wait_engine_version(),
        "session_id": row.session_id,
        "workflow_version_id": row.workflow_version_id,
        "graph_digest": canonical_digest(row.material["graph"]),
        "input_node": row.material["input_node"],
    }


def _start_id(row):
    return next(node["id"] for node in row.material["graph"]["nodes"] if node["data"]["type"] == "start")


def validate_linear_wait(snapshot, binding, start, next_node):
    _validate_size(snapshot)
    _require(type(snapshot) is dict)
    _require(all(type(snapshot.get(k)) is type(v) and snapshot[k] == v for k, v in binding.items()))
    _require(set(snapshot) == binding.keys() | {"checkpoint", "metadata", "variables", "memory", "steps"})
    start_channel, input_channel = f"branch:to:{start}", f"branch:to:{next_node}"
    cp = snapshot["checkpoint"]
    _require(type(cp) is dict and cp.keys() == _CHECKPOINT_KEYS and type(cp["v"]) is int and cp["v"] == 4)
    _require(all(type(cp[key]) is str and cp[key] for key in ("id", "ts")))
    channel_versions = cp["channel_versions"]
    _require(
        type(channel_versions) is dict
        and channel_versions.keys() == {"__start__", "flag", start_channel, input_channel}
        and all(type(value) is str for value in channel_versions.values())
    )
    seen = cp["versions_seen"]
    _require(
        type(seen) is dict
        and seen.keys() == {"__input__", "__start__", start}
        and seen["__input__"] == {}
        and all(
            type(seen[node]) is dict and seen[node].keys() == {channel} and type(seen[node][channel]) is str
            for node, channel in (("__start__", "__start__"), (start, start_channel))
        )
    )
    _require(cp["channel_values"] == {"flag": False, input_channel: None} and cp["channel_values"]["flag"] is False)
    _require(type(cp["updated_channels"]) is list and sorted(cp["updated_channels"]) == sorted([input_channel, "flag"]))
    metadata = snapshot["metadata"]
    _require(metadata == {"source": "loop", "step": 1, "parents": {}} and type(metadata["step"]) is int)
    variables, steps, memory = snapshot["variables"], snapshot["steps"], snapshot["memory"]
    _require(type(variables) is dict and variables.keys() == {start} and type(variables[start]) is dict)
    start_vars = variables[start]
    _require(start_vars.keys() == {"current_time", "chat_history", "preset_question", "custom_variables", "user_info"})
    _require(
        type(start_vars["current_time"]) is str
        and start_vars["chat_history"] == ""
        and type(start_vars["preset_question"]) is dict
        and type(start_vars["custom_variables"]) is dict
        and (start_vars["user_info"] is None or type(start_vars["user_info"]) is str)
    )
    _require(type(steps) is dict and steps.keys() == {start} and type(steps[start]) is int and steps[start] == 1)
    _require(
        type(memory) is dict
        and memory.keys() == {"k", "human_prefix", "ai_prefix"}
        and type(memory["k"]) is int
        and all(type(memory[key]) is str for key in ("human_prefix", "ai_prefix"))
    )


def capture_linear_wait(workflow, binding, start, next_node):
    engine = workflow.graph_engine
    config = engine.graph_config
    cp = engine.graph.checkpointer.get_tuple(config)
    _require(cp is not None and not cp.pending_writes)
    _require(engine.graph.get_state(config).next == (next_node,))
    memory = engine.graph_state.history_memory
    # 当前图在开始与首个输入之间不会产生历史消息。
    _require(memory is not None and not memory.chat_memory.messages)
    snapshot = {
        **binding,
        "checkpoint": cp.checkpoint,
        "metadata": cp.metadata,
        "variables": engine.graph_state.variables_pool,
        "memory": {"k": memory.k, "human_prefix": memory.human_prefix, "ai_prefix": memory.ai_prefix},
        "steps": {start: engine.nodes_map[start].current_step},
    }
    validate_linear_wait(snapshot, binding, start, next_node)
    return snapshot


def capture_wait(workflow, row, input_node):
    _require(input_node == row.material["input_node"])
    return capture_linear_wait(workflow, _binding(row), _start_id(row), input_node)


def restore_linear_wait(workflow, snapshot, thread_id, next_node):
    prepare_thread(workflow, thread_id)
    engine = workflow.graph_engine
    checkpoint = snapshot["checkpoint"]
    engine.graph.checkpointer.put(engine.graph_config, checkpoint, snapshot["metadata"], checkpoint["channel_versions"])
    _require(engine.graph.get_state(engine.graph_config).next == (next_node,))
    engine.graph_state.variables_pool = snapshot["variables"]
    engine.graph_state.history_memory = ConversationBufferWindowMemory(**snapshot["memory"])
    for node_id, step in snapshot["steps"].items():
        engine.nodes_map[node_id].current_step = step


def restore_wait(workflow, row, snapshot):
    try:
        input_node = row.material["input_node"]
        validate_linear_wait(snapshot, _binding(row), _start_id(row), input_node)
        restore_linear_wait(workflow, snapshot, row.session_id, input_node)
    except Exception as exc:
        raise RunError("RESUME_STATE_INVALID") from exc
