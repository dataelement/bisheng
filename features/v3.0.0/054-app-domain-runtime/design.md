# Design: 托管应用领域模型与运行时（compose 形态 + 统一入口）

> **本文档定位 — 现状快照（Why this How）**
>
> - `spec.md` 回答 **做什么**（65 条 AC、边界、8 条决议）
> - `design.md`（本文）回答 **为什么这么实现**：关键决策（含被否决的备选）、运行时不直观的事实、对外契约
> - `tasks.md` 是 **流水账**：拆了哪些任务、做了什么改动
>
> 调整原则（详见 `docs/SDD-Guide.md` §3-§4）：实现变化 → 覆盖更新本文档、只留"今天的状态"；但每个决策保留"为什么 + 被否方案"和坑。推翻已 ★ 确认的决策 → 停下与用户重新确认；纯实现细节 → 直接改 design。
>
> **代码事实口径**：本文所有 `文件:行号` 均按 `3.0-vibe`（HEAD `b63a320f2`，含 F048）在 2026-08-17 由四份探查笔记（E1 权限与构建页 / E2 运行时基建 / E3 前端壳与广场 / E4 基线核实）核实，路径以 `src/backend/bisheng/` 为根（前端另注 `platform/` = `src/frontend/platform/src/`、`client/` = `src/frontend/client/src/`；仓根路径显式写出）。行号会漂移、符号名不会——落地前以符号名重定位。凡文档锚点已在代码中消失的，标「**已失效**」。
>
> **本文是"要建成的样子"**：F054 尚未开工，`app_runtime` 模块 / runtime-manager / app-proxy 三者全是绿地（E2 §0：backend 今天零 docker 依赖、零进程管理器、零 cgroup 操作）。实现后按现状覆盖本文。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)（待写）· [release-contract.md](../release-contract.md)（表 1 App / AppVersion / AppInstance；INV-32 / INV-33 / INV-35）· [mvp-114-path.md](../mvp-114-path.md)（**§6 MVP-核心是本轮裁剪基准**、§3 114 环境事实）· 姊妹 [F055](../055-app-publish-pipeline/spec.md) / [F053](../053-dev-cli-skills/spec.md) / [F056](../056-app-square-governance/spec.md) · [F049 design](../049-openapi-auth-baseline/design.md)（凭据底座与开放能力层开关的兄弟键形态）
**技术路线依据**: `docs/product/3.0 附录：纳管应用技术路线与架构选型调研.md`（下称《调研》）· `docs/product/3.0 应用工场 产品方案.md` §4.1 / §4.5 / §4.8
**版本**: v3.0.0
**最后更新**: 2026-08-18（D5.2 补第 4 条「裸应用根路径先补尾斜杠再呈现」——114 实测白屏；此前：2026-08-17 初版 → 同日按独立审查 16 条发现修订，见修订历史）

---

## 1. 目标与非目标

- **目标**：把「托管应用」立成与工作流 / 助手并列的第三种平台应用类型——落三张表与一个五动作状态机（应用态的唯一写入方）、把它注册进 F048 权限体系当一种资源类型、交付 compose 单机形态的编排器 runtime-manager（backend 零编排依赖）与统一入口 app-proxy（`/apps/{slug}` 验会话 → 判可见范围 → 注入身份 → 反代），并在 platform 构建页加第三种类型卡片与应用详情页四 tab 壳。一句话：**让一个本地写好的应用在平台上"是一个对象、有一条地址、跑在笼子里、被权限管住"**。
- **非目标**（防后人误扩范围）：
  - **本 Feature 不做任何平台能力集成**——知识库检索、模型调用、身份组织工具、SDK、MCP 一律不碰（MVP-核心定调，`mvp-114-path.md` §6）；app-proxy 注入的 OBO 令牌本期**只签发与注入、无消费方**，其能力范围语义归 F055（决议-4）。
  - 发布管线 / 审批 / 版本写入时机 / 能力声明的冻结与注入 / 资源档位实体 / 审批期预览实例的生命周期 → **F055**（本 Feature 只提供领域对象、状态动作、构建 / 探活 / 容量 / 预览入口路由供其调用）。
  - 应用广场、授权交互、审计查询面、GOV-07 验收 → **F056**；k8s 形态 → **F059**；CLI → **F053**。
  - **MVP-核心之外的项一律后置**（出站白名单、docker-socket-proxy、WS 三不变量、两个过渡态页、附件存储、数据面 WB-06、访问记录留痕、二维码、预览入口、`node20` / `static` 模板、备份手册）——逐项落点见 **§8** 与 **D15**，tasks.md 排在 `[MVP-核心]` 波次之后。**它们属本 Feature 范围、不得被裁掉**（spec 决议-3 对出站白名单已明确要求）。

---

## 2. 关键约束

> 全局铁律（DDD 分层 / 双 DB / 多租户自动注入 / 权限唯一入口 / 错误码 / 无硬编码密钥 / 前端 store 不直连 HTTP）一律遵循 [`docs/constitution.md`](../../../docs/constitution.md) **C1–C7**，本节不重抄。以下只写本 Feature 特有的硬约束。

| # | 约束 | 出处 / 后果 |
|---|---|---|
| **K1** | **编排特权是全案最重安全约束**：backend **编译期与运行期零编排依赖**——不 import docker / kubernetes / aiodocker 客户端、不挂 `/var/run/docker.sock` 或 kubeconfig、不起 DinD；只向 runtime-manager 下发**期望态 intent**。今天这是纸面承诺：`scripts/arch-guard.sh:6-15` 只有 RULE-1~9、**无任何 docker/k8s 禁令**（CLAUDE.md 说"8 条"已过时），全仓 `import docker` = 0、`docker.sock` 仅出现在 `.drone.yml:57,89,173,224,259,316`（CI）。→ **必须新增 RULE-10 并同步 `docs/constitution.md` 锚点表**，否则 AC-14「部署检查可核验」无强制力 | 产品方案 §4.1 / §4.5「编排特权」/ §4.8「边界纪律」；《调研》§4；E2 §0 / E4 §0-6 |
| **K2** | **单机容量是硬闸门，且构建也要过闸**：114 是 32G 机器，available 曾长期 ~0.9G（ES + OpenFGA 双 JVM + uvicorn + celery×3 + linsight worker×4），近期 18–20G；`docker build` 装 pip 依赖会吃内存。容量不足时**不得拉起"先起来再说"的半可用实例**（spec §3），构建同样要在启动前判可用内存并限 `--memory` | E4 §0-10；spec AC-19 / AC-65；memory `reference_remote_dev` |
| **K3** | **RT-08 的 5 分钟自愈预算要在 compose 单机上算得出来**：docker 单机的 healthcheck 与 restart policy **无联动**（unhealthy 不触发重启），所以「进程退出」靠 docker restart policy、「存活但不健康」必须由 runtime-manager 的 reconcile 轮询补；两条路合计 ≤ 5 分钟必须能分解到具体探测周期 | 《调研》§2.6 要点 1/2；spec AC-20 |
| **K4** | **双 DB（C2）对新表与大字段**：`app` / `app_version` / `app_instance` 三张表须 MySQL + DM8 双方言可建；能力声明 / 注入配置只能用 `JsonType`（`core/database/dialect_helpers.py:196`，DM8 落 CLOB），**禁 `JSON_EXTRACT` / `JSON_CONTAINS`**——凡需要 SQL 筛选的字段（`state` / `runtime` / `tier_id` / `slug`）一律拆成显式列；**代码快照体、SQLite 快照体、构建产物一律不入库**，库里只存 MinIO 对象键（String 列）。历史教训：`FlowVersion.data` 全量 JSON 入库在 DM8 上撑爆 undo（memory `project_linsight_dm8_history_write_amplification`） | C2；E2 §5；E4 §A5 |
| **K5** | **多租户（C3）三件事必须手工做**：① 新模型模块要登记进 `core/database/tenant_filter.py:39 _TENANT_AWARE_MODEL_MODULES`（自动发现只认"已 import 且**有 `tenant_id` 列**"的表，`_discover_tenant_aware_tables` + `_EXCLUDED_TABLES` :31；注释 :33-38 记着 v2.5 就因此漏过租户）；②**`app_version` 没有 `tenant_id` 列**（版本记录挂在应用下），登记进该元组后**仍然不受自动过滤**——它的租户隔离只能靠"先按 `app_id` 取 `app` 行、由 `app` 的自动过滤兜住，再查版本"，任何直接按 `version_id` 起手的读写都必须自己 join `app` 或先校验归属（D8 已把这条写进读写口径）；③ **UNION 子查询的自动过滤失效**——`database/models/flow.py:660-702 _build_apps_subquery` 的 docstring（:661-671）明写这点，**今天只有两支**且各自手工 `build_tenant_filter_clause(...)`（`flow_clause` :695、`assistant_clause` :698），**没有现成的三支范例可抄**，第三支要照两支的写法自己加。另：租户过滤监听器**只拦 SELECT**（`tenant_filter.py:164-165`），状态动作里任何批量 UPDATE / DELETE 必须手写租户条件 | C3；memory `reference_tenant_filter_in_list_trap` |
| **K6** | **SQLite-per-app 绑定「单应用单实例 + 本机卷」**：WAL 单写者、不支持网络文件系统；快照必须走 tar 上 MinIO，**绝不把 WAL 库文件放网络存储**；多实例 / 多机演进前必须先升档（Postgres schema-per-app 中档）。本版单实例是 GOV-03 既定约束、不是实现偷懒 | 《调研》§2.7；spec §3「每应用数据库的形态承诺」；产品方案 §4.1 |
| **K7** | **cookie 同源免登是白吃的、但只白吃一半**：`access_token_cookie` = `path=/`、`domain=None`（host-only）、`httponly=True`（`core/config/settings.py:516-527 CookieConf`；`user/domain/services/auth.py:135`），`/apps/*` 同源自动携带 → 零登录改造。但 **JWT payload 只有 `sub/exp/iss`**（`auth.py:139-149`），`token_version`（Redis `user:{id}:token_version` → DB）、账号禁用、租户禁用三项校验都在 HTTP 中间件里（`utils/http_middleware.py:124-142 / 263-279 / 325-349`）——**只本地解 JWT 会绕过它们**，与 INV-30 fail-closed 精神冲突 | E2 §2.1 / §2.2；E4 §0-5 |
| **K8** | **商业版 Java 网关只认 `/api`**：它处理 `/api/oauth2/*`、`/api/sso|wx` 回调、`/api/sensitive/*`、`/api/group/*`，代理 `/api/v1|v2/**` 与 WS，**完全不认 `/apps`**（`docs/architecture/11-gateway.md:27-38`）；`/apps/` 必须在其前面的 nginx 层直达 app-proxy。含义：**网关的敏感词过滤与限流不覆盖托管应用流量**，安全逻辑必须一处实现在 app-proxy 内、不随开源 / 商业版分叉 | 产品方案 §4.5；E2 §2.6 |
| **K9** | **Catalog 范围表只写一次 + 授权模型 checksum 双闸**：`permission_action_resource_scope` 的写入点只有两处（首次迁移 `permission/migration/f048_runtime_storage.py:834-963`、草稿发布 `catalog_api.py:769-848`），而 `CatalogChangeType`（`permission/domain/schemas/f048.py:60-67`，7 值）**没有一个能改 `resource_types`** → 代码里给 `ACTION_RESOURCE_SCOPES` 加 `app` 后，线上任何路径都不会把它写进 DB，判权（`sql_runtime.py:115-140`）按 DB join 判 fail-closed。同时改 `MIGRATED_RESOURCE_TYPES` 就改了模型 checksum（`authorization_model_f048.py:523-529`）→ 存量环境启动即 `migration_required=True`、**全站权限 503**。**存量生效必须是"发模型 + 改 release 指针 + 补 scope 行"三件套原子完成再全进程重启** | E1 §2；E4 §0-2 / §0-3；spec AC-13 |
| **K10** | **MVP-核心边界与 114 部署形态**：本轮只做「本地应用 → deploy → 托管上线 → 广场可用」闭环（`mvp-114-path.md` §6）；114 的部署增量 = **两个 systemd 单元**（`bisheng-runtime-manager.service` / `bisheng-app-proxy.service`，追加进 `bisheng.target` 的 `Wants=`）+ **nginx `location /apps/`** 一段 + **`deploy.sh` 的 `SERVICES=` 与 `smoke.sh` 增量**。⚠️ 这些文件**都不在产品仓**：它们在独立仓 `~/Projects/bisheng-ops/`，114 的 nginx conf 在 `/etc/nginx/conf.d/bisheng-lilu.conf`（4101）与 `bisheng-external-13000.conf`（13000 → 公网 50071）。产品仓根 `./deploy.sh`（钉 `feat/2.5.0` 的 nohup 老脚本）与 `docker/deploy.sh`（compose 运维壳）**都不是 114 在用的**，不要引用 | E4 §C1 / §C2；memory `reference_remote_dev` |
| **K11** | **错误码段 161**（`app_factory`）：`common/errcode/` 现占 100–111 / 120 / **130**（chat）/ 140 / 150 / 160 / 170 / 180 / 181 / 190–198 / 200 / 210 / 220 / 230 / 240 / 250 / **260**（开放 API，**F049 已落码** `common/errcode/open_api.py`——E2 笔记写作时 260 还是"预留"，现已占用，勿再当空段）；**161 空闲**（16x 只有 160=dataset，已复核）。F054 用 161，F055=162 / F056=163 / F059=164。落码同一 PR 回写 `docs/constitution.md` C5 登记表 + `packages/locales/src/api_errors/{zh-Hans,en,ja}.json` 三语（生成物勿手改，CI `pnpm check-i18n` 校验） | C5；E2 §6；release-contract 表「已分配模块编码」 |
| **K12** | **工场运行时层开关是部署级、不是租户偏好**：三段式 `settings.app_runtime.enabled`（YAML，需重启）→ `GET /api/v1/env`（匿名可读，在 `TENANT_CHECK_EXEMPT_PATHS`）→ 两个 SPA。**不进 DB 热配置**（`initdb_config` 有 100s Redis 缓存、语义是租户偏好）。与 F049 的开放能力层开关（`settings.open_platform.enabled`）是**同形态兄弟键、不合并**（真身在 F049 design 的 **K8**〔:39，"开放能力层开关三段式"〕与 **D9**〔:160-165，`OpenPlatformConf` → `get_env` → `appConfig.openPlatformEnabled` 全链〕，对外契约表 `GET /api/v1/env` 行 :242-243；~~:149-152~~ 是 share-link 通道段落，勿引）；AC-61 两开关任意组合可启动。⚠️ `load_settings_from_yaml`（`common/services/config_service.py:91-107`）对未知顶层键直接 `KeyError` 拒启 → **必须先发代码、后往 `config.yaml` 加键** | E2 §1.4；E3 §3；F049 design K8 |

**Constitution Check（自查）**：
- **C1（DDD 分层）**：新模块 `bisheng/app_runtime/` 按 `api/ + domain/services` 分层；不跨模块 import 其他模块的 `api/`（RULE-5）；permission adapter 只依赖 `permission.domain.schemas` 与 `permission_action_service.PermissionActor`（同 `tool/domain/services/f048_tool_permission.py` 的 import 面），**不 import OpenFGA 基础设施**（RULE-9）。runtime-manager / app-proxy 是 `bisheng` 包**之外**的独立包，不参与 RULE-1~9，但受**新增 RULE-10** 约束的是反向：`src/backend/bisheng/**` 禁 docker/k8s import 与 socket 路径字面量。
  - ⚠️ **三张表的 ORM 定义不能放 `app_runtime/domain/models/`**——UNION 第三支必须写在 `database/models/flow.py` 的 `_build_apps_subquery` 里（AC-51 / AC-57 的一次查询前提，D8），该文件就得 `from bisheng.app_runtime.domain.models.app import App`，而 `scripts/arch-guard.sh` **RULE-2**（:37-45）对路径含 `/database/models/` 且匹配 `^(from|import) bisheng\.[a-z_]+\.domain\.` 的文件**必报 VIOLATION**（已核实：`database/models/flow.py` 今天只 import `common/core/database` 与同目录模型，无任何既有豁免可援引）。**故 D8 把三张表定在 `bisheng/database/models/{app,app_version,app_instance}.py`**（与 UNION 另两支 `flow.py` / `assistant.py` 同目录，`database/models` 内互相 import 不触 RULE-2），`app_runtime/` 只留 `domain/services/` 与 `api/`。取舍与被否方案见 **D8「模型落点」**。
- **C2（双 DB）**：见 K4；Alembic revision DDL-only、`down_revision` 取 `uv run alembic heads` 唯一头（`core/database/alembic/AGENTS.md`），不传 `mysql_charset/mysql_collate`。**per-app SQLite 在 SQLModel / tenant_filter 之外**——它不是平台库，隔离靠库边界，是 C2/C3 的显式例外（产品方案 §4.1 已定；本文 D10 论证）。
- **C3（多租户）**：见 K5。`app` / `app_instance` / `app_access_log` 三张表带 `tenant_id`、走自动过滤；**`app_version` 无 `tenant_id`**（K5 ②），其隔离是"经 `app_id` 借道 `app` 行"的派生隔离，登记进 `_TENANT_AWARE_MODEL_MODULES` 只为保证 metadata 被 import，不代表它受自动过滤——版本相关的每个读写入口都要在 design/tasks 的验收注释里点明这一点。
- **C4（权限）**：`app` 的一切判权只经 `permission/application/business_authorization.py:27/48/64` 三个函数；无 OpenFGA 直连；**owner-only（删除 / 数据 tab）与 owner∪租户管理员（日志 tab）是业务规则前置拦截**，不能靠权限运行时（管理员在那里被身份短路放行，`permission_action_service.py:372-385`）——spec §3 已声明。
- **C5（错误码）**：见 K11。
- **C6（无硬编码密钥）**：runtime-manager / app-proxy ↔ backend 的 HMAC 共享密钥走 `!env` 或 config.yaml（Fernet），不落代码；OBO 签名密钥独立于 `jwt_secret`（D6）。
- **C7（前端 store 不直连 HTTP）**：platform 新页面经 `controllers/API/hostedApp.ts`，不 import axios。

---

## 3. 方案对比与选定

> 每条 3 段：备选 / 选定 / 原因 + **何时该重新考虑**。这里是"想当然会走但被否决"的路的登记处。

### D1：编排器进程形态与 backend ↔ 编排器通信 = 独立包 + 独立进程 + 意图式 HTTP RPC（HMAC）

- **备选**：
  - A. **backend 进程内直接调 docker SDK**（`pip install docker`）— 优点：零新进程；缺点：**直接违反 K1**（backend 即持 root-on-host 等价权限），私有化银行 / 信创客户安全团队一票否决，与「安全来自笼子」自相矛盾
  - B. **Celery 任务下发**（新建 `app_runtime` 队列，worker 挂 socket）— 优点：复用既有异步基建；缺点：celery worker 与 backend **同一代码库、同一镜像**（`docker/bisheng/entrypoint.sh:37-40` worker 模式还与 beat / linsight worker 合跑一个容器），docker 依赖照样进 backend 的 `pyproject.toml`，K1 只是换了个进程名；且 build / 探活需要**同步拿结果**，任务队列要靠轮询结果表绕
  - C. **独立包 + 独立常驻进程 + HTTP 意图 RPC**（选定）
  - D. 独立进程 + **Redis 队列**（照 `bisheng/linsight/worker.py:529-560` 的独立 worker 范式）— 优点：仓内有现成骨架；缺点：同 B 的请求-响应语义问题；且 reconcile 是"自己巡检"不是"被喂任务"，队列模型不贴合
