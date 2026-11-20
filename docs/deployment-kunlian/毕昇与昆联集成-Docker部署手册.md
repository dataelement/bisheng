# 毕昇与昆联集成：Docker Compose 部署手册

适用分支：`bisheng`（`feat/v3.0.0/118-kunlian-integration`）、`bisheng-gateway`（`feat/kunlian-integration`）· 部署模式：单机 Linux、Docker Engine + Compose V2（`≥ 2.24.4`，overlay 使用 `!override`）。

## 1. 集成能力与运行时架构

当前版本已完整覆盖以下毕昇与昆联协同能力，部署时按需启用对应配置即可：

1. **SSO 单点登录与目录同步**：OIDC 授权码 + PKCE S256 登录、统一退出、全租户只读目录周期同步；支持人工创建租户映射或开启 `auto_onboarding_enabled` 自动开通。
2. **昆联平台资源节点（Workflow 内调用）**：
   - **平台大模型（`platform_llm`）**：目录拉取与推理（`/api/platform/v1/chat/completions`）。
   - **平台知识库（`platform_knowledge`）**：目录拉取与真实检索（`/api/platform/v1/knowledge/retrieve`）。
   - **平台 Agent（`platform_agent`）**：目录拉取、同步对话与异步回调交互（`/api/platform/v1/agent-runtime/invoke` + `/runs/{id}`）。
3. **Workflow 资料实时同步**：工作流新建、编辑、发布、上下线通过 Outbox + Celery 回调昆联同步接口。
4. **昆联反向调用 Workflow**：
   - 账号作用域 OpenAPI：`/api/v2/kunlian/**`（服务账号密钥 + `user_account`）。
   - 候选交互协议（`kunlian-workflow-candidate-v1`）：`/api/v2/workflow/{capabilities,invoke,invocations/{operation_key},sessions/{session_id},sessions/{session_id}/cancel}`，通过昆联 `/oidc/introspect` 验票及 `/oidc/workflow-callback/token` 换票回调 Agent。

```text
浏览器 / 昆联平台服务端
  -> 公开入口（外层 HTTPS 反代，转发至 frontend:3001）
  -> frontend（Nginx，SPA 静态资源 + 协议路由 + /api 转发）
  -> gateway:8080（License、昆联 OIDC 登录/退出协议、HTTP/WS 转发）
  -> backend:7860 / backend_worker（API + Celery Worker + Beat + Linsight）
       ├─ 内部依赖：MySQL（bisheng / bisheng_gateway / openfga）、Redis、OpenFGA、MinIO、Milvus、etcd、ES、code-runner-1/2
       └─ 外部对接昆联：OIDC（authorize/token/jwks/logout/introspect/workflow-callback）、用户目录 API、平台资源网关（/api/platform/v1/...）、资料同步回调
```

## 2. 镜像、主机要求与前置信息清单

### 2.1 主机与镜像要求

- **环境要求**：Linux x86_64（推荐 `8 vCPU / 32 GiB RAM / 200 GiB SSD`），NTP 时钟同步，Docker Engine + Compose V2 **≥ 2.24.4**（旧版 Python `docker-compose` V1 不支持 `!override`）。
- **内核参数**（Elasticsearch 需要）：

```bash
sudo sysctl -w vm.max_map_count=262144
printf 'vm.max_map_count=262144\n' | sudo tee /etc/sysctl.d/90-bisheng-es.conf
sudo sysctl --system
```

- **镜像引用**（公网仓库统一 `cr.dataelem.com`，需先 `docker login cr.dataelem.com`；生产验收后建议锁定 `@sha256:...` digest）：

| 用途 | 镜像引用 |
| --- | --- |
| API / Worker / Beat / Linsight | `cr.dataelem.com/dataelement/bisheng-backend:feat_v3.0.0_118-kunlian-integration` |
| 前端 SPA + Nginx | `cr.dataelem.com/dataelement/bisheng-frontend:feat_v3.0.0_118-kunlian-integration` |
| 代码沙箱（双实例共用） | `cr.dataelem.com/dataelement/bisheng-sandbox:feat_v3.0.0_118-kunlian-integration` |
| 商业 Gateway（AMD64 / ARM64） | `cr.dataelem.com/dataelement/gateway:feat_kunlian-integration`（ARM 加 `-arm64`） |

