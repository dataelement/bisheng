import json
import re
from typing import Iterable, List, Optional, Sequence

from langchain_core.documents import Document
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.core.database import get_sync_db_session
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import Tag, TagBusinessTypeEnum, TagLink
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import (
    FileSource,
    FileType,
    KnowledgeFile,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.models.knowledge_space_tag_library import (
    KnowledgeSpaceTagLibraryDao,
)
from bisheng.llm.domain import LLMService


AUTO_TAG_MAX_CONTENT = 7000
AUTO_TAG_MAX_RESULT = 5
DEFAULT_AUTO_TAG_SYSTEM_PROMPT = (
    "你是知识空间文件自动标签分类器。只能从候选标签中选择最相关的标签，"
    "最多返回 5 个。只输出严格 JSON，格式固定为 {\"tags\": [\"标签名\"]}。"
)


class KnowledgeSpaceAutoTagService:
    @classmethod
    def apply_after_upload_parse(
        cls,
        knowledge: Knowledge,
        db_file: KnowledgeFile,
        documents: Optional[Sequence[Document]] = None,
    ) -> None:
        try:
            if not cls._should_run(knowledge, db_file):
                return

            library = KnowledgeSpaceTagLibraryDao.get(knowledge.auto_tag_library_id)
            if not library or not library.tags:
                logger.info(
                    "auto_tag_skip_empty_library space_id={} file_id={} library_id={}",
                    knowledge.id,
                    db_file.id,
                    knowledge.auto_tag_library_id,
                )
                return

            llm_config = LLMService.get_knowledge_llm(tenant_id=db_file.tenant_id)
            if not llm_config.auto_tag_enabled or not llm_config.extract_title_model_id:
                return

            text = cls._collect_content(documents, db_file)
            if not text:
                logger.info(
                    "auto_tag_skip_empty_content space_id={} file_id={}",
                    knowledge.id,
                    db_file.id,
                )
                return

            llm = LLMService.get_bisheng_llm_sync(
                model_id=llm_config.extract_title_model_id,
                app_id=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
                app_name=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
                app_type=ApplicationTypeEnum.KNOWLEDGE_BASE,
                user_id=db_file.user_id,
            )
            system_prompt = (
                (llm_config.auto_tag_prompt or "").strip()
                or DEFAULT_AUTO_TAG_SYSTEM_PROMPT
            )
            selected = cls._invoke_llm(llm, text, library.tags or [], system_prompt)
            matched = cls._match_library_tags(selected, library.tags or [])
            if not matched:
                logger.info(
                    "auto_tag_no_match space_id={} file_id={}", knowledge.id, db_file.id
                )
                return

            cls._append_file_tags(
                space_id=knowledge.id,
                file_id=db_file.id,
                tag_names=matched,
                user_id=db_file.user_id or 0,
                tenant_id=db_file.tenant_id,
            )
            logger.info(
                "auto_tag_success space_id={} file_id={} tags={}",
                knowledge.id,
                db_file.id,
                matched,
            )
        except Exception:
            logger.exception(
                "auto_tag_failed space_id={} file_id={}",
                getattr(knowledge, "id", None),
                getattr(db_file, "id", None),
            )

    @staticmethod
    def _should_run(knowledge: Knowledge, db_file: KnowledgeFile) -> bool:
        return (
            knowledge
            and db_file
            and knowledge.type == KnowledgeTypeEnum.SPACE.value
            and knowledge.auto_tag_enabled
            and bool(knowledge.auto_tag_library_id)
            and db_file.file_type == FileType.FILE.value
            and db_file.status == KnowledgeFileStatus.SUCCESS.value
            and db_file.file_source
            in {FileSource.UPLOAD.value, FileSource.SPACE_UPLOAD.value}
        )

    @staticmethod
    def _collect_content(
        documents: Optional[Sequence[Document]], db_file: KnowledgeFile
    ) -> str:
        parts: List[str] = []
        for doc in documents or []:
            if not doc or not doc.page_content:
                continue
            parts.append(doc.page_content)
            if sum(len(part) for part in parts) >= AUTO_TAG_MAX_CONTENT:
                break
        content = "".join(parts).strip()
        if not content and db_file.abstract:
            content = db_file.abstract.strip()
        return content[:AUTO_TAG_MAX_CONTENT]

    @staticmethod
    def _invoke_llm(
        llm,
        text: str,
        library_tags: List[str],
        system_prompt: str = DEFAULT_AUTO_TAG_SYSTEM_PROMPT,
    ) -> List[str]:
        candidate_text = "\n".join(f"- {tag}" for tag in library_tags)
        response = llm.invoke(
            [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"候选标签：\n{candidate_text}\n\n文件内容：\n{text}",
                },
            ]
        )
        return KnowledgeSpaceAutoTagService._parse_llm_tags(
            getattr(response, "content", "") or ""
        )

    @staticmethod
    def _parse_llm_tags(raw: str) -> List[str]:
        text = raw.strip()
        if not text:
            return []
        fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
        if fenced:
            text = fenced.group(1).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("auto_tag_invalid_json raw={}", raw[:500])
            return []
        tags = payload.get("tags") if isinstance(payload, dict) else None
        if not isinstance(tags, list):
            return []
        return [str(tag).strip() for tag in tags if str(tag).strip()]

    @staticmethod
    def _match_library_tags(
        selected: Iterable[str], library_tags: List[str]
    ) -> List[str]:
        allowed = {tag: tag for tag in library_tags}
        matched: List[str] = []
        for tag in selected:
            if tag in allowed and tag not in matched:
                matched.append(allowed[tag])
            if len(matched) >= AUTO_TAG_MAX_RESULT:
                break
        return matched

    @staticmethod
    def _append_file_tags(
        space_id: int,
        file_id: int,
        tag_names: List[str],
        user_id: int,
        tenant_id: Optional[int],
    ) -> None:
        if not tag_names:
            return
        with get_sync_db_session() as session:
            existing_tags = session.exec(
                select(Tag).where(
                    Tag.business_type == TagBusinessTypeEnum.KNOWLEDGE_SPACE,
                    Tag.business_id == str(space_id),
                    Tag.name.in_(tag_names),
                )
            ).all()
            tag_by_name = {tag.name: tag for tag in existing_tags}
            for tag_name in tag_names:
                if tag_name not in tag_by_name:
                    tag = Tag(
                        name=tag_name,
                        business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE,
                        business_id=str(space_id),
                        user_id=user_id,
                        tenant_id=tenant_id,
                    )
                    session.add(tag)
                    session.flush()
                    tag_by_name[tag_name] = tag

            tag_ids = [
                tag_by_name[name].id for name in tag_names if tag_by_name.get(name)
            ]
            existing_links = session.exec(
                select(TagLink).where(
                    TagLink.resource_id == str(file_id),
                    TagLink.resource_type == ResourceTypeEnum.SPACE_FILE.value,
                    TagLink.tag_id.in_(tag_ids),
                )
            ).all()
            existing_tag_ids = {link.tag_id for link in existing_links}
            for tag_id in tag_ids:
                if tag_id in existing_tag_ids:
                    continue
                session.add(
                    TagLink(
                        tag_id=tag_id,
                        resource_id=str(file_id),
                        resource_type=ResourceTypeEnum.SPACE_FILE.value,
                        user_id=user_id,
                        tenant_id=tenant_id,
                    )
                )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                logger.info(
                    "auto_tag_duplicate_link_ignored space_id={} file_id={}",
                    space_id,
                    file_id,
                )
