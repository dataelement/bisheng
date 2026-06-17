# BiSheng E2E 测试常见陷阱与诊断修复

## 陷阱 1：业务错误 HTTP 200

**症状**：`assert resp.status_code == 400` 失败，实际收到 200。

**原因**：BiSheng 的 `UnifiedResponseModel` 将业务错误包装在 HTTP 200 响应体中，通过 `status_code` 字段区分。

**修复**：
```python
# ❌ BiSheng 业务错误也返回 HTTP 200
assert resp.status_code == 400

# ✅ 检查响应体中的 status_code
body = resp.json()
assert body["status_code"] == 10901  # 具体 MMMEE 错误码
assert body["status_message"] != "SUCCESS"
```

---

## 陷阱 2：认证 Token 获取失败

**症状**：登录 API 返回错误，或后续请求 401。

**原因**：BiSheng 登录密码需要 RSA 加密。前端从 `/api/v1/user/public_key` 获取公钥后加密。

**修复**：
```python
# ✅ 先获取公钥，再加密密码
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

resp = await client.get("/user/public_key")
public_key_pem = resp.json()["data"]["public_key"]

# 加密密码
public_key = serialization.load_pem_public_key(public_key_pem.encode())
encrypted = public_key.encrypt(password.encode(), padding.PKCS1v15())
encrypted_password = base64.b64encode(encrypted).decode()

# 登录
resp = await client.post("/user/login", json={
    "user_name": username,
    "password": encrypted_password,
})
```

**建议**：将此逻辑封装在 `helpers/auth.py` 中，测试文件直接调用 `get_admin_token()`。

---

## 陷阱 3：tenant_id 自动注入导致测试数据不可见

**症状**：创建了数据但 GET 列表查不到。

**原因**：SQLAlchemy event 自动注入 `tenant_id` 过滤，测试用户的 tenant_id 与数据不匹配。

**修复**：
```python
# ✅ 确保测试用户属于正确的租户
# 1. 创建测试租户
# 2. 将测试用户加入该租户
# 3. 用该用户的 token 创建和查询数据

# ❌ 不要试图绕过 tenant_id（那是安全底线）
```

---

## 陷阱 4：OpenFGA 权限未同步

**症状**：创建资源后，同一用户立即查询却被权限拒绝。

**原因**：资源创建时应同步写入 OpenFGA owner 元组，如果 `PermissionService.authorize()` 调用失败或遗漏，用户虽然创建了资源但没有 owner 权限。

**修复**：
```python
# ✅ 创建后验证权限元组已写入
resp = await client.post("/resource", json={...}, headers=admin_headers)
data = assert_resp_200(resp)

# 紧接着用同一用户查询，应该能看到
get_resp = await client.get(f"/resource/{data['id']}", headers=admin_headers)
assert_resp_200(get_resp)  # 如果失败，说明 OpenFGA 元组没写入
```

---

## 陷阱 5：cleanup 顺序错误

**症状**：`DELETE /resource/{id}` 返回错误，因为有关联数据未先删除。

**原因**：BiSheng 资源间有关联关系（如知识库→文件、助手→工具/技能/知识库），删除有顺序要求。

**修复**：
```python
# ✅ 正确的 cleanup 顺序（依赖关系逆序）
async def cleanup_feature_data(client, token, prefix):
    headers = auth_headers(token)

    # 1. 先删除依赖方（如关联表、子资源）
    # 2. 再删除主资源
    # 3. 最后清理 OpenFGA 元组（如有直接操作的话）

    # 示例：删除知识库
    # 先删知识库文件 → 再删知识库空间

# ❌ 不要假设可以直接删除主资源
```

---

## 陷阱 6：Celery 异步任务未完成就断言

**症状**：创建知识库文件后立即查询，状态还是 `WAITING` 而非 `SUCCESS`。

**原因**：文件处理通过 Celery `knowledge_celery` 队列异步执行，创建 API 返回后任务可能还在处理。

**修复**：
```python
# ✅ 轮询等待异步任务完成
import asyncio

async def wait_for_status(client, path, token, expected_status, timeout=30):
    headers = auth_headers(token)
    for _ in range(timeout):
        resp = await client.get(path, headers=headers)
        data = resp.json()["data"]
        if data["status"] == expected_status:
            return data
        await asyncio.sleep(1)
    raise TimeoutError(f"Status not reached: {expected_status}")

# 使用
data = await wait_for_status(
    client, f"/knowledge_file/{file_id}",
    admin_token, expected_status=2  # SUCCESS
)
```

---

## 陷阱 7：分页参数不一致

**症状**：列表查询返回的数据数量不对。

**原因**：BiSheng 不同 API 的分页参数名称可能不同（`page`/`page_num`、`limit`/`page_size`/`size`）。

**修复**：
```python
# ✅ 先查看 API 文档确认参数名
# 常见模式：
resp = await client.get("/resource", params={
    "page": 1,       # 或 page_num
    "limit": 10,     # 或 page_size 或 size
}, headers=headers)

# ✅ 响应分页格式（PageData）
data = resp.json()["data"]
items = data["data"]   # 列表数据
total = data["total"]  # 总数
```

---

## 陷阱 8：WebSocket 测试

**症状**：WebSocket 连接失败或消息收不到。

**原因**：BiSheng 的 WebSocket 使用特殊的认证方式（`UserPayload.get_login_user_from_ws`），token 通过 query 参数传递。

**修复**：
```python
# ✅ WebSocket 认证
import websockets

async with websockets.connect(
    f"ws://localhost:7860/api/v1/chat/{flow_id}?t={token}"
) as ws:
    # 发送消息
    await ws.send(json.dumps({"message": "hello"}))
    # 接收响应
    response = await ws.recv()
```

---

## 陷阱 9：RSA 公钥缓存

**症状**：多个测试用不同用户登录，部分登录失败。

**原因**：公钥可能在短时间内变化，或 RSA 加密使用了错误的 padding。

**修复**：
```python
# ✅ 每次登录前重新获取公钥（不缓存）
# helpers/auth.py 中的 get_token() 函数应每次都获取新公钥
```

---

## 快速诊断表

| 错误关键词 | 可能原因 | 首先检查 |
|-----------|---------|---------|
| HTTP 200 但 status_code 非 200 | 业务错误 | 检查 MMMEE 错误码含义 |
| 401 Unauthorized | Token 过期或格式错误 | 重新获取 token，检查 Cookie/Header |
| 查不到刚创建的数据 | tenant_id 不匹配 | 确认用户与资源同租户 |
| 权限拒绝（刚创建的资源） | OpenFGA 元组未写入 | 检查 PermissionService.authorize() |
| DELETE 失败 400/409 | 有关联数据 | 按依赖逆序删除 |
| 异步操作状态不对 | Celery 任务未完成 | 轮询等待 + 增加 timeout |
| 分页数据数量不对 | 参数名不一致 | 查 API 文档确认 page/limit 参数名 |
| 登录失败 | RSA 加密问题 | 检查公钥获取和加密 padding |
| `Connection refused` | 后端未启动 | 确认 localhost:7860 可访问 |
| `Redis connection error` | Redis 未启动 | 确认 Redis 服务运行中 |
