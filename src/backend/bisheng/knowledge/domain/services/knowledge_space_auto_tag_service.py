import json
import re
from collections.abc import Iterable, Sequence

from langchain_core.documents import Document
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.core.database import get_sync_db_session
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import Tag, TagBusinessTypeEnum, TagLink, TagResourceTypeEnum
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
from bisheng.knowledge.domain.models.knowledge_tag_library_link import (
    KnowledgeTagLibraryLinkDao,
)
from bisheng.knowledge.domain.services.tag_library_tag_service import (
    TagLibraryTagService,
)
from bisheng.llm.domain import LLMService

AUTO_TAG_MAX_CONTENT = 3000
AUTO_TAG_MAX_RESULT = 5
DEFAULT_AUTO_TAG_SYSTEM_PROMPT = (
    "你是文件自动标签分类器。只能从候选标签中选择最相关的标签，最多返回 5 个标签。\n"
    '输出格要求严格遵循 JSON 格式： {"tags": ["标签名"]}。'
)


class KnowledgeSpaceAutoTagService:
    @classmethod
    def apply_after_upload_parse(
        cls,
        knowledge: Knowledge,
        db_file: KnowledgeFile,
        documents: Sequence[Document] | None = None,
    ) -> None:
        try:
            if not cls._should_run(knowledge, db_file):
                return

            library_ids = cls._resolve_library_ids(knowledge)
            manual_tags, ai_tags = cls._collect_library_tags(library_ids)
            if not manual_tags and not ai_tags:
                logger.info(
                    "auto_tag_skip_empty_library space_id={} file_id={} library_ids={}",
                    knowledge.id,
                    db_file.id,
                    library_ids,
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
            system_prompt = (llm_config.auto_tag_prompt or "").strip() or DEFAULT_AUTO_TAG_SYSTEM_PROMPT

            tags_list = list(dict.fromkeys(tag for tag in manual_tags + ai_tags if tag))
            selected = cls._invoke_llm(llm, text, tags_list, system_prompt)
            matched, ai_matched = cls._match_library_tags(selected, manual_tags, ai_tags)
            if not matched:
                logger.info("auto_tag_no_match space_id={} file_id={}", knowledge.id, db_file.id)
                return
            else:
                cls._append_file_tags(
                    space_id=knowledge.id,
                    file_id=db_file.id,
                    tag_names=matched,
                    user_id=db_file.user_id or 0,
                    tenant_id=db_file.tenant_id,
                    resource_type=TagResourceTypeEnum.SYSTEM_TAG,
                )
            if not ai_matched:
                logger.info("auto_tag_no_match space_id={} file_id={}", knowledge.id, db_file.id)
                return
            else:
                cls._append_file_tags(
                    space_id=knowledge.id,
                    file_id=db_file.id,
                    tag_names=ai_matched,
                    user_id=db_file.user_id or 0,
                    tenant_id=db_file.tenant_id,
                    resource_type=TagResourceTypeEnum.AI_AUTO_TAG,
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

    @classmethod
    def _resolve_library_ids(cls, knowledge: Knowledge) -> list[int]:
        library_ids = KnowledgeTagLibraryLinkDao.list_library_ids_by_knowledge(int(knowledge.id))
        if library_ids:
            return library_ids
        if knowledge.auto_tag_library_id:
            return [int(knowledge.auto_tag_library_id)]
        return [1]

    @classmethod
    def _collect_library_tags(cls, library_ids: list[int]) -> tuple[list[str], list[str]]:
        manual_tags: list[str] = []
        ai_tags: list[str] = []
        for library_id in library_ids:
            system, manual, ai = TagLibraryTagService.list_tag_names_sync(library_id)
            if not system and not manual and not ai:
                library = KnowledgeSpaceTagLibraryDao.get(library_id)
                if library:
                    system = list(library.tags or [])
                    ai = list(library.ai_tags or [])
            non_ai = TagLibraryTagService.non_ai_tag_names(system, manual)
            for tag in non_ai:
                if tag not in manual_tags:
                    manual_tags.append(tag)
            for tag in ai:
                if tag not in ai_tags:
                    ai_tags.append(tag)
        return manual_tags, ai_tags

    @staticmethod
    def _should_run(knowledge: Knowledge, db_file: KnowledgeFile) -> bool:
        has_libraries = bool(
            KnowledgeTagLibraryLinkDao.list_library_ids_by_knowledge(int(knowledge.id)) or knowledge.auto_tag_library_id
        )
        return (
            knowledge
            and db_file
            and knowledge.type == KnowledgeTypeEnum.SPACE.value
            and knowledge.auto_tag_enabled
            and has_libraries
            and db_file.file_type == FileType.FILE.value
            and db_file.status == KnowledgeFileStatus.SUCCESS.value
            and db_file.file_source in {FileSource.UPLOAD.value, FileSource.SPACE_UPLOAD.value}
            and not KnowledgeSpaceAutoTagService._has_manual_upload_tags(db_file)
        )

    @staticmethod
    def _has_manual_upload_tags(db_file: KnowledgeFile) -> bool:
        metadata = db_file.user_metadata or {}
        return bool(metadata.get("manual_upload_tags_applied"))

    @staticmethod
    def _collect_content(documents: Sequence[Document] | None, db_file: KnowledgeFile) -> str:
        parts: list[str] = []
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
        library_tags: list[str],
        system_prompt: str = DEFAULT_AUTO_TAG_SYSTEM_PROMPT,
    ) -> list[str]:
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
        return KnowledgeSpaceAutoTagService._parse_llm_tags(getattr(response, "content", "") or "")

    @staticmethod
    def _parse_llm_tags(raw: str) -> list[str]:
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
        selected: Iterable[str], library_tags: list[str], ai_tags: list[str]
    ) -> tuple[list[str], list[str]]:
        allowed = {tag: tag for tag in library_tags}
        matched: list[str] = []
        for tag in selected:
            if tag in allowed and tag not in matched:
                matched.append(allowed[tag])
            if len(matched) >= AUTO_TAG_MAX_RESULT:
                break
        ai_matched: list[str] = []
        count = len(matched)
        if count < AUTO_TAG_MAX_RESULT:
            ai_allowed = {tag: tag for tag in ai_tags}
            for tag in selected:
                if tag in ai_allowed and tag not in ai_matched and tag not in matched:
                    ai_matched.append(ai_allowed[tag])
                if count + len(ai_matched) >= AUTO_TAG_MAX_RESULT:
                    break
        return matched, ai_matched

    @staticmethod
    def _append_file_tags(
        space_id: int,
        file_id: int,
        tag_names: list[str],
        user_id: int,
        tenant_id: int | None,
        resource_type: TagResourceTypeEnum,
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
                        resource_type=resource_type,
                        user_id=user_id,
                        tenant_id=tenant_id,
                    )
                    session.add(tag)
                    session.flush()
                    tag_by_name[tag_name] = tag

            tag_ids = [tag_by_name[name].id for name in tag_names if tag_by_name.get(name)]
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
