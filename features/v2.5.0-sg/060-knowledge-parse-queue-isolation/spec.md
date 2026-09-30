# Feature: F060-知识文件解析队列隔离

> **前置步骤**：已完成 Spec Discovery。用户于 2026-08-05 确认：
> `knowledge_celery` 只承载文件解析必要任务，其他现有任务迁移到默认 `celery` 队列。

**关联需求**: 知识空间文件解析 Worker 队列治理  
**优先级**: P0  
**所属版本**: v2.5.0-sg  
**状态**: Confirmed（2026-08-05 用户确认规格）  
**类型**: 后端 Celery 运行时路由调整；不新增 API、数据库表、迁移或第三方依赖。

---

## 1. 概述与用户故事

作为 **平台运维和研发人员**，
我希望 `knowledge_celery` 成为只处理知识文件解析的专用队列，
以便知识迁移、推荐、投影、组织同步和其他后台任务不会占用解析 Worker，稳定文件解析吞吐和等待时间。

### 当前问题

- `bisheng.worker.knowledge.*` 当前整体路由到 `knowledge_celery`，解析、复制、删除、迁移、推荐、投影、QA 和重建任务共享同一队列。
- 组织同步、租户修复、权限清理、消息推送和课程清理等非知识解析任务也复用 `knowledge_celery`。
- 部分生产代码通过 `apply_async(queue="knowledge_celery")` 绕过通用路由配置。
- 仓库包含多份 YAML 配置和两份 Worker 启动脚本，当前队列契约缺少统一的自动化约束。

---

## 2. 目标与非目标

### 2.1 目标

- 将 `knowledge_celery` 收敛为文件解析专用队列。
- 只有明确白名单中的三个任务能够路由到 `knowledge_celery`。
- 将当前所有其他 `knowledge_celery` 任务迁移到默认 `celery` 队列。
- 保持 `knowledge_pdf_celery`、`workflow_celery` 的职责和路由不变。
- 通过自动化契约测试阻止未来非解析任务重新进入 `knowledge_celery`。
- 保持 API、文件状态机、解析算法、租户上下文和业务结果不变。

### 2.2 非目标

- 不修改文件解析实现、自动重试、超时和幂等机制。
- 不修改 Worker 并发数、线程池类型或 Redis Broker 配置。
- 不合并或删除 `knowledge_pdf_celery`、`workflow_celery`。
- 不清空、迁移或重写 Redis 中已经发布的存量消息。
- 不为每类非解析任务新建独立队列。
- 不调整 Celery Beat 的任务周期。
- 不新增任务结果后端、监控系统或管理 API。

---

## 3. 队列职责契约

### 3.1 `knowledge_celery` 白名单

以下三个任务属于一次文件进入 RAG 管线的必要链路，必须保留在 `knowledge_celery`：

| Task Name | 职责 |
|-----------|------|
| `bisheng.worker.knowledge.file_title_worker.extract_knowledge_file_title_celery` | 解析前标题提取和 AI 别名生成；结束后投递正式解析 |
| `bisheng.worker.knowledge.file_worker.parse_knowledge_file_celery` | 首次执行文件 Load、Transform、Milvus/ES Ingest |
| `bisheng.worker.knowledge.file_worker.retry_knowledge_file_celery` | 删除旧向量后重新执行文件解析 |

### 3.2 不属于文件解析的任务

以下任务类别必须进入默认 `celery` 队列：

- 文件删除、复制和向量复制；
- 相似文件候选刷新；
- 文件 Chunk 元数据重建、知识库整体重建；
- QA 导入、复制和重建；
- 知识空间初始化、迁移和回收站清理；
- 文档投影、推荐、热搜和收藏通知；
- 知识文件迁移预检、执行和 reconcile；
- 组织同步、租户 reconcile、管理员 scope 清理；
- 权限补偿、部门变更清理、消息推送和课程清理；
- 当前或未来未进入解析白名单的其他任务。

### 3.3 保持独立的队列

| Queue | 保持的职责 |
|-------|------------|
| `knowledge_pdf_celery` | PDF Artifact 校验、转换和重试 |
| `workflow_celery` | 工作流和审批执行 |
| `celery` | 除解析、PDF、工作流外的默认后台任务 |

---

## 4. 需求 Requirements

| ID | 需求 |
|----|------|
| REQ-001 | 系统必须使用显式任务白名单定义 `knowledge_celery` 的合法任务，白名单只能包含 §3.1 的三个任务。 |
| REQ-002 | 当前所有非白名单任务必须通过 Celery 路由或显式投递参数进入默认 `celery` 队列。 |
| REQ-003 | PDF Artifact 必须继续进入 `knowledge_pdf_celery`，工作流和审批任务必须继续进入 `workflow_celery`。 |
| REQ-004 | 路由构建必须覆盖仓库默认配置和旧版宽泛 `bisheng.worker.knowledge.* → knowledge_celery` 配置，避免旧配置破坏专用队列不变量。 |
| REQ-005 | 仓库内 YAML、Python 默认配置、显式投递点、注释和测试必须使用一致的队列契约。 |
| REQ-006 | 队列调整不得改变任务参数、任务名称、业务状态、租户 header、Beat 周期或 API 契约。 |
| REQ-007 | 发布不得清空存量队列；旧 `knowledge_celery` 消息由现有 Worker 自然消费，新消息按新路由投递。 |

