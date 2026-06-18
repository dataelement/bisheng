# L1 任务审查检查清单

本清单定义了 `/task-review` 在每个任务完成后执行的精简检查项。
L1 聚焦约定合规和架构红线，不检查边界条件、权限、并发、测试覆盖（留给 L2）。

## 检查项

| # | 检查项 | 适用文件 | 严重度 | 检查方法 |
|---|--------|---------|--------|---------|
| 1 | 架构分层 | 后端 `*.py` | HIGH | Endpoint 不直接实例化 DAO 做复杂业务（应通过 Service）；Service 不导入 FastAPI 对象（Request/Response/Depends/APIRouter）；`domain/models/` 不得 `from bisheng.*.domain.services`；`common/` 和 `core/` 不得导入领域模块；新代码不放 `api/services/`（旧服务层），应放 `{module}/domain/services/`；Worker 只导入 Domain Services 不导入 Endpoint |
| 2 | 命名规范 | 全部 | MEDIUM | DAO 方法：同步 `get_xxx`/`create_xxx`/`update_xxx`/`delete_xxx`，异步 `aget_xxx`/`acreate_xxx`/`aupdate_xxx`/`adelete_xxx`；DAO 为 `@classmethod`；Service 类名 `{Module}{Function}Service`；错误码类名 `{Module}{Error}Error`，Code 遵循 MMMEE；前端页面 PascalCase，store 文件 camelCase+Store，API 函数 camelCase；i18n key 小写+点分隔 |
| 3 | 序列化约定 | 后端 `*.py` | HIGH | ORM 继承 `SQLModelSerializable`；API 响应用 `UnifiedResponseModel`（`resp_200`/`resp_500`/`ErrorClass.return_resp`）；分页用 `PageData[T]`（新代码）；枚举序列化为 `.value`；SSE 用 `to_sse_event()`；WS 关闭用 `websocket_close_message()` |
| 4 | 数据库约定 | 后端 models/migration `*.py` | HIGH | 新表必须含 `tenant_id`（`index=True`）；必须含 `create_time`/`update_time`；禁止手动 `WHERE tenant_id=`（SQLAlchemy event 自动注入）；禁止 Service 层直接写 SQL（用 DAO classmethod）；新模块 DAO 放 `{module}/domain/models/` 而非 `database/models/`；使用 `get_sync_db_session()`/`get_async_db_session()` |
| 5 | 前端约定 | `*.tsx`/`*.ts` | MEDIUM | Platform: 全局状态用 Zustand store（`src/store/`），API 通过 `controllers/API/` 封装，用户可见文字走 `t('key')` i18n，新路由在 `src/routes/` 注册。Client: API 通过 `src/api/` 封装，store 用 Zustand（`src/store/`），路由基础路径 `/workspace` |
| 6 | 信息泄漏 | 全部 | HIGH | 无硬编码密码/密钥/token（`password = "xxx"` 等）；错误响应不暴露堆栈/SQL（用 BaseErrorCode）；日志中敏感字段脱敏；API 不返回 tenant_id 到前端；前端不硬编码后端 IP。排除：测试 fixtures、config.yaml.example |

## 差异化处理规则

### 测试任务
- 仅检查：#2 命名规范 + #5 前端约定中的 i18n + AC 标注格式（`覆盖 AC: AC-NN`）
- 跳过：#1 架构分层、#3 序列化、#4 数据库

### 实现任务
- 完整执行 #1~#6
- 额外验证：配对的测试任务是否已完成（tasks.md 中已打勾）

### 基础设施任务（ORM 模型、错误码、配置）
- 检查：#1 架构分层、#4 数据库约定、#6 信息泄漏
- 跳过：#5 前端约定

### Worker 任务
- 检查：#1 架构分层、#4 数据库约定、#6 信息泄漏
- 额外检查：tenant_id 是否通过 Celery headers 传递并在 Worker 侧恢复 ContextVar

## 判定规则

| 结果 | 条件 | 动作 |
|------|------|------|
| **PASS** | 全部通过 | 打勾，继续下一任务 |
| **PASS_WITH_NOTES** | 仅 MEDIUM 级信息性提醒 | 打勾 + 记录偏差，继续 |
| **NEEDS_FIX** | 任何 HIGH 违规 | 修复 → 重审（最多 1 轮） |
