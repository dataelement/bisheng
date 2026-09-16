# Design: bisheng-sdk（Python 首发三件套 auth / retrieve / storage + 开发者指南）

> **本文档定位 — 现状快照（Why this How）**
>
> - `spec.md` 回答 **做什么**（36 条 AC、边界、11 条决议）
> - `design.md`（本文）回答 **为什么这么实现**：关键决策（含被否决的备选）、运行时不直观的事实、对外契约
> - `tasks.md` 是 **流水账**：拆了哪些任务、做了什么改动
>
> 调整原则（详见 `docs/SDD-Guide.md` §3-§4）：实现变化 → 覆盖更新本文档、只留"今天的状态"；每个决策保留"为什么 + 被否方案"和坑。推翻已 ★ 确认的决策 → 停下与用户重新确认；纯实现细节 → 直接改 design。
>
> **代码事实口径**：本文所有 `文件:行号` 按 `3.0-vibe` **`fe10f75ea`**（2026-09-16）核实。**两个待合入分支是本 Feature 的前置依赖，其契约按其源码核实、不按 `3.0-vibe` 的缺位判断**：
> - **`wt/storage-handle` `23886547f`**（F054 T084 / T085 附件句柄；D8 / §4.2 ④ / 坑 30）
> - **`wt/cli-dev` `b61b209e4`**（F053 T038 / T042–T044 / T047 / T048：`bisheng dev` 迷你代理与 `platform-wiring` 技能包；D12 / §4.2 ② / 坑 31–36）
>
> 后端路径以 `src/backend/bisheng/` 为根，runtime-manager 以 `src/runtime-manager/runtime_manager/` 为根，CLI 以 `src/bisheng-cli/` 为根，其余以仓库根为根。行号会漂移、符号名不会——**落地前一律以符号名重定位，不要按行号跳**。
>
> **本文是"要建成的样子"**：全仓**没有任何** `bisheng_sdk` / `bisheng-sdk` 代码（grep 只命中 feature 文档与 PRD）。`src/bisheng-sdk/` 是全新目录，是继 `src/bisheng-cli/` 之后本仓第二个可发布包工程；平台侧只在 F053 已建的 `bisheng/dev_toolkit/` 上做增量——**含 `skills/platform-wiring/` 技能包本体：它已由 F053 T038 在 `wt/cli-dev` 建成（身份头 / 应用数据库 / 模型「暂未提供」/ `dev` 四章 + 样例 + 自检），本 Feature 是它的增量编辑者而不是创建者**（D12、坑 31）。实现后按现状覆盖本文。
>
> **2026-09-16 全自动模式**：用户已放弃 ★ 暂停点，本文 D1–D16 每条均按建议直接定案并标「全自动模式定案」，理由与备选留痕供追溯；`/sdd-review design` 如有 high 级发现再就地修订。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md) · [release-contract.md](../release-contract.md)（表 3 F057 行；INV-28 / INV-30 / INV-32 / INV-35 / INV-36）· [mvp-114-path.md](../mvp-114-path.md) §2（F057 不在纵切上）
**上游 / 姊妹**: [F053 design D10 / D11 / §4.2 ⑤](../053-dev-cli-skills/design.md)（分发端点、`versions` 载荷的 `sdk.*` 字段位、`skills sync`）· [F054 design D5.2 / §4.2 ③⑤ / 坑 20](../054-app-domain-runtime/design.md)（注入头、注入环境变量、`bisheng-apps` 独立桶）· [F054 contracts-runtime-manager.md §5](../054-app-domain-runtime/contracts-runtime-manager.md)（环境变量清单）· [F055 design §3 能力总线段](../055-app-publish-pipeline/design.md)（`16273` / `16274`、OBO 为审计 subject）· [F052 spec AC-19–AC-27 / AC-46](../052-mcp-server-face/spec.md)（门面语义；**F052 尚无 design / tasks**）
**版本**: v3.0.0
**最后更新**: 2026-09-16

---

## 1. 目标与非目标

**目标**：交付一个**与后端零耦合的独立 Python 包 `bisheng-sdk`**（import 名 `bisheng_sdk`），把三件「平台特有 ∧ 写错了会出安全事故」的事各封成一行到位的默认做法——`auth.current_user()` 读平台注入身份（无注入即抛错）、`retrieve.search()` 以**当前访问者**凭据经 F052 门面检索、`storage.put/get/list/delete()` 在应用附件空间内存取——并让这三行在 `bisheng dev` 本地与托管上线后一字不改。同时：由平台自身分发 SDK 安装件（复用 F053 的 `dev-toolkit` 端点族）、托管构建期能从平台自身装到它、随包发布开发者指南与「平台能力接线」技能包的 SDK 章节 / 样例 / 自检脚本。SDK **不拥有任何服务端能力**，只读注入、调门面、消费句柄。

**非目标**（防止后人误扩，理由已在 spec §范围边界 / §4 决议）：

| 不做 | 为什么 | 归属 |
|---|---|---|
| `chat` / `appdb` 及任何便捷封装（连接工厂、客户端工厂） | PRD-1 DEV-07「刻意不进 SDK 的两样」；准入门槛见 D2 | 指南教标准库接法（F053 AC-17 同源） |
| 身份头验签、本地权限判定、本地白名单模拟 | 信任根在入口拓扑 + 服务端门面（spec 决议-3 / 决议-8） | F054 AC-32/33、F053 AC-25、F052 |
| OBO 令牌的服务端受理、白名单 ∩ 用户、能力收回判定 | 服务端能力 | **F052 / F055 T057–T059**（本文 §6.2 登记为阻塞项） |
| 附件存储服务端（MinIO 桶、四操作、上限、删除联动、句柄注入） | 服务端能力，**F054 T084 / T085 已在 `wt/storage-handle` 落码** | **F054**（契约以其源码为准，本文 §4.2 ④ 只是消费者视角快照 + 对账测试） |
| `bisheng dev` 迷你代理与同名环境变量注入 | CLI 侧 | **F053 T042–T044**（本文提供头名常量与句柄名） |
| 非 Python SDK、下载直链 / 分享链接、附件级权限、清空附件空间 | spec 决议-9；v3.1 视需求 | — |
| 新错误码模块（用户预留 26400–26409） | **不申请**（D14）：SDK 侧错误是 Python 异常类、服务端码各归其主 | — |

---

## 2. 关键约束

> 全局架构铁律遵循 [`docs/constitution.md`](../../../docs/constitution.md) C1–C8，本节不重抄。**作用域提醒**：C1–C7 与 `scripts/arch-guard.sh` 约束的是 `src/backend/`；`src/bisheng-sdk/` 是独立工程，只有 RULE-7（硬编码密钥字面量）会对它出声，且只是 WARNING——测试里的假令牌一律用拼接（`"bs-sak-" + "x" * 43`），让它保持零输出。

- **CON-1 SDK 是独立包，不 import `bisheng`**：不读后端配置、不连数据库、不引 FastAPI / SQLModel。依赖预算 **`httpx>=0.27,<1.0` 一条**（D1）；其余全标准库。推论：版本比较不引 `packaging`（照 CLI `http.py:_version_tuple` 的三段元组比较）。
- **CON-2 只访问平台注入的两个地址**：SDK 运行期只打 `BISHENG_PLATFORM_API_BASE`（retrieve、版本探测）与 `BISHENG_APP_STORAGE_ENDPOINT`（附件；值是 runtime-manager 的应用面地址而非平台 API，F054 契约 §5 / 坑 27）；不做遥测、不查公网、不引第三方地址（spec §3「托管期出站可达」：F054 AC-16 运行期出站白名单须含这两个地址，F054 契约 §9 已登记）。
- **CON-3 两类凭据结构上不混用**：托管容器内同时存在应用运行期凭据（`BISHENG_APP_TOKEN`，F055 T056 注入，应用自身身份）与每请求注入的访问者凭据（`X-BiSheng-Access-Token`，F054 AC-34）。SDK retrieve **只从请求上下文读后者**，代码里不出现 `BISHENG_APP_TOKEN` 字面量（tests 以 grep 断言），不提供 `as_user` 及任何等价参数（AC-08 / AC-12 / 决议-2）。
- **CON-4 无注入即抛错，不返回 None / 缺省身份、不提供宽松开关**（AC-07 / 决议-1）。健康探活、后台任务、单测裸调用遇到抛错是**刻意的**。
- **CON-5 请求作用域**：身份与凭据只活在当前请求上下文（AC-09），不跨请求缓存；同进程并发互不串扰；WebSocket 取握手时的头。
- **CON-6 凭据不落盘、不回显**（AC-04）：所有异常 `__str__`、日志、`repr` 统一过 `redact()`；`Identity` 对象**不携带**访问令牌（令牌只在上下文里供 retrieve 读）。
- **CON-7 与三处注入契约同一份**（AC-31）：头名 = app-proxy `INJECTED_HEADER_NAMES`（`src/app-proxy/app_proxy/headers.py:29-40`），**`bisheng dev` 已复制同一张表且自带 `ast` 对账测试**（`wt/cli-dev`：`bisheng_cli/devproxy.py:63-74` + `tests/test_platform_contract.py`）——SDK 是第三份副本，对账测试读 app-proxy 这个上游而不是读 CLI；环境变量名 = F054 contracts §5（含 `BISHENG_APP_STORAGE_ENDPOINT` / `_TOKEN` / `_MAX_FILE_MB`，真身 `runtime_manager/storage.py:STORAGE_ENV_NAMES`、backend 副本 `app_runtime/domain/constants.py:APP_STORAGE_ENV_NAMES`）+ 本文为本地期新定的 `BISHENG_APP_STORAGE_DIR`（§4.2 ②）。SDK 把这两张表复制成常量模块 `_headers.py` / `_env.py`，并由 tests 与源文件**逐字对账**（tests 读 `headers.py` / `storage.py` / `constants.py` 文本比对，仓内可跑、发布件不依赖；对方文件不存在时 `skip` 并打印原因）。
- **CON-8 版本独立、区间兼容**（AC-03 / 决议-6）：SDK 版本 `0.x` 独立于平台 `3.0.0`；平台声明 `sdk.min_compatible`；不兼容在**首次平台交互**抛错（auth 不交互，故可能到 retrieve / storage 才暴露——自检脚本补位）。
- **CON-9 商业版网关只转发 `/api/v1/**` 与 `/api/v2/**`**（`docs/architecture/11-gateway.md:36-37`）：分发端点、简单索引都必须落在这两个前缀下。附件 API **不经网关**——它是应用容器到 runtime-manager 的内网直连（F054 D10），与网关无关。
- **CON-10 分发件随后端包走**：backend 镜像 build context 只有 `src/backend/`（`src/backend/Dockerfile` `COPY ./ ./`），SDK wheel 与 CLI wheel 同理必须**构建后提交进 `bisheng/dev_toolkit/artifacts/`**（F053 T030 契约；坑 10 / 11）。

**Constitution Check（自查）**：
- **C1（DDD 分层）**：`src/bisheng-sdk/` 是 `src/backend/` 之外的独立工程（同 F053 CLI、F054 runtime-manager），RULE-1～9 不作用于它，只有 RULE-7 会对测试里的密钥字面量出声（§2 开头已处理）。平台侧增量只落 `bisheng/dev_toolkit/`（`api/endpoints/distribution.py` + `domain/services/artifact_service.py` + 新常量 `sdk_compat.py`）：端点经 service 读盘、不 import `database/models`（RULE-3）、不跨模块 import 他人 `api/`（RULE-5）；runtime-manager 增量（D15 两个 buildarg）在 `bisheng` 包之外。**RULE-10**：SDK 与 backend 增量都不 import docker / 不碰 socket。
- **C2（双 DB）**：无新表、无 Alembic revision；`sdk_compat.py` 是纯常量。
- **C3（多租户）**：四个新端点匿名、租户对 SDK 不可见（spec §3）；`/api/v1/dev-toolkit` 前缀已在 `TENANT_CHECK_EXEMPT_PATHS`（`utils/http_middleware.py`，F053 D10 落码），新端点同前缀、零改动。
- **C4（权限）**：SDK 不做任何权限判定、不持验签材料（spec 决议-8）；分发端点匿名与 F053 D10 同源；retrieve / storage 的判权全在服务端（F052 门面 / F054 manager Bearer 绑 `app_id`）。
- **C5（错误码）**：**不申请模块段**（D14）；`16170–16174` 由 F054 在 `app_factory.py:224-234` 预留、首个 backend 调用方落码，本 Feature 不落、不依赖；SDK 侧可区分性由异常类承担，不进 `api_errors` 三语文案。
- **C6（无硬编码密钥）**：SDK 不持任何密钥材料；OBO 与 storage token 只从注入读、不落盘、异常经 `redact()`；测试假令牌一律拼接（坑 22）。
- **C7（前端 store 不直连 HTTP）**：无前端改动。
- **C8（本地文件系统不放共享状态）**：托管期附件真身恒在 MinIO `bisheng-apps`（经 manager，多实例 / 重建后一致，AC-24）；SDK 的本地目录后端**只在 `bisheng dev` 单机开发期**生效（D8 互斥判定保证线上不会静默落本地）；SDK 进程内唯一的缓存是 D7 的版本探测结果（内存，不落盘）。

