# mcp-runtime-infra

## summary
MCP 方向上仓内只有完备的 MCP client 基建（mcp_manage/ + 工具体系 ToolPresetType.MCP），平台自身对外的 MCP server 面完全不存在，但官方 `mcp>=1.27.0` SDK 已在依赖内、server 端原语可直接用，且六类工具背后的 domain service 全部已有，MCP 工具面本质是"薄封装+鉴权"。应用托管运行时则是彻底的绿地：仓内无 docker SDK、无进程管理器、无资源限制配置，最近的参照物只有 linsight 独立 worker（固定常驻，非 per-app）与容器级 restart:on-failure；/apps/{slug} 动态路由在现有纯静态 nginx 配置上也无挂点。单机资源限制最兼容的路线是 docker SDK+docker.sock（compose 单机拓扑天然契合），代码快照存储可复用 MinioStorage+FlowVersion DAO 双模式。

## current_state
【MCP 现状（均已在代码核实）】平台今天的 MCP 全部是"客户端消费外部 MCP server"：`src/backend/bisheng/mcp_manage/manager.py` 的 `ClientManager` 按配置 JSON（mcpServers 键）分派三种传输——`clients/sse.py`/`clients/stdio.py`/`clients/streamable.py`，共同基类 `clients/base.py:BaseMcpClient` 直接用官方 `mcp` SDK 的 `ClientSession`（list_tools/call_tool，每次调用新建会话、无连接池）；`async_runner.py` 维护一条专用事件循环线程（bisheng-mcp-async）供同步上下文调 MCP。MCP 作为一种工具类型接入工具体系：`tool/domain/const.py` `ToolPresetType.MCP=2`，`tool/domain/services/tool.py` 的 `parse_mcp_schema`/`refresh_all_mcp`/`refresh_mcp_tools` 负责用户注册与刷新外部 MCP server（stdio 可被 `core/config/settings.py:572 McpConf.enable_stdio` 配置禁用），`tool/domain/services/executor.py:_init_mcp_tool` 经 `mcp_manage/langchain/tool.py:McpTool` 包装成 LangChain BaseTool，供助手/工作流/灵思消费（`linsight/domain/services/agent_factory.py:42` 注释确认灵思 tools 含用户配置的 MCP 工具）。角色授权侧已有 `database/models/role_access.py:56 AccessType.MCP="mcp"` 资源类型。前端 platform 有完整的 MCP 工具配置 UI（`pages/BuildPage/tools/EditMcp.tsx` + `controllers/API/tools.ts` 的 getMcpServeByConfig/testMcpApi）；client 端 `types/chat/mcp.ts` 是 LibreChat 遗留的 zod schema，非平台自建。全仓 grep 无任何 `mcp.server`/FastMCP 引用——平台对外暴露的 MCP server 为零；同时 `database/models/` 下无任何 ApiKey/ServiceAccount 表，v2 开放接口（`open_endpoints/api/endpoints/{knowledge,chat,workflow,...}.py`）经 `open_endpoints/domain/utils.py:get_default_operator_async` 解析操作者、无鉴权（与开放 API PRD 的"零鉴权现状"一致）。【执行基建】代码执行有两套且都不 per-app：① 灵思 code interpreter `src/backend/bisheng_langchain/gpts/tools/code_interpreter/`——`local_executor.py:LocalExecutor`（在 worker 容器内直接 subprocess 执行、tempfile 工作目录、DEFAULT_TIMEOUT=600s、零隔离零资源限制）与 `e2b_executor.py:E2bCodeExecutor`（E2B 云沙箱，worker 中介 copy-in/out，SIZE_AUTOPUSH=5MB），由 `tool/domain/services/executor.py:157` 注入 minio 配置、`linsight/domain/task_exec.py:492` 会话尾清理；② 工作流 CodeNode `workflow/nodes/code/{code.py,code_parse.py}`——进程内 AST 解析后 compile+`exec()`，连子进程都没有。后端零 docker SDK 使用、compose 无 docker.sock 挂载。【容器拓扑】`docker/docker-compose.yml` 单机 compose：backend（api，uvicorn --workers 2）与 backend_worker 共用同一镜像，`docker/bisheng/entrypoint.sh` worker 模式 = min_worker(celery 四队列合一) + linsight worker + beat 同容器合跑；另有 frontend(nginx)、mysql、redis、openfga(+migrate)、es、milvus(etcd+minio)。全 compose 无任何 cpus/mem_limit；崩溃恢复仅靠容器级 `restart: on-failure`。【路由】`docker/nginx/conf.d/default.conf`（frontend 容器挂载，`src/frontend/nginx.conf` 镜像内置同构）：3001 端口，`/`→platform 静态、`/workspace/`→client 静态 alias、正则 `^(/workspace)?/api(/|$)`→backend:7860（含 websocket upgrade map、proxy_read_timeout 300s）、`/bisheng|/tmp-dir`→minio:9000。纯静态配置文件，无动态 upstream/lua/consul，`/apps` 无任何现有路由。商业版前面还有 Java gateway（docs/architecture/11-gateway.md，本仓外）。【MinIO】`core/storage/minio/minio_manager.py` MinioManager/get_minio_storage（app_context 生命周期）+ `minio_storage.py:MinioStorage`（bucket 管理、put_object/put_object_tmp/copy_object/get_share_link、_metered 指标、S3Error 解冻）。租户前缀函数 `core/storage/tenant_storage.py:get_minio_prefix` 存在但是死代码（F008 未落地，调用点未接线——记忆核实过的现状）。版本化先例：工作流版本走 MySQL 表 `database/models/flow_version.py:FlowVersion`（图 JSON 全量入库）；灵思工作区走 MinIO per-chat 前缀 + copy-forward（`linsight/domain/services/workbench_impl.py` 以 chat_id 限定 workspace 前缀，put_object 到 minio_client.bucket）。【部署开关先例】`common/services/config_service.py:224` BISHENG_PRO 环境变量、`settings.multi_tenant.enabled`、McpConf 等 settings 开关；路由目前在 `bisheng/api/router.py` 无条件注册，没有"整层不装"的条件注册模式。