### 2.2 需要昆联方提供的信息（部署前索取）

| 类别 | 配置项 | 说明与落地位置 |
| --- | --- | --- |
| **OIDC 基础** | `issuer`、各固定端点、RS256 JWKS | 不得依赖 301 重定向；接入 `sso_sync.kunlian` 与 `custom.kunlian` |
| **OIDC 客户端** | `client_id`、`client_secret` | 需启用 `client_secret_basic`、PKCE S256、`openid profile`、Token Exchange；`client_secret` 写入双端 env 文件 |
| **OIDC 反向调用授权** | `/oidc/introspect`、`/oidc/workflow-callback/token` 权限 | 若需使用昆联调毕昇 Workflow 及回调交互 Agent，昆联必须为该 `client_id` 开放这两个端点与对应 scope |
| **用户目录同步** | 全租户只读 `X-API-Key` | 写入 `secrets/kunlian-backend.env` 的 `KUNLIAN_SYNC_API_KEY` |
| **准入范围与语义** | `allowed_tenant_id`、`allowed_workspace_ids`、`state_semantics_revision` | 若开启多租户/自动开通，另需确认各租户 Workspace 映射清单与测试 `subject` |
| **平台资源网关** | `resource_base_url`、`resource_audience` | `resource_base_url` 为平台资源 API 基地址（如 `https://platform.example.com`）；`resource_audience` 默认 `moduvela-platform-resources`，若昆联自定义则必须对齐；均在管理后台「系统配置」`workflow` 段填写 |
| **Workflow 资料回调**（可选） | 回调 URL、`key_id`、`secret_hex` | 需要实时同步工作流元数据到昆联时提供；分别填入 `KUNLIAN_SNAPSHOT_CALLBACK_URL`、`KUNLIAN_CALLBACK_KEY_ID`、`KUNLIAN_CALLBACK_SECRET_HEX`（64 位小写 hex） |
| **测试资产** | 测试账号、可调用测试 Agent/知识库/模型 | 用于联调与权限验收（含支持交互的子 Agent） |

### 2.3 毕昇侧需向昆联反向登记的信息

| 登记项 | 取值规则 | 说明 |
| --- | --- | --- |
| **登录回调白名单** | `{PUBLIC_ORIGIN}/api/kunlian/callback` | 协议、小写域名、非默认端口须与公网入口完全一致 |
| **退出回调白名单** | `{PUBLIC_ORIGIN}/api/kunlian/logout/callback` | 同上 |
| **毕昇 Workflow 调用入口** | `{PUBLIC_ORIGIN}/api/v2/workflow/...`（OpenAPI `/api/v2/kunlian/...`） | 需保证昆联服务端出网可访问此地址；若启用 OpenAPI，还需在毕昇后台签发服务账号 `bs-kl-*` Key |

### 2.4 毕昇侧自行准备或生成的信息

| 项目 | 来源 / 生成方式 | 说明 |
| --- | --- | --- |
| **商业 License 文件** | 毕昇授权方签发 | 先收集宿主机指纹申请 License；由 `install.sh --prepare-only` 注入 `.env` |
| **数据库 / MinIO / 沙箱凭据** | `openssl rand -hex 32` | 分别生成并填入 `docker/.env`；`config.yaml` 中 MySQL 密码须再经 `encrypt_token` 加密 |
| **内部通信与加密密钥** | 见第 4.2 节生成命令 | `KUNLIAN_INTERNAL_SECRET`、`KUNLIAN_BACKEND_CSRF_SECRET`、`KUNLIAN_BACKEND_FERNET_KEY`、`KUNLIAN_GATEWAY_TRANSACTION_KEY` 四者严禁复用 |
| **Gateway 对端 IP** | 容器启动后 `docker inspect` 读取 | 精确 `/32` 填入 `trusted_gateway_networks` |

## 3. 初始化部署目录与镜像预检

假定源码与配置包解压至 `/opt/bisheng-kunlian/source`，后续操作均在其下 `docker/` 目录执行：

```bash
cd /opt/bisheng-kunlian/source
test -f docker/.env || cp docker/.env.example docker/.env
chmod 600 docker/.env
install -d -m 700 docker/secrets
cp docs/deployment-kunlian/compose.kunlian.yml docker/compose.kunlian.yml
cp docs/deployment-kunlian/kunlian-protocol-proxy.inc docker/nginx/kunlian-protocol-proxy.inc
```

