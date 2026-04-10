# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

BiSheng (毕昇) v2.4.0 — 面向企业的开源 LLM 应用 DevOps 平台。支持工作流编排、知识库管理、多 Agent 协作（Linsight 灵思）、模型评测与微调、MCP 集成。

**架构定位**：前后端分离 + 异步任务处理的分层架构。7 个运行时进程组 + 5 个基础设施服务，后端遵循 DDD（领域驱动设计）模式。

## 部署架构

采用混合部署：主要服务本地源码运行，存储服务 Docker 容器化。

```
本地服务 (源码部署)                    Docker 存储层
├── FastAPI 后端 (uvicorn) :7860      ├── Milvus 2.5 向量库  :19530
├── MySQL 8.0            :3306        ├── Elasticsearch 8.12 :9200
├── Redis 7.0            :6379        ├── MinIO 对象存储     :9000
├── Celery Workers                    └── OnlyOffice         :8701
├── Linsight Worker (可选)
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

## 代码架构

> 详细架构文档见 `docs/architecture/`，以下为关键导航信息。

### 仓库结构

```
bisheng/
├── src/backend/bisheng/           # FastAPI 后端主应用
├── src/backend/bisheng_langchain/  # LangChain 扩展包 (独立 Python 包)
├── src/frontend/platform/          # Platform 管理端前端 (React)
├── src/frontend/client/            # Client 用户端前端 (React)
├── docker/                         # Docker Compose 部署
└── docs/architecture/              # 架构文档 (10 篇)
```

### 后端 (`src/backend/bisheng/`)

#### 入口与生命周期

- **`main.py`** — FastAPI 应用创建，lifespan 管理（初始化基础设施 → 初始化默认数据 → yield → 逆序清理）
- **`api/router.py`** — 全局路由注册（v1: 29 个路由，v2: 6 个 RPC 路由）
- **`config.yaml`** — 主配置文件（本地开发用）

中间件栈（请求入站顺序）：`CORSMiddleware` → `CustomMiddleware`（请求日志 + X-Trace-ID） → `WebSocketLoggingMiddleware`

#### 基础设施初始化顺序

`ApplicationContextManager`（`core/context/manager.py`）按依赖顺序初始化：
```
DatabaseManager → RedisManager → MinioManager → EsConnManager(业务) → EsConnManager(统计) → HttpClientManager → PromptManager
```
关闭时逆序清理。所有 Manager 继承 `BaseContextManager[T]`，提供线程安全的延迟加载。

#### 后端模块地图

**独立 DDD 领域模块**（有自己的顶级目录 + `api/` + `domain/` 结构）：

| 模块 | 路径 | 职责 |
|------|------|------|
| knowledge | `knowledge/` | 知识库管理、RAG 文档处理管道 |
| workflow | `workflow/` | 工作流 DAG 执行引擎（LangGraph） |
| linsight | `linsight/` | Linsight Agent 自主任务框架，独立 Worker |
| llm | `llm/` | LLM 供应商管理、模型注册与配置 |
| chat_session | `chat_session/` | 聊天会话管理、消息持久化 |
| tool | `tool/` | 工具/插件管理 |
| channel | `channel/` | 多渠道通信、情报中心 |
| message | `message/` | 消息收件箱 |
| user | `user/` | 用户管理、认证（JWT）、RBAC |
| finetune | `finetune/` | 模型微调流水线 |
| share_link | `share_link/` | 公开分享链接 |
| telemetry_search | `telemetry_search/` | 遥测数据检索 |
| workstation | `workstation/` | 工作台后端 |
| open_endpoints | `open_endpoints/` | v2 RPC 接口，面向外部系统集成 |
| mcp_manage | `mcp_manage/` | MCP 协议集成（SSE/STDIO/Streamable） |

**非独立模块**（路由在 `api/v1/` 中，无独立顶级目录）：

assistant, evaluation, audit, group, tag, mark, flows, skillcenter, variable, report, invite_code

**基础设施模块**：

| 目录 | 职责 |
|------|------|
| `core/context/` | 应用生命周期上下文管理（BaseContextManager → ApplicationContextManager） |
| `core/config/settings.py` | Pydantic Settings 配置模型（约 40 个字段） |
| `core/database/` | SQLAlchemy 引擎工厂（同步 pymysql + 异步 aiomysql，pool_size=100） |
| `core/cache/` | Redis 缓存（RedisManager） |
| `core/ai/` | AI 模型服务封装（llm/, embeddings/, asr/, tts/, rerank/） |
| `core/storage/minio/` | MinIO S3 对象存储 |
| `core/search/elasticsearch/` | Elasticsearch 集成（业务实例 + 统计实例） |
| `core/vectorstore/` | Milvus 向量库集成 |
| `core/prompts/` | 提示词模板管理 |
| `core/external/` | HTTP 客户端、情报中心客户端 |
| `common/errcode/` | 错误码定义（5 位编码，前 3 位=模块，后 2 位=错误序号） |
| `common/schemas/api.py` | 统一响应模型 UnifiedResponseModel（resp_200 / resp_500） |
| `common/dependencies/` | FastAPI 依赖注入（user_deps.py: UserPayload） |
| `common/init_data.py` | 默认数据初始化（管理员、角色、用户组、模板） |
| `database/models/` | SQLModel ORM 模型（24 个），每个文件含 Base/Read/Create/Update Schema + DAO 类 |
| `worker/` | Celery 异步任务（knowledge_celery / workflow_celery / celery 三个队列） |

#### DDD 分层约定

标准模块目录结构：
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
      interfaces/                # 仓储接口
      implementations/           # 仓储实现
```

