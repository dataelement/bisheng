import ast
from fnmatch import fnmatchcase
from pathlib import Path

import pytest
import yaml

from bisheng.core.config.celery_queues import (
    DEFAULT_CELERY_QUEUE,
    KNOWLEDGE_PARSE_QUEUE,
    KNOWLEDGE_PARSE_TASKS,
    KNOWLEDGE_PDF_QUEUE,
    PDF_ARTIFACT_TASK,
    POINTS_AWARD_QUEUE,
    POINTS_AWARD_TASK,
    WORKFLOW_CELERY_QUEUE,
    build_celery_task_routes,
)
from bisheng.core.config.settings import CeleryConf

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = Path(__file__).resolve().parents[4]


class _ConfigLoader(yaml.SafeLoader):
    pass


_ConfigLoader.add_constructor("!env", lambda loader, node: loader.construct_scalar(node))


def _resolve_queue(task_name: str, routes: dict) -> str | None:
    route = routes.get(task_name)
    if route is None:
        route = next(
            (candidate for pattern, candidate in routes.items() if "*" in pattern and fnmatchcase(task_name, pattern)),
            None,
        )
    if isinstance(route, str):
        return route
    return route.get("queue") if route else None


@pytest.mark.parametrize("task_name", sorted(KNOWLEDGE_PARSE_TASKS))
def test_parse_task_whitelist_routes_to_knowledge_queue(task_name: str):
    assert _resolve_queue(task_name, build_celery_task_routes({})) == KNOWLEDGE_PARSE_QUEUE


@pytest.mark.parametrize(
    "task_name",
    [
        "bisheng.worker.knowledge.file_worker.delete_knowledge_file_celery",
        "bisheng.worker.knowledge.file_worker.copy_knowledge_file_celery",
        "bisheng.worker.knowledge.file_worker.refresh_file_similarity_candidates_celery",
        "bisheng.worker.knowledge.rebuild_knowledge_worker.rebuild_knowledge_celery",
        "bisheng.worker.knowledge.qa.rebuild_qa_knowledge_celery",
        "bisheng.worker.knowledge.file_migration.execute_knowledge_migration",
        "bisheng.worker.knowledge.document_projection.process_document_projection",
        "bisheng.worker.knowledge.portal_recommendation.rebuild_portal_recommendation_pool",
        "bisheng.worker.org_sync.tasks.execute_org_sync",
        "bisheng.worker.permission.department_transfer_cleanup.process_event",
        "bisheng.worker.message.tasks.send_message",
        "bisheng.worker.portal_course.tasks.scan_portal_course_media_cleanup",
    ],
)
def test_non_parse_tasks_route_to_default_queue(task_name: str):
    assert _resolve_queue(task_name, build_celery_task_routes({})) == DEFAULT_CELERY_QUEUE


@pytest.mark.parametrize(
    ("task_name", "expected_queue"),
    [
        (PDF_ARTIFACT_TASK, KNOWLEDGE_PDF_QUEUE),
        (POINTS_AWARD_TASK, POINTS_AWARD_QUEUE),
        ("bisheng.worker.workflow.tasks.run_workflow", WORKFLOW_CELERY_QUEUE),
        ("bisheng.worker.approval.tasks.execute_approval_outbox", WORKFLOW_CELERY_QUEUE),
    ],
)
def test_protected_non_default_routes_are_unchanged(task_name: str, expected_queue: str):
    assert _resolve_queue(task_name, build_celery_task_routes({})) == expected_queue


def test_other_points_tasks_do_not_use_award_queue():
    """刷榜/月奖等非发分任务不进 points_award_celery（无显式路由时 Celery 落 default）。"""
    routes = build_celery_task_routes({})
    for task_name in (
        "bisheng.worker.points.tasks.refresh_points_rank_snapshots",
        "bisheng.worker.points.tasks.run_monthly_admin_rewards",
        "bisheng.worker.points.tasks.reconcile_point_balances",
    ):
        queue = _resolve_queue(task_name, routes)
        assert queue != POINTS_AWARD_QUEUE
        assert queue in (None, DEFAULT_CELERY_QUEUE)


def test_legacy_broad_knowledge_route_cannot_capture_non_parse_tasks():
    routes = build_celery_task_routes(
        {
            "bisheng.worker.knowledge.*": {"queue": "knowledge_celery"},
            "bisheng.worker.knowledge.document_projection.*": {"queue": "knowledge_celery"},
            "custom.task": {"queue": "custom_queue"},
        }
    )

    assert _resolve_queue(next(iter(KNOWLEDGE_PARSE_TASKS)), routes) == KNOWLEDGE_PARSE_QUEUE
    assert _resolve_queue("bisheng.worker.knowledge.document_projection.reconcile", routes) == DEFAULT_CELERY_QUEUE
    assert _resolve_queue("bisheng.worker.knowledge.qa.insert_qa_celery", routes) == DEFAULT_CELERY_QUEUE
    assert _resolve_queue("custom.task", routes) == "custom_queue"


