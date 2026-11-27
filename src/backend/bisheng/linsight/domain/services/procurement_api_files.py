# ruff: noqa: RUF001
"""D procurement native-API adapter: durable JSON first, small receipt second.

The HTTP API remains external. This adapter binds the already-authorized tool to
the current task's WorkspaceBackend; model arguments never choose its workspace.
"""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import logging
import os
import re
import stat
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

from langchain.agents.middleware.types import AgentMiddleware, ModelResponse
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, ConfigDict, Field, SkipValidation, model_validator

# Deployment-owned registration binding; defaults preserve the published D slot.
# The model cannot choose these values. New platforms assign their own IDs/keys.
PROCUREMENT_TOOL_NAME = os.environ.get("PROCUREMENT_NATIVE_TOOL_KEY", "tool_type_21_df150bfcffc4d3a398f68301818e9165")
PROCUREMENT_TOOL_ID = os.environ.get("PROCUREMENT_NATIVE_TOOL_ID", "44")
MAX_JSON_BYTES = 64 * 1024 * 1024
CODE_TOOL_NAME = "bisheng_code_interpreter"
FINAL_MARKER = "__BISHENG_PROCUREMENT_FINAL_V1__"
EXECUTION_FAILURE = "采购固定入口未能完成本轮处理，已停止。请检查技能资源或隔离执行服务；本次失败不表示没有历史数据。"
PARALLEL_ACTION = "__parallel_not_supported__"

AUTO_AUTH_BASE = os.environ.get("PROCUREMENT_API_ORIGIN", "http://procurement-api:18768").rstrip("/")
AUTO_AUTH_CALL = "/openapi/tic-definition/integrationInterface/call?functionCode=mock_procurement_history_v1"
AUTO_AUTH_CONFIG = Path("/app/data/procurement-private/client.json")
AUTO_AUTH_CACHE = Path("/app/data/procurement-private/token-cache.json")


class ProcurementAuthError(RuntimeError):
    """Safe fixed reason only; never include an HTTP body or private configuration."""


class _NoProcurementRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ProcurementTokenManager:
    """Server-side short-lived bearer cache, shared across processes with flock.

    No administrator session, persistent bearer or model-supplied destination.
    Only a 401/invalid_token permits one token refresh and query replay.
    """

    LOCK_WAIT_SECONDS = 10

    def __init__(self, config_path=AUTO_AUTH_CONFIG, cache_path=AUTO_AUTH_CACHE, approved_base=AUTO_AUTH_BASE):
        self.config_path, self.cache_path = Path(config_path), Path(cache_path)
        self.approved_base = approved_base

    @staticmethod
    def _private_parent(path):
        try:
            value = path.parent.lstat()
            if not stat.S_ISDIR(value.st_mode) or value.st_uid != os.geteuid() or stat.S_IMODE(value.st_mode) & 0o077:
                raise ProcurementAuthError("private_directory_permissions")
        except OSError:
            raise ProcurementAuthError("private_directory_unavailable") from None

    @staticmethod
    def _read_private(path):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        except OSError:
            raise ProcurementAuthError("private_file_unavailable") from None
        with os.fdopen(fd, "rb") as source:
            mode = os.fstat(source.fileno())
            if not stat.S_ISREG(mode.st_mode) or mode.st_uid != os.geteuid() or stat.S_IMODE(mode.st_mode) & 0o077:
                raise ProcurementAuthError("private_file_permissions")
            raw = source.read(65537)
        if len(raw) > 65536:
            raise ProcurementAuthError("private_file_budget")
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else None
        except (ValueError, UnicodeError):
            return None

    def _config(self):
        self._private_parent(self.config_path)
        value = self._read_private(self.config_path)
        if (
            not isinstance(value, dict)
            or set(value) != {"base_url", "functionCode", "appKey", "appSecret"}
            or value["base_url"] != self.approved_base
            or value["functionCode"] != "mock_procurement_history_v1"
            or not all(isinstance(value.get(k), str) and 12 <= len(value[k]) <= 4096 for k in ("appKey", "appSecret"))
        ):
            raise ProcurementAuthError("private_config_invalid")
        return value

    @staticmethod
    def _post(url, body, token=None, limit=MAX_JSON_BYTES):
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        try:
            data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
            request = urllib.request.Request(url, data=data, headers=headers, method="POST")
            opener = urllib.request.build_opener(_NoProcurementRedirect())
            try:
                response = opener.open(request, timeout=8)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                raw = response.read(limit + 1)
                status_code = response.code
            if len(raw) > limit:
                raise ProcurementAuthError("http_response_budget")
            return status_code, raw
        except ProcurementAuthError:
            raise
        except Exception:
            raise ProcurementAuthError("http_transport_error") from None

    def token(self, rejected=None):
        config = self._config()
        self._private_parent(self.cache_path)
        fingerprint = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        lock_path = self.cache_path.with_suffix(".lock")
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        except OSError:
            raise ProcurementAuthError("cache_lock_unavailable") from None
        with os.fdopen(fd, "a+b") as lock:
            mode = os.fstat(lock.fileno())
            if not stat.S_ISREG(mode.st_mode) or mode.st_uid != os.geteuid() or stat.S_IMODE(mode.st_mode) & 0o077:
                raise ProcurementAuthError("cache_lock_permissions")
            deadline = time.monotonic() + self.LOCK_WAIT_SECONDS
            while True:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise ProcurementAuthError("cache_lock_timeout") from None
                    time.sleep(0.05)
            cache = self._read_private(self.cache_path) or {}
            now = time.time()
            ttl, expiry = cache.get("expires_in"), cache.get("expires_at")
            value = cache.get("access_token")
            cache_valid = (
                cache.get("config_fingerprint") == fingerprint
                and isinstance(value, str)
                and re.fullmatch(r"[A-Za-z0-9._~-]{16,4096}", value)
                and type(ttl) is int
                and 1 <= ttl <= 7200
                and type(expiry) in (int, float)
                and expiry == expiry
                and now < expiry <= now + 7200
                and now + min(30, ttl / 10) < expiry
            )
            if cache_valid and value != rejected:
                return value
            status_code, raw = self._post(
                self.approved_base + "/authapi/getToken", {k: config[k] for k in ("appKey", "appSecret")}, limit=16384
            )
            if status_code != 200:
                raise ProcurementAuthError("token_issue_http_" + str(status_code))
            try:
                issued = json.loads(raw)
                value, ttl = issued["access_token"], issued["expires_in"]
                assert issued["errcode"] == 0 and isinstance(value, str)
                assert re.fullmatch(r"[A-Za-z0-9._~-]{16,4096}", value)
                assert type(ttl) is int and 1 <= ttl <= 7200
            except Exception:
                raise ProcurementAuthError("token_issue_invalid_response") from None
            # Start expiry from before the token request, conservatively.
            generation = cache.get("generation", 0)
            if type(generation) is not int or not 0 <= generation < 1000000000:
                generation = 0
            reason = "server_401" if rejected is not None else "expired_or_missing"
            updated = {
                "access_token": value,
                "expires_in": ttl,
                "expires_at": now + ttl,
                "issued_at": now,
                "config_fingerprint": fingerprint,
                "generation": generation + 1,
                "refresh_reason": reason,
            }
            tmp_name = None
            try:
                with tempfile.NamedTemporaryFile(
                    "w", dir=self.cache_path.parent, prefix=".token-", delete=False
                ) as target:
                    tmp_name = target.name
                    json.dump(updated, target)
                    target.flush()
                    os.fsync(target.fileno())
                os.replace(tmp_name, self.cache_path)
            except Exception:
                if tmp_name:
                    Path(tmp_name).unlink(missing_ok=True)
                raise ProcurementAuthError("cache_write_failed") from None
            logging.getLogger("bisheng.procurement.auth").info(
                "PROCUREMENT_TOKEN_REFRESH reason=%s ttl=%s generation=%s", reason, ttl, generation + 1
            )
            return value

    def query(self, url, params, body, extra):
        if (
            url != self.approved_base + AUTO_AUTH_CALL
            or params not in ({}, None)
            or extra
            or not isinstance(body, dict)
            or set(body) != {"requestQuery"}
        ):
            raise ProcurementAuthError("query_scope_mismatch")
        token = self.token()
        status_code, raw = self._post(url, body, token)
        if status_code == 401:
            try:
                invalid = json.loads(raw).get("code") == "invalid_token"
            except Exception:
                invalid = False
            if invalid:
                logging.getLogger("bisheng.procurement.auth").warning(
                    "PROCUREMENT_TOKEN_REJECTED http_status=401 retry_budget=1"
                )
                token = self.token(rejected=token)
                status_code, raw = self._post(url, body, token)
        if status_code != 200:
            raise ProcurementAuthError("query_http_" + str(status_code))
        try:
            return raw.decode("utf-8")
        except UnicodeError:
            raise ProcurementAuthError("query_invalid_encoding") from None


