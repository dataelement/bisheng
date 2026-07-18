"""F018 resource-type registry — 7 supported transfer types.

Single source of truth for the shape of each resource type that F018's
owner-transfer logic touches. Adding a type here is the only place that
needs to change when Dashboard (or any future resource) joins the 7-type
MVP set — the service loops over ``REGISTRY`` for both SELECT and UPDATE.

Each metadata entry answers:
  - ``table``: MySQL table name (SQL template directly interpolates it)
  - ``id_type``: ``int`` or ``str`` — Flow/Assistant/Channel carry UUIDs
  - ``type_filter_sql``: optional WHERE clause fragment to distinguish
    resource variants that share a physical table (knowledge ↔ chat,
    flow ↔ assistant/workstation, etc.)

Rules:
  - Do NOT parameterize ``table`` or ``type_filter_sql`` — they come from
    this module's constants only, never from user input (no injection).
  - ``type_filter_sql`` is appended via ``AND``; write it as a bare
    boolean expression, no leading ``AND``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from bisheng.common.errcode.resource_owner_transfer import (
    ResourceTransferUnsupportedTypeError,
)


@dataclass(frozen=True)
class ResourceTypeMeta:
    resource_type: str
    table: str
    id_type: type
    type_filter_sql: Optional[str]


REGISTRY: Dict[str, ResourceTypeMeta] = {
    # Knowledge Space — Knowledge.type = 3 (KnowledgeTypeEnum.SPACE).
    # The other Knowledge.type values carry chat/QA/private variants we
    # deliberately exclude from transfer.
    'knowledge_space': ResourceTypeMeta(
        resource_type='knowledge_space',
        table='knowledge',
        id_type=int,
        type_filter_sql='type = 3',
    ),
    # Folder — KnowledgeFile.file_type = 0 (FileType.DIR).
    'folder': ResourceTypeMeta(
        resource_type='folder',
        table='knowledgefile',
        id_type=int,
        type_filter_sql='file_type = 0',
    ),
    # Knowledge File — KnowledgeFile.file_type = 1 (FileType.FILE).
    'knowledge_file': ResourceTypeMeta(
        resource_type='knowledge_file',
        table='knowledgefile',
        id_type=int,
        type_filter_sql='file_type = 1',
    ),
    # Workflow — Flow.flow_type = 10 (FlowType.WORKFLOW). Flow.id is a
    # UUID string.
    'workflow': ResourceTypeMeta(
        resource_type='workflow',
        table='flow',
        id_type=str,
        type_filter_sql='flow_type = 10',
    ),
    # Assistant — standalone table; id is a UUID string.
    'assistant': ResourceTypeMeta(
        resource_type='assistant',
        table='assistant',
        id_type=str,
        type_filter_sql=None,
    ),
    # Tool — t_gpts_tools; is_delete=0 excludes tombstones.
    'tool': ResourceTypeMeta(
        resource_type='tool',
        table='t_gpts_tools',
        id_type=int,
        type_filter_sql='is_delete = 0',
    ),
    # Channel — standalone table; id is CHAR(36) UUID.
    'channel': ResourceTypeMeta(
        resource_type='channel',
        table='channel',
        id_type=str,
        type_filter_sql=None,
    ),
}

SUPPORTED_TYPES = tuple(REGISTRY.keys())


def get_meta(resource_type: str) -> ResourceTypeMeta:
    """Return metadata for ``resource_type`` or raise 19604.

    The service layer relies on this to short-circuit on unknown types
    before running any SQL.
    """
    meta = REGISTRY.get(resource_type)
    if meta is None:
        raise ResourceTransferUnsupportedTypeError()
    return meta