---

## 5. 验收标准

| ID | 关联需求 | 场景 | 预期结果 | 验证方式 |
|----|----------|------|----------|----------|
| AC-01 | REQ-001 | 解析三个白名单任务的最终路由 | 三个任务均解析为 `knowledge_celery` | 纯函数路由单元测试 |
| AC-02 | REQ-002 | 解析文件删除、复制、相似度、重建、QA、迁移、投影和推荐任务路由 | 均解析为默认 `celery` | 参数化路由单元测试 |
| AC-03 | REQ-002, REQ-005 | 扫描生产代码中的显式队列投递 | 除三个白名单任务路由定义外，不存在非解析任务显式投递到 `knowledge_celery` | 部署契约/source scan 测试 |
| AC-04 | REQ-003 | 解析 PDF、工作流和审批任务路由 | 分别保持 `knowledge_pdf_celery`、`workflow_celery` | 参数化路由单元测试 |
| AC-05 | REQ-004 | 输入旧版 `bisheng.worker.knowledge.* → knowledge_celery` 自定义配置 | 非白名单任务仍进入 `celery`，三个白名单任务仍进入 `knowledge_celery` | 兼容性单元测试 |
| AC-06 | REQ-005 | 检查仓库内运行配置 | 默认配置、Docker 配置和开发配置均声明相同路由 | YAML 契约测试 |
| AC-07 | REQ-006 | 执行解析标题后继任务及现有租户路由测试 | 参数、后继解析投递和 tenant header 行为保持不变 | 现有相关回归测试 |
| AC-08 | REQ-007 | 按发布顺序部署新生产者和 Worker | 不执行队列 purge；存量消息可继续被消费，新非解析任务进入默认队列 | 静态发布检查 + 人工 Worker 冒烟 |

---

## 6. 架构设计

### 6.1 路由模型

新增一个无外部依赖的队列契约模块，集中维护：

- 队列名称常量；
- 文件解析任务白名单；
- 受保护的 PDF、工作流和审批路由；
- 从用户配置构建最终 `task_routes` 的纯函数。

最终路由构建遵循以下顺序：

1. 读取 `settings.celery_task.task_routers`。
2. 将任何试图把非白名单任务或宽泛 pattern 路由到 `knowledge_celery` 的旧配置规范化到默认队列。
3. 写入非解析任务的默认路由。
4. 最后写入三个解析任务、PDF 任务和工作流/审批任务的受保护精确路由。

受保护路由不允许被旧版宽泛配置覆盖。对旧配置采用兼容性规范化，而不是启动失败，便于滚动升级。

### 6.2 显式投递

- 三个解析任务继续通过 `.delay()` 使用最终路由，不改变调用参数。
- 当前硬编码到 `knowledge_celery` 的非解析 `apply_async()` 调用改为默认 `celery`，或移除多余的 `queue` 参数并依赖统一路由。
- 跨租户 fanout 任务继续显式传递 tenant header；只改变 queue，不改变 header 和参数。

### 6.3 发布时消息行为

Celery 消息在发布时已经确定队列。路由变更不会移动 Redis 中的历史消息：

```text
发布前已进入 knowledge_celery 的非解析消息
    → 继续由 knowledge Worker 消费直至自然清空

发布后产生的非解析消息
    → 进入默认 celery 队列
```

禁止通过 `celery purge`、Redis key 删除或其他破坏性方式处理存量消息。

---

## 7. 兼容性与风险

### 7.1 默认 Worker 容量

非解析任务迁移后，默认 Worker 的任务量会上升。仓库默认部署已经启动 `celery` 队列消费者，但实际容量仍需在发布环境观察：

- 默认队列 backlog；
- 任务等待时间和失败率；
- 默认 Worker CPU、内存和线程使用；
- `knowledge_celery` 文件从 `WAITING` 到 `PROCESSING` 的等待时间。

本 Feature 不自动修改并发数；需要扩容时作为独立运维动作处理。

### 7.2 滚动发布窗口

旧生产者在滚动发布期间仍可能把非解析任务投递到 `knowledge_celery`。由于知识 Worker 可以加载全部已注册任务，这些消息仍能执行；待所有生产者升级后，新路由完全生效。

### 7.3 自定义配置兼容

旧部署配置中的宽泛知识任务路由会被规范化，不能继续把非解析任务放回专用队列。这是有意的兼容性收敛，不改变任务业务行为。

