# Verification: F084-Filelib 检索返回原文件直链

**日期**: 2026-08-21

**自动化结论**: PASS（遗留文件全量 Ruff 基线债务已单独说明）

**人工环境结论**: MANUAL_REQUIRED

## 1. 验证范围

- 原文件链接 Service：批量去重、持久化 `object_name` 优先、规范路径回退、对象缺失、7 天单次绝对签名、相对 URL 派生和非缺失异常传播。
- `/retrieve` Endpoint：只向链接 Service 传最终 Top-K 可见文件、同文件 Chunk 复用、缺失链接为空、其他响应字段和顺序兼容。
- 权限边界：F069 用户上下文覆盖检索与签名阶段；文件可见性由 `view_file` 决定；新链路不调用 `download_file`、下载额度、审计、水印、审批或分发限制。
- 安全：完整预签名 URL、签名和 Developer Token 不写入日志或文档真实示例。
- 文档：OpenAPI 汇总文档和 retrieve 专项文档同步 7 天 Bearer URL、缺失/异常行为和残余风险。
- 未连接真实 MySQL、Redis、OpenFGA、Milvus、Elasticsearch 或 MinIO。

## 2. Test-First 与回归证据

| Evidence | Code State | Command / Step | Result | Scope |
|----------|------------|----------------|--------|-------|
| E-001 | 修改前基线 | `./.venv/bin/python -m pytest test/knowledge/test_knowledge_space_chat_service_retrieve.py test/open_endpoints/test_filelib_external_user_context.py -q` | PASS：47 项，8 条既有告警，退出码 0。 | 既有 Filelib/F069/Knowledge 行为。 |
| E-002 | T001 红灯 | 新 Service 测试在实现前运行。 | RED：测试收集因 `filelib_retrieve_source_service` 不存在失败，退出码 2。 | T001 Test-First。 |
| E-003 | T002 绿灯 | `./.venv/bin/python -m pytest test/open_endpoints/test_filelib_retrieve_source_service.py -q` | PASS：5 项，退出码 0。 | V-001, V-002, V-005, V-006。 |
| E-004 | T003 红灯 | 两项 Endpoint 契约测试在接线前运行。 | RED：`retrieve_chunks()` 不接受 `source_service`，2 项按预期失败。 | T003 Test-First。 |
| E-005 | T004 绿灯 | Endpoint URL 映射、DI 与 F069 生命周期三项定向测试。 | PASS：3 项，退出码 0。 | V-003, V-004, V-005。 |
| E-006 | T004 模块检查点 | 三个目标测试文件联合回归。 | PASS：52 项，8 条既有告警，退出码 0。 | Service + Endpoint + F069 + Knowledge。 |
| E-007 | 权限拒绝边界 | `view_file` 允许/拒绝参数化回归。 | PASS：2 项，退出码 0；拒绝文件在进入链接 Service 前被过滤。 | AC-03, AC-04 / V-004。 |
| E-008 | 最终工作区 | `./.venv/bin/python -m pytest test/open_endpoints/test_filelib_retrieve_source_service.py test/open_endpoints/test_filelib_external_user_context.py test/knowledge/test_knowledge_space_chat_service_retrieve.py -q` | PASS：54 项，8 条既有告警，退出码 0。 | V-001 至 V-007 的行为回归。 |

E-008 对应主要文件 SHA-1：Service `94e3a8c0`、Endpoint `aa02840a`、Dependencies `d0f3be52`、Service Test `482ac769`、F069 Test `08f1fbe`、Knowledge Test `3a6d7748`、OpenAPI Doc `14582806`、Retrieve Doc `b5d0008b`。

## 3. 静态、架构与安全验证

| Evidence | 检查 | 状态 | 证据摘要 |
|----------|------|------|----------|
| E-009 | Ruff | PASS / BASELINE_DEBT | 新 Service 与新测试完整 `ruff format --check`、`ruff check` 通过；既有 Endpoint/测试的 `E9,F,I` 定向检查通过。`filelib.py` 全文件格式和现代类型规则、`dependencies.py` 导入排序在本变更前已有债务，未扩大为无关格式化。 |
| E-010 | Architecture Guard | PASS | 逐个检查新 Service、Dependencies、Filelib Endpoint，无 RULE-1 至 RULE-8 输出，退出码 0。 |
| E-011 | 敏感信息扫描 | PASS | 无 16 位以上真实 `X-Amz-Signature` 或 `bst_` Token；文档/测试仅包含 `REDACTED`、短占位值。 |
| E-012 | 下载控制边界扫描 | PASS | 新 Service 不引用 `get_file_download`、`download_file`、watermark 或 quota；旧门户 URL helper 和 `/knowledge-spaces?...` 来源地址已移除。 |
| E-013 | 文档与空白检查 | PASS | 两份文档字段语义、7 天、权限和错误行为一致；目标 tracked diff 与 ignored SDD/新文件均无尾随空白。 |

