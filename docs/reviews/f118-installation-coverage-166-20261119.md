# F118 新安装初始化修复与 166 覆盖验收

日期：2026-11-19，Asia/Taipei。发布线：`feat/3.1.0-beta1`。现场分析与初始验证基线 `39c8debc57`，发布集成基线 `95dcbb6155`；与本次修复相关的安装/覆盖/冻结解析入口在两基线上一致。

## 问题与代码修复

166 首次安装时，历史 F001 迁移先创建默认租户，API 随后因默认租户已存在而跳过原始创建事务内的空租户覆盖签发。`knowledge_unification_run` 为 0，五个模型服务的 `POST /api/v1/llm/server-removal-plan` 均返回 HTTP 200、业务码 10994；原生覆盖检查原因为 `production_coverage_certificate_missing`。

保留所有已发布 Alembic 修订。在两个 API entrypoint 的 Alembic 之前加入 `python scripts/initialize_installation.py --apply`，源码部署说明采用同一顺序。仅空 schema 可申请持久 `installation_bootstrap` 标记；建表阶段可中断重试，随后实际新建 Root、真实空集验证、原格式覆盖凭据和 completed 标记同事务提交。既有数据库直接退出该入口，不自动补签；没有新增在线业务闸门。表按模型发现规则创建，无新 Alembic head。

166 正式预检额外发现线上 Owner 会保存 `knowledge_space.target_space_id=target_id`，冻结解析器却一律拒绝非文件的空间元数据。修复解析器保留真实自指空间元数据，继续拒绝其他空间 ID 和模型携带空间元数据；没有清空或重写这 8 条有效绑定。

## 166 备份与执行

- 原镜像：`sha256:8261e3effe3b7b78051a62e4fe2e60569033ec7ad159d2bfd9081ab98fe0012e`。
- 备份目录（服务器）：`/root/bisheng-backups/f118-coverage-20261119-2327`，目录权限 0700。
- 停止前端、Celery/Linsight/Beat，暂停 API 进程；数据库快照期间暂停 OpenFGA，随后恢复 OpenFGA 供正式盘点读取。
- 同时备份 `bisheng`、`openfga` 全库及独立 schema，另备份 Compose、环境文件、配置与原挂载 entrypoint。gzip 完整性和 SHA-256 均校验成功，SQL 有完整结束标记；未宣称做过全库恢复演练。
- 数据库备份和 schema 上传到同环境 MinIO 内容寻址对象并回读核对哈希。已核对桶的匿名读取仅开放图片前缀，不开放本次 `f118/backups/` 对象。凭据、配置和 SQL 备份均未复制进仓库。
- 正式环境标识使用 CURRENT Catalog 所引用 ACTIVE authorization release 的实际值 `dev`。
- Run：`repair166-coverage-20261119`。先完成只读完整预检，再由原 `unify_knowledge_spaces` CLI 以 `--apply --operator-id 1` 执行 M2→M3→M4。结果 `complete=true,ready=true,coverage_epoch=1`，账本 `origin=migration,phase=completed`。六类来源全部完成验收，36 条引用均有效，无存量失效。
- 维护解析器先备份并核对与发布线原文件同哈希，再对后端容器应用同一窄范围修复。修复后文件 SHA-256：`fe433e61e5e85d8849779a9a351c5a6ac227aebebbb737dcf20f290b76a1d503`。此次未构建或替换发布镜像；新安装入口随后续包含该提交的后端镜像交付。
- API 重启加载正式发布的 Catalog 后，恢复前端和 worker。后端、OpenFGA 健康。

## 验收

| 对象 | 前 | 后 |
|---|---:|---:|
| 模型服务 | 5 | 5 |
| 模型 | 98 | 98 |
| 工作流 / 版本 | 1 / 2 | 1 / 2 |
| 助手 | 1 | 1 |
| 知识库 / 文件 | 5 / 58 | 5 / 58 |
| 引用来源集合 / 明细 | 25 / 36 | 25 / 36 |
| 覆盖验收账本 | 0 | 1（completed） |

通过当前真实管理员会话验证 API，会话不输出、不落盘。经临时 SSH 转发运行本地 pytest E2E：1 passed，完整比较预检前后的模型清单。另经截图相同的 `192.168.106.166:3001` 前端代理逐个请求五个服务：HTTP 与业务码全部 200，`check_complete=true`，均生成确认计划。服务 1、4 无引用，2、3、5 有实际引用影响。没有执行任何模型删除。

独立 MySQL 数据库实际完成新安装初始化→全部历史 Alembic→API `_init_default_tenant`→全局 Coverage，结果 ready=true、epoch=1；再次初始化为 already_initialized。测试逐 SQL 拦截任何非独立测试库连接。独立测试库在验收后清理。

初始基线上，安装/启动、迁移预检/删除事实、迁移 CLI、单 head 和在线建表的 67 项回归通过，来源盘点、正式覆盖和完整回填应用的 53 项回归通过。基于最新发布线重新验证的 127 项相关回归通过，另补充仅部分表创建后中断的真实续办用例通过，共覆盖 128 个相关用例。Ruff、架构守卫、两个 shell 入口语法及 diff 检查通过。DM8 未在本机实测，继续由中央回归验证；本次没有修改历史迁移或引入 MySQL 专用业务 SQL。

仅包含计数、哈希与预检摘要的可入库证据见 [evidence](./evidence/f118-installation-coverage-166-20261119/)。完整备份、执行日志、原/修复解析器保留在服务器备份目录。

## Code Review Report

范围：首次安装入口、持久来源证明、同事务签发、正常空间绑定盘点兼容、部署文档及针对性回归。按 `sdd-code-review` 七维自查，原 F118 AC-89 与空安装覆盖合同保持不变。

| Dimension | High | Medium | Low | Status |
|---|---:|---:|---:|---|
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 0 | 0 | PASS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync | 0 | 0 | 0 | PASS |

无 HIGH/MEDIUM findings。并发竞争不能重复签发：唯一安装标记及行锁串行化实际租户事务；并发初始 DDL 冲突会失败退出并由部署重试。原 Root/凭据失败同事务回滚，pending DDL 来源证明保留。既有 Root 无凭据不自动回填，错误空间元数据仍阻断。**Overall: PASS**。
