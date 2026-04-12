# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

BiSheng (毕昇) v2.5.0-dev — 面向企业的开源 LLM 应用 DevOps 平台。支持工作流编排、知识库管理、多 Agent 协作（Linsight 灵思）、模型评测与微调、MCP 集成。

**架构定位**：前后端分离 + 异步任务处理的分层架构。7 个运行时进程组 + 6 个基础设施服务，后端遵循 DDD（领域驱动设计）模式。

**v2.5 核心改造**：权限体系从 RBAC 迁移到 ReBAC（OpenFGA）+ 多租户支持（逻辑隔离）。改造上下文见「v2.5 改造上下文」章节。

## 部署架构

采用混合部署：主要服务本地源码运行，存储服务 Docker 容器化。

```
本地服务 (源码部署)                    Docker 存储层
├── FastAPI 后端 (uvicorn) :7860      ├── Milvus 2.5 向量库  :19530
├── MySQL 8.0            :3306        ├── Elasticsearch 8.12 :9200
├── Redis 7.0            :6379        ├── MinIO 对象存储     :9000
├── Celery Workers                    ├── OpenFGA 权限引擎   :8080
├── Linsight Worker (可选)            └── OnlyOffice         :8701
├── Platform 前端 Vite   :3001
└── Client 前端 Vite     :4001
```

**Nginx 反向代理**: 8860 → 3001（Platform 前端），前端 vite 代理 API 到 7860（后端）

**关键原则**: 本地与 Docker 绝不运行同类服务，避免端口冲突。

## 开发命令

### 环境准备
```bash
# Python 3.10.14 (必须)
conda create --name BiShengVENV python==3.10.14
conda activate BiShengVENV

# 后端依赖 (使用 uv，lockfile 为 uv.lock)
cd src/backend
uv sync --frozen --python /path/to/python
```

### 启动服务
```bash
# 1. Docker 存储服务 (远程服务器)
cd docker && docker compose -p bisheng up -d
# 停止与本地冲突的容器
docker stop bisheng-mysql bisheng-redis bisheng-backend bisheng-backend-worker bisheng-frontend

# 2. 后端 API (端口 7860)
cd src/backend
.venv/bin/uvicorn bisheng.main:app --host 0.0.0.0 --port 7860 --workers 1 --no-access-log

# 3. Celery Workers (各开一个终端)
.venv/bin/celery -A bisheng.worker.main worker -l info -c 20 -P threads -Q knowledge_celery -n knowledge@%h
.venv/bin/celery -A bisheng.worker.main worker -l info -c 100 -P threads -Q workflow_celery -n workflow@%h
.venv/bin/celery -A bisheng.worker.main beat -l info

# 4. Linsight Worker (可选，灵思 Agent 框架)
.venv/bin/python bisheng/linsight/worker.py --worker_num 4 --max_concurrency 5
```

### 前端开发
```bash
# Platform 前端 (管理端，端口 3001)
cd src/frontend/platform
npm install
npm start -- --host 0.0.0.0   # 代理 /api/ 到 localhost:7860

# Client 前端 (用户端，端口 4001，基础路径 /workspace)
cd src/frontend/client
npm install
npm run dev
```

### 测试与代码风格
```bash
cd src/backend
.venv/bin/pytest test/                           # 全部测试
.venv/bin/pytest test/test_xxx.py::test_fn       # 单个用例
.venv/bin/pytest test/ -k "keyword"              # 按关键字
.venv/bin/black .                                # 格式化
.venv/bin/ruff check . --fix                     # lint 检查
```

## 代码导航

> 回答"代码在哪"。详细架构文档见 `docs/architecture/`。

### 仓库结构

```
bisheng/
├── src/backend/bisheng/            # FastAPI 后端主应用
├── src/backend/bisheng_langchain/  # LangChain 扩展包 (独立 Python 包)
├── src/frontend/platform/          # Platform 管理端前端 (React)
├── src/frontend/client/            # Client 用户端前端 (React)
├── docker/                         # Docker Compose 部署
└── docs/                           # 架构文档 + PRD
```

### 后端入口与启动

