# 设计说明 Design: Filelib Fixed-Rule File Sync

## 设计目标 Goals
- 在不复制 11 套业务逻辑的前提下提供 11 个字面量路由。
- 保持 `Router → Endpoint → Service → Repository → DB` 分层。
- 复用知识空间上传的权限、容量、原文件存储、逻辑文档和解析流程。
- 在 Celery 入队前完成分类、业务域、来源元数据和文件编码。

## 非目标 Non-goals
- 不改变全局 HTTP 异常处理器。
- 不为普通上传强制同步编码。
- 不提供消息队列投递补偿任务。
- 不基于 `external_file_id` 去重、预占或保存独立同步历史。

## 组件设计

### API 层
`open_endpoints/api/endpoints/filelib_sync.py` 注册 11 个明确路径，使用同一私有处理函数。`file`、`params` 声明为可选并在端点内校验，以便返回实际 HTTP 422；领域错误由端点转换为带实际 HTTP 状态的 `ORJSONResponse`。

### Schema 与规则表
`open_endpoints/domain/schemas/filelib_sync.py` 定义 params、响应和规则数据类。规则表仅包含文档已确认的分类名称、业务域策略和目标策略。

### Service
`FilelibSyncService` 按以下顺序编排：
1. 校验 params、责任人和主责单位。
2. 读取门户配置，解析分类和业务域编码。
3. 解析并验证目标空间、业务域绑定和上传权限。
4. 保存临时上传对象，调用 `KnowledgeSpaceService.add_file(..., enqueue_processing=False)`。
5. 将 `external_file_id`、接口编号和规范化身份写入元数据，并同步生成文件编码。
6. 提交解析任务并返回排队状态；入队前失败时清理已创建文件和临时对象。

### Repository
`FilelibSyncRepository` 接口与实现以现有 `KnowledgeFile` 为基础实体，负责人、部门、部门绑定、固定空间和文件更新所需查询。Service 不直接构造 ORM 查询。

### 数据模型
不新增同步记录表，也不修改现有知识文件表结构。`external_file_id` 与 `filelib_sync_endpoint` 作为来源信息写入 `KnowledgeFile.user_metadata`，不建立唯一约束或查询索引。

### 编码
在现有 `FileEncodingTransformer` 中暴露固定编码生成入口，沿用其公司前缀、按目标空间和创建月份计算序号、组成编码的实现。解析阶段发现 `file_encoding` 已存在时保持幂等跳过分类。

### 知识上传兼容
`KnowledgeSpaceService.add_file` 新增默认值为 `True` 的 `enqueue_processing` 参数；默认调用保持原行为。新增显式入队方法供同步接口在元数据和编码写入后调用。

## 错误处理
| HTTP | 场景 |
|---:|---|
| 400 | params JSON、必填字段、ID/名称不一致、非法文件名 |
| 403 | 目标知识空间上传权限不足 |
| 404 | 用户、部门、主部门、配置、分类、业务域、目标空间不存在 |
| 409 | 现有知识上传校验判定文件内容或名称重复 |
| 422 | multipart 缺少 `file` 或 `params` |

业务错误使用 `common/errcode/filelib_sync.py` 中的 199xx 代码承载稳定消息；端点返回时 HTTP 状态与响应体 `status_code` 保持一致。

## 安全设计
- 仅接受开发者 Token 认证用户。
- 每次请求重新检查目标空间根目录 `upload_file` 权限。
- ID 为权威，防止调用方通过伪造名称绕过关联。
- 文件名拒绝路径分隔与空值；实际文件能力、容量、敏感词由现有上传服务校验。
- 不在日志或错误响应中输出 Token、文件内容或内部异常堆栈。

## 可靠性与回滚
- 相同 `external_file_id` 的重复或并发请求会各自执行上传；系统不承诺幂等，调用方负责避免业务重复。
- 数据库提交与 Celery 发布无法原子化；投递失败会传播 500 并保留已创建文件，运维可依据日志重投。这是当前系统既有边界。
- 本次删除尚未发布的同步记录模型和迁移，不产生数据库结构变更；如果迁移已在任何环境执行，必须停止直接删除并改用前向迁移。

## 文件结构计划
- `specs/047-filelib-file-sync/*`
- `src/backend/bisheng/open_endpoints/api/endpoints/filelib_sync.py`
- `src/backend/bisheng/open_endpoints/domain/{repositories,schemas,services}/...`
- `src/backend/bisheng/common/errcode/filelib_sync.py`
- `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`
- `src/backend/bisheng/knowledge/rag/pipeline/transformer/file_encoding.py`
- `src/backend/bisheng/shougang_portal_config/domain/schemas/portal_config_schema.py`
- `src/backend/test/open_endpoints/test_filelib_sync.py`

## 可追踪性 Traceability
| Requirement | Components |
|---|---|
| REQ-001 | 规则表、门户配置解析、固定路由 |
| REQ-002 | params schema、人员部门 repository/service、metadata |
| REQ-003 | 目标解析 repository/service、PermissionService |
| REQ-004 | 来源 metadata、响应 schema、固定编码入口 |
| REQ-005 | endpoint、KnowledgeSpaceService 延迟入队、测试 |
