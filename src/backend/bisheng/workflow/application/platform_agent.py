"""平台 Agent 的应用装配入口。配置仅从服务端读取。"""

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import HTTPException

from bisheng.chat_session.application import workflow_output
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.flow import (
    PlatformAgentError,
    PlatformAgentExecutionError,
    PlatformAgentPermissionError,
    PlatformAgentUpstreamError,
)
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.common.errcode.tenant_resolver import TokenVersionMismatchError
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
from bisheng.workflow.domain.repositories.platform_agent import PlatformAgentRepository
from bisheng.workflow.domain.schemas.platform_agent import (
    PUBLICATION_KEY,
    AgentReference,
    interaction_node_ids,
    long_task_resume_node_ids,
    uses_agent_interaction,
    uses_long_platform_agent,
    uses_platform_agent,
)
from bisheng.workflow.domain.services.platform_agent_service import PlatformAgentService


class QueuedExecutionRejected(Exception):
    """只有已领取的派发才能携带失败上下文返回 Worker。"""

    def __init__(self, context, reason):
        super().__init__("queued platform Agent execution rejected")
        self.context = context
        self.reason = reason


def get_service():
    return PlatformAgentService(
        config=settings.get_workflow_conf().platform_agent,
        config_source=lambda: settings.get_workflow_conf().platform_agent,
    )


def public_execution_error(error):
    if isinstance(error, TokenVersionMismatchError):
        return TokenVersionMismatchError()
    if isinstance(error, PlatformAgentError):
        return type(error)()
    if isinstance(error, (UnAuthorizedError, PermissionDeniedError)):
        return PlatformAgentPermissionError()
    return PlatformAgentUpstreamError()