- **`main.py`** — FastAPI 应用创建，lifespan 管理（初始化基础设施 → 初始化默认数据 → yield → 逆序清理）
- **`api/router.py`** — 全局路由注册（v1: 29 个路由，v2: 6 个 RPC 路由）
- **`config.yaml`** — 主配置文件（本地开发用）

中间件栈（请求入站顺序）：`CORSMiddleware` → `CustomMiddleware`（请求日志 + X-Trace-ID） → `WebSocketLoggingMiddleware`

基础设施初始化顺序（`ApplicationContextManager`，`core/context/manager.py`）：
```
DatabaseManager → RedisManager → MinioManager → EsConnManager(业务) → EsConnManager(统计) → HttpClientManager → PromptManager → FGAClient(OpenFGA)
```

### 后端模块地图

**DDD 领域模块**（有自己的顶级目录 + `api/` + `domain/` 结构）：

| 模块 | 路径 | 职责 |
|------|------|------|
| knowledge | `knowledge/` | 知识库管理、RAG 文档处理管道 |
| workflow | `workflow/` | 工作流 DAG 执行引擎（LangGraph） |
| permission | `permission/` | ReBAC 权限引擎（OpenFGA 集成、权限检查、授权管理、数据迁移） |
| linsight | `linsight/` | Linsight Agent 自主任务框架，独立 Worker |
| llm | `llm/` | LLM 供应商管理、模型注册与配置 |
| chat_session | `chat_session/` | 聊天会话管理、消息持久化 |
| tool | `tool/` | 工具/插件管理 |
| channel | `channel/` | 多渠道通信、情报中心 |
| message | `message/` | 消息收件箱 |
| user | `user/` | 用户管理、认证（JWT）、RBAC 菜单权限 |
| finetune | `finetune/` | 模型微调流水线 |
| share_link | `share_link/` | 公开分享链接 |
| telemetry_search | `telemetry_search/` | 遥测数据检索 |
| workstation | `workstation/` | 工作台后端 |
| open_endpoints | `open_endpoints/` | v2 RPC 接口，面向外部系统集成 |
| mcp_manage | `mcp_manage/` | MCP 协议集成（SSE/STDIO/Streamable） |

**非独立模块**（路由在 `api/v1/` 中，无独立顶级目录）：assistant, evaluation, audit, group, tag, mark, flows, skillcenter, variable, report, invite_code

**基础设施模块**：

| 目录 | 职责 |
|------|------|
| `core/context/` | 应用生命周期上下文管理（BaseContextManager → ApplicationContextManager） |
| `core/config/settings.py` | Pydantic Settings 配置模型 |
| `core/database/` | SQLAlchemy 引擎工厂（同步 pymysql + 异步 aiomysql） |
| `core/cache/` | Redis 缓存（RedisManager） |
| `core/ai/` | AI 模型服务封装（llm/, embeddings/, asr/, tts/, rerank/） |
| `core/storage/minio/` | MinIO S3 对象存储 |
| `core/search/elasticsearch/` | Elasticsearch 集成（业务实例 + 统计实例） |
| `core/vectorstore/` | Milvus 向量库集成 |
| `core/openfga/` | OpenFGA SDK 封装（FGAClient 单例） |
| `core/prompts/` | 提示词模板管理 |
| `core/external/` | HTTP 客户端、情报中心客户端 |
| `common/errcode/` | 错误码定义（5 位编码 MMMEE） |
| `common/schemas/api.py` | 统一响应模型 UnifiedResponseModel |
| `common/dependencies/` | FastAPI 依赖注入（UserPayload） |
| `database/models/` | SQLModel ORM 模型，每个文件含 Schema + DAO |
| `worker/` | Celery 异步任务 |

### API 路由

**v1** (`/api/v1`，29 个，面向前端)：chat, knowledge, knowledge_space, qa, workflow, assistant, llm, user, group, tool, evaluation, finetune, server, linsight, session, channel, message, share_link, telemetry_search, flows, workstation, skillcenter, endpoints, variable, report, audit, tag, mark, invite_code

**v2 RPC** (`/api/v2`，6 个，面向外部集成)：knowledge_rpc, filelib_rpc, chat_rpc, assistant_rpc, workflow_rpc, llm_rpc。实现在 `open_endpoints/api/`。

