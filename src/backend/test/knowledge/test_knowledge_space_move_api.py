"""F034 — move endpoint contract tests (signature-level, AST-based).

Mirrors test_list_children_endpoint.py: importing the FastAPI app pulls a long
chain of repo modules, so we verify the endpoint↔service wiring structurally.
Behavioural coverage is in test_knowledge_space_move.py (service layer).
"""

import ast
import inspect
from pathlib import Path

from bisheng.knowledge.domain.schemas.knowledge_space_schema import FileMoveReq

_BACKEND_ROOT = Path(__file__).resolve().parents[2] / "bisheng"


def _find_func(source: str, name: str):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def test_move_request_schema_shape():
    """FileMoveReq carries the full move contract (design §4.2)."""
    fields = FileMoveReq.model_fields
    assert {"items", "target_space_id", "target_folder_id", "skip_invalid"} <= set(fields)
    # defaults: optional target folder (root) + non-skipping by default
    assert fields["target_folder_id"].default is None
    assert fields["skip_invalid"].default is False


def test_move_endpoint_registered_and_delegates():
    """POST /{space_id}/files/move exists, takes FileMoveReq, and calls move_items."""
    ep_file = _BACKEND_ROOT / "knowledge" / "api" / "endpoints" / "knowledge_space.py"
    source = ep_file.read_text()
    fn = _find_func(source, "move_file_folder")
    assert fn is not None, "move_file_folder endpoint not found"
    # decorated with the move route
    decos = "\n".join(ast.get_source_segment(source, d) for d in fn.decorator_list)
    assert "files/move" in decos
    # request body typed as FileMoveReq
    annotations = {a.arg: getattr(a.annotation, "id", None) for a in fn.args.args}
    assert annotations.get("req") == "FileMoveReq"
    # body delegates to the service's move_items
    assert "move_items" in ast.get_source_segment(source, fn)


def test_service_move_items_signature():
    """KnowledgeSpaceService.move_items must accept the move contract args."""
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    sig = inspect.signature(KnowledgeSpaceService.move_items)
    params = set(sig.parameters)
    assert {"space_id", "items", "target_space_id", "target_folder_id", "skip_invalid"} <= params