class BrowserPlatformAgentRuntime:
    """由路由装配的浏览器运行端口。common 不依赖平台 Agent 领域实现。"""

    def __init__(self, repository=None):
        self.repository = repository or PlatformAgentRepository()

    public_error = staticmethod(public_execution_error)
    is_interaction_graph = staticmethod(uses_agent_interaction)

    @staticmethod
    async def _check_browser_session(login_user, workflow_id, session_id):
        from bisheng.chat_session.domain.chat import ChatSessionService
        from bisheng.chat_session.domain.session_subject import SessionSubject

        suffix = "_async_task_id"
        chat_id = session_id.removesuffix(suffix) if isinstance(session_id, str) else ""
        if not chat_id or chat_id == session_id:
            raise PlatformAgentPermissionError()
        subject = SessionSubject.natural_person(tenant_id=login_user.tenant_id, user_id=login_user.user_id)
        try:
            with tenant_execution_scope(login_user.tenant_id):
                session = await ChatSessionService.get_subject_session_if_exists(chat_id, subject)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            raise PlatformAgentPermissionError() from None
        if session is not None and session.flow_id != workflow_id:
            raise PlatformAgentPermissionError()

    async def prepare(self, login_user, workflow_id, session_id, graph, *, published, execution_snapshot=None):
        stored_graph = self.repository.get_workflow(workflow_id)["data"]
        if not uses_platform_agent(graph) and not uses_platform_agent(stored_graph):
            return None
        if execution_snapshot is not None:
            actual_user_from_snapshot(SimpleNamespace(**execution_snapshot), login_user.user_id)
        frozen_graph = stored_graph if published else graph
        options = (
            {"interaction_session": published and execution_snapshot is None}
            if uses_agent_interaction(frozen_graph)
            else {}
        )
        service = get_service()
        if (
            not options
            and published
            and execution_snapshot is None
            and getattr(service, "long_task_resume_available", False)
            and uses_long_platform_agent(frozen_graph)
        ):
            options["long_task_resume_session"] = True
        if (options.get("interaction_session") and service.interaction_available) or options.get("long_task_resume_session"):
            await self._check_browser_session(login_user, workflow_id, session_id)
        execution, dispatch_id = await service.admit(
            login_user, workflow_id, session_id, frozen_graph, "PUBLISHED" if published else "DEBUG", **options
        )
        return frozen_graph, {"execution_id": execution["execution_id"], "dispatch_id": dispatch_id}

    async def resume(self, login_user, workflow_id, execution_id, *, published):
        service = get_service()
        actor = await service.authorize(login_user, workflow_id, "use" if published else "edit")
        record = service.repository.get_execution(execution_id)
        if (record["workflow_id"], record["user_id"], record["tenant_id"]) != (
            workflow_id,
            actor.user_id,
            actor.tenant_id,
        ):
            raise PlatformAgentExecutionError()
        if record["actor_reference"].get("token_version") != actor.token_version:
            raise TokenVersionMismatchError()
        dispatch_id = service.repository.prepare_resume(execution_id, actor)
        return {"execution_id": execution_id, "dispatch_id": dispatch_id}

    def abort(self, execution_id):
        get_service().repository.request_stop(execution_id)

    async def _long_execution(self, login_user, workflow_id, session_id, execution_id):
        if not execution_id:
            return None
        service = get_service()
        if not service.enable_long_tasks:
            return None
        with tenant_execution_scope(login_user.tenant_id):
            record = service.repository.get_execution(execution_id)
            if (record["workflow_id"], record["session_id"], record["tenant_id"], record["user_id"]) != (
                workflow_id,
                session_id,
                login_user.tenant_id,
                login_user.user_id,
            ):
                raise PlatformAgentPermissionError()
            if not uses_long_platform_agent(record["graph_snapshot"]):
                return None
            if uses_agent_interaction(record["graph_snapshot"]):
                self._check_browser_origin(service, login_user, record)
            await service._long_actor(login_user, record)
        return service, record

    async def long_status(self, login_user, workflow_id, session_id, execution_id):
        resolved = await self._long_execution(login_user, workflow_id, session_id, execution_id)
        if resolved is None:
            return None
        service, record = resolved
        return service.long_summary(record)

    async def stop_long(self, login_user, workflow_id, session_id, execution_id):
        resolved = await self._long_execution(login_user, workflow_id, session_id, execution_id)
        if resolved is None:
            return False
        service, _ = resolved
        with tenant_execution_scope(login_user.tenant_id):
            service.repository.request_stop(execution_id, cancel_long=True)
            service.wake_long(login_user.tenant_id, execution_id)
        return True

    async def read_long_task_resume_output(self, login_user, workflow_id, session_id, execution_id):
        with tenant_execution_scope(login_user.tenant_id):
            service = get_service()
            record = self.repository.get_execution(execution_id)
            if (record["workflow_id"], record["session_id"], record["user_id"], record["tenant_id"]) != (
                workflow_id, session_id, login_user.user_id, login_user.tenant_id,
            ):
                raise PlatformAgentPermissionError()
            if record["state"] != "SUCCEEDED":
                return None
            for call in record["calls"].values():
                receipt = call.get("long_task", {}).get("resume", {})
                if receipt.get("message_id"):
                    self._check_browser_origin(service, login_user, record)
                    deadline = self.repository.clock() + service.config.invoke_timeout_seconds
                    await authorize_long_task_resume(service, login_user, record, call, deadline)
                    with self.repository.transaction() as session:
                        return workflow_output.read_output(
                            session, message_id=receipt["message_id"], **_workflow_output_scope(record)
                        )
            return None

    async def _long_task_resume_execution(self, login_user, workflow_id, session_id, execution_id):
        service = get_service()
        if execution_id is None:
            if not service.long_task_resume_available:
                return None
            record = self.repository.find_active_session_execution(workflow_id, session_id)
            if record is None:
                record = self.repository.find_session_execution(workflow_id, session_id)
        else:
            record = self.repository.get_execution(execution_id)
        if record is None or not any(item.get("long_task_resume") for item in record["dispatches"].values()):
            return None
        if (
            record["entry_kind"] != "PUBLISHED"
            or (record["workflow_id"], record["session_id"], record["tenant_id"], record["user_id"])
            != (workflow_id, session_id, login_user.tenant_id, login_user.user_id)
        ):
            raise PlatformAgentPermissionError()
        self._check_browser_origin(service, login_user, record)
        _, node_id = long_task_resume_node_ids(record["graph_snapshot"])
        binding = record["graph_snapshot"][PUBLICATION_KEY]["nodes"][node_id]
        deadline = self.repository.clock() + service.config.invoke_timeout_seconds
        # TODO [F126][EXT-04] 正式实际用户委托、有效期和撤权规则待双方确认。
        await authorize_long_task_resume(service, login_user, record, binding, deadline)
        return service, self.repository.get_execution(record["execution_id"]), f"{node_id}:0"

    def _long_task_resume_view(self, service, record, key):
        execution_id = record["execution_id"]
        active = record["state"] in {"READY", "RUNNING", "WAITING"} and not record["stop_requested"]
        summary = service.long_summary(record, key) or {
            "execution_id": execution_id,
            "local_state": "WAITING_RESULT" if active else "STOPPED" if record["stop_requested"] else "FAILED",
            "remote_state": "NOT_SENT", "cancel_state": "NONE", "status_version": 0,
        }
        output = None
        receipt = record["calls"].get(key, {}).get("long_task", {}).get("resume", {})
        if record["state"] == "SUCCEEDED" and receipt.get("message_id"):
            with self.repository.transaction() as session:
                output = workflow_output.read_output(
                    session, message_id=receipt["message_id"], **_workflow_output_scope(record)
                )
        return {"execution_id": execution_id, "active": active, "summary": summary, "output": output}

    async def long_task_resume_status(self, login_user, workflow_id, session_id, execution_id=None):
        with tenant_execution_scope(login_user.tenant_id):
            resolved = await self._long_task_resume_execution(login_user, workflow_id, session_id, execution_id)
            if resolved is not None:
                return self._long_task_resume_view(*resolved)

    async def stop_long_task_resume(self, login_user, workflow_id, session_id, execution_id=None):
        with tenant_execution_scope(login_user.tenant_id):
            resolved = await self._long_task_resume_execution(login_user, workflow_id, session_id, execution_id)
            if resolved is None:
                return None
            service, record, key = resolved
            execution_id = record["execution_id"]
            self.repository.request_stop(execution_id, cancel_long=True)
            service.wake_long(login_user.tenant_id, execution_id)
            return self._long_task_resume_view(service, self.repository.get_execution(execution_id), key)

    async def _interaction_execution(self, login_user, workflow_id, session_id, execution_id):
        service = get_service()
        if not service.interaction_available:
            return None
        repo = service.repository
        if execution_id is None:
            record = repo.find_active_session_execution(workflow_id, session_id)
        else:
            record = repo.get_execution(execution_id)
        if record is None or not uses_agent_interaction(record["graph_snapshot"]):
            return None
        if (
            (record["workflow_id"], record["session_id"], record["tenant_id"], record["user_id"])
            != (workflow_id, session_id, login_user.tenant_id, login_user.user_id)
            or record["entry_kind"] != "PUBLISHED"
        ):
            raise PlatformAgentPermissionError()
        self._check_browser_origin(service, login_user, record)
        await self._check_browser_session(login_user, workflow_id, session_id)
        # TODO [F125][EXT-04] 确认正式接口复用 SSO Token 或原实际用户委托的规则。
        actor = await service._long_actor(login_user, record)
        _, node_id = interaction_node_ids(record["graph_snapshot"])
        binding = record["graph_snapshot"][PUBLICATION_KEY]["nodes"][node_id]
        await service.provider.check_use(actor, AgentReference.model_validate(binding["ref"]))
        return service, repo.get_execution(record["execution_id"]), f"{node_id}:0"

    @staticmethod
    def _check_browser_origin(service, login_user, record):
        if record["actor_reference"].get("browser_origin", {"source": "local"}) != service.browser_origin(login_user):
            raise PlatformAgentPermissionError()

    @staticmethod
    def _interaction_view(service, record, key):
        summary = service.long_summary(record, key)
        message = {"agent_long_task": summary} if summary else {}
        call = record["calls"].get(key, {})
        interaction = call.get("long_task", {}).get("interaction")
        active = record["state"] in {"READY", "RUNNING", "WAITING"} and not record["stop_requested"]
        if interaction:
            form = interaction.get("form", {})
            view = {
                "execution_id": record["execution_id"],
                "interaction_id": interaction["interaction_id"],
                "revision": form.get("revision") or interaction.get("remote_interaction", {}).get("revision"),
                "phase": interaction["phase"],
                "status_version": interaction["status_version"],
                "expires_at": datetime.fromtimestamp(interaction["expires_at"], UTC).isoformat(),
            }
            if active and interaction["phase"] == "WAITING_INPUT" and service.repository.clock() < call["deadline"]:
                view["form"] = {
                    "type": "text", "label": form["label"], "required": True, "max_length": form["max_length"]
                }
            message["agent_interaction"] = view
        return {
            "execution_id": record["execution_id"],
            "active": active,
            "state": record["state"],
            "output_allowed": active or record["state"] == "SUCCEEDED",
            "message": message,
        }

    async def interaction_status(self, login_user, workflow_id, session_id, execution_id=None):
        with tenant_execution_scope(login_user.tenant_id):
            resolved = await self._interaction_execution(login_user, workflow_id, session_id, execution_id)
            if resolved is not None:
                return self._interaction_view(*resolved)

    async def submit_interaction(self, login_user, workflow_id, session_id, execution_id, interaction_id,
                                 revision, submission_id, answer):
        with tenant_execution_scope(login_user.tenant_id):
            resolved = await self._interaction_execution(login_user, workflow_id, session_id, execution_id)
            if resolved is None or not execution_id:
                raise PlatformAgentExecutionError()
            service, _, key = resolved
            await service.submit_interaction_answer(
                login_user, execution_id, key, interaction_id, revision, submission_id, answer
            )
            return self._interaction_view(service, service.repository.get_execution(execution_id), key)

    async def stop_interaction(self, login_user, workflow_id, session_id, execution_id=None):
        with tenant_execution_scope(login_user.tenant_id):
            resolved = await self._interaction_execution(login_user, workflow_id, session_id, execution_id)
            if resolved is None:
                return None
            service, record, key = resolved
            original = record["execution_id"]
            await self.stop_long(login_user, workflow_id, session_id, original)
            return self._interaction_view(service, service.repository.get_execution(original), key)


