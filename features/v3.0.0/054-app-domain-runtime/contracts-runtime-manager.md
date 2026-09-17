# runtime-manager ↔ backend 接线契约（批 2 交付物，2026-08-17）

> 由 F054 批 2（`src/runtime-manager/`，commit `8e9afaf48`）产出并**已实现**；批 4（T028–T031：reconciler + 三个只读端点）已并入本文，见 §2 表末三行与 §8。后续批次（backend 入口判定与内部授权端点、领域服务与 API、F055 发布管线、F053 CLI、114 部署）**按本文逐条接线**，与 design §4.2 冲突时以本文为准（本文是实现后的实际形状）。

## 1. 地址与鉴权

- 监听 `http://127.0.0.1:8091`（backend 配置项 `app_runtime.manager_base_url` 默认值即此）
- HMAC：签名串 `METHOD\nPATH\nraw_body`，请求头 `X-Signature`，小写 hex，恒时比较；**PATH 不含 query string**，且是**百分号解码后**的路径（manager 侧取 ASGI `scope["path"]`，不取 `request.url.path`——后者会把段内的 `?` / `#` 当分隔符截断）；含保留字符的路径段（数据面行键 `a?b`、`100%`）由 backend `quote(key, safe="")` 上线、签名仍按解码形；空密钥 fail-closed
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
| `POST /v1/intents/preview` | `{instance_id, upstream, phase}`（入参 `{session_id, app_id, slug, version_id, version_no, image_ref, tier, port, env, health, platform_api_base, base_path, expires_at, timeout}` —— 与 `deploy` 同一组，因为容器拿的是 §5 的**整套**环境；`base_path` 是 `/apps/preview/{session}`，**不注入附件句柄**）；容量不足 → `capacity_exhausted`、探活不过 → `probe_failed`（两种都已把容器拆掉） | **F055 审批期预览拉起（T053）** |
| `POST /v1/intents/preview/stop` | `{reclaimed: bool}`，**幂等**——已回收的会话答 `{reclaimed:false}` 而不是 404 | F055 回收（终态 / 手动 / 超时三条腿都走它） |
| `GET /v1/previews/{session_id}/route` | `{upstream, version_id, generation}`（`generation` 恒为 0，预览不做原地切换）；**404 = 已回收 / 从未拉起 → 渲染「不存在」，不要重试** | **app-proxy `/apps/preview/{session}`** |
| `GET /v1/apps/{app_id}/status` | `{instance_id, phase, health, current_version_id, started_at, restart_count, last_probe_at}`；`phase ∈ pending\|building\|starting\|running\|unhealthy\|stopped\|failed`；**404 = 无实例**（`detail.code=not_found`） | F054 详情页 / `app_instance` 对账 · **F052** MCP 应用状态工具 |
| `GET /v1/apps/{app_id}/logs?tail=&since=&keyword=` | `{lines: [...]}`（无日志即 `[]`） | 详情页运行日志 tab · **F053** CLI `logs` · **F052** MCP 日志工具 |
| `GET /v1/runtime/status` | `{backend_available, supported_runtimes[], capacity{...}, preflight[{name, ok, detail}]}` | 超管运行环境状态（AC-23）· F055 预检前置自检 |
| `GET /v1/apps/{app_id}/storage/objects?prefix=&cursor=&limit=` | `{objects: [{key, size, content_type, etag, last_modified}], next_cursor}`（`key` 是应用内相对路径，永不含 bucket / 前缀） | **托管应用自身**（F057 SDK storage，Bearer）· F052 MCP（HMAC） |
| `PUT /v1/apps/{app_id}/storage/objects/{key}` | 裸字节 body，`Content-Type` 即对象类型；返 `{key, size, content_type, etag, last_modified}`；超单文件上限 → **413 `payload_too_large`**（先看 `Content-Length` 再看实收字节，一个字节都不落） | 同上 |
| `GET /v1/apps/{app_id}/storage/objects/{key}` | 流式字节 + `Content-Type` / `Content-Length` / `ETag`；不存在 → 404 `not_found` | 同上 |
| `GET /v1/apps/{app_id}/storage/meta/{key}` | 元信息 JSON（同 `objects` 一项）；不存在 → 404 | 同上 |
| `DELETE /v1/apps/{app_id}/storage/objects/{key}` | `{}`；**不存在 → 404**（不装作成功，F057 AC-25） | 同上 |
| `GET /v1/apps/{app_id}/db/tables` | `{tables: [{name, column_count}]}`（只列用户表，`sqlite_*` 不出；库文件不存在 → **404 `db_not_found`**） | **backend `AppDataService`**（数据 tab · F052 MCP 数据工具，**均经它、不得直连**） |
| `GET /v1/apps/{app_id}/db/tables/{table}/schema` | `{table, columns: [{name, type, notnull, default, pk, editable}], key: {column, kind: primary_key\|rowid}, editable}` | 同上 |
| `GET /v1/apps/{app_id}/db/tables/{table}/rows?page=&size=&order=` | `{rows: [{key, values{}}], total, page, size, order}`；`size` 1–200（默认 50）；`order` = `col` / `-col`，**行键恒为次级排序键**（分页不重不漏）；BLOB 值以 `<blob N bytes>` 占位 | 同上 |
| `PATCH /v1/apps/{app_id}/db/tables/{table}/rows/{key}` | 入参 `{values: {col: scalar}}` → `{table, key, before{}, after{}}`；**只改一行**（`BEGIN IMMEDIATE` 短事务，受影响行数 ≠ 1 回滚）；行键列 / BLOB 列 / 非标量值 / 未知列 → 400 `data_invalid` | 同上（backend 用 `before/after` 写 `app.data_row_edit` 审计） |
| `GET /v1/apps/{app_id}/db/export?table=` | `text/csv` 文件（`Content-Disposition: attachment; filename="{table}.csv"`），临时文件发送后即删 | 同上 |

