# runtime-manager ↔ backend 接线契约（批 2 交付物，2026-08-17）

> 由 F054 批 2（`src/runtime-manager/`，commit `8e9afaf48`）产出并**已实现**；批 4（T028–T031：reconciler + 三个只读端点）已并入本文，见 §2 表末三行与 §8。后续批次（backend 入口判定与内部授权端点、领域服务与 API、F055 发布管线、F053 CLI、114 部署）**按本文逐条接线**，与 design §4.2 冲突时以本文为准（本文是实现后的实际形状）。

## 1. 地址与鉴权

- 监听 `http://127.0.0.1:8091`（backend 配置项 `app_runtime.manager_base_url` 默认值即此）
- HMAC：签名串 `METHOD\nPATH\nraw_body`，请求头 `X-Signature`，小写 hex，恒时比较；**PATH 不含 query string**；空密钥 fail-closed
- ⚠️ backend 的 `orchestrator_client` 必须对**自己实际发出的字节**签名（不要让 httpx 重新序列化 json，否则签名对不上）
- 三方共用一把密钥：`RTM_HMAC_SECRET` == backend `app_runtime.manager_hmac_secret` == app-proxy 侧 manager secret
- `GET /healthz` 免签（systemd / smoke 用）

## 2. 已就绪端点

| 端点 | 返回 | 消费方 |
|---|---|---|
| `POST /v1/admission` | `{admitted, reason, message, stage, required_mb, required_cpu, snapshot{mem_available_mb, committed_mb, total_mb, cpu, committed_cpu, reserve_mb, overcommit_ratio}}` | F055 上线终检 / F054 重新上线 |
| `POST /v1/intents/build` | `{build_id, status}` | F055 预检 |
| `GET /v1/builds/{build_id}` | `{build_id, status, stage, message, tail[], image_ref}` | F055 预检轮询 |
| `POST /v1/intents/deploy` | `{instance_id, phase, generation}` | F054 上线动作 |
| `POST /v1/intents/stop` / `destroy` | `{phase}` / `{}` | F054 下线 / 删除 |
| `POST /v1/intents/probe` | `{ready, reason}`（入参 `app_id` 或 `{image_ref, env, port, health}` 二选一，都不给 → 400） | F055 预检 / 终检 |
| `GET /v1/apps/{app_id}/route` | `{upstream, version_id, generation}`；**404 = 无实例 / 已下线 → 直接渲染停用页，不要重试** | **app-proxy** |
| `GET /v1/apps/{app_id}/status` | `{instance_id, phase, health, current_version_id, started_at, restart_count, last_probe_at}`；`phase ∈ pending\|building\|starting\|running\|unhealthy\|stopped\|failed`；**404 = 无实例**（`detail.code=not_found`） | F054 详情页 / `app_instance` 对账 · **F052** MCP 应用状态工具 |
| `GET /v1/apps/{app_id}/logs?tail=&since=&keyword=` | `{lines: [...]}`（无日志即 `[]`） | 详情页运行日志 tab · **F053** CLI `logs` · **F052** MCP 日志工具 |
| `GET /v1/runtime/status` | `{backend_available, supported_runtimes[], capacity{...}, preflight[{name, ok, detail}]}` | 超管运行环境状态（AC-23）· F055 预检前置自检 |
| `GET /v1/apps/{app_id}/storage/objects?prefix=&cursor=&limit=` | `{objects: [{key, size, content_type, etag, last_modified}], next_cursor}`（`key` 是应用内相对路径，永不含 bucket / 前缀） | **托管应用自身**（F057 SDK storage，Bearer）· F052 MCP（HMAC） |
| `PUT /v1/apps/{app_id}/storage/objects/{key}` | 裸字节 body，`Content-Type` 即对象类型；返 `{key, size, content_type, etag, last_modified}`；超单文件上限 → **413 `payload_too_large`**（先看 `Content-Length` 再看实收字节，一个字节都不落） | 同上 |
| `GET /v1/apps/{app_id}/storage/objects/{key}` | 流式字节 + `Content-Type` / `Content-Length` / `ETag`；不存在 → 404 `not_found` | 同上 |
| `GET /v1/apps/{app_id}/storage/meta/{key}` | 元信息 JSON（同 `objects` 一项）；不存在 → 404 | 同上 |
| `DELETE /v1/apps/{app_id}/storage/objects/{key}` | `{}`；**不存在 → 404**（不装作成功，F057 AC-25） | 同上 |

**入参约定**：`tier{cpu: vCPU float, mem: MiB int}`；build 必带 **`code_url`（MinIO 预签 URL）** + `code_object_key`（溯源）+ `slug` + `version_no`；deploy 带 `env{}`、`health{path,interval,timeout,retries,start_period}`、`platform_api_base`、`base_path`（缺省 `/apps/{slug}`）。