### 数据模型与存储

核心 ORM 模型（`database/models/`）：

| 模型 | 说明 |
|------|------|
| Flow | 应用统一定义（FlowType: ASSISTANT=5, WORKFLOW=10, WORKSTATION=15, LINSIGHT=20, CHANNEL_ARTICLE=25, KNOWLEDGE_SPACE=30）|
| FlowVersion | 版本控制，`is_current` 标记当前版本 |
| Assistant / AssistantLink | 助手配置 + 关联表（工具/技能/知识库） |
| ChatMessage | 聊天消息（LONGTEXT），含 liked/solved/sensitive_status |
| MessageSession | 会话记录，关联应用与用户 |
| Role / RoleAccess | 角色定义 + 权限映射（AdminRole=1, DefaultRole=2） |
| Tenant / UserTenant | 租户主表 + 用户-租户多对多关联 |
| Department / UserDepartment | 部门树（物化路径）+ 用户-部门关联 |

**6 种存储引擎**：MySQL（关系数据）、Redis（缓存/Broker/状态）、Milvus（稠密向量）、Elasticsearch（稀疏索引/遥测统计，双实例）、MinIO（文件对象）、OpenFGA（关系型权限）

### 前端架构

| 维度 | Platform (管理端) | Client (用户端) |
|------|-------------------|-----------------|
| 路径 | `src/frontend/platform/` | `src/frontend/client/` |
| 端口 | 3001 | 4001 |
| 基础路径 | `/` | `/workspace` |
| 定位 | 管理员/构建者 | 终端用户对话 |

**技术栈**：React 18 + TypeScript + Vite + Radix UI + Tailwind CSS + i18next（中/英/日）+ Axios

**Platform 状态管理**：Zustand stores（`src/store/`）+ React Context（`src/contexts/`，11 个 Provider）

**Platform API 层**：`src/controllers/request.ts`（Axios 封装，JWT 注入，统一拦截），API 模块在 `src/controllers/API/`

**Vite 代理**：Platform `/api/` → `:7860`，`/bisheng` `/tmp-dir` → MinIO `:9000`；Client 路径去除 `/workspace` 前缀后转发

### 数据流

同步：浏览器 → Nginx :8860 → Vite → FastAPI :7860 → Service → DAO → MySQL/Redis。异步：FastAPI → Celery → Milvus/ES/MinIO。WebSocket 通过 ChatManager 回调流式输出。

## 开发约定

> 回答"写代码遵循什么规则"。

### 分层架构

标准 DDD 模块目录结构：
```
module_name/
  api/
    router.py                    # FastAPI Router 注册
    endpoints/                   # 按功能拆分的端点文件
  domain/
    services/                    # 领域服务（核心业务逻辑）
    models/                      # 领域模型（ORM 实体 + DAO）
    schemas/                     # Pydantic DTO
    repositories/                # 仓储层（可选）
```

**调用链路**：`Router → Endpoint → Service → Repository(可选) → DAO (database/models/) → MySQL`

**DAO 命名约定**：同步 `get_xxx()` / `create_xxx()` / `update_xxx()`，异步 `aget_xxx()` / `acreate_xxx()`。通过 `get_sync_db_session()` / `get_async_db_session()` 获取会话，均为 `@classmethod`。

**新增业务模块**：① 在 `src/backend/bisheng/` 下创建模块目录（含 `api/` 和 `domain/`）→ ② 在模块 `api/router.py` 创建 APIRouter → ③ 在 `src/backend/bisheng/api/router.py` 注册路由

### API 规范

**认证注入**：`UserPayload = Depends(UserPayload.get_login_user)`，WebSocket 用 `UserPayload.get_login_user_from_ws`

**统一响应**：
```python
UnifiedResponseModel: {status_code: int, status_message: str, data: T}
resp_200(data)       # 成功
resp_500(code, msg)  # 业务错误
```

**分页**：`PageData[T]`（推荐，字段 data + total）、`PageList[T]`（旧版兼容，字段 list + total）

