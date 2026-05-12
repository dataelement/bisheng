"""Lazy exports for v1 routers.

Importing nested schema modules under ``bisheng.api.v1`` should not
eagerly initialize the entire v1 router tree. Keep router construction
lazy so domain/service scripts can safely import schema definitions.
"""

from __future__ import annotations

from typing import Any

_ROUTER_EXPORTS = {
    'assistant_router': ('bisheng.api.v1.assistant', 'router'),
    'audit_router': ('bisheng.api.v1.audit', 'router'),
    'chat_router': ('bisheng.api.v1.chat', 'router'),
    'endpoints_router': ('bisheng.api.v1.endpoints', 'router'),
    'evaluation_router': ('bisheng.api.v1.evaluation', 'router'),
    'flows_router': ('bisheng.api.v1.flows', 'router'),
    'invite_code_router': ('bisheng.api.v1.invite_code', 'router'),
    'mark_router': ('bisheng.api.v1.mark_task', 'router'),
    'report_router': ('bisheng.api.v1.report', 'router'),
    'skillcenter_router': ('bisheng.api.v1.skillcenter', 'router'),
    'tag_router': ('bisheng.api.v1.tag', 'router'),
    'group_router': ('bisheng.api.v1.usergroup', 'router'),
    'variable_router': ('bisheng.api.v1.variable', 'router'),
    'workflow_router': ('bisheng.api.v1.workflow', 'router'),
    'tool_router': ('bisheng.tool.api.tool', 'router'),
    'user_router': ('bisheng.user.api.user', 'router'),
    'workstation_router': ('bisheng.workstation.api', 'router'),
}

__all__ = list(_ROUTER_EXPORTS.keys())


def __getattr__(name: str) -> Any:
    target = _ROUTER_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = __import__(module_name, fromlist=[attr_name])
    return getattr(module, attr_name)
