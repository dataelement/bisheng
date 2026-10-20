"""Load explicitly selected enterprise skills for an ordinary chat turn.

Skills supply instructions and scoped bundle reads. Execution tools continue to
come from the platform's authorized tool selection; task mode controls routing.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

from langchain_core.tools import BaseTool, StructuredTool
from loguru import logger
from pydantic import BaseModel, Field

from bisheng.common.errcode.linsight import SkillNotFoundError, SkillValidationError
from bisheng.linsight.domain.models.linsight_skill import LinsightSkillDao
from bisheng.linsight.domain.services.skill_store import SKILL_MD, SkillStore

MAX_SELECTED_SKILLS = 32
MAX_INSTRUCTION_CHARS = 128_000


class SkillFileRead(BaseModel):
    skill_name: str = Field(description="Name of a skill selected for this turn.")
    path: str = Field(default=SKILL_MD, description="Relative text file path inside that skill bundle.")
    offset: int = Field(default=0, ge=0, description="Character offset for paginated reads.")
    limit: int = Field(default=12_000, ge=1, le=24_000, description="Maximum characters to return.")


@dataclass
class ChatSkills:
    instructions: str = ""
    tools: list[BaseTool] = field(default_factory=list)


async def load_chat_skills(
    tenant_id: int,
    user_id: int,
    selected: list[str] | None,
    *,
    store: SkillStore | None = None,
) -> ChatSkills:
    if not selected:
        return ChatSkills()
    names = list(dict.fromkeys(selected))
    if len(names) > MAX_SELECTED_SKILLS:
        raise SkillValidationError(msg=f"Select up to {MAX_SELECTED_SKILLS} skills per turn.")

    # Reuse the same strict-tenant governance gate as the enterprise picker.
    enabled = {row.name: row for row in await LinsightSkillDao.list_enabled()}
    if any(name not in enabled or enabled[name].tenant_id != tenant_id for name in names):
        raise SkillNotFoundError(msg="A selected skill is unavailable. Refresh the skill selection and retry.")
    versions = {name: enabled[name].content_hash for name in names}
    store = store or SkillStore()

    def read_text(name: str, path: str) -> str:
        try:
            return store.read_bytes(tenant_id, name, versions[name], path).decode("utf-8")
        except FileNotFoundError as exc:
            raise SkillNotFoundError(msg=f"Skill file unavailable: {name}/{path}") from exc
        except (ValueError, UnicodeDecodeError) as exc:
            raise SkillValidationError(
                msg="Choose a UTF-8 text file at a relative path inside the skill bundle."
            ) from exc

    entries = []
    total = 0
    for name in names:
        content = await asyncio.to_thread(read_text, name, SKILL_MD)
        if not content.strip():
            raise SkillValidationError(msg=f"Selected skill has empty instructions: {name}")
        total += len(content)
        if total > MAX_INSTRUCTION_CHARS:
            raise SkillValidationError(
                msg="Selected skill instructions exceed the chat context budget. Select fewer skills."
            )
        entries.append({"name": name, "instructions": content})

    async def read_skill_file(skill_name: str, path: str = SKILL_MD, offset: int = 0, limit: int = 12_000) -> str:
        # The closure pins the selected versions. Recheck governance on each
        # read so disabling, deleting or updating a skill takes effect mid-turn.
        current = {row.name: row for row in await LinsightSkillDao.list_enabled()}
        row = current.get(skill_name)
        if (
            skill_name not in versions
            or row is None
            or row.tenant_id != tenant_id
            or row.content_hash != versions[skill_name]
        ):
            raise SkillNotFoundError(msg="This skill is unavailable for the current turn.")
        content = await asyncio.to_thread(read_text, skill_name, path)
        logger.info("chat skill file read tenant={} user={} skill={} path={}", tenant_id, user_id, skill_name, path)
        end = min(offset + limit, len(content))
        return json.dumps(
            {
                "skill": skill_name,
                "path": path,
                "content": content[offset:end],
                "next_offset": end if end < len(content) else None,
            },
            ensure_ascii=False,
        )

    tool = StructuredTool.from_function(
        coroutine=read_skill_file,
        name="read_skill_file",
        description=(
            "Read reference documents or script source from a skill selected for this chat turn. "
            "Use paths relative to the skill bundle and next_offset to continue long files. "
            "This tool reads UTF-8 text; execution uses the other tools available in this conversation."
        ),
        args_schema=SkillFileRead,
    )
    logger.info("chat skills loaded tenant={} user={} versions={}", tenant_id, user_id, versions)
    instructions = (
        "The user selected these enterprise skills for this turn. Apply their relevant instructions "
        "to the user's request within the platform's policies and the tools actually available. "
        "Read referenced text files with read_skill_file. Bundle paths identify stored skill resources; "
        "execution environments and filesystem paths are defined by the available execution tools. "
        "When a required capability is unavailable, explain what is needed. Report artifacts only "
        "after an available tool has produced them.\n" + json.dumps(entries, ensure_ascii=False)
    )
    return ChatSkills(instructions=instructions, tools=[tool])