调用链路：`Router → Endpoint → Service → Repository(可选) → DAO (database/models/) → MySQL`

简单模块可省略 repositories 层，在 Service 中直接调用 DAO。

#### DAO 模式

所有 ORM 模型在 `database/models/`，DAO 方法命名约定：
- 同步：`get_xxx()`, `create_xxx()`, `update_xxx()`, `delete_xxx()`, `filter_xxx()`
- 异步：`aget_xxx()`, `acreate_xxx()` 等
- 通过 `get_sync_db_session()` / `get_async_db_session()` 获取会话，均为 `@classmethod`

#### API 路由架构

**v1 路由** (`/api/v1`，29 个，面向前端)：chat, knowledge, knowledge_space, qa, workflow, assistant, llm, user, group, tool, evaluation, finetune, server, linsight, session, channel, message, share_link, telemetry_search, flows, workstation, skillcenter, endpoints, variable, report, audit, tag, mark, invite_code

**v2 RPC 路由** (`/api/v2`，6 个，面向外部集成)：knowledge_rpc, filelib_rpc, chat_rpc, assistant_rpc, workflow_rpc, llm_rpc。实现在 `open_endpoints/api/`。

#### 统一响应格式

```python
UnifiedResponseModel: {status_code: int, status_message: str, data: T}
resp_200(data)       # 成功
resp_500(code, msg)  # 业务错误
```

分页：`PageData[T]`（推荐，字段 data + total）、`PageList[T]`（旧版兼容，字段 list + total）

#### 错误码体系

错误码定义在 `common/errcode/`，5 位编码 `MMMEE`（模块3位 + 错误2位）。支持三种输出：`return_resp()`（HTTP）、`to_sse_event()`（SSE）、`websocket_close_message()`（WS）。

模块编码：100=server, 101=finetune, 104=assistant, 105=flow, 106=user, 108=llm, 109=knowledge, 110=linsight, 120=workstation, 130=chat/channel, 140=message, 150=tool, 160=dataset, 170=telemetry, 180=knowledge_space

#### 认证与权限

**JWT 认证**：Token 存 Cookie（`access_token_cookie`），也支持 Header/WebSocket 提取。通过 `UserPayload = Depends(UserPayload.get_login_user)` 依赖注入获取当前用户。

**RBAC 三层模型**：
1. 认证：JWT → `{user_id, user_name}`
2. 身份加载：`LoginUser.init_login_user()` → 加载角色列表 → 判断 admin（role_id=1）
3. 授权：admin 全权绕过，否则检查 `Owner → RoleAccess → 拒绝`