**数据面细则（T086）**：**无 DDL、无任何承载 SQL 的入参**——表名 / 列名 / 排序列一律先对 `sqlite_master` / `PRAGMA table_info` 白名单核对再引号拼接，`CREATE / ALTER / DROP / PRAGMA` 不是"被拒绝"而是"说不出口"（结构演进归 F055）。读路径 `mode=ro`、写路径 `mode=rw`（**永不 `rwc`**——应用自己建库，manager 不替它造空库）；每次调用独立连接 + `busy_timeout=3000ms`，调用结束即关，不持长事务（WAL 单写者，长事务会卡住应用自己的写）。写锁等待超时 → **409 `data_busy`**（可重试）；表不存在 → 404 `table_not_found`；行不存在 / 受影响行数 ≠ 1 → 404 `row_not_found`。行键：单列主键用该列，否则用 `rowid`；`WITHOUT ROWID` 复合主键表 `editable=false`（可读可导、不可编辑）。

**入参约定**：`tier{cpu: vCPU float, mem: MiB int}`；build 必带 **`code_url`（MinIO 预签 URL）** + `code_object_key`（溯源）+ `slug` + `version_no`；deploy 带 `env{}`、`health{path,interval,timeout,retries,start_period}`、`platform_api_base`、`base_path`（缺省 `/apps/{slug}`）。

**只读端点细则（批 4）**：

