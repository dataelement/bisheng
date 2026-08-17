# runtime-manager ↔ backend 接线契约（批 2 交付物，2026-08-17）

> 由 F054 批 2（`src/runtime-manager/`，commit `8e9afaf48`）产出并**已实现**。后续批次（backend 入口判定与内部授权端点、领域服务与 API、F055 发布管线、F053 CLI、114 部署）**按本文逐条接线**，与 design §4.2 冲突时以本文为准（本文是实现后的实际形状）。

## 1. 地址与鉴权

- 监听 `http://127.0.0.1:8091`（backend 配置项 `app_runtime.manager_base_url` 默认值即此）
- HMAC：签名串 `METHOD\nPATH\nraw_body`，请求头 `X-Signature`，小写 hex，恒时比较；**PATH 不含 query string**；空密钥 fail-closed
- ⚠️ backend 的 `orchestrator_client` 必须对**自己实际发出的字节**签名（不要让 httpx 重新序列化 json，否则签名对不上）
- 三方共用一把密钥：`RTM_HMAC_SECRET` == backend `app_runtime.manager_hmac_secret` == app-proxy 侧 manager secret
- `GET /healthz` 免签（systemd / smoke 用）

## 2. 已就绪端点

| 端点 | 返回 | 消费方 |
|---|---|---|
| `POST /v1/admission` | `{admitted, reason, message, stage, required_mb, required_cpu, snapshot{mem_available_mb, committed_mb, total_mb, cpu, committed_cpu, reserve_mb, overcommit_ratio}}` | F055 上线终检 / F054 重新启用 |
| `POST /v1/intents/build` | `{build_id, status}` | F055 预检 |
| `GET /v1/builds/{build_id}` | `{build_id, status, stage, message, tail[], image_ref}` | F055 预检轮询 |
| `POST /v1/intents/deploy` | `{instance_id, phase, generation}` | F054 上线动作 |
| `POST /v1/intents/stop` / `destroy` | `{phase}` / `{}` | F054 停运 / 删除 |
| `POST /v1/intents/probe` | `{ready, reason}`（入参 `app_id` 或 `{image_ref, env, port, health}` 二选一，都不给 → 400） | F055 预检 / 终检 |
| `GET /v1/apps/{app_id}/route` | `{upstream, version_id, generation}`；**404 = 无实例 / 已停运 → 直接渲染停用页，不要重试** | **app-proxy** |

**入参约定**：`tier{cpu: vCPU float, mem: MiB int}`；build 必带 **`code_url`（MinIO 预签 URL）** + `code_object_key`（溯源）+ `slug` + `version_no`；deploy 带 `env{}`、`health{path,interval,timeout,retries,start_period}`、`platform_api_base`、`base_path`（缺省 `/apps/{slug}`）。

## 3. 错误信封 → 161xx 映射

manager 的 body 恒为 `{"detail": {"code","message",...}}`，backend 按此映射：

| manager | backend 错误码 |
|---|---|
| `401 unauthorized` / `503 backend_unavailable` | **16121** |
| `400 unsupported_runtime`（带 `supported_runtimes[]`） | **16123** |
| `409 capacity_exhausted`（带 `reason` + `snapshot`） | **16125** |
| `409 probe_failed` | **16124** |
| `GET /v1/builds/{id}` 的 `status=failed`（带 `stage`/`message`/`tail`） | **16122** |
| `404 not_found` | 路由 / 实例不存在（app-proxy 直接出停用页） |

## 4. 环境变量

**与 backend settings 对照**：`RTM_DATA_ROOT` / `RTM_RESERVE_MB` / `RTM_OVERCOMMIT_RATIO` / `RTM_BUILD_RESERVE_MB` / `RTM_BUILD_INDEX_URL`。
**建议 backend 补一项**：`app_runtime.build_trusted_host`（对应 `RTM_BUILD_TRUSTED_HOST`，私有 PyPI 镜像走 http 时必需）。
**manager 独有**（backend 无需对应）：`RTM_HOST/PORT/SIGNATURE_HEADER/NETWORK/DOCKER_HOST/IMAGE_PREFIX/IMAGE_RETENTION/RETIRE_GRACE_SECONDS/RECONCILE_INTERVAL_SECONDS/PROBE_TIMEOUT_SECONDS/PROBE_INTERVAL_SECONDS/STOP_TIMEOUT_SECONDS/LOG_MAX_SIZE/LOG_MAX_FILE`。

## 5. 注入应用的环境变量（F053 `bisheng dev` 必须**同名**注入，否则本地线上不同构）

`BISHENG_APP_DB_URL`（`sqlite:////data/app.db`）· `BISHENG_APP_DB_PATH` · `BISHENG_APP_ID` · `BISHENG_APP_SLUG` · `BISHENG_APP_VERSION`（版本号）· `BISHENG_APP_VERSION_ID` · `BISHENG_PLATFORM_API_BASE` · `PORT` 与 `BISHENG_APP_PORT`（两者恒等）· `BISHENG_APP_BASE_PATH`（dev 期为空串）· `BISHENG_APP_HEALTH_PATH`。
平台保留 env 名**覆盖**调用方同名值。

## 6. 给 app-proxy 的不变量

**路由缓存 3s × manager 侧旧实例宽限 30s** —— 这个差值就是「版本切换不落 502」（AC-21）的**全部**理由。改任一个数必须同时改另一个，并重跑切换用例。

## 7. 114 部署增量（批 2 部分）

- 新 systemd 单元 `bisheng-runtime-manager.service`：`After=/Requires=docker.service`；`WorkingDirectory=<repo>/src/runtime-manager`；`ExecStart=<venv>/bin/uvicorn runtime_manager.main:app --host 127.0.0.1 --port 8091`；`EnvironmentFile` 至少给 `RTM_HMAC_SECRET` / `RTM_DATA_ROOT` / `RTM_BUILD_INDEX_URL`。加进 `bisheng.target` 的 `Wants=` 与 `deploy.sh` 的 `SERVICES=`
- **前置资源**：`docker network create bisheng-apps`（不存在则所有 deploy 失败）；`/opt/bisheng/app-data/{apps,state,builds}` 可写；`docker pull python:3.11-slim` 预拉（air-gap / 信创必需）
- 依赖（独立 venv，不动 backend）：`cd src/runtime-manager && uv sync`
- smoke 增量：`curl -s 127.0.0.1:8091/healthz` → `{"status":"ok"}`；带签名 `POST /v1/admission` 应返回 `admitted` 与 snapshot（顺带验密钥配对）

## 8. 尚未实现（留给后续批次）

`GET /v1/apps/{id}/status`、`GET /v1/apps/{id}/logs`、`GET /v1/runtime-status`（T030 / T031），以及 reconciler 的容器 label 恢复、启动全量对齐、孤儿回收（T028 / T029——在批 2 已落的 `desired_state.py` 之上补，**不要重写其数据结构与 `get_store(config)`**）。
