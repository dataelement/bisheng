"""Publish and execute existing tools and distribute immutable enterprise skills."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from loguru import logger

MAX_BUNDLE_BYTES = 16 * 1024 * 1024
MAX_BUNDLE_FILES = 512


class WorkCapabilitiesService:
    def __init__(self, user, publications=None):
        self.user = user
        if publications is None:
            from bisheng.dsh.domain.repositories.work_publication import WorkPublicationRepository

            publications = WorkPublicationRepository()
        self.publications = publications

    async def _tools(self):
        from bisheng.tool.domain.services.tool import ToolServices

        groups = await ToolServices(login_user=self.user).get_tool_list(action="use")
        from bisheng.tool.domain.services.user_availability import UserToolAvailabilityService

        tools = [tool for group in groups for tool in group.children if not tool.is_delete]
        disabled = await UserToolAvailabilityService(self.user.user_id).disabled_ids(tools)
        return {tool.id: tool for tool in tools if tool.id not in disabled}

    async def _skills(self):
        from bisheng.linsight.domain.services.user_skills import UserSkillsService

        return {skill.id: skill for skill, _ in await UserSkillsService(self.user.user_id).records()}

    async def publish(self, kind: str, resource_id: int, enabled: bool):
        raise HTTPException(410, "Capabilities follow resource permissions; manage the resource directly")

    async def _executor(self, tool_id: int):
        from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
        from bisheng.tool.domain.services.executor import ToolExecutor

        return await ToolExecutor.init_by_tool_id(
            tool_id=tool_id,
            user_id=self.user.user_id,
            app_id="desktop-work",
            app_name="Desktop Work",
            app_type=ApplicationTypeEnum.DSH_DESKTOP,
        )

    async def list_tools(self):
        result = []
        for tool_id, tool in (await self._tools()).items():
            try:
                executor = await self._executor(tool_id)
                schema = self._schema(executor)
            except (ValueError, KeyError, RuntimeError, PermissionError, OSError, HTTPException) as exc:
                # A tool awaiting connection setup is optional to the rest of the directory.
                logger.warning("Work tool setup pending id={} error={}", tool_id, type(exc).__name__)
                continue
            version = hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()
            result.append(
                {
                    "name": f"bisheng_tool_{tool_id}",
                    "title": tool.name,
                    "description": tool.desc or tool.name,
                    "inputSchema": schema,
                    "_meta": {"bisheng.tool_id": tool_id, "bisheng.schema_hash": version},
                }
            )
        return sorted(result, key=lambda tool: tool["name"])

    @staticmethod
    def _schema(executor):
        schema = executor.args_schema
        if isinstance(schema, dict):
            return schema
        return executor.get_input_schema().model_json_schema()

    async def call_tool(self, name: str, arguments: dict[str, Any]):
        match = re.fullmatch(r"bisheng_tool_([1-9][0-9]*)", name)
        if not match:
            raise HTTPException(404, "Tool is unavailable")
        tool_id = int(match[1])
        allowed_tools = await self._tools()
        if tool_id not in allowed_tools:
            raise HTTPException(403, "Tool is unavailable for this user")
        executor = await self._executor(tool_id)
        # Validate against the current executable schema; the model controls only arguments.
        import jsonschema

        jsonschema.validate(arguments, self._schema(executor))
        operation_id = str(uuid4())
        await self.publications.audit(
            self.user, "call", "tool", tool_id, {"operation_id": operation_id, "status": "STARTED"}
        )
        try:
            async with asyncio.timeout(60):
                result = await executor.ainvoke(arguments)
                if getattr(allowed_tools[tool_id], "is_preset", None) == 2:
                    payload = result
                    if isinstance(payload, str):
                        try:
                            payload = json.loads(payload)
                        except json.JSONDecodeError:
                            # Legacy MCP clients may return plain text on success.
                            payload = None
                    if isinstance(payload, dict) and payload.get("isError") is True:
                        raise HTTPException(502, "Enterprise MCP execution failed")
        except BaseException:
            await self.publications.audit(
                self.user, "call", "tool", tool_id, {"operation_id": operation_id, "status": "INCOMPLETE"}
            )
            raise
        await self.publications.audit(
            self.user, "call", "tool", tool_id, {"operation_id": operation_id, "status": "SUCCEEDED"}
        )
        return result

    async def list_skills(self):
        return [self._skill_info(skill) for skill in (await self._skills()).values()]

    def _skill_info(self, skill):
        return {
            "id": skill.id,
            "name": f"bisheng-{self.user.tenant_id}-{skill.id}-{skill.name}"[:64].rstrip("-"),
            "title": skill.display_name or skill.name,
            "description": skill.description,
            "version": skill.content_hash,
            "uri": f"bisheng-skill://{self.user.tenant_id}/{skill.id}/{skill.content_hash}",
        }

    async def read_skill(self, uri: str):
        match = re.fullmatch(r"bisheng-skill://([1-9][0-9]*)/([1-9][0-9]*)/([a-f0-9]{64})", uri)
        if not match or int(match[1]) != self.user.tenant_id:
            raise HTTPException(404, "Skill is unavailable")
        skill_id = int(match[2])
        skill = (await self._skills()).get(skill_id)
        if skill is None or skill.content_hash != match[3]:
            raise HTTPException(409, "Skill changed or is unavailable; refresh the catalog")
        bundle = await asyncio.to_thread(self._read_bundle, skill)
        if not set(bundle["tool_ids"]).issubset(await self._tools()):
            raise HTTPException(403, "Skill tools are unavailable for this user")
        # A resource change during object-storage IO invalidates this download.
        current = (await self._skills()).get(skill_id)
        if current is None or current.content_hash != skill.content_hash:
            raise HTTPException(409, "Skill changed while loading")
        await self.publications.audit(
            self.user, "load", "skill", skill_id, {"version": skill.content_hash, "status": "SUCCEEDED"}
        )
        return {**self._skill_info(skill), **bundle}

    async def skill_dependencies(self, skill_id: int, version: str):
        from bisheng.linsight.domain.services.skill_service import SkillService
        from bisheng.linsight.domain.services.skill_store import parse_skill_md

        skill = (await self._skills()).get(skill_id)
        if skill is None or skill.content_hash != version:
            raise HTTPException(409, "Skill changed or is unavailable; refresh the catalog")
        # Reuse the current runtime's complete, binary-safe bundle verification.
        files = await asyncio.to_thread(SkillService()._load_existing_bundle, self.user.tenant_id, skill.name, version)
        metadata, _ = parse_skill_md(files["SKILL.md"].decode("utf-8"))
        dependencies = self._dependencies(metadata)
        if not set(dependencies).issubset(await self._tools()):
            raise HTTPException(403, "Skill tools are unavailable for this user")
        current = (await self._skills()).get(skill_id)
        if current is None or current.content_hash != version:
            raise HTTPException(409, "Skill changed while loading")
        return dependencies

    @staticmethod
    def _dependencies(metadata):
        extra = metadata.get("metadata")
        if extra is None:
            extra = {}
        if not isinstance(extra, dict):
            raise HTTPException(422, "Invalid Skill metadata")
        work = extra.get("bisheng-work", {})
        if not isinstance(work, dict):
            raise HTTPException(422, "Invalid Skill Work metadata")
        dependencies = work.get("tool_ids", [])
        if not isinstance(dependencies, list) or any(type(key) is not int or key < 1 for key in dependencies):
            raise HTTPException(422, "Invalid Skill tool dependencies")
        return dependencies

    def _read_bundle(self, skill):
        from bisheng.linsight.domain.services.skill_store import SkillStore, bundle_content_hash, parse_skill_md

        store = SkillStore()
        entries = store.list_files(self.user.tenant_id, skill.name, skill.content_hash)
        if len(entries) > MAX_BUNDLE_FILES or sum(entry["size"] for entry in entries) > MAX_BUNDLE_BYTES:
            raise HTTPException(413, "Skill exceeds Desktop bundle limits")
        files = {
            entry["path"]: store.read_bytes(self.user.tenant_id, skill.name, skill.content_hash, entry["path"])
            for entry in entries
        }
        if sum(len(data) for data in files.values()) > MAX_BUNDLE_BYTES:
            raise HTTPException(413, "Skill exceeds Desktop bundle limits")
        if "SKILL.md" not in files or bundle_content_hash(files) != skill.content_hash:
            raise HTTPException(409, "Skill bundle integrity check failed")
        metadata, content = parse_skill_md(files["SKILL.md"].decode("utf-8"))
        dependencies = self._dependencies(metadata)
        return {
            "content": content,
            "tool_ids": dependencies,
            "files": [
                {"path": path, "data": base64.b64encode(data).decode(), "sha256": hashlib.sha256(data).hexdigest()}
                for path, data in sorted(files.items())
            ],
        }
