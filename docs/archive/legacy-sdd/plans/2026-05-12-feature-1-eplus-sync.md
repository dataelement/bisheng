# Feature 1 — E+ 站内信同步 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 BiSheng 站内信中频道订阅 / 知识空间加入的 6 个 action_code 异步转发到中粮 E+ 消息中心，textcard 点击回跳后 client 自动打开站内信弹窗。

**Architecture:** 在 `MessageService.send_message()` 末尾加非阻塞钩子，BackgroundTasks 排程到 `CofcoEPlusClient`；E+ textcard 的 `url` 字段拼接 `?open-notifications=1&message-id=...`，client 端 `useSearchParams` hook 检测并打开 `NotificationsDialog`（tab 选择/scroll/highlight 推到 v2）。失败 fire-and-forget，纯 WARN 日志，不阻塞主流程。

**Tech Stack:** FastAPI / httpx / pydantic（backend）；React 18 + Recoil + react-router v6（client app）；TDD with pytest + vitest。

**Related spec:** `docs/archive/legacy-sdd/specs/2026-05-12-2.6-features-1-and-6-design.md`（§1 系列）

## Logging（简约版，客户环境快速定位）

只打 3 类事件，每条 1 行，统一格式 `forward.<event> message_id=<id> action_code=<code> ...`：

| 事件名 | 级别 | 何时打 | 字段 |
|---|---|---|---|
| `forward.skipped` | INFO | 短路：开关关 / 不在白名单 / 接收人解析失败 | `message_id, action_code, reason` |
| `forward.attempt` | INFO | HTTP POST 前 | `message_id, action_code, recipient` |
| `forward.result` | INFO（code=0）/ WARN（其它） | HTTP POST 后（或异常） | `message_id, code, elapsed_ms, msg` |

排障操作：`grep "message_id=42"` → 必有 1 条 `forward.skipped` 或 1 对 `forward.attempt` + `forward.result`。


**File map:**

| 操作 | 文件 |
|---|---|
| Create | `src/backend/bisheng/notification/__init__.py` |
| Create | `src/backend/bisheng/notification/external/__init__.py` |
| Create | `src/backend/bisheng/notification/external/cofco_eplus_client.py` |
| Create | `src/backend/bisheng/notification/external/_payload.py` |
| Create | `src/backend/bisheng/notification/forwarder.py` |
| Modify | `src/backend/bisheng/core/config/settings.py`（追加 config 类） |
| Modify | `src/backend/bisheng/message/domain/services/message_service.py:47-70`（在 send_message 末尾加钩子） |
| Create | `src/backend/tests/notification/test_payload.py` |
| Create | `src/backend/tests/notification/test_cofco_eplus_client.py` |
| Create | `src/backend/tests/notification/test_forwarder.py` |
| Create | `src/frontend/client/src/hooks/useNotificationsFromUrl.ts` |
| Modify | `src/frontend/client/src/layouts/UserPopMenu.tsx`（两个变体都接入 hook） |
| Modify | `src/frontend/client/src/components/NotificationsDialog.tsx`（接收 initialTab + focusedMessageId props） |

---

## Task 1: Add config schema for `in_app_message_forwarding`

**Files:**
- Modify: `src/backend/bisheng/core/config/settings.py`
- Test: `src/backend/tests/core/test_settings_cofco_forwarding.py`

- [ ] **Step 1: Write the failing test**

```python
# src/backend/tests/core/test_settings_cofco_forwarding.py
from bisheng.core.config.settings import Settings


def test_in_app_message_forwarding_defaults_disabled():
    s = Settings()
    assert s.in_app_message_forwarding.cofco.enabled is False
    assert s.in_app_message_forwarding.cofco.api_base == ""
    assert s.in_app_message_forwarding.cofco.timeout_seconds == 5.0
    assert s.in_app_message_forwarding.cofco.enable_duplicate_check == 0


def test_in_app_message_forwarding_override():
    s = Settings(
        in_app_message_forwarding={
            "cofco": {
                "enabled": True,
                "api_base": "http://10.28.64.30:8070/qwmsg-ui",
                "app_id": "bisheng",
                "secret": "xxx",
                "agentid": 1,
                "bisheng_inbox_url": "https://bisheng.cofco.com",
            }
        }
    )
    c = s.in_app_message_forwarding.cofco
    assert c.enabled is True
    assert c.api_base.endswith("/qwmsg-ui")
    assert c.agentid == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd src/backend && uv run pytest tests/core/test_settings_cofco_forwarding.py -v
```
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'in_app_message_forwarding'`

- [ ] **Step 3: Implement config classes**

Find the end of the `Settings` class in `src/backend/bisheng/core/config/settings.py`. Add **above** the `Settings` class definition:

```python
from pydantic import BaseModel, Field


class CofcoForwardingConf(BaseModel):
    enabled: bool = Field(default=False)
    api_base: str = Field(default="", description="例：http://10.28.64.30:8070/qwmsg-ui")
    app_id: str = Field(default="")
    secret: str = Field(default="")
    agentid: int | None = Field(default=None)
    timeout_seconds: float = Field(default=5.0)
    bisheng_inbox_url: str = Field(default="", description="回跳 BiSheng client base URL")
    enable_duplicate_check: int = Field(default=0)
    duplicate_check_interval: int = Field(default=1800)


class InAppMessageForwardingConf(BaseModel):
    cofco: CofcoForwardingConf = CofcoForwardingConf()
```

In the existing `Settings` class body, add the new field next to other typed config blocks (look for `celery_task:` or similar):

```python
    in_app_message_forwarding: InAppMessageForwardingConf = InAppMessageForwardingConf()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd src/backend && uv run pytest tests/core/test_settings_cofco_forwarding.py -v
