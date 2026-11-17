"""Protect legacy browser form-variable entry points with canonical workflow facts."""

from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.workflow.domain.repositories.variable_repository import VariableRepository


async def _parent(user, flow_id, version_id, action):
    parent, version = await VariableRepository.parent(flow_id, version_id)
    if action == "edit" and parent.tenant_id != get_current_tenant_id():
        raise UnAuthorizedError()
    await require_business_action(user, resource_type="workflow", resource_id=parent.id, action=action)
    return parent, version


async def list_variables(user, flow_id, node_id=None, variable_name=None, version_id=None):
    parent, version = await _parent(user, flow_id, version_id, "visible")
    return await VariableRepository.listing(parent, version, node_id, variable_name)


async def save_variable(user, variable):
    parent, version = await _parent(user, variable.flow_id, variable.version_id, "edit")
    if variable.id:
        old = await VariableRepository.by_id(variable.id)
        if (old.flow_id, old.version_id, old.tenant_id) != (parent.id, version.id, parent.tenant_id):
            raise NotFoundError()
    return await VariableRepository.mutate(parent, [variable])


async def delete_variable(user, variable_id):
    value = await VariableRepository.by_id(variable_id)
    parent, _ = await _parent(user, value.flow_id, value.version_id, "edit")
    if value.tenant_id != parent.tenant_id:
        raise NotFoundError()
    await VariableRepository.mutate(parent, delete_id=variable_id)


async def replace_variables(user, values):
    if not values:
        return  # The legacy empty payload carries no parent; it cannot delete anything.
    parent, _ = await _parent(user, values[0].flow_id, values[0].version_id, "edit")
    for value in values:
        if value.flow_id != parent.id:
            raise NotFoundError()
        checked, _ = await VariableRepository.parent(value.flow_id, value.version_id)
        if checked.tenant_id != parent.tenant_id:
            raise NotFoundError()
    await VariableRepository.mutate(parent, values, replace=True)