- **选定**：**C**。`src/runtime-manager/`（仓根新目录，自带 `pyproject.toml`，**不在 `src/backend/bisheng/` 包内**）；FastAPI 进程，监听 `127.0.0.1:8091`（compose 形态为 service `runtime-manager`，**不 publish 端口**）；backend 侧只有一个薄客户端 `bisheng/app_runtime/domain/services/orchestrator_client.py`（httpx + 超时 + 重试），**接口语义形态无关**（见 §4.2，无 container / compose 字样）。服务间鉴权照抄 `sso_sync/domain/services/hmac_auth.py:58-110`（签名串 `METHOD\nPATH\nraw_body`、`X-Signature` 头、`hmac.compare_digest`、**空 secret fail-closed**），换 secret 字段与错误码。
- **意图式而非命令式**：backend 下发的是"这个应用应当以版本 V 的镜像、档位 T 运行"这一**期望态**，manager 自 reconcile；backend 不发"docker run"。含义：manager 重启后从自己的期望态存储（本机 JSON/SQLite 状态文件 + docker labels 双写）恢复对齐（AC-50），backend 不需要重放。
- **原因**：C 是唯一同时满足「K1 零依赖 + 同步拿 build/探活结果 + 形态无关接口（INV-33，F059 只换 manager 内部后端）」的落点。A/B 都把 docker 依赖留在 backend 侧；D 的队列语义与 reconcile 不贴合。用 Python + FastAPI 而非 Go：团队栈一致、`hmac_auth` / 日志 / 配置写法可照搬，编排逻辑本身不是性能瓶颈。
- **何时该重新考虑**：F059 k8s 形态进场且两个后端由不同团队实现 → 按 spec 决议-1，可把「编排后端」抽为独立 Feature；单机演进为多机调度 → RPC 之外要加节点注册与调度，那时 HTTP 同步语义要重估。

### D2：编排后端访问面 = MVP-核心直连 dockerd，docker-socket-proxy 紧随其后

- **备选**：
  - A. **直连 `/var/run/docker.sock`**（manager 以 root 或 docker 组运行）— 优点：零额外组件，build / run / logs / exec 全可用；缺点：manager 一旦被攻破即 host root
  - B. **`tecnativa/docker-socket-proxy` 端点白名单**（默认拒写与 exec，只放行需要的 API 端点）— 优点：把"全有全无的 root 等价权限"收成端点级；缺点：白名单需要按实际用到的 Docker API 端点实测（`/build`、`/containers/create|start|stop|remove`、`/images`、`/networks`）、多一个容器 / 单元、114 首波会拖慢跑通
  - C. **rootless docker / podman socket** — 缺点：114 上 onlyoffice 等既有容器跑在 rootful daemon 上，改 daemon 形态影响面超出本 Feature
- **选定**：**A 作 MVP-核心，B 作紧随其后的后置 Wave**（spec 明确排除「编排后端访问面的进一步收窄」，只交付默认档；本文 §8 登记）。无论 A/B，**代理端口绝不对外暴露**（127.0.0.1 绑定 + compose 内部网络）。
- **原因**：《调研》§2.6 要点 3 与 `mvp-114-path.md` §3 都写明"纵切内可直连 dockerd、纵切后加 socket-proxy"；A→B 的切换对 manager 代码是**换一个 base URL**（Docker API 兼容），不构成返工。
- **何时该重新考虑**：任何面向客户的环境部署前（B 必须先落）；Docker 29 起 nftables 后端无 `DOCKER-USER` 链（《调研》§2.8 坑 3）→ 与 D12 的 iptables 兜底一并重估。

### D3：构建路线 = 平台持有的 Dockerfile 模板矩阵，首发只 `python3.11`

- **备选**：
  - A. **平铺 Dockerfile 模板 + 基础镜像矩阵**：`runtime: python3.11 | node20 | static` 直接映射到一份平台维护的 Dockerfile 模板，开发者与 AI 不写 Dockerfile
  - B. **CNB buildpacks（`pack`）** — 优点：自动探测；缺点：只覆盖 x86_64/arm64、构建过程不透明、失败原因难映射成 AC-15 要求的"可读的失败原因与失败阶段"
  - C. **Railpack / Nixpacks** — **已否决，勿再议**（《调研》§1 表、§2.5）
  - D. 让开发者或 AI 提供 Dockerfile — **PRD-1 DEV-04 明禁**（托管运行契约：语言运行时由平台给）
- **选定**：**A**。MVP-核心期**只实现 `python3.11` 模板**；`node20` / `static` 模板后置（D15）。`SUPPORTED_RUNTIMES` 是 runtime-manager 侧按"本部署实际存在的模板"给出的动态集合，backend 经 `GET /v1/runtime/status` 取回并在预检（F055 调）时校验 → AC-15 的"取值不在集合内 → 拒绝并列出支持的取值"在 MVP 期实际列出 `python3.11` 一项。
- **镜像与包源**：
  - 镜像命名 `bisheng-app/{slug}:{version_no}-{version_id[:8]}`，**tag 永不复用**（AppVersion 只增不改，AC-02）；保留策略 = 当前运行版本 + 上一个版本（AC-21 的旧实例宽限退休需要旧镜像），更早的在下一次构建成功后清理。
  - 构建期包源经 `--build-arg PIP_INDEX_URL/PIP_TRUSTED_HOST` 注入，取值来自 `app_runtime.build_index_url`（114 先用可达的 PyPI 镜像）；自托管 devpi / verdaccio 与"构建期唯二放行"的 egress 收窄随 D12 后置。
  - 构建资源：`--memory` 限额（默认 2G）+ 构建前过容量准入（D11，`purpose=build`）——K2。
  - 构建日志按阶段（`fetch_source` / `render_dockerfile` / `docker_build` / `probe`）分段收集，失败时返回 `{stage, message, tail}` 供 F055 预检输出（AC-15）。
- **原因**：A 是《调研》§1/§2.5 的结论，且只有它能把失败原因映射到确定的阶段；模板由平台维护意味着安全基线（read-only rootfs、no-new-privileges、非 root 用户）**由平台统一落，开发者改不了**。
- **何时该重新考虑**：出现第四种 runtime 或同一 runtime 的多版本诉求（则模板矩阵要参数化基础镜像 tag）；k8s 形态（F059）——那时构建必须换成无守护进程构建器（Kaniko/Buildah）+ 镜像仓库，但**构建定义必须与 compose 形态同一份**（产品方案 §4.5「产物一致性」）。

### D4：崩溃自愈与切流量 = docker restart policy 兜进程退出 + reconciler 只补 unhealthy-but-alive；切流量走 health gate

- **备选**：
  - A. **runtime-manager 自研重启循环**（自己监听容器退出事件、自己退避重启）— 缺点：重复造 docker 已内置的指数退避（100ms → 1min、跑满 10s 重置），且 manager 宕机期间无人重启，直接违反 AC-22
  - B. **只靠 docker healthcheck** — **不成立**：docker 单机的 healthcheck 与 restart policy 无联动，容器 unhealthy 会一直 unhealthy 地活着（K3）
  - C. **docker restart policy + reconciler 补洞**（选定）
- **选定**：**C**。
  - 容器创建时带 `--restart unless-stopped`（**不用 `always`**：下线动作是显式 `docker stop`，`unless-stopped` 语义正好是"显式停了就别自愈"，避免下线与自愈打架）+ `HEALTHCHECK`（`interval=10s`、`timeout=3s`、`retries=3`、`start_period` 按档位 20–60s）。
  - reconciler：manager 内 **15 秒**一轮，比对期望态 vs `docker ps` 实际态，三类动作——缺失即拉起、`unhealthy` 连续 2 轮即**重建**（stop → rm → run，卷不动）、孤儿容器（无期望态）即回收。
  - **5 分钟预算分解**（AC-20 / NFR-6）：进程退出 → docker 自身退避重启 ≤ 60s；存活但不健康 → healthcheck 判 unhealthy ≤ 30s + reconcile 感知 ≤ 30s（2 轮）+ 重建拉起并探活 ≤ 90s（镜像已在本地）= **≤ 2.5 分钟**，余量给 114 的 IO 抖动。
  - **切流量（AC-21）**：Dokku CHECKS 语义——先以新版本镜像起**新容器**（容器名带 version 后缀，与旧容器并存）→ 通过启动探活 → 更新路由（`app_instance.current_version_id` + manager 侧路由表条目原子替换、`generation+1`）→ 旧容器**宽限 30 秒**后 stop + rm。**路由表怎么被 app-proxy 看到、30 秒这个数字为什么是 30 秒 → 见 D5.1**（app-proxy 经 `GET /v1/apps/{app_id}/route` 取 upstream、缓存 3s；宽限期必须 ≫ 缓存 TTL + 在途请求，否则切换窗口出 502）。切换窗口内 app-proxy 对入口访问渲染「发布中」过渡页（**后置 Wave**，MVP 期窗口内表现为短暂 502 → 由 app-proxy 统一转成兜底页而非报错页，见 D7）。
  - **AC-22 / AC-50**：容器存活依赖 dockerd 而非 manager；manager 重启只影响 reconcile 时效，启动时先做一次全量对齐（期望态存储 = 本机状态文件 + 容器 label 双写，label 是灾备真相）。
- **原因**：《调研》§2.6 要点 1/2/4 的三条结论；Coolify 的先例说明"控制面宕机不影响数据面"必须作为显式验收项而非默认属性。
- **何时该重新考虑**：k8s 形态（Deployment 原生滚动 + `restartPolicy` + readiness gate，reconciler 退化为薄壳）；单实例约束放开（那时切流量要变成真正的滚动，宽限期要按连接排空算）。

### D5：app-proxy = 自研 Python 独立包，nginx 变量式 upstream + error_page 回落，未部署引导页落 platform SPA

- **备选**：
  - A. **nginx `auth_request` + 平台端点** — 缺点：现网零使用（纯新建）；注入头与 OBO 签发要写 lua/njs；**`auth_request` 不覆盖 WebSocket upgrade**
  - B. **oauth2-proxy** — 缺点：不认平台会话与 OpenFGA；且 **CVE-2025-64484（CVSS 8.5）正是头剥离不彻底**——我们托管的是不可控的 Python 应用框架，这条是设计前提级红线（《调研》§2.3）
  - C. **自研 Python（FastAPI + httpx/websockets 反代）**（选定）
  - D. 自研 Go — 优点：反代性能好、单二进制好部署；缺点：仓内无 Go 工程与 CI，运维与调试成本换不回收益
- **选定**：**C**。`src/app-proxy/`（仓根独立包，自带 `pyproject.toml`），监听 `127.0.0.1:8090`；**不 import `bisheng` 包**（理由见 D6）。
- **nginx 接线**（`docker/nginx/conf.d/default.conf` 与**同构副本** `src/frontend/nginx.conf` **两份都要改**；114 另在 bisheng-ops 仓的两份 conf）：新增 `location /apps/`（前缀匹配，长于 `/` 故优先于 platform SPA fallback；不与正则 `~ ^(/workspace)?/api(/|$)` 冲突），关键指令 = **变量式 upstream + `resolver`（compose 用 127.0.0.11）延迟解析** + `proxy_http_version 1.1` + `Upgrade/Connection` 头（复用文件顶部既有 `map`，`default.conf:3-6`）+ 长 `proxy_read_timeout` + `proxy_buffering off` + `error_page 502 503 504 = @apps_unavailable`；`@apps_unavailable` 反代到 backend 的极小引导页端点。
- **D5.1 上游地址解析 = 问 runtime-manager 的路由表（bridge IP:port）+ 3 秒缓存；切流量的可见性靠"旧容器宽限期 ≫ 缓存 TTL"覆盖**（补 AC-25 / AC-26 / AC-33 / AC-21 的落点空白）
  - **问题**：app-proxy「不 import `bisheng` 包、不做权限判定」，内部授权端点返回的是**判定与身份材料**（`decision / headers / obo_token / app_state / app_name / owner_name`），里面**没有目标实例地址**；而 D4 的切流量只说"manager 侧路由表原子切换"，没说这张表怎么被 app-proxy 读到。数据面主链路必须补这一段。
  - **备选**：
    - A. **容器名 / docker DNS 直连**（`http://bisheng-app-{slug}:{port}`）— 缺点：**114 上 app-proxy 是宿主 systemd 单元、不在 docker 网络里，根本解析不了容器名**（compose 形态才成立），且 D4 的新旧容器并存要求容器名带 version 后缀，与"固定名"冲突；用 network alias 搬迁又不原子、还受 DNS 缓存干扰
    - B. **在容器上 publish 宿主端口**（`127.0.0.1:{动态端口}`）— **直接违反 AC-33**（"不暴露可被 app-proxy 之外访问的端口"）与 §7 的 `docker inspect` 无 `Ports` 断言
    - C. **backend 内部授权端点顺带返回 upstream**（backend 转问 manager）— 缺点：把数据面路由塞进鉴权响应，backend 又多认识一层运行时布局；且鉴权缓存与路由缓存的失效节奏本就不同（鉴权跟权限走、路由跟发布走）
    - D. **app-proxy 直接问 runtime-manager 的路由接口**（选定）
  - **选定**：**D**。runtime-manager 新增 `GET /v1/apps/{app_id}/route`（HMAC，同 §4.2 ① 那套签名），返回 `{upstream: "http://172.20.x.y:8080", version_id, generation}`——`upstream` 是容器在 `bisheng-apps` **bridge 网络上的 IP:端口**（manager 从 `docker inspect` 取），**宿主可达、外部不可达**，两种部署形态同一机制（compose 形态下 app-proxy 也在该网络上，取到的地址照样能连）。app-proxy 按 `app_id` 缓存 **3 秒**（与鉴权缓存同口径、**两把缓存独立**），连接失败（`ECONNREFUSED` / 连接超时）即**立刻作废该条并重取一次**，再失败才渲染「应用恢复中」。
  - **切流量对 app-proxy 可见（AC-21）**：manager 在新容器**通过启动探活后**原子更新自己的路由条目（`generation+1`），旧容器**宽限 30 秒**再 stop——**30s 宽限 ≫ 3s 路由缓存 + 在途请求**，所以切换窗口内命中旧地址的请求仍能被旧容器正常服务，不产生 502。这条不等式是 D4「宽限 30 秒」这个数字的**真正理由**，改任一侧前先读这里。
  - **`app_instance.exec_ref` 与路由表的关系**：`exec_ref`（容器名）是**平台侧的审计 / 排障引用**，**不是路由依据**；路由的唯一真相在 manager 的期望态存储（本机状态文件 + 容器 label 双写，D4/AC-50），backend 不复制它。
  - **何时该重新考虑**：多机形态（那时 `upstream` 要带节点地址、manager 要变成有节点注册的调度器）；k8s 形态（`upstream` 换成 Service ClusterIP，接口语义不变——INV-33 的又一次检验）。
- **D5.2 路径前缀契约 = app-proxy 剥 `/apps/{slug}` + 下发 `X-Forwarded-Prefix` + 注入 `BISHENG_APP_BASE_PATH`，模板把它接进框架 root_path**（补 AC-25「应用内相对路径…经该入口正常工作」的落点空白）
  - **问题**：托管的是平台模板给出的 FastAPI / Streamlit 类应用。若原样带前缀转发，应用要自己认得 `/apps/{slug}`；若剥掉前缀不告诉它，应用生成的绝对 URL（`/static/*`、`/docs`、表单 `action="/submit"`、重定向 `Location: /`）在浏览器侧会打到 `/static/*` 而**不是** `/apps/{slug}/static/*`，一律 404。同一份代码在 F053 `bisheng dev` 下又跑在根路径（INV-32 要求两处注入同构），口径必须一次定死。
  - **备选**：A. 不剥前缀，让应用自己解析（把平台的 URL 布局泄进应用代码，且本地 dev 跑不了同一份代码）· B. 剥前缀但不告知（上面那批绝对路径全 404）· C. **剥前缀 + 告知 base path**（选定）· D. 给每个应用一个子域名（要泛域名证书与 DNS，114 与私有化客户都不成立；且 K7 的 cookie 是 **host-only**，换域名即丢免登录）
  - **选定**：**C**。三件事同时做：
    1. app-proxy 转发时**剥掉 `/apps/{slug}` 前缀**（`/apps/foo/x?y=1` → 上游 `/x?y=1`；`/apps/foo` 与 `/apps/foo/` 都 → `/`）——转发层面等同处理是对的，但**呈现层面不是**，见下面第 4 条；
    2. 同时下发 `X-Forwarded-Prefix: /apps/{slug}`（并按既有反代惯例给 `X-Forwarded-Proto` / `X-Forwarded-Host`）——**这三个 `X-Forwarded-*` 头不在 `x-bisheng-` 剥离等价类里，但同样必须先剥客户端伪造值再由 app-proxy 重写**（AC-32 只管 `x-bisheng-*`，这三个要单独写一句，否则应用会信任伪造的 Host 生成外链）；
    3. 注入环境变量 **`BISHENG_APP_BASE_PATH`**（线上 = `/apps/{slug}`；F053 `bisheng dev` 注入**同名变量、值为空串**——INV-32 的"同构"是**变量名与语义同构**，不是取值相同），`python3.11` 模板的入口 wrapper 读它并接到框架的 base path（FastAPI `root_path=` / Streamlit `--server.baseUrlPath=`），使框架自动生成带前缀的绝对 URL。
    4. **先把裸应用根路径重定向到带尾斜杠，再呈现应用文档**（2026-08-18 补，实测于 114）：对 GET / HEAD 的 `/apps/{slug}`，在鉴权 allow 之后、转发之前返回 **308** 到 `/apps/{slug}/`（query 原样带上）。前三条只覆盖了「框架在运行时生成绝对 URL」这一条路径——`X-Forwarded-Prefix` 与 `root_path` 对**纯静态产物无效**：一个 Vite 打包的 SPA 把 `./assets/index-x.js` 写死在 HTML 里，没有任何框架会在运行时重写它，解析完全由浏览器按文档 URL 做。文档挂在 `/apps/foo` 时基准是 `/apps/`，`./assets/x.js` 解析成 `/apps/assets/x.js`（另一个 slug），全部 404、页面白屏；挂在 `/apps/foo/` 才解析成 `/apps/foo/assets/x.js`。**位置两处都是有意的**：放在 allow 之后，是因为登录交接 / 无权限 / 已下线 / 不存在 / 恢复中五张页面都是平台自己的 HTML、不解析任何相对 URL，重定向它们只会多一跳并改掉登录后的返回地址（AC-27 的回跳地址）；只对 GET / HEAD，是因为 API 调用不按相对 URL 解析任何东西。
  - **这条为什么会被漏掉（值得记）**：失败在服务端**完全不可见**——两种形式都被归一成 `/` 转发，应用规规矩矩返回 200，日志一片干净，唯一线索在浏览器 console 的资源 404。D5.2 原文写「`/apps/foo` 与 `/apps/foo/` 都 → `/`」时，把"到达同一个页面"当成了"两者等价"，而它们作为**相对 URL 基准**并不等价。
  - **如实登记的残余约束**：应用**手写**的根绝对路径（`<img src="/logo.png">`、`fetch('/api/x')`）仍会 404——平台不做 HTML 重写（要解析 / 改写全部响应体，代价与破坏面都不可接受）。这条写进 **DEV-04 托管运行契约**（"用相对路径或框架 base path，别硬编码根绝对路径"）并由模板的 README 与示例应用示范；F055 的托管预检**不校验**它（静态分析判不准）。
  - **何时该重新考虑**：产品接受给应用发子域名（那时 cookie 要从 host-only 改 `domain=`，K7 的免登录前提整条重估）；出现大量存量应用无法改绝对路径（那时才谈响应体重写，且只对 `text/html` 做，代价照实评估）。
