"""T505: actual API/worker composition installs all source families safely.

覆盖 AC: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-92
Construction is tested without SQL, permissions transport or migration I/O.
"""

import pytest

from bisheng.app_publish.application.reference_source_owner import HostedAppReferenceSourceOwner
from bisheng.channel.application.reference_source_owner import ChannelReferenceSourceOwner
from bisheng.knowledge.application import model_reference_read as knowledge_access
from bisheng.knowledge.application.reference_read_identity import KnowledgeModelReadIdentityPort
from bisheng.knowledge.application.reference_source_owner import KnowledgeReferenceSourceOwner
from bisheng.llm.application import model_default_read as defaults_access
from bisheng.llm.application.model_default_read_identity import ModelDefaultReadIdentityPort
from bisheng.llm.application.model_default_source_owner import ModelDefaultSourceOwner
from bisheng.resource_reference import composition, read_composition
from bisheng.resource_reference.application import access, source_access
from bisheng.resource_reference.application.contracts import SourceType, TargetType


@pytest.fixture(autouse=True)
def isolated_process_graphs(monkeypatch):
    for module, names in [
        (composition, ("_runtime",)),
        (read_composition, ("_runtime", "_knowledge_model_runtime", "_model_default_runtime")),
        (access, ("_runtime",)),
        (source_access, ("_runtime",)),
        (knowledge_access, ("_runtime",)),
        (defaults_access, ("_runtime",)),
    ]:
        for name in names:
            monkeypatch.setattr(module, name, None, raising=False)


async def test_register_installs_actual_remaining_owners_and_distinct_private_graphs(monkeypatch):
    from bisheng.core import database
    from bisheng.llm.application import source_read_target_owner

    def unexpected(*args, **kwargs):
        raise AssertionError("composition must not initialize business or permission I/O")
    monkeypatch.setattr(database, "get_async_db_session", unexpected)
    monkeypatch.setattr(database, "get_sync_db_session", unexpected)
    monkeypatch.setattr(source_read_target_owner, "get_permission_relation_api", unexpected)
    composition.register()
    public = await source_access.get_reference_read_runtime()
    assert isinstance(public.verifier._owners[SourceType.HOSTED_APP_VERSION], HostedAppReferenceSourceOwner)
    assert isinstance(public.verifier._owners[SourceType.CHANNEL_SYNC], ChannelReferenceSourceOwner)
    assert isinstance(public.verifier._owners[SourceType.KNOWLEDGE], KnowledgeReferenceSourceOwner)
    assert SourceType.MODEL_DEFAULT not in public.verifier._owners
    knowledge = knowledge_access.get_knowledge_model_read_runtime_sync()
    defaults = defaults_access.get_model_default_read_runtime()
    assert isinstance(knowledge.identity_port, KnowledgeModelReadIdentityPort)
    assert isinstance(defaults.identity_port, ModelDefaultReadIdentityPort)
    assert set(knowledge.core.verifier._owners) == {SourceType.KNOWLEDGE}
    assert set(defaults.core.verifier._owners) == {SourceType.MODEL_DEFAULT}
    assert isinstance(defaults.core.verifier._owners[SourceType.MODEL_DEFAULT], ModelDefaultSourceOwner)
    assert knowledge.core.verifier._owners[SourceType.KNOWLEDGE].identity_port is knowledge.identity_port
    assert defaults.core.verifier._owners[SourceType.MODEL_DEFAULT].identity_port is defaults.identity_port
    assert knowledge.core.verifier._identity_port is knowledge.identity_port
    assert defaults.core.verifier._identity_port is defaults.identity_port
    assert len({id(public.verifier), id(knowledge.core.verifier), id(defaults.core.verifier)}) == 3
    for core in (public, knowledge.core, defaults.core):
        owner = core.target_owners[TargetType.MODEL]
        assert owner.verifier is core.verifier is core.repository.verifier
        assert owner.legacy_evidence.repository.verifier is core.verifier
    composition.register()
    assert await source_access.get_reference_read_runtime() is public
    assert knowledge_access.get_knowledge_model_read_runtime_sync() is knowledge
    assert defaults_access.get_model_default_read_runtime() is defaults
    assert access.get_reference_binding_runtime_sync() is await access.get_reference_binding_runtime()
