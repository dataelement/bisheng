"""One bounded background unit, independent of model, body and billing workflows."""

from bisheng.dsh.domain.services.model_audit_queries import DshModelAuditQueryService


class DshAuditTreeProjectionService:
    def __init__(self, repository_scope):
        self.queries = DshModelAuditQueryService(None, repository_scope)

    async def step(self, tenant, *, owner=None):
        folded = await self.queries.execute(tenant, lambda repo: repo.fold_hierarchy_batch())
        if folded["has_more"]:
            return {"has_more": True, "owner": owner, "status": "FOLD"}
        return await self.queries.execute(tenant, lambda repo: repo.tree_step(owner=owner))

    async def failed(self, tenant, *, owner=None):
        def mark(repo):
            state = repo.tree_state(create=True, lock=True)
            if state.lease_owner and state.lease_owner != owner:
                return
            state.failed = True
            state.lease_owner, state.lease_until = None, None
            repo.session.add(state)

        await self.queries.execute(tenant, mark)
