# F112 验证记录

- Date: 2026-10-22（Asia/Shanghai）
- Status: LOCAL_VERIFIED_WITH_BASELINE_FAILURE
- 结论：14 个 Filelib 文件接口已收口至 SPACE；本次新增/更新的用例均通过。相关共享回归存在 1 个已复现的既有失败，不能声称全部相关测试通过。
- 未部署、未迁移真实数据、未删除旧物理存储、未提交或推送。
- 解释器：`src/backend/.venv/bin/python`；测试工作目录：`src/backend`。
- 基线：`938634642`，保留当前 `codex/mcp-external-user-identity` 上原有工作区。
- 20 个涉及 Python 文件（含测试）的 SHA-256 清单：`/tmp/f112-final-code-manifest.json`；清单摘要 `ac501ee71b6a45729c8302fd35c538fd5a637b2b67cad58493fd0389d46d0005`。

## 实际测试证据

所有 pytest 命令均使用 `.venv/bin/python -m pytest <下列文件> -q --disable-warnings`。
按表分别启动进程，避免现有全局测试替身跨模块污染；同一代码状态的成功证据复用，不额外重复整套测试。

| Evidence | 文件 / 范围 | 结果 | 日志 |
|---|---|---|---|
| E-001 | 修改前 `test/knowledge/test_knowledge_space_chat_service_retrieve.py`；原地址与检索 service | 49 passed；15 passed | `/tmp/f112-baseline-query.log`、`/tmp/f112-baseline-source.log` |
| E-002 | `test/open_endpoints/test_filelib_shared_{content,commands,repository,api,e2e}.py`（命令中逐个列出 5 个文件） | 43 passed，exit 0 | `/tmp/f112-final-feature.log` |
| E-003 | `test/knowledge/test_knowledge_space_chat_service_retrieve.py` | 48 passed，exit 0 | `/tmp/f112-final-query.log` |
| E-004 | `test/open_endpoints/test_filelib_external_user_context.py`、`test_filelib_knowledge_list.py`、`test_filelib_file_source_url.py`、`test_filelib_retrieve_service.py`、`test_filelib_sync_factory.py` | 51 passed，exit 0 | `/tmp/f112-final-compat.log` |
| E-005 | `test/knowledge/test_shared_space_direct_ingestion.py` | 12 passed，exit 0 | `/tmp/f112-regression-direct.log` |
| E-006 | `test/knowledge/test_distribution_container_delete.py`、`test_distribution_container_cleanup.py` | 12 passed，exit 0 | `/tmp/f112-regression-delete.log` |
| E-007 | `test/knowledge/test_knowledge_document_projection_service.py`、`test/knowledge/fulltext/test_fulltext_parse_lifecycle.py` | 19 passed，exit 0 | `/tmp/f112-regression-projection.log` |
| E-008 | `test/knowledge/test_shared_only_space_storage.py` | 26 passed，1 failed，exit 1 | `/tmp/f112-regression-shared-only.log` |

最终相关范围合计：**211 passed，1 个既有失败**。E-001 是修改前基线，不计入最终通过数量。
旧查询测试中一个整体模拟 `_load_file_content_from_es` 的用例已由实际共享读取回归替代，故该文件从 49 项变为 48 项；独立回归增加在 E-002 中。

分析阶段已直接执行旧回退函数和实际保护逻辑，复现 SPACE 在创建 ES 客户端前抛出 `routing_not_configured`，ES 创建次数为 0。
新测试初次因新模块/DTO 尚未实现而无法收集；这种收集失败不作为行为验证通过或原问题行为红灯证据。

## 既有失败与基线对照

失败：`test_cross_space_restore_requeues_shared_membership_after_commit`。

- 位置：未修改的 `knowledge_recycle_service.py:903`。
- 错误：测试夹具的 `SimpleNamespace` 没有 `document_id`，触发 `AttributeError`。
- 对照：通过临时 import loader 从 `git show HEAD:<path>` 重新加载本次涉及的六个既有生产模块原始内容，执行相同单用例，仍出现完全相同错误，结果 `1 failed in 0.76s`。
- 六个模块：`common/errcode/knowledge.py`、`knowledge_service.py`、Filelib `dependencies.py`、`filelib.py`、`schemas/filelib.py`、`filelib_file_source_service.py`。
- 对照不覆盖完整仓库的其他工作；它证明替换回本次相关模块原始内容后该夹具失败依旧存在。失败测试和回收服务均未修改。

## 受控 HTTP 端到端与边界

E-002 的端到端用例通过真实 HTTP 路由、Filelib 命令/查询/内容服务、SQLite ORM、文档入口 resolver、共享直写编排、共享仓储查询和原链接服务完成：

`chunks_string → file/list → file/detail → retrieve → file/source_url → clear 引用空间 → 再读管理空间正文`。

