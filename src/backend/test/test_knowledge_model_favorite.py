from bisheng.knowledge.domain.models.knowledge import Knowledge


def test_knowledge_has_is_favorite_default_false():
    k = Knowledge(name="x", user_id=1, type=3)
    assert hasattr(k, "is_favorite")
    assert k.is_favorite is False


def test_knowledge_is_favorite_settable():
    k = Knowledge(name="我的收藏", user_id=1, type=3, is_favorite=True)
    assert k.is_favorite is True