- `status`：`restart_count` = **daemon 重启数 + manager 重建数之和**（重建后新容器的 `RestartCount` 归零，只取 daemon 的会让长期不健康的应用显示"从未重启"）；`instance_id` 与 `phase` 之外无形态字段（INV-33）。**路径名是 `/v1/runtime/status`**（本文旧版 §8 曾误写 `/v1/runtime-status`，以本行为准）。
- `logs`：`tail`（1–5000，默认 500）与 `since`（**epoch 秒 或 `30m`/`2h`/`7d` 相对窗口**，不可解析 → 400 `invalid_request`）下发给 daemon；`keyword`（大小写不敏感子串）在 manager 内过滤——**所以带 keyword 时返回行数可能 < tail，这是设计不是 bug**。保留期 = docker 轮转窗口（10m × 3 / 应用），产品口径「最近的运行日志」。脱敏**只**对平台注入的敏感 env 值（名字含 `SECRET|TOKEN|PASSWORD|CREDENTIAL|SIGNATURE|API_KEY|PRIVATE_KEY`、长度 ≥6）做字面量替换为 `***`；**不做通用脱敏**（D14，密钥靠 F055 发布期扫描兜）——backend 不要在自己那层再加正则，会把应用正常输出打烂。
- `runtime/status`：**恒 200**，dockerd 宕机时 `backend_available=false` 而不是抛错（这正是它最有用的一句话）。`capacity` = admission 同源快照 + `instances`（在跑实例数）+ `readable`（`/proc/meminfo` 可读否）+ `reason`。`preflight` 十项：`orchestration_backend` / `application_network` / `data_root_writable` / `host_data_root_mapping` / `runtime_templates` / `base_images` / `attachment_storage`（T084，见下方细则）/ `egress_whitelist` / `application_network_internal` / `egress_firewall_fallback`（T077，末三项见 §9），`detail` 直接写修法（缺网络就给 `docker network create bisheng-apps`）。**manager 只读不建网络**——自动建会把"新机器每次发布都失败"的唯一线索藏掉。
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
| `404 db_not_found` / `404 table_not_found` / `404 row_not_found` | **16163** / **16164** / **16165**（数据面，T087） |
| `400 data_invalid` / `409 data_busy` | **16166** / **16167**（数据面，T087） |

## 4. 环境变量

**与 backend settings 对照**：`RTM_DATA_ROOT` / `RTM_RESERVE_MB` / `RTM_OVERCOMMIT_RATIO` / `RTM_BUILD_RESERVE_MB` / `RTM_BUILD_INDEX_URL`。
**建议 backend 补一项**：`app_runtime.build_trusted_host`（对应 `RTM_BUILD_TRUSTED_HOST`，私有 PyPI 镜像走 http 时必需）。
**manager 独有**（backend 无需对应）：`RTM_HOST/PORT/SIGNATURE_HEADER/NETWORK/DOCKER_HOST/IMAGE_PREFIX/IMAGE_RETENTION/RETIRE_GRACE_SECONDS/RECONCILE_INTERVAL_SECONDS/**RECONCILE_ENABLED**/PROBE_TIMEOUT_SECONDS/PROBE_INTERVAL_SECONDS/STOP_TIMEOUT_SECONDS/LOG_MAX_SIZE/LOG_MAX_FILE`。`RTM_RECONCILE_ENABLED` 生产**恒 true**（它就是 AC-20 的自愈机制），只有单测把它关掉。
**出站白名单（T077，manager 独有，2026-09-16 起）**：`RTM_EGRESS_PROXY`（**应用容器视角**的 `host:port`，空 = 整层未部署——没有「开关开了但代理不在」这种能掐死全部出站的组合）/ `RTM_EGRESS_LISTEN`（代理进程自己绑的地址，缺省 `0.0.0.0:3128`；systemd 形态要绑 `bisheng-apps` 网关而不是回环）/ `RTM_EGRESS_ALLOW` / `RTM_EGRESS_BUILD_ALLOW`（逗号分隔的额外放行项，`host` 或 `host:port`，前导点 = 整个域）/ `RTM_PLATFORM_BASE_URL`（**构建期**唯一放行的平台分发端点，装 bisheng-sdk 用；运行期的平台地址来自 deploy 意图的 `platform_api_base`）/ `RTM_BUILD_NETWORK`（构建期专用 `--internal` 网）/ `RTM_APPS_SUBNET` + `RTM_FIREWALL_BACKEND`（L3 兜底；后者留空则探测，探到 nftables 直接判红——坑 22）。
**编排访问面（T078）**：`RTM_DOCKER_HOST=tcp://docker-socket-proxy:2375` 把 D2-A 换成 D2-B，**manager 零代码改动**。端点白名单由 `runtime_manager.docker_backend.SOCKET_PROXY_PERMISSIONS` 唯一定义，`socket_proxy_env()` 产出代理容器的整份环境（每个开关都显式写出，含 0），`tests/test_socket_proxy.py` 与 compose 逐字比对。