准备商业 License 文件（如 `/opt/bisheng-kunlian/secrets/license.txt`，权限 `0600`）后，执行**仅生成配置、不启动**命令，自动写入 Gateway 密码、HMAC 密钥、License 文本并生成 Nginx 配置目录：

```bash
cd /opt/bisheng-kunlian/source
bash docker/install.sh --prepare-only --gateway \
  --license-file /opt/bisheng-kunlian/secrets/license.txt \
  --public-url https://workflow.example.com
cd docker
```

> 注意：后续升级或重启禁止再无参执行 `install.sh`，避免覆盖手工调整的 Nginx 与 `.env`；多组件统一通过第 5 节 `docker compose` 命令操作。

拉取镜像并核验架构（离线环境在同架构联网机 `docker save` 后拷贝导入即可）：

```bash
docker login cr.dataelem.com
docker pull cr.dataelem.com/dataelement/bisheng-backend:feat_v3.0.0_118-kunlian-integration
docker pull cr.dataelem.com/dataelement/bisheng-frontend:feat_v3.0.0_118-kunlian-integration
docker pull cr.dataelem.com/dataelement/bisheng-sandbox:feat_v3.0.0_118-kunlian-integration
docker pull cr.dataelem.com/dataelement/gateway:feat_kunlian-integration
```

## 4. 全量配置说明（按文件逐项填写）

> **配置分层规则**：`docker/.env` 仅做 Compose 插值和固定基础变量，不会自动透传全部键进容器；昆联秘密通过 `secrets/*.env` 经 `compose.kunlian.yml` 的 `env_file` 注入；SSO/基础设施写在 `bisheng/config/config.yaml` 和 `gateway/config/application.yml`（均只读挂载）；而平台大模型 / 知识库 / Agent 节点参数（`workflow` 段）保存在**数据库系统配置 `initdb_config`** 中，服务启动后通过管理后台「系统配置」修改生效。

### 4.1 `docker/.env`

保留 `install.sh --prepare-only` 生成的 `BISHENG_GATEWAY_*`、`BISHENG_NGINX_CONF_DIR`、`BISHENG_PUBLIC_URL`、`COMPOSE_PROFILES=gateway`、`BISHENG_PRO=true`，核对并替换以下变量（勿保留 `REPLACE_*`）：

```dotenv
BISHENG_BACKEND_IMAGE=cr.dataelem.com/dataelement/bisheng-backend:feat_v3.0.0_118-kunlian-integration
BISHENG_FRONTEND_IMAGE=cr.dataelem.com/dataelement/bisheng-frontend:feat_v3.0.0_118-kunlian-integration
BISHENG_SANDBOX_IMAGE=cr.dataelem.com/dataelement/bisheng-sandbox:feat_v3.0.0_118-kunlian-integration
BISHENG_GATEWAY_IMAGE=cr.dataelem.com/dataelement/gateway:feat_kunlian-integration

COMPOSE_PROJECT_NAME=bisheng-kunlian
BISHENG_NETWORK_NAME=bisheng-kunlian-network
COMPOSE_PROFILES=gateway
BISHENG_PRO=true
BISHENG_PUBLIC_URL=https://workflow.example.com
DOCKER_VOLUME_DIRECTORY=.
SANDBOX_CPUS=2
LOCAL_ISOLATION=uid

# 全部使用 openssl rand -hex 32 分别生成；MYSQL_ROOT_PASSWORD 与 OPENFGA_DATASTORE_URI 密码须一致
MYSQL_ROOT_PASSWORD=REPLACE_RANDOM_HEX
OPENFGA_DATASTORE_URI=root:REPLACE_SAME_MYSQL_PASSWORD@tcp(mysql:3306)/openfga?parseTime=true
MINIO_ROOT_USER=REPLACE_ACCESS_KEY
MINIO_ROOT_PASSWORD=REPLACE_RANDOM_SECRET
SANDBOX_TOKEN=REPLACE_RANDOM_SECRET
```

- 不依赖应用工场时，**不要**开启 `app-runtime` profile（但保留 `.env.example` 中可选镜像变量的合法占位值以满足主 Compose 校验）。
- 已有数据的 MySQL / MinIO **仅改 `.env` 不会更改库内密码**；必须用原有凭据或按数据库标准流程改密。

