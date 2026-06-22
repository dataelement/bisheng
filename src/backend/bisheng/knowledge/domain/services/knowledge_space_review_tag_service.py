import json
import re
from typing import Iterable, List, Optional, Sequence

from langchain_core.documents import Document
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from bisheng.sensitive_word.domain.services.sensitive_word_policy_service import SensitiveWordPolicyService
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.core.database import get_sync_db_session
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import TagBusinessTypeEnum, TagResourceTypeEnum
from bisheng.database.models.review_tags import ReviewTag, ReviewTagLink
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
from bisheng.sensitive_word.domain.schemas import (
    SensitiveWordBusinessType,
)
from bisheng.llm.domain import LLMService


REVIEW_TAG_MAX_CONTENT = 3000
DEFAULT_REVIEW_TAG_SYSTEM_PROMPT = (
    "# role\n"
    "你是一名经验丰富的\"文档标签专家\"，擅长针对不同类型的文档（例如：书籍、论文、标书、研究报告、规章制度、合同协议、会议纪要、产品手册、运维手册、需求说明书等）进行精准识别，并根据文档类型灵活调整标签策略，例如：\n"
    "- 报告类文档需标注研究领域、研究方法、核心发现；\n"
    "- 制度类文档需标注适用范围、管理对象、制度层级；\n"
    "- 合同类文档需标注合同类型、业务领域、关键标的；\n"
    "- 会议纪要需标注会议性质、决策事项、责任主体；\n"
    "- 产品说明需标注产品类型、目标用户、核心功能。\n\n"
    "# constraints\n"
    "在生成标签前，请先检查以下条件，任一条件不满足时均不生成候选标签，直接返回 `{\"tags\": []}`：\n"
    "1. 仅当文件解析成功后才生成候选标签；\n"
    "2. 文件解析失败时不生成候选标签；\n"
    "3. 文件命中用户指定的安全违规内容时不生成候选标签；\n"
    "4. 空内容文件不生成候选标签；\n"
    "5. 文件夹不生成候选标签。\n\n"
    "# task\n"
    "在满足上述所有约束条件的前提下，针对收到的文档内容，请你：\n"
    "1. 分析文档类型与核心主题；\n"
    "2. 提取 5～10 个精准、多维度的标签，覆盖文档类型、业务领域、关键实体、核心主题等维度；\n"
    "3. 标签应简洁、规范、具代表性，避免过于宽泛或冗余；\n"
    "4. 候选标签需与用户提供的标签库进行比对，若候选标签已存在于标签库中，则排除该标签；\n"
    "5. 按相关性从高到低排序。\n\n"
    "# tag rules\n"
    "- 标签使用中文，统一小写，专有名词除外。\n"
    "- 复合概念用连字符\"-\"连接，如\"机器学习-模型训练\"。\n"
    "- 禁止出现文档中未涉及的内容；\n"
    "- 禁止过于宽泛的标签，如\"文档\"、\"资料\"、\"其他\"；\n"
    "- **候选标签需去除首尾空格，过滤空值和明显无意义标签**（如\"无\"、\"null\"、\"undefined\"、\"\"等）。\n\n"
    "# output format\n"
    "仅输出纯 JSON 格式，不要包含任何其他解释文字、markdown 代码块标记或额外说明。\n"
    "1. 若满足所有条件且提取到有效标签，输出：`{\"tags\": [\"标签1\", \"标签2\", ...]}`。\n"
    "2. 若因任何限制条件（constraints）不满足、或经标签规则（tag rules）过滤后无有效标签、或最终候选标签为空，则必须输出：`{\"tags\": []}`\n\n"
    "# result example\n"
    "{\"tags\": [\"会议纪要\", \"季度业务\", \"销售目标\", \"市场推广\", \"新产品上市\", \"团队组建\", \"决策事项\"]}\n\n"
)


