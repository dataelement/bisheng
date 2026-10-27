"""S-022. Page copy is the Chinese the case names. The config response is not the echo."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from test.sandbox.release.client import (
    MASK,
    ApiError,
    code_interpreter_type,
    data_of,
    extra_of,
    open_api,
    read_execution_type,
    save_execution_type,
    tool_categories,
)
from test.sandbox.release.conftest import sandbox_reachable
from test.sandbox.release.env import PAGE_LABELS, SANDBOX_TOKEN, SANDBOX_URL

_LOCALE = Path(__file__).resolve().parents[4] / "frontend/platform/public/locales/zh-Hans/tool.json"


def _label_problems() -> list[str]:
    copy = json.loads(_LOCALE.read_text(encoding="utf-8"))
    problems = []
    for key, expected in PAGE_LABELS.items():
        actual = copy.get(key)
        if actual != expected:
            problems.append(f"页面文案 {key} 是 {actual!r}，用例要求 {expected!r}")
    return problems


def _restore_type(client, tool_id: int, original: str | None) -> None:
    if original:
        save_execution_type(client, original)


def _config_problems(client) -> list[str]:
    problems: list[str] = []
    item = code_interpreter_type(tool_categories(client))
    if item is None:
        return ["未测：工具列表没有 bisheng_code_interpreter 所在分类"]
    original = extra_of(item).get("type")
    try:
        for mode in ("local", "container", "e2b"):
            save_execution_type(client, mode)
            seen = read_execution_type(client)
            if seen != mode:
                problems.append(f"保存 {mode} 后 GET /api/v1/tool 分类 extra.type 是 {seen!r}")
        saved = data_of(client.post("/tool/config", json={"tool_id": item["id"], "extra": {"type": "local"}}))
        if saved is True and read_execution_type(client) == "local":
            pass
        elif read_execution_type(client) != "local":
            problems.append("POST /tool/config 的响应不能当作回显，重新读取后 type 不是 local")
    except ApiError as exc:
        problems.append(f"执行方式接口失败: {exc}")
    finally:
        try:
            _restore_type(client, item["id"], original if isinstance(original, str) else None)
        except ApiError as exc:
            problems.append(f"恢复执行方式失败: {exc}")
    return problems


def _address_problems(client) -> list[str]:
    problems: list[str] = []
    try:
        before = data_of(client.get("/tool/sandbox_conf"))
    except ApiError as exc:
        return [f"未测：读不到沙箱地址 ({exc})"]
    if not isinstance(before, dict):
        return ["sandbox_conf 的 data 不是对象"]
    original_endpoints = list(before.get("endpoints") or [])
    had_token = before.get("token") == MASK
    endpoints = list(dict.fromkeys([*original_endpoints, SANDBOX_URL]))
    token = MASK if had_token else SANDBOX_TOKEN
    try:
        data_of(client.post("/tool/sandbox_conf", json={"endpoints": endpoints, "token": token}))
        viewed = data_of(client.get("/tool/sandbox_conf"))
        if SANDBOX_URL not in (viewed.get("endpoints") or []):
            problems.append(f"data.endpoints 不包含 {SANDBOX_URL}: {viewed.get('endpoints')!r}")
        if viewed.get("token") != MASK:
            problems.append(f"data.token 不是掩码: {viewed.get('token')!r}")
        if not sandbox_reachable():
            problems.append("未测：沙箱进程未启动，没有用掩码令牌探测已保存的地址")
        else:
            probed = data_of(
                client.post(
                    "/tool/sandbox_conf/test",
                    json={"endpoints": [SANDBOX_URL], "token": MASK},
                )
            )
            results = probed.get("results") if isinstance(probed, dict) else None
            status = ""
            if isinstance(results, list):
                for item in results:
                    if isinstance(item, dict) and item.get("url") == SANDBOX_URL:
                        status = item.get("status") or ""
            if status != "ok":
                problems.append(f"掩码令牌探测 {SANDBOX_URL} 的 status 是 {status!r}，不是 ok")
    except ApiError as exc:
        problems.append(f"沙箱地址接口失败: {exc}")
    finally:
        restore_token = MASK if had_token or token != "" else ""
        if not had_token:
            restore_token = ""
        try:
            data_of(
                client.post(
                    "/tool/sandbox_conf",
                    json={"endpoints": original_endpoints, "token": restore_token},
                )
            )
        except ApiError as exc:
            problems.append(f"恢复沙箱地址失败: {exc}")
    return problems


def test_s022():
    problems = _label_problems()
    client = open_api()
    if client is None:
        reason = getattr(open_api, "problem", "") or "后端不可登录"
        problems.append(f"未测：{reason}，执行方式、地址和令牌没有核对")
    else:
        try:
            problems.extend(_config_problems(client))
            problems.extend(_address_problems(client))
        finally:
            client.close()
    hard = [item for item in problems if not item.startswith("未测")]
    if hard:
        pytest.fail("S-022\n" + "\n".join(problems))
    if problems:
        pytest.skip("S-022 " + "；".join(problems))


def test_s022_install_and_upgrade_need_their_own_databases():
    pytest.skip("未测：新装默认 container 和升级不改写已有 extra 各需要一份独立数据库，不能从配置接口的返回值推断")