```
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/backend/bisheng/core/config/settings.py src/backend/tests/core/test_settings_cofco_forwarding.py
git commit -m "feat(notification): add in_app_message_forwarding.cofco config schema"
```

---

## Task 2: Implement `_payload.build_textcard` + URL builder

**Files:**
- Create: `src/backend/bisheng/notification/__init__.py`（空）
- Create: `src/backend/bisheng/notification/external/__init__.py`（空）
- Create: `src/backend/bisheng/notification/external/_payload.py`
- Test: `src/backend/tests/notification/__init__.py`（空）
- Test: `src/backend/tests/notification/test_payload.py`

- [ ] **Step 1: Write the failing tests**

```python
# src/backend/tests/notification/test_payload.py
import pytest
from unittest.mock import patch
from bisheng.notification.external._payload import (
    FORWARDABLE_ACTION_CODES,
    build_textcard,
    build_textcard_url,
)


def test_forwardable_set_has_six_codes():
    assert FORWARDABLE_ACTION_CODES == {
        "request_channel", "approved_channel", "rejected_channel",
        "request_knowledge_space", "approved_knowledge_space", "rejected_knowledge_space",
    }


@patch("bisheng.notification.external._payload.settings")
def test_build_textcard_url_basic(mock_settings):
    mock_settings.in_app_message_forwarding.cofco.bisheng_inbox_url = "https://bisheng.cofco.com/"
    url = build_textcard_url(message_id=12345)
    assert url == "https://bisheng.cofco.com/?open-notifications=1&message-id=12345"


@patch("bisheng.notification.external._payload.settings")
def test_build_textcard_url_strips_trailing_slash(mock_settings):
    mock_settings.in_app_message_forwarding.cofco.bisheng_inbox_url = "https://bisheng.cofco.com"
    url = build_textcard_url(message_id=999)
    assert url == "https://bisheng.cofco.com/?open-notifications=1&message-id=999"


@patch("bisheng.notification.external._payload.settings")
def test_build_textcard_request_channel(mock_settings):
    mock_settings.in_app_message_forwarding.cofco.bisheng_inbox_url = "https://bisheng.cofco.com"
    card = build_textcard(
        message_id=1,
        action_code="request_channel",
        applicant_name="张三",
        resource_name="技术频道",
        triggered_at="2026-05-13 10:30",
    )
    assert card["title"] == "[知源] 新的频道订阅申请"
    assert "张三 申请订阅频道「技术频道」" in card["description"]
    assert "需要你审批" in card["description"]
    assert "2026-05-13 10:30" in card["description"]
    assert card["btntxt"] == "去查看"
    assert "open-notifications=1" in card["url"]


@patch("bisheng.notification.external._payload.settings")
def test_build_textcard_approved_knowledge_space(mock_settings):
    mock_settings.in_app_message_forwarding.cofco.bisheng_inbox_url = "https://bisheng.cofco.com"
    card = build_textcard(
        message_id=2, action_code="approved_knowledge_space",
        applicant_name="李四", resource_name="研发知识空间", triggered_at="2026-05-13 11:00",
    )
    assert card["title"] == "[知源] 知识空间加入申请已通过"
    assert "你加入知识空间「研发知识空间」的申请" in card["description"]
    assert "已通过" in card["description"]


def test_build_textcard_unknown_action_code_raises():
    with pytest.raises(KeyError):
        build_textcard(
            message_id=3, action_code="unknown_code",
            applicant_name="A", resource_name="B", triggered_at="2026-05-13 12:00",
        )


@patch("bisheng.notification.external._payload.settings")
def test_build_textcard_truncates_long_title(mock_settings):
    """E+ 接口 title ≤128 字节、description ≤512 字节"""
    mock_settings.in_app_message_forwarding.cofco.bisheng_inbox_url = "https://bisheng.cofco.com"
    long_name = "X" * 1000
    card = build_textcard(
        message_id=4, action_code="request_channel",
        applicant_name=long_name, resource_name=long_name, triggered_at="2026-05-13 12:00",
    )
    assert len(card["title"].encode("utf-8")) <= 128
    assert len(card["description"].encode("utf-8")) <= 512
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd src/backend && uv run pytest tests/notification/test_payload.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'bisheng.notification'`

- [ ] **Step 3: Create module init files**

```bash
touch src/backend/bisheng/notification/__init__.py
touch src/backend/bisheng/notification/external/__init__.py
touch src/backend/tests/notification/__init__.py
```

- [ ] **Step 4: Implement `_payload.py`**

Create `src/backend/bisheng/notification/external/_payload.py`:

```python
"""Build E+ textcard payloads from action_codes."""
from bisheng.core.config import settings


FORWARDABLE_ACTION_CODES: set[str] = {
    "request_channel",
    "approved_channel",
    "rejected_channel",
    "request_knowledge_space",
    "approved_knowledge_space",
    "rejected_knowledge_space",
}


_TEMPLATES: dict[str, dict[str, str]] = {
    "request_channel": {
        "title": "[知源] 新的频道订阅申请",
        "normal": "{applicant} 申请订阅频道「{resource_name}」",
        "highlight": "需要你审批",
    },
    "approved_channel": {
        "title": "[知源] 频道订阅申请已通过",
        "normal": "你订阅频道「{resource_name}」的申请",
        "highlight": "已通过",
    },
    "rejected_channel": {
        "title": "[知源] 频道订阅申请被拒绝",
        "normal": "你订阅频道「{resource_name}」的申请",
        "highlight": "被拒绝",
    },
    "request_knowledge_space": {
        "title": "[知源] 新的知识空间加入申请",
        "normal": "{applicant} 申请加入知识空间「{resource_name}」",
        "highlight": "需要你审批",
    },
    "approved_knowledge_space": {
        "title": "[知源] 知识空间加入申请已通过",
        "normal": "你加入知识空间「{resource_name}」的申请",
        "highlight": "已通过",
    },
    "rejected_knowledge_space": {
        "title": "[知源] 知识空间加入申请被拒绝",
        "normal": "你加入知识空间「{resource_name}」的申请",
        "highlight": "被拒绝",
    },
}


def build_textcard_url(message_id: int) -> str:
    base = settings.in_app_message_forwarding.cofco.bisheng_inbox_url.rstrip("/")
    return f"{base}/?open-notifications=1&message-id={message_id}"


def _truncate_bytes(text: str, max_bytes: int) -> str:
    """按 UTF-8 字节数截断（不破坏多字节字符）。"""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    # 二分查找最大可保留的字符数
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(text[:mid].encode("utf-8")) <= max_bytes:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo]


def build_textcard(
    *,
    message_id: int,
    action_code: str,
    applicant_name: str,
    resource_name: str,
    triggered_at: str,
) -> dict:
    """Build the `textcard` dict for E+ /v2/message/send body.

    Returns a dict with keys: title, description, url, btntxt.
    Raises KeyError when action_code is unknown.
    """
    tpl = _TEMPLATES[action_code]
    title = _truncate_bytes(tpl["title"], 128)
    normal = tpl["normal"].format(applicant=applicant_name, resource_name=resource_name)
    description = (
        f'<div class="gray">{triggered_at}</div>'
        f'<div class="normal">{normal}</div>'
        f'<div class="highlight">{tpl["highlight"]}</div>'
    )
    description = _truncate_bytes(description, 512)
    return {
        "title": title,
        "description": description,
        "url": build_textcard_url(message_id),
        "btntxt": "去查看",
    }
```

- [ ] **Step 5: Run tests to verify pass**

```bash
cd src/backend && uv run pytest tests/notification/test_payload.py -v
```
Expected: PASS (8 passed)

- [ ] **Step 6: Commit**

```bash
git add src/backend/bisheng/notification/ src/backend/tests/notification/__init__.py src/backend/tests/notification/test_payload.py
git commit -m "feat(notification): add textcard payload builder for 6 action_codes"
```

---

## Task 3: Implement `CofcoEPlusClient.send_textcard`

**Files:**
- Create: `src/backend/bisheng/notification/external/cofco_eplus_client.py`
- Test: `src/backend/tests/notification/test_cofco_eplus_client.py`

- [ ] **Step 1: Write the failing tests**

```python
# src/backend/tests/notification/test_cofco_eplus_client.py
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from bisheng.notification.external.cofco_eplus_client import CofcoEPlusClient


@pytest.fixture
def mock_settings():
    with patch("bisheng.notification.external.cofco_eplus_client.settings") as m:
        m.in_app_message_forwarding.cofco.api_base = "http://10.28.64.30:8070/qwmsg-ui"
        m.in_app_message_forwarding.cofco.app_id = "bisheng"
        m.in_app_message_forwarding.cofco.secret = "secret123"
        m.in_app_message_forwarding.cofco.agentid = 1
        m.in_app_message_forwarding.cofco.timeout_seconds = 5.0
        m.in_app_message_forwarding.cofco.enable_duplicate_check = 0
        m.in_app_message_forwarding.cofco.duplicate_check_interval = 1800
        yield m


@pytest.mark.asyncio
async def test_send_textcard_success_logs_nothing(mock_settings, caplog):
    """code=='0' → no warning."""
    client = CofcoEPlusClient()
    mock_response = MagicMock()
    mock_response.json.return_value = {"code": "0", "msg": "操作成功", "data": "[\"jobid1\"]"}

    with patch("bisheng.notification.external.cofco_eplus_client.httpx.AsyncClient") as ACli:
        ACli.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        await client.send_textcard(
            message_id=1, action_code="request_channel",
            touser=["U001", "U002"],
            textcard={"title": "t", "description": "d", "url": "http://x", "btntxt": "去查看"},
        )

    assert "send_textcard failed" not in caplog.text
    assert "exception" not in caplog.text.lower()


@pytest.mark.asyncio
async def test_send_textcard_code_not_zero_logs_warning(mock_settings, caplog):
    client = CofcoEPlusClient()
    mock_response = MagicMock()
    mock_response.json.return_value = {"code": "82001", "msg": "All touser invalid"}

    with patch("bisheng.notification.external.cofco_eplus_client.httpx.AsyncClient") as ACli:
        ACli.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        await client.send_textcard(
            message_id=2, action_code="approved_channel",
            touser=["U001"], textcard={"title": "t", "description": "d", "url": "u", "btntxt": "b"},
        )

    assert "82001" in caplog.text
    assert "All touser invalid" in caplog.text
    assert "forward.result" in caplog.text
    assert "message_id=2" in caplog.text


@pytest.mark.asyncio
async def test_send_textcard_exception_does_not_raise(mock_settings, caplog):
    """网络异常应吞掉并 WARN。"""
    client = CofcoEPlusClient()
    with patch("bisheng.notification.external.cofco_eplus_client.httpx.AsyncClient") as ACli:
        ACli.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=Exception("network down")
        )
        await client.send_textcard(
            message_id=3, action_code="rejected_channel",
            touser=["U1"], textcard={"title": "t", "description": "d", "url": "u", "btntxt": "b"},
        )

    assert "forward.result" in caplog.text
    assert "code=exception" in caplog.text


@pytest.mark.asyncio
async def test_send_textcard_request_shape(mock_settings):
    """验证 URL / headers / body 结构正确。"""
    client = CofcoEPlusClient()
    mock_response = MagicMock()
    mock_response.json.return_value = {"code": "0"}
    captured = {}

    async def fake_post(url, json=None, headers=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return mock_response

    with patch("bisheng.notification.external.cofco_eplus_client.httpx.AsyncClient") as ACli:
        ACli.return_value.__aenter__.return_value.post = AsyncMock(side_effect=fake_post)
        await client.send_textcard(
            message_id=4, action_code="request_channel",
            touser=["U1", "U2"],
            textcard={"title": "t", "description": "d", "url": "u", "btntxt": "b"},
        )

    assert captured["url"] == "http://10.28.64.30:8070/qwmsg-ui/v2/message/send"
    assert captured["headers"] == {"appId": "bisheng", "secret": "secret123"}
    body = captured["json"]
    assert body["touser"] == "U1|U2"
    assert body["msgtype"] == "textcard"
    assert body["agentid"] == 1
    assert body["textcard"] == {"title": "t", "description": "d", "url": "u", "btntxt": "b"}
    assert body["enable_duplicate_check"] == 0
    assert body["duplicate_check_interval"] == 1800


@pytest.mark.asyncio
async def test_send_textcard_empty_touser_skipped(mock_settings, caplog):
    client = CofcoEPlusClient()
    with patch("bisheng.notification.external.cofco_eplus_client.httpx.AsyncClient") as ACli:
        post = AsyncMock()
        ACli.return_value.__aenter__.return_value.post = post
        await client.send_textcard(message_id=5, action_code="approved_channel", touser=[], textcard={"title": "t"})
        post.assert_not_called()


@pytest.mark.asyncio
async def test_send_textcard_success_emits_attempt_and_result(mock_settings, caplog):
    """成功路径必须打 attempt + result，含 message_id 用于排障。"""
    import logging
    caplog.set_level(logging.INFO)
    client = CofcoEPlusClient()
    mock_response = MagicMock()
    mock_response.json.return_value = {"code": "0", "msg": "ok"}

    with patch("bisheng.notification.external.cofco_eplus_client.httpx.AsyncClient") as ACli:
        ACli.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        await client.send_textcard(
            message_id=42, action_code="request_channel",
            touser=["EMP001"], textcard={"title": "t", "description": "d", "url": "u", "btntxt": "b"},
        )

    assert "forward.attempt" in caplog.text
    assert "forward.result" in caplog.text
    assert "message_id=42" in caplog.text
    assert "code=0" in caplog.text
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd src/backend && uv run pytest tests/notification/test_cofco_eplus_client.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'bisheng.notification.external.cofco_eplus_client'`

