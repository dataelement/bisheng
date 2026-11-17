"""Authenticated workflow-variable operations with verified ownership."""

from fastapi import HTTPException

from bisheng.common.errcode.flow import WorkFlowOnlineEditError
from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.variable.domain.repositories.variable_repository import VariableRepository


class VariableService:
    @staticmethod
    def _tenant(user):
        tenant_id = get_current_tenant_id()
        if not tenant_id or tenant_id <= 0:
            raise HTTPException(403, "Missing tenant context")
        return tenant_id

    @staticmethod
    def _target(repository, flow_id, version_id, tenant_id, *, write=False):
        flow = repository.flow(flow_id, lock=write)
        if not flow or flow.flow_type != 10 or flow.tenant_id != tenant_id:
            raise HTTPException(404, "Workflow not found")
        version = repository.version(flow_id, version_id, lock=write)
        if not version or version.tenant_id != tenant_id or version.flow_type != 10:
            raise HTTPException(404, "Workflow version not found")
        if write and flow.status == 2 and version.is_current == 1:
            raise WorkFlowOnlineEditError()
        return flow, version

    @staticmethod
    def _owned(variable, tenant_id):
        if not variable or variable.tenant_id != tenant_id:
            raise HTTPException(404, "Variable not found")
        return variable

    @staticmethod
    async def _authorize(user, flow, action):
        await require_business_action(user, resource_type="workflow", resource_id=flow.id, action=action)

    @classmethod
    async def list(cls, user, flow_id, version_id=None, node_id=None, variable_name=None):
        tenant_id = cls._tenant(user)
        with strict_tenant_filter(), VariableRepository.transaction() as repository:
            flow, version = cls._target(repository, flow_id, version_id, tenant_id)
            await cls._authorize(user, flow, "visible")
            rows = repository.variables(flow.id, version.id, node_id, variable_name)
            return [cls._owned(row, tenant_id).model_dump(exclude={"tenant_id"}) for row in rows]

    @classmethod
    async def save(cls, user, data):
        tenant_id = cls._tenant(user)
        with strict_tenant_filter(), VariableRepository.transaction() as repository:
            variable = None
            if data.id is not None:
                variable = cls._owned(repository.variable(data.id), tenant_id)
                flow_id, version_id = variable.flow_id, variable.version_id
            else:
                flow_id, version_id = data.flow_id, data.version_id
            flow, version = cls._target(repository, flow_id, version_id, tenant_id)
            await cls._authorize(user, flow, "edit")
            # No awaits after locking: sync lock waits must not block a lock holder's await.
            flow, version = cls._target(repository, flow_id, version_id, tenant_id, write=True)
            if data.id is not None:
                variable = cls._owned(repository.variable(data.id, lock=True), tenant_id)
                if (variable.flow_id, variable.version_id) != (flow.id, version.id):
                    raise HTTPException(409, "Variable ownership changed")
            if (data.flow_id, data.version_id) != (flow.id, version.id) or (
                variable and data.node_id != variable.node_id
            ):
                raise HTTPException(400, "Variable ownership cannot be changed")
            duplicates = repository.variables(flow.id, version.id, data.node_id, data.variable_name, lock=True)
            if any(row.id != data.id for row in duplicates):
                raise HTTPException(409, "Variable name already exists")
            values = data.model_dump(exclude={"id"})
            if variable is None:
                variable = repository.insert(values, tenant_id)
            else:
                for name in ("variable_name", "value", "value_type", "is_option"):
                    setattr(variable, name, values[name])
                repository.flush()
            return variable.model_dump(exclude={"tenant_id"})

    @classmethod
    async def delete(cls, user, variable_id):
        tenant_id = cls._tenant(user)
        with strict_tenant_filter(), VariableRepository.transaction() as repository:
            variable = cls._owned(repository.variable(variable_id), tenant_id)
            target = (variable.flow_id, variable.version_id)
            flow, _ = cls._target(repository, *target, tenant_id)
            await cls._authorize(user, flow, "edit")
            cls._target(repository, *target, tenant_id, write=True)
            variable = cls._owned(repository.variable(variable_id, lock=True), tenant_id)
            if (variable.flow_id, variable.version_id) != target:
                raise HTTPException(409, "Variable ownership changed")
            repository.remove(variable)

    @classmethod
    async def replace(cls, user, data):
        if not data:
            raise HTTPException(400, "Variables must not be empty")
        target = (data[0].flow_id, data[0].version_id)
        if any((item.flow_id, item.version_id) != target for item in data):
            raise HTTPException(400, "Variables must belong to one workflow version")
        keys = [(item.node_id, item.variable_name) for item in data]
        if len(keys) != len(set(keys)):
            raise HTTPException(400, "Duplicate variable names")
        tenant_id = cls._tenant(user)
        with strict_tenant_filter(), VariableRepository.transaction() as repository:
            flow, version = cls._target(repository, *target, tenant_id)
            await cls._authorize(user, flow, "edit")
            flow, version = cls._target(repository, *target, tenant_id, write=True)
            for variable in repository.variables(flow.id, version.id, lock=True):
                repository.remove(cls._owned(variable, tenant_id))
            repository.flush()
            for item in data:
                repository.insert(item.model_dump(exclude={"id"}), tenant_id)
