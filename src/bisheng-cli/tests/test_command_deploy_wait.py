"""T023 — `bisheng deploy` polling, stage output and the `--wait` terminal states.

Two invariants this file defends.

**Stage order is the server's business.** The eleven stage values are a *set*,
not a sequence. The server already reordered `secret_scan` relative to the
precheck stages once; a CLI that asserts an order turns the next reordering into
a client-side bug and drags the README along with it. So the assertions here are
"any order survives" and "an unknown stage prints verbatim", never a fixed list.

**`cancelled` and `exception` end the wait immediately.** An application deleted
mid-flight and an approval with no resolvable approver both produce requests that
will never reach a decision. Recognising only the four "normal" terminal states
means `--wait` polls until the timeout and then prints "this is not a failure,
keep waiting" — advice that is exactly backwards.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from bisheng_cli import credentials
from bisheng_cli.commands import deploy as deploy_mod
from bisheng_cli.commands.deploy import (
    POLL_INTERVAL_MAX,
    POLL_INTERVAL_START,
    next_interval,
)
from bisheng_cli.errors import (
    EXIT_APPROVAL_EXCEPTION,
    EXIT_CANCELLED,
    EXIT_OK,
    EXIT_PENDING_ONLINE,
    EXIT_PRECHECK_FAILED,
    EXIT_REJECTED,
    EXIT_SECRET_FOUND,
    EXIT_WAIT_TIMEOUT,
    EXIT_WITHDRAWN,
)
from bisheng_cli.main import run as main_run
from tests.helpers.platform_mock import (
    FAKE_KEY,
    FAKE_KEY_MASK,
    PlatformMock,
    deploy_accept,
    deploy_limits,
    deployment,
    deployment_seq,
    failure_tuple,
    use_mock_transport,
)

BASE = "http://platform.test"
LIMITS = "/api/v2/apps/deploy-limits"
DEPLOY = "/api/v2/apps/deploy"
POLL = "/api/v2/apps/deployments/dep-1"

# The authoritative enumeration (F055 design). Order below is F055's own writing
# order and is used here only as "a set of values", never as a schedule.
SERVER_STAGES = (
    "received",
    "secret_scan",
    "precheck_manifest",
    "precheck_build",
    "precheck_probe",
    "version_recorded",
    "approval_created",
    "approved",
    "publishing",
    "online",
    "pending_online",
)


@pytest.fixture
def logged_in(home_dir) -> None:
    credentials.save_profile(
        BASE,
        {
            "api_key": FAKE_KEY,
            "key_mask": FAKE_KEY_MASK,
            "tenant_id": 1,
            "service_account": {"id": 123, "name": "问卷小队开发号"},
        },
    )


def _mock(polls: list) -> PlatformMock:
    return PlatformMock().get(LIMITS, deploy_limits()).post(DEPLOY, deploy_accept()).get(POLL, deployment_seq(polls))


def _run(
    argv: list[str], *, monkeypatch: pytest.MonkeyPatch, mock: PlatformMock, sleeps: list[float] | None = None
) -> tuple[int, str, str]:
    use_mock_transport(monkeypatch, deploy_mod, mock)
    recorder = sleeps if sleeps is not None else []
    monkeypatch.setattr(deploy_mod, "_sleep", lambda seconds: recorder.append(seconds))
    out, err = io.StringIO(), io.StringIO()
    code = main_run(argv, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def _events(stdout: str) -> list[dict]:
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def _waiting(**kw):
    payload = {
        "stage": "approval_created",
        "status": "waiting_approval",
        "approval": {"instance_id": "ap-1", "status": "pending"},
    }
    payload.update(kw)
    return deployment(**payload)


def test_stage_events_in_server_order_received_first(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    # The very first polling response carries `received`. Leaving it out of the
    # label table would drop every deploy's first line into the unknown-stage
    # branch.
    mock = _mock([deployment(stage="received", status="running"), _waiting()])
    code, out, err = _run(["--json", "deploy", str(sample_project)], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_OK
    stages = [event["stage"] for event in _events(out) if event["event"] == "stage"]
    assert stages[0] == "received"
    assert "received" not in err  # translated for humans, not echoed raw
    assert "已接收" in err


def test_all_eleven_server_stages_translate_or_pass_through(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    polls = [deployment(stage=stage, status="running") for stage in SERVER_STAGES]
    polls.append(_waiting())
    mock = _mock(polls)
    code, out, _ = _run(["--json", "deploy", str(sample_project)], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_OK
    stages = [event["stage"] for event in _events(out) if event["event"] == "stage"]
    assert set(SERVER_STAGES) <= set(stages)
    # `approval_created` stays the machine value; the Chinese phrase is display
    # only, and swapping them makes `--json` disagree with the server.
    assert "approval_created" in stages


def test_stage_translation_is_a_mapping_not_an_ordered_sequence(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    shuffled = ["precheck_probe", "secret_scan", "received", "precheck_build", "version_recorded"]
    polls = [deployment(stage=stage, status="running") for stage in shuffled]
    polls.append(_waiting())
    code, out, _ = _run(["--json", "deploy", str(sample_project)], monkeypatch=monkeypatch, mock=_mock(polls))
    assert code == EXIT_OK
    stages = [event["stage"] for event in _events(out) if event["event"] == "stage"]
    assert stages[: len(shuffled)] == shuffled


def test_unknown_stage_printed_verbatim_not_an_error(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    polls = [deployment(stage="quantum_review", status="running"), _waiting()]
    code, out, err = _run(["--json", "deploy", str(sample_project)], monkeypatch=monkeypatch, mock=_mock(polls))
    assert code == EXIT_OK
    assert "quantum_review" in err
    assert "quantum_review" in [e.get("stage") for e in _events(out)]


def test_any_failed_stage_stops_polling_and_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    failed = deployment(
        stage="precheck_build",
        status="failed",
        failure=failure_tuple("precheck_build", 16227, "pip install failed"),
    )
    mock = _mock([deployment(stage="received", status="running"), failed, _waiting()])
    code, _, _ = _run(["deploy", str(sample_project)], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_PRECHECK_FAILED
    # Two polls, then stop — the third response was never fetched.
    assert mock.paths_called().count(POLL) == 2


def test_failure_tuple_passed_through_untouched_in_json(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    tuple_ = failure_tuple("precheck_manifest", 16221, "missing field", missing=["port"])
    mock = _mock([deployment(stage="precheck_manifest", status="failed", failure=tuple_)])
    code, out, _ = _run(["--json", "deploy", str(sample_project)], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_PRECHECK_FAILED
    result = _events(out)[-1]
    assert result["event"] == "result"
    # Byte for byte: `details` and `hints` are the agent's whole repair input.
    assert result["failure"] == tuple_


def test_precheck_failure_prints_missing_items_and_hints_lines(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    tuple_ = failure_tuple("precheck_manifest", 16221, "manifest 缺少 port", missing=["port"])
    mock = _mock([deployment(stage="precheck_manifest", status="failed", failure=tuple_)])
    code, _, err = _run(["deploy", str(sample_project)], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_PRECHECK_FAILED
    assert "manifest 缺少 port" in err
    assert "hint for 16221" in err


def test_16241_scan_hit_prints_file_line_only_never_the_value(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    secret = "bs-sak-" + "z" * 20
    tuple_ = failure_tuple(
        "secret_scan",
        16241,
        "扫描命中",
        hits=[{"rule_id": "bisheng-service-account-key", "file": "config/settings.py", "line": 12}],
    )
    mock = _mock([deployment(stage="secret_scan", status="failed", failure=tuple_)])
    (sample_project / "config").mkdir(exist_ok=True)
    (sample_project / "config" / "settings.py").write_text(f'KEY = "{secret}"\n', encoding="utf-8")

    code, out, err = _run(["--json", "deploy", str(sample_project)], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_SECRET_FOUND
    assert "config/settings.py:12" in err
    # The server withholds even a redacted value on purpose; reading the line
    # back out of the local file would hand back what it refused to give.
    assert secret not in err and secret not in out


def test_default_returns_0_at_waiting_approval_with_three_tracking_paths(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    mock = _mock([deployment(stage="received", status="running"), _waiting()])
    code, _, err = _run(["deploy", str(sample_project)], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_OK
    assert "ap-1" in err
    assert "应用详情页" in err and "MCP" in err and "deploy --wait" in err


def test_wait_online_exits_0_with_entry_url_or_pointer(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    online = deployment(
        stage="online",
        status="succeeded",
        approval={"instance_id": "ap-1", "status": "executed"},
        app_state="已上线",
    )
    mock = _mock([deployment(stage="publishing", status="running"), online])
    code, _, err = _run(["deploy", str(sample_project), "--wait"], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_OK
    # An older platform omits `entry_url` from the poll; the pointer is then the
    # honest answer rather than a printed `None`.
    assert "应用详情页" in err and "None" not in err


def test_wait_online_prints_the_entry_url_when_the_poll_carries_it(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    """The address is the one thing the developer actually wants at this moment.

    It used to be unreachable here: `entry_url` lived only on the POST response,
    where a first deploy is still a draft and the value was null. F055's
    write-back puts it on every poll, so `--wait` can end with a real link
    instead of sending the developer to a page to look it up.
    """
    online = deployment(
        stage="online",
        status="succeeded",
        approval={"instance_id": "ap-1", "status": "executed"},
        app_state="已上线",
        entry_url="https://bisheng.example.com/apps/form-survey",
    )
    mock = _mock([deployment(stage="publishing", status="running"), online])
    code, _, err = _run(["deploy", str(sample_project), "--wait"], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_OK
    assert "https://bisheng.example.com/apps/form-survey" in err


def test_wait_rejected_exits_20_with_full_reason(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    reason = "驳回理由" + "，需要补充数据留存说明并说明外呼域名" * 5
    rejected = deployment(
        stage="approval_created",
        status="waiting_approval",
        approval={"instance_id": "ap-1", "status": "rejected", "reject_reason": reason},
    )
    code, _, err = _run(["deploy", str(sample_project), "--wait"], monkeypatch=monkeypatch, mock=_mock([rejected]))
    assert code == EXIT_REJECTED
    assert reason in err  # never truncated: it is the instruction for the retry


def test_wait_withdrawn_exits_21(monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path) -> None:
    withdrawn = deployment(
        stage="approval_created",
        status="waiting_approval",
        approval={"instance_id": "ap-1", "status": "withdrawn"},
    )
    code, _, err = _run(["deploy", str(sample_project), "--wait"], monkeypatch=monkeypatch, mock=_mock([withdrawn]))
    assert code == EXIT_WITHDRAWN
    assert "应用详情页" in err


def test_wait_pending_online_exits_22_with_manual_publish_path(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    pending = deployment(
        stage="pending_online",
        status="succeeded",
        approval={"instance_id": "ap-1", "status": "executed"},
        app_state="待上线",
        pending_reason="capacity",
    )
    code, _, err = _run(["deploy", str(sample_project), "--wait"], monkeypatch=monkeypatch, mock=_mock([pending]))
    assert code == EXIT_PENDING_ONLINE
    assert "capacity" in err and "手动上线" in err


def test_wait_cancelled_exits_24_immediately_not_timeout(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    cancelled = deployment(
        stage="approval_created",
        status="running",
        approval={"instance_id": "ap-1", "status": "cancelled"},
    )
    sleeps: list[float] = []
    code, _, err = _run(
        ["deploy", str(sample_project), "--wait"], monkeypatch=monkeypatch, mock=_mock([cancelled]), sleeps=sleeps
    )
    assert code == EXIT_CANCELLED
    assert sleeps == []  # decided on the first poll, no waiting at all
    assert "已被删除" in err and "永远不会有结论" in err


def test_wait_exception_exits_25_immediately_not_timeout(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    exception = deployment(
        stage="approval_created",
        status="running",
        approval={"instance_id": "ap-1", "status": "exception"},
    )
    sleeps: list[float] = []
    code, _, err = _run(
        ["deploy", str(sample_project), "--wait"],
        monkeypatch=monkeypatch,
        mock=_mock([exception]),
        sleeps=sleeps,
    )
    assert code == EXIT_APPROVAL_EXCEPTION
    assert sleeps == []
    assert "审批人" in err and "管理员" in err


def test_wait_timeout_exits_23_and_says_not_a_failure(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    pending = deployment(
        stage="approval_created",
        status="waiting_approval",
        approval={"instance_id": "ap-1", "status": "pending"},
    )
    code, _, err = _run(
        ["deploy", str(sample_project), "--wait", "--wait-timeout", "0"],
        monkeypatch=monkeypatch,
        mock=_mock([pending]),
    )
    assert code == EXIT_WAIT_TIMEOUT
    # Timeout and rejection lead to opposite actions — keep waiting vs change the
    # code — so the copy has to separate them explicitly.
    assert "这不是失败" in err


def test_backoff_2s_x1_5_capped_10s() -> None:
    schedule: list[float] = []
    interval = POLL_INTERVAL_START
    for poll in range(1, 31):
        schedule.append(interval)
        interval = next_interval(interval, poll)

    assert schedule[:5] == [2.0] * 5
    assert schedule[5:10] == [3.0] * 5
    assert schedule[10:15] == [4.5] * 5
    assert max(schedule) == POLL_INTERVAL_MAX == 10.0
    assert schedule[-1] == 10.0
