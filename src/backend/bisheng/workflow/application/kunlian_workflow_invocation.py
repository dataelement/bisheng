"""反向运行的可信主体与业务授权边界。"""

from asyncio import to_thread

from loguru import logger
from pydantic import ValidationError

from bisheng.common.errcode.flow import WorkflowRegistrationDenied
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.permission import (
    InvalidCatalogActionError,
    PermissionDeniedError,
    PermissionInvalidResourceError,
)
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.open_api.application.runtime_authorization import without_open_api_identity
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.permission.application.identity import reset_current_permission_actor, set_current_permission_actor
from bisheng.public_endpoints.domain.context import reset_current_public_api_principal, set_current_public_api_principal
from bisheng.workflow.domain.schemas.kunlian_registration import RegistrationScope
from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import (
    RunError,
    RunOutput,
    RunSubject,
    read_run_control,
)

_QUERY_OPERATION = {"WAITING_INPUT": "interaction", "SUCCEEDED": "result"}


class WorkflowInvocationService:
    def __init__(self, repository, resolve_user, dispatch, *, authorize_operation=None):
        self.repository = repository
        self.resolve_user = resolve_user
        self.dispatch = dispatch
        self.authorize_operation = authorize_operation

    async def authorize(self, subject, workflow_id):
        with tenant_execution_scope(subject.tenant_id):
            try:
                # TODO [F122][EXT-01] 按双方合同解析连接资格与当前自然人身份。
                # TODO [F123][EXT-01] 确认交互提交及恢复时实际用户的解析与授权时效。
                user = await self.resolve_user(subject)
                if user is None or (user.tenant_id, user.user_id) != (subject.tenant_id, subject.user_id):
                    raise RunError("FORBIDDEN")
                await to_thread(self.repository.verify_target, subject.tenant_id, workflow_id)
                # F048 优先读取上下文中的主体。只用本次核验的实际用户做决策。
                with without_open_api_identity():
                    actor_token = set_current_permission_actor(None)
                    guest_token = set_current_public_api_principal(None)
                    try:
                        await require_business_action(
                            user, resource_type="workflow", resource_id=workflow_id, action="use"
                        )
                    finally:
                        reset_current_public_api_principal(guest_token)
                        reset_current_permission_actor(actor_token)
            except (
                UnAuthorizedError,
                InvalidCatalogActionError,
                PermissionDeniedError,
                PermissionInvalidResourceError,
                WorkflowRegistrationDenied,
            ) as exc:
                raise RunError("FORBIDDEN") from exc
        return user

    async def submit(self, subject, key, body):
        await self.authorize(subject, body.workflow_id)
        scope = RegistrationScope(subject.tenant_id, subject.connection_id, 0)
        options = {"run_control": True} if self.authorize_operation is not None else {}
        record, created = await to_thread(self.repository.admit, scope, subject.user_id, key, body, **options)
        logger.info(
            "昆联运行受理,session_id={} version_id={} replay={}",
            record.session_id,
            record.workflow_version_id,
            not created,
        )
        if created:
            await self.deliver(record.tenant_id, record.session_id)
        return record, created

    async def deliver(self, tenant_id, session_id, interaction_id=None):
        try:
            args = (tenant_id, session_id) if interaction_id is None else (tenant_id, session_id, interaction_id)
            await to_thread(self.dispatch, *args)
        except Exception as exc:
            # 会话已提交,补投会再次处理待领取记录。避免日志输出消息或凭据。
            logger.warning("昆联运行投递待补偿,session_id={} error_type={}", session_id, type(exc).__name__)

    async def _authorized_row(self, subject, session_id):
        row = await to_thread(self.repository.load, subject.tenant_id, session_id)
        if row is None or (row.connection_id, row.user_id) != (subject.connection_id, subject.user_id):
            raise RunError("SESSION_NOT_FOUND")
        try:
            await self.authorize(subject, row.workflow_id)
        except RunError as exc:
            if str(exc) != "FORBIDDEN":
                raise
            raise RunError("SESSION_NOT_FOUND") from exc
        if self.repository.is_expired(row):
            raise RunError("SESSION_NOT_FOUND")
        return row

    async def query(self, subject, session_id):
        row = await self._authorized_row(subject, session_id)
        if read_run_control(row.material) is None:
            material = row.material or {}
            if material.get("mode") == "interactive" or "interaction_id" in material:
                return await to_thread(self.repository.refresh, subject, session_id)
            return row

        await self._require_operation(subject, row, "status")
        authorized = set()
        while True:
            operation = _QUERY_OPERATION.get(row.status)
            if operation is not None and operation not in authorized:
                await self._require_operation(subject, row, operation)
                authorized.add(operation)
            row = await to_thread(self.repository.refresh, subject, session_id)
            if read_run_control(row.material) is None:
                raise RunError("CONTROL_UNAVAILABLE")
            operation = _QUERY_OPERATION.get(row.status)
            if operation is None or operation in authorized:
                return row

    async def _operation_allowed(self, subject, row, operation):
        # TODO [F127][EXT-01] 正式接入时校验可信委托及操作权限映射。
        if self.authorize_operation is None:
            raise RunError("UNAVAILABLE")
        with tenant_execution_scope(subject.tenant_id):
            allowed = await self.authorize_operation(subject, row.workflow_id, operation)
        if type(allowed) is not bool:
            raise RunError("UNAVAILABLE")
        return allowed

    async def _require_operation(self, subject, row, operation):
        if not await self._operation_allowed(subject, row, operation):
            raise RunError("SESSION_NOT_FOUND")

    async def _authorized_control(self, subject, session_id, operation):
        row = await self._authorized_row(subject, session_id)
        await self._require_operation(subject, row, operation)
        if read_run_control(row.material) is None:
            raise RunError("CONTROL_UNAVAILABLE")
        return row

    async def status(self, subject, session_id):
        authorized = await self._authorized_control(subject, session_id, "status")
        can_read_events = await self._operation_allowed(subject, authorized, "events")
        row = await to_thread(self.repository.refresh, subject, session_id)
        control = read_run_control(row.material)
        if control is None:
            raise RunError("CONTROL_UNAVAILABLE")
        return row, control.last_seq if can_read_events else None

    async def cancel(self, subject, session_id):
        await self._authorized_control(subject, session_id, "cancel")
        return await to_thread(self.repository.request_cancel, subject, session_id)

    async def events(self, subject, session_id, after, limit):
        await self._authorized_control(subject, session_id, "events")
        return await to_thread(self.repository.read_events, subject, session_id, after, limit)

    async def result(self, subject, session_id):
        await self._authorized_control(subject, session_id, "result")
        row, _ = await to_thread(self.repository.read_control, subject, session_id)
        if row.status != "SUCCEEDED":
            raise RunError("RESULT_NOT_AVAILABLE")
        try:
            output = RunOutput.model_validate(row.output).model_dump()
        except ValidationError as exc:
            raise RunError("UNAVAILABLE") from exc
        return {"session_id": row.session_id, "workflow_version_id": str(row.workflow_version_id), "output": output}

    async def trace(self, subject, session_id):
        await self._authorized_control(subject, session_id, "trace")
        row, control = await to_thread(self.repository.read_control, subject, session_id)
        return {"session_id": row.session_id, "trace_id": control.trace_id}

    async def answer(self, subject, session_id, interaction_id, key, body):
        row = await self._authorized_row(subject, session_id)
        if read_run_control(row.material) is not None:
            await self._require_operation(subject, row, "interaction")
        receipt, created = await to_thread(self.repository.answer, subject, session_id, interaction_id, key, body.input)
        if created:
            await self.deliver(subject.tenant_id, session_id, interaction_id)
        return receipt, created

    async def reconcile(self, scope, limit=100):
        pending = await to_thread(self.repository.reconcile, scope, limit, include_resumes=True)
        for session_id, interaction_id in pending:
            await self.deliver(scope.tenant_id, session_id, interaction_id)

    async def authorize_run(self, row):
        return await self.authorize(RunSubject(row.tenant_id, row.connection_id, row.user_id), row.workflow_id)