- **未部署引导页（AC-30）两层**：
  1. **整层没装（nginx 里根本没有 `location /apps/`）**：`/apps/x` 落 `location /` → platform SPA 的 `index.html` → 现状是已登录 `* → /404`、未登录 → `LoginPage`（`platform/routes/index.tsx:144/250`）。→ **platform SPA 增一条 `apps/*` 路由（public + private 两张表都加）渲染「本环境未启用应用工场」引导页**，读匿名 `/api/v1/env.app_runtime_enabled` 判定。**零 nginx 变更**，已部署环境该路由永远命中不到（被更长前缀截走）。
  2. **装了但 app-proxy 挂了**：nginx `error_page` 回落到 backend 的 `GET /api/v1/apps/_unavailable`（返回同一张引导页 HTML）。backend 提供一张静态 HTML **不违反 K1**（零 docker 依赖）。
- **原因**：C 是唯一能同时做「验平台会话 + FGA 判定 + 归一化剥离 + 签注入 + WS 反代 + 自渲染兜底页」的落点，且安全逻辑一处实现、开源版与商业版（K8）不分叉。nginx 用变量式 upstream 是因为 **nginx 在 config load 时解析静态 `proxy_pass` 的主机名，profile 未启动 → 容器名不可解析 → nginx 直接起不来**（E4 §0-9），这是"整层可不装"与"静态 conf"的硬冲突。
- **何时该重新考虑**：`/apps` 流量成为瓶颈（Python 反代吞吐不足）→ 换 Go 或把纯反代段下沉给 nginx、只把鉴权留在 app-proxy；商业版 Java 网关决定接管 `/apps`（那时 K8 的前提变了，注入逻辑要在两处对齐——**强烈不建议**）。

### D6：会话校验与身份注入 = backend 内部授权端点（HMAC）+ app-proxy 本地短缓存；注入头按等价类归一化剥离

- **备选**：
  - A. **app-proxy 本地解 JWT**（只需 `jwt_secret` + `jwt_iss`）— 优点：零跨进程调用；缺点：**漏 token_version / 账号禁用 / 租户禁用三项**（K7），且要把平台会话密钥复制到第二个进程
  - B. **app-proxy 直连 Redis + DB**（`initialize_app_context` 拿 Redis/DB/MinIO，自己复刻 `http_middleware` 的判定链 + 自己查 FGA）— 缺点：app-proxy 变成 backend 的第二个副本（全套 Settings / SQLModel / OpenFGA 客户端），**双份真相**；F048 判定逻辑一改就要改两处；且 app-proxy 一旦 import `bisheng` 包，K1 的"独立包"边界形同虚设（依赖树互相污染）
  - C. **backend 内部授权端点**（选定）：`POST /api/v1/internal/app-proxy/authorize`（HMAC 保护、加入 `TENANT_CHECK_EXEMPT_PATHS`、handler 内 `bypass_tenant_filter`），一次返回**判定结果 + 注入头材料 + OBO 令牌**；app-proxy 按 `(cookie 值哈希, slug)` 本地缓存 **3 秒**（与 F049 D2 的 3 秒口径一致）
- **选定**：**C**。
- **判定顺序**（严格按 spec §3「入口判定顺序与信息泄漏口径」，任一步失败即短路）：
  1. 工场层是否部署（`settings.app_runtime.enabled`）→ 否则「未启用」引导页；
  2. **登录态**：复用 backend 中间件同一函数集——解 cookie（`_extract_http_access_token` `http_middleware.py:60-73`）→ `token_version` 比对（`:124-142`）→ 账号禁用（`:263-279`）→ 租户禁用黑名单（`:325-349`）；无 token → 登录交接页（D7）；
  3. **应用是否存在且曾上线**：`app` 行存在 ∧ `state ∈ {已上线, 已下线}`（草稿 / 待上线 / 已删除 / 不存在**一视同仁**返回「不存在或未上线」页，AC-29）；
  4. **可见范围**：`check_business_action("app", app_id, actor, "use")`（D9）→ 否则「无权限」页（可带应用名与 owner，PRD 明示的引导信息）；
  5. **应用态**：已下线 → 「已下线」页（**只对可见范围内用户呈现**）；
  6. 转发。
  - **权限引擎不可用 → 拒绝**（AC-12，INV-19/INV-30 同向）：内部端点对 `PermissionServiceUnavailableError` / `PermissionBackendUnavailableError` 一律返回 deny + 明确错误页，**绝不放行**；app-proxy 侧对内部端点超时 / 5xx 同样 fail-closed。
- **注入头集合**（AC-31，主体类型必须在内）：`X-BiSheng-User-Id` / `X-BiSheng-User-Name` / `X-BiSheng-Tenant-Id` / `X-BiSheng-Dept-Id`（`Department.dept_id` 业务键 `BS@xxx`，**不是自增 id**）/ `X-BiSheng-Dept-Name` / `X-BiSheng-Dept-Path` / `X-BiSheng-Subject-Kind`（`human` \| `service_account`）/ `X-BiSheng-App-Id` / `X-BiSheng-Access-Token`（OBO）/ `X-BiSheng-Request-Id`。**含非 ASCII 的三个头（User-Name / Dept-Name / Dept-Path）一律 UTF-8 percent-encoding 后再放头**——HTTP 头是 latin-1，直接塞中文姓名会被 uvicorn/h11 拒或乱码（§5 坑 9）。头名以 F053 `bisheng dev` 迷你代理注入的**同一套**为准（PRD DEV-05 / INV-32），本文定名、F053 消费。
- **归一化剥离（AC-32 / CVE-2025-64484）**：转发前遍历**全部**入站头，把 name 做 `lower()` 且 `_` → `-` 归一后，凡以 `x-bisheng-` 开头者**一律丢弃**（不是只丢精确的十个名字）；WS 升级请求走同一段代码。理由：托管的是不可控的 Python 应用，WSGI/ASGI 框架把 `X_BiSheng_User_Id` 与 `X-BiSheng-User-Id` 归一到同一个 `HTTP_X_BISHENG_USER_ID` 是常态——**只按精确名剥离等于没剥离**。
- **OBO 短时令牌形态与签发**（AC-34、决议-4）：HS256 JWT，`aud="bisheng-app-obo"`、`iss` 同平台、`sub={app_id, user_id, tenant_id, subject_kind}`、`exp = now + app_runtime.obo_ttl_seconds`（默认 900）；**签名密钥独立于 `settings.jwt_secret`**（新键 `app_runtime.obo_secret`）——否则一个 OBO 令牌能被当平台会话 cookie 用。由 **backend 内部端点签发**（app-proxy 不持签名密钥），随授权结果一起下发、随缓存一起复用（缓存 3s ≪ TTL 900s，安全）。**不持久化、不出现在任何界面、不登记为领域对象**；**本期无消费方**（能力范围 = 能力声明 ∩ 用户权限，归 F055）。
- **WS 三不变量落地程度**：
  - MVP-核心期 **只反代 HTTP**（`mvp-114-path.md` §6 F054 行明写）；
  - 后置 Wave 落 **不变量①**：握手时一次性定死连接授权有效期 = `min(OBO 剩余寿命, app_runtime.ws_max_lifetime_seconds〔默认 8h〕)` + 随机抖动，到期主动 `close(4001)`；
  - **不变量②**（吊销 / 下线事件主动断连，app-proxy 维护 connection → (user, app) 索引）与**不变量③**（前端把"断开 → 重握手"做成常态）随 §8 后续；**②正是自研 app-proxy 的核心理由**（反代生态无先例，《调研》§2.9），不要因为"先只做①"就把它忘了。
- **原因**：C 让「谁能进」这一判定**只有一份实现**（backend 的 F048 链路），app-proxy 退化为"问一次 + 缓存 + 剥离 + 注入 + 反代"；A 的三项漏检与 INV-30 直接冲突；B 的双份真相在 F048 这种高变更面上必然漂移。3 秒缓存的代价是「可见范围撤销 / 下线生效」有 ≤3 秒延迟，与 AC-10「自下一次请求起生效」的口径相容（下一次请求 = 缓存过期后的下一次）。
- **何时该重新考虑**：内部端点成为热点（每次导航一次 RPC）→ 把判定结果按 `(user, app, 权限版本)` 缓存进 Redis 由两端共享；F050 / F055 需要 OBO 可离线校验或跨进程持久 → 按决议-4，升格为领域对象并补 INV。

### D7：兜底页与过渡态渲染归属 = app-proxy 自渲染（A′），登录回跳靠内联 JS 页

- **备选**：
  - A. **app-proxy 自渲染 HTML**（4 类兜底 + 2 类过渡 + 登录交接页）— 优点：**URL 不变**（扫码 / 收藏 / 刷新重试语义最稳）、hash 零丢失、client 零改动；缺点：品牌 / 三语 / 深色主题要在 Python 侧再做一小套，`pnpm check-i18n` 覆盖不到
  - B. **302 → client SPA 的 gate 路由**（`/workspace/apps/gate/:slug?reason=…`）— 优点：品牌 / 三语 / 主题天然一致；缺点：① gate 路由**必须放在 `AuthLayout` 之外**，否则 `AuthContextProvider` 一挂载就拉 `/user/info`、401 拦截器先跑 `redirectToLogin()`（**首次调用胜出的一次性守卫**，`client/src/utils/loginRedirect.ts:87-106`）→ 写进 `LOGIN_PATHNAME` 的会是 gate 页 URL 而非应用 URL；② `forbidden` / `stopped` 页要应用名与 owner，得再加一个登录态接口或把它们塞 query；③ **过渡页反正只能 A**（gate 页轮询要多一个接口）
  - C. 复用 platform SPA 承接 — 缺点：platform 是管理端，兜底页给的是普通业务用户看的
- **选定**：**A′ = A 全承接**（4 兜底 + 2 过渡 + 登录交接内联页）；**「未部署」引导页两条路都覆盖不了**（app-proxy 不存在）→ 落 platform SPA `apps/*` 路由（D5）。
- **登录回跳（AC-27，含 query 与 hash）**：**服务端 302 做不到**——① hash 永远不上送服务器；② platform 登录页**只消费 `localStorage.LOGIN_PATHNAME` + `LOGIN_PATHNAME_AT`**（`platform/src/utils/loginReturnTo.ts:35-70`，一次性 + 10 分钟时效 + 同源校验），**不认任何 `?redirect=` query**（`login.tsx:375-390` 只读 `status_code`）。→ app-proxy 对未登录的**导航请求**返回一段**内联 JS 交接页**：写这两个 key（值 = `location.href`，天然含 query+hash）后 `location.replace('/admin')`。`/admin` 未登录即 platform `LoginPage`；配了 SSO 时它自己跳 IdP（`login.tsx:71-86`），回来后 `App.tsx:154-160` 或 `login.tsx:168-172` 消费同一 key 回跳。**这两个 key 名 / 同源校验 / 10 分钟时效是跨 SPA 契约，app-proxy 复刻时必须原样。**
- **非导航请求分流**（两条路都必须做）：仅当 `Sec-Fetch-Mode: navigate`（或 `Sec-Fetch-Dest: document`，回落 `Accept: text/html`）时返回页面 / 交接页；XHR / fetch 返回 **JSON + 真实 HTTP 状态**（401/403/404/503）；WS 升级请求直接以关闭码拒绝。否则应用内的 XHR 会拿到一坨 HTML，前端解析崩。
- **过渡态**（AC-36 / AC-48，**后置 Wave**）：「发布中」「应用恢复中」由 app-proxy 自渲染 + `meta http-equiv=refresh`（或内联 JS 定时 `location.reload()`）自动重试，就绪后自动进入应用、用户无需手动刷新；两者与四类兜底页**互斥**。MVP-核心期这两个窗口内表现为短暂不可达 → app-proxy 统一渲染「应用恢复中」的**静态版**（不自动重试），不落报错页。
- **原因**：A′ 与 E2 §2.6 (b)、E3 §2.3 建议、`mvp-114-path.md` §2 F054 首波「无权限 / 已下线 / 不存在 / 未部署四类页」口径一致；B 的坑①是**竞态型**缺陷（表现为"登录后落回 gate 页"），排查成本远高于在 Python 侧写一套极简样式。
- **何时该重新考虑**：产品要求兜底页与 client 品牌主题 / 三语机制完全同构 → 改 B，并按 E3 §2.3 处理坑①②；或平台登录页增加 `?return_to=` 同源校验入口（改 `login.tsx` + `App.tsx` 两处）→ 那时交接页可退化为纯 302。

### D8：领域模型与表设计 = 三张新表 + 显式状态列 + 快照体走 MinIO 引用；UNION 第三支投影出 `flow_type=35`

- **备选**：
  - A. **塞进既有 `flow` 表**（`FlowType` 加值 35，版本记录复用 `flow_version`）— 优点：构建页 UNION / 标签 / 版本下拉全白吃；缺点：**RT-05「只增不改」与 `flow_version` 的可变指针语义正相反**（`database/models/flow_version.py:207 change_current_version` 原地切换 `is_current`），release-contract 表 1 已裁定独立建模；`flow` 表列结构（`data` 大 JSON）与应用完全不匹配
  - B. **三张新表 + 构建页列表另开一个接口，前端合并两个列表** — 缺点：构建页是 **cursor 分页**（`useInfiniteCursorTable` + keyset `(update_time, id)`），前端合并两个游标流做不到稳定排序
  - C. **三张新表 + 复用同一列表接口的 UNION 第三支**（选定）
- **选定**：**C**。
- **模型落点（arch-guard RULE-2 逼出来的、与直觉相反的一项）**：
  - **备选**：
    - M1. 三张表放 `bisheng/app_runtime/domain/models/`（模块内聚，与 F049 `open_api/domain/models/` 同形）— **不可行**：UNION 第三支写在 `database/models/flow.py`，该文件就必须 `from bisheng.app_runtime.domain.models.app import App`，`scripts/arch-guard.sh` RULE-2（:37-45，条件 = 路径含 `/database/models/` ∧ 匹配 `^(from|import) bisheng\.[a-z_]+\.domain\.`）**必报 VIOLATION**，且 `flow.py` 今天无任何既有豁免可援引（它只 import `common/core/database` 与同目录模型）
    - M2. 保留 M1 的落点，把 UNION 第三支**注入**进来：`_build_apps_subquery` 加 `extra_selects` 参数，由 `api/services/workflow.py` 组装后传入 — 可行但要穿透 `FlowDao` 的 **4 个调用点**（`flow.py:435 / :541 / :813 / :850`）及其上游签名，并让 `FlowDao` 接受外部拼好的 SQL 片段（评审面更差）
    - M3. **三张表放 `bisheng/database/models/{app,app_version,app_instance}.py`**（选定）
  - **选定 M3**：与 UNION 另两支 `flow.py` / `assistant.py` **同目录同层**，`database/models` 内部互相 import 不触任何 RULE（`flow.py` 今天就 import `database/models/assistant`）；`_TENANT_AWARE_MODEL_MODULES` 里也与 `bisheng.database.models.flow` / `.assistant` 同一邻里。**C1 不禁止**（宪法 C1 只列 RULE-1~5，`database/models/` 是合法的 ORM 层；RULE-3「endpoint 不直接 import `database/models`」仍要守——`app_runtime/api/endpoints/*` 一律经 domain service）。代价：`app_runtime/` 模块只有 `domain/services/` + `api/`，模型不在模块内、内聚性弱一档——**这是为 UNION 第三支（AC-51 / AC-57 的一次查询前提）付的确定代价，不是疏忽**。
  - **何时该重新考虑**：构建页列表改成"按类型分表查 + 服务端归并"（UNION 消失）→ 三张表可搬回 `app_runtime/domain/models/`，同批把 `_TENANT_AWARE_MODEL_MODULES` 的登记改掉；或 arch-guard 为 UNION 场景开出显式豁免（不建议：豁免一开就会被复制）。
  - `app`（`bisheng/database/models/app.py`）：`id`(str, PK) / `slug`(str, **全局唯一 `UniqueConstraint`**，跨租户唯一，AC-08) / `name` / `description` / `logo` / `owner_user_id`(int) / `tenant_id`(int) / `state`(VARCHAR16 显式列) / `current_version_id`(str, nullable) / **`pending_version_id`(str, nullable)** / `create_time` / `update_time`。**主键用 str**——`Flow.id`（`flow.py:99`）与 `Assistant.id`（`assistant.py:21`）都是 str，UNION 三支列类型必须一致（K5）。
  - `app_version`：`id` / `app_id` / `version_no`(int) / `kind`(`initial`\|`iteration`) / `terminal_state`(`online`\|`rejected`\|`withdrawn`\|null) / `code_object_key`(str，MinIO) / `manifest`(JsonType) / `capabilities`(JsonType) / `injections`(JsonType) / `tier_id`(显式列) / `runtime`(显式列) / `image_ref` / `submitted_at`。**四者（代码快照 · 能力声明 · 注入配置 · 资源档位）同属一条记录**，任何写入方（F055）不得只改其一（AC-02）——落地手段 = **本表只 INSERT、不提供 UPDATE 方法**（`terminal_state` 是唯一例外，由 F055 的终态标注单列更新）。**本表无 `tenant_id`**（隔离经 `app_id` 借道 `app` 行，K5 ②）：一切按 `version_id` 起手的读写必须先取 `app` 行校验归属，禁止直接 `select(AppVersion).where(id=...)` 后就用。
  - **「已审批待运行版本」怎么表达（AC-04 / AC-05，原设计的空白）**：`terminal_state` 的四个取值（`online` / `rejected` / `withdrawn` / null）表达的是**审批终态**，表达不了"审批已通过、但还没生效"这一格。补 **`app.pending_version_id`** 一列承担它：
    - F055 审批通过后调 **`AppStateService.stage_version(app_id, version_id)`**（§4.2 ②）写 `pending_version_id`，**不改应用态**——这正是 AC-04「已下线态允许 F055 落新的待运行版本但不自动重新上线」；已上线态下 F055 紧接着调 `publish` 直接切，`stage_version` 只是同一事务里的前一步。
    - `resume`（重新上线）取 **`pending_version_id ?? current_version_id`** 拉起——AC-04「重新上线后新版本生效」由此成立；`publish` / `manual_publish` 同此取版规则。
    - 任何一次拉起成功后：`current_version_id = 本次生效版本`、`pending_version_id = NULL`、该版本 `terminal_state='online'`。
    - 被驳回 / 撤回**不写** `pending_version_id`（只标 `terminal_state`），故 AC-05「迭代被驳回不改变已上线态、当前版本继续运行」天然成立。
    - `pending_version_id` **不是应用态**，但它的写入同样只在 `AppStateService` 内（决议-8 的精神一致：F055 只调不直写）。
  - `app_instance`：`id` / `app_id` / `tenant_id` / `version_id` / `phase` / `health` / `exec_ref`（执行体引用，compose 形态是容器名——**这是唯一允许出现形态特有值的字段，且只对内**）/ `started_at` / `restart_count` / `last_probe_at`。
  - `app_access_log`（AC-38，**后置 Wave**）：`tenant_id` / `user_id` / `app_id` / `created_at`，索引 `(app_id, created_at)`。