实际静态命令摘要：

```bash
./.venv/bin/ruff format --check \
  bisheng/open_endpoints/domain/services/filelib_retrieve_source_service.py \
  test/open_endpoints/test_filelib_retrieve_source_service.py

./.venv/bin/ruff check \
  bisheng/open_endpoints/domain/services/filelib_retrieve_source_service.py \
  test/open_endpoints/test_filelib_retrieve_source_service.py

./.venv/bin/ruff check --select E9,F \
  bisheng/open_endpoints/api/dependencies.py \
  bisheng/open_endpoints/api/endpoints/filelib.py \
  test/open_endpoints/test_filelib_external_user_context.py \
  test/knowledge/test_knowledge_space_chat_service_retrieve.py

./.venv/bin/ruff check --select I \
  bisheng/open_endpoints/api/endpoints/filelib.py \
  test/open_endpoints/test_filelib_external_user_context.py \
  test/knowledge/test_knowledge_space_chat_service_retrieve.py
```

仓库根目录逐文件执行 `scripts/arch-guard.sh`，并执行敏感签名/Token、下载链路、旧门户来源地址扫描和 `git diff --check`。

## 4. Acceptance Criteria

| AC | 状态 | 自动化证据 | 说明 |
|----|------|------------|------|
| AC-01 | PASS | E-005, E-008 | 绝对/相对字段均来自原对象预签名映射，不再返回门户页面地址。真实 GET 可访问性属于 T007。 |
| AC-02 | PASS | E-003 | 断言每个唯一文件仅调用一次 `get_share_link(clear_host=False, expire_days=7)`，相对值由同一绝对值派生。 |
| AC-03 | PASS | E-007, E-008, E-012 | 检索只调用 `view_file` 可见性检查，新签名链路无 `download_file` 或门户下载控制调用。真实权限组合属于 T007。 |
| AC-04 | PASS | E-005, E-007 | `view_file` 拒绝时 Chunk 被过滤；Endpoint 只把最终结果文件 ID 传给链接 Service。 |
| AC-05 | PASS | E-003 | 持久化 `object_name` 优先并用于对象存在性检查和签名。 |
| AC-06 | PASS | E-003 | `object_name` 为空时按既有规则回退到 `original/{file_id}.{ext}`。 |
| AC-07 | PASS | E-003, E-005, E-008 | 同文件多个 Chunk 复用同一 URL；Repository 单次批量读取、唯一文件单次检查和签名。 |
| AC-08 | PASS | E-003, E-005 | 文件记录、对象名、对象或映射缺失时保留 Chunk，两个 URL 为空。 |
| AC-09 | PASS | E-003 | `object_exists` 与签名阶段非缺失异常均原样传播，不返回部分成功。真实 MinIO 故障注入属于 T007。 |
| AC-10 | PASS | E-001, E-006, E-008 | 除 URL 值外，状态、包装、Chunk 内容、顺序、文件字段和 `total` 回归通过。 |
| AC-11 | PASS | E-003, E-011 | 正常/异常测试日志和静态扫描均无完整 URL、签名或 Token。 |
| AC-12 | PASS | E-009, E-010 | 保持 Endpoint → Service → Repository/Storage；Endpoint 无新增 ORM，未新增 DAO。 |

## 5. 人工门禁

T007 / V-008 未执行，状态为 `MANUAL_REQUIRED`。当前会话没有获授权的隔离环境、受控 Developer Token、仅有 `view_file` 的真实用户、无权用户和可安全操作的 MinIO 对象；按任务边界不得连接生产或自行修改真实权限/文件。

隔离环境需要验证：

1. `source_full_url` 无 Developer Token 可直接 GET 原文件。
2. `source_url` 拼接部署文件 Origin 后可 GET 同一对象。
3. 真实签名过期时间为 7 天，同文件多个 Chunk URL 完全相同。
4. 仅 `view_file`、无 `download_file` 的用户可获得链接；无 `view_file` 用户无 Chunk、无签名。
5. 原对象缺失返回空链接，MinIO 非缺失异常使整个请求失败。
6. 应用和调用方日志均不保留完整 URL。

若环境启用多租户，应停止发布并重新评审 F069/F084，不执行当前全局用户上下文和对象路径方案。

## 6. 已知风险与回退

- `view_file` 与 `download_file` 的区分在本接口不再保护原文件，门户额度、审计、水印和分发限制也不覆盖这些 URL；这是用户明确接受的行为。
- URL 是 7 天 Bearer 凭证，权限撤销、Token 禁用或退出登录不会使其提前失效。
- 回滚代码不会撤销已签发 URL；紧急处置只能移走/删除对象、轮换 MinIO 签名密钥或等待过期，且可能影响其他调用方。
- 应用回滚可恢复旧门户来源地址并移除链接 Service/DI；无数据库、配置或数据迁移，无需数据回滚。
