"""T503: default JSON compatibility conversion belongs to frozen offline M3.

覆盖 AC: AC-37, AC-79, AC-83, AC-89
Inspect the startup function without initializing middleware or running migration.
"""

import ast
from pathlib import Path


def test_api_startup_cannot_rewrite_default_payload_before_reference_baseline():
    tree = ast.parse((Path(__file__).parents[2] / "bisheng/main.py").read_text())
    lifespan = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan")
    called = {
        node.func.id
        for node in ast.walk(lifespan)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not called.intersection({"backfill_linsight_default_model", "backfill_chat_default_model"})
    assert "_register_resource_reference_composition" in called
    assert "init_default_data" in called