---

## 8. 回滚方案

- 回滚生产代码和 YAML 路由即可恢复原有队列分配。
- 不涉及数据库和对象存储数据变更，无需数据回滚。
- 回滚不搬迁已发布消息：新旧队列中的消息由对应 Worker 自然消费。
- 回滚期间必须同时保持 `knowledge_celery` 和默认 `celery` Worker 在线，避免任一队列积压。

---

## 9. 文件结构计划

### 新建

| 文件 | 说明 |
|------|------|
| `features/v2.5.0-sg/060-knowledge-parse-queue-isolation/spec.md` | 本规格 |
| `features/v2.5.0-sg/060-knowledge-parse-queue-isolation/tasks.md` | 规格确认后的实施任务 |
| `features/v2.5.0-sg/060-knowledge-parse-queue-isolation/verification.md` | 最终验证证据 |
| `src/backend/bisheng/core/config/celery_queues.py` | 队列常量、解析白名单和路由构建逻辑 |
| `src/backend/test/celery/test_knowledge_parse_queue_routing.py` | 路由、配置和 source scan 契约测试 |

### 修改

| 文件范围 | 变更内容 |
|----------|----------|
| `src/backend/bisheng/worker/config.py` | 使用统一路由构建逻辑 |
| `src/backend/bisheng/core/config/settings.py` | 默认任务路由改为解析白名单 + 默认队列 |
| `src/backend/bisheng/config*.yaml` | 多环境配置与新契约对齐 |
| `docker/bisheng/config/config*.yaml` | Docker 配置与新契约对齐 |
| 非解析任务的显式投递文件 | `knowledge_celery` 改为默认队列 |
| 受影响的既有测试 | 更新原队列断言，保持业务断言不变 |
| `features/v2.5.0-sg/release-contract.md` | 登记 F060 队列所有权和依赖不变量 |

具体生产文件列表以 `tasks.md` 中的检索基线为准；实现不得修改文件解析算法和无关业务逻辑。

---

## 10. 验证策略

### V1 定向验证

- 纯函数验证解析白名单、非解析默认路由和旧配置兼容。
- 参数化验证 PDF、工作流、审批路由不变。
- YAML 配置解析验证多份部署配置一致。
- Source scan 验证不存在非白名单 `knowledge_celery` 显式投递。

### V2 模块验证

- 运行 Celery 配置、标题后继解析、组织同步、权限清理、推荐、热搜、投影等受影响测试。
- 执行 Ruff、格式检查、`compileall`、架构守卫和 `git diff --check`。

### V3 发布前人工验证

在带 Redis 的非生产环境分别启动：

```bash
celery -A bisheng.worker.main worker -l info -P threads -Q knowledge_celery -n knowledge@%h
celery -A bisheng.worker.main worker -l info -P threads -Q celery -n celery@%h
celery -A bisheng.worker.main worker -l info -P threads -Q knowledge_pdf_celery -n knowledge_pdf@%h
```

上传一个小型文本文件，并触发一个非解析后台任务，确认：

- 标题提取、首次解析进入 `knowledge_celery`；
- 非解析任务进入 `celery`；
- PDF Artifact 进入 `knowledge_pdf_celery`；
- 文件最终进入 `SUCCESS`；
- 不执行真实队列清空或生产数据写入。

---

## 11. Spec Discovery 确认记录

- 2026-08-05：用户确认 `knowledge_celery` 仅负责文件解析，其他任务迁移到默认队列。
- 2026-08-05：用户确认本规格，可进入任务拆解和实现。
- 解析白名单按“标题前置、首次解析、解析重试”三项定义。
- PDF Artifact 保持独立队列。
- 存量消息自然消费，不执行 purge。

### 设计校正记录

- 统一队列契约模块由初稿的 `bisheng.worker.task_queues` 调整到
  `bisheng.core.config.celery_queues`。原因是 `settings.py` 在配置模型校验阶段需要使用该纯函数，
  而导入 `bisheng.worker` 会先执行其任务注册 `__init__.py`，形成配置加载循环。
  此调整只改变代码落点，不改变任何已确认的队列行为和验收标准。

## 12. 规格自检

- `REQ-001` 至 `REQ-007` 均有可观察的验收标准。
- `AC-01` 至 `AC-07` 均有自动化验证路径；`AC-08` 明确拆分静态证据和非生产人工 Worker 冒烟。
- 文件解析白名单与当前实际任务名称一致。
- 已覆盖 Python 默认路由、YAML 自定义路由和生产代码显式 `queue` 三种入口。
- 未引入 API、数据库、依赖、Worker 并发和任务业务语义变化。
- 已明确默认 Worker 容量、滚动发布、旧配置和存量消息风险及回滚方式。
- 当前无阻塞规格缺口；实施前仍需用户确认本版 `spec.md`。