**错误码**：5 位编码 `MMMEE`（模块 3 位 + 错误 2 位），定义在 `common/errcode/`。三种输出：`return_resp()`（HTTP）、`to_sse_event()`（SSE）、`websocket_close_message()`（WS）。模块编码：100=server, 101=finetune, 104=assistant, 105=flow, 106=user, 108=llm, 109=knowledge, 110=linsight, 120=workstation, 130=chat/channel, 140=message, 150=tool, 160=dataset, 170=telemetry, 180=knowledge_space

### 认证与权限

**JWT**：Token 存 Cookie（`access_token_cookie`），也支持 Header/WebSocket 提取。Payload：`{user_id, user_name, tenant_id}`。

**权限检查链路**（五级短路）：
1. 系统管理员（`system:global` 的 `super_admin`）→ 全权放行
2. 租户归属检查 → `tenant_id` 不匹配直接拒绝（安全底线）
3. 租户管理员（`tenant:{id}` 的 `admin`）→ 租户内全权放行
4. ReBAC（OpenFGA）→ owner/manager/editor/viewer 四级资源角色
5. RBAC 菜单权限 → `WEB_MENU` 控制前端导航可见性

**关键文件**：`permission/`（ReBAC 权限模块，统一权限检查入口 `PermissionService`）、`user/domain/services/auth.py`（LoginUser，内部委托 PermissionService）、`common/dependencies/user_deps.py`（UserPayload）

### 多租户与数据隔离

- 所有业务表包含 `tenant_id` 字段，通过 SQLAlchemy event 自动注入查询过滤和写入填充，无需手动 WHERE
- 资源创建时同步写入 OpenFGA owner 元组（通过 `PermissionService.authorize`）
- 权限检查使用 `PermissionService.check()` 而非直接查询 `RoleAccess`
- Celery 任务发送时将 `tenant_id` 写入 headers，Worker 执行前恢复 `current_tenant_id` ContextVar
- 外部存储按租户隔离：MinIO 路径前缀、Milvus/ES collection/index 前缀、Redis key 前缀

### 扩展工作流节点

三步：① `workflow/common/node.py` 添加 NodeType 枚举 → ② `workflow/nodes/<name>/` 创建节点类继承 BaseNode 实现 `_run()` → ③ `workflow/nodes/node_manage.py` 注册到 NODE_CLASS_MAP

## 核心子系统

> 回答"核心引擎内部怎么运转"。

### 工作流引擎 (`workflow/`)

基于 LangGraph 的 DAG 执行引擎。核心组件：
- `graph/graph_engine.py` — GraphEngine，将工作流 JSON 编译为 LangGraph 状态机
- `graph/graph_state.py` — GraphState 变量池，节点间数据传递
- `graph/workflow.py` — Workflow 包装类，管理超时和对话历史
- `nodes/node_manage.py` — NodeFactory 工厂 + NODE_CLASS_MAP 注册表
- `edges/edges.py` — EdgeManage 边管理
- `callback/` — 回调系统（on_node_start, on_stream_msg, on_output_msg 等）

**14 种节点类型**（每种在 `workflow/nodes/` 下有独立子目录）：START, END, INPUT, OUTPUT, FAKE_OUTPUT, LLM, CODE, CONDITION, KNOWLEDGE_RETRIEVER, QA_RETRIEVER, RAG, TOOL, AGENT, REPORT

**中断/恢复**：INPUT 节点和 OUTPUT（通过 FakeNode）触发 LangGraph `interrupt_before`，暂停等待用户输入。通过 Redis 存储状态，Celery 任务恢复执行。

**变量引用格式**：`{node_id}.{variable_key}` 或 `{node_id}.{variable_key}#{index}`

**配置**：WorkflowConf（max_steps=50, timeout=720min）

**Celery 执行**：`execute_workflow` / `continue_workflow` / `stop_workflow`，任务在 `worker/workflow/tasks.py`

### 知识库/RAG 管道 (`knowledge/`)

三阶段管道：**Load → Transform → Ingest**