### 4.2 `docker/secrets/kunlian-backend.env` 与 `docker/secrets/kunlian-gateway.env`

先用已拉取的后端镜像离线生成后端 Fernet 密钥，再创建两份 `0600` 秘密文件：

```bash
# 生成后端 Fernet key（URL-safe Base64，32 字节）
docker run --rm --network none --entrypoint python \
  cr.dataelem.com/dataelement/bisheng-backend:feat_v3.0.0_118-kunlian-integration -c \
  'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'

# 生成 Gateway 事务密钥（标准 Base64，32 字节）
openssl rand -base64 32

# 生成各独立 hex 密钥（每次执行生成一把）
openssl rand -hex 32
```

**`docker/secrets/kunlian-backend.env`**（由 `backend` 与 `backend_worker` 同时挂载）：

```dotenv
# --- [昆联方提供] OIDC 与目录同步凭据 ---
KUNLIAN_CLIENT_SECRET=REPLACE_FROM_KUNLIAN
KUNLIAN_SYNC_API_KEY=REPLACE_FROM_KUNLIAN

# --- [毕昇侧生成] 内部验签与会话加密 ---
KUNLIAN_INTERNAL_SECRET=REPLACE_SHARED_RANDOM_HEX
KUNLIAN_BACKEND_CSRF_SECRET=REPLACE_DISTINCT_RANDOM_HEX
KUNLIAN_BACKEND_FERNET_KEY=REPLACE_URLSAFE_BASE64_32_BYTES

# --- [昆联方提供，可选] Workflow 资料同步回调（三项全填即启用，不填则静默跳过同步推送） ---
# KUNLIAN_SNAPSHOT_CALLBACK_URL=https://platform.example.com/api/v1/workflows/sync-callback
# KUNLIAN_CALLBACK_KEY_ID=REPLACE_KEY_ID
# KUNLIAN_CALLBACK_SECRET_HEX=REPLACE_64_HEX_CHARS
```

**`docker/secrets/kunlian-gateway.env`**（由 `gateway` 挂载）：

```dotenv
# 与 kunlian-backend.env 保持完全一致
KUNLIAN_CLIENT_SECRET=REPLACE_SAME_CLIENT_SECRET
KUNLIAN_INTERNAL_SECRET=REPLACE_SAME_INTERNAL_SECRET

# [毕昇侧生成] 标准 Base64（32 字节），与 Fernet key 不同
KUNLIAN_GATEWAY_TRANSACTION_KEY=REPLACE_STANDARD_BASE64_32_BYTES
```

```bash
chmod 600 .env secrets/kunlian-backend.env secrets/kunlian-gateway.env
```

### 4.3 `docker/bisheng/config/config.yaml`（后端主配置）

1. **MySQL 密码密文与基础设施段**：`database_url` 中的密码段**必须**使用项目内置 `encrypt_token` 生成的密文（不能填明文，也不能使用上面新生成的 Fernet key）：

```bash
docker run --rm --network none --entrypoint python \
  cr.dataelem.com/dataelement/bisheng-backend:feat_v3.0.0_118-kunlian-integration -c \
  'import getpass; from bisheng.core.config.settings import encrypt_token; print(encrypt_token(getpass.getpass("MySQL password: ")).decode())'
```

填入 `config.yaml`（同网络容器域名为 `mysql` / `redis` / `openfga`，不要写 `127.0.0.1`）：

```yaml
database_url: "mysql+pymysql://root:REPLACE_ENCRYPTED_PASSWORD@mysql:3306/bisheng?charset=utf8mb4"
redis_url: "redis://redis:6379/1"
celery_redis_url: "redis://redis:6379/2"
openfga:
  enabled: true
  api_url: "http://openfga:8080"
```

2. **昆联 SSO 与目录配置**：按 [后端配置片段](backend-kunlian.fragment.yaml) 合并到 `config.yaml`，不要重复已有顶层键（**`platform_llm` / `platform_agent` / `platform_knowledge` 不在这里配置**，请见第 4.4 节）。重点项如下：

