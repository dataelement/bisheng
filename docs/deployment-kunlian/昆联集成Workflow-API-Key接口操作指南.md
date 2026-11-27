# 昆联集成 Workflow API Key 接口操作指南

> 适用分支：`feat/v3.0.0/118-kunlian-integration`（F133 昆联集成开放接口凭证管理）。

## 1. 适用范围与前置条件

- **用途**：签发并管理 `bs-kl-` 前缀的昆联集成 API Key，供昆联服务端携带 `Authorization: Bearer bs-kl-...` 调用毕昇正式昆联 Workflow 开放接口（`/api/v2/kunlian/*`）。
- **无前端 UI**：该密钥**没有前端管理页面**，所有签发、查询、更新、轮换和吊销均通过后端控制面 HTTP API 完成。
- **调用方权限要求**：
  - 所有管理接口均要求调用方为**毕昇本地全局超级管理员**（通过 `UserPayload.get_login_user` 解析用户，并在租户 `1` 下实时校验当前 `is_global_super` 资格）。
  - 账号来源必须为**本地账号**（`/api/v1/user/login` 会直接拒绝 `source="kunlian"` 的昆联同步账号）。
  - 业务侧 `bs-kl-...` API Key **不能**用于调用本控制面接口。
- **安全与审计约束**：
  - 所有响应均自动携带 `Cache-Control: no-store`。
  - 每次控制面请求均会通过 `KunlianAuditService` 记录审计日志。

---

## 2. 获取本地超管登录 Cookie

控制面接口路径为 `/api/v1/identity-integrations/kunlian/api-keys*`，支持以下任意一种登录态凭证：
- **Cookie 鉴权**：`Cookie: access_token_cookie=<JWT>`（推荐运维脚本用 `--cookie "$COOKIE_JAR"` 传递）；
- **Bearer 鉴权**：`Authorization: Bearer <登录响应 data.access_token>`。

### 方式一：浏览器通过 `/admin-login` 登录后提取（最简便）

1. 在浏览器访问本地超管专属登录入口：
   `https://<PUBLIC_ORIGIN>/admin-login`（例如 `http://110.16.193.170:50055/admin-login`）。
   > 使用 `/admin-login` 可绕开昆联统一登录自动跳转，强制进入本地账号密码登录页。
2. 使用毕昇**本地全局超级管理员**账号密码登录。
3. 打开浏览器开发者工具（F12）：
   - **方法 A（复制 Cookie）**：进入 **Application → Cookies → 当前域名**，复制 `access_token_cookie` 的值；后续 `curl` 请求加上：
     ```bash
     -H "Cookie: access_token_cookie=<复制的Cookie值>"
     ```
   - **方法 B（导入成 Cookie Jar 或直接导出请求）**：在 **Network** 面板选中任意 `/api/v1/...` 请求，右键 **Copy → Copy as cURL**，提取其中的 `-b 'access_token_cookie=...'` 或 `Cookie` 请求头。

### 方式二：命令行调用登录接口生成 `$COOKIE_JAR`（适合脚本自动化）

毕昇 `/api/v1/user/login` 对密码有两项前置机制：
1. **RSA 加密**：只要 Redis 中存在缓存公钥 `RSA_KEY`（任意端访问过登录页或调用过 `/api/v1/user/public_key` 后即存在），后端会先用服务端私钥做 **PKCS#1 v1.5 + Base64 解密**；因此脚本应固定先拉取 `/api/v1/user/public_key` 对密码加密。
2. **验证码开关**：通过 `GET /api/v1/user/get_captcha` 返回的 `data.user_capthca` 判断（默认关闭；若为 `true`，需携带 `captcha_key` 与 `captcha`）。

以下完整脚本会完成「获取 RSA 公钥 → 检查验证码开关 → 加密密码登录 → 保存 `access_token_cookie` 至 `$COOKIE_JAR`」：