- **Load**：按文件类型选择加载器（PDF/DOCX/TXT/HTML/Excel/图片），PDF 支持 4 种引擎（ETL4LM/MineRU/PaddleOCR/本地）
- **Transform**：摘要提取 → 附件/图片处理 → 缩略图生成 → 文本分块（ElemCharacterTextSplitter，默认 chunk_size=1000） → 预览缓存
- **Ingest**：同时写入 Milvus（稠密向量，语义检索）+ Elasticsearch（稀疏索引，BM25 关键词检索）

**文件处理状态**：WAITING(5) → PROCESSING(1) → SUCCESS(2) / FAILED(3) / TIMEOUT(6)

**异步处理**：所有文件处理通过 Celery `knowledge_celery` 队列执行

**核心管道类**：`knowledge/rag/pipeline/base.py`（NormalPipeline）、`knowledge/rag/knowledge_file_pipeline.py`（KnowledgeFilePipeline）

### Linsight Agent 框架 (`linsight/`)

独立 Worker 进程架构，通过 Redis 队列与 API 解耦。

**流程**：用户提交 → SOP 生成 → 任务拆解 → Agent 逐步执行（支持工具调用、用户交互、子任务生成）

**事件驱动**：TaskStart, TaskEnd, ExecStep, NeedUserInput, GenerateSubTask

**状态持久化**：Redis 缓存 + MySQL 双写，Redis 键 TTL 1 小时

**Worker 进程模型**：多个 ScheduleCenterProcess（multiprocessing），每个内部 asyncio.Semaphore 控制并发

**核心文件**：`linsight/worker.py`（Worker 入口）、`linsight/domain/task_exec.py`（LinsightWorkflowTask 任务执行器）

**bisheng_langchain 运行时**：`src/backend/bisheng_langchain/linsight/`（LinsightAgent, TaskManage, Task/ReactTask）

### MCP 管理 (`mcp_manage/`)

Factory 模式创建三种 MCP 客户端（SSE/STDIO/Streamable）。`McpTool`（`mcp_manage/langchain/tool.py`）将 MCP 工具桥接为 LangChain StructuredTool，供 TOOL/AGENT 节点和 Linsight Agent 调用。

### Celery Workers (`worker/`)

| 队列 | 并发 | 职责 |
|------|------|------|
| `knowledge_celery` | 20 线程 | 文档解析、Embedding、向量写入 |
| `workflow_celery` | 100 线程 | 工作流 DAG 执行 |
| `celery` (默认) | 100 线程 | 遥测统计 |

Beat 定时任务：每日 00:30 同步遥测统计，05:30 同步情报中心文章。Worker 心跳：每 5 秒向 Redis 写入（`celery_worker_alive_queues`）。多租户下 Beat 遍历所有活跃租户逐个执行。

## v2.5 改造上下文

> 理解遗留代码和迁移背景。目标架构的行为已在上方各章节中描述。

### 权限体系：RBAC → ReBAC

**为什么改**：旧 RBAC 权限分散在 `role_access` + `group_resource` + `space_channel_member` 三套机制中，无部门概念、无文件夹级权限、无操作级细粒度。

**新旧体系分工**：
```
OpenFGA (ReBAC)                     role 表 (策略角色 RBAC，保留)
├── 谁能访问/编辑/管理什么资源        ├── 能看到哪些菜单 (WEB_MENU)
├── 部门/用户组/文件夹继承            ├── 各资源创建上限 (Quota)
└── super_admin 短路判定              └── 角色作用域（部门级）
```

**权限金字塔**：`owner ⊃ manager(can_manage) ⊃ editor(can_edit) ⊃ viewer(can_read)`

**三种授权主体**：`user:X`、`department:X#member`、`user_group:X#member`

**OpenFGA 资源类型**：system, tenant, department, user_group, knowledge_space, folder, knowledge_file, channel, workflow, assistant, tool, dashboard

**关键设计决策**：
- 部门 admin 向下传递（`admin from parent`），member 不继承
- 授权给"部门(含子部门)"时，业务层展开子部门树，为每个子部门写入元组
- MySQL 与 OpenFGA 双写，失败记入 `failed_tuples` 补偿表
- `LoginUser.access_check` 内部委托 `PermissionService.check`

**废弃表**（迁移后）：`role_access`（资源授权部分）、`group_resource`、`space_channel_member` → 迁至 OpenFGA。保留 `role_access` 中 WEB_MENU 类型。

