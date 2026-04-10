# 后端领域模块总览

BiSheng 后端采用 DDD（领域驱动设计）架构，将业务逻辑拆分为 15+ 自治领域模块，每个模块拥有独立的 API 层、领域服务层和数据访问层。模块间通过明确的接口交互，基础设施层（`core/`）提供数据库、缓存、对象存储、向量库等共享能力。

所有后端代码位于 `src/backend/bisheng/` 目录下。

## 模块清单

### 业务领域模块

| 模块 | 路径 | 职责 | 内部结构 |
|------|------|------|----------|
| knowledge | `knowledge/` | 知识库管理、RAG 文档处理管道 | `api/` + `domain/services/` + `domain/repositories/` + `domain/models/` + `rag/` |
| workflow | `workflow/` | 工作流 DAG 执行引擎（LangGraph） | `graph/` + `nodes/` + `edges/` + `callback/` + `common/` |
| linsight | `linsight/` | Linsight Agent 自主任务框架 | `api/` + `domain/services/` + `domain/models/` + `worker.py` |
| llm | `llm/` | LLM 供应商管理、模型注册与配置 | `api/` + `domain/services/` + `domain/llm/` + `domain/models/` |
| chat_session | `chat_session/` | 聊天会话管理、消息持久化 | `api/` + `domain/services/` |
| tool | `tool/` | 工具/插件管理 | `api/` + `domain/services/` + `domain/models/` + `domain/langchain/` |
| channel | `channel/` | 多渠道通信、情报中心 | `api/` + `domain/services/` + `domain/repositories/` + `domain/models/` + `domain/es/` |
| message | `message/` | 消息收件箱 | `api/` + `domain/services/` + `domain/repositories/` + `domain/models/` |
| user | `user/` | 用户管理、认证、RBAC | `api/` + `domain/services/` + `domain/repositories/` + `domain/models/` |
| mcp_manage | `mcp_manage/` | MCP 协议集成（SSE/STDIO/Streamable） | `clients/` + `langchain/` + `manager.py` |
| finetune | `finetune/` | 模型微调流水线 | `api/` + `domain/services/` + `domain/models/` |
| share_link | `share_link/` | 公开分享链接管理 | `api/` + `domain/services/` + `domain/repositories/` + `domain/models/` |
| telemetry_search | `telemetry_search/` | 遥测数据检索与可视化 | `api/` + `domain/services/` + `domain/repositories/` + `domain/models/` |
| workstation | `workstation/` | 工作台后端 | `api/` + `domain/services/` + `domain/schemas/` |
| open_endpoints | `open_endpoints/` | v2 RPC 接口，面向外部系统集成 | `api/` + `domain/schemas/` |

### 非独立模块

以下模块没有独立的顶级目录，其路由定义在 `api/v1/` 中，数据模型在 `database/models/` 中：

| 路由 | 来源 | 职责 |
|------|------|------|
| assistant | `api/v1/assistant.py` | AI 助手生命周期管理 |
| evaluation | `api/v1/evaluation.py` | 模型评测 |
| audit | `api/v1/audit.py` | 审计日志 |
| group | `api/v1/group.py` | 用户组管理 |
| tag | `api/v1/tag.py` | 标签管理 |
| mark | `api/v1/mark.py` | 数据标注 |
| flows | `api/v1/flows.py` | 应用流程管理 |
| skillcenter | `api/v1/skillcenter.py` | 技能中心 |
| variable | `api/v1/variable.py` | 变量管理 |
| report | `api/v1/report.py` | 报表生成 |
| invite_code | `api/v1/invite_code.py` | 邀请码管理 |

## API 路由注册

路由注册在 `api/router.py` 中完成，分为两个版本：

**v1 路由**（`/api/v1`，共 29 个路由），面向前端应用：

```
chat, endpoints, knowledge, knowledge_space, server, user, qa, variable,
report, finetune, assistant, group, audit, evaluation, tag, llm, workflow,
mark, workstation, skillcenter, flows, linsight, tool, invite_code,
session, share_link, telemetry_search, channel, message
```

