from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.schemas.knowledge_space_schema import KnowledgeSpaceInfoResp


def test_space_info_resp_carries_is_favorite():
    k = Knowledge(id=200, name="我的收藏", user_id=7, type=3, is_favorite=True)
    resp = KnowledgeSpaceInfoResp(**k.model_dump(), is_pinned=False)
    assert resp.is_favorite is True


def test_space_info_resp_defaults_is_favorite_false():
    k = Knowledge(id=201, name="普通库", user_id=7, type=3)
    resp = KnowledgeSpaceInfoResp(**k.model_dump(), is_pinned=False)
    assert resp.is_favorite is False
