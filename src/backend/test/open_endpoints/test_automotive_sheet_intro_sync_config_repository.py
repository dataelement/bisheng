from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.open_endpoints.domain.repositories.implementations.automotive_sheet_intro_sync_config_repository_impl import (
    AutomotiveSheetIntroSyncConfigRepositoryImpl,
)
from bisheng.open_endpoints.domain.repositories.interfaces.automotive_sheet_intro_sync_config_repository import (
    automotive_sheet_intro_sync_physical_key,
)


def test_automotive_sheet_intro_sync_physical_key_pattern():
    assert automotive_sheet_intro_sync_physical_key(1) == "automotive_sheet_intro_sync"
    assert automotive_sheet_intro_sync_physical_key(5) == "automotive_sheet_intro_sync:t:5"
    with pytest.raises(ValueError):
        automotive_sheet_intro_sync_physical_key(0)


async def test_config_repository_flushes_without_committing():
    session = MagicMock()
    session.exec = AsyncMock(return_value=MagicMock(first=MagicMock(return_value=None)))
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    repository = AutomotiveSheetIntroSyncConfigRepositoryImpl(session)

    await repository.write_value(5, "{}")

    session.flush.assert_awaited_once()
    session.commit.assert_not_awaited()
    added = session.add.call_args.args[0]
    assert added.key == "automotive_sheet_intro_sync:t:5"
    assert added.value == "{}"