| 配置路径 | 填写来源 | 必填 | 关键说明 |
| --- | --- | --- | --- |
| `multi_tenant.enabled` | 毕昇固定 | 是 | 必须为 `true` |
| `sso_sync.gateway_hmac_secret` | 毕昇自动 | 是 | 保持 `!env ${BISHENG_GATEWAY_HMAC_SECRET}` |
| `sso_sync.kunlian.directory_enabled` / `login_enabled` | 毕昇控制 | 是 | 初始置 `directory_enabled: true`、`login_enabled: false`；目录与映射就绪后再递增 `policy_revision` 开启登录 |
| `sso_sync.kunlian.issuer` / `client_id` | **昆联提供** | 是 | `issuer` 须与 OIDC discovery 返回严格一致 |
| `sso_sync.kunlian.login_scope_mode` | 双方确认 | 是 | `fixed`（单租户，填 `allowed_tenant_id` + `allowed_workspace_ids`）、`tenant_workspace_map`（填 `tenant_workspace_allowlist`）或 `directory_active_tenants` |
| `sso_sync.kunlian.auto_onboarding_enabled` | 双方确认 | 否 | 默认 `false`（人工创建本地租户并显式绑定）；设 `true` 时按目录自动开通本地租户与基础角色 |
| `sso_sync.kunlian.state_semantics_revision` | **双方确认** | 是 | 双方约定的停用/启用语义版本，不得留空或填 `REPLACE` |
| `sso_sync.kunlian.public_origin` / `redirect_uri` / `logout_redirect_uri` | 毕昇入口 | 是 | 协议+小写域名+非默认端口（无结尾 `/`），回调路径固定 `/api/kunlian/callback` 与 `/api/kunlian/logout/callback` |
| `sso_sync.kunlian.approved_test_origins` | 双方确认 | 仅测试 | 正式 HTTPS 环境保持 `[]`；HTTP 内网联调时须将 IdP 与站点 HTTP Origin 精确填入（不含 `*` 或网段） |
| `sso_sync.kunlian.endpoint_allowlist` | **昆联提供** | 是 | 须逐条列出 discovery、JWKS、introspect、分页用户列表、单用户详情模板完整 URL（见 [后端配置片段](backend-kunlian.fragment.yaml)） |
| `sso_sync.kunlian.trusted_gateway_networks` | 毕昇环境 | 是 | 启动 Gateway 后取实际同网 IP 填精确 `/32`（初次启动前可暂填片段占位地址，开登录前必须替换） |

### 4.4 管理后台「系统配置」（`initdb_config` 的 `workflow` 段）

后端运行时通过系统配置表 `initdb_config` 下的 **`workflow` 键**读取昆联平台资源节点参数（不在 `config.yaml` 读取）。在第 5.2 节服务启动并完成管理员登录后，进入管理后台「系统配置」，在现有 `workflow:` 块下补充以下子键并保存（后台保存会自动清除 Redis `config:initdb_config` 缓存并立即生效，无需重启容器）：

```yaml
workflow:
  max_steps: 50
  timeout: 5
  auto_rerun_on_open: false
  code_node_enabled: false
  platform_llm:
    enabled: true
    # [昆联提供] 昆联平台资源网关基地址（不会自动继承 issuer，必须显式填写）
    resource_base_url: https://platform.example.com
    # [昆联提供，可选] 留空时自动回退为 {sso_sync.kunlian.issuer}/oidc/token
    oidc_token_url: https://idp.example.com/oidc/token
    # [昆联提供] 若与默认值不同须改为昆联实际值
    resource_audience: moduvela-platform-resources
  platform_agent:
    mode: real
    # 上方 platform_llm.enabled=true 且已填地址时可省略并自动继承；否则必须显式填写
    resource_base_url: https://platform.example.com
    oidc_token_url: https://idp.example.com/oidc/token
    resource_audience: moduvela-platform-resources
    list_timeout_seconds: 10.0
    invoke_timeout_seconds: 135.0
  platform_knowledge:
    mode: real
    resource_base_url: https://platform.example.com
    oidc_token_url: https://idp.example.com/oidc/token
    resource_audience: moduvela-platform-resources
    list_timeout_seconds: 10.0
    retrieve_timeout_seconds: 65.0
  # 可选：昆联正式 Workflow API 并发与超时预算（不写则使用默认值）
  # kunlian_api:
  #   queue_seconds: 120
  #   run_seconds: 300
  #   wait_seconds: 900
  #   retain_seconds: 86400
  #   max_active_per_user: 5
  #   request_limit: 120
  #   request_window_seconds: 60
```

