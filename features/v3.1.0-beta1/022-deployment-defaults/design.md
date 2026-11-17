# Design: 默认部署与可选 BS Client 地址

**关联**：[spec.md](./spec.md)
**版本**：v3.1.0-beta1
**最后更新**：2026-11-17
**状态**：2026-11-17 用户确认后已实现；本地验证完成，真实部署验收仍待执行，见 [verification.md](./verification.md)。

## 1. 目标与非目标

默认部署启用 Vibe App、沙箱和 BS Client，并让应用在受控材料下载阶段取得镜像外依赖。`platform_public_url` 是可选地址覆盖项，留空时 DSH 的登录、Chat、会话、Work 工具和技能功能仍可使用。

本次交付源码、部署配置、文档和验证记录。API 路径与 Desktop 协议标识、应用运行权限、业务资源授权、发行镜像和线上环境均沿用现有边界。

## 2. 关键约束

- 遵循 [constitution](../../../docs/constitution.md) C1–C8 与 [release contract](../release-contract.md)。不新增数据库对象、错误码或业务对象写入权。
- 默认开关不能替代运行时服务身份、PKCE、正常业务权限与实际宿主/集群运行条件；已有明确关闭、离线策略和密钥必须保留。
- DSH 配置仍为进程级配置；当前请求的对外地址只能存在于请求上下文，不能回写共享 Settings、Redis 或全局 MCP allowlist。
- 新部署只要求填写实际需要覆盖的配置。HTTPS 反向代理须正确保留公开 Host（含端口）及可信的协议信息；不要求为此另填 `platform_public_url`。
- Vibe 在线能力只开放受控依赖下载阶段，安装/编译与正式运行保持各自既有出网限制。

## 3. 方案对比与选定

### D1：地址留空时逐请求解析，显式配置仍具有最高优先级

- **选定**：统一地址解析入口，以 `platform_public_url` 为最高优先级；未配置时读取当前请求的有效协议和真实 Host，保留端口，沿用 `normalize_dsh_origin` 的 HTTP(S) 规范化与非法地址拒绝规则。空白字符串视同未配置。
- **备选**：继续强制填写地址，会违反 AC-04；只删除启动校验，会留下授权链接拼接 `None`、浏览器 Origin 与 `None` 比较失败、MCP 空允许列表拒绝所有请求的问题；使用首次请求地址作为全局配置，会使后续其他地址请求相互污染。
- **原因**：已核实当前唯一的地址依赖位于 `DshSettings` 校验、`DshAuthorizationService.create`、浏览器授权/撤销会话以及 `work_transport_security`。Chat 和令牌等入口共享运行时，不需另建地址配置。
- **重新考虑条件**：未来需要无请求上下文的后台任务生成对外链接，或者新增路径前缀部署合同；届时另行定义后台地址来源，不偷偷记住某次请求。

### D2：公开 Host 与可信代理协议分开处理

- **选定**：公开 authority 只读取实际 HTTP Host；不使用客户端随意传入的 `X-Forwarded-Host` 改写安全目标。协议优先使用已由 ASGI 服务器处理的值；若最后一跳仍为 HTTP，仅对部署声明的可信代理读取单值 `X-Forwarded-Proto`，且仅允许 `http` / `https`。
- **部署接线**：在 `bs_client.trusted_proxy_hosts`（可选字符串列表）中，Compose 声明可信代理服务 `frontend`、启用 Gateway 时包括 `gateway`；Helm 创建本 release 的 frontend/gateway headless peers Service 并生成其 DNS 名称（普通 ClusterIP 不等于连接 peer，不能用作这里的身份）。可信代理地址可由 IP/CIDR 或部署控制的 DNS 名声明；DNS 名在请求处理中异步解析并与连接 peer 对比，既不信任任意私网，也不在 Settings 导入时发起网络请求。原生源码默认只信任回环代理。部署使用 Uvicorn 自身可信代理处理时，优先消费其已验证的 ASGI scheme。新部署模板提供默认接线，该列表不构成 DSH 启用前置配置。
- **代理要求**：Nginx 保留 `$http_host`；Gateway 路由保留原始 Host，传递单一公开协议，不能把内部 `backend:7860` 或自己的容器端口当成公开地址。外层 TLS 终止代理需覆盖来自客户端的转发头。Nginx `geo $bs_trusted_edge` 默认只接受回环边缘代理，`map` 只放行其单一 HTTP(S) 协议；Compose 外部边缘代理在配置文件登记 CIDR，Helm 使用 `frontend.proxy.trustedForwardedCidrs`。默认 HTTP 不需要新增配置；自定义 TLS 代理按这套约定登记，仍无需填写 DSH 对外地址。
- **备选**：无条件相信全部转发头，会让不可信客户端影响安全目标；用浏览器 Origin 充当配置，会将待验证数据当成校验依据；信任所有私网 CIDR，会扩大公开 backend 端口的代理信任范围。
- **原因**：已核实项目现有下载包 URL helper 无条件读转发头，其注释明确只适用于本请求返回的下载文件。它不能直接用于 DSH 浏览器来源和 MCP 安全判定。现有 Nginx API 路由已经保留公开 Host，需维护该合同。
- **重新考虑条件**：支持会重写 Host 的新网关或受控多级代理时，应新增可验证的转发链合同和实机测试，不通过放宽任意 Host 解决。

