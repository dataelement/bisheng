# E2E 验证清单: F001 多租户核心基础设施

**测试环境**: http://192.168.106.114:3001 (Platform)
**前置条件**: 后端已运行 Alembic 迁移 + 重启

## 数据库验证

### AC-01: DDL 结构
- [ ] 连接 MySQL，执行 `SHOW CREATE TABLE tenant` — 确认字段/索引匹配 spec §5
- [ ] 执行 `SHOW CREATE TABLE user_tenant` — 确认 UniqueConstraint(user_id, tenant_id)
- [ ] 执行 `DESCRIBE flow` — 确认包含 `tenant_id INT NOT NULL DEFAULT 1` + `idx_flow_tenant_id`

### AC-02: 默认租户
- [ ] 执行 `SELECT * FROM tenant WHERE id=1` — 确认 tenant_code='default', status='active'
- [ ] 执行 `SELECT COUNT(*) FROM user_tenant WHERE tenant_id=1` — 应等于 `SELECT COUNT(*) FROM user`

### AC-03: 业务表 tenant_id
- [ ] 抽查 5 张表: `SELECT tenant_id FROM flow LIMIT 5` / `knowledge` / `assistant` / `chatmessage` / `role` — 全部为 1

## Platform 前端回归

### AC-07 + AC-11: 登录 + 基本功能
- [ ] 以 admin/admin123 登录 Platform — 登录成功，无异常
- [ ] 导航到"构建"页面 — 应用列表正常加载
- [ ] 导航到"知识库"页面 — 知识库列表正常加载
- [ ] 导航到"模型管理"页面 — 页面正常加载
- [ ] 创建一个测试工作流（名称: `e2e-f001-test-flow`）— 创建成功
- [ ] 删除该测试工作流 — 删除成功
- [ ] 打开浏览器 DevTools → Console — 无 JS 错误

### AC-07: WebSocket 验证
- [ ] 打开任意工作流/助手的对话页面 — WebSocket 连接成功（DevTools Network → WS 无断开）
- [ ] 发送一条消息 — 收到流式回复（确认 WS 中间件的 tenant context 不影响功能）

## Celery Worker 验证

### AC-09: 任务上下文传播
- [ ] 上传一个文件到知识库 — Celery worker 日志无 tenant_id 相关报错
- [ ] 文件处理完成（状态变为"成功"）— 确认异步任务在 tenant 上下文下正常执行

## 回归检查
- [ ] 系统管理页面正常加载
- [ ] 非 admin 用户（如有）登录后功能正常
- [ ] 所有页面无 console 错误