- **注意事项**：
  - `platform_agent` 与 `platform_knowledge` 代码默认 `mode: real`，未填写 `resource_base_url`（且未启用 `platform_llm.enabled: true` + 填写 `resource_base_url`）时会直接报未就绪。
  - 反向调用候选协议 `/api/v2/workflow/*` 的 `/oidc/introspect` 与 `/oidc/workflow-callback/token` 地址及 `expected_audience` 也读取上述 `platform_agent`（及回退 `sso_sync.kunlian.issuer`）配置。

### 4.5 `docker/gateway/config/application.yml`

将 [网关配置片段](gateway-kunlian.fragment.yaml) 合并进 `docker/gateway/config/application.yml`，保留原有路由、`spring.datasource`、`spring.data.redis`（db=3）与 `bisheng.*` 配置：

- **双端必须完全一致的字段**：`connection-id`、`issuer`、`client-id`、`allowed-tenant-id`、`allowed-workspace-ids`、`public-origin`、`redirect-uri`、`logout-redirect-uri`、`approved-test-origins`、`internal-key-id`、`internal-secret-reference`（`env:KUNLIAN_INTERNAL_SECRET`）、`client-secret-reference`（`env:KUNLIAN_CLIENT_SECRET`）。
- **网关专有字段**：
  - `enabled: false`（完成第 5 节目录同步与策略开启后再改为 `true`）
  - `backend-base-url: http://backend:7860` 与 `approved-service-origins: ["http://backend:7860"]`
  - `endpoint-allowlist`：须包含 `/.well-known/openid-configuration`、`/oidc/authorize`、`/oidc/token`、`/oidc/jwks`、`/oidc/logout` 完整 URL
  - `transaction-encryption-secret-reference: env:KUNLIAN_GATEWAY_TRANSACTION_KEY`
- **API 转发验证**：模板中 `bisheng-http` 已转发 `/api/v1/**,/api/v2/**,/api/v3/**` 到 `http://backend:7860`，且 `/api/v2` 在 `anonymous-path-prefixes` 中，因此 `/api/v2/workflow/**` 与 `/api/v2/kunlian/**` 无需新增 Gateway 路由。

### 4.6 Nginx 入口与协议路由

将 [SSO Nginx location 片段](nginx-kunlian-locations.conf) 插入 `.env` 中 `$BISHENG_NGINX_CONF_DIR/default.conf` 的 `server { listen 3001; ... }` 内部（不可放在 `http` 顶层），保证四条登录/退出精确路径走 Gateway 且**关闭协议日志避免泄露 `code`/`state`/`ticket`**：

- `GET /api/oauth2/kunlian`、`GET /api/kunlian/callback`、`POST /api/kunlian/logout`、`GET /api/kunlian/logout/callback`

若前端外层有 SLB/Nginx 终止 TLS，转发到 `3001` 时须保留 `Host`、`X-Forwarded-Proto`、`X-Forwarded-Host` 与 WebSocket `Upgrade` 头，并清洗客户端伪造头。

## 5. 按顺序启动与启用集成功能

以下均在 `/opt/bisheng-kunlian/source/docker` 执行，统一使用组合命令确保注入 `secrets/*.env` 与 `127.0.0.1` 端口收敛：

```bash
DC=(docker compose --env-file .env -f docker-compose.yml -f compose.kunlian.yml)
"${DC[@]}" config --quiet
```

### 5.1 启动中间件与 Backend API（等待迁移完成）

```bash
"${DC[@]}" up -d mysql redis etcd minio elasticsearch
"${DC[@]}" up -d openfga
"${DC[@]}" up -d milvus
"${DC[@]}" up -d backend
# 确认日志中 alembic upgrade head 成功且 /health 返回 200
"${DC[@]}" logs --tail=80 backend
curl --fail --silent --show-error http://127.0.0.1:7860/health
```

### 5.2 启动 Worker、沙箱与 Gateway，并回填精确 Peer IP

> 注意：默认 `backend_worker` 为组合模式（含 Celery Worker + Linsight + **单个 Beat**），禁止通过横向复制该容器实现高可用，否则定时任务与目录同步会重复调度。

