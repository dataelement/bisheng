# 本地 bisheng + Gateway，Docker 仅中间件

## 1. 启动中间件

在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File docker/local-dev/start-middleware.ps1
```

Linux/macOS:

```bash
bash docker/local-dev/start-middleware.sh
```

脚本会：停止 `bisheng-backend` / `bisheng-backend-worker` / `bisheng-frontend` 容器（若存在），再启动 MySQL、OpenFGA、Redis、ES、Milvus 依赖栈，并初始化 `bisheng_gateway` 库表。

## 1b. 清空 bisheng 业务库并同步清空 OpenFGA / Redis（避免 FGA 与 user_id 不一致）

仅执行 `reset-full-db-keep-superadmin.sql` **不会**清空 OpenFGA 使用的独立 MySQL 库 `openfga`，历史上会出现「新用户占用旧 user_id，继承旧权限元组」的问题。

**推荐一键顺序**（先停本机 uvicorn / Celery，再执行）：

```powershell
powershell -ExecutionPolicy Bypass -File docker/local-dev/reset-full-local-stack.ps1
```

Linux / macOS：

```bash
bash docker/local-dev/reset-full-local-stack.sh
```

脚本会：`FLUSHDB` Redis `1,2,3`（与默认 `config.yaml` 的 bisheng/celery 及 Gateway 常用库一致）→ `DROP/CREATE` MySQL `openfga` → `docker compose … openfga-migrate` → 导入 `reset-full-db-keep-superadmin.sql`。

**未包含**：Elasticsearch 索引、Milvus 集合、MinIO 桶内对象；若需「知识库也干净」，请另行删除对应索引/集合/桶，或使用 compose 卷重建（会丢全部 Docker 数据）。

## 2. 对齐关系

| 组件 | 地址 | 说明 |
|------|------|------|
| bisheng 后端 | `http://127.0.0.1:7860` | 源码启动，读 `src/backend/bisheng/config.yaml`（已指向本机中间件） |
| Gateway | `http://127.0.0.1:8180` | `bisheng-gateway` 仓库，`application-local.yml` |
| Gateway ↔ bisheng | `bisheng.bisheng-api-url` | 已设为 `7860` |
| Gateway ↔ Redis | `spring.data.redis` | `127.0.0.1:6379`，**database: 3**（与 bisheng 用的 db 1/2 区分） |
| Gateway ↔ MySQL | `bisheng_gateway` | root 密码与 compose 一致 `1234` |
| 组织同步 HMAC | `sso_sync.gateway_hmac_secret` / Gateway `bisheng.gateway-hmac-secret` | 两处必须一致（示例：`bisheng-local-hmac-20260422`）；Gateway 使用 F014 `POST /api/v1/departments/sync` 推部门（bisheng 已无 `/api/v2/group/sync`） |
| 管理端 Vite | `VITE_PROXY_TARGET` | 走 Gateway 时设为 `http://127.0.0.1:8180` |
| 工作台 Vite | `VITE_DEV_API_TARGET` | 走 Gateway 时设为 `http://127.0.0.1:8180` |

## 3. 启动顺序建议

1. 中间件脚本（含 OpenFGA migrate）
2. bisheng API：`cd src/backend`，`$env:config = "config.yaml"`（勿用 `bisheng\config.yaml`）
3. Celery worker / beat（与 `AGENTS.md` 一致，否则异步任务不跑）
4. Gateway：`cd bisheng-gateway`，`mvn package -DskipTests` 后 `java -jar ... --spring.profiles.active=local --server.port=8180`
5. Platform：`src/frontend/platform`，配置好 `.env.development.local` 后 `npm start`
6. Client：`src/frontend/client`，将 `src/frontend/env.development.gateway.example` 复制为 `src/frontend/.env.development.local` 后 `npm start`

示例环境变量见 `src/frontend/platform/env.development.gateway.example` 与 `src/frontend/env.development.gateway.example`。

## 4. Gateway 仓库