- [ ] **Step 3: Implement `cofco_eplus_client.py`**

```python
# src/backend/bisheng/notification/external/cofco_eplus_client.py
"""HTTP client for 中粮 E+ 消息中心 textcard interface."""
import logging
import time
import httpx

from bisheng.core.config import settings

logger = logging.getLogger(__name__)


class CofcoEPlusClient:
    """Thin wrapper over POST /v2/message/send.

    All errors (HTTP-level, non-zero response code, exceptions) are
    swallowed and logged. Callers MUST NOT rely on success to gate
    business logic.

    Logging: emits exactly two lines per call —
      INFO  forward.attempt  message_id=<id> action_code=<code> recipient=<eid>
      INFO  forward.result   message_id=<id> code=<n> elapsed_ms=<ms> msg=<...>
    (WARN level when code != "0" or exception)
    """

    async def send_textcard(
        self,
        *,
        message_id: int,
        action_code: str,
        touser: list[str],
        textcard: dict,
    ) -> None:
        if not touser:
            logger.debug("cofco_eplus send_textcard skipped: empty touser message_id=%s", message_id)
            return

        conf = settings.in_app_message_forwarding.cofco
        url = f"{conf.api_base.rstrip('/')}/v2/message/send"
        headers = {"appId": conf.app_id, "secret": conf.secret}
        body: dict = {
            "touser": "|".join(touser),
            "msgtype": "textcard",
            "textcard": textcard,
            "enable_duplicate_check": conf.enable_duplicate_check,
            "duplicate_check_interval": conf.duplicate_check_interval,
        }
        if conf.agentid is not None:
            body["agentid"] = conf.agentid

        # 1) attempt — proves request is about to fire
        logger.info(
            "forward.attempt message_id=%s action_code=%s recipient=%s",
            message_id, action_code, "|".join(touser),
        )

        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=conf.timeout_seconds) as client:
                resp = await client.post(url, json=body, headers=headers)
                data = resp.json()
                elapsed_ms = int((time.monotonic() - started) * 1000)
                code = str(data.get("code"))
                msg = data.get("msg", "")

                # 2) result — captures E+ response
                if code == "0":
                    logger.info(
                        "forward.result message_id=%s code=%s elapsed_ms=%s msg=%s",
                        message_id, code, elapsed_ms, msg,
                    )
                else:
                    logger.warning(
                        "forward.result message_id=%s code=%s elapsed_ms=%s msg=%s",
                        message_id, code, elapsed_ms, msg,
                    )
        except Exception as exc:  # broad on purpose: fire-and-forget
            elapsed_ms = int((time.monotonic() - started) * 1000)
            logger.warning(
                "forward.result message_id=%s code=exception elapsed_ms=%s msg=%s",
                message_id, elapsed_ms, exc, exc_info=True,
            )
```

