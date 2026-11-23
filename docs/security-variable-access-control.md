# GHSA-w3vf-p29c-h5p3 修复记录

## 已确认范围

本次采用用户确认的安全收口：四个接口统一登录；GET 校验 workflow/visible；所有写操作校验 workflow/edit；仅接受真实 WORKFLOW 资源；旧数组协议空列表明确拒绝。不新增 use/分享授权旁路，不迁移或清理存量数据。

## 实现

- 路由：`src/backend/bisheng/api/v1/variable.py`，保留四个 URL，登录依赖由整个子路由强制执行。
- 输入：`src/backend/bisheng/variable/domain/schemas.py`，不允许 tenant_id、时间戳等持久化字段；版本和变量 ID 为正数。
- 服务：`src/backend/bisheng/variable/domain/services/variable_service.py`，校验真实流程/版本/租户/软删除/类型；更新删除以变量真实归属授权，不允许迁移节点或父资源。
- 仓储：`src/backend/bisheng/variable/domain/repositories/variable_repository.py`，真实 ORM 实体删除代替无租户约束的 bulk DELETE；批量替换限目标版本，删除插入同一事务。
- 写入先完成异步授权，再按 Flow → Version → Variable 顺序锁定并重验。锁定后不再 await，避免同步锁等待与异步授权形成事件循环阻塞。重复检查及替换集合也使用 FOR UPDATE current read 和 populate_existing，避免 MySQL REPEATABLE READ 继续读取授权前快照。
- 在线当前版本禁止编辑，非当前版本仍可编辑；读取和写入均限定当前租户，暂不增加管理租户切换或跨租户分享能力。
- 返回数据不含 tenant_id；原有变量表单业务字段保留。

## 回归证据

运行目录：`src/backend`。环境：现有 `.venv/bin/python`，Python 3.14.0。

修复前：

- `.venv/bin/python -m pytest test/variable/test_variable_auth.py -q`：8 failed，四个路由缺登录依赖、HTTP 请求未执行认证。
- `.venv/bin/python -m pytest test/variable/test_variable_security.py -q`：19 failed，包括无授权操作、跨租户删除、跨版本删除、失败无法回滚等。
- 审查发现锁后 await 风险后，先增加锁顺序回归并确认 3 failed，再调整锁/授权顺序。

修复后：

```bash
.venv/bin/python -m pytest test/variable test/api/test_route_login_guard.py test/workflow/test_flow_dao_tenant_isolation.py -q --tb=short
```

结果：51 passed，20 条环境/第三方弃用警告。

测试包含真实 FastAPI 路由、SQLite ORM 事务和真实租户过滤事件；身份和权限外部决策在 focused 测试中被替换。覆盖匿名依赖拒绝、无流程权限、跨租户边界、真实归属、防伪造 tenant_id、空/混合批次、原子回滚、版本隔离、合法增改删、线上状态、软删除、节点归属、同名及缺租户上下文。

Ruff 检查、格式化及逐文件 arch-guard 检查已执行。

## 发布前仍需验证

- 项目规定的 Python 3.11 环境；本地仅有可复用的 Python 3.14 测试环境，不能把当前通过结果视为 3.11 验证。
- MySQL/DM8 真实并发、行锁及事务语义；SQLite 不提供等价的 FOR UPDATE 证明。
- 使用非管理员账号、真实身份依赖和 OpenFGA/Catalog 的部署级端到端验证；focused 测试没有证明真实凭证签发及权限基础设施可用。
- 当前租户严格读取、仅 WORKFLOW、禁止在线当前版本写入、拒绝额外请求字段属于明确收口，部署前核查旧调用方兼容性。
- 未运行全量后端测试或覆盖率测量，未声称生产部署验收完成。

无需数据库 schema 迁移。补丁不轮换历史可能泄露的密钥；若部署曾暴露，应另外检查访问记录、受损数据并轮换凭据。
