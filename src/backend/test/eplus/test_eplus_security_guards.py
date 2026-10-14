from __future__ import annotations

import ast
import re
from pathlib import Path

from bisheng.eplus.infrastructure.protocol import REDACTED, sanitize_for_log

ROOT = Path(__file__).resolve().parents[4]
BACKEND = ROOT / "src/backend/bisheng"
EPLUS = BACKEND / "eplus"


def _python_sources(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def test_production_sources_do_not_contain_customer_credentials() -> None:
    credential_literal = re.compile(
        r"(?i)(?:bot_id|secret)\s*=\s*['\"][A-Za-z0-9_-]{24,}['\"]"
    )
    production_paths = [
        *_python_sources(EPLUS),
        ROOT / "src/frontend/platform/src/controllers/API/eplus.ts",
        ROOT / "src/frontend/platform/src/types/eplus.ts",
        ROOT / "src/frontend/platform/src/pages/BuildPage/assistant/editAssistant/EPlusRobotSettings.tsx",
        ROOT / "docker/docker-compose.yml",
        ROOT / "docker/bisheng/entrypoint.sh",
    ]
    for path in production_paths:
        source = path.read_text(encoding="utf-8")
        assert credential_literal.search(source) is None, path
        assert "cofco.com" not in source.lower(), path


def test_log_sanitizer_removes_message_secret_aes_key_and_url_query() -> None:
    secret = "runtime-secret"
    sanitized = sanitize_for_log(
        {
            "content": "original user question",
            "secret": secret,
            "aeskey": "image-key",
            "url": f"https://media.example/image?token={secret}",
            "error": f"request failed for secret={secret}",
        },
        secrets=(secret,),
    )

    rendered = repr(sanitized)
    assert "original user question" not in rendered
    assert secret not in rendered
    assert "image-key" not in rendered
    assert "?token=" not in rendered
    assert REDACTED in rendered


def test_eplus_sources_never_use_per_user_file_visibility_service() -> None:
    for path in _python_sources(EPLUS):
        assert "KnowledgeFileVisibilityService" not in path.read_text(encoding="utf-8"), path


def test_internal_assistant_entrypoints_do_not_read_eplus_tables() -> None:
    internal_sources = (
        BACKEND / "common/chat/client.py",
        BACKEND / "assistant/domain/services/published_assistant_service.py",
        BACKEND / "workstation/domain/services/chat_service.py",
    )
    forbidden = ("EPlusBotConfig", "EPlusInboundMessage", "EPlusTurn", "EPlusConfigRepository")
    for path in internal_sources:
        source = path.read_text(encoding="utf-8")
        assert not any(name in source for name in forbidden), path


def test_eplus_worker_has_no_local_cross_process_state() -> None:
    worker = (EPLUS / "worker.py").read_text(encoding="utf-8")
    assert "/app/data" not in worker
    assert "open(" not in worker
    assert "write_text(" not in worker
    assert "write_bytes(" not in worker

    compose = (ROOT / "docker/docker-compose.yml").read_text(encoding="utf-8")
    worker_section = compose.split("  backend_eplus_worker:", 1)[1].split("\n  frontend:", 1)[0]
    assert "/app/data" not in worker_section


def test_shared_assistant_runtime_does_not_log_model_or_user_content() -> None:
    path = BACKEND / "api/services/assistant_agent.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden_names = {"result", "inputs", "query", "chat_history", "message", "messages"}
    violations: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"debug", "info", "warning", "error", "exception"}:
            continue
        for argument in (*node.args, *[keyword.value for keyword in node.keywords]):
            if any(isinstance(item, ast.Name) and item.id in forbidden_names for item in ast.walk(argument)):
                violations.append(node.lineno)
    assert violations == []