@contextmanager
def queue_tenant_scope(headers, reference):
    if reference is None:
        yield
        return
    tenant_id = (headers or {}).get("tenant_id")
    if type(tenant_id) is not int or tenant_id <= 0:
        raise PlatformAgentExecutionError()
    with tenant_execution_scope(tenant_id):
        yield


def actual_user_from_snapshot(snapshot, user_id):
    if snapshot.authorization_subject_type != "user" or snapshot.effective_user_id != user_id:
        raise PlatformAgentExecutionError()
    return UserPayload(user_id=user_id, user_role=[], tenant_id=snapshot.tenant_id)


def _workflow_output_scope(record):
    suffix = "_async_task_id"
    chat_id = record["session_id"].removesuffix(suffix)
    if not chat_id or chat_id == record["session_id"]:
        raise PlatformAgentExecutionError()
    return {
        "execution_id": record["execution_id"], "workflow_id": record["workflow_id"],
        "chat_id": chat_id, "user_id": record["user_id"], "tenant_id": record["tenant_id"],
    }


async def authorize_long_task_resume(service, user, record, call, deadline):
    await service._long_request(
        deadline, BrowserPlatformAgentRuntime._check_browser_session, user, record["workflow_id"], record["session_id"]
    )
    actor = await service._long_request(deadline, service._long_actor, user, record)
    await service._long_request(deadline, service.provider.check_use, actor, AgentReference.model_validate(call["ref"]))