## key_files
- src/backend/bisheng/mcp_manage/manager.py — ClientManager：MCP client 三传输(SSE/STDIO/Streamable)分派，纯客户端
- src/backend/bisheng/mcp_manage/clients/base.py — BaseMcpClient：官方 mcp SDK ClientSession 封装，list_tools/call_tool 每次新建会话
- src/backend/bisheng/tool/domain/services/tool.py — parse_mcp_schema/refresh_all_mcp：用户注册外部 MCP server 为工具（ToolPresetType.MCP）
- src/backend/bisheng/tool/domain/services/executor.py — ToolExecutor：_init_mcp_tool 包装 McpTool；:157 code_interpreter 注入 minio 配置
- src/backend/bisheng_langchain/gpts/tools/code_interpreter/local_executor.py — LocalExecutor：worker 容器内 subprocess 直执行，零隔离零限额——现有最接近'执行体'的组件
- src/backend/bisheng_langchain/gpts/tools/code_interpreter/e2b_executor.py — E2bCodeExecutor：外部云沙箱路线先例（copy-in/out 中介模式）
- src/backend/bisheng/workflow/nodes/code/code_parse.py — 工作流 CodeNode：进程内 exec()，无隔离
- docker/docker-compose.yml — 单机拓扑全貌：无资源限制、restart:on-failure 是唯一自愈机制、无 docker.sock 挂载
- docker/bisheng/entrypoint.sh — worker 容器合跑 celery+linsight+beat；api 模式先跑 alembic
- docker/nginx/conf.d/default.conf — 生产 nginx 路由：/、/workspace/、(/workspace)?/api→7860、minio；/apps/{slug} 的天然挂点，但纯静态配置
- src/backend/bisheng/core/storage/minio/minio_storage.py — MinioStorage：put/copy/share_link 全套，app 代码快照的存储层直接可用
- src/backend/bisheng/database/models/flow_version.py — FlowVersion：版本快照领域模型的现成 DAO 范式
- src/backend/bisheng/open_endpoints/api/dependencies.py — v2 开放接口现状：无鉴权、get_default_operator_async——PRD 明令不得复用其旧检索路径
- src/backend/bisheng/core/config/settings.py — McpConf(enable_stdio)/multi_tenant.enabled/bisheng_pro：部署级开关先例，GOV-07 分层开关可循此模式
- src/backend/bisheng/database/models/role_access.py — AccessType.MCP：角色-资源授权模式，GOV-07 两个角色权限配置项的既有面
- src/frontend/platform/src/pages/BuildPage/tools/EditMcp.tsx — platform 端 MCP server 配置+测试 UI（消费方向）

