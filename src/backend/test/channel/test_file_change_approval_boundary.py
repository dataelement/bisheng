from __future__ import annotations

from pathlib import Path


def test_channel_domain_does_not_depend_on_file_change_approval_module():
    backend_root = Path(__file__).resolve().parents[2]
    channel_root = backend_root / "bisheng" / "channel"
    forbidden = (
        "knowledge_space_file_change",
        "SYSTEM_FILE_CHANGE_SCENARIO_CODE",
        "file-change-configuration",
    )

    violations = []
    for path in channel_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for marker in forbidden:
            if marker in source:
                violations.append(f"{path.relative_to(backend_root)}: {marker}")

    assert violations == []


def test_file_change_routes_remain_outside_channel_namespace():
    from bisheng.knowledge.api.endpoints.knowledge_space_file_change import router

    paths = [route.path for route in router.routes]

    assert paths
    assert all(not path.startswith("/channel") for path in paths)