**权限类型**（AccessType）：KNOWLEDGE(1)/KNOWLEDGE_WRITE(3), ASSISTANT_READ(5)/WRITE(6), GPTS_TOOL_READ(7)/WRITE(8), WORKFLOW(9)/WRITE(10), DASHBOARD(11)/WRITE(12), WEB_MENU(99)

**知识空间**独立走成员制（SpaceChannelMember），不走 RBAC：Creator > Admin > Member

**关键文件**：`user/domain/services/auth.py`（LoginUser 权限核心）、`common/dependencies/user_deps.py`（UserPayload）

#### 工作流引擎 (`workflow/`)

基于 LangGraph 的 DAG 执行引擎。核心组件：
- `graph/graph_engine.py` — GraphEngine，将工作流 JSON 编译为 LangGraph 状态机
- `graph/graph_state.py` — GraphState 变量池，节点间数据传递
- `graph/workflow.py` — Workflow 包装类，管理超时和对话历史
- `nodes/node_manage.py` — NodeFactory 工厂 + NODE_CLASS_MAP 注册表
- `edges/edges.py` — EdgeManage 边管理
- `callback/` — 回调系统（on_node_start, on_stream_msg, on_output_msg 等）

**14 种节点类型**（每种在 `workflow/nodes/` 下有独立子目录）：START, END, INPUT, OUTPUT, FAKE_OUTPUT, LLM, CODE, CONDITION, KNOWLEDGE_RETRIEVER, QA_RETRIEVER, RAG, TOOL, AGENT, REPORT

**中断/恢复机制**：INPUT 节点和 OUTPUT（通过 FakeNode）触发 LangGraph `interrupt_before`，暂停等待用户输入。通过 Redis 存储状态，Celery 任务恢复执行。

**变量引用格式**：`{node_id}.{variable_key}` 或 `{node_id}.{variable_key}#{index}`

**配置**：WorkflowConf（max_steps=50, timeout=720min）

**Celery 执行**：`execute_workflow` / `continue_workflow` / `stop_workflow`，任务在 `worker/workflow/tasks.py`，RedisCallback 在 `worker/workflow/redis_callback.py`。

**扩展新节点**：① `workflow/common/node.py` 添加 NodeType 枚举 → ② `workflow/nodes/<name>/` 创建节点类继承 BaseNode 实现 `_run()` → ③ `workflow/nodes/node_manage.py` 注册到 NODE_CLASS_MAP

#### 知识库/RAG 管道 (`knowledge/`)

三阶段管道：**Load → Transform → Ingest**

- **Load**：按文件类型选择加载器（PDF/DOCX/TXT/HTML/Excel/图片），PDF 支持 4 种引擎（ETL4LM/MineRU/PaddleOCR/本地）
- **Transform**：摘要提取 → 附件/图片处理 → 缩略图生成 → 文本分块（ElemCharacterTextSplitter，默认 chunk_size=1000） → 预览缓存
- **Ingest**：同时写入 Milvus（稠密向量，语义检索）+ Elasticsearch（稀疏索引，BM25 关键词检索）

**文件处理状态**：WAITING(5) → PROCESSING(1) → SUCCESS(2) / FAILED(3) / TIMEOUT(6)

**异步处理**：所有文件处理通过 Celery `knowledge_celery` 队列执行

**核心管道类**：`knowledge/rag/pipeline/base.py`（NormalPipeline）、`knowledge/rag/knowledge_file_pipeline.py`（KnowledgeFilePipeline）

#### Linsight Agent 框架 (`linsight/`)

独立 Worker 进程架构，通过 Redis 队列与 API 解耦。

**流程**：用户提交 → SOP 生成 → 任务拆解 → Agent 逐步执行（支持工具调用、用户交互、子任务生成）

**事件驱动**：TaskStart, TaskEnd, ExecStep, NeedUserInput, GenerateSubTask

**状态持久化**：Redis 缓存 + MySQL 双写，Redis 键 TTL 1 小时