### D3：共享身份与会话运行时，地址和 MCP 安全策略按请求隔离

- **选定**：`DshRuntime` 继续缓存身份、Redis 与会话依赖，不缓存推导地址。登录授权创建调用显式传入本请求有效地址；`DshAuthorizationService` 保留显式 origin 的已有构造调用兼容。浏览器授权及会话撤销共用严格同源校验 helper，继续检查 JSON 与 `Sec-Fetch-Site`。
- **MCP**：保持现有单个协议 Server 和 ContextVar 业务上下文，将 SDK stateless transport manager 的安全配置绑定到本次请求，再在请求生命周期内 `run/handle_request/close`。默认工厂提供 `RequestScopedWorkMcpRuntime` 门面，与 main 生命周期现有调用相容，统一支持固定地址与动态地址；显式传入 `security_settings` 的已有 Python 调用仍返回 SDK manager；不临时修改共享 manager 的 `security_settings`。显式配置时仍使用固定 Host/Origin 允许列表；未配置时使用本请求有效地址，正常无 Origin 的原生 MCP 调用仍经过既有认证。
- **备选**：共享 manager 上临时替换 allowlist，存在并发请求串用策略；关闭全部 MCP 传输保护，会取消应有的内容类型/来源校验；按 Host 永久缓存一套 manager，会让外部输入增长常驻资源。
- **原因**：本地已安装的 MCP SDK `_handle_stateless_request` 每次创建 transport，但取的是共享 `security_settings`；请求级 manager 能用其公开接口限定生命周期，无需补丁 SDK 私有实现。
- **重新考虑条件**：采用 stateful MCP 会话或性能测量表明每请求 manager 成本不可接受时，需重新评估会话归属和有界缓存。

### D4：单一规范配置块，旧名称在输入边界归一化

- **选定**：Settings 的规范字段为 `bs_client`；输入包含该键时整块优先，否则将旧 `dsh` 映射到它，移除旧输入键后再验证。`settings.dsh` 保留为返回同一对象的内部兼容属性，序列化与新模板使用 `bs_client`。YAML loader 必须在 unknown-key 过滤前完成名称归一化。`validate_lists` 不得将空 `bs_client: {}` 改成列表。
- **默认值**：客户端部署开关默认开启；显式 `enabled: false` 保留。地址留空不再触发 enabled 地址校验，其余容量、时区和显式 URL 验证保留。
- **Helm**：新增 `bs_client` 参数并保留旧 `dsh` 输入；为区分「缺省新值」和「用户显式新值」，新 values 的 `bs_client` 使用 null 表示未覆盖，实际默认 enabled 为 true。非 null 的新块整块优先，空对象也有效。`config.settings` 同样先做新旧归一化，最终只输出一个 `bs_client` 配置块，避免默认生成的新键掩盖旧配置中的显式关闭。Schema、示例与说明同步。
- **备选**：同时保存两个完整字段，容易出现优先级、序列化和读调用分裂；只加 Pydantic alias 而不改 YAML 过滤，旧名/新名之一仍可能被提前丢弃；合并新旧块违背已确认的整块优先语义。
- **原因**：当前 loader 只允许 `Settings.model_fields` 中的顶层键，而项目有多个既有 `.dsh` 内部消费者；边界归一化可减少无关调用链改动。
- **重新考虑条件**：所有维护中的部署配置均已迁移且另有明确兼容退役计划时，才考虑删除旧名称。

### D5：默认部署包含完整服务接线，下载源属于 runtime-manager

