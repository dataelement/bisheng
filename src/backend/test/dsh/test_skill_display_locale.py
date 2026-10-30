from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.dsh.api.endpoints.skills import list_skills
from bisheng.linsight.domain.services.user_skills import UserSkillsService


@pytest.mark.parametrize("name", ["bisheng-docx", "bisheng-pptx", "bisheng-xlsx", "future-skill"])
@pytest.mark.parametrize("source", ["builtin", "manual", "sop_migrated", "personal"])
async def test_skill_list_exposes_builtin_identity_from_stored_source(monkeypatch, name, source):
    record = SimpleNamespace(
        id=7,
        name=name,
        display_name="Configured title",
        description="Configured description",
        source=source,
        owner_user_id=None,
        content_hash="a" * 64,
        update_time=None,
        create_time=datetime(2026, 10, 30),
    )
    records = AsyncMock(return_value=[(record, False)])
    monkeypatch.setattr(UserSkillsService, "records", records)
    monkeypatch.setattr(
        "bisheng.dsh.api.endpoints.skills.SkillService",
        lambda **kwargs: SimpleNamespace(get_detail=AsyncMock(return_value=SimpleNamespace(preview="Body", files=[]))),
    )

    result = await list_skills(SimpleNamespace(user_id=12, tenant_id=2))

    records.assert_awaited_once_with(False)
    row = result.data[0]
    assert row["builtin_key"] == (name if source == "builtin" else None)
    assert row["source"] == ("personal" if source == "personal" else "platform")
    assert row["name"] == name
    assert row["display_name"] == record.display_name
    assert row["description"] == record.description
    assert row["id"] == 7
    assert row["enabled"] is False
    assert row["content_hash"] == record.content_hash