class ProcurementAutoAuthHTTP:
    def __init__(self, manager=None):
        self.manager = manager or ProcurementTokenManager()

    def __repr__(self):
        return "<ProcurementAutoAuthHTTP>"

    async def apost(self, url, params=None, json=None, **extra):
        return await asyncio.to_thread(self.manager.query, url, params, json, extra)


def authenticated_native_procurement_tool(inner):
    """Clone the HTTP owner only; native ToolExecutor still checks current ACL/use.

    Plain BaseTools used by synthetic adapter tests have no native tool_instance.
    They remain unchanged. A real native ToolExecutor must match the trusted
    deployment registration and fixed endpoint before receiving credentials.
    """
    instance = getattr(inner, "tool_instance", None)
    if instance is None:
        return inner
    if not re.fullmatch(r"[1-9][0-9]{0,9}", PROCUREMENT_TOOL_ID) or not re.fullmatch(
        r"tool_type_[1-9][0-9]*_[a-f0-9]{32}", PROCUREMENT_TOOL_NAME
    ):
        raise ProcurementAuthError("native_tool_scope_configuration")
    owner = getattr(getattr(instance, "coroutine", None), "__self__", None)
    if (
        getattr(inner, "tool_id", None) != int(PROCUREMENT_TOOL_ID)
        or inner.name != PROCUREMENT_TOOL_NAME
        or owner is None
        or owner.url != AUTO_AUTH_BASE
        or owner.params.get("path") != AUTO_AUTH_CALL
        or owner.params.get("method", "").lower() != "post"
    ):
        raise ProcurementAuthError("native_tool_scope_mismatch")
    copied_owner = owner.model_copy(update={"async_client": ProcurementAutoAuthHTTP()})
    copied_instance = instance.model_copy(update={"coroutine": copied_owner.arun})
    return inner.model_copy(update={"tool_instance": copied_instance})


def _invalid_constant(_value: str) -> None:
    raise ValueError("Non-finite number in JSON")


def failure(status: str) -> dict:
    messages = {
        "api_error": "采购接口调用失败，未取得可分析的完整数据。",
        "invalid_api_response": "采购接口返回格式不符合约定，未进行历史分析。",
        "file_error": "采购原始JSON未成功保存，已停止分析；请检查任务文件服务。",
    }
    return {"status": status, "terminal": False, "next_action": "run_fixed_entry", "message": messages[status]}


def prepare(result: Any) -> tuple[bytes, dict]:
    """Preserve a native JSON string verbatim; validate only the transport shell."""
    if isinstance(result, str):
        if not result or len(result) > MAX_JSON_BYTES:
            raise ValueError("Invalid response budget")
        raw = result.encode("utf-8")
        if len(raw) > MAX_JSON_BYTES:
            raise ValueError("Invalid response budget")
        payload = json.loads(result, parse_constant=_invalid_constant)
    elif isinstance(result, dict):
        raw = json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
        payload = result
    else:
        raise ValueError("Unsupported tool response")
    if not raw or len(raw) > MAX_JSON_BYTES or not isinstance(payload, dict):
        raise ValueError("Invalid response budget")
    if payload.get("success") is not True:
        raise RuntimeError("API returned failure")
    outer = payload.get("data")
    if not isinstance(outer, dict) or outer.get("status") != 200:
        raise RuntimeError("API business status failed")
    data = outer.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("result"), list):
        raise ValueError("Missing result list")
    # Do not return rows, field mappings or previews to the model. Full validation
    # and business projections belong to the Skill's fixed execution entrypoint.
    query = data.get("query")
    if not isinstance(query, dict) or set(query) != {"model", "match_mode"}:
        raise ValueError("Invalid query metadata")
    if (
        not isinstance(query["model"], str)
        or not 1 <= len(query["model"]) <= 256
        or query["match_mode"] not in ("exact", "regex")
    ):
        raise ValueError("Invalid query metadata values")
    metadata = {"query": {"model": query["model"], "match_mode": query["match_mode"]}}
    for key, minimum, maximum in (
        ("pageNum", 1, 100000),
        ("pageSize", 1, 10000),
        ("totalElements", 0, 1000000000),
        ("totalPages", 0, 1000000000),
        ("matchedModelCount", 0, 1000000000),
    ):
        value = data.get(key)
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError("Invalid paging metadata")
        metadata[key] = value
    for key in ("hasNext", "mock"):
        if type(data.get(key)) is not bool:
            raise ValueError("Invalid boolean metadata")
        metadata[key] = data[key]
    snapshot = data.get("snapshotId")
    if not isinstance(snapshot, str) or not 1 <= len(snapshot) <= 128:
        raise ValueError("Invalid snapshot metadata")
    metadata["snapshotId"] = snapshot
    if len(json.dumps(metadata, ensure_ascii=False).encode("utf-8")) > 2048:
        raise ValueError("Receipt metadata exceeds budget")
    return raw, metadata


async def persist_response(result: Any, backend: Any) -> dict:
    try:
        raw, metadata = prepare(result)
    except RuntimeError:
        return failure("api_error")
    except Exception:
        return failure("invalid_api_response")
    file_path = "/uploads/procurement-api/" + uuid4().hex + ".json"
    try:
        responses = await backend.aupload_files([(file_path, raw)])
        # WorkspaceBackend can populate its cache before a MinIO failure. A cache
        # hit is not proof of persistence: every upload response must succeed.
        if len(responses) != 1 or responses[0].error or responses[0].path != file_path:
            return failure("file_error")
    except Exception:
        return failure("file_error")
    return {
        "status": "api_json_saved",
        "raw_json_file": file_path.lstrip("/"),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        **metadata,
    }


class ProcurementApiFileTool(BaseTool):
    name: str
    description: str
    args_schema: Annotated[ArgsSchema | None, SkipValidation()] = Field(default=None)
    inner: BaseTool = Field(exclude=True, repr=False)
    workspace: Any = Field(exclude=True, repr=False)
    response_format: Literal["content_and_artifact"] = "content_and_artifact"

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        receipt = failure("api_error")
        return json.dumps(receipt, ensure_ascii=False), None

    async def _arun(self, config: RunnableConfig | None = None, **kwargs: Any) -> Any:
        try:
            # Native ToolExecutor still enforces permission and account checks.
            native = authenticated_native_procurement_tool(self.inner)
            result = await native.ainvoke(kwargs, config=config)
        except Exception:
            receipt = failure("api_error")
        else:
            receipt = await persist_response(result, self.workspace)
        artifact = completion_artifact(receipt["message"]) if receipt.get("terminal") is True else None
        return json.dumps(receipt, ensure_ascii=False), artifact


def bind_procurement_api_files(tools: list, backend: Any) -> list:
    bound = []
    for tool in tools:
        if getattr(tool, "name", None) != PROCUREMENT_TOOL_NAME:
            bound.append(tool)
            continue
        if isinstance(tool, ProcurementApiFileTool):
            if tool.workspace is backend:
                bound.append(tool)
                continue
            tool = tool.inner
        bound.append(
            ProcurementApiFileTool(
                name=tool.name,
                args_schema=tool.args_schema,
                inner=tool,
                workspace=backend,
                description=(
                    tool.description + "\n成功时原始JSON已保存在当前任务工作区；"
                    "返回raw_json_file和分页元数据，不返回明细预览。"
                    "将各页raw_json_file传给采购Skill固定入口；错误回执不重试，单型号用api_failure，多型号在items对应项写error_kind并继续其他项，最后一次batch。"
                ),
            )
        )
    return bound


class ProcurementFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    supplier: str | None = None
    customer: str | None = None
    date_from: str | None = Field(default=None, description="确认日期起，YYYY-MM-DD，含当日")
    date_to: str | None = Field(default=None, description="确认日期止，YYYY-MM-DD，含当日")
    currency: str | None = None
    unit: str | None = None
    incoterms: str | None = None
    incoterms_place: str | None = None


class ProcurementItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: str = Field(min_length=1, max_length=256)
    error_kind: Literal["api_error", "invalid_api_response", "file_error"] | None = None
    page_files: list[str] | None = None
    set: ProcurementFilters | None = None
    unset: (
        list[
            Literal["supplier", "customer", "date_from", "date_to", "currency", "unit", "incoterms", "incoterms_place"]
        ]
        | None
    ) = None
    sort: Literal["time_desc", "price_asc", "price_desc", "none"] | None = None
    page_size: int | None = Field(
        default=None, ge=1, le=50, description="Chat展示每页1—50，默认20；不是API的pageSize，不照抄API页大小"
    )
    purchaser: str | None = None


class ProcurementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="before")
    @classmethod
    def ignore_unknown_null_placeholders(cls, value):
        # Some tool providers append unused optional nulls (observed sort_by=None).
        # Null has no condition/action value. Never discard a non-null unknown field.
        if isinstance(value, dict):
            return {k: v for k, v in value.items() if k in cls.model_fields or v is not None}
        return value

    action: Literal[
        "history",
        "show",
        "filter",
        "compare",
        "suppliers",
        "reset",
        "batch",
        "batch_summary",
        "resolve",
        "choose",
        "confirm",
        "confirmations",
        "unconfirm",
        "explain_limits",
        "api_failure",
        "help",
        "__parallel_not_supported__",
    ]
    model: str | None = Field(default=None, description="首次查询的完整型号或API原样正则")
    match_mode: Literal["exact", "regex"] | None = None
    reference_model: str | None = Field(default=None, description="regex时原始目标型号")
    page_files: list[str] | None = Field(default=None, description="仅首次，API各页回执raw_json_file的原样数组")
    target_model: str | None = None
    item_index: int | None = Field(default=None, description="手动多型号输入项序号，区别于价格记录/相近型号序号")
    items: list[ProcurementItem] | None = Field(default=None, min_length=1, max_length=20)
    intent: Literal["history", "suppliers"] | None = Field(
        default=None,
        description="本轮目的；batch/choose/resolve使用。resolve新型号精确结果省略默认history，已有待核对沿原意图。",
    )
    decision: Literal["keep", "correct"] | None = None
    candidate_position: int | None = None
    supplier_id: str | None = None
    supplier_name: str | None = None
    confirmation_id: str | None = None
    topic: Literal["delivery", "sourcing"] | None = None
    error_kind: Literal["api_error", "invalid_api_response", "file_error"] | None = None
    set: ProcurementFilters | None = Field(
        default=None, description="本轮全部筛选，history/suppliers首问也必须带齐；字段不可放顶层"
    )
    unset: (
        list[
            Literal["supplier", "customer", "date_from", "date_to", "currency", "unit", "incoterms", "incoterms_place"]
        ]
        | None
    ) = None
    sort: Literal["time_desc", "price_asc", "price_desc", "none"] | None = None
    page: int | None = None
    page_size: int | None = Field(
        default=None, ge=1, le=50, description="Chat展示每页1—50，默认20；不是API的pageSize，不照抄API页大小"
    )
    positions: list[int] | None = None
    line_ids: list[str] | None = None
    purchaser: str | None = Field(
        default=None,
        description="本次甲方持续状态；明确切换必须传新名称，其他甲方也传；省略沿用。支持history/show/filter/suppliers",
    )

    @model_validator(mode="after")
    def action_field_contract(self):
        criteria = {"set", "unset", "sort", "page_size", "purchaser"}
        shared = {"action", "item_index"}
        contracts = {
            "history": {"model", "match_mode", "reference_model", "page_files", "target_model", "page", *criteria},
            "suppliers": {"model", "match_mode", "reference_model", "page_files", "target_model", "page", *criteria},
            "show": {"target_model", "page", "sort", "page_size", "purchaser"},
            "filter": {"target_model", "page", *criteria},
            "compare": {"target_model", "positions", "line_ids"},
            "reset": {"target_model"},
            "batch": {"items", "intent", *criteria},
            "batch_summary": set(),
            "resolve": {"decision", "model", "page_files", "match_mode", "reference_model", "intent", *criteria},
            "choose": {"candidate_position", "target_model", "intent", *criteria},
            "confirm": {"supplier_id", "supplier_name", "target_model"},
            "confirmations": {"confirmation_id"},
            "unconfirm": {"confirmation_id"},
            "explain_limits": {"topic"},
            "api_failure": {"model", "error_kind"},
            "help": set(),
            "__parallel_not_supported__": set(),
        }
        permitted = contracts[self.action] | shared
        present = {key for key in self.model_fields_set if getattr(self, key) is not None}
        if present - permitted:
            raise ValueError(
                "动作 "
                + self.action
                + " 不接受字段 "
                + ",".join(sorted(present - permitted))
                + "；本动作只允许 "
                + ",".join(sorted(permitted))
            )
        if (
            self.action in {"history", "suppliers"}
            and self.page_files is None
            and (present & {"match_mode", "reference_model"})
        ):
            raise ValueError(
                "续问没有page_files时不得传match_mode/reference_model；保持原用户全部筛选、甲方、排序，仅移除不适用匹配字段后纠正一次。"
            )
        return self


class ProcurementActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request: ProcurementRequest = Field(
        description="采购动作。一次带齐用户本轮全部set筛选与sort排序；只用下列明确字段，不附API回执元数据、不再嵌套request。执行后立即结束。"
    )


def completion_artifact(answer: str) -> dict:
    return {"protocol": "procurement-fixed-entry-v1", "terminal": True, "next_action": "none", "answer": answer}


def execution_code(request: dict) -> str:
    """Only data is variable; no model-authored Python or shell is executed."""
    encoded = json.dumps(request, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode("utf-8")) > 65536:
        raise ValueError("Request exceeds budget")
    return (
        "import importlib.util,json,sys\n"
        "from pathlib import Path\n"
        "_path=Path('skills/procurement-history/scripts/procurement.py')\n"
        "sys.path.insert(0,str(_path.parent))\n"
        "_spec=importlib.util.spec_from_file_location('procurement_fixed_entry',_path)\n"
        "_module=importlib.util.module_from_spec(_spec)\n"
        "sys.modules[_spec.name]=_module\n"
        "_spec.loader.exec_module(_module)\n"
        "_result=_module.run(json.loads(" + repr(encoded) + "))\n"
        "_final={k:_result[k] for k in ('protocol','status','terminal','next_action','answer','outcome','models')}\n"
        "print(" + repr(FINAL_MARKER) + "+json.dumps(_final,ensure_ascii=False,allow_nan=False))\n"
    )


def execution_answer(result: Any, request=None) -> str:
    if isinstance(result, str):
        if len(result.encode("utf-8")) > MAX_JSON_BYTES:
            raise ValueError("Executor output exceeds budget")
        result = json.loads(result, parse_constant=_invalid_constant)
    if not isinstance(result, dict) or type(result.get("exitcode")) is not int or result["exitcode"] != 0:
        raise ValueError("Executor did not succeed")
    log = result.get("log")
    if not isinstance(log, str):
        raise ValueError("Missing execution log")
    records = [line[len(FINAL_MARKER) :] for line in log.splitlines() if line.startswith(FINAL_MARKER)]
    if len(records) != 1:
        raise ValueError("Missing unique completion record")
    envelope = json.loads(records[0], parse_constant=_invalid_constant)
    if (
        not isinstance(envelope, dict)
        or envelope.get("protocol") != "procurement-fixed-entry-v1"
        or envelope.get("terminal") is not True
        or envelope.get("next_action") != "none"
        or envelope.get("status") not in ("final", "user_clarification")
    ):
        raise ValueError("Invalid completion record")
    answer = envelope.get("answer")
    if not isinstance(answer, str) or not answer.strip() or len(answer.encode("utf-8")) > 131072:
        raise ValueError("Invalid final answer")
    return business_process("procurement", request, envelope) if request is not None else answer


