"""F034 Wave 5 — folder-upload endpoint contract tests (signature-level, AST-based).

Mirrors test_knowledge_space_move_api.py: importing the FastAPI app pulls a long
chain of repo modules, so we verify the endpoint↔service wiring structurally.
Behavioural coverage is in test_knowledge_space_folder_upload.py (service layer).
"""

import ast
import inspect
from pathlib import Path

from bisheng.knowledge.domain.schemas.knowledge_space_schema import FolderUploadItem, FolderUploadReq

_BACKEND_ROOT = Path(__file__).resolve().parents[2] / "bisheng"


def _find_func(source: str, name: str):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def test_folder_upload_request_schema_shape():
    """FolderUploadReq carries the folder-upload contract (design §9.4)."""
    req_fields = FolderUploadReq.model_fields
    assert {"parent_id", "items"} <= set(req_fields)
    assert req_fields["parent_id"].default is None
    item_fields = FolderUploadItem.model_fields
    assert {"file_path", "relative_path", "size"} <= set(item_fields)
    assert item_fields["size"].default == 0


def test_folder_upload_endpoint_registered_and_delegates():
    """POST /{space_id}/folders/upload exists, takes FolderUploadReq, calls upload_folder_items."""
    ep_file = _BACKEND_ROOT / "knowledge" / "api" / "endpoints" / "knowledge_space.py"
    source = ep_file.read_text()
    fn = _find_func(source, "upload_folder")
    assert fn is not None, "upload_folder endpoint not found"
    decos = "\n".join(ast.get_source_segment(source, d) for d in fn.decorator_list)
    assert "folders/upload" in decos
    annotations = {a.arg: getattr(a.annotation, "id", None) for a in fn.args.args}
    assert annotations.get("req") == "FolderUploadReq"
    assert "upload_folder_items" in ast.get_source_segment(source, fn)


def test_service_upload_folder_items_signature():
    """KnowledgeSpaceService.upload_folder_items must accept the upload contract args."""
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    sig = inspect.signature(KnowledgeSpaceService.upload_folder_items)
    params = set(sig.parameters)
    assert {"knowledge_id", "items", "parent_id"} <= params
