"""覆盖 AC: AC-15、AC-36、AC-37、AC-43、AC-48、AC-50."""

import hashlib
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from bisheng.common.errcode.app_factory import AppDataBusyError, AppDataForbiddenError
from test.app_runtime.test_runtime_data_sessions import repo as repo
from test.app_runtime.test_runtime_data_sessions import session as session


async def test_unknown_write_is_queried_only_through_a_new_read_session(session):
    c = session
    original = await c.svc._start(c.app, c.actor, "update", {"table": "items", "key": "1", "values": {"name": "new"}})
    original.status, original.stage, original.cleanup_status = "failed", "failed", "complete"
    original.payload = {**original.payload, "data_action_finished": "unknown"}
    await c.repo.save(original)
    await c.repo.release(original.id, stopped=True)
    observed = []

    async def call(app_id, action, parameters, ticket, *, timeout):
        observed.append((action, parameters, ticket))
        return {
            "state": "done",
            "request_id": original.payload["request_id"],
            "result": {"before": {"name": "old"}, "after": {"name": "new"}},
        }

    c.transport.call = call
    result = await c.svc.recover(c.app, c.actor, original.id)
    assert result["state"] == "done"
    assert observed[0][0] == "result" and len(observed) == 1
    assert observed[0][1] == {
        "target_request_id": original.payload["request_id"],
        "parameters_sha256": original.payload["parameters_digest"],
    }
    assert observed[0][2]["claims"]["request_id"] != original.payload["request_id"]
    assert observed[0][2]["claims"]["operation_id"] != original.id


async def test_recovery_cannot_drop_an_unknown_writer_mutex_or_widen_owner(session):
    c = session
    original = await c.svc._start(c.app, c.actor, "update", {"table": "items", "key": "1", "values": {"name": "new"}})
    with pytest.raises(AppDataBusyError):
        await c.svc.recover(c.app, c.actor, original.id)
    with pytest.raises(AppDataForbiddenError):
        await c.svc.recover(c.app, SimpleNamespace(user_id=2, is_global_super=True), original.id)
    assert c.transport.calls == 0


@pytest.mark.parametrize("wrong_digest", [False, True])
async def test_export_uses_bounded_stream_and_removes_incomplete_files(tmp_path, monkeypatch, wrong_digest):
    from bisheng.app_runtime.domain.services import runtime_data_session_service as mod

    data = b"id,name\n" + b"1,fixture\n" * 10000

    class Bytes(httpx.AsyncByteStream):
        async def __aiter__(self):
            for offset in range(0, len(data), 7000):
                yield data[offset : offset + 7000]

    def response(request):
        return httpx.Response(
            200,
            stream=Bytes(),
            headers={
                "Content-Length": str(len(data)),
                "X-Content-Sha256": "0" * 64 if wrong_digest else hashlib.sha256(data).hexdigest(),
            },
        )

    monkeypatch.setattr(
        mod,
        "settings",
        SimpleNamespace(
            app_runtime=SimpleNamespace(
                manager_base_url="http://manager", runtime_control_key_id="platform", runtime_control_secret="fixture"
            )
        ),
    )
    transport = mod._DataTransport(http_transport=httpx.MockTransport(response), cache_root=tmp_path / "exports")
    ticket = {"claims": {"operation_id": "op", "request_id": "request"}}
    if wrong_digest:
        with pytest.raises(AppDataBusyError):
            await transport.call("app-a", "export", {"table": "items"}, ticket, timeout=60)
        assert not list(tmp_path.rglob("*.csv"))
    else:
        result = await transport.call("app-a", "export", {"table": "items"}, ticket, timeout=60)
        assert isinstance(result, Path) and result.read_bytes() == data
        assert result.stat().st_mode & 0o077 == 0
        result.unlink()
        result.parent.rmdir()