- **选定**：Compose 全新 `.env` 默认选择 `app-runtime`，安装器只为缺失的运行时身份生成独立随机密钥和合法 Fernet key，重复运行保留既有值；已有 `.env` 中的 profile 选择不自动重写。模板启用 `app_runtime` 并提供 manager 服务地址、控制密钥、入口授权密钥、OBO 密钥与 backend/worker 一致的接线。沙箱沿用已有两个 runner 和逐副本 endpoints。
- **第三方包**：全新默认采用在线模式、PyPI 与 npm 官方源；部署者显式私有源/离线值优先。通过 Compose 注入实际 npm 源，复用 Docker 的 `build_package_sources` 与 Kubernetes 的 `_package_sources`，无需改写现有策略解析器；默认来源包括：PyPI 除索引外包含 `files.pythonhosted.org`，npm 包来源需明确进入下载策略。下载策略不得从不可信应用清单任意扩大。
- **Helm**：已有 runtime/sandbox 默认开启，保留该行为，补齐客户端默认开启与新 key；离线/来源覆盖沿用当前公开参数。
- **备选**：只打开页面开关，不部署运行服务或接入密钥，会让入口可见但请求失败；在 backend YAML 中配置下载源，是修改一个 runtime-manager 不读取的字段。
- **原因**：已核实 Compose runtime 服务仍在 profile 后、模板 app_runtime 块被注释；Helm 已默认开启 runtime/sandbox 和在线下载。Docker 原在线 npm 默认为空时，不会自动进入 `build_package_sources`，现已在 `.env.example` 和 Compose 缺省值中补齐；私有源不回退公网由真实策略测试覆盖。
- **重新考虑条件**：发行方案迁移至统一部署向导或切换默认依赖源时，应修改唯一模板和对应回归，不修改既有用户配置。

## 4. 系统现状

### 4.1 已核实基线

最初调研基线为 `754cf11e0f`；当前工作区是独立分支 `codex/beta1-deployment-defaults-20261116`。实现开始前已快进至当天发版线 `0e975096fe`，只在此隔离分支修改本特性文件。

现有地址流为 `DshSettings.platform_public_url → 共享 DshRuntime/静态 MCP policy → 授权链接和来源校验`，enabled 时禁止地址缺省。

### 4.2 当前数据流

`YAML 新旧名称 → 单一 bs_client → 启用状态与可选地址覆盖 → 当前请求有效地址 → 授权链接 / 浏览器同源校验 / 本请求 MCP policy`。

与地址无关的发现、令牌换取和续期、Chat 模型访问、个人资料、Work 发布/工具/技能路径保留既有身份、权限、模型和配额流程；不新增地址前置校验。

| 字段/接口 | 目标契约 | 消费者 |
|---|---|---|
| `bs_client` | 规范顶层对象；旧 `dsh` 输入兼容，新块整块优先 | Settings、YAML loader、Compose、Helm |
| `platform_public_url` | 可选 HTTP(S) origin；null、空字符串或空白字符串表示按请求解析 | 登录链接、浏览器与 Work MCP |
| 可信代理声明 | 部署拥有的 IP/CIDR 或服务 DNS 名；缺省回环；不授予业务权限 | 地址解析 helper |
| `authorize_url` | 仍为绝对 URL，使用显式配置或本请求对外地址 | Desktop 原生登录 |
| HTTP 路径和协议字段 | 继续保留 `/dsh/...`、`dsh-desktop`、现有 contract_version | 已发行 Desktop 与 Web |

| 模块 | 职责 | 边界 |
|---|---|---|
| `core/config/settings.py`、`dsh.py` | 单一 typed 配置、兼容归一化、默认与合法性验证 | 不读取请求，不访问代理 DNS |
| `common/services/config_service.py` | YAML 输入归一化与既有未知键过滤 | 不改数据库中的业务配置 |
| `dsh/request_origin.py` | 逐请求解析、可信代理协议、严格同源校验 | 不缓存请求地址到共享状态 |
| `local_auth.py`、`identity.py`、`self_service.py` | 传入本请求地址并使用统一校验 | 不重写身份、PKCE 或会话服务 |
| `work_mcp.py` | 保留协议 Server 与业务 ContextVar，建立请求级 transport 生命周期 | 不放宽工具权限，不突变共享 policy |
| Compose / installer / Helm | 默认服务、来源、密钥、可信代理与新旧 key 接线 | 不替代实际宿主/集群准入 |

## 5. 已知坑与处理位置

| 事实 | 忽略后的结果 | 处理位置 |
|---|---|---|
| 只取消 enabled 地址校验仍有三个消费点依赖固定地址 | 启动成功但登录/撤销/MCP 失败 | 统一地址 helper 与 D3 调用点 |
| DSH 运行时跨请求共享，SDK stateless manager 的 policy 也是共享字段 | 并发不同 Host 请求串用 allowlist | `work_mcp.py` 请求级 transport |
| Settings 前置空值归一化会把未知空对象变为列表 | `bs_client: {}` 无法正常加载 | `Settings.validate_lists` |
| YAML unknown-key 过滤早于 Pydantic 验证 | alias 已声明但配置仍被忽略 | `ConfigService.load_settings_from_yaml` |
| Helm 默认 canonical 对象会掩盖旧名显式 false | 升级意外打开功能 | nullable values + D4 优先规则 |
| PyPI 索引和 wheel 下载不是同一域名 | 能查包但下载被 egress 拒绝 | `build_package_sources`，保留既有 files 主机测试 |
| 运行时 profile 和开关不同步、密钥未接入 | 页面可见但发布/应用访问失败 | installer、Compose、活动 YAML 块 |