> Test impact: the existing tests in this task pass `touser` + `textcard` only. Update them to also pass `message_id=<int>` and `action_code=<str>` kwargs (they're now required). Add one new assertion: `caplog.text` contains `"forward.attempt"` and `"forward.result"` on the success path.

- [ ] **Step 4: Run tests to verify pass**

```bash
cd src/backend && uv run pytest tests/notification/test_cofco_eplus_client.py -v
```
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/backend/bisheng/notification/external/cofco_eplus_client.py src/backend/tests/notification/test_cofco_eplus_client.py
git commit -m "feat(notification): add CofcoEPlusClient.send_textcard"
```

---

## Task 4: Implement `forwarder` (recipient resolution + hook entry)

**Files:**
- Create: `src/backend/bisheng/notification/forwarder.py`
- Test: `src/backend/tests/notification/test_forwarder.py`

> **Background for the implementer**: `InboxMessage` model has fields `id` (int), `action_code` (str), `target_user_id` (int / receiver), `create_time` (datetime), and content metadata holding `applicant_user_id` + resource info. Look at `src/backend/bisheng/message/domain/models/inbox_message.py` for the exact schema; the `_extract_payload_fields` helper below adapts that into the four fields textcard needs.

- [ ] **Step 1: Write the failing tests**

```python
# src/backend/tests/notification/test_forwarder.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bisheng.notification.forwarder import (
    resolve_eplus_recipient, maybe_forward_external,
)


# ---- resolve_eplus_recipient ----

@patch("bisheng.notification.forwarder.UserDao")
def test_resolve_returns_none_when_user_missing(UserDao):
    UserDao.get_user.return_value = None
    rid, reason = resolve_eplus_recipient(123)
    assert rid is None
    assert reason == "user_not_found"


@patch("bisheng.notification.forwarder.UserDao")
def test_resolve_returns_none_when_source_not_eplus(UserDao):
    user = MagicMock(source="local", external_id="X1")
    UserDao.get_user.return_value = user
    rid, reason = resolve_eplus_recipient(123)
    assert rid is None
    assert "not_eplus" in reason


@patch("bisheng.notification.forwarder.UserDao")
def test_resolve_returns_none_when_external_id_empty(UserDao):
    user = MagicMock(source="cofco_eplus", external_id="")
    UserDao.get_user.return_value = user
    rid, reason = resolve_eplus_recipient(123)
    assert rid is None
    assert reason == "external_id_empty"


@patch("bisheng.notification.forwarder.UserDao")
def test_resolve_returns_external_id(UserDao):
    user = MagicMock(source="cofco_eplus", external_id="EMP001")
    UserDao.get_user.return_value = user
    rid, reason = resolve_eplus_recipient(123)
    assert rid == "EMP001"
    assert reason == ""


# ---- maybe_forward_external ----

@pytest.fixture
def fake_msg():
    m = MagicMock()
    m.id = 100
    m.action_code = "request_channel"
    m.target_user_id = 5
    m.create_time = MagicMock()
    m.create_time.strftime.return_value = "2026-05-13 10:00"
    return m


@pytest.fixture
def bg_tasks():
    bg = MagicMock()
    bg.add_task = MagicMock()
    return bg


@patch("bisheng.notification.forwarder.settings")
def test_forward_skipped_when_disabled(mock_settings, fake_msg, bg_tasks):
    mock_settings.in_app_message_forwarding.cofco.enabled = False
    maybe_forward_external(fake_msg, bg_tasks)
    bg_tasks.add_task.assert_not_called()


@patch("bisheng.notification.forwarder.settings")
def test_forward_skipped_when_action_code_not_forwardable(mock_settings, fake_msg, bg_tasks):
    mock_settings.in_app_message_forwarding.cofco.enabled = True
    fake_msg.action_code = "some_other_code"
    maybe_forward_external(fake_msg, bg_tasks)
    bg_tasks.add_task.assert_not_called()


@patch("bisheng.notification.forwarder.resolve_eplus_recipient")
@patch("bisheng.notification.forwarder.settings")
def test_forward_skipped_when_recipient_unresolved(mock_settings, mock_resolve, fake_msg, bg_tasks):
    mock_settings.in_app_message_forwarding.cofco.enabled = True
    mock_resolve.return_value = (None, "external_id_empty")
    maybe_forward_external(fake_msg, bg_tasks)
    bg_tasks.add_task.assert_not_called()


@patch("bisheng.notification.forwarder._extract_payload_fields")
@patch("bisheng.notification.forwarder.resolve_eplus_recipient")
@patch("bisheng.notification.forwarder.settings")
def test_forward_schedules_background_task(
    mock_settings, mock_resolve, mock_extract, fake_msg, bg_tasks
):
    mock_settings.in_app_message_forwarding.cofco.enabled = True
    mock_resolve.return_value = ("EMP001", "")
    mock_extract.return_value = ("张三", "技术频道")

    maybe_forward_external(fake_msg, bg_tasks)

    bg_tasks.add_task.assert_called_once()
    args, kwargs = bg_tasks.add_task.call_args
    # First positional is the coroutine function; remaining is kwargs to it
    assert kwargs["message_id"] == 100
    assert kwargs["action_code"] == "request_channel"
    assert kwargs["touser"] == ["EMP001"]
    assert kwargs["textcard"]["title"] == "[知源] 新的频道订阅申请"


@patch("bisheng.notification.forwarder.resolve_eplus_recipient")
@patch("bisheng.notification.forwarder.settings")
def test_skipped_logs_include_message_id_and_reason(
    mock_settings, mock_resolve, fake_msg, bg_tasks, caplog
):
    """跳过路径的日志必须含 forward.skipped + 关键字段，用于客户环境排障。"""
    import logging
    caplog.set_level(logging.INFO)
    mock_settings.in_app_message_forwarding.cofco.enabled = True
    mock_resolve.return_value = (None, "external_id_empty")

    maybe_forward_external(fake_msg, bg_tasks)

    assert "forward.skipped" in caplog.text
    assert "message_id=100" in caplog.text
    assert "reason=external_id_empty" in caplog.text
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd src/backend && uv run pytest tests/notification/test_forwarder.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'bisheng.notification.forwarder'`

- [ ] **Step 3: Implement `forwarder.py`**

```python
# src/backend/bisheng/notification/forwarder.py
"""Hook entry: decide / resolve / schedule. Synchronous, never blocks."""
import logging
from typing import Optional, Tuple