### 多租户引入

**为什么**：面向大型集团企业（中粮、首钢），需数据隔离、独立管理、统一管控。

**核心概念**：租户 = 部门树根节点，创建租户时自动创建根部门。系统管理员跨租户，租户管理员管租户内。用户与租户多对多（`user_tenant`）。

**隔离方式**：逻辑隔离 — 共享数据库 + `tenant_id` 字段。23+ 张业务表添加 `tenant_id`。默认租户（tenant_id=1）兼容升级，新租户用新前缀。

**配置开关**：`multi_tenant.enabled`（默认 false，关闭时行为与单租户一致）。

### 文档索引

| 文档 | 路径 |
|------|------|
| 权限改造 PRD | `docs/PRD/2.5 权限管理体系改造 PRD/2.5 权限管理体系改造 PRD.md` |
| 多租户需求文档 | `docs/PRD/2.5 权限管理体系改造 PRD/2.5 多租户需求文档.md` |
| 多租户管理 PRD | `docs/PRD/2.5 权限管理体系改造 PRD/2.5 多租户管理 PRD.md` |
| ReBAC 技术方案 | `docs/PRD/2.5 权限管理体系改造 PRD/2.5 技术方案.md` |
| 技术方案 Review | `docs/PRD/2.5 权限管理体系改造 PRD/2.5 技术方案 Review.md` |
| v2.4 权限体系详解 | `docs/architecture/10-permission-rbac.md` |

## 运维参考

### 核心配置

主配置文件: `src/backend/bisheng/config.yaml`

配置加载优先级：`YAML 文件 → 环境变量(BS_*) → 数据库配置(initdb_config) → Redis 缓存(100s TTL)`

主要配置分组：
- `database_url` — MySQL 连接（密码 Fernet 加密，key 在 settings.py 的 `secret_key`）
- `redis_url` / `celery_redis_url` — Redis 连接
- `vector_stores.milvus` / `vector_stores.elasticsearch` — 向量库与搜索引擎
- `object_storage.minio` — MinIO 对象存储
- `openfga` — OpenFGA 连接（api_url, store_id, model_id）
- `multi_tenant` — 多租户开关（enabled, default_tenant_code, storage_isolation）
- `celery_task` — Celery 任务路由和定时任务
- `workflow_conf` — 工作流参数（max_steps=50, timeout=720min）
- `linsight_conf` — Linsight 参数（max_steps=200, retry_num=3）
- `knowledge` — 知识库解析引擎配置（loader_provider: etl4lm/mineru/paddle_ocr）
- `cookie_conf` — JWT Cookie 配置（默认过期 86400s）

支持 `!env ${VAR}` 语法从环境变量注入配置值。

### CI/CD

- **协作分支**: `2.5.0-PM`（v2.5 开发主线）
- **Drone CI**: push 到 `2.5.0-PM` 自动触发构建 + 部署到测试服务器 + 飞书通知
- **配置文件**: `.drone.yml`（两条流水线：`cicd` 用于 release，`feat_cicd` 用于开发分支）

### 访问地址

| 服务 | 地址 |
|------|------|
| 主界面（本地） | http://localhost:3001 |
| API 文档 | http://localhost:7860/docs |
| 健康检查 | GET /health |

### 已知事项

1. **默认管理员**: 首个注册用户为系统管理员（super_admin），多租户开启时需先创建租户
2. **密码加密**: Fernet key 在 `core/config/settings.py` 中，用于加密 config.yaml 中的数据库/Redis 密码
3. **uv 依赖管理**: 使用 uv（非 Poetry），lockfile 为 `uv.lock`
4. **前端开发模式**: `npm start` 运行 vite dev server，自动代理 API 到后端
5. **MinIO 图片代理签名匹配**: Vite 的 `fileServiceTarget`（`vite.config.mts`）必须与后端 `config.yaml` 的 `object_storage.minio.sharepoint` 一致，否则签名校验失败导致图片 403
6. **OpenFGA**: 必须部署 OpenFGA 服务（Docker），作为 ReBAC 权限引擎

## SDD 开发规范