**附件存储（T084，manager 独有）**：`RTM_MINIO_ENDPOINT` / `RTM_MINIO_ACCESS_KEY` / `RTM_MINIO_SECRET_KEY` / `RTM_MINIO_SECURE`（缺省 false）/ `RTM_STORAGE_BUCKET`（缺省 `bisheng-apps`，**不得**是 `bisheng`）/ `RTM_STORAGE_MAX_FILE_MB`（缺省 20）/ `RTM_APP_FACING_BASE_URL`（应用容器访问本进程的地址，见 §2 细则）。MinIO 三项可与 backend 的 `minio.*` 取同值，但**这是 manager 自己的一份配置**，backend 不代管。

## 5. 注入应用的环境变量（F053 `bisheng dev` 必须**同名**注入，否则本地线上不同构）

`BISHENG_APP_DB_URL`（`sqlite:////data/app.db`）· `BISHENG_APP_DB_PATH` · `BISHENG_APP_ID` · `BISHENG_APP_SLUG` · `BISHENG_APP_VERSION`（版本号）· `BISHENG_APP_VERSION_ID` · `BISHENG_PLATFORM_API_BASE` · `PORT` 与 `BISHENG_APP_PORT`（两者恒等）· `BISHENG_APP_BASE_PATH`（dev 期为空串）· `BISHENG_APP_HEALTH_PATH`。
**附件句柄（T085，2026-09-16 起）**：`BISHENG_APP_STORAGE_ENDPOINT`（`{RTM_APP_FACING_BASE_URL}/v1/apps/{app_id}/storage`）· `BISHENG_APP_STORAGE_TOKEN`（每应用一把、整个生命周期不变、destroy 后才轮换；deploy 新版本沿用旧 token，30s 宽限期内新旧实例同一凭据）· `BISHENG_APP_STORAGE_MAX_FILE_MB`。**不注入** bucket / 前缀 / MinIO 凭据——收窄在 manager 侧做，应用只见相对路径（F057 AC-21）。名字的 backend 侧副本在 `app_runtime/domain/constants.py::APP_STORAGE_ENV_NAMES`。F053 `dev` 期同名注入的是**本地附件目录句柄**（F053 AC-27），SDK 按有无 `ENDPOINT` 分辨两种形态。
**模型协议直连面（F051，2026-09-16 起）**：`OPENAI_BASE_URL`（= `{浏览器可见 origin}/api/v2/model/v1`，由 backend 的 `open_api/api/public_base_url.py::model_gateway_base_url` 唯一产出，不因租户或密钥而异）· `OPENAI_API_KEY`（= 该应用的运行期凭据明文，与 `BISHENG_APP_TOKEN` 同值——官方 `openai` 客户端零配置直读的就是这两个名字）· `BISHENG_MODEL_BASE_URL`（= `OPENAI_BASE_URL`，给不读 OpenAI 惯例变量的引擎与技能包文案用的平台保留名）。三名的定义方是 F051 design D2；`dev` 期由 F053 同名注入，故本地与线上代码零差异。
**出站代理（T077，2026-09-16 起，仅在 `RTM_EGRESS_PROXY` 非空时注入）**：`HTTP_PROXY` / `HTTPS_PROXY`（= `http://{principal}:{token}@{RTM_EGRESS_PROXY}`）· `NO_PROXY`（本网内可直连的地址：本进程的 `RTM_APP_FACING_BASE_URL` 主机 + 回环）· 三者各带一份小写孪生（`curl` 只读小写）· `BISHENG_APP_EGRESS_TOKEN`（凭据本身，名字取成 `*_TOKEN` 是为了让 `readonly._redactions` 按名命中，从而把它在日志里的每一处出现——包括 `HTTP_PROXY` 里的那份——一起抹掉）。`principal` 是 `app_id`，**预览实例是 `bisheng-preview-{session}`**，绝不共用应用的那把。**这四个名字属平台保留，覆盖应用自带的同名值**：能靠自带 `HTTP_PROXY` 改写出口的白名单等于没有白名单。
平台保留 env 名**覆盖**调用方同名值（含上述三个）。