```bash
export PUBLIC_ORIGIN="http://110.16.193.170:50055"
export SUPER_USER="admin"
export COOKIE_JAR="/tmp/bisheng-super-admin.cookies"

# 从终端安全读入本地超管明文密码（不留在命令历史）
read -r -s -p "Local super admin password: " SUPER_PWD; echo
export SUPER_PWD

# 1. 检查是否开启图形验证码
curl --silent --show-error "$PUBLIC_ORIGIN/api/v1/user/get_captcha" \
  | python3 -c 'import sys,json; d=json.load(sys.stdin)["data"]; print("captcha_required:", d["user_capthca"])'

# 2. 获取 PKCS#1 RSA 公钥并用 Python rsa 库加密后登录，写入 Cookie Jar
#    注：若本机未全局安装 rsa，可使用项目虚拟环境 src/backend/.venv/bin/python
ENCRYPTED_PWD=$(
  curl --silent --show-error "$PUBLIC_ORIGIN/api/v1/user/public_key" \
  | python3 -c '
import base64, json, os, rsa, sys
pubkey_pem = json.load(sys.stdin)["data"]["public_key"].encode("utf-8")
pubkey = rsa.PublicKey.load_pkcs1(pubkey_pem)
cipher = rsa.encrypt(os.environ["SUPER_PWD"].encode("utf-8"), pubkey)
print(base64.b64encode(cipher).decode("ascii"))
'
)
unset SUPER_PWD

LOGIN_RESP=$(
  curl --silent --show-error --fail-with-body \
    --cookie-jar "$COOKIE_JAR" \
    -X POST "$PUBLIC_ORIGIN/api/v1/user/login" \
    -H "Content-Type: application/json" \
    --data "{\"user_name\":\"$SUPER_USER\",\"password\":\"$ENCRYPTED_PWD\"}"
)
unset ENCRYPTED_PWD

# 3. 校验登录成功、全局超管身份及 Cookie Jar 是否已写入 access_token_cookie
python3 - <<'PY' "$LOGIN_RESP"
import json, sys
resp = json.loads(sys.argv[1])
data = resp.get("data") or {}
assert resp.get("status_code") == 200, f"Login failed: {resp}"
assert data.get("is_global_super") is True, f"Not global super admin: {data}"
assert not data.get("requires_tenant_selection"), "Super admin hit multi-tenant selection"
print("Login OK: user_id=", data.get("user_id"), "is_global_super=", data.get("is_global_super"))
PY
grep -q "access_token_cookie" "$COOKIE_JAR" && echo "COOKIE_JAR ready: $COOKIE_JAR"
```

> **提示**：
> - 若 `get_captcha` 返回 `user_capthca: true`，可从该响应拿到 `data.captcha_key` 与 Base64 验证码图片 `data.captcha`，在 `/api/v1/user/login` 请求体补上 `"captcha_key"` 和 `"captcha"` 字段即可。
> - 仅在本地开发环境且 Redis 尚未生成过 `RSA_KEY` 时密码才会按明文兜底；生产及联调环境请始终先调 `/api/v1/user/public_key` 加密。
> - 若登录账号属于多个租户且返回 `requires_tenant_selection: true`，请改用所属租户单一的本地超管账号，或在浏览器 `/admin-login` 完成选租户后再提取 Cookie。

---

## 3. 接口总览

统一路由前缀：`/api/v1/identity-integrations/kunlian/api-keys`

| 操作 | 方法与路径 | 成功 HTTP 状态 | 说明 |
| --- | --- | --- | --- |
| 签发 Key | `POST /api/v1/identity-integrations/kunlian/api-keys` | `201` | 创建新密钥，明文仅本次返回一次 |
| 查询列表 | `GET /api/v1/identity-integrations/kunlian/api-keys` | `200` | 分页返回元数据（无明文） |
| 查询详情 | `GET /api/v1/identity-integrations/kunlian/api-keys/{key_id}` | `200` | 返回单个密钥元数据（含已吊销记录） |
| 更新授权 | `PATCH /api/v1/identity-integrations/kunlian/api-keys/{key_id}` | `200` | 修改外部租户范围、能力集合或过期时间 |
| 轮换 Key | `POST /api/v1/identity-integrations/kunlian/api-keys/{key_id}/rotate` | `201` | 原子吊销旧 Key 并签发继承配置的新 Key |
| 吊销 Key | `POST /api/v1/identity-integrations/kunlian/api-keys/{key_id}/revoke` | `200` | 立即吊销（幂等操作） |

---

## 4. 签发 API Key（核心操作）

### 4.1 请求说明

```http
POST /api/v1/identity-integrations/kunlian/api-keys
Content-Type: application/json
Cookie: access_token_cookie=<本地超管Cookie>
```

### 4.2 请求体参数（`KeyIssue`，严格校验 `extra="forbid"`）