```bash
"${DC[@]}" up -d backend_worker code-runner-1 code-runner-2
"${DC[@]}" up -d gateway
"${DC[@]}" logs --tail=80 gateway-db-init gateway

# 查询 Gateway 在 Docker 共享网段的真实 IP，将精确 /32 更新进 config.yaml 的 trusted_gateway_networks
docker inspect bisheng-gateway --format '{{json .NetworkSettings.Networks}}'

# 使 config.yaml 与 secret 变更生效必须 force-recreate（单纯 restart 不会重载 env_file）
"${DC[@]}" up -d --force-recreate backend backend_worker

# 校验 Nginx 配置后启动前端
"${DC[@]}" run --rm --no-deps --entrypoint nginx frontend -t
"${DC[@]}" up -d frontend
```

### 5.3 系统配置、人工租户映射与开启登录

1. 用本地全局管理员登录 `/admin-login`，并在「系统配置」中按第 4.4 节完成 `workflow` 段（`platform_llm` / `platform_agent` / `platform_knowledge`）保存。
2. 若保持 `auto_onboarding_enabled: false`（默认推荐）：
   - 在租户管理新建或选定本地目标租户（记录整数 ID `LOCAL_TENANT_ID`）。
   - 通过管理 API 绑定昆联租户（替换占位符与本地管理员登录 Cookie Jar）：

```bash
# 查询现有绑定（新绑定 expected_revision 传 null；更新须传返回的 revision）
curl --silent --show-error --cookie "$COOKIE_JAR" \
  "$PUBLIC_ORIGIN/api/v1/identity-integrations/kunlian/tenant-bindings/$EXTERNAL_TENANT_ID"

curl --silent --show-error --cookie "$COOKIE_JAR" -X PUT \
  -H 'Content-Type: application/json' \
  --data '{"local_tenant_id":2,"expected_revision":null,"enabled":true}' \
  "$PUBLIC_ORIGIN/api/v1/identity-integrations/kunlian/tenant-bindings/$EXTERNAL_TENANT_ID"
```

3. 触发一次全量目录同步并确认就绪（目标映射 `materialized=true`、批次 `PUBLISHED`）：

```bash
curl --silent --show-error --cookie "$COOKIE_JAR" -X POST \
  "$PUBLIC_ORIGIN/api/v1/identity-integrations/kunlian/sync"
curl --silent --show-error --cookie "$COOKIE_JAR" \
  "$PUBLIC_ORIGIN/api/v1/identity-integrations/kunlian/status"
```

4. 为试点昆联影子用户分配对应角色与基础菜单（如 `admin`、`build`、`create_app`；若开启 `auto_onboarding_enabled: true` 则按目录自动分配基础访问）。
5. **先后端、后 Gateway 开启登录**：
   - 修改 `config.yaml`：`sso_sync.kunlian.login_enabled: true` 且 `policy_revision` 在当前值基础上 `+ 1`，执行 `"${DC[@]}" up -d --force-recreate backend backend_worker`，再调一次 `/sync` 并核验 `/status`。
   - 修改 Gateway `application.yml`：`custom.kunlian.enabled: true`，执行 `"${DC[@]}" up -d --force-recreate gateway`。
   - 若 Gateway 重建后 IP 变更，再次核对 `trusted_gateway_networks`；同步重载前端 Nginx：

```bash
"${DC[@]}" exec frontend nginx -t && "${DC[@]}" exec frontend nginx -s reload
curl --silent --show-error "$PUBLIC_ORIGIN/api/oauth2/list"
```

## 6. 联调与验收检查表

