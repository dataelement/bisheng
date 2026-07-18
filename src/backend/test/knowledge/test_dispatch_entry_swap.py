from unittest.mock import MagicMock


def test_process_knowledge_file_uses_enqueue_or_dispatch(monkeypatch):
    """Upload entrypoint must go through scheduler.enqueue_or_dispatch."""
    from bisheng.knowledge.domain.services import knowledge_service as svc

    monkeypatch.setattr(
        svc.KnowledgeService,
        "save_knowledge_file",
        classmethod(
            lambda cls, *a, **kw: (
                MagicMock(),
                [],
                [
                    MagicMock(id=1, user_id=10, file_name="a.pdf"),
                    MagicMock(id=2, user_id=10, file_name="b.txt"),
                ],
                ["pk1", "pk2"],
            )
        ),
    )
    monkeypatch.setattr(svc.KnowledgeService, "upload_knowledge_file_hook", classmethod(lambda *a, **kw: None))

    captured = []

    def fake(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.enqueue_or_dispatch", fake)

    req = MagicMock(callback_url="cb")
    svc.KnowledgeService.process_knowledge_file(
        request=MagicMock(),
        login_user=MagicMock(user_id=10),
        background_tasks=MagicMock(),
        req_data=req,
    )

    assert len(captured) == 2
    assert captured[0]["user_id"] == 10
    assert captured[0]["file_id"] == 1
    assert captured[0]["file_name"] == "a.pdf"
    assert captured[0]["preview_cache_key"] == "pk1"
    assert captured[0]["callback_url"] == "cb"


async def test_aprocess_knowledge_file_uses_enqueue_or_dispatch(monkeypatch):
    from bisheng.knowledge.domain.services import knowledge_service as svc

    async def fake_save(cls, *a, **kw):
        return (MagicMock(), [], [MagicMock(id=5, user_id=20, file_name="img.png")], ["pk"])

    monkeypatch.setattr(svc.KnowledgeService, "asave_knowledge_file", classmethod(fake_save))
    monkeypatch.setattr(svc.KnowledgeService, "upload_knowledge_file_hook", classmethod(lambda *a, **kw: None))

    captured = []
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.enqueue_or_dispatch",
        lambda **kw: captured.append(kw),
    )

    await svc.KnowledgeService.aprocess_knowledge_file(
        request=MagicMock(),
        login_user=MagicMock(user_id=20),
        background_tasks=MagicMock(),
        req_data=MagicMock(callback_url=""),
    )

    assert captured == [
        {"user_id": 20, "file_id": 5, "file_name": "img.png", "preview_cache_key": "pk", "callback_url": ""},
    ]
