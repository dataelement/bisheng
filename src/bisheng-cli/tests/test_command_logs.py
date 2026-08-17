"""T025 — `bisheng logs`.

The recurring theme: everything authoritative happens on the server. Ownership is
judged there against the key's resource owner, keyword filtering happens there,
and the log retention window is whatever docker's rotation left behind. The CLI's
whole job is to forward the query, print what came back, and translate refusals
into sentences that point somewhere.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from bisheng_cli import credentials, project
from bisheng_cli.commands import logs as logs_mod
from bisheng_cli.errors import (
    EXIT_FORBIDDEN,
    EXIT_NOT_ENABLED,
    EXIT_NOT_LOGGED_IN,
    EXIT_OK,
    EXIT_PUBLISH_CONFLICT,
    EXIT_UNREACHABLE,
)
from bisheng_cli.main import run as main_run
from tests.helpers.platform_mock import (
    FAKE_KEY,
    FAKE_KEY_MASK,
    PlatformMock,
    use_mock_transport,
    v2_error,
)
from tests.helpers.platform_mock import (
    logs as logs_response,
)

BASE = "http://platform.test"
APP_ID = "app-1"
LOGS = f"/api/v2/apps/{APP_ID}/logs"


class _Stop(KeyboardInterrupt):
    """What Ctrl-C looks like to `--follow`."""


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


@pytest.fixture
def project_dir(sample_project: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project.save_app_ref(sample_project, BASE, app_id=APP_ID, app_name="问卷小应用")
    monkeypatch.chdir(sample_project)
    return sample_project


def _run(
    argv: list[str],
    *,
    monkeypatch: pytest.MonkeyPatch,
    mock: PlatformMock,
    sleeps: list[float] | None = None,
    stop_after: int = 1,
) -> tuple[int, str, str]:
    use_mock_transport(monkeypatch, logs_mod, mock)
    recorder = sleeps if sleeps is not None else []

    def _fake_sleep(seconds: float) -> None:
        recorder.append(seconds)
        if len(recorder) >= stop_after:
            raise _Stop

    monkeypatch.setattr(logs_mod, "_sleep", _fake_sleep)
    out, err = io.StringIO(), io.StringIO()
    code = main_run(argv, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_not_logged_in_exits_3_without_request(monkeypatch: pytest.MonkeyPatch, home_dir, sample_project: Path) -> None:
    monkeypatch.chdir(sample_project)
    mock = PlatformMock()
    code, _, err = _run(["logs"], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_NOT_LOGGED_IN
    assert "login" in err
    assert mock.paths_called() == []


def test_tail_since_keyword_forwarded_as_query_params(
    monkeypatch: pytest.MonkeyPatch, logged_in, project_dir: Path
) -> None:
    mock = PlatformMock().get(LOGS, logs_response(["hello"]))
    code, _, _ = _run(
        ["logs", "--tail", "50", "--since", "30m", "--keyword", "ERROR"], monkeypatch=monkeypatch, mock=mock
    )
    assert code == EXIT_OK
    params = mock.calls[0].url.params
    assert params["tail"] == "50" and params["since"] == "30m" and params["keyword"] == "ERROR"


def test_16254_owner_only_refused_with_readable_reason(
    monkeypatch: pytest.MonkeyPatch, logged_in, project_dir: Path
) -> None:
    mock = PlatformMock().get(LOGS, v2_error(16254, "owner only", http_status=403))
    code, _, err = _run(["logs"], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_PUBLISH_CONFLICT
    assert "归属人" in err


def test_16205_other_owner_refused(monkeypatch: pytest.MonkeyPatch, logged_in, project_dir: Path) -> None:
    mock = PlatformMock().get(LOGS, v2_error(16205, "belongs to somebody else", http_status=403))
    code, _, err = _run(["logs"], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_PUBLISH_CONFLICT
    assert "归属" in err


def test_cli_never_checks_ownership_itself(monkeypatch: pytest.MonkeyPatch, logged_in, project_dir: Path) -> None:
    # One request, straight to the logs endpoint. A CLI-side pre-check would be a
    # second judge working from data the CLI cannot see (the key's resource
    # owner), and the two would eventually disagree.
    mock = PlatformMock().get(LOGS, logs_response(["hello"]))
    _run(["logs"], monkeypatch=monkeypatch, mock=mock)
    assert mock.paths_called() == [LOGS]


def test_26003_missing_app_manage_exits_5(monkeypatch: pytest.MonkeyPatch, logged_in, project_dir: Path) -> None:
    mock = PlatformMock().get(LOGS, v2_error(26003, "scope missing", required="app:manage"))
    code, _, err = _run(["logs"], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_FORBIDDEN
    assert "app:manage" in err


def test_16207_layer_absent_exits_8(monkeypatch: pytest.MonkeyPatch, logged_in, project_dir: Path) -> None:
    mock = PlatformMock().get(LOGS, v2_error(16207, "runtime layer off", http_status=404))
    code, _, err = _run(["logs"], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_NOT_ENABLED
    assert "应用工场" in err


def test_empty_lines_prints_app_state_hint_not_blank(
    monkeypatch: pytest.MonkeyPatch, logged_in, project_dir: Path
) -> None:
    mock = PlatformMock().get(LOGS, logs_response([]))
    code, _, err = _run(["logs"], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_OK
    assert "没有运行实例" in err and "应用详情页" in err


def test_empty_lines_names_the_state_when_the_server_sends_it(
    monkeypatch: pytest.MonkeyPatch, logged_in, project_dir: Path
) -> None:
    """"Not running" and "running but quiet" need opposite next steps.

    The log text can never tell them apart, so the server names the state
    (F055 write-back 2). Listing all three candidates when the answer is known
    would be a worse answer than the one we have.
    """
    for state, expected, unexpected in (
        ("draft", "还是草稿", "已停运"),
        ("stopped", "已停运", "还是草稿"),
        ("online", "还没有输出任何日志", "没有运行实例"),
    ):
        mock = PlatformMock().get(LOGS, logs_response([], app_state=state))
        code, _, err = _run(["logs"], monkeypatch=monkeypatch, mock=mock)
        assert code == EXIT_OK
        assert expected in err, (state, err)
        assert unexpected not in err, (state, err)


def test_empty_lines_pending_capacity_includes_the_reason(
    monkeypatch: pytest.MonkeyPatch, logged_in, project_dir: Path
) -> None:
    mock = PlatformMock().get(LOGS, logs_response([], app_state="pending_capacity", pending_reason="capacity"))
    code, _, err = _run(["logs"], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_OK
    assert "待上线" in err and "capacity" in err


def test_follow_polls_with_since_every_3s(monkeypatch: pytest.MonkeyPatch, logged_in, project_dir: Path) -> None:
    mock = PlatformMock().get(LOGS, [logs_response(["a"]), logs_response(["b"])])
    sleeps: list[float] = []
    code, _, _ = _run(["logs", "--follow"], monkeypatch=monkeypatch, mock=mock, sleeps=sleeps, stop_after=2)
    assert code == EXIT_OK
    assert sleeps == [logs_mod.FOLLOW_INTERVAL, logs_mod.FOLLOW_INTERVAL] == [3.0, 3.0]
    # The first round has no `since` (the user gave none); every later round
    # carries one so the server does not resend the whole tail.
    assert "since" not in mock.calls[0].url.params
    assert "since" in mock.calls[1].url.params


def test_since_accepts_epoch_seconds_and_relative_window(
    monkeypatch: pytest.MonkeyPatch, logged_in, project_dir: Path
) -> None:
    for value in ("1700000000", "30m", "2h", "7d"):
        mock = PlatformMock().get(LOGS, logs_response(["x"]))
        code, _, _ = _run(["logs", "--since", value], monkeypatch=monkeypatch, mock=mock)
        assert code == EXIT_OK
        # Verbatim. Turning `30m` into an epoch locally would be a second
        # implementation of a semantics the server already owns.
        assert mock.calls[0].url.params["since"] == value


def test_keyword_may_return_fewer_lines_than_tail_is_not_a_bug(
    monkeypatch: pytest.MonkeyPatch, logged_in, project_dir: Path
) -> None:
    mock = PlatformMock().get(LOGS, logs_response(["only one match"]))
    code, _, err = _run(["logs", "--tail", "500", "--keyword", "match"], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_OK
    assert len(mock.calls) == 1  # no retry
    assert "警告" not in err


def test_16121_orchestrator_unavailable_says_retry_not_app_missing(
    monkeypatch: pytest.MonkeyPatch, logged_in, project_dir: Path
) -> None:
    # dockerd or runtime-manager down comes back as 503 → 16121. Reporting it as
    # "the app is gone" sends the owner to look for a deletion that never
    # happened.
    mock = PlatformMock().get(LOGS, v2_error(16121, "backend unavailable", http_status=503))
    code, _, err = _run(["logs"], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_UNREACHABLE
    assert "编排器不可用" in err and "可重试" in err
    assert "应用已删除" not in err


def test_follow_dedupes_same_second_repeats(monkeypatch: pytest.MonkeyPatch, logged_in, project_dir: Path) -> None:
    # docker timestamps are second-resolution, so the last second comes back
    # again in the next `since` window.
    first = logs_response(["line-a", "line-b", "line-c"])
    second = logs_response(["line-b", "line-c", "line-d"])
    mock = PlatformMock().get(LOGS, [first, second])
    code, _, err = _run(["logs", "--follow"], monkeypatch=monkeypatch, mock=mock, stop_after=2)
    assert code == EXIT_OK
    assert err.count("line-b") == 1 and err.count("line-c") == 1
    assert err.count("line-d") == 1


def test_app_id_resolution_same_as_deploy(monkeypatch: pytest.MonkeyPatch, logged_in, project_dir: Path) -> None:
    explicit = "/api/v2/apps/app-99/logs"
    mock = PlatformMock().get(explicit, logs_response(["x"]))
    code, _, _ = _run(["logs", "--app-id", "app-99"], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_OK
    assert mock.paths_called() == [explicit]

    saved = PlatformMock().get(LOGS, logs_response(["x"]))
    code, _, _ = _run(["logs"], monkeypatch=monkeypatch, mock=saved)
    assert code == EXIT_OK
    assert saved.paths_called() == [LOGS]


def test_since_empty_says_no_logs_in_range_or_rotated_not_never_happened(
    monkeypatch: pytest.MonkeyPatch, logged_in, project_dir: Path
) -> None:
    mock = PlatformMock().get(LOGS, logs_response([]))
    code, _, err = _run(["logs", "--since", "7d"], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_OK
    assert "轮转" in err
    assert "什么都没发生" in err  # stated as what the CLI cannot claim