---

## 3. 方案对比与选定

> 每条：备选 / 选定 / 原因 / 何时该重新考虑。全部为**全自动模式定案**。

### D1：包工程 = `src/bisheng-sdk/`（hatchling wheel），三名分离，依赖仅 `httpx`，版本 `0.1.0` 独立于平台

- **备选**：A. 并入 `bisheng-cli` 同一包 — CLI 是开发者本机工具、SDK 是应用运行期依赖，合包让应用容器背上 PyYAML 与 CLI 代码（spec 决议-5 已否决）；B. 放进 `src/backend/bisheng/sdk/` 随后端包分发 — 应用容器必须装整个 backend，荒谬；C. **独立工程，照抄 `src/bisheng-cli/pyproject.toml`**（选定）。
- **落地形状**：发行名 `bisheng-sdk` · import 名 **`bisheng_sdk`** · 无 console script。`requires-python = ">=3.11"`（托管 `runtime` 矩阵首发 python3.11，`src/runtime-manager/runtime_manager/templates/` 只有 `python3.11/`）。`dependencies = ["httpx>=0.27,<1.0"]`——**带上界**（CLI T001 的教训：wheel 的分发路径上 `uv.lock` 不参与解析，metadata 上界是唯一约束）。`[tool.hatch.build.targets.wheel] packages = ["bisheng_sdk"]`（目录带连字符时缺它 = 空 wheel，F053 D1）。`[tool.ruff]` 照 CLI（含 `RUF001/002/003` ignore——异常文案是中文）。版本单一真相 `bisheng_sdk/__init__.py:__version__ = "0.1.0"`。
- **原因**：与 CLI 同一套工具链与 CI 形态（`cli-quality.yml` 三 leg：locked / highest / wheel smoke），零选型成本；`0.x` 起版是因为 spec 决议-6 要求独立于平台号——SDK 被应用依赖清单锁定、随版本快照走，若与平台同号则平台每次升级都让存量应用不兼容（重发必审 INV-34）。
- **何时该重新考虑**：出现第二个语言的 SDK → 目录改 `src/sdk/python/`；或 `httpx` 在客户内网镜像普遍缺失 → 退回 `urllib` 实现（代价：无连接池、无流式上传）。

### D2：公开面 = 恰三个能力模块 `auth` / `retrieve` / `storage` + 一个异常模块 `errors`；其余全部下划线私有；准入门槛写进 `test_public_surface.py`

- **备选**：A. 把异常类挂进各能力模块（`auth.NoIdentityError`）— 三处重复、跨模块共用的 `PlatformUnreachableError` 无处安放；B. 顶层 `bisheng_sdk.SdkError` 单一异常 — AC-19 / AC-25 要求可区分；C. **`errors.py` 一个公开模块承载全部异常层次**（选定）。
- **AC-33 的自动化校验**：`test_public_surface.py` 用 `pkgutil.iter_modules(bisheng_sdk.__path__)` 枚举，断言**非下划线模块集合 == {auth, retrieve, storage, errors}**、`bisheng_sdk.__all__ == ("auth", "retrieve", "storage")`、`import bisheng_sdk.chat` / `.appdb` / `.llm` / `.db` / `.client` 全部 `ModuleNotFoundError`、全包无名为 `as_user` / `login` / `verify_token` / `impersonate` 的公开符号。**`errors` 不是能力模块**，spec AC-33「恰为三模块」指能力面；异常模块是三模块的共同出错形状，不违背准入门槛。
- **准入门槛（流程规则，spec 决议-10）**：新增第四个能力模块须同时证明「平台特有」∧「写错了会出安全事故」，并**先改 `test_public_surface.py` 的集合再写代码**——把门槛做成一条会红的测试，比写在备忘录里可靠。chat / appdb 的否决理由见 PRD-1 DEV-07 两表，不重抄。
- **何时该重新考虑**：PRD-2「密钥引用」进入能力总线且过门槛 → 另起 AC 后加模块。

### D3：请求上下文 = `ContextVar` + 纯 ASGI 中间件 / WSGI 中间件 / 显式 `auth.bind()`；不要求把 request 传给每个调用

- **备选**：A. 每个 API 显式收 `request` / `headers` 参数 — 违背「一行到位」，且 retrieve / storage 都要带；B. 线程局部变量 — asyncio 下失效；C. 进程级全局 — 违反 AC-09；D. **`contextvars.ContextVar` 存本请求的注入头快照，由框架适配层在请求边界 set / reset**（选定）。
- **三个接法（指南与技能包只教这三种）**：
  1. **ASGI**（FastAPI / Starlette）：`app.add_middleware(bisheng_sdk.auth.ASGIMiddleware)`。⚠️ **实现必须是纯 ASGI 可调用（`__call__(scope, receive, send)`），不能继承 Starlette `BaseHTTPMiddleware`**——后者把 `call_next` 放进独立任务，ContextVar 在任务边界只复制不回传，`reset` 会抛 `ValueError: Token was created in a different Context`（坑 14）。只处理 `scope["type"] in ("http", "websocket")`；WebSocket 取握手 scope 的 headers（AC-09）。
  2. **WSGI**（Flask 等）：`app.wsgi_app = bisheng_sdk.auth.WSGIMiddleware(app.wsgi_app)`；WSGI 把头折成 `HTTP_X_BISHENG_USER_ID`，适配层按 `headers.py:78-80` 的归一化（小写 + `_`→`-`）还原。
  3. **显式绑定**（Streamlit、无中间件钩子的框架、测试）：`with bisheng_sdk.auth.bind(headers): ...` 或脚本顶部 `bisheng_sdk.auth.bind(st.context.headers).__enter__()`（Streamlit 每次 rerun 是新线程、新空上下文，必须在脚本顶部绑，坑 13）。`auth.from_headers(mapping) -> Identity` 是无上下文的纯函数版本，供握手回调等一次性场景。
- **中间件不拒绝无头请求**：没有注入头的请求（健康探活）照常进入应用，只是上下文为空；**只有调用 `current_user()` 那一刻才抛**（AC-07 的落点在读取处，不在中间件）。
- **原因**：`ContextVar` 是标准库、对 asyncio 任务与线程都有正确的隔离语义（新任务复制、新线程为空）；后台线程 / 任务里 `current_user()` 抛错正是 spec §3 要的行为。
- **何时该重新考虑**：出现主流框架既非 ASGI 也非 WSGI 且无请求头钩子 → 加第四种适配；不动核心。

### D4：`Identity` 形状 = 十头原样映射、`str` 类型标识、令牌不上对象、缺省部门为 `None`、`subject_kind` 透传 `human` / `service_account`

- **备选**：A. `user_id: int` — 本地 `dev` 期 `X-BiSheng-User-Id` 是**服务账号 id**、不是 `user` 表行（F053 design K15「服务账号不是 user 表的行」），应用若按 int 去 join 平台用户会得到错的人；B. SDK 把 `human` 翻成 `natural_person` 对齐 `api_credential` 常量 — AC-06 明令「原样暴露、不自行推导或补全」；C. **全部 `str`、透传**（选定）。
- **形状**（frozen dataclass，`bisheng_sdk.auth.Identity`）：`user_id: str` · `user_name: str` · `tenant_id: str` · `dept_id: str | None` · `dept_name: str | None` · `dept_path: str | None` · `subject_kind: str`（线上恒 `"human"`：`entry_authz_service.py:_user_facts`（`:310-322`）硬编码；`dev` 期**取决于 `login` 用的密钥**——服务账号密钥 → `"service_account"`、个人访问令牌（`bs-pat-`）→ `"human"`，`devproxy.py:DevIdentity.from_whoami`（`:204-213`）按 `whoami.actor_kind` 判，坑 33）· `app_id: str` · `request_id: str | None`。⚠️ **没有 `access_token` 字段**（CON-6）；`repr` 不含任何头值以外的东西。
- **解码**：非 ASCII 值在注入侧被 `quote(text, safe="/")`（`entry_authz_service.py:_encode`、`app-proxy/headers.py:encode_header_value`），SDK 对 `User-Name` / `Dept-Name` / `Dept-Path` 做 `urllib.parse.unquote`；**缺失的部门三头是"不发"而不是"发空串"**（`headers.py:161-164`），SDK 映成 `None`（AC-10：服务账号无部门）。`X-BiSheng-User-Id` 缺失 → `PlatformIdentityMissingError`。
- **与 spec 的口径差（全自动模式定案：不改 spec、由 design 记差）**：spec AC-06 / AC-10 写「`dev` 期返回开发者**服务账号**、组织字段可为空」，而已落地的 `bisheng dev` 允许用个人访问令牌（`bs-pat-`）`login`，此时注入的是**自然人**身份（`subject_kind="human"`、可能有部门）。两者对 SDK 是同一条码路（原样透传，AC-06「不自行推导或补全」），AC-10 在服务账号密钥这一主用法上仍逐字成立；把 PAT 情形写进 spec 会把 F053 的密钥策略拽进 F057 的 AC。指南按「取决于你 login 用的密钥」写（T033），本地/线上差异清单里补这一句。
- **何时该重新考虑**：F050 若给注入头加字段（如角色）→ 在 `_headers.py` 追加常量 + `Identity` 追加可选字段，三处对账测试会先红。

### D5：retrieve 执行凭据 = 请求上下文里的 `X-BiSheng-Access-Token` 值，作为 `Authorization: Bearer` 直投 `POST /api/v2/filelib/retrieve`；SDK 对令牌形态不感知

- **备选**：A. 用 `BISHENG_APP_TOKEN` + `X-On-Behalf-Of: <user_id>` 走 F050 模式 D — F050 spec §范围边界明写 OBO 与模式 D 是**两套信任机制、不得混用**；且会让 SDK 读进程级凭据（CON-3 违规）；B. 新开一个专用端点 `POST /api/v2/apps/self/retrieve` — F052 AC-26「门面是开放面上唯一检索路径」、AC-25「v2 `POST /filelib/retrieve` 经同一门面」，再开端点是第二条路径；C. **复用 `POST /api/v2/filelib/retrieve`（`open_endpoints/api/endpoints/filelib.py:687-736`），Bearer = 注入的访问者凭据**（选定）。
- **对令牌形态不感知**：线上它是 app-proxy 注入的 HS256 OBO JWT（aud `bisheng-app-obo`、900 s，`entry_authz_service.py:379-425`）；`dev` 期是 `bisheng dev` 迷你代理每请求现铸的 `bsdev.<b64 payload>.<hmac>` 句柄（`devproxy.py:HandleMinter.mint`（`:247-262`）、TTL 900 s、**本地自签**）。SDK 只做「上下文里有就带、没有就抛 `VisitorCredentialMissingError`」，**不解析、不校验、不续期**——两种形态对 SDK 是同一条码。
- **服务端必须补的三半（本文 §6.2 登记为阻塞项，SDK 先按现有线上契约落码）**：① `validate_bearer`（`open_api/domain/services/credential_validator.py:43` 的 `_TOKEN_RE` 只认 `bs-sak-` / `bs-pat-`）要能受理 OBO 令牌并以 `sub.user_id` 为执行身份、`sub.app_id` 定白名单（F055 T057）——`entry_authz_service.py:389-394` 的 docstring 明写「OBO 有了第一个消费者时签发必须改 fail-closed」，**那个消费者就是本 SDK**；② `RetrieveReq.knowledge_base_ids` 今天 `min_length=1` 必填（`open_endpoints/domain/schemas/filelib.py:43-45`），F052 AC-22「未指定目标 → 在全部被授予范围内检索」要求它可省略；③ **`dev` 的 `bsdev.` 句柄是本地 HMAC 自签的，平台无从验签**——本地期 retrieve 因此与托管期同样答 `26001`（坑 32）。**全自动模式定案**：修法归 F053 / F052 而不是 SDK——`bisheng dev` 用 `login` 密钥向平台换一枚平台签发的短时凭据（每会话换、每请求下发，`login` 密钥仍不进应用进程），SDK 侧零改动；备选「F052 受理本地自签句柄」被否决（要求平台信任开发者机器上自选的 HMAC 密钥，等于给任何本地进程一条以服务账号身份检索的路，与 INV-30 相悖）。
- **入参出参 = 门面的入参出参**（AC-11 / AC-18）：`search(query, *, knowledge_base_ids=None, top_k=10, max_content=15000, filters=None)`，字段名与 `RetrieveReq` 一一对应，`filters` 形状 = `RetrieveFilters`；`knowledge_base_ids=None` 时**省略该键**（`extra="forbid"`，不能送 `null` 以外的自造值）；出参 `RetrieveResult(chunks: list[Chunk], total: int)`，`Chunk` 六字段照 `RetrieveChunk`。SDK 不排序、不去重、不截断、不缓存。
- **何时该重新考虑**：F052 design 若把门面独立成新路径（如 `/api/v2/knowledge/retrieve`）→ 只改 `_http.py` 的 `RETRIEVE_PATH` 常量与 `_codes.py`。

