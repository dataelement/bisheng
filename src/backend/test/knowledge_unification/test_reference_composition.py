"""T290: API and worker install real business Owners, never test defaults.

覆盖 AC: AC-87, AC-88, AC-89
Bootstrap hooks run in isolation; this does not start application services.
"""

import ast
from pathlib import Path

import pytest

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.resource_reference.application import access
from bisheng.resource_reference.application.contracts import TargetType


@pytest.fixture(autouse=True)
def isolated_access(monkeypatch):
    monkeypatch.setattr(access, "_runtime", None)


async def test_missing_composition_fails_closed():
    with pytest.raises(ReferenceCoverageNotReadyError):
        await access.get_reference_binding_runtime()


async def test_composition_has_real_shared_knowledge_owner_and_frozen_evidence(monkeypatch):
    from bisheng.knowledge.application.reference_legacy_evidence import KnowledgeLegacyReferenceEvidence
    from bisheng.knowledge.application.reference_target_owner import KnowledgeReferenceTargetOwner
    from bisheng.llm.application.reference_target_owner import DefaultModelReferenceSharing, ModelReferenceTargetOwner
    from bisheng.resource_reference import composition

    monkeypatch.setattr(composition, "_runtime", None)
    composition.register()
    runtime = await access.get_reference_binding_runtime()
    owners = runtime.verifier._owners
    knowledge = owners[TargetType.KNOWLEDGE_SPACE]
    model = owners[TargetType.MODEL]
    assert isinstance(knowledge, KnowledgeReferenceTargetOwner)
    assert knowledge is owners[TargetType.KNOWLEDGE_FILE]
    assert isinstance(model, ModelReferenceTargetOwner)
    assert isinstance(knowledge.legacy_evidence, KnowledgeLegacyReferenceEvidence)
    assert model.legacy_evidence is knowledge.legacy_evidence
    assert isinstance(model.sharing, DefaultModelReferenceSharing)
    assert runtime.repository.verifier is runtime.verifier
    assert runtime.bindings.verifier is runtime.verifier
    composition.register()
    assert await access.get_reference_binding_runtime() is runtime


@pytest.mark.parametrize("module,entry", [("main.py", "lifespan"), ("worker/main.py", "on_worker_init")])
async def test_real_api_and_worker_registration_hooks_install_runtime(module, entry, monkeypatch):
    from bisheng.resource_reference import composition

    monkeypatch.setattr(composition, "_runtime", None)
    root = Path(__file__).resolve().parents[2] / "bisheng"
    path = root / module
    tree = ast.parse(path.read_text())
    helper_name = "_register_resource_reference_composition"
    helper = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == helper_name), None)
    assert helper is not None, f"{module} must install reference composition"
    caller = next(
        node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == entry
    )
    assert any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == helper_name
        for node in ast.walk(caller)
    )
    namespace = {}
    exec(compile(ast.Module(body=[helper], type_ignores=[]), str(path), "exec"), namespace)
    namespace[helper_name]()
    runtime = await access.get_reference_binding_runtime()
    assert runtime.repository.verifier is runtime.verifier
