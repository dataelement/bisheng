"""Administrator scope is historical audit tenant, not current observed-user membership."""

from datetime import UTC, datetime

from bisheng.common.errcode.dsh_audit import DshAuditQueryInvalidError, DshAuditRequestUnavailableError
from bisheng.common.schemas.api import PageData
from bisheng.dsh.domain.services.profile import profile_scope
from bisheng.dsh.infrastructure.model_audit_blocking import run_audit_blocking


class DshModelAuditQueryService:
    def __init__(self, authorize_admin, repository_scope, *, activity=None, window=300, now=None):
        self.authorize_admin, self.repository_scope = authorize_admin, repository_scope
        self.activity, self.window, self.now = activity, window, now or (lambda: datetime.now(UTC))

    async def target(self, actor_id, tenant_id):
        actor, target = await self.authorize_admin(actor_id, tenant_id)
        return target if target is not None else int(actor["tenant_id"])

    async def execute(self, tenant, function):
        def read():
            with profile_scope(tenant), self.repository_scope() as repository:
                return function(repository)

        return await run_audit_blocking(read)

    async def page(self, actor_id, tenant_id, *, user_keyword=None, **query):
        tenant = await self.target(actor_id, tenant_id)
        if query.get("model_id") is not None and query.get("model_name") is not None:
            raise DshAuditQueryInvalidError()
        if user_keyword:
            query["user_keyword"] = user_keyword
        for key in ("start_at", "end_at"):
            value = query.get(key)
            if value is not None and value.tzinfo is not None:
                query[key] = value.astimezone(UTC).replace(tzinfo=None)
        try:
            return await self.execute(tenant, lambda repository: repository.page(**query))
        except ValueError:
            raise DshAuditQueryInvalidError() from None

    async def models(self, actor_id, tenant_id, *, page=1, page_size=20, keyword=None):
        from bisheng.dsh.admin_runtime import read_available_models
        from bisheng.llm.domain.services.llm import LLMService

        tenant = await self.target(actor_id, tenant_id)
        with profile_scope(tenant):
            rows = await read_available_models(await LLMService.get_dsh_model_ids(), LLMService.get_dsh_model_snapshot)
        if keyword:
            rows = [row for row in rows if keyword.casefold() in row["name"].casefold()]
        rows.sort(key=lambda row: (row["name"], row["id"]))
        return {
            "data": [{"id": row["id"], "name": row["name"]} for row in rows[(page - 1) * page_size : page * page_size]],
            "total": len(rows),
        }

    async def users(self, actor, tenant_id, *, page=1, page_size=20, keyword=None):
        from bisheng.tenant.domain.services.tenant_service import TenantService

        tenant = await self.target(actor.user_id, tenant_id)
        with profile_scope(tenant):
            result = await TenantService.aget_tenant_users(
                tenant, page=page, page_size=page_size, keyword=keyword, login_user=actor
            )
        return PageData[dict](
            data=[{"user_id": row["user_id"], "user_name": row["user_name"]} for row in result["data"]],
            total=result["total"],
        ).model_dump()

    async def detail(self, actor_id, tenant_id, request_id):
        tenant = await self.target(actor_id, tenant_id)

        def read(repository):
            row = repository.request(request_id)
            return repository.metadata(row) if row else repository.missing(request_id)

        result = await self.execute(tenant, read)
        if result.get("audit_record_missing") and result["gap"] == "CONFIRMED":
            entered = result["model_entered_at"]
            active = await self.activity(request_id) if self.activity is not None else None
            if active is True or (self.now() - entered).total_seconds() < self.window:
                result["gap"] = "AWAITING"
        return result

    async def parent_conversation(self, actor_id, tenant_id, request_id):
        tenant = await self.target(actor_id, tenant_id)

        def read(repository):
            row = repository.request(request_id)
            if row is None:
                raise DshAuditRequestUnavailableError()
            parent = row.parent_conversation_id
            if (
                row.session_origin != "subagent"
                or not row.conversation_id
                or not parent
                or parent == row.conversation_id
            ):
                return {"status": "NOT_PROVIDED"}
            page = repository.page(user_id=row.user_id, conversation_id=parent, limit=1)
            return (
                {"status": "AVAILABLE", "user_id": row.user_id, "conversation_id": parent}
                if page["items"]
                else {"status": "UNAVAILABLE"}
            )

        return await self.execute(tenant, read)

    async def body_facts(self, actor_id, tenant_id, request_id):
        tenant = await self.target(actor_id, tenant_id)

        def read(repository):
            row = repository.request(request_id)
            if row is None:
                raise DshAuditRequestUnavailableError()
            _manifest, occurrences, contents = repository.facts(request_id)
            return row, occurrences, contents

        return tenant, await self.execute(tenant, read)