ES、MinIO、embedding 和 writer 后端受控；共享 prepare/finalize 与解析状态持久化在此用例中隔离，
其领域规则由 E-005/E-006/E-007 的已有回归补充。检索召回在 E2E 中使用共享仓储受控适配器，
真实检索编排的权限、合并与降级由 E-003/E-004 覆盖。不得把本用例视为真实服务或生产环境验收。

已验证的独立风险包括：文本产物缺失后的共享分块读取、完整多页正文、发布/分享入口实际内容身份、历史版本拒绝、
投影/内容缺失明确失败、后端不可用、读取期间版本变化、独立快照复核、冻结时读取与写入边界、
上传前拒绝、非 SPACE/跨租户/已回收原链接拒绝、跨空间批量拒绝、清空后其他空间有效内容保留、
字符串输入 metadata 不被修改以及 writer 更新的代次不被解析结果覆盖。

## 验收映射

| Acceptance | 本地状态 | Evidence |
|---|---|---|
| AC-01 默认 SPACE / 团队库创建与目标校验 | PASS | E-002, E-004, E-008 的通过用例 |
| AC-02 旧类型、别名冲突、混合目标拒绝 | PASS | E-002, E-003, E-004 |
| AC-03 文本与完整共享正文 | PASS | E-002 |
| AC-04 内容身份、摘要和版本隔离 | PASS | E-002, E-003 |
| AC-05 共享直写及失败状态 | PASS | E-002, E-005, E-007 |
| AC-06 文件与批量入口删除 | PASS | E-002, E-006 |
| AC-07 清空 / 退役保护共享内容 | PASS（本地） | E-002, E-006；真实异步任务单列 |
| AC-08 检索及原文件签名 | PASS | E-002, E-003, E-004 |
| AC-09 路由 / 后端 / 投影失败 | PASS | E-002, E-008 的通过用例 |
| AC-10 权限、身份、租户与冻结边界 | PASS（本地） | E-002, E-003, E-004；真实 OpenFGA 单列 |
| AC-11 URL、成功字段及分页兼容 | PASS | E-002, E-003, E-004 |
| AC-12 QA 与统计下载原样保留 | PASS | E-002 的 7 个函数 AST 校验；另逐函数恢复并核对原始源码 |

## 静态检查与工作区保护

- 5 个新增生产文件与 5 个新增测试文件：完整 `ruff check`，`All checks passed`。
- 已修改旧文件：定向 Ruff `E9,F63,F7,F82,F401,F841,I`；新增问题 0，3 个既有问题与 HEAD 内容对照一致，记录 `/tmp/f112-static-results.json`；不清理其既有类型注解等风格问题。
- 20 个涉及 Python 文件语法编译通过。
- `git diff --check`：exit 0。
- `bash scripts/arch-guard.sh <11 个涉及生产文件>`：exit 0，未输出违规。
- 初始已有未提交文件的 SHA-256 校验全部一致，保护记录 `/tmp/f112-protected-baseline.json`。
- 7 个排除函数源码从初始干净 HEAD 原样恢复，AST 校验一致。没有改写 QA 业务或删除旧适配器保护。
- 执行过程中其他会话新增的聊天反馈/审计/邮件/前端修改均未触碰；不纳入本次测试和审查结论。

## 任务与特性审查

- T001–T013 按执行批次核对文件边界、依赖、配对测试和验收证据，无新增未完成的本地实现任务。
- L1：端点委托服务、SQL 留在 Repository、统一响应与业务错误、租户事件/共享路由保留；架构守卫通过。
- L2 增量审查范围为 F112 自身修改和新增文件，基于当前 HEAD 对照；不把原有 MCP 和并行其他工作纳入本次审查。
- 检查边界输入、权限/认证、并发状态、信息泄漏、测试有效性和代码风格。本地未发现新增阻塞问题。
- 审查中补齐了已回收原链接拒绝、独立会话版本复核、解析最终状态锁定/刷新及相应回归。

## MANUAL_REQUIRED

本地未连接真实 ES/Milvus/MinIO、MySQL/DM8、OpenFGA 和 Celery Worker；本次不新增依赖、不开生产写入测试。

发布前在已初始化共享路由和已完成历史迁移的专用测试租户中，使用专用前缀测试数据执行：

1. 以合法 default_operator 创建团队库；检查 scope、共享目标/模型及 owner 权限。
2. 三种入库接口分别上传，等待 Worker/投影收敛，再检查详情、摘要、检索及原链接。
3. 管理入口发布/分享到第二空间；切换主版本、重解析，与详情读取并发，确认无旧版本/新版本混合。
4. 不同业务用户及无权用户检查 `external_id` 与文件权限；维持 F069 无租户部署限制。
5. 删除发布/分享入口、清空第二空间、删库/退役；等待既有后台任务，检查有效入口正文仍可读、共享目标未 drop、原对象未误删。
6. 在 Linux DM8 和 MySQL 上验证 ORM 查询、最终状态事务、只读快照、回收/退役路径；清理仅限本测试创建的数据。

代码回退不撤销已发生的共享写入或删除；数据恢复使用现有回收/恢复能力，不能靠旧开关切回逐库存储。