**v2 RPC 路由**（`/api/v2`，共 6 个路由），面向外部系统集成：

```
knowledge_rpc, filelib_rpc, chat_rpc, assistant_rpc, workflow_rpc, llm_rpc
```

v2 路由的实现位于 `open_endpoints/api/` 目录下，提供 RPC 风格的接口供第三方系统调用。

## DDD 分层约定

采用 DDD 分层的模块遵循以下目录结构约定：

```
module_name/
  api/                          # API 层：路由定义、请求/响应处理
    router.py                   # FastAPI Router 注册
    endpoints/                  # 按功能拆分的路由文件
  domain/                       # 领域层：业务逻辑核心
    services/                   # 领域服务，封装业务规则
    models/                     # 领域模型（非 ORM，业务实体）
    schemas/                    # Pydantic 数据传输对象（DTO）
    repositories/               # 数据访问抽象
      interfaces/               # 仓储接口定义
      implementations/          # 仓储实现（访问 database/models/）
```

请求处理的调用链路：

```
FastAPI Router (api/)
  --> 领域服务 (domain/services/)
    --> 仓储实现 (domain/repositories/implementations/)
      --> ORM 模型 DAO (database/models/)
        --> MySQL / Redis / Milvus / ES
```

部分模块（如 `workflow/`、`mcp_manage/`）由于业务特殊性，未采用标准 DDD 分层，而是按功能组件组织：`graph/`、`nodes/`、`edges/`、`callback/` 等。

## 核心基础设施（core/）

`core/` 目录提供所有领域模块共享的基础设施能力。

### 上下文管理（context/）

应用生命周期管理框架，负责基础设施资源的初始化和销毁。

- **`BaseContextManager[T]`** -- 通用基类，提供线程安全的延迟加载、自动缓存和健康检查
- **`ApplicationContextManager`** -- 编排所有上下文管理器，按依赖顺序初始化
- **`ContextRegistry`** -- 全局注册表，管理上下文实例的注册和查找

初始化顺序：`DatabaseManager` --> `RedisManager` --> `MinioManager` --> `EsConnManager` --> `HttpClientManager` --> `PromptManager`。关闭时逆序清理。

### 配置管理（config/）

`settings.py` 基于 Pydantic Settings，`Settings` 类包含约 40 个配置字段。配置加载优先级：

```
YAML 文件 (config.yaml) --> 环境变量 (bisheng_*) --> 数据库配置合并 --> Redis 缓存 (100s TTL)
```

支持 `!env ${VAR}` 语法从环境变量注入配置值。

### 数据库（database/）

SQLAlchemy 引擎工厂，支持同步和异步双模式会话。连接池默认 `pool_size=100`。ORM 模型定义在 `database/models/` 目录下，共 24 个模型文件。

每个模型文件包含：
- **Base 模型** -- SQLModel ORM 定义（表结构）
- **Read/Create/Update Schema** -- Pydantic 数据校验模型
- **DAO 类** -- 数据访问对象，提供同步 `get_xxx()` 和异步 `aget_xxx()` 方法

现有模型：flow, flow_version, assistant, knowledge (via domain), session, message, user_link, user_group, role, role_access, group, group_resource, tag, evaluation, dataset, mark_task, mark_record, mark_app_user, audit_log, report, template, variable_value, recall_chunk, invite_code。

### 缓存（cache/）

`RedisManager` 继承 `BaseContextManager`，提供 Redis 客户端的线程安全单例。支持同步和异步访问模式。

### 对象存储（storage/minio/）

`MinioManager` 管理与 MinIO/S3 的连接。`BaseStorage` 抽象接口定义文件上传、下载、删除等操作，方便替换存储后端。

### 搜索引擎（search/elasticsearch/）

`EsConnManager` 管理 Elasticsearch 连接，维护两个实例：主实例（文档检索）和统计实例（遥测数据）。

### 向量存储（vectorstore/）