**deploy / preview 意图新增字段 `egress_domains`（T077）**：来自版本 manifest 的 `egress.domains` 原样透传（backend 侧唯一产出点 `app_publish/domain/schemas/app_manifest.py::egress_domains_of`）。平台自身的地址**不在这个列表里**——它们由 manager 按自己的配置补齐，所以应用既不能靠声明拿到平台，也不会因为没声明而丢掉平台。字段同时落成容器标签 `bisheng.egress.domains`，状态文件丢了也能从标签恢复（恢复出一个更窄的白名单 = 应用突然访问不了自家 API，且哪儿都没写为什么）。

## 6. 给 app-proxy 的不变量

**预览实例按 `session_id` 定址，不进期望态**（F055 AC-26）：容器名 `bisheng-preview-{session}`、标签 `bisheng.managed=preview`，因此 reconciler（只看 `bisheng.managed=true`）既不收养也不回收它，`store.committed()` 与 `capacity.instances` 都不计它——这就是「不占应用运行实例名额」的落点。`/data` 是 tmpfs 而非应用卷（AC-29：试用数据带不进生产），`RestartPolicy=no`（平台回收后不得自己复活）。容量仍然照判：内存是真的花掉的，只是名额不计。
**环境变量给的是 §5 整套**，只差两处，两处都是 AC 在说话：`BISHENG_APP_BASE_PATH` 为 `/apps/preview/{session}`；**附件三名一个都不注入**（应用自己的 storage bearer 交给临时实例，试用上传就会落进生产附件前缀，与数据库同一条红线）。给半套环境的预览不是「试用这个版本」——应用拿不到 `BISHENG_APP_DB_URL` 直接启动失败，审批人看到的是「这个版本是坏的」。

**路由缓存 3s × manager 侧旧实例宽限 30s** —— 这个差值就是「版本切换不落 502」（AC-21）的**全部**理由。改任一个数必须同时改另一个，并重跑切换用例。

**`generation` 还有第二个来源（批 4 新增）**：reconciler 重建不健康实例时也 `generation+1`——新执行体拿到的是新 bridge IP，`generation` 正是 app-proxy 的缓存失效信号。app-proxy 不要假设 `generation` 变化 ⇒ 版本变化，要按 `upstream` 变化处理（`version_id` 可能不变）。

## 7. 114 部署增量（批 2 部分）

