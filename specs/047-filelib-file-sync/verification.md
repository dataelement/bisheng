# 验证记录 Verification: Filelib Fixed-Rule File Sync

## 验证结论

- 结论：代码级验收通过。
- 日期：`2026-07-16`
- 覆盖范围：规则、参数归一化、部门/责任人解析、分类与业务域校验、目标空间解析、权限错误映射、重复 `external_file_id` 放行、文件编码、来源元数据、延迟入队、HTTP 路由及既有开发者 Token 回归。
- 环境限制：未连接真实 MinIO、Redis 与 Celery 执行集成冒烟。

## 验收覆盖

| 需求 | 覆盖结论 | 主要证据 |
|---|---|---|
| REQ-001 固定接口规则 | 通过 | 11 条规则表与实际路由检查；分类、斜杠字面量及动态/固定业务域单测 |
| REQ-002 人员与部门归一化 | 通过 | ID 权威、名称一致性、默认调用人/主部门及元数据单测 |
| REQ-003 目标空间解析 | 通过 | 最近祖先绑定、固定公共库、固定部门直接绑定、业务域双向绑定及权限映射单测 |
| REQ-004 文件来源与文件编码 | 通过 | 相同 `external_file_id` 连续上传两次、来源元数据、原样响应及固定编码单测 |
| REQ-005 上传编排与响应 | 通过 | 编排单测、FastAPI 422/业务错误状态、默认上传入队回归及开发者 Token 回归 |

## 自动化证据

### 相关测试

命令：

```bash
cd src/backend
uv run --python=.venv/bin/python pytest -q \
  test/open_endpoints/test_filelib_sync.py \
  test/shougang_portal_config/test_portal_config_schema.py \
  test/knowledge/test_file_encoding_async_bridge.py \
  test/developer_token/test_developer_token_api.py \
  test/developer_token/test_developer_token_dependency.py \
  test/developer_token/test_developer_token_service.py
```

结果：`89 passed, 6 warnings`，退出码 `0`。警告来自 SWIG/Jieba 依赖弃用提示，与本功能无关。

### 格式与静态检查

对本功能新增文件、测试和门户 schema 执行 `ruff format --check` 与 `ruff check`。

结果：`13 files already formatted`、`All checks passed!`，退出码 `0`。

### 架构与变更完整性

- `bash scripts/arch-guard.sh`：退出码 `0`。
- `git diff --check`：退出码 `0`。
- 删除迁移前 `alembic current`：当前数据库为 `f044_route_allowlist (mergepoint)`，确认未执行 `f059`。
- 删除迁移后 `alembic heads`：仅返回 `f044_route_allowlist (head)`。
- 运行时路由检查：存在且仅列出 `/api/v2/filelib/file/sync/03,04,05,06,07,09,10,11,12,14,15` 这 11 条目标路由。

## 安全复核

- 接口沿用开发者 Token 认证，并在运行时重新检查目标知识空间根目录上传权限。
- 用户、部门以 ID 为权威；名称只能用于一致性校验，不能替代非调用人或非默认部门 ID。
- 文件名拒绝路径分隔符，文件类型、容量、重名和敏感词继续复用现有上传校验。
- ORM 查询参数化，不在日志与响应中输出 Token、文件内容或内部异常堆栈。
- `external_file_id` 不执行唯一性校验，仅与接口编号共同写入文件元数据；调用方负责处理重复业务数据。

## 手工/集成验证项

发布前应在目标集成环境执行：

1. 配置真实部门、科室知识库、分类和业务域后，对 11 个接口各执行一次上传冒烟。
2. 对同一接口连续提交相同 `external_file_id`，确认仅受现有文件内容/名称校验约束，不产生外部 ID 冲突。
3. 验证 MinIO 原文件、数据库元数据、最终编码及 Celery 解析任务状态一致。
4. 模拟 Celery 发布失败，确认已创建文件保留并按运维流程重投。

## 已知边界

- 数据库提交与 Celery 发布不是分布式事务；发布失败会保留已创建文件，需要日志告警与人工重投。
- 文件编码序号沿用现有“目标空间 + 月份”计算方式；并发写入时仍继承现有序号竞争边界。
- 相同 `external_file_id` 可以创建多份文件，系统不提供同步历史和幂等查询。