### D6：错误层次 = 一个基类 + 按「应用的下一步动作」分格的 18 个子类；服务端码经 `_codes.py` 一张表映射，未登记码绝不吞

- **备选**：A. 直接抛 `httpx.HTTPStatusError` — 应用要读 HTTP 状态 + 信封才能分支，正是 SDK 该消化的；B. 一个 `SdkError(code)` — AC-19 / AC-25 要求可区分且各附可读原因；C. **异常子类 = 动作分格**（选定，同 F053 D9「一码一处置」判据）。
- **层次**（全部在 `bisheng_sdk.errors`，基类带 `message` / `next_step` / `code: int | None` / `details: dict | None`，`__str__` = `redact(f"{message}（下一步：{next_step}）")`）：

  | 异常 | 触发 | 应用的下一步 |
  |---|---|---|
  | `PlatformIdentityMissingError` | `current_user()` 时上下文无 `X-BiSheng-User-Id` | 这条路径不该调 auth（探活 / 后台任务），或未经入口访问 |
  | `VisitorCredentialMissingError` | retrieve 时上下文无 `X-BiSheng-Access-Token`（含无上下文） | 同上；线上另查 `app_runtime.obo_secret`（坑 4） |
  | `VisitorCredentialRejectedError` | HTTP 401（`26001` / `26002` / `26027` 或无信封） | 凭据过期 / 会话失效 / 应用下线，让用户刷新重进 |
  | `ScopeMissingError(required)` | HTTP 403 + `26003`（`data.required` 是**单个字符串**，`errcode/open_api.py:36-39`） | 本地期：请管理员给密钥勾 `knowledge:read` |
  | `TargetUnreachableError(ids)` | F052 AC-11「不可及」码（**待 F052 design 分配**，`_codes.py` 留 `TARGET_UNREACHABLE_CODES = frozenset()`） | 去掉不可及的库 id；托管期检查能力声明 |
  | `CapabilityRevokedError(capability, reason)` | `16273`（F055 T058） | owner 重新声明 / 找管理员 |
  | `CapabilityNotDeclaredError(capability)` | `16274` | 在 `bisheng-app.yaml` 声明后重发 |
  | `PermissionEvaluationError` | `26030`（`OpenApiAuthDependencyUnavailableError`，HTTP 503） | 稍后重试，**不得**改小范围重试 |
  | `PlatformRefusedError(code, message, details)` | 任何未登记的业务码（含 422 校验失败） | 按 message 处置；**永不吞掉** |
  | `PlatformUnreachableError` | 连接 / 超时 / 无码 5xx / `BISHENG_PLATFORM_API_BASE` 未注入 | 检查平台地址与网络 |
  | `SdkIncompatibleError(sdk_version, min_compatible, platform_version)` | 版本探测 `min_compatible > __version__` | 从当前平台重新获取 SDK 后重发 |
  | `PlatformTooOldError` | `versions` 404 或 `sdk` 块为 null | 升级平台 / 确认开放能力层已部署 |
  | `StorageHandleMissingError` | 既无 `BISHENG_APP_STORAGE_ENDPOINT` 也无 `_DIR`、**两者都有**、或有 `ENDPOINT` 无 `TOKEN` | 经 `bisheng dev` 启动 / 检查注入 |
  | `StorageHandleRejectedError(reason)` | 附件 API 401 `unauthorized`（令牌不属本应用 / 应用已 destroy / 未带 Bearer；**没有 403、没有「下线」专用码**，坑 28） | 重启实例 / 重新上线；仍 401 则找管理员 |
  | `StorageUnavailableError` | 附件 API 503 `storage_unavailable`（manager 未配 MinIO / MinIO 不可达）、连接失败（坑 27）、无码 5xx | 稍后重试；线上查 `runtime/status` preflight `attachment_storage` |
  | `AttachmentNotFoundError(path)` | 404 `not_found` / 本地不存在 | — |
  | `AttachmentTooLargeError(path, limit_bytes)` | 客户端按 `BISHENG_APP_STORAGE_MAX_FILE_MB` 预判（两端同名）/ 服务端 413 `payload_too_large` | 分片或缩小 |
  | `InvalidAttachmentPathError(path)` | 客户端路径校验（= manager `validate_key` 规则）或服务端 400 `invalid_object_key` | 用应用内相对路径 |

- **映射顺序**（照 CLI 坑 12）：先读信封——backend 形状 `{status_code, status_message, data}`（`/api/v2` 是真 HTTP 状态 + 信封 body；`/api/v1` 是 HTTP 200 + 信封）或 manager 形状 `{"detail": {"code", "message", …}}`（附件 API，坑 26）——再按 HTTP 状态类兜底（401 → Rejected、403 → Refused、5xx → Unreachable / Unavailable），三者都判不了才 `PlatformRefusedError`。**`details` / `data` / `detail` 原样挂在异常上**，不裁剪。
- **何时该重新考虑**：F052 / F055 若把「不可及」与「已收回」合成一个码 → 先反对（GOV-05 要求两者可区分）。

### D7：版本兼容 = 首次平台交互前、每进程一次的懒探测 `GET /api/v1/dev-toolkit/versions`；`min_compatible` 三段元组比较；auth 永不探测

- **备选**：A. import 时探测 — 让 `import bisheng_sdk` 打网络，单测与探活都被拖下水；B. 每次调用都探测 — 多一倍请求；C. **懒探测 + 进程内按 base URL 缓存成功结果**（选定）。失败（不可达）**不缓存**，下次再试。
- **判据**：`sdk.min_compatible <= __version__`（按 `_version_tuple`，与 CLI `http.py:_version_tuple` 同算法）否则 `SdkIncompatibleError`；`versions` 404 或 `data.sdk` 为 null / `sdk.version` 为 null → `PlatformTooOldError`（文案同时点明「开放能力层未部署」的可能，AC-05 不另设分支）。`platform.version` 只用于文案。
- **原因**：spec 决议-6「首次交互即报错」；auth 不交互（AC-03 备注），所以指南要求应用启动时跑一次自检（D12 的 `selfcheck.py` 正是它）。不比较上界：平台升级后老 SDK 仍在区间内即无需重发（AC-03）。
- **何时该重新考虑**：F055 若在托管预检加「应用锁定的 SDK 版本 ∈ 平台区间」校验 → 本条不变、只是暴露更早。

### D8：storage 句柄契约 = 托管期 `BISHENG_APP_STORAGE_ENDPOINT` + `_TOKEN` + `_MAX_FILE_MB`（F054 T084 / T085 **已实现**的 HTTP 句柄，落 runtime-manager），本地期 `BISHENG_APP_STORAGE_DIR`（目录句柄）；同一 API 两个后端，按有无 `ENDPOINT` 分辨

- **事实（`wt/storage-handle` `23886547f`，尚未合入 `3.0-vibe`，坑 30）**：F054 T084 / T085 已落码——`runtime_manager/storage.py`（`STORAGE_ENV_NAMES`、`validate_key`、`AppStorageService` 四操作 + `purge_app`、`storage_env()`）、`runtime_manager/api/storage.py`（router `prefix="/v1/apps/{app_id}/storage"`，Bearer 绑 `app_id`、无 Bearer 走 HMAC）、`lifecycle.build_env` 注入三个变量、backend 契约副本 `app_runtime/domain/constants.py:APP_STORAGE_ENV_NAMES`，F054 contracts §2「附件存储句柄细则」/ §5。**本文初稿（同日上午）建议的 `BISHENG_APP_STORAGE_URL` + 落 backend `/api/v1/app-storage/*` 已作废**：F054 先落码、SDK 是消费者，按对方为准，不再回写。
- **备选（曾考虑，留痕）**：A. 注入 MinIO endpoint + 桶 + 前缀 + 凭据，SDK 直连对象存储 — AC-21 明令不暴露，F054 也明确不注入（`constants.py:185-187`）；B. 注入预签名 URL — 有效期与四操作矩阵都不好表达；C. 附件 API 落 backend `/api/v1/*` 经网关 — 本文初稿建议；F054 选了 **manager 直连 + `RTM_APP_FACING_BASE_URL`**（manager 已持 MinIO 客户端、backend 零改动，代价 = 可达性要 ops 配网桥网关地址，坑 27）；D. **HTTP 句柄 = manager 应用面 URL + 每应用不透明 Bearer**（F054 选定，本文承接）。
- **托管期形态**：`BISHENG_APP_STORAGE_ENDPOINT = {RTM_APP_FACING_BASE_URL}/v1/apps/{app_id}/storage`（`storage.py:storage_endpoint_for`）；`BISHENG_APP_STORAGE_TOKEN` = `secrets.token_urlsafe(32)`，每应用一把、redeploy 沿用、destroy 后才轮换（`lifecycle.py` T085 段）；`BISHENG_APP_STORAGE_MAX_FILE_MB` = `RTM_STORAGE_MAX_FILE_MB`（缺省 20），F054 注入它就是**为了让 SDK 发送前能拒**。`app_id` 只在 URL 里、由 F054 注入，SDK 不拼、不改、不发。
- **本地期形态**：`BISHENG_APP_STORAGE_DIR` 由 `bisheng dev`（F053 T043）注入，值 = `<项目根>/.bisheng/attachments/` 的绝对路径。⚠️ **已落地的 `bisheng dev` 还没有注入它**：`wt/cli-dev` 的 `devdb.py:INJECTED_ENV`（`:48-58`）只有 `BISHENG_APP_DB_*` / `BISHENG_APP_ID` / `BISHENG_APP_SLUG` / `BISHENG_APP_VERSION*` / `BISHENG_PLATFORM_API_BASE` / `PORT` 一族，无任何 `BISHENG_APP_STORAGE_*`（坑 34）——本地期 storage 在该注入补齐前恒 `StorageHandleMissingError`，登记为 §6.2 契约 ⑦（回写 F053）。选 `.bisheng/` 之下是因为它已是 CLI 的**硬排除**目录（`bisheng_cli/ignore.py:42-56`，`!` 取不回），比软排除的 `attachments/` 更强地保证附件不进上传包（F053 AC-32）；`dev` 同时写 `<项目根>/.bisheng/.gitignore`（内容 `attachments/` + `*.db`），使 F053 D13「建议把 `.bisheng/app.json` 提交进 git」与「附件不进 git」并存。`BISHENG_APP_STORAGE_MAX_FILE_MB` 本地**可选、同名**（`dev` 可注入以模拟线上上限；不注入 = 不限，坑 23）。
- **后端选择（`storage._backend()`，每次调用重算、不缓存）**：有 `ENDPOINT` → 远端（此时 `TOKEN` 缺 → `StorageHandleMissingError`「句柄不完整」）；无 `ENDPOINT` 有 `DIR` → 本地；**两者都有** → `StorageHandleMissingError`「句柄不唯一」（环境配错，宁可停下也不猜——spec §3「不静默改写到本地临时目录」同向）；都没有 → `StorageHandleMissingError`。F054 契约 §5 原话「SDK 按有无 `ENDPOINT` 分辨两种形态」。
- **单文件上限**：两端都先按 `_MAX_FILE_MB` 客户端预判（数据长度已知时）→ `AttachmentTooLargeError(limit_bytes = MB × 1024²)`，零请求 / 零落盘；线上服务端再判一次答 413 `payload_too_large`（先看 `Content-Length` 再按流计数，`api/storage.py:_read_capped`），SDK 原样呈现。
- **何时该重新考虑**：PRD-2「附件字段」需要短时下载句柄 → 由 F054 在 `/v1/apps/{app_id}/storage/` 上加 presign，SDK 再暴露。

