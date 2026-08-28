"""Generate AI-powered file alias names using an LLM."""
# ruff: noqa: RUF001

import json
import os
import re

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.core.prompts.manager import get_prompt_manager_sync
from bisheng.knowledge.domain.services.file_title_extractor import sanitize_file_name
from bisheng.llm.domain.services.llm import LLMService


def _halfwidth(text: str) -> str:
    """Convert common full-width alphanumerics to half-width for comparison."""
    table = str.maketrans(
        "０１２３４５６７８９ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ",
        "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
    )
    return text.translate(table)


def _normalize_name_for_compare(name: str) -> str:
    """Drop spaces, brackets, separators and case for structural comparison."""
    if not name:
        return ""
    name = _halfwidth(name).lower()
    name = re.sub(r"[\s\-_《》（）()\[\]【】]", "", name)
    return name


def _extract_protected_info(name: str) -> list[str]:
    """Return normalized standard numbers, dates and versions present in ``name``."""
    protected: list[str] = []
    search_name = name.replace("_", "-")
    for match in re.finditer(
        r"[A-Za-z]{1,6}(?:/[A-Za-z]{1,6})?\s*\d+(?:\.\d+)?\s*[—–\-]\s*\d{2,4}",
        search_name,
    ):
        protected.append(_normalize_name_for_compare(match.group(0)))
    for match in re.finditer(r"\d{4}[年/\-\.]\d{1,2}[月/\-\.]?\d{0,2}日?", search_name):
        protected.append(_normalize_name_for_compare(match.group(0)))
    for match in re.finditer(r"(?i)v\d+(?:\.\d+)*|第\s*\d+\s*版|版本\s*\d+", search_name):
        protected.append(_normalize_name_for_compare(match.group(0)))
    # Keep structural markers such as "第1部分" and "1号高炉".
    for match in re.finditer(r"第\s*\d+\s*(?:部分|章|节|篇|册|卷)", search_name):
        protected.append(_normalize_name_for_compare(match.group(0)))
    for match in re.finditer(r"\d+\s*号\s*(?:设备|高炉|线|机组)", search_name):
        protected.append(_normalize_name_for_compare(match.group(0)))
    return [p for p in protected if p]


def _extract_bracket_content(name: str) -> list[str]:
    """Return normalized contents of Chinese book-title and parenthesis pairs."""
    contents: list[str] = []
    for left, right in (("《", "》"), ("（", "）"), ("(", ")")):
        pattern = re.compile(re.escape(left) + r"(.*?)" + re.escape(right))
        for match in pattern.finditer(name):
            contents.append(_normalize_name_for_compare(match.group(1)))
    return [c for c in contents if c]


_AUXILIARY_PREFIX_RE = re.compile(
    r"^(?:"
    r"附件[一二三四五六七八九十0-9]*[：:.、\-—\s]+"
    r"|[（(]\d+[)）]\s*"
    r"|\d{1,2}[.．、：:]\s+"
    r"|\d{1,2}\s+"
    r"|[一二三四五六七八九十]+[、.．]\s+"
    r")+",
    re.UNICODE,
)


def _remove_auxiliary_prefix(name: str) -> str:
    """Remove leading auxiliary text such as 'Attachment 1:' without harming real titles."""
    cleaned = _AUXILIARY_PREFIX_RE.sub("", name)
    return cleaned.strip() if cleaned.strip() else name.strip()


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
                knowledge_llm.file_alias_model_id if knowledge_llm and knowledge_llm.file_alias_model_id else None
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
        """Sanitize the LLM output, enforce deterministic rules and force the original extension."""
        original_ext = os.path.splitext(original_file_name)[1].lower()
        alias_base, alias_ext = os.path.splitext(raw_alias)
        alias_base = alias_base.strip()
        logger.info(
            "alias normalize raw_alias=%s original_file_name=%s alias_base=%s",
            raw_alias,
            original_file_name,
            alias_base,
        )
        if not alias_base:
            logger.info("alias normalize skipped, empty base")
            return None

        original_base = os.path.splitext(original_file_name)[0]

        # 1. Deterministic removal of leading auxiliary prefixes.
        cleaned_base = _remove_auxiliary_prefix(alias_base)

        normalized_cleaned = _normalize_name_for_compare(cleaned_base)

        # 2. Any standard number / date / version from the original must be preserved.
        for token in _extract_protected_info(original_base):
            if token and token not in normalized_cleaned:
                logger.info(
                    "alias normalize dropped, protected info missing original=%s alias=%s missing=%s",
                    original_file_name,
                    cleaned_base,
                    token,
                )
                return None

        # 3. Bracketed content from the original must not be silently dropped.
        for content in _extract_bracket_content(original_base):
            if not content or len(content) <= 1 or re.fullmatch(r"\d+", content):
                continue
            if content not in normalized_cleaned:
                logger.info(
                    "alias normalize dropped, bracket content missing original=%s alias=%s missing=%s",
                    original_file_name,
                    cleaned_base,
                    content,
                )
                return None

        # 4. Do not suggest a rename that is only a formatting difference.
        if _normalize_name_for_compare(original_base) == normalized_cleaned:
            logger.info(
                "alias normalize dropped, only formatting difference original=%s alias=%s",
                original_file_name,
                cleaned_base,
            )
            return None

        # 5. Normalize separators: never use underscores, use hyphen instead.
        ext = original_ext if original_ext else alias_ext.lower()
        max_base_length = max(200 - len(ext), 1)
        safe_base = sanitize_file_name(cleaned_base, max_length=max_base_length, use_hyphen=True)
        if not safe_base:
            return None
        safe_base = re.sub(r"_+", "-", safe_base)
        safe_base = re.sub(r"-+", "-", safe_base).strip("-")
        if not safe_base:
            return None

        result = f"{safe_base}{ext}"
        logger.info("alias normalize result=%s", result)
        return result
