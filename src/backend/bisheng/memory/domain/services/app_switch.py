"""App-level memory switches read from the database (design decision 17, R5).

Never trust the object a runtime happens to hold: the assistant switch is read
by primary key each time, and the workflow switch comes from the ONLINE version
(``flow.status == 2`` and ``flow_version.is_current == 1``) start node parameter
``memory_enabled``. A version without the parameter counts as off (AC-71).
"""

from __future__ import annotations

from sqlmodel import select

from bisheng.memory.domain.ports import SCENE_ASSISTANT, SCENE_DAILY, SCENE_LINSIGHT, SCENE_WORKFLOW
from bisheng.memory.domain.repositories import _db

FLOW_TYPE_SCENE = {5: SCENE_ASSISTANT, 10: SCENE_WORKFLOW, 15: SCENE_DAILY, 20: SCENE_LINSIGHT}
START_NODE_TYPE = "start"


def start_node_memory_enabled(data: dict | None) -> bool:
    """Read the start node's ``memory_enabled`` from a workflow graph JSON."""
    for node in (data or {}).get("nodes") or []:
        node_data = node.get("data") or {}
        if node_data.get("type") != START_NODE_TYPE:
            continue
        for group in node_data.get("group_params") or []:
            for param in group.get("params") or []:
                if param.get("key") == "memory_enabled":
                    return bool(param.get("value"))
    return False


async def assistant_memory_enabled(assistant_id: str | None) -> tuple[bool, str | None]:
    if not assistant_id:
        return False, None
    from bisheng.database.models.assistant import Assistant

    async with _db.async_session() as s:
        row = await s.get(Assistant, assistant_id)
    if row is None or row.is_delete:
        return False, None
    return bool(row.memory_enabled), row.name


def assistant_memory_enabled_sync(assistant_id: str | None) -> bool:
    if not assistant_id:
        return False
    from bisheng.database.models.assistant import Assistant

    with _db.sync_session() as s:
        row = s.get(Assistant, assistant_id)
    return bool(row is not None and not row.is_delete and row.memory_enabled)


def _online_stmt(flow_id: str):
    from bisheng.database.models.flow import Flow
    from bisheng.database.models.flow_version import FlowVersion

    return (
        select(FlowVersion.data, Flow.name)
        .join(Flow, Flow.id == FlowVersion.flow_id)
        .where(FlowVersion.flow_id == flow_id, FlowVersion.is_current == 1, Flow.status == 2)
    )


async def workflow_memory_enabled(flow_id: str | None) -> tuple[bool, str | None]:
    if not flow_id:
        return False, None
    async with _db.async_session() as s:
        row = (await s.exec(_online_stmt(flow_id))).first()
    if row is None:
        return False, None
    return start_node_memory_enabled(row[0]), row[1]


def workflow_memory_enabled_sync(flow_id: str | None) -> bool:
    if not flow_id:
        return False
    with _db.sync_session() as s:
        row = s.exec(_online_stmt(flow_id)).first()
    return bool(row is not None and start_node_memory_enabled(row[0]))


async def session_scene(chat_id: str):
    """(scene, app_id, app_enabled, app_name, deleted) for a registered session."""
    from bisheng.database.models.session import MessageSession

    async with _db.async_session() as s:
        session = await s.get(MessageSession, chat_id)
    if session is None:
        return SCENE_DAILY, None, True, None, False
    scene = FLOW_TYPE_SCENE.get(int(session.flow_type or 15), SCENE_DAILY)
    deleted = bool(session.is_delete)
    if scene == SCENE_ASSISTANT:
        enabled, name = await assistant_memory_enabled(session.flow_id)
        return scene, session.flow_id, enabled, name, deleted
    if scene == SCENE_WORKFLOW:
        enabled, name = await workflow_memory_enabled(session.flow_id)
        return scene, session.flow_id, enabled, name, deleted
    return scene, None, True, None, deleted
