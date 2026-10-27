from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.permission.application.roster_search import search_source_page


async def test_search_reaches_people_beyond_first_page_without_losing_cursor():
    rows = [
        SimpleNamespace(
            source_id=i,
            subject_type="user",
            subject_id=str(i),
            model_key="view",
            source_type="DIRECT",
            inherited_from=None,
        )
        for i in range(1, 5)
    ]

    async def load(**kwargs):
        remaining = [r for r in rows if r.source_id > kwargs["after_id"]]
        return remaining[:2], len(remaining) > 2

    runtime = SimpleNamespace(list_permission_sources_page=load)
    subjects = SimpleNamespace(display_names=AsyncMock(return_value={("user", "3"): "Alice", ("user", "4"): "Alice 2"}))
    selected, more = await search_source_page(
        runtime=runtime,
        subjects=subjects,
        actor=None,
        target=None,
        after_id=0,
        page_size=1,
        keyword="alice",
        subject_type="user",
        model_names={},
    )
    assert [r.source_id for r in selected] == [3]
    assert more
    selected, more = await search_source_page(
        runtime=runtime,
        subjects=subjects,
        actor=None,
        target=None,
        after_id=3,
        page_size=1,
        keyword="alice",
        subject_type="user",
        model_names={},
    )
    assert [r.source_id for r in selected] == [4]
    assert not more
