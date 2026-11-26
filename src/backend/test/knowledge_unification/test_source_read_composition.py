"""T386: both production bootstrap paths install the actual read graph."""

import ast
from pathlib import Path

import pytest

from bisheng.assistant.application.reference_source_owner import AssistantReferenceSourceOwner
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.knowledge.application.reference_read_legacy_evidence import KnowledgeReferenceReadLegacyEvidence
from bisheng.knowledge.application.source_read_target_owner import KnowledgeSourceReadTargetOwner
from bisheng.llm.application.source_read_target_owner import ModelSourceReadTargetOwner
from bisheng.resource_reference import read_composition
from bisheng.resource_reference.application import source_access
from bisheng.resource_reference.application.contracts import SourceType, TargetType
from bisheng.resource_reference.application.read_identity import AuthenticatedSourceReadIdentity
from bisheng.workflow.application.reference_source_owner import WorkflowReferenceSourceOwner


@pytest.fixture(autouse=True)
def isolated_read_graph(monkeypatch):
    monkeypatch.setattr(source_access, "_runtime", None)
    monkeypatch.setattr(read_composition, "_runtime", None)


async def test_read_access_is_closed_until_actual_composition():
    with pytest.raises(ReferenceCoverageNotReadyError):
        await source_access.get_reference_read_runtime()


async def test_register_uses_actual_business_owners_and_one_private_authority():
    read_composition.register()
    runtime = await source_access.get_reference_read_runtime()
    verifier = runtime.verifier
    assert isinstance(verifier._owners[SourceType.ASSISTANT], AssistantReferenceSourceOwner)
    assert isinstance(verifier._owners[SourceType.WORKFLOW_VERSION], WorkflowReferenceSourceOwner)
    assert isinstance(verifier._identity_port, AuthenticatedSourceReadIdentity)
    knowledge = runtime.target_owners[TargetType.KNOWLEDGE_SPACE]
    model = runtime.target_owners[TargetType.MODEL]
    assert knowledge is runtime.target_owners[TargetType.KNOWLEDGE_FILE]
    assert isinstance(knowledge, KnowledgeSourceReadTargetOwner)
    assert isinstance(model, ModelSourceReadTargetOwner)
    assert knowledge.verifier is model.verifier is runtime.repository.verifier is verifier
    assert isinstance(knowledge.legacy_evidence, KnowledgeReferenceReadLegacyEvidence)
    assert model.legacy_evidence is knowledge.legacy_evidence
    assert knowledge.legacy_evidence.repository.verifier is verifier
    read_composition.register()
    assert await source_access.get_reference_read_runtime() is runtime


@pytest.mark.parametrize("module, entry", [("main.py", "lifespan"), ("worker/main.py", "on_worker_init")])
async def test_actual_api_and_worker_hooks_also_install_read_runtime(module, entry):
    # Execute the real bootstrap helper in isolation, not the full middleware
    # environment. This proves the registration call graph, not service E2E.
    root = Path(__file__).resolve().parents[2] / "bisheng"
    path = root / module
    tree = ast.parse(path.read_text())
    name = "_register_resource_reference_composition"
    helper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    caller = next(
        node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == entry
    )
    assert any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
        for node in ast.walk(caller)
    )
    namespace = {}
    exec(compile(ast.Module(body=[helper], type_ignores=[]), str(path), "exec"), namespace)
    namespace[name]()
    runtime = await source_access.get_reference_read_runtime()
    assert runtime.repository.verifier is runtime.verifier
