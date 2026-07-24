import json
import re
from collections.abc import Iterable, Sequence

from langchain_core.documents import Document
from loguru import logger

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.database.models.tag import TagResourceTypeEnum
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import (
    FileSource,
    FileType,
    KnowledgeFile,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.services.knowledge_space_auto_tag_service import (
    AUTO_TAG_MAX_AI_TAGS_PER_FILE,
    KnowledgeSpaceAutoTagService,
)
from bisheng.knowledge.domain.services.tag_library_tag_service import (
    LINK_B_PROMPT_CATALOG_LIMIT,
    TagLibraryTagService,
)
from bisheng.llm.domain import LLMService
from bisheng.sensitive_word.domain.schemas import (
    SensitiveWordBusinessType,
)
from bisheng.sensitive_word.domain.services.sensitive_word_policy_service import SensitiveWordPolicyService

REVIEW_TAG_MAX_CONTENT = 3000
DEFAULT_REVIEW_TAG_SYSTEM_PROMPT = (
    "# role\n"
    '你是一名经验丰富的"文档标签专家"，擅长针对不同类型的文档（例如：书籍、论文、标书、研究报告、规章制度、合同协议、会议纪要、产品手册、运维手册、需求说明书等）进行精准识别，并根据文档类型灵活调整标签策略，例如：\n'
    "- 报告类文档需标注研究领域、研究方法、核心发现；\n"
    "- 制度类文档需标注适用范围、管理对象、制度层级；\n"
    "- 合同类文档需标注合同类型、业务领域、关键标的；\n"
    "- 会议纪要需标注会议性质、决策事项、责任主体；\n"
    "- 产品说明需标注产品类型、目标用户、核心功能。\n\n"
    "# constraints\n"
    '在生成标签前，请先检查以下条件，任一条件不满足时均不生成候选标签，直接返回 `{"tags": []}`：\n'
    "1. 仅当文件解析成功后才生成候选标签；\n"
    "2. 文件解析失败时不生成候选标签；\n"
    "3. 文件命中用户指定的安全违规内容时不生成候选标签；\n"
    "4. 空内容文件不生成候选标签；\n"
    "5. 文件夹不生成候选标签。\n\n"
    "# task\n"
    "在满足上述所有约束条件的前提下，结合文件的业务域、文件分类与文档内容，请你：\n"
    "1. 分析文档类型与核心主题；\n"
    "2. 提取最多 5 个精准、多维度的标签，覆盖文档类型、业务领域、关键实体、核心主题等维度；\n"
    "3. 标签应简洁、规范、具代表性，避免过于宽泛或冗余；\n"
    "4. 输出标签前，必须与「已入库标签」「待审核标签」比对：\n"
    "   - 与已入库标签**名称完全一致**（仅空格/全半角差异）：必须复用已入库标签的**确切名称**；\n"
    "   - 与待审核标签语义相同或接近：必须复用待审核标签的**确切名称**（不得创建近似新名）；\n"
    "   - 已入库标签优先于待审核标签；\n"
    "   - 仅当与已入库不完全一致、且与待审核也不构成相同/接近语义时，才可输出新标签名。\n"
    "5. 按相关性从高到低排序。\n\n"
    "# tag rules\n"
    "- 标签使用中文，统一小写，专有名词除外。\n"
    '- 复合概念用连字符"-"连接，如"机器学习-模型训练"。\n'
    "- 禁止出现文档中未涉及的内容；\n"
    '- 禁止过于宽泛的标签，如"文档"、"资料"、"其他"；\n'
    '- **候选标签需去除首尾空格，过滤空值和明显无意义标签**（如"无"、"null"、"undefined"、""等）。\n'
    "- 已入库标签必须名称完全一致才能复用；待审核标签不得输出仅差少量用字的变体名称。\n\n"
    "# output format\n"
    "仅输出纯 JSON 格式，不要包含任何其他解释文字、markdown 代码块标记或额外说明。\n"
    '1. 若满足所有条件且提取到有效标签，输出：`{"tags": ["标签1", "标签2", ...]}`。\n'
    '2. 若因任何限制条件（constraints）不满足、或经标签规则（tag rules）过滤后无有效标签、或最终候选标签为空，则必须输出：`{"tags": []}`\n\n'
    "# result example\n"
    '{"tags": ["会议纪要", "季度业务", "销售目标", "市场推广", "新产品上市", "团队组建", "决策事项"]}\n\n'
)
REVIEW_TAG_CONTEXT_INSTRUCTION = (
    "请结合上述业务域、文件分类与文件内容生成标签。"
    "优先复用用户消息中「已入库标签」「待审核标签」列表里的确切名称；"
    "仅当无合适复用对象时再输出新标签名。"
)


class KnowledgeSpaceReviewTagService:
    @classmethod
    def apply_after_review_upload_parse(
        cls,
        knowledge: Knowledge,
        db_file: KnowledgeFile,
        documents: Sequence[Document] | None = None,
    ) -> None:
        try:
            if not cls._should_run(knowledge, db_file):
                return

            library_ids = KnowledgeSpaceAutoTagService._resolve_library_ids(knowledge)
            manual_tags, ai_tags = KnowledgeSpaceAutoTagService._collect_library_tags(library_ids)
            if not manual_tags and not ai_tags:
                logger.info(
                    "auto_tag_skip_empty_library space_id={} file_id={} library_ids={}",
                    knowledge.id,
                    db_file.id,
                    library_ids,
                )
                return

            llm_config = LLMService.get_knowledge_llm(tenant_id=db_file.tenant_id)
            if not llm_config.review_tag_enabled or not llm_config.extract_title_model_id:
                return

            check_text = cls._collect_all_content(documents, db_file)
            non_compliant = SensitiveWordPolicyService.check_text(
                tenant_id=db_file.tenant_id,
                business_type=SensitiveWordBusinessType.KNOWLEDGE_SPACE_FILE_PARSE,
                text=check_text,
            )
            if non_compliant.enabled and non_compliant.hits:
                logger.error(
                    "review_tag_skip_empty_content content safety reason is sensitive_check, auto_reply={}, hits={}",
                    non_compliant.auto_reply,
                    [hit.model_dump() for hit in non_compliant.hits],
                )
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
                temperature=0,
            )
            system_prompt = KnowledgeSpaceAutoTagService._build_file_context_system_prompt(
                (llm_config.review_tag_prompt or "").strip() or DEFAULT_REVIEW_TAG_SYSTEM_PROMPT,
                db_file,
                REVIEW_TAG_CONTEXT_INSTRUCTION,
            )

            logger.info(
                "review_tag_system_prompt space_id={} file_id={} system_prompt={}",
                knowledge.id,
                db_file.id,
                system_prompt,
            )
            tags_list = list(dict.fromkeys(tag for tag in manual_tags + ai_tags if tag))

            catalog = TagLibraryTagService.load_link_b_tenant_catalog_sync(
                db_file.tenant_id,
                TagResourceTypeEnum.AI_AUTO_TAG,
            )
            library_by_key = catalog.library_by_key
            pending_catalog = catalog.pending_catalog
            tenant_library_names = catalog.library_names[:LINK_B_PROMPT_CATALOG_LIMIT]
            tenant_pending_names = [(tag.name or "").strip() for tag in pending_catalog if (tag.name or "").strip()][
                :LINK_B_PROMPT_CATALOG_LIMIT
            ]

            selected = cls._invoke_llm(
                llm,
                text,
                tags_list,
                system_prompt,
                tenant_library_names=tenant_library_names,
                tenant_pending_names=tenant_pending_names,
            )
            if not selected:
                logger.info(
                    "review_tag_no_llm_output space_id={} file_id={}",
                    knowledge.id,
                    db_file.id,
                )
                return

            resolved = TagLibraryTagService.resolve_link_b_tag_candidates_sync(
                tenant_id=db_file.tenant_id,
                candidates=selected,
                resource_type=TagResourceTypeEnum.AI_AUTO_TAG,
                library_by_key=library_by_key,
                pending_catalog=pending_catalog,
            )
            if not resolved.entries:
                logger.info(
                    "review_tag_no_resolved space_id={} file_id={} selected_count={}",
                    knowledge.id,
                    db_file.id,
                    len(selected),
                )
                return

            capped_names = KnowledgeSpaceAutoTagService._cap_ai_tags_for_file(
                db_file.id,
                [entry.canonical_name for entry in resolved.entries],
            )
            if not capped_names:
                logger.info(
                    "review_tag_cap_reached space_id={} file_id={}",
                    knowledge.id,
                    db_file.id,
                )
                return

            target_by_name = {entry.canonical_name: entry.target for entry in resolved.entries}
            approved_names = [name for name in capped_names if target_by_name.get(name) == "approved"]
            pending_names = [name for name in capped_names if target_by_name.get(name) == "pending"]

            if approved_names:
                TagLibraryTagService.append_file_library_tags_sync(
                    space_id=knowledge.id,
                    file_id=db_file.id,
                    tag_names=approved_names,
                    user_id=db_file.user_id or 0,
                    tenant_id=db_file.tenant_id,
                    resource_type=TagResourceTypeEnum.AI_AUTO_TAG,
                )
            if pending_names:
                TagLibraryTagService.append_file_library_review_tags_sync(
                    space_id=knowledge.id,
                    file_id=db_file.id,
                    tag_names=pending_names,
                    user_id=db_file.user_id or 0,
                    tenant_id=db_file.tenant_id,
                    resource_type=TagResourceTypeEnum.AI_AUTO_TAG,
                )

            logger.info(
                "review_tag_success space_id={} file_id={} approved_tags={} pending_tags={}",
                knowledge.id,
                db_file.id,
                approved_names,
                pending_names,
            )
        except Exception:
            logger.exception(
                "auto_tag_failed space_id={} file_id={}",
                getattr(knowledge, "id", None),
                getattr(db_file, "id", None),
            )

    @staticmethod
    def _should_run(knowledge: Knowledge, db_file: KnowledgeFile) -> bool:
        if not knowledge or not db_file:
            return False
        has_libraries = bool(KnowledgeSpaceAutoTagService._resolve_library_ids(knowledge))
        return (
            knowledge.type == KnowledgeTypeEnum.SPACE.value
            and knowledge.auto_tag_enabled
            and has_libraries
            and db_file.file_type == FileType.FILE.value
            and db_file.status == KnowledgeFileStatus.SUCCESS.value
            and db_file.file_source in {FileSource.UPLOAD.value, FileSource.SPACE_UPLOAD.value}
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
            if sum(len(part) for part in parts) >= REVIEW_TAG_MAX_CONTENT:
                break
        content = "".join(parts).strip()
        if not content and db_file.abstract:
            content = db_file.abstract.strip()
        return content[:REVIEW_TAG_MAX_CONTENT]

    @staticmethod
    def _collect_all_content(documents: Sequence[Document] | None, db_file: KnowledgeFile) -> str:
        parts: list[str] = []
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
        library_tags: list[str],
        system_prompt: str = DEFAULT_REVIEW_TAG_SYSTEM_PROMPT,
        *,
        tenant_library_names: list[str] | None = None,
        tenant_pending_names: list[str] | None = None,
    ) -> list[str]:
        space_library_text = "\n".join(f"- {tag}" for tag in library_tags)
        user_sections = [f"当前空间标签库（供参考，Link A 候选）：\n{space_library_text}"]

        if tenant_library_names:
            approved_text = "\n".join(f"- {tag}" for tag in tenant_library_names)
            user_sections.insert(
                0,
                "已入库标签（租户全局，名称必须完全一致方可复用，系统将直接生效）：\n" + approved_text,
            )
        if tenant_pending_names:
            pending_text = "\n".join(f"- {tag}" for tag in tenant_pending_names)
            user_sections.insert(
                1 if tenant_library_names else 0,
                "待审核标签（租户全局，语义相同或接近必须复用下列名称）：\n" + pending_text,
            )

        user_content = "\n\n".join(user_sections) + f"\n\n文件内容：\n{text}"
        response = llm.invoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ]
        )
        return KnowledgeSpaceReviewTagService._parse_llm_tags(getattr(response, "content", "") or "")

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
            logger.warning("review_tag_invalid_json raw={}", raw[:500])
            return []
        tags = payload.get("tags") if isinstance(payload, dict) else None
        if not isinstance(tags, list):
            return []
        return [str(tag).strip() for tag in tags if str(tag).strip()]

    @staticmethod
    def _match_library_tags(selected: Iterable[str], library_tags: list[str]) -> list[str]:
        """Deprecated: kept for backward-compatible unit tests."""
        not_allowed = {tag: tag for tag in library_tags}
        matched: list[str] = []
        for tag in selected:
            if tag not in not_allowed and tag not in matched:
                matched.append(tag)
            if len(matched) >= AUTO_TAG_MAX_AI_TAGS_PER_FILE:
                break
        return matched

    @staticmethod
    def _append_file_tags(
        space_id: int,
        file_id: int,
        tag_names: list[str],
        user_id: int,
        tenant_id: int | None,
    ) -> None:
        TagLibraryTagService.append_file_library_review_tags_sync(
            space_id=space_id,
            file_id=file_id,
            tag_names=tag_names,
            user_id=user_id,
            tenant_id=tenant_id,
            resource_type=TagResourceTypeEnum.AI_AUTO_TAG,
        )