默认与 bisheng 同级目录：`../bisheng-gateway`（已由脚本/说明克隆时放在该路径）。若路径不同，自行调整启动命令中的目录。

构建需要 **JDK 17** 与 **Maven**（`mvn` 在 PATH 中）。示例：

```bash
cd ../bisheng-gateway
mvn -DskipTests package
java -jar target/gateway-0.0.1-SNAPSHOT.jar --spring.profiles.active=local --server.port=8180
```

`application-local.yml` 在 gateway 仓库内，覆盖路由、MySQL、Redis 与 `bisheng-api-url`，与 Docker 中间件及本机 bisheng 端口一致。

启用商业版 SSO 等需在后端启动前设置 `BISHENG_PRO=true`，见 `AGENTS.md`。

## 5. bisheng 后端（Windows，已开启 SSO）

一键启动（需已 `uv sync`、中间件已起）：

```powershell
powershell -ExecutionPolicy Bypass -File docker/local-dev/start-backend-sso.ps1
```

或手动：

```powershell
cd src/backend
# 须为「相对 bisheng 包目录」的文件名，勿写成 bisheng\config.yaml（会拼成双 bisheng 路径）
$env:config = "config.yaml"
$env:BISHENG_PRO = "true"
$env:BS_SSO_SYNC__GATEWAY_HMAC_SECRET = "bisheng-local-hmac-20260422"
.\.venv\Scripts\python.exe -m uvicorn bisheng.main:app --host 0.0.0.0 --port 7860 --workers 1 --no-access-log
```

Linux/macOS：`export config=config.yaml`（不要用 `bisheng/config.yaml`）。

## 6. Gateway → bisheng 组织 / 部门同步（可测）

bisheng 侧为 **F014**：`POST /api/v1/departments/sync` + 请求头 `X-Signature`（算法见 `bisheng/sso_sync/domain/services/hmac_auth.py`）。

### 一键拉起（中间件 + API + Celery + Gateway + 冒烟）

```powershell
powershell -ExecutionPolicy Bypass -File docker/local-dev/start-full-stack.ps1
```

### 方式 A：Gateway 代签推送（推荐）

- **企业微信拉树并推送（部门 + 已激活成员）**（需 `application.yml` / `application-local.yml` 里企业微信 `wxoauth` 为真实可用凭证）：  
  `GET http://127.0.0.1:8180/api/group/test`  
  Gateway 将部门树 + 成员打成一个请求，经 HMAC 调用 bisheng **`POST /api/v1/internal/sso/gateway-wecom-org-sync`**（内部先 `departments/sync` 再逐人 `login-sync`，**`org_sync_log` 只落一行**；企微「部门负责人」依赖 **`user/get` 返回的 `is_leader_in_dept`**，Gateway 已对每位激活成员补拉详情后再组 `department_admin_external_ids`，并始终下发该数组（可为空）以便 bisheng 对账 FGA）。
- **自定义 JSON**（与 bisheng `DepartmentsSyncRequest` 同结构）：  
  `POST http://127.0.0.1:8180/api/group/sso-departments-raw`  
  Body 示例：`{"upsert":[{"external_id":"d1","name":"研发","parent_external_id":null,"sort":0,"ts":1710000000}],"remove":[],"source_ts":1710000000}`

### 方式 B：本机脚本自签（不经过 Gateway 亦可）

```powershell
cd src/backend
.\.venv\Scripts\python.exe ..\..\scripts\dev\gateway_hmac_org_sync_smoke.py --base http://127.0.0.1:8180
.\.venv\Scripts\python.exe ..\..\scripts\dev\gateway_hmac_org_sync_smoke.py --base http://127.0.0.1:7860
```

管理端查看同步日志（需登录）：`GET /api/v1/org-sync/gateway-logs`（经 Gateway 代理为 `/api/v1/...`）。

**成员 / 日志**：`GET /api/group/test` 走合并接口；单点登录仍可用 `POST /api/v1/internal/sso/login-sync`（HMAC，每条单独写 `org_sync_log`）。