from bisheng.core.config import settings
from bisheng.user.domain.daos.user_dao import UserDao
from bisheng.notification.external._payload import (
    FORWARDABLE_ACTION_CODES, build_textcard,
)
from bisheng.notification.external.cofco_eplus_client import CofcoEPlusClient

logger = logging.getLogger(__name__)


def resolve_eplus_recipient(target_user_id: int) -> Tuple[Optional[str], str]:
    """Return (e_plus_userid, skip_reason). Reason is empty when resolved."""
    user = UserDao.get_user(target_user_id)
    if not user:
        return None, "user_not_found"
    if user.source != "cofco_eplus":
        return None, f"source={user.source}_not_eplus"
    if not user.external_id:
        return None, "external_id_empty"
    return user.external_id, ""


def _extract_payload_fields(message) -> Tuple[str, str]:
    """Extract (applicant_name, resource_name) from InboxMessage content.

    InboxMessage stores rich content blocks. We dig the user-id type block for
    applicant and business_url type block for resource. If something is missing,
    return ('', '') — the textcard will render blanks but still send.
    """
    applicant_name = ""
    resource_name = ""
    try:
        for block in (message.content or []):
            btype = block.get("type")
            if btype == "user":
                # Resolve user id -> display name
                applicant_id = (block.get("metadata") or {}).get("user_id")
                if applicant_id:
                    user = UserDao.get_user(int(applicant_id))
                    if user:
                        applicant_name = user.user_name or user.email or str(applicant_id)
            elif btype == "business_url":
                meta = block.get("metadata") or {}
                btype_inner = meta.get("business_type") or ""
                data = (meta.get("data") or {}).get(btype_inner) or {}
                resource_name = data.get("resource_name") or data.get("name") or ""
    except Exception as exc:
        logger.debug("_extract_payload_fields parse error: %s", exc, exc_info=True)
    return applicant_name, resource_name


def maybe_forward_external(message, background_tasks) -> None:
    """Synchronous hook called from MessageService.send_message().

    Logging contract:
      - INFO `forward.skipped` for every short-circuit path (with reason)
      - delegates `forward.attempt` / `forward.result` to CofcoEPlusClient
    """
    conf = settings.in_app_message_forwarding.cofco
    if not conf.enabled:
        # 高频路径，不打 INFO 防止刷屏；只在 DEBUG 留痕
        logger.debug(
            "forward.skipped message_id=%s reason=feature_disabled",
            getattr(message, "id", "?"),
        )
        return
    if message.action_code not in FORWARDABLE_ACTION_CODES:
        logger.info(
            "forward.skipped message_id=%s action_code=%s reason=not_in_whitelist",
            message.id, message.action_code,
        )
        return

    recipient_id, skip_reason = resolve_eplus_recipient(message.target_user_id)
    if recipient_id is None:
        logger.info(
            "forward.skipped message_id=%s action_code=%s reason=%s target_user_id=%s",
            message.id, message.action_code, skip_reason, message.target_user_id,
        )
        return

    applicant_name, resource_name = _extract_payload_fields(message)
    triggered_at = message.create_time.strftime("%Y-%m-%d %H:%M")

    textcard = build_textcard(
        message_id=message.id,
        action_code=message.action_code,
        applicant_name=applicant_name,
        resource_name=resource_name,
        triggered_at=triggered_at,
    )

    client = CofcoEPlusClient()
    background_tasks.add_task(
        client.send_textcard,
        message_id=message.id,
        action_code=message.action_code,
        touser=[recipient_id],
        textcard=textcard,
    )
```

> Implementer note: the `UserDao.get_user` import path above (`bisheng.user.domain.daos.user_dao`) follows the codebase convention—verify by `grep -r "from bisheng.user.domain.daos" src/backend/bisheng/message/`. If it differs, align both imports here and in tests.

- [ ] **Step 4: Run tests to verify pass**

```bash
cd src/backend && uv run pytest tests/notification/test_forwarder.py -v
```
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add src/backend/bisheng/notification/forwarder.py src/backend/tests/notification/test_forwarder.py
git commit -m "feat(notification): add forwarder hook + recipient resolution"
```

---

## Task 5: Hook `maybe_forward_external` into `MessageService.send_message()`

**Files:**
- Modify: `src/backend/bisheng/message/domain/services/message_service.py`（around lines 47-70）
- Test: `src/backend/tests/notification/test_send_message_integration.py`

- [ ] **Step 1: Write the failing test**

```python
# src/backend/tests/notification/test_send_message_integration.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
@patch("bisheng.message.domain.services.message_service.maybe_forward_external")
async def test_send_message_calls_forwarder_at_the_end(mock_forward):
    """send_message() 末尾必须调 maybe_forward_external，传入 message + bg_tasks."""
    from bisheng.message.domain.services.message_service import MessageService

    # Build a service with mocked deps (only what we need)
    svc = MessageService.__new__(MessageService)  # bypass __init__
    svc._dao = MagicMock()
    saved = MagicMock(id=42, action_code="request_channel", target_user_id=7)
    svc._dao.insert = MagicMock(return_value=saved)

    bg = MagicMock()
    await svc.send_message(message_input=MagicMock(), background_tasks=bg)

    mock_forward.assert_called_once()
    args, kwargs = mock_forward.call_args
    # forwarder called with (saved_message, bg_tasks)
    assert args[0] is saved
    assert args[1] is bg
```

> Implementer note: depending on how `send_message` is structured, the test setup above may need to be adapted (the real `send_message` validates `message_input`, builds content blocks, etc.). The intent is: prove the **last** statement in the happy path is the forwarder call.

- [ ] **Step 2: Run test to verify failure**

```bash
cd src/backend && uv run pytest tests/notification/test_send_message_integration.py -v
```
Expected: FAIL — forwarder not yet hooked.

