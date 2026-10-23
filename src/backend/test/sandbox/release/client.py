"""Logged-in calls to the BiSheng routes the release plan names."""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from typing import Any
from urllib.parse import urlsplit

import httpx

from test.sandbox.release.env import API_BASE, FRONTEND_ORIGIN, TOOL_NAME
from test.sandbox.release.parse import history_steps, parse_object, task_tool_results

MASK = "********"


class ApiError(RuntimeError):
    pass


def encrypt_password(client: httpx.Client, password: str) -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    public_key_pem = client.get("/user/public_key").json()["data"]["public_key"]
    public_key = serialization.load_pem_public_key(public_key_pem.encode())
    encrypted = public_key.encrypt(password.encode(), padding.PKCS1v15())
    return base64.b64encode(encrypted).decode()


def login(client: httpx.Client) -> str:
    username = os.environ.get("E2E_ADMIN_USER", "admin")
    password = os.environ.get("E2E_ADMIN_PASSWORD", "Bisheng@top1")
    resp = client.post(
        "/user/login",
        json={"user_name": username, "password": encrypt_password(client, password)},
    )
    body = resp.json()
    if body.get("status_code") != 200:
        raise ApiError(body.get("status_message") or "login failed")
    return body["data"]["access_token"]


def open_api() -> httpx.Client | None:
    """Logged-in client. ``open_api.problem`` explains a miss (captcha, password, or the process)."""
    open_api.problem = ""
    client = httpx.Client(base_url=API_BASE, timeout=60.0)
    token = os.environ.get("E2E_ACCESS_TOKEN")
    if not token:
        try:
            token = login(client)
        except (httpx.HTTPError, ApiError, KeyError, ValueError) as exc:
            open_api.problem = str(exc) or "后端不可登录"
            client.close()
            return None
    client.cookies.set("access_token_cookie", token)
    client.headers["Cookie"] = f"access_token_cookie={token}"
    return client


def data_of(resp: httpx.Response) -> Any:
    try:
        body = resp.json()
    except json.JSONDecodeError as exc:
        raise ApiError(resp.text[:300]) from exc
    if resp.status_code != 200 or body.get("status_code") != 200:
        raise ApiError(f"HTTP {resp.status_code} {body}")
    return body.get("data")


def iter_sse(resp: httpx.Response):
    event = "message"
    lines: list[str] = []
    for raw in resp.iter_lines():
        line = raw.decode() if isinstance(raw, bytes) else raw
        if line == "":
            if lines:
                yield event, "\n".join(lines)
            event = "message"
            lines = []
            continue
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            lines.append(line.split(":", 1)[1].lstrip())
    if lines:
        yield event, "\n".join(lines)


def tool_categories(client: httpx.Client) -> list[dict]:
    payload = data_of(client.get("/tool", params={"is_preset": 1}))
    return payload if isinstance(payload, list) else []


def code_interpreter_type(categories: list[dict]) -> dict | None:
    for item in categories:
        children = item.get("children") or []
        if any(isinstance(child, dict) and child.get("tool_key") == TOOL_NAME for child in children):
            return item
    return None


def extra_of(item: dict) -> dict:
    extra = item.get("extra")
    parsed = parse_object(extra) if isinstance(extra, str) else extra if isinstance(extra, dict) else None
    return dict(parsed or {})


def read_execution_type(client: httpx.Client) -> str | None:
    item = code_interpreter_type(tool_categories(client))
    if item is None:
        return None
    return extra_of(item).get("type")


def save_execution_type(client: httpx.Client, mode: str) -> None:
    item = code_interpreter_type(tool_categories(client))
    if item is None or item.get("id") in (None, ""):
        raise ApiError("代码执行器不在工具列表里")
    data_of(client.post("/tool/config", json={"tool_id": item["id"], "extra": {"type": mode}}))


def linsight_tool_payload(client: httpx.Client) -> dict:
    item = code_interpreter_type(tool_categories(client))
    if item is None:
        preset = data_of(client.get("/tool/linsight/preset"))
        rows = preset if isinstance(preset, list) else []
        item = code_interpreter_type(rows)
    if item is None:
        raise ApiError("任务模式工具列表没有代码执行器")
    children = []
    for child in item.get("children") or []:
        if not isinstance(child, dict):
            continue
        children.append(
            {
                "id": child.get("id"),
                "name": child.get("name"),
                "tool_key": child.get("tool_key"),
                "desc": child.get("desc"),
            }
        )
    return {
        "id": item["id"],
        "name": item.get("name"),
        "is_preset": item.get("is_preset", 1),
        "desc": item.get("desc") or item.get("description"),
        "children": children,
    }