class ProcurementExecutionTool(BaseTool):
    name: str = CODE_TOOL_NAME
    description: str = (
        "采购Skill唯一固定执行入口。输入request动作JSON，不输入Python代码。"
        "history仅展示历史价格、条件与来源，不附供应商推荐；用户明确要供应商时才用suppliers或topic=sourcing。历史后要供应商沿用批次，不再取API。首次history或suppliers传model、match_mode、page_files；多型号用batch/items各项自己的model和page_files。"
        "API失败不重试；单型号api_failure/model/error_kind；多型号items失败项填error_kind，继续其他项，最后batch。"
        "API精确结果即使0条也先history/suppliers登记；多个输入先batch登记，不预先regex或resolve。"
        "精确未命中后用resolve：修正correct或确认无误keep并取限定regex新结果；choose/candidate_position选择相近型号。"
        "choose可带intent=suppliers及本轮criteria，一次选型号并给供应商结果，不计划第二次工具。"
        "batch_summary汇总；item_index指定输入项。confirm/supplier_name记录当前推荐表或供应商视图中已展示的供应商；confirmations查看，unconfirm撤销，均限本Chat。"
        "explain_limits/topic=delivery说明交付数据缺口；topic=sourcing按当前型号分开展示历史供应商与名录候选（不混排、不设统一首选，无历史也按物料寻源）；用户要推荐供应商时用suppliers或topic=sourcing。"
        "一次带齐用户本轮全部要求：history/suppliers同时支持set筛选与sort排序/分页，filter也可同时带sort。"
        "此工具返回即结束，不能先无条件history再计划追加筛选或排序。"
        "供应商排序用suppliers+sort；show/filter保留当前视图。明确切换甲方用suppliers+purchaser，其他甲方也显式传名称，省略会沿用。compare/positions、reset。"
        "它确定性处理会话、价格与QPL/QSL表，直接给出最终中文答复并结束当前轮。"
    )
    args_schema: Annotated[ArgsSchema | None, SkipValidation()] = ProcurementActionInput
    return_direct: bool = False
    response_format: Literal["content_and_artifact"] = "content_and_artifact"
    inner: BaseTool = Field(exclude=True, repr=False)

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Procurement task execution requires the async tool path")

    async def _arun(self, request: dict, config: RunnableConfig | None = None) -> tuple:
        try:
            if isinstance(request, BaseModel):
                request = request.model_dump(exclude_unset=True, exclude_none=True)
            if request == {"action": PARALLEL_ACTION}:
                answer = "本轮包含多个并行采购动作，已停止；请先明确一个查询、筛选或比较操作。"
            else:
                raw = await self.inner.ainvoke({"python_code": execution_code(request)}, config=config)
                answer = execution_answer(raw, request)
        except Exception as exc:
            diagnostic = {"result_type": type(locals().get("raw")).__name__}
            value = locals().get("raw")
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except Exception:
                    value = None
            if isinstance(value, dict):
                log = value.get("log")
                diagnostic.update(
                    exitcode=value.get("exitcode"),
                    keys=sorted(value),
                    log_bytes=len(log.encode()) if isinstance(log, str) else None,
                    final_markers=log.count(FINAL_MARKER) if isinstance(log, str) else None,
                )
            # Structural diagnostics only: never log user rows, model arguments,
            # raw executor output, tokens or provider configuration.
            logging.getLogger("bisheng.procurement").warning(
                "PROCUREMENT_EXECUTION_FAILURE action=%s exception=%s reason=%s shape=%s",
                request.get("action") if isinstance(request, dict) else None,
                type(exc).__name__,
                str(exc) if type(exc) is ValueError else "execution-path-error",
                diagnostic,
            )
            answer = EXECUTION_FAILURE
        # The original tool-call AIMessage must remain last: LangChain's
        # return_direct routing uses it. Artifact survives result offloading and
        # is consumed by TaskExec, without asking a model to rewrite the answer.
        return answer, completion_artifact(answer)


def bind_procurement_tools(tools: list, backend: Any, selected_skills: Any = None) -> list:
    tools = bind_procurement_api_files(tools, backend)
    if isinstance(selected_skills, list) and "order-tracking" in selected_skills:
        return [
            OrderExecutionTool(inner=tool)
            if getattr(tool, "name", None) == CODE_TOOL_NAME and not isinstance(tool, OrderExecutionTool)
            else tool
            for tool in tools
        ]
    if not isinstance(selected_skills, list) or "procurement-history" not in selected_skills:
        return tools
    return [
        tool
        if getattr(tool, "name", None) != CODE_TOOL_NAME or isinstance(tool, ProcurementExecutionTool)
        else ProcurementExecutionTool(inner=tool)
        for tool in tools
    ]


def extract_procurement_completion(messages: Any) -> str | None:
    if not isinstance(messages, (list, tuple)) or not messages:
        return None
    last = messages[-1]
    name = last.get("name") if isinstance(last, dict) else getattr(last, "name", None)
    artifact = last.get("artifact") if isinstance(last, dict) else getattr(last, "artifact", None)
    kind = last.get("type", last.get("role")) if isinstance(last, dict) else getattr(last, "type", None)
    if kind in {"ai", "assistant"}:
        extra = last.get("additional_kwargs", {}) if isinstance(last, dict) else getattr(last, "additional_kwargs", {})
        artifact = extra.get("procurement_completion") if isinstance(extra, dict) else None
        if not isinstance(artifact, dict):
            return None
        name = CODE_TOOL_NAME
    elif name not in (CODE_TOOL_NAME, PROCUREMENT_TOOL_NAME) or kind != "tool":
        return None
    if not isinstance(artifact, dict):
        status = last.get("status") if isinstance(last, dict) else getattr(last, "status", None)
        if name == PROCUREMENT_TOOL_NAME and status != "error":
            return None  # A successful API receipt deliberately continues to the entrypoint.
        return EXECUTION_FAILURE
    if (
        artifact.get("protocol") not in ("procurement-fixed-entry-v1", "order-fixed-entry-v1")
        or artifact.get("terminal") is not True
        or artifact.get("next_action") != "none"
    ):
        return EXECUTION_FAILURE
    answer = artifact.get("answer")
    if not isinstance(answer, str) or not answer.strip() or len(answer.encode("utf-8")) > 131072:
        return EXECUTION_FAILURE
    return answer


def explicit_input_index(messages: Any) -> int | None:
    """Bind only an unambiguous positive item ordinal in the latest real user message."""
    for message in reversed(messages or []):
        get = (
            (lambda key, message=message: message.get(key))
            if isinstance(message, dict)
            else (lambda key, message=message: getattr(message, key, None))
        )
        kind = get("type") or get("role")
        if kind not in {"human", "user"}:
            continue
        content = get("content")
        if isinstance(content, list):
            content = "\n".join(
                block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
            )
        if not isinstance(content, str):
            return None
        # Native tasks prepend a history summary to this same HumanMessage.
        # Only the platform-delimited current question may bind an item.
        header = r"(?m)^# 用户问题[ \t]*\r?\n"
        if re.search(header, content):
            prefix = re.split(r"(?m)^# (?:可用文件|可用知识库)[^\n]*\r?\n", content, maxsplit=1)[0]
            markers = list(re.finditer(header, prefix))
            if not markers:
                return None
            content = prefix[markers[-1].end() :]
        if re.search(r"不是|不要|不处理|别处理|不要动|不动|\bnot\b|don.t", content, re.I):
            return None
        values = []
        digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
        for token in re.findall(r"第\s*([0-9]{1,2}|[一二三四五六七八九十]{1,3})\s*项", content):
            if token.isascii() and token.isdecimal():
                value = int(token)
            elif token in digits:
                value = digits[token]
            elif token == "十":
                value = 10
            elif token == "二十":
                value = 20
            elif len(token) == 2 and token.startswith("十") and token[1] in digits:
                value = 10 + digits[token[1]]
            else:
                return None
            if not 1 <= value <= 20:
                return None
            values.append(value)
        return values[0] if values and len(set(values)) == 1 and 1 <= values[0] <= 30 else None
    return None


