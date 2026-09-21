# Verification: F071 知识空间历史对话按空间保留

**日期**：2026-09-18
**分支 / worktree**：`feat/923-3.0.0-beta1` / `.worktrees/feat-923-3.0.0-beta1`
**当前结论**：代码与本地自动化验证通过；真实 MySQL/DM8、运行中 Celery/API E2E、浏览器和脱敏快照迁移演练尚未执行，不能作为发布完成证据。

## 1. 已实现合同

- `message_session.entry_flow_id` nullable 字段及单列索引；Alembic 只做 DDL。
- effective entry Repository：列表、chat+entry 校验、文件会话复用和精确 flow 批量回收。
- 原空间/具体资源权限先于 session 使用；历史与新消息始终使用原 `session.flow_id`。
- recovered root 使用原空间全量可见文件检索；内部 `entry_flow_id` 不进入 HTTP 响应。
- 文件/文件夹删除、batch、`clear_space` 和跨空间移动在各自 DB commit 后 best-effort 派发；同空间移动和完整删除空间不派发。
- Celery 默认延时 5 秒、每批 500 flow、`acks_late`、最多 3 次 retry；重复执行只更新 null entry。
- DB-only 迁移脚本提供稳定 manifest SHA、apply 确认、blocker、掩码样例、checkpoint 和终态校验。
- 前端零代码改动；新增环境门禁式 API E2E 与页面/运维手工清单。

## 2. 已执行验证

所有命令从 `src/backend/` 执行，并使用主 worktree 的 `config.yaml`。

| 验证 | 结果 | 说明 |
|---|---|---|
| F071 聚焦测试、知识 chat 回归、Celery wiring、迁移图 | `66 passed` | 覆盖 schema、Repository、入口校验、检索范围、worker、触发顺序、迁移脚本和 single head |
| `test/chat_session/` | `5 passed` | 通用会话路径回归 |
| `test/knowledge/ -k "chat or move or filelib"` | `113 passed, 1 skipped` | 1 项为既有环境条件 skip；其余知识问答/移动/filelib 回归通过 |
| move + v2 filelib + knowledge space service | `43 passed` | 修正旧测试 fixture 漂移后通过 |
| F071 API E2E 收集 | `4 skipped` | 缺少 `E2E_F071_TOKEN`、运行中 API/worker；按设计不伪造通过 |
| affected-file Ruff | 通过 | 新增/修改的 F071 Python 文件与测试无新增 lint 问题 |
| `git diff --check` | 通过 | 无 whitespace error |
| `scripts/arch-guard.sh` | 通过 | 无架构守卫违规 |

本地测试使用 SQLite 或 mock 锁定行为，不替代双数据库与真实异步基础设施验证。

## 3. 迁移脚本验收状态

脚本：`src/backend/scripts/migrate_f068_knowledge_chat_entries.py`

已自动验证：

- root/present/missing/moved/deleted-space/soft-deleted/unparseable/cross-tenant/type-conflict 分类；
- manifest 按 `(tenant_id, chat_id)` 稳定排序，entry 改写不改变 SHA；
- 数据库身份不输出密码、chat 样例掩码；
- 无 reviewed SHA、SHA 不同、blocker 或非法 checkpoint cursor 时拒写；
- 只更新活动、null entry、知识空间 session，保留原 flow/create_time，重复 apply 零更新。

待运维环境验证：

- [ ] 在脱敏快照 dry-run，核对 DB identity、分类、blocker 和 SHA。
- [ ] MySQL apply、批次中断、checkpoint 续跑、终态及第二次零更新。
- [ ] DM8 apply、批次中断、checkpoint 续跑、终态及第二次零更新。
- [ ] 核对消息、引用、session create_time 与原 flow 的前后 checksum。

## 4. 发布前硬门禁

- [ ] MySQL 与 DM8 分别执行 Alembic upgrade/downgrade 演练，确认唯一 head。
- [ ] 两种数据库记录 effective-entry OR 查询和批量 UPDATE 执行计划；只有证据显示必要时才调整为 `UNION ALL` 或复合索引。
- [ ] 运行 API + `knowledge_celery`，执行 [E2E 清单](./e2e-checklist.md) 与自动化文件。
- [ ] 两个以上用户验证 owner/permission/目标空间隔离；浏览器验证历史、继续问答、重命名和删除。
- [ ] broker publish 失败、worker retry/终态失败、并发提交窗口和人工修复演练。
- [ ] 在 reviewed SHA 下完成生产维护窗口 dry-run/apply；`unparseable=0`、`cross_tenant_conflict=0`、非法 entry=0、`recoverable_orphan_remaining=0`。
- [ ] 完成最终代码评审与 CI；未完成以上门禁前不得把本文件结论提升为发布完成。

## 5. 回滚边界

新增列可保留，不能通过清空 `entry_flow_id` 或改写原 `flow_id` 回滚。旧镜像会忽略 entry，导致 recovered 会话再次失去入口；功能启用后应关闭相关入口并前向修复，而不是把旧镜像当作可用业务终态。