| 字段 | 类型 | 必填 | 约束说明 |
| --- | --- | --- | --- |
| `connection_id` | `string` | 是 | `1 ~ 128` 字符，非空白且首尾不能有空格；须与系统配置 `sso_sync.kunlian.connection_id` 一致（例如 `104` 环境当前为 `"kunlian-workflow-test"`） |
| `integration_id` | `string` | 是 | `1 ~ 128` 字符，非空白且首尾不能有空格（例如 `"kunlian"`） |
| `tenant_ids` | `string[]` | 是 | `1 ~ 1000` 项，每项 `1 ~ 128` 字符且首尾无空格（服务端自动按序去重）；填允许访问的**昆联外部租户 ID** 列表，或传 `["*"]` 表示授权全部已映射外部租户 |
| `capabilities` | `string[]` | 是 | `1 ~ 5` 项，仅允许枚举值 `read`、`write`、`publish`、`invoke`、`grant` |
| `expires_at` | `string \| null` | 否 | ISO-8601 时间戳或 `null`（默认永不过期）；非 `null` 时**必须晚于当前 UTC 时间** |

**`capabilities` 权限范围说明：**
- `read`：查询工作流列表、详情、版本列表与授权查询
- `write`：新建、修改工作流及草稿/版本
- `publish`：发布或下线工作流
- `invoke`：触发运行、提交交互输入、取消与查询运行状态
- `grant`：授予或回收工作流访问/使用权限

### 4.3 请求示例

```bash
curl --silent --show-error --fail-with-body \
  --cookie "$COOKIE_JAR" \
  -X POST "$PUBLIC_ORIGIN/api/v1/identity-integrations/kunlian/api-keys" \
  -H "Content-Type: application/json" \
  --data '{
    "connection_id": "kunlian-workflow-test",
    "integration_id": "kunlian",
    "tenant_ids": ["kunlian-tenant-001"],
    "capabilities": ["read", "write", "publish", "invoke", "grant"],
    "expires_at": null
  }'
```

### 4.4 成功响应示例（HTTP `201 Created`）

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "id": 1,
    "integration_id": "kunlian",
    "connection_id": "kunlian-workflow-test",
    "policy_revision": 1,
    "expires_at": null,
    "revoked_at": null,
    "created_by": 1,
    "create_time": "2026-11-25T10:40:00",
    "rotated_from_id": null,
    "tenant_ids": ["kunlian-tenant-001"],
    "capabilities": ["read", "write", "publish", "invoke", "grant"],
    "key_mask": "bs-kl-****AbCd",
    "api_key": "bs-kl-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  }
}
```

> **重要提醒**：`api_key` 明文格式固定为 `bs-kl-` + 43 位 URL 安全字符（正则 `bs-kl-[A-Za-z0-9_-]{43}`），**仅在签发（`POST`）和轮换（`POST .../rotate`）接口返回一次**。数据库只保存 `token_hash`（SHA-256）与末 4 位掩码 `last4`，丢失后无法找回，只能轮换或重新签发。

---

## 5. 生命周期管理接口

### 5.1 分页查询列表

```bash
curl --silent --show-error --cookie "$COOKIE_JAR" \
  "$PUBLIC_ORIGIN/api/v1/identity-integrations/kunlian/api-keys?offset=0&limit=20"
```
- 查询参数：`offset >= 0`（默认 `0`），`1 <= limit <= 100`（默认 `100`）。
- 返回 `data` 为密钥元数据列表（不含 `api_key`）。

### 5.2 查询单个详情

```bash
curl --silent --show-error --cookie "$COOKIE_JAR" \
  "$PUBLIC_ORIGIN/api/v1/identity-integrations/kunlian/api-keys/1"
```
- `key_id` 须为正整数；已吊销的 Key 仍可查看元数据与 `revoked_at`。

### 5.3 更新授权范围或过期时间

```bash
curl --silent --show-error --cookie "$COOKIE_JAR" \
  -X PATCH "$PUBLIC_ORIGIN/api/v1/identity-integrations/kunlian/api-keys/1" \
  -H "Content-Type: application/json" \
  --data '{
    "tenant_ids": ["kunlian-tenant-001", "kunlian-tenant-002"],
    "capabilities": ["read", "invoke"],
    "expires_at": "2027-01-01T00:00:00Z"
  }'
```
- `tenant_ids`、`capabilities`、`expires_at` 均可选（按实际传入字段局部更新；显式传 `"expires_at": null` 可改为永不过期），禁止未知字段。
- 已吊销的 Key 不可更新（返回 `409`）；更新成功后 `policy_revision` 自动递增 `1`。

### 5.4 轮换 API Key

```bash
curl --silent --show-error --cookie "$COOKIE_JAR" \
  -X POST "$PUBLIC_ORIGIN/api/v1/identity-integrations/kunlian/api-keys/1/rotate"