> BiSheng 采用 SDD（Spec-Driven Development）方法论进行 Feature 级开发。
> 完整指南：`docs/SDD-Guide.md`，项目适配：`features/README.md`。

### 工作流（9 步）

```
0. release-contract.md（版本开始时，一次性）
1. Spec Discovery → ★ 用户确认
2. 编写 spec.md
3. /sdd-review spec → ★ 用户确认
4. 编写 tasks.md
5. /sdd-review tasks（自动推进）
6. 创建 Feature 分支 feat/v2.5.0/{NNN}-{name}，基于 2.5.0-PM
7. 逐任务执行 → /task-review → 打勾
7.5. /e2e-test（强制）
8. /code-review --base 2.5.0-PM（自动）
9. 合并回 2.5.0-PM
```

### 产物位置

| 产物 | 路径 |
|------|------|
| 版本契约 | `features/v2.5.0/release-contract.md` |
| Feature 规格 | `features/v2.5.0/{NNN}-{name}/spec.md` |
| Feature 任务 | `features/v2.5.0/{NNN}-{name}/tasks.md` |
| 模板 | `features/_templates/` |

### 架构红线（L0 自动守卫）

以下规则由 `scripts/arch-guard.sh` 在每次 Write/Edit 后自动检查（通过 `.claude/settings.json` PostToolUse hook）：

| # | 规则 | 严重度 | 说明 |
|---|------|--------|------|
| 1 | common/core 不导入 domain/api | VIOLATION | 基础设施层不反向依赖领域层 |
| 2 | database/models 不导入 domain | VIOLATION | 纯 ORM 层不知道领域逻辑 |
| 3 | Endpoint 不直接导入 database/models | WARNING | 迁移期降级，应通过 Domain 层访问 |
| 4 | domain.models 不导入 domain.services | VIOLATION | 模型层不反向依赖服务层 |
| 5 | API 层不跨模块互相导入 | VIOLATION | 各模块 API 独立 |
| 6 | 前端 store 不直接调 HTTP | WARNING | 应通过 controllers/API 或 api/ 封装 |
| 7 | 硬编码敏感信息检测 | WARNING | password/secret/token 赋值检测 |

### 测试要求（务实版）

| 层 | 要求 | 当前现状 |
|----|------|---------|
| 后端 Service | Test-First：先测试再实现 | 需先搭建 conftest（F000） |
| 后端 API | 集成测试覆盖 happy path + error path | 需搭建 TestClient fixture |
| 前端 Platform | 手动验证（待搭建 Vitest 后转自动化） | 无测试框架 |
| 前端 Client | 手动验证（有 Jest 配置但无用例） | 有 Jest 但空 |
| E2E | API 端到端测试 + 手动验证清单 | 无浏览器 E2E 框架 |

### 审查命令

| 命令 | 时机 | 说明 |
|------|------|------|
| `/sdd-review <dir> spec` | spec 编写后 | 14 项需求+架构检查 |
| `/sdd-review <dir> tasks` | tasks 编写后 | 21 项拆解质量检查 |
| `/task-review <dir> <task_id>` | 每个任务完成后 | L1 约定合规（6 项） |
| `/code-review --base 2.5.0-PM` | Feature 全部完成后 | L2 多维度审查（6 维度） |
| `/e2e-test <dir>` | 全部任务完成后 | 生成并运行 E2E 测试 |

### 命名速查

| 对象 | 约定 |
|------|------|
| DAO 方法（同步） | `get_xxx()` / `create_xxx()` / `update_xxx()` / `delete_xxx()` |
| DAO 方法（异步） | `aget_xxx()` / `acreate_xxx()` / `aupdate_xxx()` / `adelete_xxx()` |
| 错误码 | 5 位 MMMEE，类名 `{Module}{Error}Error`，继承 `BaseErrorCode` |
| API 响应 | `resp_200(data)` / `resp_500(code, msg)` / `UnifiedResponseModel[T]` |
| Feature 分支 | `feat/v2.5.0/{NNN}-{name}`，基于 `2.5.0-PM` |
| Feature 目录 | `features/v2.5.0/{NNN}-{kebab-case-name}/` |