**Worker 进程模型**：多个 ScheduleCenterProcess（multiprocessing），每个内部 asyncio.Semaphore 控制并发

**核心文件**：`linsight/worker.py`（Worker 入口）、`linsight/domain/task_exec.py`（LinsightWorkflowTask 任务执行器）

**bisheng_langchain 运行时**：`src/backend/bisheng_langchain/linsight/`（LinsightAgent, TaskManage, Task/ReactTask）

#### MCP 管理 (`mcp_manage/`)

Factory 模式创建三种 MCP 客户端：
- `clients/sse.py` — SSE（Server-Sent Events）
- `clients/stdio.py` — STDIO（标准输入/输出）
- `clients/streamable.py` — Streamable HTTP

`McpTool`（`mcp_manage/langchain/tool.py`）将 MCP 工具桥接为 LangChain StructuredTool，供 TOOL/AGENT 节点和 Linsight Agent 调用。

#### Celery Workers (`worker/`)

| 队列 | 并发 | 职责 |
|------|------|------|
| `knowledge_celery` | 20 线程 | 文档解析、Embedding、向量写入 |
| `workflow_celery` | 100 线程 | 工作流 DAG 执行 |
| `celery` (默认) | 100 线程 | 遥测统计 |

任务路由配置在 `core/config/settings.py`。Beat 定时任务：每日 00:30 同步遥测统计，05:30 同步情报中心文章。

Worker 心跳：每 5 秒向 Redis 写入心跳（`celery_worker_alive_queues`）。

#### 数据模型 (`database/models/`)

**24 个 ORM 模型**，核心模型：

| 模型 | 说明 |
|------|------|
| Flow | 应用统一定义（FlowType: ASSISTANT=5, WORKFLOW=10, WORKSTATION=15, LINSIGHT=20, CHANNEL_ARTICLE=25, KNOWLEDGE_SPACE=30）|
| FlowVersion | 版本控制，`is_current` 标记当前版本 |
| Assistant / AssistantLink | 助手配置 + 关联表（工具/技能/知识库） |
| ChatMessage | 聊天消息（LONGTEXT），含 liked/solved/sensitive_status |
| MessageSession | 会话记录，关联应用与用户 |
| Role / RoleAccess | 角色定义 + 权限映射（AdminRole=1, DefaultRole=2） |
| Group / UserGroup / GroupResource | 用户组 + 组成员 + 组资源 |

**5 种存储引擎**：MySQL（关系数据）、Redis（缓存/Broker/状态）、Milvus（稠密向量）、Elasticsearch（稀疏索引/遥测统计，双实例）、MinIO（文件对象）

#### bisheng_langchain 扩展包 (`src/backend/bisheng_langchain/`)

独立 Python 包，被主应用导入。包含：chains, chat_models, document_loaders, embeddings, vectorstores, rag（检索器/评分/重排序）, agents, gpts（工具集）, linsight（Agent 核心逻辑）, memory 等。

### 双前端架构

| 维度 | Platform (管理端) | Client (用户端) |
|------|-------------------|-----------------|
| 路径 | `src/frontend/platform/` | `src/frontend/client/` |
| 端口 | 3001 | 4001 |
| 基础路径 | `/` | `/workspace` |
| 定位 | 管理员/构建者 | 终端用户对话 |
| 状态管理 | Zustand + React Context | Zustand (18+ slices) |
| PWA | 不支持 | 支持 |

**共同技术栈**：React 18 + TypeScript + Vite + Radix UI + Tailwind CSS + i18next（中/英/日）+ Axios

**Platform 状态管理**：
- Zustand stores（`src/store/`）：dashboardStore, editFlowStore, diffFlowStore, assistantStore
- React Context（`src/contexts/`）：11 个 Provider 层级嵌套（UserProvider, SSEProvider, AlertProvider, DarkProvider 等）

**Platform API 层**：`src/controllers/request.ts`（Axios 封装，JWT 注入，统一拦截），API 模块在 `src/controllers/API/`（index, workflow, flow, user, dashboard, evaluate, label, log, tools, linsight, finetune, assistant, workbench 等）

