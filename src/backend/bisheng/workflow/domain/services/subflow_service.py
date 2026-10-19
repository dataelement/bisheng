"""F086: reference bookkeeping and the online, save and delete checks for subflows.

Every entry that writes ``Flow.data`` must call ``sync_refs``; otherwise the
delete check lets a still-referenced workflow go (design pitfall 4).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from bisheng.common.errcode.flow import (
    WorkFlowReferencedDeleteError,
    WorkFlowSubflowNotFoundError,
    WorkFlowSubflowOnlineCheckError,
)
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.core.database import get_async_db_session
from bisheng.database.models.flow import FlowDao, FlowType
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.workflow.domain.repositories.implementations.subflow_ref_repository_impl import SubflowRefRepositoryImpl
from bisheng.workflow.domain.repositories.interfaces.subflow_ref_repository import SubflowRefRepository
from bisheng.workflow.domain.services.subflow_inspect import FlowInspection, inspect_flow_data

CANDIDATE_FIELDS = ("id", "name", "description", "logo")
# Names in error texts are joined with this; the frontend shows them as one string.
NAME_SEPARATOR = ", "


@asynccontextmanager
async def _ref_repo() -> AsyncIterator[SubflowRefRepository]:
    async with get_async_db_session() as session:
        yield SubflowRefRepositoryImpl(session)


def _diff(old: list[str], new: list[str]) -> tuple[list[str], list[str]]:
    return [one for one in new if one not in old], [one for one in old if one not in new]


def _problem_names(inspection: FlowInspection) -> list[str]:
    return [one["name"] for one in inspection.forbidden_nodes] + inspection.invalid_output_names


class SubflowService:
    @classmethod
    async def sync_refs(cls, flow_id: str, data: dict | None) -> None:
        """Record the workflows that ``data`` (the current version of ``flow_id``) uses as subflows."""
        child_ids = [one for one in inspect_flow_data(data).subflow_ids if one != flow_id]
        async with _ref_repo() as repo:
            await repo.replace_for_parent(flow_id, child_ids)

    @classmethod
    async def clear_refs(cls, flow_id: str) -> None:
        async with _ref_repo() as repo:
            await repo.delete_for_parent(flow_id)

    @classmethod
    async def _referrers(cls, flow_id: str) -> list[dict]:
        """Existing workflows that reference ``flow_id``, as ``[{id, name}]``."""
        async with _ref_repo() as repo:
            parent_ids = await repo.list_referrer_ids(flow_id)
        if not parent_ids:
            return []
        parents = {one.id: one for one in await FlowDao.aget_flow_by_ids(parent_ids)}
        return [{"id": one, "name": parents[one].name} for one in parent_ids if one in parents]

    @classmethod
    async def check_online(cls, data: dict | None) -> None:
        """Reject going online when a referenced workflow cannot run as a subflow."""
        child_ids = inspect_flow_data(data).subflow_ids
        if not child_ids:
            return
        children = {one.id: one for one in await FlowDao.aget_flow_by_ids(child_ids)}
        for child_id in child_ids:
            child = children.get(child_id)
            if child is None:
                raise WorkFlowSubflowNotFoundError()
            inspection = inspect_flow_data(child.data)
            if not inspection.eligible:
                raise WorkFlowSubflowOnlineCheckError(
                    subflow_name=child.name,
                    reasons=NAME_SEPARATOR.join(_problem_names(inspection)),
                    reason_codes=inspection.ineligible_reasons,
                )

    @classmethod
    async def build_save_warning(cls, flow_id: str, old_data: dict | None, new_data: dict | None) -> dict | None:
        """Warning for the editor of a referenced workflow; ``None`` when there is nothing to say.

        ``old_data`` must be read before the save overwrites it, or the
        interface never looks changed.
        """
        referrers = await cls._referrers(flow_id)
        if not referrers:
            return None
        old, new = inspect_flow_data(old_data), inspect_flow_data(new_data)
        old_inputs = [one["name"] for one in old.inputs]
        new_inputs = [one["name"] for one in new.inputs]
        inputs_added, inputs_removed = _diff(old_inputs, new_inputs)
        outputs_added, outputs_removed = _diff(old.outputs, new.outputs)
        changes = {
            "inputs_added": inputs_added,
            "inputs_removed": inputs_removed,
            "outputs_added": outputs_added,
            "outputs_removed": outputs_removed,
        }
        if not new.forbidden_nodes and not any(changes.values()):
            return None
        return {"referenced_by": referrers, "forbidden_nodes": new.forbidden_nodes, "interface_changes": changes}

    @classmethod
    async def check_delete(cls, flow_id: str) -> None:
        referrers = await cls._referrers(flow_id)
        if referrers:
            raise WorkFlowReferencedDeleteError(
                referenced_by=NAME_SEPARATOR.join(one["name"] for one in referrers),
                referrers=referrers,
            )

    @classmethod
    async def filter_candidates(cls, rows: list[dict], exclude_flow_id: str | None) -> list[dict]:
        """Keep the rows of one list page whose workflow can be used as a subflow."""
        ids = [row["id"] for row in rows if row.get("id") and row["id"] != exclude_flow_id]
        flows = {one.id: one for one in await FlowDao.aget_flow_by_ids(ids)}
        result = []
        for row in rows:
            flow = flows.get(row.get("id"))
            if flow is None or not inspect_flow_data(flow.data).eligible:
                continue
            result.append({key: row.get(key) for key in CANDIDATE_FIELDS})
        return result

    @classmethod
    async def get_interface(cls, login_user: Any, flow_id: str) -> dict:
        """Input parameters and return names of a workflow, for the editor who configures it."""
        flow = await FlowDao.aget_flow_by_id(flow_id)
        if flow is None or flow.flow_type != FlowType.WORKFLOW.value:
            raise NotFoundError()
        await require_business_action(login_user, resource_type="workflow", resource_id=flow_id, action="edit")
        inspection = inspect_flow_data(flow.data)
        return {
            "id": flow.id,
            "name": flow.name,
            "inputs": inspection.inputs,
            "outputs": inspection.outputs,
            "eligible": inspection.eligible,
            "ineligible_reasons": inspection.ineligible_reasons,
        }
