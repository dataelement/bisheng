"""F118 真实 HTTP 验收助手。昆联登录使用真实网关 Cookie,不生成测试 JWT。"""

import asyncio
import json
import logging
import os
import re
import stat
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from test.e2e.helpers.api import assert_resp_200
from test.e2e.helpers.auth import auth_headers

PREFIX = "e2e-kunlian-"


def private_json(path):
    """凭据交接文件必须有界、非链接且只对当前用户可读。"""
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
            raise ValueError("交接文件必须属于当前用户且权限为 0600")
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError("交接文件超过大小限制")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("交接文件必须是 JSON 对象")
    return value


def exact_origin(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("F118 E2E 只允许明确登记的 HTTPS Origin")
    return value.rstrip("/")


def validate_manifest(value):
    """检查专属数据边界,不为未知上游编造管理接口。"""
    required = {
        "origin",
        "connection_id",
        "external_tenant_id",
        "local_tenant_id",
        "foreign_local_tenant_id",
        "actors",
        "expected_member_count",
        "return_to",
    }
    if set(value) != required:
        raise ValueError("manifest 字段缺失或含未知字段")
    result = dict(value)
    result["origin"] = exact_origin(value["origin"])
    if not re.fullmatch(r"e2e-kunlian-[a-z0-9-]{1,48}", value["connection_id"]):
        raise ValueError("连接必须是 e2e-kunlian- 专属标识")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value["external_tenant_id"]):
        raise ValueError("外部租户必须是显式登记的不透明标识")
    for key in ("local_tenant_id", "foreign_local_tenant_id", "expected_member_count"):
        if type(value[key]) is not int or value[key] <= 0:
            raise ValueError("租户和成员数量必须是显式正整数")
    if value["local_tenant_id"] == value["foreign_local_tenant_id"]:
        raise ValueError("跨租户对照必须使用不同租户")
    if value["return_to"] not in {"/", "/workspace"}:
        raise ValueError("测试落点只允许 / 或 /workspace")
    if set(value["actors"]) != {"a", "b", "c", "missing"}:
        raise ValueError("必须提供 A/B、跨租户 C 和独立缺目录探针 missing")
    for key, actor in value["actors"].items():
        fields = {"user_id", "name"} if key in {"a", "b"} else {"name"}
        if set(actor) != fields:
            raise ValueError("A/B 必须有 user_id 和 name,其余探针只提供 name")
        if key in {"a", "b"} and (type(actor["user_id"]) is not int or actor["user_id"] <= 0):
            raise ValueError("A/B 必须有明确的正整数 user_id")
        if not isinstance(actor["name"], str) or not actor["name"].startswith(PREFIX):
            raise ValueError("只允许专属前缀的测试账号")
    if value["actors"]["a"]["user_id"] == value["actors"]["b"]["user_id"]:
        raise ValueError("A/B 不能复用同一账号")
    if len({actor["name"] for actor in value["actors"].values()}) != 4:
        raise ValueError("四个身份不能复用名称")
    return result