**只读端点细则（批 4）**：

- `status`：`restart_count` = **daemon 重启数 + manager 重建数之和**（重建后新容器的 `RestartCount` 归零，只取 daemon 的会让长期不健康的应用显示"从未重启"）；`instance_id` 与 `phase` 之外无形态字段（INV-33）。**路径名是 `/v1/runtime/status`**（本文旧版 §8 曾误写 `/v1/runtime-status`，以本行为准）。
- `logs`：`tail`（1–5000，默认 500）与 `since`（**epoch 秒 或 `30m`/`2h`/`7d` 相对窗口**，不可解析 → 400 `invalid_request`）下发给 daemon；`keyword`（大小写不敏感子串）在 manager 内过滤——**所以带 keyword 时返回行数可能 < tail，这是设计不是 bug**。保留期 = docker 轮转窗口（10m × 3 / 应用），产品口径「最近的运行日志」。脱敏**只**对平台注入的敏感 env 值（名字含 `SECRET|TOKEN|PASSWORD|CREDENTIAL|SIGNATURE|API_KEY|PRIVATE_KEY`、长度 ≥6）做字面量替换为 `***`；**不做通用脱敏**（D14，密钥靠 F055 发布期扫描兜）——backend 不要在自己那层再加正则，会把应用正常输出打烂。
- `runtime/status`：**恒 200**，dockerd 宕机时 `backend_available=false` 而不是抛错（这正是它最有用的一句话）。`capacity` = admission 同源快照 + `instances`（在跑实例数）+ `readable`（`/proc/meminfo` 可读否）+ `reason`。`preflight` 七项：`orchestration_backend` / `application_network` / `data_root_writable` / `host_data_root_mapping` / `runtime_templates` / `base_images` / `attachment_storage`（T084，见下方细则），`detail` 直接写修法（缺网络就给 `docker network create bisheng-apps`）。**manager 只读不建网络**——自动建会把"新机器每次发布都失败"的唯一线索藏掉。
- **后端不可用 ≠ 实例不存在**：`status` / `logs` 在 dockerd 不可达时返 **503 `backend_unavailable`**（→ 16121），实例真的没有才 404。backend 与前端不要把两者合并，否则 dockerd 一重启详情页就显示"已删除"。

**附件存储句柄细则（T084 / T085，2026-09-16）**：

