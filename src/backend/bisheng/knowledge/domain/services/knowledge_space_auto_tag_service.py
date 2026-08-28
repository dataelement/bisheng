import json
import re
from collections.abc import Iterable, Sequence

from langchain_core.documents import Document
from loguru import logger
from sqlmodel import func, select

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.models.config import Config
from bisheng.common.services.config_service import settings
from bisheng.core.config.settings import DEFAULT_SHOUGANG_FILE_DOCUMENT_TYPES
from bisheng.core.database import get_sync_db_session
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.review_tags import ReviewTag, ReviewTagLink
from bisheng.database.models.tag import Tag, TagLink, TagResourceTypeEnum
from bisheng.knowledge.domain.constants import (
    BUSINESS_DOMAIN_OPTIONS,
    get_business_domain_code_from_file,
    parse_shougang_file_encoding_codes,
)
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
from bisheng.knowledge.domain.services.tag_blacklist_service import TagBlacklistService
from bisheng.knowledge.domain.services.tag_library_tag_service import (
    TagLibraryTagService,
)
from bisheng.llm.domain import LLMService
from bisheng.shougang_portal_config.domain.repositories.interfaces.portal_admin_config_repository import (
    portal_admin_config_physical_key,
)
from bisheng.shougang_portal_config.domain.schemas.portal_config_schema import ShougangPortalAdminConfig

AUTO_TAG_MAX_CONTENT = 3000
AUTO_TAG_MIN = 3
AUTO_TAG_MAX = 5
AUTO_TAG_MAX_LIBRARY_MATCH = 5
AUTO_TAG_MAX_AI_TAGS_PER_FILE = 5
AUTO_TAG_LINK_B_MAX_LINK_A_TAGS = 3
RECOMMEND_TAG_MAX = 10
RECOMMENDED_TAGS_METADATA_KEY = "_recommended_tags"
DEFAULT_AUTO_TAG_SYSTEM_PROMPT = (
    "你是文件自动标签分类器。只能从候选标签中选择最相关的标签，最多返回 5 个标签。\n"
    "请结合文件的业务域、文件分类与文件内容选择标签。\n"
    '输出格式要求严格遵循 JSON：有合适标签时输出 {"tags": ["标签名"]}；'
    '没有合适标签时输出 {"tags": []}。'
)
DEFAULT_RECOMMEND_TAG_SYSTEM_PROMPT = (
    "你是文件标签推荐器。只能从候选标签中选择与文件内容最相关的标签，必须返回 10 个。\n"
    "请结合文件的业务域、文件分类与文件内容选择标签。\n"
    '输出格式要求严格遵循 JSON：输出 {"tags": ["标签名", ...]}，tags 必须恰好包含 10 个标签。'
)
AUTO_TAG_CONTEXT_INSTRUCTION = (
    '请结合上述业务域、文件分类与文件内容，从候选标签中选择最相关的标签；若无合适标签则输出 {"tags": []}。'
)
RECOMMEND_CONTEXT_INSTRUCTION = (
    "请结合上述业务域、文件分类与文件内容，从候选标签中必须选出 10 个最相关的标签。"
)