- **状态机落库与并发**：`app.state` 单列 + 五个状态动作集中在 `AppStateService`（**应用态唯一写入方**，决议-8；F055 只调不直写）。每个动作的落库是**带前态断言的单行 UPDATE**（`WHERE id=:id AND state IN (:允许前态)`），受影响行数为 0 → 抛 `AppStateConflictError`（16102）。这样并发的「下线」与「上线终检」不会互相覆盖，也不需要行锁。**不建独立状态机 / 状态历史表**——每次动作已计审计（`app.*` 命名空间，D14），审计就是历史。
- **UNION 第三支**：`database/models/flow.py:660-702 _build_apps_subquery` 加第三支 `SELECT`，把 `app` 表投影成同一列集 `(id, name, description, flow_type, logo, user_id, status, create_time, update_time)`——其中 `flow_type` 投影为**常量 35**（`FlowType` 新枚举值，避开已占的 5/10/15/20/25/30，`flow.py:33-39`），`user_id` 投影 `owner_user_id`，`status` 投影为 **2（已上线）/ 1（其余四态）** 供既有 `status` 过滤与卡片开关复用；**应用态五值另经新查询参数 `app_state` 过滤**（不塞 `status` 列，见坑 12）。第三支的 `tenant_id` 条款**手工** `build_tenant_filter_clause(App.tenant_id)`——照 `flow_clause`（:695）/ `assistant_clause`（:698）两支的写法自己加，**今天没有第三支范例**（K5 ③）。
- **但 UNION 第三支只是"第三类型接入"的一半——后端另有 6 组硬闸**（E1 §3.2 / E4 §0-7 已逐条列出；行号会漂，按符号名定位。**只加 UNION 第三支的话，前端选「托管应用」得到的是恒空列表，AC-51 / AC-57 直接不成立**）：
  1. **`api/services/workflow.py:76 SUPPORTED_APP_TYPES`**（今天 = `{WORKFLOW, ASSISTANT}`）加 `FlowType.HOSTED_APP.value`（35）。**三处 `flow_type not in SUPPORTED_APP_TYPES` 直接 `return [], False`**：`:198`（构建页列表）· `:514`（广场在线列表，F056 消费）· `:592`（cursor 分页）——这是第三类型撞上的**第一道闸**，且失败现象是"空列表"而非报错，极易被当成"权限没配好"排查半天。
  2. **`:77-80 _FLOW_TYPE_TO_RESOURCE_TYPE`** 加 `35 → "app"`，并给 `_application_action_map`（`:146-179`）的 `grouped` 字典（`:151-154`）加 `"app": []` 桶。不加则第三支的行**分桶落空**、拿不到 `batch_check_business_actions` 结果 → 卡片的动作位与 `can_share` 恒为空（表现为"有卡片但什么都点不了"）。
  3. **`:83-84 filter_supported_apps`** 是公共闸，被 **6 处**调用（`:95` `add_extra_field` / `:156` / `:241` / `:351` / `:444` / `:948`）——它读的就是第 1 项那个集合，**加 1 即全放行、无需逐处改**（这是这组改动里唯一的好消息）。
  4. **`add_extra_field`（`:87-127`）**：`user_name`（`UserDao.get_user_by_ids`）/ `tags` / `logo` / `write` 四项对 app 可直接复用；**`version_list` 不行**——它来自 `FlowVersionDao.get_list_by_flow_ids`（`:112`），对 app 恒空，托管应用的只读版本下拉必须另给数据源（坑 13）。
  5. **标签体系 4 处 + 1 个枚举**：列表侧 tag 预过滤硬编码资源类型对 `[ResourceTypeEnum.WORK_FLOW, ResourceTypeEnum.ASSISTANT]` 在 `:203`（构建页）· `:598`（cursor）· `:998-999`（`aget_resources_by_tags` 两次 gather），以及 `api/services/tag.py:75-103 check_tag_link_permission`（只认 ASSISTANT / WORK_FLOW，其余 `raise NotFoundError()`，入参在 `api/v1/tag.py`）；底座是 **`database/models/group_resource.py:14-22 ResourceTypeEnum`**（已占 1/3/4/5/6/7/8/9）→ 新增 **`HOSTED_APP = 10`**。AC-51「复用既有标签筛选」不改这组就是"筛选框在、结果恒空"，打标还会直接 404。
  6. **`status` 列语义**：`flow.py:568 sub_query.c.status == status` + 前端 `getAppsApi` 只放行 `status ∈ {1,2}`（坑 8）→ 第三支的 `status` 投影为 2/1，应用态五值走**新参数 `app_state`**（见上一条）。
  - **前端 14 处扩展点在 D13**（那一节**只覆盖 platform 前端**，不含本条的后端 6 组，两处要一起读）。
- **双 DB**：`manifest` / `capabilities` / `injections` 用 `JsonType`；`runtime` / `tier_id` / `state` / `slug` 是显式列（K4）；Alembic revision `v3_0_0_f054_app_runtime_tables.py`（DDL-only，`down_revision` 取 `alembic heads`）。
- **原因**：C 让"托管应用是构建页的第三种类型"这件事在**一次查询**里成立（AC-51 / AC-57），同时不把 RT-05 的只增不改语义压进 `flow_version`。`flow_type=35` 只是**给前端与既有列表管线的类型标识**，不代表托管应用是一条 flow——`app` 表才是真身。
- **何时该重新考虑**：应用数量使 UNION 三支的 keyset 分页变慢（那时列表改成"按类型分表查 + 服务端归并"）；PRD-2 引入平台内造应用后 `app_version` 需要草稿版本语义（则 `terminal_state` 要扩，且"只 INSERT"的约束要重审）。

### D9：`app` 资源类型注册 = 走 `MIGRATED_RESOURCE_TYPES` 全适配器路线；存量环境靠新写的三件套升级脚本

- **备选**：
  - A. **照抄 `linsight_skill` 的 `OWNER_PROJECTION_RESOURCE_TYPES` 档**（`authorization_model_f048.py:44` + `skill_service.py:105`）— 缺点：**它只投影 owner、不进 Catalog、registry 未注册、grant_subjects 未放行**，任何 `check_business_action("linsight_skill")` 会 `InvalidCatalogActionError`；托管应用需要"对用户 / 部门 / 用户组授可见范围"，**不能照抄**
  - B. **新增专属 action code**（如 `app:enter`）— 缺点：新 code = 模型 relation 面变化 + Catalog 全表变更 + `INITIAL_ACTION_LEVELS` + 前端 catalog 文案，且存量环境需要新 Catalog release 才能生效；收益为零
  - C. **走 `MIGRATED_RESOURCE_TYPES` 全适配器路线 + 复用既有 action code**（选定）
- **选定**：**C**。
- **动作集合（不新增 code）**：`use`(L1) = 可见范围 / 入口访问 / 广场可见；`edit`(L2) = 元信息更新；`manage_permission`(L3)；`delete`(L4)；`publish` / `unpublish`(L3) = 重新上线 / 下线。**入口访问判定用 `check_business_action(..., "use")` 而非 `runtime.check_visible`**——前者与 PermissionDialog 授的档位语义一致（viewer 档即含 `use`），后者对"授了 editor 但没 use"的自定义模型更宽、会让可见范围口径与弹窗显示不一致。
- **后端必改 8 处**（E1 §1.2 / E4 §A3 核实；行号会漂，按符号名定位）：
  1. `core/openfga/authorization_model_f048.py:32-42 MIGRATED_RESOURCE_TYPES` 加 `"app"`（**不是** :44 的 OWNER_PROJECTION 档）；顺带 `MODEL_VERSION` 升 `f048-v2` 便于运维辨识。
  2. 同文件 `:55-78 RESOURCE_ACTION_SCOPES` 的 `publish` / `unpublish` / `use` / `edit` 加 `"app"`（该常量**全仓无消费者、是死常量**，为可读性同步即可，别在评审里当锚点）。**只需手工加这 4 个**：`manage_permission` 与 `delete` 的取值直接写作 `frozenset(MIGRATED_RESOURCE_TYPES)`，第 1 项加完就自动带上——手工再加一次是写重复值。第 4 项（`catalog_policy.ACTION_RESOURCE_SCOPES`）同理。
  3. `permission/domain/services/catalog_policy.py:31-43 MIGRATED_RESOURCE_TYPES` 加 `"app"`（**与 1 必须同步**，见坑 1）。
  4. 同文件 `:45-68 ACTION_RESOURCE_SCOPES` 逐 action 加 `"app"`。
  5. `permission/domain/services/resource_lifecycle_policy.py:14-26` 把 `"app"` 加进 **`FIXED_CUSTOM_TYPES`**（起始 CUSTOM；`linsight_skill` 就在 :24）。
  6. **新建 adapter** `bisheng/app_runtime/domain/services/f048_app_permission.py`（Loader + Adapter 两件，模板 = `tool/domain/services/f048_tool_permission.py:1-80+`）：`load_permission_record`（读 tenant/owner/state/update_time + `runtime.get_permission_version`）、`resolve_permission_target` → `VerifiedPermissionTarget.from_business_service`（含状态白名单 / 租户匹配 / owner>0 三判）、`authorize_created`（`mode="CUSTOM", protected=True`）、`project_delete`。
  7. `api/services/f048_permission_runtime.py:128-196 build_f048_resource_composition`：`adapters["app"]` + `registry.register("app", ...)`——**这是 API 与 worker 两个组合根共用的注册点**，漏了则 celery / linsight 进程判权直接 `RuntimeError("F048 resource registry is not configured")`。
  8. `permission/api/endpoints/grant_subjects.py:28-40 GRANT_SUBJECT_RESOURCE_TYPES` 加 `"app"`——**baseline 的"12 处"漏掉的活闸门**，漏了则授权弹窗能打开但搜不到任何主体（**5 个端点 / 5 处硬闸**：`:89` users · `:113` user-groups · `:135` departments/children · `:152` departments/search · **`:168` departments/{dept_id}/path-tree**——最后一处最容易漏列，漏了它的现象是"能搜到部门、但点开树是空的"）。
  - **明确不改**：`PARENT_TYPES`（app 无父级）；`SYSTEM_SHARED_ACTION_TYPES`（app 不做系统共享，正好符合"默认仅 owner 可见" AC-11）；`SYSTEM_OWNED_RESOURCE_ALLOWLIST`（app 恒有 owner）；`REGISTERED_ACTION_CODES` / `DEFAULT_ACTION_CODES`（不新增 code）；`permission/migration/f048_source_inventory.py`（**迁移专用**，legacy→F048 一次性白名单，源里本就没有 app 数据）；`permission_schema.VALID_RESOURCE_TYPES` 与 `core/openfga/authorization_model.py`（**死代码**，别把工时花在它们上）。
- **前端 3 处 union**：`platform/controllers/API/permission.ts:6-16`、`platform/components/bs-comp/permission/types.ts:3-13`（与前者**重复定义**）、`client/src/api/permission.ts:3-13`（F056 用，F054 可一并加）。`PermissionDialog` 组件本身**无 per-type 分支**，union 加完即可用。
- **114 存量生效脚本（AC-13）**：新写 `src/backend/scripts/upgrade_f048_authorization_model.py`（仿 `reconcile_f048_projection_operations.py` 的 `--apply` 默认 dry-run 惯例），**步骤 1 是 OpenFGA 控制面写、步骤 2–4 才是同一 SQL 事务**（原写"三件套同一 SQL 事务"不成立：步骤 1 是一次 HTTP 写 authorization model，进不了 SQL 事务）：
  1. **（控制面 HTTP，事务外）** store 内发布含 `app` 的新模型 M2——先按 checksum 找已存在的模型保证幂等，照 **`_find_remote_model`（`permission/migration/f048_runtime_storage.py:463-479`，被 `aget_or_publish` `:420-444` 调用）**；⚠️ **不在 `core/openfga/discovery.py`**（该文件全文仅 268 行、无此符号，幂等查重逻辑在**迁移存储层**而非发现层，照旧锚点去找会扑空）；checksum 必须用同一个 `canonicalize_authorization_model`（`authorization_model_f048.py:537-563`）算；
  2. `authorization_model_release` 新增 ACTIVE 行（`model_version=f048-v2`、`predecessor_model_id=M1`、重算 `required_relations_checksum`），M1 行置 RETIRED（照 `amark_ready` 的两条 UPDATE，`f048_runtime_storage.py:370-397`）；
  3. CURRENT `permission_catalog_release.required_authorization_model_release_id` 指向新行；
  4. **scope 行原地补**（方案 a）：对 CURRENT release 的目标 action `INSERT permission_action_resource_scope(action_id, 'app')` 并重算 release checksum。
  - **回滚语义（别被"事务"两字误导）**：步骤 2–4 在一个 SQL 事务里、可整体回滚；**步骤 1 写进 store 的 M2 回滚不掉、会永久留在 OpenFGA**。所以实际的回滚手段是 **"把 `authorization_model_release` 的 ACTIVE 指针指回 M1 行 + 撤掉 scope 行 + 全进程重启"**，M2 变成 store 里一个没人 pin 的孤儿模型（无害：运行时只认 SQL pin 的那个）。因为步骤 1 按 checksum 查重幂等，重跑不会再多写一个 M2。
  - **不用 `force_write_model`**：它只写 OpenFGA 不写 SQL、不查重（每次重启多写一个重复 model）、生产禁用（`core/config/openfga.py:47-55`），三条都让它当不了升级手段。
  - 前置检查：唯一 store、`list_runtime_heartbeats()` 为空或显式 `--allow-live`、CURRENT release 恰一条且非 write_fenced、代码 checksum ≠ 当前 ACTIVE 才继续（否则 no-op）。`verify` 子命令重跑读侧断言（`current_catalog()` 通过 + `is_action_effective("app", 每个动作)` 为真）。
  - **跑完必须全进程重启**（API / celery×3 / beat / linsight worker）：心跳每 15s 复核、TTL 45s，不重启的旧进程会自行 fail-closed（不是"还能用"）。
  - 正规路径（扩 `CatalogChangeType` 加 `SET_ACTION_RESOURCE_SCOPES` + `_apply_changes` 分支 → 走 draft/publish）登记进 §8，**不在 MVP-核心**。
- **原因**：`app` 需要完整的"授给用户 / 部门 / 用户组"能力（AC-09），只有全适配器路线提供；`linsight_skill` 档是存量隐患的样板、不是范例。原地补 scope 行（方案 a）可 dry-run、幂等、纯 SQL 可回滚（把 pin 指回 M1 行即可），代价是违背"release 不可变"直觉且 `commit_checksum` 会漂移（仅 migration verify 用，运行时读侧不校验）。
- **何时该重新考虑**：F048 扩出改 `resource_types` 的变更类型 → 升级脚本改走正规 publish 路径；再新增第五种业务资源类型时（第三次手工改 8 处）→ 值得把这 8 处收敛成一张注册表。

### D10：per-app SQLite = 本机卷 + 同名连接环境变量；快照走 `.backup` 后 tar 上独立 bucket

- **备选**：
  - A. **平台 MySQL/DM8 里给每个应用建库或建 schema** — 缺点：应用要用标准库直连平台主库（凭据下发 = 平台库权限外泄面）；DM8 上 schema-per-app 的权限模型与平台单 URL 单例连接池（`core/database/connection.py:73`，pool 100+20）冲突
  - B. **Postgres schema-per-app**（中档，Databricks Lakebase 同款：per-app 独立角色、仅 CONNECT+CREATE、标准 `PG*` 环境变量）— 优点：可到数千应用、支持多实例；缺点：**引入一个平台原本不需要的数据库**，MVP 不值
  - C. **SQLite-per-app + 本机卷**（选定，《调研》§2.7 小档）
- **选定**：**C**，且**显式绑定 K6 的硬约束**（单实例 + 本机卷；WAL 不上网络存储）。
- **卷与可写路径**：宿主 `{app_runtime.data_root}/apps/{app_id}/db/`（默认 `/opt/bisheng/app-data`），容器内挂 `/data`；容器 rootfs **read-only**、`/tmp` 用 tmpfs、`/data` 是唯一可写持久路径（AC-17）。
- **同名连接环境变量**（AC-45「与本地 `bisheng dev` 同名」）：`BISHENG_APP_DB_URL`（值 `sqlite:////data/app.db`）+ `BISHENG_APP_DB_PATH`（`/data/app.db`）。**名字在本文定、F053 `dev` 同名注入**（§6.1 登记为 Outgoing 契约）；应用用标准 `sqlite3` / SQLAlchemy 即可读写。
- **快照（AC-45「可随存档快照与备份」）**：**绝不裸 tar 一个 WAL 库**——先在容器外用 SQLite 的一致性备份（`.backup` / `VACUUM INTO`）生成 `app.db.snapshot`，再 tar 上 MinIO，对象键 `apps/{app_id}/db-snapshots/{ts}.tar`。**独立 bucket `bisheng-apps`**（不进公共 `bisheng` 桶）：`bisheng` 桶虽非整桶匿名读（匿名策略只覆盖 `knowledge/images/*` 与 `tmp/images/*`，`minio_storage.py:297-311`），但 **nginx `/bisheng/` location 会把任意 key 转发到 MinIO**，安全边界只剩 MinIO 策略本身；新桶不挂 nginx location、不设匿名策略。代码快照同桶不同前缀 `apps/{app_id}/versions/{version_id}/code.tar.gz`（**只增不改**，不要用灵思 workspace 的 copy-forward 语义——版本间无继承）。
- **数据面服务端接口的落点（AC-56，后置 Wave 但落点现在就要定死）**：库文件在**宿主** `{data_root}/apps/{app_id}/db/app.db`，而 backend **不认识容器 / 卷布局**（K1），多节点下 backend 与容器还常常不同机——**"挂宿主日志文件让 backend 直读"被 D14 否决的那条论证对 SQLite 一字不差地成立**。
  - **备选**：A. backend 直接打开宿主库文件（违反 K1 + 多节点直接错） · B. 在应用容器里塞一个平台的数据面 sidecar / agent（要求应用镜像里有平台代码，破坏"平台只给运行时、不进应用进程"的模板契约） · C. **runtime-manager 提供数据面 RPC**（选定）——它本来就与库文件同机、且已持有卷路径
  - **选定 C**：`GET /v1/apps/{app_id}/db/tables` · `GET /v1/apps/{app_id}/db/tables/{table}/schema` · `GET /v1/apps/{app_id}/db/tables/{table}/rows?page=&size=&order=` · `PATCH /v1/apps/{app_id}/db/tables/{table}/rows/{pk}` · `GET /v1/apps/{app_id}/db/export?table=`（产文件），**一律不含 DDL**（表结构由应用包声明、平台建表，spec AC-56）。backend 侧唯一服务方 `AppDataService`（经 `orchestrator_client`），**权限（仅 owner，业务规则前置拦截）与审计（`app.data_row_edit`）都在 backend 做，manager 不认识 owner**；F052 的 MCP 应用数据工具复用同一 backend 方法（同 owner 收窄、写入同样计审计），**不得**绕过去直连 manager。
  - **并发**：manager 与应用容器同机、同一 WAL 库文件多进程读写，是 SQLite 支持的形态（K6 的"单写者"是**同一时刻**的约束，不是"只能一个进程打开"）；manager 侧写入用短事务 + `busy_timeout`，别开长事务扫全表。
  - **形态无关（INV-33）**：k8s 形态（F059）用同一组 RPC 语义换实现（ephemeral 容器 / 数据卷挂载的 job），backend 与 F052 侧零改动。
- **附件句柄（AC-45，后置 Wave）**：按应用收窄的存储句柄（上传 / 下载 / 列举 / 删除四操作、越界拒绝、单文件上限为部署配置项、不计租户存储配额），经 `BISHENG_APP_STORAGE_*` 系列变量注入，与 F057 SDK storage 同名同 API。MVP-核心不做。
- **原因**：《调研》§2.7 与产品方案 §4.1（"应用库选单文件 SQLite 后，数据部分的存档简化为 tar 一个文件"）；SQLite 让"每应用一个库"的供给成本≈零，而单实例本来就是 GOV-03 的既定约束。
- **何时该重新考虑**：任何多实例 / 多机 / 自动扩缩容诉求出现前，**必须先升档到 B**（PRD-1 §5.2 已写明"多实例 / 多机演进前须先评估该库的升档路径"）；单应用数据量超出单文件合理区间（经验阈值 ~GB 级）。

### D11：容量准入 = MemAvailable + 已承诺额度双闸，构建与拉起共用；档位限额映射三档