### D9：storage API 面 = 六个模块级函数（put / get / open / stat / list / delete）+ `AttachmentMeta`；无清空、无批量删除、无直链

- **备选**：A. 类 S3 的 `Bucket` / `Object` 对象模型 — 把对象存储心智带给应用，正是要藏的；B. 只有 put / get — AC-20 要四操作含元信息；C. **函数面**（选定）：`put(path, data: bytes | BinaryIO | PathLike, *, content_type=None) -> AttachmentMeta` · `get(path) -> bytes` · `open(path) -> BinaryIO`（流式，大文件）· `stat(path) -> AttachmentMeta` · `list(prefix="", *, limit=None) -> list[AttachmentMeta]`（内部翻页取完）· `delete(path) -> None`。`AttachmentMeta(path, size, content_type, modified_at: datetime)`。
- **路径规则（`_paths.py` = manager `runtime_manager/storage.py:validate_key` 的逐条镜像，对账测试守住）**：非空 `str`；UTF-8 ≤ 1024 字节；不含控制字符（`< 0x20` 与 `0x7F`）；不含 `\`；不以 `/` 开头、**不以 `/` 结尾**；按 `/` 分段后段不得为空、`.`、`..`；`posixpath.normpath(key) == key`（规范形）；**不以 `apps/` 开头**（manager 保留命名空间，哪怕是自己应用的前缀也拒）。违反 → `InvalidAttachmentPathError`，**不规范化后放行**（`a/../b` 是拒绝，不是变成 `b`）。`list(prefix)` 的 `prefix` 允许空或以 `/` 结尾，其余同规则（`validate_prefix`）。
- **无清空**（AC-24）：不提供 `clear()` / `delete_prefix()`；`delete` 只收单个路径。**无直链**（AC-22）：不提供任何返回 URL 的函数。
- **何时该重新考虑**：AC-24「按显式清单」若成为高频需求 → 加 `delete_many(paths: Sequence[str])`，仍拒绝前缀语义。

### D10：同步 + 异步双形态（`retrieve.search` / `asearch`，storage 六函数各有 `a` 前缀异步孪生）；auth 只有同步

- **备选**：A. 只同步 — FastAPI 是指南推荐框架，在事件循环里做阻塞 HTTP 是经典事故，且 retrieve 是每请求调用；B. 只异步 — Flask / Streamlit 用户要自己跑 loop；C. **两套，共用一份请求构造与错误映射**（选定，`_http.py` 内以 `httpx.Client` / `httpx.AsyncClient` 各一）。
- **auth 只同步**：它是纯上下文读取、零 I/O，没有异步的理由。
- **原因**：httpx 天然双形态，代价只是薄薄一层包装；单测对两条路径跑同一组用例（参数化）。
- **何时该重新考虑**：无。

### D11：HTTP 客户端策略 = 进程内按 base URL 复用连接池、`trust_env=False`、分档超时、**零重试**

- **落地**：`_http.py` 持 `dict[base_url, httpx.Client]`（线程安全的懒建）；超时 connect 5 s、retrieve 读 30 s、storage 读 / 写 120 s；`trust_env=False`（默认不读 `HTTP_PROXY` 等——托管容器里代理变量会把平台调用送进被封的出站，开发机上公网代理会劫持内网地址，F053 坑 2 的同型；`BISHENG_SDK_TRUST_ENV=1` 可显式打开）；**不重试**：PUT 非幂等，且 AC-16 明令「不本地重试成更小范围」——重试是应用的决定。
- **何时该重新考虑**：附件上传出现真实丢包 → 由 F054 在附件 API 上做分片 + 幂等键，SDK 再加可控重试。

### D12：指南与技能包同源一份 = `bisheng/dev_toolkit/skills/platform-wiring/SKILL.md`（**F053 已建，本 Feature 做增量**）；开发者指南端点直接吐它；README 只做入口

- **备选**：A. 指南独立写在 `src/bisheng-sdk/README.md`、技能包另写 — 两份必漂移（spec 决议-7）；B. 指南 = 技能包 SKILL.md 的生成物 — 多一个生成步骤；C. **技能包 SKILL.md 就是指南，`GET /api/v1/dev-toolkit/sdk-guide.md` 读同一文件**（选定，照 `get_install_guide` 的 `text/markdown` + 缺失 404 形态，`distribution.py:118-137`）。
- **今天的包**（`wt/cli-dev` `b61b209e4`，F053 T038 已交付；226 行 SKILL.md + `example/`（标准库 FastAPI-free 样例：读头 + `sqlite3` 便签）+ `selfcheck.py`（109 行：凭据 / 平台可达 / `whoami` / 应用库变量））：目录五章 = ① 访问者身份（读头，`> ⚠️` 警示块已就位，**末尾一节「SDK 用法（随后续版本补齐）」是留给本 Feature 的桩**）② 应用数据库 ③ 平台模型（**暂未提供**，F051 前不得发明 base URL）④ 本地运行 `bisheng dev` ⑤ 自检清单。
- **本 Feature 的增量（不是重写，坑 31）**：① 在 auth 章把那节桩换成 SDK 三件套的 auth 用法（`current_user()` 一行 + 三种接法 + AC-07 抛错 + 「健康端点不调 auth」），**警示块、章序、目录第一条位置一律不动**——F053 的 `test_skill_packs.py::test_auth_chapter_is_first_in_toc_and_in_the_body_and_opens_with_the_warning` / `test_auth_chapter_teaches_exactly_app_proxys_header_names` 按现状断言，改了会先红；② 新增 retrieve 章（per-user 语义 + 四处本地/线上差异 + 错误类速查）与 storage 章（六函数 + 本地目录 vs 平台存储 + 不计配额 + 无直链），插在 auth 章之后、应用数据库章之前，并同步更新目录；③ 模型章**保持「暂未提供」**（F051 未落地，spec AC-30 的模型半边由 F051 验收，本轮只在 SDK 章点明「模型不进 SDK」）；④ `example/` 追加一个用 SDK 三件套的版本，**保留现有标准库样例**（`test_example_is_stdlib_only` 对两个包都断言，新增依赖会先红 → 新样例另置 `example-sdk/` 并在 `SKILL.md` 指路，D12 落地细则见 tasks T034）；⑤ `selfcheck.py` 追加 SDK 三步（D13 的 ①④⑤）。
- **分发零改动**：`artifact_service.read_skill_pack` 按目录名打包（`artifact_service.py:211-231`），目录内容变更即自动随包下发；**CLI 侧 `DEFAULT_PACKS`（`bisheng_cli/commands/skills.py:57`）已由 F053 改成 `("deploy-hosting", "platform-wiring")` 并重打过 CLI wheel**（`wt/cli-dev`）——`3.0-vibe` 上仍是单元素元组，两分支合并后本 Feature 只需核对而不是再改一次（坑 35 / §6.1）。
- **何时该重新考虑**：技能包数量 ≥ 4 → `DEFAULT_PACKS` 改由 `versions` 载荷下发。

### D13：自检脚本 = 在 F053 已交付的 `selfcheck.py` 上**追加** SDK 三步；只依赖标准库 + 可选 `bisheng_sdk`，每步一句可读原因；退出码 0 仅当全过

- **既有脚本**（`skills/platform-wiring/selfcheck.py`，F053 T038）：读 `~/.bisheng/credentials.json` → 打 `/api/v2/auth/whoami` → 校验应用库变量；`fail(reason, next_step)` 打两行、`raise SystemExit(1)`、**不打堆栈不打密钥**。本 Feature 沿用它的 `fail()` 与输出风格，只加步骤，不重写脚本骨架（`test_selfcheck_reports_readable_reason_when_not_logged_in` 对两个包参数化断言）。
- **步骤**（① ② ④ ⑤ 为本 Feature 新增，③ 复用既有 whoami 段）：① `import bisheng_sdk`（失败 → 打印 `pip install` 自平台端点的命令）；② `GET /api/v1/dev-toolkit/versions` 比对 `sdk.min_compatible`（AC-03 文案含双方版本与处置）；③ auth：有 `BISHENG_APP_ID` 且能对本地入口发一次探测请求（`dev` 期经迷你代理）→ 用 `auth.from_headers` 解析响应回显的头；否则提示「请经 `bisheng dev` 启动」；④ retrieve：`search("selfcheck", top_k=1)`，逐类异常翻译成一句（`ScopeMissingError` → 找管理员勾位；`VisitorCredentialRejectedError` 且 401 → 「平台尚未受理访问者凭据（F052 门面未就绪）」——坑 5 的如实呈现）；⑤ storage：`put("_selfcheck/probe.txt")` → `stat` → `delete`。任何一步失败：`✗ 没通过：<原因> / 下一步：<动作>`，**绝不打 traceback、绝不打密钥**（照 `deploy-hosting/selfcheck.py:25-29` 的 `fail()`）。
- **原因**：AC-28；也是 D7「auth 不探测版本」的补位。
- **何时该重新考虑**：自检步数 > 8 或需要判定平台侧配置（如 `obo_secret` 是否配好）时 → 改为「脚本调一个平台自检端点、只负责呈现」，那时端点归 F053 / F054，本脚本退化成客户端。

### D14：不申请错误码模块（用户预留的 26400–26409 **不使用**）

- **理由**：SDK 侧的可区分性由 Python 异常类承担（D6），它不在 `common/errcode/` 体系内、也不会出现在前端 `api_errors` 文案里；服务端新增的码各归其主——附件 API 归 F054 161 段 `16160-16179` 数据面子段，其中 **`16170–16174` 已由 `wt/storage-handle` 以注释预留**（`app_factory.py:224-234`：`storage_unavailable` / `invalid_object_key` / `payload_too_large` / `not_found` / `unauthorized` 各一，待首个 **backend** 调用方落码；SDK 走 Bearer 直连 manager，遇不到它们）、门面归 F052 / F055 162 段、鉴权归 260；SDK 安装件缺失与 CLI 同型：**真 HTTP 404 + 信封、不是错误码**（`distribution.py:96-117`，F053 CON-8）。申请一个只被 SDK 消费、没有前端文案的模块段，是给 `pnpm check-i18n` 平添三语条目。
- **何时该重新考虑**：出现「只有 SDK 通道才会遇到、且要在平台审计页显示」的服务端错误 → 那时再向 F054 / F055 申请子段，仍不独立成模块。

### D15：托管构建期取包 = 平台提供 PEP 503 简单索引 `GET /api/v1/dev-toolkit/simple/{,bisheng-sdk/}`，runtime-manager 以 `--extra-index-url` 接入；第三方依赖仍走 `--index-url`

- **备选**：A. 让客户把 wheel 放进自家镜像源 — 每个客户多一步运维，AC-02 明令不要求；B. `--find-links <sdk/download>` — pip 要求链接文件名为合法 wheel 名，而下载端点路径不带文件名（要靠 `Content-Disposition`，pip 的 find-links 不看它）；C. 构建期把 wheel 拷进 build context 再 `pip install ./bisheng_sdk-*.whl` — 要 manager 先从 backend 拉 wheel、再改 Dockerfile 模板对每个应用都多 COPY 一层，且 `requirements.txt` 里写 `bisheng-sdk` 的解析仍会去索引找；D. **简单索引 + extra-index**（选定）：索引页列出 `<a href="../sdk/download/bisheng_sdk-0.1.0-py3-none-any.whl#sha256=…">`，pip 按文件名与 hash 取；`Dockerfile.j2` 加 `ARG PIP_EXTRA_INDEX_URL` / `PIP_EXTRA_TRUSTED_HOST`（`templates/python3.11/Dockerfile.j2:21-42` 今天只有 `PIP_INDEX_URL` / `PIP_TRUSTED_HOST`），`builder.py:366-369` 多传两个 buildarg，`config.py` 加 `RTM_BUILD_EXTRA_INDEX_URL` / `RTM_BUILD_EXTRA_TRUSTED_HOST`。
- **为什么是 ops 配的环境变量而不是 backend 推导**：`settings.app_runtime.entry_base_url` 允许为空（「derive from request」，`core/config/app_runtime.py:96-99`），且浏览器可达的入口地址（114 上是 nginx `:4101`）未必是 **docker 构建容器**可达的地址（bridge 网络里 `localhost` 指向容器自己，坑 15）。manager 的 `RTM_BUILD_INDEX_URL` 已是同一形态。
- **下载端点要接受带文件名的路径**：`GET /api/v1/dev-toolkit/sdk/download` 与 `GET /api/v1/dev-toolkit/sdk/download/{filename}` 同一处理器（后者校验 `filename == manifest.sdk.filename`，否则 404）——pip 从索引页链接取的 URL 末段必须是 wheel 文件名。
- **何时该重新考虑**：平台开始分发多个 Python 发布件 → 索引页按包名循环，形状不变。

### D16：SDK ↔ 平台分发件的版本真相链 = `bisheng_sdk.__version__` → `scripts/pack_sdk_wheel.sh` → `artifacts/manifest.json["sdk"]` → `/versions` 载荷；`min_compatible` 的单一来源在 backend

- **`sdk.min_compatible` 是平台的声明**，不是 SDK 的：落 `bisheng/dev_toolkit/sdk_compat.py:SDK_MIN_COMPATIBLE = "0.1.0"`，由打包脚本 `sed` 读入 manifest（照脚本读 `__version__` 的做法），端点只读 manifest（`artifact_service.read_snapshot` 的既有原则：版本是构建属性、不读源码常量）。
- **两个打包脚本改成合并写 manifest**：`pack_cli_wheel.sh:96-110` 今天用 heredoc **整体重写** manifest，且 `:88` `rm -f "${ARTIFACTS_DIR}"/*.whl` 会**删掉 SDK 的 wheel**——两处都改：只删自己前缀的 wheel、用 `python3 -c` 读旧 manifest 合并自己的 section 再写回（坑 9 / 10）。`cli-quality.yml` 的「Artifacts are committed」步骤对 manifest 做 `git diff --quiet`，合并写法保证 CLI 重打不会动 `sdk` 段。

---

## 4. 系统现状（接手必读）

### 4.1 数据流

**A. auth（托管期）**
```
浏览器 → app-proxy（验平台会话 → POST /api/v1/internal/app-proxy/authorize → 拿 material + OBO）
  → strip x-bisheng-* 伪造头 → 注入十头（headers.py:build_upstream_headers）
  → 应用进程：bisheng_sdk.auth.ASGIMiddleware 把 x-bisheng-* 头快照进 ContextVar（_context.py）
  → 业务代码 auth.current_user() → _headers.parse_identity(snapshot) → Identity | raise PlatformIdentityMissingError
```
`dev` 期同形：入口换成 F053 迷你代理（`bisheng_cli/devproxy.py`，剥 `x-bisheng-*` 前缀后注入同十头），服务账号密钥 `login` → `Subject-Kind=service_account` 且无部门三头；个人访问令牌 `login` → `human`（D4「与 spec 的口径差」）。

**B. retrieve**
```
retrieve.search(query, ...) 
  → _context.access_token()（无 → VisitorCredentialMissingError）
  → _compat.ensure_compatible(base)（每进程一次；GET /api/v1/dev-toolkit/versions）
  → POST {BISHENG_PLATFORM_API_BASE}/api/v2/filelib/retrieve  Authorization: Bearer <token>  body=RetrieveReq
  → _http.parse_envelope → 200: RetrieveResult ；错误: _codes.map(status, code) → errors.*
```
服务端（非本 Feature）：`verify_open_api_access` 受理 OBO → 门面按 `sub.app_id` 定白名单 ∩ `sub.user_id` 可见范围（F055 T057 / F052 AC-21）→ 审计 actor=app / subject=user（F055 T059）。

**C. storage**
```
storage.put(path, data)
  → _paths.validate(path)（InvalidAttachmentPathError；规则 = manager validate_key）
  → storage._backend()：ENDPOINT(+TOKEN) → _RemoteBackend ；DIR → _LocalDirBackend ；其余 → StorageHandleMissingError
  → 已知长度 > BISHENG_APP_STORAGE_MAX_FILE_MB → AttachmentTooLargeError（零请求 / 零落盘）
  → Remote: PUT {ENDPOINT}/objects/{path}  Authorization: Bearer <BISHENG_APP_STORAGE_TOKEN>  body=原始字节流
            → 200 meta ；错误 {"detail":{"code":…}} → _codes.map_storage(code, http_status) → errors.*
    Local : tmp 文件 + os.replace 原子落 <DIR>/<path>
  → AttachmentMeta
```
服务端（F054，已实现）：`api/storage.py:verify_storage_caller` 以 `hmac.compare_digest` 比对期望态记录里的 token → `AppStorageService.upload` 强制前缀 `apps/{app_id}/attachments/`、桶 `bisheng-apps`。

**D. 分发与构建**
```
scripts/pack_sdk_wheel.sh → uv build → 清 venv 装 wheel 冒烟 → 拷 artifacts/ → 合并 manifest["sdk"]
backend: GET /api/v1/dev-toolkit/versions（sdk 段）· /sdk/download[/{filename}] · /simple/ · /simple/bisheng-sdk/ · /sdk-guide.md
runtime-manager 构建：pip install --index-url $PIP_INDEX_URL --extra-index-url $PIP_EXTRA_INDEX_URL -r requirements.txt
```

### 4.2 关键数据结构 / 字段约定（对外契约）

**① 注入头 → `Identity` 映射**（头名照 `app-proxy/headers.py:29-40`，`_headers.py` 逐字复制）

| 头 | `Identity` 字段 | 解码 | 缺失时 |
|---|---|---|---|
| `X-BiSheng-User-Id` | `user_id: str` | 原样 | **抛 `PlatformIdentityMissingError`** |
| `X-BiSheng-User-Name` | `user_name: str` | `unquote` | `""` |
| `X-BiSheng-Tenant-Id` | `tenant_id: str` | 原样 | `""` |
| `X-BiSheng-Dept-Id` / `-Dept-Name` / `-Dept-Path` | `dept_id` / `dept_name` / `dept_path: str \| None` | `unquote`（Path 保留 `/`） | `None`（服务账号 / 无部门） |
| `X-BiSheng-Subject-Kind` | `subject_kind: str` | 原样（`human` / `service_account`） | `"human"`（与注入侧缺省一致，`entry_authz_service.py:172`） |
| `X-BiSheng-App-Id` | `app_id: str` | 原样 | `""` |
| `X-BiSheng-Request-Id` | `request_id: str \| None` | 原样 | `None` |
| `X-BiSheng-Access-Token` | **不上对象**；`_context.access_token()` 供 retrieve | 原样 | retrieve 抛 `VisitorCredentialMissingError` |

头名匹配按归一化（小写、`_`→`-`）做，与 `headers.py:normalize_header_name` 同规则；WSGI 的 `HTTP_X_BISHENG_*` 同样归一。

**② 环境变量（SDK 读取清单，`_env.py`）**

| 变量 | 谁注入 | SDK 用途 |
|---|---|---|
| `BISHENG_PLATFORM_API_BASE` | F054 `lifecycle.py:164`（值 = `settings.app_runtime.entry_base_url`，经 `app_state_service.py:405`）· F053 `dev` 同名（`devdb.py:INJECTED_ENV`，值 = 当前 `login` 平台地址）✅ 已实现 | retrieve 与版本探测的 base URL；空 → `PlatformUnreachableError`（文案点名该变量与 `app_runtime.entry_base_url`） |
| `BISHENG_APP_STORAGE_ENDPOINT` · `BISHENG_APP_STORAGE_TOKEN` · `BISHENG_APP_STORAGE_MAX_FILE_MB` | **F054 T085 ✅**（`wt/storage-handle`：`lifecycle.py:build_env` → `storage.storage_env`；backend 副本 `app_runtime/domain/constants.py:APP_STORAGE_ENV_NAMES`） | 托管期附件 HTTP 句柄（④）；`_MAX_FILE_MB` 用于发送前预判 |
| `BISHENG_APP_STORAGE_DIR` | **F053 T043 的增补项**（本文定名；`wt/cli-dev` 的 `dev` **尚未注入**，坑 34 / §6.2 契约 ⑦） | 本地期目录句柄（D8） |
| `BISHENG_APP_STORAGE_MAX_FILE_MB`（本地） | 可选（F053 `dev` 可注入，与线上同名） | 本地期单文件上限；不注入 = 不限（坑 23） |
| `BISHENG_SDK_TRUST_ENV` | 开发者 | `=1` 时 httpx 读代理环境变量（D11） |

SDK **不读** `BISHENG_APP_TOKEN` / `BISHENG_API_KEY` / 任何密钥类变量（CON-3；tests 以源码 grep 断言）。

**③ retrieve 线上契约**（= `POST /api/v2/filelib/retrieve` 既有形状，`open_endpoints/domain/schemas/filelib.py:39-69`）

```jsonc
// 请求  Authorization: Bearer <X-BiSheng-Access-Token 的值>
{ "query": "…", "knowledge_base_ids": [1, 2],          // None 时省略该键（待 F052 放宽必填）
  "filters": {"knowledge_base_filters": [{"knowledge_base_id": 1, "tags": ["a"], "tag_match_mode": "any"}]},
  "top_k": 10, "max_content": 15000 }
// 200 → 信封 data
{ "chunks": [{"content": "…", "knowledge_id": 1, "document_id": 7, "document_name": "x.pdf",
              "chunk_index": 3, "document_update_time": "2026-09-01 10:00:00"}], "total": 1 }
// 错误 → 真 HTTP 状态 + 信封 {status_code, status_message, data}（/api/v2 口径）
```

**④ storage 附件 API 契约**（**F054 T084 已实现**，`runtime_manager/api/storage.py` + `storage.py`；SDK `_storage_remote.py` 消费——本表是消费者视角快照，以对方源码为准，`test_contract_alignment.py` 对账路由、常量与路径规则）

`{E}` = `BISHENG_APP_STORAGE_ENDPOINT`（已含 `/v1/apps/{app_id}/storage`）；所有请求 `Authorization: Bearer {BISHENG_APP_STORAGE_TOKEN}`；`{key}` = 应用内相对路径，按 D9 规则、**逐段 `quote(seg, safe="")` 后拼进 URL**（服务端 `{key:path}` 解码）。

| 操作 | 请求 | 成功 | 失败（真 HTTP 状态 + manager 信封） |
|---|---|---|---|
| 上传 | `PUT {E}/objects/{key}`，body = **原始字节**（非 multipart），`Content-Type` 可选（缺省 `application/octet-stream`），`Content-Length` 尽量带（服务端先按它拒 413，缺失则按流计数） | `200 {key,size,content_type,etag,last_modified}` | `400 invalid_object_key` · `413 payload_too_large` · `401 unauthorized` · `503 storage_unavailable` |
| 下载 | `GET {E}/objects/{key}` | `200` 字节流 + `Content-Type` + `Content-Length`（+ `ETag`） | `404 not_found` |
| 元信息 | `GET {E}/meta/{key}` | `200 {key,size,content_type,etag,last_modified}` | `404 not_found` |
| 列举 | `GET {E}/objects?prefix=&cursor=&limit=`（`limit` 1–1000、缺省 100；`cursor` = 上页最后一个 `key`） | `200 {objects:[meta…], next_cursor: str\|null}`，按 key 升序 | `400 invalid_object_key`（prefix / cursor 非法） |
| 删除 | `DELETE {E}/objects/{key}` | **`200 {}`**（不是 204） | `404 not_found`（缺失不是静默成功） |

- **错误信封 = manager 形状** `{"detail": {"code": "<机器码>", "message": "…", …extra}}`（`runtime_manager/errors.py:RuntimeManagerError`），**不是** backend 的 `{status_code, status_message, data}`——`_http.parse_envelope` 必须认两种（坑 26）。机器码 → 异常：`unauthorized` → `StorageHandleRejectedError(reason=detail.message)` · `invalid_object_key` → `InvalidAttachmentPathError` · `payload_too_large` → `AttachmentTooLargeError` · `not_found` → `AttachmentNotFoundError` · `storage_unavailable` / 连接失败 → `StorageUnavailableError` · 其它 → `PlatformRefusedError(code=None, details=detail)`。**没有 403、没有「应用下线」专用码**：下线 = 期望态记录消失 = 401（坑 28）。
- **`AttachmentMeta` 映射**：`key` → `path`；`last_modified`（ISO 8601 字符串，MinIO 无值时 `""`）→ `modified_at: datetime | None`；`etag` 保留；`size` / `content_type` 原样。
- 鉴权：`app_id` 只由 URL（F054 注入）与令牌的绑定关系决定，A 的 token 打 B 的 URL = 401；无 Bearer 的请求走 HMAC（backend / F052 用，**SDK 永不走**）。对象键 = `apps/{app_id}/attachments/{key}`、桶 `bisheng-apps`——对 SDK 与应用**不可见**；不计租户存储配额；backend 错误码 `16170–16174` 由 F054 预留（`app_factory.py:224-234`）、待首个 backend 调用方落码，SDK 不依赖它们。

**⑤ `/versions` 载荷的 `sdk` 段**（今天是 `{"version": null, "min_compatible": null, "download_path": null}` 三键留位，`distribution.py:80`；本 Feature **填值并追加三键**，已有三键语义不变）

```jsonc
"sdk": { "version": "0.1.0", "min_compatible": "0.1.0",
         "filename": "bisheng_sdk-0.1.0-py3-none-any.whl", "sha256": "…",
         "download_path": "/api/v1/dev-toolkit/sdk/download",
         "index_path": "/api/v1/dev-toolkit/simple/" }      // 未打包 / 未提交 → 整段 null，notice 说明
```

**⑥ 新增端点**（同 F053 D10：匿名、`open_platform.enabled=false` 时路由不注册 → 404）

| 端点 | 返回 |
|---|---|
| `GET /api/v1/dev-toolkit/sdk/download` · `GET …/sdk/download/{filename}` | `FileResponse` wheel；缺失 → 真 404 + 信封 `SDK_MISSING_MESSAGE` |
| `GET /api/v1/dev-toolkit/simple/` | PEP 503 HTML：`<a href="bisheng-sdk/">bisheng-sdk</a>` |
| `GET /api/v1/dev-toolkit/simple/bisheng-sdk/` | HTML：`<a href="../../sdk/download/{filename}#sha256={sha256}">{filename}</a>`；缺失 → 404 |
| `GET /api/v1/dev-toolkit/sdk-guide.md` | `text/markdown` = `skills/platform-wiring/SKILL.md`；缺失 → 404 |

**⑦ manifest.json**（`bisheng/dev_toolkit/artifacts/manifest.json`，两个脚本各写自己的 section）

```jsonc
{ "cli": {…既有…}, "sdk": {"version": "0.1.0", "min_compatible": "0.1.0", "filename": "…", "sha256": "…"},
  "platform": {"version": "3.0.0"}, "_note": "…" }
```

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `bisheng_sdk/__init__.py` | `__version__`、`__all__`、导出三模块 | 不做任何 I/O |
| `bisheng_sdk/auth.py` | `Identity`、`current_user()`、`from_headers()`、`bind()`、`ASGIMiddleware`、`WSGIMiddleware` | 不验签、不解析令牌、不读环境变量 |
| `bisheng_sdk/retrieve.py` | `search` / `asearch`、`RetrieveResult` / `Chunk` / `KnowledgeBaseFilter` | 不过滤、不缓存、不读进程级凭据 |
| `bisheng_sdk/storage.py` | 六函数 + 异步孪生、`AttachmentMeta`、后端选择 | 不暴露 URL / 键 / 桶；不清空 |
| `bisheng_sdk/errors.py` | 异常层次 + `redact()` | — |
| `bisheng_sdk/_context.py` | `ContextVar[RequestSnapshot]`、`bind` / `access_token` | — |
| `bisheng_sdk/_headers.py` / `_env.py` | 头名 / 环境变量名常量、归一化、解码、`parse_identity` | — |
| `bisheng_sdk/_http.py` | 客户端池、超时、**两种信封**解析（backend `status_code` / manager `detail.code`）、`_codes` 映射 | 不重试 |
| `bisheng_sdk/_compat.py` | 懒版本探测与缓存 | — |
| `bisheng_sdk/_codes.py` | backend `int code → 异常类` 表 + manager `str code → 异常类` 表 + `TARGET_UNREACHABLE_CODES` 留位 | — |
| `bisheng_sdk/_paths.py` · `_storage_local.py` · `_storage_remote.py` | 路径规则（镜像 manager `validate_key`）、两个后端；远端后端只认 `ENDPOINT` + `TOKEN`、路径逐段 percent-encode | 不拼 `app_id`、不走 HMAC |
| backend `dev_toolkit/domain/services/artifact_service.py` | `SdkArtifact` + `DistributionSnapshot.sdk` + `read_sdk_guide()` | 不读 DB |
| backend `dev_toolkit/api/endpoints/distribution.py` | ⑥ 的四个端点 + `versions` 的 `sdk` 段 | 无鉴权依赖 |
| backend `dev_toolkit/sdk_compat.py` | `SDK_MIN_COMPATIBLE` 常量 | — |
| backend `dev_toolkit/skills/platform-wiring/` | **增量**：SKILL.md 的 SDK / retrieve / storage 三段 · 新目录 `example-sdk/`（装 SDK 的 FastAPI 样例）· `selfcheck.py` 追加三步 | 不新建包、不改章序与警示块、不动既有 `example/`（零依赖样例是 AC-32 的第二条合法路径） |
| `scripts/pack_sdk_wheel.sh` | 构建 → 冒烟 → 暂存 → 合并 manifest | 不动 `cli` 段 |
| runtime-manager `config.py` / `builder.py` / `templates/python3.11/Dockerfile.j2` | extra index 两个 buildarg（+ `docs/architecture/14-app-factory-deployment.md:151` 环境变量表追两行） | — |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | `X-BiSheng-Subject-Kind` 线上字面值是 **`human`**（`entry_authz_service.py:_user_facts` 硬编码），不是 `api_credential` 的 `natural_person` | SDK 若按 `natural_person` 判自然人，线上全部误判成"服务账号" | D4 透传；指南写「自然人 = `human`」 |
| 2 | 部门三头**缺失 = 不发**而非空串（`headers.py:161-164`） | 用 `== ""` 判无部门永远为假 | D4 映 `None` |
| 3 | 非 ASCII 头值被 `quote(safe="/")`；ASCII 值原样（`_encode`） | 中文名读出来是 `%E5%BC%A0…`；一个含字面 `%E5` 的 ASCII 名会被误解码（病态输入，接受） | `_headers.py` `unquote` |
| 4 | **OBO 今天没有消费者**：`obo_secret` 空或等于 `jwt_secret` 时 app-proxy **不注入** `X-BiSheng-Access-Token`（`entry_authz_service.py:401-411`，每进程只 warn 一次） | 托管期 auth 正常、retrieve 抛 `VisitorCredentialMissingError`，看起来像 SDK 的 bug | 异常 `next_step` 点名 `app_runtime.obo_secret`；selfcheck ④；§6.2 阻塞项 ② 要求 F052/F055 落地时把签发改 fail-closed |
| 5 | `validate_bearer` 的 `_TOKEN_RE` 只认 `bs-sak-` / `bs-pat-`（`credential_validator.py:43`）→ OBO Bearer 今天答 `26001`（HTTP 401） | SDK 报「凭据被拒」，开发者去换密钥——换什么都没用 | selfcheck ④ 文案；`VisitorCredentialRejectedError.next_step` 含「平台未受理访问者凭据时请确认 F052 门面已部署」 |
| 6 | `RetrieveReq.knowledge_base_ids` 必填 `min_length=1`、`extra="forbid"`（`schemas/filelib.py:40-45`） | `search(query)` 不带库 id 今天答 422 → `PlatformRefusedError(422)` | D5 省略键 + §6.2 契约 ③；指南本轮示例必带 `knowledge_base_ids` |
| 7 | `/api/v1` 业务错误是 HTTP 200 + 信封，`/api/v2` 是真状态 + 信封（F053 坑 12） | 先看 HTTP 状态会把 `/versions` 的降级载荷当失败、把 v2 的 401 当无信封 | `_http.parse_envelope` 先读 body `status_code` |
| 8 | F053 测试**断言 `sdk` 三键全 null**（`test/dev_toolkit/test_distribution_api.py:80-81`、`:228`；`wt/cli-dev` 上同两处漂到 `:82-83`、`:230`） | 填上 `sdk` 段的那一刻 F053 套件红 | T026 同批改断言（同一 PR） |
| 9 | `pack_cli_wheel.sh:106-119` 用 heredoc **整体重写** manifest | 下一次重打 CLI wheel 静默删掉 `sdk` 段，平台 `/versions` 又答 null、托管构建装不到 SDK | D16：两个脚本都改成 python 合并写 |
| 10 | `pack_cli_wheel.sh:97` `rm -f "${ARTIFACTS_DIR}"/*.whl` | 重打 CLI 时把 SDK wheel 一起删了，manifest 还指着它 → `/sdk/download` 404 | 改成 `rm -f bisheng_cli-*.whl`；SDK 脚本同理只删 `bisheng_sdk-*.whl` |
| 11 | `.gitignore` 的 `build/ lib/ wheels/ sdist/` 无前导斜杠、任意层级生效 | 产物目录改名就 `git add` 静默失败 | 沿用 `artifacts/`，脚本末尾 `git check-ignore` 自检 |
| 12 | 目录带连字符时 hatchling 不能推断包目录 | `uv build` 打出**空 wheel**，装得上、`import` 失败 | `packages = ["bisheng_sdk"]` + 脚本 `unzip -l` 校验（照 CLI，注意 `pipefail` 下不能 `\| grep -q`） |
| 13 | Streamlit 每次 rerun 是新线程，`ContextVar` 为空；请求头只能从 `st.context.headers`（≥ 1.37）拿 | 中间件式接法在 Streamlit 下永远 `PlatformIdentityMissingError` | D3 接法 3；指南 Streamlit 段 |
| 14 | Starlette `BaseHTTPMiddleware` 在独立任务里跑 `call_next`，ContextVar token 跨任务 `reset` 抛 `ValueError` | 中间件第二个请求起崩 | D3：纯 ASGI 可调用 |
| 15 | docker 构建容器在 bridge 网络：`localhost` 指向容器自身；http 索引要 `--trusted-host` | `RTM_BUILD_EXTRA_INDEX_URL=http://localhost:7860/...` 构建必失败，日志像"pip 拉不到包"= 平台故障 | D15：ops 配宿主机 IP；Dockerfile 加 trusted-host；T032 在 114 验 |
| 16 | pip 简单索引只认 PEP 503 规范化名 `bisheng-sdk` 与合法 wheel 文件名；`#sha256=` 让 pip 校验 | 链接末段不是文件名 → pip 跳过该链接、静默回落主索引找不到 | D15 下载端点接受 `/{filename}` |
| 17 | `open_platform.enabled=false` 时 `dev-toolkit` 整个 router 不注册（`api/router.py:141`） | 关开关的平台上托管构建装 `bisheng-sdk` 必 404 | 指南写明；F054 AC-30 / F053 AC-05 前提 |
| 18 | runtime-manager 日志脱敏按**环境变量名**匹配（`api/readonly.py:57-68`，`*TOKEN*` / `*SECRET*`，短值不脱） | 应用若把 token 复制进别的变量名（如 `MY_KEY`）再打日志就不会被脱敏 | F054 定名 `_TOKEN`（`test_logs_redact_known_injected_secrets` 读真铸造的 token 断言 `***`）；指南写「不要复制句柄变量」 |
| 19 | `entry_base_url` 允许为空（「derive from request」）→ `BISHENG_PLATFORM_API_BASE` 注入空串（`app_state_service.py:405`） | retrieve 打到 `/api/v2/...` 相对地址 → httpx 报 `UnsupportedProtocol`，看不出是配置缺失 | `_env.py` 空串即抛 `PlatformUnreachableError` 并点名配置键 |
| 20 | `dev` 期 `X-BiSheng-User-Id` 是服务账号 id，与线上 user id 不是一张表（F053 K15） | 应用把它当 `user.id` 去查平台用户 / 做外键 | D4 `str` + 指南 auth 章 |
| 21 | 同进程 `ContextVar` 在后台线程 / `asyncio.create_task` 里：新线程为空，新任务是**副本**（能读到父请求的身份） | 请求里 `create_task` 出去的后台任务能拿到身份并检索——这是 asyncio 语义，不是 SDK 兜底；线程池则抛错 | 指南写明「后台任务不要假设有访问者」；SDK 不额外清空副本（清空会破坏 FastAPI 依赖注入的正常任务树） |
| 22 | arch-guard RULE-7 扫 `api_key = "<8+ 字符>"` 字面量，对 `src/bisheng-sdk/tests/` 也出声（WARNING） | 长期噪声让真正的硬编码密钥那天没人看 | 假令牌一律拼接（`"bs-sak-" + "x" * 43`） |
| 23 | 本地期单文件上限只在 `bisheng dev` 注入了 `BISHENG_APP_STORAGE_MAX_FILE_MB` 时生效（线上 F054 恒注入，缺省 20 MB） | 本地传 500 MB 通过、线上 413 | 指南 storage 章列为四处差异之外的第五处；F053 T043 建议按平台 `RTM_STORAGE_MAX_FILE_MB` 同值注入 |
| 24 | `skills sync` 只拉 `DEFAULT_PACKS`（`3.0-vibe` 的 `commands/skills.py:57` = `("deploy-hosting",)`；`wt/cli-dev` 已改成两元素并重打过 wheel） | 新包已可下载但没人拉；`login` 后开发者的 AI 仍不知道 SDK | T038：合并后**先核对**，只在仍为单元素时才改 + 重打（与 SDK wheel 串行，避免二进制冲突） |
| 25 | F055 `16273` / `16274` 已在 errcode 文件登记但**无写入方**（Wave 5 顺延） | 单测能过，114 上永远触发不到 | tasks 标 `[受阻于 F055 T058]`，只用 mock |
| 26 | manager 的错误信封是 `{"detail": {"code": "<str>", "message"}}`（`runtime_manager/errors.py:38-47`），backend 是 `{status_code: <int>, status_message, data}` | 用一套解析，storage 的 401 / 413 / 404 全落成 `PlatformRefusedError`、机器码丢失 | `_http.parse_envelope` 认两种；`_codes` 分 int 表与 str 表 |
| 27 | `BISHENG_APP_STORAGE_ENDPOINT` 指向 runtime-manager 的**应用面地址**（compose = `http://runtime-manager:8091`，systemd = `bisheng-apps` 网桥网关如 `172.18.0.1:8091`，由 `RTM_APP_FACING_BASE_URL` 决定），不是平台 API；manager 只听 `127.0.0.1` 且没配该变量时应用容器根本够不到 | storage 全部 `StorageUnavailableError`（连接拒绝），像 SDK 坏了 | `StorageUnavailableError.next_step` 点名 `runtime/status` preflight `attachment_storage`；F054 契约 §2 已写修法；F054 出站白名单落地时须放行该地址（契约 §9） |
| 28 | 附件 API 没有 403、没有「应用下线」专用码：token 错、应用 destroy、无 Bearer **全是 401 `unauthorized`**（`api/storage.py:verify_storage_caller`） | 想按「下线」与「句柄失效」分支的应用分不出来 | `StorageHandleRejectedError` 一类、`reason` = `detail.message`；AC-25 只要求与 NotFound / Unavailable **彼此可区分**，满足 |
| 29 | `delete` 成功答 `200 {}` 不是 204；元信息路径是 `/meta/{key}` 不是 `/stat/`；`apps/` 前缀**即使是自己应用的**也 400；`prefix` / `cursor` 按 key 同规则校验 | 照 REST 直觉写客户端会把 200 当异常、把 stat 打到 404 | §4.2 ④ 表；`test_contract_alignment.py` 读 `api/storage.py` 文本对账路由 |
| 30 | `wt/storage-handle`（F054 T084 / T085）**尚未合入 `3.0-vibe`**（`git branch --contains 23886547f` 只列它自己） | 在 `3.0-vibe` 上跑对账测试会发现 `runtime_manager/storage.py` 不存在，误判「契约不存在」 | 合并顺序：storage-handle 先于 F057 实现分支；对账测试在文件缺失时 `skip` 并打印原因；远端后端单测只依赖 `httpx.MockTransport` |
| 31 | **`skills/platform-wiring/` 已经存在**（F053 T038 于 `wt/cli-dev` `b61b209e4`：226 行 SKILL.md + `example/` + `selfcheck.py`），auth 章里留的是一节「SDK 用法（随后续版本补齐）」桩 | 照初稿「新建 SKILL.md」写会覆盖掉身份 / 应用数据库 / `dev` 三章，且 F053 的 `test_skill_packs.py`（`PACKS` 已参数化两包 + `WIRING` 专项断言）当场红 | D12 改为增量编辑：换桩、插两章、保留章序与警示块；T033 / T034 / T036 的动作全部是 `（增量）` |
| 32 | `bisheng dev` 每请求注入的 `X-BiSheng-Access-Token` 是**本地 HMAC 自签**的 `bsdev.<b64>.<sig>`（`devproxy.py:HandleMinter`），平台无从验签 | 以为「dev 已落地 → 本地 retrieve 能跑」，在 114 上看到 401 会误判成 SDK 或密钥问题 | D5 ③：修法归 F053 / F052（`dev` 用 `login` 密钥换平台签发的短时凭据）；SDK 零改动；§6.2 阻塞项 ③ |
| 33 | `dev` 的 `X-BiSheng-Subject-Kind` **取决于 login 密钥种类**：`bs-sak-` → `service_account`、`bs-pat-` → `human`（`devproxy.py:204-213` 按 `whoami.actor_kind`） | 把「本地恒 service_account」写进指南或断言，PAT 开发者一跑就打脸 | D4；指南 auth 章按「取决于你 login 用的密钥」写；测试两种都覆盖 |
| 34 | `dev` 的注入清单（`devdb.py:INJECTED_ENV`）**没有任何 `BISHENG_APP_STORAGE_*`** | 本地 storage 恒 `StorageHandleMissingError`，看着像 SDK 后端选择写错了 | D8 本地期段；§6.2 契约 ⑦ 回写 F053；T016 / T020 用例直接 `monkeypatch.setenv` 造句柄，不依赖 `dev` |
| 35 | `wt/cli-dev` **已重打并提交 CLI wheel**（`manifest.json.cli.sha256=fe51ceea…`），而本 Feature 的 T029 也要写同一个 `artifacts/` 目录 | 两分支都动同一个二进制 + manifest，合并必冲突且无法 textual merge | 合并顺序：`wt/cli-dev` → `wt/storage-handle` → F057 实现分支；F057 落地时**重跑两个打包脚本各一次**（合并写 manifest 后 `cli` 与 `sdk` 段并存），不手工改 manifest |
| 36 | F053 的 `test_auth_chapter_teaches_exactly_app_proxys_header_names` 断言 **SKILL.md 全文反引号里的 `X-BiSheng-*` 名集合 == app-proxy 的十个**，且 `X-BiSheng-Access-Token` 行必须含「不要依赖」 | 新写的 retrieve / storage 章里随手提一个不存在的头名，或让 SDK 开始消费 Access-Token 却不改那行文案，套件都会红——而报错信息指向 F053 的测试，容易被误判成「对方的测试坏了」 | T033 ①④：两章不得引入第十一个头名；Access-Token 行文案与 F053 那条断言**同批**改 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `bisheng_sdk.auth` / `retrieve` / `storage` / `errors` 公开面（§4.2 ①、D6、D9） | Python API（wheel） | 托管应用、PRD-2 WB-01 模板（同一范式，AC-32）、技能包样例 |
| `bisheng_sdk._headers.INJECTED_HEADER_NAMES` 等常量（与 app-proxy 逐字一致） | Python 常量 | **F053 T042** `dev` 迷你代理可直接复用（避免第三份头名表） |
| 本地期环境变量名 `BISHENG_APP_STORAGE_DIR`（+ 可选同名 `BISHENG_APP_STORAGE_MAX_FILE_MB`）与 `.bisheng/attachments/` 落点（§4.2 ②、D8） | 环境变量契约 | **F053 T043 的增补项**（`dev` 今天未注入，坑 34）；托管期三名归 F054，本文只消费 |
| `platform-wiring` 包 auth 章「SDK 用法」桩的填法与 retrieve / storage 两章的位置（D12） | 技能包文本契约 | **F053 T038 的后继编辑者**（本 Feature）；F053 的 `test_skill_packs.py` 断言是这份契约的守卫 |
| `_paths.validate` = manager `validate_key` 镜像 + `_storage_remote` 路径 / 信封形状（§4.2 ④） | 对账测试 | 若 F054 改 `validate_key` / 路由 / 信封，`test_contract_alignment.py` 先红 |
| `GET /api/v1/dev-toolkit/sdk/download[/{filename}]` · `/simple/…` · `/sdk-guide.md`；`/versions` 的 `sdk` 段（§4.2 ⑤⑥） | HTTP（匿名） | 开发者、pip、runtime-manager 构建、selfcheck、接入信息区（F053 顺延项） |
| `platform-wiring` 技能包（三件套 + 两条标准库接法章） | 技能包（`skills sync`） | 开发者的 coding agent；**F053 T038 以此收口** |
| `manifest.json["sdk"]` 段 + `scripts/pack_sdk_wheel.sh` | 构建契约 | CI `sdk-quality.yml`；发布流程（改 SDK 必重打并提交 wheel） |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 状态（`fe10f75ea`） | 风险点 / 本文任务 |
|---|---|---|---|
| app-proxy 注入十头 + OBO（F054 AC-31 / AC-34；`headers.py:29-40`、`entry_authz_service.py:284-306, 379-425`） | HTTP 头契约 | ✅ 已落码；**OBO 仅在 `obo_secret` 配置正确时注入** | 头名变更 → `_headers.py` 三处对账测试先红；坑 4 |
| `bisheng dev` 迷你代理注入同构十头 + 每请求短时凭据 + 同名环境变量（F053 T042–T044） | CLI | ✅ **已实现于 `wt/cli-dev` `b61b209e4`，未合入 `3.0-vibe`**（`3.0-vibe` 仍是 `cli.py:24 DEFERRED_COMMANDS=("dev",)`） | 十头逐字同 app-proxy（`devproxy.py:INJECTED_HEADER_NAMES`）→ `_headers.py` 可三处对账；`subject_kind` 随密钥种类（坑 33）；**未注入 `BISHENG_APP_STORAGE_*`**（契约 ⑦）、访问凭据为本地自签（阻塞项 ③） |
| **阻塞项 ③** `dev` 的 `bsdev.` 访问凭据需换成**平台签发**的短时凭据（F053 `devproxy.HandleMinter` → 平台兑换端点；或等价方案） | CLI + 服务端 | ❌ 未实现（坑 32） | 本地期 retrieve 端到端不可验（答 `26001`）；AC-14 只能单测；修法归 F053 / F052，SDK 零改动（D5 ③） |
| **契约 ⑦** `dev` 注入 `BISHENG_APP_STORAGE_DIR`（+ 可选 `BISHENG_APP_STORAGE_MAX_FILE_MB`）（F053 T043 增补） | 环境变量 | ❌ 未注入（`devdb.py:INJECTED_ENV`，坑 34） | 本地期 storage 端到端不可验；T016 / T020 用例自造句柄；回写 F053 |
| `skills/platform-wiring/` 包本体（SKILL.md 五章 + `example/` + `selfcheck.py`）与 `DEFAULT_PACKS` 两元素（F053 T038） | 技能包 + CLI 常量 | ✅ **已实现于 `wt/cli-dev`，未合入** | 本 Feature 做增量编辑（D12）；改章序 / 警示块会让 F053 断言先红（坑 31）；`artifacts/` 二进制合并顺序见坑 35 |
| **阻塞项 ②** 后端受理 OBO Bearer 于 `/api/v2/filelib/retrieve`，执行身份 = `sub.user_id`、白名单 = `sub.app_id` 当前生效声明、审计双归属、签发改 fail-closed（**F052 门面 + F055 T057 / T058 / T059**；`credential_validator.py:43`） | 服务端 | ❌ 未实现（F052 无 design / tasks） | 托管期 retrieve 端到端不可验；SDK 按现有线上契约落码 + mock；坑 5 |
| **契约 ③** `RetrieveReq.knowledge_base_ids` 可省略（F052 AC-22） | schema | ❌ 今天必填 | `search(query)` 无库 id → 422；T014 用例标 `[受阻于 F052]` |
| **契约 ④** F052「不可及」错误码 + `data.unreachable_ids`（AC-11）；「能力已收回」经 F055 转成 `16273` | 错误形状 | ❌ F052 未分配 | `_codes.py` 留位；T014 用例按占位码 |
| **契约 ⑤** 附件 API 服务端 + `BISHENG_APP_STORAGE_ENDPOINT/_TOKEN/_MAX_FILE_MB` 注入（F054 T084 / T085；`runtime_manager/storage.py`、`api/storage.py`、`lifecycle.py:build_env`） | 服务端 + 环境变量 | ✅ **已实现于 `wt/storage-handle` `23886547f`，未合入 `3.0-vibe`**（坑 30） | SDK 远端后端按其契约落码（§4.2 ④）+ 对账测试；114 联调要求该分支先部署且 `RTM_MINIO_*` / `RTM_APP_FACING_BASE_URL` 已配（F054 契约 §2 / `docs/architecture/14`）；无回写 |
| `GET /api/v1/dev-toolkit/versions` `sdk` 字段位（F053 D11；`distribution.py:76-80`） | HTTP | ✅ 留位为 null | T027 填值；坑 8 |
| `artifact_service.read_skill_pack` / `read_install_guide` 模式（`artifact_service.py:211-243`） | 内部 Python | ✅ | 新包目录自动分发；`sdk-guide.md` 照 `install-guide` 形态 |
| `scripts/pack_cli_wheel.sh` 与 `cli-quality.yml` 的 manifest 契约 | 构建脚本 | ✅ 但会**清空 `sdk` 段 / 删 SDK wheel** | T023 同批改 CLI 脚本（坑 9 / 10） |
| runtime-manager 构建参数（`builder.py:366-369`、`config.py:159-160, 231-232`、`Dockerfile.j2:21-42`） | 构建契约 | ✅ 只有 `PIP_INDEX_URL` | T030–T032 加 extra index |
| F055 `BISHENG_APP_TOKEN` 注入（T056）与 `16273` / `16274` 写入方（T058） | 环境变量 / 错误码 | ❌ 未实现 | SDK 不读前者（CON-3）；后者只 mock（坑 25） |
| `bisheng_cli.commands.skills.DEFAULT_PACKS` | CLI 常量 | ✅ 只含 `deploy-hosting` | T038 追加 + 重打 CLI wheel（坑 24） |

**跨 Feature 回写登记（本文提出、对方 tasks 受理）**：
1. **F054**：**无回写**——附件句柄契约以 `wt/storage-handle` 为准，本文初稿的 backend 落点 / `_URL` 命名 / `16163+` 建议全部作废。仅登记一句事实供对方知悉：F057 `_storage_remote.py` 是该 router 的 Bearer 路径首个消费者，`validate_key` / 路由 / 信封任何改动会让 F057 `test_contract_alignment.py` 先红。
2. **F053**（T042–T044 / T038 已交付于 `wt/cli-dev`，以下是**在其之上的增补**，各写成对方 tasks 的追加条目）：
   - **T043 增补**：注入 `BISHENG_APP_STORAGE_DIR=<项目根>/.bisheng/attachments/`（绝对路径）并写 `.bisheng/.gitignore`；建议同名注入 `BISHENG_APP_STORAGE_MAX_FILE_MB`（值取平台 `RTM_STORAGE_MAX_FILE_MB`，坑 23）；**不注入 `BISHENG_APP_STORAGE_ENDPOINT`**（否则 SDK 判「句柄不唯一」）。契约 ⑦。
   - **T042 增补**：`devproxy.HandleMinter` 现铸的 `bsdev.` 句柄改为**平台签发**的短时凭据（用 `login` 密钥换取、`login` 密钥仍不进应用进程），否则本地期 retrieve 恒 `26001`（坑 32 / 阻塞项 ③）。
   - **已无需回写**：`INJECTED_HEADER_NAMES` 十头已与 app-proxy 逐字一致（`devproxy.py:63-74`）；`DEFAULT_PACKS` 已含 `platform-wiring`。
3. **F052 / F055**：OBO Bearer 受理（含 `entry_authz` 签发改 fail-closed）与 **`bsdev` 一类平台签发的本地短时凭据受理**；`knowledge_base_ids` 可省略；「不可及」码与 `data.unreachable_ids`；`16273` 载荷含 `data.capability` 与 `data.reason="revoked"`。

---

## 7. 测试与可观测

- **SDK 单测**（`src/bisheng-sdk/tests/`，`cd src/bisheng-sdk && uv sync --frozen --extra dev && uv run pytest`）：零网络（autouse 哨兵把 `httpx.Client` / `AsyncClient` 默认 transport 换成抛 `AssertionError` 的 transport，同 CLI T002）；所有平台响应经 `tests/helpers/platform_mock.py` 的 `httpx.MockTransport` 工厂按 §4.2 ③④⑤ **逐字**构造；`@pytest.mark.network` 用例默认跳过、只在 114 手验跑。三处对账测试读仓内文件（`src/app-proxy/app_proxy/headers.py`、F054 contracts §5 表）——在仓外跑时 `pytest.skip`。
- **后端测试**（`src/backend/test/dev_toolkit/`，`asyncio_mode=auto`，conftest 已剥代理变量）：`staged_artifacts` fixture（`conftest.py:61`）扩出 `sdk` 段 + 假 wheel；四个新端点的 200 / 404 / 匿名 / 开关关闭 = 404；简单索引 HTML 形状；技能包增量断言落**新文件** `test_platform_wiring_sdk.py`（F053 的 `test_skill_packs.py` 不改，其中两条回归断言反过来守住本 Feature 不改坏 auth 章与模型章，坑 31）；自检脚本无环境时可读失败；评测样本结构断言。
- **runtime-manager 测试**：`test_build.py` 断言两个新 buildarg 渲染进 Dockerfile 与传给 `build_image`。
- **CI**：新 `.github/workflows/sdk-quality.yml`（paths `src/bisheng-sdk/**` / `scripts/pack_sdk_wheel.sh`），三 leg 照 `cli-quality.yml`（locked / highest-resolution / wheel smoke + manifest drift guard on `sdk.version`）。
- **114 手验**（在阻塞项 ②③ 落地、`wt/storage-handle` 与 `wt/cli-dev` 合入并部署后）：`bash scripts/pack_sdk_wheel.sh` → 提交 → `bash /opt/bisheng-ops/deploy.sh` → `curl -s http://192.168.106.114:7860/api/v1/dev-toolkit/versions | jq .data.sdk` → `pip install --extra-index-url http://<114>:7860/api/v1/dev-toolkit/simple/ bisheng-sdk` → `bisheng deploy` platform-wiring 的 `example-sdk/` → 用非 admin `shuiwu` 与另一非 admin 账号访问，断言 `auth` 各得其身份、retrieve 集合等于 `/api/v2/filelib/retrieve` 同用户限定声明库的结果、应用 B 列不到应用 A 附件（storage 先看 `GET /v1/runtime/status` preflight `attachment_storage.ok`，systemd 形态要 `RTM_APP_FACING_BASE_URL` 指到 `bisheng-apps` 网桥网关，坑 27）。**验权限一律非 admin**（super_admin 短路 ReBAC）。
- **测试环境前提**：SDK 单测与后端单测**不需要**两个前置分支（一切经 mock / fixture）；只有 `test_contract_alignment.py` 的三条对账用例要读 `wt/storage-handle` 的 `runtime_manager/storage.py`、`api/storage.py` 与 app-proxy 的 `headers.py`——文件缺失时 `skip` 并打印「前置分支未合入」（坑 30）。技能包增量任务（T033–T036）**必须**在 `wt/cli-dev` 已合入的基线上做（T000 核对，坑 31）。
- **可观测**：SDK 不写日志（应用的日志是应用的）；异常 `__str__` 足以定位；runtime-manager 日志对 `BISHENG_APP_STORAGE_TOKEN` 值自动脱敏（`api/readonly.py` 的 `*TOKEN*` 名匹配，坑 18）。

---

## 8. 后续改进 / 不打算做的事

- **不做**：SDK 侧重试 / 断路器；`as_user`；本地白名单预演（除非 F055 提供预检可及性接口，spec 决议-3）；清空附件空间；下载直链；非 Python SDK（v3.1）。
- **不做（本 Feature 边界，理由已定案）**：不为「`dev` 的本地自签句柄」在 SDK 里开任何兼容分支（阻塞项 ③ 的修法在 F053 / F052，SDK 改动为零——它只是把上下文里的值当 Bearer 送出去）；不在 SDK 里兜底缺失的 `BISHENG_APP_STORAGE_DIR`（契约 ⑦；宁可 `StorageHandleMissingError` 也不静默落临时目录，spec §3）。
- **待上游落地后的 SDK 增量**：F052 分配「不可及」码 → 填 `_codes.py`；`knowledge_base_ids` 放宽 → 指南示例改为可省略；F054 附件 API 加 presign → `storage.share()`（另起 AC）；F054 若为 backend 调用方落 `16170–16174` → `_codes` 的 str 表旁加 int 表项（SDK 走 Bearer 路径不会遇到，仅为对账完整）。
- **可选增强**：`versions` 载荷下发 `packs[]` 替代 CLI `DEFAULT_PACKS`（第三个技能包出现时）；F055 托管预检校验应用锁定的 SDK 版本 ∈ 平台区间。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-09-16 | 初版（D1–D16、坑 1–25、§4.2 契约 ①–⑦、§6.2 阻塞项 ①②⑤ 与契约 ③④、回写三项）；全自动模式定案 | spec 定稿后补 design |
| 2026-09-16（同日续） | 补 §2 Constitution Check（C1–C8）；**D8 / §4.2 ②④ / D6 storage 行 / D9 路径规则 / §4.1 C 按 F054 `wt/storage-handle`（T084 / T085 已实现）改写**：句柄改 `BISHENG_APP_STORAGE_ENDPOINT/_TOKEN/_MAX_FILE_MB`、落 runtime-manager `/v1/apps/{app_id}/storage`、manager 信封 `{"detail":{code}}`、`/meta/` 路径、`200 {}` 删除、`apps/` 保留前缀；作废初稿的 backend 落点 / `_URL` / `16163+` 建议与 F054 回写项；§6.2 ⑤ 由阻塞项改为已实现契约；新增坑 26–30；修正引用 tasks 编号（T026 / T032 / T038 / T027 / T023 / T030–T032 / T014）| 续写前核对 storage-handle worktree（brief 要求） |
| 2026-09-16（同日三续） | **按 F053 分支 `wt/cli-dev` `b61b209e4` 改写**：D12 由「新建技能包」改为「在 F053 已建的 `platform-wiring` 上做增量」、D13 自检改为追加步骤、D4 `subject_kind` 随密钥种类、D5 增第三半（`bsdev.` 本地自签句柄不可被平台受理，修法归 F053 / F052）、D8 本地句柄标注「`dev` 今天未注入」；§6.2 阻塞项 ① 消解为已实现契约，新增阻塞项 ③ 与契约 ⑦；新增坑 31–36；回写登记第 2 条按「已交付 + 增补」重写；修正行号（`credential_validator.py:43`、`pack_cli_wheel.sh:97 / 106-119`、`api/router.py:141`、`artifact_service.py:211-231`、`distribution.py:80`）| `/sdd-review design` + brief 要求核对 cli-dev worktree |