**Vite 代理（Platform）**：`/api/` → `:7860`，`/health` → `:7860`，`/bisheng` → MinIO `:9000`，`/tmp-dir` → MinIO `:9000`

**Vite 代理（Client）**：所有路径需重写去除 `/workspace` 前缀后再转发

### 核心数据流

```
浏览器 → Nginx :8860 → Vite :3001/:4001 → FastAPI :7860 → Service → DAO → MySQL/Redis
                                                         → Celery Task → Milvus/ES/MinIO
WebSocket → ChatManager → 回调流式输出 → 队列缓冲 → 消息持久化
```

## 开发约定

### 新增业务模块

1. 在 `src/backend/bisheng/` 下创建模块目录，含 `api/` 和 `domain/`
2. 在 `api/router.py` 创建 APIRouter
3. 在 `src/backend/bisheng/api/router.py` 注册路由
4. 实现调用链：Router → Endpoint → Service → Repository/DAO

### 新增 API 端点

- 使用 `UserPayload = Depends(UserPayload.get_login_user)` 获取认证用户
- 返回 `UnifiedResponseModel`，用 `resp_200()` / `resp_500()`
- WebSocket 用 `UserPayload.get_login_user_from_ws`

### 新增工作流节点

三步：① `workflow/common/node.py` 添加 NodeType → ② `workflow/nodes/<name>/` 实现 BaseNode._run() → ③ `workflow/nodes/node_manage.py` 注册 NODE_CLASS_MAP

## CI/CD

- **协作分支**: `2.5.0-PM`（v2.5 开发主线）
- **Drone CI**: push 到 `2.5.0-PM` 自动触发构建 + 部署到测试服务器 + 飞书通知
- **配置文件**: `.drone.yml`（两条流水线：`cicd` 用于 release，`feat_cicd` 用于开发分支）

## 核心配置

主配置文件: `src/backend/bisheng/config.yaml`

配置加载优先级：`YAML 文件 → 环境变量(BS_*) → 数据库配置(initdb_config) → Redis 缓存(100s TTL)`

主要配置分组：
- `database_url` — MySQL 连接（密码 Fernet 加密，key 在 settings.py 的 `secret_key`）
- `redis_url` / `celery_redis_url` — Redis 连接
- `vector_stores.milvus` — Milvus 向量库
- `vector_stores.elasticsearch` — Elasticsearch
- `object_storage.minio` — MinIO 对象存储
- `celery_task` — Celery 任务路由和定时任务
- `workflow_conf` — 工作流参数（max_steps=50, timeout=720min）
- `linsight_conf` — Linsight 参数（max_steps=200, retry_num=3）
- `knowledge` — 知识库解析引擎配置（loader_provider: etl4lm/mineru/paddle_ocr）
- `logger_conf` — 日志配置
- `password_conf` — 密码策略
- `cookie_conf` — JWT Cookie 配置（默认过期 86400s）

支持 `!env ${VAR}` 语法从环境变量注入配置值。

## 访问地址

| 服务 | 地址 |
|------|------|
| 主界面（本地） | http://localhost:3001 |
| API 文档 | http://localhost:7860/docs |
| 健康检查 | GET /health |

## 已知事项

1. **默认管理员**: 首个注册用户自动获得管理员权限
2. **密码加密**: Fernet key 在 `core/config/settings.py` 中，用于加密 config.yaml 中的数据库/Redis 密码
3. **uv 依赖管理**: 2.4.0 使用 uv（非 Poetry），lockfile 为 `uv.lock`
4. **前端开发模式**: `npm start` 运行 vite dev server，自动代理 API 到后端
5. **MinIO 图片代理签名匹配**: Vite 的 `fileServiceTarget`（`vite.config.mts`）必须与后端 `config.yaml` 的 `object_storage.minio.sharepoint` 一致。MinIO presigned URL 签名包含 Host 头，Vite proxy 的 `changeOrigin: true` 会将 Host 改为 target 地址，若与 sharepoint 不匹配则签名校验失败导致图片 403
