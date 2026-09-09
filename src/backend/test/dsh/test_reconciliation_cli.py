"""T064: Coverage AC: AC-23, AC-28, AC-29, AC-30, AC-31."""

import pytest

from bisheng.dsh.cli.reconcile import build_parser, run


def test_no_actor_or_force_override_flags():
    for flag in ["--actor-id", "--force-unfreeze", "--set-zero"]:
        with pytest.raises(SystemExit):
            build_parser().parse_args(["status", "--tenant-id", "2", "--operation-id", "op", flag, "1"])


async def test_hidden_login_and_processing_output():
    calls = []

    class Service:
        async def status(self, operation_id, *, actor_user_id):
            calls.append((operation_id, actor_user_id))
            return {"operation_id": operation_id, "status": "PROCESSING", "payload": {"sensitive": "never-print"}}

    async def authenticate(token, *, tenant_id):
        assert tenant_id == 2
        assert token == "hidden-jwt"
        return 7

    result = await run(
        ["status", "--tenant-id", "2", "--operation-id", "op"],
        service=Service(),
        authenticate=authenticate,
        credential_reader=lambda prompt: "hidden-jwt",
    )
    assert calls == [("op", 7)]
    assert result == {"operation_id": "op", "status": "PROCESSING"}
