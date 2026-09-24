# Verification: F069-Filelib OpenAPI 外部用户权限上下文

**日期**: 2026-08-02  
**分支**: `feat/2.5.0-sg`  
**自动化结论**: PASS（存在一项既有文件格式基线说明）  
**人工环境结论**: MANUAL_REQUIRED

## 1. 验证范围

- User Repository：全局精确匹配全部 `delete=0` 候选，不按 `source` 或租户取首条。
- Filelib 用户上下文：缺省回退、完整目标身份、全局超级管理员标记、失败关闭、全局查询与业务上下文、异常/取消复位。
- 四接口：三个 GET Query 与 `/retrieve` Body 暴露可选 `external_id`；Token 错误优先；空白/超长 `422`；目标用户传播到 Knowledge 业务。
- 回归：Developer Token 认证依赖、知识列表/文件列表/详情/Chunk 检索既有测试。
- 静态：Ruff、架构守卫、敏感信息扫描、文档契约和 `git diff --check`。
- 未连接真实 MySQL、Redis、OpenFGA、Milvus、Elasticsearch 或 MinIO。

## 2. Test-First 证据

| 证据 | 命令/阶段 | 结果 |
|------|-----------|------|
| E-001 | Repository 测试在接口实现前运行 | RED：2 项因 `list_active_by_external_id` 不存在失败。 |
| E-002 | `pytest test/user/test_user_repository_external_id.py test/user/test_user_primary_department_contract.py -q` | PASS：7 项。 |
| E-003 | Filelib 用户上下文测试在 Service 实现前运行 | RED：测试收集因目标 Service 模块不存在失败。 |
| E-004 | `pytest test/open_endpoints/test_filelib_external_user_context.py -q`（上下文批次） | PASS：7 项。 |
| E-005 | Endpoint 契约测试在接线前运行 | RED：测试收集因新 Service builder 不存在失败。 |
| E-006 | 增加全局候选查询上下文断言 | RED：2 项证明原实现查询时仍保留 Token 租户上下文；修正后转绿。 |
| E-007 | 最终联合定向回归 | PASS：85 项，8 条既有第三方/模型告警，退出码 0。 |

最终联合回归命令（从 `src/backend/` 执行）：

```bash
./.venv/bin/python -m pytest \
  test/user/test_user_repository_external_id.py \
  test/user/test_user_primary_department_contract.py \
  test/open_endpoints/test_filelib_external_user_context.py \
  test/knowledge/test_knowledge_space_chat_service_retrieve.py \
  test/developer_token/test_developer_token_dependency.py -q
```

## 3. 静态与安全验证

| 检查 | 状态 | 证据摘要 |
|------|------|----------|
| Ruff format（除遗留 Endpoint 文件） | PASS | 8 个新增/局部文件 `ruff format --check` 通过。 |
| Ruff check（除遗留 Endpoint 文件） | PASS | 8 个新增/局部文件全规则检查通过。 |
| `filelib.py` 定向安全 lint | PASS | `--select E9,F63,F7,F82,F401,I001` 通过，覆盖语法、未定义名和导入错误。 |
| `filelib.py` 全文件 format/check | BASELINE_DEBT | 该 700+ 行遗留文件在本变更前即未统一 Ruff 格式；全文件格式化会产生数百行无关 diff，因此未扩大范围。全规则检查报告 47 项既有 `Optional/List` 现代化及旧字符串格式问题；本次新增导入与代码的定向 lint 通过。 |
| Architecture Guard | PASS | 逐个检查 9 个 F069 Python 文件，无 RULE-1 至 RULE-8 输出。 |
| 敏感信息扫描 | PASS | 排除 `tasks.md` 中扫描命令字面量后，无 `bst_` 明文 Token 或异常 Header 示例。 |
| OpenAPI 参数一致性 | PASS | 自动测试确认三个 GET 的 Query 和 `/retrieve` JSON Schema 均包含 `external_id`。 |
| `git diff --check` | PASS | 无空白错误。 |
| 范围检查 | PASS | 未新增 migration、依赖、配置、前端或其他 Filelib 路由改动；保留任务前已有工作区修改。 |

## 4. Acceptance Criteria

| AC | 状态 | 自动化证据 | 说明 |
|----|------|------------|------|
| AC-01 | PASS | E-007 | GET 与 POST 均验证无效 Token 优先于无效 `external_id`，且未查询用户。 |
| AC-02 | PASS | E-007 | OpenAPI Schema 与 Pydantic/Query 校验覆盖四接口合法参数。 |
| AC-03 | PASS | E-004, E-007 | 缺失参数原样复用 Token 用户，不改变上下文。 |
| AC-04 | PASS | E-004, E-007 | 唯一普通用户构造完整 `UserPayload`，Endpoint/检索 Service 使用目标用户。 |
| AC-05 | PASS | E-004, E-007 | `init_login_user` 产生的 `is_global_super=true` 被完整保留并传播；真实权限数据验证仍属 T009。 |
| AC-06 | PASS | E-004, E-007 | 不存在/禁用等价空候选与重复候选返回同一 HTTP `403`。 |
| AC-07 | PASS | E-007 | 空、纯空白和超过 255 字符均 `422`，不查用户。 |
| AC-08 | PASS | E-007 | 四个入口继续调用既有 Knowledge 权限检查，权限主体为目标用户；真实 OpenFGA 元组组合仍属 T009。 |
| AC-09 | PASS | E-004, E-006, E-007 | 正常、拒绝、异常与取消路径均复位可见租户和 bypass ContextVar；Worker 连续真实请求仍属 T009。 |
| AC-10 | PASS | E-007 | 既有知识列表、文件列表、详情与检索 fixture 回归通过。 |
| AC-11 | PASS | E-004 + 安全扫描 | `403` 不回显标识或匹配原因，日志仅记录 Token ID 和抽象原因，不记录原始标识/Token。 |
| AC-12 | PASS | 架构守卫 + diff | 保持 Endpoint → Service → Repository；未新增 DAO，Endpoint 不查询 User ORM。 |

## 5. 人工门禁

T009 未执行，状态为 `MANUAL_REQUIRED`。原因是当前会话没有获授权的隔离环境、受控 Token、真实普通/无权/重复用户及 OpenFGA 数据；按任务边界不得连接生产或自行修改真实身份与权限数据。

人工验证前必须先确认 `multi_tenant.enabled=false`。若环境启用多租户，应停止发布并更新 F069 规格，不能执行当前的全局数据作用域方案。

## 6. 已知风险与回退

- 显式 `external_id` 会采用目标用户完整权限，不与 Token 用户权限取交集；这是已确认的高权限委托语义。
- 全局候选查询与四接口业务期间会临时绕过租户 SQL 过滤，仅允许在无租户部署使用；上下文已通过 `finally` 和回归测试复位。
- 回退时应同步撤销四接口接线、`RetrieveReq.external_id`、用户上下文 Service/Repository 方法以及同版本公开文档；无需数据库或配置回滚。
