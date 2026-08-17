"""Composition root of the publish pipeline (design D16).

One function, :func:`register`, called once per **process**. It subscribes F055
to the events F054 publishes, which is the only wiring that cannot be resolved
lazily at the call site: nobody imports this module in order to delete an
application, so the subscription has to be installed up front.

**It must be called from two places, and only calling one is the worst
outcome.** The API process handles deletions from the detail page; the Celery
worker runs the approval outbox and anything a task triggers. Wire only the API
and everything works when a developer tests it by hand, while in production the
worker never cancels an in-flight approval — and the trail is a single log
line. The two call sites are ``main.py``'s ``lifespan`` and ``worker/main.py``'s
``on_worker_init``.

Why the scenario handler is *not* registered here: the runtime handler factory
builds it from a hard-coded branch, on demand, in whichever process asks. That
is deliberate — a registry filled by a composition root fails exactly the way
K1 ③ warns about (approval passes, the factory finds no handler, the outbox
records a failure and the application silently never goes online) whenever the
root has not run. A branch that imports what it needs cannot be forgotten.
:func:`register` therefore *verifies* the branch resolves and leaves the
mechanism alone.
"""

from __future__ import annotations

from loguru import logger

from bisheng.app_publish.domain.services.app_publish_scenario_handler import SCENARIO_CODE


async def on_app_deleted(*, app_id: str, actor_user_id: int, tenant_id: int) -> None:
    """Cancel whatever release of this application was still under approval (AC-35).

    Notifies the **approvers**, not the applicant: the applicant is the person
    who just pressed delete. The approvers are the ones left holding a task
    that points at an application which no longer exists.

    Raising here does **not** roll the deletion back — by the time hooks run the
    container and the volume are already gone, and undoing the state change
    would leave "the app exists but its data does not". F054 records the failure
    as ``app.delete_hook_failed`` instead, and the publish face judges "was this
    cancelled" from the application's own state rather than trusting that this
    hook arrived (design D10).
    """
    from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService

    instance = await ApprovalCenterService.cancel_instance_by_business(
        scenario_code=SCENARIO_CODE,
        business_resource_type="app",
        business_resource_id=str(app_id),
        tenant_id=int(tenant_id or 0),
        reason="应用已删除, 发布申请自动取消",
        operator_user_id=int(actor_user_id or 0),
    )
    if instance is not None:
        logger.info(f"app_publish.release_cancelled app_id={app_id} instance_id={instance.id}")


def register() -> None:
    """Install F055's subscriptions in this process. Safe to call more than once.

    Idempotence is by callable identity inside
    ``lifecycle_hooks.register_app_deleted_hook``, which matters because a
    worker that re-initialises would otherwise cancel the same approval twice.
    """
    from bisheng.app_runtime.domain.services import lifecycle_hooks

    lifecycle_hooks.register_app_deleted_hook(on_app_deleted)
    logger.debug("app_publish.composition registered (app-deleted hook)")