def test_celery_conf_uses_canonical_routes_for_default_and_legacy_config():
    default_config = CeleryConf()
    legacy_config = CeleryConf(
        task_routers={"bisheng.worker.knowledge.*": {"queue": "knowledge_celery"}},
        beat_schedule={},
    )

    for config in (default_config, legacy_config):
        for task_name in KNOWLEDGE_PARSE_TASKS:
            assert _resolve_queue(task_name, config.task_routers) == KNOWLEDGE_PARSE_QUEUE
        assert (
            _resolve_queue("bisheng.worker.knowledge.qa.insert_qa_celery", config.task_routers) == DEFAULT_CELERY_QUEUE
        )


@pytest.mark.parametrize(
    "config_path",
    [
        BACKEND_DIR / "bisheng/config_3002.yaml",
        BACKEND_DIR / "bisheng/config_3003.yaml",
        PROJECT_DIR / "docker/bisheng/config/config.yaml",
        PROJECT_DIR / "docker/bisheng/config/config_dev.yaml",
    ],
)
def test_runtime_yaml_declares_parse_only_knowledge_queue(config_path: Path):
    config = yaml.load(config_path.read_text(encoding="utf-8"), Loader=_ConfigLoader)
    routes = config["celery_task"]["task_routers"]

    assert routes["bisheng.worker.knowledge.*"] == {"queue": DEFAULT_CELERY_QUEUE}
    for task_name in KNOWLEDGE_PARSE_TASKS:
        assert routes[task_name] == {"queue": KNOWLEDGE_PARSE_QUEUE}
    assert routes[PDF_ARTIFACT_TASK] == {"queue": KNOWLEDGE_PDF_QUEUE}
    assert routes["bisheng.worker.workflow.*"] == {"queue": WORKFLOW_CELERY_QUEUE}


def test_worker_entrypoints_keep_default_queue_consumers_enabled():
    entrypoints = (
        BACKEND_DIR / "entrypoint.sh",
        PROJECT_DIR / "docker/bisheng/entrypoint.sh",
    )

    for path in entrypoints:
        source = path.read_text(encoding="utf-8")
        assert "start_default" in source
        assert "-Q celery" in source


def test_worker_entrypoints_include_points_award_in_worker_bundle():
    """发分队列必须进 All-in-one worker；本地也可单独 entrypoint.sh points_award。"""
    backend = (BACKEND_DIR / "entrypoint.sh").read_text(encoding="utf-8")
    deploy = (PROJECT_DIR / "docker/bisheng/entrypoint.sh").read_text(encoding="utf-8")

    for source in (backend, deploy):
        assert "start_points_award" in source
        assert "points_award_celery" in source
        assert "points_award" in source

    backend_bundle = backend.split("start_all_workers()", 1)[1].split('case "$START_MODE"', 1)[0]
    assert "start_points_award" in backend_bundle

    deploy_bundle = deploy.split('elif [ "$start_mode" = "worker" ]', 1)[1].split("else", 1)[0]
    assert "start_points_award" in deploy_bundle


def test_non_parse_production_dispatches_do_not_target_knowledge_queue():
    allowed_files = {
        BACKEND_DIR / "scripts/enqueue_reparse_knowledge_space_files.py",
    }
    violations: list[str] = []

    for root in (BACKEND_DIR / "bisheng", BACKEND_DIR / "scripts"):
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            knowledge_queue_names = {"KNOWLEDGE_PARSE_QUEUE", "KNOWLEDGE_QUEUE"} | {
                target.id
                for node in ast.walk(tree)
                if isinstance(node, (ast.Assign, ast.AnnAssign))
                for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
                if isinstance(target, ast.Name)
                and isinstance(node.value, ast.Constant)
                and node.value.value == KNOWLEDGE_PARSE_QUEUE
            }
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                queue_values = [keyword.value for keyword in node.keywords if keyword.arg == "queue"]
                for value in queue_values:
                    targets_knowledge = (
                        (isinstance(value, ast.Constant) and value.value == KNOWLEDGE_PARSE_QUEUE)
                        or (isinstance(value, ast.Name) and value.id in knowledge_queue_names)
                        or (isinstance(value, ast.Attribute) and value.attr == "KNOWLEDGE_PARSE_QUEUE")
                    )
                    if targets_knowledge and path not in allowed_files:
                        violations.append(f"{path.relative_to(PROJECT_DIR)}:{node.lineno}")

    assert violations == []
