"""Generate AI-powered file alias names using an LLM."""

import json
import os
import re

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.core.prompts.manager import get_prompt_manager_sync
from bisheng.knowledge.domain.services.file_title_extractor import sanitize_file_name
from bisheng.llm.domain.services.llm import LLMService


class FileAliasNameGeneratorService:
    """Generate a display alias for a knowledge file via LLM.

    The service reads the file's type, current name, code-extracted title and a
    small text snippet, sends them to a configured LLM, and expects a JSON
    response shaped like:

        {"status": "success|no_title", "new_file_name": "string|null"}

    On any failure (missing model, LLM error, invalid JSON, empty result), the
    service returns ``None`` so the caller can fall back to ``file_name``.
    """

    # Extensions for which reading a raw text snippet is safe and useful.
    _TEXT_LIKE_EXTS: frozenset[str] = frozenset(
        {
            "txt",
            "md",
            "html",
            "csv",
            "json",
            "py",
            "js",
            "java",
            "go",
            "rs",
            "c",
            "cpp",
            "h",
            "ts",
            "jsx",
            "tsx",
            "yaml",
            "yml",
            "xml",
            "log",
        }
    )

    _JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)

    @classmethod
    def generate_alias_name(
        cls,
        file_path: str,
        file_name: str,
        extracted_title: str,
        invoke_user_id: int,
        tenant_id: int | None = None,
    ) -> str | None:
        """Return an LLM-generated alias (with original extension) or ``None``."""
        try:
            knowledge_llm = LLMService.get_knowledge_llm(tenant_id=tenant_id)
            if not knowledge_llm or not knowledge_llm.file_alias_model_id:
                logger.debug(
                    "file_alias_model_id not configured tenant_id={}",
                    tenant_id,
                )
                return None

            llm = LLMService.get_bisheng_llm_sync(
                model_id=knowledge_llm.file_alias_model_id,
                app_id=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
                app_name=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
                app_type=ApplicationTypeEnum.KNOWLEDGE_BASE,
                user_id=invoke_user_id,
                temperature=0,
            )

            raw_snippet = cls._read_text_snippet(file_path)
            file_type = cls._extract_file_type(file_name)

            prompt_manager = get_prompt_manager_sync()
            prompt_obj = prompt_manager.render_prompt(
                "gen_title",
                "knowledge_file_alias",
                file_type=file_type,
                file_name=file_name,
                extracted_title=extracted_title or "",
                raw_content_snippet=raw_snippet,
            )

            messages = [
                SystemMessage(content=prompt_obj.prompt.system),
                HumanMessage(content=prompt_obj.prompt.user),
            ]
            response = llm.invoke(messages)
            content = response.content.strip() if response.content else ""
            if not content:
                logger.warning("LLM returned empty alias generation response")
                return None

            raw_alias = cls._parse_llm_json(content)
            if not raw_alias:
                return None

            return cls._normalize_alias_name(raw_alias, file_name)
        except Exception as e:
            # Alias generation is best-effort and must never block parsing.
            logger.warning("file alias generation failed: {}", e)
            return None

    @classmethod
    def _extract_file_type(cls, file_name: str) -> str:
        """Return the lowercase file extension without the leading dot."""
        return os.path.splitext(file_name)[1].lower().lstrip(".") or "unknown"

    @classmethod
    def _read_text_snippet(cls, file_path: str, max_chars: int = 800) -> str:
        """Read a short text snippet for text-like files; return empty otherwise."""
        ext = cls._extract_file_type(file_path)
        if ext not in cls._TEXT_LIKE_EXTS:
            return ""
        try:
            with open(file_path, "rb") as f:
                raw = f.read(max_chars * 4)
            text = raw.decode("utf-8", errors="ignore")
            return text[:max_chars].strip()
        except Exception as e:
            logger.debug("failed to read text snippet: {}", e)
            return ""

    @classmethod
    def _parse_llm_json(cls, content: str) -> str | None:
        """Parse the LLM JSON response and return the raw new_file_name."""
        # Try direct JSON parsing first.
        try:
            data = json.loads(content)
            return cls._extract_alias_from_dict(data)
        except json.JSONDecodeError:
            pass

        # Fall back to extracting the first JSON object with a regex.
        match = cls._JSON_BLOCK_RE.search(content)
        if match:
            try:
                data = json.loads(match.group(0))
                return cls._extract_alias_from_dict(data)
            except json.JSONDecodeError:
                pass

        logger.warning("failed to parse alias JSON from LLM response: {}", content)
        return None

    @classmethod
    def _extract_alias_from_dict(cls, data: dict) -> str | None:
        """Validate the parsed JSON dict and return the new file name."""
        if data.get("status") != "success":
            logger.debug("LLM returned status=%s", data.get("status"))
            return None
        new_name = data.get("new_file_name")
        if not isinstance(new_name, str) or not new_name.strip():
            return None
        return new_name.strip()

    @classmethod
    def _normalize_alias_name(cls, raw_alias: str, original_file_name: str) -> str | None:
        """Sanitize the LLM output and force the original file extension."""
        original_ext = os.path.splitext(original_file_name)[1].lower()
        alias_base, alias_ext = os.path.splitext(raw_alias)
        alias_base = alias_base.strip()
        if not alias_base:
            return None

        # Always keep the original extension for consistency with file_name.
        ext = original_ext if original_ext else alias_ext.lower()
        max_base_length = 200 - len(ext)
        safe_base = sanitize_file_name(alias_base, max_length=max(max_base_length, 1))
        if not safe_base:
            return None
        return f"{safe_base}{ext}"
