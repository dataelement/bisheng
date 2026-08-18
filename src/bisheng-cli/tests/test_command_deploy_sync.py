"""T021 — `bisheng deploy`, synchronous leg.

This file carries red line 1. `POST /api/v2/apps/deploy` answers with the
ownership, size, unpack, manifest, local-reference and in-flight verdicts *in the
response to the upload itself* — the deployment row does not exist yet. None of
those failures can appear in the polling payload, so every one of them must
terminate the command where it is raised. The mock enforces this structurally:
the polling path is simply not registered, so a run that starts polling fails
with "unexpected request".
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from bisheng_cli import credentials
from bisheng_cli.commands import deploy as deploy_mod
from bisheng_cli.errors import (
    EXIT_FORBIDDEN,
    EXIT_LOCAL_INVALID,
    EXIT_NOT_ENABLED,
    EXIT_NOT_LOGGED_IN,
    EXIT_OK,
    EXIT_PUBLISH_CONFLICT,
)
from bisheng_cli.main import run as main_run
from tests.helpers.platform_mock import (
    FAKE_KEY,
    FAKE_KEY_MASK,
    PlatformMock,
    deploy_accept,
    deploy_limits,
    deploy_sync_err,
    deployment,
    use_mock_transport,
)

BASE = "http://platform.test"
LIMITS = "/api/v2/apps/deploy-limits"
DEPLOY = "/api/v2/apps/deploy"


class _Tty(io.StringIO):
    """A stream that claims to be a terminal, so the interactive path is reachable."""

    def isatty(self) -> bool:
        return True


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


def _mock(*, limits: bool = True) -> PlatformMock:
    mock = PlatformMock()
    if limits:
        mock.get(LIMITS, deploy_limits())
    return mock


def _run(
    argv: list[str],
    *,
    monkeypatch: pytest.MonkeyPatch,
    mock: PlatformMock,
    tty: bool = False,
) -> tuple[int, str, str]:
    use_mock_transport(monkeypatch, deploy_mod, mock)
    monkeypatch.setattr(deploy_mod, "_sleep", lambda _s: None)
    out: io.StringIO = io.StringIO()
    err: io.StringIO = _Tty() if tty else io.StringIO()
    code = main_run(argv, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def _waiting_seq() -> list:
    return [
        deployment(stage="received", status="running"),
        deployment(
            stage="approval_created",
            status="waiting_approval",
            approval={"instance_id": "ap-1", "status": "pending"},
        ),
    ]


def test_not_logged_in_exits_3_without_any_request(
    monkeypatch: pytest.MonkeyPatch, home_dir, sample_project: Path
) -> None:
    mock = _mock()
    code, _, err = _run(["deploy", str(sample_project)], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_NOT_LOGGED_IN
    assert "login" in err
    assert mock.paths_called() == []


def test_local_manifest_failure_refuses_before_packaging(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    (sample_project / "bisheng-app.yaml").unlink()
    mock = _mock()
    code, _, err = _run(["deploy", str(sample_project)], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_LOCAL_INVALID
    assert "bisheng-app.yaml" in err
    assert mock.paths_called() == []


def test_dry_run_stops_after_packaging_and_prints_stats(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    mock = _mock()
    code, _, err = _run(["deploy", str(sample_project), "--dry-run"], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_OK
    assert "已排除" in err and "打包条目" in err and "未上传" in err
    # Nothing at all is created on the platform by a dry run.
    assert mock.paths_called() == []


def test_oversize_refused_locally_with_top10(monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path) -> None:
    mock = _mock(limits=False).get(LIMITS, deploy_limits(max_package_mb=0))
    code, _, err = _run(["deploy", str(sample_project)], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_LOCAL_INVALID
    assert "整包拒绝" in err
    # The excluded count comes before the file list: "the limit is too small" is
    # the wrong first conclusion nine times out of ten.
    assert err.index("已排除") < err.index("Top 文件")
    assert DEPLOY not in mock.paths_called()


def test_upload_is_streamed_multipart_not_read_bytes(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    def _forbidden(self, *a, **kw):  # pragma: no cover - must never run
        raise AssertionError("the package was slurped into memory via read_bytes()")

    monkeypatch.setattr(Path, "read_bytes", _forbidden)

    mock = _mock().post(DEPLOY, deploy_accept()).get("/api/v2/apps/deployments/dep-1", _waiting_seq())
    code, _, _ = _run(["deploy", str(sample_project)], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_OK
    upload = next(call for call in mock.calls if call.url.path == DEPLOY)
    assert upload.headers["content-type"].startswith("multipart/form-data")


def test_app_id_persisted_immediately_on_http_200_even_if_pipeline_later_fails(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    # The platform has already created a draft application and assigned this id.
    # Saving it only on success means the next attempt creates a second one.
    failed = deployment(
        stage="precheck_build",
        status="failed",
        failure={"stage": "precheck_build", "code": 16227, "message": "pip failed", "details": {}, "hints": []},
    )
    mock = _mock().post(DEPLOY, deploy_accept(app_id="app-42")).get("/api/v2/apps/deployments/dep-1", failed)
    code, _, _ = _run(["deploy", str(sample_project)], monkeypatch=monkeypatch, mock=mock)

    assert code != EXIT_OK
    saved = json.loads((sample_project / ".bisheng" / "app.json").read_text(encoding="utf-8"))
    assert saved["apps"][BASE]["app_id"] == "app-42"


def test_iterative_deploy_prints_target_app_name_and_id_before_upload(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    from bisheng_cli import project

    project.save_app_ref(sample_project, BASE, app_id="app-7", app_name="问卷小应用")
    mock = _mock().post(DEPLOY, deploy_accept(app_id="app-7")).get("/api/v2/apps/deployments/dep-1", _waiting_seq())
    code, _, err = _run(["deploy", str(sample_project)], monkeypatch=monkeypatch, mock=mock)

    assert code == EXIT_OK
    assert err.index("问卷小应用") < err.index("开始上传")
    assert "app-7" in err


def test_interactive_confirm_skipped_by_yes_flag(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    from bisheng_cli import project

    def _explode(_prompt: str) -> str:  # pragma: no cover - must never run
        raise AssertionError("prompted despite --yes")

    monkeypatch.setattr("builtins.input", _explode)
    project.save_app_ref(sample_project, BASE, app_id="app-7", app_name="问卷小应用")
    mock = _mock().post(DEPLOY, deploy_accept(app_id="app-7")).get("/api/v2/apps/deployments/dep-1", _waiting_seq())
    code, _, _ = _run(["deploy", str(sample_project), "--yes"], monkeypatch=monkeypatch, mock=mock, tty=True)
    assert code == EXIT_OK


def test_first_deploy_prints_app_id_and_entry_url_when_present_else_points_to_detail_page(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    with_url = _mock().post(DEPLOY, deploy_accept(entry_url="http://platform.test/apps/app-1"))
    with_url.get("/api/v2/apps/deployments/dep-1", _waiting_seq())
    code, _, err = _run(["deploy", str(sample_project)], monkeypatch=monkeypatch, mock=with_url)
    assert code == EXIT_OK and "http://platform.test/apps/app-1" in err

    (sample_project / ".bisheng" / "app.json").unlink()
    without = _mock().post(DEPLOY, deploy_accept(entry_url=None))
    without.get("/api/v2/apps/deployments/dep-1", _waiting_seq())
    code, _, err = _run(["deploy", str(sample_project)], monkeypatch=monkeypatch, mock=without)
    assert code == EXIT_OK
    # Neither an empty string nor the word None: a pointer to where it lives.
    assert "应用详情页" in err and "None" not in err


def test_26003_missing_app_manage_refused_and_names_the_required_scope(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    mock = _mock().post(DEPLOY, deploy_sync_err(26003, "scope missing", required="app:manage"))
    code, _, err = _run(["deploy", str(sample_project)], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_FORBIDDEN
    # `data.required` is one string. Joining it as a list prints "a, p, p, :, m…".
    assert "app:manage" in err


def test_16205_other_owner_refused_and_names_the_owner(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    mock = _mock().post(DEPLOY, deploy_sync_err(16205, "该应用归属于 张三", http_status=403, owner_user_name="张三"))
    code, out, err = _run(["--json", "deploy", str(sample_project)], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_PUBLISH_CONFLICT
    assert "张三" in err
    result = json.loads(out.strip().splitlines()[-1])
    assert result["failure"]["details"]["owner_user_name"] == "张三"


def test_16251_in_flight_approval_refused_with_withdraw_path(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    mock = _mock().post(DEPLOY, deploy_sync_err(16251, "in flight", http_status=409))
    code, _, err = _run(["deploy", str(sample_project)], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_PUBLISH_CONFLICT
    assert "应用详情页" in err and "撤回" in err


def test_16252_pending_online_refused(monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path) -> None:
    mock = _mock().post(DEPLOY, deploy_sync_err(16252, "pending online", http_status=409))
    code, _, err = _run(["deploy", str(sample_project)], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_PUBLISH_CONFLICT
    assert "待上线" in err


def test_16229_schema_change_requires_confirm_flag(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    mock = _mock().post(DEPLOY, deploy_sync_err(16229, "schema change unconfirmed", http_status=409))
    code, _, err = _run(["deploy", str(sample_project)], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_PUBLISH_CONFLICT
    assert "--confirm-schema-change" in err
    # Terminated at the synchronous response: no approval request was created,
    # and no polling happened.
    assert mock.paths_called().count(DEPLOY) == 1


def test_confirm_schema_change_flag_forwarded_as_form_field(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    mock = _mock().post(DEPLOY, deploy_accept()).get("/api/v2/apps/deployments/dep-1", _waiting_seq())
    _run(["deploy", str(sample_project), "--confirm-schema-change"], monkeypatch=monkeypatch, mock=mock)
    body = next(call for call in mock.calls if call.url.path == DEPLOY).content
    assert b'name="confirm_schema_change"' in body
    assert b"true" in body


def test_16207_workshop_runtime_layer_absent_exits_8(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    mock = _mock().post(DEPLOY, deploy_sync_err(16207, "app runtime disabled", http_status=404))
    code, _, err = _run(["deploy", str(sample_project)], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_NOT_ENABLED
    assert "应用工场" in err


@pytest.mark.parametrize("code", [16201, 16202, 16203])
def test_16201_16202_16203_map_to_exit_6(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path, code: int
) -> None:
    mock = _mock().post(DEPLOY, deploy_sync_err(code, f"gate {code}", http_status=400))
    exit_code, _, err = _run(["deploy", str(sample_project)], monkeypatch=monkeypatch, mock=mock)
    assert exit_code == EXIT_LOCAL_INVALID
    if code == 16203:
        # 16203 after a passing local check can only mean the package root is
        # not the project root; "create a manifest" would send the user in a
        # circle, since they already have one.
        assert "包根" in err
        assert "创建" not in err


def test_sync_error_never_enters_polling_loop(monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path) -> None:
    # The polling route is deliberately not registered: entering the loop hits
    # the mock's "unexpected request" assertion instead of quietly succeeding.
    mock = _mock().post(DEPLOY, deploy_sync_err(16221, "manifest invalid", http_status=400))
    code, _, _ = _run(["deploy", str(sample_project)], monkeypatch=monkeypatch, mock=mock)
    assert code == 10
    assert not [path for path in mock.paths_called() if "deployments" in path]


# ---- AGENTS.md pointer ----------------------------------------------------
#
# The pack itself must never be committed (its version follows the platform, so
# git would freeze it at whatever the contract was that week). A *pointer* is the
# opposite: it survives being committed, it reaches tools that have no skills
# directory at all, and a path does not go stale the way a copied contract does.


def _deploy_ok(project: Path, monkeypatch: pytest.MonkeyPatch, *extra: str) -> tuple[int, str, str]:
    mock = _mock().post(DEPLOY, deploy_accept()).get("/api/v2/apps/deployments/dep-1", _waiting_seq())
    return _run(["deploy", str(project), "--yes", *extra], monkeypatch=monkeypatch, mock=mock)


def test_deploy_leaves_a_pointer_to_the_skill_pack(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    code, _, err = _deploy_ok(sample_project, monkeypatch)
    assert code == EXIT_OK
    text = (sample_project / "AGENTS.md").read_text(encoding="utf-8")
    assert "deploy-hosting/SKILL.md" in text
    assert "不要拷贝进本仓库" in text
    assert "AGENTS.md" in err


def test_pointer_is_written_once(monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path) -> None:
    _deploy_ok(sample_project, monkeypatch)
    first = (sample_project / "AGENTS.md").read_text(encoding="utf-8")
    _deploy_ok(sample_project, monkeypatch)
    assert (sample_project / "AGENTS.md").read_text(encoding="utf-8") == first


def test_no_agents_note_opts_out(monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path) -> None:
    code, _, _ = _deploy_ok(sample_project, monkeypatch, "--no-agents-note")
    assert code == EXIT_OK
    assert not (sample_project / "AGENTS.md").exists()


def test_dry_run_writes_nothing_into_the_working_tree(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    # "未上传，平台上什么都没有创建" has to include the developer's own tree.
    code, _, _ = _run(["deploy", str(sample_project), "--dry-run"], monkeypatch=monkeypatch, mock=_mock())
    assert code == EXIT_OK
    assert not (sample_project / "AGENTS.md").exists()


def test_failed_deploy_leaves_the_tree_untouched(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    # The pointer asserts "this project deploys to this platform"; until the
    # platform accepts the package that is still a guess.
    mock = _mock().post(DEPLOY, deploy_sync_err(16203, "包根不对", http_status=400))
    code, _, _ = _run(["deploy", str(sample_project), "--yes"], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_LOCAL_INVALID
    assert not (sample_project / "AGENTS.md").exists()


def test_existing_agents_md_is_appended_never_rewritten(
    monkeypatch: pytest.MonkeyPatch, logged_in, sample_project: Path
) -> None:
    original = "# 我的项目\n\n本地约定若干。\n"
    (sample_project / "AGENTS.md").write_text(original, encoding="utf-8")
    _deploy_ok(sample_project, monkeypatch)
    text = (sample_project / "AGENTS.md").read_text(encoding="utf-8")
    assert text.startswith(original)
    assert "deploy-hosting/SKILL.md" in text