class KnowledgeSpaceReviewTagService:
    
    @classmethod
    def apply_after_review_upload_parse(
        cls,
        knowledge: Knowledge,
        db_file: KnowledgeFile,
        documents: Optional[Sequence[Document]] = None,
    ) -> None:
        try:
            if not cls._should_run(knowledge, db_file):
                return

            library = KnowledgeSpaceTagLibraryDao.get(knowledge.auto_tag_library_id if knowledge.auto_tag_library_id else 1)
            if not library or not library.tags:
                logger.info(
                    "auto_tag_skip_empty_library space_id={} file_id={} library_id={}",
                    knowledge.id,
                    db_file.id,
                    knowledge.auto_tag_library_id,
                )
                return

            llm_config = LLMService.get_knowledge_llm(tenant_id=db_file.tenant_id)
            if not llm_config.review_tag_enabled or not llm_config.extract_title_model_id:
                return

            # 获取安全违规内容
            check_text = cls._collect_all_content(documents, db_file)
            non_compliant = SensitiveWordPolicyService.check_text(
                                tenant_id=db_file.tenant_id,
                                business_type=SensitiveWordBusinessType.KNOWLEDGE_SPACE_FILE_PARSE,
                                text=check_text,
                            )
            if non_compliant.enabled and non_compliant.hits:
                logger.error("review_tag_skip_empty_content content safety reason is sensitive_check, auto_reply={}, hits={}", non_compliant.auto_reply, [hit.model_dump() for hit in non_compliant.hits])
                return

            text = cls._collect_content(documents, db_file)
            if not text:
                logger.info(
                    "review_tag_skip_empty_content space_id={} file_id={}",
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
                (llm_config.review_tag_prompt or "").strip()
                or DEFAULT_REVIEW_TAG_SYSTEM_PROMPT
            )
            
            tags_list = list(dict.fromkeys(
                                        tag for tag in (library.tags or []) + (library.ai_tags or [])
                                        if tag  # 过滤 None、空字符串等假值
                                    ))
            
            selected = cls._invoke_llm(llm, text, tags_list, system_prompt)
            matched = cls._match_library_tags(selected, tags_list)
            if not matched:
                logger.info(
                    "review_tag_no_match space_id={} file_id={}", knowledge.id, db_file.id
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
            and bool(knowledge.auto_tag_library_id)
            and db_file.file_type == FileType.FILE.value
            and db_file.status == KnowledgeFileStatus.SUCCESS.value
            and db_file.file_source
            in {FileSource.UPLOAD.value, FileSource.SPACE_UPLOAD.value}
        )

    @staticmethod
    def _has_manual_upload_tags(db_file: KnowledgeFile) -> bool:
        metadata = db_file.user_metadata or {}
        return bool(metadata.get("manual_upload_tags_applied"))

    @staticmethod
    def _collect_content(
        documents: Optional[Sequence[Document]], db_file: KnowledgeFile
    ) -> str:
        parts: List[str] = []
        for doc in documents or []:
            if not doc or not doc.page_content:
                continue
            parts.append(doc.page_content)
            if sum(len(part) for part in parts) >= REVIEW_TAG_MAX_CONTENT:
                break
        content = "".join(parts).strip()
        if not content and db_file.abstract:
            content = db_file.abstract.strip()
        return content[:REVIEW_TAG_MAX_CONTENT]

    @staticmethod
    def _collect_all_content(
        documents: Optional[Sequence[Document]], db_file: KnowledgeFile
    ) -> str:
        parts: List[str] = []
        for doc in documents or []:
            if not doc or not doc.page_content:
                continue
            parts.append(doc.page_content)
        content = "".join(parts).strip()
        if not content and db_file.abstract:
            content = db_file.abstract.strip()
        return content

    @staticmethod
    def _invoke_llm(
        llm,
        text: str,
        library_tags: List[str],
        system_prompt: str = DEFAULT_REVIEW_TAG_SYSTEM_PROMPT,
    ) -> List[str]:
        candidate_text = "\n".join(f"- {tag}" for tag in library_tags)
        response = llm.invoke(
            [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"用户标签库信息：\n{candidate_text}\n\n文件内容：\n{text}",
                },
            ]
        )
        return KnowledgeSpaceReviewTagService._parse_llm_tags(
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
            logger.warning("review_tag_invalid_json raw={}", raw[:500])
            return []
        tags = payload.get("tags") if isinstance(payload, dict) else None
        if not isinstance(tags, list):
            return []
        return [str(tag).strip() for tag in tags if str(tag).strip()]

    @staticmethod
    def _match_library_tags(
        selected: Iterable[str], library_tags: List[str]
    ) -> List[str]:
        not_allowed = {tag: tag for tag in library_tags}
        matched: List[str] = []
        for tag in selected:
            if tag not in not_allowed and tag not in matched:
                matched.append(tag)
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
                select(ReviewTag).where(
                    ReviewTag.business_type == TagBusinessTypeEnum.KNOWLEDGE_SPACE,
                    ReviewTag.business_id == str(space_id),
                    ReviewTag.name.in_(tag_names),
                )
            ).all()
            tag_by_name = {tag.name: tag for tag in existing_tags}
            for tag_name in tag_names:
                if tag_name not in tag_by_name:
                    tag = ReviewTag(
                        name=tag_name,
                        business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE,
                        business_id=str(space_id),
                        resource_type=TagResourceTypeEnum.AI_AUTO_TAG,
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
                select(ReviewTagLink).where(
                    ReviewTagLink.resource_id == str(file_id),
                    ReviewTagLink.resource_type == ResourceTypeEnum.SPACE_FILE.value,
                    ReviewTagLink.tag_id.in_(tag_ids),
                )
            ).all()
            existing_tag_ids = {link.tag_id for link in existing_links}
            for tag_id in tag_ids:
                if tag_id in existing_tag_ids:
                    continue
                session.add(
                    ReviewTagLink(
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