- [ ] **Step 3: Modify `message_service.py`**

Open `src/backend/bisheng/message/domain/services/message_service.py`. At the top imports, add:

```python
from bisheng.notification.forwarder import maybe_forward_external
```

Locate `send_message` (around lines 47-70). At the **end** of the happy path (after the message has been persisted, before returning), add:

```python
        # E+ 站内信转发钩子（同步、轻量；HTTP 在 BackgroundTasks 中执行）
        if background_tasks is not None:
            try:
                maybe_forward_external(saved_message, background_tasks)
            except Exception as exc:
                # Defensive: never let forwarder bug break the main flow.
                logger.warning("maybe_forward_external raised: %s", exc, exc_info=True)
```

> **Implementer note**: this assumes `send_message` already receives a `background_tasks: BackgroundTasks | None` parameter from its FastAPI caller. If the current signature doesn't have it, **add it** (default `None`) and propagate from the calling endpoint(s) in `bisheng/message/api/endpoints/*.py`. This is part of this task.

If the variable holding the persisted message is named differently (e.g. `msg`, `created`, `record`), adjust accordingly.

- [ ] **Step 4: Run test to verify pass**

```bash
cd src/backend && uv run pytest tests/notification/test_send_message_integration.py -v
```
Expected: PASS

- [ ] **Step 5: Run all backend notification tests as smoke**

```bash
cd src/backend && uv run pytest tests/notification/ -v
```
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/backend/bisheng/message/domain/services/message_service.py src/backend/tests/notification/test_send_message_integration.py
git commit -m "feat(message): wire maybe_forward_external hook into send_message"
```

---

## Task 6: Create `useNotificationsFromUrl` hook (client)

**Files:**
- Create: `src/frontend/client/src/hooks/useNotificationsFromUrl.ts`
- Test: `src/frontend/client/src/hooks/useNotificationsFromUrl.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// src/frontend/client/src/hooks/useNotificationsFromUrl.test.ts
import { renderHook, act } from "@testing-library/react";
import { MemoryRouter, useSearchParams } from "react-router-dom";
import { describe, it, expect } from "vitest";
import { useNotificationsFromUrl } from "./useNotificationsFromUrl";

const wrap = (initialEntries: string[]) => ({ children }: { children: React.ReactNode }) =>
  <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>;