- **备选**：
  - A. **只看 `free -m` / MemAvailable** — 缺点：忽略"已拉起但尚未吃满"的应用，连拉 N 个轻量应用会全部通过、随后集体 OOM
  - B. **只看已承诺额度之和**（sum of limits ≤ 总量 × 比例）— 缺点：忽略平台自身（ES / OpenFGA 双 JVM + uvicorn + celery×3 + linsight worker×4）的实际占用，在 114 上会在 available 只剩 0.9G 时仍判"额度还够"
  - C. **双闸取与**（选定）
- **选定**：**C**。判定在 **runtime-manager**（只有它知道实际），backend 经 `POST /v1/admission` 取结果（AC-19），`purpose ∈ {run, build}`：
  - 闸①（实时）：`MemAvailable - app_runtime.reserve_mb`（默认 2048，给 114 的 JVM 抖动留余量）≥ 本次所需；
  - 闸②（承诺）：`已运行实例的 mem limit 之和 + 本次` ≤ `总内存 × app_runtime.overcommit_ratio`（默认 0.8）；CPU 同理按 `nproc × ratio`；
  - **构建同样过闸**（`purpose=build`，所需 = `app_runtime.build_reserve_mb`，默认 2048）——K2；不足时 AC-15 的失败阶段 = `build_admission`、原因文案是「运行环境容量不足」。
  - 返回体带**判定快照**（`mem_available_mb / committed_mb / total_mb / cpu`），供 F055 把"待上线（资源不足）"的成因如实展示（AC-65）、供超管的运行环境状态接口（AC-23）复用。
- **档位限额映射（GOV-03 落地）**：`ResourceTier` 实体归 **F055**（release-contract 表 1），F054 **只读**。MVP-核心期 F055 的表可能尚未落 → F054 内置**兜底常量表** `DEFAULT_TIERS`（轻量 0.5 vCPU / 512 MiB、标准 1 / 1024、增强 2 / 2048），**表存在时以表为准**；
  - **与 F055 seed 的对账口径（不定死就会两套数值打架）**：`DEFAULT_TIERS` 是**三档出厂规格的唯一代码来源**，**F055 的 `ResourceTier` seed 从这张常量表读取落库**（登记为 §6.1 Outgoing 契约），所以"表未落"与"表刚 seed 完"两个时刻的规格恒等；超管调整后以表为准（AC-64）。**AC-63「实例限额与档位规格一致」的核验基准恒是"该实例所属版本快照里 `tier_id` 当时解析出的规格"**（拉起时固化进容器，`docker inspect` 的 `NanoCpus` / `Memory`），**不是**"当下的常量表"也**不是**"当下的 `ResourceTier` 表"——否则超管调完规格，运行中实例会被判成不一致（而 AC-64 恰恰要求运行中实例不受影响）。
  - **何时该重新考虑**：**「支持删档」这条已被 F055 关掉**——`ResourceTierDao` 不提供删除，退役只有 `enabled=False`，且停用只拦新选择、存量 `tier_id` 照常解析规格（F055 design D11 / AC-47）。**「`tier_id` 永远解析得出」因此是 F054 可以依赖的不变量**，不需要为"版本快照引用了已删档位"准备兜底。真正该重新考虑的是反向情形：若日后产品要求物理删档，先改 F055 AC-47，F054 才轮到改成按快照冻结的规格值拉起。档位 → `--cpus` / `--memory`（AC-63 可在运行环境中核验：`docker inspect` 的 `NanoCpus` / `Memory`）。档位规格调整**自下一次发布或重新上线生效**、运行中实例不受影响（AC-64）——落地手段 = 限额在**创建容器时**固化，不做在线 update。
- **原因**：spec §3「容量准入是硬闸门 …… 判定与档位限额同源」；两个闸各自能被现实证伪（A 被"连拉 N 个"证伪，B 被 114 的 0.9G 证伪），取与是最省的正确解。
- **何时该重新考虑**：多机 / k8s（判定改为问调度器，本接口语义不变——这是 INV-33 的一次检验）；cgroup v2 能给出更精确的"实际可分配"统计。

### D12：出站白名单 = 双层（`--internal` 网络 + egress-proxy，DOCKER-USER 兜底）——**本轮后置，但不得裁掉**

- **备选**：
  - A. **DNS-only 过滤** — **否决**：Harden-Runner 的 DoH 绕过（GHSA-46g3-37rh-v698）证明它挡不住
  - B. **换沙箱 runtime（gVisor / Kata）解决 egress** — **否决**：gVisor netstack 只有限速能力，白名单恒在宿主 / 代理层（《调研》§2.8 末段）
  - C. **双层：L1 `docker network create --internal` + 唯一出口 egress-proxy（HTTP CONNECT / Host / SNI 白名单，放行平台 API + manifest 声明域名）；L2 宿主 `DOCKER-USER` iptables 兜底**（选定）
- **选定**：**C**，**并同时封禁 UDP 出站**（QUIC / HTTP3 无法按域名过滤）与未走代理的直连 TCP。构建期与运行期**两段分离**：构建期只放行平台配置的包源与平台自身分发端点（AC-16），运行期零包源。
- **MVP-核心期的实际状态（如实登记）**：容器接入一个普通 bridge 网络 `bisheng-apps`、**不 publish 端口**（AC-33 的"仅经 app-proxy 可达"由此成立），但**出站不受限**。这是**已知缺口**，spec 决议-3 明确"不允许被裁掉"，只是排在 MVP-核心之后的独立 Wave。
- **原因**：《调研》§2.8 判定"默认出站白名单比换 runtime 更重要"；A/B 的否决都有一手证据。
- **何时该重新考虑**：**任何非 114 的环境部署前必须先落**（这是硬前置，不是"看情况"）；Docker 29 起 nftables 后端**无 `DOCKER-USER` 链**（坑 22）→ manager 需探测 iptables/nftables 后端分别下发规则，或在部署基线里锁定 iptables。

### D13：构建页第三类型的扩展点与详情页壳 = `build/apps/:appId` + 抽卡片与动作 hook

- **备选（详情页承载）**：
  - A. **顶层路由 `/app/:id`**（照 `/flow/:id`、`/assistant/:id`，`routes/index.tsx:113-126`，无 `permission` 字段、页面自守卫）— 优点：全屏无侧栏，与工作流 / 助手编辑器一致；缺点：托管应用详情是**四 tab 的管理页**、不是编辑器，全屏无导航反而别扭
  - B. **`MainLayout` 子路由 `build/apps/:appId` + `permission: 'build'`**（照 `filelib/:id`）（选定）— **零新增菜单 / 权限点**（AC-58 / GOV-07）
  - C. 新开一个 `web_menu` 键 — 违反 AC-58
- **选定**：**B**。副作用：顶部「应用 / 工具 / 工作台配置」子 tab 在详情页会消失（`layout/HeaderMenu.tsx:24` 只在**精确等于**三个路径时渲染），与知识库详情页同行为，可接受。
- **构建页扩展点（14 处，**仅 platform 前端**；**后端的 6 组硬闸 + UNION 第三支在 D8**，两处必须一起改，只改本条会得到"筛选项有、列表恒空"）（E1 §3.1 / E3 §1.2 逐行核实）**：`SelectAppStatus`（应用态五值，见坑 12）· `SelectType`（加「托管应用」，**且必须加条件 prop**——该组件被模板页 `appTemps.tsx:82` 复用）· `TypeNames` · `APP_ACTIONS` · 第三桶 `useResourceActions('app', …)` · `handleOpenPermission` 的 `typeMap`（默认回落 `'workflow'`，见坑 7）· `handleCheckedChange`（第三支 = 下线 / 重新上线 + 二次确认）· `typeCnNames`（角标）· `handleDelete`（第三支 + 三条红底文案）· `handleSetting`（→ 详情页）· 卡片 props（`onAddTemp=undefined` / `showCopy=false` 即隐藏"创建模板 / 复制"，**零改共享组件**）· `AppAvator` 图标 · `getAppsApi` 的 `type` 联合类型与 map · `LabelSelect` 的 `ResourceTypeEnum` 映射。
- **`CardComponent` 唯一的共享组件改动**：AC-42 要求已上线时删除项**置灰 + 提示「请先下线」**，而现状是 `!checked && onDelete` **整项不渲染**（`cardComponent/index.tsx:239-244`）→ 新增 `deleteDisabledHint?: string` prop（`DropdownMenuItem disabled` + Tooltip），**保持 workflow / assistant 现行为不变**（回归验证由 F056 承接 GOV-01 验收 6）。上下线 Switch 文案固定 `t('skills.online/offline')` → 加 `switchTexts` prop 表达"下线 / 重新上线"。**（2026-08-18 推翻：`switchTexts` 已删，卡片与工作流共用 `t('skills.online/offline')` = 「上线 / 下线」；动作口径两字放得进 `w-12`，见 tasks T065 补记。）**
- **≤600 行硬规与技术债**：`apps.tsx` 已 **426 行** + `// @ts-strict-ignore` + 至少 1 处硬编码中文（`:269 '无编辑权限'`，frozen violation）→ **同 PR 抽出** `HostedAppCard.tsx` 与 `useHostedAppActions.ts`（下线 / 重新上线 / 删除三动作 + 确认文案，**卡片与详情页共用**，避免两份文案漂移），并按"谁触碰谁还债"把该文件的中文抽键。
- **详情页目录**（E3 §1.11）：`platform/src/pages/BuildPage/hostedApp/{index.tsx, Header.tsx, tabs/{PublishTab,DataTab,LogsTab,VersionsTab}.tsx, hooks/useHostedApp.ts, types.ts}`；四 tab 用 `bs-ui/tabs`（范式 `pages/SystemPage/index.tsx:54-118`）；**发布 tab 用 slot / children 给 F055（管线 / 能力 / 档位 / 危险操作）与 F056（可见范围区）留位**，避免三个 Feature 改同一文件冲突（决议-6）。
- **两个自建件**（platform 无先例，E3 §1.8 / §1.9）：运行日志 tab = 筛选栏（`DatePicker`×2 + 关键字 + 刷新）+ `<pre>` 等宽块 + 空态 + `setInterval` 轮询（无 `usePolling` hook）；数据 tab = `bs-ui/table` + `useResizableColumns` + `AutoPagination` + `Dialog` 表单行编辑（保存前 `bsConfirm`），导出**走后端产文件 + `downloadFile`**（别新用已被 lint 冻结的 `xlsx`）。**数据 tab 属后置 Wave**。
- **两条不能踩的前端红线**：① **react-query v3 在 platform 已被 lint 冻结**（`eslint.config.mjs:45,51`），新代码用 `useTable` / `useInfiniteCursorTable` / 裸 `useState+useEffect`；② 详情页 / 日志 / 数据接口对非 owner **不能返回 `status_code 403/404`**——platform 拦截器对 GET 会**整页跳 `/403` 或 `/404`**（`controllers/request.ts:160-166`），要用业务码 161xx 或加 `silent: true`。
- **入口链接与二维码**：入口 URL **由后端返回完整地址**（部署配置的公网基址），**别用 `location.origin` 拼**（dev 下 origin 是 :3001 且 `/apps` 不在 vite 代理内）；二维码用 `qrcode.react` 走 pnpm catalog 加进 platform（`pnpm-workspace.yaml:22` 已登记 `^4.2.0`，monorepo 不引入新库）——**二维码属后置 Wave**，MVP 期只给可复制的入口链接。
- **原因**：B 满足 AC-58 的"零新增菜单 / 权限点"且四 tab 需要侧栏导航；构建页 14 处扩展点是"改既有分支"而非"新建页面"，抽两个文件是 600 行硬规逼出来的必然。
- **何时该重新考虑**：PRD-2 的造应用工作台（左侧管家对话 + 预览 / 代码 / 资源 tab）落地时，本详情页要演进为完整工作台——届时 `hostedApp/` 目录是承载点、路由与入口不变。

### D14：日志读取与保留、访问记录留痕通道

- **备选（日志）**：
  - A. **应用日志写进平台库或 ES** — 缺点：高频写放大、要给每个应用配采集器；WB-13 只要"最近的、可筛的只读日志"
  - B. **`docker logs` 直读**（json-file driver + `--log-opt max-size=10m max-file=3` 轮转）（选定）
  - C. 挂宿主日志文件让 backend 直读 — 违反 K1（backend 又要认识容器布局）
- **选定（日志）**：**B**。runtime-manager 提供 `GET /v1/apps/{app_id}/logs?tail=&since=&keyword=`（形态无关；k8s 侧换成 `kubectl logs` 等价调用）；backend `GET /api/v1/apps/{app_id}/logs` 是唯一服务方法，**三个入口（详情页 tab / CLI `logs` F053 / MCP 日志工具 F052）内容范围一致、权限各按入口口径**（详情页：owner ∪ 本租户租户管理员；MCP/CLI：仅密钥归属人 owner 的应用）——AC-23 / AC-55。**保留期 = docker 日志轮转窗口**（30MB / 应用），产品口径是"最近的运行日志"，不承诺永久留存。
- **日志里的密钥（AC-55「不出现密钥值」）**：运行日志是**应用自己打印的**，平台不做通用脱敏（那是幻觉级承诺）。可做且要做的两件：① 读取路径对**平台注入的已知敏感值**（如附件存储 token）做字面量替换为 `***`；② 密钥泄漏由**发布期扫描**兜（F055 的密钥扫描规则集）。这个口径要写进 tasks 的验收注释，别让评审误以为做了全量脱敏。
- **备选（访问记录 AC-38）**：
  - A. 写 `audit_log` — 缺点：审计表有 UI 白名单与 `operator_name` 查询开销，且访问是高频事件
  - B. **独立表 `app_access_log` + `asyncio.create_task` 异步写 + 失败吞掉 + Redis 去重窗口**（选定）
- **选定（访问记录）**：**B**（照 `llm_call_log` 的独立业务日志表范式 + `BaseTelemetryService.log_event` 的 fire-and-forget 范式）。去重：Redis `SETNX app_access:{app_id}:{user_id}` TTL = 合并窗口（默认 300s，**窗口值由 F056 定**）；**一次进入一条、不记请求级明细**。写入方是 **backend 的内部授权端点**（判定通过时顺带），不是 app-proxy 直连库。**后置 Wave**。
- **审计（AC-65 五个状态动作 + AC-06 元信息 + AC-56 数据行编辑）**：`app.*` 命名空间常量 Enum 放 `bisheng/app_runtime/domain/constants.py`（先例 `tenant/domain/constants.py:14-46`），经 `AuditLogDao.ainsert_v2`；动作清单 `app.publish` / `app.publish_pending` / `app.manual_publish` / `app.stop` / `app.resume` / `app.delete` / `app.meta_update` / `app.data_row_edit`（可见范围变更由 F056 写）。**要出现在「系统操作」页必须三处同改**：`_UI_VISIBLE_V2_ACTIONS`（`database/models/audit_log.py:178-203`）+ `_V2_NAMESPACE_TO_ACTION_PREFIX`（`:209-213`）+ platform `controllers/API/log.ts` 三处（模块下拉 / actions 数组 / `getActionsByModuleApi` switch）+ 三语 i18n。
- **原因**：B（日志）让平台侧零采集器、零存储成本，且形态无关；B（访问记录）避免把高频事件塞进操作审计表。
- **何时该重新考虑**：客户要求日志长期留存与全文检索 → 引入日志采集（Fluent Bit → ES），那时保留期承诺要重写；访问记录需要请求级明细（合规诉求）→ 那是另一个数据量级，要先做采样与分区。

### D15：MVP-核心边界（本轮做哪些 AC、哪些后置）

- **备选**：
  - A. 按 spec 65 条 AC 全量交付 — 与用户定调的预算受限冲突
  - B. **按 `mvp-114-path.md` §6 F054 行逐项裁剪**（选定）
  - C. 自行再裁（例如连详情页壳也砍）— 缺点：剧本步 8「owner 看日志、下线」就跑不通，纵切不闭环
- **选定**：**B**。逐项对照如下（tasks.md 以 `[MVP-核心]` 标记首波，其余排后但**不删**）：

| 分组 | `[MVP-核心]` 首波 | 后置 Wave（release 仍必做） |
|---|---|---|
| 领域与状态机 | AC-01～AC-08（五个状态动作 + 审计 AC-65） | — |
| 权限注册 | AC-09～AC-13（含 114 存量生效脚本） | — |
| 运行时编排 | **AC-14 编排特权（backend 零编排依赖 + 新增 arch-guard RULE-10 使"部署检查可核验"，K1）** · AC-15（**仅 `python3.11`**）· AC-17（限额 / 只读 rootfs / no-new-privileges / 注入变量）· AC-18 探活 · AC-19 容量准入 · AC-20 崩溃自愈 · AC-22 · AC-23 状态与日志只读接口 · AC-24 单实例 · AC-63 档位限额 | AC-15 的 `node20`/`static` 模板 · **AC-16 出站白名单**（D12）· AC-21 切流量的「发布中」过渡态 · AC-50 对齐窗口的自动化验收 · AC-49 双形态用例形式化 |
| 入口与注入 | AC-25 入口地址 · AC-26 免登录 · AC-27 登录回跳 · AC-28 无权限页 · AC-29 已下线 / 不存在页 · AC-30 未部署引导页 · AC-31 注入身份 · AC-32 归一化剥离 · AC-33 不可绕过 · AC-34 OBO 注入（只签发） | AC-35 WS 三不变量 · AC-36 / AC-48 两个过渡态页 · AC-37 预览入口 · AC-38 访问记录留痕 |
| 资产与生命周期 | AC-39 / AC-40 / AC-41 下线与重新上线 · AC-42 删除前置状态闸 · AC-43 显式删除 · AC-44 非 owner 拒绝 · AC-45 的**每应用数据库**部分 | AC-45 的**附件存储**与**备份手册**部分 |
| 稳定性 | AC-46 / AC-47（手动验证） | AC-49 用例的 k8s 可移植性形式化（随 F059） |
| 构建页与详情页 | AC-51 类型筛选与卡片 · AC-52 只读版本下拉 · AC-53 ⚙️ 裁剪 · AC-54 四 tab 壳（发布 tab = 应用态 + 入口链接 + 运营动作；日志 tab）· AC-55 运行日志 · AC-57 归属过滤 · AC-58 零新增菜单 | AC-54 的二维码 · **AC-56 数据 tab（WB-06）** |
| 部署开关 | AC-59～AC-62 | — |
| 档位 | AC-63（限额一致）· AC-65（上线动作） | AC-64（超管调规格 → 下次生效，依赖 F055 的档位管理 tab） |

- **原因**：裁剪判据 = **"剧本 §1 步 1–8 能不能跑通"**。凡不影响剧本闭环、且属"加固 / 完整性"的项（出站白名单、WS 不变量、过渡态、附件、数据面、留痕、二维码）后置；凡剧本必经的（状态机、权限注册、构建 + 拉起 + 探活 + 容量、入口五步判定、日志、开关）全在首波。
- **何时该重新考虑**：预算恢复（则按 §8 顺序补回，**出站白名单排第一**）；或本 Feature 要发布给 114 之外的任何环境（则 D12 与 D2-B 变成硬前置，不能再后置）。

---

## 4. 系统现状（接手必读）

> 本节写"建成后代码长什么样"。F054 尚未开工，全部为绿地。

### 4.1 数据流

**A. 发布上线（F055 调 → F054 执行）**

```
F055 管线（快照已入 MinIO）
  → AppStateService.publish(app_id, version_id)
      → orchestrator_client.admission(tier, purpose=run)        # AC-19，不足 → state=待上线(资源不足)
      → orchestrator_client.build(app_id, version_id, runtime, code_object_key)   # AC-15
      → orchestrator_client.deploy(期望态：image_ref + tier + env + volume + port + health)
      → runtime-manager: docker build → docker run(新容器) → 启动探活   # AC-18
      → 探活通过 → 路由切到新实例 → 旧容器宽限 30s 退休           # AC-21
      → AppInstance 落行 + app.state=已上线 + app.current_version_id
      → 审计 app.publish
```

