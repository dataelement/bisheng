"""Portal QA citation enqueue keeps non-personal files and swallows queue failures."""

from types import SimpleNamespace

from bisheng.telemetry.domain.mid_table.knowledge_space_content import KnowledgeSpaceContentStat


async def test_enqueue_keeps_non_personal_files_once(monkeypatch):
    calls = []

    def build(file_id: int):
        levels = {11: "public", 12: "personal", 13: "team"}
        level = levels.get(file_id)
        return None if level is None else SimpleNamespace(space_level=level)

    async def enqueue(**kwargs):
        calls.append(kwargs)
        return True

    monkeypatch.setattr(KnowledgeSpaceContentStat, "enqueue_success_event_async", enqueue)

    queued = await KnowledgeSpaceContentStat.enqueue_portal_qa_citations_async(
        file_ids=[11, 11, 12, 0, 13, 99],
        user_id=7,
        record_builder=build,
    )

    assert queued == 2
    assert [call["file_id"] for call in calls] == [11, 13]
    assert {call["record_type"] for call in calls} == {"qa_citation_daily"}
    assert {call["event_type"] for call in calls} == {"portal_qa_citation"}


async def test_enqueue_failure_does_not_raise(monkeypatch):
    async def enqueue(**kwargs):
        raise RuntimeError("redis down")

    monkeypatch.setattr(KnowledgeSpaceContentStat, "enqueue_success_event_async", enqueue)

    queued = await KnowledgeSpaceContentStat.enqueue_portal_qa_citations_async(
        file_ids=[8],
        user_id=7,
        record_builder=lambda file_id: SimpleNamespace(space_level="department"),
    )

    assert queued == 0