- **两把凭据**：`/v1/apps/{app_id}/storage/**` 是本进程唯一有两类调用方的路由。`Authorization: Bearer <BISHENG_APP_STORAGE_TOKEN>` 是应用自己（token 在 deploy 时铸造、写在期望态记录的 env 里、**绑定该 `app_id`**——A 的 token 打 B 的 URL 是 401 不是"帮你收窄"；destroy 后记录消失 token 即失效）；没有 Bearer 头则走与其它 `/v1` 完全一样的 HMAC（backend / F052 用）。
- **key 是应用内相对路径**：manager 侧恒加前缀 `apps/{app_id}/attachments/`；`..` / 绝对路径 / `//` / `./` / 反斜杠 / 控制字符 / 以 `apps/` 开头（哪怕是自己的）/ 超 1024 字节 → **400 `invalid_object_key`**，**拒绝而不是改写**。`prefix` 与 `cursor` 按同一规则校验。
- **bucket 恒为 `bisheng-apps`**（`RTM_STORAGE_BUCKET`，缺省即此），首次使用不存在就建、**从不写桶策略**；配成平台公共桶 `bisheng` 直接 503 拒绝工作（坑 20）。**不计租户存储配额**——本进程没有平台客户端，无处可计。
- **单文件上限** `RTM_STORAGE_MAX_FILE_MB`（缺省 20），同值注入为 `BISHENG_APP_STORAGE_MAX_FILE_MB` 让 SDK 发送前就能拒。
- **未配 MinIO**（`RTM_MINIO_*` 缺）：句柄照常注入，所有调用答 **503 `storage_unavailable`**；`runtime/status` 的 preflight 新增一项 **`attachment_storage`** 指出缺什么。
- **可达性缺口的解法（systemd 形态）**：本进程只监听 `127.0.0.1:8091` 时应用容器从 bridge 上够不到它。注入的 `BISHENG_APP_STORAGE_ENDPOINT` 前缀取 `RTM_APP_FACING_BASE_URL`，缺省从 `RTM_HOST:RTM_PORT` 推导；systemd 形态须把 `RTM_HOST` 与 `RTM_APP_FACING_BASE_URL` 指到 `bisheng-apps` 网桥的网关地址（`docker network inspect bisheng-apps -f '{{(index .IPAM.Config 0).Gateway}}'`，形如 `172.18.0.1`，宿主本地、外网不可达），compose 形态用服务名 `http://runtime-manager:8091`。`RTM_HOST` 仍是回环而没给 `RTM_APP_FACING_BASE_URL` → preflight `attachment_storage` 报 `ok=false` 并写明修法。
- **删除**：`destroy(purge_volume=true)` 顺带清空该应用前缀下全部对象（AC-43）；存储当时不可达只告警不阻断（删除已经发生，平台会重试 destroy）。
- **日志脱敏**：`BISHENG_APP_STORAGE_TOKEN` 命中 `logs` 端点的注入敏感名规则，值一律 `***`。
- backend 错误码 **16170–16174** 已在 `app_factory.py` 预留（storage_unavailable / invalid_object_key / payload_too_large / not_found / unauthorized 的映射），**首个 backend 调用方出现的那一波再落码 + 三语文案**；目前唯一消费者是应用自己（Bearer），不经 backend。

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
**manager 独有**（backend 无需对应）：`RTM_HOST/PORT/SIGNATURE_HEADER/NETWORK/DOCKER_HOST/IMAGE_PREFIX/IMAGE_RETENTION/RETIRE_GRACE_SECONDS/RECONCILE_INTERVAL_SECONDS/**RECONCILE_ENABLED**/PROBE_TIMEOUT_SECONDS/PROBE_INTERVAL_SECONDS/STOP_TIMEOUT_SECONDS/LOG_MAX_SIZE/LOG_MAX_FILE`。`RTM_RECONCILE_ENABLED` 生产**恒 true**（它就是 AC-20 的自愈机制），只有单测把它关掉。
**附件存储（T084，manager 独有）**：`RTM_MINIO_ENDPOINT` / `RTM_MINIO_ACCESS_KEY` / `RTM_MINIO_SECRET_KEY` / `RTM_MINIO_SECURE`（缺省 false）/ `RTM_STORAGE_BUCKET`（缺省 `bisheng-apps`，**不得**是 `bisheng`）/ `RTM_STORAGE_MAX_FILE_MB`（缺省 20）/ `RTM_APP_FACING_BASE_URL`（应用容器访问本进程的地址，见 §2 细则）。MinIO 三项可与 backend 的 `minio.*` 取同值，但**这是 manager 自己的一份配置**，backend 不代管。

## 5. 注入应用的环境变量（F053 `bisheng dev` 必须**同名**注入，否则本地线上不同构）

`BISHENG_APP_DB_URL`（`sqlite:////data/app.db`）· `BISHENG_APP_DB_PATH` · `BISHENG_APP_ID` · `BISHENG_APP_SLUG` · `BISHENG_APP_VERSION`（版本号）· `BISHENG_APP_VERSION_ID` · `BISHENG_PLATFORM_API_BASE` · `PORT` 与 `BISHENG_APP_PORT`（两者恒等）· `BISHENG_APP_BASE_PATH`（dev 期为空串）· `BISHENG_APP_HEALTH_PATH`。
**附件句柄（T085，2026-09-16 起）**：`BISHENG_APP_STORAGE_ENDPOINT`（`{RTM_APP_FACING_BASE_URL}/v1/apps/{app_id}/storage`）· `BISHENG_APP_STORAGE_TOKEN`（每应用一把、整个生命周期不变、destroy 后才轮换；deploy 新版本沿用旧 token，30s 宽限期内新旧实例同一凭据）· `BISHENG_APP_STORAGE_MAX_FILE_MB`。**不注入** bucket / 前缀 / MinIO 凭据——收窄在 manager 侧做，应用只见相对路径（F057 AC-21）。名字的 backend 侧副本在 `app_runtime/domain/constants.py::APP_STORAGE_ENV_NAMES`。F053 `dev` 期同名注入的是**本地附件目录句柄**（F053 AC-27），SDK 按有无 `ENDPOINT` 分辨两种形态。
平台保留 env 名**覆盖**调用方同名值（含上述三个）。

## 6. 给 app-proxy 的不变量

**路由缓存 3s × manager 侧旧实例宽限 30s** —— 这个差值就是「版本切换不落 502」（AC-21）的**全部**理由。改任一个数必须同时改另一个，并重跑切换用例。

**`generation` 还有第二个来源（批 4 新增）**：reconciler 重建不健康实例时也 `generation+1`——新执行体拿到的是新 bridge IP，`generation` 正是 app-proxy 的缓存失效信号。app-proxy 不要假设 `generation` 变化 ⇒ 版本变化，要按 `upstream` 变化处理（`version_id` 可能不变）。

