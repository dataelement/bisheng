# E2E 测试文件骨架模板

## 完整 pytest 模板

```python
"""
E2E tests for <FEATURE_NAME>

Prerequisites:
- Backend running on localhost:7860
- MySQL/Redis/Milvus/ES/OpenFGA services running

Covers:
- AC-01: <description>
- AC-02: <description>
"""

import pytest
import httpx

from test.e2e.helpers.auth import get_admin_token, get_user_token, auth_headers, create_test_user
from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.cleanup import cleanup_by_prefix, ensure_test_tenant

# Data prefix for test isolation (must be >= 5 chars)
PREFIX = "e2e-<feature>-"

# Test tenant for multi-tenant isolation
TEST_TENANT = "e2e-<feature>-tenant"


class TestE2E<FeatureName>:
    """E2E: <feature_name>"""

    # ──────── Fixtures ────────

    @pytest.fixture(autouse=True, scope="class")
    async def setup_and_teardown(self):
        """双重 cleanup: setup 清理上次残留 + teardown 清理本次"""
        async with httpx.AsyncClient(base_url=API_BASE, timeout=30.0) as client:
            # Setup: 获取 admin token
            admin_token = await get_admin_token(client)
            headers = auth_headers(admin_token)

            # Setup: 确保测试租户存在
            await ensure_test_tenant(client, admin_token, TEST_TENANT)

            # Setup: 清理上次残留的测试数据
            await cleanup_by_prefix(client, "/resource", PREFIX, admin_token)

            yield  # 运行测试

            # Teardown: 清理本次创建的测试数据
            await cleanup_by_prefix(client, "/resource", PREFIX, admin_token)

    @pytest.fixture
    async def client(self):
        """提供 httpx AsyncClient"""
        async with httpx.AsyncClient(base_url=API_BASE, timeout=30.0) as client:
            yield client

    @pytest.fixture
    async def admin_token(self, client):
        """获取管理员 token"""
        return await get_admin_token(client)

    @pytest.fixture
    async def user_token(self, client, admin_token):
        """创建并返回普通用户 token"""
        user = await create_test_user(
            client, admin_token,
            username=f"{PREFIX}user",
            role_id=2  # DefaultRole
        )
        return await get_user_token(client, user["user_name"], "test_password")

    # ──────── Happy Path Tests ────────

    async def test_ac01_create_success(self, client, admin_token):
        """AC-01: <操作描述> → <预期结果>"""
        headers = auth_headers(admin_token)

        # 创建资源
        resp = await client.post(
            "/resource",
            json={"name": f"{PREFIX}test-entity"},
            headers=headers,
        )

        # 断言 UnifiedResponseModel 成功格式
        data = assert_resp_200(resp)
        assert data["name"] == f"{PREFIX}test-entity"
        assert "id" in data

        # 通过 GET 验证最终状态（不仅依赖创建响应）
        get_resp = await client.get(f"/resource/{data['id']}", headers=headers)
        get_data = assert_resp_200(get_resp)
        assert get_data["name"] == f"{PREFIX}test-entity"

    async def test_ac02_list_with_pagination(self, client, admin_token):
        """AC-02: 分页查询资源列表"""
        headers = auth_headers(admin_token)

        resp = await client.get(
            "/resource",
            params={"page": 1, "limit": 10},
            headers=headers,
        )

        data = assert_resp_200(resp)
        assert "data" in data  # PageData format
        assert "total" in data

    # ──────── Error Path Tests ────────

    async def test_ac03_duplicate_name_rejected(self, client, admin_token):
        """AC-03: 重复名称 → 返回 MMMEE 错误码"""
        headers = auth_headers(admin_token)

        # 创建第一个
        await client.post(
            "/resource",
            json={"name": f"{PREFIX}duplicate"},
            headers=headers,
        )

        # 创建同名第二个
        resp = await client.post(
            "/resource",
            json={"name": f"{PREFIX}duplicate"},
            headers=headers,
        )

        # 断言具体错误码（不仅检查非 200）
        assert_resp_error(resp, expected_code=10901)  # MMMEE

    # ──────── Permission Tests ────────

    async def test_ac04_unauthorized_access_denied(self, client, user_token, admin_token):
        """AC-04: 普通用户无权访问管理接口 → 权限拒绝"""
        headers = auth_headers(user_token)

        resp = await client.get("/admin-only-resource", headers=headers)
        assert_resp_error(resp, expected_code=10601)  # user permission denied

    async def test_ac05_cross_tenant_blocked(self, client, admin_token):
        """AC-05: 跨租户访问 → tenant_id 不匹配拒绝"""
        # 创建资源属于 tenant A
        headers_a = auth_headers(admin_token)  # tenant A
        resp = await client.post(
            "/resource",
            json={"name": f"{PREFIX}tenant-a-only"},
            headers=headers_a,
        )
        resource_id = assert_resp_200(resp)["id"]

        # 用 tenant B 的 token 尝试访问
        # （需要创建 tenant B 的用户和 token）
        # headers_b = auth_headers(tenant_b_token)
        # resp = await client.get(f"/resource/{resource_id}", headers=headers_b)
        # assert resp.status_code == 200
        # body = resp.json()
        # assert body["status_code"] != 200  # 应该被拒绝
```

## 关键结构规则

1. **class-based 组织** — 每个 Feature 一个 TestClass，fixture 管理生命周期
2. **setup_and_teardown 是 class-scoped** — 确保整个类运行前清理 + 运行后清理
3. **每个测试方法 docstring 标注 AC-NN** — 追溯到 spec.md 的 AC 表格
4. **PREFIX 常量** — 所有测试数据以 `e2e-{feature}-` 开头
5. **API 验证** — 数据变更后，通过 GET 断言最终状态
6. **共享 helpers** — 认证/断言/清理使用 `test/e2e/helpers/`，不在文件内重定义
7. **权限配对** — 每个 "允许" 操作配对一个 "拒绝" 测试

## 响应断言模式

```python
# ✅ 正确：断言 UnifiedResponseModel 完整格式
def assert_resp_200(resp):
    assert resp.status_code == 200
    body = resp.json()
    assert body["status_code"] == 200
    assert body["status_message"] == "SUCCESS"
    return body["data"]

# ✅ 正确：断言具体 MMMEE 错误码
def assert_resp_error(resp, expected_code):
    body = resp.json()
    assert body["status_code"] == expected_code

# ❌ 错误：只检查 HTTP 状态码
assert resp.status_code == 400  # BiSheng 业务错误也返回 HTTP 200
```

## 认证模式

```python
# ✅ JWT Cookie 认证（BiSheng 主要认证方式）
headers = {"Cookie": f"access_token_cookie={token}"}

# ✅ 或 Header 认证
headers = {"Authorization": f"Bearer {token}"}

# 获取 token
resp = await client.post("/user/login", json={
    "user_name": "admin",
    "password": "<rsa_encrypted_password>"
})
token = resp.json()["data"]["access_token"]
```

## 多租户测试模式

```python
# ✅ 测试租户隔离
TEST_TENANT_CODE = "e2e-feature-tenant"

# setup: 确保测试租户存在
await ensure_test_tenant(client, admin_token, TEST_TENANT_CODE)

# 创建属于测试租户的数据
# （tenant_id 由 SQLAlchemy event 自动注入，不需手动设置）

# 验证：不同租户的用户看不到此数据
```
