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

    # Extract a JSON object from free-form LLM output. Non-greedy so it stops
    # at the first closing brace and avoids swallowing trailing explanation text.
    _JSON_BLOCK_RE = re.compile(r"\{.*?\}", re.DOTALL)
    # Extract JSON that is wrapped in a markdown code block.
    _CODE_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

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
            file_alias_model_id = (
                knowledge_llm.file_alias_model_id
                if knowledge_llm and knowledge_llm.file_alias_model_id
                else None
            )
            # Fallback to the extract-title model when no alias model is configured.
            if not file_alias_model_id and knowledge_llm and knowledge_llm.extract_title_model_id:
                file_alias_model_id = knowledge_llm.extract_title_model_id
            logger.info(
                "alias generation config tenant_id={} file_alias_model_id={} extract_title_model_id={} resolved_model_id={}",
                tenant_id,
                getattr(knowledge_llm, "file_alias_model_id", None) if knowledge_llm else None,
                getattr(knowledge_llm, "extract_title_model_id", None) if knowledge_llm else None,
                file_alias_model_id,
            )
            if not file_alias_model_id:
                logger.warning(
                    "file_alias_model_id not configured and no extract_title_model_id fallback tenant_id={}",
                    tenant_id,
                )
                return None

            llm = LLMService.get_bisheng_llm_sync(
                model_id=file_alias_model_id,
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
            logger.info(
                "alias generation llm response file_name={} content={}",
                file_name,
                content,
            )
            if not content:
                logger.warning("LLM returned empty alias generation response")
                return None

            raw_alias = cls._parse_llm_json(content)
            logger.info(
                "alias generation parsed raw_alias={} file_name={}",
                raw_alias,
                file_name,
            )
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
        # Strategy: markdown code block -> direct JSON -> first JSON object in text.
        candidates = []

        code_match = cls._CODE_BLOCK_RE.search(content)
        if code_match:
            candidates.append(code_match.group(1).strip())

        candidates.append(content.strip())

        json_match = cls._JSON_BLOCK_RE.search(content)
        if json_match:
            candidates.append(json_match.group(0))

        for candidate in candidates:
            if not candidate:
                continue
            try:
                data = json.loads(candidate)
                alias = cls._extract_alias_from_dict(data)
                if alias is not None:
                    return alias
            except json.JSONDecodeError:
                continue

        logger.warning("failed to parse alias JSON from LLM response: {}", content)
        return None

    @classmethod
    def _extract_alias_from_dict(cls, data: dict) -> str | None:
        """Validate the parsed JSON dict and return the new file name."""
        status = data.get("status")
        new_name = data.get("new_file_name")
        logger.info("alias extract from dict status=%s new_file_name=%s", status, new_name)
        if status != "success":
            logger.info("LLM returned non-success status=%s", status)
            return None
        if not isinstance(new_name, str) or not new_name.strip():
            logger.info("LLM returned empty or invalid new_file_name")
            return None
        return new_name.strip()

    @classmethod
    def _normalize_alias_name(cls, raw_alias: str, original_file_name: str) -> str | None:
        """Sanitize the LLM output and force the original file extension."""
        original_ext = os.path.splitext(original_file_name)[1].lower()
        alias_base, alias_ext = os.path.splitext(raw_alias)
        alias_base = alias_base.strip()
        logger.info(
            "alias normalize raw_alias=%s original_ext=%s alias_base=%s",
            raw_alias,
            original_ext,
            alias_base,
        )
        if not alias_base:
            logger.info("alias normalize skipped, empty base")
            return None

        # Always keep the original extension for consistency with file_name.
        ext = original_ext if original_ext else alias_ext.lower()
        max_base_length = 200 - len(ext)
        safe_base = sanitize_file_name(alias_base, max_length=max(max_base_length, 1))
        result = f"{safe_base}{ext}" if safe_base else None
        logger.info("alias normalize result=%s", result)
        return result
