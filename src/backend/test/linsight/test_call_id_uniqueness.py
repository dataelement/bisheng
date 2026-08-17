"""Regression: providers whose tool_call ids are only unique WITHIN one response
must not lose execution history.

Session ``8a570723…`` on 114 (kimi-k3 via tokenrouter) issued 156
``bisheng_code_interpreter`` calls, 9 ``read_file`` and 2 ``write_file`` across 171
model turns — yet ``linsight_execute_task.history`` ended up holding 4 tool rows,
and the step flow read "运行代码 1 次 · 编辑 1 个文件".

Cause: tokenrouter mints ``<tool_name>:<index>`` and restarts the index at 0 on
every response (probing its ``/chat/completions`` returns ``read_file:0`` /
``read_file:1``). That is legal — the OpenAI contract only requires the id to be
the handle a ToolMessage refers back to, never a cross-request guarantee. But
``add_execution_task_step`` upserts by call_id across the WHOLE history, so each
call silently overwrote its predecessor.

Fix: the mapper mints the id it emits (``<raw>#<run_token>:<seq>``) while its own
bookkeeping dicts stay keyed by the provider's value — that is what comes back on
``ToolMessage.tool_call_id``. These tests drive the real mapper into the real
persistence upsert, which nothing covered end-to-end before.
"""

from langchain_core.messages import AIMessage, ToolMessage

from bisheng.linsight.domain.services.stream_event_mapper import StreamEventMapper
from bisheng_langchain.linsight.event import ExecStep
from test.linsight.test_step_persistence import _make_manager

SVID = "8a570723-0838-47a7-b2c0-df2a3be9879f"


def _steps(mapper: StreamEventMapper, message) -> list[ExecStep]:
    return [e for e in mapper.normalize("messages", (message, {})) if isinstance(e, ExecStep)]


def _call_round(mapper: StreamEventMapper, *, tool: str, raw_id: str, args: dict, output: str) -> list[ExecStep]:
    """One model turn: the AIMessage announcing a tool call, then its result."""
    start = AIMessage(content="", tool_calls=[{"id": raw_id, "name": tool, "args": args}])
    end = ToolMessage(content=output, tool_call_id=raw_id, name=tool)
    return _steps(mapper, start) + _steps(mapper, end)


async def _persist(mgr, steps: list[ExecStep]) -> None:
    for step in steps:
        await mgr.add_execution_task_step("t1", step)


async def test_repeated_provider_id_keeps_one_row_per_call(monkeypatch):
    """The exact 114 failure: N turns reusing ``bisheng_code_interpreter:0``.

    Each turn is a start+end pair that must fold into ONE row (that part always
    worked); what regressed is that turn N+1 used to overwrite turn N's row.
    """
    mgr, store = _make_manager(monkeypatch)
    mapper = StreamEventMapper(svid=SVID)

    rounds = 6
    for i in range(rounds):
        await _persist(
            mgr,
            _call_round(
                mapper,
                tool="bisheng_code_interpreter",
                raw_id="bisheng_code_interpreter:0",  # provider restarts at 0 each turn
                args={"python_code": f"print({i})"},
                output=f"out-{i}",
            ),
        )

    assert len(store["history"]) == rounds, "each tool call must own a history row"
    # ...and in call order, with nothing overwritten.
    assert [h["output"] for h in store["history"]] == [f"out-{i}" for i in range(rounds)]


async def test_ids_do_not_collide_across_mapper_instances(monkeypatch):
    """A mapper is built fresh per RUN of one session version (first execute /
    ask_user resume / follow-up turn), all sharing one svid. A per-instance
    counter alone would restart at 1 and overwrite the earlier run's rows, so the
    id also carries ``run_token`` — same reasoning as thinking segments.
    """
    mgr, store = _make_manager(monkeypatch)

    for run, output in ((StreamEventMapper(svid=SVID), "first-run"), (StreamEventMapper(svid=SVID), "resumed-run")):
        await _persist(
            mgr,
            _call_round(
                run, tool="read_file", raw_id="read_file:0", args={"file_path": "/uploads/a.md"}, output=output
            ),
        )

    assert len(store["history"]) == 2
    assert [h["output"] for h in store["history"]] == ["first-run", "resumed-run"]


async def test_parallel_calls_in_one_response_stay_separate(monkeypatch):
    """Two calls inside a SINGLE response: here the provider's ids do differ
    (``read_file:0`` / ``read_file:1``), and each must still end its own row —
    this is the case that rules out "only merge against history[-1]" as a fix.
    """
    mgr, store = _make_manager(monkeypatch)
    mapper = StreamEventMapper(svid=SVID)

    start = AIMessage(
        content="",
        tool_calls=[
            {"id": "read_file:0", "name": "read_file", "args": {"file_path": "/uploads/a.md"}},
            {"id": "read_file:1", "name": "read_file", "args": {"file_path": "/uploads/b.md"}},
        ],
    )
    await _persist(mgr, _steps(mapper, start))
    # Results come back interleaved-last, as they do on the wire.
    for raw_id, output in (("read_file:0", "内容A"), ("read_file:1", "内容B")):
        await _persist(mgr, _steps(mapper, ToolMessage(content=output, tool_call_id=raw_id, name="read_file")))

    assert len(store["history"]) == 2
    assert sorted(h["output"] for h in store["history"]) == ["内容A", "内容B"]
    assert all(h["status"] == "end" for h in store["history"]), "end frame must supersede its start"


async def test_globally_unique_provider_ids_are_unaffected(monkeypatch):
    """Guard on the promise made when choosing this fix: a provider that already
    returns globally-unique ids (OpenAI's ``call_xxx``) behaves exactly as before —
    one row per call, start/end still merged. Only the stored id string changes.
    """
    mgr, store = _make_manager(monkeypatch)
    mapper = StreamEventMapper(svid=SVID)

    for i in range(3):
        await _persist(
            mgr,
            _call_round(mapper, tool="search", raw_id=f"call_abc{i}", args={"q": str(i)}, output=f"r-{i}"),
        )

    assert len(store["history"]) == 3
    assert [h["output"] for h in store["history"]] == ["r-0", "r-1", "r-2"]
    # The provider's id stays greppable as the prefix.
    assert [h["call_id"].split("#")[0] for h in store["history"]] == ["call_abc0", "call_abc1", "call_abc2"]