- 新 systemd 单元 `bisheng-runtime-manager.service`：`After=/Requires=docker.service`；`WorkingDirectory=<repo>/src/runtime-manager`；`ExecStart=<venv>/bin/uvicorn runtime_manager.main:app --host 127.0.0.1 --port 8091`；`EnvironmentFile` 至少给 `RTM_HMAC_SECRET` / `RTM_DATA_ROOT` / `RTM_BUILD_INDEX_URL`（T092 起内网 npm 源另给 `RTM_BUILD_NPM_REGISTRY`）。加进 `bisheng.target` 的 `Wants=` 与 `deploy.sh` 的 `SERVICES=`
- **前置资源**：`docker network create bisheng-apps`（不存在则所有 deploy 失败）；`/opt/bisheng/app-data/{apps,state,builds}` 可写；基础镜像预拉（air-gap / 信创必需）：`docker pull python:3.11-slim node:20-slim nginx:1.27-alpine`——三个运行时模板各一个（T092 起），以 `GET /v1/runtime/status` 的 `base_images` 检查项为准
- 依赖（独立 venv，不动 backend）：`cd src/runtime-manager && uv sync`
- smoke 增量：`curl -s 127.0.0.1:8091/healthz` → `{"status":"ok"}`；带签名 `POST /v1/admission` 应返回 `admitted` 与 snapshot（顺带验密钥配对）
- **批 4 增量**：进程启动即拉起 reconcile 线程（15s 一轮，启动先做一次全量对齐）。部署自检改用带签名的 `GET /v1/runtime/status`——它一次性回答"编排后端通不通 / 网络建了没 / data_root 可写否 / 模板与基础镜像在不在"，比逐条 `docker` 命令核对可靠。**新机器只要 `preflight` 有 `ok=false`，就不要开始上线应用**
- **Wave 4 增量（T077 / T078）**：
  - 建网改成 `docker network create --internal bisheng-apps` 与 `docker network create --internal bisheng-build`。**已存在的网不会被 `create` 改属性**：先停掉全部托管应用 → `docker network rm` → 按上面重建，`preflight` 的 `application_network_internal` 就是用来发现「看着装好了其实没改」的。
  - 新 systemd 单元 `bisheng-egress-proxy.service`（模板见本目录 `deploy/`）：跑 runtime-manager 同一个包的第二个入口点，**绑 `bisheng-apps` 网关而非回环**（容器里的 127.0.0.1 是容器自己），与 manager 单元共用 `RTM_DATA_ROOT`。同样进 `bisheng.target` 与 `deploy.sh` 的 `SERVICES=`。
  - D2-B：起一个 `tecnativa/docker-socket-proxy`（**只绑 127.0.0.1:2375**），环境照 `python -c "from runtime_manager.docker_backend import socket_proxy_env; print(socket_proxy_env())"` 输出逐项写；manager 单元加 `RTM_DOCKER_HOST=tcp://127.0.0.1:2375` 并可以退出 docker 组。
  - L3 兜底：`RTM_APPS_SUBNET` 取自 `docker network inspect bisheng-apps -f '{{(index .IPAM.Config 0).Subnet}}'`，规则用 `python -m runtime_manager.egress firewall --print` 先看、`--apply` 再下发（先删后插，可重复执行）。Docker 29 的 nftables 后端没有 `DOCKER-USER` 链，`--print-nft` 出的是对应的 nft ruleset（坑 22）。

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


**`GET /v1/apps/{app_id}/route` 的 `409 deploying` 信封（「发布中」窗口，T083，2026-09-16）**：app-proxy 侧**已消费**——`detail.code=deploying` → 导航请求渲染「发布中」自动重试页、XHR 返 503 + 16147、WS 升级以 4503 关闭，并按路由缓存的 3s 缓存该答案（不把一次发布变成对 manager 的请求风暴）。manager 侧**当前不发**：`deploy` 是同步的——探活通过才写期望态（`generation+1`），backend 也要等 `deploy` 返回才把应用置 `online`，重发布期间旧实例照常服务到 30s 宽限期结束；所以现在**不存在**能观察到「发布中」的窗口，路由端点只有 `{upstream,…}` 与 404 两种答案（404 → 「应用恢复中」）。若日后把 deploy 改成异步（先登记期望态再拉起），该窗口即出现，届时**必须**发此信封而不是 404，否则用户在首发布期间看到的是「恢复中」文案。
（`GET /v1/apps/{app_id}/db/*` 数据面已于 T086 落地，见 §2 表末五行。）