def workbench_model_id(client: httpx.Client) -> str | None:
    chosen = os.environ.get("BISHENG_RELEASE_MODEL_ID")
    if chosen:
        return chosen
    payload = data_of(client.get("/llm/workbench"))
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        payload = payload["data"]
    if not isinstance(payload, dict):
        return None
    for key in ("linsight_default_model_id", "chat_default_model_id"):
        if payload.get(key):
            return str(payload[key])
    models = payload.get("models") or []
    if models and isinstance(models[0], dict) and models[0].get("id") not in (None, ""):
        return str(models[0]["id"])
    return None


def child_tool(client: httpx.Client) -> dict | None:
    item = code_interpreter_type(tool_categories(client))
    if item is None:
        return None
    for child in item.get("children") or []:
        if isinstance(child, dict) and child.get("tool_key") == TOOL_NAME:
            return child
    return None


def wait_files_parsed(client: httpx.Client, files: list[dict], timeout_s: float = 180.0) -> list[dict]:
    """Submit accepts only parsing_status completed. Upload returns running."""
    pending = [dict(item) for item in files]
    if not pending or all(item.get("parsing_status") == "completed" for item in pending):
        return pending
    ids = [str(item["file_id"]) for item in pending if item.get("file_id")]
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        payload = data_of(client.post("/linsight/workbench/file-parsing-status", json={"file_ids": ids}))
        rows = payload if isinstance(payload, list) else []
        by_id: dict[str, dict] = {}
        for index, row in enumerate(rows):
            parsed = parse_object(row) if not isinstance(row, dict) else row
            if not isinstance(parsed, dict):
                continue
            key = str(parsed.get("file_id") or (ids[index] if index < len(ids) else ""))
            if key:
                by_id[key] = parsed
        done = True
        for item in pending:
            row = by_id.get(str(item.get("file_id")))
            status = str(row.get("parsing_status") or "") if row else ""
            if status in {"failed", "unsupported", "expired"}:
                detail = row.get("error_message") if row else ""
                raise ApiError(f"{item.get('file_name')} 解析状态是 {status}，不能提交。{detail}")
            if status != "completed":
                done = False
                continue
            item["parsing_status"] = "completed"
        if done:
            return pending
        time.sleep(2)
    names = ", ".join(str(item.get("file_name")) for item in pending if item.get("parsing_status") != "completed")
    raise ApiError(f"文件解析未在时限内变为 completed: {names}")


def upload_linsight_file(client: httpx.Client, filename: str, content: bytes) -> dict:
    resp = client.post(
        "/linsight/workbench/upload-file", files={"file": (filename, content, "application/octet-stream")}
    )
    uploaded = data_of(resp)
    if not isinstance(uploaded, dict):
        raise ApiError("upload-file 没有返回 file_id")
    return {
        "file_id": uploaded.get("file_id"),
        "file_name": uploaded.get("file_name") or filename,
        "parsing_status": uploaded.get("parsing_status") or "",
    }


def submit_task(
    client: httpx.Client, question: str, files: list[dict] | None = None, skills: list[str] | None = None
) -> str:
    body: dict[str, Any] = {
        "question": question,
        "tools": [linsight_tool_payload(client)],
        "files": files or [],
        "org_knowledge_enabled": False,
        "personal_knowledge_enabled": False,
    }
    if skills:
        body["skills"] = skills
    if files:
        files = wait_files_parsed(client, files)
        body["files"] = files
    model_id = workbench_model_id(client)
    if model_id:
        body["model"] = model_id
    version_id = ""
    with client.stream("POST", "/linsight/workbench/submit", json=body, timeout=120.0) as resp:
        if resp.status_code != 200:
            raise ApiError(f"submit HTTP {resp.status_code}")
        for event, raw in iter_sse(resp):
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if event == "error" or payload.get("status_code") not in (None, 200):
                raise ApiError(payload.get("status_message") or raw[:300])
            if event == "linsight_workbench_submit":
                version = payload.get("linsight_session_version") or {}
                version_id = str(version.get("id") or "")
                break
    if not version_id:
        raise ApiError("submit 没有返回 linsight_session_version.id")
    started = data_of(
        client.post("/linsight/workbench/start-execute", json={"linsight_session_version_id": version_id})
    )
    if started is not True:
        raise ApiError(f"start-execute data 不是 true: {started!r}")
    return version_id