class KnowledgeSpaceAutoTagService:
    @classmethod
    def is_tenant_auto_tag_enabled(cls) -> bool:
        """Tenant master switch (config key auto_tag_visible). Fail open on read errors."""
        try:
            from bisheng.api.services.workstation import WorkStationService

            cfg, *_rest = WorkStationService.query_knowledge_space_config_with_meta()
            return bool(getattr(cfg, "auto_tag_visible", True)) if cfg else True
        except Exception:
            logger.exception("auto_tag_master_switch_read_failed")
            return True

    @classmethod
    def should_run_link_b_after_link_a(cls, link_a_applied_tag_count: int) -> bool:
        return link_a_applied_tag_count < AUTO_TAG_MIN

    @classmethod
    def apply_after_upload_parse(
        cls,
        knowledge: Knowledge,
        db_file: KnowledgeFile,
        documents: Sequence[Document] | None = None,
    ) -> int:
        try:
            if not cls._should_run(knowledge, db_file):
                return 0

            llm_config = LLMService.get_knowledge_llm(tenant_id=db_file.tenant_id)
            if not llm_config.auto_tag_enabled or not llm_config.extract_title_model_id:
                return 0

            text = cls._collect_content(documents, db_file)
            if not text:
                logger.info(
                    "auto_tag_skip_empty_content space_id={} file_id={}",
                    knowledge.id,
                    db_file.id,
                )
                return 0

            llm = LLMService.get_bisheng_llm_sync(
                model_id=llm_config.extract_title_model_id,
                app_id=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
                app_name=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
                app_type=ApplicationTypeEnum.KNOWLEDGE_BASE,
                user_id=db_file.user_id,
                temperature=0,
            )
            system_prompt = cls._build_auto_tag_system_prompt(
                (llm_config.auto_tag_prompt or "").strip() or DEFAULT_AUTO_TAG_SYSTEM_PROMPT,
                db_file,
            )

            bound_ids = cls._resolve_library_ids(knowledge)
            applied_names: list[str] = []
            applied_names.extend(
                cls._select_and_apply_from_library_ids(
                    knowledge=knowledge,
                    db_file=db_file,
                    llm=llm,
                    text=text,
                    system_prompt=system_prompt,
                    library_ids=bound_ids,
                    exclude_names=applied_names,
                    max_count=AUTO_TAG_MAX,
                )
            )
            if len(applied_names) >= AUTO_TAG_MIN:
                return len(applied_names)

            unbound_ids = cls._resolve_unbound_public_library_ids(knowledge, bound_ids)
            remaining = AUTO_TAG_MAX - len(applied_names)
            applied_names.extend(
                cls._select_and_apply_from_library_ids(
                    knowledge=knowledge,
                    db_file=db_file,
                    llm=llm,
                    text=text,
                    system_prompt=system_prompt,
                    library_ids=unbound_ids,
                    exclude_names=applied_names,
                    max_count=remaining,
                )
            )
            logger.info(
                "auto_tag_waterfall_done space_id={} file_id={} applied_count={} bound_ids={} unbound_ids={}",
                knowledge.id,
                db_file.id,
                len(applied_names),
                bound_ids,
                unbound_ids,
            )
            return len(applied_names)
        except Exception:
            logger.exception(
                "auto_tag_failed space_id={} file_id={}",
                getattr(knowledge, "id", None),
                getattr(db_file, "id", None),
            )
            return 0

    @classmethod
    def recommend_bound_library_tags_sync(
        cls,
        knowledge: Knowledge,
        db_file: KnowledgeFile,
        *,
        exclude_names: Sequence[str] | None = None,
        documents: Sequence[Document] | None = None,
        limit: int = RECOMMEND_TAG_MAX,
    ) -> list[str]:
        bound_ids = cls._resolve_library_ids(knowledge)
        if not bound_ids:
            return []
        excluded = {name.strip() for name in (exclude_names or []) if str(name).strip()}
        manual_tags, ai_tags = cls._collect_library_tags(bound_ids)
        candidates = [tag for tag in dict.fromkeys(manual_tags + ai_tags) if tag and tag not in excluded]
        candidates = cls._exclude_blacklisted(candidates)
        if not candidates:
            return []
        if len(candidates) <= limit:
            return list(candidates)

        llm_config = LLMService.get_knowledge_llm(tenant_id=db_file.tenant_id)
        if not llm_config.extract_title_model_id:
            return []
        text = cls._collect_content(documents, db_file)
        if not text:
            return []
        llm = LLMService.get_bisheng_llm_sync(
            model_id=llm_config.extract_title_model_id,
            app_id=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
            app_name=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
            app_type=ApplicationTypeEnum.KNOWLEDGE_BASE,
            user_id=db_file.user_id,
            temperature=0,
        )
        system_prompt = cls._build_file_context_system_prompt(
            DEFAULT_RECOMMEND_TAG_SYSTEM_PROMPT,
            db_file,
            RECOMMEND_CONTEXT_INSTRUCTION,
        )
        selected = cls._invoke_llm(llm, text, candidates, system_prompt)
        allowed = set(candidates)
        result: list[str] = []
        for tag in selected:
            if tag in allowed and tag not in result:
                result.append(tag)
            if len(result) >= limit:
                break
        if len(result) < limit:
            for tag in candidates:
                if tag not in result:
                    result.append(tag)
                if len(result) >= limit:
                    break
        return result

    @classmethod
    def generate_recommended_tags_after_parse(
        cls,
        knowledge: Knowledge,
        db_file: KnowledgeFile,
        documents: Sequence[Document] | None = None,
        *,
        persist: bool = False,
    ) -> list[str]:
        """Generate up to 10 bound-library recommendations after parse. Does not apply tags."""
        try:
            if not knowledge or not db_file or knowledge.type != KnowledgeTypeEnum.SPACE.value:
                return []
            if db_file.file_type != FileType.FILE.value:
                return []
            applied = cls._list_file_applied_tag_names(int(db_file.id)) if db_file.id else []
            names = cls.recommend_bound_library_tags_sync(
                knowledge,
                db_file,
                exclude_names=applied,
                documents=documents,
            )
            if persist:
                cls.persist_recommended_tag_names(db_file, names)
            else:
                cls._set_recommended_tag_names(db_file, names)
            logger.info(
                "recommend_tags_generated space_id={} file_id={} count={} excluded={}",
                knowledge.id,
                db_file.id,
                len(names),
                len(applied),
            )
            return names
        except Exception:
            # Best-effort: parse success must not depend on recommendation generation.
            logger.exception(
                "recommend_tags_generate_failed space_id={} file_id={}",
                getattr(knowledge, "id", None),
                getattr(db_file, "id", None),
            )
            return []

    @classmethod
    def read_recommended_tag_names(cls, db_file: KnowledgeFile) -> list[str] | None:
        raw = (db_file.user_metadata or {}).get(RECOMMENDED_TAGS_METADATA_KEY)
        if raw is None:
            return None
        if not isinstance(raw, list):
            return []
        return [str(name).strip() for name in raw if str(name).strip()]

    @classmethod
    def persist_recommended_tag_names(cls, db_file: KnowledgeFile, names: list[str]) -> None:
        cls._set_recommended_tag_names(db_file, names)
        file_id = getattr(db_file, "id", None)
        if file_id is None:
            return
        with get_sync_db_session() as session:
            row = session.get(KnowledgeFile, int(file_id))
            if row is None:
                return
            metadata = dict(row.user_metadata or {})
            metadata[RECOMMENDED_TAGS_METADATA_KEY] = list(names)
            row.user_metadata = metadata
            session.add(row)
            session.commit()

    @staticmethod
    def _set_recommended_tag_names(db_file: KnowledgeFile, names: list[str]) -> None:
        metadata = dict(db_file.user_metadata or {})
        metadata[RECOMMENDED_TAGS_METADATA_KEY] = list(names)
        db_file.user_metadata = metadata

    @classmethod
    def _list_file_applied_tag_names(cls, file_id: int) -> list[str]:
        file_id_str = str(file_id)
        names: list[str] = []
        with get_sync_db_session() as session:
            approved = session.exec(
                select(Tag.name)
                .join(TagLink, TagLink.tag_id == Tag.id)
                .where(
                    TagLink.resource_id == file_id_str,
                    TagLink.resource_type == ResourceTypeEnum.SPACE_FILE.value,
                    Tag.name.is_not(None),
                )
            ).all()
            pending = session.exec(
                select(ReviewTag.name)
                .join(ReviewTagLink, ReviewTagLink.tag_id == ReviewTag.id)
                .where(
                    ReviewTagLink.resource_id == file_id_str,
                    ReviewTagLink.resource_type == ResourceTypeEnum.SPACE_FILE.value,
                    ReviewTagLink.is_deleted == False,  # noqa: E712
                    ReviewTag.review_status == 0,
                    ReviewTag.is_deleted == False,  # noqa: E712
                    ReviewTag.name.is_not(None),
                )
            ).all()
        for raw in list(approved) + list(pending):
            name = str(raw or "").strip()
            if name and name not in names:
                names.append(name)
        return names

    @classmethod
    def _select_and_apply_from_library_ids(
        cls,
        *,
        knowledge: Knowledge,
        db_file: KnowledgeFile,
        llm,
        text: str,
        system_prompt: str,
        library_ids: list[int],
        exclude_names: Sequence[str],
        max_count: int,
    ) -> list[str]:
        if not library_ids or max_count <= 0:
            return []
        excluded = {name.strip() for name in exclude_names if str(name).strip()}
        manual_tags, ai_tags = cls._collect_library_tags(library_ids)
        catalog = cls._blacklist_catalog()
        manual_tags = TagBlacklistService.filter_unblocked_names(manual_tags, catalog)
        ai_tags = TagBlacklistService.filter_unblocked_names(ai_tags, catalog)
        manual_tags = [tag for tag in manual_tags if tag not in excluded]
        ai_tags = [tag for tag in ai_tags if tag not in excluded]
        if not manual_tags and not ai_tags:
            return []
        tags_list = list(dict.fromkeys(tag for tag in manual_tags + ai_tags if tag))
        selected = cls._invoke_llm(llm, text, tags_list, system_prompt)
        matched, ai_matched = cls._match_library_tags(selected, manual_tags, ai_tags)
        matched = matched[:max_count]
        remaining = max_count - len(matched)
        ai_matched = ai_matched[:remaining]
        applied: list[str] = []
        if matched:
            cls._append_file_tags(
                space_id=knowledge.id,
                file_id=db_file.id,
                tag_names=matched,
                user_id=db_file.user_id or 0,
                tenant_id=db_file.tenant_id,
                resource_type=TagResourceTypeEnum.SYSTEM_TAG,
            )
            applied.extend(matched)
        if ai_matched:
            ai_matched = cls._cap_ai_tags_for_file(db_file.id, ai_matched)
        if ai_matched:
            cls._append_file_tags(
                space_id=knowledge.id,
                file_id=db_file.id,
                tag_names=ai_matched,
                user_id=db_file.user_id or 0,
                tenant_id=db_file.tenant_id,
                resource_type=TagResourceTypeEnum.AI_AUTO_TAG,
            )
            applied.extend(ai_matched)
        return applied

    @classmethod
    def _blacklist_catalog(cls) -> list[tuple[str, str]]:
        return TagBlacklistService.list_catalog_entries_sync()

    @classmethod
    def _exclude_blacklisted(cls, names: Sequence[str]) -> list[str]:
        return TagBlacklistService.filter_unblocked_names(names, cls._blacklist_catalog())

    @classmethod
    def _resolve_library_ids(cls, knowledge: Knowledge) -> list[int]:
        return KnowledgeTagLibraryLinkDao.list_library_ids_by_knowledge(int(knowledge.id))

    @classmethod
    def _resolve_unbound_public_library_ids(cls, knowledge: Knowledge, bound_ids: list[int]) -> list[int]:
        bound = {int(library_id) for library_id in bound_ids}
        public_ids = KnowledgeSpaceTagLibraryDao.list_public_ids_by_tenant_sync(getattr(knowledge, "tenant_id", None))
        return [library_id for library_id in public_ids if library_id not in bound]

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
        if not knowledge or not db_file:
            return False
        # Link A runs whenever the tenant master switch is on. Binding is optional:
        # unbound spaces still pick from other public libraries.
        return (
            KnowledgeSpaceAutoTagService.is_tenant_auto_tag_enabled()
            and knowledge.type == KnowledgeTypeEnum.SPACE.value
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
    def _format_business_domain_display(business_domain_code: str | None) -> str | None:
        normalized = (business_domain_code or "").strip().upper()
        if not normalized:
            return None
        label = BUSINESS_DOMAIN_OPTIONS.get(normalized)
        return f"{normalized}（{label}）" if label else normalized

    @staticmethod
    def _normalize_category_code(value: str | None) -> str | None:
        if not isinstance(value, str):
            return None
        code = value.strip().upper()
        if not code or len(code) > 16:
            return None
        return code

    @classmethod
    def _get_file_category_code_from_split_rule(cls, split_rule) -> str | None:
        if isinstance(split_rule, str) and split_rule.strip():
            try:
                split_rule = json.loads(split_rule)
            except json.JSONDecodeError:
                return None
        if not isinstance(split_rule, dict):
            return None
        return cls._normalize_category_code(split_rule.get("file_category_code"))

    @classmethod
    def _resolve_file_category_code(cls, db_file: KnowledgeFile) -> str | None:
        file_category_code = cls._get_file_category_code_from_split_rule(getattr(db_file, "split_rule", None))
        if file_category_code:
            return file_category_code
        document_code, _ = parse_shougang_file_encoding_codes(db_file)
        return document_code or None

    @staticmethod
    def _resolve_item_label(item, fallback: str) -> str:
        if isinstance(item, dict):
            label = item.get("label")
        else:
            label = getattr(item, "label", None)
        if isinstance(label, str) and label.strip():
            return label.strip()
        return fallback

    @classmethod
    def _load_document_types_for_tenant(cls, tenant_id: int | None) -> list[dict]:
        resolved_tenant_id = int(tenant_id or 1)
        try:
            with get_sync_db_session() as session:
                config_row = session.exec(
                    select(Config).where(Config.key == portal_admin_config_physical_key(resolved_tenant_id))
                ).first()
            if config_row and config_row.value:
                portal_config = ShougangPortalAdminConfig.model_validate_json(config_row.value)
                document_types = getattr(getattr(portal_config, "portal", None), "document_types", None) or []
                if document_types:
                    return [item.model_dump(mode="json") for item in document_types if item]
        except Exception:
            logger.warning(
                "auto_tag_load_portal_document_types_failed tenant_id={}",
                resolved_tenant_id,
            )

        try:
            shougang_conf = settings.get_all_config().get("shougang", {}) or {}
            file_encoding_conf = shougang_conf.get("file_encoding", {}) or {}
            document_types = file_encoding_conf.get("document_types")
            if isinstance(document_types, list) and document_types:
                return [dict(item) if isinstance(item, dict) else item for item in document_types]
        except Exception:
            logger.warning("auto_tag_load_shougang_document_types_failed tenant_id={}", resolved_tenant_id)

        return [dict(item) for item in DEFAULT_SHOUGANG_FILE_DOCUMENT_TYPES]

    @classmethod
    def _build_document_type_label_lookup(
        cls,
        raw_document_types: list[dict],
    ) -> tuple[dict[str, str], dict[str, str]]:
        parent_labels: dict[str, str] = {}
        subcategory_labels: dict[str, str] = {}
        for item in raw_document_types or DEFAULT_SHOUGANG_FILE_DOCUMENT_TYPES:
            parent_code = cls._normalize_category_code(
                item.get("code") if isinstance(item, dict) else getattr(item, "code", None)
            )
            if not parent_code:
                continue
            parent_labels[parent_code] = cls._resolve_item_label(item, parent_code)

            raw_children = item.get("children") if isinstance(item, dict) else getattr(item, "children", None)
            children = raw_children if isinstance(raw_children, list) and raw_children else [item]
            for child in children:
                child_code = cls._normalize_category_code(
                    child.get("code") if isinstance(child, dict) else getattr(child, "code", None)
                )
                if not child_code:
                    continue
                subcategory_labels[child_code] = cls._resolve_item_label(child, child_code)
        return parent_labels, subcategory_labels

    @classmethod
    def get_document_type_label_lookup_for_tenant(
        cls,
        tenant_id: int | None,
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Resolve configured first- and second-level category labels for projections."""
        return cls._build_document_type_label_lookup(
            cls._load_document_types_for_tenant(tenant_id)
        )

    @classmethod
    def _format_file_category_display(cls, db_file: KnowledgeFile) -> str | None:
        parent_labels, subcategory_labels = cls._build_document_type_label_lookup(
            cls._load_document_types_for_tenant(getattr(db_file, "tenant_id", None))
        )
        parts: list[str] = []
        file_category_code = cls._resolve_file_category_code(db_file)
        if file_category_code:
            parts.append(parent_labels.get(file_category_code, file_category_code))
        file_subcategory_code = cls._normalize_category_code(getattr(db_file, "file_subcategory_code", None))
        if file_subcategory_code:
            subcategory_name = subcategory_labels.get(file_subcategory_code, file_subcategory_code)
            if not parts or subcategory_name != parts[0]:
                parts.append(subcategory_name)
        return " / ".join(parts) if parts else None

    @classmethod
    def _resolve_file_tagging_context(cls, db_file: KnowledgeFile) -> tuple[str | None, str | None]:
        business_domain_code = get_business_domain_code_from_file(db_file)
        business_domain = cls._format_business_domain_display(business_domain_code)
        file_category = cls._format_file_category_display(db_file)
        return business_domain, file_category

    @classmethod
    def _build_file_context_system_prompt(
        cls,
        base_prompt: str,
        db_file: KnowledgeFile,
        context_instruction: str,
    ) -> str:
        business_domain, file_category = cls._resolve_file_tagging_context(db_file)
        context_lines: list[str] = []
        if business_domain:
            context_lines.append(f"业务域：{business_domain}")
        if file_category:
            context_lines.append(f"文件分类：{file_category}")
        if not context_lines:
            return base_prompt.strip()

        parts = [base_prompt.strip(), "\n".join(context_lines), context_instruction]
        return "\n\n".join(part for part in parts if part)

    @classmethod
    def _build_auto_tag_system_prompt(cls, base_prompt: str, db_file: KnowledgeFile) -> str:
        return cls._build_file_context_system_prompt(base_prompt, db_file, AUTO_TAG_CONTEXT_INSTRUCTION)

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
            if len(matched) >= AUTO_TAG_MAX_LIBRARY_MATCH:
                break
        ai_matched: list[str] = []
        ai_allowed = {tag: tag for tag in ai_tags}
        for tag in selected:
            if tag in ai_allowed and tag not in ai_matched and tag not in matched:
                ai_matched.append(ai_allowed[tag])
            if len(ai_matched) >= AUTO_TAG_MAX_AI_TAGS_PER_FILE:
                break
        return matched, ai_matched

    @classmethod
    def _count_file_ai_auto_tags(cls, file_id: int) -> int:
        """Count approved and pending-review AI tags linked to a space file."""
        file_id_str = str(file_id)
        with get_sync_db_session() as session:
            approved_count = session.exec(
                select(func.count())
                .select_from(TagLink)
                .join(Tag, Tag.id == TagLink.tag_id)
                .where(
                    TagLink.resource_id == file_id_str,
                    TagLink.resource_type == ResourceTypeEnum.SPACE_FILE.value,
                    Tag.resource_type == TagResourceTypeEnum.AI_AUTO_TAG.value,
                )
            ).one()
            pending_review_count = session.exec(
                select(func.count())
                .select_from(ReviewTagLink)
                .join(ReviewTag, ReviewTag.id == ReviewTagLink.tag_id)
                .where(
                    ReviewTagLink.resource_id == file_id_str,
                    ReviewTagLink.resource_type == ResourceTypeEnum.SPACE_FILE.value,
                    ReviewTagLink.is_deleted == False,  # noqa: E712
                    ReviewTag.resource_type == TagResourceTypeEnum.AI_AUTO_TAG.value,
                    ReviewTag.review_status == 0,
                    ReviewTag.is_deleted == False,  # noqa: E712
                )
            ).one()
        return int(approved_count or 0) + int(pending_review_count or 0)

    @classmethod
    def _cap_ai_tags_for_file(cls, file_id: int, tag_names: list[str]) -> list[str]:
        if not tag_names:
            return []
        remaining = AUTO_TAG_MAX_AI_TAGS_PER_FILE - cls._count_file_ai_auto_tags(file_id)
        if remaining <= 0:
            return []
        return tag_names[:remaining]

    @staticmethod
    def _append_file_tags(
        space_id: int,
        file_id: int,
        tag_names: list[str],
        user_id: int,
        tenant_id: int | None,
        resource_type: TagResourceTypeEnum,
    ) -> None:
        TagLibraryTagService.append_file_library_tags_sync(
            space_id=space_id,
            file_id=file_id,
            tag_names=tag_names,
            user_id=user_id,
            tenant_id=tenant_id,
            resource_type=resource_type,
        )