向量库集成层，支持 Milvus 稠密向量检索 + Elasticsearch BM25 关键词检索的混合检索模式。

### AI 服务（ai/）

统一的 AI 模型服务封装层，按模型类型分子模块：

| 子模块 | 职责 |
|--------|------|
| `llm/` | 大语言模型调用封装 |
| `embeddings/` | 文本向量化服务 |
| `asr/` | 语音识别（Automatic Speech Recognition） |
| `tts/` | 语音合成（Text-to-Speech） |
| `rerank/` | 重排序模型 |

### 提示词管理（prompts/）

`PromptManager` 管理系统级提示词模板，YAML 格式存储，按场景加载。

### 外部服务（external/）

HTTP 客户端管理和外部服务集成：

- `http_client/` -- `HttpClientManager`，统一的 HTTP 客户端（连接池、超时、重试）
- `bisheng_information_client/` -- 情报中心服务客户端

## bisheng_langchain 扩展包

独立的 LangChain 扩展包，位于 `src/backend/bisheng_langchain/`，作为单独的 Python 包安装，被主应用 `bisheng` 导入使用。

包含以下子模块：

| 子模块 | 职责 |
|--------|------|
| `chains/` | 自定义 Chain 实现（QA、检索、路由等） |
| `chat_models/` | 聊天模型适配器 |
| `document_loaders/` | 文档加载器扩展 |
| `embeddings/` | Embedding 模型适配器 |
| `vectorstores/` | 向量存储适配器 |
| `rag/` | RAG 检索增强管道（评分、重排序、检索器初始化） |
| `agents/` | Agent 实现（LLM Functions Agent、ChatGLM Functions Agent） |
| `gpts/` | GPTs 工具集（Web 搜索、代码解释器、SQL Agent、DALL-E 等） |
| `linsight/` | Linsight Agent 核心逻辑 |
| `memory/` | 会话记忆管理 |
| `sql/` | SQL 执行相关 |
| `retrievers/` | 自定义检索器 |
| `input_output/` | 输入输出处理 |
| `utils/` | 工具函数 |

## 错误码体系

错误码基类 `BaseErrorCode` 定义在 `common/errcode/base.py` 中，采用 5 位数编码方案：

```
错误码格式: MMMEE
  MMM = 模块编码（前 3 位）
  EE  = 模块内错误序号（后 2 位）
```

### 模块编码分配

| 模块编码 | 模块 | 错误码范围 | 定义文件 |
|----------|------|-----------|----------|
| 100 | server（基础服务） | 10000-10099 | `server.py` |
| 101 | finetune（微调） | 10100-10199 | `finetune.py` |
| 103 | component（组件） | 10300-10399 | `component.py` |
| 104 | assistant（助手） | 10400-10499 | `assistant.py` |
| 105 | flow（应用/工作流） | 10500-10599 | `flow.py` |
| 106 | user（用户） | 10600-10699 | `user.py` |
| 108 | llm（模型管理） | 10800-10899 | `llm.py` |
| 109 | knowledge（知识库） | 10900-10999 | `knowledge.py` |
| 110 | linsight | 11000-11099 | `linsight.py` |
| 120 | workstation（工作台） | 12000-12099 | `workstation.py` |
| 130 | chat/channel | 13000-13099 | `chat.py`, `channel.py` |
| 140 | message（消息） | 14000-14099 | `message.py` |
| 150 | tool（工具） | 15000-15099 | `tool.py` |
| 160 | dataset（数据集） | 16000-16099 | `dataset.py` |
| 170 | telemetry（遥测） | 17000-17099 | `telemetry.py` |
| 180 | knowledge_space（知识空间） | 18000-18099 | `knowledge_space.py` |

### 错误返回格式

`BaseErrorCode` 支持三种错误返回格式，适配不同通信协议：

| 方法 | 用途 | 输出格式 |
|------|------|----------|
| `return_resp()` | HTTP 响应 | `UnifiedResponseModel` JSON |
| `to_sse_event()` | SSE 事件流 | `event: error\ndata: {...}\n\n` |
| `websocket_close_message()` | WebSocket 关闭 | JSON 消息 + 连接关闭 |