def task_detail(client: httpx.Client, version_id: str) -> list:
    payload = data_of(client.get("/linsight/workbench/execute-task-detail", params={"session_version_id": version_id}))
    return payload if isinstance(payload, list) else []


def wait_tasks(client: httpx.Client, version_id: str, timeout_s: float | None = None) -> list:
    limit = timeout_s if timeout_s is not None else float(os.environ.get("BISHENG_RELEASE_TIMEOUT", "180"))
    deadline = time.time() + limit
    last: list = []
    terminal = {"success", "failed", "terminated"}
    while time.time() < deadline:
        last = task_detail(client, version_id)
        if last and all(task.get("status") in terminal for task in last if isinstance(task, dict)):
            return last
        if any(isinstance(task, dict) and task.get("status") == "waiting_for_user_input" for task in last):
            return last
        time.sleep(2)
    return last


def waiting_task_id(tasks: list) -> str | None:
    for task in tasks:
        if isinstance(task, dict) and task.get("status") == "waiting_for_user_input" and task.get("id"):
            return str(task["id"])
    for step in history_steps(tasks):
        if step.get("name") in {"ask_user", "call_user_input"} and step.get("task_id"):
            return str(step["task_id"])
    return None


def continue_task(client: httpx.Client, version_id: str, question: str) -> None:
    started = data_of(
        client.post(
            "/linsight/workbench/continue",
            json={"session_version_id": version_id, "question": question},
        )
    )
    if started is not True:
        raise ApiError(f"continue data 不是 true: {started!r}")


def user_input(client: httpx.Client, version_id: str, task_id: str, text: str) -> None:
    started = data_of(
        client.post(
            "/linsight/workbench/user-input",
            json={
                "session_version_id": version_id,
                "linsight_execute_task_id": task_id,
                "input_content": text,
            },
        )
    )
    if started is not True:
        raise ApiError(f"user-input data 不是 true: {started!r}")


def _presigned_proxy_path(file_url: str) -> str:
    """file_list entries are presigned MinIO URLs. Strip the host and use the frontend proxy."""
    parts = urlsplit(file_url)
    path = parts.path or ""
    if not path.startswith("/"):
        raise ApiError(f"分享地址没有路径: {file_url[:120]}")
    return path + (f"?{parts.query}" if parts.query else "")


def download_bytes(client: httpx.Client, version_id: str, file_url: str) -> bytes:
    if file_url.startswith("http://") or file_url.startswith("https://"):
        path = _presigned_proxy_path(file_url)
    else:
        payload = data_of(
            client.post(
                "/linsight/workbench/file_download",
                json={"file_url": file_url, "session_version_id": version_id},
            )
        )
        if not isinstance(payload, dict):
            raise ApiError("file_download 没有 data.file_path")
        path = payload.get("file_path") or ""
        if not isinstance(path, str) or not path.startswith("/"):
            raise ApiError(f"file_path 不是去掉主机名的分享路径: {path!r}")
    fetched = httpx.get(f"{FRONTEND_ORIGIN}{path}", timeout=60.0, follow_redirects=True)
    if fetched.status_code != 200 or not fetched.content:
        raise ApiError(f"前端代理取文件失败 HTTP {fetched.status_code} {path}")
    return fetched.content


def file_urls(result: dict | None) -> list[str]:
    if not result:
        return []
    urls = []
    for item in result.get("file_list") or []:
        if isinstance(item, str) and item:
            urls.append(item)
        elif isinstance(item, dict) and item.get("url"):
            urls.append(str(item["url"]))
    return urls


def first_sum_result(tasks: list, accept) -> dict | None:
    """A code-interpreter step accept() allows, else the last step."""
    from test.sandbox.release.parse import chosen_tool_result

    return chosen_tool_result([item["result"] for item in task_tool_results(tasks)], accept)


def run_task_question(
    client: httpx.Client,
    question: str,
    files: list[dict] | None = None,
    skills: list[str] | None = None,
) -> tuple[str, list]:
    version_id = submit_task(client, question, files=files, skills=skills)
    return version_id, wait_tasks(client, version_id)


def daily_sum(client: httpx.Client, prompt: str) -> dict | None:
    from test.sandbox.release.parse import chosen_tool_result, daily_tool_result, log_sum

    model_id = workbench_model_id(client)
    child = child_tool(client)
    if not model_id or child is None or child.get("id") in (None, ""):
        return None
    body = {
        "clientTimestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": model_id,
        "text": prompt,
        "tools": [{"id": child["id"], "tool_key": TOOL_NAME, "type": "tool"}],
        "task_mode": False,
        "search_enabled": False,
    }

    found: list = []
    with client.stream("POST", "/workstation/chat/completions", json=body, timeout=180.0) as resp:
        if resp.status_code != 200:
            raise ApiError(f"daily chat HTTP {resp.status_code}")
        for event, raw in iter_sse(resp):
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            parsed = daily_tool_result(event, payload)
            if parsed:
                found.append(parsed)
    return chosen_tool_result(found, log_sum)


