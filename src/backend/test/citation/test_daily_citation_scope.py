"""F075 — the daily chat shares the F069 session handle table.

AC-01: one source keeps one number across daily turns and task turns of the
same conversation. The trap pinned here (design §5 #1): the allocator pins the
task-mode contract (``meta:enabled``) when it creates the table. If the daily
chat created it with that pin, the task-mode kill switch would stop working for
the conversation — so the daily scope never pins.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.citation.domain.services import citation_handle_service as svc
from bisheng.citation.domain.services import linsight_citation_scope as scope_mod
from bisheng.citation.domain.services.citation_handle_service import assign_handles
from bisheng.citation.domain.services.daily_citation_scope import DailyCitationScope
from bisheng.citation.domain.services.linsight_citation_scope import LinsightCitationScope


class FakeRedis:
    def __init__(self):
        self.store: dict[str, dict[str, str]] = {}

    def _h(self, name):
        return self.store.setdefault(name, {})

    async def ahget(self, name, key):
        return self._h(name).get(key)

    async def ahgetall(self, name):
        return dict(self._h(name))

    async def ahincrby(self, name, key, amount=1):
        h = self._h(name)
        h[key] = str(int(h.get(key, "0")) + amount)
        return int(h[key])

    async def ahsetnx(self, name, key, value):
        h = self._h(name)
        if key in h:
            return False
        h[key] = value
        return True

    async def ahset(self, name, key=None, value=None, mapping=None, items=None, expiration=3600):
        h = self._h(name)
        if mapping:
            h.update(mapping)
        if key is not None:
            h[key] = value
        return 1

    async def aexpire_key(self, key, expiration):
        return None


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch):
    fake = FakeRedis()
    monkeypatch.setattr(svc, "get_redis_client", AsyncMock(return_value=fake))
    monkeypatch.setattr(scope_mod, "get_redis_client", AsyncMock(return_value=fake))
    return fake


def _rag(citation_id: str, item_id: str, document_id: int):
    return SimpleNamespace(
        key=f"{citation_id}:{item_id}",
        citationId=citation_id,
        itemId=item_id,
        type=SimpleNamespace(value="rag"),
        sourcePayload=SimpleNamespace(
            documentId=document_id,
            documentName="制度.docx",
            knowledgeName="制度库",
            items=[SimpleNamespace(itemId=item_id, page=None, chunkIndex=int(item_id))],
        ),
    )


async def test_daily_scope_creating_the_table_does_not_pin_the_task_contract(redis):
    scope = DailyCitationScope("chat-1")

    handles = await assign_handles(scope, [_rag("knowledgesearch_aaaa1111", "0", 11)])

    assert handles == {"knowledgesearch_aaaa1111:0": "S1"}
    assert "meta:enabled" not in redis.store["linsight:cite_handles:chat-1"]
    assert scope.handles == {"S1": "knowledgesearch_aaaa1111:0"}


async def test_task_scope_still_pins_when_it_creates_the_table(redis):
    scope = LinsightCitationScope(svid="sv-1", session_id="chat-2", enabled=True)

    await assign_handles(scope, [_rag("knowledgesearch_aaaa1111", "0", 11)])

    assert redis.store["linsight:cite_handles:chat-2"]["meta:enabled"] == "1"


async def test_same_source_gets_the_same_number_across_modes_and_turns(redis):
    task = LinsightCitationScope(svid="sv-1", session_id="chat-3", enabled=True)
    await assign_handles(task, [_rag("knowledgesearch_aaaa1111", "0", 11)])

    # a later daily turn retrieves the same chunk under a fresh registry id
    daily = DailyCitationScope("chat-3")
    await daily.load()
    handles = await assign_handles(
        daily, [_rag("knowledgesearch_bbbb2222", "0", 11), _rag("knowledgesearch_cccc3333", "4", 12)]
    )

    assert handles == {"knowledgesearch_bbbb2222:0": "S1", "knowledgesearch_cccc3333:4": "S2"}
    # the number is the task turn's; it now points at this turn's fresh key so
    # the answer binds to an item collected this turn ...
    assert daily.handles["S1"] == "knowledgesearch_bbbb2222:0"
    # ... while the task turn's key still maps back for history replay
    assert daily.key_to_handle["knowledgesearch_aaaa1111:0"] == "S1"


async def test_load_failure_leaves_an_empty_usable_scope(monkeypatch):
    monkeypatch.setattr(svc, "get_redis_client", AsyncMock(side_effect=RuntimeError("redis down")))
    scope = DailyCitationScope("chat-4")

    await scope.load()

    assert scope.loaded is False
    assert scope.handles == {}
