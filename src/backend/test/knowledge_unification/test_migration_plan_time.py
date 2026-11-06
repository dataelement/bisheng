"""Real M2 plans must freeze times representable by existing DateTime columns."""

import json
from datetime import datetime

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.application.unification_inventory_codec import digest
from bisheng.knowledge.domain.schemas.unification_conversion import initial_version_templates
from test.knowledge_unification import test_migration_inventory_application as inventory

resource_native = inventory.resource_native
native = inventory.native
module = inventory.module
complete = inventory.complete
transport = inventory.transport


@pytest.mark.parametrize("microsecond", [0, 123456, 999999])
async def test_real_m2_freezes_one_representable_time_and_matching_templates(
    module, complete, transport, monkeypatch, microsecond
):
    now = datetime(2026, 11, 7, 3, 4, 5, microsecond)
    planned = now.replace(microsecond=0)
    calls = []

    def clock():
        calls.append(True)
        return now

    monkeypatch.setattr(module, "unification_now", clock)
    await complete.insert(inventory.resources.Knowledge, [inventory.resources.resource(1000, 1, model=None)])
    await complete.insert(inventory.resources.KnowledgeFile, [inventory.resources.file(2, 1, knowledge_id=1000)])
    async with AsyncSession(complete.engine) as session, session.begin():
        await inventory.application(module, transport).arun(session, **transport.inputs)
    commands = [
        row
        for content in transport.objects.values()
        for row in json.loads(content)["records"]
        if row.get("record_type") == "initialize_v1"
    ]
    assert calls == [True]
    assert {row["tenant_id"] for row in commands} == {1, 101}
    assert {row["planned_at"] for row in commands} == {planned.isoformat()}
    for row in commands:
        document, version = initial_version_templates(
            knowledge_id=row["knowledge_id"],
            file_id=row["file_id"],
            file_level_path=row["file_level_path"],
            level=row["level"],
            natural_key=row["natural_key"],
            planned_at=planned,
        )
        assert row["document_template_digest"] == digest(document)
        assert row["version_template_digest"] == digest(version)
