"""Credential-free capability discovery and audited, read-only demo execution."""

import asyncio
import json
from time import monotonic

import jsonschema
from fastapi import HTTPException
from loguru import logger

from bisheng.dsh.domain.services.work_capabilities import WorkCapabilitiesService
from bisheng.tool.domain.services.user_availability import UserToolAvailabilityService, manages_availability

DEMO_TOOLS = {
    (1, "get_current_time"): {"scenario": "time", "arguments": {"timezone": "Asia/Shanghai"}},
    (0, "demo_get_order"): {"scenario": "order", "arguments": {"order_id": "DEMO-20261022-001"}},
    (2, "demo_check_inventory"): {"scenario": "inventory", "arguments": {"product_code": "MAT-001"}},
}


def demo_for(tool):
    identity = tool.tool_key if tool.is_preset == 1 else tool.name
    return DEMO_TOOLS.get((tool.is_preset, identity))


class CapabilityCatalogService:
    def __init__(self, user, work=None):
        self.user = user
        self.work = work or WorkCapabilitiesService(user)

    async def list(self):
        from bisheng.tool.domain.services.tool import ToolServices

        groups = await ToolServices(login_user=self.user).get_tool_list(action="use")
        disabled = await UserToolAvailabilityService(self.user.user_id).disabled_ids(
            [tool for group in groups for tool in group.children or []]
        )
        rows = []
        for group in groups:
            for tool in group.children or []:
                if tool.is_delete:
                    continue
                demo = demo_for(tool)
                # Select fields explicitly. Group schemas and extras may contain credentials.
                rows.append(
                    {
                        "id": f"tool:{tool.id}",
                        "resource_id": tool.id,
                        "kind": {0: "api", 1: "builtin", 2: "mcp"}[tool.is_preset],
                        "name": tool.name,
                        "description": tool.desc or "",
                        "provider": group.name,
                        "ready": tool.id not in disabled,
                        "availability_enabled": tool.id not in disabled if manages_availability(tool) else None,
                        "demo": bool(demo and demo["scenario"] != "time"),
                        "trial": demo,
                        "invocation_name": f"mcp__bisheng__bisheng_tool_{tool.id}",
                    }
                )
        usable_tool_ids = {row["resource_id"] for row in rows if row["ready"]}
        from bisheng.linsight.domain.services.user_skills import UserSkillsService

        for record, enabled in await UserSkillsService(self.user.user_id).records(False):
            skill = self.work._skill_info(record)
            ready = enabled
            if ready:
                try:
                    bundle = await asyncio.to_thread(self.work._read_bundle, record)
                    ready = set(bundle["tool_ids"]).issubset(usable_tool_ids)
                except Exception:
                    # One unavailable bundle is non-critical to the rest of the catalog.
                    logger.exception("Capability catalog Skill bundle unavailable id={}", skill["id"])
                    ready = False
            rows.append(
                {
                    "id": f"skill:{skill['id']}",
                    "resource_id": skill["id"],
                    "kind": "skill",
                    "name": skill["title"],
                    "description": skill["description"],
                    "provider": "BISHENG",
                    "ready": ready,
                    "demo": "demo-order-review" in skill["name"],
                    "trial": None,
                    "invocation_name": skill["name"],
                }
            )
        return {"items": sorted(rows, key=lambda row: (row["kind"], row["id"]))}

    async def picker_tools(self):
        """Safe grouped catalog for per-task selection, independent of workbench curation."""
        from bisheng.tool.domain.services.tool import ToolServices

        groups = await ToolServices(login_user=self.user).get_tool_list(action="use")
        disabled = await UserToolAvailabilityService(self.user.user_id).disabled_ids(
            [tool for group in groups for tool in group.children or []]
        )
        return [
            {
                "id": group.id,
                "name": group.name,
                "description": group.description or "",
                "is_preset": group.is_preset,
                "default_checked": False,
                "children": [
                    {
                        "id": tool.id,
                        "name": tool.name,
                        "tool_key": tool.tool_key,
                        "desc": tool.desc or "",
                        "enabled": tool.id not in disabled,
                    }
                    for tool in group.children or []
                    if not tool.is_delete
                ],
            }
            for group in groups
            if any(not tool.is_delete for tool in group.children or [])
        ]

    async def set_availability(self, tool_id: int, enabled: bool):
        from bisheng.tool.domain.services.tool import ToolServices

        groups = await ToolServices(login_user=self.user).get_tool_list(action="use")
        tool = next(
            (tool for group in groups for tool in group.children or [] if tool.id == tool_id and not tool.is_delete),
            None,
        )
        if tool is None or not manages_availability(tool):
            raise HTTPException(404, "Account availability is unavailable for this tool")
        await UserToolAvailabilityService(self.user.user_id).save(tool_id, enabled)
        await self.work.publications.audit(self.user, "availability", "tool", tool_id, {"enabled": enabled})
        return {"tool_id": tool_id, "enabled": enabled}

    async def trial(self, tool_id: int, arguments: dict):
        if len(json.dumps(arguments).encode()) > 4096:
            raise HTTPException(413, "Demo arguments exceed the allowed size")
        tool = (await self.work._tools()).get(tool_id)
        if tool is None or demo_for(tool) is None:
            raise HTTPException(404, "This capability has no read-only demonstration")
        started = monotonic()
        try:
            # The ordinary Work path rechecks tenant, use permission, schema and audit.
            result = await self.work.call_tool(f"bisheng_tool_{tool_id}", arguments)
        except jsonschema.ValidationError:
            raise HTTPException(422, "Demo arguments do not match the tool schema") from None
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                # Text results, such as the current time, remain text.
                result = {"value": result}
        if tool.is_preset == 2 and isinstance(result, dict):
            content = result.get("content", [])
            if len(content) == 1 and content[0].get("type") == "text":
                try:
                    result = json.loads(content[0]["text"])
                except json.JSONDecodeError:
                    result = {"value": content[0]["text"]}
        return {
            "tool_id": tool_id,
            "result": result,
            "elapsed_ms": round((monotonic() - started) * 1000),
            "demo_data": demo_for(tool)["scenario"] != "time",
        }