## 统一响应模型

所有 API 响应遵循 `UnifiedResponseModel` 结构，定义在 `common/schemas/api.py` 中：

```python
class UnifiedResponseModel(BaseModel, Generic[DataT]):
    status_code: int        # 状态码，200 表示成功，其他为错误码
    status_message: str     # 状态描述
    data: DataT = None      # 响应数据
```

辅助函数：

| 函数 | 用途 |
|------|------|
| `resp_200(data, message)` | 成功响应 |
| `resp_500(code, data, message)` | 业务错误响应 |

分页数据模型：

| 模型 | 字段 | 说明 |
|------|------|------|
| `PageList[T]` | `list: List[T]`, `total: int` | 旧版分页（兼容保留） |
| `PageData[T]` | `data: List[T]`, `total: int` | 新版分页（推荐使用） |

SSE 流式响应使用 `SSEResponse` 模型，输出格式为 `event: {event}\ndata: {data}\n\n`。

## Worker / Celery 任务

异步任务处理基于 Celery，代码位于 `worker/` 目录。

### 任务队列架构

```
Celery Broker (Redis)
  |
  +--> knowledge_celery 队列
  |      file_worker.py       -- 文件解析、知识库文件处理
  |      qa.py                -- QA 问答对生成
  |      rebuild_knowledge_worker.py -- 知识库重建、分块重建
  |
  +--> workflow_celery 队列
  |      tasks.py             -- execute_workflow, continue_workflow, stop_workflow
  |
  +--> celery 默认队列
         article.py           -- sync_information_article（情报中心文章同步）
         mid_table.py         -- 遥测统计中间表同步
```

### 已注册任务

| 任务函数 | 队列 | 职责 |
|----------|------|------|
| `parse_knowledge_file_celery` | knowledge_celery | 解析知识库文件、生成向量 |
| `file_copy_celery` | knowledge_celery | 文件复制 |
| `retry_knowledge_file_celery` | knowledge_celery | 失败文件重试 |
| `rebuild_knowledge_celery` | knowledge_celery | 知识库整体重建 |
| `rebuild_knowledge_file_chunk` | knowledge_celery | 单文件分块重建 |
| `execute_workflow` | workflow_celery | 执行工作流 |
| `continue_workflow` | workflow_celery | 恢复暂停的工作流（用户输入后继续） |
| `stop_workflow` | workflow_celery | 停止运行中的工作流 |
| `sync_information_article` | celery | 同步情报中心文章 |
| `sync_mid_user_increment` | celery | 同步用户增量统计 |
| `sync_mid_knowledge_increment` | celery | 同步知识库增量统计 |
| `sync_mid_app_increment` | celery | 同步应用增量统计 |
| `sync_mid_user_interact_dtl` | celery | 同步用户交互明细 |

### Beat 定时任务

Celery Beat 定时调度器配置在 `Settings.celery_task.beat_schedule` 中，典型的定时任务包括：

- 每日凌晨同步遥测统计中间表（用户/知识库/应用增量）
- 每日同步情报中心文章

### Worker 心跳机制

Worker 启动后，通过后台线程每 5 秒向 Redis 写入心跳时间戳（`celery_worker_alive_queues` 哈希键），用于监控 Worker 存活状态。

## 相关文档

| 文档 | 说明 |
|------|------|
| [系统架构全景图](./01-architecture-overview.md) | 运行时组件、请求数据流、技术栈 |
| [工作流引擎](./03-workflow-engine.md) | 工作流 DAG 执行引擎详解 |
| [知识库与 RAG 管道](./04-knowledge-rag.md) | 文档处理流水线、双向量存储 |
| [Linsight Agent 与 MCP](./05-linsight-agent.md) | Agent 框架与 MCP 协议集成 |
| [数据模型与存储层](./07-data-models.md) | ORM 模型定义、DAO 模式 |
