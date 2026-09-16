"""Composition root of the publish pipeline (design D16).

One function, :func:`register`, called once per **process**. It subscribes F055
to the events F054 publishes and installs the ``hosted_app`` credential subject
resolver — the wiring that cannot be resolved lazily at the call site: nobody
imports this module in order to delete an application or to authenticate a
runtime credential, so both have to be installed up front.

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


async def on_app_deleted_revoke_credential(*, app_id: str, actor_user_id: int, tenant_id: int) -> None:
    """Revoke the deleted application's runtime credential (AC-58).

    A **separate** subscriber from :func:`on_app_deleted` rather than two steps
    in one: the hook fan-out collects failures per subscriber, so cancelling the
    approval and killing the key each get audited on their own instead of one
    swallowing the other's failure.

    Deliberately not paired with a re-issue anywhere: going offline deactivates
    the subject through :func:`resolve_hosted_app` (the application is no longer
    ``online``) and resuming revives the same key, so only deletion is terminal.
    """
    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService

    await AppRuntimeCredentialService.revoke(app_id)


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
    from bisheng.app_publish.domain.services.app_credential_service import (
        assert_hosted_app_executable,
        resolve_hosted_app,
    )
    from bisheng.app_runtime.domain.services import lifecycle_hooks
    from bisheng.open_api.domain.models.api_credential import SUBJECT_KIND_HOSTED_APP
    from bisheng.open_api.domain.services.credential_validator import SUBJECT_RESOLVERS
    from bisheng.open_api.domain.services.execution_context import SUBJECT_EXECUTION_GUARDS

    lifecycle_hooks.register_app_deleted_hook(on_app_deleted)
    lifecycle_hooks.register_app_deleted_hook(on_app_deleted_revoke_credential)
    # Registered here rather than declared in ``open_api`` so the dependency
    # keeps pointing F055 → the credential base and never back (F049 design D2:
    # "defined and registered by F055"). Until this runs, a ``hosted_app``
    # credential is refused with 26002 by ``_resolve_from_database`` — which is
    # the fail-closed behaviour we want in a process that did not wire F055.
    SUBJECT_RESOLVERS[SUBJECT_KIND_HOSTED_APP] = resolve_hosted_app
    # The same registration for the asynchronous leg. **Both or neither** — a
    # process that resolves the subject at admission but cannot re-check it at
    # execution would let a queued task outlive the stop that was supposed to
    # end it, so this pair belongs in one function.
    SUBJECT_EXECUTION_GUARDS[SUBJECT_KIND_HOSTED_APP] = assert_hosted_app_executable
    logger.debug("app_publish.composition registered (app-deleted hooks + hosted_app subject resolver and guard)")