class ProcurementSerialMiddleware(AgentMiddleware):
    """A fixed entry is one state transition; never execute it in parallel."""

    @staticmethod
    def _serial(state: dict) -> dict | None:
        messages = state.get("messages") or []
        if not messages or not isinstance(messages[-1], AIMessage):
            return None
        last = messages[-1]
        fixed = [call for call in last.tool_calls if call.get("name") == CODE_TOOL_NAME]
        if not fixed:
            return None
        call = dict(fixed[0])
        changed = len(last.tool_calls) > 1
        if len(fixed) > 1:
            call["args"] = {"request": {"action": PARALLEL_ACTION}}
        else:
            args = call.get("args")
            req = args.get("request") if isinstance(args, dict) else None
            index = explicit_input_index(messages[:-1])
            scoped = {
                "history",
                "suppliers",
                "show",
                "filter",
                "compare",
                "reset",
                "resolve",
                "choose",
                "confirm",
                "api_failure",
            }
            if (
                index is not None
                and isinstance(req, dict)
                and req.get("action") in scoped
                and req.get("item_index") != index
            ):
                # Scope comes from the real user, never a tool result or the model's remembered focus.
                call["args"] = {**args, "request": {**req, "item_index": index}}
                changed = True
                logging.getLogger("bisheng.procurement").info("PROCUREMENT_INPUT_SCOPE_BOUND index=%s", index)
        if not changed:
            return None
        return {"messages": [last.model_copy(update={"tool_calls": [call], "invalid_tool_calls": []})]}

    def after_model(self, state, runtime):
        return self._serial(state)

    async def aafter_model(self, state, runtime):
        return self._serial(state)

    def __init__(self):
        self._final_guard_used = False
        self._parameter_retry_used = False

    @staticmethod
    def _parameter_error(request):
        messages = request.state.get("messages") or []
        if not messages:
            return False
        last = messages[-1]
        get = (lambda key: last.get(key)) if isinstance(last, dict) else (lambda key: getattr(last, key, None))
        return get("name") == CODE_TOOL_NAME and get("status") == "error" and not isinstance(get("artifact"), dict)

    def _correct_parameters(self, request):
        self._parameter_retry_used = True
        logging.getLogger("bisheng.procurement").warning("PROCUREMENT_PARAMETER_RETRY one_correction_only")
        return request.override(
            messages=[
                *request.messages,
                SystemMessage(
                    content=(
                        "上一采购工具请求未通过参数校验，尚未执行业务动作。现在只允许按原用户意图纠正一次参数，禁止改变甲方/型号/筛选或编数据。"
                        "仅一个request，动作不能带不适用字段；resolve不传target_model，confirm不传purchaser；choose可带intent及筛选；"
                        "展示page_size为1—50，不能照抄API页大小。请仅调用采购固定执行器。"
                    )
                ),
            ],
            tool_choice={"type": "function", "function": {"name": CODE_TOOL_NAME}},
        )

    @staticmethod
    def _has_tool_calls(response):
        return any(getattr(message, "tool_calls", None) for message in response.result)

    def _required_entry(self, request):
        self._final_guard_used = True
        instruction = SystemMessage(
            content=(
                "采购本轮必须经固定执行器给出结果，禁止凭记忆自行确认、拒绝、建议切甲方或编数据。"
                "请仅调用bisheng_code_interpreter，以一个request选择准确动作。"
                "确认/撤销即使目标不可推荐也用confirm/unconfirm由代码判定；"
                "未取得新API数据不得复用旧型号；API失败用api_failure，多项用batch保留error_kind；"
                "缺型号或仅问使用方法用help；已有空批次核对状态用resolve；相近选择用choose。"
            )
        )
        return request.override(
            messages=[*request.messages, instruction],
            tool_choice={"type": "function", "function": {"name": CODE_TOOL_NAME}},
        )

    @staticmethod
    def _unexecuted():
        answer = "本轮未能形成有效采购动作，已停止；没有确认供应商或改变业务条件。请提供完整型号，或明确要查询、比价、选择供应商、确认或撤销。"
        return ModelResponse(
            result=[
                AIMessage(content=answer, additional_kwargs={"procurement_completion": completion_artifact(answer)})
            ]
        )

    def wrap_model_call(self, request, handler):
        if self._parameter_error(request):
            if self._parameter_retry_used:
                return self._unexecuted()
            response = handler(self._correct_parameters(request))
            return response if self._has_tool_calls(response) else self._unexecuted()
        answer = extract_procurement_completion(request.state.get("messages"))
        if answer is not None:
            return ModelResponse(
                result=[
                    AIMessage(content=answer, additional_kwargs={"procurement_completion": completion_artifact(answer)})
                ]
            )
        response = handler(request)
        if self._has_tool_calls(response):
            return response
        if self._final_guard_used:
            return self._unexecuted()
        response = handler(self._required_entry(request))
        return response if self._has_tool_calls(response) else self._unexecuted()

    async def awrap_model_call(self, request, handler):
        if self._parameter_error(request):
            if self._parameter_retry_used:
                return self._unexecuted()
            response = await handler(self._correct_parameters(request))
            return response if self._has_tool_calls(response) else self._unexecuted()
        answer = extract_procurement_completion(request.state.get("messages"))
        if answer is not None:
            return ModelResponse(
                result=[
                    AIMessage(content=answer, additional_kwargs={"procurement_completion": completion_artifact(answer)})
                ]
            )
        response = await handler(request)
        if self._has_tool_calls(response):
            return response
        if self._final_guard_used:
            return self._unexecuted()
        response = await handler(self._required_entry(request))
        return response if self._has_tool_calls(response) else self._unexecuted()


# Generated from assistant-workbench/process_summary.py
"""A bounded, source-backed business execution recap, never model internal reasoning.

This pure function is embedded into the three already-mounted tool adapters by
build_release.py. It does not modify the underlying business answer or compute fees.
"""


