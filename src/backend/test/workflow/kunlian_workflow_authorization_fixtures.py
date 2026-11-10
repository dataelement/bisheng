from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

from bisheng.permission.domain.services.permission_action_service import PermissionActor

WORKFLOW = "a" * 32
OTHER_WORKFLOW = "b" * 32
TENANT = 7
ADMIN = 11
MEMBER = 12
SOURCE_ID = "4611686018427387901"


class Receipts:
    def __init__(self):
        self.records = {}

    async def claim_or_read(self, key, digest):
        from bisheng.workflow.application.kunlian_workflow_authorization import GrantReceipt

        # 隔离 ASGI 应用内的领取和写入在同一协程步骤完成。
        if key in self.records:
            return self.records[key], False
        self.records[key] = GrantReceipt(digest=digest, ref=uuid4().hex)
        return self.records[key], True

    async def complete(self, key, result):
        current = self.records[key]
        if current.result is None:
            self.records[key] = replace(current, result=result)
        return self.records[key].result


def direct_row(*, subject_type="user", scope="LOCAL", protected=False, assignee_id=SOURCE_ID):
    return {
        "assignee_id": assignee_id,
        "assignee_version": 1,
        "subject": {"type": subject_type, "id": str(MEMBER), "name": "内部姓名"},
        "model": {"key": "viewer"},
        "scope": scope,
        "inherited_from": None if scope == "LOCAL" else "folder:1",
        "protected": protected,
        "editable": True,
    }


class PermissionFixture:
    def __init__(self):
        self.revision = 3
        self.catalog = 12
        self.current = True
        self.known = True
        self.managers = {ADMIN}
        self.active_users = {ADMIN, MEMBER, 13}
        self.membership = False
        self.rows = []
        self.page_callback = None
        self.operations = {}
        self.receipts = Receipts()
        self.mutations = 0
        self.target_user = (TENANT, MEMBER)
        self.after_change = None

    def actions(self, actor):
        if actor.user_id in self.managers:
            return {"manage_permission", "visible"}
        if actor.user_id == MEMBER and (self.membership or any(row["subject"]["type"] == "user" for row in self.rows)):
            return {"visible"}
        return set()

    async def check(self, *, resource_type, resource_id, action, actor):
        assert resource_type == "workflow" and resource_id == WORKFLOW
        return action in self.actions(actor) if self.known else None

    async def resolve(self, *, resource_type, resource_id, action, actor):
        return SimpleNamespace(
            tenant_id=TENANT if resource_id == WORKFLOW else 8,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_version=self.revision,
        )

    async def verify_subject(self, subject, workflow_id, action):
        return (
            subject.connection_id == "kunlian-mock"
            and subject.tenant_id == TENANT
            and subject.user_id in self.active_users
        )

    async def resolve_member(self, subject, subject_ref):
        return self.target_user if subject_ref == "member-b" else None

    async def get_context(self, **kwargs):
        return {
            "resource_version": self.revision,
            "catalog_release_id": self.catalog,
            "projection_state": "CURRENT" if self.current else "PROJECTING",
            "can_manage_permission": kwargs["actor"].user_id in self.managers,
        }

    async def list_grants(self, *, cursor, page_size, **kwargs):
        offset = int(cursor or 0)
        end = offset + page_size
        result = {
            "data": self.rows[offset:end],
            "has_more": end < len(self.rows),
            "next_cursor": str(end) if end < len(self.rows) else None,
        }
        if self.page_callback is not None:
            self.page_callback()
        return result

    async def get_grantable_models(self, **kwargs):
        return [{"key": "viewer", "active": True}, {"key": "owner", "active": True}]

    async def get_my_permissions(self, **kwargs):
        return {
            "actions": sorted(self.actions(kwargs["actor"])),
            "projection_degraded": not self.current,
            "sources": ["private"],
        }

    async def check_workflow_direct_user_grant(self, *, resource_id, actor, assignee_id, expected_assignee_version):
        from bisheng.common.errcode.permission import PermissionInvalidResourceError, PermissionVersionConflictError

        row = next((item for item in self.rows if int(item["assignee_id"]) == assignee_id), None)
        if row is None or row["protected"] or row["scope"] != "LOCAL" or row["subject"]["type"] != "user":
            raise PermissionInvalidResourceError()
        if row["assignee_version"] != expected_assignee_version:
            raise PermissionVersionConflictError()

    async def mutate_grants(self, *, resource_type, resource_id, actor, request):
        from bisheng.common.errcode.permission import PermissionVersionConflictError

        if (request.expected_resource_version, request.expected_catalog_release_id) != (self.revision, self.catalog):
            raise PermissionVersionConflictError()
        (change,) = request.changes
        self.last_change = change
        if change.op.value == "ADD":
            assert change.subject.id == str(MEMBER) and change.subject.type == "user"
            self.rows.append(direct_row())
        else:
            self.rows = [row for row in self.rows if row["assignee_id"] != change.assignee_id]
        self.revision += 1
        self.mutations += 1
        applied_revision = self.revision
        self.operations[request.idempotency_key] = ("FINALIZED", applied_revision)
        if self.after_change is not None:
            await self.after_change(request.idempotency_key)
        return {"resource_version": applied_revision}

    async def get_workflow_grant_outcome(self, *, resource_id, actor, idempotency_key):
        return self.operations.get(idempotency_key)

    def subject(self, user=ADMIN, **changes):
        from bisheng.workflow.application.kunlian_workflow_authorization import AuthorizationSubject

        return replace(
            AuthorizationSubject("kunlian-mock", TENANT, user, PermissionActor(user_id=user, tenant_id=TENANT)),
            **changes,
        )

    def service(self):
        from bisheng.workflow.application.kunlian_workflow_authorization import WorkflowAuthorizationService

        return WorkflowAuthorizationService(
            permissions=self,
            targets=self,
            decisions=self,
            verify_subject=self.verify_subject,
            resolve_member=self.resolve_member,
            receipts=self.receipts,
            allowed_models={"viewer"},
        )

    def app(self):
        from fastapi import FastAPI

        from bisheng.open_endpoints.api.endpoints import kunlian_workflow_permissions as api

        app = FastAPI()
        app.include_router(api.router)
        app.dependency_overrides[api.authorization_service] = self.service
        return app, api
