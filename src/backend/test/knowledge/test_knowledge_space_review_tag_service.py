from types import SimpleNamespace
from unittest.mock import patch

from bisheng.database.models.tag import TagResourceTypeEnum
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import (
    FileSource,
    FileType,
    KnowledgeFile,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.services.knowledge_space_auto_tag_service import (
    KnowledgeSpaceAutoTagService,
)
from bisheng.knowledge.domain.services.knowledge_space_review_tag_service import (
    REVIEW_TAG_CONTEXT_INSTRUCTION,
    KnowledgeSpaceReviewTagService,
)
from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService

_LINK_DAO_PATCH = (
    "bisheng.knowledge.domain.services.knowledge_space_review_tag_service."
    "KnowledgeSpaceAutoTagService._resolve_library_ids"
)


def test_build_review_tag_system_prompt_appends_business_domain_and_file_category():
    db_file = KnowledgeFile(
        id=1,
        split_rule='{"file_category_code": "STD", "business_domain_code": "PP"}',
        file_subcategory_code="STD_A",
    )
    document_types = [
        {
            "code": "STD",
            "label": "标准规范",
            "children": [{"code": "STD_A", "label": "安全规程"}],
        }
    ]
    with patch.object(
        KnowledgeSpaceAutoTagService,
        "_load_document_types_for_tenant",
        return_value=document_types,
    ):
        prompt = KnowledgeSpaceAutoTagService._build_file_context_system_prompt(
            "base prompt",
            db_file,
            REVIEW_TAG_CONTEXT_INSTRUCTION,
        )
    assert "base prompt" in prompt
    assert "业务域：PP（生产）" in prompt
    assert "文件分类：标准规范 / 安全规程" in prompt
    assert "生成不在标签库中的新标签" not in prompt
    assert "优先复用用户消息中" in prompt


def test_build_review_tag_system_prompt_without_metadata_keeps_base_prompt():
    db_file = KnowledgeFile(id=3)
    prompt = KnowledgeSpaceAutoTagService._build_file_context_system_prompt(
        "base prompt",
        db_file,
        REVIEW_TAG_CONTEXT_INSTRUCTION,
    )
    assert prompt == "base prompt"


def test_append_file_tags_delegates_to_tag_library_review_sync():
    with patch.object(
        TagLibraryTagService,
        "append_file_library_review_tags_sync",
    ) as append_sync:
        KnowledgeSpaceReviewTagService._append_file_tags(
            space_id=3556,
            file_id=91652,
            tag_names=["候选标签"],
            user_id=1,
            tenant_id=1,
        )

    append_sync.assert_called_once_with(
        space_id=3556,
        file_id=91652,
        tag_names=["候选标签"],
        user_id=1,
        tenant_id=1,
        resource_type=TagResourceTypeEnum.AI_AUTO_TAG,
    )


def test_review_tag_llm_uses_zero_temperature():
    module_path = "bisheng.knowledge.domain.services.knowledge_space_review_tag_service"
    knowledge = SimpleNamespace(id=1)
    db_file = SimpleNamespace(id=2, tenant_id=1, user_id=7, abstract="评审内容")

    resolved = SimpleNamespace(
        entries=[
            SimpleNamespace(canonical_name="新标签", target="pending"),
        ]
    )

    with (
        patch.object(KnowledgeSpaceReviewTagService, "_should_run", return_value=True),
        patch(f"{module_path}.KnowledgeSpaceAutoTagService._resolve_library_ids", return_value=[10]),
        patch(f"{module_path}.KnowledgeSpaceAutoTagService._collect_library_tags", return_value=(["已有标签"], [])),
        patch(
            f"{module_path}.LLMService.get_knowledge_llm",
            return_value=SimpleNamespace(review_tag_enabled=True, extract_title_model_id=123, review_tag_prompt=""),
        ),
        patch(
            f"{module_path}.SensitiveWordPolicyService.check_text",
            return_value=SimpleNamespace(enabled=False, hits=[]),
        ),
        patch(f"{module_path}.LLMService.get_bisheng_llm_sync", return_value=object()) as get_llm,
        patch(
            f"{module_path}.TagLibraryTagService.load_link_b_tenant_catalog_sync",
            return_value=SimpleNamespace(
                library_by_key={},
                pending_catalog=[],
                library_names=[],
                cache_source="db",
            ),
        ),
        patch.object(KnowledgeSpaceReviewTagService, "_invoke_llm", return_value=["新标签"]),
        patch(f"{module_path}.TagLibraryTagService.resolve_link_b_tag_candidates_sync", return_value=resolved),
        patch.object(KnowledgeSpaceAutoTagService, "_cap_ai_tags_for_file", side_effect=lambda _fid, tags: tags),
        patch(f"{module_path}.TagLibraryTagService.append_file_library_review_tags_sync") as append_pending,
        patch(f"{module_path}.TagLibraryTagService.append_file_library_tags_sync") as append_approved,
    ):
        KnowledgeSpaceReviewTagService.apply_after_review_upload_parse(knowledge, db_file)

    assert get_llm.call_args.kwargs["temperature"] == 0
    append_pending.assert_called_once()
    append_approved.assert_not_called()


def test_review_tag_should_run_only_when_space_auto_tag_enabled():
    knowledge = Knowledge(
        id=1,
        name="space",
        type=KnowledgeTypeEnum.SPACE.value,
        auto_tag_enabled=True,
        auto_tag_library_id=10,
    )
    db_file = KnowledgeFile(
        id=2,
        knowledge_id=1,
        file_name="a.txt",
        file_type=FileType.FILE.value,
        file_source=FileSource.UPLOAD.value,
        status=KnowledgeFileStatus.SUCCESS.value,
    )

    with patch(_LINK_DAO_PATCH, return_value=[10]):
        assert KnowledgeSpaceReviewTagService._should_run(knowledge, db_file)

        knowledge.auto_tag_enabled = False
        assert not KnowledgeSpaceReviewTagService._should_run(knowledge, db_file)


def test_review_tag_should_run_with_default_library_when_no_explicit_binding():
    knowledge = Knowledge(
        id=1,
        name="space",
        type=KnowledgeTypeEnum.SPACE.value,
        auto_tag_enabled=True,
        auto_tag_library_id=None,
    )
    db_file = KnowledgeFile(
        id=2,
        knowledge_id=1,
        file_name="a.txt",
        file_type=FileType.FILE.value,
        file_source=FileSource.UPLOAD.value,
        status=KnowledgeFileStatus.SUCCESS.value,
    )

    with patch(_LINK_DAO_PATCH, return_value=[1]):
        assert KnowledgeSpaceReviewTagService._should_run(knowledge, db_file)


def test_review_tag_match_limits_to_five_tags():
    selected = [f"新标签-{i}" for i in range(8)]
    matched = KnowledgeSpaceReviewTagService._match_library_tags(selected, ["已有标签"])
    assert matched == [f"新标签-{i}" for i in range(5)]


def test_review_tag_cap_skips_when_file_already_has_five_ai_tags():
    module_path = "bisheng.knowledge.domain.services.knowledge_space_review_tag_service"
    knowledge = SimpleNamespace(id=1)
    db_file = SimpleNamespace(id=2, tenant_id=1, user_id=7, abstract="评审内容")
    resolved = SimpleNamespace(
        entries=[
            SimpleNamespace(canonical_name="新标签-1", target="pending"),
            SimpleNamespace(canonical_name="新标签-2", target="pending"),
        ]
    )

    with (
        patch.object(KnowledgeSpaceReviewTagService, "_should_run", return_value=True),
        patch(f"{module_path}.KnowledgeSpaceAutoTagService._resolve_library_ids", return_value=[10]),
        patch(f"{module_path}.KnowledgeSpaceAutoTagService._collect_library_tags", return_value=(["已有标签"], [])),
        patch(
            f"{module_path}.LLMService.get_knowledge_llm",
            return_value=SimpleNamespace(review_tag_enabled=True, extract_title_model_id=123, review_tag_prompt=""),
        ),
        patch(
            f"{module_path}.SensitiveWordPolicyService.check_text",
            return_value=SimpleNamespace(enabled=False, hits=[]),
        ),
        patch(f"{module_path}.LLMService.get_bisheng_llm_sync", return_value=object()),
        patch(
            f"{module_path}.TagLibraryTagService.load_link_b_tenant_catalog_sync",
            return_value=SimpleNamespace(
                library_by_key={},
                pending_catalog=[],
                library_names=[],
                cache_source="db",
            ),
        ),
        patch.object(KnowledgeSpaceReviewTagService, "_invoke_llm", return_value=["新标签-1", "新标签-2"]),
        patch(f"{module_path}.TagLibraryTagService.resolve_link_b_tag_candidates_sync", return_value=resolved),
        patch.object(KnowledgeSpaceAutoTagService, "_cap_ai_tags_for_file", return_value=[]),
        patch(f"{module_path}.TagLibraryTagService.append_file_library_review_tags_sync") as append_pending,
    ):
        KnowledgeSpaceReviewTagService.apply_after_review_upload_parse(knowledge, db_file)

    append_pending.assert_not_called()


def test_review_tag_dual_channel_write_for_approved_and_pending():
    module_path = "bisheng.knowledge.domain.services.knowledge_space_review_tag_service"
    knowledge = SimpleNamespace(id=1)
    db_file = SimpleNamespace(id=2, tenant_id=1, user_id=7, abstract="评审内容")
    resolved = SimpleNamespace(
        entries=[
            SimpleNamespace(canonical_name="行业情报", target="approved"),
            SimpleNamespace(canonical_name="新标签", target="pending"),
        ]
    )

    with (
        patch.object(KnowledgeSpaceReviewTagService, "_should_run", return_value=True),
        patch(f"{module_path}.KnowledgeSpaceAutoTagService._resolve_library_ids", return_value=[10]),
        patch(f"{module_path}.KnowledgeSpaceAutoTagService._collect_library_tags", return_value=(["已有标签"], [])),
        patch(
            f"{module_path}.LLMService.get_knowledge_llm",
            return_value=SimpleNamespace(review_tag_enabled=True, extract_title_model_id=123, review_tag_prompt=""),
        ),
        patch(
            f"{module_path}.SensitiveWordPolicyService.check_text",
            return_value=SimpleNamespace(enabled=False, hits=[]),
        ),
        patch(f"{module_path}.LLMService.get_bisheng_llm_sync", return_value=object()),
        patch(
            f"{module_path}.TagLibraryTagService.load_link_b_tenant_catalog_sync",
            return_value=SimpleNamespace(
                library_by_key={},
                pending_catalog=[],
                library_names=[],
                cache_source="db",
            ),
        ),
        patch.object(KnowledgeSpaceReviewTagService, "_invoke_llm", return_value=["行业情报", "新标签"]),
        patch(f"{module_path}.TagLibraryTagService.resolve_link_b_tag_candidates_sync", return_value=resolved),
        patch.object(
            KnowledgeSpaceAutoTagService,
            "_cap_ai_tags_for_file",
            side_effect=lambda _fid, tags: tags,
        ),
        patch(f"{module_path}.TagLibraryTagService.append_file_library_tags_sync") as append_approved,
        patch(f"{module_path}.TagLibraryTagService.append_file_library_review_tags_sync") as append_pending,
    ):
        KnowledgeSpaceReviewTagService.apply_after_review_upload_parse(knowledge, db_file)

    append_approved.assert_called_once_with(
        space_id=1,
        file_id=2,
        tag_names=["行业情报"],
        user_id=7,
        tenant_id=1,
        resource_type=TagResourceTypeEnum.AI_AUTO_TAG,
    )
    append_pending.assert_called_once_with(
        space_id=1,
        file_id=2,
        tag_names=["新标签"],
        user_id=7,
        tenant_id=1,
        resource_type=TagResourceTypeEnum.AI_AUTO_TAG,
    )
