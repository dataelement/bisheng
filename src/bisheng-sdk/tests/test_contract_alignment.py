"""对账：SDK 复制的三张表必须与源头逐字一致（AC-11 / AC-20 / AC-21 / AC-31）。

SDK 是可发布的独立包，装进应用容器时看不到这个仓库——所以这些常量只能是副本。
副本的代价是漂移，对账测试就是收这个代价：**读源文件的文本**，而不是 import 它们
（SDK 不依赖 backend / runtime-manager / app-proxy 任何一个包）。

仓外运行（发布件里跑）或源文件不存在时 `skip` 并打印原因——那不是失败，只是
在那个环境里对不了账。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from bisheng_sdk import _env, _headers, _paths, _storage_remote, retrieve

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_PROXY_HEADERS = REPO_ROOT / "src" / "app-proxy" / "app_proxy" / "headers.py"
MANAGER_STORAGE = REPO_ROOT / "src" / "runtime-manager" / "runtime_manager" / "storage.py"
MANAGER_STORAGE_API = REPO_ROOT / "src" / "runtime-manager" / "runtime_manager" / "api" / "storage.py"
BACKEND_FILELIB = REPO_ROOT / "src" / "backend" / "bisheng" / "open_endpoints" / "api" / "endpoints" / "filelib.py"
BACKEND_MODEL_RANGE = (
    REPO_ROOT / "src" / "backend" / "bisheng" / "open_api" / "domain" / "services" / "model_range_policy.py"
)
BACKEND_APP_CREDENTIAL = (
    REPO_ROOT / "src" / "backend" / "bisheng" / "app_publish" / "domain" / "services" / "app_credential_service.py"
)
RTM_CONTRACT = REPO_ROOT / "features" / "v3.0.0" / "054-app-domain-runtime" / "contracts-runtime-manager.md"


def _source(path: Path) -> str:
    if not path.is_file():
        pytest.skip(f"契约源文件不在本检出里（仓外运行或前置分支未合入）：{path}")
    return path.read_text(encoding="utf-8")


def _tuple_literal(text: str, name: str) -> list[str]:
    """从源码里取一个模块级字符串元组常量的值。"""
    tree = ast.parse(text)
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == name and node.value is not None:
                return [element.value for element in node.value.elts]  # type: ignore[attr-defined]
    raise AssertionError(f"没在源文件里找到常量 {name}")


def test_header_names_match_app_proxy_verbatim():
    upstream = _tuple_literal(_source(APP_PROXY_HEADERS), "INJECTED_HEADER_NAMES")
    assert list(_headers.INJECTED_HEADER_NAMES) == upstream


def test_header_normalisation_matches_app_proxy():
    text = _source(APP_PROXY_HEADERS)
    assert 'strip().lower().replace("_", "-")' in text
    assert _headers.normalize_name("X_BiSheng_User_Id") == "x-bisheng-user-id"


def test_storage_env_names_match_the_manager():
    text = _source(MANAGER_STORAGE)
    names = {
        "ENV_STORAGE_ENDPOINT": _env.ENV_STORAGE_ENDPOINT,
        "ENV_STORAGE_TOKEN": _env.ENV_STORAGE_TOKEN,
        "ENV_STORAGE_MAX_FILE_MB": _env.ENV_STORAGE_MAX_FILE_MB,
    }
    for constant, ours in names.items():
        match = re.search(rf'^{constant} = "([^"]+)"', text, re.MULTILINE)
        assert match, f"manager 里没有 {constant}"
        assert match.group(1) == ours


def test_platform_env_names_are_in_the_runtime_contract():
    text = _source(RTM_CONTRACT)
    for name in (_env.ENV_PLATFORM_API_BASE, _env.ENV_STORAGE_ENDPOINT, _env.ENV_STORAGE_TOKEN):
        assert name in text, f"契约文档 §5 里没有 {name}"


def test_app_token_env_name_matches_the_capability_bus():
    text = _source(BACKEND_APP_CREDENTIAL)
    match = re.search(r'^HOSTED_APP_TOKEN_ENV = "([^"]+)"', text, re.MULTILINE)
    assert match, "app_credential_service 里没有 HOSTED_APP_TOKEN_ENV"
    assert match.group(1) == _env.ENV_APP_TOKEN


def test_access_token_header_name_matches_the_verifier():
    text = _source(BACKEND_MODEL_RANGE)
    match = re.search(r'^ACCESS_TOKEN_HEADER = "([^"]+)"', text, re.MULTILINE)
    assert match, "model_range_policy 里没有 ACCESS_TOKEN_HEADER"
    assert match.group(1) == retrieve.ACCESS_TOKEN_HEADER
    assert match.group(1) in _headers.INJECTED_HEADER_NAMES


def test_retrieve_path_and_hosted_branch_still_exist():
    text = _source(BACKEND_FILELIB)
    assert '@router.post("/retrieve")' in text
    assert retrieve.RETRIEVE_PATH.endswith("/filelib/retrieve")
    # 托管应用走能力总线（白名单 ∩ 访问用户），不是门面直连——这是 SDK 必须同时
    # 送两把凭据的原因。任何一侧改了这条分支，这里先红。
    assert "HOSTED_APP_ACTOR_KIND" in text
    assert "hosted_app_access_user" in text


def test_storage_routes_match_the_manager_router():
    text = _source(MANAGER_STORAGE_API)
    assert 'prefix="/v1/apps/{app_id}/storage"' in text
    for route in ('@router.get("/objects")', '@router.get("/meta/{key:path}")', '@router.put("/objects/{key:path}")'):
        assert route in text, f"manager 的附件路由变了：{route}"
    assert '@router.delete("/objects/{key:path}")' in text
    # SDK 拼的 URL 必须落在同样的形状上。
    backend = _storage_remote.RemoteBackend("http://m.test/v1/apps/app-1/storage", "t")
    assert backend._objects_url("a/b.txt").endswith("/storage/objects/a/b.txt")
    assert backend._meta_url("a.txt").endswith("/storage/meta/a.txt")


def test_path_rules_mirror_manager_validate_key():
    text = _source(MANAGER_STORAGE)
    assert f"MAX_KEY_BYTES = {_paths.MAX_KEY_BYTES}" in text
    assert f'APPS_NAMESPACE = "{_paths.APPS_NAMESPACE}"' in text
    for rule in (
        'raise _reject(key, "absolute path")',
        'raise _reject(key, "trailing slash")',
        'raise _reject(key, "backslashes")',
        'raise _reject(key, "control characters")',
        "if posixpath.normpath(key) != key:",
    ):
        assert rule in text, f"manager 的路径规则变了：{rule}"
