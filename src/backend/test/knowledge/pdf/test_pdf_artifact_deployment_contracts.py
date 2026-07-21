import os
import shutil
import subprocess
from pathlib import Path

import yaml

BACKEND_DIR = Path(__file__).resolve().parents[3]
PROJECT_DIR = Path(__file__).resolve().parents[5]


class _ConfigLoader(yaml.SafeLoader):
    pass


_ConfigLoader.add_constructor("!env", lambda loader, node: loader.construct_scalar(node))


def test_both_entrypoints_expose_pdf_only_mode_without_joining_worker_bundle():
    backend_entrypoint = (BACKEND_DIR / "entrypoint.sh").read_text(encoding="utf-8")
    deploy_entrypoint = (PROJECT_DIR / "docker/bisheng/entrypoint.sh").read_text(encoding="utf-8")

    for source in (backend_entrypoint, deploy_entrypoint):
        assert "start_pdf" in source
        assert "knowledge_pdf_celery" in source
        assert "KNOWLEDGE_PDF_CONCURRENCY" in source

    backend_worker_bundle = backend_entrypoint.split("start_all_workers()", 1)[1].split('case "$START_MODE"', 1)[0]
    deploy_worker_bundle = deploy_entrypoint.split('elif [ "$start_mode" = "worker" ]', 1)[1].split("else", 1)[0]
    assert "start_pdf" not in backend_worker_bundle
    assert "start_pdf" not in deploy_worker_bundle


def test_backend_entrypoint_switches_from_posix_shell_to_bash():
    entrypoint = (BACKEND_DIR / "entrypoint.sh").read_text(encoding="utf-8")
    bash_reexec_index = entrypoint.index('exec bash "$0" "$@"')
    assert bash_reexec_index < entrypoint.index("set -Eeuo pipefail")
    assert bash_reexec_index < entrypoint.index("PIDS=()")

    shell = shutil.which("dash") or shutil.which("sh")
    assert shell is not None

    result = subprocess.run(
        [shell, str(BACKEND_DIR / "entrypoint.sh"), "syntax-smoke"],
        cwd=BACKEND_DIR,
        env={**os.environ, "APP_HOME": str(BACKEND_DIR)},
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "Invalid start mode: syntax-smoke" in result.stdout
    assert "Illegal option" not in output
    assert "Syntax error" not in output


def test_config_supports_dedicated_pdf_worker():
    deploy_config_path = PROJECT_DIR / "docker/bisheng/config/config.yaml"
    deploy_config_text = deploy_config_path.read_text(encoding="utf-8")
    deploy_config = yaml.load(deploy_config_text, Loader=_ConfigLoader)

    routes = deploy_config["celery_task"]["task_routers"]
    route_names = list(routes)
    exact_task = "bisheng.worker.knowledge.pdf_artifact_worker.generate_knowledge_file_pdf_celery"
    assert routes[exact_task] == {"queue": "knowledge_pdf_celery"}
    assert route_names.index(exact_task) < route_names.index("bisheng.worker.knowledge.*")
    assert deploy_config["knowledges"]["pdf_artifact"]["queue_name"] == "knowledge_pdf_celery"

    worker_docs = (BACKEND_DIR / "AGENTS.md").read_text(encoding="utf-8")
    assert "knowledge_pdf_celery" in worker_docs
    assert "entrypoint.sh pdf" in worker_docs
