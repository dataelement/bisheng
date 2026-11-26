"""Dispatch latency contract: a committed operation is woken immediately.

The remote library used to be created only when the 30s recovery sweep noticed
the ledger row (and the project step waited for the next sweep again), so a new
space appeared in WeKnora about a minute late. Committing must wake the worker
once, while the sweep stays the safety net for a broker that is down.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def api():
    from bisheng.knowledge.application import provider_provisioning

    return provider_provisioning


def ops():
    from bisheng.worker.knowledge import provider_operations

    return provider_operations


def catalog():
    m = api().ModelProof
    return {
        k: m(k, kind, "v1", 7, "org", True, dimension, images)
        for k, kind, dimension, images in [
            ("L", "chat", None, False),
            ("E", "embedding", 768, False),
            ("V", "vision", None, True),
        ]
    }


def proof():
    return api().PresetProof(
        catalog(),
        True,
        "controlled sample",
        ("label",),
        ("a", "b"),
        (("a", "related", "b"),),
        "d" * 64,
    )


def preset(**changes):
    return api().Preset(
        **{
            "tenant_id": 17,
            "instance_id": 7,
            "scope": "org",
            "revision": 3,
            "summary": "L",
            "embedding": "E",
            "vision": "V",
            "chunk_size": 512,
            "overlap": 32,
            **changes,
        }
    )


async def test_committed_create_is_dispatched_immediately(monkeypatch):
    repo, remote = AsyncMock(), AsyncMock()
    service = api().ProviderProvisioning(repo, remote, AsyncMock(return_value=True), AsyncMock())
    config = api().preflight(preset(), proof())
    op = SimpleNamespace(operation_id="op-1", tenant_id=17, revision=1, state="pending")
    repo.replay.return_value = None
    repo.reserve_create.return_value = op
    remote.probe_preset.return_value = proof()
    wakes = []
    monkeypatch.setattr(ops(), "wake_provider_operation", lambda **kwargs: wakes.append(kwargs) or True)

    result = await service.create(
        tenant_id=17,
        expected_tenant=17,
        actor=3,
        key="q",
        space=api().SpaceSpec("space"),
        preset=preset(),
        summary=config,
    )
    assert result is op
    assert wakes == [{"tenant_id": 17, "operation_id": "op-1", "expected_revision": 1}]


async def test_an_idempotent_replay_is_not_dispatched(monkeypatch):
    """The replay already has its own wakeup; a second one would duplicate work."""
    repo, remote = AsyncMock(), AsyncMock()
    service = api().ProviderProvisioning(repo, remote, AsyncMock(return_value=True), AsyncMock())
    repo.replay.return_value = SimpleNamespace(operation_id="already", state="succeeded")
    wakes = []
    monkeypatch.setattr(ops(), "wake_provider_operation", lambda **kwargs: wakes.append(kwargs) or True)

    await service.create(
        tenant_id=17,
        expected_tenant=17,
        actor=3,
        key="q",
        space=api().SpaceSpec("space"),
        preset=preset(),
        summary={},
    )
    assert wakes == []
    repo.reserve_create.assert_not_awaited()


async def test_a_settings_write_is_dispatched_immediately(monkeypatch):
    repo, remote = AsyncMock(), AsyncMock()
    service = api().ProviderProvisioning(repo, remote, AsyncMock(return_value=True), AsyncMock())
    repo.replay.return_value = None
    repo.active_target.return_value = SimpleNamespace(
        remote_kb_id="k",
        provider_instance_id=7,
        remote_scope_id="org",
        revision=3,
        pending=None,
        tenant_id=17,
        generation=1,
        capability_revision=3,
        space_id=5,
    )
    remote.probe_settings.return_value = ({}, 4)
    op = SimpleNamespace(operation_id="op-2", tenant_id=17, revision=1, state="pending")
    repo.reserve_settings.return_value = op
    wakes = []
    monkeypatch.setattr(ops(), "wake_provider_operation", lambda **kwargs: wakes.append(kwargs) or True)

    await service.settings(
        tenant_id=17,
        expected_tenant=17,
        actor=3,
        space_id=5,
        key="p",
        expected_revision=3,
        patch={"wiki_model_id": None},
    )
    assert wakes == [{"tenant_id": 17, "operation_id": "op-2", "expected_revision": 1}]


@pytest.mark.parametrize(
    "state,delay,chained",
    [
        ("applying", 0, True),
        ("pending", 0, True),
        ("reconciling", 0, True),
        ("applying", 5, False),  # a retry keeps its own backoff
        ("succeeded", 0, False),
        ("failed", 0, False),
        ("manual_review", 0, False),
    ],
)
def test_only_immediate_phase_transitions_chain(state, delay, chained):
    assert ops().should_chain_wakeup(state=state, delay=delay) is chained


def test_the_wakeup_binds_tenant_and_revision(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ops().advance_provider_operation,
        "apply_async",
        lambda **kwargs: calls.append(kwargs),
    )
    assert ops().wake_provider_operation(tenant_id=17, operation_id="op-3", expected_revision=2) is True
    assert calls == [
        {
            "kwargs": {"operation_id": "op-3", "expected_revision": 2},
            "headers": {"tenant_id": 17},
            "queue": "knowledge_celery",
            "retry": False,
        }
    ]


def test_a_broker_failure_is_not_fatal(monkeypatch):
    """The committed request already succeeded; the sweep will pick the row up."""

    def boom(**kwargs):
        raise OSError("broker down")

    monkeypatch.setattr(ops().advance_provider_operation, "apply_async", boom)
    assert ops().wake_provider_operation(tenant_id=17, operation_id="op-4", expected_revision=1) is False
