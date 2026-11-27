# L1 任务审查检查清单

本清单定义了 `/task-review` 在每个任务完成后执行的精简检查项。
L1 聚焦约定合规和架构红线，不检查边界条件、权限、并发、测试覆盖（留给 L2）。

## 检查项

| # | 检查项 | 适用文件 | 严重度 | 检查方法 |
|---|--------|---------|--------|---------|
| 1 | 架构分层 | 后端 `*.py` | HIGH | 按 [C1](../../../../docs/constitution.md#c1-ddd-layered-call-chain) 和[后端规范](../../../../src/backend/AGENTS.md) 核查改动的调用链、导入方向和模块位置。另查 Service 是否引入 FastAPI 对象，以及 Worker 的业务调用是否经 Domain Service |
| 2 | 命名规范 | 全部 | MEDIUM | DAO 方法：同步 `get_xxx`/`create_xxx`/`update_xxx`/`delete_xxx`，异步 `aget_xxx`/`acreate_xxx`/`aupdate_xxx`/`adelete_xxx`；DAO 为 `@classmethod`；Service 类名 `{Module}{Function}Service`；错误码类名 `{Module}{Error}Error`，Code 遵循 MMMEE；前端页面 PascalCase，store 文件 camelCase+Store，API 函数 camelCase；i18n key 小写+点分隔 |
| 3 | 序列化约定 | 后端 `*.py` | HIGH | ORM 继承 `SQLModelSerializable`；API 响应用 `UnifiedResponseModel`（`resp_200`/`resp_500`/`ErrorClass.return_resp`）；分页用 `PageData[T]`（新代码）；枚举序列化为 `.value`；SSE 用 `to_sse_event()`；WS 关闭用 `websocket_close_message()` |
| 4 | 数据库约定 | 后端 models/migration `*.py` 及访问租户数据的查询、写入代码 | HIGH | 新增租户所属表必须含 `tenant_id`（`index=True`）；全局表按实际数据归属建模；新表必须含 `create_time`/`update_time`；按 [C3](../../../../docs/constitution.md#c3-multi-tenant-data-isolation) 核查 ORM 查询、批量写入和原生 SQL 的租户范围；新模块 DAO 放 `{module}/domain/models/` 而非 `database/models/`；使用 `get_sync_db_session()`/`get_async_db_session()` |
| 5 | 前端约定 | `*.tsx`/`*.ts` | MEDIUM | 根据改动所属应用，按[共享前端规范](../../../../src/frontend/AGENTS.md)及 [Platform](../../../../src/frontend/platform/AGENTS.md) 或 [Client](../../../../src/frontend/client/AGENTS.md) 规范核查状态、请求和国际化。新增路由核对应用的注册入口和 base path |
| 6 | 信息泄漏 | 全部 | HIGH | 无硬编码密码/密钥/token（`password = "xxx"` 等）；错误响应不暴露堆栈/SQL（用 BaseErrorCode）；日志中敏感字段脱敏；API 只返回业务所需且调用方有权访问的租户信息（含 `tenant_id`）；前端不硬编码后端 IP。排除：测试 fixtures、config.yaml.example |
| 7 | 设计同步 | 全部 | MEDIUM | **触发条件**：本任务修改了 service / endpoint / store / API 契约 / 数据模型 / 渲染器 / 任何 design.md §4.3 "关键模块职责" 表里列出的文件。**检查**：(a) design.md 修订历史是否反映了本任务的改动（或本任务后会一并补）；(b) 改动是否触及 §3 决策（替换/新增）、§4 数据流或字段约定、§5 已知坑（新增反直觉事实）、§6 对外契约或依赖 —— 若是，必须**同步更新对应章节**；(c) 仅本地小修小补（重构、改文案、调样式、bugfix 不涉及对外行为）→ 标 PASS 即可。**判定**：触发但 design.md 未同步 → FAIL（MEDIUM）；触发且已同步 / 未触发 → PASS |

## 差异化处理规则

### 测试任务
- 仅检查：#2 命名规范 + #5 前端约定中的 i18n + AC 标注格式（`覆盖 AC: AC-NN`）
- 跳过：#1 架构分层、#3 序列化、#4 数据库、#7 设计同步

### 实现任务
- 完整执行 #1~#7
- 额外验证：配对的测试任务是否已完成（tasks.md 中已打勾）

### 基础设施任务（ORM 模型、错误码、配置）
- 检查：#1 架构分层、#4 数据库约定、#6 信息泄漏、#7 设计同步（新表/新错误码很可能影响 design.md §4.2 字段约定 + §6 契约）
- 跳过：#5 前端约定

### Worker 任务
- 检查：#1 架构分层、#4 数据库约定、#6 信息泄漏、#7 设计同步
- 额外检查：tenant_id 是否通过 Celery headers 传递并在 Worker 侧恢复 ContextVar

## 判定规则

| 结果 | 条件 | 动作 |
|------|------|------|
| **PASS** | 全部通过 | 打勾，继续下一任务 |
| **PASS_WITH_NOTES** | 仅 MEDIUM 级信息性提醒 | 打勾 + 记录偏差，继续 |
| **NEEDS_FIX** | 任何 HIGH 违规 | 修复 → 重审（最多 1 轮） |