async def claim_long_task_resume(execution_id, key, dispatch_id):
    service = get_service()
    if not service.long_task_resume_available:
        return None
    repository = service.repository
    tenant_id = get_current_tenant_id()
    dispatch = repository.claim_long_task_resume_dispatch(execution_id, key, dispatch_id, tenant_id)
    if dispatch is None:
        return None
    execution = repository.get_execution(execution_id)
    claimed = execution["dispatches"][dispatch_id]
    if claimed["state"] != "CLAIMED" or claimed["owner"] != dispatch.owner:
        return None
    user = UserPayload(user_id=execution["user_id"], tenant_id=tenant_id, user_role=[])
    context = {"service": service, "login_user": user, "dispatch": dispatch, "execution": execution,
               "long_task_resume_key": key}
    try:
        await authorize_long_task_resume(service, user, execution, execution["calls"][key], claimed["lease_until"])
    except (UnAuthorizedError, PlatformAgentPermissionError, PermissionDeniedError, TokenVersionMismatchError):
        repository.fail_long_task_resume(dispatch, key, "FORBIDDEN")
        return None
    return context


async def commit_long_task_resume_output(context, message):
    service = context["service"]
    record = context["execution"]
    key = context["long_task_resume_key"]
    dispatch = context["dispatch"]
    service.repository.assert_long_graph_live(dispatch)
    deadline = record["dispatches"][dispatch.dispatch_id]["lease_until"]
    await authorize_long_task_resume(service, context["login_user"], record, record["calls"][key], deadline)
    scope = _workflow_output_scope(record)
    return service.repository.commit_long_task_resume_output(
        dispatch, key, lambda session: workflow_output.write_output(session, **scope, message=message)
    )


