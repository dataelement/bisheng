from types import SimpleNamespace
from unittest.mock import patch

from bisheng.database.models.tag import TagResourceTypeEnum
from bisheng.knowledge.domain.services.knowledge_space_review_tag_service import (
    KnowledgeSpaceReviewTagService,
)
from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService


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
        patch.object(KnowledgeSpaceReviewTagService, "_invoke_llm", return_value=["新标签"]),
        patch.object(KnowledgeSpaceReviewTagService, "_append_file_tags") as append_file_tags,
    ):
        KnowledgeSpaceReviewTagService.apply_after_review_upload_parse(knowledge, db_file)

    assert get_llm.call_args.kwargs["temperature"] == 0
    append_file_tags.assert_called_once()