## 6. 对外契约与依赖

### 6.1 提供的契约

- 规范 `bs_client` 配置与旧 `dsh` 输入兼容，内部 `settings.dsh` 读调用保持可用；外部 API 与协议标识不改名。
- Desktop 授权仍返回绝对 `authorize_url`；PKCE、令牌请求/响应与错误格式保持原合同。
- 浏览器授权和撤销要求精确 Origin、JSON 与现有 fetch-site 约束；MCP 仍需通过原身份认证与工具权限，不把「地址可选」解释成「访问免认证」。
- 默认部署提供在线材料下载，但不替换应用冻结依赖、静默回退公网或改变正式运行网络权限。

### 6.2 依赖及风险

| 依赖 | 风险 |
|---|---|
| Nginx / 可选 Gateway 保留公开 Host 和可信协议 | 丢失端口、改写 Host、追加多个协议会使自动地址错误；必须测试代理路径 |
| 部署控制的 Service DNS / 网络 | DNS 与 peer 不匹配时不信任其转发头；不得放宽成任意来源 |
| MCP SDK stateless manager 公开生命周期 API | 升级 SDK 时复查 Server 跨请求复用与 ContextVar 传播，测试并发隔离 |
| Docker Host isolation / Kubernetes CNI、存储与运行身份 | 真实前提未满足时运行操作仍明确失败；默认开关不伪造已验收状态 |
| PyPI/npm 或企业镜像及其证书、网络 | 依赖不可取得须报告实际失败；CI 静态策略检查不能证明公网下载成功 |
| 发行镜像 | 当前 Compose 示例仍指向既有发行 tag；源码行为需用包含本变更的新镜像交付，不能宣称旧镜像已有支持 |

## 7. 验证与可观测

- 已执行基线：`bash scripts/tests/compose/test-install.sh`，18 项通过；DSH `test_public_origin.py` + `test_config_contracts.py`，32 项通过。它们尚未验证本设计的目标行为。
- 当前实现的配置单测覆盖新旧名称、整块优先、空块/空地址、显式关闭与非法 URL；API 集成覆盖不配置地址的授权创建/批准、真实 SQLite/PKCE/密码学换票与续期、会话撤销；Chat 协议回归继续执行；MCP 用真实 SDK 请求验证 initialize、tools/list/call 与 skills/resource，包含并发不同地址和错误 Origin。
- 代理验证：本地有 Nginx 时运行 `test_public_origin_nginx.py`，扩展覆盖未配置地址的 HTTP、TLS 双层代理、端口、IPv6 与伪造转发头。无 Nginx 或真实 Gateway 则明确记录未验证项，不以 mock 替代实机结论。
- 部署验证：安装器回归检查首次开启与独立密钥、重复运行保留、已有明确关闭、profile 组合；Compose render、Helm render/schema 与默认/旧 key 覆盖验证最终配置。下载策略单测覆盖 Python 文件域名、npm 与私有源/离线不回退。
- 真实环境按 QA 用例验证：访问平台 → Desktop 登录 → Chat → Work 工具与技能 → 续期/退出 → 撤销指定会话；同时确认非管理员权限边界。Vibe 分别部署依赖镜像外 Python/npm 包的小应用，观察下载、禁网安装与应用返回，测试离线缺包失败。
- 地址校验日志只记录字段/原因，不输出令牌或密钥。保留下载失败与业务错误的原始错误路径，结果记录区分静态、API、代理与真实环境。

## 8. 后续改进与范围限制

本阶段不自动安装宿主防火墙、不改变既有 runtime 证明机制，不构建发布镜像，不重写客户已有 `.env`/YAML。当前尚未使用 Docker Engine 启动服务，缺少 Nginx/Gateway/集群与独立测试数据库，交付本地代码验证与明确的待执行项；不以默认开关替代完整安装验收。后续更复杂代理、路径前缀与 stateful MCP 按 D1–D3 的触发条件重新设计。

## 修订历史

| 日期 | 改动 | 原因 |
|---|---|---|
| 2026-11-16 | 设计草稿；记录现有依赖、可选地址与请求隔离方案 | 用户明确未配置地址时 DSH 相关功能也须正常使用 |
| 2026-11-17 | 同步实现现状、headless代理身份与边缘协议清理、验证边界 | 用户确认后完成实现和本地回归 |

Compose真实配置解析及运行时接线检查已通过（清空profile为13服务，启用为17服务），没有启动容器。

当前验证汇总：后端 182 passed / 2 skipped / 5 deselected；安装器 18 项；Helm与发行门禁47项；运行时出口/构建100 passed / 8 skipped。基线已有失败与环境限制详见 verification.md。