async def claim_queued_execution(
    reference, workflow_id, session_id, user_id, *, execution_snapshot=None, dispatch_kind="START"
):
    if not isinstance(reference, dict) or set(reference) != {"execution_id", "dispatch_id"}:
        raise PlatformAgentExecutionError()
    service = get_service()
    if execution_snapshot is not None:
        actual_user_from_snapshot(execution_snapshot, user_id)
    execution = service.repository.get_execution(reference["execution_id"])
    if (execution["workflow_id"], execution["session_id"], execution["user_id"], execution["tenant_id"]) != (
        workflow_id,
        session_id,
        user_id,
        get_current_tenant_id(),
    ):
        raise PlatformAgentExecutionError()
    if execution["dispatches"].get(reference["dispatch_id"], {}).get("kind") != dispatch_kind:
        raise PlatformAgentExecutionError()
    login_user = UserPayload(user_id=user_id, user_role=[], tenant_id=execution["tenant_id"])
    dispatch = service.repository.claim_dispatch(reference["execution_id"], reference["dispatch_id"])
    if dispatch is None:
        return None
    context = {"service": service, "login_user": login_user, "dispatch": dispatch, "execution": execution}
    try:
        actor = await service.authorize(
            login_user, workflow_id, "edit" if execution["entry_kind"] == "DEBUG" else "use"
        )
        if execution["actor_reference"].get("token_version") != actor.token_version:
            raise TokenVersionMismatchError()
        if service.repository.environment(service.current_config) != execution["actor_reference"].get("environment"):
            from bisheng.common.errcode.flow import PlatformAgentEnvironmentError

            raise PlatformAgentEnvironmentError()
    except Exception as error:
        raise QueuedExecutionRejected(context, error) from None
    return context
