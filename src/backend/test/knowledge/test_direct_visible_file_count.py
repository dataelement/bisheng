"""当前目录文件数只计入当前用户可见的直接子文件."""

from types import SimpleNamespace

import pytest

from bisheng.knowledge.domain.services.direct_visible_file_count import count_visible_direct_files


def _file(file_id: int) -> SimpleNamespace:
    return SimpleNamespace(id=file_id, update_time=file_id, file_name=f"{file_id}.md")


@pytest.mark.asyncio
async def test_count_skips_files_the_viewer_cannot_see():
    cursors = []

    async def list_batch(cursor):
        cursors.append(cursor)
        if cursor is None:
            return [_file(1), _file(2)]
        if cursor[-1] == 2:
            return [_file(3)]
        return []

    async def filter_visible(items):
        return [item for item in items if item.id != 2]

    total = await count_visible_direct_files(
        list_batch=list_batch,
        filter_visible=filter_visible,
        batch_size=2,
    )

    assert total == 2
    assert cursors[0] is None
    assert cursors[1][-1] == 2
