from unittest.mock import MagicMock, patch

from bisheng.knowledge.domain.services.knowledge_space_review_tag_service import (
    KnowledgeSpaceReviewTagService,
)


def test_append_file_tags_checks_existing_library_tags_without_name_error():
    module_path = "bisheng.knowledge.domain.services.knowledge_space_review_tag_service"
    session = MagicMock()
    session.exec.side_effect = [
        MagicMock(all=MagicMock(return_value=[])),
        MagicMock(all=MagicMock(return_value=[])),
    ]

    def set_review_tag_id(obj):
        if obj.__class__.__name__ == "ReviewTag":
            obj.id = 10

    session.add.side_effect = set_review_tag_id

    session_context = MagicMock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False

    with (
        patch(f"{module_path}.get_sync_db_session", return_value=session_context),
        patch(f"{module_path}.TagLibraryTagService.find_library_tag_by_name_sync", return_value=None) as find_tag,
    ):
        KnowledgeSpaceReviewTagService._append_file_tags(
            space_id=3556,
            file_id=91652,
            tag_names=["候选标签"],
            user_id=1,
            tenant_id=1,
        )

    find_tag.assert_called_once_with(tenant_id=1, tag_name="候选标签")
    session.commit.assert_called_once()