def _ws_url(path: str) -> str:
    base = API_BASE.replace("https://", "wss://").replace("http://", "ws://")
    return f"{base}{path}"


def _token_of(client: httpx.Client) -> str:
    return client.cookies.get("access_token_cookie") or ""


def _ws_connect(path: str, token: str):
    """Workflow and assistant sockets authenticate from the access cookie.

    The ``t`` query argument is overwritten by that cookie and never decoded.
    """
    import websockets

    if not token:
        raise ApiError("WebSocket 没有 access_token_cookie")
    return websockets.sync.client.connect(
        _ws_url(path),
        additional_headers={"Cookie": f"access_token_cookie={token}"},
        open_timeout=10,
    )


def workflow_events(client: httpx.Client, workflow_id: str, text: str, timeout_s: float = 180.0) -> list[dict]:
    flow = data_of(client.get(f"/workflow/get_one_flow/{workflow_id}"))
    if not isinstance(flow, dict):
        raise ApiError("工作流不存在")
    graph = flow.get("data") if isinstance(flow.get("data"), dict) else {}
    init_data = {key: value for key, value in flow.items() if key != "data"}
    init_data.update(graph)
    init = {"action": "init_data", "flow_id": workflow_id, "data": init_data}
    frames: list[dict] = []
    token = _token_of(client)
    deadline = time.time() + timeout_s
    with _ws_connect(f"/workflow/chat/{workflow_id}", token) as ws:
        ws.send(json.dumps(init))
        node_id = ""
        variable = ""
        sent = False
        while time.time() < deadline:
            raw = ws.recv(timeout=max(1, deadline - time.time()))
            frame = json.loads(raw)
            if isinstance(frame, dict):
                frames.append(frame)
                message = frame.get("message") if isinstance(frame.get("message"), dict) else {}
                if frame.get("category") == "input" and not sent:
                    node_id = str(message.get("node_id") or "")
                    schema = message.get("input_schema") or message.get("schema") or {}
                    variable = _input_key(schema) or "user_input"
                    ws.send(
                        json.dumps(
                            {
                                "action": "input",
                                "flow_id": workflow_id,
                                "data": {
                                    node_id: {
                                        "data": {variable: text},
                                        "message": text,
                                        "message_id": message.get("message_id") or str(uuid.uuid4()),
                                        "category": "question",
                                        "extra": "",
                                        "source": 0,
                                    }
                                },
                            }
                        )
                    )
                    sent = True
                if frame.get("category") == "processing" and frame.get("type") == "close":
                    break
    return frames


def _input_key(schema: Any) -> str:
    if isinstance(schema, dict):
        value = schema.get("value")
        if isinstance(value, list) and value and isinstance(value[0], dict) and value[0].get("key"):
            return str(value[0]["key"])
        if schema.get("key"):
            return str(schema["key"])
    return ""


def assistant_events(client: httpx.Client, assistant_id: str, text: str, timeout_s: float = 180.0) -> list[dict]:
    info = data_of(client.get(f"/assistant/info/{assistant_id}"))
    if not isinstance(info, dict):
        raise ApiError("助手不存在")
    chat_id = str(uuid.uuid4())
    payload = {
        "chatHistory": [],
        "flow_id": assistant_id,
        "chat_id": chat_id,
        "name": info.get("name") or "",
        "description": info.get("desc") or info.get("description") or "",
        "inputs": {"data": {"chatId": chat_id, "id": assistant_id, "type": 5}, "input": text},
    }
    frames: list[dict] = []
    token = _token_of(client)
    deadline = time.time() + timeout_s
    with _ws_connect(f"/assistant/chat/{assistant_id}", token) as ws:
        ws.send(json.dumps(payload))
        while time.time() < deadline:
            raw = ws.recv(timeout=max(1, deadline - time.time()))
            frame = json.loads(raw)
            if isinstance(frame, dict):
                frames.append(frame)
                # Each model turn emits processing/end, including the turn that
                # only chooses a tool. The assistant turn itself ends with processing/close.
                if frame.get("category") == "processing" and frame.get("type") == "close":
                    break
    return frames
