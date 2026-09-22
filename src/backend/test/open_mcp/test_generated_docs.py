from pathlib import Path

from bisheng.open_mcp.registry import TOOL_DEFINITIONS

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DOC = BACKEND_ROOT / "docs/api/open-mcp.md"


def test_public_doc_covers_the_exact_registry_allowlist():
    content = PUBLIC_DOC.read_text(encoding="utf-8")

    assert "10 个知识资源和知识文件工具" in content
    assert "https://<BISHENG_HOST>/api/v2/mcp" in content
    for definition in TOOL_DEFINITIONS:
        assert content.count(f"`{definition.name}`") >= 1


def test_public_doc_covers_contract_and_security_boundaries():
    content = PUBLIC_DOC.read_text(encoding="utf-8")

    assert "Authorization: Bearer <credential>" in content
    assert "inputSchema" in content
    assert "outputSchema" in content
    assert "structuredContent" in content
    assert '"success":true' in content
    assert '"code": "INVALID_ARGUMENT"' in content
    assert "不暴露 `callback_url`" in content
    assert "不转成 `permission_ids`" in content
    assert "TagItem[]" in content
    assert "<BISHENG_API_KEY>" in content
    assert "关键输出字段语义" in content
    assert "`is_released` (不是 `is_release`)" in content
    assert "仅 `type=3` 有业务意义" in content