**B. 用户访问（AC-25～AC-34 的主线）**

```
浏览器 GET /apps/{slug}/...
  → nginx location /apps/（变量式 upstream，error_page 回落 backend 引导页）
  → app-proxy
      ① 归一化剥离全部 x-bisheng-* 入站头                        # AC-32
      ② 查本地缓存（cookie 哈希 + slug，TTL 3s）；未命中 →
         POST /api/v1/internal/app-proxy/authorize（HMAC）
           → backend：开关 → 登录态(token_version/禁用/租户禁用) → 应用存在且曾上线
                       → check_business_action("app", id, actor, "use") → 应用态
           → 返回 {decision, headers{...}, obo_token, app_state, app_name, owner_name}
      ③ decision != allow → 自渲染兜底页 / 登录交接内联 JS 页（仅导航请求）  # AC-27~30
      ④ allow → 解析上游：查本地路由缓存（app_id，TTL 3s）；未命中 →       # D5.1
             GET /v1/apps/{app_id}/route（HMAC，问 runtime-manager）
             → {upstream: http://<bridge IP>:<port>, version_id, generation}
      ⑤ 剥 /apps/{slug} 前缀 + 重写 X-Forwarded-Prefix/Proto/Host        # D5.2 / AC-25
      ⑥ 注入 X-BiSheng-* 十个头 → 反代到 upstream（HTTP；WS 后置）        # AC-31/34
             连接失败 → 作废该条路由缓存重取一次 → 仍失败 → 「应用恢复中」页
```

**C. 下线 / 重新上线 / 删除（AC-41～AC-44）**

```
platform 卡片开关 或 详情页运营动作
  → POST /api/v1/apps/{id}/actions/{stop|resume}
      → 业务规则前置拦截（删除仅 owner；下线 owner ∪ 租户管理员 ∪ 超管代行）
      → 带前态断言的单行 UPDATE（冲突 → 16102）
      → orchestrator_client.stop / (admission → deploy 取 pending_version_id ?? current_version_id)   # AC-04
      → 审计 app.stop / app.resume（超管代行记超管本人）

DELETE /api/v1/apps/{id}                                            # AC-42~44
      → 前置状态闸（已上线 → 16104「请先下线」）+ 仅 owner（16105）
      → 带前态断言的单行 UPDATE → state=已删除
      → orchestrator_client.destroy(purge_volume=true)
      → 资产回收（MinIO 代码快照 / 库快照前缀）
      → **触发 on_app_deleted 钩子 → F055 取消在途审批单**（AC-43；F055 AC-35）
      → 审计 app.delete
```
**「通知 F055 取消在途审批单」的落点（AC-43，原设计全文缺失）**：不能让 F054 去 import F055（release-contract 的依赖方向是 F055 → F054，反向 import 是依赖倒挂；跨模块 `api/` import 还撞 RULE-5）。落点 = **F054 侧的删除事件钩子注册表** `bisheng/app_runtime/domain/services/lifecycle_hooks.py`（`register_app_deleted_hook(fn)` / `on_app_deleted(app_id, actor, tenant_id)`，注册发生在**组合根**，范式同 `build_f048_resource_composition` 的 adapter 注册），**F055 在自己的组合根注册实现**（置在途审批单为「已取消」+ 通知审批人 + 计审计，F055 AC-35）。语义：
- **同一请求内同步调用**，在应用态已置「已删除」之后；
- **钩子失败不回滚删除**（删除是终态、且资产已回收，回滚只会造出一个"态还在但资产没了"的僵尸）→ 失败即写审计 `app.delete_hook_failed` + 告警日志；
- **F055 侧必须自带防御**：审批单读侧对"应用已删除"要能独立判定并按已取消呈现，不把正确性全押在钩子送达上（这条写进 §6.1 的契约行）。

**D. 崩溃自愈（AC-20，无人干预）**

```
runtime-manager reconcile 循环（15s）
  ├ 容器缺失     → 拉起
  ├ unhealthy×2  → 重建（stop → rm → run，卷不动）
  └ 孤儿容器     → 回收
（进程退出由 docker restart policy 内置退避兜住，manager 不参与）
```

### 4.2 关键数据结构 / 字段约定（对外契约）

**① runtime-manager 意图 RPC**（backend → manager，HMAC；**语义形态无关，无 container/compose 字样**）

| 接口 | 主要入参 | 返回 | 消费者 |
|---|---|---|---|
| `POST /v1/intents/build` | `app_id, version_id, runtime, code_object_key, build_args{index_url}` | `{build_id, status}` | F055 托管预检 / 上线 |
| `GET /v1/builds/{build_id}` | — | `{status: building\|succeeded\|failed, stage, message, tail, image_ref}` | 同上（AC-15 失败原因与阶段） |
| `POST /v1/intents/deploy` | `app_id, slug, version_id, image_ref, tier{cpu,mem}, env{}, volumes[], port, health{path,interval,timeout,retries,start_period}` | `{instance_id, phase}` | 上线 / 重新上线 / 手动上线 |
| `POST /v1/intents/stop` | `app_id` | `{phase}` | 下线 |
| `POST /v1/intents/destroy` | `app_id, purge_volume: bool` | `{}` | 删除（`purge_volume=true`） |
| `POST /v1/intents/probe` | `app_id` \| `{image_ref, env, port, health}`（临时） | `{ready: bool, reason}` | AC-18；F055 预检 / 预览实例 |
| `POST /v1/admission` | `tier{cpu,mem}, purpose: run\|build` | `{admitted, reason, snapshot{mem_available_mb, committed_mb, total_mb, cpu}}` | AC-19 / AC-65 |
| `GET /v1/apps/{app_id}/route` | — | `{upstream: "http://<bridge IP>:<port>", version_id, generation}` | **app-proxy**（D5.1；唯一的数据面路由真相，切流量后 `generation+1`） |
| `GET /v1/apps/{app_id}/status` | — | `{instance_id, phase, health, current_version_id, started_at, restart_count, last_probe_at}` | AC-23 |
| `GET /v1/apps/{app_id}/db/tables` · `/tables/{t}/schema` · `/tables/{t}/rows` · `PATCH /tables/{t}/rows/{pk}` · `GET /db/export` | 分页 / 排序 / 单行 patch | 表清单 / 表结构 / 行数据 / 导出文件（**无 DDL**） | AC-56 数据 tab · F052 MCP 数据工具（**均经 backend `AppDataService`，不得直连**）——**后置 Wave**（D10） |
| `GET /v1/apps/{app_id}/logs` | `tail, since, keyword` | `{lines[]}` | AC-23 / AC-55 / F052 / F053 |
| `GET /v1/runtime/status` | — | `{backend_available, supported_runtimes[], capacity{...}, preflight[]}` | AC-23 运行环境状态（超管） |

`phase` 取值：`pending \| building \| starting \| running \| unhealthy \| stopped \| failed`（形态无关）。

**② 状态动作接口**（backend 对内 / 对前端；应用态**唯一写入方**）

| 接口 | 语义 | 谁在调 |
|---|---|---|
| `POST /api/v1/apps/{app_id}/actions/publish` | 上线（容量准入 → 拉起 → 切流量；不足 → 待上线） | F055 上线终检（AC-65） |
| `POST /api/v1/apps/{app_id}/actions/manual-publish` | 手动上线（无需重审） | F055 发布面（AC-32 of F055） |
| `POST /api/v1/apps/{app_id}/actions/stop` | 下线（二次确认在前端） | 卡片开关 / 详情页 |
| `POST /api/v1/apps/{app_id}/actions/resume` | 重新上线（叠加容量准入） | 卡片开关 / 详情页 |
| `DELETE /api/v1/apps/{app_id}` | 显式删除（前置状态闸 + 仅 owner；末尾触发 `on_app_deleted` 钩子 → F055 取消在途审批单，AC-43） | 卡片 ⚙️ / 详情页危险操作区 |
| `PATCH /api/v1/apps/{app_id}` | **元信息更新**（名称 / 描述 / 图标）：**不改应用态、不产生版本记录、计审计 `app.meta_update`**（AC-06） | platform 详情页 · **F055**（release-contract「元信息随 deploy 更新」= 管线调同一方法，不另写一份） |
| Python：`AppProvisionService.create_draft(name, slug, description, owner_user_id, tenant_id) -> app_id` | **建应用**（落 `app` 行 `state=draft` + F048 owner 投影）——首发的唯一入口 | F055 首发（决议-8：F055 不直写 `app` 表）|
| Python：`AppStateService.{publish,manual_publish,stop,resume,delete}` | 五个状态动作 | F055 **只调不直写**（决议-8） |
| Python：`AppStateService.stage_version(app_id, version_id)` | 落**已审批待运行版本**（写 `app.pending_version_id`，**不改应用态**）——AC-04 的落点 | F055 审批通过节点 |
| Python：`AppMetaService.update_meta(*, app_id, name, description, logo, actor=None)` | AC-06 的**唯一实现**（HTTP 与 F055 管线共用）；`logo` 存 **object_name** 不是预签 URL；`actor` 可空＝管线调用（归属已在 F055 侧校验） | 详情页 · F055 |

其余读接口：`GET /api/v1/apps/{app_id}`（详情，含 `entry_url`）· `GET /api/v1/apps/{app_id}/instance`（状态 / 健康 / 当前版本）· **`GET /api/v1/apps/{app_id}/versions`**（只读版本列表，`[{version_id, version_no, kind, terminal_state, submitted_at, is_current, is_pending}]` 按 `version_no` 倒序，**无切换 / 无回滚写口**——卡片下拉、版本 tab、CLI 三处共用这一个路径与形状）· **`GET /api/v1/apps`**（AC-57：owner 看自己 owner 的、租户管理员看本租户全部；与构建页 UNION 列表是两条路，后者走 `/api/v1/flows` 的既有分页管线）· `GET /api/v1/apps/{app_id}/logs` · `GET /api/v1/apps/runtime-status`（超管）· `GET /api/v1/apps/_unavailable`（nginx error_page 回落的引导页 HTML）· 内部 `POST /api/v1/internal/app-proxy/authorize`（HMAC，加入 `TENANT_CHECK_EXEMPT_PATHS`，handler 内 `bypass_tenant_filter`）。**该端点只回判定与身份材料，刻意不含目标实例地址**——上游解析是 app-proxy ↔ runtime-manager 的独立通道（D5.1），两者缓存节奏不同（鉴权跟权限走、路由跟发布走），合并会让"改权限"和"切版本"互相踩。

**③ app-proxy 注入头**（INV-32；**F053 `bisheng dev` 迷你代理注入同一套**）

| 头名 | 值 / 格式 | 说明 |
|---|---|---|
| `X-BiSheng-User-Id` | 十进制整数字符串 | 平台 user_id |
| `X-BiSheng-User-Name` | **UTF-8 percent-encoded** | 中文姓名必须编码（坑 9） |
| `X-BiSheng-Tenant-Id` | 十进制整数字符串 | |
| `X-BiSheng-Dept-Id` | `BS@xxx` 业务键 | `Department.dept_id`，**不是自增 id** |
| `X-BiSheng-Dept-Name` / `X-BiSheng-Dept-Path` | **UTF-8 percent-encoded** | 主部门（`is_primary==1`） |
| `X-BiSheng-Subject-Kind` | `human` \| `service_account` | AC-31 要求的主体类型 |
| `X-BiSheng-App-Id` | str | 应用标识（内部 id） |
| `X-BiSheng-Access-Token` | OBO JWT（HS256，`aud=bisheng-app-obo`，TTL 900s） | AC-34；本期无消费方 |
| `X-BiSheng-Request-Id` | uuid4 | 贯穿 app-proxy → 应用 → 平台日志 |
| `X-Forwarded-Prefix` | `/apps/{slug}` | **D5.2**：app-proxy 已剥掉该前缀，应用 / 框架据此生成带前缀的绝对 URL |
| `X-Forwarded-Proto` / `X-Forwarded-Host` | 外部访问的协议与主机 | 同上；**必须由 app-proxy 重写，不得透传客户端值**（否则应用会用伪造 Host 生成外链 / 重定向） |

**剥离规则**：入站头 name 经 `lower()` + `_`→`-` 归一后凡以 `x-bisheng-` 开头**一律丢弃**（AC-32）；`x-forwarded-*` 三个头**不在该等价类里**，但同样先丢客户端值再由 app-proxy 写入（D5.2）。

**④ `bisheng-app.yaml` 中本 Feature 消费的字段**（**形态归 F055**，本 Feature 只消费）

`name` / `description` / `icon`（→ `app` 元信息）· `runtime`（→ Dockerfile 模板选择，AC-15）· `port`（→ 容器监听端口与探活目标）· `tier`（→ 档位限额，AC-63）· `egress.domains`（→ 出站白名单，D12 后置）。**应用标识 `slug` 若声明则以声明为准、未声明由平台按名称生成**（AC-08）。

**⑤ 注入给应用的环境变量**（本 Feature 定名，F053 `dev` 同名注入）

| 变量 | 值 | 备注 |
|---|---|---|
| `BISHENG_APP_DB_URL` | `sqlite:////data/app.db` | AC-45「与 `bisheng dev` 同名」 |
| `BISHENG_APP_DB_PATH` | `/data/app.db` | |
| `BISHENG_APP_ID` / `BISHENG_APP_SLUG` / `BISHENG_APP_VERSION` | str | |
| `BISHENG_PLATFORM_API_BASE` | 平台 API 基址 | 供 SDK / 能力总线（后续） |
| `PORT` / `BISHENG_APP_PORT` | int | 与 manifest `port` 一致 |
| `BISHENG_APP_BASE_PATH` | 线上 `/apps/{slug}`；**F053 `bisheng dev` 注入同名变量、值为空串** | **D5.2**：模板 wrapper 把它接到框架 base path（FastAPI `root_path` / Streamlit `--server.baseUrlPath`）。INV-32 的"同构"= **变量名与语义同构**，不是取值相同 |
| `BISHENG_APP_STORAGE_*` | 附件句柄 | **后置 Wave** |

**⑥ 错误码段 161**（`bisheng/common/errcode/app_factory.py`；落码同 PR 回写 constitution C5 + 三语 `api_errors`）

| 段 | 用途 | 示例 |
|---|---|---|
| 16100–16119 | 领域 / 状态机 | `16101` 应用不存在 · `16102` 状态冲突（前态不符）· `16103` slug 冲突 · `16104` 已上线不可删除（请先下线）· `16105` **仅** owner 可执行（删除 / 数据 tab，租户管理员也拒）· `16106` owner ∪ 租户管理员 ∪ 超管之外（下线 / 重新上线 / 改元信息 / 运行环境状态）——两者不可合并，否则会告诉一个**有权限**的租户管理员「只有负责人能做」 |
| 16120–16139 | 运行时 / 编排 | `16121` 编排器不可用 · `16122` 构建失败 · `16123` `runtime` 取值不支持 · `16124` 启动探活失败 · `16125` 运行环境容量不足 |
| 16140–16159 | 入口 / 注入 | `16141` 未登录 · `16142` 无访问权限 · `16143` 应用已下线 · `16144` 应用不存在或未上线 · `16145` 工场未启用 · `16146` 权限引擎不可用（fail-closed） |
| 16160–16179 | 数据面 / 日志 | `16161` 无权查看日志 · `16162` 无权访问应用数据（后置） |
| 16180–16199 | 部署开关 / 运维 | `16181` 工场运行时层未部署 |

**⑦ `/api/v1/env` 新增字段**：`app_runtime_enabled: bool`（匿名可读）→ platform `appConfig.appRuntimeEnabled`（`contexts/locationContext.tsx:75-92` + `types/api/app.ts`）· client `BishengConfig.app_runtime_enabled`（`@types/chat.ts:102`；**client 新读取 hook 不得 import recoil**——lint 冻结，用 react-query v4 拉 `/api/v1/env`）。

**⑧ systemd 单元名与端口约定**（114 / bisheng-ops 仓）：`bisheng-runtime-manager.service`（`127.0.0.1:8091`，`After=docker.service`，以 root 或 docker 组运行）· `bisheng-app-proxy.service`（`127.0.0.1:8090`，`After=bisheng-api.service`，**不需要 docker 权限**）；两者追加进 `bisheng.target` 的 `Wants=` 与 `deploy.sh` 的 `SERVICES=`。compose 形态对应两个 service，建议用 profile 表达「整层不装」（仓内无 profiles 先例，`docker/deploy.sh` 需加 `--profile`）。

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `bisheng/database/models/{app,app_version,app_instance,app_access_log}.py` | 三张表 + 访问记录表的 SQLModel 定义与 DAO | **不放 `app_runtime/domain/models/`**——UNION 第三支要在 `database/models/flow.py` 里 import 它，放 domain 即触 arch-guard **RULE-2**（论证与被否方案见 D8「模型落点」）；不含业务逻辑；**四个模块路径必须登记进 `core/database/tenant_filter.py:39`**（`app_version` 无 `tenant_id`、登记后仍不受自动过滤，K5 ②） |
| `bisheng/app_runtime/domain/services/app_provision_service.py` | **建应用**：slug 解析（声明冲突拒 16103 / 生成的加后缀）+ 落 `app` 行 + F048 owner 投影（AC-11） | 不碰应用态（创建不是迁移，故不在 `AppStateService` 内）；不写版本记录 |
| `bisheng/app_runtime/domain/services/app_state_service.py` | **五个状态动作的唯一实现**（上线 / 手动上线 / 下线 / 重新上线 / 删除）+ `stage_version`（待运行版本，AC-04）+ 前态断言 + 审计 | 不直连 docker；不做审批（F055）；不做可见范围授权（F056 交互，本模块只经 F048 runtime） |
| `bisheng/app_runtime/domain/services/app_meta_service.py` | **AC-06 元信息更新的唯一实现**（名称 / 描述 / 图标 → 不改态、不产版本、计审计 `app.meta_update`） | 不碰应用态；不产生 `app_version` 行；F055 的「元信息随 deploy 更新」调它而非自己写库 |
| `bisheng/app_runtime/domain/services/app_data_service.py` | AC-56 数据面的 backend 侧唯一服务方（owner 收窄 + 审计 + 转发给 manager 数据面 RPC）——**后置 Wave** | 不直接打开宿主库文件（K1 / 多节点，D10） |
| `bisheng/app_runtime/domain/services/lifecycle_hooks.py` | 删除事件钩子注册表（`register_app_deleted_hook` / `on_app_deleted`），F055 在组合根注册取消在途审批单 | 不 import F055（依赖方向是 F055 → F054） |
| `bisheng/app_runtime/domain/services/app_query_service.py` | 详情 / 实例状态 / 日志 / 运行环境状态的读侧；三入口权限口径分派 | 不写库 |
| `bisheng/app_runtime/domain/services/orchestrator_client.py` | runtime-manager 的薄 HTTP 客户端（HMAC + 超时 + 重试） | **绝不 import docker**；不含编排语义判断 |
| `bisheng/app_runtime/domain/services/f048_app_permission.py` | F048 Loader + Adapter（`app` 资源类型） | 不 import OpenFGA（RULE-9）；不做业务规则前置拦截 |
| `bisheng/app_runtime/domain/services/entry_authz_service.py` | 入口五步判定（供内部授权端点），签发 OBO | 不反代、不渲染页面 |
| `bisheng/app_runtime/domain/constants.py` | `app.*` 审计动作 Enum、状态枚举、默认档位兜底表 | — |
| `bisheng/app_runtime/api/endpoints/{apps,internal_app_proxy}.py` | 状态动作 / 读接口 / 内部授权端点 / `_unavailable` 引导页 | 不直接 import `database/models`（RULE-3 迁移期） |
| `src/runtime-manager/`（**独立包**，仓根） | 构建 / 生命周期 / 探活 / 容量准入 / 日志 / reconcile / **路由表（`GET /v1/apps/{id}/route`，D5.1）** / **数据面 RPC（AC-56，后置）**；**唯一持编排后端访问** | 不认识平台业务（无 DB / 无 FGA / 不认识 owner 与权限）；对外接口不暴露 compose 概念 |
| `src/app-proxy/`（**独立包**，仓根） | 归一化剥离 → 问 backend 判定（缓存 3s）→ **问 manager 取 upstream（另一把 3s 缓存，D5.1）** → 剥 `/apps/{slug}` 前缀并重写 `X-Forwarded-*`（D5.2）→ 注入 → 反代；自渲染兜底页与登录交接页 | **不 import `bisheng` 包**；不做权限判定（问 backend）；不签 OBO（backend 签）；不自己发现容器（问 manager） |
| `src/backend/scripts/upgrade_f048_authorization_model.py` | 存量环境 `app` 类型生效三件套（dry-run / `--apply` / `verify`） | 不做 legacy→F048 迁移（那是 `migrate_f048_permission_data.py`） |
| `platform/src/pages/BuildPage/apps.tsx` | 列表骨架 + 三类型分派 | 托管应用卡片装配与动作**抽走**（600 行硬规） |
| `platform/src/pages/BuildPage/HostedAppCard.tsx` · `useHostedAppActions.ts` | 卡片 props 装配；下线 / 重新上线 / 删除三动作 + 确认文案 | 卡片与详情页**共用**，不许两份文案 |
| `platform/src/pages/BuildPage/hostedApp/**` | 详情页四 tab 壳（发布 / 数据 / 运行日志 / 版本） | 发布 tab 内容归 F055、可见范围区归 F056（slot 留位） |
| `platform/src/controllers/API/hostedApp.ts` | 全部 HTTP 封装 | 不 import axios（C7） |