describe("useNotificationsFromUrl", () => {
  it("returns closed state when no query param", () => {
    const { result } = renderHook(() => useNotificationsFromUrl(), {
      wrapper: wrap(["/"]),
    });
    expect(result.current.open).toBe(false);
    expect(result.current.focusedMessageId).toBeNull();
  });

  it("opens dialog and parses message-id from query", () => {
    const { result } = renderHook(() => useNotificationsFromUrl(), {
      wrapper: wrap(["/?open-notifications=1&message-id=42"]),
    });
    expect(result.current.open).toBe(true);
    expect(result.current.focusedMessageId).toBe(42);
  });

  it("setOpen(false) closes the dialog", () => {
    const { result } = renderHook(() => useNotificationsFromUrl(), {
      wrapper: wrap(["/?open-notifications=1"]),
    });
    expect(result.current.open).toBe(true);
    act(() => result.current.setOpen(false));
    expect(result.current.open).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd src/frontend/client && pnpm vitest run src/hooks/useNotificationsFromUrl.test.ts
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the hook**

```ts
// src/frontend/client/src/hooks/useNotificationsFromUrl.ts
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

export interface UseNotificationsFromUrlResult {
  open: boolean;
  setOpen: (open: boolean) => void;
  focusedMessageId: number | null;
}

export function useNotificationsFromUrl(): UseNotificationsFromUrlResult {
  const [searchParams, setSearchParams] = useSearchParams();
  const [open, setOpen] = useState<boolean>(
    () => searchParams.get("open-notifications") === "1"
  );

  const midRaw = searchParams.get("message-id");
  const focusedMessageId = midRaw && /^\d+$/.test(midRaw) ? Number(midRaw) : null;

  useEffect(() => {
    if (searchParams.get("open-notifications") === "1") {
      // 留痕：客户那边远程发 console 时能看到 dialog 是否被 URL 触发开过
      // eslint-disable-next-line no-console
      console.info("[notifications] auto-open", { messageId: focusedMessageId });
      const next = new URLSearchParams(searchParams);
      next.delete("open-notifications");
      next.delete("message-id");
      setSearchParams(next, { replace: true });
    }
    // run once per searchParams change
  }, [searchParams, setSearchParams, focusedMessageId]);

  return { open, setOpen, focusedMessageId };
}
```

- [ ] **Step 4: Run test to verify pass**

```bash
cd src/frontend/client && pnpm vitest run src/hooks/useNotificationsFromUrl.test.ts
```
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/frontend/client/src/hooks/useNotificationsFromUrl.ts src/frontend/client/src/hooks/useNotificationsFromUrl.test.ts
git commit -m "feat(client): add useNotificationsFromUrl hook"
```

---

## Task 7: Wire hook into `UserPopMenu` (both Drawer + Rail variants)

**Files:**
- Modify: `src/frontend/client/src/layouts/UserPopMenu.tsx`

- [ ] **Step 1: Add a manual smoke test plan first (no automated test for this layout file)**

Document in a comment at the top of UserPopMenu.tsx the manual verification:

```
// Manual smoke (run after change):
// 1. cd src/frontend/client && pnpm dev
// 2. open http://localhost:5173/?open-notifications=1&tab=request&message-id=99
// 3. NotificationsDialog must open on "request" tab; URL is rewritten to "/"
// 4. open http://localhost:5173/  → dialog stays closed; bell icon click still works
```

- [ ] **Step 2: Modify both variants**

Locate `UserPopMenuDrawer()` (currently around lines 29-241) and `UserPopMenuRail()` (around lines 243-451). In each, replace the `useState` declaration of `notificationsDialogOpen` and the `setNotificationsDialogOpen` callsite with the hook:

```tsx
import { useNotificationsFromUrl } from "@/hooks/useNotificationsFromUrl";

// Inside each variant, at the top of the component body:
const {
  open: notificationsDialogOpen,
  setOpen: setNotificationsDialogOpen,
  focusedMessageId,
} = useNotificationsFromUrl();
```

At the JSX rendering `<NotificationsDialog>` (currently around lines 235-237 in Drawer, 449-451 in Rail), pass new props:

```tsx
<NotificationsDialog
  open={notificationsDialogOpen}
  onOpenChange={setNotificationsDialogOpen}
  focusedMessageId={focusedMessageId}
/>
```

- [ ] **Step 3: Type-check**

```bash
cd src/frontend/client && pnpm tsc --noEmit
```
Expected: 0 errors. If `NotificationsDialog` props don't yet accept `initialTab` / `focusedMessageId`, this is OK to fail temporarily — Task 8 will add them.

If you want to keep tsc clean intra-task, run Task 8 first then return to Step 3.

- [ ] **Step 4: Commit (after Task 8 also done)**

> Hold the commit until Task 8 lands. They're a coupled change.

---

## Task 8: Extend `NotificationsDialog` with `focusedMessageId` prop

**Files:**
- Modify: `src/frontend/client/src/components/NotificationsDialog.tsx`

> Scope reminder: tab switching / scrollIntoView / highlight is **out of scope for v1**. We accept `focusedMessageId` as a prop for forward-compatibility but do not enforce any visual behavior; the dialog opens to its existing default tab.

- [ ] **Step 1: Extend props**

In `NotificationsDialog.tsx`, extend the props interface:

```tsx
export interface NotificationsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  focusedMessageId?: number | null;
}
```

Accept the new prop and stash it in a ref for v2 hookup:

```tsx
const focusedMessageIdRef = useRef<number | null>(focusedMessageId ?? null);
useEffect(() => {
  focusedMessageIdRef.current = focusedMessageId ?? null;
}, [focusedMessageId]);
// v2: wire scroll-into-view + highlight against this ref
```

- [ ] **Step 2: Type-check + lint**

```bash
cd src/frontend/client && pnpm tsc --noEmit && pnpm lint
```
Expected: clean.

- [ ] **Step 3: Commit (combined with Task 7)**

```bash
git add src/frontend/client/src/layouts/UserPopMenu.tsx \
        src/frontend/client/src/components/NotificationsDialog.tsx
git commit -m "feat(client): open NotificationsDialog from textcard URL"
```

---

## Task 9: End-to-end manual verification

**Files:** none (manual)

- [ ] **Step 1: Start backend with cofco_eplus stub**

In a scratch terminal, run a tiny Python HTTP echo to capture E+ requests:

```bash
python3 -c "
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(n).decode()
        print('--- E+ stub got ---')
        print('Headers:', dict(self.headers))
        print('Body:', body)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{\"code\":\"0\",\"msg\":\"ok\"}')
HTTPServer(('127.0.0.1', 8765), H).serve_forever()
"
```

Configure `config.yaml` (dev env):

```yaml
in_app_message_forwarding:
  cofco:
    enabled: true
    api_base: "http://127.0.0.1:8765/qwmsg-ui"
    app_id: "test"
    secret: "test"
    bisheng_inbox_url: "http://localhost:5173"
```

Start backend.

- [ ] **Step 2: Trigger a request_channel via real flow**

1. As user A, request to subscribe to a channel that requires approval.
2. Observe E+ stub stdout: should print `Headers` containing `appId: test` and `Body` containing `msgtype: textcard`.
3. The body's `textcard.url` should be `http://localhost:5173/?open-notifications=1&tab=request&message-id=<N>`.

- [ ] **Step 3: Trigger the URL → dialog flow**

1. Copy the URL from the E+ stub log, open in a browser with client running.
2. Dialog auto-opens on the "request" tab.
3. URL in browser becomes `http://localhost:5173/` (cleaned).
4. Manually close dialog → reopen with bell icon → still works.

- [ ] **Step 4: Negative tests**

- Set `enabled: false` → trigger same flow → E+ stub receives **nothing**.
- Set wrong `app_id` → stub still receives request (we don't verify); check backend log shows nothing.
- Stop E+ stub mid-flow → trigger again → backend log shows WARN `cofco_eplus send_textcard exception: ConnectionRefused` (no exception bubbles up).

- [ ] **Step 5: Document outcome**

In the PR description, paste the captured E+ stub log + screenshot of dialog auto-opening.

---

## Self-review

- [ ] **Spec coverage**: §1.2（开关）→ Task 1；§1.6（接口契约）→ Task 3；§1.7（回调 URL）→ Tasks 6-8；§1.8（代码组织）→ Tasks 2-5；§1.9（接收人解析）→ Task 4；§1.10（失败语义）→ Tasks 3-4 测试；§1.11（测试策略）→ each task；§1.12（部署清单）→ Task 9。
- [ ] No "TBD" / "fill in later" markers.
- [ ] Type names consistent: `CofcoEPlusClient`, `InAppMessageForwardingConf`, `FORWARDABLE_ACTION_CODES` referenced the same across tasks.
- [ ] Imports unambiguous: `from bisheng.notification.external._payload import ...` everywhere.

---

## Execution handoff

Plan complete and saved. Recommended execution: **subagent-driven** — each backend task is independent enough to dispatch a fresh subagent, with the writer reviewing diffs between tasks. Front-end Tasks 7-8 are coupled and should land in one subagent.

If you prefer batch inline execution, use `superpowers:executing-plans`.