| 检查项 | 验证方法与预期结果 |
| --- | --- |
| **基础健康** | 所有容器 `Up`（`openfga-migrate` / `gateway-db-init` 为 `Exited (0)`）；`http://127.0.0.1:7860/health` 返回 200 |
| **SSO 登录与退出** | 访问 `/build/workflows` 跳转昆联完成认证回跳；`is_global_super=false` 且租户隔离生效；应用内退出完成双端回调，旧 Cookie 重放被拒；代理与后端日志无 `code`/`state`/`ticket` 泄露 |
| **目录周期同步** | 等待超过 `sync_interval_seconds`（默认 300s），`status` 中批次推进且测试账号停用/启用语义同步生效 |
| **平台 LLM / 知识库 / Agent 节点** | 画布中打开平台大模型、平台知识库、平台 Agent 节点，能列出昆联授权列表；调试运行返回真实推理/检索/Agent 结果；勾选 `allow_interaction` 的 Agent 节点可触发人工输入并恢复 |
| **Workflow 资料回调**（若启用） | 保存或发布工作流后，`backend_worker` 日志无投递错误，昆联侧收到带 `X-Workflow-Signature` 签名的 `202` 回执事件 |
| **反向调用能力探测** | `GET $PUBLIC_ORIGIN/api/v2/workflow/capabilities` 返回 `HTTP 200`，含 `protocol_version: "kunlian-workflow-candidate-v1"` |
| **反向调用与 Agent 交互** | 昆联持执行 Token 调 `POST /api/v2/workflow/invoke`（带 `workflow_version_id` 与 `X-Idempotency-Key`），`/oidc/introspect` 通过；工作流调起可交互子 Agent 时外层状态进入 `waiting_input`；子 Agent 完成后外层自动恢复并 `succeeded` |

## 7. 运维规范与常见故障排查

### 7.1 备份、升级与安全回退

- **必备份项**：`.env`、`secrets/`、License、`config.yaml`、`application.yml`、Nginx 配置，以及 MySQL 三个库（`bisheng`、`bisheng_gateway`、`openfga`）和 MinIO/Milvus/ES 卷；禁止执行 `docker compose down -v`。
- **修改生效方式**：改动 `.env`、`secrets/*.env` 或原子替换只读挂载 YAML 后，必须使用 `"${DC[@]}" up -d --force-recreate <service>`，单纯 `restart` 不会重读 `env_file` 或新 inode。
- **SSO 安全回退**：需保留用户退出能力时，**先**在入口阻断新登录 `GET /api/oauth2/kunlian` 并将后端 `login_enabled` 置 `false`（`policy_revision + 1`），退出窗口过后再停用 Gateway `custom.kunlian.enabled: false`（直接关闭网关开关会一并禁用退出端点）。

### 7.2 常见故障速查

| 现象 | 排查要点与处理 |
| --- | --- |
| Gateway HTTP 200 但业务码 `11001` | License 为空、过期或无效；核对 `.env` 中 `BISHENG_GATEWAY_LICENSE` 已由 `install.sh` 注入且与挂载文件一致 |
| `/api/oauth2/list` 无 `kunlian` | 核对 `custom.kunlian.enabled=true`、`KUNLIAN_GATEWAY_TRANSACTION_KEY` 为标准 Base64 32 字节、且双端 `client_id` / `issuer` 一致 |
| 内部签名失败 / `19324` | 核对双端 `internal_key_id`、`KUNLIAN_INTERNAL_SECRET`、服务器 NTP 时间、以及 `trusted_gateway_networks` 是否匹配 Gateway 当前 `/32` IP |
| `DIRECTORY_NOT_READY` | 检查 `backend_worker` 内 Beat 是否存活（且仅单实例）、`KUNLIAN_SYNC_API_KEY` 权限、`endpoint_allowlist` 是否含分页与详情模板路径 |
| 平台 LLM / 知识库 / Agent 报错未就绪 | 检查**管理后台「系统配置」**（数据库 `initdb_config`）`workflow` 段下 `platform_{llm,agent,knowledge}.resource_base_url` 已显式填写（不会从 `issuer` 自动推导）；使用大模型节点时需 `platform_llm.enabled: true` |
| 反向调用 `/api/v2/workflow/invoke` 401/503 | 确认昆联侧已对当前 `client_id` 开通 `POST /oidc/introspect`；检查系统配置 `workflow.platform_agent.oidc_token_url`（或 `issuer`）、`KUNLIAN_CLIENT_SECRET` 及 `resource_audience` 与执行 Token `aud` 是否匹配 |
| 工作流内交互 Agent 回调失败 | 确认昆联侧已对当前 `client_id` 开通 `POST /oidc/workflow-callback/token` 与 `platform.agent.invoke` scope，且 `backend` / `backend_worker` 容器均挂载最新 `secrets/kunlian-backend.env` |
| 任务排队不执行 | 检查 `backend_worker` 启动正常、监听 `workflow_celery` / `celery` 队列、且与 API 共享同一 `redis` 与 `mysql` |