## 7. 114 部署增量（批 2 部分）

- 新 systemd 单元 `bisheng-runtime-manager.service`：`After=/Requires=docker.service`；`WorkingDirectory=<repo>/src/runtime-manager`；`ExecStart=<venv>/bin/uvicorn runtime_manager.main:app --host 127.0.0.1 --port 8091`；`EnvironmentFile` 至少给 `RTM_HMAC_SECRET` / `RTM_DATA_ROOT` / `RTM_BUILD_INDEX_URL`。加进 `bisheng.target` 的 `Wants=` 与 `deploy.sh` 的 `SERVICES=`
- **前置资源**：`docker network create bisheng-apps`（不存在则所有 deploy 失败）；`/opt/bisheng/app-data/{apps,state,builds}` 可写；`docker pull python:3.11-slim` 预拉（air-gap / 信创必需）
- 依赖（独立 venv，不动 backend）：`cd src/runtime-manager && uv sync`
- smoke 增量：`curl -s 127.0.0.1:8091/healthz` → `{"status":"ok"}`；带签名 `POST /v1/admission` 应返回 `admitted` 与 snapshot（顺带验密钥配对）
- **批 4 增量**：进程启动即拉起 reconcile 线程（15s 一轮，启动先做一次全量对齐）。部署自检改用带签名的 `GET /v1/runtime/status`——它一次性回答"编排后端通不通 / 网络建了没 / data_root 可写否 / 模板与基础镜像在不在"，比逐条 `docker` 命令核对可靠。**新机器只要 `preflight` 有 `ok=false`，就不要开始上线应用**

## 8. 自愈与恢复语义（批 4，T028–T031 已实现）

reconciler 每 **15s** 一轮，`RTM_RECONCILE_ENABLED` 关不掉的产品语义如下，backend / app-proxy 侧的判断要与之对齐：

| 实际态 | 动作 | 为什么不是别的做法 |
|---|---|---|
| 期望 running、执行体**不存在** | 按期望态重建并探活（卷不动） | — |
| 期望 running、执行体**已退出** | 只 `start`，**不重建** | 进程退出归 docker `unless-stopped` 的指数退避；重建会丢掉退避，还让崩溃循环每 15s 换一个新实例 id 藏起来 |
| 期望 running、**存活但 unhealthy 连续 2 轮** | stop → rm → run（同名同卷）、`generation+1`、再探活 | **docker 单机 healthcheck 与 restart policy 无联动**（坑 17），这一类故障没人管；这是薄 reconciler 存在的核心理由 |
| 期望 stopped、执行体在跑 | stop | 下线是显式动作，reconciler 不与运维打架 |
| 带 `bisheng.managed=true` 标签、**无任何期望态声明** | 回收（stop + rm，**不删卷**） | — |

**不误杀边界（backend 不必处理，但排障时要知道）**：只有 manager 自己打了 `bisheng.managed=true` 的容器才可能被回收；同机其它容器（onlyoffice / rabbitmq…）、探活临时实例（`bisheng.managed=probe`）、以及处于 30s 宽限期内的旧版本实例一律不动。

**恢复口径（AC-22 / AC-50）**：容器存活依赖 dockerd 而非 manager；manager 重启只影响 reconcile 时效。启动第一件事是**先从容器 label 恢复期望态、再做孤儿回收**（顺序反了 = 状态文件一丢就清空全站）。状态文件 `{data_root}/state/desired-state.json` 是缓存，**容器 label 才是灾备真相**；label 恢复时"存在但没在跑"判为**已下线**（`unless-stopped` 下 dockerd 会把非显式下线的拉回来）。

**5 分钟自愈预算（AC-20）**：healthcheck 判定 30s + reconcile 感知 2×15s + 重建探活 ≤90s = **≤150s**；`recovery_budget_seconds(config)` 用配置算出该值并被用例断言 ≤300s，所以调大 `RTM_RECONCILE_INTERVAL_SECONDS` / `RTM_PROBE_TIMEOUT_SECONDS` 会先让测试红，而不是先让客户超时。

## 9. 尚未实现（留给后续批次）

`GET /v1/apps/{app_id}/db/*`（数据 tab / MCP 数据工具，D10，后置 Wave）；出站白名单双层与 docker-socket-proxy（D12 / D2-B，Wave 4，后者**零代码改动**——只改 `RTM_DOCKER_HOST`）。出站白名单落地时须放行 `BISHENG_APP_STORAGE_ENDPOINT` 所指的 manager 地址，否则附件句柄随白名单一起断。
