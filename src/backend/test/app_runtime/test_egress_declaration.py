"""``egress.domains`` reaching the orchestrator (F054 T077 / AC-16).

The enforcement lives in runtime-manager; what the backend owes it is one
input — *which* domains this version declared. Two ways that goes wrong and
neither shows up anywhere else:

* the key is dropped on the way, and every hosted application silently loses
  access to its own API the moment the whitelist is switched on;
* the key is read carelessly out of a JSON column written by some older version
  of the publish pipeline, and a malformed declaration crashes a start.

So this file pins the reader's behaviour on hostile shapes and pins the fact
that the value is actually in the intent.
"""

from __future__ import annotations

import pytest

from bisheng.app_publish.domain.schemas.app_manifest import egress_domains_of
from bisheng.app_runtime.domain.constants import AppState

# No module-level ``pytest.mark.asyncio``: this file mixes sync and async tests
# and ``asyncio_mode=auto`` already covers the async half. Marking the sync ones
# produces a warning per test and nothing else.


def _deploy_kwargs(fake_orchestrator) -> dict:
    return next(kwargs for name, kwargs in fake_orchestrator.calls if name == "deploy")


# ---------------------------------------------------------------------------
# the reader
# ---------------------------------------------------------------------------


def test_a_declared_list_comes_through_trimmed():
    assert egress_domains_of({"egress": {"domains": [" api.openai.com ", "*.example.com"]}}) == [
        "api.openai.com",
        "*.example.com",
    ]


@pytest.mark.parametrize(
    "manifest",
    [
        {},
        {"egress": None},
        {"egress": {}},
        {"egress": {"domains": None}},
        {"egress": {"domains": "api.openai.com"}},  # a string, not a list
        {"egress": []},
        None,
    ],
)
def test_every_unreadable_shape_yields_nothing_rather_than_a_guess(manifest):
    """Denied-by-default is the right failure: visible, reported, republishable."""
    assert egress_domains_of(manifest) == []


def test_non_string_entries_are_dropped_not_stringified():
    """``str(None)`` would put the literal text ``None`` on a whitelist."""
    assert egress_domains_of({"egress": {"domains": ["a.example.com", None, 42, "", "  "]}}) == ["a.example.com"]


# ---------------------------------------------------------------------------
# the wire
# ---------------------------------------------------------------------------


async def test_the_start_path_sends_the_declared_domains(app_db, app_factory, app_owner, fake_orchestrator):
    from bisheng.app_runtime.domain.services.app_state_service import AppStateService
    from bisheng.database.models.app_version import AppVersionDao

    app, version = await app_factory(state=AppState.PENDING_CAPACITY.value)
    async with app_db() as session:
        row = await AppVersionDao.aget(session, app.id, version.id)
        row.manifest = {**row.manifest, "egress": {"domains": ["api.openai.com"]}}
        session.add(row)
        await session.commit()

    await AppStateService.manual_publish(app.id, actor=app_owner.payload)

    assert _deploy_kwargs(fake_orchestrator)["egress_domains"] == ["api.openai.com"]


async def test_a_version_that_declares_nothing_still_sends_the_key(app_factory, app_owner, fake_orchestrator):
    """An absent key would read to the manager as "an older backend" rather than
    as "this application declared nothing", and the two must not be the same."""
    from bisheng.app_runtime.domain.services.app_state_service import AppStateService

    app, _version = await app_factory(state=AppState.PENDING_CAPACITY.value)

    await AppStateService.manual_publish(app.id, actor=app_owner.payload)

    assert _deploy_kwargs(fake_orchestrator)["egress_domains"] == []