## reuse
- MCP 协议栈零新依赖：pyproject.toml:50 已锁 `mcp>=1.27.0`，官方 SDK 自带 server 端原语（FastMCP/streamable-http ASGI app，可直接 mount 进 FastAPI）——此点为 SDK 事实推断，仓内未用过 server 侧，需 POC 验证版本行为
- DEV-02 六类工具的后端能力全部有现成 domain service 可薄封装：知识库检索走 F029 双层过滤路径（knowledge 模块 view_file 双层过滤，PRD:147 明确要求与平台工作台同源，恰好只能复用这条）、知识库清单（knowledge domain + ReBAC 可见范围）、模型清单（llm 模块）、身份/组织查询（user/tenant 模块）；MCP 工具面本体≈鉴权层+工具注册层
- API key 鉴权的载体设计已由伴生 PRD 定稿（个人 key + 服务账号密钥 bs-sak-，v2 迁移改 SAK）——实现是新建，但方案无需再设计
- 应用代码快照存储：MinioStorage（core/storage/minio/minio_storage.py 的 put_object/copy_object/get_share_link）+ FlowVersion（database/models/flow_version.py）的表模式双拼即可承载 WB-15/RT-05 双保险；目录树型代码包可仿灵思 workspace 的 per-前缀+manifest 模式（linsight/domain/services/workbench_impl.py）
- RT-01 登录复用：/apps/* 同域部署下 JWT cookie 直接可用（common/dependencies/user_deps.py UserPayload.get_login_user），登录回跳复用平台既有登录页与 SSO 配置；四类兜底页的降级页机制可借鉴 client 的 bs:service-maintenance overlay 模式（request.ts 拦截器）
- GOV-07 部署开关：BISHENG_PRO env（common/services/config_service.py:224）与 settings.multi_tenant.enabled 是既有的部署级开关范式；『未部署开放能力层则入口不出现』可经 /api/v1/env 下发前端（api/v1/endpoints.py:90 已下发 pro 标志的先例）
- GOV-07 角色权限两配置项：role_access.py AccessType + 既有菜单权限体系（v2.6 已拆 workbench/admin scope）——纯配置项新增，零新机制
- nginx 挂点：docker/nginx/conf.d/default.conf 是 /apps/{slug} location 的天然落点；WebSocket upgrade map 与 minio 转发的写法可直接沿用

## gaps
- MCP server 面整体（DEV-02）：FastMCP/lowlevel server 装配、API key 鉴权中间件、per-key scope 过滤、按 key 计量账单——全仓无一行；且其前置的 API key 体系本身也是 0→1（database/models 无 ApiKey 表，需建表+hash 校验+管理页）
- 模型双协议直连面（OpenAI/Anthropic 兼容 endpoint + 流式 + key 计量）：现有 llm 模块只做平台内调用，无对外协议兼容层
- 应用托管运行时=完整绿地：per-app 实例编排器（拉起/停止/1-4 核限额/崩溃检测/<=5min 自动重启/发布切换与回滚）、实例注册表、健康探测、端口分配——仓内无 docker SDK、无 supervisor、无 cgroup 操作、无任何按需进程管理代码；最近参照 linsight worker 也只是固定常驻进程
- /apps/{slug} 动态路由层：现 nginx 纯静态 conf 无法按 slug 动态转发到 per-app 实例；需三选一新建——backend FastAPI 反代（含 WebSocket 透传）、openresty/模板 render+reload、或专职 ingress 组件；商业版还需 Java gateway 侧同步适配（本仓外）
- 四类兜底页（无权限/未部署工场/已停用/不存在）+ 发布中/恢复中 holding page 及其状态机驱动切换：全新（含路由层在实例不可达时返回 holding page 而非 502 的机制）
- 应用领域模型：app 表、发布版本快照表、行级归属、状态机（草稿/待上线/运行/停运/已删除）、GOV-03 实例配额——全新表（须注册 _TENANT_AWARE_MODEL_MODULES）
- MCP 工具面第 5 项『应用数据表结构与数据查询』：平台无 per-app 数据库/schema 概念，从存储选型到工具全新
- MCP 工具面第 6 项『应用状态/日志自查』：无 per-app 日志采集通道（现日志=loguru 落容器 stdout），需新建日志捕获/留存/按 owner 过滤查询
- GOV-07『整层不装』的条件注册模式：bisheng/api/router.py 现无条件注册所有路由，需引入按部署配置裁剪路由+前端入口的机制

## risks
- 权限红线（C4/NFR-1.4）：MCP 检索若图省事复用 open_endpoints 旧检索（仅知识库级一次校验、无文件级过滤，伴生 PRD 附录 B 已核实）即成活越权；必须走 F029 双层过滤且 fail-closed，验收样本须含同库部分文件无权场景（PRD:161-162）
- 单机容量硬约束：compose 全栈已合跑在一两台机上（entrypoint.sh worker 容器合跑 celery+linsight+beat；114 曾因重启 linsight worker OOM 死机），再叠 per-app 1-4 核实例，无 GOV-03 配额强约束会把平台核心挤死——与 RT-08『应用可以不稳定，平台必须正常』直接冲突
- 资源限制技术路线未定且各有硬伤：docker SDK+docker.sock 路线与现单机 compose 拓扑最兼容（--cpus/--memory 即 cgroup，restart policy 现成），但把 docker.sock 交给平台组件≈host root 权限，且信创/DM8 客户环境（105/116 类）docker 权限不确定；裸进程+cgroup v2 路线无容器依赖但镜像内无 systemd、跨发行版 cgroup 挂载差异大；两条路线都未在仓内有任何先例
- C3 多租户：per-app 实例是长驻独立进程，平台的 ContextVar 租户注入完全不适用；app 回调平台必须全部走带 SAK 的开放 API/MCP 面显式传身份（与伴生 PRD 对齐），任何让 app 进程直连 MySQL 的捷径都会绕过租户过滤
- 5 分钟自动恢复承诺（RT-08/NFR-6）超出 restart:on-failure 能力：容器重启只覆盖进程退出不覆盖 hang，需主动健康探测+超时判定+holding page 切换的可靠性工程，属可测量的产品承诺，测试成本高
- MCP streamable-http 长连接经 nginx（proxy_read_timeout 300s、buffering）与商业版 Java gateway 双层代理的兼容性需实测；勿把 McpConf.enable_stdio（client 侧禁 stdio）与 server 面混淆
- C1 分层：MCP server 面必须作为新 api 层模块复用 domain services + PermissionService，禁止在 MCP 工具 handler 内直查 DB（arch-guard 8 RULE 会拦，但 MCP handler 是新形态入口，规则覆盖需确认）
- MinIO 租户前缀函数是死代码（F008 未落地）：若 app 快照要求租户隔离前缀，不能假设 get_minio_prefix 已在写路径生效，需显式接线，否则对外宣称隔离会翻车

## open_questions
- 工场运行时层隔离技术选型：docker（平台组件挂 docker.sock）vs 裸进程+cgroup v2 vs 预留 k8s？关键输入=目标客户（含信创环境）是否保证有 docker 且允许平台持有 socket 权限
- /apps/{slug} 路由承接者：nginx/openresty 增强、backend FastAPI 反代、还是独立 ingress 组件？商业版 Java gateway（本仓外）由谁改、何时改？——直接决定 RT-01 登录回跳与 holding page 的实现位置
- MCP server 部署形态：与 backend 同进程 mount（GOV-07『无新增常驻负担』倾向此）还是独立进程/端口（『整层可不装』更干净）？传输选 streamable-http 单一还是兼容 SSE？
- 『1-4 核』是 cgroup hard quota 还是调度参考？单机超卖策略与 GOV-03 配额的换算关系？
- 应用运行时契约：托管的 app 是任意 HTTP web 进程还是固定框架模板？决定健康探测协议、端口约定、发布切换是蓝绿双实例还是单实例停换（后者『发布中』窗口更长）
- 应用自有数据（MCP 工具第 5 项）落库形态：主 MySQL per-app schema、sqlite per-app、还是应用自带？涉及备份承诺（RT-07『存档随平台数据一同备份』）
- 模型双协议直连面是否复用现 llm 模块出口做协议转换，还是引入现成网关（如 litellm 类）？自研 Anthropic 兼容层的维护成本需拍板
