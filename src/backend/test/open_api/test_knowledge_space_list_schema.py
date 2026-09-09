from bisheng.knowledge.domain.schemas.knowledge_space_schema import KnowledgeSpaceListItemResp


def test_knowledge_space_list_item_declares_enrichment_fields():
    item = KnowledgeSpaceListItemResp(
        id=1,
        name="space",
        user_name="holder",
        actions=["visible", "edit"],
    )

    assert item.user_name == "holder"
    assert item.actions == ["visible", "edit"]
