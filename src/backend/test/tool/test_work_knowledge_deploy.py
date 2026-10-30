"""Exercise the release entrypoint with a recording Docker command boundary."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def deploy(tmp_path, request):
    root = Path(__file__).resolve().parents[4]
    directory = tmp_path / getattr(request, "param", "deployment")
    (directory / "scripts").mkdir(parents=True)
    (directory / "docker").mkdir()
    script = directory / "scripts/deploy.sh"
    shutil.copy2(root / "scripts/deploy.sh", script)
    log = tmp_path / "calls.jsonl"
    docker = tmp_path / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['DEPLOY_TEST_LOG'], 'a') as output:\n"
        "    output.write(json.dumps(args) + '\\n')\n"
        "command = args[3:]\n"
        "stage = command[0]\n"
        "if stage == 'up': stage = 'backend' if command[-1] == 'backend' else 'remaining'\n"
        "if stage == os.environ.get('DEPLOY_TEST_FAIL'): sys.exit(17)\n"
        "if stage == 'exec': print(json.dumps({'ready': True}))\n"
    )
    docker.chmod(0o755)

    def run(*arguments, fail=""):
        log.unlink(missing_ok=True)
        result = subprocess.run(
            ["bash", str(script), *arguments],
            env={
                **os.environ,
                "PATH": f"{tmp_path}:{os.environ['PATH']}",
                "DEPLOY_TEST_LOG": str(log),
                "DEPLOY_TEST_FAIL": fail,
            },
            capture_output=True,
            text=True,
        )
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        for call in calls:
            assert call[:3] == ["compose", "-f", str(directory / "docker/docker-compose.yml")]
        return result, [call[3:] for call in calls]

    return run


CONFIRMATION = ("--confirm-store-id", "fixture-store", "--operator-id", "27")


@pytest.mark.parametrize("targets", [(), ("backend",), ("frontend", "backend", "worker")])
def test_backend_release_runs_upgrade_before_remaining_services_and_completion(deploy, targets):
    result, calls = deploy("update", *targets, *CONFIRMATION)
    assert result.returncode == 0, result.stderr
    assert calls[0][0] == "pull"
    assert calls[1] == ["up", "-d", "--no-deps", "--pull", "never", "--wait", "--wait-timeout", "180", "backend"]
    assert calls[2] == [
        "exec",
        "-T",
        "backend",
        "python",
        "scripts/register_work_knowledge_tool.py",
        "--apply",
        *CONFIRMATION,
    ]
    if targets == ("backend",):
        assert len(calls) == 4
    else:
        assert calls[3][0] == "up"
        assert "backend_worker" in calls[3]
        assert "frontend" in calls[3]
    assert calls[-1][0] == "ps"
    assert "更新完成" in result.stdout


@pytest.mark.parametrize(
    "stage,expected_calls", [("pull", 1), ("backend", 2), ("exec", 3), ("remaining", 4), ("ps", 5)]
)
def test_failed_release_stops_at_failed_stage_and_returns_error(deploy, stage, expected_calls):
    result, calls = deploy("update", *CONFIRMATION, fail=stage)
    assert result.returncode == 17
    assert len(calls) == expected_calls
    assert "更新完成" not in result.stdout
    if stage == "exec":
        assert "backend 已更新" in result.stderr


@pytest.mark.parametrize(
    "arguments",
    [
        (),
        ("backend",),
        ("--confirm-store-id",),
        ("--operator-id", "0"),
        ("--operator-id", "-1"),
        ("--operator-id", "invalid"),
        ("--unknown",),
        ("worker", *CONFIRMATION),
    ],
)
def test_invalid_confirmation_stops_before_docker_operations(deploy, arguments):
    result, calls = deploy("update", *arguments)
    assert result.returncode == 2
    assert calls == []


def test_preview_uses_target_image_in_one_off_container_and_keeps_service_running(deploy):
    result, calls = deploy("upgrade-preview")
    assert result.returncode == 0
    assert calls == [
        ["pull", "backend"],
        [
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "--pull",
            "never",
            "backend",
            "python",
            "scripts/register_work_knowledge_tool.py",
        ],
    ]


@pytest.mark.parametrize("target,service", [("worker", "backend_worker"), ("frontend", "frontend")])
def test_non_backend_update_preserves_service_scope(deploy, target, service):
    result, calls = deploy("update", target)
    assert result.returncode == 0
    assert [call[0] for call in calls] == ["pull", "up", "ps"]
    assert all(call[-1] == service for call in calls)


def test_restart_keeps_existing_runtime_operation(deploy):
    result, calls = deploy("restart", "backend")
    assert result.returncode == 0
    assert calls == [["restart", "backend"], ["ps", "backend"]]


@pytest.mark.parametrize("deploy", ["deployment with spaces"], indirect=True)
def test_compose_path_with_spaces_is_passed_as_one_argument(deploy):
    result, calls = deploy("update", "backend", *CONFIRMATION)
    assert result.returncode == 0
    assert len(calls) == 4


def test_failed_preview_propagates_status_and_keeps_services_unchanged(deploy):
    result, calls = deploy("upgrade-preview", fail="run")
    assert result.returncode == 17
    assert [call[0] for call in calls] == ["pull", "run"]


def test_release_can_resume_after_maintenance_failure(deploy):
    failed, _ = deploy("update", *CONFIRMATION, fail="exec")
    assert failed.returncode == 17
    retried, calls = deploy("update", *CONFIRMATION)
    assert retried.returncode == 0
    assert calls[2][0] == "exec"
    assert calls[-1][0] == "ps"