**出站白名单双层与 docker-socket-proxy（D12 / D2-B）已于 T077 / T078 落地**，见 §4 与 §5 的新增项。落地口径三条，排障时按这个顺序看：
1. **三层，不是一层**。L1 = `bisheng-apps` / `bisheng-build` 建成 `--internal`（应用没有默认路由）；L2 = `egress-proxy`（runtime-manager 同一个包的第二个入口点 `python -m runtime_manager.egress_proxy`），它是唯一能看见**域名**的一层，也就是「只放行声明域名」唯一可能成立的地方；L3 = `DOCKER-USER` / nft 兜底，兼管 UDP（CONNECT 代理看不见数据报）。
2. **`BISHENG_APP_STORAGE_ENDPOINT` 所指地址恒在放行名单上**，并且同时进 `NO_PROXY`（同网直连，不绕代理），`tests/test_egress.py::test_the_attachment_handle_host_is_always_on_the_run_phase_list` 钉住这条。
3. **策略是一个文件**（`{RTM_DATA_ROOT}/egress/policy.json`），不是一次 RPC：编排器重启不该把每个托管应用的出站一起带走。代理按 mtime 重读，读坏了保留上一份。文件里存了**凭据明文**（reconciler 重建实例、重发布宽限期都必须复用同一把），因此目录 0700、文件 0600，只有本部署的两个进程读得到。
4. **放行名单分两半，判定不同**（2026-09-16 review 补）：部署侧配置的那半（deploy 意图的 `platform_api_base`、`RTM_APP_FACING_BASE_URL`、`RTM_EGRESS_ALLOW` / `RTM_EGRESS_BUILD_ALLOW`、包源）标 `trusted`，**允许是私网地址**——私有化平台本来就是。应用 manifest 声明的那半**不允许**：代理按定义同时挂在 `bisheng-apps` 与有默认路由的网上（compose 形态下它就坐在 mysql / redis / minio 旁边），不加这道闸，一行 `egress: {domains: [mysql]}` 就把「唯一出口」变成「进平台内网的中继」，正是 L1 要消除的可达性。落法：代理放行后先解析域名，**任一**解析结果非公网即 403 `private_address`，报文直接写出运维侧的口子 `RTM_EGRESS_ALLOW`；随后连的是刚判过的那个地址而不是域名（第二次解析不可能给出不同答案）。`trusted` 标志随策略文件一起落盘，`from_dict` 缺字段一律按 **不可信** 读。
5. **平台侧那半是从「平台注入了哪些地址」推出来的，不是一张手写清单**（2026-09-16 review 补）：`platform_api_base` 不等于「平台」——F051 的模型面 `OPENAI_BASE_URL` 取 `open_api.public_base_url`（**浏览器可见 origin**），只有它没配才退回 `app_runtime.entry_base_url`（= `platform_api_base`）。两者不同是被文档化的常规形态，按 `platform_api_base` 单独建名单，白名单一开托管应用的模型调用全被拒。落法：`runtime_manager.egress.PLATFORM_URL_ENV_NAMES`（`BISHENG_PLATFORM_API_BASE` / `BISHENG_APP_STORAGE_ENDPOINT` / `OPENAI_BASE_URL` / `BISHENG_MODEL_BASE_URL`）里的值一律进可信名单。这些名字是平台保留名、backend 在版本自带注入**之后**覆写，所以值必是平台的；下一个平台地址加进来时这里不用改。

**已在线实例随层配置对齐（2026-09-17）**：代理变量在创建容器时固化，层配置却属于部署——开层、关层、改 `RTM_EGRESS_PROXY` / `RTM_APP_FACING_BASE_URL` 之后，存量实例的变量就不再对。reconciler 每轮检查在跑且健康的实例，漂移即按同版本重发布的形态蓝绿替换（`generation+1`，探活通过才切，旧实例宽限期后退役），**每轮至多一个应用**，失败保留旧实例并退避 600s；`rtm.reconcile` 的 `actions.realigned` 计数。策略条目（`RTM_EGRESS_ALLOW` 改动、策略文件丢失）原地补写，不重建容器。**所以开层后无需逐个 resume**，等 `应用数 × 15s` 即可；核对：`docker inspect <容器> -f '{{range .Config.Env}}{{println .}}{{end}}' | grep -c HTTPS_PROXY`。

**存量环境升级注意**：`docker network create` 不会把已存在的网改成 internal，compose 也不会。`GET /v1/runtime/status` 的 preflight 新增 `egress_whitelist` / `application_network_internal` / `egress_firewall_fallback` 三行，**没改到位时逐行给出改法**；`RTM_EGRESS_PROXY` 留空时第一行直接写「托管应用出站不受限」。