---

## 5. 已知坑 / 反直觉事实

> 代码里看不出、踩过才知道的东西。每条带"如果不知道会怎样"与"在哪处理"。

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | **`MIGRATED_RESOURCE_TYPES` 有两份且都被消费**：`core/openfga/authorization_model_f048.py:32-42`（生成 OpenFGA 模型）与 `permission/domain/services/catalog_policy.py:31-43`（校验 Catalog 行） | 漏前者 → 模型里没有 `app` type，写 tuple 400；漏后者 → `derive_action_release` 在每次 `_load_snapshot` 都跑，**Catalog 读取直接崩** | D9 的 8 处清单第 1、3 项，同一 PR 改 |
| 2 | **`grant_subjects.py:28-40 GRANT_SUBJECT_RESOURCE_TYPES` 是 baseline「12 处」之外的活闸门**（**5 个端点 / 5 处**入口硬闸 :89/:113/:135/:152/**:168**——第 5 处 `departments/{dept_id}/path-tree` 最易漏） | 授权弹窗能打开、但选人 / 选部门 / 选用户组**一个都搜不到**，且报的是 PermissionDenied 不指向类型 | D9 第 8 项；配套测试 `test/permission/test_f048_grant_subjects.py:37-49` |
| 3 | **`force_write_model=true` 不能当升级手段**：只写 OpenFGA 不写 SQL、`_resolve_model` 在 force 模式**不查重**（每次重启多写一个重复 model）、生产环境直接禁用；且 `_refresh_catalog_runtime` 仍会因 SQL pin 不匹配判 `catalog_pin_mismatch` | 以为"打开开关重启就行"，结果 store 被灌满重复 model 且权限运行时仍 not-ready | D9 的升级脚本；脚本以 **checksum** 定位模型而非"取最新" |
| 4 | **SQL 三件套改完必须全进程重启**（API / celery×3 / beat / linsight worker）：心跳每 15s 复核、TTL 45s，旧进程会在 ≤15s 内自行 fail-closed | 只重启 API，后台任务里的 `check_business_action` 全抛 `PermissionPublishNotReadyError` —— 表现为"工具执行 / 技能静默失败"（既有教训） | 升级说明（AC-13）；114 用 `bash /opt/bisheng-ops/deploy.sh` 全量重启 |
| 5 | **`permission_schema.VALID_RESOURCE_TYPES`、`authorization_model_f048.RESOURCE_ACTION_SCOPES`、`core/openfga/authorization_model.py` 全是死代码**（零消费者 / 只被 test 引用） | 把工时花在它们上；更糟的是在评审里拿它们当"已改完"的锚点 | D9 明确「不改」清单 |
| 6 | **CardComponent 的"删除"是 `!checked && onDelete` 整项不渲染**（`cardComponent/index.tsx:239-244`），不是置灰 | AC-42「已上线置灰 + 提示请先下线」照现状实现会变成"看不见"，验收不过 | D13 新增 `deleteDisabledHint` prop，**保持 workflow/assistant 现行为** |
| 7 | **`handleOpenPermission` 的 `typeMap = {5:'assistant',10:'workflow'}` 默认回落 `'workflow'`**（`apps.tsx:215-219`） | 不补映射 → 托管应用卡片对着 **workflow 类型**开授权弹窗，registry 校验 record 类型不符 → 19003，且现象是"弹窗打开但一片红" | D13 扩展点第 6 项 |
| 8 | **`getAppsApi` 只放行 `status ∈ {1,2}`**（`controllers/API/flow.ts:204`）+ 后端 `sub_query.c.status == status`（`flow.py:568`） | 把应用态五值硬塞进 `status` 会与工作流"上线/下线"撞语义，且前端第一道就把值滤掉 | D8：`status` 投影为 2/1 复用既有开关；五值走**新参数 `app_state`** |
| 9 | **HTTP 头是 latin-1**：中文姓名 / 部门名直接放头会被 uvicorn/h11 拒或乱码 | 应用侧读到乱码或 app-proxy 转发时 500 —— 而且只在有中文名的用户身上复现，测试账号常是英文名，**极易漏测** | D6：三个头 UTF-8 percent-encoding；§7 必须用中文名账号验一遍 |
| 10 | **只按精确头名剥离等于没剥离**（oauth2-proxy CVE-2025-64484，CVSS 8.5）：WSGI/ASGI 把 `X_BiSheng_User_Id` 与 `X-BiSheng-User-Id` 归一到同一个 `HTTP_X_BISHENG_USER_ID` | 攻击者用下划线变体伪造身份头，应用侧读到的就是伪造值 —— **越权且无痕** | D6 归一化等价类剥离；单测必须覆盖下划线 / 大小写 / 混合变体 |
| 11 | **服务端 302 拿不到 hash，平台登录页也不认 `?redirect=`**：回跳只认 `localStorage.LOGIN_PATHNAME` + `LOGIN_PATHNAME_AT`（一次性 + 10 分钟 + 同源校验） | 手机扫码带参数的链接登录后丢参数，应用打开即空白（AC-27 验收不过） | D7 的内联 JS 交接页；键名 / 时效 / 同源校验必须原样复刻 |
| 12 | **`SelectType` 组件被模板页复用**（`appTemps.tsx:82` `navigate('/build/temps/${v}')`） | 直接加「托管应用」选项 → 模板管理页出现一个点了会 404 的类型 | D13：加条件 prop（如 `includeHosted`），且只在 `appRuntimeEnabled` 时给 |
| 13 | **`CardSelectVersion` 的切换会调 `changeWorkflowCurrentVersion`**（`CardSelectVersion.tsx:23-31`），而 `add_extra_field` 的 `version_list` 来自 `FlowVersionDao.get_list_by_flow_ids`（`services/workflow.py:112`） | 托管应用卡片直接复用 → 版本下拉一点就去改**工作流**的当前版本；且 `version_list` 恒为空 | D8/D13：app 版本源另给；版本下拉换**只读**组件（AC-52） |
| 14 | **nginx 在 config load 时解析静态 `proxy_pass` 主机名**：`profiles` 未启动 → 容器名不可解析 → **nginx 起不来**（不是 502，是整个前端挂） | "整层可不装"与"静态 conf"直接冲突，客户升级后前端白屏 | D5：变量式 upstream + `resolver` 延迟解析 + `error_page` 回落 |
| 15 | **`/apps/*` 无 location 时会落到 platform SPA 的 `index.html`**（`location /` 的 `try_files … /index.html`），已登录 → `/404`、未登录 → 登录页 | AC-30「未部署也要出引导页、不返回 404/5xx」在默认路径上就不成立 | D5：platform SPA 加 `apps/*` 路由（public + private 两表），零 nginx 变更 |
| 16 | **nginx conf 在仓内有 4 份、生产只认 2 份**：`docker/nginx/conf.d/default.conf`（compose 挂载，权威）与 `src/frontend/nginx.conf`（镜像内置同构）**必须同时改**；`platform/nginx.conf` / `client/nginx.conf` 是历史残留。114 的两份在**仓外**（bisheng-ops / `/etc/nginx/conf.d/`） | 只改一份 → 客户没挂载 conf 的部署形态下 `/apps/` 404；只改产品仓 → 114 上根本不生效 | D5 / K10；tasks 的部署脚本增量任务 |
| 17 | **docker 单机的 healthcheck 与 restart policy 无联动**：容器 unhealthy 会一直 unhealthy 地活着 | 以为"配了 healthcheck 就会自愈"，AC-20 的第二类故障（存活但不健康）永远不恢复 | D4：reconciler 补 unhealthy-but-alive 重建 |
| 18 | **`.drone.yml` 是全仓唯一出现 `docker.sock` 的地方**（:57/:89/:173/:224/:259/:316，CI 用） | 加 RULE-10 时若不排除 CI 配置，守卫会对 `.drone.yml` 报假阳性、被人顺手关掉 | RULE-10 只扫 `src/backend/bisheng/**` 的 `.py` |
| 19 | **裸 tar 一个 WAL 模式的 SQLite 库会得到不一致副本**（`-wal` / `-shm` 与主库不同步） | 备份看起来成功，恢复时数据丢最近的写或直接 corrupt —— 且只在有并发写时复现 | D10：先 `.backup` / `VACUUM INTO` 出一致副本再 tar |
| 20 | **`bisheng` 公共桶不是整桶匿名读**（匿名策略只覆盖两个 images 前缀），但 **nginx `/bisheng/` 会把任意 key 转发给 MinIO** | 把应用附件 / 代码快照放进公共桶 → 只差一个知道 key 的人就能拉走全部应用源码 | D10：独立 bucket `bisheng-apps`，不挂 nginx location、不设匿名策略 |
| 21 | **`_build_apps_subquery` 的租户自动过滤对 subquery 失效**（docstring `flow.py:661-671` 明写），三支各自手工注入 | 第三支忘了注入 → **跨租户能看到别家的托管应用**（且列表接口是普通用户可达的） | D8 / K5；`_TENANT_AWARE_MODEL_MODULES` 同批登记 |
| 22 | **Docker 29 起 nftables 后端没有 `DOCKER-USER` 链** | 出站白名单的 L2 兜底静默失效（规则下发"成功"但不生效） | D12：manager 探测后端分别下发，或部署基线锁定 iptables |
| 23 | **`load_settings_from_yaml` 对未知顶层键直接 `KeyError` 拒启**（`common/services/config_service.py:91-107`） | 先往 `config.yaml` 加 `app_runtime:` 再发代码 → **后端起不来**（且现象是启动即崩、不是功能不可用） | K12：先发代码、后加键；114 升级步骤里写死顺序 |
| 24 | **`llm_call_log` 式的独立业务日志表 ≠ `audit_log`**：v2 审计 action 不在 `_UI_VISIBLE_V2_ACTIONS`（`audit_log.py:178-203`）白名单里会**写库但不出现在「系统操作」页** | AC-65「五个动作均计审计」代码写了、审计页看不到，验收时被判不通过 | D14：三处白名单 + platform `log.ts` 三处 + 三语 i18n 同 PR |
| 25 | **platform 拦截器对 GET 的 `status_code ∈ {403,404}` 会整页跳 `/403` / `/404`**（`controllers/request.ts:160-166`） | 详情页 / 日志 / 数据接口对非 owner 返回 403 → 用户被甩出页面，而不是看到"无权限"提示 | D13：用业务码 161xx 或 `silent: true` |
| 26 | **114 是多租户环境**（`multi_tenant.enabled: true`），且 **admin 会短路 ReBAC** | 用 admin 验证"可见范围生效"会全绿，实际普通用户进不去（memory 反复踩过） | §7：步 6 必须用**非管理员**账号；health 200 不能当证据 |
| 27 | **`database/models/flow.py` import `app_runtime.domain.models` 会被 arch-guard RULE-2 当场判 VIOLATION**（:37-45；条件 = 路径含 `/database/models/` ∧ `^(from\|import) bisheng\.[a-z_]+\.domain\.`），而 UNION 第三支非写在该文件不可 | 按"新模块模型放 domain/models"的直觉落笔，第一次 Write 就被 PostToolUse hook 打回；改成 `# noqa` 式绕过则是把守卫关掉 | D8「模型落点」：三张表落 `database/models/`，`app_runtime/` 只留 services + api |
| 28 | **`_FLOW_TYPE_TO_RESOURCE_TYPE` / `SUPPORTED_APP_TYPES` 这组闸门失败时全是"空列表"，不报错**（`workflow.py:198 / :514 / :592` 直接 `return [], False`） | 只加了 UNION 第三支就去点前端，看到空列表 → 先怀疑权限、再怀疑租户、最后才想到类型白名单；AC-51 / AC-57 卡在这里 | D8「后端 6 组硬闸」第 1–3 项 |
| 29 | **托管的应用在 `/apps/{slug}` 前缀下，根绝对路径静态资源必 404**（`/static/*`、`fetch('/api/x')`、`Location: /`），而同一份代码在 `bisheng dev` 下跑在根路径 | 本地跑得好好的应用一上线就"页面白板 / 样式全丢"，且只在有静态资源的应用上复现 | D5.2：剥前缀 + `X-Forwarded-Prefix` + `BISHENG_APP_BASE_PATH` → 框架 root_path；手写根绝对路径写进 DEV-04 运行契约（平台不做 HTML 重写） |
| 30 | **114 上 app-proxy 是宿主 systemd 单元、不在 docker 网络里** → 容器名 / docker DNS 解析不了，而 AC-33 又禁 publish 端口 | 照 compose 直觉写 `proxy_pass http://bisheng-app-{slug}` → 114 上永远连不上，且现象是 DNS 失败不是 502 | D5.1：manager 出 `GET /v1/apps/{id}/route` 给 bridge IP:port（宿主可达、外部不可达），两形态同一机制 |
| 31 | **`app_version` 没有 `tenant_id` 列**，登记进 `_TENANT_AWARE_MODEL_MODULES` 也**不会**被自动过滤（`_discover_tenant_aware_tables` 只纳入有该列的表） | 以为"登记了就安全"，写一个按 `version_id` 起手的读接口 → 跨租户读到别家版本记录与 `code_object_key`（等于源码对象键泄漏） | K5 ②/ D8：一切按 `version_id` 起手的读写先取 `app` 行校验归属 |
| 32 | **`linsight_skill` 是"注册了一半"的反面样板**（模型有、`FIXED_CUSTOM_TYPES` 有、前端 union 有，但 registry / Catalog scope / grant_subjects 全无） | 照抄它 → `app` 能创建、能投影 owner，但任何 `check_business_action("app")` 抛 `InvalidCatalogActionError`，入口访问永远拒绝 | D9 明确走 `MIGRATED_RESOURCE_TYPES` 全适配器路线 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `AppStateService.{publish, manual_publish, stop, resume, delete}` + 对应 `POST /api/v1/apps/{id}/actions/*` | 内部 Python API + HTTP | **F055**（管线在审批通过 / 手动上线时调用；决议-8：只调不直写）· platform 卡片与详情页 |
| `AppStateService.stage_version(app_id, version_id)`（落已审批待运行版本，写 `app.pending_version_id`、不改应用态；`resume` / `publish` 取 `pending ?? current`） | 内部 Python API | **F055**（审批通过节点；AC-04「已下线态可落新版本但不自动启用」的唯一落点） |
| `AppMetaService.update_meta` + `PATCH /api/v1/apps/{app_id}`（不改态 / 不产版本 / 计审计 `app.meta_update`，AC-06） | 内部 Python API + HTTP | **F055**（release-contract「元信息随 deploy 更新」调它，**不另写一份**）· platform 详情页 |
| **删除事件钩子** `lifecycle_hooks.register_app_deleted_hook(fn)` → 删除动作末尾同步 `on_app_deleted(app_id, actor, tenant_id)`（AC-43） | 内部 Python 回调（**F055 在组合根注册**） | **F055**（收到即取消在途审批单 → 已取消 + 通知审批人，F055 AC-35）。**钩子失败不回滚删除**（写 `app.delete_hook_failed` 审计）→ **F055 侧必须自带防御**：审批单读侧对"应用已删除"独立判定并按已取消呈现 |
| `DEFAULT_TIERS` 三档出厂规格常量（轻量 **1C/2G** · 标准 **2C/4G** · 性能 **4C/8G**；数值与第三档名以 F055 spec AC-44 为准，2026-08-17 由 F055 T015 回写，坑 27） | 内部 Python 常量 | **F055** 的 `ResourceTier` seed **从本常量读取落库**（保证"表未落"与"表刚 seed"两个时刻规格恒等，D11 对账口径）；超管调整后以表为准 |
| runtime-manager 意图 RPC（§4.2 ①）经 `orchestrator_client` 暴露的 Python 门面：`build / deploy / stop / destroy / probe / admission / status / logs / runtime_status` | 内部 Python API | **F055**（托管预检、上线终检、预览实例）· **F059**（同一门面换 k8s 后端，INV-33） |
| `GET /api/v1/apps/{id}/logs`（三入口同一服务方法、内容范围一致） | HTTP + Python | 详情页运行日志 tab · **F053** CLI `logs` · **F052** MCP 日志工具 |
| `GET /api/v1/apps/{id}/instance`、`GET /api/v1/apps/runtime-status` | HTTP | **F052** MCP 应用状态工具 · 超管运行环境状态 |
| 每应用数据库服务端接口（表清单 / 表结构 / 行数据读写 / 导出，**不含 DDL**）——**落点已定**：backend `AppDataService`（owner 收窄 + 审计）→ `orchestrator_client` → **runtime-manager 数据面 RPC**（它与库文件同机；backend 直读宿主库文件违反 K1 且多节点下必错，同 D14 否决 C 的论证，见 D10） | HTTP（backend）+ 意图 RPC（manager） | 详情页数据 tab（AC-56）· **F052** MCP 应用数据工具（**经同一 backend 方法**、同 owner 收窄、写入同样计审计，**不得直连 manager**）——**后置 Wave** |
| **注入头集合** `X-BiSheng-*` + `X-Forwarded-Prefix/Proto/Host`（§4.2 ③） | HTTP 头契约 | 托管应用本体 · **F053**（`bisheng dev` 迷你代理注入同一套；`dev` 在根路径运行 → `X-Forwarded-Prefix` 为空）· **F057** SDK auth · INV-32 |
| **注入环境变量名** `BISHENG_APP_DB_URL` / `BISHENG_APP_DB_PATH` / `BISHENG_APP_ID` / `BISHENG_APP_SLUG` / `BISHENG_PLATFORM_API_BASE` / `PORT` / **`BISHENG_APP_BASE_PATH`**（§4.2 ⑤） | 环境变量契约 | 托管应用本体 · **F053**（`dev` 同名注入，AC-45；`BISHENG_APP_BASE_PATH` 值为空串——同构指**名与语义**，不是取值，D5.2）· **F057** SDK storage（后置） |
| `app` **资源类型**（F048 注册 + `use/edit/manage_permission/delete/publish/unpublish` 动作集） | 权限体系扩展点 | **F056** 授权交互与广场过滤 · platform `PermissionDialog` · client `PermissionDialog`（F056） |
| 预览入口路由（`/apps/preview/{session}`，仅审批人可达、注入审批人身份） | HTTP 路由 | **F055**（AC-26～28 调用；实例生命周期归 F055）——**后置 Wave** |
| `app.*` 审计事件（`app.publish` / `publish_pending` / `manual_publish` / `stop` / `resume` / `delete` / `meta_update` / `data_row_edit`） | 审计事件 | **F056** 审计查询面（登记 + 查询归它，写入归本 Feature） |
| `GET /api/v1/env.app_runtime_enabled`（+ `settings.app_runtime.enabled`） | 部署开关 | platform 构建页 / 详情页 · **F056** 广场 · 引导页（AC-62） |
| `FlowType=35` + UNION 第三支 + `app_state` 查询参数 + `SUPPORTED_APP_TYPES` / `_FLOW_TYPE_TO_RESOURCE_TYPE` 放行 + `ResourceTypeEnum.HOSTED_APP=10`（标签体系）——**后端 6 组硬闸清单见 D8** | 列表契约 | platform 构建页 · **F056** 广场（`get_online_flows_page` `workflow.py:514` 同一道 `SUPPORTED_APP_TYPES` 闸，F056 直接受益，不要重复改） |
| systemd 单元 / compose service / nginx location 三份部署增量 | 部署契约 | 运维（bisheng-ops 仓）· `docker/deploy.sh` 的 `ALL_SERVICES` |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| **F048 权限运行时**：`check_business_action` / `require_business_action` / `batch_check_business_actions`、`runtime.authorize_created` / `project_delete`、`build_f048_resource_composition` | 内部 Python API + 注册点 | 注册点签名或 adapter 协议变化 → `app` 判权直接抛；Catalog / 模型 checksum 机制变化 → 升级脚本作废（D9） |
| **F049**：资源归属人语义（CLI 首发应用的 owner = 密钥所属服务账号的资源归属人）、`app:manage` 位 | 语义契约 | owner 写入方是 F055；若 F049 的归属人语义改成"可追溯变更"，AC-07「不因归属人后续变更而追溯改变」要重议 |
| **F055**：`bisheng-app.yaml` 形态（`runtime` / `port` / `tier` / `egress.domains`）、`ResourceTier` 实体、版本记录的写入时机 | 数据契约 | manifest 字段改名 → 构建与拉起静默取到 None；`ResourceTier` 表未落时靠 D11 的兜底常量（MVP 期常态） |
| 平台会话：`access_token_cookie`（HS256、`sub/exp/iss`）、`token_version`（Redis `user:{id}:token_version` → DB）、账号禁用、`DISABLED_TENANT_KEY` | 隐式数据契约 | cookie 名 / 属性 / payload 结构变化 → app-proxy 免登录失效；`CookieConf.domain` 若改成非 host-only，同源前提要重估 |
| 跨 SPA 登录回跳契约：`localStorage.LOGIN_PATHNAME` + `LOGIN_PATHNAME_AT`（一次性 / 10 分钟 / 同源校验） | 隐式前端契约 | platform 改消费逻辑（`loginReturnTo.ts` / `login.tsx` / `App.tsx`）→ 扫码登录回跳静默失效（坑 11） |
| 部门信息：`UserDepartmentDao.aget_user_primary_department`、`Department.dept_id`（业务键）/ `path` | 内部 Python API | `user_department` 表**无 tenant_id**、`department` 表有 → 独立进程读需上下文或 `bypass_tenant_filter` |
| MinIO：`MinioStorage`（`put_object` / `get_object` / `copy_object` / `get_share_link`），新桶 `bisheng-apps` | 基础设施 | `_init_bucket_conf` 只在 NoSuchBucketPolicy 时写策略 → 存量环境不会被收窄（坑 20） |
| 审计：`AuditLogDao.ainsert_v2` + `_UI_VISIBLE_V2_ACTIONS` / `_V2_NAMESPACE_TO_ACTION_PREFIX` | 内部 API + 白名单 | 白名单未加 `app` → 写库但审计页看不到（坑 24） |
| 构建页与卡片组件：`apps.tsx`、`CardComponent`、`CardSelectVersion`、`PermissionDialog`、`useResourceActions`、`bs-ui/*` | 前端组件 | `CardComponent` 是**共享组件**，改它会影响 workflow / assistant（回归归 F056） |
| **docker daemon**（compose 形态）+ `nproc` / `/proc/meminfo` | 系统依赖 | daemon 不可用 → 全部编排接口 `16121`；Docker 29 nftables 影响 D12（坑 22） |
| **nginx**（开源版）/ **Java 网关**（商业版，只认 `/api`） | 部署依赖 | 网关若某天接管 `/apps`，注入逻辑会出现第二处实现（K8） |

---

## 7. 测试与可观测

**分层策略**（不重复 tasks.md 清单）：

- **单元**（`test/app_runtime/`，`asyncio_mode=auto`）：状态机——五个动作 × 前态矩阵（含**非法跃迁**：已上线 → 已删除必须被拒，AC-03）与并发前态断言（模拟两次 UPDATE、第二次影响 0 行 → 16102）；`slug` 全局唯一与生成规则（AC-08）；**头归一化剥离**——`X_BiSheng_User_Id` / `x-bisheng-user-id` / `X-BISHENG-USER-ID` / 混合下划线连字符全部被丢弃（坑 10）；中文姓名的 percent-encoding 往返（坑 9）；入口五步判定顺序与信息泄漏口径（草稿 / 待上线 / 已删除 / 不存在**返回同一页**）；容量准入双闸的边界（闸①过闸②不过、反之）；Dockerfile 模板渲染的确定性；`SUPPORTED_RUNTIMES` 外取值被拒且错误里列出支持值；**前缀剥离与重写**（`/apps/foo`、`/apps/foo/`、`/apps/foo/x?y=1#…` 三种形态 → 上游 `/`、`/`、`/x?y=1`，且 `X-Forwarded-Prefix` 恒为 `/apps/foo`、客户端伪造的 `X-Forwarded-*` 被丢弃，D5.2）；**取版规则**（`resume` / `publish` 取 `pending_version_id ?? current_version_id`，生效后 `pending` 置空、`terminal_state='online'`，AC-04）。
- **集成**（pytest + httpx，连 test 中间件 MySQL / Redis / OpenFGA）：`app` 资源类型全链路——非管理员用户建应用 → `my-permissions` 有动作 → 授予某用户 `use` → 该用户入口判定 allow、未授予者 deny → 权限引擎不可用时 **deny（不是放行）**；UNION 第三支的**租户隔离**（子租户账号列不出别租户应用，坑 21）+ **第三类型端到端可见**（`flow_type=35` 走完 `SUPPORTED_APP_TYPES` → UNION → `_application_action_map` 分桶 → `add_extra_field`，断言"列表非空且带 `write` / `tags`"——只加 UNION 会在这里挂，坑 28）；**按 `version_id` 起手的读接口跨租户被拒**（坑 31）；**删除钩子**（注册一个假 hook，`DELETE` 后断言被调用；hook 抛异常时删除仍成功且落 `app.delete_hook_failed`，AC-43）；状态动作的审计落行 + UI 白名单可见；升级脚本的 dry-run / apply / verify 三态（在一个干净 store 上模拟 M1 → M2）。
- **编排层**（需要 docker 的环境，CI 上打标跳过 / 114 上真跑）：build → deploy → probe → logs → stop → destroy 全链路；`docker inspect` 断言 `NanoCpus` / `Memory` 与档位一致（AC-63）、`ReadonlyRootfs=true`、`no-new-privileges`、**无 published port**（AC-33）；`docker kill` 后 ≤5 分钟自愈（AC-20 第一类）；把健康端点改成 500 后 ≤5 分钟重建（第二类）；`systemctl restart bisheng-runtime-manager` 期间应用**持续可访问**（AC-22）。
- **E2E**（`/e2e-test`，AC 全覆盖 + 页面手动清单）：构建页三类型筛选 / 状态筛选五值 / ⚙️ 菜单只两项 / 已上线删除置灰；详情页四 tab；下线 → 入口呈已下线 → 重新上线恢复。

**114 手动验证**（对应 `mvp-114-path.md` §1 **步 4–8**；前置：`bash /opt/bisheng-ops/deploy.sh` 部署 + **先发代码再往 `config.yaml` 加 `app_runtime: enabled: true`** + 跑升级脚本 `--apply` + 全量重启）：

0. 前置自检：`curl -s http://127.0.0.1:7860/api/v1/env | jq .app_runtime_enabled` → `true`；`systemctl is-active bisheng-runtime-manager bisheng-app-proxy` → 均 active；超管调 `GET /api/v1/apps/runtime-status` → `backend_available=true`、`supported_runtimes=["python3.11"]`、容量快照有值。
1. **步 4（审批通过 → 上线）**：F055 审批通过后观察 `docker ps` 出现 `bisheng-app-*` 容器；`docker inspect` 核对 CPU / 内存与「轻量」档一致、`ReadonlyRootfs=true`、无 `Ports` 映射；应用态 → 已上线；审计页出现 `app.publish`。
2. **步 5（可见范围）**：owner 在构建 → 应用 → 卡片 ⚙️「管理权限」授予全员（根部门或全员用户组）→ 弹窗能搜到主体（验证坑 2）。
3. **步 6（普通用户使用）**：**用非管理员账号**（admin 短路 ReBAC，坑 26）浏览器访问 `https://114:4101/apps/{slug}` → 免二次登录进入 → 页面顶部显示"当前访问者：{姓名} · {部门}"（**账号姓名必须是中文**，验证坑 9）→ 提交问卷 → 再次进入能看到刚提交的数据（验证 SQLite 卷持久）。
4. **步 7（未登录 / 无权限）**：无痕窗口访问 `https://114:4101/apps/{slug}?a=1#b` → 跳登录页 → 登录后**回到带 `?a=1#b` 的原地址**（验证坑 11）；用未授权账号访问 → 「无权限」页含应用名与 owner、有「返回广场」；访问 `/apps/__nonexistent__` → 「应用不存在或未上线」页（**不是 502 / 404**）。
5. **步 8（owner 运维）**：详情页运行日志 tab 能看到应用 stdout（`curl` 触发几条）、关键字筛选生效；点上下线开关 → 二次确认 → 下线后入口呈「已下线」页、`docker ps` 无该容器、卷仍在；重新上线 → 恢复访问；伪造头验证：`curl -H "X_BiSheng_User_Id: 1" -H "x-bisheng-user-name: root" .../apps/{slug}/whoami` → 应用读到的仍是**真实访问者**（AC-32）。
6. **稳定性抽测**：`docker kill` 该容器 → 计时 ≤5 分钟自动恢复且平台其它功能无感（AC-20 / AC-46）；`systemctl restart bisheng-runtime-manager` 期间持续 `curl` 应用入口 → **零中断**（AC-22）。

**关键日志 / 指标**：
- app-proxy：`app_proxy.request`（结构化：`request_id / slug / user_id / decision / reason / cache_hit / upstream_status / latency_ms`）· `app_proxy.header_strip`（剥离到的伪造头名，**异常值应告警**）· `app_proxy.fallback`（兜底页类型分布）。
- runtime-manager：`rtm.intent`（`kind / app_id / result / latency_ms`）· `rtm.reconcile`（每轮的 `desired/actual/actions`）· `rtm.rebuild`（unhealthy 重建，**频次异常 = 应用本身有问题**）· `rtm.admission_reject`（含容量快照）。
- backend：`app.state_transition`（`from → to / reason / actor`）· 审计页 `app.*`。
- Redis 键：`app_access:{app_id}:{user_id}`（访问去重窗口，后置）。

---

## 8. 后续改进 / 不打算做的事

- **紧随 MVP-核心（按此优先级补齐，release 必做）**：
  1. **D12 出站白名单双层 + UDP 封禁**（spec 决议-3 明确不得裁掉；**任何非 114 环境部署前是硬前置**）；
  2. **D2-B docker-socket-proxy 端点白名单**；
  3. **WS 反代 + 不变量①**（握手定死有效期），随后**不变量②**（吊销 / 下线事件主动断连，app-proxy 维护 connection → (user, app) 索引——**这才是自研 app-proxy 的核心理由**）与**③**（前端把重握手做成常态）；
  4. **两个过渡态页**（「发布中」/「应用恢复中」+ 自动重试，AC-36 / AC-48）；
  5. **附件存储句柄**（AC-45）与**数据面 WB-06**（AC-56，含 F052 MCP 数据工具复用）——**落点已定、只是排后**：manager 数据面 RPC + backend `AppDataService`（owner 收窄 + 审计），见 **D10**；
  6. **访问记录留痕**（AC-38，D14-B）与**审批期预览入口**（AC-37，配合 F055）；
  7. `node20` / `static` 模板；二维码；备份手册（应用存档位置随平台备份）。
- **已知短板（暂不投入，理由如实）**：
  - **日志保留期 = docker 轮转窗口**（30MB/应用），不做长期留存与全文检索——引入采集链路的成本远大于 WB-13 的诉求。
  - **运行日志不做通用脱敏**（D14）：日志是应用自己打印的，通用脱敏是幻觉级承诺；密钥靠发布期扫描兜。
  - **`app` 类型注册仍是手工改 8 处**：第三次新增业务资源类型时才值得把它收敛成注册表（现在做等于为一个未来重构预付）。
  - **Catalog 范围表的正规变更路径**（扩 `CatalogChangeType` 加 `SET_ACTION_RESOURCE_SCOPES` + `_apply_changes` 分支 + 走 draft/publish）：MVP 用原地补行脚本（D9 方案 a），正规路径登记为后续。
  - **升级脚本只覆盖 `app` 一种类型**：通用化（任意新类型的模型 + Catalog 升级）等有第二个用例再说。
- **明确不做**：
  - **本 Feature 不做任何平台能力集成**（知识库 / 模型 / 身份工具 / SDK / MCP）——归 F051 / F052 / F057，OBO 令牌本期只签发不消费；
  - **沙箱推荐档 gVisor systrap 与加固档 Kata/Firecracker**：114 是 x86_64 虚机、默认 Docker 加固档已强于 Posit Connect 商业基线；gVisor 在鲲鹏 / 飞腾 + 麒麟 / 统信上**无一手实测**，LoongArch 只剩加固 Docker 档（《调研》§2.4 / §3）；
  - **闲置回收、自动扩缩容、多机调度、compose ↔ k8s 形态迁移、同环境双形态并存**（PRD-1 §5.1 / 产品方案 §4.8）；
  - **Postgres schema-per-app 中档**：本版单实例 + SQLite 小档；升档是**任何多实例诉求的硬前置**（K6）；
  - **应用代码存档计入存储配额**、**RT-09 iframe 嵌入安全升级**、**owner 离职的归属转移**（PRD-1 §5.2 顺延）；
  - **平台内造应用的界面新建入口**（WB-01，随 PRD-2）；本册唯一创建路径 = CLI 首发。
- **重写 / 拆分触发条件**：F059 k8s 后端由不同团队实现 → 按 spec 决议-1 把「编排后端」抽为独立 Feature；app-proxy 的 Python 反代成为吞吐瓶颈 → 换 Go 或把纯反代段下沉给 nginx、只留鉴权在 app-proxy；托管应用数量使 UNION 三支的 keyset 分页变慢 → 列表改"分表查 + 服务端归并"。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-08-17 | **审查修订：处理 16 条**（3 high / 5 medium / 8 low；其中 low「D9 三件套事务表述」并入 ⑤、low「`app_version` 无 `tenant_id`」并入 ⑪ 叙述，故下面编到 ⑮）。**high**：① D8 补齐「后端 6 组硬闸」（`SUPPORTED_APP_TYPES` 三处空页闸 / `_FLOW_TYPE_TO_RESOURCE_TYPE` 分桶 / `filter_supported_apps` / `add_extra_field` 的 `version_list` / 标签 4 处 + `ResourceTypeEnum.HOSTED_APP=10` / `status` 语义），D13 标注为「仅前端」；② 解 C1 与 D8 的 arch-guard **RULE-2** 冲突——三张表改落 `bisheng/database/models/`，记 M1/M2/M3 备选与代价（坑 27 新增）；③ 新增 **D5.1 上游地址解析**（manager `GET /v1/apps/{id}/route` 出 bridge IP:port + 3s 缓存；宽限 30s ≫ 缓存 TTL 是 AC-21 不落 502 的真正理由，坑 30 新增）。**medium**：④ 新增 **D5.2 路径前缀契约**（剥 `/apps/{slug}` + `X-Forwarded-Prefix` + `BISHENG_APP_BASE_PATH` → 框架 root_path，坑 29 新增）；⑤ D9 步骤 1 锚点改正为 `permission/migration/f048_runtime_storage.py:463`（`core/openfga/discovery.py` 无此符号），并把「三件套同一 SQL 事务」订正为「步骤 1 控制面 HTTP + 步骤 2–4 同事务」、补真实回滚语义；⑥ 补 AC-43 的「通知 F055 取消在途审批单」落点（`lifecycle_hooks` 钩子注册表 + 失败不回滚 + F055 侧防御）；⑦ 补 AC-04 的「已审批待运行版本」表达（`app.pending_version_id` + `stage_version` + `resume` 取版规则）；⑧ 补 AC-56 数据面落点（manager 数据面 RPC + backend `AppDataService`，D10）。**low**：⑨ K11 错误码占用补 130 / **260（F049 已落码）**；⑩ D9 第 8 项与坑 2 补第 5 处硬闸 `:168`；⑪ K5 订正为「今天只有两支、无三支范例」并补 `app_version` 无 `tenant_id` 的派生隔离口径（坑 31 新增、C3 自查同步）；⑫ D15 波次表补 AC-14；⑬ K12 跨文档锚点改指 F049 design K8 `:39` / D9 `:160-165` / 契约表 `:242-243`；⑭ D11 补 `DEFAULT_TIERS` ↔ F055 `ResourceTier` seed 的对账口径与 AC-63 核验基准；⑮ 补 AC-06 元信息更新落点（`PATCH /api/v1/apps/{app_id}` + `AppMetaService`，与 F055「元信息随 deploy 更新」共用一处实现）。坑表 27 → 32 条 | `/sdd-review` 独立审查 16 条发现 |
| 2026-08-17 | 初版：D1–D15 决策 + 27 条坑 + 对外契约（编排 RPC / 状态动作 / 注入头 / 环境变量 / 错误码 161 段 / 部署单元）+ 测试与 114 手动验证 + MVP-核心边界表。**需回写上游的两项**：① `release-contract.md` 的「已分配模块编码」表把 `app_factory` 的 `_待分配_` 落定为 **161（F054）/ 162（F055）/ 163（F056）/ 164（F059）**；② `docs/constitution.md` 的 arch-guard 锚点表需在 RULE-10 落地时同批新增一行（backend 禁 docker/k8s import 与 socket 路径字面量） | F054 design 编写（spec 65 AC + 四份探查笔记 E1–E4 + `mvp-114-path.md` §6 裁剪基准 + 《调研》+ 产品方案 §4.1/§4.5/§4.8） |

<!-- self-check: design-checklist 24 项自检 —— 第 1–11、13–23 项满足；未满足 / 部分满足 3 项：
  · 第 12 项「与 spec §5-§7 的实际实现一致」——本文以"要建成的样子"口径写（F054 尚未开工），实现后须按现状覆盖，届时逐节复核；
  · 第 24 项「反映 tasks.md 实际偏差记录」——tasks.md 尚未编写，暂不适用，实现后回填；
  · 第 22 项「修订历史在 feature 完成时已记初版」——已记初版，但 feature 尚未完成，属提前记录（F049 design 同口径）。
  另登记两项需回写上游（见修订历史）：release-contract 错误码表 161 段落定、constitution 锚点表 RULE-10 行。 -->