```
- 返回 HTTP `201`：原子吊销旧 Key，并签发继承旧 Key 的 `connection_id`、`integration_id`、`tenant_ids`、`capabilities`、`expires_at` 的新 Key（`rotated_from_id` 记录旧 `id`），并在 `data.api_key` 返回新明文一次。
- 旧 Key 若已吊销或发生并发更新冲突，返回 `409`。

### 5.5 吊销 API Key

```bash
curl --silent --show-error --cookie "$COOKIE_JAR" \
  -X POST "$PUBLIC_ORIGIN/api/v1/identity-integrations/kunlian/api-keys/1/revoke"
```
- 写入 `revoked_at` 并将 `policy_revision + 1`；重复吊销具有幂等性。

---

## 6. 签发后业务接口验活

拿到 `bs-kl-...` 密钥后，不要带管理员 Cookie，直接使用 Bearer Key + `user_account` 验证：

```bash
export KL_API_KEY="bs-kl-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
export USER_ACCOUNT="<已在毕昇生效的昆联用户User.user_name>"

curl --silent --show-error \
  -H "Authorization: Bearer $KL_API_KEY" \
  "$PUBLIC_ORIGIN/api/v2/kunlian/workflows?user_account=$USER_ACCOUNT"
```

**调用 `/api/v2/kunlian/*` 强制规范：**
1. 必须有且仅有一个查询参数 `user_account`（严格匹配毕昇活跃用户的 `User.user_name`，且目标外部租户在 Key 的 `tenant_ids` 允许范围内或 Key 为 `["*"]`）；
2. **严禁**携带 `Cookie`、`X-On-Behalf-Of`、`X-End-User`、`X-User-Id`、`X-Tenant-Id` 请求头，以及 `external_tenant_id` / `external_user_id` 查询参数（出现即返回 `422`）。
3. **多租户账号消歧与可选请求头 `X-Kunlian-Tenant-Id`**：
   - 若用户归属单个租户，直接解析通过，无需额外参数。
   - 若同一 `user_account` 归属多个租户，服务端依次按 **API Key `tenant_ids`（非 `["*"]` 时自动收窄）→ 请求头 `X-Kunlian-Tenant-Id` → URL 路径 `{workflow_id}` 自动定位工作流所属租户** 收敛至唯一有效身份。
   - 使用 `["*"]`（或包含多租户的）Key 访问**不含 `workflow_id` 的接口**（如 `GET /workflows`、`POST /workflows`、`POST /workflow-runs`）且命中多个租户时，需显式携带 `-H "X-Kunlian-Tenant-Id: <昆联外部租户ID>"`（1～64 字符、单值、无首尾空白）；未指定且仍存在多租户歧义时返回 `403`，格式非法或传多值返回 `422`（注意区分：指定外部租户应使用 `X-Kunlian-Tenant-Id`，禁止使用被拦截的 `X-Tenant-Id`）：
     ```bash
     curl --silent --show-error \
       -H "Authorization: Bearer $KL_API_KEY" \
       -H "X-Kunlian-Tenant-Id: kunlian-tenant-001" \
       "$PUBLIC_ORIGIN/api/v2/kunlian/workflows?user_account=$USER_ACCOUNT"
     ```

---

## 7. 常见错误码对照

| HTTP 状态 | 业务 `status_code` | 原因说明 | 排查建议 |
| --- | --- | --- | --- |
| `401` | `401` / `26002` | 未登录、Cookie 失效、或业务 Key 无效/已过期/已吊销 | 重新获取本地超管 Cookie；业务调用确认未用错或已吊销的 Key |
| `403` | `19322` | 当前登录用户非全局超级管理员，或业务 Key 缺少对应能力/外部租户不在白名单 | 确认使用本地超管调用控制面；确认 `capabilities` 与 `tenant_ids` 覆盖当前请求 |
| `404` | `19322` | 指定的 `key_id` 不存在 | 先调列表接口核对 `id` |
| `409` | `19327` | 对已吊销的 Key 执行更新/轮换，或并发修改 `policy_revision` 冲突 | 调详情接口确认 `revoked_at` 与最新状态 |
| `422` | `19320` / Pydantic 校验 | 字段缺失、多余字段、`capabilities` 非法、`expires_at` 早于当前时间、`key_id <= 0` 或字符串含首尾空白 | 按第 4.2 节参数约束修正 JSON |
| `503` | `19324` | 数据库或底层依赖不可用 | 检查 `bisheng-kunlian-backend` 与数据库服务状态 |

---

## 8. 运维安全建议

- 操作完成后及时清理临时 Cookie 文件与明文环境变量：`rm -f "$COOKIE_JAR"`，`unset KL_API_KEY`。
- 禁止将签发返回的真实 `bs-kl-...` 明文写入 Git 仓库、镜像或公开文档。