def business_process(scene, request, result):
    import json

    if not isinstance(request, dict) or not isinstance(result, dict):
        return result.get("answer", "") if isinstance(result, dict) else ""
    answer = result.get("answer", "")
    if not isinstance(answer, str) or not answer:
        return answer
    if answer.startswith("```business-process\n"):
        return answer
    action = request.get("action", "show")
    outcome = result.get("outcome", "unknown")
    names = {"procurement": "采购", "transport": "运输", "customs": "报关"}
    nodes = []

    def add(title, summary, status="done", details=None):
        nodes.append(
            {
                "title": title,
                "summary": str(summary)[:500],
                "status": status,
                "details": [str(x)[:600] for x in (details or [])][:8],
            }
        )

    labels = {
        "model": "规格型号",
        "target_model": "当前型号",
        "purchaser": "本次甲方",
        "origin": "起点",
        "destination": "目的地",
        "mode": "运输方式",
        "dangerous_goods": "危化属性",
        "net_weight_kg": "净重kg",
        "gross_weight_kg": "毛重kg",
        "house_numbers": "分单号",
        "bill_numbers": "账单号",
        "date_from": "起始日期",
        "date_to": "截止日期",
        "currency": "币种",
        "carrier": "服务商",
        "sort": "排序",
        "reference": "费用引用",
        "supplier_name": "询价对象",
    }
    conditions = []
    for source in [request, request.get("query"), request.get("target"), request.get("set")]:
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if key in labels and value is not None:
                conditions.append(labels[key] + "：" + str(value)[:160])
    action_names = {
        "history": "历史查询",
        "suppliers": "供应商选取",
        "compare": "记录比价",
        "filter": "条件筛选",
        "reset": "恢复条件",
        "show": "查看结果",
        "inquiry": "寻找历史参考",
        "detail": "单据追溯",
        "confirm": "确认询价对象",
        "unconfirm": "撤销确认",
        "confirmations": "查看确认记录",
        "choose": "选择近似型号",
        "resolve": "型号核对",
        "help": "输入引导",
        "explain_limits": "说明数据边界",
    }
    add("理解本轮需求", action_names.get(action, "按本轮要求处理"), details=conditions)
    failed = outcome in {
        "execution_error",
        "source_unavailable",
        "state_error",
        "validation_error",
        "invalid_request",
        "stale_source",
        "stale_reference",
        "query_error",
        "invalid_query",
        "file_or_state_error",
        "api_failure",
        "api_error",
        "api_timeout",
        "invalid_filter",
        "invalid_regex",
    }
    waiting = result.get("status") == "user_clarification" or outcome in {
        "needs_clarification",
        "needs_input",
        "needs_query",
        "needs_new_query",
        "needs_correction",
        "pending_correction",
        "pending_candidates",
        "awaiting_correction",
        "awaiting_selection",
        "no_exact_match",
        "invalid_selection",
        "page_out_of_range",
    }
    if scene == "procurement" and "请核对是否需要修正" in answer:
        waiting = True
    empty = outcome in {"no_records", "no_exact_history", "no_history"}
    if failed:
        add("本轮处理未完成", "本次失败不能解释为没有历史记录", "error", [answer[:450]])
        add("恢复处理", "请按错误提示重试或补充；未获得的数据不作结论", "pending")
    elif scene == "procurement":
        models = result.get("models") or []
        if isinstance(models, list) and models:
            if "型号差异：原始目标为" in answer:
                add(
                    "按确认执行近似召回",
                    "返回" + str(len(models[:3])) + "个近似型号，按型号分别展示",
                    details=["型号：" + str(m.get("model", "")) for m in models[:3] if isinstance(m, dict)]
                    + ["规格差异和可替代性尚未核验，不合并不同型号价格"],
                )
            for model in models[:3]:
                if not isinstance(model, dict):
                    continue
                c = model.get("counts") or {}
                sc = model.get("supplier_counts") or {}
                add(
                    "核对历史与筛选",
                    str(model.get("model", "当前型号"))
                    + " · 原批次"
                    + str(c.get("original_batch_records", 0))
                    + "条，当前匹配"
                    + str(c.get("total_matches", 0))
                    + "条",
                    "empty" if not c.get("total_matches") else "done",
                    [
                        "生效筛选：" + json.dumps(model.get("active_filters", {}), ensure_ascii=False),
                        "本次数据已由固定执行入口校验；价格按型号分别展示",
                    ],
                )
                recommendation_in_answer = model.get("view") == "history" and "**供应商推荐" in answer
                if (
                    model.get("view") == "suppliers"
                    or sc.get("historical_supplier_groups", 0)
                    or recommendation_in_answer
                ):
                    buyer = model.get("purchaser") or request.get("purchaser")
                    if buyer in ["空客", "空中客车", "Airbus", "airbus", "商飞", "中国商飞", "COMAC", "comac"]:
                        name = "QPL" if buyer in ["空客", "空中客车", "Airbus", "airbus"] else "QSL"
                        recap = (
                            "已依据" + name + "名单生成本轮推荐；具体候选与证据见下方"
                            if recommendation_in_answer
                            else "历史条件组"
                            + str(sc.get("historical_supplier_groups", 0))
                            + "项 · 保留"
                            + str(sc.get("total_items", 0))
                            + "项 · 排除或待核验"
                            + str(sc.get("excluded_supplier_groups", 0))
                            + "项"
                        )
                        add(
                            "按甲方核验 " + name,
                            recap,
                            "done",
                            [
                                "名单命中、未列入、待核验分别按实际结果显示",
                                "所给版本的主体和产品适用范围见业务结果中的名录证据",
                            ],
                        )
                    else:
                        add("核对名录要求", "本次甲方未指定，或按现有范围无需核验名录", "skipped")
            add(
                "形成本轮结果",
                "按生效条件展示；价格排序与可比口径详见下方",
                details=["沿用用户当前排序和筛选，不生成新的报价或交付指标"],
            )
        elif action in ["confirm", "unconfirm", "confirmations"]:
            add(
                "更新本对话确认记录",
                {"confirm": "记录本次询价对象", "unconfirm": "撤销本次确认", "confirmations": "读取已有确认记录"}[
                    action
                ],
                details=["记录仅限本对话，不向订单系统下单"],
            )
        elif waiting or empty:
            add(
                "核对型号与可用数据",
                "需要补充或选择后继续；具体原因见下方",
                "waiting" if waiting else "empty",
                [answer[:450]],
            )
        else:
            add("执行本轮处理", "固定入口已返回本轮结果", details=["动作：" + str(action), "结果状态：" + str(outcome)])
        if waiting:
            add("等待你确认或补充", "后续步骤暂停，按下方提示回复即可", "waiting")
        elif empty:
            add("本轮查询无匹配", "仅针对当前取数范围和条件，不表示全部历史无记录", "empty")
        elif action not in ["confirm", "unconfirm", "confirmations"]:
            add("查看与继续", "可继续筛选、比较或确认询价对象")
    else:
        if waiting:
            add("核对必要条件", "需要补齐条件后继续匹配", "waiting", [answer[:450]])
            add("等待你补充", "尚未完成匹配和费用判断", "pending")
        elif outcome == "capability_limits":
            add("核对数据边界", "当前能力与缺失项见下方说明")
        else:
            match = result.get("match") or {}
            counts = result.get("counts") or {}
            kind = match.get("match_type", "history")
            history_empty = empty or kind == "no_records"
            recommendations = result.get("recommendation") or []
            if isinstance(recommendations, list) and recommendations:
                tiers = [r.get("tier", 0) for r in recommendations if isinstance(r, dict)]
                cross = bool(tiers) and min(tiers) >= 3
                add(
                    "整理" + ("运输方案" if scene == "transport" else "报关代理") + "候选",
                    str(len(recommendations))
                    + "项"
                    + ("相近经验推荐；当前硬条件没有历史匹配" if history_empty else "历史经验推荐"),
                    details=["跨线路或目的港经验只用于候选参考，不作为当前硬条件命中的费用"]
                    if cross
                    else ["推荐依据和历史金额口径见下方；不构成本次正式报价"],
                )
            labels_match = {
                "history": "按单据与条件查询历史",
                "full": "完整条件匹配",
                "approximate": "近似条件匹配",
                "no_records": "当前条件暂无匹配",
            }
            add(
                "核对查询与匹配",
                labels_match.get(kind, "按当前条件匹配"),
                "empty" if history_empty else "done",
                [
                    "保护条件："
                    + ("线路、运输方式、危化属性" if scene == "transport" else "目的港、危化属性；重量采用毛重口径"),
                    "逐级匹配步骤：" + json.dumps(match.get("steps", []), ensure_ascii=False)[:550],
                ],
            )
            if result.get("reference_strength") == "protected_only":
                add(
                    "核对参考强度",
                    "仅保护条件命中，物料、重量和尺寸均未匹配；属于弱参考",
                    details=["历史总额不构成本次正式报价，不能将弱匹配讲成同条件价格"],
                )
            if counts:
                add(
                    "核对费用与完整覆盖",
                    str(counts.get("matched_details", 0))
                    + "条命中明细 · "
                    + str(counts.get("unique_bills", 0))
                    + "张去重账单",
                    "empty" if history_empty else "done",
                    ["共享账单按完整覆盖展示，总额去重，不自动分摊", "金额、币种、日期及匹配差异见业务结果"],
                )
            add(
                "展示" + ("单据详情" if action == "detail" else "历史参考"),
                "当前硬条件无历史匹配；候选推荐另行说明"
                if history_empty
                else "结果与依据已返回，可继续查看详情或调整条件",
                "empty" if history_empty else "done",
            )
    demo = any(
        str(v).startswith("DEMO-Q")
        for v in [
            request.get("model"),
            request.get("target_model"),
            *[m.get("model") for m in result.get("models", []) if isinstance(m, dict)],
        ]
    )
    payload = {
        "version": 1,
        "scene": scene,
        "title": names.get(scene, "业务") + "分析过程",
        "action": action,
        "outcome": outcome,
        "mode": "execution_recap",
        "demo": demo,
        "conditions": conditions[:12],
        "nodes": nodes[:12],
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("`", "\\u0060")
    return (
        "```business-process\n"
        + encoded
        + "\n```\n\n"
        + ("> 模拟演示数据：型号、订单、价格与日期为合成；名单证据引用所提供版本。\n\n" if demo else "")
        + answer
    )


# Additive order-only fixed entry. Existing procurement/API adapters remain unchanged.


async def inherit_order_context(minio, src_svid, dst_svid):
    """Carry one server-owned state object from MinIO truth, never scratch caches."""
    if not all(re.fullmatch(r"[a-f0-9]{32}", str(value)) for value in (src_svid, dst_svid)) or src_svid == dst_svid:
        return
    path = "scratch/order-assistant-context.json"

    def read(svid):
        try:
            return minio.get_object_sync(bucket_name=minio.bucket, object_name=f"workspace/{svid}/{path}")
        except Exception as error:
            if getattr(error, "code", None) == "NoSuchKey":
                return None
            raise

    if await asyncio.to_thread(read, dst_svid) is not None:
        return  # Includes a newer empty tombstone; never replace it from history.
    content = await asyncio.to_thread(read, src_svid)
    if content is None or len(content) > 16384 or not isinstance(json.loads(content), dict):
        return
    await asyncio.to_thread(minio.put_object_sync, bucket_name=minio.bucket,
                            object_name=f"workspace/{dst_svid}/{path}", file=content)


async def restore_order_context(backend, file_dir):
    path = Path(file_dir) / "scratch/order-assistant-context.json"
    if path.parent.is_symlink() or path.is_symlink() or (path.exists() and not path.is_file()):
        return None
    return await asyncio.to_thread(backend.ensure_local, "scratch/order-assistant-context.json")


class OrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["overview", "orders", "detail", "alerts", "reminder", "help"]
    order: str | None = Field(default=None, max_length=80)
    position: int | None = Field(default=None, ge=1, le=30)
    node: Literal["payment", "delivery", "settlement", "all"] | None = None
    window: Literal["all", "attention", "past", "today", "week", "month", "future", "missing"] | None = None
    supplier: str | None = Field(default=None, max_length=150)
    material: str | None = Field(default=None, max_length=150)
    mode: Literal["7", "30", "off", "default"] | None = None
    as_of: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    limit: int | None = Field(default=None, ge=1, le=30)
    offset: int | None = Field(default=None, ge=0, le=500)


class OrderActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request: OrderRequest


class OrderExecutionTool(BaseTool):
    name: str = CODE_TOOL_NAME
    description: str = (
        "AI订单助手唯一固定执行入口，只输入request动作JSON，不输入Python代码。"
        "overview概览；orders查订单；detail按完整order订单号看物料金额与三类日期；alerts按node和window筛日期。"
        "node为payment/delivery/settlement/all；window为past/today/week/month/future/missing/attention/all。"
        "reminder只生成待确认设置链接，须明确order、单node和mode=7/30/off/default，不保存或发送。"
        "续问detail/reminder可省略order沿用当前Chat唯一焦点；明确列表序号用position，不能与order同时给。供应商/物料用supplier/material。"
        "返回即结束；最终答复由执行器直接给出，禁止模型改写金额、日期或追加业务推测。"
    )
    args_schema: Annotated[ArgsSchema | None, SkipValidation()] = OrderActionInput
    return_direct: bool = False
    response_format: Literal["content_and_artifact"] = "content_and_artifact"
    inner: BaseTool = Field(exclude=True, repr=False)

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Order execution requires async path")

    async def _arun(self, request: dict, config: RunnableConfig | None = None) -> tuple:
        try:
            if isinstance(request, BaseModel):
                request = request.model_dump(exclude_unset=True, exclude_none=True)
            request = {k: v for k, v in request.items() if v is not None}
            encoded = json.dumps(request, ensure_ascii=False, allow_nan=False)
            if len(encoded.encode()) > 65536:
                raise ValueError("Request exceeds budget")
            code = (
                "import importlib.util,json\nfrom pathlib import Path\n"
                "p=Path('skills/order-tracking/scripts/run.py')\n"
                "s=importlib.util.spec_from_file_location('order_fixed_entry',p)\n"
                "m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n"
                "r=m.execute(json.loads(" + repr(encoded) + "))\n"
                "print('__ORDER_FIXED_FINAL__'+json.dumps({'protocol':'order-fixed-entry-v1','terminal':True,'next_action':'none','answer':r['answer']},ensure_ascii=False))\n"
            )
            raw = await self.inner.ainvoke({"python_code": code}, config=config)
            value = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(value, dict) or value.get("exitcode") != 0:
                raise ValueError("Executor failed")
            records = [
                line[len("__ORDER_FIXED_FINAL__") :]
                for line in value.get("log", "").splitlines()
                if line.startswith("__ORDER_FIXED_FINAL__")
            ]
            if len(records) != 1:
                raise ValueError("Completion record missing")
            envelope = json.loads(records[0])
            answer = envelope.get("answer")
            if (
                envelope.get("protocol") != "order-fixed-entry-v1"
                or not isinstance(answer, str)
                or not answer.strip()
                or len(answer.encode()) > 131072
            ):
                raise ValueError("Invalid completion record")
        except Exception as exc:
            logging.getLogger("bisheng.orders").warning("ORDER_EXECUTION_FAILURE exception=%s", type(exc).__name__)
            answer = "订单查询本次未能完成。请稍后重试；查询失败不代表没有订单，未更改任何提醒设置。"
        return answer, {"protocol": "order-fixed-entry-v1", "terminal": True, "next_action": "none", "answer": answer}


class OrderMiddleware(AgentMiddleware):
    """Return the authenticated fixed executor answer, never a model rewrite."""

    def __init__(self):
        self._retry = False
        self._forced = False

    @staticmethod
    def _question(messages):
        for msg in reversed(messages):
            get = (
                (lambda k, msg=msg: msg.get(k)) if isinstance(msg, dict) else (lambda k, msg=msg: getattr(msg, k, None))
            )
            if (get("type") or get("role")) not in {"human", "user"}:
                continue
            content = get("content")
            if isinstance(content, list):
                content = "\n".join(
                    x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "text"
                )
            if not isinstance(content, str):
                return ""
            prefix = re.split(r"(?m)^# (?:可用文件|可用知识库)[^\n]*\r?\n", content, maxsplit=1)[0]
            markers = list(re.finditer(r"(?m)^# 用户问题[ \t]*\r?\n", prefix))
            return prefix[markers[-1].end() :] if markers else content
        return ""

    @staticmethod
    def _turn_order(messages):
        """Only this user's explicit identity may replace the fixed executor's focus.

        A landing-page context is a first-turn seed, not a standing instruction.
        Later model arguments must not revive an old order from conversation history
        after the fixed entry has rejected or invalidated a switch.
        """
        question = OrderMiddleware._question(messages)
        contextual = re.match(
            r"^(?:当前订单|Current order|現在の注文)[:：]\s*([^\r\n]+)\s*\n+"
            r"(?:用户问题|User question|ユーザーの質問)[:：]\s*([\s\S]*)$",
            question,
        )
        user_question = contextual[2] if contextual else question
        identities = set(
            re.findall(r"(?<![A-Za-z0-9_/-])(?:DEMO-ORDER-[A-Z0-9-]+|SIM-ORDER-\d+|26DMAC/ZDA\d{3}(?:US|CH|HK))(?![A-Za-z0-9_/-])", user_question, re.I)
        )
        identities.update(
            re.findall(r"(?:订单(?:号)?|\border\s+(?:number\b|no\.?(?=\s|[:：#]))|注文番号)\s*[:：#]?\s*([A-Z0-9][A-Z0-9/_-]{2,79})", user_question, re.I)
        )
        identities = {identity.upper() for identity in identities}
        if identities:
            return next(iter(identities)) if len(identities) == 1 else "__UNRESOLVED_ORDER_SWITCH__"
        if re.search(
            r"第[一二三四五六七八九十0-9]+(?:个|笔|项|条)|\b(?:first|second|third)\s+(?:order|one|item)|(?:最初|[一二三四五六七八九十0-9]+番目)の?(?:注文|項目)",
            user_question, re.I,
        ):
            return None if OrderMiddleware._turn_position(messages) is not None else "__UNRESOLVED_ORDER_SELECTION__"
        if re.search(r"切换|换到|改查|另(?:一|外).*订单|switch\s+(?:to|order)|切り替|別の注文", user_question, re.I):
            return "__UNRESOLVED_ORDER_SWITCH__"
        human_messages = [
            msg for msg in messages
            if (msg.get("type") or msg.get("role") if isinstance(msg, dict) else getattr(msg, "type", None)) in {"human", "user"}
        ]
        has_history = len(human_messages) > 1 or any(
            "# 前情回顾" in str(msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", ""))
            for msg in human_messages
        )
        return contextual[1].strip() if contextual and not has_history else None

    @staticmethod
    def _turn_position(messages):
        question = OrderMiddleware._question(messages)
        question = re.split(r"(?:用户问题|User question|ユーザーの質問)[:：]", question)[-1]
        numerals = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        values = []
        for value in re.findall(r"第([一二三四五六七八九十0-9]+)(?:个|笔|项|条)|([一二三四五六七八九十0-9]+)番目", question):
            token = next(part for part in value if part)
            number = int(token) if token.isascii() and token.isdigit() else numerals.get(token)
            if number is None and token.count("十") == 1:
                tens, ones = token.split("十")
                if (not tens or tens in numerals) and (not ones or ones in numerals):
                    number = numerals.get(tens, 1) * 10 + numerals.get(ones, 0)
            if number is not None:
                values.append(number)
        values.extend({"first": 1, "second": 2, "third": 3}[word.lower()] for word in re.findall(r"\b(first|second|third)\s+(?:order|one|item)", question, re.I))
        if "最初の注文" in question:
            values.append(1)
        return values[0] if values and len(set(values)) == 1 and 1 <= values[0] <= 30 else None

    @staticmethod
    def _serial(state):
        messages = state.get("messages") or []
        if not messages or not isinstance(messages[-1], AIMessage):
            return None
        last = messages[-1]
        calls = [c for c in last.tool_calls if c.get("name") == CODE_TOOL_NAME]
        if not last.tool_calls:
            return None
        if not calls and all(
            c.get("name") == "write_todos"
            or (
                c.get("name") == "read_file"
                and str(c.get("args", {}).get("file_path", c.get("args", {}).get("path", "")))
                .replace("\\", "/")
                .endswith("skills/order-tracking/SKILL.md")
            )
            for c in last.tool_calls
        ):
            return None
        changed = len(last.tool_calls) > 1 or len(calls) != 1
        if len(calls) != 1:
            call = (
                dict(calls[0])
                if calls
                else {"id": last.tool_calls[0].get("id", "order-safe-help"), "name": CODE_TOOL_NAME}
            )
            question = OrderMiddleware._question(messages[:-1])
            req = {"action": "help"}
            if "提醒" in question:
                req = {"action": "reminder"}
                match = re.search(r"26DMAC/ZDA\d{3}(?:US|CH|HK)", question)
                if match:
                    req["order"] = match.group()
                if re.search(r"(?:30|三十)\s*天(?:之)?后", question):
                    req["mode"] = "30"
                elif re.search(r"(?:7|七)\s*天(?:之)?后", question):
                    req["mode"] = "7"
            call["args"] = {"request": req}
        else:
            call = dict(calls[0])
            args = call.get("args") or {}
            req = args.get("request")
            if isinstance(req, dict) and req.get("action") == "reminder":
                req = dict(req)
                question = OrderMiddleware._question(messages[:-1])
                ns = [
                    n
                    for n, pattern in [
                        ("payment", r"付款|支付"),
                        ("delivery", r"交付|交货|交期"),
                        ("settlement", r"结算"),
                    ]
                    if re.search(pattern, question)
                ]
                if len(ns) == 1:
                    req["node"] = ns[0]
                elif len(ns) > 1:
                    req["node"] = "all"
                else:
                    req.pop("node", None)
                modes = [
                    m
                    for m, pattern in [
                        ("7", r"(?:(?:7|七)\s*天(?:之)?后|(?:延后|推迟)\s*(?:7|七)\s*天)"),
                        ("30", r"(?:(?:30|三十)\s*天(?:之)?后|(?:延后|推迟)\s*(?:30|三十)\s*天)"),
                        ("off", r"(?:不再|停止|取消).{0,12}提醒"),
                        ("default", r"默认提醒|按规则提醒|恢复默认|恢复.{0,12}提醒"),
                    ]
                    if re.search(pattern, question)
                ]
                if len(modes) == 1:
                    req["mode"] = modes[0]
                else:
                    req.pop("mode", None)
                if req != args.get("request"):
                    call["args"] = {**args, "request": req}
                    changed = True
        args = call.get("args") or {}
        if isinstance(args.get("request"), dict):
            req = dict(args["request"])
            order = OrderMiddleware._turn_order(messages[:-1])
            position = OrderMiddleware._turn_position(messages[:-1]) if order is None else None
            req.pop("position", None)
            if order is None:
                req.pop("order", None)
                if position is not None:
                    req["position"] = position
                    if req.get("action") != "reminder":
                        req["action"] = "detail"
            else:
                req["order"] = order
            if req != args["request"]:
                call["args"] = {**args, "request": req}
                changed = True
        if not changed:
            return None
        fixed = AIMessage(
            content=last.content,
            id=last.id,
            name=last.name,
            tool_calls=[call],
            additional_kwargs={
                k: v for k, v in last.additional_kwargs.items() if k not in {"tool_calls", "function_call"}
            },
            response_metadata=last.response_metadata,
        )
        return {"messages": [fixed]}

    def after_model(self, state, runtime):
        return None

    async def aafter_model(self, state, runtime):
        return None

    def _normalise(self, response, request):
        changed = self._serial({"messages": [*request.messages, *response.result]})
        if not changed:
            return response
        return ModelResponse(result=[*response.result[:-1], changed["messages"][0]])

    @staticmethod
    def _terminal(answer):
        artifact = {"protocol": "order-fixed-entry-v1", "terminal": True, "next_action": "none", "answer": answer}
        return ModelResponse(result=[AIMessage(content=answer, additional_kwargs={"procurement_completion": artifact})])

    def _guard(self, request):
        messages = request.state.get("messages") or []
        last = messages[-1] if messages else None
        get = (lambda k: last.get(k)) if isinstance(last, dict) else (lambda k: getattr(last, k, None))
        bad = get("name") == CODE_TOOL_NAME and get("status") == "error" and not isinstance(get("artifact"), dict)
        if bad:
            if self._retry:
                return self._terminal(
                    "本次订单参数未能核对，未修改任何设置。请提供完整订单号、日期节点或提醒周期。"
                ), None
            self._retry = True
            text = "上一订单工具参数未通过校验，尚未执行。仅纠正一次request参数；按原用户意图调用订单固定执行器，不输入python_code，不改变订单或日期条件。"
        else:
            if self._forced:
                return self._terminal("本轮未能形成有效订单查询，未修改任何设置。请明确要查询的订单或日期范围。"), None
            self._forced = True
            text = "订单问题必须经固定执行器核对。只调用bisheng_code_interpreter，输入request动作JSON；不自行回答、判断付款状态或声称已保存提醒。无法执行的任务调用help。"
        return None, request.override(
            messages=[*request.messages, SystemMessage(content=text)],
            tool_choice={"type": "function", "function": {"name": CODE_TOOL_NAME}},
        )

    @staticmethod
    def _calls(response):
        return any(getattr(m, "tool_calls", None) for m in response.result)

    def wrap_model_call(self, request, handler):
        if ProcurementSerialMiddleware._parameter_error(request):
            final, forced = self._guard(request)
            if final:
                return final
            response = handler(forced)
            return (
                self._normalise(response, request)
                if self._calls(response)
                else self._terminal("订单参数未能核对，未修改设置。请补充订单号、节点或周期。")
            )
        answer = extract_procurement_completion(request.state.get("messages"))
        if answer is not None:
            return self._terminal(answer)
        response = handler(request)
        if self._calls(response):
            return self._normalise(response, request)
        final, forced = self._guard(request)
        if final:
            return final
        response = handler(forced)
        return (
            self._normalise(response, request)
            if self._calls(response)
            else self._terminal("本轮订单查询未完成，未修改任何设置。请补充订单号或日期条件后重试。")
        )

    async def awrap_model_call(self, request, handler):
        if ProcurementSerialMiddleware._parameter_error(request):
            final, forced = self._guard(request)
            if final:
                return final
            response = await handler(forced)
            return (
                self._normalise(response, request)
                if self._calls(response)
                else self._terminal("订单参数未能核对，未修改设置。请补充订单号、节点或周期。")
            )
        answer = extract_procurement_completion(request.state.get("messages"))
        if answer is not None:
            return self._terminal(answer)
        response = await handler(request)
        if self._calls(response):
            return self._normalise(response, request)
        final, forced = self._guard(request)
        if final:
            return final
        response = await handler(forced)
        return (
            self._normalise(response, request)
            if self._calls(response)
            else self._terminal("本轮订单查询未完成，未修改任何设置。请补充订单号或日期条件后重试。")
        )