@dataclass(repr=False)
class OperatorBridge:
    """用私有文件接入真实 OP 登录及上游操作,不执行任意命令。"""

    directory: Path
    timeout: float
    run_id: str = field(default_factory=lambda: uuid4().hex)

    async def checkpoint(self, phase, **instructions):
        nonce = uuid4().hex
        stem = f"{self.run_id}-{nonce}"
        request, reply = self.directory / f"{stem}.request.json", self.directory / f"{stem}.reply.json"
        payload = {"run_id": self.run_id, "nonce": nonce, "phase": phase, **instructions}
        descriptor = os.open(request, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            with os.fdopen(descriptor, "w") as stream:
                json.dump(payload, stream, ensure_ascii=False)
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                if reply.exists():
                    try:
                        answer = private_json(reply)
                    except (json.JSONDecodeError, OSError):
                        # 操作侧必须原子写入;短暂未完成仅在本次有界等待内重读。
                        await asyncio.sleep(0.2)
                        continue
                    if answer.get("nonce") != nonce or answer.get("ok") is not True:
                        raise AssertionError("操作回执不匹配本次 checkpoint 或未确认成功")
                    return answer
                await asyncio.sleep(0.2)
            raise AssertionError("真实环境 checkpoint 超时;不得改成通过或跳过")
        finally:
            request.unlink(missing_ok=True)
            reply.unlink(missing_ok=True)


@dataclass(repr=False)
class Journey:
    manifest: dict
    bridge: OperatorBridge
    admin_token: str = field(repr=False)
    admin: httpx.AsyncClient = field(repr=False)
    worker: object = field(repr=False)
    clients: list = field(default_factory=list, repr=False)
    workflows: dict = field(default_factory=dict)

    @property
    def origin(self):
        return self.manifest["origin"]

    async def admin_call(self, method, path, *, status=200, **kwargs):
        response = await self.admin.request(method, "/api/v1" + path, headers=auth_headers(self.admin_token), **kwargs)
        return envelope(response, status=status)

    async def status(self):
        result = await self.admin_call("GET", "/identity-integrations/kunlian/status")
        assert result["connection_id"] == self.manifest["connection_id"], "连接不属于本测试"
        return result

    async def preflight(self):
        for key in ("local_tenant_id", "foreign_local_tenant_id"):
            tenant = await self.admin_call("GET", f"/tenants/{self.manifest[key]}")
            assert tenant["id"] == self.manifest[key] and tenant["tenant_code"].startswith(PREFIX)
            assert tenant["tenant_name"].startswith(PREFIX), "只能使用已准备的专属测试租户"
        await self.status()

    async def sync(self):
        """只入队真实任务,通过管理读接口等候持久完成,不直调领域服务。"""
        try:
            async with asyncio.timeout(self.bridge.timeout):
                return await self._sync_once()
        except TimeoutError:
            raise AssertionError("真实 Worker 验证超过总预算") from None

    async def _sync_once(self):
        before = await self.status()
        requested = await self.admin_call("POST", "/identity-integrations/kunlian/sync", status=202)
        version = requested["requested_version"]
        assert version > before["sync_completed_version"]
        # 等待真实 Broker/Worker 回执。不使用 Task.apply 或任务本体直调。
        task = await asyncio.to_thread(
            self.worker.send_task,
            "bisheng.worker.sso_sync.tasks.sync_directory",
            args=[self.manifest["connection_id"]],
            headers={"tenant_id": 1},
            queue="celery",
            retry=False,
        )
        deadline = time.monotonic() + self.bridge.timeout
        while not await asyncio.to_thread(task.ready):
            if time.monotonic() >= deadline:
                raise AssertionError("真实 Worker 未返回本次任务结果")
            await asyncio.sleep(1)
        if not await asyncio.to_thread(task.successful):
            raise AssertionError("真实 Worker 任务失败;不能以状态查询成功替代")
        result = await asyncio.to_thread(task.get, timeout=5)
        if not isinstance(result, dict) or result.get("directory_status") not in {"PUBLISHED", "FETCHING"}:
            raise AssertionError("真实 Worker 没有接受目录执行")
        while time.monotonic() < deadline:
            current = await self.status()
            if current["directory_status"] == "FAILED":
                raise AssertionError("真实 Worker 同步失败;请检查脱敏关联线索")
            if (
                current["sync_completed_version"] >= version
                and current["directory_status"] == "PUBLISHED"
                and current["projection_pending"] == 0
                and current["projection_failed"] == 0
            ):
                assert current["active_batch_id"] != before["active_batch_id"]
                assert current["member_count"] == self.manifest["expected_member_count"]
                return current
            await asyncio.sleep(1)
        raise AssertionError("真实 Worker/投影未在预算内完成")

    async def login(self, actor, *, expected_status=303, reason=None):
        """客户端发起事务;操作侧完成 OP 交互并截获尚未消费的回调。"""
        client = httpx.AsyncClient(base_url=self.origin, timeout=30, follow_redirects=False, trust_env=False)
        self.clients.append(client)
        start = await client.get("/api/oauth2/kunlian", params={"return_to": self.manifest["return_to"]})
        assert start.status_code == 303, "网关未发起专用授权事务"
        answer = await self.bridge.checkpoint(
            "oidc-" + actor,
            actor=self.manifest["actors"][actor]["name"],
            authorization_url=start.headers["location"],
            instruction="真实登录 OP;在访问网关前截获完整 callback_url,不消费回调",
        )
        callback = answer.get("callback_url", "")
        parsed = urlsplit(callback)
        if (
            parsed.scheme + "://" + parsed.netloc != self.origin
            or parsed.path != "/api/kunlian/callback"
            or not parsed.query
            or parsed.fragment
            or len(callback) > 8192
        ):
            raise AssertionError("OP 回调不属于本测试登记地址")
        response = await client.get(callback)
        assert response.status_code == expected_status, "真实网关回调结果不符"
        if reason is not None:
            if reason not in response.text:
                raise AssertionError("网关没有返回预期稳定原因")
        else:
            location = response.headers.get("location", "")
            assert location.endswith("#kunlian-login"), "未收到受限昆联启动提示"
            assert client.cookies.get("access_token_cookie"), "网关没有签发本地 Cookie"
        return client

    async def browser_call(self, client, method, path, *, status=200, code=200, **kwargs):
        headers = {"Origin": self.origin}
        if method not in {"GET", "HEAD"}:
            csrf = envelope(await client.get("/api/v1/identity-integrations/kunlian/session/csrf"))
            headers["X-CSRF-Token"] = csrf["csrf_token"]
        response = await client.request(method, "/api/v1" + path, headers=headers, **kwargs)
        return envelope(response, status=status, code=code)

    async def user(self, client, actor):
        data = await self.browser_call(client, "GET", "/user/info")
        assert data["auth_source"] == "kunlian" and data["user_id"] == self.manifest["actors"][actor]["user_id"]
        assert data["user_name"] == self.manifest["actors"][actor]["name"]
        assert data.get("role") != "admin" and data.get("is_global_super") is False
        assert data.get("is_child_admin") is False, "不能用管理员短路证明业务权限"
        return data

    async def roster(self, workflow_id):
        value = await self.admin_call(
            "GET", f"/permissions/resources/workflow/{workflow_id}/grants", params={"page_size": 100}
        )
        assert not value.get("has_more"), "测试授权超过一页,不能只核对部分记录"
        return value["data"]

    async def mutate_grants(self, workflow_id, changes):
        context = await self.admin_call("GET", f"/permissions/resources/workflow/{workflow_id}/context")
        return await self.admin_call(
            "POST",
            f"/permissions/resources/workflow/{workflow_id}/grants:mutate",
            json={
                "idempotency_key": "f118-" + uuid4().hex,
                "expected_resource_version": context["resource_version"],
                "expected_catalog_release_id": context["catalog_release_id"],
                "changes": changes,
            },
        )

    async def check_action(self, client, workflow_id, action):
        data = await self.browser_call(
            client,
            "POST",
            "/permissions/check",
            json={
                "resource_type": "workflow",
                "resource_id": workflow_id,
                "action": action,
            },
        )
        assert type(data["allowed"]) is bool
        return data["allowed"]

    async def cleanup(self):
        """只处理本次创建且再次核对名称/创建者/租户的工作流。"""
        for workflow_id, expected in self.workflows.items():
            current = await self.admin_call("GET", "/workflow/get_one_flow/" + workflow_id)
            for key in ("name", "user_id", "tenant_id"):
                assert current[key] == expected[key], "工作流归属变化,停止清理"
            assert current["name"].startswith(PREFIX)
            await self.admin_call("DELETE", "/flows/" + workflow_id)


def envelope(response, *, status=200, code=200):
    """限制错误输出,避免断言打印完整代理页面、Cookie 或上游载荷。"""
    if response.status_code != status:
        raise AssertionError("HTTP 状态与场景预期不符")
    body = response.json()
    if not {"status_code", "status_message", "data"} <= body.keys() or body["status_code"] != code:
        raise AssertionError("统一响应格式或业务码与场景预期不符")
    if code == 200 and status == 200:
        return assert_resp_200(response)
    return body["data"]


@asynccontextmanager
async def live_journey(environ):
    names = (
        "F118_E2E_MANIFEST",
        "F118_E2E_CONTROL_DIR",
        "F118_E2E_ADMIN_TOKEN",
        "F118_E2E_BROKER_URL",
        "F118_E2E_RESULT_BACKEND",
    )
    if any(not environ.get(name) for name in names):
        raise ValueError("F118_E2E=1 时必须提供 manifest、私有操作目录、专属管理员 Token 和 Broker/结果后端")
    broker, backend = urlsplit(environ["F118_E2E_BROKER_URL"]), urlsplit(environ["F118_E2E_RESULT_BACKEND"])
    if (
        broker.scheme not in {"redis", "rediss", "amqp", "amqps"}
        or not broker.hostname
        or backend.scheme not in {"redis", "rediss"}
        or not backend.hostname
    ):
        raise ValueError("真实 E2E 需要显式网络 Broker 和 Redis 结果后端。禁止内存替代")
    manifest = validate_manifest(private_json(environ["F118_E2E_MANIFEST"]))
    directory = Path(environ["F118_E2E_CONTROL_DIR"])
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise ValueError("操作目录必须属于当前用户、非链接且权限为 0700")
    timeout = float(environ.get("F118_E2E_CHECKPOINT_TIMEOUT", "600"))
    if not 5 <= timeout <= 1800:
        raise ValueError("checkpoint 预算必须介于 5—1800 秒")
    # HTTP 日志包含真实回调参数,不能写入常规日志。
    levels = {name: logging.getLogger(name).level for name in ("httpx", "httpcore")}
    for name in levels:
        logging.getLogger(name).setLevel(logging.WARNING)
    from celery import Celery

    worker = Celery(
        "f118-live-tests", broker=environ["F118_E2E_BROKER_URL"], backend=environ["F118_E2E_RESULT_BACKEND"]
    )
    worker.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_accept_content=["json"],
        task_publish_retry=False,
        broker_connection_timeout=5,
        broker_transport_options={"socket_connect_timeout": 5, "socket_timeout": 5, "max_retries": 0},
        redis_socket_connect_timeout=5,
        redis_socket_timeout=5,
        result_backend_transport_options={"retry_policy": {"timeout": 5, "max_retries": 0}},
    )
    async with httpx.AsyncClient(
        base_url=manifest["origin"], timeout=30, follow_redirects=False, trust_env=False
    ) as admin:
        journey = Journey(manifest, OperatorBridge(directory, timeout), environ["F118_E2E_ADMIN_TOKEN"], admin, worker)
        try:
            yield journey
        finally:
            try:
                await journey.cleanup()
            finally:
                for client in journey.clients:
                    await client.aclose()
                for name, level in levels.items():
                    logging.getLogger(name).setLevel(level)
                worker.close()
