"""Celery task for the asynchronous half of the publish pipeline (F055 design D1).

Runs on the **default ``celery`` queue**, alongside the approval outbox. Not a
queue of its own: a new queue means a new worker unit in 114's systemd set and
in compose, while MVP-era concurrent publishes are a single-digit number. The
trade-off to watch is in design D1's "when to reconsider" — a build starving the
outbox shows up as approvals taking minutes to execute.

⚠️ **Registration is the failure mode to know about.** The app is
``Celery("bisheng", include=["bisheng.worker"])``, which imports the package and
does **not** walk its submodules — every task is registered by the explicit
import block at the top of ``bisheng/worker/__init__.py``. Omitting the line
there produces the least locatable symptom in this feature: ``apply_async``
returns normally, ``deploy`` reports success, and the deployment sits at
``stage=received`` forever while the backend log stays clean (the ``NotRegistered``
is raised on the worker side). Self-check after deploying::

    uv run celery -A bisheng.worker.main:bisheng_celery inspect registered | grep app_publish

The tenant id is *not* passed as an argument: ``worker/tenant_context.py``
carries it in the task header and restores the ContextVar before the body runs.
``run_pipeline`` still checks it against the row and says so loudly on a
mismatch — a silently wrong tenant is worse than a crash.
"""

from __future__ import annotations

import logging

from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)


@bisheng_celery.task(
    acks_late=True,
    # A dependency build is minutes; the ceiling is generous on purpose, and the
    # pipeline's own build poll times out well before it.
    time_limit=3600,
    soft_time_limit=3540,
    name="bisheng.worker.app_publish.tasks.run_publish_pipeline",
)
def run_publish_pipeline(deployment_id: str) -> bool:
    return run_async_task(lambda: _run_publish_pipeline_async(deployment_id))


async def _run_publish_pipeline_async(deployment_id: str) -> bool:
    from bisheng.app_publish.domain.services.publish_pipeline_service import PublishPipelineService

    await PublishPipelineService.run_pipeline(deployment_id)
    return True
