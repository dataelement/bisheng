"""The CLI's test doubles, checked against the server they claim to imitate.

Why this file exists: when the open-API base was swapped from F049 to beta2's
F053, `GET /api/v2/auth/whoami` stopped sending `subject_kind` /
`service_account: {id, name}` / `resource_owner: {user_id, user_name}` and
started sending `actor_kind` / `actor_id` / `actor_name` / `resource_owner:
{user_id}`. Not one of the 254 tests in this suite noticed, because they all
assert against `tests/helpers/platform_mock.py` — and the mock had not moved.
A green suite against a server that does not exist is worse than a red one.

**Why read the server's source instead of importing it.** `pyproject.toml`
budgets this package at two runtime dependencies and describes it as having
"zero coupling to the backend package"; the backend needs fastapi, sqlmodel and
the rest, none of which exist in this project's environment, so
`import bisheng.open_api...` would turn the whole file into a collection error
rather than a check. `ast` parses the declaration without importing anything and
without adding a dependency — the field names are what matters, and they are
right there in the source. The cost is that a field added dynamically (there are
none) would be missed.

If the backend tree is not next to this package, these tests **fail** rather
than skip: a silent skip is the same failure mode this file was written to
close.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from bisheng_cli.commands.login import resource_owner_user_id
from tests.helpers.platform_mock import OPEN_API_HTTP_STATUS, WHOAMI_FIELDS, whoami_ok

REPO_ROOT = Path(__file__).resolve().parents[3]
WHOAMI_SCHEMA = REPO_ROOT / "src/backend/bisheng/open_api/domain/schemas/credential.py"
OPEN_API_ERRCODES = REPO_ROOT / "src/backend/bisheng/common/errcode/open_api.py"


def _module(path: Path) -> ast.Module:
    if not path.is_file():
        pytest.fail(
            f"找不到服务端契约源文件 {path}。"
            "这个测试要拿服务端的真实模型来核对 CLI 的测试桩，找不到就等于没核对——"
            "所以它失败而不是跳过。若后端目录被移动，请改这里的路径。"
        )
    return ast.parse(path.read_text(encoding="utf-8"))


def _class_fields(path: Path, name: str) -> list[str]:
    """Annotated field names declared directly on a pydantic model, in order."""
    for node in _module(path).body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return [
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and stmt.target.id != "model_config"
            ]
    pytest.fail(f"{path.name} 里没有 {name} 了——服务端契约被改名或移走，CLI 侧必须跟着改")
    raise AssertionError("unreachable")


def _error_codes(path: Path) -> dict[int, int]:
    """`{Code: http_status}` for every error class declared in the module."""
    codes: dict[int, int] = {}
    for node in _module(path).body:
        if not isinstance(node, ast.ClassDef):
            continue
        values: dict[str, int] = {}
        for stmt in node.body:
            target = None
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                target = stmt.target.id
            elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                target = stmt.targets[0].id
            if target in ("Code", "http_status") and isinstance(stmt.value, ast.Constant):
                values[target] = stmt.value.value
        if "Code" in values:
            codes[values["Code"]] = values.get("http_status", 400)
    return codes


def test_whoami_stub_has_exactly_the_fields_the_server_sends() -> None:
    """The mock's payload == `WhoamiResponse`'s fields. No extras, none missing.

    An extra key means the CLI may be reading something the server never sends
    (that is how `service_account.name` kept "working" in tests while login
    printed nothing). A missing key means a field landed that no test covers.
    """
    server_fields = _class_fields(WHOAMI_SCHEMA, "WhoamiResponse")
    payload = json.loads(whoami_ok().content)["data"]

    assert list(WHOAMI_FIELDS) == server_fields
    assert sorted(payload) == sorted(server_fields)


def test_resource_owner_carries_the_one_field_the_cli_reads() -> None:
    # `WhoamiResourceOwner` lost `user_name` in the F049 → beta2 move, which is
    # why `login` prints an id. If a name ever comes back, this goes red and the
    # copy can be improved on purpose rather than by accident.
    assert _class_fields(WHOAMI_SCHEMA, "WhoamiResourceOwner") == ["user_id"]

    payload = json.loads(whoami_ok().content)["data"]
    assert resource_owner_user_id(payload) == payload["resource_owner"]["user_id"]


def test_open_api_error_codes_the_stub_declares_still_exist_with_that_http_status() -> None:
    """Status drift is invisible from inside this suite otherwise.

    `OPEN_API_HTTP_STATUS` decides what the mock puts on the status line, and
    the CLI's fallback ladder keys on exactly that. A code retired server-side,
    or moved from 401 to 403, would leave every test here passing against a
    status the platform stopped sending.
    """
    server = _error_codes(OPEN_API_ERRCODES)
    missing = sorted(code for code in OPEN_API_HTTP_STATUS if code not in server)
    assert not missing, f"服务端已不再定义这些错误码，CLI 桩仍在用：{missing}"

    drifted = {
        code: (declared, server[code]) for code, declared in OPEN_API_HTTP_STATUS.items() if server[code] != declared
    }
    assert not drifted, f"HTTP 状态与服务端不一致（桩值, 服务端值）：{drifted}"
