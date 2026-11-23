"""Formal F133 composition: stable integration ownership and existing run engine.

Published core Workflow graphs reuse the native engine with a single text/form
input and text output boundary. Context-dependent platform nodes are rejected
before admission until their separate dispatch contexts are wired.
"""

from asyncio import to_thread
from dataclasses import asdict

from bisheng.workflow.application.kunlian_workflow_invocation import WorkflowInvocationService
from bisheng.workflow.domain.repositories.kunlian_registration import PublishedRunRegistrationRepository
from bisheng.workflow.domain.repositories.kunlian_workflow_run import RunRepository
from bisheng.workflow.domain.schemas.kunlian_registration import RegistrationScope
from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunError, RunSubject


def run_subject_from_request(access):
    principal, user = access.credential, access.user
    return RunSubject(
        tenant_id=user.tenant_id,
        connection_id=principal.integration_id,
        user_id=user.user_id,
        credential_id=principal.credential_id,
        identity_connection_id=principal.connection_id,
        external_tenant_id=access.external_tenant_id,
        external_user_id=access.external_user_id,
        policy_revision=principal.policy_revision,
    )


class KunlianRuntimeService(WorkflowInvocationService):
    def __init__(self, repository, resolve_user, dispatch, *, authorize_operation=None, resolve_candidate_user=None):
        super().__init__(repository, resolve_user, dispatch, authorize_operation=authorize_operation)
        self._resolve_candidate_user = resolve_candidate_user

    async def submit(
        self,
        subject,
        key,
        body,
        *,
        allow_platform_agent: bool = False,
        extra_material: dict | None = None,
    ):
        await self.authorize(subject, body.workflow_id)
        record, created = await to_thread(
            self.repository.admit,
            RegistrationScope(subject.tenant_id, subject.connection_id, 0),
            subject.user_id,
            key,
            body,
            run_control=True,
            identity=asdict(subject),
            allow_platform_agent=allow_platform_agent,
            extra_material=extra_material,
        )
        if created:
            await self.deliver(record.tenant_id, record.session_id)
        return record, created

    async def lookup_operation(self, subject, operation_key: str):
        row = await to_thread(
            self.repository.lookup_by_operation_key,
            RegistrationScope(subject.tenant_id, subject.connection_id, 0),
            subject.user_id,
            operation_key,
        )
        if row is None:
            raise RunError("SESSION_NOT_FOUND")
        await self.authorize(subject, row.workflow_id)
        return row

    async def answer(self, subject, session_id, interaction_id, key, body):
        row = await self._authorized_row(subject, session_id)
        if row.status == "WAITING_INPUT":
            # A rotated Key can inspect/cancel the stable owner's run, but cannot
            # resurrect execution whose original credential was revoked.
            await self.authorize_run(row)
        return await super().answer(subject, session_id, interaction_id, key, body)

    async def authorize_run(self, row):
        identity = (row.material or {}).get("kunlian_identity")
        if not isinstance(identity, dict):
            raise RunError("FORBIDDEN")
        try:
            subject = RunSubject(**identity)
        except TypeError:
            raise RunError("FORBIDDEN") from None
        if (subject.tenant_id, subject.connection_id, subject.user_id) != (
            row.tenant_id,
            row.connection_id,
            row.user_id,
        ):
            raise RunError("FORBIDDEN")
        material = row.material if isinstance(row.material, dict) else {}
        is_candidate = (
            subject.credential_id is None
            and subject.policy_revision is None
            and (
                material.get("kunlian_protocol") == "kunlian-workflow-candidate-v1"
                or (isinstance(material.get("context_id"), str) and bool(material["context_id"].strip()))
            )
        )
        resolver = self._resolve_candidate_user if is_candidate and self._resolve_candidate_user is not None else None
        return await self.authorize(subject, row.workflow_id, resolve_user=resolver)

    def check_node_entry(self, row):
        # Called from the graph thread, not the async worker loop.
        from bisheng.worker._asyncio_utils import run_async_task

        run_async_task(lambda: self.authorize_run(row))


def create_kunlian_runtime_service(
    *, resolve_user, dispatch, repository=None, resolve_candidate_user=None
):
    """Explicit composition port also usable by independent workers/tests."""

    async def allow_operation(subject, workflow_id, operation):
        # WorkflowInvocationService already checks use permission and ownership.
        # F133 exposes no additional trace/event privilege or identity bypass.
        return operation in {"status", "result", "interaction", "cancel"}

    if repository is None:
        from bisheng.common.services.config_service import settings

        limits = settings.get_workflow_conf().kunlian_api
        repository = RunRepository(
            PublishedRunRegistrationRepository(),
            queue_seconds=limits.queue_seconds,
            run_seconds=limits.run_seconds,
            wait_seconds=limits.wait_seconds,
            retain_seconds=limits.retain_seconds,
            max_active_per_user=limits.max_active_per_user,
        )

    return KunlianRuntimeService(
        repository,
        resolve_user,
        dispatch,
        authorize_operation=allow_operation,
        resolve_candidate_user=resolve_candidate_user,
    )


async def get_kunlian_runtime_service(app=None):
    """Production factory; no test registration or in-memory availability facts."""
    from types import SimpleNamespace

    from bisheng.open_api.application.kunlian_access import revalidate_kunlian_subject
    from bisheng.user.application.runtime_identity import read_current_person_facts
    from bisheng.worker.workflow.kunlian_runtime import dispatch_run

    async def resolve(subject):
        from bisheng.common.errcode.sso_sync import KunlianError
        from bisheng.open_api.domain.services.kunlian_credential import KunlianAccessError

        try:
            return await revalidate_kunlian_subject(subject, app=app)
        except (KunlianAccessError, KunlianError) as exc:
            raise RunError("UNAVAILABLE" if exc.http_status >= 500 else "FORBIDDEN") from exc

    async def resolve_candidate(subject):
        # 候选 OIDC 协议运行使用 introspect 返回的 context_id，没有 API Key credential_id
        facts = (await read_current_person_facts([subject.user_id])).get(subject.user_id, {})
        if facts.get("state") != "active" or facts.get("tenant_id") != subject.tenant_id:
            raise RunError("FORBIDDEN")
        return SimpleNamespace(user_id=subject.user_id, tenant_id=subject.tenant_id)

    return create_kunlian_runtime_service(
        resolve_user=resolve,
        dispatch=dispatch_run,
        resolve_candidate_user=resolve_candidate,
    )
