import importlib.util
from pathlib import Path

import pytest

from bisheng.open_mcp.registry import TOOL_REGISTRY

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = BACKEND_ROOT / "scripts/verify_open_mcp.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("verify_open_mcp", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verifier_allowlist_and_calls_are_read_only():
    script = _load_script()

    assert script.EXPECTED_TOOL_NAMES == frozenset(TOOL_REGISTRY)
    assert script.READ_ONLY_TOOL_NAMES == {
        "bisheng_knowledge_list",
        "bisheng_knowledge_retrieve",
        "bisheng_knowledge_file_list",
    }
    args = script._parser().parse_args(
        [
            "--url",
            "https://bisheng.example.com/api/v2/mcp",
            "--call-tool",
            "bisheng_knowledge_list",
            "--arguments-json",
            '{"page_size":1}',
        ]
    )
    assert args.arguments_json == {"page_size": 1}
    assert args.expected_profile == "full"


def test_verifier_detects_missing_and_unexpected_tools_for_exact_profiles():
    script = _load_script()

    missing, unexpected = script._tool_differences(
        script.EXPECTED_TOOL_NAMES - {"bisheng_knowledge_delete"},
        "full",
    )
    assert missing == ["bisheng_knowledge_delete"]
    assert unexpected == []

    missing, unexpected = script._tool_differences(
        script.READ_ONLY_TOOL_NAMES | {"bisheng_knowledge_delete"},
        "pat",
    )
    assert missing == []
    assert unexpected == ["bisheng_knowledge_delete"]


def test_verifier_scope_filtered_profile_only_rejects_out_of_allowlist_tools():
    script = _load_script()

    missing, unexpected = script._tool_differences(
        {"bisheng_knowledge_list", "not_a_f067_tool"},
        "scope-filtered",
    )
    assert missing == []
    assert unexpected == ["not_a_f067_tool"]


def test_verifier_rejects_write_tool_selection():
    script = _load_script()

    with pytest.raises(SystemExit):
        script._parser().parse_args(
            [
                "--url",
                "https://bisheng.example.com/api/v2/mcp",
                "--call-tool",
                "bisheng_knowledge_delete",
            ]
        )


def test_verifier_reports_auth_failure_without_leaking_token(monkeypatch, capsys):
    script = _load_script()
    token = "secret-token-that-must-not-appear"
    monkeypatch.setenv("BISHENG_API_KEY", token)

    def fail_run(coroutine):
        coroutine.close()
        raise RuntimeError(f"transport rejected Bearer {token}")

    monkeypatch.setattr(script.asyncio, "run", fail_run)

    assert script.main(["--url", "https://bisheng.example.com/api/v2/mcp"]) == 3
    output = capsys.readouterr()
    assert token not in output.out
    assert token not in output.err
    assert "RuntimeError" in output.err


def test_verifier_missing_credential_returns_nonzero(monkeypatch, capsys):
    script = _load_script()
    monkeypatch.delenv("BISHENG_API_KEY", raising=False)

    assert script.main(["--url", "https://bisheng.example.com/api/v2/mcp"]) == 2
    assert "missing credential" in capsys.readouterr().err
