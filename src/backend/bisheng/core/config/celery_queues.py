"""Celery queue ownership and routing contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DEFAULT_CELERY_QUEUE = "celery"
KNOWLEDGE_PARSE_QUEUE = "knowledge_celery"
KNOWLEDGE_PDF_QUEUE = "knowledge_pdf_celery"
WORKFLOW_CELERY_QUEUE = "workflow_celery"
POINTS_AWARD_QUEUE = "points_award_celery"

KNOWLEDGE_PARSE_TASKS = frozenset(
    {
        "bisheng.worker.knowledge.file_title_worker.extract_knowledge_file_title_celery",
        "bisheng.worker.knowledge.file_worker.parse_knowledge_file_celery",
        "bisheng.worker.knowledge.file_worker.retry_knowledge_file_celery",
    }
)
PDF_ARTIFACT_TASK = "bisheng.worker.knowledge.pdf_artifact_worker.generate_knowledge_file_pdf_celery"
POINTS_AWARD_TASK = "bisheng.worker.points.tasks.process_points_award_event"

_DEFAULT_QUEUE_PATTERNS = (
    "bisheng.worker.knowledge.*",
    "bisheng.worker.org_sync.*",
    "bisheng.worker.tenant_reconcile.*",
    "bisheng.worker.admin_scope.*",
    "bisheng.worker.message.*",
    "bisheng.worker.portal_course.*",
    "bisheng.worker.permission.*",
)
_WORKFLOW_QUEUE_PATTERNS = (
    "bisheng.worker.workflow.*",
    "bisheng.worker.approval.*",
)


def _normalize_configured_route(route: Any) -> Any:
    """Prevent legacy custom routes from assigning work to the parse queue."""
    if isinstance(route, str):
        return DEFAULT_CELERY_QUEUE if route == KNOWLEDGE_PARSE_QUEUE else route
    if isinstance(route, Mapping):
        normalized = dict(route)
        if normalized.get("queue") == KNOWLEDGE_PARSE_QUEUE:
            normalized["queue"] = DEFAULT_CELERY_QUEUE
        return normalized
    return route


def build_celery_task_routes(configured_routes: Mapping[str, Any] | None) -> dict[str, Any]:
    """Build final routes while enforcing exclusive parse-queue ownership."""
    routes: dict[str, Any] = {pattern: {"queue": WORKFLOW_CELERY_QUEUE} for pattern in _WORKFLOW_QUEUE_PATTERNS}
    routes.update({pattern: {"queue": DEFAULT_CELERY_QUEUE} for pattern in _DEFAULT_QUEUE_PATTERNS})

    for task_pattern, route in (configured_routes or {}).items():
        if task_pattern in routes or task_pattern in KNOWLEDGE_PARSE_TASKS:
            continue
        routes[task_pattern] = _normalize_configured_route(route)

    routes[PDF_ARTIFACT_TASK] = {"queue": KNOWLEDGE_PDF_QUEUE}
    # 异步发分专用队列：避免共享 Broker 上远端 default Worker 抢走未注册任务。
    routes[POINTS_AWARD_TASK] = {"queue": POINTS_AWARD_QUEUE}
    routes.update({task_name: {"queue": KNOWLEDGE_PARSE_QUEUE} for task_name in sorted(KNOWLEDGE_PARSE_TASKS)})
    return routes
